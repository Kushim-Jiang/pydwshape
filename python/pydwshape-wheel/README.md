# pydwshape

**Windows-only.** A DWriteCore-native per-lookup OpenType shaping tracer for
[BabelMap](https://www.babelstone.co.uk/BabelMap/index.html)'s OpenType test
framework — the DirectWrite analogue of its HarfBuzz/HarfRust engines.

It shapes **entirely with Microsoft DWriteCore** (app-local, version-pinned)
and returns the babelsoft `/api/opentype/shape` result dict, including the
per-lookup glyph-mutation trace. No system `dwrite.dll` / `TextShaping.dll` is
loaded (no DLL-hijack surface), and no subprocess is spawned — the Rust engine
runs in-process via this PyO3 **abi3** extension.

## Requires

- Windows 10 1809+ (x64)
- CPython 3.9+ (any 3.9+ interpreter; wheel tag `cp39-abi3-win_amd64`)

Importing on any other OS raises `OSError`.

## Install

```powershell
pip install pydwshape
```

## Usage

```python
from pydwshape import shape_with_dwrite

font = open("font.otf", "rb").read()
res = shape_with_dwrite(font, "ᠰᠠᠢᠬᠠᠨ", script="mong")
# res = {upem, glyph_count, stages:[{m,glyphs,depth,effective}], final, messages, engine}
```

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
