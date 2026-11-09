# QFAN — Architektur

Die Repository-Struktur wurde auf ein stabiles Python-Paket-Interface umgestellt, ohne die vorhandenen Legacy-Dateien zu verlieren.

- Paket-Start: `python -m qfan`
- Legacy-Module bleiben als Kompatibilitäts-Schnittstelle erhalten
- Batch-Skripte starten weiterhin Host/Client-Instanzen

Aktuelle Struktur:

- `qfan/` – neues Paket-Interface
- `app.py` – Legacy-Host/Client-Anwendung
- `substrates.py`, `field_*`, `qdns.py`, `qfan_core.py` – Kernmodule
- `README.md`, `SPEC.md`, `ARCHITECTURE.md` – Dokumentation

Die Struktur dient dazu, die Anwendung sowohl als Paket als auch als bestehendes Repository sauber zu betreiben.
