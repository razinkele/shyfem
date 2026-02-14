# Phase 20: Proxy Support for Rate Limiting — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix rate limiter to use real client IP behind reverse proxies via trusted_proxies config and X-Forwarded-For parsing.

**Architecture:** Add `trusted_proxies` config field, implement `get_client_ip()` pure function with TDD, then wire it into existing `RateLimitMiddleware`. The pure function is independently testable — no ASGI mocking needed.

**Tech Stack:** Python stdlib `ipaddress`, Pydantic settings, pytest

---

### Task 1: Add `trusted_proxies` config field with test

**Files:**
- Modify: `shyfem_ui/config.py:125-131` (add field after rate_limit_rpm)
- Modify: `tests/test_config.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_config.py` in the `TestConfigDefaults` class:

```python
    def test_default_trusted_proxies(self):
        """Test trusted_proxies defaults to empty list."""
        config = _clean_config()
        assert config.trusted_proxies == []
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py::TestConfigDefaults::test_default_trusted_proxies -v`
Expected: FAIL with `AttributeError`

**Step 3: Implement — add field to Config**

In `shyfem_ui/config.py`, after the `max_upload_size_mb` field block (after line 131), add:

```python
    # Proxy settings (server mode)
    trusted_proxies: list[str] = Field(
        default_factory=list,
        description="Trusted proxy CIDR ranges for X-Forwarded-For (e.g., ['127.0.0.1/8', '10.0.0.0/8'])"
    )
```

**Step 4: Run all config tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -v --tb=short`
Expected: All 30 tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_config.py && git commit -m "feat: add trusted_proxies config field

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Implement `get_client_ip()` with TDD

**Files:**
- Modify: `shyfem_ui/app.py` (add function before RateLimitMiddleware class)
- Create: `tests/test_proxy.py` (new test file)

**Step 1: Create test file with comprehensive tests**

Create `tests/test_proxy.py`:

```python
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
        # 127.0.0.1 = trusted, 10.0.0.5 = trusted, 203.0.113.50 = not trusted → return it
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
        # Should not crash — falls back gracefully
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_proxy.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_client_ip'`

**Step 3: Implement `get_client_ip()`**

In `shyfem_ui/app.py`, add after the existing imports (after line 10 `from pathlib import Path`) and before line 12 (`import shinyswatch`):

```python
import ipaddress
```

Then add the function BEFORE the `RateLimitMiddleware` class (before line 188). A good location is right after the `BasicAuthMiddleware` class (after line 185):

```python
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

    # Parse trusted networks once
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
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_proxy.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_proxy.py && git commit -m "feat: add get_client_ip() with trusted proxy X-Forwarded-For parsing

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire `get_client_ip()` into RateLimitMiddleware

**Files:**
- Modify: `shyfem_ui/app.py:188-226` (update RateLimitMiddleware)
- Modify: `shyfem_ui/app.py:86-88` (pass trusted_proxies at registration)

**Step 1: Update RateLimitMiddleware constructor**

Change the constructor from:

```python
class RateLimitMiddleware:
    """ASGI middleware that enforces per-client request rate limits."""

    def __init__(self, app, rpm: int = 120):
        self.app = app
        self.rpm = rpm
        self._window = 60.0  # 1 minute sliding window
        self._requests: dict[str, list[float]] = defaultdict(list)
```

To:

```python
class RateLimitMiddleware:
    """ASGI middleware that enforces per-client request rate limits."""

    def __init__(self, app, rpm: int = 120, trusted_proxies: list[str] | None = None):
        self.app = app
        self.rpm = rpm
        self.trusted_proxies = trusted_proxies or []
        self._window = 60.0  # 1 minute sliding window
        self._requests: dict[str, list[float]] = defaultdict(list)
```

**Step 2: Update client key extraction in `__call__`**

In the `__call__` method, replace:

```python
        client = scope.get("client", ("unknown", 0))
        client_key = f"{client[0]}:{client[1]}"
```

With:

```python
        client_key = get_client_ip(scope, self.trusted_proxies)
```

**Step 3: Update middleware registration in `create_app()`**

In `create_app()`, change line 88 from:

```python
        app = RateLimitMiddleware(app, rpm=config.rate_limit_rpm)
```

To:

```python
        app = RateLimitMiddleware(app, rpm=config.rate_limit_rpm, trusted_proxies=config.trusted_proxies)
```

**Step 4: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short --ignore=tests/test_playwright_active_project.py --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_interactions.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py`
Expected: All tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/app.py && git commit -m "feat: wire get_client_ip into RateLimitMiddleware

Rate limiter now respects trusted_proxies config and extracts
real client IP from X-Forwarded-For when behind a reverse proxy.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Update TODO_NEXT.md and final verification

**Files:**
- Modify: `TODO_NEXT.md` — check off Phase 20 items

**Step 1: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short --ignore=tests/test_playwright_active_project.py --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_interactions.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py`
Expected: All tests PASS including 11 new proxy tests + 1 new config test

**Step 2: Update TODO_NEXT.md**

Check off items 20.1, 20.2. Mark 20.3 as skipped with a note.

**Step 3: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md && git commit -m "docs: mark phase 20 proxy support complete

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
