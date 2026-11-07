"""Offline-first MAC vendor lookup.

Vendor names come from the IEEE public registries (MA-L, MA-M, MA-S), which
are downloaded once and cached locally. Lookups never leave your machine
unless you explicitly enable the online fallback (api.macvendors.com).
"""

from __future__ import annotations

import csv
import io
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

USER_AGENT = "arp-vendor-lookup (+https://github.com/romeoreynolds/arp-vendor-lookup)"

# IEEE registries, largest blocks first. Assignment lengths: 6, 7, 9 hex digits.
IEEE_SOURCES = {
    "oui.csv": "https://standards-oui.ieee.org/oui/oui.csv",          # MA-L /24
    "mam.csv": "https://standards-oui.ieee.org/oui28/mam.csv",        # MA-M /28
    "oui36.csv": "https://standards-oui.ieee.org/oui36/oui36.csv",    # MA-S /36
}

ONLINE_API = "https://api.macvendors.com/{mac}"
ONLINE_MIN_INTERVAL = 1.05  # free tier allows ~1 request/second


def default_cache_dir() -> Path:
    """Per-user cache folder, following each OS's convention."""
    override = os.environ.get("ARP_VENDOR_CACHE")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "arp-vendor-lookup"


def bundled_data_dir() -> Path | None:
    """Folder holding registries packed into a standalone (PyInstaller) build."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        path = Path(base) / "oui_data"
        if path.is_dir():
            return path
    return None


def update_database(
    cache_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
    timeout: float = 60,
) -> Path:
    """Download the IEEE registries into the cache folder."""
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, url in IEEE_SOURCES.items():
        if progress:
            progress(f"Downloading {name} from IEEE...")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        tmp = cache_dir / (name + ".part")
        tmp.write_bytes(data)
        tmp.replace(cache_dir / name)
    if progress:
        progress("OUI database updated.")
    return cache_dir


class VendorLookup:
    """Resolve MAC addresses to vendor names.

    Uses the cached IEEE registries first. If ``online`` is True, unknown
    prefixes fall back to api.macvendors.com (rate limited to 1 req/sec).
    Results are cached in memory, so duplicate MACs cost nothing.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        online: bool = False,
        timeout: float = 5,
        bundled_dir: Path | None = None,
    ):
        self.cache_dir = cache_dir or default_cache_dir()
        self.bundled_dir = bundled_dir if bundled_dir is not None else bundled_data_dir()
        self.online = online
        self.timeout = timeout
        self._prefixes: dict[str, str] = {}
        self._memo: dict[str, str | None] = {}
        self._last_online_call = 0.0
        self._lock = threading.Lock()
        self.load()

    # -- database ---------------------------------------------------------
    def load(self) -> int:
        """(Re)load registry files. Returns entry count.

        Each registry file is taken from the user's cache folder if present
        (freshest, written by update_database), otherwise from the copy bundled
        inside a standalone build.
        """
        self._prefixes.clear()
        self._memo.clear()
        self.source = None
        for name in IEEE_SOURCES:
            for folder, label in ((self.cache_dir, "cache"), (self.bundled_dir, "bundled")):
                path = folder / name if folder else None
                if path and path.exists():
                    self._load_csv(path.read_text(encoding="utf-8", errors="replace"))
                    self.source = self.source or label
                    break
        return len(self._prefixes)

    def _load_csv(self, text: str) -> None:
        reader = csv.reader(io.StringIO(text))
        next(reader, None)  # header: Registry,Assignment,Organization Name,Organization Address
        for row in reader:
            if len(row) >= 3 and row[1].strip():
                self._prefixes[row[1].strip().upper()] = row[2].strip()

    @property
    def has_database(self) -> bool:
        return bool(self._prefixes)

    @property
    def size(self) -> int:
        return len(self._prefixes)

    # -- lookups ----------------------------------------------------------
    def lookup(self, mac: str) -> str | None:
        """Return the vendor for a normalized MAC (AA:BB:CC:DD:EE:FF) or None."""
        hexstr = mac.replace(":", "").upper()
        if hexstr in self._memo:
            return self._memo[hexstr]
        vendor = self._lookup_offline(hexstr)
        if vendor is None and self.online:
            vendor = self._lookup_online(mac)
        self._memo[hexstr] = vendor
        return vendor

    def _lookup_offline(self, hexstr: str) -> str | None:
        # Most specific block wins: MA-S (36 bits) > MA-M (28) > MA-L (24)
        for length in (9, 7, 6):
            vendor = self._prefixes.get(hexstr[:length])
            if vendor:
                return vendor
        return None

    def _lookup_online(self, mac: str) -> str | None:
        with self._lock:
            wait = ONLINE_MIN_INTERVAL - (time.monotonic() - self._last_online_call)
            if wait > 0:
                time.sleep(wait)
            self._last_online_call = time.monotonic()
        # Only the OUI (first 3 octets) is sent - never the full device MAC.
        url = ONLINE_API.format(mac=mac[:8])
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace").strip() or None
        except (urllib.error.URLError, TimeoutError, OSError):
            # 404 = prefix unknown; other errors = network trouble. Either way, no answer.
            return None
