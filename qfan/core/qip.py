"""QIP identifier formatting helpers."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

import numpy as np

QIP_RE = re.compile(r"^QIP-(\d+)-([0-9A-Fa-f]{6,12})$", re.I)


def phase_signature(q, p, name: str = "") -> str:
    raw = np.asarray(q, dtype=float).tobytes() + np.asarray(p, dtype=float).tobytes() + name.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:6].upper()


def make_qip(node_id, q, p, name: str = "") -> str:
    digits = "".join(c for c in node_id if c.isdigit()) if isinstance(node_id, str) else str(int(node_id))
    return f"QIP-{int(digits) if digits else 0}-{phase_signature(q, p, name)}"


def parse_qip(qip: str) -> Optional[Dict[str, Any]]:
    value = qip.strip().upper().replace(":", "-").replace(" ", "")
    if not value.startswith("QIP-"):
        value = "QIP-" + value
    match = QIP_RE.match(value)
    if not match:
        return None
    number, signature = match.groups()
    return {"qip": f"QIP-{number}-{signature.upper()}", "node_num": int(number),
            "node_id": f"NODE-{number}", "sig": signature.upper()}
