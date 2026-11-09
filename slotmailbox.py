"""
Slot-Mailbox-Substrat — atomare Einzel-Slots im gemeinsamen Feld-Verzeichnis.

Jeder Frame wird als eigene Datei `<ziel>.<zeitstempel_ns>.slot` abgelegt (erst `.tmp`, dann
os.replace). Der Empfänger liest seine Slots in Zeitreihenfolge und löscht sie. Dadurch gibt es
keine halb geschriebenen Frames und keine Überschreibungen, auch nicht bei hoher Frequenz.

Funktioniert über jeden gemeinsamen Ordner: lokal, NAS/SMB/NFS oder ein per Syncthing,
Nextcloud, OneDrive o. Ä. synchronisierter Ordner (so auch zwischen verschiedenen Netzen,
ohne offenen Port).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List

from qfan.substrates import BaseSubstrate

STALE_CORRUPT_SEC = 10.0


class SlotMailbox(BaseSubstrate):
    name = "file"

    def __init__(self, mailbox: str | Path, my_name: str):
        self.root = Path(mailbox)
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.root.mkdir(parents=True, exist_ok=True)
        self._last_ns = 0

    def _next_ns(self) -> int:
        ns = time.time_ns()
        if ns <= self._last_ns:
            ns = self._last_ns + 1
        self._last_ns = ns
        return ns

    def send_frame(self, packet: dict) -> bool:
        target = str(packet.get("to") or packet.get("target") or "").lower().replace("qfan.de/", "").strip()
        if not target or "/" in target or "\\" in target or target.startswith("."):
            return False
        ns = self._next_ns()
        final = self.root / f"{target}.{ns}.slot"
        tmp = self.root / f".{target}.{ns}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(json.dumps(packet, ensure_ascii=False).encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
            return True
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            return False

    def receive_frames(self) -> List[dict]:
        out: List[dict] = []
        try:
            slots = sorted(self.root.glob(f"{self.my_name}.*.slot"), key=lambda p: p.name)
        except OSError:
            return out
        now = time.time()
        for path in slots:
            try:
                raw = path.read_bytes()
            except OSError:
                continue                              # wird gerade synchronisiert: später erneut
            try:
                pkt = json.loads(raw.decode("utf-8"))
                if not isinstance(pkt, dict):
                    raise ValueError("kein Objekt")
            except ValueError:
                try:                                  # unvollständige Sync-Datei erst nach Frist verwerfen
                    if now - path.stat().st_mtime > STALE_CORRUPT_SEC:
                        path.unlink()
                except OSError:
                    pass
                continue
            try:
                path.unlink()
            except OSError:
                continue                              # nicht löschbar: nicht doppelt zustellen
            pkt["_substrate"] = "file"
            out.append(pkt)
        return out
