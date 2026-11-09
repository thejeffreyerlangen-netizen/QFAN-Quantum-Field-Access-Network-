# Betrieb

## Voraussetzungen

- Python 3.10 oder neuer
- Abhängigkeit installieren: `python -m pip install -r requirements.txt`
- Für die Desktop-Oberfläche: Python-Installation mit Tkinter

## Starten

Host-Oberfläche: `python run_host.py` oder `python -m qfan --role host`.

Client: `python run_client.py --name jan --hub <Host-Adresse>` oder `python -m qfan --role client --name jan --hub <Host-Adresse>`. Bei Start ohne Namen fragt die Desktop-Anwendung nach den nötigen Angaben. Der Headless-Modus wird über `--headless` aktiviert; erfordert beim Client einen Namen, z. B. `python -m qfan --role client --name jan --hub <Host-Adresse> --headless`.

Unter Windows: zuerst `client/INSTALL.bat` ausführen, anschließend `host/START_HOST.bat` bzw. `client/START_CLIENT.bat`.

## Tests

`python -m unittest discover -s tests -v`

## Einschränkungen und Sicherheit

Die Feldprüfungen sind Softwareprüfungen, keine Authentifizierung. Der UDP-Träger nutzt das normale IP-Netzwerk des Betriebssystems. Es gibt keine kryptografische Transportsicherheit. Nicht als sicherheitskritischen oder öffentlich erreichbaren Netzwerkdienst einsetzen. Details stehen in [SPEC.md](SPEC.md).