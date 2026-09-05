# dwtshape — DirectWrite step-by-step shaping tracer (Rust)

Rust rewrite of the old pydwshape (Python + Frida, now archived in
`build/legacy/`). It emits a **per-feature / per-lookup shaping trace** in the
shape-trace schema used by [BabelSoft](https://github.com/)'s BabelMap
`/api/opentype/shape` endpoint — i.e. the DirectWrite analogue of the
HarfBuzz / HarfRust trace engines.

### Engine: DWriteCore-only (native per-lookup trace)

**Everything runs on DWriteCore** (app-local, version-pinned, hijack-proof):
both the authoritative `final` glyphs + positions **and** the step-by-step
per-lookup trace — no system `TextShaping`/`dwrite` is loaded at all.
Located via `--dwcore`, env `DWCORE_DLL`, next to the exe, or
`build/dwc_poc/DWriteCore.dll`.

DirectWrite has no buffer-message callback, so to see inside a shape we
self-hook one internal function of DWriteCore's Rust `otls` engine — the
GSUB/GPOS single-lookup dispatcher:

| Hooked fn | DWriteCore RVA | role |
| --------- | -------------- | ---- |
| otls per-lookup dispatcher | `base+0x6D280` | one lookup application; glyph buffer (`[obj+8]` records, `[obj+0x10]` count) is snapshotted on entry |

Verified against DWriteCore 2.1.1.2605; the first bytes are checked against
the known signature before patching (never a blind hook). See
`build/dwc_poc/USE_shaping_order.md` for how the resulting per-lookup timeline
maps onto the Microsoft USE (Universal Shaping Engine) ordering.

## Output format (babelsoft `/api/opentype/shape`)

```jsonc
{
  "upem": 1000, "glyph_count": 907, "engine": "directwrite",
  "stages": [ // Crowbar-style, same as harfrust / uharfbuzz engines
    { "m": "start lookup 1 GSUB features: init medi fina (DirectWrite)",
      "glyphs": [{ "g": 673, "cl": 0, "dx": 0, "dy": 0, "ax": 0, "ay": 0, "flags": 0 }],
      "depth": 1, "effective": true },
    ...
  ],
  "final": [ { "g": 675, "cl": 0, "dx": 0, "dy": 0, "ax": 147, "ay": 0, "flags": 0 }, ... ],
  "messages": [ "feature phase table=GSUB features=[init medi fina]", ... ]
}
```

Golden check (Mongolian): `hudum.otf` + `ᠰᠠᠢᠬᠠᠨ` →
`[675,281,303,471,281,351]` — identical to system TextShaping, DWriteCore and
HarfBuzz.

## Validation

Regression matrix (Mongolian golden + Latin/Arabic/Hebrew/Devanagari vs
HarfBuzz, incl. GPOS capture + trace self-consistency):

```sh
# needs the babelsoft venv (uharfbuzz)
& 'D:\Github\babelsoft-py\.venv\Scripts\python.exe' python/compare_harfbuzz.py
```

## Build / run

```sh
cargo build --release
# shape Mongolian text -> JSON trace
target/release/dwtshape --font "hudum.otf" --text "ᠰᠠᠢᠬᠠᠨ" \
    --script mong --out trace.json
```

CLI: `--font <path> --text <str> [--script <iso15924>] [--language <bcp47>]
[--direction auto|ltr|rtl] [--features <+tag,-tag,tag=N,...>]
[--dwcore <DWriteCore.dll>] [--show-all-lookups] [--out <file>]`.
`--script` may be omitted (or `auto`/empty): the script number is then
auto-detected from the text using DWriteCore's own Unicode script data
(`src/script_data.rs`, a byte-exact dump of DWriteCore's `unicode_data` trie;
Common/Inherited/combining marks inherit from context).
(Passing `--text` with non-ASCII from a Windows PowerShell command line is lossy;
use the Python adapter or an UTF-16-capable launcher.)

### Feature toggling (`--features`)

`--features` accepts a comma list of `+tag` (on), `-tag` / `tag=0` (off) or
`tag=N` (parameter N, e.g. `ss01=2`). It is forwarded to DWriteCore's
`GetGlyphs`/`GetGlyphPlacements` as typographic features
(`DWRITE_TYPOGRAPHIC_FEATURES`, one range over the whole text). Tag values use
the `DWRITE_FONT_FEATURE_TAG` convention (the 4CC stored little-endian, e.g.
`'kern'` = `0x6E72654B`).

Semantics follow DirectWrite's engine, not HarfBuzz's:

| case | example | DWriteCore result |
|---|---|---|
| optional feature **off by default**, turned on | `+smcp` on Calibri `abc` | `[258,271,272] → [131,144,145]` (matches HarfBuzz) |
| optional feature **on by default**, turned off | `liga=0` on Calibri `office fi` | `ffi/fi` ligatures removed (matches HarfBuzz) |
| **script-required** feature (Mongolian/Arabic …) | `init=0,medi=0,fina=0,rclt=0` on hudum | **ignored** — glyphs stay `[675,281,303,471,281,351]` |

The last row is a DWriteCore constraint: positional/required features of
complex scripts are engine-managed and cannot be disabled through typographic
features (HarfBuzz *can*, giving `[673,277,295,461,277,350]`). The babelmap
UI toggle therefore works for optional features; required-feature checkboxes
reflect DWriteCore's fixed behavior.

## babelmap integration

Two ways to drive BabelMap's DirectWrite engine from this repo:

1. **Shell-out shaper** — `python/dwrite_trace_shaper.py` calls the `dwtshape`
   binary (see its docstring for wiring).
2. **Native wheel (recommended for deployment)** — the PyO3 abi3 wheel
   `pydwshape` (see `python/pydwshape-wheel/`) shapes **in-process** via the
   bundled DWriteCore, no subprocess:

   ```python
   from pydwshape import shape_with_dwrite
   res = shape_with_dwrite(font_bytes, text)  # script omitted -> auto-detected
   res = shape_with_dwrite(font_bytes, text, script="mong")  # explicit
   ```

Sample output: `build/samples/dwrite_mong.json`.

## Python wheel (Windows-only, PyO3 abi3)

`python/pydwshape-wheel/` packages the engine as `pydwshape-…-py3-none-win_amd64.whl`
(abi3 ≥ 3.9), bundling `DWriteCore.dll` and the native extension so BabelMap
can call the pure-DWriteCore per-lookup tracer without a subprocess.

**This is Windows-only**: the engine drives Microsoft DWriteCore (Windows App
SDK) and the trace relies on an x64 inline hook. The wheel carries the
`Operating System :: Microsoft :: Windows` classifier, is tagged
`…-win_amd64`, and `import pydwshape` on any other OS raises `OSError`.

```powershell
cd python/pydwshape-wheel
Copy-Item ..\..\build\dwc_poc\DWriteCore.dll .\python\pydwshape\DWriteCore.dll  # MS-signed DLL (git-ignored)
maturin build --release --interpreter <python> -o dist
```

Repeated in-process calls are safe (the hook is installed per call and
restored afterwards); `features` uses `{tag: bool}` like the HarfBuzz engines.

## Layout

- `src/lib.rs` — the engine (`dwtshape::shape_json`, hook + DWrite driver +
  Crowbar assembly); `src/main.rs` — thin CLI (`dwtshape::run_cli`).
- `python/` — babelmap shaper adapter, `compare_harfbuzz.py` regression matrix,
  `label_features.py` (per-lookup feature-name labeling), and the
  `pydwshape-wheel/` PyO3 abi3 wheel project (Windows-only).
- `build/` — research + artifacts (git-ignored): `dwc_poc/` (RE + PoCs,
  `USE_shaping_order.md`, `hb_compare.py`, `frida_probe_feat.py`), `legacy/`
  (old Python pydwshape), `samples/`.

## Notes / constraints

- Windows-only, **single engine = DWriteCore** (app-local, version-pinned):
  final glyphs/positions AND the per-lookup trace both come from it. No system
  `TextShaping`/`dwrite` is loaded.
- Hook target is signature-locked for DWriteCore 2.1.1.2605 (RVA `0x6D280`).
  If a newer DWriteCore moves it, `dwtshape` **auto-relocates** by scanning the
  DLL's executable sections for the 12-byte prologue before failing.
- Single-threaded by design (hooks installed in our own process, trace driven
  by our own `GetGlyphs`/`GetGlyphPlacements` calls).
- RTL scripts (Arabic/Hebrew) output glyphs in a different order than
  HarfBuzz unless `--direction rtl` is passed; per-lookup buffers are in
  logical order, the final run may be reordered for RTL.
- Per-feature toggling is wired through the Rust engine (`--features`, see
  above) — optional features toggle, script-required features are fixed.
- Per-lookup feature-name labels are delivered **tool-side** by aligning each
  DWriteCore stage to the (proven identical) HarfBuzz per-lookup trace:
  `python/label_features.py --font F --text T --script S [--features X]`.
  Why not native: DWriteCore's otls dispatcher (hooked at RVA `0x6D280`)
  fires per *matched position-region* (finer than HarfBuzz's once-per-lookup)
  and carries no feature tag; the feature-enablement helper (`0x6CA90`) gets
  the 4CC but is bulk-precomputed per segment, so no per-dispatch feature is
  observable at that layer. HarfBuzz alignment is exact (Mongolian: all 37
  stages labelled `init`/`medi`/`fina`/`rclt`).
- Trace-completeness caveat: a few substitutions (e.g. a trailing `smcp`
  single-subst on Latin) happen outside the hooked dispatcher, so the stage
  list may not replay 100% of GSUB changes even though `final` is correct;
  `label_features.py` reports `trace-complete:` to flag this.
