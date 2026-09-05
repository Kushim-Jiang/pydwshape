"""pydwshape — DWriteCore-native per-lookup shaping tracer (Windows only).

Drop-in for ``babelmap.backend.dwriteshape_shaper.shape_with_dwrite``: returns
the babelsoft ``/api/opentype/shape`` engine dict (Crowbar-style stages), but
the shaping is done **in-process by the bundled DWriteCore** via the native
PyO3 extension ``pydwshape._pydwshape`` — no subprocess, no system dwrite /
TextShaping (hijack-proof, engine = DWriteCore only).

This package is Windows-only: it bundles ``DWriteCore.dll`` and the native
engine is a Windows x64 binary. Importing on any other OS raises OSError.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if os.name != "nt":
    raise OSError(
        "pydwshape is Windows-only (it drives Microsoft DWriteCore). "
        "See https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/"
        "use-visual-studio-to-build-windows-apps for the Windows platform."
    )

try:
    from . import _pydwshape
except ImportError as e:  # pragma: no cover - only when the wheel is broken
    raise ImportError(
        "pydwshape native module missing — the wheel is corrupt, or it was "
        "built for a different Python/ABI. Reinstall the Windows wheel."
    ) from e

_DLL = Path(__file__).with_name("DWriteCore.dll")


def _require_dll() -> str:
    if not _DLL.exists():
        raise FileNotFoundError(
            f"DWriteCore.dll not found next to the module ({_DLL}) — the wheel "
            "is incomplete. Reinstall pydwshape."
        )
    return str(_DLL)


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
) -> dict:
    """Shape ``text`` with bundled DWriteCore and return the full per-lookup
    trace dict (babelsoft ``/api/opentype/shape`` schema).

    ``features`` uses the same ``{tag: bool}`` convention as the HarfBuzz /
    harfrust engines. Note DWriteCore applies script-required features
    unconditionally, so toggles only affect *optional* features (see README).
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be font file bytes")
    fs = _features_to_str(features)
    out = _pydwshape.shape_json(
        bytes(data),
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
