"""pydwshape quickstart — trace one Mongolian string and print the stages.

Usage:
    uv run python examples/quickstart.py [FONT]

Requires a font with a Mongolian OpenType layout (e.g. Menksoft Qagan/Hudum).
If omitted, points at the default hudum path used during development.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pydwshape

DEFAULT_FONT = Path(r"D:\Github\mongfontbuilder\temp\hudum.otf")
TEXT = "\u1830\u1820\u1822\u182c\u1820\u1828"  # Mongolian "ᠰᠠᠢᠬᠠᠨ" (beautiful)


def main() -> int:
    font = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FONT
    if not font.is_file():
        print(f"font not found: {font}")
        return 1

    print(f"tracing {TEXT!r} with {font.name} ...")
    result = pydwshape.trace_directwrite(font=font, text=TEXT)

    print(f"\nupem            : {result.upem}")
    print(f"final glyphs    : {result.final_glyphs}")
    print(
        "glyph names     : "
        + ", ".join(f"{gid}={name}" for gid, name in sorted(result.glyph_names.items()))
    )

    for run in result.runs:
        print(f"\nrun #{run.index} ({run.table})")
        for phase in run.feature_phases:
            print(f"  phase #{phase.index}  features={phase.features}")
            for lookup in phase.lookups:
                changed = ""
                if lookup.changed:
                    changed = "  changed=" + ",".join(f"{p}:{o}->{n}" for p, o, n in lookup.changed)
                print(f"    lookup #{lookup.index:>2}  glyphs={lookup.glyphs}{changed}")

    print(
        f"\nmeta: engine_build={result.meta.get('ts_version')} "
        f"addr={result.meta.get('addr_source')} "
        f"elapsed={result.meta.get('elapsed_s')}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
