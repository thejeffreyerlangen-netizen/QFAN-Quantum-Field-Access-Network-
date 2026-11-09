"""CLI for inspecting QFAN analyzer JSONL files."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .analyzer import LOG_DIR


def load(path):
    events = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            try: events.append(json.loads(line))
            except ValueError: continue
    return events


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main(argv=None):
    parser = argparse.ArgumentParser(description="QFAN Analyzer")
    sub = parser.add_subparsers(dest="command", required=True)
    files = sub.add_parser("files")
    files.set_defaults(action="files")
    for name in ("summary", "substrate", "errors", "qips", "timeline", "live"):
        cmd = sub.add_parser(name); cmd.add_argument("path"); cmd.set_defaults(action=name)
    args = parser.parse_args(argv)
    if args.action == "files":
        for path in sorted(LOG_DIR.glob("*.jsonl")):
            print(f"{path.name:<50} {path.stat().st_size:>10} Byte")
        return
    events = load(args.path)
    if args.action == "summary":
        print(f"Log: {args.path}\nEvents: {len(events)}")
        if events:
            print(f"Zeitraum: {fmt_ts(events[0]['ts'])} -> {fmt_ts(events[-1]['ts'])}")
            print("Event-Verteilung:")
            for event, count in Counter(item.get("event") for item in events).most_common(): print(f"  {event:<20} {count}")
    elif args.action == "errors":
        bad = [e for e in events if e.get("event") in ("error", "qgate_reject", "liouville_reject")]
        for event in bad[:200]: print(f"{fmt_ts(event['ts'])} | {event.get('substrate') or '-':<12} | {event.get('event')} | {event.get('raw', '')[:100]}")
        if not bad: print("Keine Fehler im Log.")
    elif args.action in ("timeline", "live"):
        for event in events: print(f"{fmt_ts(event['ts'])} | {event.get('substrate') or '-':<12} | {event.get('event')} | {event.get('raw', '')[:120]}")
    elif args.action == "substrate":
        counts = Counter((e.get("substrate") or "-", e.get("event")) for e in events)
        for key, count in sorted(counts.items()): print(f"{key[0]:<15} {key[1]:<20} {count}")
    elif args.action == "qips":
        qips = sorted({str(v) for e in events for v in (e.get("parsed") or {}).values() if str(v).startswith("QIP-")})
        print("\n".join(qips) if qips else "Keine QIPs gesehen.")


if __name__ == "__main__":
    main()
