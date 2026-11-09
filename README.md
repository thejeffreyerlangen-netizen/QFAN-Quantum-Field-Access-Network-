# QFAN — Quantum Field Access Network (v1.3)

Host-Server und Client-Browser auf dem QFAN-Feldkern (Q-DNS, Field-DHCP, EQ1–EQ5, Ronmetrik,
Liouville, Torsion, QIP, Burst/Takt-Sync). Substrate tragen nur Bytes, die Freigabe macht das Feld.

```
Client Browser ──┐                       ┌── file  (gemeinsamer/synchronisierter Ordner)
Client Browser ──┼── Host · Nexus ───────┼── hub   (UDP, auch zwischen verschiedenen Netzen)
Client Browser ──┘  (Hub-and-Spoke)      └── adapter / ble (optional)
```

## Start

| Was | Befehl |
|---|---|
| Host mit Oberfläche | `host\START_HOST.bat` oder `python -m qfan --role host` |
| Host als Server (ohne Fenster) | `host\START_HOST_SERVER.bat` oder `python -m qfan --role host --headless` |
| Client | `client\START_CLIENT.bat` oder `python -m qfan --role client --name jan --hub <Host-Adresse>` |

## Verbindung zwischen verschiedenen Netzen

- **hub (UDP):** Host auf einem erreichbaren Rechner starten (Portfreigabe UDP 19812, Server oder VPN).
  Clients: `--hub <IP>[:Port]`. Clients brauchen keine Portfreigabe.
- **file (Ordner):** Host und Clients zeigen mit `--path` auf denselben Ordner (NAS, Syncthing, Nextcloud, OneDrive).
  Kein offener Port nötig.
- **Selbes Netz:** `--hub auto` sucht den Host per Broadcast.

## Funktionen

- Login-Popup und grün/grau-Anzeige, sobald sich ein Knoten im Feld anmeldet oder abmeldet
- Field-DHCP (NODE-700 ff.), QIP-Adresse, Presence für alle Clients
- Chat an alle oder privat (läuft über den Host)
- Feld-Vault: Host gibt Dateien frei, Clients rufen sie mit Prüfsumme ab
- WORM-Ledger (SHA-256-Kette, prüfbar), Telemetrie (Export als .log), Stress-Simulation (`/stress` im Headless-Modus)
- Jeder Frame läuft durch das Feld-Gate: Liouville, EQ1–EQ5, Residuum, Torsion

## Tests

```
python -m unittest tests.test_engine tests.test_ui_smoke -v
```

Hinweise: Nachrichten werden unverschlüsselt übertragen. Der bisherige Peer-to-Peer-Modus bleibt
unverändert über `python -m qfan.app` erreichbar. HMAC-Statussicherheit.
