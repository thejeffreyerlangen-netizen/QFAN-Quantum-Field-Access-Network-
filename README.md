# QFAN — Quantum Field Access Network

QFAN ist ein Python-Softwareprototyp für eine Host-/Client-Oberfläche mit Nachrichten, Datei-Vault, Telemetrie und mehreren experimentellen Trägern. Die Begriffe „Quantenfeld“, „Liouville“ und „QIP“ sind Projektkonzepte: Das Projekt implementiert weder ein quantenphysikalisches Netzwerk noch kryptografische Peer-Authentifizierung oder sichere Transportverschlüsselung. UDP nutzt die normale IP-Netzwerkebene des Betriebssystems.

## Schnellstart

Voraussetzungen: Python 3.10+ und `numpy` (Installation: `python -m pip install -r requirements.txt`). Für die Tkinter-Oberfläche muss Tkinter in der Python-Installation verfügbar sein.

```bash
python run_host.py
python run_client.py --name jan --hub 127.0.0.1
```

Alternativ: `python -m qfan --role host` oder `python -m qfan --role client --name jan --hub 127.0.0.1`. Unter Windows stehen Startdateien in `host/` und `client/` bereit.

Tests werden mit `python -m unittest discover -s tests -v` gestartet.

## Projektstruktur

- `qfan/`: Paket mit Oberfläche, Prototyp-App, Kernbausteinen, Trägern und Analyse
- `host/`, `client/`: Windows-Starter und kurze Anleitungen
- `tests/`: automatisierte Tests
- `docs/`: Spezifikation, Architektur und Betrieb
- Root: Startskripte, Dependencies und Projektmetadaten

Siehe [Architektur](docs/ARCHITECTURE.md), [Spezifikation](docs/SPEC.md) und [Betrieb](docs/BETRIEB.md).