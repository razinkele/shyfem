# Phase 24: Fix Pre-Existing Test Failures — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate all 29 async test failures by properly isolating Playwright e2e tests from unit tests. Target: 429+ passed, 0 failed.

**Architecture:** Add pytest markers and default ignore-glob for Playwright files. No code changes to async tests needed.

**Tech Stack:** pytest configuration (pyproject.toml), pytest markers

---

### Task 1: Configure pytest markers and default ignores

**Files:**
- Modify: `pyproject.toml` (lines 78-80)

**Step 1: Update pyproject.toml**

Add markers and addopts to `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--ignore-glob=tests/test_playwright_*.py"
markers = [
    "e2e: end-to-end browser tests (require Playwright + live server)",
    "slow: tests that take more than 5 seconds",
]
```

**Step 2: Run unit tests to verify 0 failures**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 429+ passed, 0 failed (Playwright tests auto-excluded by addopts)

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "fix: exclude Playwright tests from default pytest runs

Playwright's sync_playwright() creates a background event loop that
conflicts with pytest-asyncio's Runner. Adding --ignore-glob to addopts
ensures unit tests run without event loop interference."
```

---

### Task 2: Add e2e markers to Playwright test files

**Files:**
- Modify: `tests/test_playwright_active_project.py`
- Modify: `tests/test_playwright_dashboard.py`
- Modify: `tests/test_playwright_interactions.py`
- Modify: `tests/test_playwright_navigation.py`
- Modify: `tests/test_playwright_pages.py`

**Step 1: Add `pytestmark` to each file**

Add `pytestmark = [pytest.mark.e2e]` (or extend the existing pytestmark list)
at the top of each Playwright test file. For files that already have
`pytestmark = pytest.mark.usefixtures(...)`, convert to a list:

```python
pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]
```

For files without existing pytestmark, add:

```python
pytestmark = pytest.mark.e2e
```

**Step 2: Verify e2e marker works for selection**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -m e2e --collect-only --no-header -q 2>&1 | tail -3`
Expected: Shows only Playwright test items

**Step 3: Commit**

```bash
git add tests/test_playwright_*.py
git commit -m "test: add e2e marker to all Playwright test files"
```

---

### Task 3: Final verification and TODO update

**Step 1: Run full unit test suite (default)**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 429+ passed, 0 failed, 0 warnings about unknown markers

**Step 2: Verify e2e tests can still be run explicitly**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_active_project.py --collect-only -q`
Expected: Collects Playwright tests (they may skip if no browser)

**Step 3: Update TODO_NEXT.md**

Mark Phase 24 items complete.

**Step 4: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 24 test failures fixed in TODO_NEXT.md"
```
