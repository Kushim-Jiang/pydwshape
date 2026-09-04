# NOTICE

pydwshape is an independent, community project. **It is not a Microsoft
product and is not endorsed by Microsoft.** It observes the behaviour of the
Windows system component `TextShaping.dll` (and `dwrite.dll`) at runtime for
font-development purposes; it bundles, modifies or redistributes **no**
Microsoft binary or PDB, and makes **no network requests** at runtime.

## Acknowledgements

- **[frida](https://frida.re)** — dynamic instrumentation toolkit used to
  attach to the local shaping worker and observe the engine's internal
  feature/lookup calls. Frida is licensed under the wxWindows Library Licence
  (an independent dependency; no copyleft obligations on this project).
- **[Microsoft DWriteShapePy](https://github.com/microsoft/DWriteShapePy)**
  (`dwriteshapepy` on PyPI) — the Cython wrapper over DirectWrite's
  `IDWriteTextAnalyzer` that drives the public shaping API. MIT licensed.
- The reverse-engineering approach and the golden Mongolian test data were
  developed against Windows' own `TextShaping.dll` / `dwrite.dll` and
  cross-checked with HarfBuzz; Ghidra was used offline during development.

## Third-party licences

This package depends at runtime on `frida` (wxWindows Library Licence) and
`dwriteshapepy` (MIT), both of which are distributed separately on PyPI and
install only on Windows (`platform_system == 'Windows'` markers). No code from
either project is copied into this repository.

## Trademarks

DirectWrite, Windows and Microsoft are trademarks of Microsoft Corporation in
the United States and/or other countries. HarfBuzz is a trademark of its
contributors. All other trademarks belong to their respective owners.
