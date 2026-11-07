from pathlib import Path

import pytest

from arp_vendor_lookup.parser import classify_mac, normalize_mac, parse_arp_table, parse_line

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("00:1b:17:00:01:10", "00:1B:17:00:01:10"),
        ("00-1B-17-00-01-10", "00:1B:17:00:01:10"),
        ("001b.1700.0110", "00:1B:17:00:01:10"),
        ("0:1b:17:0:1:10", "00:1B:17:00:01:10"),
        ("001B17000110", "00:1B:17:00:01:10"),
        ("00:1b:17:00:01", None),
        ("zz:1b:17:00:01:10", None),
    ],
)
def test_normalize_mac(raw, expected):
    assert normalize_mac(raw) == expected


def test_classify():
    assert classify_mac("FF:FF:FF:FF:FF:FF") == ("broadcast",)
    assert classify_mac("00:00:00:00:00:00") == ("null",)
    assert classify_mac("01:00:5E:00:00:16") == ("multicast",)
    assert classify_mac("3A:91:5C:77:0E:21") == ("private/random",)
    assert classify_mac("00:1B:17:00:01:10") == ()


def test_headers_and_junk_are_skipped():
    for line in [
        "Interface: 192.168.1.50 --- 0xb",
        "  Internet Address      Physical Address      Type",
        "Address  HWtype  HWaddress  Flags Mask  Iface",
        "192.168.1.22   (incomplete)   eth0",
        "Internet  10.10.10.40  0  Incomplete  ARPA",
        "",
        "-" * 80,
    ]:
        assert parse_line(line) is None, line


EXPECTED = {
    "windows.txt": [("192.168.1.1", "00:1B:17:00:01:10"), ("192.168.1.20", "B8:27:EB:12:34:56"),
                    ("192.168.1.33", "3A:91:5C:77:0E:21")],
    "linux_arp_n.txt": [("192.168.1.1", "00:1B:17:00:01:10"), ("192.168.1.15", "00:50:56:A1:B2:C3")],
    "linux_ip_neigh.txt": [("192.168.1.1", "00:1B:17:00:01:10"), ("192.168.1.40", "DC:A6:32:AA:BB:CC")],
    "linux_proc_net_arp.txt": [("192.168.1.1", "00:1B:17:00:01:10")],
    "macos.txt": [("192.168.1.1", "00:1B:17:00:01:10"), ("192.168.1.12", "3C:22:FB:01:02:03")],
    "cisco_ios.txt": [("10.10.10.1", "00:1A:A1:00:00:01"), ("10.10.10.25", "00:50:56:A1:B2:C3"),
                      ("10.10.10.30", "88:15:44:01:02:03")],
    "paloalto_panos.txt": [("10.20.0.1", "00:09:0F:09:00:01"), ("10.20.0.15", "00:50:56:A1:B2:C3"),
                           ("10.30.0.8", "F0:9F:C2:10:20:30")],
    "fortinet.txt": [("10.40.0.1", "00:1B:17:00:01:10"), ("10.40.0.22", "B8:27:EB:12:34:56")],
    "juniper_junos.txt": [("10.50.0.1", "00:05:85:00:00:01"), ("10.50.0.30", "00:0C:29:AB:CD:EF")],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_formats(name):
    entries = parse_arp_table((SAMPLES / name).read_text())
    assert [(e.ip, e.mac) for e in entries] == EXPECTED[name]


def test_include_special_keeps_broadcast_and_multicast():
    text = (SAMPLES / "windows.txt").read_text()
    macs = [e.mac for e in parse_arp_table(text, include_special=True)]
    assert "FF:FF:FF:FF:FF:FF" in macs
    assert "01:00:5E:00:00:16" in macs


def test_duplicates_removed():
    text = "10.0.0.1 00:1b:17:00:01:10\n10.0.0.1 00-1B-17-00-01-10\n"
    assert len(parse_arp_table(text)) == 1
