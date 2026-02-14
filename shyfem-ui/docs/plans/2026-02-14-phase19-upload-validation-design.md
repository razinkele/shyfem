# Phase 19: File Upload & Input Validation — Design

**Date:** 2026-02-14
**Scope:** Add file size and extension validation to the single upload widget

## Context

Only one actual file upload widget exists: `file_browser` component used in grid_prep.py.
All other pages use text path inputs reading from the server filesystem. The original spec
item 19.4 (Content-Length ASGI middleware) is skipped because Shiny uploads go over WebSocket.

## Changes

### 1. Config class (`config.py`)
Add `max_upload_size_mb: int = 500` (env: `SHYFEM_UI_MAX_UPLOAD_SIZE_MB`).

### 2. File browser component (`components/file_browser.py`)
In `file_browser_server()`, before calling `on_select` callback:
- **Size check**: `file_info["size"]` vs `config.max_upload_size_mb * 1024 * 1024`
- **Extension check**: `Path(file_info["name"]).suffix.lower()` vs `accept` list

Both failures show `ui.notification_show(..., type="error")` and return early.

### 3. No other changes needed
- No MIME type checking (unreliable for .grd/.bas)
- No Content-Length middleware (WebSocket uploads bypass it)
- No per-page extension config (YAGNI — one upload widget)
