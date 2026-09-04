"""Zero-network address resolution for ``TextShaping.dll`` internals.

``ApplyFeatures`` / ``ApplyLookup`` are *not* exported functions, so Frida's
``enumerateExports`` cannot find them. Historically the drite work resolved
them from a local PDB (requires ``_NT_SYMBOL_PATH``). pydwshape instead ships an
**offline RVA registry** (``rva_registry.json``) and never talks to the network:

1. read the ``TextShaping.dll`` file version from disk (stdlib ``version.dll``
   API via :mod:`ctypes`),
2. look up the version family in the package registry to get the RVAs of
   ``ApplyFeatures`` / ``ApplyLookup`` plus a byte-signature prefix,
3. after Frida attach, the orchestrator reads the bytes at ``base + rva`` in
   the worker and verifies them against the signature **before** hooking —
   never a blind hook.

An optional, non-default enhancement: if the worker has a matching PDB on
``_NT_SYMBOL_PATH`` *and* ``PY_DWSHAPE_USE_SYMBOLS=1`` is set, names are
resolved from symbols first (still no network).
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_uint32,
    c_void_p,
    create_string_buffer,
    wintypes,
)
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, cast

from .errors import UnsupportedTextShapingError

__all__ = [
    "FunctionAddress",
    "Resolution",
    "TextShapingInfo",
    "detect_textshaping",
    "family_from_version",
    "registry_entry",
    "registry_families",
    "resolve",
    "symbols_requested",
    "textshaping_path",
    "verify_signature",
]

#: Env var that opts in to PDB-symbol resolution (off by default).
SYMBOLS_ENV: str = "PY_DWSHAPE_USE_SYMBOLS"


class _VS_FIXEDFILEINFO(Structure):
    """Windows ``VS_FIXEDFILEINFO`` (we only read the file-version fields)."""

    _fields_ = [
        ("dwSignature", c_uint32),
        ("dwStrucVersion", c_uint32),
        ("dwFileVersionMS", c_uint32),
        ("dwFileVersionLS", c_uint32),
        ("dwProductVersionMS", c_uint32),
        ("dwProductVersionLS", c_uint32),
        ("dwFileFlagsMask", c_uint32),
        ("dwFileFlags", c_uint32),
        ("dwFileOS", c_uint32),
        ("dwFileType", c_uint32),
        ("dwFileSubtype", c_uint32),
        ("dwFileDateMS", c_uint32),
        ("dwFileDateLS", c_uint32),
    ]


def textshaping_path() -> Path:
    """Path of the ``TextShaping.dll`` the *worker* will load.

    A 32-bit Python loads the SysWOW64 copy; a 64-bit Python loads System32.
    Because the orchestrator spawns the worker from the same interpreter, both
    observe the same DLL.
    """
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    sub = "System32" if struct.calcsize("P") == 8 else "SysWOW64"
    return Path(root) / sub / "TextShaping.dll"


def _file_version(path: Path) -> str | None:
    """Return the FileVersion (``A.B.C.D``) of a PE file via ``version.dll``."""
    try:
        ver = ctypes.WinDLL("version", use_last_error=True)
    except OSError:
        return None
    ver.GetFileVersionInfoSizeW.restype = c_uint32
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if size <= 0:
        return None
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, c_void_p]
    buf = create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    ver.VerQueryValueW.argtypes = [c_void_p, wintypes.LPCWSTR, POINTER(c_void_p), wintypes.LPDWORD]
    p_block = c_void_p()
    p_len = wintypes.UINT()
    if not ver.VerQueryValueW(buf, "\\", byref(p_block), byref(p_len)) or not p_block.value:
        return None
    info = ctypes.cast(p_block, POINTER(_VS_FIXEDFILEINFO)).contents
    if info.dwSignature != 0xFEEF04BD:
        return None
    ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


@dataclass(frozen=True)
class TextShapingInfo:
    """Detected facts about the local ``TextShaping.dll``."""

    path: Path
    version: str
    family: str


def detect_textshaping() -> TextShapingInfo:
    """Detect the TextShaping.dll the worker will load (stdlib only)."""
    path = textshaping_path()
    version = _file_version(path) if path.is_file() else None
    if not version:
        raise UnsupportedTextShapingError(
            f"Could not read a FileVersion from {path}. pydwshape is Windows-only "
            "and requires a real TextShaping.dll on this machine."
        )
    return TextShapingInfo(path=path, version=version, family=family_from_version(version))


def family_from_version(version: str) -> str:
    """Map a full version to its registry family key (first 3 segments).

    >>> family_from_version("10.0.26100.9223")
    '10.0.26100'
    """
    parts = version.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else version


def _registry() -> dict[str, Any]:
    text = resources.files("pydwshape").joinpath("rva_registry.json").read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))


def registry_families() -> tuple[str, ...]:
    """Sorted tuple of supported TextShaping version families."""
    windows = _registry().get("windows", {})
    return tuple(sorted(windows.keys()))


#: Public alias (also re-exported from the package ``__init__``).
supported_textshaping_families = registry_families


@dataclass(frozen=True)
class FunctionAddress:
    """RVA + byte-signature for one hookable internal function."""

    name: str
    rva: int
    signature: str  # hex string prefix of the first instructions

    @property
    def rva_hex(self) -> str:
        return f"0x{self.rva:x}"


@dataclass(frozen=True)
class Resolution:
    """The offline resolution result for the local TextShaping build."""

    version: str
    family: str
    path: Path
    mode: str  # always "rva" for now; "symbols" is a future opt-in
    functions: dict[str, FunctionAddress]

    def required_functions(self) -> tuple[str, ...]:
        """Hook targets that must be present for a trace."""
        return ("ApplyFeatures", "ApplyLookup")


def registry_entry(family: str) -> dict[str, Any] | None:
    """Return the raw registry entry dict for a family, or ``None``."""
    entry = _registry().get("windows", {}).get(family)
    if entry is None:
        return None
    return cast(dict[str, Any], entry)


def resolve(info: TextShapingInfo) -> Resolution:
    """Resolve hook addresses for a detected TextShaping build.

    Raises :class:`UnsupportedTextShapingError` when the build is not covered
    by the offline registry — with instructions to extend it.
    """
    entry = registry_entry(info.family)
    if entry is None:
        supported = ", ".join(registry_families())
        raise UnsupportedTextShapingError(
            f"TextShaping {info.version} (family {info.family!r}) is not in the offline "
            f"RVA registry. Supported families: {supported or '(none)'}.\n"
            "To add it: decompile this build (tools/ghidra/README.md), find the RVAs of "
            "ApplyFeatures/ApplyLookup, dump signatures with tools/pe_rva.py, and append a "
            f"'{info.family}' entry to src/pydwshape/rva_registry.json."
        )
    functions: dict[str, FunctionAddress] = {}
    raw = entry.get("functions", {})
    for name, spec in raw.items():
        functions[name] = FunctionAddress(
            name=name,
            rva=int(str(spec["rva"]), 16),
            signature=str(spec.get("signature", "")).lower(),
        )
    return Resolution(
        version=info.version,
        family=info.family,
        path=info.path,
        mode="rva",
        functions=functions,
    )


def verify_signature(actual_hex: str, expected_hex: str) -> bool:
    """True when the observed bytes start with the expected signature prefix.

    The comparison is deliberately a *prefix* match on hex so a slightly longer
    read still validates, and a shorter stored signature still works.
    """
    return actual_hex.lower().startswith(expected_hex.lower()) if expected_hex else True


def symbols_requested() -> bool:
    """Whether PDB-symbol resolution was explicitly opted in via env var."""
    return os.environ.get(SYMBOLS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
