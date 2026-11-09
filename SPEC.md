# QFAN — Vollständige Spezifikation (Konsolidierung)

Quelle: gesamter Entwicklungsverlauf (Mensah-Theorie, 8-Schichten-Modell, Equalizer, Substrate).

## 0. Nicht-Verhandelbar

- **Kein IP-Stack in der Steuerung.** Keine IP-Adresse, kein TCP/UDP als Logik, kein klassisches DNS.
- **Kein HTML/Localhost-Ersatzbrowser.** Zugang über den eigenen QFAN-Desktop-Browser (Host/Client).
- **Substrate tragen nur Bytes/Frames.** Freigabe macht das Feld (Qubit, EQ, Liouville).

## 1. Software-Qubit

\[
(q,p)\in\mathcal{P}^6,\quad q=(q_1,q_2,q_3),\ p=(p_1,p_2,p_3)
\]

Erzeugt durch **Q-DNS** aus `qfan.de/<name>`.

## 2. Taktanker

\[
f_0 = 98{,}112\ \mathrm{Hz},\quad T = 1/f_0 \approx 10{,}19\ \mathrm{ms}
\]

Burst schreibt Frames auf Slot-Grenzen. **Takt-Sync** zieht Phasen sanft nach (Software-PLL).

## 3. Equalizer EQ1–EQ5 (Quantum Equalizer)

Fünf phasenstarre Stufen. Client überträgt EQ-Parameter (oder sie werden aus `(q,p)` abgeleitet). Host prüft gegen Feld-Referenz am Taktanker.

| Stufe | Rolle |
|-------|--------|
| EQ1 | Grundphase sin |
| EQ2 | Grundphase cos |
| EQ3 | Kreuzterm q·p |
| EQ4 | Differenzterm q−p |
| EQ5 | Produktterm × Takt |

Mismatch → **LOCKDOWN** (wie Liouville-Fehler).

## 4. Ronmetrik

Jitter-Dämpfung vor dem Substrat:

\[
x' = x_{\mathrm{ideal}} + (x-x_{\mathrm{ideal}})\,e^{-|x-x_{\mathrm{ideal}}|\,f_0/100}
\]

## 5. Liouville

\[
\det(J)\approx 1
\]

sonst LOCKDOWN. Gate an Handshake und Stichprobe pro Frame.

## 6. Torsion / Residuum (Schicht 7)

Residuum-Schwelle 0,25. Darüber Torsions-Eskalation (Faktor ≈ 1,3415).

## 7. Field-DHCP & Matrix

- Nodes: `NODE-700…`
- Helix-Slots
- 3D **8-Layer-Matrix** (Layer 0–7)
- QIP: `QIP-700-XXXX` aus Node + Phasen-Signatur

## 8. Acht Schichten

| Schicht | Name | Inhalt |
|---------|------|--------|
| 8 | Applikation | Desktop-Browser Host/Client, Telemetrie |
| 7 | Torsion / Ausbruch | Residuum, Escape |
| 6 | Liouville | det(J)≈1 |
| 5 | Ronmetrik | Smoothing |
| 4 | QTCP / Burst | 98,112 Hz, Kuramoto-Kohärenz |
| 3 | QIP | Feld-Routing-Kennung |
| 2 | Q-DNS + Field-DHCP | Name → Qubit, Lease |
| 1 | Substrat | file (optional), adapter (Blindträger), BLE (≤251 B paketiert) |

## 9. Kette

```
Name → Q-DNS → Qubit
    → Ronmetrik → EQ1–EQ5 → Liouville
    → Field-DHCP → QIP + Helix
    → Burst @ 98.112 Hz
    → Multi-Substrat
    → Empfänger: Liouville + EQ erneut
```

## 10. UI

- Host: **QFAN Server · Nexus** (cyan)
- Client: **QFAN Client Browser** (orange)
- Dynamischer Client-Name
- Kontakte live über Field-DHCP / Presence
