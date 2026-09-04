"""Tests for the public API surface, result dataclasses, and event grouping."""

from __future__ import annotations

import pydwshape as pyd
from pydwshape import FeaturePhase, LookupEvent, ShapeRun, TraceResult
from pydwshape.api import _group_runs, build_trace_result


def test_version_is_exported() -> None:
    assert isinstance(pyd.__version__, str)
    assert pyd.version_tuple == tuple(int(x) for x in pyd.__version__.split("."))
    assert len(pyd.version_tuple) == 3


def test_public_names_are_exported() -> None:
    for name in (
        "trace_directwrite",
        "DirectWriteTracer",
        "supported_textshaping_families",
        "TraceResult",
        "ShapeRun",
        "FeaturePhase",
        "LookupEvent",
        "GlyphChange",
        "FontSource",
        "PydwshapeError",
        "WindowsOnlyError",
        "WorkerError",
        "FridaError",
        "UnsupportedTextShapingError",
        "AddressMismatchError",
        "TraceTimeoutError",
    ):
        assert hasattr(pyd, name), f"missing public name: {name}"
    assert set(pyd.__all__) >= set(pyd.__dict__["__all__"])


def test_py_typed_marker_present() -> None:
    import importlib.resources

    files = importlib.resources.files("pydwshape").iterdir()
    assert any(p.name == "py.typed" for p in files)


def test_package_data_files_are_present() -> None:
    import importlib.resources

    root = importlib.resources.files("pydwshape")
    names = {p.name for p in root.iterdir()}
    assert "agent.js" in names
    assert "rva_registry.json" in names


def test_type_aliases_are_typing_compatible() -> None:
    assert pyd.FontSource is not None
    assert pyd.GlyphChange == tuple[int, int, int]


def test_dataclass_defaults() -> None:
    lk = LookupEvent(index=1, table="GSUB", glyphs=[1, 2])
    assert lk.changed is None
    ph = FeaturePhase(index=1, table="GSUB", features=["ccmp"])
    assert ph.lookups == []
    run = ShapeRun(index=1, table="GSUB")
    assert run.lookups == []
    assert run.feature_phases == []


def _synthetic_events() -> list[dict]:
    """A realistic GSUB run + a GPOS run (matching the agent's event order)."""
    return [
        {"t": "run_start", "run": 1, "table": "GSUB"},
        {
            "t": "feature",
            "run": 1,
            "phase": 1,
            "table": "GSUB",
            "count": 2,
            "features": ["ccmp", "locl"],
        },
        {
            "t": "lookup",
            "run": 1,
            "phase": 1,
            "n": 1,
            "table": "GSUB",
            "glyphs": [10, 20, 30],
            "changed": None,
        },
        {"t": "feature", "run": 1, "phase": 2, "table": "GSUB", "count": 1, "features": ["init"]},
        {
            "t": "lookup",
            "run": 1,
            "phase": 2,
            "n": 2,
            "table": "GSUB",
            "glyphs": [11, 20, 30],
            "changed": [[0, 10, 11]],
        },
        {"t": "run_end", "run": 1, "table": "GSUB"},
        {"t": "run_start", "run": 2, "table": "GPOS"},
        {"t": "gpos_start", "run": 2, "table": "GPOS"},
        {"t": "feature", "run": 2, "phase": 1, "table": "GPOS", "count": 1, "features": ["kern"]},
        {
            "t": "lookup",
            "run": 2,
            "phase": 1,
            "n": 1,
            "table": "GPOS",
            "glyphs": [11, 20, 30],
            "changed": [],
        },
        {"t": "gpos_end", "run": 2, "table": "GPOS"},
        {"t": "run_end", "run": 2, "table": "GPOS"},
    ]


def test_group_runs_builds_ordered_structure() -> None:
    runs = _group_runs(_synthetic_events())
    assert [r.table for r in runs] == ["GSUB", "GPOS"]
    assert [r.index for r in runs] == [1, 2]

    gsub = runs[0]
    assert [ph.features for ph in gsub.feature_phases] == [
        ["ccmp", "locl"],
        ["init"],
    ]
    assert gsub.feature_phases[0].lookups[0].changed is None
    init_phase = gsub.feature_phases[1]
    assert len(init_phase.lookups) == 1
    assert init_phase.lookups[0].index == 1
    assert init_phase.lookups[0].changed == [(0, 10, 11)]
    assert runs[1].feature_phases[0].features == ["kern"]
    # runs[1] is the positioning run: table came from its own run_start
    assert runs[1].table == "GPOS"


def test_group_runs_ignores_coordination_events() -> None:
    runs = _group_runs([{"t": "hello", "base": "0x1"}, {"t": "ready"}, *_synthetic_events()])
    assert len(runs) == 2


def test_build_trace_result_maps_and_extracts() -> None:
    result = build_trace_result(
        events=_synthetic_events(),
        worker_result={
            "upem": 2048,
            "glyphs": [11, 20, 30],
            "glyph_names": {"11": "uni1830", "20": "uni1820"},
        },
        meta={"engine_build": "10.0.26100"},
    )
    assert result.upem == 2048
    assert result.final_glyphs == [11, 20, 30]
    assert result.glyph_names == {11: "uni1830", 20: "uni1820"}
    assert result.meta["engine"] == "directwrite"
    assert result.meta["engine_build"] == "10.0.26100"
    assert result.substitutions() == [(0, 10, 11)]
    assert len(result.raw_events) == len(_synthetic_events())


def test_build_trace_result_empty_result() -> None:
    result = build_trace_result(events=[], worker_result=None, meta={})
    assert result.upem == 0
    assert result.final_glyphs == []
    assert result.runs == []
    assert result.glyph_names == {}


def test_shape_run_lookups_property() -> None:
    runs = _group_runs(_synthetic_events())
    assert len(runs[0].lookups) == 2
    # GPOS run has one lookup too
    assert len(runs[1].lookups) == 1


def test_feature_phases_property_flattens_in_order() -> None:
    runs = _group_runs(_synthetic_events())
    t = TraceResult(upem=1, final_glyphs=[], glyph_names={}, runs=runs)
    assert [ph.features for ph in t.feature_phases] == [
        ["ccmp", "locl"],
        ["init"],
        ["kern"],
    ]
