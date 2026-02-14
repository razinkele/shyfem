# Phase 20: Proxy Support for Rate Limiting — Design

**Date:** 2026-02-14
**Scope:** Fix rate limiter to use real client IP behind reverse proxies

## Context

RateLimitMiddleware uses `scope["client"][0]` which returns the proxy's IP behind
nginx/Caddy, making all users share one rate limit bucket. CSRF (item 20.3) skipped
because Shiny is WebSocket-first with same-origin protection.

## Changes

### 1. Config (`config.py`)
Add `trusted_proxies: list[str] = []` — CIDR strings (e.g., `["127.0.0.1/8"]`).
Empty = don't trust any proxy (current behavior preserved).

### 2. Helper function (`app.py`)
`get_client_ip(scope, trusted_proxies)` — pure function:
- Empty trusted_proxies → `scope["client"][0]`
- ASGI client IP in trusted CIDR → rightmost non-trusted IP from X-Forwarded-For
- Untrusted proxy → `scope["client"][0]`

Uses stdlib `ipaddress` module, no new dependencies.

### 3. RateLimitMiddleware (`app.py`)
Accept `trusted_proxies` in constructor. Use `get_client_ip()` for client key.

### Skipped
- 20.3 CSRF tokens — WebSocket same-origin policy suffices
- X-Real-IP header — X-Forwarded-For is the standard
