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

# Fallback: Wireshark's vendor list, regenerated from the IEEE registries.
WIRESHARK_MANUF = "https://www.wireshark.org/download/automated/data/manuf"

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


SYSTEM_DATA_DIRS = (
    Path("/usr/share/arp-vendor-lookup/oui_data"),        # .deb package
    Path("/usr/local/share/arp-vendor-lookup/oui_data"),
)


def bundled_data_dir() -> Path | None:
    """Folder holding registries shipped with a standalone build or OS package."""
    candidates = []
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller one-click apps
    if base:
        candidates.append(Path(base) / "oui_data")
    if not sys.platform.startswith("win"):
        candidates.extend(SYSTEM_DATA_DIRS)
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _download(url: str, timeout: float, retries: int, progress: Callable[[str], None] | None) -> bytes:
    delay = 5.0
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if len(data) < 1000:
                raise OSError(f"response too small ({len(data)} bytes)")
            return data
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == retries:
                raise
            if progress:
                progress(f"  attempt {attempt} failed ({exc}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


_MASK_TO_FILE = {24: ("oui.csv", "MA-L", 6), 28: ("mam.csv", "MA-M", 7), 36: ("oui36.csv", "MA-S", 9)}
_CSV_HEADER = "Registry,Assignment,Organization Name,Organization Address\n"


def manuf_to_registry_csvs(text: str) -> dict[str, str]:
    """Convert Wireshark's ``manuf`` file into IEEE-style registry CSVs.

    manuf lines look like ``00:00:0C<TAB>Cisco<TAB>Cisco Systems, Inc`` or,
    for smaller blocks, ``00:1B:C5:00:00:00/36<TAB>Short<TAB>Long Name``.
    """
    rows: dict[str, list[list[str]]] = {name: [] for name, _, _ in _MASK_TO_FILE.values()}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        prefix, _, mask = fields[0].strip().partition("/")
        hexstr = prefix.replace(":", "").replace("-", "").replace(".", "").upper()
        bits = int(mask) if mask else 24
        if bits not in _MASK_TO_FILE or not all(c in "0123456789ABCDEF" for c in hexstr):
            continue
        name, registry, length = _MASK_TO_FILE[bits]
        if len(hexstr) < length:
            continue
        vendor = (fields[2] if len(fields) > 2 and fields[2].strip() else fields[1]).strip()
        rows[name].append([registry, hexstr[:length], vendor, ""])
    out = {}
    for name, entries in rows.items():
        buf = io.StringIO()
        buf.write(_CSV_HEADER)
        csv.writer(buf, lineterminator="\n").writerows(entries)
        out[name] = buf.getvalue()
    return out


def _fetch_ieee(timeout, retries, progress) -> dict[str, bytes]:
    files = {}
    for name, url in IEEE_SOURCES.items():
        if progress:
            progress(f"Downloading {name} from IEEE...")
        files[name] = _download(url, timeout, retries, progress)
    return files


def _fetch_wireshark(timeout, retries, progress) -> dict[str, bytes]:
    if progress:
        progress("Downloading vendor list from Wireshark (IEEE mirror)...")
    text = _download(WIRESHARK_MANUF, timeout, retries, progress).decode("utf-8", errors="replace")
    files = {name: content.encode("utf-8") for name, content in manuf_to_registry_csvs(text).items()}
    if files["oui.csv"].count(b"\n") < 10000:
        raise OSError("Wireshark vendor list looks incomplete")
    return files


def update_database(
    cache_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
    timeout: float = 60,
    retries: int = 3,
) -> Path:
    """Download the vendor registries into the cache folder.

    Tries IEEE first. IEEE's server often refuses automated downloads, so if
    it fails the same data is taken from Wireshark's published copy. Files are
    only replaced once a full set has downloaded.
    """
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = _fetch_ieee(timeout, retries, progress)
        source = "IEEE"
    except (urllib.error.URLError, TimeoutError, OSError) as ieee_exc:
        if progress:
            progress(f"IEEE download failed ({ieee_exc}); trying Wireshark mirror...")
        files = _fetch_wireshark(timeout, retries, progress)
        source = "Wireshark"
    for name, data in files.items():
        tmp = cache_dir / (name + ".part")
        tmp.write_bytes(data)
        tmp.replace(cache_dir / name)
    if progress:
        progress(f"OUI database updated (source: {source}).")
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
