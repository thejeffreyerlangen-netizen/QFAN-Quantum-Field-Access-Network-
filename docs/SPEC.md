# QFAN prototype specification

This document describes the current Python software prototype. It is not a validated quantum networking system or a production security protocol.

- Q-DNS deterministically maps local names to six numeric values; it does not query Internet DNS.
- QFANCore calculates software-derived equalizer values and checks a fixed Jacobian. This is not peer authentication.
- FieldDHCP stores leases in process memory; it is not distributed DHCP.
- The file carrier exchanges JSON lines through a shared local directory.
- The adapter carrier sends UDP broadcast datagrams and therefore uses the host OS IP stack.
- BLE helpers fragment/reassemble frames only. There is no operational BLE radio implementation.
- The Tkinter UI is a prototype. There is no cryptographic transport security or reliable-delivery protocol.

The terms “quantum”, “Liouville”, “field” and “QIP” refer to project concepts and do not imply quantum hardware or cryptographic security.
