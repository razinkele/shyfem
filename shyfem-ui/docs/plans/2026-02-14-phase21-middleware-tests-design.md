# Phase 21: Middleware & Infrastructure Tests — Design

**Date:** 2026-02-14
**Scope:** Unit tests for RateLimitMiddleware, BasicAuthMiddleware, and session cleanup

## Context

Three critical middleware components have zero unit tests. All can be tested with
pure ASGI scope/mock patterns — no HTTP server or Shiny session needed.

Alembic migration tests (21.4) skipped — low ROI given init_db() fallback logic
and only 2 migration files.

## Test Suites

### 1. RateLimitMiddleware (`tests/test_rate_limit.py`)
Mock ASGI app + synthetic scope dicts. Patch `time.monotonic` for window control.
- Under-limit requests pass through
- At-limit requests return 429 + Retry-After
- Sliding window resets after 60s
- WebSocket scopes bypass rate limiting
- Independent per-client buckets

### 2. BasicAuthMiddleware (`tests/test_basic_auth.py`)
Same ASGI mocking pattern with base64-encoded credentials.
- Valid credentials → inner app called
- Invalid/missing/malformed credentials → 401 + WWW-Authenticate
- WebSocket bad auth → close code 4001
- Non-http/websocket scopes → pass through

### 3. Session Cleanup (`tests/test_session_cleanup.py`)
Replicate `_on_session_ended` callback logic with mocked job_queue.
- Active jobs cancelled on session end
- Inactive jobs not cancelled
- Exceptions logged, not raised
- Empty job list → no cancellation

## Architecture
- Pure ASGI mocking — no HTTP client, no server startup
- No new dependencies
- ~20 tests total across 3 files
