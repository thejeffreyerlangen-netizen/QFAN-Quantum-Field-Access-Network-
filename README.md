# QFAN — Quantum Field Access Network

QFAN is a Python desktop prototype for deterministic local names, software phase-vector checks, and interchangeable frame carriers. It is not a quantum network and does not provide production-grade authentication, encryption, or delivery guarantees. The UDP adapter uses the operating system's IP stack; the project is not IP-free in its current implementation.

## Layout

- `qfan/core/` — phase checks, local name mapping, identifiers, leases, timing.
- `qfan/network/` — frame codec, local file mailbox, UDP carrier, BLE fragmentation helpers.
- `qfan/analysis/` — JSONL logging and analyzer CLI.
- `qfan/app.py` — Tk desktop prototype.
- `client/`, `host/` — Windows installers and role launchers.
- `docs/` — architecture and prototype specification.
- `tests/` — package integration and codec tests.

Legacy root Python modules are small import shims only. The canonical implementations live under `qfan/`.

## Run

Python 3.10+ and NumPy are required. Tkinter is required for the desktop UI.

```bash
python -m pip install -r requirements.txt
python -m qfan --role host --name nexus
python -m qfan --role client --name jan --target nexus
```

The file carrier requires a shared mailbox path. The UDP carrier is local-network broadcast and can be affected by firewall rules. BLE code only fragments and reassembles frames; it does not operate a Bluetooth radio.

## Test

```bash
python -m unittest discover -s tests -v
```

Logs and reports are written under the repository root in `qfan_logs/` and `logs/`.
