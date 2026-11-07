"""Command-line interface.

Examples:
    arp -a | arpvendor
    arpvendor arp_dump.txt -f csv -o results.csv
    arpvendor --update-db
    arpvendor --gui
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import FORMATTERS, resolve, sort_by_ip
from .oui import VendorLookup, default_cache_dir, update_database


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="arpvendor",
        description="Resolve MAC addresses in an ARP table to hardware vendors "
        "(Windows, Linux, macOS, Cisco, Palo Alto, Fortinet, Juniper...).",
    )
    p.add_argument("input", nargs="?", help="file with ARP output (default: stdin)")
    p.add_argument("-f", "--format", choices=sorted(FORMATTERS), default="table", help="output format")
    p.add_argument("-o", "--output", help="write results to a file instead of stdout")
    p.add_argument("--online", action="store_true",
                   help="fall back to api.macvendors.com for prefixes missing offline (sends OUI only)")
    p.add_argument("--all", action="store_true", help="include broadcast, multicast and null entries")
    p.add_argument("--sort", action="store_true", help="sort results by IP address")
    p.add_argument("--update-db", action="store_true", help="download the latest IEEE OUI registries")
    p.add_argument("--gui", action="store_true", help="launch the graphical interface")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import main as gui_main
        gui_main()
        return 0

    if args.update_db:
        try:
            path = update_database(progress=lambda m: print(m, file=sys.stderr))
        except Exception as exc:  # network errors, permission errors
            print(f"error: could not update OUI database: {exc}", file=sys.stderr)
            return 1
        print(f"Saved to {path}", file=sys.stderr)
        if not args.input and sys.stdin.isatty():
            return 0

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        build_parser().print_help()
        return 2

    lookup = VendorLookup(online=args.online)
    if not lookup.has_database and not args.online:
        print(
            "warning: no offline OUI database found in "
            f"{default_cache_dir()}.\n         Run `arpvendor --update-db` once, or add --online.",
            file=sys.stderr,
        )

    results = resolve(text, lookup, include_special=args.all)
    if args.sort:
        results = sort_by_ip(results)
    if not results:
        print("No IP/MAC pairs found in input.", file=sys.stderr)
        return 1

    output = FORMATTERS[args.format](results)
    if args.output:
        Path(args.output).write_text(output if output.endswith("\n") else output + "\n", encoding="utf-8")
        print(f"Wrote {len(results)} entries to {args.output}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
