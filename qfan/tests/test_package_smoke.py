"""QFAN package tests.

These smoke tests validate the package import surface and the core frame codec behavior.
"""

import unittest

from qfan.core.substrates import BLEReassembler, decode_qfan_body, encode_qfan_body, fragment_ble


class FrameCodecTests(unittest.TestCase):
    def test_frame_round_trip(self):
        packet = {"type": "msg", "from": "jan", "text": "Grüße", "seq": 1}
        self.assertEqual(decode_qfan_body(encode_qfan_body(packet)), packet)

    def test_ble_fragments_reassemble(self):
        packet = {"type": "msg", "from": "jan", "text": "x" * 500}
        fragments = fragment_ble(packet, mtu=251, msg_id=7)
        self.assertTrue(all(len(fragment) <= 251 for fragment in fragments))

        reassembler = BLEReassembler()
        result = None
        for fragment in fragments:
            result = reassembler.push(fragment) or result

        self.assertIsNotNone(result)
        self.assertEqual(result["type"], packet["type"])
        self.assertEqual(result["text"], packet["text"])


if __name__ == "__main__":
    unittest.main()
