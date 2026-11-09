# QFAN architecture (prototype)

QFAN is currently a Python desktop prototype with a deterministic name-to-vector mapping, an in-process lease allocator, frame encoding, optional file mailbox, and UDP broadcast adapter. The UDP adapter uses the operating system's IP stack; it is not an IP-free networking implementation.

## Modules

- `qfan_core.py`: phase-vector checks, equalizer values, smoothing, and handshake evaluation.
- `qdns.py` / `qip.py`: deterministic local name mapping and identifier formatting.
- `field_dhcp.py`: in-memory node/slot allocation for one process.
- `field_burst.py` / `field_sync.py`: local scheduling and clock-offset simulation.
- `substrates.py`: file mailbox, UDP adapter, and BLE frame-fragmentation helpers. BLE radio transport is not implemented.
- `app.py`: Tkinter host/client UI.

`qfan/` currently exposes a package entry point and compatibility import modules; implementation source remains at the repository root. See [SPEC.md](SPEC.md) for details and limitations.
