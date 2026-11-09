# QFAN — prototype specification

This document describes the current software prototype, not a validated quantum networking system or a production security protocol.

## Current behavior

- Names are normalized under `qfan.de/` and mapped deterministically to six floating-point values by a local hash function.
- `QFANCore` derives five equalizer values and evaluates a fixed Jacobian/determinant check. These are software checks and do not establish peer identity.
- `FieldDHCP` allocates in-memory `NODE-*` slots; leases are local to the process and are not a distributed DHCP service.
- The file carrier exchanges JSON frames through a shared directory.
- The adapter carrier sends UDP broadcast datagrams through the operating system's IP stack. Network access may be restricted by firewall or network configuration.
- BLE fragmentation/reassembly helpers exist, but an operational BLE radio transport is not implemented.
- The Tkinter UI is a host/client prototype. The current message transport does not provide production-grade encryption, authentication, or delivery guarantees.

## Processing outline

```text
name -> deterministic local phase vector
     -> software checks and lease allocation
     -> frame encoding / selected carrier
     -> receiver-side software checks
```

## Intended layers

1. Carrier/frame I/O
2. Name mapping and local node allocation
3. Scheduling and synchronization simulation
4. Software validation gates
5. Desktop UI and analyzer

The conceptual terms “Liouville,” “QIP,” “field,” and “quantum” in this codebase describe the project's model and do not imply quantum hardware or cryptographic security.
