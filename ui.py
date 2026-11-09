"""
QFAN Workstation — Desktop-Oberfläche für Host (Server · Nexus, cyan) und Client (Browser, orange).
Links: Feld-Knoten (Presence) und Vault. Rechts: Feld-Stream. Beim Login eines Knotens poppt eine Meldung auf.
"""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

from qfan.engine import FieldEngine
from qfan.qdns import PREFIX

HOST_ACCENT, CLIENT_ACCENT = "#00ffcc", "#ff9f43"


class Workstation:
    def __init__(self, root: tk.Tk, engine: FieldEngine):
        self.root, self.eng = root, engine
        self.is_host = engine.is_host
        self.accent = HOST_ACCENT if self.is_host else CLIENT_ACCENT
        self.role_label = "QFAN Server · Nexus" if self.is_host else "QFAN Client Browser"
        self._rows: list = []                 # Knotennamen passend zu den Listbox-Zeilen
        self._contacts: dict = {}
        self._vault_names: list = []
        self._popups: list = []

        root.title(f"{self.role_label} — {engine.full_id}")
        root.geometry("1150x720")
        root.minsize(860, 540)
        root.configure(bg="#0d0d0d")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build_menu()
        self._build_ui()
        self.engine_started = False

        self.sys(f"{self.role_label} '{engine.name}' bereit · Substrate: {', '.join(engine.substrates()) or '—'}")
        for line in engine.hardware():
            self.sys(f"[HARDWARE] {line}")
        if self.is_host:
            self.refresh_vault_from_host()
        engine.start()
        root.after(150, self._poll)
        root.after(1000, self._status_tick)

    # ------------------------------------------------------------------ Aufbau
    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)
        file_m = tk.Menu(bar, tearoff=0)
        if self.is_host:
            file_m.add_command(label="Datei im Vault freigeben…", command=self.share_file)
        else:
            file_m.add_command(label="Vault aktualisieren", command=self.eng.refresh_files)
        file_m.add_command(label="Telemetrie exportieren…", command=self.export_telemetry)
        file_m.add_separator()
        file_m.add_command(label="Beenden", command=self.close)
        bar.add_cascade(label="Datei", menu=file_m)
        edit_m = tk.Menu(bar, tearoff=0)
        edit_m.add_command(label="Feld-Stream leeren", command=self.clear_log)
        bar.add_cascade(label="Bearbeiten", menu=edit_m)
        view_m = tk.Menu(bar, tearoff=0)
        view_m.add_command(label="Telemetrie-Übersicht", command=self.show_telemetry)
        view_m.add_command(label="WORM-Ledger prüfen", command=self.check_ledger)
        view_m.add_command(label="Substrate / Hardware", command=self.show_hardware)
        bar.add_cascade(label="Ansicht", menu=view_m)
        self.root.config(menu=bar)

    def _build_ui(self) -> None:
        acc = self.accent
        top = tk.Frame(self.root, bg="#161616")
        top.pack(fill=tk.X, padx=6, pady=6)
        tk.Label(top, text=self.role_label, font=("Consolas", 11, "bold"), fg=acc, bg="#161616").pack(side=tk.LEFT, padx=8)
        tk.Label(top, text=self.eng.full_id, font=("Consolas", 10), fg="#aaaaaa", bg="#161616").pack(side=tk.LEFT, padx=8)
        self.lbl_target = tk.Label(top, text="Ziel: alle", font=("Consolas", 10, "bold"), fg=acc, bg="#161616")
        self.lbl_target.pack(side=tk.RIGHT, padx=8)
        tk.Button(top, text="An alle", font=("Consolas", 9), bg="#1e3a5f", fg="#7dd3fc",
                  command=self.clear_selection).pack(side=tk.RIGHT, padx=4)

        self.lbl_status = tk.Label(self.root, text="STATUS: —", font=("Consolas", 9, "bold"),
                                   fg=acc, bg="#0d0d0d", anchor="w")
        self.lbl_status.pack(fill=tk.X, padx=10)
        self.lbl_qip = tk.Label(self.root, text="", font=("Consolas", 9), fg="#9ca3af", bg="#0d0d0d", anchor="w")
        self.lbl_qip.pack(fill=tk.X, padx=10)

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a", sashwidth=5)
        paned.pack(expand=True, fill=tk.BOTH, padx=8, pady=4)

        left = tk.Frame(paned, bg="#121212")
        paned.add(left, minsize=270)
        tk.Label(left, text="FELD-KNOTEN", font=("Consolas", 9, "bold"), fg="#fff", bg="#121212").pack(anchor="w", padx=8, pady=(8, 2))
        self.listbox = tk.Listbox(left, font=("Consolas", 10), bg="#1a1a1a", fg="#9ca3af", selectbackground=acc,
                                  selectforeground="#000", bd=0, highlightthickness=0, activestyle="none", exportselection=False)
        self.listbox.pack(expand=True, fill=tk.BOTH, padx=8, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        tk.Label(left, text="FELD-VAULT (Doppelklick = abrufen)" if not self.is_host else "FELD-VAULT (freigegebene Dateien)",
                 font=("Consolas", 9, "bold"), fg="#fff", bg="#121212").pack(anchor="w", padx=8, pady=(6, 2))
        self.vault_list = tk.Listbox(left, font=("Consolas", 10), bg="#1a1a1a", fg="#9ca3af", selectbackground=acc,
                                     selectforeground="#000", bd=0, highlightthickness=0, height=7, exportselection=False)
        self.vault_list.pack(fill=tk.X, padx=8, pady=(2, 8))
        if not self.is_host:
            self.vault_list.bind("<Double-Button-1>", self.download_selected)

        right = tk.Frame(paned, bg="#0d0d0d")
        paned.add(right, minsize=520)
        self.log_view = scrolledtext.ScrolledText(right, wrap=tk.WORD, font=("Consolas", 10), bg="#0a0a0a",
                                                  fg=acc, insertbackground=acc, state=tk.DISABLED)
        self.log_view.pack(expand=True, fill=tk.BOTH)
        self.log_view.tag_config("sys", foreground="#6b7280")
        self.log_view.tag_config("in", foreground=acc)
        self.log_view.tag_config("out", foreground="#ffffff")
        self.log_view.tag_config("warn", foreground="#ff5555")

        bottom = tk.Frame(self.root, bg="#161616")
        bottom.pack(fill=tk.X, padx=6, pady=6)
        self.entry_msg = tk.Entry(bottom, font=("Consolas", 11), bg="#222", fg="#fff", insertbackground="#fff")
        self.entry_msg.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4)
        self.entry_msg.bind("<Return>", lambda e: self.send())
        self.btn_send = tk.Button(bottom, text="Ins Feld senden", font=("Consolas", 9, "bold"), bg=acc, fg="#000", command=self.send)
        self.btn_send.pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------ Log
    def _write(self, text: str, tag: str) -> None:
        self.log_view.config(state=tk.NORMAL)
        self.log_view.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {text}\n", tag)
        self.log_view.see(tk.END)
        self.log_view.config(state=tk.DISABLED)

    def sys(self, text: str) -> None:
        self._write(text, "warn" if text.startswith(("[GATE]", "[LOCKDOWN]")) else "sys")

    def clear_log(self) -> None:
        self.log_view.config(state=tk.NORMAL)
        self.log_view.delete("1.0", tk.END)
        self.log_view.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ Ereignisse
    def _poll(self) -> None:
        try:
            while True:
                self.handle(self.eng.events.get_nowait())
        except Exception as exc:
            if type(exc).__name__ != "Empty":
                self.sys(f"[UI] {exc!r}")
        self.root.after(150, self._poll)

    def handle(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "log":
            self.sys(ev[1])
        elif kind == "online":
            _, name, info, initial = ev
            self._contacts[name] = dict(info, online=True)
            self.refresh_contacts()
            if not initial and name != self.eng.host_name:
                self.popup(f"🟢  {PREFIX}{name} ist jetzt online")
        elif kind == "offline":
            if ev[1] in self._contacts:
                self._contacts[ev[1]]["online"] = False
            self.refresh_contacts()
        elif kind == "connected":
            info = ev[1]
            self.popup(f"🔗  Verbunden mit {PREFIX}{info.get('host')}  ·  {info.get('node_id')}")
            self.update_status()
        elif kind == "host_lost":
            self.popup("⚠  Verbindung zum Host verloren")
            self.update_status()
        elif kind == "denied":
            self.lbl_status.config(text=f"STATUS: LOCKDOWN — {ev[1]}", fg="#ff5555")
        elif kind == "msg":
            _, origin, text, dest, _ts = ev
            where = "" if dest in ("*", "") else f" → {dest}"
            self._write(f"{PREFIX}{origin}{where}: {text}", "in")
        elif kind == "files":
            self.set_vault(ev[1])
        elif kind == "file_done":
            self.sys(f"[VAULT] '{ev[1]}' gespeichert: {ev[2]}")
            self.popup(f"📦  {ev[1]} abgerufen")
        elif kind == "file_error":
            self.sys(f"[LOCKDOWN] Vault '{ev[1]}': {ev[2]}")
        elif kind == "file_progress":
            self.lbl_qip.config(text=f"Download {ev[1]}: {ev[2]}/{ev[3]} Chunks")

    def popup(self, text: str) -> None:
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(pop, text=text, font=("Consolas", 11, "bold"), fg="#000000", bg=self.accent, padx=20, pady=14).pack()
        pop.update_idletasks()
        idx = len([p for p in self._popups if p.winfo_exists()])
        x = self.root.winfo_x() + self.root.winfo_width() - pop.winfo_width() - 25
        y = self.root.winfo_y() + self.root.winfo_height() - pop.winfo_height() - 70 - idx * 60
        pop.geometry(f"+{x}+{y}")
        self._popups.append(pop)
        pop.after(4000, pop.destroy)

    # ------------------------------------------------------------------ Knotenliste
    def refresh_contacts(self) -> None:
        self.listbox.delete(0, tk.END)
        self._rows = []
        for name in sorted(self._contacts, key=lambda n: (not self._contacts[n].get("online"), n)):
            c = self._contacts[name]
            on = c.get("online")
            node = c.get("node_id") or ""
            via = f" via {c['via']}" if c.get("via") and on else ""
            self.listbox.insert(tk.END, f"{'🟢' if on else '⚫'}  {PREFIX}{name}  [{node}]{via}")
            self.listbox.itemconfig(tk.END, fg=self.accent if on else "#6b7280")
            self._rows.append(name)
        self.update_status()

    def _on_select(self, _evt=None) -> None:
        sel = self.listbox.curselection()
        self.lbl_target.config(text=f"Ziel: {self._rows[sel[0]]}" if sel and sel[0] < len(self._rows) else "Ziel: alle")

    def clear_selection(self) -> None:
        self.listbox.selection_clear(0, tk.END)
        self.lbl_target.config(text="Ziel: alle")

    def selected_target(self) -> str:
        sel = self.listbox.curselection()
        return self._rows[sel[0]] if sel and sel[0] < len(self._rows) else "*"

    # ------------------------------------------------------------------ Aktionen
    def send(self) -> None:
        text = self.entry_msg.get().strip()
        if not text:
            return
        dest = self.selected_target()
        label = "alle" if dest == "*" else dest
        if self.is_host:
            n = self.eng.say(text, dest)
            if n:
                self._write(f"Du → {label}: {text}", "out")
            else:
                self.sys(f"[FELD] Niemand erreichbar ({label}) — Nachricht nicht gesendet")
                return
        else:
            if not self.eng.connected:
                self.sys("[FELD] Noch nicht mit dem Host verbunden — Nachricht nicht gesendet")
                return
            self.eng.say_to(text, dest)
            self._write(f"Du → {label}: {text}", "out")
        self.entry_msg.delete(0, tk.END)

    def share_file(self) -> None:
        path = filedialog.askopenfilename(title="Datei im Vault freigeben")
        if not path:
            return
        try:
            self.eng.share_file(path)
        except (OSError, ValueError) as exc:
            messagebox.showwarning("Vault", f"Datei konnte nicht freigegeben werden:\n{exc}")
            return
        self.refresh_vault_from_host()

    def refresh_vault_from_host(self) -> None:
        self.set_vault(self.eng.vault.list_info())

    def set_vault(self, files: list) -> None:
        self.vault_list.delete(0, tk.END)
        self._vault_names = []
        for f in files:
            self.vault_list.insert(tk.END, f"📦 {f['name']}  ({self._size(f.get('size', 0))})")
            self._vault_names.append(f["name"])

    @staticmethod
    def _size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return ""

    def download_selected(self, _evt=None) -> None:
        sel = self.vault_list.curselection()
        if not sel or sel[0] >= len(self._vault_names):
            return
        name = self._vault_names[sel[0]]
        dest = filedialog.asksaveasfilename(title="Datei aus dem Feld abrufen", initialfile=name)
        if not dest:
            return
        if self.eng.download(name, dest):
            self.sys(f"[VAULT] Abruf von '{name}' gestartet")
        else:
            self.sys("[VAULT] Nicht mit dem Host verbunden")

    def export_telemetry(self) -> None:
        path = filedialog.asksaveasfilename(title="Telemetrie exportieren", defaultextension=".log",
                                            initialfile=f"qfan_telemetrie_{self.eng.name}.log")
        if path:
            out = self.eng.telemetry.export(path)
            self.sys(f"[ANALYSE] Telemetrie exportiert: {out}")

    def show_telemetry(self) -> None:
        messagebox.showinfo("QFAN Telemetrie", self.eng.telemetry.format_summary())

    def check_ledger(self) -> None:
        ok, bad = self.eng.ledger.verify_integrity()
        msg = f"WORM-Ledger: {len(self.eng.ledger)} Blöcke\n" + ("Kette lückenlos, Integrität OK." if ok else f"FEHLER ab Block {bad}!")
        messagebox.showinfo("QFAN WORM-Ledger", msg) if ok else messagebox.showerror("QFAN WORM-Ledger", msg)

    def show_hardware(self) -> None:
        messagebox.showinfo("QFAN Substrate", "\n".join(self.eng.hardware()) or "—")

    # ------------------------------------------------------------------ Status
    def update_status(self) -> None:
        s = self.eng.status()
        if self.is_host:
            self.lbl_status.config(text=f"STATUS: ONLINE  |  {s['peers']} Client(s)  |  Substrate: {', '.join(s['substrates'])}"
                                        f"  |  Ledger {s['ledger']}", fg=self.accent)
            self.lbl_qip.config(text=f"Frames: ↑{s['tx']} ↓{s['rx']}")
        elif s["connected"]:
            self.lbl_status.config(text=f"STATUS: VERBUNDEN  |  {PREFIX}{s['host']}  |  {s['node_id']}  |  via {s['via']}",
                                   fg=self.accent)
            self.lbl_qip.config(text=f"QIP: {s['qip']}   Frames: ↑{s['tx']} ↓{s['rx']}")
        else:
            self.lbl_status.config(text=f"STATUS: SUCHE HOST {PREFIX}{s['host']} …  |  Substrate: {', '.join(s['substrates'])}",
                                   fg="#ff9f43")

    def _status_tick(self) -> None:
        self.update_status()
        self.root.after(1000, self._status_tick)

    def close(self) -> None:
        try:
            self.eng.stop()
        finally:
            self.root.destroy()
