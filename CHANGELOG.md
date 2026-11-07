# Changelog

## 2.1.1 - 2026-11-07

- **Update OUI DB** now falls back to Wireshark's copy of the IEEE vendor list when
  IEEE's server refuses the download (it often blocks automated requests). Existing
  data is only replaced after a complete download.

## 2.1.0 - 2026-11-07

- **Debian package** (`.deb`) for Debian 12+, Ubuntu 22.04+, Kali and Raspberry Pi OS:
  installs via apt, adds an app-menu entry and the `arpvendor` command, and bundles
  the IEEE vendor database. Tested on Debian 12 and 13 in CI.
- Release builds fetch the IEEE database once and retry on failure.

## 2.0.0 - 2026-11-07

Rewrite of the original `MAClist1_1.py` (kept in `legacy/`).

- **Offline vendor lookup** from the IEEE MA-L/MA-M/MA-S registries; the old
  macvendorlookup.com API was unreliable and sent full MACs to a third party.
- Optional online fallback (api.macvendors.com) sends only the OUI, rate limited.
- **Format-independent parsing**: Windows, Linux, macOS, Cisco, Palo Alto, Fortinet,
  Juniper. v1 assumed the MAC was always the 4th column.
- Skips headers, incomplete, broadcast, null and multicast entries; de-duplicates.
- Labels private/randomized MACs.
- GUI runs lookups on a background thread (v1 froze), adds sortable table,
  progress bar, file open, copy and CSV export.
- New CLI with table/CSV/JSON output and stdin support.
- Packaged with pyproject.toml, test suite, CI on Windows/macOS/Linux.
- One-click standalone apps for Windows, macOS and Linux with the IEEE vendor
  database built in, published on GitHub Releases.

## 1.1

Original single-file Tkinter script.
