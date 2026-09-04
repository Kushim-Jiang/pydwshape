"""Tests for decode.py — layout constants, tag helpers, and snapshot diffs."""

from __future__ import annotations

from pydwshape import decode
from pydwshape.decode import (
    GLYPH_RECORD_SIZE,
    OTL_COUNT_OFFSET,
    OTL_DATA_OFFSET,
    OTL_ELEM_SIZE_OFFSET,
    diff_glyphs,
    name_to_tag,
    tag_to_name,
)


def test_table_tag_constants() -> None:
    assert decode.TAG_GSUB == 0x42555347
    assert decode.TAG_GPOS == 0x534F5047
    assert name_to_tag("GSUB") == decode.TAG_GSUB
    assert name_to_tag("GPOS") == decode.TAG_GPOS


def test_tag_roundtrip() -> None:
    for tag in ("GSUB", "GPOS", "ccmp", "init", "medi", "fina", "rlig", "locl", "kern"):
        assert tag_to_name(name_to_tag(tag)) == tag


def test_tag_to_name_rejects_control_chars() -> None:
    assert tag_to_name(0x00000000) is None
    assert tag_to_name(0x20202020) == "    "  # spaces are technically printable


def test_otl_layout_constants() -> None:
    # Cross-checked with DESIGN.md §4.1: data@+0, elemSize@+8(u16), count@+0xC(u16).
    assert OTL_DATA_OFFSET == 0x00
    assert OTL_ELEM_SIZE_OFFSET == 0x08
    assert OTL_COUNT_OFFSET == 0x0C
    assert GLYPH_RECORD_SIZE == 8
    assert decode.GLYPH_GID_OFFSET == 0


def test_diff_glyphs_semantics() -> None:
    # None: no previous snapshot.
    assert diff_glyphs(None, [1, 2]) is None
    # None: length changed (decomposition/ligature) — callers compare full arrays.
    assert diff_glyphs([1, 2, 3], [1, 2]) is None
    # []: equal length, no change.
    assert diff_glyphs([1, 2], [1, 2]) == []
    # list of changes.
    assert diff_glyphs([673, 277, 295], [675, 277, 295]) == [(0, 673, 675)]
    assert diff_glyphs([673, 277, 295], [675, 281, 302]) == [
        (0, 673, 675),
        (1, 277, 281),
        (2, 295, 302),
    ]
