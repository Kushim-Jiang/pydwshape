# Extending the RVA registry for a new TextShaping.dll build

`ApplyFeatures` / `ApplyLookup` are **not exported** from `TextShaping.dll`, and
pydwshape resolves them with **zero network**: a static RVA registry
(`src/pydwshape/rva_registry.json`) plus byte-signature verification before
hooking. When a user hits an unsupported Windows build, pydwshape raises
`UnsupportedTextShapingError` with a pointer to this file.

Adding a new build takes ~10 minutes on a machine with that build installed
(the DLL itself is enough — no PDB required if you can recognise the two
functions; a local PDB just makes naming easier).

## Reference measurements (this repo's starting point)

Measured 2026-09-04 against **TextShaping 10.0.26100.9223** (Windows 11 24H2;
dwrite 10.0.26100.8875):

| function        | RVA       | first-16-bytes signature           |
| --------------- | --------- | ---------------------------------- |
| `ApplyFeatures` | `0x15650` | `4055564154415541564157488dac24e8` |
| `ApplyLookup`   | `0x7A60`  | `4c894c24204889542410555356415441` |

These are encoded in the `10.0.26100` registry entry. **Do not assume other
builds match** — verify each new build with the steps below.

## Steps for a new build (e.g. 10.0.xxxxx)

### 1. Copy the DLL

```
copy C:\Windows\System32\TextShaping.dll  <workdir>\TextShaping.dll
```

If you have a matching PDB (`C:\Windows\System32\TextShaping.pdb` or from a
local symbol store), keep it alongside — Ghidra can auto-analyse it for names.

### 2. Decompile with Ghidra (headless)

Ghidra 12.x headless: `analyzeHeadless.bat` (the _project dir must already
exist_).

```
D:\...\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat ^
    <workdir>\ghidra_proj  TextShaping  ^
    -import <workdir>\TextShaping.dll ^
    -scriptPath tools\ghidra ^
    -postScript ExportDecompiled.java "<workdir>\decompiled" ^
    -deleteProject
```

Outputs: `decompiled/TextShaping_all.c`, `decompiled/functions/` and
`decompiled/TextShaping_symbols.tsv` (address → name).

### 3. Find ApplyFeatures / ApplyLookup

- With a PDB loaded, their names appear directly in the symbols TSV and the
  per-function files.
- Without a PDB, the functions are named `FUN_1800xxxxx`. Match them by
  signature in `TextShaping_all.c`:

  ```c
  // ApplyFeatures — many otlList*/otlResourceMgr* pointer args; reads tag arg[0]
  int __cdecl ApplyFeatures(int tag, otlFeatureSet *fs, otlList *p3, otlList *p4,
                            otlResourceMgr *rm, int scriptTag, int langTag, ...)
  // ApplyLookup — glyph otlList is arg[2] (records of 4 x u16)
  int ApplyLookup(int tag, otlList *glyphIdx, otlList *glyphs, otlResourceMgr *, ...)
  ```

  On x64 the RVA = address − `0x180000000` (the preferred image base), e.g.
  `0x180015650 − 0x180000000 = 0x15650`.

### 4. Dump the byte signatures

`tools/pe_rva.py` maps RVA → file offset and prints the first instructions
(no third-party dependency):

```
python tools\pe_rva.py <workdir>\TextShaping.dll 0x15650 0x7A60 -n 16
```

### 5. Add the registry entry

Append to `src/pydwshape/rva_registry.json` under `windows`:

```jsonc
"10.0.xxxxx": {
  "family": "10.0.xxxxx",
  "note": "Windows <name>. Measured <date> against TextShaping <full version>.",
  "functions": {
    "ApplyFeatures": { "rva": "0x____", "signature": "<hex from step 4>" },
    "ApplyLookup":   { "rva": "0x____", "signature": "<hex from step 4>" }
  }
}
```

### 6. Verify

```
uv run pytest tests/test_addr_resolve.py          # registry parses & resolves
uv run pytest tests/test_golden_mongolian.py -k golden -v   # full E2E (needs hudum.otf + frida)
```

## Notes

- **Signature verification is the anti-blind-hook safety net**: pydwshape reads
  the bytes at `base + RVA` in the worker and refuses to instrument on a
  mismatch (never hooks a wrong address).
- Same-`10.0.xxxxx` minor builds usually share these RVAs, but verify the first
  time; if a servicing update moves the functions, add a distinct entry.
- `pe_rva.py` and `export_decompiled.java` both ship in this repo; no PDB
  download is ever performed.
