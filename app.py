#!/usr/bin/env python3
"""
QFAN Field Node — Host/Client
Multi-Substrat · Equalizer EQ1–EQ5 · Liouville · kein IP-Stack.
"""
from __future__ import annotations

import argparse
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog

from qfan.substrates import MultiSubstrateBus
from qfan.field_burst import FieldBurstSequencer
from qfan.field_sync import TaktSync
from qfan.field_dhcp import FieldDHCP
from qfan.qdns import PREFIX, QDNS, normalize
from qfan.qfan_core import QFANCore
from qfan.qip import make_qip
from qfan.qfan_analyzer import AnalysisSession

DEFAULT_MAILBOX = Path(__file__).resolve().parents[1] / "field_mailbox"


class QFANApp:
    def __init__(self, root, my_name: str, role: str, mailbox: Path, target: str = "",
                 analyze: bool = False):
        self.root = root
        self.my_name = my_name.lower().replace("qfan.de/", "").strip()
        self.is_host = role == "host"
        self.role_label = "QFAN Server · Nexus" if self.is_host else "QFAN Client Browser"
        self.accent = "#00ffcc" if self.is_host else "#ff9f43"
        self.full_id = f"{PREFIX}{self.my_name}"

        self.analyzer = AnalysisSession() if analyze else None
        self.substrate = "file"  # Default-Tag; Frames tragen _substrate

        self.core = QFANCore()
        self.qdns = QDNS()
        self.dhcp = FieldDHCP()
        # Substrate: file + adapter (NIC als Blindträger). BLE optional.
        want = ["adapter", "ble"]
        if mailbox is not None:
            want = ["file"] + want
        self.bus = MultiSubstrateBus(
            self.my_name,
            mailbox or Path("."),
            substrates=want,
        )
        # Burst-Sequenz: hebt Pakete taktsynchron @ 98.112 Hz ins Substrat
        self.takt = TaktSync()
        self.burst = FieldBurstSequencer(
            send_fn=self.bus.send,
            burst_len=8,
            on_log=lambda msg: self.root.after(0, lambda m=msg: self.log(m)),
            takt_sync=self.takt,
        )
        self._own_phase = self.qdns.resolve(self.full_id)
        self.qdns.register(self.full_id)

        self.contacts = {}  # name -> status dict
        self.active_target = target.replace("qfan.de/", "") if target else ("nexus" if not self.is_host else "")
        self.current_lock = False
        self.my_lease = None

        root.title(f"{self.role_label} — {self.full_id}")
        root.geometry("1100x700")
        root.configure(bg="#0d0d0d")
        root.protocol("WM_DELETE_WINDOW", self._close)

        self._build_ui()
        self._self_lock()
        self.log(f"{self.role_label} '{self.my_name}' gestartet")
        self.log(f"Feld-Pfad: {mailbox}")
        self.log(f"Feld-Adresse: {self.full_id}  |  EQ1–EQ5 · Liouville · QIP")
        self.log("Schicht-1 Substrate: " + ", ".join(self.bus.active_names()))
        for hw in self.bus.hardware():
            self.log(f"[HARDWARE] {hw}")
        self.log("Kette: Qubit → Ronmetrik → Liouville → Burst @ 98.112 Hz → Substrat")
        if self.analyzer:
            self.log(f"[ANALYSE] Session {self.analyzer.session} → {self.analyzer.current_file()}")
        self.root.after(200, self._tick)

    def _self_lock(self):
        res = self.qdns.resolve(self.full_id)
        lease = self.dhcp.verify_and_lease(self.full_id, res["q"], res["p"])
        self.my_lease = lease
        if lease["status"] == "LOCKED":
            self.log(
                f"Eigen-Lock OK  det(J)={lease['det_j']:.6f}  "
                f"{lease['node_id']}  Helix {lease['helix_slot']}  {lease.get('qip')}"
            )
            self.lbl_qip.config(text=f"QIP: {lease.get('qip', '—')}", fg=self.accent)
        else:
            self.log(f"Eigen-Lock FEHLER: {lease.get('error')}")

    def _build_ui(self):
        top = tk.Frame(self.root, bg="#161616")
        top.pack(fill=tk.X, padx=6, pady=6)
        tk.Label(top, text=self.role_label, font=("Consolas", 10, "bold"),
                 fg=self.accent, bg="#161616").pack(side=tk.LEFT, padx=6)
        tk.Label(top, text="Ziel:", font=("Consolas", 10), fg="#aaa", bg="#161616").pack(side=tk.LEFT)
        self.entry_target = tk.Entry(top, font=("Consolas", 11), bg="#222", fg=self.accent,
                                     insertbackground=self.accent, width=24)
        self.entry_target.insert(0, self.active_target or "")
        self.entry_target.pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="FELD VERBINDEN", font=("Consolas", 9, "bold"),
                  bg=self.accent, fg="#000", command=self.lock_target).pack(side=tk.LEFT, padx=6)
        tk.Button(top, text="Analyse", font=("Consolas", 9), bg="#1e3a5f", fg="#7dd3fc",
                  command=self.export_report).pack(side=tk.RIGHT, padx=6)

        self.lbl_status = tk.Label(
            self.root,
            text=f"STATUS: BEREIT  |  {self.full_id}  |  Feld-Bus aktiv",
            font=("Consolas", 9, "bold"), fg=self.accent, bg="#0d0d0d", anchor="w",
        )
        self.lbl_status.pack(fill=tk.X, padx=10)
        self.lbl_qip = tk.Label(self.root, text="QIP: —", font=("Consolas", 9),
                                fg=self.accent, bg="#0d0d0d", anchor="w")
        self.lbl_qip.pack(fill=tk.X, padx=10)

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a", sashwidth=4)
        paned.pack(expand=True, fill=tk.BOTH, padx=8, pady=4)

        left = tk.Frame(paned, bg="#121212")
        paned.add(left, minsize=260)
        tk.Label(left, text="FELD-KNOTEN (Presence + DHCP)", font=("Consolas", 9, "bold"),
                 fg="#fff", bg="#121212").pack(anchor="w", padx=8, pady=6)
        self.listbox = tk.Listbox(left, font=("Consolas", 10), bg="#1a1a1a", fg="#9ca3af",
                                  selectbackground=self.accent, selectforeground="#000",
                                  bd=0, highlightthickness=0)
        self.listbox.pack(expand=True, fill=tk.BOTH, padx=8, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = tk.Frame(paned, bg="#0d0d0d")
        paned.add(right, minsize=500)
        self.log_view = scrolledtext.ScrolledText(
            right, wrap=tk.WORD, font=("Consolas", 10), bg="#0a0a0a",
            fg=self.accent, insertbackground=self.accent,
        )
        self.log_view.pack(expand=True, fill=tk.BOTH)

        bottom = tk.Frame(self.root, bg="#161616")
        bottom.pack(fill=tk.X, padx=6, pady=6)
        self.entry_msg = tk.Entry(bottom, font=("Consolas", 11), bg="#222", fg="#fff",
                                  insertbackground="#fff")
        self.entry_msg.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
        self.entry_msg.bind("<Return>", lambda e: self.send_msg())
        tk.Button(bottom, text="Nachricht senden", font=("Consolas", 9, "bold"),
                  bg=self.accent, fg="#000", command=self.send_msg).pack(side=tk.RIGHT, padx=4)

    def log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        self.log_view.insert(tk.END, f"[{ts}] {text}\n")
        self.log_view.see(tk.END)
        if self.analyzer:
            try:
                self.analyzer.record(self.substrate, text)
            except Exception:
                pass


    def _attach_qubit(self, packet: dict) -> dict:
        """Ronmetrik + Qubit in jeden Frame, bevor er ins Substrat geht."""
        own = getattr(self, "_own_phase", None) or self.qdns.resolve(self.full_id)
        q, p = own["q"], own["p"]
        frame_q = self.core.prepare_frame_qubit(q, p)
        packet = dict(packet)
        packet["q"] = frame_q["q"]
        packet["p"] = frame_q["p"]
        packet["det_j"] = frame_q["det_j"]
        packet["eq"] = frame_q.get("eq")
        packet["kuramoto_r"] = frame_q.get("kuramoto_r")
        packet["liouville_ok"] = frame_q["liouville_ok"]
        packet["takt_slot"] = self.takt.local_slot()
        if self.my_lease:
            packet["qip"] = self.my_lease.get("qip")
        return packet

    def lock_target(self):
        name = self.entry_target.get().strip()
        if not name:
            return
        url = normalize(name)
        short = url.replace(PREFIX, "")
        self.active_target = short
        res = self.qdns.resolve(url)
        lease = self.dhcp.verify_and_lease(url, res["q"], res["p"])
        if lease["status"] == "LOCKED":
            self.current_lock = True
            self.contacts[short] = {
                "status": "ONLINE",
                "node_id": lease["node_id"],
                "qip": lease.get("qip"),
                "helix_slot": lease.get("helix_slot"),
            }
            self.lbl_status.config(
                text=f"STATUS: VERBUNDEN  |  {url}  |  {lease['node_id']}",
                fg=self.accent,
            )
            self.log(f"Liouville-Handshake OK det(J)={lease['det_j']:.6f}")
            self.log(f"Matrix-Lease: {lease['node_id']}  Helix {lease['helix_slot']}")
            self.log(f"QIP: {lease.get('qip')}")
            # Handshake-Paket ins Feld
            hs = self._attach_qubit({
                "type": "handshake",
                "from": self.my_name,
                "to": short,
                "node_id": lease["node_id"],
            })
            # Ziel-Qubit: Q-DNS, dann Ronmetrik, dann erst Substrat
            smoothed = self.core.prepare_frame_qubit(res["q"], res["p"])
            hs["q"] = smoothed["q"]
            hs["p"] = smoothed["p"]
            hs["det_j"] = smoothed["det_j"]
            hs["liouville_ok"] = smoothed["liouville_ok"]
            results = self.burst.enqueue_now(hs)
            self.log(f"Handshake auf Substrate: {results}")
            self._refresh_contacts()
        else:
            self.current_lock = False
            self.lbl_status.config(text="STATUS: LOCKDOWN", fg="#ff5555")
            self.log(f"LOCKDOWN: {lease.get('error')}")

    def send_msg(self):
        msg = self.entry_msg.get().strip()
        if not msg:
            return
        target = self.active_target or self.entry_target.get().strip().replace("qfan.de/", "")
        if not target:
            messagebox.showinfo("QFAN", "Zuerst Ziel setzen und FEL D-KOPPELN.")
            return
        if not self.current_lock:
            self.lock_target()
        packet = self._attach_qubit({
            "type": "msg",
            "from": self.my_name,
            "to": target,
            "text": msg,
            "ts": time.time(),
        })
        # Ronmetrik-Qubit + Burst → Substrat
        self.burst.enqueue(packet)
        st = self.burst.stats()
        self.log(
            f"Du [{self.full_id}]: {msg}  → Burst-Queue "
            f"(depth={st['queue_depth']}, bursts={st['bursts']})"
        )
        self.entry_msg.delete(0, tk.END)

    def _on_select(self, _evt):
        sel = self.listbox.curselection()
        if not sel:
            return
        line = self.listbox.get(sel[0])
        # "🟢  qfan.de/jan  [NODE-700] QIP-..."
        parts = line.split()
        for p in parts:
            if p.startswith("qfan.de/") or (p not in ("🟢", "○", "[STANDBY]") and not p.startswith("[")):
                name = p.replace("qfan.de/", "")
                if name and not name.startswith("QIP") and not name.startswith("NODE"):
                    self.entry_target.delete(0, tk.END)
                    self.entry_target.insert(0, name)
                    break

    def _refresh_contacts(self):
        self.listbox.delete(0, tk.END)
        for name, st in sorted(self.contacts.items()):
            url = f"{PREFIX}{name}"
            if st.get("status") == "ONLINE":
                qip = st.get("qip") or ""
                node = st.get("node_id") or ""
                sub = st.get("substrate") or ""
                self.listbox.insert(
                    tk.END, f"🟢  {url}  [{node}]  {qip}  {sub}"
                )
                self.listbox.itemconfig(tk.END, fg=self.accent)
            else:
                self.listbox.insert(tk.END, f"○  {url}  [STANDBY]")
                self.listbox.itemconfig(tk.END, fg="#9ca3af")

    def _tick(self):
        # Presence broadcast
        pres = {
            "qip": (self.my_lease or {}).get("qip"),
            "node_id": (self.my_lease or {}).get("node_id"),
            "role": "host" if self.is_host else "client",
            "takt_slot": self.takt.local_slot(),
        }
        try:
            self.bus.publish_presence(pres)
        except Exception:
            pass
        # Takt-Sync-Pulse auf alle Substrate (Kohärenz)
        try:
            pulse = self.takt.make_pulse(
                qip=(self.my_lease or {}).get("qip") or "",
                name=self.my_name,
            )
            self.bus.send(pulse)
        except Exception:
            pass

        # Presence scan
        for peer in self.bus.scan_presence():
            name = peer.get("name")
            if not name:
                continue
            url = f"{PREFIX}{name}"
            if name not in self.contacts or self.contacts[name].get("status") != "ONLINE":
                res = self.qdns.resolve(url)
                lease = self.dhcp.verify_and_lease(url, res["q"], res["p"])
                if lease["status"] == "LOCKED":
                    self.contacts[name] = {
                        "status": "ONLINE",
                        "node_id": lease["node_id"],
                        "qip": lease.get("qip") or peer.get("qip"),
                        "helix_slot": lease.get("helix_slot"),
                    }
                    self.log(f"[FIELD-DHCP] Node online: {url} → {lease['node_id']}  {lease.get('qip')}")
                    self._refresh_contacts()

        # Receive frames from all substrates
        for pkt in self.bus.receive():
            if pkt.get("type") == "presence":
                name = pkt.get("name") or pkt.get("from")
                if not name or name == self.my_name:
                    continue
                url = f"{PREFIX}{name}"
                if name not in self.contacts or self.contacts[name].get("status") != "ONLINE":
                    res = self.qdns.resolve(url)
                    lease = self.dhcp.verify_and_lease(url, res["q"], res["p"])
                    if lease["status"] == "LOCKED":
                        self.contacts[name] = {
                            "status": "ONLINE",
                            "node_id": lease["node_id"],
                            "qip": lease.get("qip") or pkt.get("qip"),
                            "helix_slot": lease.get("helix_slot"),
                            "substrate": pkt.get("_substrate") or pkt.get("substrate"),
                        }
                        self.log(
                            f"[FIELD-DHCP] Node online: {url} → {lease['node_id']}  "
                            f"{lease.get('qip')}  via {pkt.get('_substrate', '?')}"
                        )
                        self._refresh_contacts()
                continue
            self._handle_packet(pkt)

        self.root.after(400, self._tick)

    def _handle_packet(self, pkt: dict):
        ptype = pkt.get("type")
        sender = pkt.get("from", "?")
        sub = pkt.get("_substrate") or "?"
        if ptype == "takt_sync":
            adj = self.takt.observe(pkt)
            if abs(adj) > 1e-6:
                self.log(f"[TAKT-SYNC] via {sub}: Δ={adj*1000:.3f} ms  slot={pkt.get('slot')}")
            return
        if ptype == "handshake":
            url = f"{PREFIX}{sender}"
            q = pkt.get("q")
            p = pkt.get("p")
            if q is not None and p is not None:
                # Liouville-Gate — unabhängig vom Substrat
                lease = self.dhcp.verify_and_lease(url, q, p)
                if lease["status"] == "LOCKED":
                    self.contacts[sender] = {
                        "status": "ONLINE",
                        "node_id": lease["node_id"],
                        "qip": lease.get("qip") or pkt.get("qip"),
                        "helix_slot": lease.get("helix_slot"),
                        "substrate": sub,
                    }
                    self.log(f"[HANDSHAKE] {url} LOCKED det(J)={lease['det_j']:.6f} via {sub}")
                    self.log(f"  → {lease['node_id']}  {lease.get('qip')}")
                    self._refresh_contacts()
                else:
                    self.log(f"[HANDSHAKE] LOCKDOWN von {url} via {sub}: {lease.get('error')}")
            else:
                self.log(f"[HANDSHAKE] von {sender}")
        elif ptype == "msg":
            text = pkt.get("text", "")
            # Qubit-pro-Frame: Stichprobe Liouville, wenn (q,p) mitkommen
            q, p = pkt.get("q"), pkt.get("p")
            gate = ""
            if q is not None and p is not None:
                chk = self.core.liouville_check(q, p)
                if not chk["ok"]:
                    self.log(f"[LIOUVILLE-GATE] reject det(J)={chk['det_j']:.6f} via {sub}")
                    return
                gate = f" det(J)={chk['det_j']:.6f}"
            self.log(f"Empfang von {PREFIX}{sender}: {text}  [{sub}]{gate}")
            if sender not in self.contacts:
                self.contacts[sender] = {
                    "status": "ONLINE",
                    "node_id": "?",
                    "qip": pkt.get("qip"),
                    "substrate": sub,
                }
                self._refresh_contacts()
        else:
            self.log(f"[FELD] {pkt}")

    def export_report(self):
        path = Path(__file__).resolve().parent / "logs" / f"report_{self.my_name}_{int(time.time())}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "QFAN Feld-Report",
            f"Node: {self.full_id}",
            f"Role: {self.role_label}",
            f"Lease: {self.my_lease}",
            f"Contacts: {self.contacts}",
            f"Mailbox: {self.bus.root}",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        self.log(f"[ANALYSE] {path}")
        messagebox.showinfo("Analyse", str(path))

    def _close(self):
        try:
            self.burst.close()
        except Exception:
            pass
        try:
            self.bus.close()
        except Exception:
            pass
        if getattr(self, "analyzer", None):
            try:
                path = self.analyzer.current_file()
                self.analyzer.close()
                print(f"Analyse-Log: {path}")
            except Exception:
                pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="QFAN Field Node")
    parser.add_argument("--role", choices=("host", "client"), default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--path", default=str(DEFAULT_MAILBOX), help="Optional: file-Substrat")
    parser.add_argument("--no-file", action="store_true", help="Ohne file-Substrat")
    parser.add_argument("--target", default="", help="Ziel-Name (ohne qfan.de/)")
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Hintergrund-Analyse aktivieren (JSONL in qfan_logs/)",
    )
    args = parser.parse_args()

    root = tk.Tk()
    root.withdraw()

    role = args.role
    name = args.name
    if role is None:
        choice = messagebox.askquestion(
            "QFAN",
            "Als Master-Host starten?\n\nJa = Host (cyan)\nNein = Client (orange)",
        )
        role = "host" if choice == "yes" else "client"
    if not name:
        if role == "host":
            name = "nexus"
        else:
            name = simpledialog.askstring("QFAN Client", "Client-Name (qfan.de/<name>):")
            if not name:
                root.destroy()
                return

    root.deiconify()
    mailbox = None if getattr(args, "no_file", False) else Path(args.path)
    QFANApp(
        root,
        my_name=name,
        role=role,
        mailbox=mailbox,
        target=args.target,
        analyze=args.analyze,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
