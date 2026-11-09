#!/usr/bin/env python3
"""QFAN Analyzer — strukturiertes Hintergrund-Logging für den Feld-Stack.

Jedes Log-Event wird mit Substrat-Tag als JSONL geschrieben.
Thread-safe, Rotation bei 50 MB.

Format pro Zeile:
{
  "ts": 1730000000.123,
  "session": "sess-...",
  "substrate": "file" | "rawl2" | ...,
  "event": "send" | "recv" | "handshake" | "dhcp" | "liouville_reject" | ...,
  "raw": "<Original-Text>",
  "parsed": { ... }
}
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Optional

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "qfan_logs"))
ROTATE_SIZE_BYTES = 50 * 1024 * 1024

# --- Parser für QFAN-Field Log-Zeilen ---
RE_RECV = re.compile(
    r"Empfang von (?:qfan\.de/)?(?P<sender>[\w.\-]+):\s*(?P<text>.*)$"
)
RE_SEND = re.compile(
    r"Du \[(?:qfan\.de/)?(?P<from>[\w.\-/]+)\]:\s*(?P<text>.*)$"
)
RE_HANDSHAKE_OK = re.compile(
    r"\[HANDSHAKE\].*?(?:qfan\.de/)?(?P<node>[\w.\-]+).*?LOCKED.*?det\(J\)=(?P<det>[0-9.\-]+)",
    re.I,
)
RE_LIOUVILLE_OK = re.compile(
    r"Liouville-Handshake OK det\(J\)=(?P<det>[0-9.\-]+)",
    re.I,
)
RE_LIOUVILLE_FAIL = re.compile(
    r"LOCKDOWN:\s*(?P<err>.*)$",
    re.I,
)
RE_DHCP = re.compile(
    r"\[FIELD-DHCP\] Node online:\s*(?P<url>\S+)\s*→\s*(?P<node_id>\S+)\s*(?P<qip>QIP-[\w\-]+)?",
    re.I,
)
RE_QIP = re.compile(r"QIP:\s*(?P<qip>QIP-[\dA-Fa-f\-]+)")
RE_MATRIX = re.compile(
    r"Matrix-Lease:\s*(?P<node_id>NODE-\d+)\s+Helix\s+(?P<helix>\d+)",
    re.I,
)
RE_TORSION = re.compile(
    r"\[E_res\(t\)\].*?Residuum:\s*(?P<res>[0-9.]+)",
    re.I,
)
RE_EMPFANGEN_LEGACY = re.compile(
    r"\[EMPFANGEN\] von (?P<sender>QIP-[\dA-F\-]+) \| "
    r"(?P<text>.*?) \| Qubit (?P<qubit>\d+) \| "
    r"det\(J\)=(?P<det>[0-9.\-]+)",
    re.I,
)
RE_SENDEN_LEGACY = re.compile(
    r"\[SENDEN\] Qubit (?P<qubit>\d+) -> (?P<target>QIP-[\dA-F\-]+)",
    re.I,
)
RE_QGATE_REJECT = re.compile(r"\[QUBIT-GATE\] reject.*?‖ψ‖²=(?P<norm>[0-9.]+)")
RE_LIOUVILLE_REJECT = re.compile(
    r"\[LIOUVILLE-GATE\] reject det\(J\)=(?P<det>[0-9.\-]+)"
)


def classify(text: str) -> tuple:
    """(event_type, parsed_dict) — best-effort."""
    m = RE_RECV.search(text)
    if m:
        return "recv", {"sender": m["sender"], "msg_text": m["text"]}
    m = RE_SEND.search(text)
    if m:
        return "send", {"from": m["from"], "msg_text": m["text"]}
    m = RE_HANDSHAKE_OK.search(text)
    if m:
        return "handshake", {"node": m["node"], "det_j": float(m["det"])}
    m = RE_LIOUVILLE_OK.search(text)
    if m:
        return "handshake", {"det_j": float(m["det"])}
    m = RE_LIOUVILLE_FAIL.search(text)
    if m:
        return "liouville_reject", {"error": m["err"]}
    m = RE_DHCP.search(text)
    if m:
        return "dhcp", {
            "url": m["url"],
            "node_id": m["node_id"],
            "qip": m.group("qip"),
        }
    m = RE_MATRIX.search(text)
    if m:
        return "dhcp", {"node_id": m["node_id"], "helix_slot": int(m["helix"])}
    m = RE_QIP.search(text)
    if m and "QIP:" in text[:20]:
        return "info", {"qip": m["qip"]}
    m = RE_TORSION.search(text)
    if m:
        return "torsion", {"residuum": float(m["res"])}
    m = RE_EMPFANGEN_LEGACY.search(text)
    if m:
        return "recv", {
            "sender": m["sender"],
            "msg_text": m["text"],
            "qubit_id": int(m["qubit"]),
            "det_j": float(m["det"]),
        }
    m = RE_SENDEN_LEGACY.search(text)
    if m:
        return "send", {"target": m["target"], "qubit_id": int(m["qubit"])}
    m = RE_QGATE_REJECT.search(text)
    if m:
        return "qgate_reject", {"norm_sq": float(m["norm"])}
    m = RE_LIOUVILLE_REJECT.search(text)
    if m:
        return "liouville_reject", {"det_j": float(m["det"])}
    if any(x in text for x in ("[FEHLER]", "[WATCHER ERROR]", "[SENDEFEHLER]", "ERROR")):
        return "error", {}
    return "info", {}


class AnalysisSession:
    def __init__(self, log_dir: str = LOG_DIR):
        os.makedirs(log_dir, exist_ok=True)
        self.log_dir = log_dir
        self.session = f"sess-{secrets.token_hex(4)}-{int(time.time())}"
        self.base_path = os.path.join(log_dir, f"qfan_{self.session}.jsonl")
        self._lock = threading.Lock()
        self._fh = None
        self._bytes_written = 0
        self._rotate_index = 0
        self._open()

    def _open(self):
        path = (
            self.base_path
            if self._rotate_index == 0
            else self.base_path.replace(".jsonl", f".{self._rotate_index}.jsonl")
        )
        self._fh = open(path, "a", encoding="utf-8")
        self._bytes_written = 0

    def _rotate(self):
        try:
            self._fh.close()
        except Exception:
            pass
        self._rotate_index += 1
        self._open()

    def record(
        self,
        substrate: Optional[str],
        text: str,
        extra_event: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ):
        event, parsed = classify(text)
        if extra_event:
            event = extra_event
        if extra_data:
            parsed.update(extra_data)
        entry = {
            "ts": time.time(),
            "session": self.session,
            "substrate": substrate or "file",
            "event": event,
            "raw": text,
            "parsed": parsed,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            try:
                self._fh.write(line)
                self._fh.flush()
                self._bytes_written += len(line.encode("utf-8"))
                if self._bytes_written >= ROTATE_SIZE_BYTES:
                    self._rotate()
            except OSError:
                pass

    def close(self):
        with self._lock:
            try:
                self._fh.close()
            except Exception:
                pass

    def current_file(self) -> str:
        return self._fh.name if self._fh else self.base_path


class AnalyzerWrappedNotify:
    """Wrappt notify(kind, **kw) und loggt substrate-getaggt."""

    def __init__(self, substrate: str, session: AnalysisSession, downstream):
        self.substrate = substrate
        self.session = session
        self.downstream = downstream

    def __call__(self, kind, **kw):
        text = kw.get("text", "") if kind == "log" else ""
        if kind == "log" and text:
            self.session.record(self.substrate, text)
        if self.downstream:
            try:
                self.downstream(kind, **kw)
            except Exception:
                pass
