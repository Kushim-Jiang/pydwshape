"""pydwshape.worker — the DirectWrite shaping child process (Frida target).

Run as ``python -m pydwshape.worker``. This process *performs* the shaping with
``dwriteshapepy`` and is the process the orchestrator attaches Frida to, so the
``TextShaping.dll`` internals can be traced. It never traces itself.

Startup sequence
----------------
1. import :mod:`dwriteshapepy` (loads ``dwrite.dll``);
2. preload ``TextShaping.dll`` (via ``LoadLibraryExW``) so its base address is
   already known before the orchestrator attaches — DirectWrite's delay-load
   then reuses this same module;
3. emit one JSON ``{"t": "ready", ...}`` line (flushed).

Command loop
------------
One JSON command per stdin line; exactly one JSON reply per command:

.. code-block:: json

    {"cmd": "shape", "font": "C:\\\\...\\\\hudum.otf", "text": "..."}
    {"t": "result", "upem": 2048, "glyphs": [..], "glyph_names": {..}}

stdin EOF ends the process. The worker is intentionally single-threaded and
serial so trace events never interleave.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import addr_resolve
from .errors import WindowsOnlyError, WorkerError

__all__ = ["main"]


def _textshaping_base() -> int | None:
    """Base address of a loaded TextShaping.dll, or ``None``."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=False)
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    handle = k32.GetModuleHandleW("TextShaping.dll")
    return int(handle) if handle else None


def _preload_textshaping() -> None:
    """Map TextShaping.dll into this process before the orchestrator attaches.

    The DLL is a system delay-load dependency of DirectWrite; loading it early
    is safe (Windows maps it once) and guarantees ``Process.getModuleByName``
    sees it the moment Frida attaches.

    NB: use a *plain* ``LoadLibraryW`` (absolute path). Loading with
    ``LOAD_LIBRARY_SEARCH_*`` flags keeps the module out of the loader list
    that Frida scans, so the agent would not be able to see or hook it.
    """
    path = addr_resolve.textshaping_path()
    try:
        ctypes.WinDLL(str(path))
    except OSError as exc:
        raise WorkerError(f"Failed to preload {path}: {exc}") from exc


def _normalize_features(features: Any) -> dict[str, Any]:
    """Coerce a JSON-decoded feature spec into ``{tag: bool|int}``."""
    if not features:
        return {}
    out: dict[str, Any] = {}
    for tag, value in features.items():
        if isinstance(value, bool):
            out[str(tag)] = value
        elif isinstance(value, (int, float)):
            out[str(tag)] = bool(value) if value in (0, 1) else int(value)
        else:
            out[str(tag)] = bool(value)
    return out


def _shape(
    font_bytes: bytes,
    text: str,
    features: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    """Shape ``text`` with DirectWrite and return glyphs + metadata."""
    import dwriteshapepy as dw

    face = dw.Face(font_bytes)
    font = dw.Font(face)
    upem = int(getattr(font, "upem", 0) or 0) or 2048

    buf = dw.Buffer()
    buf.add_str(text)
    if language:
        with contextlib.suppress(Exception):
            buf.language = language

    dw.shape(font, buf, _normalize_features(features))

    infos = list(buf.glyph_infos)
    poss = list(buf.glyph_positions)
    glyphs: list[int] = []
    glyph_records: list[dict[str, int]] = []
    for i, gi in enumerate(infos):
        gid = int(gi.codepoint)
        glyphs.append(gid)
        po = poss[i] if i < len(poss) else None
        glyph_records.append(
            {
                "g": gid,
                "cl": int(getattr(gi, "cluster", 0) or 0),
                "dx": round(float(getattr(po, "x_offset", 0) or 0)),
                "dy": round(float(getattr(po, "y_offset", 0) or 0)),
                "ax": round(float(getattr(po, "x_advance", 0) or 0)),
                "ay": round(float(getattr(po, "y_advance", 0) or 0)),
            }
        )
    glyph_names: dict[int, str] = {}
    for gid in set(glyphs):
        try:
            name = font.glyph_to_string(gid)
        except Exception:
            name = None
        if name:
            glyph_names[gid] = str(name)
    return {
        "upem": upem,
        "glyphs": glyphs,
        "glyph_records": glyph_records,
        "glyph_names": glyph_names,
    }


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _warmup() -> None:
    """A tiny shape so DirectWrite's machinery is fully initialised.

    Best-effort and silent: this is not the mechanism that loads
    TextShaping.dll (that is ``_preload_textshaping``), so any failure here is
    fine. Uses the always-present Segoe UI + an Arabic string.
    """
    with contextlib.suppress(Exception):
        segoe = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "Fonts" / "segoeui.ttf"
        if segoe.is_file():
            _shape(segoe.read_bytes(), "\u0645\u0631\u062d\u0628\u0627", {"rlig": True}, "ara")


def main(argv: list[str] | None = None) -> int:
    del argv  # worker takes no arguments
    if os.name != "nt":
        raise WindowsOnlyError("pydwshape.worker only runs on Microsoft Windows.")

    # Force UTF-8 text I/O regardless of the console code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    try:
        # Import first: a missing dwriteshapepy is the clearest error.
        import dwriteshapepy  # noqa: F401  (type: ignore[import-untyped])
    except Exception as exc:  # pragma: no cover - env-dependent
        _emit({"t": "fatal", "message": f"dwriteshapepy import failed: {exc}"})
        return 1

    try:
        _preload_textshaping()
        _warmup()
    except WorkerError as exc:
        _emit({"t": "fatal", "message": str(exc)})
        return 1

    ts_base = _textshaping_base()
    _emit({"t": "ready", "pid": os.getpid(), "ts_base": f"0x{ts_base:x}" if ts_base else None})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            command = json.loads(raw)
        except json.JSONDecodeError as exc:
            _emit({"t": "error", "message": f"bad JSON command: {exc}"})
            continue

        kind = command.get("cmd")
        if kind == "ping":
            _emit({"t": "pong"})
        elif kind == "shape":
            try:
                font_path = Path(command["font"])
                text = str(command.get("text") or "")
                features = command.get("features") or {}
                language = str(command.get("language") or "")
                font_bytes = font_path.read_bytes()
                if not text:
                    raise WorkerError("empty text")
                result = _shape(font_bytes, text, features, language)
                _emit({"t": "result", **result})
            except Exception as exc:
                _emit({"t": "error", "message": f"{type(exc).__name__}: {exc}"})
        else:
            _emit({"t": "error", "message": f"unknown command: {kind!r}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
