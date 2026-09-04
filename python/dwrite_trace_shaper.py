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
) -> dict:
    """Shape ``text`` with system DirectWrite/TextShaping and return the full
    per-lookup shaping trace (schema-compatible with the HarfBuzz engine)."""
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
        # NOTE: per-feature toggling is not yet wired through the Rust engine
        # (it shapes with the font's default features). Passed/ignored here so
        # callers don't have to special-case the DirectWrite engine.
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
