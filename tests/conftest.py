"""Shared pytest fixtures and environment handling for pydwshape tests.

Two optional resources gate the tests, and every test auto-skips when its
resource is missing (mirrors the pygraphite2 test layout):

* a **live DirectWrite environment**: Windows + ``frida`` + ``dwriteshapepy``;
* a **Mongolian test font** (``hudum.otf``; override the path with the
  ``PYDWSHAPE_HUDUM`` env var).

The pure-Python parts (result assembly, address resolution, decoding) run
anywhere and are always exercised.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Optional Mongolian OpenType font used by the golden test.
HUDUM = Path(os.environ.get("PYDWSHAPE_HUDUM", r"D:\Github\mongfontbuilder\temp\hudum.otf"))

IS_WINDOWS = os.name == "nt"


def _frida_available() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import frida  # noqa: F401

        return True
    except Exception:
        return False


def _dwriteshapepy_available() -> bool:
    try:
        import dwriteshapepy  # noqa: F401

        return True
    except Exception:
        return False


needs_native = pytest.mark.skipif(
    not (_frida_available() and _dwriteshapepy_available()),
    reason="live DirectWrite trace needs Windows + frida + dwriteshapepy",
)

needs_worker = pytest.mark.skipif(
    not (IS_WINDOWS and _dwriteshapepy_available()),
    reason="worker protocol test needs Windows + dwriteshapepy",
)

needs_hudum = pytest.mark.skipif(
    not HUDUM.is_file(),
    reason=f"missing Mongolian test font: {HUDUM} (set PYDWSHAPE_HUDUM)",
)


@pytest.fixture(scope="session")
def hudum_path() -> Path:
    """Path to the hudum.otf Mongolian test font."""
    return HUDUM


@pytest.fixture(scope="session")
def live_trace_supported(hudum_path: Path) -> bool:
    """Probe whether a real DirectWrite trace is possible on this machine.

    Returns ``True`` when a full trace succeeds. When the environment cannot
    be instrumented (e.g. a font tool such as MacType intercepts DirectWrite
    so Frida cannot read ``dwrite.dll``/``TextShaping.dll``), the whole golden
    module skips with the reason — matching the graceful-degradation style of
    the rest of the suite.
    """
    del hudum_path
    if not (IS_WINDOWS and _frida_available() and _dwriteshapepy_available() and HUDUM.is_file()):
        return False
    import pydwshape
    from pydwshape.errors import FridaError

    try:
        pydwshape.trace_directwrite(font=HUDUM, text=MONGOLIAN, timeout=6.0)
        return True
    except FridaError as exc:
        msg = str(exc)
        if "MacType" in msg or "cannot see/instrument" in msg:
            pytest.skip(f"live DirectWrite tracing is blocked on this machine: {msg}")
        raise


# ---------------------------------------------------------------------------
# Golden fixture: hudum.otf + this Mongolian text must shape to these glyphs
# under BOTH DirectWrite and HarfBuzz (see DESIGN.md §4.5).
# ---------------------------------------------------------------------------
MONGOLIAN = "\u1830\u1820\u1822\u182c\u1820\u1828"  # ᠰᠠᠢᠬᠠᠨ
GOLDEN_GLYPHS = [675, 281, 303, 471, 281, 351]
