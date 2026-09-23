"""List the Wi-Fi networks Phase 1 recovered, with a QR code to re-add each one."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import segno

from ssba.core.parsers.html_page import esc, page, write_output
from ssba.core.parsers.scan_report import ScanReportError, category_files

# WifiConfigStore.xml holds wpa_supplicant blocks, then this marker and
# Android's XML backup, whose networks are all also in the blocks.
_NEW_STYLE_MARKER = "New_Version_Style"
_HEX = re.compile(r"(?:[0-9A-Fa-f]{2})+")
# Characters the ZXing WIFI: format requires to be backslash-escaped.
_QR_SPECIAL = re.compile(r'([\\;,:"])')
_SECURITY_LABELS = {
    "WPA": "WPA/WPA2/WPA3",
    "WPA-nopass": "WPA (password not in backup)",
    "open": "Open",
    "other": "Other (EAP/WEP)",
}
# key_mgmt values (wpa_supplicant, upper-cased, space-split) that mean the
# network is password-protected even when no psk was recovered.
_PROTECTED_KEY_MGMT = {"WPA-PSK", "SAE", "WPA-PSK-SHA256", "FT-PSK"}


class WifiExportError(Exception):
    """Raised when no Wi-Fi networks can be exported from a scan output directory."""


@dataclass
class WifiNetwork:
    ssid: str
    security: str  # "WPA", "open" or "other"
    password: str | None
    hidden: bool


@dataclass
class WifiExportResult:
    networks: int
    with_password: int
    skipped: int = 0


def _unquote(raw: str) -> str | None:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return None


def _ssid(raw: str) -> str:
    quoted = _unquote(raw)
    if quoted is not None:
        return quoted
    if _HEX.fullmatch(raw):
        return bytes.fromhex(raw).decode("utf-8", errors="replace")
    return raw


def _password(raw: str) -> str:
    # An unquoted psk is a raw 64-hex-digit key, which Android also accepts.
    quoted = _unquote(raw)
    return raw if quoted is None else quoted


def _blocks(text: str) -> list[dict[str, str]]:
    text = text.split(_NEW_STYLE_MARKER, 1)[0]
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "network={":
            current = {}
        elif stripped == "}" and current is not None:
            blocks.append(current)
            current = None
        elif current is not None and "=" in stripped:
            key, value = stripped.split("=", 1)
            current.setdefault(key.strip(), value.strip())
    if current is not None:  # truncated file: keep what was read
        blocks.append(current)
    return blocks


def read_networks(scan_dir: Path) -> tuple[list[WifiNetwork], int]:
    try:
        paths = category_files(scan_dir, "WIFICONFIG")
    except ScanReportError as exc:
        raise WifiExportError(str(exc)) from exc

    grouped: dict[str, list[dict[str, str]]] = {}
    skipped = 0
    found = False
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise WifiExportError(f"cannot read {path}: {exc}") from exc
        if "network={" not in text:
            continue
        found = True
        for block in _blocks(text):
            if "ssid" not in block:
                skipped += 1
                continue
            grouped.setdefault(_ssid(block["ssid"]), []).append(block)
    if not found:
        raise WifiExportError("no Wi-Fi configuration found in the scan output")

    networks = []
    for ssid, blocks in grouped.items():
        password = next(
            (_password(b["psk"]) for b in blocks if b.get("psk") and _password(b["psk"])),
            None,
        )
        other = any(
            "EAP" in b.get("key_mgmt", "").upper() or any(k.startswith("wep_key") for k in b)
            for b in blocks
        )
        protected = any(
            _PROTECTED_KEY_MGMT & set(b.get("key_mgmt", "").upper().split()) for b in blocks
        )
        if other:
            security = "other"
        elif password:
            security = "WPA"
        elif protected:
            security = "WPA-nopass"
        else:
            security = "open"
        hidden = any(b.get("scan_ssid") == "1" for b in blocks)
        networks.append(WifiNetwork(ssid, security, password, hidden))
    return networks, skipped


def _qr_escape(text: str) -> str:
    return _QR_SPECIAL.sub(r"\\\1", text)


def qr_payload(network: WifiNetwork) -> str | None:
    """The ZXing WIFI: text Android's camera and Wi-Fi settings understand."""
    if network.security in ("other", "WPA-nopass"):
        return None
    hidden = "H:true;" if network.hidden else ""
    ssid = _qr_escape(network.ssid)
    if network.security == "WPA":
        return f"WIFI:T:WPA;S:{ssid};P:{_qr_escape(network.password or '')};{hidden};"
    return f"WIFI:T:nopass;S:{ssid};{hidden};"


def export_wifi(scan_dir: Path, out_path: Path) -> WifiExportResult:
    networks, skipped = read_networks(scan_dir)
    if not networks:
        raise WifiExportError("no Wi-Fi networks found in the scan output")

    rows = []
    for network in networks:
        payload = qr_payload(network)
        if payload:
            svg = segno.make(payload, error="m", micro=False).svg_inline(scale=8)
            qr = f"<details><summary>Show QR code</summary>{svg}</details>"
        else:
            qr = "\u2014"
        password = (
            f"<details><summary>Show password</summary><code>{esc(network.password)}</code></details>"
            if network.password
            else "\u2014"
        )
        cells = (
            esc(network.ssid),
            esc(_SECURITY_LABELS[network.security]),
            "yes" if network.hidden else "no",
            qr,
            password,
        )
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    body = (
        '<p class="note">This page contains Wi-Fi passwords in clear text. Keep it private.</p>\n'
        "<p>To add a network on Android: Settings &rarr; Wi-Fi &rarr; the QR code icon "
        "next to &ldquo;Add network&rdquo;, then scan its code. Open \u201cShow QR code\u201d and scan it with the phone.</p>\n"
        "<table>\n<tr><th>Network</th><th>Security</th><th>Hidden</th><th>QR code</th><th>Password</th></tr>\n" + "\n".join(rows) + "\n</table>"
    )
    write_output(out_path, page("Wi-Fi networks", body), WifiExportError)
    return WifiExportResult(
        networks=len(networks),
        with_password=sum(n.password is not None for n in networks),
        skipped=skipped,
    )
