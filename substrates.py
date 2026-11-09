#!/usr/bin/env python3
"""
QFAN Substrate-Schicht (Schicht 1)
==================================
Nur physische Träger für QFAN-Frames (Qubits/Pakete).
Anwendungslogik: kein IP-Stack. Substrate = physische Blindträger.

  file     – Slot-Mailbox (gemeinsames Verzeichnis)
  adapter  – Netzwerkadapter als Blindträger (Frames mit QIP im Payload)
  ble      – Bluetooth LE als Blindträger (optional, falls bleak installiert)

Jeder Empfang geht danach durch Liouville/Q-DNS/Field-DHCP in der App —
das Substrat entscheidet NICHT über Identität oder Freigabe.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

QFAN_MAGIC = b"QFAN1"
MAX_FRAME = 60000
BLE_MTU = 251
BLE_HDR = 6  # QB + msg_id(2) + idx(1) + count(1)


def encode_qfan_body(packet: dict) -> bytes:
    body = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return QFAN_MAGIC + struct.pack("!I", len(body)) + body


def decode_qfan_body(data: bytes) -> Optional[dict]:
    if not data.startswith(QFAN_MAGIC):
        return None
    try:
        (length,) = struct.unpack("!I", data[5:9])
        body = data[9 : 9 + length]
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def fragment_ble(packet: dict, mtu: int = BLE_MTU, msg_id: int = 1) -> List[bytes]:
    """Schneidet einen QFAN-Frame in BLE-Stücke <= mtu."""
    raw = encode_qfan_body(packet)
    chunk = max(1, mtu - BLE_HDR)
    parts = [raw[i : i + chunk] for i in range(0, len(raw), chunk)]
    if len(parts) > 255:
        raise ValueError("BLE-Frame zu lang für 255 Stücke")
    out = []
    mid = msg_id & 0xFFFF
    n = len(parts)
    for i, piece in enumerate(parts):
        frag = b"QB" + struct.pack("!HBB", mid, i, n) + piece
        if len(frag) > mtu:
            raise ValueError("Fragment über MTU")
        out.append(frag)
    return out


class BLEReassembler:
    def __init__(self):
        self._buf: Dict[int, Dict[int, bytes]] = {}
        self._need: Dict[int, int] = {}

    def push(self, frag: bytes) -> Optional[dict]:
        if len(frag) < BLE_HDR or not frag.startswith(b"QB"):
            return None
        mid, idx, n = struct.unpack("!HBB", frag[2:6])
        piece = frag[6:]
        bucket = self._buf.setdefault(mid, {})
        bucket[idx] = piece
        self._need[mid] = n
        if len(bucket) < n:
            return None
        raw = b"".join(bucket[i] for i in range(n))
        del self._buf[mid]
        del self._need[mid]
        pkt = decode_qfan_body(raw)
        if pkt is not None:
            pkt["_substrate"] = "ble"
        return pkt


class BaseSubstrate:
    name = "base"

    def send_frame(self, packet: dict) -> bool:
        raise NotImplementedError

    def receive_frames(self) -> List[dict]:
        raise NotImplementedError

    def publish_presence(self, payload: dict) -> None:
        pass

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        return []

    def close(self) -> None:
        pass


class FileSubstrate(BaseSubstrate):
    """Slot-Mailbox: atomare Queues im Feld-Verzeichnis."""

    name = "file"

    def __init__(self, mailbox: str | Path, my_name: str):
        self.root = Path(mailbox)
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "presence").mkdir(exist_ok=True)

    def _atomic_write(self, path: Path, data: bytes):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def send_frame(self, packet: dict) -> bool:
        target = str(packet.get("to") or packet.get("target") or "").lower()
        target = target.replace("qfan.de/", "").strip()
        if not target:
            return False
        queue = self.root / f"{target}.queue.jsonl"
        signal = self.root / f"{target}.slot"
        line = json.dumps(packet, ensure_ascii=False) + "\n"
        with open(queue, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self._atomic_write(signal, b"1")
        return True

    def receive_frames(self) -> List[dict]:
        queue = self.root / f"{self.my_name}.queue.jsonl"
        signal = self.root / f"{self.my_name}.slot"
        packets: List[dict] = []
        if not queue.exists():
            if signal.exists():
                try:
                    signal.unlink()
                except OSError:
                    pass
            return packets
        try:
            text = queue.read_text(encoding="utf-8")
            self._atomic_write(queue, b"")
            if signal.exists():
                try:
                    signal.unlink()
                except OSError:
                    pass
            for line in text.splitlines():
                if line.strip():
                    pkt = json.loads(line)
                    pkt["_substrate"] = "file"
                    packets.append(pkt)
        except Exception:
            pass
        return packets

    def publish_presence(self, payload: dict) -> None:
        path = self.root / "presence" / f"{self.my_name}.json"
        body = dict(payload)
        body["name"] = self.my_name
        body["ts"] = time.time()
        body["substrate"] = "file"
        self._atomic_write(path, json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        now = time.time()
        out = []
        pres = self.root / "presence"
        if not pres.exists():
            return out
        for f in pres.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if now - float(data.get("ts", 0)) > max_age_sec:
                    continue
                if data.get("name") == self.my_name:
                    continue
                data["_substrate"] = "file"
                out.append(data)
            except Exception:
                continue
        return out


class AdapterSubstrate(BaseSubstrate):
    """
    Netzwerkadapter als physischer Blindträger.

    Der Adapter trägt nur Bytes. Im Frame steckt QFAN (QIP, Name, q/p).
    Anwendungslogik adressiert niemals über IP — nur über QIP/Name.
    OS stellt lediglich den Draht/Funkkanal bereit.
    """

    name = "adapter"

    def __init__(self, my_name: str, port: int = 19811):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.port = port
        self._inbox: List[dict] = []
        self._lock = threading.Lock()
        self._running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        self.sock.bind(("", port))
        self.sock.settimeout(0.3)
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        while self._running:
            try:
                data, _addr = self.sock.recvfrom(MAX_FRAME)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                continue
            pkt = self._decode(data)
            if not pkt:
                continue
            # eigene Echo-Frames verwerfen
            if pkt.get("from") == self.my_name:
                continue
            pkt["_substrate"] = "adapter"
            with self._lock:
                self._inbox.append(pkt)

    def _encode(self, packet: dict) -> bytes:
        body = json.dumps(packet, ensure_ascii=False).encode("utf-8")
        return QFAN_MAGIC + struct.pack("!I", len(body)) + body

    def _decode(self, data: bytes) -> Optional[dict]:
        if not data.startswith(QFAN_MAGIC):
            return None
        try:
            (length,) = struct.unpack("!I", data[5:9])
            body = data[9 : 9 + length]
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def send_frame(self, packet: dict) -> bool:
        try:
            frame = self._encode(packet)
            # Broadcast auf dem Adapter — Ziel steht als QIP/Name im Payload
            self.sock.sendto(frame, ("<broadcast>", self.port))
            return True
        except OSError:
            try:
                self.sock.sendto(frame, ("255.255.255.255", self.port))
                return True
            except OSError:
                return False

    def receive_frames(self) -> List[dict]:
        with self._lock:
            out = list(self._inbox)
            self._inbox.clear()
        return out

    def publish_presence(self, payload: dict) -> None:
        body = dict(payload)
        body["type"] = "presence"
        body["from"] = self.my_name
        body["name"] = self.my_name
        body["ts"] = time.time()
        body["substrate"] = "adapter"
        self.send_frame(body)

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        # Presence kommt als Frames rein und wird in receive_frames behandelt
        return []

    def close(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass


class BLESubstrate(BaseSubstrate):
    """
    BLE-Blindträger. Frames werden in Stücke <= 251 Byte geschnitten.
    Ohne Funk-Stack bleibt die Funke aus; die Paketierung ist trotzdem da.
    """

    name = "ble"

    def __init__(self, my_name: str, mtu: int = BLE_MTU):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.mtu = mtu
        self.available = False
        self._reasm = BLEReassembler()
        self._inbox: List[dict] = []
        self._seq = 1
        try:
            import bleak  # noqa: F401
            self.available = False
        except ImportError:
            self.available = False

    def send_frame(self, packet: dict) -> bool:
        try:
            frags = fragment_ble(packet, mtu=self.mtu, msg_id=self._seq)
        except ValueError:
            return False
        self._seq = (self._seq + 1) & 0xFFFF or 1
        # Lokale Gegenstelle: Stücke sofort wieder zusammensetzen (Funk-Schleife).
        for frag in frags:
            pkt = self._reasm.push(frag)
            if pkt is not None and pkt.get("to") == self.my_name:
                self._inbox.append(pkt)
        return True

    def receive_frames(self) -> List[dict]:
        out = list(self._inbox)
        self._inbox.clear()
        return out




class SubstrateBroker:
    """Wählt Träger nach einfacher Resonanz-Heuristik (Erfolg/Fehler)."""

    def __init__(self):
        self.score = {"file": 1.0, "adapter": 1.0, "ble": 0.2}

    def report(self, name: str, ok: bool):
        if name not in self.score:
            self.score[name] = 1.0
        if ok:
            self.score[name] = min(3.0, self.score[name] + 0.05)
        else:
            self.score[name] = max(0.05, self.score[name] * 0.85)

    def order(self, names):
        return sorted(names, key=lambda n: self.score.get(n, 0.0), reverse=True)


class MultiSubstrateBus:
    """
    Fächer: sendet auf alle aktiven Substrate, sammelt Empfang.
    Identität/Freigabe bleibt außerhalb (Liouville in der App).
    """

    def __init__(
        self,
        my_name: str,
        mailbox: str | Path,
        substrates: Optional[List[str]] = None,
        adapter_port: int = 19811,
    ):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        want = substrates or ["file", "adapter"]
        self.carriers: Dict[str, BaseSubstrate] = {}
        self.broker = SubstrateBroker()

        if "file" in want:
            self.carriers["file"] = FileSubstrate(mailbox, self.my_name)
        if "adapter" in want:
            try:
                self.carriers["adapter"] = AdapterSubstrate(self.my_name, port=adapter_port)
            except OSError:
                pass
        if "ble" in want:
            ble = BLESubstrate(self.my_name)
            self.carriers["ble"] = ble

    def active_names(self) -> List[str]:
        names = []
        for k, c in self.carriers.items():
            if k == "ble" and not getattr(c, "available", False):
                continue
            names.append(k)
        return names

    def send(self, packet: dict) -> Dict[str, bool]:
        results = {}
        names = self.broker.order(list(self.carriers.keys()))
        addressed = bool(str(packet.get("to") or packet.get("target") or "").strip())
        for name in names:
            carrier = self.carriers[name]
            if name == "ble" and not getattr(carrier, "available", False):
                results[name] = False
                continue
            # File-Slot braucht ein Ziel. Broadcast-Pulse (Takt) gehen nur über Funk/Adapter.
            if name == "file" and not addressed and packet.get("type") in ("takt_sync", "presence"):
                continue
            try:
                ok = bool(carrier.send_frame(packet))
            except Exception:
                ok = False
            results[name] = ok
            self.broker.report(name, ok)
        return results

    def hardware(self) -> List[str]:
        """Was die Hardware gerade wirklich trägt."""
        lines = []
        for name, carrier in self.carriers.items():
            if name == "file":
                lines.append(f"file → Speicher {carrier.root}")
            elif name == "adapter":
                lines.append(f"adapter → Netzwerkkarte, Feld-Port {carrier.port}")
            elif name == "ble":
                state = "Funkchip bereit" if getattr(carrier, "available", False) else "kein BLE-Stack"
                lines.append(f"ble → {state}")
        return lines

    def receive(self) -> List[dict]:
        out: List[dict] = []
        for carrier in self.carriers.values():
            try:
                out.extend(carrier.receive_frames())
            except Exception:
                continue
        return out

    def publish_presence(self, payload: dict) -> None:
        for carrier in self.carriers.values():
            try:
                carrier.publish_presence(payload)
            except Exception:
                pass

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        out: List[dict] = []
        seen = set()
        for carrier in self.carriers.values():
            try:
                for p in carrier.scan_presence(max_age_sec):
                    key = p.get("name")
                    if key and key not in seen:
                        seen.add(key)
                        out.append(p)
            except Exception:
                continue
        return out

    def close(self) -> None:
        for carrier in self.carriers.values():
            try:
                carrier.close()
            except Exception:
                pass
