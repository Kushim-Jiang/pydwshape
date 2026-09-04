"""Tests for addr_resolve.py — offline RVA registry resolution (no Frida)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pydwshape as pyd
from pydwshape.addr_resolve import (
    TextShapingInfo,
    family_from_version,
    registry_entry,
    registry_families,
    resolve,
    symbols_requested,
    textshaping_path,
    verify_signature,
)
from pydwshape.errors import UnsupportedTextShapingError


def test_family_from_version() -> None:
    assert family_from_version("10.0.26100.9223") == "10.0.26100"
    assert family_from_version("10.0.19041") == "10.0.19041"
    assert family_from_version("0.0.0.0") == "0.0.0"


def test_registry_is_populated_and_valid() -> None:
    families = registry_families()
    assert families, "registry must contain at least one family"
    for family in families:
        entry = registry_entry(family)
        assert entry is not None
        funcs = entry["functions"]
        for name in ("ApplyFeatures", "ApplyLookup"):
            spec = funcs[name]
            rva = int(str(spec["rva"]), 16)
            sig = str(spec["signature"])
            assert rva > 0
            assert len(sig) >= 16  # at least 8 bytes
            assert len(sig) % 2 == 0
            int(sig, 16)  # valid hex


def test_resolve_known_family() -> None:
    info = TextShapingInfo(
        path=Path("."),
        version="10.0.26100.9223",
        family="10.0.26100",
    )
    resolution = resolve(info)
    assert resolution.mode == "rva"
    assert resolution.family == "10.0.26100"
    assert resolution.required_functions() == ("ApplyFeatures", "ApplyLookup")
    af = resolution.functions["ApplyFeatures"]
    al = resolution.functions["ApplyLookup"]
    assert af.rva == 0x15650 and af.signature
    assert al.rva == 0x7A60 and al.signature
    assert af.rva_hex == "0x15650"


def test_resolve_unknown_family_raises_with_guidance() -> None:
    info = TextShapingInfo(path=Path("."), version="10.0.99999.1", family="10.0.99999")
    with pytest.raises(UnsupportedTextShapingError) as excinfo:
        resolve(info)
    msg = str(excinfo.value)
    assert "10.0.99999" in msg
    assert "rva_registry.json" in msg  # guidance points at the registry


def test_verify_signature_prefix_match() -> None:
    assert verify_signature("4055564154415541564157488dac24e8", "4055564154415541")
    assert verify_signature("40555641", "40555641")
    assert not verify_signature("deadbeef", "40555641")
    assert verify_signature("anything", "")  # empty expectation => accept


def test_symbols_requested_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PY_DWSHAPE_USE_SYMBOLS", raising=False)
    assert symbols_requested() is False
    monkeypatch.setenv("PY_DWSHAPE_USE_SYMBOLS", "1")
    assert symbols_requested() is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only path layout")
def test_textshaping_path_on_windows() -> None:
    p = textshaping_path()
    assert p.name.lower() == "textshaping.dll"
    assert p.is_absolute()


def test_supported_families_exported() -> None:
    assert tuple(pyd.supported_textshaping_families()) == registry_families()
