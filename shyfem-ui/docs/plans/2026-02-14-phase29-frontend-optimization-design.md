# Phase 29: Frontend Bundle Optimization — Design

**Date:** 2026-02-14
**Status:** Design approved, implementation pending

## Scope

Add ASGI middleware that injects `Cache-Control` headers on static asset
responses (CSS, JS, fonts, images). Inserted between rate limiter and
Shiny app in the middleware stack.

## How It Works

- New `CacheHeaderMiddleware` wraps the Shiny ASGI app
- Inspects `path` from ASGI `scope` on HTTP requests
- If path ends with static extension (`.css`, `.js`, `.woff2`, `.woff`,
  `.ttf`, `.png`, `.svg`, `.ico`), injects
  `Cache-Control: public, max-age=86400` (1 day) into response headers
- Non-matching paths pass through unchanged
- WebSocket connections bypass entirely

## Config

- `static_cache_max_age` config field (default 86400 seconds)
- Env var: `SHYFEM_UI_STATIC_CACHE_MAX_AGE`
- Set to 0 to disable caching headers

## Tests

- Mock ASGI app, verify headers added for static paths
- Verify headers NOT added for HTML/API paths
- WebSocket bypass
- Configurable max_age
- max_age=0 disables headers

## Skipped

- **29.2 Lazy tab rendering** — Invasive refactor of all 9 page modules.
  Shiny is server-rendered, not SPA. Low ROI.
- **29.3 Plotly precision** — Micro-optimization. Negligible benefit for
  current mesh sizes.
