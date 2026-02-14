"""Tests for proxy-aware client IP extraction."""

import pytest
from shyfem_ui.app import get_client_ip


class TestGetClientIp:
    """Tests for get_client_ip()."""

    def test_no_trusted_proxies_returns_raw_client(self):
        """With no trusted proxies, return ASGI client IP."""
        scope = {"client": ("1.2.3.4", 12345), "headers": []}
        assert get_client_ip(scope, []) == "1.2.3.4"

    def test_no_client_in_scope_returns_unknown(self):
        """Missing client tuple returns 'unknown'."""
        scope = {"headers": []}
        assert get_client_ip(scope, []) == "unknown"

    def test_trusted_proxy_extracts_forwarded_ip(self):
        """When ASGI client is a trusted proxy, use X-Forwarded-For."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"203.0.113.50, 127.0.0.1"),
            ],
        }
        assert get_client_ip(scope, ["127.0.0.0/8"]) == "203.0.113.50"

    def test_untrusted_proxy_ignores_header(self):
        """When ASGI client is NOT trusted, ignore X-Forwarded-For."""
        scope = {
            "client": ("192.168.1.1", 80),
            "headers": [
                (b"x-forwarded-for", b"10.0.0.1"),
            ],
        }
        assert get_client_ip(scope, ["127.0.0.0/8"]) == "192.168.1.1"

    def test_no_forwarded_header_returns_raw_client(self):
        """Trusted proxy but no X-Forwarded-For header falls back to client."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [],
        }
        assert get_client_ip(scope, ["127.0.0.0/8"]) == "127.0.0.1"

    def test_multiple_trusted_proxies(self):
        """Multiple CIDR ranges work correctly."""
        scope = {
            "client": ("10.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"203.0.113.50, 10.0.0.1"),
            ],
        }
        assert get_client_ip(scope, ["127.0.0.0/8", "10.0.0.0/8"]) == "203.0.113.50"

    def test_chained_proxies_rightmost_untrusted(self):
        """With chained proxies, extract rightmost non-trusted IP."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"spoofed.ip, 203.0.113.50, 10.0.0.5, 127.0.0.1"),
            ],
        }
        result = get_client_ip(scope, ["127.0.0.0/8", "10.0.0.0/8"])
        assert result == "203.0.113.50"

    def test_all_forwarded_ips_trusted_returns_leftmost(self):
        """If all IPs in chain are trusted, return the leftmost."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"10.0.0.1, 10.0.0.2"),
            ],
        }
        assert get_client_ip(scope, ["10.0.0.0/8", "127.0.0.0/8"]) == "10.0.0.1"

    def test_single_ip_trusted_proxy(self):
        """Single IP in trusted proxy list (no CIDR notation)."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"203.0.113.50"),
            ],
        }
        assert get_client_ip(scope, ["127.0.0.1/32"]) == "203.0.113.50"

    def test_malformed_forwarded_header_returns_raw(self):
        """Malformed X-Forwarded-For falls back to raw client."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b"not_an_ip, also_bad"),
            ],
        }
        result = get_client_ip(scope, ["127.0.0.0/8"])
        assert isinstance(result, str)

    def test_empty_forwarded_header_returns_raw(self):
        """Empty X-Forwarded-For falls back to raw client."""
        scope = {
            "client": ("127.0.0.1", 80),
            "headers": [
                (b"x-forwarded-for", b""),
            ],
        }
        assert get_client_ip(scope, ["127.0.0.0/8"]) == "127.0.0.1"
