"""dwtshape — DirectWrite step-by-step shaping-trace engine, babelmap shaper adapter.

Drop-in replacement for ``babelmap.backend.dwriteshape_shaper`` that calls the
Rust ``dwtshape`` binary (this repo) instead of ``dwriteshapepy``, so the
DirectWrite engine returns a **per-lookup / per-stage trace** (Crowbar-style),
exactly like the HarfBuzz (``opentype.shape_trace``) and HarfRust
(``harfrust_shaper``) engines — which plain DirectWrite cannot (no
buffer-message callback).

The engine's JSON output already matches babelsoft's ``/api/opentype/shape``
result schema: ``{upem, glyph_count, stages:[{m,glyphs,depth,effective}],
final, messages, engine}``; the server appends ``features`` / ``font_info`` /
``glyph_names`` / ``svg``.

Usage (inside babelmap): point the ``directwrite`` engine here, e.g. in
``babelmap/backend/server.py`` replace::

    from babelmap.backend.dwriteshape_shaper import shape_with_dwrite

with::

    from babelsoft_pydwshape.dwrite_trace_shaper import shape_with_dwrite

(or copy this file into ``babelmap/backend/`` and use its name).

The binary location comes from env ``DWSHAPE_BIN``, else
``<repo>/target/{release,debug}/dwtshape.exe``. DWriteCore is located by the
binary itself (``--dwcore`` / ``DWCORE_DLL`` / next to the exe / repo copy).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def _binary() -> str:
    p = os.environ.get("DWSHAPE_BIN")
    if p and os.path.exists(p):
        return p
    here = Path(__file__).resolve().parent.parent  # repo root
    for sub in ("release", "debug"):
        cand = here / "target" / sub / ("dwtshape.exe" if os.name == "nt" else "dwtshape")
        if cand.exists():
            return str(cand)
    raise ImportError(
        "dwtshape binary not found — build it first (`cargo build`) or set DWSHAPE_BIN"
    )


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
    """Shape ``text`` and return the full per-lookup shaping trace.

    ``backend`` selects the engine:
      * ``"dwcore"`` (default, Windows-only) — native Microsoft DWriteCore via
        the ``dwtshape`` binary (authoritative DirectWrite trace).
      * ``"winedwrite"`` (cross-platform) — the standalone Wine DWrite port
        (``tools/wine_dwrite``), loaded in-process via ctypes. Script is
        auto-detected from the text; Mongolian converges byte-identically to
        DWriteCore on the corpus.

    ``features`` is a ``{tag: bool|int}`` map (same convention as babelmap's
    HarfBuzz / harfrust engines) or a ready-made ``+tag,-tag,tag=N`` string.
    Note: DWriteCore applies script-required features unconditionally, so
    toggles only affect *optional* features (e.g. ``liga``/``kern``/``smcp``)
    and are ignored for mandatory positional features (Mongolian/Arabic
    ``init``/``medi``/``fina``/``rclt`` …).
    """
    if backend == "winedwrite":
        from winedwrite_shaper import shape_with_winedwrite
        d = shape_with_winedwrite(data, text, script=script, direction=direction)
        d.setdefault("messages", []).insert(
            0, "engine=winedwrite (cross-platform Wine DWrite port; script auto-detected)")
        return d
    if backend not in ("dwcore", "dwrite", "directwrite"):
        raise ValueError(f"unknown backend: {backend!r} (use 'dwcore' or 'winedwrite')")

    fd, tmp = tempfile.mkstemp(suffix=".font")
    try:
        os.close(fd)
        with open(tmp, "wb") as f:
            f.write(data)
        args = [
            _binary(),
            "--font",
            tmp,
            "--text",
            text,
        ]
        if script and script not in ("", "auto"):
            args += ["--script", script]
        if language:
            args += ["--language", language]
        if direction not in ("", "auto"):
            args += ["--direction", direction]
        if show_all_lookups:
            args += ["--show-all-lookups"]
        fs = _features_to_str(features)
        if fs:
            args += ["--features", fs]
        r = subprocess.run(args, capture_output=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                "dwtshape failed (rc={}): {}".format(
                    r.returncode, r.stderr.decode("utf-8", "replace")[-2000:]
                )
            )
        return json.loads(r.stdout.decode("utf-8"))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _features_to_str(features) -> str | None:
    """Normalise ``{tag: bool|int}`` (or a pre-built string) into the
    engine's ``+tag/-tag/tag=N`` list, mirroring babelmap's harfrust shaper."""
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
