"""VPN detection via network interfaces, routing table, and scutil."""

import logging
import re
import socket
import subprocess  # nosec B404
from dataclasses import dataclass

import psutil

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VpnStatus:
    """Result of a single VPN detection check."""

    is_active: bool
    tunnel_mode: str  # "full", "split", or "unknown"
    provider: str | None


def detect_tunnel_interface() -> tuple[str, str] | None:
    """Find first tun/utun interface with an IPv4 address.

    Returns (interface_name, ip_address) or None if no tunnel interface found.
    """
    for name, addrs in psutil.net_if_addrs().items():
        if name.startswith(("tun", "utun")):
            for addr in addrs:
                if addr.family == socket.AF_INET and addr.address:
                    log.debug("vpn: found tunnel interface %s with IP %s", name, addr.address)
                    return name, addr.address
    log.debug("vpn: no tunnel interface found")
    return None


def detect_tunnel_mode(vpn_interface: str) -> str:
    """Determine tunnel mode by analyzing the routing table.

    Parses ``netstat -rn -f inet`` output. Returns ``"full"`` if default route
    or OpenVPN-style 0/1 + 128.0/1 routes go through the VPN interface,
    ``"split"`` otherwise, or ``"unknown"`` on parse failure.
    """
    try:
        output = subprocess.check_output(["netstat", "-rn", "-f", "inet"], text=True, timeout=5)  # noqa: S607 — fixed system command, no user input  # nosec B603, B607
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("vpn: netstat failed: %s", exc)
        return "unknown"

    has_0_1 = False
    has_128_0_1 = False
    default_via_vpn = False

    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue

        dest, iface = parts[0], parts[3]
        if iface != vpn_interface:
            continue

        if dest == "0/1":
            has_0_1 = True
        elif dest == "128.0/1":
            has_128_0_1 = True
        elif dest == "default":
            default_via_vpn = True

    # OpenVPN-style full tunnel: two halves covering all IPs
    if has_0_1 and has_128_0_1:
        return "full"
    # Direct default route via VPN or split tunnel
    return "full" if default_via_vpn else "split"


def detect_provider() -> str | None:
    """Detect VPN provider via ``scutil --nc list``.

    Looks for a service with ``(Connected)`` status and extracts its name
    from the quoted string. Returns None if no connected service found.
    """
    try:
        output = subprocess.check_output(["scutil", "--nc", "list"], text=True, timeout=5)  # noqa: S607 — fixed system command, no user input  # nosec B603, B607
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("vpn: scutil failed: %s", exc)
        return None

    for line in output.splitlines():
        if "(Connected)" not in line:
            continue
        # Service name is the last quoted string on the line
        match = re.search(r'"([^"]+)"', line)
        if match:
            return match.group(1)

    return None


def check_vpn() -> VpnStatus:
    """Detect current VPN status: active/inactive, tunnel mode, and provider."""
    iface_result = detect_tunnel_interface()
    if iface_result is None:
        return VpnStatus(is_active=False, tunnel_mode="unknown", provider=None)

    interface, _ip = iface_result
    tunnel_mode = detect_tunnel_mode(interface)
    provider = detect_provider()

    return VpnStatus(is_active=True, tunnel_mode=tunnel_mode, provider=provider)
