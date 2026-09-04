"""pydwshape — feature-level DirectWrite shaping traces (Windows-only).

``pydwshape`` takes ``(font, text)``, shapes it with Microsoft DirectWrite
(via ``dwriteshapepy``), and returns a **feature-level trace**: every feature
phase plus the full glyph snapshot after each OpenType lookup, semantically
aligned with HarfBuzz stages so font developers can compare DWrite vs
HarfBuzz behaviour.

Because DirectWrite / ``TextShaping.dll`` exist only on Windows and may not be
redistributed, pydwshape is **Windows-only** and never bundles any Microsoft
binary. Address resolution of the internal hook points is done entirely
offline (a shipped RVA registry + byte-signature verification) — pydwshape
makes **no network requests** at runtime.

Typical use::

    import pydwshape

    result = pydwshape.trace_directwrite(font="hudum.otf", text="\\u1830\\u1820\\u1822\\u182c\\u1820\\u1828")
    print(result.final_glyphs)          # e.g. [675, 281, 303, 471, 281, 351]
    for phase in result.feature_phases:
        print(phase.features)           # e.g. ['ccmp'], ['init'], ['medi'], ...
"""

from __future__ import annotations

from ._version import __version__, version_tuple
from .addr_resolve import supported_textshaping_families
from .api import (
    DirectWriteTracer,
    FeaturePhase,
    FontSource,
    GlyphChange,
    GlyphRecord,
    LookupEvent,
    ShapeRun,
    TraceResult,
    trace_directwrite,
)
from .errors import (
    AddressMismatchError,
    FridaError,
    PydwshapeError,
    TraceTimeoutError,
    UnsupportedTextShapingError,
    WindowsOnlyError,
    WorkerError,
)

__all__ = [
    # version
    "__version__",
    "version_tuple",
    # public API
    "trace_directwrite",
    "DirectWriteTracer",
    "supported_textshaping_families",
    # result types
    "TraceResult",
    "ShapeRun",
    "FeaturePhase",
    "LookupEvent",
    "GlyphChange",
    "GlyphRecord",
    "FontSource",
    # errors
    "PydwshapeError",
    "WindowsOnlyError",
    "WorkerError",
    "FridaError",
    "UnsupportedTextShapingError",
    "AddressMismatchError",
    "TraceTimeoutError",
]
