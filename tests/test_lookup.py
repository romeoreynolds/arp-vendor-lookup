import shutil
from pathlib import Path

import pytest

from arp_vendor_lookup import cli
from arp_vendor_lookup.core import resolve, to_csv, to_json, to_table
from arp_vendor_lookup.oui import VendorLookup

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    for f in FIXTURES.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setenv("ARP_VENDOR_CACHE", str(tmp_path))
    return tmp_path


def test_offline_lookup(cache):
    lk = VendorLookup(cache_dir=cache)
    assert lk.has_database
    assert lk.lookup("00:50:56:A1:B2:C3") == "VMware, Inc."
    assert lk.lookup("12:34:56:78:9A:BC") is None


def test_most_specific_block_wins(cache):
    lk = VendorLookup(cache_dir=cache)
    assert lk.lookup("00:1B:17:10:00:00") == "Example MA-M Block Owner"  # MA-M 001B171
    assert lk.lookup("00:1B:17:20:00:00") == "Palo Alto Networks"        # MA-L 001B17


def test_online_disabled_makes_no_network_calls(cache, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used while offline")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    VendorLookup(cache_dir=cache).lookup("12:34:56:78:9A:BC")


def test_online_sends_only_oui(cache, monkeypatch):
    seen = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"Example Corp"

    def fake(req, timeout):
        seen.append(req.full_url)
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake)
    monkeypatch.setattr("arp_vendor_lookup.oui.ONLINE_MIN_INTERVAL", 0)
    lk = VendorLookup(cache_dir=cache, online=True)
    assert lk.lookup("AC:DE:48:11:22:33") == "Example Corp"
    assert seen == ["https://api.macvendors.com/AC:DE:48"]


def test_resolve_and_formatters(cache):
    text = (SAMPLES / "windows.txt").read_text()
    results = resolve(text, VendorLookup(cache_dir=cache))
    vendors = {r.ip: r.vendor for r in results}
    assert vendors["192.168.1.1"] == "Palo Alto Networks"
    assert vendors["192.168.1.33"] == "(private / randomized MAC)"
    assert "Palo Alto Networks" in to_table(results)
    assert to_csv(results).splitlines()[0] == "ip,mac,vendor,notes"
    assert '"vendor": "Raspberry Pi Foundation"' in to_json(results)


def test_cli_file_to_csv(cache, tmp_path, capsys):
    out = tmp_path / "out.csv"
    rc = cli.main([str(SAMPLES / "paloalto_panos.txt"), "-f", "csv", "-o", str(out), "--sort"])
    assert rc == 0
    lines = out.read_text().splitlines()
    assert lines[1].startswith("10.20.0.1,00:09:0F:09:00:01,")
    assert len(lines) == 4
