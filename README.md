# pydwshape

**Feature-level DirectWrite shaping traces — feature names + per-lookup glyph
snapshots, semantically aligned with HarfBuzz stages.** Windows-only.

`pydwshape` takes `(font, text)`, shapes it with Microsoft DirectWrite (via
[`dwriteshapepy`](https://github.com/microsoft/DWriteShapePy)), and returns a
structured trace of *every* OpenType feature phase and the full glyph snapshot
after *every* lookup inside `TextShaping.dll` — the Windows component that does
real complex-script shaping (GSUB/GPOS) for DirectWrite. Font developers can
use the output to compare DirectWrite's engine behaviour with HarfBuzz.

```python
import pydwshape

result = pydwshape.trace_directwrite(font=r"D:\...\hudum.otf", text="ᠰᠠᠢᠬᠠᠨ")

print(result.final_glyphs)  # [675, 281, 303, 471, 281, 351]
for run in result.runs:  # a GSUB run, then a GPOS run
    for phase in run.feature_phases:
        print(phase.features)  # ['ccmp', 'locl'], ['init'], ['medi'], ...
        for lookup in phase.lookups:
            print(lookup.glyphs, lookup.changed)
```

## Highlights

- **Feature-level granularity** — DirectWrite normally exposes only the final
  glyph run. pydwshape observes the internal `ApplyFeatures` / `ApplyLookup`
  calls in `TextShaping.dll` (via Frida) to expose each feature phase and the
  per-lookup glyph state, mirroring HarfBuzz's per-lookup messages.
- **Zero network at runtime.** The hook addresses are *not* exported by
  `TextShaping.dll`, but pydwshape never downloads PDBs. It ships an offline
  RVA registry + byte-signature verification (see `rva_registry.json` and
  `tools/ghidra/README.md`) and refuses to *blind-hook*.
- **No Microsoft binaries are bundled or redistributed.** pydwshape observes
  the already-present system component read-only.
- **Pure-Python wheel** (`py3-none-any`) — only `frida` and `dwriteshapepy` as
  dependencies; nothing else.

## Platform / support

| | |
|---|---|
| OS | **Microsoft Windows 10 / 11 only** (DirectWrite & `TextShaping.dll` do not exist elsewhere and cannot be redistributed). On macOS/Linux use HarfBuzz for an equivalent trace. |
| TextShaping builds | A fixed offline registry covers e.g. `10.0.26100` (Win11 24H2). Unsupported builds raise `UnsupportedTextShapingError` with steps to extend the registry (`tools/ghidra/README.md`). |
| Python | `>=3.9` (developed on 3.13). |
| Scope | Complex-script OT shaping that runs through `TextShaping.dll` (Mongolian, Arabic, Indic, …). Simple Latin runs produce a glyph result with an empty trace. |

## Installation

```bash
pip install pydwshape          # Windows only (markers gate the deps)
# or from source
uv sync --extra dev
```

## Usage

### One-shot

```python
result = pydwshape.trace_directwrite(font=r"D:\...\hudum.otf", text="ᠰᠠᠢᠬᠠᠨ")
```

`font` may be a path or raw bytes; `features` maps an OpenType tag to
`True`/`False`/int (default: engine defaults); `language` sets the run
language.

### Reuse one worker (many shapes, one Frida session)

```python
with pydwshape.DirectWriteTracer() as tracer:
    for text in texts:
        r = tracer.shape(hudum, text)
```

Each tracer owns a private worker subprocess that does the shaping; Frida is
attached to *that* process, never to yours.

### Result structure

`TraceResult`:

| field | meaning |
|---|---|
| `upem` | font units-per-em |
| `final_glyphs` | authoritative final glyph ids (from DirectWrite) |
| `glyph_names` | `gid → name` for the final glyphs (via `dwriteshapepy`) |
| `runs` | `ShapeRun`s — one per top-level bracket (GSUB run(s), then GPOS) |
| `meta` | `ts_version`, `addr_source` (`rva`/`symbols`), timings, … |
| `raw_events` | the raw agent events (for debugging / re-parsing) |

`ShapeRun` → `FeaturePhase` (a `features` tag set applied together) →
`LookupEvent` (`glyphs` = full glyph array after the lookup; `changed` =
`[(pos, old, new), …]` diff, `None` when the count changed).

Conveniences: `TraceResult.feature_phases` (flattened), `.substitutions()`
(all reported glyph substitutions), `ShapeRun.lookups`.

## Development

```bash
uv sync --extra dev        # create the venv and install editable + dev tools
uv run pytest              # run the tests (live ones auto-skip without frida/font)
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy src            # type-check the package (strict)
```

Tests that need a live environment auto-skip:
- live DirectWrite trace → needs Windows + `frida` + `dwriteshapepy`;
- the golden Mongolian test → additionally needs a Mongolian OpenType font.
  Point at yours with `PYDWSHAPE_HUDUM` (default
  `D:\Github\mongfontbuilder\temp\hudum.otf`).

The golden test asserts `ᠰᠠᠢᠬᠠᠨ` with hudum.otf finishes at
`[675, 281, 303, 471, 281, 351]` — identical under DirectWrite **and**
HarfBuzz (see `DESIGN.md §4.5`), and that `init` / `medi` / `fina` phases and
the known `673→675`, `350→351` substitutions are visible in the trace.

## Troubleshooting

- **`FridaError: ... another program is intercepting DirectWrite (e.g. a font
  tool such as MacType)`** — pydwshape needs to read/hook the *real*
  `dwrite.dll` / `TextShaping.dll` in the worker. Font-replacement tools such
  as **MacType** load those modules through their own loader, which makes them
  invisible/unreadable to Frida (the worker still shapes fine). Disable the
  tool for the traced process — exiting its tray icon may not fully unload its
  hooks, so a full exit or reboot may be needed — then retry. The golden
  tests auto-skip with this reason when tracing is blocked.
- `UnsupportedTextShapingError` — your `TextShaping.dll` build isn't in the
  offline RVA registry yet. Follow `tools/ghidra/README.md` to add it.
- Only a final glyph run, no feature phases — the text went through a path
  that doesn't hit `TextShaping.dll` (e.g. plain Latin). Complex-script text
  (Mongolian, Arabic, Indic…) produces the full trace.

## How it works (short version)

```
Python (you)  pydwshape.api.DirectWriteTracer
   │  spawns
   ▼
worker (python -m pydwshape.worker)   ← Frida attaches here
   │   shapes via dwriteshapepy → dwrite → TextShaping.dll (OTLS engine)
   ▼
agent.js hooks ShapingGetGlyphs / ShapingGetGlyphPositions (run brackets),
   ApplyFeatures (feature phases) and ApplyLookup (per-lookup glyph snapshots),
   emitting structured send() events that the orchestrator assembles.
```

Addresses of `ApplyFeatures`/`ApplyLookup` come from the offline RVA registry
keyed by the local `TextShaping.dll` file version, verified against byte
signatures before hooking. See `DESIGN.md` (kept alongside the drite research
workspace) for the full design and the reverse-engineered struct layouts.

## License & notices

MIT — see `LICENSE`. `NOTICE.md` acknowledges `frida`, Microsoft's
`DWriteShapePy`/`dwriteshapepy`, and states that pydwshape is **not a
Microsoft product and has no Microsoft endorsement**. It traces Windows system
components read-only; no Microsoft binary or PDB is bundled or redistributed.
