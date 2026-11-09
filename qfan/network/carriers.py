"""QFAN frame carriers and framing helpers.

The adapter carrier is UDP/IP-based. These classes are prototype transports,
not secure or IP-free networking.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

QFAN_MAGIC = b"QFAN1"
MAX_FRAME = 60000
BLE_MTU = 251
BLE_HDR = 6


def encode_qfan_body(packet: dict) -> bytes:
    body = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return QFAN_MAGIC + struct.pack("!I", len(body)) + body


def decode_qfan_body(data: bytes) -> Optional[dict]:
    if len(data) < 9 or not data.startswith(QFAN_MAGIC):
        return None
    try:
        length, = struct.unpack("!I", data[5:9])
        if length > MAX_FRAME or len(data) != 9 + length:
            return None
        value = json.loads(data[9:].decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError, struct.error):
        return None


def fragment_ble(packet: dict, mtu: int = BLE_MTU, msg_id: int = 1) -> List[bytes]:
    if mtu <= BLE_HDR:
        raise ValueError("MTU must exceed fragment header")
    raw = encode_qfan_body(packet)
    chunk_size = mtu - BLE_HDR
    parts = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    if len(parts) > 255:
        raise ValueError("BLE frame exceeds 255 fragments")
    return [b"QB" + struct.pack("!HBB", msg_id & 0xFFFF, index, len(parts)) + part
            for index, part in enumerate(parts)]


class BLEReassembler:
    def __init__(self):
        self._buf: Dict[int, Dict[int, bytes]] = {}
        self._need: Dict[int, int] = {}

    def push(self, frag: bytes) -> Optional[dict]:
        if len(frag) < BLE_HDR or len(frag) > BLE_MTU or not frag.startswith(b"QB"):
            return None
        mid, idx, count = struct.unpack("!HBB", frag[2:6])
        if count == 0 or idx >= count:
            return None
        bucket = self._buf.setdefault(mid, {})
        bucket[idx] = frag[6:]
        self._need[mid] = count
        if len(bucket) != count:
            return None
        raw = b"".join(bucket[i] for i in range(count))
        del self._buf[mid]
        del self._need[mid]
        packet = decode_qfan_body(raw)
        if packet is not None:
            packet["_substrate"] = "ble"
        return packet


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
    name = "file"
    def __init__(self, mailbox: str | Path, my_name: str):
        self.root = Path(mailbox)
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "presence").mkdir(exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, data: bytes):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def send_frame(self, packet: dict) -> bool:
        target = str(packet.get("to") or packet.get("target") or "").lower().replace("qfan.de/", "").strip()
        if not target or target in (".", "..") or any(c in target for c in "/\\"):
            return False
        queue = self.root / f"{target}.queue.jsonl"
        with queue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(packet, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._atomic_write(self.root / f"{target}.slot", b"1")
        return True

    def receive_frames(self) -> List[dict]:
        queue = self.root / f"{self.my_name}.queue.jsonl"
        if not queue.exists():
            return []
        try:
            text = queue.read_text(encoding="utf-8")
            self._atomic_write(queue, b"")
            packets = []
            for line in text.splitlines():
                try:
                    packet = json.loads(line)
                    if isinstance(packet, dict):
                        packet["_substrate"] = self.name
                        packets.append(packet)
                except ValueError:
                    continue
            return packets
        except OSError:
            return []

    def publish_presence(self, payload: dict) -> None:
        body = {**payload, "name": self.my_name, "ts": time.time(), "substrate": self.name}
        self._atomic_write(self.root / "presence" / f"{self.my_name}.json", json.dumps(body).encode())

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        out, now = [], time.time()
        for path in (self.root / "presence").glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if row.get("name") != self.my_name and now - float(row.get("ts", 0)) <= max_age_sec:
                    row["_substrate"] = self.name
                    out.append(row)
            except (OSError, ValueError, TypeError):
                continue
        return out


class AdapterSubstrate(BaseSubstrate):
    """UDP broadcast carrier; uses the operating system's IP stack."""
    name = "adapter"
    def __init__(self, my_name: str, port: int = 19811):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.port = int(port)
        self._inbox: List[dict] = []
        self._lock = threading.Lock()
        self._running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", self.port))
        self.sock.settimeout(.3)
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        while self._running:
            try:
                data, _address = self.sock.recvfrom(MAX_FRAME + 9)
            except socket.timeout:
                continue
            except OSError:
                break
            packet = decode_qfan_body(data)
            if packet is None or packet.get("from") == self.my_name:
                continue
            packet["_substrate"] = self.name
            with self._lock:
                self._inbox.append(packet)

    def send_frame(self, packet: dict) -> bool:
        try:
            self.sock.sendto(encode_qfan_body(packet), ("255.255.255.255", self.port))
            return True
        except OSError:
            return False

    def receive_frames(self) -> List[dict]:
        with self._lock:
            packets, self._inbox = self._inbox, []
            return packets

    def publish_presence(self, payload: dict) -> None:
        self.send_frame({**payload, "type": "presence", "from": self.my_name,
                         "name": self.my_name, "ts": time.time(), "substrate": self.name})

    def close(self) -> None:
        self._running = False
        self.sock.close()
        self._thread.join(timeout=.5)


class BLESubstrate(BaseSubstrate):
    """Fragmentation test adapter only; no BLE radio transport is implemented."""
    name = "ble"
    def __init__(self, my_name: str, mtu: int = BLE_MTU):
        self.my_name, self.mtu = my_name, mtu
        self.available = False
        self._inbox: List[dict] = []
        self._reasm = BLEReassembler()
        self._seq = 1

    def send_frame(self, packet: dict) -> bool:
        try:
            fragments = fragment_ble(packet, self.mtu, self._seq)
        except ValueError:
            return False
        self._seq = (self._seq + 1) & 0xFFFF or 1
        for fragment in fragments:
            decoded = self._reasm.push(fragment)
            if decoded is not None and decoded.get("to") == self.my_name:
                self._inbox.append(decoded)
        return True

    def receive_frames(self) -> List[dict]:
        result, self._inbox = self._inbox, []
        return result


class SubstrateBroker:
    def __init__(self):
        self.score = {"file": 1.0, "adapter": 1.0, "ble": .2}
    def report(self, name: str, ok: bool):
        self.score[name] = min(3.0, self.score.get(name, 1.0) + .05) if ok else max(.05, self.score.get(name, 1.0) * .85)
    def order(self, names):
        return sorted(names, key=lambda name: self.score.get(name, 0.0), reverse=True)


class MultiSubstrateBus:
    def __init__(self, my_name: str, mailbox: str | Path, substrates: Optional[List[str]] = None,
                 adapter_port: int = 19811):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.carriers: Dict[str, BaseSubstrate] = {}
        self.broker = SubstrateBroker()
        for name in substrates or ["file", "adapter"]:
            try:
                if name == "file": self.carriers[name] = FileSubstrate(mailbox, self.my_name)
                elif name == "adapter": self.carriers[name] = AdapterSubstrate(self.my_name, adapter_port)
                elif name == "ble": self.carriers[name] = BLESubstrate(self.my_name)
            except OSError:
                continue

    def active_names(self) -> List[str]:
        return [name for name, carrier in self.carriers.items() if name != "ble" or carrier.available]

    def send(self, packet: dict) -> Dict[str, bool]:
        results = {}
        addressed = bool(str(packet.get("to") or packet.get("target") or "").strip())
        for name in self.broker.order(list(self.carriers)):
            carrier = self.carriers[name]
            if name == "ble" and not carrier.available:
                results[name] = False
                continue
            if name == "file" and not addressed and packet.get("type") in ("takt_sync", "presence"):
                continue
            try: ok = bool(carrier.send_frame(packet))
            except Exception: ok = False
            results[name] = ok
            self.broker.report(name, ok)
        return results

    def hardware(self) -> List[str]:
        return [f"file → Speicher {c.root}" if n == "file" else
                f"adapter → UDP/IP Port {c.port}" if n == "adapter" else
                "ble → Fragmentierungstest (kein Funktransport)" for n, c in self.carriers.items()]

    def receive(self) -> List[dict]:
        result = []
        for carrier in self.carriers.values():
            try: result.extend(carrier.receive_frames())
            except Exception: continue
        return result

    def publish_presence(self, payload: dict) -> None:
        for carrier in self.carriers.values():
            try: carrier.publish_presence(payload)
            except Exception: continue

    def scan_presence(self, max_age_sec: float = 8.0) -> List[dict]:
        seen, result = set(), []
        for carrier in self.carriers.values():
            for peer in carrier.scan_presence(max_age_sec):
                if peer.get("name") and peer["name"] not in seen:
                    seen.add(peer["name"]); result.append(peer)
        return result

    def close(self) -> None:
        for carrier in self.carriers.values():
            try: carrier.close()
            except Exception: continue
