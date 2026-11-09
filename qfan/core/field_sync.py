"""Best-effort local software clock phase adjustment."""
from __future__ import annotations

import time
from typing import Optional

FREQ_ANCHOR_HZ = 98.112
SLOT_PERIOD = 1.0 / FREQ_ANCHOR_HZ


class TaktSync:
    def __init__(self, freq_hz: float = FREQ_ANCHOR_HZ, pull: float = .15):
        if freq_hz <= 0:
            raise ValueError("freq_hz must be positive")
        self.period = 1.0 / float(freq_hz)
        self.freq_hz = float(freq_hz)
        self.pull = max(0.0, min(1.0, pull))
        self.phase_offset = 0.0
        self.last_peer_slot: Optional[int] = None
        self.last_adjust = 0.0

    def local_slot(self, now: Optional[float] = None) -> int:
        return int(((time.time() if now is None else now) + self.phase_offset) / self.period)

    def next_boundary(self, now: Optional[float] = None) -> float:
        t = (time.time() if now is None else now) + self.phase_offset
        return (int(t / self.period) + 1) * self.period - self.phase_offset

    def make_pulse(self, qip: str = "", name: str = "") -> dict:
        now = time.time()
        return {"type": "takt_sync", "slot": self.local_slot(now), "hz": self.freq_hz,
                "ts": now, "qip": qip, "from": name, "phase_offset": self.phase_offset}

    def observe(self, pulse: dict) -> float:
        if pulse.get("type") != "takt_sync":
            return 0.0
        try:
            peer_slot = int(pulse["slot"])
            peer_ts = float(pulse["ts"])
        except (KeyError, TypeError, ValueError):
            return 0.0
        if not (self.freq_hz * .999 <= float(pulse.get("hz", self.freq_hz)) <= self.freq_hz * 1.001):
            return 0.0
        delta = peer_slot - int((peer_ts + self.phase_offset) / self.period)
        if abs(delta) > 1000:
            return 0.0
        adjustment = self.pull * delta * self.period
        self.phase_offset += adjustment
        self.last_peer_slot, self.last_adjust = peer_slot, adjustment
        return adjustment
