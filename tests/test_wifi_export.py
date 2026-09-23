from __future__ import annotations

import re

import pytest

from ssba.core.parsers.wifi import (
    WifiExportError,
    WifiNetwork,
    export_wifi,
    qr_payload,
    read_networks,
)
from tests.scan_fixtures import add_category
from tests.wifi_fixtures import block, build_wifi_scan_dir, store


def _read(tmp_path, text):
    return read_networks(build_wifi_scan_dir(tmp_path / "scan", text))


def test_duplicate_blocks_become_one_network_each(tmp_path):
    networks, skipped = read_networks(build_wifi_scan_dir(tmp_path / "scan"))
    assert networks == [
        WifiNetwork("Casa", "WPA", "segreta123", False),
        WifiNetwork("Bar Aperto", "open", None, False),
        WifiNetwork("Nascosta", "WPA", "x", True),
    ]
    assert skipped == 0


def test_new_version_style_part_is_ignored(tmp_path):
    networks, _ = read_networks(build_wifi_scan_dir(tmp_path / "scan"))
    assert "OnlyInNewStyle" not in [n.ssid for n in networks]


def test_hex_ssid_is_decoded_and_unquoted_psk_kept(tmp_path):
    raw_key = "0123456789abcdef" * 4
    networks, _ = _read(tmp_path, store(block(ssid="4361666520e29895", psk=raw_key, key_mgmt="WPA-PSK")))
    assert networks == [WifiNetwork("Cafe \u2615", "WPA", raw_key, False)]


def test_unquoted_non_hex_ssid_is_kept_as_written(tmp_path):
    networks, _ = _read(tmp_path, store(block(ssid="plain-name", key_mgmt="NONE")))
    assert networks[0].ssid == "plain-name"


def test_block_without_ssid_is_skipped_and_counted(tmp_path):
    networks, skipped = _read(tmp_path, store(block(key_mgmt="NONE"), block(ssid='"Ok"', key_mgmt="NONE")))
    assert [n.ssid for n in networks] == ["Ok"]
    assert skipped == 2  # counted once per source file (WifiConfigStore.xml and wpa_supplicant.conf)


@pytest.mark.parametrize("fields", [
    dict(ssid='"Ufficio"', key_mgmt="WPA-EAP", eap="PEAP"),
    dict(ssid='"Ufficio"', key_mgmt="NONE", wep_key0='"abcde"'),
])
def test_eap_and_wep_networks_are_other_without_qr(tmp_path, fields):
    networks, _ = _read(tmp_path, store(block(**fields)))
    assert networks[0].security == "other"
    assert qr_payload(networks[0]) is None


@pytest.mark.parametrize("wep_key_field", ["wep_key0", "wep_key1", "wep_key2", "wep_key3"])
def test_any_wep_key_index_is_other(tmp_path, wep_key_field):
    fields = {"ssid": '"Ufficio"', "key_mgmt": "NONE", wep_key_field: '"abcde"'}
    networks, _ = _read(tmp_path, store(block(**fields)))
    assert networks[0].security == "other"
    assert qr_payload(networks[0]) is None


@pytest.mark.parametrize("key_mgmt", ["WPA-PSK", "SAE", "WPA-PSK-SHA256", "FT-PSK"])
def test_protected_key_mgmt_without_password_is_wpa_nopass(tmp_path, key_mgmt):
    networks, _ = _read(tmp_path, store(block(ssid='"Ufficio"', key_mgmt=key_mgmt)))
    assert networks[0].security == "WPA-nopass"
    assert qr_payload(networks[0]) is None


def test_open_networks_without_psk_stay_open(tmp_path):
    networks, _ = _read(
        tmp_path,
        store(block(ssid='"Bar"', key_mgmt="NONE"), block(ssid='"Bar2"', key_mgmt="OWE")),
    )
    assert [n.security for n in networks] == ["open", "open"]


def test_block_left_open_at_the_end_is_kept(tmp_path):
    text = 'Old_Version_Style\nnetwork={\n\tssid="Coda"\n\tkey_mgmt=NONE\n'
    networks, _ = _read(tmp_path, text)
    assert [n.ssid for n in networks] == ["Coda"]


def test_qr_payload_for_wpa_escapes_special_characters():
    network = WifiNetwork(ssid='a;b,c:d"e\\f', security="WPA", password="p;q", hidden=True)
    assert qr_payload(network) == r'WIFI:T:WPA;S:a\;b\,c\:d\"e\\f;P:p\;q;H:true;;'


def test_qr_payload_for_open_network():
    assert qr_payload(WifiNetwork("Bar", "open", None, False)) == "WIFI:T:nopass;S:Bar;;"


def test_export_labels_wpa_nopass_networks_and_skips_their_qr(tmp_path):
    text = store(block(ssid='"Ufficio"', key_mgmt="WPA-PSK"))
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", text)
    out = tmp_path / "wifi.html"
    export_wifi(scan_dir, out)
    html = out.read_text(encoding="utf-8")
    assert "WPA (password not in backup)" in html
    assert "<svg" not in html


def test_export_writes_one_qr_code_per_network(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "export" / "wifi.html"

    result = export_wifi(scan_dir, out)

    assert (result.networks, result.with_password, result.skipped) == (3, 2, 0)
    html = out.read_text(encoding="utf-8")
    assert html.count("<svg") == 3
    assert "segreta123" in html
    assert "clear text" in html
    assert "<script" not in html


def test_export_escapes_names_and_passwords(tmp_path):
    text = store(block(ssid='"<script>alert(1)</script>"', psk='"a<b>&c"', key_mgmt="WPA-PSK"))
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", text)
    out = tmp_path / "wifi.html"
    export_wifi(scan_dir, out)
    html = out.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert "a&lt;b&gt;&amp;c" in html


def test_missing_category_raises(tmp_path):
    add_category(tmp_path, "CONTACT", [])
    with pytest.raises(WifiExportError, match="WIFICONFIG"):
        export_wifi(tmp_path, tmp_path / "wifi.html")


def test_no_network_blocks_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", "nothing here", supplicant=False)
    with pytest.raises(WifiExportError, match="no Wi-Fi configuration"):
        export_wifi(scan_dir, tmp_path / "wifi.html")


def test_only_nameless_blocks_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan", store(block(key_mgmt="NONE")))
    with pytest.raises(WifiExportError, match="no Wi-Fi networks"):
        export_wifi(scan_dir, tmp_path / "wifi.html")


def test_unwritable_output_raises(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    out.mkdir()
    with pytest.raises(WifiExportError, match="cannot write"):
        export_wifi(scan_dir, out)


def test_qr_codes_and_passwords_are_shown_only_on_request(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    export_wifi(scan_dir, out)
    html = out.read_text(encoding="utf-8")
    assert html.count("<summary>Show QR code</summary><svg") == 3
    assert html.count("<svg") == 3
    assert "<summary>Show password</summary><code>segreta123</code></details>" in html
    assert re.search(r"<td>segreta123</td>", html) is None


def test_network_without_password_has_no_password_section(tmp_path):
    scan_dir = build_wifi_scan_dir(tmp_path / "scan")
    out = tmp_path / "wifi.html"
    export_wifi(scan_dir, out)
    row = next(r for r in out.read_text(encoding="utf-8").split("<tr>") if "Bar Aperto" in r)
    assert "Show password" not in row
    assert "Show QR code" in row
