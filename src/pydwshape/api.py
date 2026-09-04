"""Public API for pydwshape: feature-level DirectWrite shaping traces.

Typical use
-----------

.. code-block:: python

    import pydwshape

    result = pydwshape.trace_directwrite(
        font=r"D:\\...\\hudum.otf",
        text="\u1830\u1820\u1822\u182c\u1820\u1828",  # Mongolian
    )
    print(result.final_glyphs)
    for run in result.runs:
        for phase in run.feature_phases:
            print(phase.table, phase.features)

Or reuse one worker process for many shapes:

.. code-block:: python

    with pydwshape.DirectWriteTracer() as tracer:
        for text in texts:
            r = tracer.shape(font, text)
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

from ._version import __version__
from .addr_resolve import registry_families as supported_textshaping_families
from .errors import PydwshapeError, WindowsOnlyError

__all__ = [
    "DirectWriteTracer",
    "FeaturePhase",
    "FontSource",
    "GlyphChange",
    "GlyphRecord",
    "LookupEvent",
    "ShapeRun",
    "TraceResult",
    "supported_textshaping_families",
    "trace_directwrite",
]

#: Where a font may come from: a path or raw bytes.
FontSource = Union[str, "os.PathLike[str]", bytes, bytearray]

#: A glyph change ``(position, old_gid, new_gid)``.
GlyphChange = tuple[int, int, int]


@dataclass(frozen=True)
class GlyphRecord:
    """One positioned glyph of the final DirectWrite run (babelmap-compatible).

    Field semantics follow BabelMap's trace glyph schema: ``g`` = glyph id,
    ``cl`` = DirectWrite cluster (character index), ``dx/dy`` offsets and
    ``ax/ay`` advances in font units.
    """

    g: int
    cl: int
    dx: int = 0
    dy: int = 0
    ax: int = 0
    ay: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "g": self.g,
            "cl": self.cl,
            "dx": self.dx,
            "dy": self.dy,
            "ax": self.ax,
            "ay": self.ay,
        }


@dataclass
class LookupEvent:
    """One ``ApplyLookup`` application and the glyph state after it."""

    index: int  # 1-based position within its feature phase
    table: str  # 'GSUB' / 'GPOS'
    glyphs: list[int]  # full glyph-id array *after* this lookup
    changed: list[GlyphChange] | None = None
    #: ``None`` — a diff is not meaningful (first snapshot, or the glyph count
    #: changed during the lookup); ``[]`` — no glyph changed; else the diff.


@dataclass
class FeaturePhase:
    """One feature phase: a set of OpenType features applied together."""

    index: int  # 1-based phase number within its run
    table: str  # 'GSUB' / 'GPOS'
    features: list[str] = field(default_factory=list)  # feature tags in this phase
    lookups: list[LookupEvent] = field(default_factory=list)


@dataclass
class ShapeRun:
    """One top-level shaping invocation (a GSUB or GPOS bracket)."""

    index: int  # sequential run number across the shape
    table: str = "?"  # 'GSUB' or 'GPOS'
    feature_phases: list[FeaturePhase] = field(default_factory=list)

    @property
    def lookups(self) -> list[LookupEvent]:
        """All lookups across the phases of this run, in order."""
        return [lk for phase in self.feature_phases for lk in phase.lookups]


@dataclass
class TraceResult:
    """The full feature-level trace of one ``dw.shape()`` call."""

    upem: int  # font units-per-em
    final_glyphs: list[int]  # authoritative final glyph ids (from the worker)
    glyph_names: dict[int, str]  # gid -> PostScript-style name (final glyphs)
    final_records: list[GlyphRecord] = field(default_factory=list)  # final run w/ cluster+positions
    runs: list[ShapeRun] = field(default_factory=list)  # GSUB run(s) then the GPOS run, in order
    meta: dict[str, Any] = field(default_factory=dict)  # engine/build/addr info
    raw_events: list[dict[str, Any]] = field(default_factory=list)  # agent events

    @property
    def feature_phases(self) -> list[FeaturePhase]:
        """All feature phases across all runs, in trace order."""
        return [phase for run in self.runs for phase in run.feature_phases]

    def substitutions(self) -> list[GlyphChange]:
        """Every reported glyph substitution in trace order (for assertions)."""
        return [
            change
            for lookup in (lk for run in self.runs for lk in run.lookups)
            for change in (lookup.changed or [])
        ]


def _as_int_mapping(data: Mapping[Any, Any] | None) -> dict[int, str]:
    """Coerce a JSON-decoded ``{"gid": "name"}`` mapping to int keys."""
    if not data:
        return {}
    out: dict[int, str] = {}
    for key, value in data.items():
        try:
            out[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def _as_glyph_records(data: Any) -> list[GlyphRecord]:
    """Coerce a JSON-decoded ``glyph_records`` list into GlyphRecords."""
    if not isinstance(data, list):
        return []
    out: list[GlyphRecord] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        try:
            out.append(
                GlyphRecord(
                    g=int(item.get("g", 0)),
                    cl=int(item.get("cl", 0) or 0),
                    dx=int(item.get("dx", 0) or 0),
                    dy=int(item.get("dy", 0) or 0),
                    ax=int(item.get("ax", 0) or 0),
                    ay=int(item.get("ay", 0) or 0),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _group_runs(events: Iterable[dict[str, Any]]) -> list[ShapeRun]:
    """Group raw agent events into ordered runs / phases / lookups.

    Only ``run_start``/``run_end``/``feature``/``lookup`` events are used;
    ``hello``/``gpos_*`` markers are coordination signals, not trace content.
    """
    runs: dict[int, ShapeRun] = {}
    order: list[int] = []
    phases: dict[int, dict[int, FeaturePhase]] = {}
    phase_order: dict[int, list[int]] = {}

    def ensure_run(rid: int) -> ShapeRun:
        if rid not in runs:
            runs[rid] = ShapeRun(index=rid)
            order.append(rid)
            phases[rid] = {}
            phase_order[rid] = []
        return runs[rid]

    def set_run_table(rid: int, table: str | None) -> None:
        run = ensure_run(rid)
        if table and (run.table in ("?", "")):
            run.table = table

    def ensure_phase(rid: int, pidx: int, table: str | None) -> FeaturePhase:
        run = ensure_run(rid)
        if table and run.table in ("?", ""):
            run.table = table
        phase = phases[rid].get(pidx)
        if phase is None:
            phase = FeaturePhase(index=pidx, table=table or run.table or "?")
            phases[rid][pidx] = phase
            phase_order[rid].append(pidx)
        elif table and phase.table in ("?", ""):
            phase.table = table
        return phase

    for event in events:
        kind = event.get("t")
        rid = int(event.get("run", 0))
        if kind == "run_start" or kind == "run_end":
            set_run_table(rid, str(event.get("table") or ""))
        elif kind == "feature":
            pidx = int(event.get("phase", 0))
            phase = ensure_phase(rid, pidx, str(event.get("table") or ""))
            tags = [str(x) for x in event.get("features") or []]
            if not phase.features:
                phase.features = tags
        elif kind == "lookup":
            pidx = int(event.get("phase", 0))
            phase = ensure_phase(rid, pidx, str(event.get("table") or ""))
            gids = [int(g) for g in event.get("glyphs") or []]
            changed = event.get("changed")
            changes: list[GlyphChange] | None = None
            if changed is not None:
                changes = [(int(a), int(b), int(c)) for a, b, c in changed]
            phase.lookups.append(
                LookupEvent(
                    index=len(phase.lookups) + 1,
                    table=str(event.get("table") or phase.table or "?"),
                    glyphs=gids,
                    changed=changes,
                )
            )

    result: list[ShapeRun] = []
    for rid in order:
        run = runs[rid]
        run.feature_phases = [phases[rid][p] for p in phase_order[rid]]
        result.append(run)
    return result


def build_trace_result(
    events: list[dict[str, Any]],
    worker_result: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
) -> TraceResult:
    """Assemble a :class:`TraceResult` from raw events + worker glyph result."""
    worker_result = dict(worker_result or {})
    upem = int(worker_result.get("upem") or 0)
    glyphs = [int(g) for g in worker_result.get("glyphs") or []]
    names = _as_int_mapping(worker_result.get("glyph_names"))
    records = _as_glyph_records(worker_result.get("glyph_records"))
    meta_out = dict(meta or {})
    meta_out.setdefault("engine", "directwrite")
    meta_out.setdefault("pydwshape_version", __version__)
    return TraceResult(
        upem=upem,
        final_glyphs=glyphs,
        glyph_names=names,
        final_records=records,
        runs=_group_runs(events),
        meta=meta_out,
        raw_events=list(events),
    )


class DirectWriteTracer:
    """A reusable DirectWrite tracer backed by one worker process.

    The worker (and its Frida instrumentation) is started lazily on the first
    :meth:`shape` call and torn down by :meth:`close`. Usable as a context
    manager.
    """

    def __init__(self, *, timeout: float = 10.0, symbols: bool = False) -> None:
        if os.name != "nt":
            raise WindowsOnlyError(
                "pydwshape traces Windows' DirectWrite/TextShaping and runs only on "
                "Microsoft Windows. On macOS/Linux use HarfBuzz for the equivalent trace."
            )
        self.timeout = float(timeout)
        self.symbols = bool(symbols)
        self._engine: Any = None
        self._temp_files: list[Path] = []

    # ------------------------------------------------------------- lifecycle
    def _ensure_engine(self) -> None:
        if self._engine is None:
            from .orchestrator import Engine

            self._engine = Engine(timeout=self.timeout, symbols=self.symbols)

    def _font_to_path(self, font: FontSource) -> Path:
        if isinstance(font, (str, os.PathLike)):
            path = Path(font)
            if not path.is_file():
                raise PydwshapeError(f"font file not found: {path}")
            return path
        if isinstance(font, (bytes, bytearray)):
            fd, tmp = tempfile.mkstemp(prefix="pydwshape-", suffix=".font")
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(font))
            path = Path(tmp)
            self._temp_files.append(path)
            return path
        raise TypeError(f"font must be a path or bytes, not {type(font).__name__!r}")

    def shape(
        self,
        font: FontSource,
        text: str,
        *,
        features: dict[str, Any] | None = None,
        language: str = "",
    ) -> TraceResult:
        """Trace one shape of ``text`` with ``font``.

        ``features`` maps an OpenType tag to ``True``/``False`` or an int
        (``None`` means the engine's defaults).
        """
        if not text:
            raise ValueError("text must not be empty")
        self._ensure_engine()
        outcome = self._engine.shape(
            self._font_to_path(font), text, features=features, language=language
        )
        return build_trace_result(outcome.events, outcome.result, outcome.meta)

    def close(self) -> None:
        """Stop the worker and clean up temporary font files (idempotent)."""
        if self._engine is not None:
            try:
                self._engine.close()
            finally:
                self._engine = None
        for path in self._temp_files:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        self._temp_files.clear()

    def __enter__(self) -> DirectWriteTracer:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - destructor safety
        with contextlib.suppress(Exception):
            self.close()


def trace_directwrite(
    font: FontSource,
    text: str,
    *,
    features: dict[str, Any] | None = None,
    language: str = "",
    timeout: float = 10.0,
    symbols: bool = False,
) -> TraceResult:
    """One-shot DirectWrite shaping trace (spawns a fresh worker each call).

    See :class:`DirectWriteTracer` for a reusable alternative.
    """
    with DirectWriteTracer(timeout=timeout, symbols=symbols) as tracer:
        return tracer.shape(font, text, features=features, language=language)
