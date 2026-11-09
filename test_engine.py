#!/usr/bin/env python3
"""Integrationstests: Host/Client-Engine über file-, hub- und kombinierte Substrate."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qfan.engine import FieldEngine  # noqa: E402
from qfan.ledger import WormLedger  # noqa: E402
from qfan.telemetry import simulate_stress  # noqa: E402
from qfan.vault import Vault  # noqa: E402

_PORT = [19900 + (os.getpid() % 500) * 3]


def port() -> int:
    _PORT[0] += 1
    return _PORT[0]


def wait(cond, timeout: float = 6.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


def kinds(eng: FieldEngine) -> list:
    out = []
    while not eng.events.empty():
        out.append(eng.events.get_nowait())
    return out


FAST = dict(beat=0.25, timeout=1.5, tick=0.01)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            e.stop(send_bye=False)
        self.tmp.cleanup()

    def mk(self, name, role, **kw):
        kw = {**FAST, **kw}
        e = FieldEngine(name, role, data_dir=self.root / name, **kw)
        self.engines.append(e)
        e.start()
        return e

    def hub_pair(self, p=None):
        p = p or port()
        host = self.mk("nexus", "host", hub_port=p, use_file=False)
        cl = self.mk("jan", "client", hub_addr=f"127.0.0.1:{p}", hub_port=p, use_file=False)
        return host, cl, p


class LoginPresence(Base):
    def test_login_over_hub(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: cl.connected))
        self.assertTrue(wait(lambda: "jan" in host.online_peers()))
        info = host.online_peers()["jan"]
        self.assertTrue(info["node_id"].startswith("NODE-"))
        self.assertTrue(any(e[0] == "online" and e[1] == "jan" and e[3] is False for e in kinds(host)))
        self.assertEqual(cl.status()["via"], "hub")

    def test_login_over_file_substrate(self):
        mb = self.root / "mailbox"
        host = self.mk("nexus", "host", mailbox=mb, hub_listen=False)
        cl = self.mk("jan", "client", mailbox=mb)
        self.assertTrue(wait(lambda: cl.connected))
        self.assertTrue(wait(lambda: "jan" in host.online_peers()))
        self.assertEqual(cl.status()["via"], "file")

    def test_both_substrates_deduplicated(self):
        mb, p = self.root / "mb", port()
        host = self.mk("nexus", "host", mailbox=mb, hub_port=p)
        cl = self.mk("jan", "client", mailbox=mb, hub_addr=f"127.0.0.1:{p}", hub_port=p)
        self.assertTrue(wait(lambda: cl.connected))
        time.sleep(0.6)
        locked = [b for b in host.ledger.chain if b["event"] == "CLIENT_LOCKED"]
        self.assertEqual(len(locked), 1)

    def test_clients_see_each_other_and_popup_events(self):
        host, a, p = self.hub_pair()
        self.assertTrue(wait(lambda: a.connected))
        kinds(a)
        b = self.mk("lisa", "client", hub_addr=f"127.0.0.1:{p}", hub_port=p, use_file=False)
        self.assertTrue(wait(lambda: b.connected))
        self.assertTrue(wait(lambda: "lisa" in a.online_peers()))
        ev = kinds(a)
        self.assertTrue(any(e[0] == "online" and e[1] == "lisa" and e[3] is False for e in ev))
        self.assertIn("jan", b.online_peers())          # späterer Login sieht frühere Clients
        b.stop()
        self.assertTrue(wait(lambda: "lisa" not in a.online_peers()))
        self.assertTrue(any(e == ("offline", "lisa") for e in kinds(a)))

    def test_crash_without_bye_times_out(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: "jan" in host.online_peers()))
        cl.stop(send_bye=False)
        self.assertTrue(wait(lambda: "jan" not in host.online_peers(), 5))
        self.assertTrue(any(b["event"] == "CLIENT_LEFT" for b in host.ledger.chain))

    def test_client_reconnects_after_host_restart(self):
        p = port()
        host = self.mk("nexus", "host", hub_port=p, use_file=False)
        cl = self.mk("jan", "client", hub_addr=f"127.0.0.1:{p}", hub_port=p, use_file=False)
        self.assertTrue(wait(lambda: cl.connected))
        host.stop(send_bye=False)
        self.assertTrue(wait(lambda: not cl.connected, 5))
        host2 = self.mk("nexus", "host", hub_port=p, use_file=False)
        self.assertTrue(wait(lambda: cl.connected, 8))
        self.assertTrue(wait(lambda: "jan" in host2.online_peers()))


class Messaging(Base):
    def test_broadcast_and_private(self):
        host, a, p = self.hub_pair()
        b = self.mk("lisa", "client", hub_addr=f"127.0.0.1:{p}", hub_port=p, use_file=False)
        c = self.mk("tom", "client", hub_addr=f"127.0.0.1:{p}", hub_port=p, use_file=False)
        self.assertTrue(wait(lambda: a.connected and b.connected and c.connected and len(host.online_peers()) == 3))
        for e in (host, a, b, c):
            kinds(e)
        self.assertTrue(a.say_to("hallo alle", "*"))
        seen = {"lisa": [], "tom": []}

        def got_all():
            seen["lisa"] += kinds(b)
            seen["tom"] += kinds(c)
            return all(any(e[0] == "msg" and e[2] == "hallo alle" for e in v) for v in seen.values())
        self.assertTrue(wait(got_all), seen)
        self.assertTrue(any(e[0] == "msg" and e[1] == "jan" for e in seen["lisa"]))
        # privat: nur lisa
        a.say_to("privat", "lisa")
        time.sleep(0.6)
        evb, evc, eva = kinds(b), kinds(c), kinds(a)
        self.assertTrue(any(e[0] == "msg" and e[1] == "jan" and e[2] == "privat" for e in evb), evb)
        self.assertFalse(any(e[0] == "msg" and e[2] == "privat" for e in evc))
        self.assertFalse(any(e[0] == "msg" for e in eva))          # kein Echo an den Absender
        evh = kinds(host)
        self.assertTrue(any(e[0] == "msg" and e[2] == "privat" and e[3] == "lisa" for e in evh))

    def test_host_say_and_ledger(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: "jan" in host.online_peers() and cl.connected))
        kinds(cl)
        self.assertEqual(host.say("Willkommen"), 1)
        ev = []
        self.assertTrue(wait(lambda: ev.extend(kinds(cl)) or any(e[0] == "msg" for e in ev)))
        self.assertTrue(any(e[0] == "msg" and e[1] == "nexus" and e[2] == "Willkommen" for e in ev))
        self.assertTrue(any(b["event"] == "MSG" for b in host.ledger.chain))

    def test_say_to_offline_client_reaches_nobody(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: "jan" in host.online_peers()))
        cl.stop()
        self.assertTrue(wait(lambda: "jan" not in host.online_peers()))
        self.assertEqual(host.say("niemand da", "jan"), 0)
        self.assertEqual(host.say("niemand da", "gibtsnicht"), 0)


class Gate(Base):
    def test_bad_qubit_rejected_and_logged(self):
        host = self.mk("nexus", "host", hub_listen=False, use_file=False)
        nan = float("nan")
        host._handle({"type": "handshake", "from": "evil", "to": "nexus", "id": "x1", "q": [nan, 0, 0], "p": [0, 0, 0]})
        host._handle({"type": "handshake", "from": "evil", "to": "nexus", "id": "x2"})
        s = host.telemetry.summary()
        self.assertEqual(s["counts"]["LIOUVILLE_REJECT"], 2)
        self.assertNotIn("evil", host.online_peers())
        self.assertEqual(sum(1 for b in host.ledger.chain if b["event"] == "LIOUVILLE_REJECT"), 2)

    def test_eq_mismatch_rejected(self):
        host = self.mk("nexus", "host", hub_listen=False, use_file=False)
        host._handle({"type": "handshake", "from": "evil", "to": "nexus", "id": "y1",
                      "q": [0.1, 0.2, 0.3], "p": [0.1, 0.1, 0.1], "eq": [9, 9, 9, 9, 9]})
        self.assertEqual(host.telemetry.summary()["counts"]["EQ_MISMATCH"], 1)
        self.assertNotIn("evil", host.online_peers())

    def test_duplicate_ids_dropped(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: cl.connected))
        n = host.stats["rx"]
        pkt = host._attach({"type": "beat", "from": "jan", "to": "nexus", "id": "dup-1", "ts": time.time()})
        host._handle(dict(pkt)); host._handle(dict(pkt))
        self.assertLessEqual(host.stats["rx"] - n, 3)  # eigene Beats können dazwischenliegen
        self.assertGreaterEqual(host.stats["dup"], 1)


class VaultTransfer(Base):
    def _share(self, host, size):
        src = self.root / "quelle.bin"
        src.write_bytes(os.urandom(size))
        return src, host.share_file(src)

    def test_download_over_hub_many_chunks(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: cl.connected))
        src, name = self._share(host, 20000)          # ~29 Chunks à 700 Byte
        self.assertTrue(wait(lambda: any(f["name"] == name for f in cl.files)))
        dest = self.root / "out" / "kopie.bin"
        self.assertTrue(cl.download(name, dest))
        self.assertTrue(wait(lambda: dest.exists(), 10))
        self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(), hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertTrue(any(b["event"] == "FILE_RECEIVED" for b in cl.ledger.chain))

    def test_download_over_file_substrate_large(self):
        mb = self.root / "mb"
        host = self.mk("nexus", "host", mailbox=mb, hub_listen=False)
        cl = self.mk("jan", "client", mailbox=mb)
        self.assertTrue(wait(lambda: cl.connected))
        src, name = self._share(host, 300000)
        self.assertTrue(wait(lambda: any(f["name"] == name for f in cl.files)))
        dest = self.root / "kopie2.bin"
        cl.download(name, dest)
        self.assertTrue(wait(lambda: dest.exists(), 10))
        self.assertEqual(dest.read_bytes(), src.read_bytes())

    def test_unknown_file_reports_error(self):
        host, cl, _ = self.hub_pair()
        self.assertTrue(wait(lambda: cl.connected))
        kinds(cl)
        cl.download("gibt-es-nicht.txt", self.root / "x")
        ev = []
        self.assertTrue(wait(lambda: ev.extend(kinds(cl)) or any(e[0] == "file_error" for e in ev)))

    def test_vault_never_overwrites_and_blocks_traversal(self):
        v = Vault(self.root / "v")
        f = self.root / "log.txt"
        f.write_text("a")
        self.assertEqual([v.store(f), v.store(f)], ["log.txt", "log (1).txt"])
        for bad in ("../x", "..", "", "nicht-da"):
            with self.assertRaises((ValueError, FileNotFoundError)):
                v.path_of(bad)


class LedgerTelemetry(unittest.TestCase):
    def test_ledger_chain_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.jsonl"
            led = WormLedger(path)
            for i in range(5):
                led.record("E", f"n{i}")
            self.assertEqual(led.verify_integrity(), (True, None))
            again = WormLedger(path)                       # Neustart lädt und prüft
            self.assertTrue(again.loaded_ok)
            self.assertEqual(len(again), len(led))
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[3] = lines[3].replace("n2", "XX")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            bad = WormLedger(path)
            self.assertFalse(bad.loaded_ok)
            self.assertEqual(bad.verify_integrity()[0], False)

    def test_stress_simulation_runs_through_core(self):
        t = simulate_stress(1000, seed=7)
        s = t.summary()
        self.assertEqual(s["frames"], 1000)
        c = s["counts"]
        self.assertEqual(sum(c.values()), 1000)
        self.assertGreater(c["TORSION_ESCAPE"], 0)
        self.assertGreater(c["RON_SMOOTHING"], 800)
        with tempfile.TemporaryDirectory() as d:
            out = t.export(Path(d) / "t.log")
            self.assertIn("RON_SMOOTHING", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)