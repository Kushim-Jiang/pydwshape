"""Exception hierarchy for :mod:`pydwshape`.

All pydwshape-specific failures derive from :class:`PydwshapeError`, so a
single ``except pydwshape.PydwshapeError`` catches every library-raised error.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AddressMismatchError",
    "FridaError",
    "PydwshapeError",
    "TraceTimeoutError",
    "UnsupportedTextShapingError",
    "WindowsOnlyError",
    "WorkerError",
]


class PydwshapeError(Exception):
    """Base class for all pydwshape errors."""


class WindowsOnlyError(PydwshapeError):
    """Raised when a Windows-only API is used on a non-Windows platform.

    pydwshape traces the Windows system component ``TextShaping.dll``, which
    exists only on Microsoft Windows and cannot be redistributed or run on
    macOS / Linux. On those platforms, use HarfBuzz for the equivalent trace.
    """


class WorkerError(PydwshapeError):
    """Raised when the DirectWrite worker subprocess fails.

    Covers spawn failures, an unclean ``READY``, an unexpected EOF, an error
    reply to a command, or a crash mid-shape.
    """


class FridaError(PydwshapeError):
    """Raised when Frida cannot attach to / instrument the worker process."""


class UnsupportedTextShapingError(PydwshapeError):
    """The local ``TextShaping.dll`` build is not covered by the RVA registry.

    Address resolution is deliberately offline (a package-internal RVA
    registry + byte-signature verification) and never falls back to a blind
    hook. When a new Windows build is encountered this error explains how to
    extend ``src/pydwshape/rva_registry.json`` (see ``tools/ghidra/README.md``).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AddressMismatchError(PydwshapeError):
    """The bytes at a resolved address did not match the expected signature.

    This is the safety net that prevents a *blind hook*: if the RVA table is
    wrong for the running build we refuse to instrument rather than hook the
    wrong location.
    """


class TraceTimeoutError(PydwshapeError):
    """A shape trace did not complete within the configured timeout."""

    def __init__(self, message: str, collected_events: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.collected_events: list[dict[str, Any]] = collected_events or []
