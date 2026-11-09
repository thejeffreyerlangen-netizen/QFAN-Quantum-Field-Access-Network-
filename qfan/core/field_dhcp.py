"""In-process field node lease allocator."""
from __future__ import annotations

import time
from typing import Any, Dict

import numpy as np

from .qfan_core import QFANCore
from .qip import make_qip


class FieldDHCP:
    def __init__(self, total_nodes: int = 32):
        self.total_nodes = int(total_nodes)
        self.active: Dict[str, dict] = {}
        self.core = QFANCore()

    def verify_and_lease(self, client_id: str, q, p) -> Dict[str, Any]:
        check = self.core.liouville_check(q, p)
        if not check["ok"]:
            return {"status": "LOCKDOWN", "error": check.get("error", "Invalid phase-space vector"),
                    "det_j": check["det_j"]}
        q, p = np.asarray(q, dtype=float).reshape(3), np.asarray(p, dtype=float).reshape(3)
        for node_id, lease in self.active.items():
            if lease["client_id"] == client_id:
                lease["last_seen"] = time.time()
                return {"status": "LOCKED", "node_id": node_id, "helix_slot": lease["helix_slot"],
                        "matrix_coord": lease["matrix_coord"], "det_j": lease["det_j"],
                        "qip": lease["qip"], "message": "Feld-Lease erneuert", "error": None}
        result = self.core.verify_handshake(q, p, client_id)
        if result["status"] != "LOCKED":
            return {"status": "LOCKDOWN", "error": result.get("error", "Liouville check failed"), "det_j": result.get("det_j")}
        if len(self.active) >= self.total_nodes:
            return {"status": "POOL_EXHAUSTED", "error": f"Matrix-Pool voll ({self.total_nodes} Knoten)"}
        idx = len(self.active)
        node_name = f"NODE-{700 + idx}"
        coord = (idx % 4, (idx // 4) % 8, idx // 16)
        lease = {"client_id": client_id, "node_id": node_name, "matrix_coord": coord,
                 "helix_slot": result["helix_slot"], "det_j": result["det_j"],
                 "qip": make_qip(node_name, q, p, client_id), "lease_time": time.time(), "last_seen": time.time()}
        self.active[node_name] = lease
        return {"status": "LOCKED", "node_id": node_name, "matrix_coord": coord,
                "helix_slot": lease["helix_slot"], "det_j": lease["det_j"], "qip": lease["qip"],
                "message": "Field-Lease neu vergeben", "error": None}
