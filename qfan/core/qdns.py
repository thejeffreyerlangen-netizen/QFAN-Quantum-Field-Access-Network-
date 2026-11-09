"""Q-DNS: deterministic local name-to-phase mapping (not Internet DNS)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

PREFIX = "qfan.de/"
LEDGER = Path(__file__).resolve().parents[2] / "logs" / "qdns_ledger.jsonl"


def normalize(name: str) -> str:
    value = (name or "").strip().lower()
    if value.startswith("qfan://"):
        value = value[len("qfan://"):]
    return value if value.startswith(PREFIX) else f"{PREFIX}{value}" if value else PREFIX


def name_to_phase(name: str):
    digest = hashlib.sha256(normalize(name).encode("utf-8")).digest()
    vals = [(int.from_bytes(digest[i * 4:(i + 1) * 4], "big") / 2**32 - .5) * 2 for i in range(6)]
    q = np.array(vals[:3], dtype=float) * 1.618 + np.array([.1, .2, .3])
    p = np.array(vals[3:], dtype=float) * .577 + np.array([.05, -.1, .15])
    torsion = np.zeros(27, dtype=float)
    torsion[0] = vals[0]
    return q, p, torsion


class QDNS:
    def __init__(self, ledger: Optional[Path] = None):
        self.ledger = Path(ledger) if ledger is not None else LEDGER
        self._registry: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.ledger.exists():
            return
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                self._registry[row["name"]] = row
            except (ValueError, KeyError):
                continue

    def register(self, name: str, meta: Optional[dict] = None) -> dict:
        key = normalize(name)
        q, p, torsion = name_to_phase(key)
        row = {"name": key, "q": q.tolist(), "p": p.tolist(), "torsion": torsion.tolist(),
               "label": key.split("/")[-1], "source": "registry", **(meta or {})}
        self._registry[key] = row
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def resolve(self, name: str) -> dict:
        key = normalize(name)
        if key in self._registry:
            data = self._registry[key]
            return {"name": key, "q": np.array(data["q"], dtype=float), "p": np.array(data["p"], dtype=float),
                    "torsion": np.array(data.get("torsion", [0.] * 27), dtype=float),
                    "label": data.get("label", key.split("/")[-1]), "source": data.get("source", "registry")}
        q, p, torsion = name_to_phase(key)
        return {"name": key, "q": q, "p": p, "torsion": torsion,
                "label": key.split("/")[-1], "source": "derived"}

    def contacts(self) -> List[dict]:
        names = ["qfan.de/nexus", "qfan.de/jan", "qfan.de/alpha", "qfan.de/secure", *self._registry]
        return [{"url": name, "label": name.split("/")[-1]} for name in dict.fromkeys(names)]
