# Port results — Wine DWrite shaping engine standalone (winedwrite)

Date: 2026-09-06. Build: `port/build/wdmain.exe` + `port/build/winedwrite.dll`
(MinGW); same C sources build on Linux/macOS via `port/Makefile`.

## Status — working

- Wine GSUB/GPOS engine extracted (`opentype_shaping.c` = upstream opentype.c
  head 1..1337 + engine 3259..6466) + `shape_port.c`, `mirror.c`,
  `arabic.c`(+`arabic_table.c`) compile standalone against self-authored
  portable headers (`port/include/`: `dwrite_private.h`, `windef.h`,
  `scripts.h`; no COM / windows.h / FreeType; zero Win-API references;
  compiles clean under `-std=c11 -Wall`).
- `wd_font.c`: raw-sfnt driver (table directory / cmap fmt 4+12 / head upem /
  hmtx; **TTC face-0** support).
- `wd_engine.c`: orchestrator mirrors Wine analyzer GetGlyphs/GetGlyphPlacements.
- Per-lookup trace: `wd_port_trace` snapshots the glyph run before every
  whole-lookup application (GSUB + GPOS) + a nominal-cmap baseline.
- `wd_script.c`: Unicode script auto-detection -> OpenType script tag(s).
- `wd_json.c`: single-call `wd_shape_json()` returning a JSON engine dict
  (used by the ctypes Python shaper).

## Design

1. **Universal joining shaper** — no per-script shapers. Wine's `arabic.c` is
   a generic Arabic-style joining shaper (state machine + `arabic_shaping_table`
   from full ArabicShaping.txt, which includes Arabic/Syriac/Mongolian/N'Ko).
   `shape_set_shaper()` always selects it; positional `isol/init/medi/fina`
   (+ Arabic fin2/fin3/med2) are driven purely by each glyph's Unicode joining
   type. Non-joining glyphs (Latin, digits, punctuation = U/T) are unaffected.
   Mirrors HarfBuzz.
2. **Script auto-detection** — dominant Unicode script of the text -> font
   OpenType script tag(s) (primary + legacy Indic secondary, e.g. dev2/deva).
   Tests never need to name a script.
3. **Per-lookup trace** — genuine nominal -> per-lookup -> final, recorded in
   the engine that produced `final`.

## Validation

Hudum.otf Mongolian (auto script):

| case | winedwrite gids | == DWriteCore | == HarfBuzz |
|---|---|---|---|
| short `ᠰᠠᠢᠬᠠᠨ` | `[675,281,303,471,281,351]` | yes (pos err 0) | yes |
| long (20 glyphs) | == `samples/dwcore_mong2_ref.json` | yes (pos err 0) | yes |

Regression (`python/compare_winedwrite.py`, all auto-script): Mongolian short/
long == DWriteCore == HarfBuzz (PASS); latin == DWriteCore/HB; hebrew ==
DWriteCore; arabic and devanagari are shaped but differ from both engines
(Wine's own Arabic joining vs HB/DWriteCore differences; wine dwrite has no
Indic reordering) — recorded as info, not failures.

Root cause that was fixed: Wine dwrite shipped no Mongolian shaping, so it only
ran its fixed default features and left letters isolated. Microsoft USE/HarfBuzz
apply `isol/init/medi/fina` first (positional joining), then `rclt/calt` on the
joined forms (hudum: 302->303, 464->471). Making the joining shaper universal
reproduces DWriteCore byte-identically.

## Repro

```
port/build.ps1                                   # Windows (wdmain + winedwrite.dll)
make -C port lib                                 # Linux/macOS shared lib
python/compare_winedwrite.py                     # regression (babelsoft venv)
python/winedwrite_shaper.py                      # ctypes shaper (drop-in)
```
