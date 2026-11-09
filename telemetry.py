"""Telemetrie — Ringpuffer für Feld-Ereignisse, Auswertung, Export und Stress-Simulation."""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Deque, Dict, List

KINDS = ("RON_SMOOTHING", "TORSION_ESCAPE", "LIOUVILLE_REJECT", "EQ_MISMATCH")


class Telemetry:
    def __init__(self, maxlen: int = 5000):
        self._rows: Deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.total = 0

    def record(self, kind: str, residuum: float, det_j: float, source: str = "", ptype: str = "") -> None:
        with self._lock:
            self.total += 1
            self._rows.append({"ts": time.time(), "kind": kind, "residuum": float(residuum),
                               "det_j": float(det_j), "source": source, "ptype": ptype})

    def rows(self) -> List[dict]:
        with self._lock:
            return list(self._rows)

    def summary(self) -> Dict[str, object]:
        rows = self.rows()
        counts = Counter(r["kind"] for r in rows)
        normal = [r["residuum"] for r in rows if r["kind"] == "RON_SMOOTHING"]
        dets = [r["det_j"] for r in rows if r["det_j"] == r["det_j"]]
        resid = [r["residuum"] for r in rows if r["residuum"] == r["residuum"]]
        return {
            "frames": len(rows),
            "counts": {k: counts.get(k, 0) for k in KINDS},
            "mean_residuum_normal": sum(normal) / len(normal) if normal else 0.0,
            "max_residuum": max(resid) if resid else 0.0,
            "mean_det_j": sum(dets) / len(dets) if dets else 0.0,
        }

    def format_summary(self) -> str:
        s = self.summary()
        c = s["counts"]
        n = max(1, s["frames"])
        return (
            f"Feld-Frames: {s['frames']}\n"
            f"RON_SMOOTHING:    {c['RON_SMOOTHING']} ({100*c['RON_SMOOTHING']/n:.1f}%)\n"
            f"TORSION_ESCAPE:   {c['TORSION_ESCAPE']} ({100*c['TORSION_ESCAPE']/n:.1f}%)\n"
            f"LIOUVILLE_REJECT: {c['LIOUVILLE_REJECT']}\n"
            f"EQ_MISMATCH:      {c['EQ_MISMATCH']}\n"
            f"Mittleres Residuum (normal): {s['mean_residuum_normal']:.6f}\n"
            f"Maximales Residuum:          {s['max_residuum']:.6f}\n"
            f"det(J) Mittelwert:           {s['mean_det_j']:.6f}"
        )

    def export(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["QFAN Telemetrie-Export", time.strftime("Erstellt: %d.%m.%Y %H:%M:%S"), "", self.format_summary(), "",
                 "ts;kind;residuum;det_j;source;type"]
        for r in self.rows():
            lines.append(f"{r['ts']:.3f};{r['kind']};{r['residuum']:.6f};{r['det_j']:.6f};{r['source']};{r['ptype']}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def simulate_stress(n: int = 1000, seed: int = 7, collapse_rate: float = 0.04,
                    name: str = "qfan.de/jan") -> Telemetry:
    """Schickt n synthetische Frames mit Phasenrauschen durch den echten Core (Liouville, EQ, Residuum, Escape)."""
    import numpy as np
    from qfan.qdns import QDNS
    from qfan.qfan_core import QFANCore

    core = QFANCore()
    ph = QDNS(ledger=Path(__import__("tempfile").gettempdir()) / "qfan_stress_qdns.jsonl").resolve(name)
    ideal = np.concatenate([ph["q"], ph["p"]])
    rng = np.random.default_rng(seed)
    tele = Telemetry(maxlen=max(n, 1))
    for _ in range(n):
        collapse = rng.random() < collapse_rate
        noise = rng.normal(0, 4.0, 6) if collapse else rng.normal(0, 0.02, 6)
        rec = ideal + noise
        q, p = rec[:3], rec[3:]
        chk = core.liouville_check(q, p)
        if not chk["ok"]:
            tele.record("LIOUVILLE_REJECT", 0.0, chk["det_j"], name, "sim")
            continue
        eq_ok = core.equalizer_lock(core.equalizer_from_state(q, p), q, p)["ok"]
        if not eq_ok:
            tele.record("EQ_MISMATCH", 0.0, chk["det_j"], name, "sim")
            continue
        res = core.residuum(rec, ideal)
        _, esc = core.evaluate_escape(res, rec.tolist())
        tele.record("TORSION_ESCAPE" if esc else "RON_SMOOTHING", res, chk["det_j"], name, "sim")
    return tele
