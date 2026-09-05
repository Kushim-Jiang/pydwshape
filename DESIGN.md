# DESIGN — dwtshape: DirectWrite step-by-step shaping trace (Rust)

> This replaces the original Python+frida pydwshape design (archived at
> `build/legacy/DESIGN.md`). Working notes / research live in `build/dwc_poc`.

## 1. Goal

Produce the **shaping trace** of a DirectWrite shape — the ordered sequence of
feature phases and per-lookup glyph mutations — semantically aligned with
HarfBuzz, so a complex-script (Mongolian etc.) run can be inspected step by
step and compared across engines.

The consumer contract is **babelsoft**'s BabelMap OpenType Test Framework
(`babelmap/backend/server.py` → `/api/opentype/shape`): every engine returns

```jsonc
{ "upem": int, "glyph_count": int,
  "stages": [{ "m": str, "glyphs": [glyph...], "depth": int, "effective": bool }],
  "final": [glyph...], "messages": [str...], "engine": "directwrite",
  "render_engine": "dwritecore" }
```

with glyph = `{g, cl, dx, dy, ax, ay, flags, (offset)}`, and the server appends
`features`, `font_info`, `glyph_names`, `svg`. HarfBuzz and HarfRust engines
already implement this (Crowbar-style). DirectWrite is the missing one:
`dwriteshape_shaper.py` notes *“DirectWrite has no buffer-message callback → no
step-by-step trace”*. This project fills exactly that hole.

## 2. Engine — DWriteCore only (native per-lookup trace)

Requirement (user): **everything must go through DWriteCore** — final
run/render AND the per-lookup trace; never fall back to the system DirectWrite
/TextShaping stack (that would keep the injection surface). Achieved:

- **One engine**: `DWriteCore.dll` (app-local, version-pinned, hijack-proof).
  The authoritative `final` glyphs + positions come from its
  `IDWriteTextAnalyzer`, and the step-by-step trace comes from **self-hooking
  one internal function of its Rust `otls` engine** — the GSUB/GPOS
  single-lookup dispatcher at **RVA `0x6D280`** (DWriteCore 2.1.1.2605,
  signature-locked).
- On entry, the 5th stack arg is the glyph-buffer object: `[obj+0x08]` →
  8-byte glyph records (`gid = u16@0`), `[obj+0x10]` → record count. The
  snapshot is the run state *before* that lookup; diffing consecutive entries
  reproduces the substitution timeline exactly (verified identical to
  TextShaping/HarfBuzz for the Mongolian golden case).
- No `TextShaping.dll`/system `dwrite.dll` is loaded anywhere.

Discovered by dynamic probing (see `build/dwc_poc/frida_probe*.py`):
functions called ~86× during one Mongolian `GetGlyphs` = per-lookup; the
dispatcher's decompiled body dispatches GSUB lookup types and references
`otls/src/gsub/singlsub.rs`.

Cross-engine parity (hudum.otf + `ᠰᠠᠢᠬᠠᠨ`):
**system TextShaping == DWriteCore == HarfBuzz == golden
`[675,281,303,471,281,351]`**, and the per-lookup mutation *sequence* is
semantically identical across TextShaping and HarfBuzz (HarfBuzz reports
whole-font-lookups `init/medi/fina/rclt…`; TextShaping reports the same
substitutions as per-glyph `ApplyLookup` calls).

## 3. USE ordering

TextShaping's `ApplyFeatures` phase groups map 1:1 onto the documented
Universal Shaping Engine stages (see
`build/dwc_poc/USE_shaping_order.md`):

1. `[locl ccmp nukt akhn]` (pre-processing; per cluster)
2. `rphf` → `pref` (reordering group; per cluster)
3. `[rkrf half abvf blwf vatu cjct pstf]` (orthographic units; per cluster)
4. `[isol init medi fina]` (topographical)
5. `[pres abvs blws psts haln rlig rclt calt liga clig rvrn]` (standard
   typographic; whole run)
6. GPOS positional stage.

## 4. Hook mechanism (self-hook, x64, DWriteCore-internal)

- Target (DWriteCore 2.1.1.2605; runtime-verified signature): the **otls
  per-lookup dispatcher** `base+0x6D280`; its first 12 bytes are clean
  one-byte pushes (`41 57 41 56 41 55 41 54 56 57 55 53`).
- **Auto-relocation**: if the fixed RVA no longer matches, `dwtshape` scans
  the DLL's executable sections for the 12-byte prologue and hooks wherever it
  lands — a future DWriteCore build that moves the dispatcher keeps working.
- **12-byte absolute-jump patch** (`mov rax,imm64; jmp rax`) to a stub placed
  in a scratch page near the module.
- Stub preserves `rcx/rdx/r8/r9` on the stack, loads the **5th stack arg**
  (`[rsp+0x28]`, the glyph-buffer object) into `rcx`, calls the Rust
  `extern "C" fn(u64)` logger, restores regs/stack, then jumps into the
  trampoline (copy of the original 12 bytes + abs jump to `target+12`).
- Because the stub only *sub*-allocates below the original frame and never
  pushes a return address for the original, the original resumes with the
  exact caller frame (stack args 5+ intact) and returns to the real caller.
  Only **onEnter** is needed — the trace is derived from the buffer arg.
- Run brackets are driven by us (`GetGlyphs` = GSUB, `GetGlyphPlacements` =
  GPOS), tagging captured lookups with the active table.

## 5. Trace assembly (Crowbar mirror)

Raw captured steps → rows → the same filtering used by
`babelmap.backend.opentype._build_trace_stages` (implemented in Rust):
- `depth` from `start lookup`/`end lookup` nesting;
- `effective` when the buffer changed inside a lookup;
- drop glyph-op noise + dedupe unchanged buffers unless `--show-all-lookups`;
- `final` = last stage buffer, merged with real DWrite advances/offsets
  (design units, `fontEmSize = upem`). Cluster (`cl`) uses one source
  everywhere — the otls glyph-record `idx` (final falls back to inverting
  DWrite `clusterMap` only if no snapshot matches).

## 6. CLI / I/O

```
dwtshape --font <path> --text <text> [--script <iso15924>]
         [--language <bcp47>] [--direction auto|ltr|rtl]
         [--features <+tag,-tag,tag=N,...>] [--dwcore <DWriteCore.dll>]
         [--show-all-lookups] [--out <file.json>]
```

`--script` may be omitted (`auto`/empty behave the same): the script number is
auto-detected from the text using DWriteCore's own Unicode script data (below).

`--features` forwards a single typographic-features range
(`DWRITE_TYPOGRAPHIC_FEATURES` + `featureRangeLengths=[len]`) to
`GetGlyphs`/`GetGlyphPlacements`. `DWRITE_FONT_FEATURE_TAG` stores the 4CC
little-endian (e.g. `'kern'` == `0x6E72654B`, matching the crate's
`DWRITE_FONT_FEATURE_TAG_KERNING`). DWriteCore semantics: optional features
toggle (verified `+smcp` → `[131,144,145]`, `liga=0` drops `ffi/fi` ligatures),
but **script-required** features (Mongolian/Arabic `init/medi/fina/rclt…`)
are engine-managed and cannot be disabled via the public API (glyphs stay
`[675,281,303,471,281,351]`; HarfBuzz would give `[673,277,295,461,277,350]`).

Emits the engine JSON above. upem/glyph_count parsed from the font's `head` /
`maxp` tables (no fontTools dependency). An explicit script tag maps to a DWrite
script number via a `GetScriptProperties` scan (title-case 4CC LE, e.g.
`mong`→`Mong`→`0x676E6F4D`→ script 59). When `--script` is omitted or `auto`,
`infer_script_number` is used instead: a per-code-point lookup in
`src/script_data.rs` (a byte-exact dump of DWriteCore's internal `unicode_data`
trie, 0..0x10FFFF → DWrite script 0..174), returning the first
non-Common/Inherited/Unknown script (transparent chars inherit; all-transparent
falls back to Common).

## 7. Repo layout

```
Cargo.toml, src/lib.rs, src/main.rs  Rust engine (lib + thin CLI)
python/dwrite_trace_shaper.py   babelmap shaper adapter (calls the binary)
python/compare_harfbuzz.py      regression matrix (needs babelsoft venv)
python/label_features.py        per-lookup feature-name labeling (HB-aligned)
python/pydwshape-wheel/         PyO3 abi3 wheel (Windows-only; bundles DWriteCore)
build/dwc_poc/              research: RE, PoCs, USE_order.md, hb_compare.py
build/legacy/               old Python pydwshape (frida) + original docs
build/samples/              produced traces (dwrite_mong.json)
```

## 8. Constraints / roadmap

- Windows-only, **single engine**: DWriteCore (`--dwcore` / `DWCORE_DLL` /
  exe dir / repo copy). No system TextShaping/dwrite anywhere.
- Hook target signature-locked for DWriteCore 2.1.1.2605 (RVA `0x6D280`) with
  **auto-relocation** by prologue scan for future builds (see §4).
- Single-threaded, our-process hooks only (12-byte absolute-jump patch).
- Validated: Mongolian golden + trace self-consistency, Latin & Devanagari vs
  HarfBuzz match and GPOS lookups captured; Arabic/Hebrew run (RTL order /
  default-feature differences vs HarfBuzz are expected). Regression matrix:
  `python/compare_harfbuzz.py`.
- Remaining / optional:
  - Per-lookup feature-name labels — **delivered tool-side** via
    `python/label_features.py`: aligns each DWriteCore stage to the (proven
    identical) HarfBuzz per-lookup trace and labels it with HB's feature.
    Native attribution was investigated and ruled out: the otls dispatcher
    (RVA `0x6D280`) fires per *matched position-region* (86x vs HB's 16x for
    the Mongolian run — DWrite splits one HB lookup into per-position
    dispatches) and carries no feature tag; the feature-enablement helper
    `0x6CA90` (enables_cache.rs) receives the 4CC in `rdx` but is
    bulk-precomputed per segment (284x, all features up front), so the last
    tag seen before a dispatch is only "the segment's last feature"
    (fina/rvrn) — not the dispatch's feature. No per-feature boundary is
    exposed at the dispatcher layer.
  - Trace-completeness caveat (same hook): a few substitutions (e.g. a
    trailing Latin `smcp` single-subst) are applied outside the hooked
    dispatcher, so stage rows can omit them while `final` stays correct;
    `label_features.py` prints `trace-complete:` to flag this.
  - Distribution: **done** — `python/pydwshape-wheel/` builds a PyO3 abi3
    wheel (`py3-none-win_amd64`) that bundles `DWriteCore.dll` and calls the
    engine in-process via `dwtshape::shape_json`. **Windows-only** (classifier
    + platform tag + runtime `OSError` on non-Windows); hook is installed per
    call and restored, so repeated in-process calls are safe. Engine refactor:
    `src/main.rs` → `src/lib.rs` (`pub fn shape_json`, `pub fn run_cli`) +
    thin `src/main.rs`.

## 9. Feature-toggle status (implemented)

- `--features` CLI + `python/dwrite_trace_shaper.py` passthrough
  (`{tag: bool} → +tag/-tag/tag=N`) — done; regression in
  `build/dwc_poc/toggle_test.py`.
- Optional features toggle through `DWRITE_FONT_FEATURE_TAG` (LE 4CC).
- Script-required features are **fixed** by DWriteCore otls (verified against
  Mongolian hudum: `init/medi/fina/rclt=0` unchanged). This is a DirectWrite
  engine constraint, not a bug — document in UI that such checkboxes reflect
  DWriteCore's fixed behavior (HarfBuzz reference output in the table above).

## 10. Feature-label status (implemented, tool-side)

`python/label_features.py` runs `dwtshape` and HarfBuzz on the same input and
walks the two per-lookup traces in lockstep: DWriteCore's fine-grained stages
are grouped under the HarfBuzz event whose cumulative end-buffer they reach,
so every stage is labelled with the feature HarfBuzz attributes to that
substitution.

```
& 'D:\Github\babelsoft-py\.venv\Scripts\python.exe' python/label_features.py \
     --font hudum.otf --text 'ᠰᠠᠢᠬᠠᠨ' --script mong
dw events=37 hb events=16
final dw=[675,281,303,471,281,351] hb=[...] equal=True
trace-complete ... True
  0 init    673>675
  1 medi    277>281
  ...
```

Validated: Mongolian (37 stages → `init`×1 `medi`×4 `fina`×1 `rclt`×31),
Latin `liga` (`office fi`), and `+smcp` (equal finals; flags `trace-complete:
False` for the tail single-subst not captured by the dispatcher hook). Exit
code 0 only when `final` equals HarfBuzz **and** the trace replays fully.

