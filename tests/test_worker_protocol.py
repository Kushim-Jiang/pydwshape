"""Worker protocol test — spawns ``pydwshape.worker`` and talks JSON over pipes.

No Frida is involved here; this validates the child process contract
(ready/ping/result) that the orchestrator relies on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .conftest import needs_worker


def _send(proc: subprocess.Popen, obj: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _recv(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "worker closed stdout unexpectedly"
    return json.loads(line)


@needs_worker
def test_worker_ready_ping_and_latin_shape() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "pydwshape.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        ready = _recv(proc)
        assert ready["t"] == "ready"
        assert isinstance(ready.get("pid"), int)

        _send(proc, {"cmd": "ping"})
        assert _recv(proc)["t"] == "pong"

        segoe = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "Fonts" / "segoeui.ttf"
        if segoe.is_file():
            _send(
                proc,
                {"cmd": "shape", "font": str(segoe), "text": "abc", "features": {}, "language": ""},
            )
            result = _recv(proc)
            assert result["t"] == "result"
            assert result["upem"] > 0
            assert isinstance(result["glyphs"], list) and result["glyphs"]
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


@needs_worker
def test_worker_reports_bad_font() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "pydwshape.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        assert _recv(proc)["t"] == "ready"
        _send(
            proc,
            {
                "cmd": "shape",
                "font": r"C:\does-not-exist.ttf",
                "text": "a",
                "features": {},
                "language": "",
            },
        )
        reply = _recv(proc)
        assert reply["t"] == "error"
        assert "FileNotFoundError" in reply["message"]
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
