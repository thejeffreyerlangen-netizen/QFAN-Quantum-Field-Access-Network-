#!/usr/bin/env python3
"""
QFAN Field-Burst — Taktanker-gekoppelte Burst-Sequenz ins Substrat
==================================================================
Statt Einzel-Frames: Pakete werden im Burst-Fenster gesammelt und
phasenstarr am 98.112-Hz-Taktanker ins Substrat gehoben.

Ziel: höhere effektive Feldrate, kohärente Einschreibung, weniger
Jitter zwischen Host und Client.

Zeitbasis:
  T = 1 / 98.112 s  ≈  10.192 ms  (ein Taktanker-Slot)
  Burst = N Slots hintereinander (default N=8)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Any

FREQ_ANCHOR_HZ = 98.112
SLOT_PERIOD = 1.0 / FREQ_ANCHOR_HZ  # ~10.192 ms
DEFAULT_BURST_LEN = 8               # Frames pro Burst
DEFAULT_FLUSH_MS = 40.0             # max. Wartezeit bis Zwangs-Flush


class FieldBurstSequencer:
    """
    Hebt QFAN-Pakete in Burst-Sequenzen ins Multi-Substrat.

    send(packet)  → queue
    Hintergrund-Thread:
      - wartet auf Taktanker-Phase (slot boundary)
      - feuert bis zu burst_len Frames schnell hintereinander
      - jeder Frame im Abstand SLOT_PERIOD (Feld-kohärent)
    """

    def __init__(
        self,
        send_fn: Callable[[dict], Dict[str, bool]],
        burst_len: int = DEFAULT_BURST_LEN,
        freq_hz: float = FREQ_ANCHOR_HZ,
        max_wait_ms: float = DEFAULT_FLUSH_MS,
        on_log: Optional[Callable[[str], None]] = None,
        takt_sync: Any = None,
    ):
        self.send_fn = send_fn
        self.burst_len = max(1, int(burst_len))
        self.period = 1.0 / float(freq_hz)
        self.max_wait = max_wait_ms / 1000.0
        self.on_log = on_log or (lambda _t: None)
        self.takt_sync = takt_sync

        self._q: Deque[dict] = deque()
        self._lock = threading.Lock()
        self._running = True
        self._stats = {
            "bursts": 0,
            "frames": 0,
            "queued": 0,
        }
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def enqueue(self, packet: dict) -> None:
        """Paket in die Burst-Warteschlange (nicht sofort senden)."""
        with self._lock:
            self._q.append(dict(packet))
            self._stats["queued"] += 1

    def enqueue_now(self, packet: dict) -> Dict[str, bool]:
        """Sofort-Einzel-Frame (z.B. kritischer Handshake) — umgeht Burst."""
        return self.send_fn(packet)

    def _next_slot_boundary(self) -> float:
        """Nächste absolute Zeit auf dem 98.112-Hz-Raster (inkl. Takt-Sync-Offset)."""
        if self.takt_sync is not None:
            return self.takt_sync.next_boundary()
        now = time.time()
        slots = now / self.period
        return (int(slots) + 1) * self.period

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                n = len(self._q)
            if n == 0:
                time.sleep(0.002)
                continue

            # Burst starten: an Taktanker ausrichten
            t0 = self._next_slot_boundary()
            delay = t0 - time.time()
            if delay > 0:
                time.sleep(min(delay, self.max_wait))

            batch: List[dict] = []
            with self._lock:
                while self._q and len(batch) < self.burst_len:
                    batch.append(self._q.popleft())

            if not batch:
                continue

            # Burst-Sequenz: Frames im Taktanker-Abstand
            ok_total = 0
            for i, pkt in enumerate(batch):
                pkt = dict(pkt)
                pkt["_burst_idx"] = i
                pkt["_burst_len"] = len(batch)
                pkt["_taktanker_hz"] = FREQ_ANCHOR_HZ
                try:
                    res = self.send_fn(pkt)
                    if any(res.values()):
                        ok_total += 1
                except Exception:
                    pass
                if i + 1 < len(batch):
                    # nächster Slot
                    target = t0 + (i + 1) * self.period
                    wait = target - time.time()
                    if wait > 0:
                        time.sleep(wait)

            self._stats["bursts"] += 1
            self._stats["frames"] += len(batch)
            self.on_log(
                f"[BURST] Sequenz #{self._stats['bursts']}  "
                f"{len(batch)} Frames @ {FREQ_ANCHOR_HZ} Hz  ok={ok_total}/{len(batch)}"
            )

    def stats(self) -> dict:
        with self._lock:
            qlen = len(self._q)
        return {**self._stats, "queue_depth": qlen}

    def flush(self) -> None:
        """Alles Sofort leeren (ohne Takt-Warten) — Shutdown."""
        with self._lock:
            batch = list(self._q)
            self._q.clear()
        for pkt in batch:
            try:
                self.send_fn(pkt)
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        self.flush()
