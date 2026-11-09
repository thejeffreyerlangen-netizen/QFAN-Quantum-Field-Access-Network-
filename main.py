#!/usr/bin/env python3
"""
QFAN — Einstieg für Host-Server und Client-Browser.

  Host (Desktop):     python -m qfan --role host
  Host (Server):      python -m qfan --role host --headless
  Client (Desktop):   python -m qfan --role client --name jan --hub 203.0.113.5
  Client (gleiches Netz): python -m qfan --role client --name jan --hub auto
  Client (Sync-Ordner):   python -m qfan --role client --name jan --path D:\\Sync\\qfan_mailbox
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from qfan.engine import NAME_RE, FieldEngine, clean_name
from qfan.hub import DEFAULT_HUB_PORT


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="qfan", description="QFAN Feld-Netzwerk — Host-Server und Client-Browser")
    ap.add_argument("--role", choices=("host", "client"))
    ap.add_argument("--name", help="Knotenname (qfan.de/<name>)")
    ap.add_argument("--host-name", default="nexus", help="Name des Hosts (Client), Standard: nexus")
    ap.add_argument("--hub", metavar="ADRESSE", help="Client: Host-Adresse IP[:Port] für andere Netze, 'auto' = Suche im LAN")
    ap.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT, help=f"UDP-Feld-Port (Standard {DEFAULT_HUB_PORT})")
    ap.add_argument("--no-hub", action="store_true", help="Host: nicht auf dem Hub-Port lauschen")
    ap.add_argument("--path", help="Gemeinsamer Feldordner (file-Substrat, z. B. Syncthing/NAS)")
    ap.add_argument("--no-file", action="store_true", help="Ohne file-Substrat")
    ap.add_argument("--lan", action="store_true", help="Zusätzlich LAN-Broadcast-Substrat (adapter)")
    ap.add_argument("--headless", action="store_true", help="Ohne Oberfläche (Server-Betrieb, Befehle über Tastatur)")
    ap.add_argument("--data-dir", help="Ordner für Ledger, Vault, Konfiguration")
    ap.add_argument("--analyze", action="store_true", help="Hintergrund-Analyse (JSONL in qfan_logs/)")
    return ap.parse_args(argv)


def build_engine(args, hub_addr: Optional[str]) -> FieldEngine:
    data_dir = Path(args.data_dir) if args.data_dir else app_dir() / "qfan_data"
    mailbox = None if args.no_file else Path(args.path) if args.path else app_dir() / "field_mailbox"
    analyzer = None
    if args.analyze:
        from qfan.qfan_analyzer import AnalysisSession
        analyzer = AnalysisSession()
    return FieldEngine(
        args.name, args.role, host_name=args.host_name, mailbox=mailbox, use_file=not args.no_file,
        hub_listen=not args.no_hub, hub_addr=hub_addr, hub_port=args.hub_port, use_lan=args.lan,
        data_dir=data_dir, analyzer=analyzer,
    )


# ---------------------------------------------------------------------- Headless
HELP = """Befehle:  /say <text>   /to <name> <text>   /who   /share <datei>   /files   /get <datei> [ziel]
          /ledger   /stats   /stress [n]   /quit        (Text ohne / geht an alle)"""


def run_headless(eng: FieldEngine) -> None:
    from qfan.telemetry import simulate_stress

    stop = threading.Event()

    def printer():
        while not stop.is_set():
            try:
                ev = eng.events.get(timeout=0.3)
            except Exception:
                continue
            k = ev[0]
            ts = time.strftime("%H:%M:%S")
            if k == "log":
                print(f"[{ts}] {ev[1]}")
            elif k == "online":
                print(f"[{ts}] 🟢 {ev[1]} online" + (" (bereits da)" if ev[3] else ""))
            elif k == "offline":
                print(f"[{ts}] ⚫ {ev[1]} offline")
            elif k == "connected":
                print(f"[{ts}] 🔗 verbunden: {ev[1].get('node_id')} via {ev[1].get('via')}")
            elif k == "msg":
                print(f"[{ts}] {ev[1]}{'' if ev[3] in ('*', '') else ' → ' + ev[3]}: {ev[2]}")
            elif k == "files":
                print(f"[{ts}] Vault: " + (", ".join(f"{f['name']} ({f['size']} B)" for f in ev[1]) or "leer"))
            elif k in ("file_done", "file_error", "denied", "host_lost"):
                print(f"[{ts}] {ev}")

    threading.Thread(target=printer, daemon=True).start()
    eng.start()
    print(f"QFAN {'Host-Server' if eng.is_host else 'Client'} {eng.full_id} läuft. {HELP}")
    try:
        while True:
            try:
                line = input()
            except EOFError:
                while True:
                    time.sleep(1)
            line = line.strip()
            if not line:
                continue
            if not line.startswith("/"):
                _say(eng, "*", line)
                continue
            cmd, _, rest = line[1:].partition(" ")
            rest = rest.strip()
            if cmd == "quit":
                break
            elif cmd == "say":
                _say(eng, "*", rest)
            elif cmd == "to":
                who, _, text = rest.partition(" ")
                _say(eng, clean_name(who), text)
            elif cmd == "who":
                for n, i in eng.online_peers().items():
                    print(f"  🟢 {n}  {i.get('node_id')}  {i.get('qip')}  via {i.get('via')}")
            elif cmd == "share" and eng.is_host:
                try:
                    eng.share_file(rest.strip('"'))
                except (OSError, ValueError) as exc:
                    print(f"Fehler: {exc}")
            elif cmd == "files":
                if eng.is_host:
                    print(", ".join(f"{f['name']} ({f['size']} B)" for f in eng.vault.list_info()) or "Vault leer")
                else:
                    eng.refresh_files()
            elif cmd == "get" and not eng.is_host:
                name, _, dest = rest.partition(" ")
                eng.download(name, dest.strip() or Path("downloads") / name)
            elif cmd == "ledger":
                ok, bad = eng.ledger.verify_integrity()
                print(f"Ledger: {len(eng.ledger)} Blöcke — " + ("OK" if ok else f"FEHLER ab Block {bad}"))
            elif cmd == "stats":
                print(eng.status())
                print(eng.telemetry.format_summary())
            elif cmd == "stress":
                n = int(rest) if rest.isdigit() else 1000
                print(simulate_stress(n).format_summary())
            else:
                print(HELP)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        eng.stop()


def _say(eng: FieldEngine, dest: str, text: str) -> None:
    if not text:
        return
    if eng.is_host:
        n = eng.say(text, dest or "*")
        print(f"→ {n} Empfänger")
    else:
        print("→ gesendet" if eng.say_to(text, dest or "*") else "→ nicht verbunden")


# ---------------------------------------------------------------------- GUI
def run_gui(args) -> None:
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    from qfan.ui import Workstation

    root = tk.Tk()
    root.withdraw()
    data_dir = Path(args.data_dir) if args.data_dir else app_dir() / "qfan_data"
    cfg_path = data_dir / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}

    role = args.role
    if role is None:
        role = "host" if messagebox.askquestion("QFAN", "Als Host-Server starten?\n\nJa = Host (cyan)\nNein = Client (orange)") == "yes" else "client"
        args.role = role
    name = clean_name(args.name or "")
    if not name:
        default = "nexus" if role == "host" else cfg.get("client_name", "")
        name = clean_name(simpledialog.askstring("QFAN", "Knotenname (qfan.de/<name>):", initialvalue=default) or "")
    if not NAME_RE.match(name):
        messagebox.showerror("QFAN", "Ungültiger Name (a-z, 0-9, _ -).")
        root.destroy()
        return
    args.name = name

    hub_addr = args.hub
    if role == "client" and hub_addr is None and not args.path:
        ans = simpledialog.askstring(
            "QFAN Client",
            "Host-Adresse (IP[:Port]) für Verbindung über andere Netze,\n'auto' = Host im lokalen Netz suchen,\nleer = nur gemeinsamer Feldordner:",
            initialvalue=cfg.get("hub", "auto"))
        hub_addr = (ans or "").strip() or None
    if role == "client":
        cfg.update({"client_name": name, "hub": hub_addr or ""})
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    try:
        eng = build_engine(args, hub_addr)
    except (ValueError, OSError) as exc:
        messagebox.showerror("QFAN", str(exc))
        root.destroy()
        return
    root.deiconify()
    Workstation(root, eng)
    root.mainloop()


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.headless:
        if not args.role or not args.name:
            args.role = args.role or "host"
            args.name = args.name or ("nexus" if args.role == "host" else "")
        if not args.name:
            sys.exit("Headless-Client braucht --name")
        run_headless(build_engine(args, args.hub))
    else:
        run_gui(args)


if __name__ == "__main__":
    main()
