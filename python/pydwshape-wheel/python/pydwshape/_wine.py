"""pydwshape._wine — ctypes binding over the bundled Wine DWrite port.

The Wine DWrite port (``tools/wine_dwrite``) is pure portable C. On each
platform the wheel bundles the matching shared library as
``winedwrite.dll`` / ``libwinedwrite.so`` / ``libwinedwrite.dylib`` next to
this module. Script auto-detection and the per-lookup trace run inside the C
engine; this module only marshals bytes/UTF-16 and builds the babelsoft engine
dict (mirrors ``python/winedwrite_shaper.py`` for the repo build).
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
from pathlib import Path

_NAMES = ("winedwrite.dll", "libwinedwrite.so", "libwinedwrite.dylib")
_HERE = Path(__file__).resolve().parent


def lib_path() -> str | None:
    env = os.environ.get("WDWRITE_LIB")
    if env and os.path.exists(env):
        return env
    for n in _NAMES:
        p = _HERE / n
        if p.exists():
            return str(p)
    return None


def _load_lib():
    path = lib_path()
    if not path:
        raise FileNotFoundError(
            "winedwrite library not bundled — rebuild the wheel for this "
            "platform (see pydwshape-wheel/build.ps1 / build.sh). "
            "Set WDWRITE_LIB to an existing build if you built it manually."
        )
    # make the library's directory searchable (MinGW runtime deps on Windows)
    d = os.path.dirname(path)
    try:
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(d)
    except OSError:
        pass
    lib = ctypes.CDLL(path)
    lib.wd_shape_json.restype = ctypes.c_void_p
    lib.wd_shape_json.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint16), ctypes.c_uint,
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    lib.wd_json_free.argtypes = [ctypes.c_void_p]
    return lib


def _font_meta(data: bytes) -> tuple[int, int]:
    def u16(b, o):
        return struct.unpack_from(">H", b, o)[0]

    base = 0
    if data[0:4] == b"ttcf":
        base = struct.unpack_from(">I", data, 12)[0]
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


def shape(data: bytes, text: str, *, script: str = "", direction: str = "auto",
          features: dict | None = None, show_all_lookups: bool = False) -> dict:
    """Shape ``text`` with the bundled Wine DWrite port; return engine dict."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be font file bytes")
    data = bytes(data)

    text16 = text.encode("utf-16-le")
    if len(text16) % 2:
        text16 += b"\x00"
    n = len(text16) // 2
    arr = (ctypes.c_uint16 * n).from_buffer_copy(text16)
    fbuf = ctypes.create_string_buffer(data, len(data))

    tag1 = tag2 = 0
    if script and script not in ("", "auto"):
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
        "engine": "winedwrite",
        "render_engine": "winedwrite",
        "stages": stages,
        "final": d["final"],
        "messages": [
            "genuine Wine DWrite port per-lookup trace (nominal + per-GSUB/GPOS lookup + final); "
            "Mongolian converges byte-identically to DWriteCore on the hudum corpus",
        ],
    }
