"""Parse ARP tables from many operating systems and network devices.

Instead of relying on fixed column positions (which differ on every platform),
each line is scanned with regular expressions for an IPv4 address and a MAC
address in any common notation. Header lines, blank lines and incomplete
entries simply produce no match and are skipped.

Supported notations:
    aa:bb:cc:dd:ee:ff   Linux, macOS, PAN-OS, FortiOS, Junos
    aa-bb-cc-dd-ee-ff   Windows
    aabb.ccdd.eeff      Cisco IOS / NX-OS
    a:b:c:d:e:f         macOS (drops leading zeros)
    aabbccddeeff        bare hex (some exports)
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")

_MAC_PATTERNS = [
    # aa:bb:cc:dd:ee:ff / aa-bb-cc-dd-ee-ff, also macOS-style single digits
    re.compile(
        r"(?<![0-9A-Fa-f:.-])"
        r"([0-9A-Fa-f]{1,2}(?P<sep>[:-])(?:[0-9A-Fa-f]{1,2}(?P=sep)){4}[0-9A-Fa-f]{1,2})"
        r"(?![0-9A-Fa-f:.-])"
    ),
    # Cisco dotted: aabb.ccdd.eeff
    re.compile(r"(?<![0-9A-Fa-f.])([0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})(?![0-9A-Fa-f.])"),
    # Bare 12 hex digits
    re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])"),
]


@dataclass(frozen=True)
class ArpEntry:
    """One IP-to-MAC mapping pulled from an ARP table."""

    ip: str
    mac: str  # normalized AA:BB:CC:DD:EE:FF
    notes: tuple[str, ...] = field(default=())


def normalize_mac(raw: str) -> str | None:
    """Return a MAC as uppercase colon-separated octets, or None if invalid."""
    raw = raw.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}", raw):
        hexstr = raw.replace(".", "")
    elif re.fullmatch(r"[0-9A-Fa-f]{12}", raw):
        hexstr = raw
    else:
        parts = re.split(r"[:-]", raw)
        if len(parts) != 6 or not all(re.fullmatch(r"[0-9A-Fa-f]{1,2}", p) for p in parts):
            return None
        hexstr = "".join(p.zfill(2) for p in parts)
    hexstr = hexstr.upper()
    return ":".join(hexstr[i : i + 2] for i in range(0, 12, 2))


def classify_mac(mac: str) -> tuple[str, ...]:
    """Flag special MAC types. Expects a normalized MAC."""
    first = int(mac[:2], 16)
    notes: list[str] = []
    if mac == "FF:FF:FF:FF:FF:FF":
        notes.append("broadcast")
    elif mac == "00:00:00:00:00:00":
        notes.append("null")
    else:
        if first & 0x01:
            notes.append("multicast")
        if first & 0x02:
            notes.append("private/random")
    return tuple(notes)


def _find_mac(line: str) -> str | None:
    for pattern in _MAC_PATTERNS:
        for match in pattern.finditer(line):
            mac = normalize_mac(match.group(1))
            if mac:
                return mac
    return None


def _find_ip(line: str) -> str | None:
    for match in _IPV4.finditer(line):
        try:
            return str(ipaddress.IPv4Address(match.group(1)))
        except ipaddress.AddressValueError:
            continue
    return None


def parse_line(line: str) -> ArpEntry | None:
    """Parse a single line. Returns None for headers, blanks and junk."""
    mac = _find_mac(line)
    if not mac:
        return None
    ip = _find_ip(line)
    if not ip:
        return None
    return ArpEntry(ip=ip, mac=mac, notes=classify_mac(mac))


def parse_arp_table(text: str, *, include_special: bool = False) -> list[ArpEntry]:
    """Parse a full ARP table dump.

    Broadcast, null and multicast entries are dropped unless include_special
    is True. Duplicate IP/MAC pairs are removed while preserving order.
    """
    seen: set[tuple[str, str]] = set()
    entries: list[ArpEntry] = []
    for line in text.splitlines():
        entry = parse_line(line)
        if entry is None:
            continue
        special = {"broadcast", "null", "multicast"} & set(entry.notes)
        if special and not include_special:
            continue
        key = (entry.ip, entry.mac)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries
