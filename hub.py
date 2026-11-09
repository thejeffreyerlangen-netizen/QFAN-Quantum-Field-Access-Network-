"""
Hub-Substrat — Blindträger für Verbindungen über verschiedene Netze.

Der Host lauscht auf einem UDP-Port. Clients senden ihre Frames dorthin; der Host lernt aus
jedem Frame die Rückroute (Name → Adresse) und antwortet über dieselbe Verbindung. Dadurch
brauchen Clients hinter NAT/Router keine Portfreigabe. Nur der Host muss erreichbar sein
(Portfreigabe, Server oder VPN). Das Substrat trägt nur Bytes; Freigabe entscheidet das Feld.

  Host:    HubSubstrate(name, role="host", port=19812)
  Client:  HubSubstrate(name, role="client", hub_addr="203.0.113.5:19812")
           hub_addr="auto" (oder leer) sucht den Host per Broadcast im lokalen Netz.
"""
from __future__ import annotations

import socket
import threading
from typing import Dict, List, Optional, Tuple

from qfan.substrates import MAX_FRAME, BaseSubstrate, decode_qfan_body, encode_qfan_body

DEFAULT_HUB_PORT = 19812


def parse_addr(text: str, default_port: int = DEFAULT_HUB_PORT) -> Tuple[str, int]:
    text = text.strip()
    if text.count(":") == 1:
        host, port = text.split(":")
        return host.strip(), int(port)
    return text, default_port


class HubSubstrate(BaseSubstrate):
    name = "hub"

    def __init__(self, my_name: str, role: str = "client", hub_addr: Optional[str] = None,
                 port: int = DEFAULT_HUB_PORT, host_name: str = "nexus"):
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.role = role
        self.port = port
        self.host_name = host_name
        self.routes: Dict[str, tuple] = {}
        self.host_addr: Optional[tuple] = None
        self._inbox: List[dict] = []
        self._lock = threading.Lock()
        self._running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if role == "host":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("", port))
        else:
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass
            self.sock.bind(("", 0))
            if hub_addr and hub_addr.strip().lower() != "auto":
                self.host_addr = parse_addr(hub_addr, port)
        self.sock.settimeout(0.3)
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        while self._running:
            try:
                data, addr = self.sock.recvfrom(MAX_FRAME)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                continue
            pkt = decode_qfan_body(data)
            if not isinstance(pkt, dict):
                continue
            sender = str(pkt.get("from", "")).lower()
            if not sender or sender == self.my_name:
                continue
            if self.role == "host":
                self.routes[sender] = addr
            elif sender == self.host_name:
                self.host_addr = addr
            pkt["_substrate"] = "hub"
            with self._lock:
                self._inbox.append(pkt)

    def send_frame(self, packet: dict) -> bool:
        try:
            data = encode_qfan_body(packet)
            if len(data) > MAX_FRAME:
                return False
            if self.role == "host":
                addr = self.routes.get(str(packet.get("to", "")).lower())
                if not addr:
                    return False
            else:
                addr = self.host_addr or ("255.255.255.255", self.port)
            self.sock.sendto(data, addr)
            return True
        except OSError:
            return False

    def receive_frames(self) -> List[dict]:
        with self._lock:
            out, self._inbox = self._inbox, []
        return out

    def close(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass
