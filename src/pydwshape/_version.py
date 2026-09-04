"""Version information for :mod:`pydwshape`.

The version lives in exactly one place (here) and is referenced by both the
package ``__init__`` and the build backend (see ``pyproject.toml``).
"""

from __future__ import annotations

__all__ = ["__version__", "version_tuple"]

#: The full public version string, e.g. ``"0.1.0"``.
__version__ = "0.1.0"

#: The same version as a tuple of ``(major, minor, patch)`` ints.
version_tuple: tuple[int, int, int] = (0, 1, 0)
