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

## Build / run

```sh
cargo build --release
# shape Mongolian text -> JSON trace
target/release/dwtshape --font "hudum.otf" --text "ᠰᠠᠢᠬᠠᠨ" \
    --script mong --out trace.json
```

CLI: `--font <path> --text <str> [--script <iso15924>] [--language <bcp47>]
[--direction auto|ltr|rtl] [--dwcore <DWriteCore.dll>] [--show-all-lookups]
[--out <file>]`.
(Passing `--text` with non-ASCII from a Windows PowerShell command line is lossy;
use the Python adapter or an UTF-16-capable launcher.)

## babelmap integration

`python/dwrite_trace_shaper.py` is a drop-in shaper that shells out to the
binary; see its docstring for wiring. Sample output:
`build/samples/dwrite_mong.json`.

## Layout

- `src/main.rs` — the whole engine (hook, DWrite driver, Crowbar assembly).
- `python/` — babelmap shaper adapter.
- `build/` — research + artifacts (git-ignored): `dwc_poc/` (RE + PoCs,
  `USE_shaping_order.md`, `hb_compare.py`), `legacy/` (old Python pydwshape),
  `samples/`.

## Notes / constraints

- Windows-only; shapes with the **system** TextShaping.dll (signature-locked
  for 10.0.26100.x). DWriteCore is intentionally _not_ traced internally (its
  Rust `otls` engine has no stable hookable ApplyFeatures/ApplyLookup); it is
  kept as a parity reference (identical output).
- Single-threaded by design (hooks installed in our own process, trace driven
  by our own `GetGlyphs`/`GetGlyphPlacements` calls).
- Custom per-feature toggling is not yet wired through the Rust engine
  (default features only).
