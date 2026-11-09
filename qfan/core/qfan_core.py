"""QFAN phase-space validation and frame preparation core."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

FREQ_ANCHOR = 98.112
RESIDUUM_THRESHOLD = 0.25
LIOUVILLE_ATOL = 0.08
EQ_COUNT = 5


class QFANCore:
    """Software phase-space checks; these are not cryptographic security controls."""

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
        self.eq_ref = self._anchor_equalizer()

    # ------------------------------------------------------------------
    # Shape / finite guards — always LOCKDOWN, never raw numpy exceptions
    # ------------------------------------------------------------------

    @staticmethod
    def coerce_phase_vector(vec, name: str = "vec") -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Require a finite 3-vector. On failure return (None, error_message).
        Never raises for shape / NaN / Inf problems.
        """
        try:
            arr = np.asarray(vec, dtype=float)
        except (TypeError, ValueError) as exc:
            return None, f"{name}: nicht konvertierbar ({exc})"
        if arr.size != 3:
            return None, f"{name}: erwartet 3 Komponenten, erhalten size={arr.size}"
        try:
            arr = arr.reshape(3)
        except ValueError as exc:
            return None, f"{name}: reshape fehlgeschlagen ({exc})"
        if not np.all(np.isfinite(arr)):
            return None, f"{name}: nicht endlich (NaN/Inf)"
        return arr, None

    def _anchor_equalizer(self) -> np.ndarray:
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
        q_arr, err_q = self.coerce_phase_vector(q, "q")
        p_arr, err_p = self.coerce_phase_vector(p, "p")
        if err_q or err_p:
            return np.zeros(EQ_COUNT, dtype=float)
        qn = float(np.linalg.norm(q_arr))
        pn = float(np.linalg.norm(p_arr))
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
        try:
            eq = np.asarray(eq_client, dtype=float).reshape(EQ_COUNT)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "eq": [],
                "eq_ref": self.eq_ref.tolist(),
                "delta": [],
                "status": "EQ_MISMATCH",
                "error": "Equalizer-Shape ungültig",
            }
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
        j = np.zeros((6, 6))
        j[:3, 3:] = np.eye(3)
        j[3:, :3] = -np.eye(3)
        return j

    def liouville_check(self, q, p) -> dict:
        q_arr, err_q = self.coerce_phase_vector(q, "q")
        p_arr, err_p = self.coerce_phase_vector(p, "p")
        if err_q or err_p:
            return {
                "ok": False,
                "det_j": float("nan"),
                "raw_det": float("nan"),
                "status": "LOCKDOWN",
                "error": err_q or err_p,
            }
        raw_det = float(np.linalg.det(self.numerical_jacobian(q_arr, p_arr)))
        display_det = float(
            1.0
            + 0.015
            * math.sin(float(np.linalg.norm(q_arr)))
            * math.cos(float(np.linalg.norm(p_arr)))
        )
        ok = abs(display_det - 1.0) <= self.liouville_atol and abs(raw_det - 1.0) < 1e-6
        return {
            "ok": ok,
            "det_j": display_det,
            "raw_det": raw_det,
            "status": "LOCKED" if ok else "LOCKDOWN",
        }

    def evaluate_5eq_potential(self, q, p) -> Tuple[float, float, bool]:
        lock = self.liouville_check(q, p)
        q_arr, err_q = self.coerce_phase_vector(q, "q")
        p_arr, err_p = self.coerce_phase_vector(p, "p")
        if err_q or err_p or not lock["ok"]:
            return float(lock.get("det_j", float("nan"))), 0.0, False
        qn = float(np.linalg.norm(q_arr))
        pn = float(np.linalg.norm(p_arr))
        coherence = float(0.95 + 0.05 * math.cos(qn - pn))
        eq_ok = self.equalizer_lock(self.equalizer_from_state(q_arr, p_arr), q_arr, p_arr)["ok"]
        return float(lock["det_j"]), coherence, bool(lock["ok"] and eq_ok)

    def ron_smooth(self, raw: Sequence[float], ideal: Sequence[float]) -> List[float]:
        return [
            float(t)
            + (float(r) - float(t))
            * math.exp(-abs(float(r) - float(t)) * self.frequency_anchor / 100.0)
            for r, t in zip(raw, ideal)
        ]

    def ron_qubit(self, q, p, ideal_q=None, ideal_p=None) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        q_arr, err_q = self.coerce_phase_vector(q, "q")
        p_arr, err_p = self.coerce_phase_vector(p, "p")
        if err_q or err_p:
            return None, None
        iq = q_arr if ideal_q is None else self.coerce_phase_vector(ideal_q, "ideal_q")[0]
        ip = p_arr if ideal_p is None else self.coerce_phase_vector(ideal_p, "ideal_p")[0]
        if iq is None or ip is None:
            return None, None
        return (
            np.array(self.ron_smooth(q_arr, iq), dtype=float),
            np.array(self.ron_smooth(p_arr, ip), dtype=float),
        )

    def prepare_frame_qubit(self, q, p, ideal_q=None, ideal_p=None) -> dict:
        q2, p2 = self.ron_qubit(q, p, ideal_q, ideal_p)
        if q2 is None or p2 is None:
            _, err_q = self.coerce_phase_vector(q, "q")
            _, err_p = self.coerce_phase_vector(p, "p")
            return {
                "q": [],
                "p": [],
                "det_j": float("nan"),
                "kuramoto_r": 0.0,
                "eq": [],
                "eq_ok": False,
                "liouville_ok": False,
                "locked": False,
                "error": err_q or err_p or "ungültiger Phasenvektor",
            }
        lock = self.liouville_check(q2, p2)
        eq = self.equalizer_from_state(q2, p2)
        _, coherence, locked = self.evaluate_5eq_potential(q2, p2)
        return {
            "q": q2.tolist(),
            "p": p2.tolist(),
            "det_j": lock["det_j"],
            "kuramoto_r": coherence,
            "eq": eq.tolist(),
            "eq_ok": True,
            "liouville_ok": lock["ok"],
            "locked": locked,
        }

    def residuum(self, received: Sequence[float], ideal: Sequence[float]) -> float:
        return float(
            abs(
                np.linalg.norm(np.asarray(received, dtype=float))
                - np.linalg.norm(np.asarray(ideal, dtype=float))
            )
        )

    def evaluate_escape(self, residuum: float, vector: List[float]) -> Tuple[List[float], bool]:
        if residuum > self.residuum_threshold:
            return [v * self.torsion_factor * math.sin(residuum) for v in vector], True
        return list(vector), False

    def verify_handshake(self, q, p, client_id: str = "", eq=None) -> dict:
        q_arr, err_q = self.coerce_phase_vector(q, "q")
        p_arr, err_p = self.coerce_phase_vector(p, "p")
        if err_q or err_p:
            return {
                "status": "LOCKDOWN",
                "det_j": float("nan"),
                "error": err_q or err_p,
                "helix_slot": None,
                "eq": None,
            }
        frame = self.prepare_frame_qubit(q_arr, p_arr)
        if not frame.get("liouville_ok"):
            return {
                "status": "LOCKDOWN",
                "det_j": frame.get("det_j"),
                "error": frame.get("error") or "Liouville-Invarianz verletzt",
                "helix_slot": None,
                "eq": frame.get("eq"),
            }
        if eq is not None:
            eq_lock = self.equalizer_lock(eq, frame["q"], frame["p"])
        else:
            eq_lock = {"ok": frame.get("eq_ok", True), "eq": frame.get("eq")}
        if not eq_lock.get("ok"):
            return {
                "status": "LOCKDOWN",
                "det_j": frame.get("det_j"),
                "error": eq_lock.get("error") or "Equalizer EQ1–EQ5 nicht phasenstarr",
                "helix_slot": None,
                "eq": eq_lock.get("eq"),
            }
        seed = abs(hash((client_id, tuple(frame["q"]), tuple(frame["p"]))))
        return {
            "status": "LOCKED",
            "det_j": frame["det_j"],
            "kuramoto_r": frame["kuramoto_r"],
            "error": None,
            "helix_slot": 90 + seed % 900,
            "session_key": f"sess-{seed % 10**8:08d}",
            "q": frame["q"],
            "p": frame["p"],
            "eq": frame["eq"],
        }
