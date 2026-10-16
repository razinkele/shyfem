"""ASGI middleware for per-client request rate limiting."""

import ipaddress
import logging
import time
from collections import defaultdict

from shyfem_ui.middleware.cache_headers import is_static_asset_request

logger = logging.getLogger(__name__)


def get_client_ip(scope: dict, trusted_proxies: list[str]) -> str:
    """Extract real client IP, respecting trusted proxy X-Forwarded-For.

    Uses the rightmost-untrusted algorithm: walk X-Forwarded-For from right
    to left, skipping IPs that match a trusted CIDR, and return the first
    untrusted IP. If all are trusted, return the leftmost.

    Args:
        scope: ASGI scope dict (needs 'client' and 'headers').
        trusted_proxies: List of CIDR strings (e.g., ["127.0.0.0/8"]).

    Returns:
        Client IP string.
    """
    client = scope.get("client")
    raw_ip = client[0] if client else "unknown"

    if not trusted_proxies:
        return raw_ip

    # Parse trusted networks
    try:
        networks = [ipaddress.ip_network(cidr, strict=False) for cidr in trusted_proxies]
    except ValueError:
        return raw_ip

    # Check if the direct client is a trusted proxy
    try:
        client_addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return raw_ip

    if not any(client_addr in net for net in networks):
        return raw_ip

    # Client is trusted — parse X-Forwarded-For
    xff = None
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"x-forwarded-for":
            xff = header_value.decode("latin-1")
            break

    if not xff:
        return raw_ip

    # Walk right-to-left, find rightmost non-trusted IP
    ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
    if not ips:
        return raw_ip

    for ip_str in reversed(ips):
        try:
            addr = ipaddress.ip_address(ip_str)
            if not any(addr in net for net in networks):
                return ip_str
        except ValueError:
            continue

    # All trusted — return leftmost
    return ips[0]


class RateLimitMiddleware:
    """ASGI middleware that enforces per-client request rate limits."""

    def __init__(
        self,
        app,
        rpm: int = 120,
        trusted_proxies: list[str] | None = None,
        max_clients: int = 10000,
        static_rpm: int | None = None,
    ):
        self.app = app
        self.rpm = rpm
        # Static assets (scripts, stylesheets, fonts) get their own bucket:
        # one page load fetches dozens, so counting them against ``rpm``
        # 429'd about the 5th load in a minute (broken page, api/whoami
        # refused), and a class behind one NAT address shares a bucket. Still
        # finite: an asset request with a forged session cookie costs a
        # validate_session DB read in SessionAuthMiddleware.
        self.static_rpm = static_rpm if static_rpm is not None else 20 * rpm
        self.trusted_proxies = trusted_proxies or []
        self._window = 60.0  # 1 minute sliding window
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max_clients = max_clients

        # This middleware is only wired in server mode, which on laguna always
        # sits behind the nginx -> Shiny Server proxy. With no trusted_proxies
        # the only client address we ever see is the proxy's, so every user
        # shares a single bucket and one busy client throttles everyone. Warn
        # loudly rather than silently degrading to per-server limiting.
        if not self.trusted_proxies:
            logger.warning(
                "Rate limiting is active but trusted_proxies is empty: behind a "
                "reverse proxy every request carries the proxy's IP, so all "
                "clients collapse into one bucket (per-server, not per-client). "
                "Set SHYFEM_UI_TRUSTED_PROXIES to your proxy's CIDR(s) so the "
                "real client IP is read from X-Forwarded-For."
            )

    def _prune_clients(self, now: float):
        """Evict stale client entries when dict exceeds max_clients."""
        if len(self._requests) <= self._max_clients:
            return
        cutoff = now - self._window
        # First pass: remove clients with no recent timestamps
        stale = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._requests[k]
        if len(self._requests) <= self._max_clients:
            return
        # Second pass: evict least-recently-active (oldest max timestamp)
        by_recency = sorted(self._requests.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
        to_remove = len(self._requests) - self._max_clients
        for k, _ in by_recency[:to_remove]:
            del self._requests[k]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Only static GET/HEAD moves to the asset bucket: this limiter is the
        # only brute-force guard on POST /login.
        client_ip = get_client_ip(scope, self.trusted_proxies)
        if is_static_asset_request(scope):
            client_key, limit = f"{client_ip}|static", self.static_rpm
        else:
            client_key, limit = client_ip, self.rpm
        now = time.monotonic()

        self._prune_clients(now)

        # Prune old entries outside the window
        timestamps = self._requests[client_key]
        cutoff = now - self._window
        self._requests[client_key] = [t for t in timestamps if t > cutoff]
        timestamps = self._requests[client_key]

        if len(timestamps) >= limit:
            body = b"Rate limit exceeded. Try again later."
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        [b"content-type", b"text/plain"],
                        [b"content-length", str(len(body)).encode()],
                        [b"retry-after", b"60"],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        timestamps.append(now)
        return await self.app(scope, receive, send)
