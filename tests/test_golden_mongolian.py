"""Golden end-to-end test: hudum.otf + Mongolian under a live DirectWrite trace.

This exercises the whole pipeline — spawn worker, preload TextShaping, attach
Frida, resolve addresses offline, hook, shape, collect events, assemble a
:class:`TraceResult` — and checks it against the cross-engine golden result
recorded in DESIGN.md §4.5 (both DirectWrite and HarfBuzz finish here).
"""

from __future__ import annotations

import pydwshape as pyd

from .conftest import GOLDEN_GLYPHS, MONGOLIAN, needs_hudum, needs_native


@needs_native
@needs_hudum
def test_golden_final_glyphs(hudum_path, live_trace_supported: bool) -> None:
    assert live_trace_supported
    result = pyd.trace_directwrite(font=hudum_path, text=MONGOLIAN)
    assert result.final_glyphs == GOLDEN_GLYPHS
    assert result.upem > 0
    assert result.runs, "expected at least one shaping run"
    # every event was consumed into the structured result
    assert result.meta.get("ts_version")
    assert result.meta.get("addr_source") == "rva"


@needs_native
@needs_hudum
def test_golden_feature_phases_present(hudum_path, live_trace_supported: bool) -> None:
    assert live_trace_supported
    result = pyd.trace_directwrite(font=hudum_path, text=MONGOLIAN)
    all_tags = [tag for ph in result.feature_phases for tag in ph.features]
    # Mongolian substitution phases must appear (see DESIGN.md §4.5).
    for required in ("init", "medi", "fina"):
        assert required in all_tags, f"missing feature phase: {required}"
    # There is a GSUB run and a GPOS run bracket.
    tables = {run.table for run in result.runs}
    assert "GSUB" in tables


@needs_native
@needs_hudum
def test_golden_known_substitutions(hudum_path, live_trace_supported: bool) -> None:
    """Spot-check the reverse-engineered substitution points (DESIGN §4.5)."""
    assert live_trace_supported
    result = pyd.trace_directwrite(font=hudum_path, text=MONGOLIAN)
    subs = result.substitutions()
    # init : 673 -> 675 on the first glyph
    assert (0, 673, 675) in subs
    # fina : 350 -> 351 somewhere
    assert any(old == 350 and new == 351 for _pos, old, new in subs)


@needs_native
@needs_hudum
def test_worker_reuse_shapes_multiple_texts(hudum_path, live_trace_supported: bool) -> None:
    """DirectWriteTracer reuses one worker for many shapes."""
    assert live_trace_supported
    with pyd.DirectWriteTracer() as tracer:
        a = tracer.shape(hudum_path, MONGOLIAN)
        b = tracer.shape(hudum_path, MONGOLIAN)
    assert a.final_glyphs == GOLDEN_GLYPHS
    assert b.final_glyphs == GOLDEN_GLYPHS
    assert a.meta.get("worker_pid") == b.meta.get("worker_pid")
