"""QFAN desktop application.

This is a local software prototype. The UDP carrier uses the host IP stack;
phase checks are not authentication or transport security.
"""
from __future__ import annotations

import argparse
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog

from .analysis.analyzer import AnalysisSession
from .core import FieldDHCP, PREFIX, QDNS, QFANCore, normalize
from .core.field_burst import FieldBurstSequencer
from .core.field_sync import TaktSync
from .network import MultiSubstrateBus

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAILBOX = ROOT / "field_mailbox"


class QFANApp:
    def __init__(self, root, my_name: str, role: str, mailbox: Path | None,
                 target: str = "", analyze: bool = False):
        self.root = root
        self.my_name = my_name.lower().replace(PREFIX, "").strip()
        self.is_host = role == "host"
        self.role_label = "QFAN Server · Nexus" if self.is_host else "QFAN Client Browser"
        self.accent = "#00ffcc" if self.is_host else "#ff9f43"
        self.full_id = f"{PREFIX}{self.my_name}"
        self.analyzer = AnalysisSession() if analyze else None
        self.core, self.qdns, self.dhcp = QFANCore(), QDNS(), FieldDHCP()
        substrates = (["file"] if mailbox is not None else []) + ["adapter", "ble"]
        self.bus = MultiSubstrateBus(self.my_name, mailbox or Path("."), substrates=substrates)
        self.takt = TaktSync()
        self.burst = FieldBurstSequencer(self.bus.send, on_log=self._queue_log, takt_sync=self.takt)
        self._own_phase = self.qdns.resolve(self.full_id)
        self.qdns.register(self.full_id)
        self.contacts: dict[str, dict] = {}
        self.active_target = target.replace(PREFIX, "") if target else ("nexus" if not self.is_host else "")
        self.current_lock = False
        self.my_lease = None
        root.title(f"{self.role_label} — {self.full_id}")
        root.geometry("1000x640")
        root.configure(bg="#0d0d0d")
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._build_ui()
        self._self_lock()
        self.log(f"{self.role_label} '{self.my_name}' gestartet")
        self.log("Aktive Träger: " + ", ".join(self.bus.active_names()))
        for item in self.bus.hardware():
            self.log("[CARRIER] " + item)
        self.root.after(200, self._tick)

    def _queue_log(self, text: str):
        self.root.after(0, lambda: self.log(text))

    def _build_ui(self):
        top = tk.Frame(self.root, bg="#161616"); top.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(top, text=self.role_label, fg=self.accent, bg="#161616").pack(side=tk.LEFT, padx=6)
        tk.Label(top, text="Ziel:", fg="#aaa", bg="#161616").pack(side=tk.LEFT)
        self.entry_target = tk.Entry(top, bg="#222", fg=self.accent, insertbackground=self.accent, width=24)
        self.entry_target.insert(0, self.active_target); self.entry_target.pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Verbinden", command=self.lock_target).pack(side=tk.LEFT, padx=5)
        tk.Button(top, text="Report", command=self.export_report).pack(side=tk.RIGHT, padx=5)
        self.lbl_status = tk.Label(self.root, text=f"BEREIT | {self.full_id}", fg=self.accent,
                                   bg="#0d0d0d", anchor="w")
        self.lbl_status.pack(fill=tk.X, padx=10)
        self.lbl_qip = tk.Label(self.root, text="QIP: —", fg=self.accent, bg="#0d0d0d", anchor="w")
        self.lbl_qip.pack(fill=tk.X, padx=10)
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a")
        pane.pack(expand=True, fill=tk.BOTH, padx=8, pady=5)
        left = tk.Frame(pane, bg="#121212"); pane.add(left, minsize=240)
        tk.Label(left, text="Knoten", fg="white", bg="#121212").pack(anchor="w", padx=8, pady=6)
        self.listbox = tk.Listbox(left, bg="#1a1a1a", fg="#ddd", selectbackground=self.accent)
        self.listbox.pack(expand=True, fill=tk.BOTH, padx=8, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        right = tk.Frame(pane, bg="#0d0d0d"); pane.add(right, minsize=450)
        self.log_view = scrolledtext.ScrolledText(right, wrap=tk.WORD, bg="#0a0a0a", fg=self.accent)
        self.log_view.pack(expand=True, fill=tk.BOTH)
        bottom = tk.Frame(self.root, bg="#161616"); bottom.pack(fill=tk.X, padx=8, pady=8)
        self.entry_msg = tk.Entry(bottom, bg="#222", fg="white", insertbackground="white")
        self.entry_msg.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
        self.entry_msg.bind("<Return>", lambda _event: self.send_msg())
        tk.Button(bottom, text="Senden", command=self.send_msg).pack(side=tk.RIGHT, padx=4)

    def log(self, text: str):
        self.log_view.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.log_view.see(tk.END)
        if self.analyzer:
            self.analyzer.record("local", text)

    def _self_lock(self):
        phase = self.qdns.resolve(self.full_id)
        self.my_lease = self.dhcp.verify_and_lease(self.full_id, phase["q"], phase["p"])
        if self.my_lease.get("status") == "LOCKED":
            self.lbl_qip.config(text=f"QIP: {self.my_lease.get('qip', '—')}")
            self.log(f"Lokaler Software-Check: {self.my_lease['node_id']} {self.my_lease.get('qip')}")
        else:
            self.log(f"Lease abgelehnt: {self.my_lease.get('error')}")

    def _attach_qubit(self, packet: dict) -> dict:
        frame = self.core.prepare_frame_qubit(self._own_phase["q"], self._own_phase["p"])
        return {**packet, "q": frame["q"], "p": frame["p"], "det_j": frame["det_j"],
                "eq": frame["eq"], "liouville_ok": frame["liouville_ok"],
                "takt_slot": self.takt.local_slot(), "qip": (self.my_lease or {}).get("qip")}

    def lock_target(self):
        name = self.entry_target.get().strip()
        if not name: return
        url = normalize(name); short = url.removeprefix(PREFIX)
        phase = self.qdns.resolve(url)
        lease = self.dhcp.verify_and_lease(url, phase["q"], phase["p"])
        if lease.get("status") != "LOCKED":
            self.current_lock = False
            self.lbl_status.config(text="LOCKDOWN", fg="#ff5555")
            self.log(f"Lease abgelehnt: {lease.get('error')}")
            return
        self.active_target, self.current_lock = short, True
        self.contacts[short] = {"status": "ONLINE", **lease}
        self.lbl_status.config(text=f"VERBUNDEN | {url} | {lease['node_id']}", fg=self.accent)
        handshake = self._attach_qubit({"type": "handshake", "from": self.my_name, "to": short})
        self.burst.enqueue_now(handshake)
        self._refresh_contacts()

    def send_msg(self):
        text = self.entry_msg.get().strip()
        target = self.active_target or self.entry_target.get().strip().replace(PREFIX, "")
        if not text: return
        if not target:
            messagebox.showinfo("QFAN", "Bitte zuerst ein Ziel eingeben."); return
        if not self.current_lock: self.lock_target()
        packet = self._attach_qubit({"type": "msg", "from": self.my_name, "to": target,
                                      "text": text, "ts": time.time()})
        self.burst.enqueue(packet)
        self.log(f"Nachricht in die Queue für {target} gelegt")
        self.entry_msg.delete(0, tk.END)

    def _on_select(self, _event):
        selected = self.listbox.curselection()
        if selected:
            name = self.listbox.get(selected[0]).split()[0].replace(PREFIX, "")
            self.entry_target.delete(0, tk.END); self.entry_target.insert(0, name)

    def _refresh_contacts(self):
        self.listbox.delete(0, tk.END)
        for name, info in sorted(self.contacts.items()):
            self.listbox.insert(tk.END, f"{PREFIX}{name} [{info.get('node_id', '?')}] {info.get('qip', '')}")

    def _tick(self):
        try:
            self.bus.publish_presence({"qip": (self.my_lease or {}).get("qip"),
                                       "node_id": (self.my_lease or {}).get("node_id"),
                                       "role": "host" if self.is_host else "client",
                                       "takt_slot": self.takt.local_slot()})
            self.bus.send(self.takt.make_pulse(name=self.my_name))
            for peer in self.bus.scan_presence():
                name = peer.get("name")
                if name and name != self.my_name and name not in self.contacts:
                    phase = self.qdns.resolve(f"{PREFIX}{name}")
                    lease = self.dhcp.verify_and_lease(f"{PREFIX}{name}", phase["q"], phase["p"])
                    if lease.get("status") == "LOCKED":
                        self.contacts[name] = {"status": "ONLINE", **lease}
                        self._refresh_contacts()
            for packet in self.bus.receive(): self._handle_packet(packet)
        except Exception as exc:
            self.log(f"[CARRIER ERROR] {exc}")
        self.root.after(400, self._tick)

    def _handle_packet(self, packet: dict):
        sender, kind = packet.get("from", "?"), packet.get("type")
        if kind == "takt_sync":
            self.takt.observe(packet); return
        if kind == "presence":
            name = packet.get("name") or sender
            if name and name != self.my_name and name not in self.contacts:
                self.contacts[name] = {"status": "ONLINE", "qip": packet.get("qip"), "node_id": packet.get("node_id")}
                self._refresh_contacts()
            return
        if kind == "handshake":
            q, p = packet.get("q"), packet.get("p")
            if q is None or p is None:
                self.log(f"Handshake von {sender} ohne Phasenvektor verworfen"); return
            lease = self.dhcp.verify_and_lease(f"{PREFIX}{sender}", q, p)
            if lease.get("status") == "LOCKED":
                self.contacts[sender] = {"status": "ONLINE", **lease}; self._refresh_contacts()
                self.log(f"Software-Handshake von {sender} akzeptiert")
            else: self.log(f"Handshake von {sender} verworfen: {lease.get('error')}")
            return
        if kind == "msg":
            q, p = packet.get("q"), packet.get("p")
            if q is not None and p is not None and not self.core.liouville_check(q, p)["ok"]:
                self.log(f"Nachricht von {sender} wegen ungültigem Vektor verworfen"); return
            self.log(f"Empfang von {sender}: {packet.get('text', '')} ({packet.get('_substrate', '?')})")
            return
        self.log(f"Unbekannter Frame von {sender}: {kind}")

    def export_report(self):
        out = ROOT / "logs" / f"report_{self.my_name}_{int(time.time())}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(["QFAN report", f"Node: {self.full_id}", f"Lease: {self.my_lease}",
                                   f"Contacts: {self.contacts}"]), encoding="utf-8")
        self.log(f"Report gespeichert: {out}")
        messagebox.showinfo("Report", str(out))

    def _close(self):
        try: self.burst.close()
        finally:
            self.bus.close()
            if self.analyzer: self.analyzer.close()
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="QFAN desktop prototype")
    parser.add_argument("--role", choices=("host", "client"), default=None)
    parser.add_argument("--name")
    parser.add_argument("--path", default=str(DEFAULT_MAILBOX))
    parser.add_argument("--no-file", action="store_true")
    parser.add_argument("--target", default="")
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args(argv)
    root = tk.Tk(); root.withdraw()
    role, name = args.role, args.name
    if role is None:
        role = "host" if messagebox.askyesno("QFAN", "Als Host starten?") else "client"
    if not name:
        name = "nexus" if role == "host" else simpledialog.askstring("QFAN", "Client-Name:")
    if not name:
        root.destroy(); return
    root.deiconify()
    mailbox = None if args.no_file else Path(args.path)
    QFANApp(root, name, role, mailbox, args.target, args.analyze)
    root.mainloop()


if __name__ == "__main__":
    main()
