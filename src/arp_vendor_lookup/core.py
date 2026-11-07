"""Glue between the parser and the vendor lookup, plus output formatting."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from .oui import VendorLookup
from .parser import ArpEntry, parse_arp_table


@dataclass
class Result:
    ip: str
    mac: str
    vendor: str
    notes: str


def _vendor_label(entry: ArpEntry, vendor: str | None) -> str:
    if vendor:
        return vendor
    if "private/random" in entry.notes:
        return "(private / randomized MAC)"
    return "Unknown"


def resolve(
    text: str,
    lookup: VendorLookup,
    *,
    include_special: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> list[Result]:
    """Parse an ARP table and resolve each MAC to a vendor."""
    entries = parse_arp_table(text, include_special=include_special)
    results: list[Result] = []
    for i, entry in enumerate(entries, start=1):
        vendor = lookup.lookup(entry.mac)
        results.append(
            Result(
                ip=entry.ip,
                mac=entry.mac,
                vendor=_vendor_label(entry, vendor),
                notes=", ".join(entry.notes),
            )
        )
        if progress:
            progress(i, len(entries))
    return results


def sort_by_ip(results: Iterable[Result]) -> list[Result]:
    return sorted(results, key=lambda r: tuple(int(o) for o in r.ip.split(".")))


def to_table(results: list[Result]) -> str:
    headers = ("IP Address", "MAC Address", "Vendor", "Notes")
    rows = [(r.ip, r.mac, r.vendor, r.notes) for r in results]
    widths = [max([len(h)] + [len(row[i]) for row in rows]) for i, h in enumerate(headers)]
    widths[2] = min(widths[2], 45)

    def fmt(row):
        cells = [str(c)[: widths[i]] if i == 2 else str(c) for i, c in enumerate(row)]
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def to_csv(results: list[Result]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["ip", "mac", "vendor", "notes"])
    for r in results:
        writer.writerow([r.ip, r.mac, r.vendor, r.notes])
    return buf.getvalue()


def to_json(results: list[Result]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2)


FORMATTERS = {"table": to_table, "csv": to_csv, "json": to_json}
