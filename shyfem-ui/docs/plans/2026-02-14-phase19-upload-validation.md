# Phase 19: File Upload & Input Validation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add file size and extension validation to the file upload component to prevent resource exhaustion and invalid file processing.

**Architecture:** Add `max_upload_size_mb` config field, then add size + extension validation in `file_browser_server()` before the `on_file_selected` callback fires. TDD with tests first.

**Tech Stack:** Pydantic settings, Shiny `FileInfo`, pytest

---

### Task 1: Add `max_upload_size_mb` to Config with tests

**Files:**
- Modify: `shyfem_ui/config.py:81-86` (add field after `theme`)
- Modify: `tests/test_config.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_config.py` in the `TestConfigDefaults` class:

```python
    def test_default_max_upload_size(self):
        """Test default max upload size is 500 MB."""
        config = _clean_config()
        assert config.max_upload_size_mb == 500
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py::TestConfigDefaults::test_default_max_upload_size -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'max_upload_size_mb'`

**Step 3: Implement — add field to Config**

In `shyfem_ui/config.py`, after the `rate_limit_rpm` field (line 125), add:

```python
    # Upload limits
    max_upload_size_mb: int = Field(
        default=500,
        description="Maximum file upload size in MB"
    )
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -v --tb=short`
Expected: All 29 tests PASS (28 existing + 1 new)

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_config.py && git commit -m "feat: add max_upload_size_mb config field

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Add upload validation to `file_browser_server()` with tests

**Files:**
- Modify: `shyfem_ui/components/file_browser.py:39-60` (add validation in handler)
- Create: `tests/test_file_browser.py` (new test file)

**Step 1: Write failing tests**

Create `tests/test_file_browser.py`:

```python
"""Tests for file browser upload validation."""

from pathlib import Path

import pytest
from shyfem_ui.components.file_browser import validate_upload


class TestValidateUpload:
    """Tests for upload validation logic."""

    def test_valid_file(self):
        """Test valid file passes validation."""
        file_info = {"name": "grid.grd", "size": 1024}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert errors == []

    def test_file_too_large(self):
        """Test oversized file is rejected."""
        file_info = {"name": "huge.grd", "size": 600 * 1024 * 1024}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert len(errors) == 1
        assert "too large" in errors[0].lower()

    def test_invalid_extension(self):
        """Test wrong extension is rejected."""
        file_info = {"name": "malicious.exe", "size": 1024}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert len(errors) == 1
        assert ".exe" in errors[0]

    def test_no_accept_filter_allows_any_extension(self):
        """Test no accept filter allows any file type."""
        file_info = {"name": "anything.xyz", "size": 1024}
        errors = validate_upload(file_info, accept=None, max_size_bytes=500 * 1024 * 1024)
        assert errors == []

    def test_case_insensitive_extension(self):
        """Test extension check is case-insensitive."""
        file_info = {"name": "GRID.GRD", "size": 1024}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert errors == []

    def test_multiple_errors(self):
        """Test both size and extension errors reported."""
        file_info = {"name": "bad.exe", "size": 600 * 1024 * 1024}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert len(errors) == 2

    def test_zero_size_file(self):
        """Test zero-size file passes validation."""
        file_info = {"name": "empty.grd", "size": 0}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=500 * 1024 * 1024)
        assert errors == []

    def test_exact_max_size(self):
        """Test file at exact max size passes."""
        max_bytes = 500 * 1024 * 1024
        file_info = {"name": "exact.grd", "size": max_bytes}
        errors = validate_upload(file_info, accept=[".grd"], max_size_bytes=max_bytes)
        assert errors == []

    def test_multiple_accepted_extensions(self):
        """Test file matching one of multiple accepted extensions."""
        file_info = {"name": "data.bas", "size": 1024}
        errors = validate_upload(file_info, accept=[".grd", ".bas", ".str"], max_size_bytes=500 * 1024 * 1024)
        assert errors == []
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_browser.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_upload' from 'shyfem_ui.components.file_browser'`

**Step 3: Implement `validate_upload` function**

In `shyfem_ui/components/file_browser.py`, add after the imports (before `@module.ui`):

```python
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_upload(
    file_info: dict,
    accept: list[str] | None,
    max_size_bytes: int,
) -> list[str]:
    """Validate an uploaded file's size and extension.

    Args:
        file_info: Shiny FileInfo dict with 'name' and 'size' keys.
        accept: List of accepted extensions (e.g., [".grd"]). None allows all.
        max_size_bytes: Maximum file size in bytes.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []

    size = file_info.get("size", 0)
    if size > max_size_bytes:
        size_mb = size / (1024 * 1024)
        max_mb = max_size_bytes / (1024 * 1024)
        errors.append(f"File too large: {size_mb:.1f} MB (max {max_mb:.0f} MB)")

    if accept:
        suffix = Path(file_info.get("name", "")).suffix.lower()
        allowed = [ext.lower() for ext in accept]
        if suffix not in allowed:
            errors.append(
                f"Invalid file type: {suffix}. Expected: {', '.join(accept)}"
            )

    return errors
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_browser.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/components/file_browser.py shyfem-ui/tests/test_file_browser.py && git commit -m "feat: add validate_upload function with tests

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire validation into `file_browser_server()`

**Files:**
- Modify: `shyfem_ui/components/file_browser.py:39-60` (add validation call in handler)

**Step 1: Modify `file_browser_server` to accept `accept` parameter and validate**

The current function signature is:
```python
@module.server
def file_browser_server(
    input,
    output,
    session,
    on_file_selected: Callable[[list[FileInfo]], None] | None = None,
):
```

Change to:
```python
@module.server
def file_browser_server(
    input,
    output,
    session,
    on_file_selected: Callable[[list[FileInfo]], None] | None = None,
    accept: list[str] | None = None,
):
```

Then modify the `_handle_file_selection` effect:

```python
    @reactive.effect
    @reactive.event(input.file_input)
    def _handle_file_selection():
        from shyfem_ui.config import get_config

        files = input.file_input()
        if not files:
            return

        config = get_config()
        max_size_bytes = config.max_upload_size_mb * 1024 * 1024

        valid_files = []
        for f in files:
            errors = validate_upload(f, accept=accept, max_size_bytes=max_size_bytes)
            if errors:
                for err in errors:
                    ui.notification_show(err, type="error", duration=8)
                    logger.warning("Upload rejected: %s — %s", f.get("name", "?"), err)
            else:
                valid_files.append(f)

        if valid_files:
            selected_files.set(valid_files)
            if on_file_selected:
                on_file_selected(valid_files)
```

**Step 2: Update grid_prep.py to pass `accept` to server**

In `shyfem_ui/pages/grid_prep.py` at line 146, change:
```python
    file_browser_server("grd_file", on_file_selected=_handle_file_upload)
```

To:
```python
    file_browser_server("grd_file", on_file_selected=_handle_file_upload, accept=[".grd"])
```

**Step 3: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short --ignore=tests/test_playwright_active_project.py --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_interactions.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py`
Expected: All tests PASS (no regressions)

**Step 4: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/components/file_browser.py shyfem-ui/shyfem_ui/pages/grid_prep.py && git commit -m "feat: wire upload validation into file_browser_server

Validates file size against max_upload_size_mb config and extension
against accept list before passing to on_file_selected callback.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Update TODO_NEXT.md and final verification

**Files:**
- Modify: `TODO_NEXT.md` — check off Phase 19 items

**Step 1: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short --ignore=tests/test_playwright_active_project.py --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_interactions.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py`
Expected: All tests PASS including 9 new file_browser tests + 1 new config test

**Step 2: Update TODO_NEXT.md**

Check off items 19.1, 19.2, 19.3. Mark 19.4 as skipped with a note.

**Step 3: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md && git commit -m "docs: mark phase 19 upload validation complete

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
