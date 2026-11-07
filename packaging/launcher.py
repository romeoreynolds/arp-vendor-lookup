"""Entry point for the standalone builds.

Double-click (no arguments) opens the GUI. Run from a terminal with
arguments to use the CLI, e.g.  ./ARP-Vendor-Lookup arp_dump.txt -f csv
"""

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from arp_vendor_lookup.cli import main as cli_main

        raise SystemExit(cli_main())
    from arp_vendor_lookup.gui import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
