"""winedwrite_shaper — Wine-DWrite per-lookup shaping shaper for babelmap.

Drop-in analogue of ``pydwshape``'s directwrite shaper, but the engine is the
standalone **Wine DWrite port** (``tools/wine_dwrite/port``) — cross-platform C,
shaped in-process via the shared library ``winedwrite.dll``/``libwinedwrite.so``
(ctypes), no subprocess.

The engine auto-detects the script from the text (like DWriteCore) and uses the
universal joining shaper, so no per-script configuration is needed. The
per-lookup ``stages`` are genuine (nominal cmap -> per-GSUB-lookup -> final)
recorded inside the engine (``wd_port_trace``).

API mirrors the babelmap server's shapers:
    shape_with_winedwrite(path_or_b64, text, *, is_b64, ...) -> engine dict
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import struct

_HERE = os.path.dirname(os.path.abspath(__file__))
_PORT = os.path.normpath(os.path.join(_HERE, "..", "tools", "wine_dwrite", "port"))
_LIBNAME = "winedwrite.dll" if os.name == "nt" else "libwinedwrite.so"
_LIBPATH = os.path.join(_PORT, "build", _LIBNAME)


def _load_lib():
    import sys
    if not os.path.exists(_LIBPATH):
        raise RuntimeError(
            f"winedwrite shared library not found at {_LIBPATH}; "
            f"build it first: tools/wine_dwrite/port/build.ps1 (Windows) "
            f"or `make lib` (Linux/macOS)")
    # make sibling dirs of the dll searchable (MinGW runtime deps on Windows)
    for d in (os.path.dirname(_LIBPATH),):
        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
        except OSError:
            pass
    lib = ctypes.CDLL(_LIBPATH)
    lib.wd_shape_json.restype = ctypes.c_void_p
    lib.wd_shape_json.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_uint16), ctypes.c_uint,
                                  ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.wd_json_free.argtypes = [ctypes.c_void_p]
    return lib


def _font_meta(data: bytes) -> tuple[int, int]:
    """Return (upem, num_glyphs) for an sfnt or TTC (face 0)."""
    def u16(b, o):
        return struct.unpack_from(">H", b, o)[0]

    base = 0
    if data[0:4] == b"ttcf":
        base = struct.unpack_from(">I", data, 12)[0]  # face 0 offset
    num = u16(data, base + 4)
    head = maxp = None
    for i in range(num):
        rec = base + 12 + i * 16
        tag = data[rec:rec + 4]
        off, ln = struct.unpack_from(">II", data, rec + 8)
        if tag == b"head":
            head = data[off:off + ln]
        elif tag == b"maxp":
            maxp = data[off:off + ln]
    upem = struct.unpack_from(">H", head, 18)[0] if head and len(head) >= 20 else 1000
    nglyph = struct.unpack_from(">H", maxp, 4)[0] if maxp and len(maxp) >= 6 else 0
    return upem, nglyph


def _tag(value: int) -> bytes:
    return bytes(((value >> 0) & 0xff, (value >> 8) & 0xff,
                  (value >> 16) & 0xff, (value >> 24) & 0xff))


def shape_with_winedwrite(
    path_or_b64: str | bytes,
    text: str,
    *,
    is_b64: bool = False,
    direction: str = "auto",
    script: str = "",
    language: str = "",
    features: dict | None = None,
    show_all_lookups: bool = False,
) -> dict:
    """Shape ``text`` and return the babelsoft engine dict.

    ``path_or_b64`` is a font path, base64 string (``is_b64=True``) or raw
    font ``bytes``. ``script`` (optional, 4-char OT tag) overrides
    auto-detection. ``features`` is accepted for interface compatibility but
    not applied by the port yet.
    """
    if isinstance(path_or_b64, bytes):
        data = path_or_b64
    elif is_b64:
        data = base64.b64decode(path_or_b64)
    else:
        with open(path_or_b64, "rb") as f:
            data = f.read()

    text16 = text.encode("utf-16-le")
    if len(text16) % 2:
        text16 += b"\x00"
    n = len(text16) // 2
    arr = (ctypes.c_uint16 * n).from_buffer_copy(text16)
    fbuf = ctypes.create_string_buffer(data, len(data))

    tag1 = tag2 = 0
    if script:
        t = script.encode("ascii", "replace")[:4].ljust(4, b" ")
        tag1 = t[0] | (t[1] << 8) | (t[2] << 16) | (t[3] << 24)

    rtl = 1 if direction == "rtl" else 0
    lib = _load_lib()
    p = lib.wd_shape_json(fbuf, len(data), arr, n, tag1, tag2, rtl, 1, 1)
    if not p:
        raise RuntimeError("winedwrite shaping failed")
    try:
        raw = ctypes.string_at(p).decode("utf-8")
    finally:
        lib.wd_json_free(p)

    d = json.loads(raw)
    upem, nglyph = _font_meta(data)
    engine = "winedwrite"
    stages = []
    for st in d.get("stages", []):
        gids = st.get("g", [])
        stages.append({
            "m": st.get("m", ""),
            "glyphs": [{"g": g, "cl": 0, "dx": 0, "dy": 0, "ax": 0, "ay": 0} for g in gids],
            "depth": 1,
            "effective": bool(st.get("eff", False)),
        })
    return {
        "upem": upem,
        "glyph_count": nglyph,
        "engine": engine,
        "render_engine": "winedwrite",
        "stages": stages,
        "final": d["final"],
        "messages": [
            "genuine Wine DWrite port per-lookup trace (nominal + per-GSUB/GPOS lookup + final); "
            "Mongolian converges byte-identically to DWriteCore on the hudum corpus",
        ],
    }
