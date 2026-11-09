# QFAN — Quantum Field Access Network

A small Python desktop prototype for experimenting with deterministic naming, field-state checks, and interchangeable frame carriers. The current implementation is software simulation: the `adapter` carrier uses UDP over the operating system's IP network, and the QFAN checks are not a substitute for cryptographic authentication or transport security.

## Project layout

- `qfan/` — package entry point and compatibility modules for the existing implementation.
- `client/` and `host/` — Windows launch scripts and role-specific notes.
- `docs/` — architecture and protocol notes.
- `tests/` — focused package/codec smoke tests.
- Root-level Python files remain as the implementation source for compatibility with existing scripts and imports.

This is an incremental organization; the implementation has not yet been physically moved out of the repository root.

## Requirements

- Python 3.10 or newer
- NumPy (`python -m pip install -r requirements.txt`)
- Tkinter for the desktop UI (usually included with Python on Windows)

## Run

From the repository root:

```bash
python -m pip install -r requirements.txt
python -m qfan --role host --name nexus
python -m qfan --role client --name jan --target nexus
```

Windows launchers are available in `host/` and `client/`. The optional file carrier requires both instances to use the same mailbox directory. The UDP adapter carrier is local-network transport and may be restricted by the host firewall.

## Tests

```bash
python -m unittest discover -s tests -v
```

See [architecture](docs/ARCHITECTURE.md) and [specification](docs/SPEC.md) for the prototype's concepts and current limitations.
