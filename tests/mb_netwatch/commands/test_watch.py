"""Tests for watch command formatting functions."""

import time

from mb_netwatch.cli.commands.watch import _format_ip, _format_row, _format_vpn
from mb_netwatch.core.db import IpCheckRow, LatencyRow, VpnCheckRow


class TestFormatVpn:
    """VPN status formatting."""

    def test_none(self):
        """None input produces question mark."""
        assert _format_vpn(None) == "VPN:?"

    def test_inactive(self):
        """Inactive VPN shows off."""
        vpn = VpnCheckRow(created_at=0.0, updated_at=0.0, is_active=False, tunnel_mode="full", provider=None)
        assert _format_vpn(vpn) == "VPN:off"

    def test_active_no_provider(self):
        """Active VPN without provider shows tunnel mode."""
        vpn = VpnCheckRow(created_at=0.0, updated_at=0.0, is_active=True, tunnel_mode="full", provider=None)
        assert _format_vpn(vpn) == "VPN:on full"

    def test_active_with_provider(self):
        """Active VPN with provider shows provider and tunnel mode."""
        vpn = VpnCheckRow(created_at=0.0, updated_at=0.0, is_active=True, tunnel_mode="split", provider="NordVPN")
        assert _format_vpn(vpn) == "VPN:on NordVPN split"


class TestFormatIp:
    """IP check formatting."""

    def test_none(self):
        """None input produces question mark."""
        assert _format_ip(None) == "IP:?"

    def test_null_ip(self):
        """Row with ip=None produces question mark."""
        ip = IpCheckRow(created_at=0.0, updated_at=0.0, ip=None, country_code=None)
        assert _format_ip(ip) == "IP:?"

    def test_ip_no_country(self):
        """IP without country shows just the address."""
        ip = IpCheckRow(created_at=0.0, updated_at=0.0, ip="1.2.3.4", country_code=None)
        assert _format_ip(ip) == "IP:1.2.3.4"

    def test_ip_with_country(self):
        """IP with country shows address and country in parens."""
        ip = IpCheckRow(created_at=0.0, updated_at=0.0, ip="1.2.3.4", country_code="US")
        assert _format_ip(ip) == "IP:1.2.3.4(US)"


class TestFormatRow:
    """Full row formatting combining latency, VPN, and IP."""

    def test_normal_latency(self):
        """Normal latency shows ms value."""
        ts = time.time()
        row = LatencyRow(ts=ts, latency_ms=42.0, winner_endpoint="https://example.com")
        result = _format_row(row, None, None)
        assert "42ms" in result
        assert "VPN:?" in result
        assert "IP:?" in result

    def test_down(self):
        """None latency shows 'down'."""
        ts = time.time()
        row = LatencyRow(ts=ts, latency_ms=None, winner_endpoint=None)
        result = _format_row(row, None, None)
        assert "down" in result

    def test_combines_all(self):
        """Combines latency, VPN, and IP strings."""
        ts = time.time()
        row = LatencyRow(ts=ts, latency_ms=100.0, winner_endpoint="x")
        vpn = VpnCheckRow(created_at=0.0, updated_at=0.0, is_active=True, tunnel_mode="full", provider="WG")
        ip = IpCheckRow(created_at=0.0, updated_at=0.0, ip="5.6.7.8", country_code="DE")
        result = _format_row(row, vpn, ip)
        assert "100ms" in result
        assert "VPN:on WG full" in result
        assert "IP:5.6.7.8(DE)" in result
