"""Runtime layouts & pure decoding helpers for the TextShaping OTLS engine.

These constants were reverse-engineered by reading live memory with Frida and
cross-checking against Ghidra decompilation (see the project DESIGN.md, §4).
The Windows PDB types for these structures are stripped shells, so the layouts
below are the *authoritative* ones used by both the Frida agent (``agent.js``)
and this package's Python side.

Relevant structures
-------------------
``otlList`` / ``otlFeatureSet`` (identical leading layout)::

    struct otlList {
        void* data;      // +0x00  pointer to an array of elements (8 bytes)
        /* padding to 0x08 */
        u16   elemSize;  // +0x08  size of one element
        u16   count;     // +0x0c  number of elements
    };

``ApplyLookup`` glyph records are ``otlList`` arrays of records with
``elemSize == 8`` (4 x u16)::

    struct glyphRec { u16 gid@+0; u16 flags@+2; u16 idx@+4; u16 ?@+6; };

A 4-character OpenType tag (e.g. ``'GSUB'``) read as a host-endian ``u32`` on
little-endian Windows equals ``0x42555347``. The helper functions here keep the
JS and Python sides from drifting apart.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "GLYPH_EXTRA_OFFSET",
    "GLYPH_FLAGS_OFFSET",
    "GLYPH_GID_OFFSET",
    "GLYPH_INDEX_OFFSET",
    "GLYPH_RECORD_SIZE",
    "MAX_GUARD",
    "OTL_COUNT_OFFSET",
    "OTL_DATA_OFFSET",
    "OTL_ELEM_SIZE_OFFSET",
    "TAG_BYTES",
    "TAG_GPOS",
    "TAG_GSUB",
    "GlyphChange",
    "diff_glyphs",
    "name_to_tag",
    "tag_to_name",
]

# --------------------------------------------------------------------------
# OpenType table tags (as read by a little-endian u32).
# --------------------------------------------------------------------------
#: ``'GSUB'`` interpreted as a little-endian u32 (the value of args[0]).
TAG_GSUB: int = 0x42555347
#: ``'GPOS'`` interpreted as a little-endian u32.
TAG_GPOS: int = 0x534F5047
#: Mapping ``u32 -> 4CC`` for the two tables we bracket.
TAG_BYTES: dict[int, str] = {TAG_GSUB: "GSUB", TAG_GPOS: "GPOS"}

# --------------------------------------------------------------------------
# otlList / otlFeatureSet field offsets (see module docstring).
# --------------------------------------------------------------------------
OTL_DATA_OFFSET: int = 0x00  # 8-byte pointer to element array
OTL_ELEM_SIZE_OFFSET: int = 0x08  # u16 element size
OTL_COUNT_OFFSET: int = 0x0C  # u16 element count

# --------------------------------------------------------------------------
# ApplyLookup glyph records (elemSize == 8).
# --------------------------------------------------------------------------
GLYPH_RECORD_SIZE: int = 8
GLYPH_GID_OFFSET: int = 0
GLYPH_FLAGS_OFFSET: int = 2
GLYPH_INDEX_OFFSET: int = 4
GLYPH_EXTRA_OFFSET: int = 6

#: Sanity bounds used while decoding untrusted memory (never blind-read).
MAX_GUARD: int = 5000

#: A single glyph change: ``(position, old_gid, new_gid)``.
GlyphChange = tuple[int, int, int]


def tag_to_name(value: int) -> str | None:
    """Return the 4CC name for a little-endian u32 tag, or ``None``.

    >>> tag_to_name(0x42555347)
    'GSUB'
    """
    b = value & 0xFFFFFFFF
    chars = bytes((b & 0xFF, (b >> 8) & 0xFF, (b >> 16) & 0xFF, (b >> 24) & 0xFF))
    try:
        text = chars.decode("ascii")
    except UnicodeDecodeError:
        return None
    return text if all(0x20 <= c <= 0x7E for c in chars) else None


def name_to_tag(name: str) -> int:
    """Encode a 4CC name as a little-endian u32 (inverse of :func:`tag_to_name`)."""
    if len(name) != 4:
        raise ValueError(f"OpenType tags are 4 characters, got {name!r}")
    raw = name.encode("ascii")
    return int.from_bytes(raw, "little")


def diff_glyphs(previous: Sequence[int] | None, current: Sequence[int]) -> list[GlyphChange] | None:
    """Diff two consecutive glyph snapshots.

    Semantics of the returned value (shared with the Frida agent):

    * ``None`` — a diff is not meaningful: there was no previous snapshot, or
      the glyph count changed between snapshots (decomposition / ligature / a
      synthetic glyph inserted then removed). Callers should compare full
      arrays instead.
    * ``[]`` — equal-length snapshots with no glyph change.
    * a list of ``(pos, old, new)`` — equal-length snapshots where some glyphs
      were substituted at ``pos``.
    """
    if previous is None or len(previous) != len(current):
        return None
    changes: list[GlyphChange] = []
    for i, (old, new) in enumerate(zip(previous, current)):
        if old != new:
            changes.append((i, int(old), int(new)))
    return changes
