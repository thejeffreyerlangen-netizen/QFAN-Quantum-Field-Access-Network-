"""
Takt-Sync — gemeinsame Phase am 98.112-Hz-Taktanker
===================================================
Nodes tauschen takt_sync-Pulse aus. Empfänger zieht seine
Slot-Phase sanft nach (Software-PLL / Kuramoto-Schritt).
"""
from __future__ import annotations

import time
from typing import Optional

FREQ_ANCHOR_HZ = 98.112
SLOT_PERIOD = 1.0 / FREQ_ANCHOR_HZ


class TaktSync:
    def __init__(self, freq_hz: float = FREQ_ANCHOR_HZ, pull: float = 0.15):
        self.period = 1.0 / float(freq_hz)
        self.freq_hz = float(freq_hz)
        self.pull = max(0.0, min(1.0, pull))  # 0=ignorieren, 1=hart übernehmen
        self.phase_offset = 0.0  # Sekunden, addiert auf lokale Zeit
        self.last_peer_slot: Optional[int] = None
        self.last_adjust = 0.0

    def local_slot(self, now: Optional[float] = None) -> int:
        t = (now if now is not None else time.time()) + self.phase_offset
        return int(t / self.period)

    def next_boundary(self, now: Optional[float] = None) -> float:
        t = (now if now is not None else time.time()) + self.phase_offset
        slots = t / self.period
        # absolute Wandzeit der nächsten Grenze
        next_local = (int(slots) + 1) * self.period
        return next_local - self.phase_offset

    def make_pulse(self, qip: str = "", name: str = "") -> dict:
        now = time.time()
        return {
            "type": "takt_sync",
            "slot": self.local_slot(now),
            "hz": self.freq_hz,
            "ts": now,
            "qip": qip,
            "from": name,
            "phase_offset": self.phase_offset,
        }

    def observe(self, pulse: dict) -> float:
        """
        Peer-Pulse verarbeiten. Rückgabe: Korrektur in Sekunden (kann 0 sein).
        """
        if pulse.get("type") != "takt_sync":
            return 0.0
        peer_slot = int(pulse.get("slot", 0))
        peer_ts = float(pulse.get("ts", time.time()))
        # Erwarteter Slot zum Peer-Zeitstempel aus unserer Sicht
        our_slot_at_peer_ts = int((peer_ts + self.phase_offset) / self.period)
        # Slot-Differenz → Zeitfehler
        delta_slots = peer_slot - our_slot_at_peer_ts
        # wrap klein halten
        if delta_slots > 1000:
            delta_slots = 0
        if delta_slots < -1000:
            delta_slots = 0
        err = delta_slots * self.period
        # sanft nachziehen
        adj = self.pull * err
        self.phase_offset += adj
        self.last_peer_slot = peer_slot
        self.last_adjust = adj
        return adj
