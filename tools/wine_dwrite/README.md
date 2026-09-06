# Wine DWrite shaping port (tools/wine_dwrite)

Standalone, **cross-platform** port of **Wine's dlls/dwrite OpenType shaping
engine** so pydwshape can emit a genuine **per-lookup trace** from a second,
portable engine (the DirectWrite analogue of pyusp's wineusp.dll).

Status: **working**. Mongolian output is byte-identical to DWriteCore.

## Layout

    tools/wine_dwrite/
      wine-src/dlls/dwrite/    pristine Wine dwrite sources (LGPL-2.1+), + LICENSE/COPYING.LIB
      NOTICE.md                LGPL provenance
      README.md
      port/
        include/               portable headers (dwrite_private.h, windef.h, scripts.h; no COM/windows.h/FreeType)
        src/
          opentype_shaping.c   GENERATED engine core (GSUB/GPOS; see tools/extract_engine.py)
          shape_port.c         shape.c shaping part (universal joining shaper selection)
          mirror.c arabic.c arabic_table.c
          wd_font.c            raw-sfnt driver (table dir / cmap fmt4+12 / head upem / hmtx; TTC face 0)
          wd_script.c          Unicode script auto-detection + OpenType tag mapping
          wd_engine.c          orchestrator (GetGlyphs/GetGlyphPlacements) + per-lookup trace
          wd_json.c / .h       single-call JSON API (wd_shape_json) for bindings
          main.c               CLI driver (wdmain)
        tools/extract_engine.py
        build.ps1              Windows/MinGW build (wdmain.exe + winedwrite.dll)
        Makefile               Linux/macOS build (make / make lib)
        RESULTS.md

## Build

Windows (MinGW):
    powershell -NoProfile -ExecutionPolicy Bypass -File port/build.ps1
    # -> port/build/wdmain.exe, port/build/winedwrite.dll

Linux/macOS (any C11 compiler):
    make -C port       # wdmain
    make -C port lib   # libwinedwrite.so / .dylib

## Use

CLI (script auto-detected from the text, like DWriteCore):
    port/build/wdmain.exe --font hudum.otf --text-file text.txt --pos --trace

Python (in-process via the shared library, no subprocess):
    from winedwrite_shaper import shape_with_winedwrite   # python/winedwrite_shaper.py
    res = shape_with_winedwrite("hudum.otf", "ᠰᠠᠢᠬᠠᠨ")

Or through the unified DirectWrite API (native or wine backend):
    from dwrite_trace_shaper import shape_with_dwrite
    res = shape_with_dwrite(font_bytes, text, backend="dwcore")        # native DWriteCore (Windows)
    res = shape_with_dwrite(font_bytes, text, backend="winedwrite")    # this port (cross-platform)

Regression matrix (wine vs DWriteCore vs HarfBuzz, all auto-script):
    & 'D:\Github\babelsoft-py\.venv\Scripts\python.exe' python/compare_winedwrite.py

## Engine design (summary)

- **One universal joining shaper** (Wine's arabic.c) for every script, no
  per-script shapers: positional isol/init/medi/fina (+ Arabic variants) are
  classified purely from each glyph's Unicode joining type. Non-joining glyphs
  (Latin, digits, punctuation) get no positional action. Mirrors HarfBuzz.
- **Script auto-detection**: dominant Unicode script of the text -> font
  OpenType script tag(s) (primary + legacy Indic secondary like dev2/deva).
- **Per-lookup trace**: snapshot of the glyph run before every whole-lookup
  application (GSUB + GPOS) plus a nominal-cmap baseline (wd_port_trace).

## Validation

See port/RESULTS.md. Headline: hudum.otf Mongolian short
[675,281,303,471,281,351] and the long string are byte-identical to DWriteCore
(gids + advances + offsets, 0 error) and equal HarfBuzz. Latin ligatures and
Hebrew fine. Arabic / Indic are shaped but intentionally not byte-identical to
DWriteCore yet (Wine's own Arabic logic; no Indic reordering in wine dwrite).

## License

Wine sources are LGPL-2.1-or-later; the port is derived and stays LGPL.
pydwshape core stays MIT; it loads the port as a separate dynamically-linked
component. See NOTICE.md.
