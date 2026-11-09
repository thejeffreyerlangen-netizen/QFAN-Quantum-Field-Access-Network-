import unittest
import numpy as np
from qfan.qfan_core import QFANCore
from qfan.field_dhcp import FieldDHCP

class InvalidVectorTests(unittest.TestCase):
    def test_liouville_check_returns_lockdown_for_wrong_shapes(self):
        core = QFANCore()
        for q, p in (([1, 2], [3, 4, 5, 6]), ([1, 2, 3], [1, 2]), (None, [1, 2, 3])):
            with self.subTest(q=q, p=p):
                self.assertEqual(core.liouville_check(q, p)["status"], "LOCKDOWN")
    def test_handshake_returns_lockdown_for_wrong_shapes(self):
        result = QFANCore().verify_handshake([1, 2], [3, 4, 5, 6], "bad-shape")
        self.assertEqual(result["status"], "LOCKDOWN")
        self.assertIsNone(result["helix_slot"])
    def test_dhcp_returns_lockdown_for_wrong_shapes(self):
        result = FieldDHCP().verify_and_lease("bad-shape", [1, 2], [3, 4, 5, 6])
        self.assertEqual(result["status"], "LOCKDOWN")
    def test_non_finite_vectors_still_lock_down(self):
        result = QFANCore().verify_handshake([np.inf, 0, 0], [0, 0, 0])
        self.assertEqual(result["status"], "LOCKDOWN")

if __name__ == "__main__":
    unittest.main()
