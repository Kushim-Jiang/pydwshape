"""Dump byte signatures at RVAs inside a Windows PE file, using only the stdlib.

This is the developer tool used to extend the offline RVA registry
(``src/pydwshape/rva_registry.json``) for a new ``TextShaping.dll`` build:

1. Decompile ``TextShaping.dll`` (see ``tools/ghidra/README.md``) to learn the
   RVAs of ``ApplyFeatures`` / ``ApplyLookup`` for that build, or resolve them
   from a matching local PDB.
2. Run this tool to capture the first-instruction bytes at each RVA:

   ::

       python tools/pe_rva.py C:\\Windows\\System32\\TextShaping.dll 0x15650 0x7A60

3. Add a ``10.0.xxxxx`` entry to the registry with those RVAs + signatures.

Rationale: the runtime (``pydwshape.addr_resolve``) never reads this file; the
signatures are baked into the shipped JSON so address resolution stays offline.

Pure stdlib on purpose (``struct`` only) — no ``pefile`` dependency.
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


def read_pe_sections(path: Path) -> list[Section]:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError(f"{path}: not a PE file")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off : pe_off + 4] != b"PE\x00\x00":
        raise ValueError(f"{path}: bad PE signature")
    n_sections = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
    sections: list[Section] = []
    for i in range(n_sections):
        off = pe_off + 24 + opt_size + i * 40
        name = data[off : off + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, raw_size, raw_off = struct.unpack_from("<IIII", data, off + 8)
        sections.append(
            Section(
                name=name,
                virtual_address=vaddr,
                virtual_size=vsize,
                raw_offset=raw_off,
                raw_size=raw_size,
            )
        )
    return sections


def rva_to_offset(sections: list[Section], rva: int) -> int | None:
    for sec in sections:
        start, end = sec.virtual_address, sec.virtual_address + max(sec.virtual_size, sec.raw_size)
        if start <= rva < end:
            return sec.raw_offset + (rva - sec.virtual_address)
    return None


def dump(path: Path, rva: int, count: int) -> None:
    sections = read_pe_sections(path)
    off = rva_to_offset(sections, rva)
    if off is None:
        print(f"  RVA 0x{rva:x}: no section maps this RVA")
        return
    data = path.read_bytes()
    sig = data[off : off + count]
    hexsig = sig.hex()
    print(f"  RVA 0x{rva:08x} -> file 0x{off:08x} ({len(sig)} bytes):")
    print(f'    signature: "{hexsig}"')
    # grouped for readability
    grouped = " ".join(hexsig[i : i + 16] for i in range(0, len(hexsig), 16))
    print(f"    grouped:   {grouped}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pe", type=Path, help="path to the PE file (e.g. TextShaping.dll)")
    ap.add_argument("rvas", nargs="+", help="RVAs to dump, e.g. 0x15650")
    ap.add_argument("-n", "--bytes", type=int, default=16, help="bytes per RVA (default 16)")
    args = ap.parse_args(argv)

    if not args.pe.is_file():
        print(f"error: no such file: {args.pe}")
        return 1

    for r in args.rvas:
        rva = int(r, 0)
        dump(args.pe, rva, args.bytes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
