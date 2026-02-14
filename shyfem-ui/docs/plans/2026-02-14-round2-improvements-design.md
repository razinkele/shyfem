# SHYFEM UI — Round 2 Improvements Design

**Date:** 2026-02-14
**Scope:** 16 phases (18–33) covering security, testing, features, performance, multi-user, and polish
**Baseline:** Phases 1–17 complete, 404 tests collected (387 passing, 17 pre-existing failures)

## Context

Round 1 (phases 1–8) built the application from scratch. Round 1.5 (phases 9–17) added test
isolation, lint cleanup, Docker hardening, component tests, Alembic migrations, performance
improvements, UX polish, CI/CD, and documentation.

A codebase audit identified these remaining gaps:
- **40+ silent exception handlers** (`except Exception: pass`) across 8 files
- **8 source files with no test coverage** (4 components, 3 pages partially tested, middleware)
- **17 pre-existing test failures** in test_workflow.py and test_wrapper.py
- **No file upload size limits** or CSRF protection
- **Rate limiter ignores proxies** (uses raw client IP)
- **No data export** (plots, CSVs, reports)
- **No session isolation** in server mode

## Design Decisions

### Error Handling Strategy
Replace all `except Exception: pass` with `except Exception as exc: logger.exception("context")`
followed by a graceful fallback (empty list, default value, notification). Never silently swallow.

### Testing Target
From 387 passing → 500+ passing, 0 failures. Fix the 17 async failures, add middleware tests,
component tests, and extracted page logic tests.

### Feature Scope
Real-time log streaming, data export, NetCDF explorer — all additive, no breaking changes.
Template expansion and project import/export are content additions.

### Multi-User Model
Session-based filtering (Shiny session ID), not full user accounts. Admin toggle for "All Jobs".
Health/metrics endpoints for production monitoring.

## Phase Summary

| Phase | Category | Description |
|-------|----------|-------------|
| 18 | Security | Error handling audit — replace 40+ silent exception blocks |
| 19 | Security | File upload & input validation — size limits, extension checks |
| 20 | Security | Proxy support & CSRF — X-Forwarded-For, CSRF tokens |
| 21 | Testing | Middleware tests — rate limiter, auth, session cleanup, migrations |
| 22 | Testing | Component tests — job_status, file_browser, log_viewer, plot_widget |
| 23 | Testing | Page logic tests — compare, ensemble, visualize pure functions |
| 24 | Testing | Fix 17 pre-existing failures, add pytest markers |
| 25 | Feature | Real-time log streaming via reactive push |
| 26 | Feature | Data export — PNG/SVG plots, CSV data, HTML reports |
| 27 | Feature | NetCDF variable explorer with dimension slicing |
| 28 | Performance | Database query optimization — eager loading, pagination, pooling |
| 29 | Performance | Frontend optimization — cache headers, lazy tab content |
| 30 | Multi-user | Session isolation — per-session job/project filtering |
| 31 | Ops | Health endpoint, structured logging, Prometheus metrics |
| 32 | Content | STR template library expansion (5+ new templates) |
| 33 | Feature | Project import/export (ZIP archive + DB metadata) |
