"""WORM-Ledger — append-only SHA-256-Kette, persistent (JSONL) und prüfbar."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple


class WormLedger:
    GENESIS = "QFAN GENESIS BLOCK"

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self.chain: List[dict] = []
        self._lock = threading.RLock()
        self.loaded_ok = True
        if self.path and self.path.exists():
            self._load()
        if not self.chain:
            self._append_block("GENESIS", self.GENESIS)

    @staticmethod
    def _hash(index: int, ts: float, event: str, data: str, prev: str) -> str:
        raw = f"{index}|{ts!r}|{event}|{data}|{prev}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load(self) -> None:
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.chain.append(json.loads(line))
        except (OSError, ValueError):
            self.loaded_ok = False
        ok, _ = self.verify_integrity()
        if not ok:
            self.loaded_ok = False

    def _append_block(self, event: str, data: str) -> dict:
        prev = self.chain[-1]["hash"] if self.chain else "0" * 64
        index = len(self.chain)
        ts = time.time()
        block = {"index": index, "ts": ts, "event": event, "data": data, "prev": prev,
                 "hash": self._hash(index, ts, event, data, prev)}
        self.chain.append(block)
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(block, ensure_ascii=False) + "\n")
                    fh.flush()
            except OSError:
                pass
        return block

    def record(self, event: str, data: str = "") -> dict:
        with self._lock:
            return self._append_block(str(event), str(data))

    def verify_integrity(self) -> Tuple[bool, Optional[int]]:
        """(True, None) wenn die Kette lückenlos stimmt, sonst (False, Index des ersten fehlerhaften Blocks)."""
        with self._lock:
            prev = "0" * 64
            for i, b in enumerate(self.chain):
                try:
                    ok = (b["index"] == i and b["prev"] == prev
                          and b["hash"] == self._hash(i, b["ts"], b["event"], b["data"], b["prev"]))
                except KeyError:
                    ok = False
                if not ok:
                    return False, i
                prev = b["hash"]
            return True, None

    def __len__(self) -> int:
        return len(self.chain)

    def tail(self, n: int = 10) -> List[dict]:
        with self._lock:
            return list(self.chain[-n:])
