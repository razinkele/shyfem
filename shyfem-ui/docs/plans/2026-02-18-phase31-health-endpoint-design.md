# Phase 31: Health Endpoint — Design

**Date:** 2026-02-18
**Status:** Design approved

## Scope

A single `/health` ASGI middleware that responds to `GET /health` with a
JSON status payload. Bypasses auth and rate limiting. No new dependencies.

## Middleware: `HealthCheckMiddleware`

- Outermost wrapper in `create_app()` (after rate limiter)
- Intercepts `GET /health` — returns JSON directly
- All other requests (including `POST /health`) pass through unchanged
- WebSocket scopes pass through

## Response Payload

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 12345,
  "database": "ok",
  "active_jobs": 3
}
```

- `version`: from `shyfem_ui.__version__`
- `uptime_seconds`: `time.monotonic() - start_time` (captured at init)
- `database`: `"ok"` if `SELECT 1` succeeds, `"error"` otherwise
- `active_jobs`: count of active jobs from job queue (-1 on error)
- `status`: `"ok"` if all healthy, `"degraded"` if any component fails

## Middleware Stack (after change)

1. `App(app_ui, server)` — core Shiny app (innermost)
2. `CacheHeaderMiddleware` — static asset Cache-Control
3. `_WsDebugMiddleware` — debug WS logging
4. `BasicAuthMiddleware` — HTTP Basic Auth
5. `RateLimitMiddleware` — rate limiting
6. `HealthCheckMiddleware` — health endpoint (outermost, bypasses everything)

## Testing

- Returns 200 + JSON for healthy state
- Database error → `"database": "error"` + `"status": "degraded"`
- Job queue error → `"active_jobs": -1` + `"status": "degraded"`
- Non-health paths pass through
- WebSocket bypasses
- Only GET responds (POST /health passes through)

## Skipped

- **31.2 Structured JSON logging** — Low priority, can add later
- **31.3 Prometheus /metrics** — Adds dependency, significant instrumentation effort
