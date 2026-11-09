"""Core package exports for QFAN."""

from .qfan_core import QFANCore
from .field_burst import FieldBurstSequencer
from .field_sync import TaktSync
from .field_dhcp import FieldDHCP
from .qdns import PREFIX, QDNS, name_to_phase, normalize
from .qip import QIP_RE, make_qip, parse_qip, phase_signature
from .substrates import (
    AdapterSubstrate,
    BaseSubstrate,
    BLEReassembler,
    BLESubstrate,
    FileSubstrate,
    MultiSubstrateBus,
    decode_qfan_body,
    encode_qfan_body,
    fragment_ble,
)

__all__ = [
    "QFANCore",
    "FieldBurstSequencer",
    "TaktSync",
    "FieldDHCP",
    "PREFIX",
    "QDNS",
    "name_to_phase",
    "normalize",
    "QIP_RE",
    "make_qip",
    "parse_qip",
    "phase_signature",
    "AdapterSubstrate",
    "BaseSubstrate",
    "BLEReassembler",
    "BLESubstrate",
    "FileSubstrate",
    "MultiSubstrateBus",
    "decode_qfan_body",
    "encode_qfan_body",
    "fragment_ble",
]
