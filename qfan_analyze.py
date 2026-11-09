#!/usr/bin/env python3
"""QFAN Analyzer CLI — liest qfan_*.jsonl und wertet aus.

  summary | substrate | errors | timeline | qips | live | files
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "qfan_logs"))


def load(path: str):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def cmd_summary(path: str):
    ev = load(path)
    if not ev:
        print("Leer.")
        return
    print(f"Log: {path}")
    print(f"Events: {len(ev)}")
    print(f"Zeitraum: {fmt_ts(ev[0]['ts'])}  ->  {fmt_ts(ev[-1]['ts'])}")
    dur = ev[-1]["ts"] - ev[0]["ts"]
    print(f"Dauer: {dur:.1f} s | Rate: {len(ev)/max(dur, 0.001):.1f} events/s")
    print()
    print("Event-Verteilung:")
    for name, count in Counter(e["event"] for e in ev).most_common():
        print(f"  {name:<20} {count}")
    print()
    print("Substrat-Verteilung:")
    for name, count in Counter(e.get("substrate") for e in ev if e.get("substrate")).most_common():
        print(f"  {name:<20} {count}")
    dets = [
        e["parsed"]["det_j"]
        for e in ev
        if e.get("parsed") and isinstance(e["parsed"].get("det_j"), (int, float))
    ]
    if dets:
        print(
            f"\ndet(J): min={min(dets):.6f} max={max(dets):.6f} "
            f"avg={sum(dets)/len(dets):.6f} n={len(dets)}"
        )
    qips = set()
    for e in ev:
        p = e.get("parsed") or {}
        for k in ("sender", "target", "qip", "from"):
            v = p.get(k)
            if v and str(v).startswith("QIP"):
                qips.add(v)
            if k == "qip" and v:
                qips.add(v)
    if qips:
        print(f"Gesehene QIPs ({len(qips)}): {sorted(qips)}")


def cmd_substrate(path: str):
    ev = load(path)
    stats = defaultdict(
        lambda: {"send": 0, "recv": 0, "reject": 0, "error": 0, "handshake": 0, "last": None}
    )
    for e in ev:
        s = e.get("substrate") or "-"
        st = stats[s]
        st["last"] = e["ts"]
        if e["event"] == "send":
            st["send"] += 1
        elif e["event"] == "recv":
            st["recv"] += 1
        elif e["event"] in ("qgate_reject", "liouville_reject"):
            st["reject"] += 1
        elif e["event"] == "error":
            st["error"] += 1
        elif e["event"] == "handshake":
            st["handshake"] += 1
    print(f"{'Substrat':<15} {'Send':>6} {'Recv':>6} {'HS':>6} {'Reject':>7} {'Error':>6} {'Letzter':<24}")
    print("-" * 80)
    for name in sorted(stats):
        st = stats[name]
        print(
            f"{name:<15} {st['send']:>6} {st['recv']:>6} {st['handshake']:>6} "
            f"{st['reject']:>7} {st['error']:>6} {fmt_ts(st['last'])}"
        )


def cmd_errors(path: str):
    ev = load(path)
    errs = [e for e in ev if e["event"] in ("qgate_reject", "liouville_reject", "error")]
    if not errs:
        print("Keine Fehler im Log.")
        return
    print(f"{len(errs)} Fehler-Events:")
    for e in errs[:200]:
        print(
            f"{fmt_ts(e['ts'])} | {e.get('substrate') or '-':<12} | "
            f"{e['event']:<18} | {e['raw'][:100]}"
        )


def cmd_timeline(path: str, substrate=None, event=None):
    ev = load(path)
    if substrate:
        ev = [e for e in ev if e.get("substrate") == substrate]
    if event:
        ev = [e for e in ev if e["event"] == event]
    for e in ev:
        print(
            f"{fmt_ts(e['ts'])} | {e.get('substrate') or '-':<12} | "
            f"{e['event']:<15} | {e['raw'][:120]}"
        )


def cmd_qips(path: str):
    ev = load(path)
    seen = defaultdict(lambda: {"first": None, "last": None, "count": 0})
    for e in ev:
        p = e.get("parsed") or {}
        candidates = []
        for key in ("sender", "target", "qip", "from"):
            if key in p and p[key]:
                candidates.append(str(p[key]))
        # auch aus raw ziehen
        import re
        for m in re.finditer(r"QIP-[\dA-Fa-f\-]+", e.get("raw", "")):
            candidates.append(m.group(0))
        for qip in candidates:
            if not qip.startswith("QIP"):
                continue
            seen[qip]["first"] = seen[qip]["first"] or e["ts"]
            seen[qip]["last"] = e["ts"]
            seen[qip]["count"] += 1
    if not seen:
        print("Keine QIPs gesehen.")
        return
    print(f"{'QIP':<22} {'Anzahl':>7} {'Erstes Mal':<24} {'Letztes Mal':<24}")
    print("-" * 80)
    for qip in sorted(seen):
        s = seen[qip]
        print(f"{qip:<22} {s['count']:>7} {fmt_ts(s['first'])} {fmt_ts(s['last'])}")


def cmd_live(path: str):
    pos = 0
    print(f"Live-Tail: {path}  (Strg+C zum Beenden)")
    try:
        while True:
            if not os.path.exists(path):
                time.sleep(0.5)
                continue
            size = os.path.getsize(path)
            if size < pos:
                pos = 0
            if size > pos:
                with open(path, "r", encoding="utf-8") as f:
                    f.seek(pos)
                    for line in f:
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        sub = e.get("substrate") or "-"
                        print(
                            f"{fmt_ts(e['ts'])} | {sub:<12} | "
                            f"{e['event']:<15} | {e['raw'][:110]}"
                        )
                    pos = f.tell()
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass


def cmd_files():
    if not os.path.isdir(LOG_DIR):
        print(f"Log-Verzeichnis existiert nicht: {LOG_DIR}")
        return
    for name in sorted(os.listdir(LOG_DIR)):
        if not name.endswith(".jsonl"):
            continue
        p = os.path.join(LOG_DIR, name)
        print(f"{name:<50} {os.path.getsize(p):>10} Byte")


def main():
    p = argparse.ArgumentParser(description="QFAN Analyzer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("files").set_defaults(func=lambda a: cmd_files())
    for name, fn in [
        ("summary", cmd_summary),
        ("substrate", cmd_substrate),
        ("errors", cmd_errors),
        ("qips", cmd_qips),
        ("live", cmd_live),
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("path")
        sp.set_defaults(func=lambda a, fn=fn: fn(a.path))
    sp_tl = sub.add_parser("timeline")
    sp_tl.add_argument("path")
    sp_tl.add_argument("--substrate", default=None)
    sp_tl.add_argument("--event", default=None)
    sp_tl.set_defaults(func=lambda a: cmd_timeline(a.path, a.substrate, a.event))
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
