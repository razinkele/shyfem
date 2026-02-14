# Phase 24: Fix Pre-Existing Test Failures — Design

**Date:** 2026-02-14

## Root Cause

All 29 "pre-existing" async test failures share one root cause:
`test_playwright_active_project.py` was not excluded from unit test runs.

Playwright's `sync_playwright().start()` creates a background event loop via
greenlets. When pytest-asyncio later creates its own `asyncio.Runner` for
`@pytest.mark.asyncio` tests, it detects the Playwright loop and raises
"Runner.run() cannot be called from a running event loop."

**Evidence:** Ignoring all 5 `test_playwright_*.py` files yields 429 passed, 0 failed.

## Fix

1. Register `e2e` and `slow` pytest markers in `pyproject.toml`
2. Add `--ignore-glob=tests/test_playwright_*.py` as default addopts so
   `pytest` excludes Playwright tests by default
3. Add `@pytest.mark.e2e` to all Playwright test files for selective running
4. Document: run e2e tests explicitly with `pytest tests/test_playwright_*.py`

## Skipped from Original TODO

- 24.1/24.2 "Fix async event loop issues" — no code fix needed, just correct
  test isolation
- 24.3 "Add pytest markers" — included (e2e + slow markers registered)
