"""Structured JSONL logging for QFAN prototype events."""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

LOG_DIR = Path(__file__).resolve().parents[2] / "qfan_logs"
ROTATE_SIZE_BYTES = 50 * 1024 * 1024

_RECV = re.compile(r"Empfang von (?:qfan\.de/)?(?P<sender>[\w.\-]+):\s*(?P<text>.*)$")
_SEND = re.compile(r"Du \[(?:qfan\.de/)?(?P<from>[\w.\-/]+)\]:\s*(?P<text>.*)$")


def classify(text: str) -> tuple:
    match = _RECV.search(text)
    if match: return "recv", {"sender": match["sender"], "msg_text": match["text"]}
    match = _SEND.search(text)
    if match: return "send", {"from": match["from"], "msg_text": match["text"]}
    if "LOCKDOWN:" in text: return "liouville_reject", {"error": text.split("LOCKDOWN:", 1)[1].strip()}
    if "Liouville-Handshake OK" in text:
        found = re.search(r"det\(J\)=([0-9.\-]+)", text)
        return "handshake", {"det_j": float(found.group(1))} if found else {}
    if "[LIOUVILLE-GATE] reject" in text:
        found = re.search(r"det\(J\)=([0-9.\-]+)", text)
        return "liouville_reject", {"det_j": float(found.group(1))} if found else {}
    if any(token in text for token in ("[FEHLER]", "ERROR", "[SENDEFEHLER]")): return "error", {}
    return "info", {}


class AnalysisSession:
    def __init__(self, log_dir: str | os.PathLike = LOG_DIR):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session = f"sess-{secrets.token_hex(4)}-{int(time.time())}"
        self.base_path = self.log_dir / f"qfan_{self.session}.jsonl"
        self._lock = threading.Lock()
        self._rotate_index = 0
        self._bytes_written = 0
        self._fh = self._open()

    def _path(self):
        return self.base_path if not self._rotate_index else self.base_path.with_name(f"{self.base_path.stem}.{self._rotate_index}.jsonl")

    def _open(self):
        self._bytes_written = 0
        return self._path().open("a", encoding="utf-8")

    def record(self, substrate: Optional[str], text: str, extra_event: Optional[str] = None, extra_data: Optional[dict] = None):
        event, parsed = classify(text)
        if extra_event: event = extra_event
        if extra_data: parsed.update(extra_data)
        line = json.dumps({"ts": time.time(), "session": self.session, "substrate": substrate or "file",
                           "event": event, "raw": text, "parsed": parsed}, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            if self._fh.closed: return
            self._fh.write(line); self._fh.flush()
            self._bytes_written += len(line.encode("utf-8"))
            if self._bytes_written >= ROTATE_SIZE_BYTES:
                self._fh.close(); self._rotate_index += 1; self._fh = self._open()

    def close(self):
        with self._lock:
            if not self._fh.closed: self._fh.close()

    def current_file(self) -> str:
        return str(self._fh.name if not self._fh.closed else self._path())


class AnalyzerWrappedNotify:
    def __init__(self, substrate: str, session: AnalysisSession, downstream):
        self.substrate, self.session, self.downstream = substrate, session, downstream
    def __call__(self, kind, **kw):
        if kind == "log" and kw.get("text"):
            self.session.record(self.substrate, kw["text"])
        if self.downstream:
            try: self.downstream(kind, **kw)
            except Exception: pass
