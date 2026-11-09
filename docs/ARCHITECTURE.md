# QFAN-Repo-Struktur

Diese Übersicht dokumentiert die vorhandene Paketaufteilung. Einige gewünschte Modulnamen der vorgeschlagenen Zielstruktur sind im aktuellen Prototyp anders organisiert: die Haupt-App liegt in `qfan/app.py`; Kernlogik, Transport und Analyse sind in `qfan/core/`, `qfan/network/` und `qfan/analysis/` gruppiert. Die Root-Module für Engine, UI, Ledger und Vault bleiben aus Kompatibilitätsgründen erhalten.

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── run_host.py
├── run_client.py
├── build_exe.bat
├── host/
│   ├── START_HOST.bat
│   └── README.md
├── client/
│   ├── START_CLIENT.bat
│   ├── INSTALL.bat
│   └── README.md
├── qfan/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── core/
│   ├── network/
│   ├── analysis/
│   └── tests/
├── tests/
└── docs/
    ├── SPEC.md
    ├── ARCHITECTURE.md
    └── BETRIEB.md
```

Die zusätzlichen Root-Module enthalten derzeit den Host-/Client-Engine-Stack und werden von Tests und/oder der Anwendung importiert. Sie wurden nicht blind verschoben, damit bestehende Importpfade intakt bleiben. Die vorhandenen PDF-Handbücher sowie das ZIP-Artefakt bleiben unverändert im Repository-Root.