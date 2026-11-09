# QFAN architecture

The canonical implementation is organized as a Python package:

- `qfan.core`: deterministic local name mapping (`qdns`), QIP formatting, in-process lease allocation, software phase-vector calculations, and timing utilities.
- `qfan.network`: JSON frame codec, file mailbox, UDP/IP broadcast carrier, and BLE fragmentation/reassembly helpers.
- `qfan.analysis`: JSONL logger and command-line report reader.
- `qfan.app`: Tkinter desktop prototype.

## Data path

```text
local name -> derived phase vector -> software validation -> encoded frame -> carrier
```

The UDP carrier uses ordinary IP networking. A local phase check or QIP value is not a cryptographic identity, and this prototype should not be exposed as a secure network service.
