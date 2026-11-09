#!/usr/bin/env python3
"""Rauchtest der Oberfläche mit simuliertem tkinter (läuft auch ohne Display)."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tk = MagicMock()
sys.modules.setdefault("tkinter", tk)
for _sub in ("filedialog", "messagebox", "scrolledtext", "simpledialog"):
    mod = MagicMock()
    sys.modules.setdefault(f"tkinter.{_sub}", mod)
    setattr(sys.modules["tkinter"], _sub, mod)

from qfan.engine import FieldEngine  # noqa: E402
from qfan import ui  # noqa: E402


def wait(cond, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


class UiSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            e.stop(send_bye=False)
        self.tmp.cleanup()

    def _pair(self, port):
        host = FieldEngine("nexus", "host", hub_port=port, use_file=False, data_dir=self.root / "h", beat=0.25, timeout=1.5, tick=0.01)
        cl = FieldEngine("jan", "client", hub_addr=f"127.0.0.1:{port}", hub_port=port, use_file=False,
                         data_dir=self.root / "c", beat=0.25, timeout=1.5, tick=0.01)
        self.engines += [host, cl]
        return host, cl

    def _pump(self, ws, secs=1.0):
        end = time.time() + secs
        while time.time() < end:
            try:
                while True:
                    ws.handle(ws.eng.events.get_nowait())
            except Exception as exc:
                if type(exc).__name__ != "Empty":
                    raise
            time.sleep(0.02)

    def test_host_and_client_ui_flow(self):
        host, cl = self._pair(19861)
        hw = ui.Workstation(MagicMock(), host)
        cw = ui.Workstation(MagicMock(), cl)
        self.assertTrue(wait(lambda: cl.connected))
        self._pump(hw, 0.8)
        self._pump(cw, 0.3)
        self.assertEqual(hw.accent, ui.HOST_ACCENT)
        self.assertEqual(cw.accent, ui.CLIENT_ACCENT)
        self.assertIn("jan", hw._contacts)
        self.assertTrue(hw._contacts["jan"]["online"])
        self.assertIn("nexus", cw._contacts)
        self.assertGreaterEqual(tk.Toplevel.call_count, 1)             # Login-Popup beim Host
        # Nachricht Client -> alle
        cw.entry_msg.get.return_value = "hallo"
        cw.listbox.curselection.return_value = ()
        cw.send()
        self._pump(hw, 0.8)
        written = " ".join(str(c.args[1]) for c in hw.log_view.insert.call_args_list if len(c.args) > 1)
        self.assertIn("hallo", written)
        # Host antwortet an Auswahl
        hw.entry_msg.get.return_value = "antwort"
        hw._rows = ["jan"]
        hw.listbox.curselection.return_value = (0,)
        hw.send()
        self._pump(cw, 0.8)
        written_c = " ".join(str(c.args[1]) for c in cw.log_view.insert.call_args_list if len(c.args) > 1)
        self.assertIn("antwort", written_c)
        # Client weg -> offline in der Liste
        cl.stop()
        self._pump(hw, 1.0)
        self.assertFalse(hw._contacts["jan"]["online"])

    def test_vault_listing_in_host_ui(self):
        host = FieldEngine("nexus", "host", hub_listen=False, use_file=False, data_dir=self.root / "h2")
        self.engines.append(host)
        f = self.root / "a.txt"
        f.write_text("x")
        host.vault.store(f)
        w = ui.Workstation(MagicMock(), host)
        self.assertEqual(w._vault_names, ["a.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
