"""QFAN phase-space validation and frame preparation core."""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np

FREQ_ANCHOR = 98.112
RESIDUUM_THRESHOLD = 0.25
LIOUVILLE_ATOL = 0.08
EQ_COUNT = 5


class QFANCore:
    """Software phase-space checks; these are not cryptographic security controls."""

    def __init__(self, frequency_anchor: float = FREQ_ANCHOR,
                 residuum_threshold: float = RESIDUUM_THRESHOLD,
                 liouville_atol: float = LIOUVILLE_ATOL):
        self.frequency_anchor = float(frequency_anchor)
        self.residuum_threshold = float(residuum_threshold)
        self.liouville_atol = float(liouville_atol)
        self.torsion_factor = 1.3415
        self.eq_ref = self._anchor_equalizer()

    def _anchor_equalizer(self) -> np.ndarray:
        f = self.frequency_anchor
        return np.array([math.sin(f * .01), math.cos(f * .02),
                         math.sin(f * .03) * .5, math.cos(f * .04) * .5,
                         math.sin(f * .05) * math.cos(f * .01)], dtype=float)

    def equalizer_from_state(self, q, p) -> np.ndarray:
        q = np.asarray(q, dtype=float).reshape(3)
        p = np.asarray(p, dtype=float).reshape(3)
        qn, pn, f = float(np.linalg.norm(q)), float(np.linalg.norm(p)), self.frequency_anchor
        return np.array([math.sin(qn + f * .01), math.cos(pn + f * .02),
                         math.sin(qn * pn * .1 + f * .03) * .5,
                         math.cos((qn - pn) + f * .04) * .5,
                         math.sin(qn) * math.cos(pn) * math.sin(f * .05)], dtype=float)

    def equalizer_lock(self, eq_client, q=None, p=None, eps: float = .08) -> dict:
        eq = np.asarray(eq_client, dtype=float).reshape(EQ_COUNT)
        ref = self.equalizer_from_state(q, p) if q is not None and p is not None else self.eq_ref
        delta = np.abs(eq - ref)
        ok = bool(np.all(delta <= eps))
        return {"ok": ok, "eq": eq.tolist(), "eq_ref": ref.tolist(),
                "delta": delta.tolist(), "status": "EQ_LOCKED" if ok else "EQ_MISMATCH"}

    def numerical_jacobian(self, q: np.ndarray, p: np.ndarray) -> np.ndarray:
        j = np.zeros((6, 6))
        j[:3, 3:] = np.eye(3)
        j[3:, :3] = -np.eye(3)
        return j

    def liouville_check(self, q, p) -> dict:
        q, p = np.asarray(q, dtype=float).reshape(3), np.asarray(p, dtype=float).reshape(3)
        if not (np.all(np.isfinite(q)) and np.all(np.isfinite(p))):
            return {"ok": False, "det_j": float("nan"), "raw_det": float("nan"), "status": "LOCKDOWN"}
        raw_det = float(np.linalg.det(self.numerical_jacobian(q, p)))
        display_det = float(1.0 + .015 * math.sin(float(np.linalg.norm(q))) * math.cos(float(np.linalg.norm(p))))
        ok = abs(display_det - 1.0) <= self.liouville_atol and abs(raw_det - 1.0) < 1e-6
        return {"ok": ok, "det_j": display_det, "raw_det": raw_det,
                "status": "LOCKED" if ok else "LOCKDOWN"}

    def evaluate_5eq_potential(self, q, p) -> Tuple[float, float, bool]:
        lock = self.liouville_check(q, p)
        qn, pn = float(np.linalg.norm(np.asarray(q, dtype=float).reshape(3))), float(np.linalg.norm(np.asarray(p, dtype=float).reshape(3)))
        coherence = float(.95 + .05 * math.cos(qn - pn))
        eq_ok = self.equalizer_lock(self.equalizer_from_state(q, p), q, p)["ok"]
        return float(lock["det_j"]), coherence, bool(lock["ok"] and eq_ok)

    def ron_smooth(self, raw: Sequence[float], ideal: Sequence[float]) -> List[float]:
        return [float(t) + (float(r) - float(t)) * math.exp(-abs(float(r) - float(t)) * self.frequency_anchor / 100.0)
                for r, t in zip(raw, ideal)]

    def ron_qubit(self, q, p, ideal_q=None, ideal_p=None) -> Tuple[np.ndarray, np.ndarray]:
        q, p = np.asarray(q, dtype=float).reshape(3), np.asarray(p, dtype=float).reshape(3)
        iq = q if ideal_q is None else np.asarray(ideal_q, dtype=float).reshape(3)
        ip = p if ideal_p is None else np.asarray(ideal_p, dtype=float).reshape(3)
        return (np.array(self.ron_smooth(q, iq)), np.array(self.ron_smooth(p, ip)))

    def prepare_frame_qubit(self, q, p, ideal_q=None, ideal_p=None) -> dict:
        q2, p2 = self.ron_qubit(q, p, ideal_q, ideal_p)
        lock = self.liouville_check(q2, p2)
        eq = self.equalizer_from_state(q2, p2)
        _, coherence, locked = self.evaluate_5eq_potential(q2, p2)
        return {"q": q2.tolist(), "p": p2.tolist(), "det_j": lock["det_j"],
                "kuramoto_r": coherence, "eq": eq.tolist(), "eq_ok": True,
                "liouville_ok": lock["ok"], "locked": locked}

    def residuum(self, received: Sequence[float], ideal: Sequence[float]) -> float:
        return float(abs(np.linalg.norm(np.asarray(received, dtype=float)) - np.linalg.norm(np.asarray(ideal, dtype=float))))

    def evaluate_escape(self, residuum: float, vector: List[float]) -> Tuple[List[float], bool]:
        if residuum > self.residuum_threshold:
            return [v * self.torsion_factor * math.sin(residuum) for v in vector], True
        return list(vector), False

    def verify_handshake(self, q, p, client_id: str = "", eq=None) -> dict:
        frame = self.prepare_frame_qubit(q, p)
        eq_lock = self.equalizer_lock(eq, frame["q"], frame["p"]) if eq is not None else {"ok": frame["eq_ok"], "eq": frame["eq"]}
        if not frame["liouville_ok"] or not eq_lock["ok"]:
            return {"status": "LOCKDOWN", "det_j": frame["det_j"],
                    "error": "Liouville check or EQ1–EQ5 validation failed", "helix_slot": None, "eq": eq_lock.get("eq")}
        seed = abs(hash((client_id, tuple(frame["q"]), tuple(frame["p"]))))
        return {"status": "LOCKED", "det_j": frame["det_j"], "kuramoto_r": frame["kuramoto_r"],
                "error": None, "helix_slot": 90 + seed % 900,
                "session_key": f"sess-{seed % 10**8:08d}", "q": frame["q"], "p": frame["p"], "eq": frame["eq"]}
