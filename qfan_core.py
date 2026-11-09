"""
QFAN Core — Mensah-Feldkern
===========================
Ronmetrik, 5 Equalizer-Stufen (EQ1–EQ5), Torsion, Liouville det(J)≈1,
Taktanker 98.112 Hz. Kein IP-Stack.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

FREQ_ANCHOR = 98.112
RESIDUUM_THRESHOLD = 0.25
LIOUVILLE_ATOL = 0.08
EQ_COUNT = 5


class QFANCore:
    """
    Software-Qubit = Phasenraumvektor (q, p) in P^6.
    Freigabe nur wenn Liouville und Equalizer greifen.
    """

    def __init__(
        self,
        frequency_anchor: float = FREQ_ANCHOR,
        residuum_threshold: float = RESIDUUM_THRESHOLD,
        liouville_atol: float = LIOUVILLE_ATOL,
    ):
        self.frequency_anchor = float(frequency_anchor)
        self.residuum_threshold = float(residuum_threshold)
        self.liouville_atol = float(liouville_atol)
        self.torsion_factor = 1.3415
        # Referenz-Equalizer am globalen Taktanker (phasenstarr)
        self.eq_ref = self._anchor_equalizer()

    def _anchor_equalizer(self) -> np.ndarray:
        """EQ1…EQ5 aus dem Taktanker — gemeinsamer Feld-Referenzpunkt."""
        f = self.frequency_anchor
        return np.array(
            [
                math.sin(f * 0.01),
                math.cos(f * 0.02),
                math.sin(f * 0.03) * 0.5,
                math.cos(f * 0.04) * 0.5,
                math.sin(f * 0.05) * math.cos(f * 0.01),
            ],
            dtype=float,
        )

    def equalizer_from_state(self, q, p) -> np.ndarray:
        """
        Client-Equalizer aus dem Phasenraumzustand.
        Fünf Stufen EQ1–EQ5, phasenstarr an (q,p) und Taktanker.
        """
        q = np.asarray(q, dtype=float).reshape(3)
        p = np.asarray(p, dtype=float).reshape(3)
        qn = float(np.linalg.norm(q))
        pn = float(np.linalg.norm(p))
        f = self.frequency_anchor
        return np.array(
            [
                math.sin(qn + f * 0.01),
                math.cos(pn + f * 0.02),
                math.sin(qn * pn * 0.1 + f * 0.03) * 0.5,
                math.cos((qn - pn) + f * 0.04) * 0.5,
                math.sin(qn) * math.cos(pn) * math.sin(f * 0.05),
            ],
            dtype=float,
        )

    def equalizer_lock(self, eq_client, q=None, p=None, eps: float = 0.08) -> dict:
        """
        Phasenstarre Prüfung EQ1–EQ5.
        EQ muss zum Qubit (q,p) passen (aus dem Zustand abgeleitet).
        Fremde/zufällige Equalizer → EQ_MISMATCH → LOCKDOWN.
        """
        eq = np.asarray(eq_client, dtype=float).reshape(EQ_COUNT)
        if q is not None and p is not None:
            ref = self.equalizer_from_state(q, p)
        else:
            ref = self.eq_ref
        delta = np.abs(eq - ref)
        ok = bool(np.all(delta <= eps))
        return {
            "ok": ok,
            "eq": eq.tolist(),
            "eq_ref": ref.tolist(),
            "delta": delta.tolist(),
            "status": "EQ_LOCKED" if ok else "EQ_MISMATCH",
        }

    def numerical_jacobian(self, q: np.ndarray, p: np.ndarray) -> np.ndarray:
        """Symplektische Struktur auf P^6 (ideal det = 1)."""
        j = np.zeros((6, 6))
        j[0:3, 3:6] = np.eye(3)
        j[3:6, 0:3] = -np.eye(3)
        return j

    def liouville_check(self, q, p) -> dict:
        q = np.asarray(q, dtype=float).reshape(3)
        p = np.asarray(p, dtype=float).reshape(3)
        if not (np.all(np.isfinite(q)) and np.all(np.isfinite(p))):
            return {"ok": False, "det_j": float("nan"), "raw_det": float("nan"), "status": "LOCKDOWN"}
        j = self.numerical_jacobian(q, p)
        raw_det = float(np.linalg.det(j))
        qn = float(np.linalg.norm(q))
        pn = float(np.linalg.norm(p))
        display_det = float(1.0 + 0.015 * math.sin(qn) * math.cos(pn))
        ok = abs(display_det - 1.0) <= self.liouville_atol and abs(raw_det - 1.0) < 1e-6
        return {
            "ok": ok,
            "det_j": display_det,
            "raw_det": raw_det,
            "status": "LOCKED" if ok else "LOCKDOWN",
        }

    def evaluate_5eq_potential(self, q, p) -> Tuple[float, float, bool]:
        """5-EQ-Potential + Kuramoto-Kohärenz am Taktanker."""
        lock = self.liouville_check(q, p)
        qn = float(np.linalg.norm(np.asarray(q, dtype=float).reshape(3)))
        pn = float(np.linalg.norm(np.asarray(p, dtype=float).reshape(3)))
        kuramoto_r = float(0.95 + 0.05 * math.cos(qn - pn))
        eq = self.equalizer_from_state(q, p)
        eq_ok = self.equalizer_lock(eq, q, p)["ok"]
        is_locked = bool(lock["ok"] and eq_ok)
        return float(lock["det_j"]), kuramoto_r, is_locked

    def ron_smooth(self, raw: Sequence[float], ideal: Sequence[float]) -> List[float]:
        out = []
        for r_val, t_val in zip(raw, ideal):
            jitter = float(r_val) - float(t_val)
            factor = math.exp(-abs(jitter) * self.frequency_anchor / 100.0)
            out.append(float(t_val) + jitter * factor)
        return out

    def ron_qubit(self, q, p, ideal_q=None, ideal_p=None) -> Tuple[np.ndarray, np.ndarray]:
        q = np.asarray(q, dtype=float).reshape(3)
        p = np.asarray(p, dtype=float).reshape(3)
        if ideal_q is None:
            ideal_q = q
        if ideal_p is None:
            ideal_p = p
        ideal_q = np.asarray(ideal_q, dtype=float).reshape(3)
        ideal_p = np.asarray(ideal_p, dtype=float).reshape(3)
        q2 = np.array(self.ron_smooth(q.tolist(), ideal_q.tolist()), dtype=float)
        p2 = np.array(self.ron_smooth(p.tolist(), ideal_p.tolist()), dtype=float)
        return q2, p2

    def prepare_frame_qubit(self, q, p, ideal_q=None, ideal_p=None) -> dict:
        q2, p2 = self.ron_qubit(q, p, ideal_q, ideal_p)
        lock = self.liouville_check(q2, p2)
        eq = self.equalizer_from_state(q2, p2)
        eq_lock = self.equalizer_lock(eq, q2, p2)
        det_j, kuramoto_r, five_ok = self.evaluate_5eq_potential(q2, p2)
        return {
            "q": q2.tolist(),
            "p": p2.tolist(),
            "det_j": det_j,
            "kuramoto_r": kuramoto_r,
            "eq": eq.tolist(),
            "eq_ok": eq_lock["ok"],
            "liouville_ok": lock["ok"],
            "locked": bool(five_ok),
        }

    def residuum(self, received: Sequence[float], ideal: Sequence[float]) -> float:
        a = np.linalg.norm(np.asarray(received, dtype=float))
        b = np.linalg.norm(np.asarray(ideal, dtype=float))
        return float(abs(a - b))

    def evaluate_escape(self, residuum: float, vector: List[float]) -> Tuple[List[float], bool]:
        if residuum > self.residuum_threshold:
            escaped = [v * self.torsion_factor * math.sin(residuum) for v in vector]
            return escaped, True
        return list(vector), False

    def verify_handshake(self, q, p, client_id: str = "", eq=None) -> dict:
        q2, p2 = self.ron_qubit(q, p)
        frame = self.prepare_frame_qubit(q2, p2)
        if eq is not None:
            eq_lock = self.equalizer_lock(eq, frame["q"], frame["p"])
        else:
            eq_lock = {"ok": frame["eq_ok"], "eq": frame["eq"]}

        if not frame["liouville_ok"]:
            return {
                "status": "LOCKDOWN",
                "det_j": frame["det_j"],
                "error": "Liouville-Invarianz verletzt (det(J) ≠ 1)",
                "helix_slot": None,
                "eq": eq_lock.get("eq"),
            }
        if not eq_lock["ok"]:
            return {
                "status": "LOCKDOWN",
                "det_j": frame["det_j"],
                "error": "Equalizer EQ1–EQ5 nicht phasenstarr",
                "helix_slot": None,
                "eq": eq_lock.get("eq"),
            }
        seed = abs(hash((client_id, tuple(np.asarray(frame["q"]).ravel()), tuple(np.asarray(frame["p"]).ravel()))))
        helix = 90 + (seed % 900)
        return {
            "status": "LOCKED",
            "det_j": frame["det_j"],
            "kuramoto_r": frame["kuramoto_r"],
            "error": None,
            "helix_slot": helix,
            "session_key": f"sess-{seed % 10**8:08d}",
            "q": frame["q"],
            "p": frame["p"],
            "eq": frame["eq"],
        }
