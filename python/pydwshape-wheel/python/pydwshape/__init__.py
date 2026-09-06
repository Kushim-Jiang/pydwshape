"""pydwshape — DWrite per-lookup shaping tracer: DWriteCore (Windows) or Wine DWrite port (cross-platform).

Drop-in for ``babelmap.backend.dwriteshape_shaper.shape_with_dwrite``: returns
the babelsoft ``/api/opentype/shape`` engine dict (Crowbar-style stages).

Two engines (``backend=``):
  * ``"dwcore"`` (default, Windows-only) — native Microsoft DWriteCore via the
    PyO3 extension ``pydwshape._pydwshape`` (in-process, bundled DWriteCore.dll,
    authoritative DirectWrite per-lookup trace).
  * ``"winedwrite"`` (cross-platform) — the standalone Wine DWrite port, loaded
    in-process via ctypes from the bundled shared library (``winedwrite.dll`` /
    ``libwinedwrite.so`` / ``libwinedwrite.dylib``). Script is auto-detected
    from the text; Mongolian converges byte-identically to DWriteCore.

Importing the package works on any OS (so the wine backend is usable
everywhere); the ``dwcore`` backend raises on non-Windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def _native() -> object:
    """The PyO3 DWriteCore extension (Windows only)."""
    if os.name != "nt":
        raise OSError(
            "backend='dwcore' requires Windows (native DWriteCore). "
            "Use backend='winedwrite' on this platform."
        )
    try:
        from . import _pydwshape
    except ImportError as e:  # pragma: no cover - corrupt wheel
        raise ImportError(
            "pydwshape native module missing — the wheel is corrupt, or it was "
            "built for a different Python/ABI. Reinstall the Windows wheel."
        ) from e
    return _pydwshape


def _require_dll() -> str:
    p = _PKG / "DWriteCore.dll"
    if not p.exists():
        raise FileNotFoundError(
            f"DWriteCore.dll not found next to the module ({p}) — the wheel is "
            "incomplete. Reinstall pydwshape."
        )
    return str(p)


def _features_to_str(features) -> str | None:
    """Normalise ``{tag: bool|int}`` (or a ready string) to ``+tag,-tag,tag=N``."""
    if isinstance(features, str):
        s = features.strip()
        return s or None
    if not features:
        return None
    parts: list[str] = []
    for tag, val in features.items():
        tag = str(tag)
        if val is True or val == 1:
            parts.append(f"+{tag}")
        elif val is False or val == 0:
            parts.append(f"-{tag}")
        else:
            parts.append(f"{tag}={val}")
    return ",".join(parts) if parts else None


def shape_with_dwrite(
    data: bytes,
    text: str,
    *,
    direction: str = "auto",
    script: str = "",
    language: str = "",
    features: dict | None = None,
    show_all_lookups: bool = False,
    backend: str = "dwcore",
) -> dict:
    """Shape ``text`` and return the full per-lookup shaping trace dict.

    ``backend`` selects the engine: ``"dwcore"`` (native DWriteCore, Windows)
    or ``"winedwrite"`` (Wine DWrite port, cross-platform). ``script`` may be
    given to override auto-detection (both engines auto-detect when omitted).
    ``features`` uses the same ``{tag: bool}`` convention as the HarfBuzz /
    harfrust engines; note DWriteCore applies script-required features
    unconditionally (see README).
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be font file bytes")
    data = bytes(data)

    if backend in ("winedwrite", "wine"):
        from . import _wine
        return _wine.shape(
            data, text, script=script, direction=direction,
            features=features, show_all_lookups=bool(show_all_lookups),
        )
    if backend not in ("dwcore", "dwrite", "directwrite"):
        raise ValueError(f"unknown backend: {backend!r} (use 'dwcore' or 'winedwrite')")

    fs = _features_to_str(features)
    out = _native().shape_json(
        data,
        text,
        script=script,
        language=language,
        direction=direction,
        show_all_lookups=bool(show_all_lookups),
        features=fs,
        dwcore=_require_dll(),
    )
    return json.loads(out)


__all__ = ["shape_with_dwrite", "_require_dll"]
