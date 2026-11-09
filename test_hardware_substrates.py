#!/usr/bin/env python3
"""20-Hersteller-Stresstest gegen den echten QFAN-Field-Kern.

Chips sind nur Blindträger (MTU). Freigabe macht Liouville + Field-DHCP.
"""
from __future__ import annotations

import json
import struct
import time

import numpy as np

from qfan.field_dhcp import FieldDHCP
from qfan.qdns import QDNS
from qfan.qfan_core import QFANCore
from qfan.substrates import BLEReassembler, encode_qfan_body, fragment_ble

HARDWARE_MANUFACTURERS = [
    {"vendor": "Intel", "model": "AX210 Wi-Fi 6E", "type": "wifi", "max_mtu": 4096},
    {"vendor": "Realtek", "model": "RTL8125 2.5GbE", "type": "ethernet", "max_mtu": 9000},
    {"vendor": "Broadcom", "model": "BCM4390 Wi-Fi 7", "type": "wifi", "max_mtu": 4096},
    {"vendor": "Qualcomm", "model": "QCA6390 FastConnect", "type": "wifi", "max_mtu": 1500},
    {"vendor": "MediaTek", "model": "MT7921 Wi-Fi 6", "type": "wifi", "max_mtu": 1500},
    {"vendor": "Nordic", "model": "nRF5340 BLE 5.3", "type": "ble", "max_mtu": 251},
    {"vendor": "Texas Instruments", "model": "CC2642R BLE", "type": "ble", "max_mtu": 251},
    {"vendor": "Cisco", "model": "VIC 1440 Ethernet NIC", "type": "ethernet", "max_mtu": 9000},
    {"vendor": "Mellanox", "model": "ConnectX-6 Dx InfiniBand/Ethernet", "type": "ethernet", "max_mtu": 9216},
    {"vendor": "Marvell", "model": "AQtion AQC113 10GbE", "type": "ethernet", "max_mtu": 16000},
    {"vendor": "Aquantia", "model": "AQC107 Network Adapter", "type": "ethernet", "max_mtu": 9000},
    {"vendor": "Infineon", "model": "CYW5551x Wi-Fi/BT", "type": "wifi", "max_mtu": 4096},
    {"vendor": "Espressif", "model": "ESP32-S3 Wi-Fi/BLE", "type": "wifi", "max_mtu": 1460},
    {"vendor": "Dialog", "model": "DA14695 BLE 5.2", "type": "ble", "max_mtu": 251},
    {"vendor": "Silicon Labs", "model": "EFR32BG22 BLE", "type": "ble", "max_mtu": 251},
    {"vendor": "NXP", "model": "IW616 Wi-Fi 6/BLE", "type": "wifi", "max_mtu": 1500},
    {"vendor": "Microchip", "model": "LAN9253 EtherCAT", "type": "ethernet", "max_mtu": 1500},
    {"vendor": "QLogic", "model": "FastLinQ QL41000", "type": "ethernet", "max_mtu": 9000},
    {"vendor": "Solarflare", "model": "SFC9250 10GbE", "type": "ethernet", "max_mtu": 9000},
    {"vendor": "TP-Link", "model": "Archer TXE75E Wi-Fi 6E", "type": "wifi", "max_mtu": 1500},
]


def pack_frame(packet: dict) -> bytes:
    return encode_qfan_body(packet)


def run_hardware_stress_test(iterations_per_hardware: int = 1000) -> dict:
    core = QFANCore()
    dhcp = FieldDHCP()
    qdns = QDNS()
    phase = qdns.resolve("qfan.de/jan")
    base_q = np.asarray(phase["q"], dtype=float)
    base_p = np.asarray(phase["p"], dtype=float)

    total_processed = 0
    total_rejected = 0
    stats = {hw["vendor"]: {"success": 0, "rejected": 0, "type": hw["type"]} for hw in HARDWARE_MANUFACTURERS}

    print(
        f"[*] QFAN 20-Hersteller Hardware-Stresstest "
        f"({len(HARDWARE_MANUFACTURERS)} Vendor, {iterations_per_hardware} je HW)"
    )
    t0 = time.time()

    for hw in HARDWARE_MANUFACTURERS:
        vendor = hw["vendor"]
        for i in range(iterations_per_hardware):
            total_processed += 1
            corrupt = i % 250 == 0
            if corrupt:
                q_vec = np.array([float("nan"), 0.0, 0.0])
                p_vec = np.array([0.0, 0.0, 0.0])
            else:
                q_vec = base_q + np.array([(i % 5) * 0.0001, 0.0, 0.0])
                p_vec = base_p

            try:
                if not np.all(np.isfinite(q_vec)) or not np.all(np.isfinite(p_vec)):
                    raise ValueError("corrupt qubit")
                frame_q = core.prepare_frame_qubit(q_vec, p_vec)
                if not frame_q["liouville_ok"]:
                    total_rejected += 1
                    stats[vendor]["rejected"] += 1
                    continue
                lease = dhcp.verify_and_lease(f"qfan.de/{vendor.lower()}-node", frame_q["q"], frame_q["p"])
                if lease.get("status") != "LOCKED":
                    total_rejected += 1
                    stats[vendor]["rejected"] += 1
                    continue
            except Exception:
                total_rejected += 1
                stats[vendor]["rejected"] += 1
                continue

            packet = {
                "type": "msg",
                "vendor": vendor,
                "model": hw["model"],
                "q": frame_q["q"],
                "p": frame_q["p"],
                "det_j": frame_q["det_j"],
                "qip": lease.get("qip"),
                "node_id": lease.get("node_id"),
            }
            if hw["type"] == "ble":
                frags = fragment_ble(packet, mtu=hw["max_mtu"], msg_id=i + 1)
                if not frags or any(len(f) > hw["max_mtu"] for f in frags):
                    total_rejected += 1
                    stats[vendor]["rejected"] += 1
                    continue
                got = None
                reasm = BLEReassembler()
                for frag in frags:
                    got = reasm.push(frag) or got
                if not got or got.get("qip") != packet["qip"]:
                    total_rejected += 1
                    stats[vendor]["rejected"] += 1
                    continue
                stats[vendor]["success"] += 1
                continue

            raw = pack_frame(packet)
            if len(raw) > hw["max_mtu"]:
                total_rejected += 1
                stats[vendor]["rejected"] += 1
                continue
            stats[vendor]["success"] += 1

    duration = time.time() - t0
    ok = total_processed - total_rejected
    print("\n=== HARDWARE-STRESSTEST (echter Kern) ===")
    print(f"Dauer: {duration:.4f} s")
    print(f"Frames: {total_processed}")
    print(f"Durch Substrat-MTU + Liouville: {ok}")
    print(f"Abgewehrt: {total_rejected}\n")
    print(f"{'Hersteller':<20} {'Typ':<10} {'OK':>6} {'Reject':>8}")
    for hw in HARDWARE_MANUFACTURERS:
        res = stats[hw["vendor"]]
        print(f"{hw['vendor']:<20} {res['type']:<10} {res['success']:>6} {res['rejected']:>8}")
    return {"duration": duration, "total": total_processed, "rejected": total_rejected, "stats": stats}


if __name__ == "__main__":
    run_hardware_stress_test()
