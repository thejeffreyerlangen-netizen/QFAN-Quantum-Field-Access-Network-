"""Q-DNS — Name → Phasenraum-Vektor (keine klassischen DNS/IPs)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

PREFIX = "qfan.de/"
LEDGER = Path(__file__).resolve().parent / "logs" / "qdns_ledger.jsonl"


def normalize(name: str) -> str:
    n = (name or "").strip().lower()
    if n.startswith("qfan.de/"):
        return n
    if n.startswith("qfan://"):
        n = n.replace("qfan://", "", 1)
    return f"{PREFIX}{n}" if n else PREFIX


def name_to_phase(name: str):
    key = normalize(name)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    # 6 floats aus Hash
    vals = []
    for i in range(6):
        chunk = digest[i * 4 : (i + 1) * 4]
        u = int.from_bytes(chunk, "big") / 2**32
        vals.append((u - 0.5) * 2.0)  # [-1, 1]
    q = np.array(vals[0:3], dtype=float)
    p = np.array(vals[3:6], dtype=float)
    # leichte Golden-Ratio-Verankerung
    q = q * 1.618 + np.array([0.1, 0.2, 0.3])
    p = p * 0.577 + np.array([0.05, -0.1, 0.15])
    torsion = np.zeros(27, dtype=float)
    torsion[0] = float(vals[0])
    return q, p, torsion


class QDNS:
    def __init__(self, ledger: Optional[Path] = None):
        self.ledger = ledger or LEDGER
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self._registry: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.ledger.exists():
            return
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                self._registry[row["name"]] = row
            except Exception:
                pass

    def register(self, name: str, meta: Optional[dict] = None) -> dict:
        key = normalize(name)
        q, p, torsion = name_to_phase(key)
        row = {
            "name": key,
            "q": q.tolist(),
            "p": p.tolist(),
            "torsion": torsion.tolist(),
            "label": key.split("/")[-1],
            "source": "registry",
            **(meta or {}),
        }
        self._registry[key] = row
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def resolve(self, name: str) -> dict:
        key = normalize(name)
        if key in self._registry:
            data = self._registry[key]
            return {
                "name": key,
                "q": np.array(data["q"], dtype=float),
                "p": np.array(data["p"], dtype=float),
                "torsion": np.array(data.get("torsion", [0.0] * 27), dtype=float),
                "label": data.get("label", key.split("/")[-1]),
                "source": data.get("source", "registry"),
            }
        q, p, torsion = name_to_phase(key)
        return {
            "name": key,
            "q": q,
            "p": p,
            "torsion": torsion,
            "label": key.split("/")[-1],
            "source": "derived",
        }

    def contacts(self) -> List[dict]:
        # Standard-Anker + Registry
        names = ["qfan.de/nexus", "qfan.de/jan", "qfan.de/alpha", "qfan.de/secure"]
        seen = set()
        out = []
        for n in names + list(self._registry.keys()):
            if n in seen:
                continue
            seen.add(n)
            out.append({"url": n, "label": n.split("/")[-1]})
        return out
