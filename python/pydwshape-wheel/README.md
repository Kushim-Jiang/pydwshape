# pydwshape

A per-lookup OpenType shaping tracer for
[BabelMap](https://www.babelstone.co.uk/BabelMap/index.html)'s OpenType test
framework — the DirectWrite analogue of its HarfBuzz/HarfRust engines.

Two engines:
* **`backend="dwcore"`** (default on Windows) — shapes **entirely with
  Microsoft DWriteCore** (app-local, version-pinned); returns the babelsoft
  `/api/opentype/shape` result dict including the per-lookup glyph-mutation
  trace. No system `dwrite.dll` / `TextShaping.dll` is loaded and no subprocess
  is spawned — the Rust engine runs in-process via this PyO3 **abi3** extension.
* **`backend="winedwrite"`** (cross-platform) — the bundled **Wine DWrite
  port** (`tools/wine_dwrite`), loaded in-process via ctypes; no DWriteCore.

The Wine backend makes the package usable on Linux/macOS too (see the
"Cross-platform Wine backend" section below).

## Requires

- Windows 10 1809+ (x64) for `backend="dwcore"` (native DWriteCore)
- any OS for `backend="winedwrite"` (bundled Wine DWrite port)
- CPython 3.9+ (any 3.9+ interpreter; wheel tags `cp39-abi3-*`)

The package imports on any OS; `backend="dwcore"` raises on non-Windows (it
needs the native DWriteCore engine). Use `backend="winedwrite"` elsewhere.

## Install

```powershell
pip install pydwshape
```

## Usage

```python
from pydwshape import shape_with_dwrite

font = open("font.otf", "rb").read()
res = shape_with_dwrite(font, "ᠰᠠᠢᠬᠠᠨ")  # script omitted -> auto-detected
res = shape_with_dwrite(font, "ᠰᠠᠢᠬᠠᠨ", script="mong")  # explicit
# res = {upem, glyph_count, stages:[{m,glyphs,depth,effective}], final, messages, engine}
```

`script` may be omitted (`auto`/empty behave the same): the script number is
auto-detected from the text using DWriteCore's own Unicode script data
(Common/Inherited/combining marks inherit from context).

`features` is a `{tag: bool}` map (same convention as the HarfBuzz/harfrust
engines): optional features toggle (`{"smcp": True}`, `{"liga": False}` …);
script-required features (Mongolian/Arabic `init/medi/fina/rclt` …) are fixed
by DWriteCore and cannot be disabled.

## Constraints

- Single-threaded by design: the per-lookup trace comes from a process-local
  hook that is installed per call and restored afterwards (the GIL serialises
  calls from Python, so repeated calls are safe).
- The hook is signature-locked to the bundled DWriteCore build
  (2.1.1.2605) with automatic relocation by prologue scan for newer builds.

## Provenance / licensing

- Our Rust/Python code: MIT (see the source repository).
- Bundled **`DWriteCore.dll`** is Microsoft software from the Windows App SDK
  (`Microsoft.WindowsAppSDK.DWrite`), redistributed under Microsoft's license
  terms for that component; the DLL is Microsoft-signed and unmodified.

## Build (maintainers, Windows)

```powershell
# stage the MS-signed DWriteCore.dll (from build/dwc_poc or the Windows App SDK NuGet)
Copy-Item build\dwc_poc\DWriteCore.dll python\pydwshape-wheel\python\pydwshape\DWriteCore.dll
cd python\pydwshape-wheel
python -m pip install maturin
python -m maturin build --release --interpreter <python> -o dist
```


## Cross-platform Wine backend (v0.2.0+)

Since 0.2.0 the wheel also bundles the **Wine DWrite port**
(`tools/wine_dwrite`) as a second, cross-platform engine:

```python
res = shape_with_dwrite(font, text, backend="dwcore")       # default, Windows: native DWriteCore
res = shape_with_dwrite(font, text, backend="winedwrite")   # Wine DWrite port, cross-platform
```

* `backend="dwcore"` is unchanged (Windows x64 only, bundled DWriteCore.dll).
* `backend="winedwrite"` loads the bundled Wine DWrite port shared library
  (`winedwrite.dll` / `libwinedwrite.so` / `libwinedwrite.dylib`) in-process via
  ctypes — no DWriteCore, no system DirectWrite. Script is auto-detected from
  the text; the per-lookup trace is genuine; Mongolian converges
  byte-identically to DWriteCore on the hudum corpus.
* On non-Windows the package imports fine; only `backend="dwcore"` raises
  (it needs the Windows DWriteCore native engine). Set `WDWRITE_LIB` to point
  at an existing build to override the bundled library.

## Building the wheel

Windows (builds the Wine port, bundles `winedwrite.dll` + `DWriteCore.dll`,
then maturin):
```
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

Linux / macOS (builds the Wine port as a shared lib, bundles it, then maturin;
the dwcore backend is not included on these platforms):
```
bash build.sh     # requires cc + make + maturin
```

License note: the bundled Wine DWrite port is LGPL-2.1-or-later; see
`python/pydwshape/NOTICE.md` in the wheel.
