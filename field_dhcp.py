"""Field-DHCP — logische Matrix-Slots / Helix, ohne IP-Lease."""
from __future__ import annotations

import time
from typing import Any, Dict

import numpy as np

from qfan.qfan_core import QFANCore
from qfan.qip import make_qip


class FieldDHCP:
    def __init__(self, total_nodes: int = 32):
        self.total_nodes = total_nodes
        self.active: Dict[str, dict] = {}  # node_id -> lease
        self.core = QFANCore()

    def verify_and_lease(self, client_id: str, q, p) -> Dict[str, Any]:
        q = np.asarray(q, dtype=float).reshape(3)
        p = np.asarray(p, dtype=float).reshape(3)

        for node_id, lease in self.active.items():
            if lease["client_id"] == client_id:
                lease["last_seen"] = time.time()
                qip = lease.get("qip") or make_qip(node_id, q, p, client_id)
                lease["qip"] = qip
                return {
                    "status": "LOCKED",
                    "node_id": node_id,
                    "helix_slot": lease["helix_slot"],
                    "matrix_coord": lease["matrix_coord"],
                    "det_j": lease.get("det_j", 1.0),
                    "qip": qip,
                    "message": "Feld-Lease erneuert",
                    "error": None,
                }

        result = self.core.verify_handshake(q, p, client_id)
        if result["status"] != "LOCKED":
            return {
                "status": "LOCKDOWN",
                "error": result.get("error", "Liouville-Invarianz verletzt"),
                "det_j": result.get("det_j"),
            }

        if len(self.active) >= self.total_nodes:
            return {"status": "POOL_EXHAUSTED", "error": "Matrix-Pool voll (32 Knoten)"}

        idx = len(self.active)
        node_name = f"NODE-{700 + idx}"
        matrix_coord = (idx % 4, (idx // 4) % 8, idx // 16)
        helix = result.get("helix_slot", 1000 + idx)
        qip = make_qip(node_name, q, p, client_id)
        lease = {
            "client_id": client_id,
            "node_id": node_name,
            "matrix_coord": matrix_coord,
            "helix_slot": helix,
            "det_j": result.get("det_j", 1.0),
            "qip": qip,
            "lease_time": time.time(),
            "last_seen": time.time(),
        }
        self.active[node_name] = lease
        return {
            "status": "LOCKED",
            "node_id": node_name,
            "matrix_coord": matrix_coord,
            "helix_slot": helix,
            "det_j": lease["det_j"],
            "qip": qip,
            "message": "Field-Lease neu vergeben",
            "error": None,
        }
