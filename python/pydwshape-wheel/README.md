# pydwshape (Python wheel)

Windows-only, DWriteCore-native per-lookup OpenType shaping tracer, packaged as
a PyO3 **abi3** wheel (`py3-none-win_amd64`). Wraps the `dwtshape` Rust engine
(see repo `README.md`) so BabelMap's OpenType test framework can call it
in-process — no subprocess, no system `dwrite`/`TextShaping`.

## Requires

- Windows 10 1809+ (x64)
- CPython >= 3.9 (abi3 → any 3.9+ interpreter works)

## Build (on Windows)

```powershell
# 1. stage the DWriteCore.dll (MS-signed, from the Windows App SDK NuGet)
Copy-Item ..\..\build\dwc_poc\DWriteCore.dll .\python\pydwshape\DWriteCore.dll

# 2. build the abi3 wheel
& <python> -m pip install maturin
maturin build --release --interpreter <python>    # -> target/wheels/pydwshape-...-py3-none-win_amd64.whl
```

`DWriteCore.dll` is git-ignored (fetched from `build/dwc_poc` which is also
git-ignored); a fresh clone must re-fetch it before building.

## Usage (inside babelmap)

```python
from pydwshape import shape_with_dwrite
res = shape_with_dwrite(font_bytes, text, script="mong")  # -> /api/opentype/shape dict
```

`features` is `{tag: bool}` (same as the HarfBuzz/harfrust engines). Optional
features toggle (`+smcp`, `liga=0` …); script-required features
(Mongolian/Arabic `init/medi/fina/rclt`…) are fixed by DWriteCore.

## Constraints

- Single-threaded shaping (hooks are process-local and restored after each
  call; the GIL serialises calls from Python).
- Importing on non-Windows raises `OSError`.
