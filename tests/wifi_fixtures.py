"""Fabricated Wi-Fi backup for tests - no real networks or passwords."""

from __future__ import annotations

from pathlib import Path

from tests.scan_fixtures import add_category, entry


def block(**fields: str) -> str:
    lines = "".join(f"\t{key}={value}\n" for key, value in fields.items())
    return "network={\n" + lines + "}\n\n"


NEW_STYLE = (
    "New_Version_Style\n<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"
    "<WifiBackupData><NetworkList><Network><WifiConfiguration>"
    "<string name=\"SSID\">&quot;OnlyInNewStyle&quot;</string>"
    "</WifiConfiguration></Network></NetworkList></WifiBackupData>\n"
)


def store(*blocks: str, new_style: bool = True) -> str:
    return "Old_Version_Style\n" + "".join(blocks) + (NEW_STYLE if new_style else "")


DEFAULT = store(
    block(ssid='"Casa"', psk='"segreta123"', key_mgmt="SAE"),
    block(ssid='"Casa"', psk='"segreta123"', key_mgmt="WPA-PSK"),
    block(ssid='"Bar Aperto"', key_mgmt="NONE"),
    block(ssid='"Bar Aperto"', key_mgmt="OWE"),
    block(ssid='"Nascosta"', scan_ssid="1", psk='"x"', key_mgmt="WPA-PSK"),
)


def build_wifi_scan_dir(scan_dir: Path, text: str = DEFAULT, *, supplicant: bool = True) -> Path:
    folder = scan_dir / "WIFICONFIG" / "WIFICONFIG.zip"
    folder.mkdir(parents=True)
    (folder / "WifiConfigStore.xml").write_text(text, encoding="utf-8")
    files = [entry("WIFICONFIG.zip/WifiConfigStore.xml", kind="text")]
    if supplicant:
        (folder / "wpa_supplicant.conf").write_text(text.split("New_Version_Style")[0], encoding="utf-8")
        files.append(entry("WIFICONFIG.zip/wpa_supplicant.conf", kind="text"))
    (folder / "wifi_wpaconf.xml").write_text("<Wi-Fi><model>X</model></Wi-Fi>", encoding="utf-8")
    files.append(entry("WIFICONFIG.zip/wifi_wpaconf.xml", kind="xml"))
    add_category(scan_dir, "WIFICONFIG", files)
    return scan_dir
