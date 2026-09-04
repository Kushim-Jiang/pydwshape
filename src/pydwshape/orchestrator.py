"""Frida orchestration: drives the worker subprocess and collects trace events.

pydwshape cannot hook its own process, so it spawns a dedicated worker
(``python -m pydwshape.worker``), attaches Frida to *that* process, resolves the
internal ``TextShaping.dll`` hook addresses from the offline RVA registry, and
feeds shape commands over the worker's stdin/stdout while events stream back
through Frida's message channel.

This module deliberately knows nothing about the public API result types; it
returns a :class:`TraceOutcome` (raw events + the worker's authoritative glyph
result + metadata) that :mod:`pydwshape.api` assembles into a
:class:`~pydwshape.TraceResult`.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from . import addr_resolve
from .errors import FridaError, TraceTimeoutError, WorkerError

__all__ = ["Engine", "TraceOutcome"]

#: The Frida agent source (shipped inside the wheel).
_AGENT_SOURCE = resources.files("pydwshape").joinpath("agent.js").read_text(encoding="utf-8")
_CFG_TOKEN = "__DWSHAPE_CFG__"


@dataclass
class TraceOutcome:
    """Everything produced by one traced shape (pre-assembly)."""

    events: list[dict[str, Any]]  # frida events for this shape, in order
    result: dict[str, Any]  # worker's authoritative reply (glyphs/upem/names)
    meta: dict[str, Any]  # engine metadata merged into TraceResult.meta
    gpos_seen: bool = False


class Engine:
    """Low-level orchestrator. One Engine == one worker process + one Frida session."""

    def __init__(self, *, timeout: float = 10.0, symbols: bool = False) -> None:
        self.timeout = timeout
        self.symbols = symbols or addr_resolve.symbols_requested()

        self._proc: Any = None
        self._session: Any = None
        self._script: Any = None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()

        self._events: list[dict[str, Any]] = []
        self._events_lock = threading.Lock()
        self._hello = threading.Event()
        self._ready = threading.Event()
        self._gpos = threading.Event()
        self._fatal: str | None = None
        self._hello_base: str | None = None
        self._hello_size: int | None = None

        self._meta: dict[str, Any] = {}
        self._started = False
        self._closed = False

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        """Spawn the worker, attach Frida, resolve + install hooks."""
        if self._started:
            return
        try:
            self._spawn_worker()
            self._attach_and_install()
        except Exception:
            self.close()
            raise
        self._started = True

    def _spawn_worker(self) -> None:
        cmd = [sys.executable, "-m", "pydwshape.worker"]
        env = os.environ.copy()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as exc:
            raise WorkerError(f"could not spawn worker {cmd!r}: {exc}") from exc

        reader = threading.Thread(
            target=self._read_worker, daemon=True, name="pydwshape-worker-reader"
        )
        reader.start()

        try:
            reply = self._wait_line({"ready"}, self.timeout, "worker ready")
        except WorkerError:
            raise
        if reply.get("t") != "ready":
            raise WorkerError("worker did not become ready")
        self._meta["worker_pid"] = reply.get("pid")
        ts_base = reply.get("ts_base")
        if ts_base:
            self._meta["worker_ts_base"] = str(ts_base)

    def _attach_and_install(self) -> None:
        import frida

        try:
            self._session = frida.attach(int(self._proc.pid))
        except Exception as exc:  # pragma: no cover - environment specific
            raise FridaError(f"could not attach to worker pid {self._proc.pid}: {exc}") from exc

        # The worker preloads TextShaping.dll before READY, so the module is
        # present. The agent computes base + RVA itself (it can read its own
        # module base), verifies the byte signature, then hooks.
        info = addr_resolve.detect_textshaping()
        resolution = addr_resolve.resolve(info)

        functions = resolution.functions
        af = functions.get("ApplyFeatures")
        al = functions.get("ApplyLookup")
        if af is None or al is None:
            raise FridaError(f"RVA registry entry for {resolution.family} lacks hook addresses")

        config = {
            "af_rva": af.rva_hex,
            "al_rva": al.rva_hex,
            "sig_af": af.signature,
            "sig_al": al.signature,
            "symbols": self.symbols,
            "addr_source": resolution.mode,
            "version": resolution.version,
        }
        self._meta.update(
            {
                "engine": "directwrite",
                "ts_version": resolution.version,
                "ts_family": resolution.family,
                "ts_path": str(resolution.path),
                "addr_source": resolution.mode,
                "addr_registry": True,
            }
        )

        source = _AGENT_SOURCE.replace(_CFG_TOKEN, json.dumps(config))
        self._script = self._session.create_script(source)
        self._script.on("message", self._on_message)
        self._script.load()

        if not self._ready.wait(self.timeout):
            hint = ""
            if self._meta.get("worker_ts_base"):
                hint = (
                    " The worker reports TextShaping.dll is loaded, but the Frida agent "
                    "cannot see/instrument it. This usually means another program is "
                    "intercepting DirectWrite (e.g. a font tool such as MacType), or a "
                    "build incompatibility. Disable such tools for the traced process, "
                    "then retry."
                )
            raise FridaError(f"frida agent did not become ready.{hint}")
        if self._fatal:
            raise FridaError(f"frida agent failed: {self._fatal}")
        if self._hello_base is not None:
            self._meta["textshaping_base"] = self._hello_base
            self._meta["textshaping_size"] = self._hello_size

    # ------------------------------------------------------------------- io
    def _read_worker(self) -> None:
        """Background thread: drain worker stdout (avoids pipe deadlock)."""
        try:
            assert self._proc is not None and self._proc.stdout is not None
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._queue.put(obj)
        except Exception:
            pass
        finally:
            self._queue.put({"t": "eof"})

    def _wait_line(self, wanted: set[str], timeout: float, what: str) -> dict[str, Any]:
        """Block until a worker line whose ``t`` is in ``wanted`` arrives."""
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TraceTimeoutError(f"timed out waiting for {what}")
            try:
                obj = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise TraceTimeoutError(f"timed out waiting for {what}") from None
            kind = obj.get("t")
            if kind == "eof":
                raise WorkerError("worker exited unexpectedly (EOF on stdout)")
            if kind == "fatal":
                raise WorkerError(str(obj.get("message") or "worker fatal error"))
            if kind in wanted:
                return obj
        raise WorkerError("internal error: _wait_line fell through")  # unreachable

    def _write(self, obj: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None or self._proc.poll() is not None:
            raise WorkerError("worker is not running")
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _on_message(self, message: dict[str, Any], data: Any) -> None:
        del data
        payload = message.get("payload") if message.get("type") == "send" else message
        if not isinstance(payload, dict):
            return
        kind = payload.get("t")
        if kind == "hello":
            self._hello_base = str(payload.get("base") or "")
            try:
                self._hello_size = int(payload.get("size") or 0)
            except (TypeError, ValueError):
                self._hello_size = None
            self._hello.set()
        elif kind == "ready":
            self._ready.set()
        elif kind == "fatal":
            self._fatal = str(payload.get("msg") or "")
            self._ready.set()
            self._gpos.set()
        else:
            with self._events_lock:
                self._events.append(payload)
            if kind == "gpos_end":
                self._gpos.set()

    # ----------------------------------------------------------------- shape
    def shape(
        self,
        font: Path,
        text: str,
        features: dict[str, Any] | None = None,
        language: str = "",
    ) -> TraceOutcome:
        """Run one traced shape and return its events + worker result."""
        self.start()

        with self._events_lock:
            start_index = len(self._events)
        self._gpos.clear()

        self._write(
            {
                "cmd": "shape",
                "font": str(font),
                "text": text,
                "features": features or {},
                "language": language,
            }
        )

        began = time.time()
        reply = self._wait_line({"result", "error"}, self.timeout, "shape result")
        if reply.get("t") == "error":
            raise WorkerError(str(reply.get("message") or "worker shape error")) from None
        if reply.get("t") != "result":
            raise WorkerError("unexpected worker reply") from None

        # Worker result marks the end of dw.shape(); trace events are already
        # queued but may still be in flight. Wait for gpos_end if any arrived.
        with self._events_lock:
            saw_events = len(self._events) > start_index
        if saw_events:
            deadline = began + self.timeout
            while not self._gpos.is_set():
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._gpos.wait(remaining)

        with self._events_lock:
            events = list(self._events[start_index:])
        gpos_seen = any(e.get("t") == "gpos_end" for e in events)

        result = reply.get("result") if isinstance(reply.get("result"), dict) else None
        if result is None:
            # reply is the flat result dict when t == 'result'
            result = {k: v for k, v in reply.items() if k != "t"}

        meta = dict(self._meta)
        meta["elapsed_s"] = round(time.time() - began, 4)
        meta["completion"] = "gpos_end" if gpos_seen else ("events" if events else "result")
        return TraceOutcome(events=events, result=result, meta=meta, gpos_seen=gpos_seen)

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        """Detach Frida and terminate the worker (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._script is not None:
                with contextlib.suppress(Exception):
                    self._script.unload()
                self._script = None
            if self._session is not None:
                with contextlib.suppress(Exception):
                    self._session.detach()
                self._session = None
        finally:
            if self._proc is not None:
                try:
                    if self._proc.stdin is not None:
                        self._proc.stdin.close()
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                except Exception:
                    pass
                self._proc = None

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
