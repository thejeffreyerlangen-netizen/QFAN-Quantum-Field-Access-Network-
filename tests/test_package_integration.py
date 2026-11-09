import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qfan.core import FieldDHCP, QDNS, QFANCore
from qfan.network import BLEReassembler, FileSubstrate, decode_qfan_body, encode_qfan_body, fragment_ble


class PackageIntegrationTests(unittest.TestCase):
    def test_core_and_lease(self):
        with TemporaryDirectory() as directory:
            qdns = QDNS(Path(directory) / "names.jsonl")
            phase = qdns.resolve("qfan.de/test-node")
            result = FieldDHCP().verify_and_lease("test-node", phase["q"], phase["p"])
            self.assertEqual(result["status"], "LOCKED")
            self.assertTrue(QFANCore().liouville_check(phase["q"], phase["p"])["ok"])

    def test_frame_codec_rejects_bad_lengths(self):
        packet = {"type": "hello", "text": "Grüße"}
        frame = encode_qfan_body(packet)
        self.assertEqual(decode_qfan_body(frame), packet)
        self.assertIsNone(decode_qfan_body(frame[:-1]))
        self.assertIsNone(decode_qfan_body(b"bad"))

    def test_ble_fragment_round_trip(self):
        packet = {"type": "msg", "text": "x" * 500}
        fragments = fragment_ble(packet, mtu=251, msg_id=7)
        self.assertTrue(all(len(item) <= 251 for item in fragments))
        reassembler, decoded = BLEReassembler(), None
        for item in fragments:
            decoded = reassembler.push(item) or decoded
        self.assertEqual(decoded["text"], packet["text"])

    def test_file_carrier_round_trip(self):
        with TemporaryDirectory() as directory:
            sender = FileSubstrate(directory, "alice")
            receiver = FileSubstrate(directory, "bob")
            self.assertTrue(sender.send_frame({"to": "bob", "text": "hello"}))
            received = receiver.receive_frames()
            self.assertEqual(received[0]["text"], "hello")
            self.assertEqual(received[0]["_substrate"], "file")


if __name__ == "__main__":
    unittest.main()
