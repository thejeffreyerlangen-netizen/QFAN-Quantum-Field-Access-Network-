"""
QFAN Field Engine — Host (Master/Server) und Client auf dem Feld-Bus.
=====================================================================
Hub-and-Spoke: Clients docken an den Host an, der Host vergibt Field-DHCP-Slots, hält die
Presence, leitet Nachrichten weiter, verwaltet den Vault und führt das WORM-Ledger.

Jeder eingehende Frame läuft durch das Feld-Gate (Liouville, EQ1–EQ5, Residuum/Torsion),
unabhängig vom Substrat. Substrate (file, hub, adapter, ble) tragen nur Bytes.

Ereignisse für die Oberfläche (self.events, Tupel):
  ("log", text)                         ("online", name, info, initial)    ("offline", name)
  ("connected", info)  [Client]         ("host_lost",)  [Client]           ("denied", reason)
  ("msg", origin, text, dest, ts)       ("files", [{name,size}])           ("file_done", name, path)
  ("file_error", name, reason)          ("file_progress", name, done, total)
"""
from __future__ import annotations

import base64
import hashlib
import queue
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from qfan.field_dhcp import FieldDHCP
from qfan.field_sync import TaktSync
from qfan.hub import DEFAULT_HUB_PORT, HubSubstrate
from qfan.ledger import WormLedger
from qfan.qdns import PREFIX, QDNS
from qfan.qfan_core import QFANCore
from qfan.slotmailbox import SlotMailbox
from qfan.substrates import MultiSubstrateBus
from qfan.telemetry import Telemetry
from qfan.vault import Vault, safe_name

NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
CHUNK_FILE = 48 * 1024      # file-Substrat: große Stücke
CHUNK_NET = 700             # hub/adapter: bleibt unter der MTU
WINDOW = 8                  # Chunks pro Anfrage
SEEN_MAX = 2048


def clean_name(name: str) -> str:
    return (name or "").strip().lower().replace("qfan.de/", "")


class FieldEngine:
    def __init__(
        self,
        name: str,
        role: str,
        host_name: str = "nexus",
        mailbox: Optional[str | Path] = None,
        use_file: bool = True,
        hub_listen: bool = True,
        hub_addr: Optional[str] = None,
        hub_port: int = DEFAULT_HUB_PORT,
        use_lan: bool = False,
        data_dir: str | Path = "qfan_data",
        beat: float = 5.0,
        timeout: float = 15.0,
        tick: float = 0.05,
        analyzer=None,
    ):
        self.name = clean_name(name)
        if not NAME_RE.match(self.name):
            raise ValueError("Name: nur a-z, 0-9, _ und - (max. 32 Zeichen)")
        if role not in ("host", "client"):
            raise ValueError("role muss 'host' oder 'client' sein")
        self.role = role
        self.is_host = role == "host"
        self.host_name = clean_name(host_name) if not self.is_host else self.name
        self.full_id = f"{PREFIX}{self.name}"
        self.beat, self.timeout, self.tick = beat, timeout, tick
        self.analyzer = analyzer

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.core = QFANCore()
        self.qdns = QDNS(ledger=self.data_dir / "qdns_ledger.jsonl")
        self.dhcp = FieldDHCP(total_nodes=128)
        self.takt = TaktSync()
        self.ledger = WormLedger(self.data_dir / f"ledger_{self.name}.jsonl")
        self.telemetry = Telemetry()
        self.vault = Vault(self.data_dir / "qfan_vault") if self.is_host else None

        own = self.qdns.resolve(self.full_id)
        self._q, self._p = own["q"], own["p"]

        # Substrate aufbauen
        want: List[str] = ["adapter"] if use_lan else []
        if not want:
            want = ["ble"]  # inaktiver Platzhalter, damit der Bus keine Vorgaben nachlädt
        self.bus = MultiSubstrateBus(self.name, self.data_dir / "field_mailbox", substrates=want)
        if use_file and mailbox is not None:
            self.bus.carriers["file"] = SlotMailbox(mailbox, self.name)
        self.hub: Optional[HubSubstrate] = None
        self.events: "queue.Queue[tuple]" = queue.Queue()
        try:
            if self.is_host and hub_listen:
                self.hub = HubSubstrate(self.name, "host", port=hub_port)
            elif not self.is_host and hub_addr is not None:
                self.hub = HubSubstrate(self.name, "client", hub_addr=hub_addr, port=hub_port,
                                        host_name=self.host_name)
        except OSError as exc:
            self._emit("log", f"[HUB] nicht verfügbar: {exc}")
        if self.hub:
            self.bus.carriers["hub"] = self.hub

        self.peers: Dict[str, dict] = {}
        self._lock = threading.RLock()
        self._seen: deque = deque()
        self._seen_set: set = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._next_beat = 0.0
        self._next_hello = 0.0
        self.stats = {"tx": 0, "rx": 0, "dup": 0}

        # Client-Zustand
        self.connected = False
        self.my_info: dict = {}
        self.host_via: Optional[str] = None
        self._host_last = 0.0
        self._dl: Optional[dict] = None
        self.files: List[dict] = []

        self.ledger.record("START", f"{self.role}:{self.name}")

    # ------------------------------------------------------------------ Hilfen
    def _emit(self, kind: str, *args) -> None:
        self.events.put((kind, *args))
        if kind == "log" and self.analyzer:
            try:
                self.analyzer.record("engine", args[0])
            except Exception:
                pass

    def log(self, text: str) -> None:
        self._emit("log", text)

    def substrates(self) -> List[str]:
        return self.bus.active_names()

    def hardware(self) -> List[str]:
        lines = [l for l in self.bus.hardware() if "kein BLE-Stack" not in l]
        if self.hub:
            if self.is_host:
                lines.append(f"hub → Host lauscht auf UDP-Feld-Port {self.hub.port} (für Clients in anderen Netzen)")
            else:
                target = self.hub.host_addr or "LAN-Suche (auto)"
                lines.append(f"hub → Verbindung zum Host {target}")
        return lines

    def online_peers(self) -> Dict[str, dict]:
        with self._lock:
            return {n: dict(i) for n, i in self.peers.items() if i.get("online")}

    def status(self) -> dict:
        peers = self.online_peers()
        base = {"role": self.role, "name": self.name, "peers": len(peers),
                "substrates": self.substrates(), "tx": self.stats["tx"], "rx": self.stats["rx"],
                "ledger": len(self.ledger), "telemetry": self.telemetry.total}
        if not self.is_host:
            base.update({"connected": self.connected, "host": self.host_name, "via": self.host_via,
                         "node_id": self.my_info.get("node_id"), "qip": self.my_info.get("qip")})
        return base

    # ------------------------------------------------------------------ Lebenszyklus
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"qfan-{self.name}")
        self._thread.start()
        subs = ", ".join(self.substrates()) or "—"
        self.log(f"{'Host-Server' if self.is_host else 'Client'} {self.full_id} gestartet · Substrate: {subs}")
        for line in self.hardware():
            self.log(f"[HARDWARE] {line}")

    def stop(self, send_bye: bool = True) -> None:
        if send_bye and self._running:
            try:
                if self.is_host:
                    for n, i in self.online_peers().items():
                        self._send(n, "bye", via=i.get("via"))
                elif self.connected:
                    self._send(self.host_name, "bye", via=self.host_via)
            except Exception:
                pass
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        try:
            self.ledger.record("STOP", self.name)
        except Exception:
            pass
        try:
            self.bus.close()
        except Exception:
            pass

    def _run(self) -> None:
        while self._running:
            try:
                for pkt in self.bus.receive():
                    self._handle(pkt)
                self._periodic()
            except Exception as exc:  # Schleife darf nie sterben
                self.log(f"[ENGINE] Fehler: {exc!r}")
            time.sleep(self.tick)

    # ------------------------------------------------------------------ Senden
    def _attach(self, pkt: dict) -> dict:
        fq = self.core.prepare_frame_qubit(self._q, self._p)
        pkt["q"], pkt["p"], pkt["det_j"] = fq["q"], fq["p"], fq["det_j"]
        pkt["eq"] = fq.get("eq")
        pkt["liouville_ok"] = fq["liouville_ok"]
        pkt["takt_slot"] = self.takt.local_slot()
        return pkt

    def _send(self, to: str, ptype: str, via: Optional[str] = None, **fields) -> bool:
        pkt = {"type": ptype, "from": self.name, "to": to, "id": uuid.uuid4().hex[:12],
               "ts": time.time(), **fields}
        pkt = self._attach(pkt)
        names = [via] if via and via in self.bus.carriers else self.bus.active_names()
        any_ok = False
        for n in names:
            carrier = self.bus.carriers.get(n)
            if carrier is None:
                continue
            try:
                ok = bool(carrier.send_frame(pkt))
            except Exception:
                ok = False
            self.bus.broker.report(n, ok)
            any_ok = any_ok or ok
        if any_ok:
            self.stats["tx"] += 1
        return any_ok

    # ------------------------------------------------------------------ Empfang + Gate
    def _reject(self, kind: str, reason: str) -> dict:
        return {"ok": False, "kind": kind, "reason": reason, "det_j": float("nan"), "residuum": 0.0}

    def _gate(self, pkt: dict, frm: str) -> dict:
        try:
            qa = np.asarray(pkt.get("q"), dtype=float).reshape(3)
            pa = np.asarray(pkt.get("p"), dtype=float).reshape(3)
        except Exception:
            return self._reject("LIOUVILLE_REJECT", "kein gültiges Qubit (q,p)")
        chk = self.core.liouville_check(qa, pa)
        if not chk["ok"]:
            r = self._reject("LIOUVILLE_REJECT", f"det(J)={chk['det_j']}")
            return r
        eq = pkt.get("eq")
        if eq is not None:
            try:
                if not self.core.equalizer_lock(eq, qa, pa)["ok"]:
                    r = self._reject("EQ_MISMATCH", "Equalizer EQ1–EQ5 nicht phasenstarr")
                    r["det_j"] = chk["det_j"]
                    return r
            except Exception:
                return self._reject("EQ_MISMATCH", "Equalizer ungültig")
        ideal = self.qdns.resolve(f"{PREFIX}{frm}")
        ideal_vec = np.concatenate([ideal["q"], ideal["p"]])
        rec = np.concatenate([qa, pa])
        res = self.core.residuum(rec, ideal_vec)
        _, escaped = self.core.evaluate_escape(res, rec.tolist())
        return {"ok": True, "kind": "TORSION_ESCAPE" if escaped else "RON_SMOOTHING",
                "det_j": chk["det_j"], "residuum": res, "qa": qa, "pa": pa}

    def _handle(self, pkt: dict) -> None:
        frm = clean_name(str(pkt.get("from", "")))
        if not NAME_RE.match(frm) or frm == self.name:
            return
        dest = clean_name(str(pkt.get("to") or ""))
        if dest not in ("", "*", self.name):
            return
        pid = pkt.get("id")
        if pid:
            if pid in self._seen_set:
                self.stats["dup"] += 1
                return
            self._seen.append(pid)
            self._seen_set.add(pid)
            if len(self._seen) > SEEN_MAX:
                self._seen_set.discard(self._seen.popleft())
        ptype = str(pkt.get("type", ""))
        if ptype in ("presence", "takt_sync", ""):
            return
        self.stats["rx"] += 1
        sub = pkt.get("_substrate")
        v = self._gate(pkt, frm)
        self.telemetry.record(v["kind"], v["residuum"], v["det_j"], frm, ptype)
        if not v["ok"]:
            self.ledger.record(v["kind"], f"{frm}:{ptype}")
            self.log(f"[GATE] {v['kind']} von {frm} ({ptype}): {v.get('reason', '')}")
            if self.is_host and ptype in ("handshake", "beat"):
                self._send(frm, "deny", via=sub, reason=f"{v['kind']}: {v.get('reason', '')}")
            return
        if not self.is_host and frm == self.host_name:
            self._host_last = time.time()
        if "takt_slot" in pkt:
            try:
                self.takt.observe({"type": "takt_sync", "slot": pkt["takt_slot"], "ts": pkt.get("ts", time.time())})
            except Exception:
                pass
        handler = getattr(self, ("_h_" if self.is_host else "_c_") + ptype, None)
        if handler:
            handler(frm, pkt, sub, v)

    # ------------------------------------------------------------------ periodische Aufgaben
    def _periodic(self) -> None:
        now = time.time()
        if self.is_host:
            if now >= self._next_beat:
                self._next_beat = now + self.beat
                for n, i in self.online_peers().items():
                    self._send(n, "beat", via=i.get("via"))
            gone = []
            with self._lock:
                for n, i in self.peers.items():
                    if i["online"] and now - i["last"] > self.timeout:
                        i["online"] = False
                        gone.append(n)
            for n in gone:
                self._peer_left(n, "Timeout")
            return
        # Client
        if not self.connected:
            if now >= self._next_hello:
                self._next_hello = now + 2.0
                self._send(self.host_name, "handshake")
        else:
            if now >= self._next_beat:
                self._next_beat = now + self.beat
                self._send(self.host_name, "beat", via=self.host_via)
            if now - self._host_last > self.timeout:
                self._host_lost()
        self._download_tick(now)

    # ------------------------------------------------------------------ Host-Handler
    def _accept(self, frm: str, sub: Optional[str], v: dict) -> None:
        lease = self.dhcp.verify_and_lease(f"{PREFIX}{frm}", v["qa"], v["pa"])
        if lease["status"] != "LOCKED":
            self._send(frm, "deny", via=sub, reason=str(lease.get("error", lease["status"])))
            self.ledger.record("HANDSHAKE_FAILED", f"{frm}:{lease.get('error')}")
            self.log(f"[DHCP] {frm} abgelehnt: {lease.get('error')}")
            return
        now = time.time()
        info = {"name": frm, "node_id": lease["node_id"], "qip": lease.get("qip"),
                "helix": lease.get("helix_slot"), "via": sub, "last": now, "online": True,
                "det_j": lease.get("det_j")}
        with self._lock:
            old = self.peers.get(frm)
            was_online = bool(old and old["online"])
            self.peers[frm] = info
            others = [{"name": n, "node_id": i["node_id"], "qip": i["qip"]}
                      for n, i in self.peers.items() if i["online"] and n != frm]
        self._send(frm, "welcome", via=sub, node_id=info["node_id"], qip=info["qip"],
                   helix_slot=info["helix"], det_j=info["det_j"], host=self.name, peers=others)
        if not was_online:
            self.ledger.record("CLIENT_LOCKED", f"{frm}:{info['node_id']}:{sub}")
            self._emit("online", frm, dict(info), False)
            self.log(f"[FIELD-DHCP] {PREFIX}{frm} online → {info['node_id']} {info['qip']} via {sub}")
            self._presence(frm, "online", info)

    def _presence(self, who: str, status: str, info: Optional[dict] = None) -> None:
        for n, i in self.online_peers().items():
            if n != who:
                self._send(n, "presence_update", via=i.get("via"), name=who, status=status,
                           node_id=(info or {}).get("node_id"), qip=(info or {}).get("qip"))

    def _peer_left(self, name: str, why: str) -> None:
        self.ledger.record("CLIENT_LEFT", f"{name}:{why}")
        self._emit("offline", name)
        self.log(f"[FIELD-DHCP] {PREFIX}{name} offline ({why})")
        self._presence(name, "offline")

    def _h_handshake(self, frm, pkt, sub, v):
        self._accept(frm, sub, v)

    def _h_beat(self, frm, pkt, sub, v):
        with self._lock:
            i = self.peers.get(frm)
            if i and i["online"]:
                i["last"], i["via"] = time.time(), sub
                return
        self._accept(frm, sub, v)   # Host war neu gestartet, Client lebt noch

    def _h_bye(self, frm, pkt, sub, v):
        with self._lock:
            i = self.peers.get(frm)
            was = bool(i and i["online"])
            if i:
                i["online"] = False
        if was:
            self._peer_left(frm, "abgemeldet")

    def _is_online(self, name: str) -> bool:
        with self._lock:
            i = self.peers.get(name)
            return bool(i and i["online"])

    def _h_msg(self, frm, pkt, sub, v):
        if not self._is_online(frm):
            return
        text = str(pkt.get("text", ""))[:4000]
        dest = clean_name(str(pkt.get("dest") or "*")) or "*"
        self._emit("msg", frm, text, dest, pkt.get("ts", time.time()))
        self.ledger.record("MSG", f"{frm}->{dest}: {text[:200]}")
        peers = self.online_peers()
        if dest == "*":
            targets = [n for n in peers if n != frm]
        elif dest in peers and dest != frm:
            targets = [dest]
        else:
            targets = []
        for t in targets:
            self._send(t, "msg", via=peers[t].get("via"), origin=frm, dest=dest, text=text)

    def _h_list_files(self, frm, pkt, sub, v):
        if self._is_online(frm):
            self._send(frm, "files", via=sub, files=self.vault.list_info())

    def _h_get_file(self, frm, pkt, sub, v):
        if not self._is_online(frm):
            return
        name = str(pkt.get("name", ""))
        try:
            cs = int(pkt.get("cs") or (CHUNK_FILE if sub == "file" else CHUNK_NET))
            cs = max(64, min(cs, CHUNK_FILE))
            want = pkt.get("want")
            if want is None:
                info = self.vault.info(name, CHUNK_FILE if sub == "file" else CHUNK_NET)
                self._send(frm, "file_info", via=sub, **info)
                return
            for idx in list(want)[:WINDOW * 2]:
                data = self.vault.read_chunk(name, int(idx), cs)
                self._send(frm, "file_chunk", via=sub, name=name, idx=int(idx),
                           data=base64.b64encode(data).decode("ascii"))
            if want and int(max(want)) * cs + cs >= self.vault.path_of(name).stat().st_size:
                self.ledger.record("FILE_SENT", f"{name}->{frm}")
        except (OSError, ValueError, TypeError) as exc:
            self._send(frm, "file_error", via=sub, name=name, reason=str(exc))

    # --- Host-Aktionen für die Oberfläche
    def say(self, text: str, dest: str = "*") -> int:
        """Host spricht ins Feld: dest='*' an alle, sonst an einen Client. Gibt Zahl der Empfänger zurück."""
        dest = clean_name(dest) or "*"
        peers = self.online_peers()
        targets = list(peers) if dest == "*" else ([dest] if dest in peers else [])
        for t in targets:
            self._send(t, "msg", via=peers[t].get("via"), origin=self.name, dest=dest, text=text[:4000])
        self.ledger.record("MSG", f"{self.name}->{dest}: {text[:200]}")
        return len(targets)

    def share_file(self, path: str | Path) -> str:
        name = self.vault.store(path)
        self.ledger.record("FILE_SHARED", name)
        self.log(f"[VAULT] '{name}' freigegeben")
        for n, i in self.online_peers().items():
            self._send(n, "files", via=i.get("via"), files=self.vault.list_info())
        return name

    # ------------------------------------------------------------------ Client-Handler
    def _c_welcome(self, frm, pkt, sub, v):
        if frm != self.host_name:
            return
        first = not self.connected
        self.connected = True
        self.host_via = sub
        self._host_last = time.time()
        self.my_info = {"node_id": pkt.get("node_id"), "qip": pkt.get("qip"),
                        "helix": pkt.get("helix_slot"), "det_j": pkt.get("det_j")}
        with self._lock:
            self.peers[self.host_name] = {"name": self.host_name, "node_id": "HOST", "qip": None,
                                          "via": sub, "last": time.time(), "online": True}
            for p in pkt.get("peers", []):
                n = clean_name(str(p.get("name", "")))
                if NAME_RE.match(n) and n != self.name:
                    self.peers[n] = {"name": n, "node_id": p.get("node_id"), "qip": p.get("qip"),
                                     "via": sub, "last": time.time(), "online": True}
        if first:
            self.ledger.record("CONNECTED", f"{self.host_name}:{self.my_info.get('node_id')}:{sub}")
            self._emit("connected", dict(self.my_info, host=self.host_name, via=sub))
            self.log(f"[WELCOME] {self.host_name}: {self.my_info.get('node_id')} {self.my_info.get('qip')} via {sub}")
            self._emit("online", self.host_name, dict(self.peers[self.host_name]), True)
            for n, i in self.online_peers().items():
                if n != self.host_name:
                    self._emit("online", n, i, True)
            self._send(self.host_name, "list_files", via=sub)

    def _c_deny(self, frm, pkt, sub, v):
        if frm == self.host_name:
            reason = str(pkt.get("reason", ""))
            self.ledger.record("DENIED", reason[:120])
            self._emit("denied", reason)
            self.log(f"[LOCKDOWN] vom Host abgelehnt: {reason}")

    def _c_beat(self, frm, pkt, sub, v):
        if frm == self.host_name and sub:
            self.host_via = sub

    def _c_bye(self, frm, pkt, sub, v):
        if frm == self.host_name:
            self._host_lost("Host hat sich abgemeldet")

    def _c_presence_update(self, frm, pkt, sub, v):
        if frm != self.host_name:
            return
        n = clean_name(str(pkt.get("name", "")))
        if not NAME_RE.match(n) or n == self.name:
            return
        if pkt.get("status") == "online":
            info = {"name": n, "node_id": pkt.get("node_id"), "qip": pkt.get("qip"),
                    "via": sub, "last": time.time(), "online": True}
            with self._lock:
                was = bool(self.peers.get(n, {}).get("online"))
                self.peers[n] = info
            if not was:
                self._emit("online", n, dict(info), False)
                self.log(f"[PRESENCE] {PREFIX}{n} ist online")
        else:
            with self._lock:
                was = bool(self.peers.get(n, {}).get("online"))
                if n in self.peers:
                    self.peers[n]["online"] = False
            if was:
                self._emit("offline", n)
                self.log(f"[PRESENCE] {PREFIX}{n} ist offline")

    def _c_msg(self, frm, pkt, sub, v):
        origin = clean_name(str(pkt.get("origin") or frm))
        self._emit("msg", origin, str(pkt.get("text", ""))[:4000], clean_name(str(pkt.get("dest") or "*")) or "*",
                   pkt.get("ts", time.time()))

    def _c_files(self, frm, pkt, sub, v):
        files = [{"name": str(f.get("name")), "size": int(f.get("size", 0))}
                 for f in pkt.get("files", []) if isinstance(f, dict) and f.get("name")]
        self.files = files
        self._emit("files", files)

    def _c_file_error(self, frm, pkt, sub, v):
        dl = self._dl
        if dl and dl["name"] == pkt.get("name"):
            self._dl = None
        self._emit("file_error", str(pkt.get("name")), str(pkt.get("reason", "")))

    def _c_file_info(self, frm, pkt, sub, v):
        dl = self._dl
        if not dl or dl["name"] != pkt.get("name") or dl.get("info"):
            return
        try:
            size, chunks, cs = int(pkt["size"]), int(pkt["chunks"]), int(pkt["chunk_size"])
        except (KeyError, ValueError, TypeError):
            return
        dl["info"] = {"size": size, "chunks": chunks, "cs": cs, "sha256": str(pkt.get("sha256", ""))}
        dl["parts"] = {}
        dl["last"] = time.time()
        self._request_window(dl)

    def _c_file_chunk(self, frm, pkt, sub, v):
        dl = self._dl
        if not dl or not dl.get("info") or dl["name"] != pkt.get("name"):
            return
        try:
            idx = int(pkt["idx"])
            data = base64.b64decode(str(pkt["data"]).encode("ascii"))
        except (KeyError, ValueError, TypeError):
            return
        if not 0 <= idx < dl["info"]["chunks"]:
            return
        dl["parts"][idx] = data
        dl["last"] = time.time()
        dl["tries"] = 0
        self._emit("file_progress", dl["name"], len(dl["parts"]), dl["info"]["chunks"])
        if len(dl["parts"]) >= dl["info"]["chunks"]:
            self._finish_download(dl)
        elif not any(i not in dl["parts"] and i in dl.get("asked", ()) for i in range(dl["info"]["chunks"])):
            self._request_window(dl)

    # --- Client-Aktionen
    def say_to(self, text: str, dest: str = "*") -> bool:
        if not self.connected:
            return False
        return self._send(self.host_name, "msg", via=self.host_via, dest=clean_name(dest) or "*", text=text[:4000])

    def refresh_files(self) -> bool:
        return self.connected and self._send(self.host_name, "list_files", via=self.host_via)

    def download(self, name: str, dest_path: str | Path) -> bool:
        if not self.connected:
            return False
        self._dl = {"name": safe_name(name), "dest": Path(dest_path), "info": None, "parts": {},
                    "asked": set(), "last": time.time(), "tries": 0}
        return self._send(self.host_name, "get_file", via=self.host_via, name=self._dl["name"])

    def _request_window(self, dl: dict) -> None:
        info = dl["info"]
        missing = [i for i in range(info["chunks"]) if i not in dl["parts"]][:WINDOW]
        if not missing:
            return
        dl["asked"] = set(missing)
        self._send(self.host_name, "get_file", via=self.host_via, name=dl["name"], want=missing, cs=info["cs"])

    def _download_tick(self, now: float) -> None:
        dl = self._dl
        if not dl or now - dl["last"] < 2.0:
            return
        dl["tries"] += 1
        dl["last"] = now
        if dl["tries"] > 6:
            self._dl = None
            self._emit("file_error", dl["name"], "Zeitüberschreitung")
            return
        if dl.get("info"):
            self._request_window(dl)
        else:
            self._send(self.host_name, "get_file", via=self.host_via, name=dl["name"])

    def _finish_download(self, dl: dict) -> None:
        info = dl["info"]
        data = b"".join(dl["parts"][i] for i in range(info["chunks"]))
        self._dl = None
        if len(data) != info["size"] or (info["sha256"] and hashlib.sha256(data).hexdigest() != info["sha256"]):
            self._emit("file_error", dl["name"], "Prüfsumme stimmt nicht")
            return
        try:
            dest = Path(dl["dest"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
        except OSError as exc:
            self._emit("file_error", dl["name"], str(exc))
            return
        self.ledger.record("FILE_RECEIVED", f"{dl['name']}:{len(data)}")
        self._emit("file_done", dl["name"], str(dest))

    def _host_lost(self, why: str = "Zeitüberschreitung") -> None:
        if not self.connected:
            return
        self.connected = False
        self.host_via = None
        with self._lock:
            gone = [n for n, i in self.peers.items() if i.get("online")]
            for i in self.peers.values():
                i["online"] = False
        self.ledger.record("HOST_LOST", why)
        for n in gone:
            self._emit("offline", n)
        self._emit("host_lost")
        self.log(f"[HOST] Verbindung verloren ({why}) — versuche neu zu verbinden")
