"""QIP — Quantum-Field Address (kein IPv4). Form: QIP-{NODE}-{SIG}"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

import numpy as np

QIP_RE = re.compile(r"^QIP-(\d+)-([0-9A-Fa-f]{6,12})$", re.I)


def phase_signature(q, p, name: str = "") -> str:
    raw = (
        np.asarray(q, dtype=float).tobytes()
        + np.asarray(p, dtype=float).tobytes()
        + name.encode("utf-8")
    )
    return hashlib.sha256(raw).hexdigest()[:6].upper()


def make_qip(node_id, q, p, name: str = "") -> str:
    if isinstance(node_id, str):
        digits = "".join(c for c in node_id if c.isdigit())
        num = int(digits) if digits else 0
    else:
        num = int(node_id)
    return f"QIP-{num}-{phase_signature(q, p, name)}"


def parse_qip(qip: str) -> Optional[Dict[str, Any]]:
    s = qip.strip().upper().replace(":", "-").replace(" ", "")
    if not s.startswith("QIP-"):
        s = "QIP-" + s
    m = QIP_RE.match(s)
    if not m:
        return None
    return {
        "qip": f"QIP-{m.group(1)}-{m.group(2).upper()}",
        "node_num": int(m.group(1)),
        "node_id": f"NODE-{m.group(1)}",
        "sig": m.group(2).upper(),
    }
