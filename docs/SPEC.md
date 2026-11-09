# QFAN software prototype specification

This document describes a local Python software prototype. It is not a validated quantum networking system or a production security protocol.

- Q-DNS deterministically maps local names to numeric values; it does not query Internet DNS.
- QFANCore performs software-derived phase/equalizer checks; these checks are not peer authentication.
- FieldDHCP allocates leases in process memory; it is not distributed DHCP.
- The file carrier exchanges frames through a shared local directory.
- UDP-based carriers use the host operating system's ordinary IP networking.
- BLE helpers perform frame fragmentation/reassembly only; they do not implement an operational BLE radio.
- The desktop UI is a prototype. There is no cryptographic transport security or reliable-delivery protocol.

The terms “quantum”, “Liouville”, “field” and “QIP” refer to project concepts and do not imply quantum hardware or cryptographic security. Do not expose this prototype as a secure network service.