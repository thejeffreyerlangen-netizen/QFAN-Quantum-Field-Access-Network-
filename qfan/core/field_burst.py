"""Timing utilities for burst transmission."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

FREQ_ANCHOR_HZ = 98.112
SLOT_PERIOD = 1.0 / FREQ_ANCHOR_HZ
DEFAULT_BURST_LEN = 8
DEFAULT_FLUSH_MS = 40.0


class FieldBurstSequencer:
    def __init__(self, send_fn: Callable[[dict], Dict[str, bool]], burst_len: int = DEFAULT_BURST_LEN,
                 freq_hz: float = FREQ_ANCHOR_HZ, max_wait_ms: float = DEFAULT_FLUSH_MS,
                 on_log: Optional[Callable[[str], None]] = None, takt_sync: Any = None):
        if freq_hz <= 0:
            raise ValueError("freq_hz must be positive")
        self.send_fn = send_fn
        self.burst_len = max(1, int(burst_len))
        self.period = 1.0 / float(freq_hz)
        self.max_wait = max_wait_ms / 1000.0
        self.on_log = on_log or (lambda _text: None)
        self.takt_sync = takt_sync
        self._q: Deque[dict] = deque()
        self._lock = threading.Lock()
        self._running = True
        self._stats = {"bursts": 0, "frames": 0, "queued": 0}
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def enqueue(self, packet: dict) -> None:
        with self._lock:
            self._q.append(dict(packet))
            self._stats["queued"] += 1

    def enqueue_now(self, packet: dict) -> Dict[str, bool]:
        return self.send_fn(packet)

    def _next_slot_boundary(self) -> float:
        if self.takt_sync is not None:
            return self.takt_sync.next_boundary()
        return (int(time.time() / self.period) + 1) * self.period

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                if not self._q:
                    batch = None
                else:
                    batch = []
            if batch is None:
                time.sleep(.002)
                continue
            t0 = self._next_slot_boundary()
            delay = t0 - time.time()
            if delay > 0:
                time.sleep(min(delay, self.max_wait))
            with self._lock:
                while self._q and len(batch) < self.burst_len:
                    batch.append(self._q.popleft())
            if not batch:
                continue
            succeeded = 0
            for i, packet in enumerate(batch):
                frame = {**packet, "_burst_idx": i, "_burst_len": len(batch), "_taktanker_hz": FREQ_ANCHOR_HZ}
                try:
                    result = self.send_fn(frame)
                    succeeded += bool(any(result.values()))
                except Exception:
                    pass
                if i + 1 < len(batch):
                    wait = t0 + (i + 1) * self.period - time.time()
                    if wait > 0:
                        time.sleep(wait)
            with self._lock:
                self._stats["bursts"] += 1
                self._stats["frames"] += len(batch)
                count = self._stats["bursts"]
            self.on_log(f"[BURST] Sequenz #{count} {len(batch)} Frames @ {FREQ_ANCHOR_HZ} Hz ok={succeeded}/{len(batch)}")

    def stats(self) -> dict:
        with self._lock:
            return {**self._stats, "queue_depth": len(self._q)}

    def flush(self) -> None:
        with self._lock:
            pending = list(self._q)
            self._q.clear()
        for packet in pending:
            try:
                self.send_fn(packet)
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        self.flush()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
