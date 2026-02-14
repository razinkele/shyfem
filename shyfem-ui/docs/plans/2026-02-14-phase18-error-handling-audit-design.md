# Phase 18: Error Handling Audit — Design

**Date:** 2026-02-14
**Scope:** Replace 28 silent exception handlers across 8 files with logged handlers + graceful fallbacks

## Context

Round 1.5 (phases 9–17) left 28 silent exception handlers (`except Exception: pass/continue/return`)
across 8 files. These hide bugs and make debugging impossible. This phase adds logging to every one.

## Decisions

- **All 28 handlers get logging** — no exception goes unlogged
- **Medium+ severity** (8 handlers): `logger.warning`/`logger.exception` + `ui.notification_show` where user-visible
- **Low severity** (20 handlers): `logger.debug` — visible in debug mode, silent in production
- **No new dependencies** — only stdlib `logging`

## Severity Tiers

| Tier | Logging | UI Notification | Criteria |
|------|---------|----------------|----------|
| Medium+ | `logger.warning` or `logger.exception` | `ui.notification_show(..., type="warning")` | Failure hides a bug or skips a visible feature |
| Low | `logger.debug` | None | Intentional fallback, parsing, retries |

## Changes Per File

### 1. `components/str_editor.py` (3 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 146 | Medium | `logger.warning("Failed to re-parse editor content for form sync", exc_info=True)` |
| 171 | Low | `logger.debug("Skipping form field conversion: %s", exc)` |
| 602 | Low | `logger.debug("Could not parse range value: %s", ...)` |

### 2. `components/timeseries.py` (5 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 170, 276, 385 | Low | `logger.debug("Column selection unavailable, using defaults")` |
| 433 | Low | `logger.debug("CSV parsing failed, falling back to whitespace-delimited")` |
| 447 | Low | `logger.debug("Skipping non-numeric line in fallback parser")` |

### 3. `pages/ensemble.py` (7 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 300, 304, 308 | Low | `logger.debug("Form field %s unavailable, using cached value", field)` |
| 565 | Low | `logger.debug("Ensemble status poll failed, retrying in 5s")` |
| 789, 793 | Low | `logger.debug("Value '%s' is not numeric, keeping as string", value)` |
| 836 | Medium | `logger.warning("Failed to load time series from %s", path, exc_info=True)` |
| 929 | Medium | `logger.warning(...)` + `ui.notification_show("Could not compute ensemble envelope", type="warning")` |

### 4. `pages/postprocess.py` (4 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 378, 386 | Low | `logger.debug("UI selection unavailable: %s", ...)` |
| 624 | Low | `logger.debug("Could not stat file %s", path)` |
| 764 | Low | `logger.debug("Skipping non-numeric line")` |
| 776 | Medium | `logger.warning(...)` + `ui.notification_show("Could not load time series preview", type="warning")` |

### 5. `pages/run.py` (2 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 301 | Low | `logger.debug("Auto-refresh poll failed, retrying in 5s")` |
| 813 | Low | `logger.debug("Workflow template selection unavailable")` |

### 6. `pages/compare.py` (2 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 165 | Low | `logger.debug("Job ID inputs unavailable, skipping comparison")` |
| 466 | Low | `logger.debug("Skipping non-numeric line in time series")` |

### 7. `db/base.py` (1 handler)

| Line | Severity | Change |
|------|----------|--------|
| 112 | Medium | `logger.exception("Database session error, rolling back")` before rollback |

### 8. `services/job_celery.py` (4 handlers)

| Line | Severity | Change |
|------|----------|--------|
| 367 | Medium | `logger.warning("Failed to read output file: %s", path, exc_info=True)` |
| 400 | Low | `logger.debug("Failed to clean up file: %s", path)` |
| 431 | Medium | `logger.warning("Health check failed", exc_info=True)` |
| 455 | Low | `logger.debug("Failed to inspect Celery workers")` |

## Logger Setup

Each file that doesn't already have a logger gets `logger = logging.getLogger(__name__)` at module level.

## Verification

1. `make lint` — 0 errors
2. `make test` — 0 new failures
3. `python -m shyfem_ui.app` — app launches without warnings
4. `grep -rn "except.*:$\s*pass" shyfem_ui/` — 0 remaining bare pass handlers
