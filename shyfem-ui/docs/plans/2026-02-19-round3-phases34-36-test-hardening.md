# Round 3: Test Hardening (Phases 34–36) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ~45 unit tests covering three untested subsystems: STR validation engine, boundary editor pure logic, and CeleryJobQueue.

**Architecture:** Pure TDD — write failing tests first, then extract/expose testable functions where needed (boundary editor closures and `_safe_filename`). No Shiny reactive testing — only pure functions.

**Tech Stack:** pytest, pytest-asyncio, unittest.mock (MagicMock/patch), tmp_path

**Baseline:** 499 tests passing, 0 failed

---

## Task 1: Phase 34 — STR Validation Engine Tests

**Files:**
- Create: `tests/test_str_validation.py`
- Read: `shyfem_ui/components/str_editor.py:471-668` (functions under test)
- Read: `shyfem_ui/services/parser_str.py:315-491` (COMMON_PARAMS)

**Step 1: Write the test file with all ~18 tests**

```python
"""Tests for STR validation engine in str_editor.py."""

import pytest
from pathlib import Path

from shyfem_ui.components.str_editor import (
    validate_str_content,
    _check_range,
    generate_section_template,
    get_parameter_help,
)


# ---------------------------------------------------------------------------
# validate_str_content — structural checks
# ---------------------------------------------------------------------------

class TestValidateStructure:
    def test_parse_error_returns_error(self):
        # Completely invalid content that StrParser can't handle
        # StrParser.parse handles most input gracefully, so test with None-ish edge
        result = validate_str_content("")
        # Empty content should at least warn about missing $para
        assert any("$para" in e for e in result)

    def test_missing_end_reports_unclosed_section(self):
        content = "$para\n    idt = 300\n"
        result = validate_str_content(content)
        assert any("not closed" in e for e in result)

    def test_extra_end_reports_unexpected(self):
        content = "$para\n    idt = 300\n$end\n$end\n"
        result = validate_str_content(content)
        assert any("Unexpected $end" in e for e in result)

    def test_missing_para_section(self):
        content = "$title\n    Test\n$end\n"
        result = validate_str_content(content)
        assert any("Missing required section: $para" in e for e in result)

    def test_missing_title_section_warning(self):
        content = "$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
        result = validate_str_content(content)
        assert any("Missing $title" in w for w in result)

    def test_valid_minimal_str_no_errors(self):
        content = (
            "$title\n    Test\n$end\n"
            "$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
        )
        result = validate_str_content(content)
        # Should have no errors (only possible warnings)
        errors = [r for r in result if not r.startswith("Warning")]
        assert errors == []


# ---------------------------------------------------------------------------
# validate_str_content — timing checks
# ---------------------------------------------------------------------------

class TestValidateTiming:
    def test_missing_itanf(self):
        content = "$title\nT\n$end\n$para\n    itend = 100\n    idt = 10\n$end\n"
        result = validate_str_content(content)
        assert any("itanf" in e and "Missing" in e for e in result)

    def test_missing_itend(self):
        content = "$title\nT\n$end\n$para\n    itanf = 0\n    idt = 10\n$end\n"
        result = validate_str_content(content)
        assert any("itend" in e and "Missing" in e for e in result)

    def test_missing_idt(self):
        content = "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n$end\n"
        result = validate_str_content(content)
        assert any("idt" in e and "Missing" in e for e in result)

    def test_itanf_ge_itend_error(self):
        content = "$title\nT\n$end\n$para\n    itanf = 200\n    itend = 100\n    idt = 10\n$end\n"
        result = validate_str_content(content)
        assert any("itanf" in e and "less than" in e for e in result)

    def test_idt_zero_error(self):
        content = "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 0\n$end\n"
        result = validate_str_content(content)
        assert any("idt" in e and "positive" in e for e in result)

    def test_idt_negative_error(self):
        content = "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = -5\n$end\n"
        result = validate_str_content(content)
        assert any("idt" in e and "positive" in e for e in result)


# ---------------------------------------------------------------------------
# validate_str_content — depth / range / unknown param
# ---------------------------------------------------------------------------

class TestValidateDepthAndRange:
    def test_hzmin_ge_hzoff_warning(self):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    hzmin = 0.1\n    hzoff = 0.05\n$end\n"
        )
        result = validate_str_content(content)
        assert any("hzmin" in w and "hzoff" in w for w in result)

    def test_unknown_param_warning(self):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    zzzfoo = 42\n$end\n"
        )
        result = validate_str_content(content)
        assert any("unknown" in w.lower() and "zzzfoo" in w for w in result)

    def test_idt_prefix_not_flagged_as_unknown(self):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    idtxyz = 3600\n$end\n"
        )
        result = validate_str_content(content)
        assert not any("idtxyz" in w for w in result)

    def test_itm_prefix_not_flagged_as_unknown(self):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    itmcon = 0\n$end\n"
        )
        result = validate_str_content(content)
        assert not any("itmcon" in w for w in result)


# ---------------------------------------------------------------------------
# validate_str_content — file existence checks
# ---------------------------------------------------------------------------

class TestValidateFiles:
    def test_missing_file_warning(self, tmp_path):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
            "$name\n    wind = 'missing.txt'\n$end\n"
        )
        result = validate_str_content(content, check_files=True, working_dir=tmp_path)
        assert any("not found" in w and "wind" in w for w in result)

    def test_existing_file_no_warning(self, tmp_path):
        (tmp_path / "wind.txt").write_text("data")
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
            "$name\n    wind = 'wind.txt'\n$end\n"
        )
        result = validate_str_content(content, check_files=True, working_dir=tmp_path)
        assert not any("not found" in w and "wind" in w for w in result)

    def test_check_files_false_skips(self, tmp_path):
        content = (
            "$title\nT\n$end\n$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
            "$name\n    wind = 'missing.txt'\n$end\n"
        )
        result = validate_str_content(content, check_files=False)
        assert not any("not found" in w for w in result)


# ---------------------------------------------------------------------------
# _check_range
# ---------------------------------------------------------------------------

class TestCheckRange:
    def _run(self, value, options_str):
        warnings = []
        _check_range(warnings, "para", "test_param", value, options_str)
        return warnings

    def test_bracket_range_in_range(self):
        assert self._run(0.5, "[0,1]") == []

    def test_bracket_range_at_boundary(self):
        assert self._run(0.0, "[0,1]") == []
        assert self._run(1.0, "[0,1]") == []

    def test_bracket_range_below(self):
        result = self._run(-0.1, "[0,1]")
        assert len(result) == 1
        assert "outside range" in result[0]

    def test_bracket_range_above(self):
        result = self._run(1.5, "[0,1]")
        assert len(result) == 1
        assert "outside range" in result[0]

    def test_gt_zero_positive(self):
        assert self._run(5.0, ">0") == []

    def test_gt_zero_zero(self):
        result = self._run(0.0, ">0")
        assert len(result) == 1
        assert ">0" in result[0]

    def test_gt_zero_negative(self):
        result = self._run(-1.0, ">0")
        assert len(result) == 1

    def test_gte_zero_positive(self):
        assert self._run(5.0, ">=0") == []

    def test_gte_zero_zero(self):
        assert self._run(0.0, ">=0") == []

    def test_gte_zero_negative(self):
        result = self._run(-1.0, ">=0")
        assert len(result) == 1
        assert ">=0" in result[0]

    def test_non_matching_options_ignored(self):
        assert self._run(42, "0=off, 1=on") == []


# ---------------------------------------------------------------------------
# generate_section_template
# ---------------------------------------------------------------------------

class TestGenerateSectionTemplate:
    @pytest.mark.parametrize("section", ["para", "title", "extra", "name", "bound"])
    def test_known_section_has_content(self, section):
        result = generate_section_template(section)
        assert result.startswith(f"${section}")
        assert "$end" in result

    def test_unknown_section_uses_generic(self):
        result = generate_section_template("waves")
        assert "$waves" in result
        assert "Add parameters here" in result
        assert "$end" in result

    def test_para_template_has_timing(self):
        result = generate_section_template("para")
        assert "itanf" in result
        assert "itend" in result
        assert "idt" in result


# ---------------------------------------------------------------------------
# get_parameter_help
# ---------------------------------------------------------------------------

class TestGetParameterHelp:
    def test_known_param_returns_help(self):
        result = get_parameter_help("para", "idt")
        assert result is not None
        assert "Time step" in result
        assert "Type:" in result

    def test_known_param_with_units(self):
        result = get_parameter_help("para", "hzmin")
        assert "Units: m" in result

    def test_known_param_with_default(self):
        result = get_parameter_help("para", "azpar")
        assert "Default: 0.5" in result

    def test_known_param_with_options(self):
        result = get_parameter_help("para", "azpar")
        assert "[0,1]" in result

    def test_unknown_param_returns_none(self):
        assert get_parameter_help("para", "nonexistent_xyz") is None

    def test_unknown_section_returns_none(self):
        assert get_parameter_help("nosuch", "idt") is None

    def test_name_section_param(self):
        result = get_parameter_help("name", "wind")
        assert result is not None
        assert "Wind" in result or "wind" in result.lower()
```

**Step 2: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_validation.py -v`
Expected: All ~40 tests PASS (these are testing existing code, not new code)

**Step 3: Commit**

```bash
git add tests/test_str_validation.py
git commit -m "test: add STR validation engine tests (Phase 34)

Cover validate_str_content(), _check_range(), generate_section_template(),
and get_parameter_help() with ~40 tests for structural checks, timing,
depth sanity, range validation, file existence, and help text."
```

---

## Task 2: Phase 35 — Extract `_safe_filename` and `generate_bound_text`

The boundary editor's text generation and CSV parsing are Shiny reactive closures —
not directly importable. We need to extract the pure logic into testable functions.
Similarly, `_safe_filename` is a closure inside `home_server()`.

**Files:**
- Modify: `shyfem_ui/pages/home.py:699-700` (move `_safe_filename` to module level)
- Modify: `shyfem_ui/components/boundary_editor.py` (extract `generate_bound_text()` and `parse_boundary_csv()`)

### Step 1: Extract `_safe_filename` to module level in home.py

Move from line 699 (inside `home_server()`) to module level (above `home_server`).
The closure inside `home_server` calls `_safe_filename(project_name)` — since it doesn't
capture any reactive state, it can be a plain module-level function.

In `shyfem_ui/pages/home.py`, move the function definition before `home_server()` (around line 60-ish, after imports). Keep the call site unchanged.

```python
def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
```

Delete the original at line 699. The existing call at line 740 works unchanged.

### Step 2: Extract pure functions from boundary_editor.py

Add two module-level functions at the bottom of `boundary_editor.py` (before the server function, or after imports):

```python
def generate_bound_text(boundaries: list[dict]) -> str:
    """Generate $bound section text from boundary definitions.

    Args:
        boundaries: List of dicts with keys: label, nodes, ibtyp, boundn, zfact, intpol

    Returns:
        Multi-line string with $bound sections
    """
    if not boundaries:
        return "! No boundaries defined"

    lines = []
    for b in boundaries:
        section_name = b["label"]
        lines.append(f"${section_name}")
        if b.get("nodes"):
            lines.append(f"        kbound = {b['nodes']}")
        lines.append(f"        ibtyp = {b['ibtyp']}")
        if b.get("boundn"):
            lines.append(f"        boundn = '{b['boundn']}'")
        if b.get("zfact", 1.0) != 1.0:
            lines.append(f"        zfact = {b['zfact']}")
        if b.get("intpol", 1) != 1:
            lines.append(f"        intpol = {b['intpol']}")
        lines.append("$end")
        lines.append("")

    return "\n".join(lines)


def parse_boundary_csv(csv_text: str, start_id: int = 1) -> list[dict]:
    """Parse CSV text into boundary definitions.

    CSV format: nodes,ibtyp[,boundn][,zfact][,intpol]
    Lines starting with # are comments. Blank lines are skipped.
    Minimum 2 columns required (nodes + ibtyp).

    Args:
        csv_text: Raw CSV text
        start_id: Starting boundary ID

    Returns:
        List of boundary dicts with keys: id, label, nodes, ibtyp, boundn, zfact, intpol
    """
    imported = []
    bid = start_id
    for line in csv_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        entry = {
            "id": bid,
            "label": f"bound{bid}",
            "nodes": parts[0],
            "ibtyp": int(parts[1]) if len(parts) > 1 else 1,
            "boundn": parts[2] if len(parts) > 2 else "",
            "zfact": float(parts[3]) if len(parts) > 3 else 1.0,
            "intpol": int(parts[4]) if len(parts) > 4 else 1,
        }
        imported.append(entry)
        bid += 1

    return imported
```

Then update `_generate_bound` (line ~207) to call:
```python
text = generate_bound_text(updated)
```

And update `_import_csv` (line ~155) to call:
```python
imported = parse_boundary_csv(csv_text, _next_id.get())
```

### Step 3: Run the app to verify no regressions

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: 499 passed

### Step 4: Commit extractions

```bash
git add shyfem_ui/pages/home.py shyfem_ui/components/boundary_editor.py
git commit -m "refactor: extract pure functions for testability (Phase 35 prep)

Move _safe_filename to module level in home.py.
Extract generate_bound_text() and parse_boundary_csv() from
boundary_editor.py reactive closures."
```

---

## Task 3: Phase 35 — Boundary Editor & Home Helper Tests

**Files:**
- Create: `tests/test_boundary_editor.py`
- Create: `tests/test_safe_filename.py`

### Step 1: Write boundary editor tests

```python
"""Tests for boundary editor pure functions."""

import pytest
from shyfem_ui.components.boundary_editor import generate_bound_text, parse_boundary_csv


def _bound(label="bound1", nodes="1 2 3", ibtyp=1, boundn="", zfact=1.0, intpol=1, bid=1):
    return {"id": bid, "label": label, "nodes": nodes, "ibtyp": ibtyp,
            "boundn": boundn, "zfact": zfact, "intpol": intpol}


# ---------------------------------------------------------------------------
# generate_bound_text
# ---------------------------------------------------------------------------

class TestGenerateBoundText:
    def test_empty_returns_comment(self):
        assert "No boundaries" in generate_bound_text([])

    def test_single_boundary_basic(self):
        result = generate_bound_text([_bound()])
        assert "$bound1" in result
        assert "kbound = 1 2 3" in result
        assert "ibtyp = 1" in result
        assert "$end" in result

    def test_boundn_included_when_set(self):
        result = generate_bound_text([_bound(boundn="tide.txt")])
        assert "boundn = 'tide.txt'" in result

    def test_boundn_omitted_when_empty(self):
        result = generate_bound_text([_bound(boundn="")])
        assert "boundn" not in result

    def test_zfact_included_when_not_default(self):
        result = generate_bound_text([_bound(zfact=2.5)])
        assert "zfact = 2.5" in result

    def test_zfact_omitted_when_default(self):
        result = generate_bound_text([_bound(zfact=1.0)])
        assert "zfact" not in result

    def test_intpol_included_when_not_default(self):
        result = generate_bound_text([_bound(intpol=2)])
        assert "intpol = 2" in result

    def test_intpol_omitted_when_default(self):
        result = generate_bound_text([_bound(intpol=1)])
        assert "intpol" not in result

    def test_multiple_boundaries(self):
        bounds = [_bound(label="bound1", bid=1), _bound(label="bound2", bid=2)]
        result = generate_bound_text(bounds)
        assert result.count("$end") == 2
        assert "$bound1" in result
        assert "$bound2" in result

    def test_nodes_empty_omits_kbound(self):
        result = generate_bound_text([_bound(nodes="")])
        assert "kbound" not in result


# ---------------------------------------------------------------------------
# parse_boundary_csv
# ---------------------------------------------------------------------------

class TestParseBoundaryCSV:
    def test_valid_two_columns(self):
        result = parse_boundary_csv("1 2 3, 1")
        assert len(result) == 1
        assert result[0]["nodes"] == "1 2 3"
        assert result[0]["ibtyp"] == 1

    def test_all_five_columns(self):
        result = parse_boundary_csv("1 2, 2, tide.txt, 0.5, 2")
        assert result[0]["boundn"] == "tide.txt"
        assert result[0]["zfact"] == pytest.approx(0.5)
        assert result[0]["intpol"] == 2

    def test_comment_lines_skipped(self):
        result = parse_boundary_csv("# header\n1 2, 1\n# another\n3 4, 2")
        assert len(result) == 2

    def test_blank_lines_skipped(self):
        result = parse_boundary_csv("\n\n1 2, 1\n\n")
        assert len(result) == 1

    def test_single_column_skipped(self):
        result = parse_boundary_csv("only_nodes")
        assert len(result) == 0

    def test_multiple_lines(self):
        csv = "1 2, 1, tide1.txt\n3 4, 2, tide2.txt"
        result = parse_boundary_csv(csv)
        assert len(result) == 2
        assert result[0]["label"] == "bound1"
        assert result[1]["label"] == "bound2"

    def test_start_id(self):
        result = parse_boundary_csv("1 2, 1", start_id=5)
        assert result[0]["id"] == 5
        assert result[0]["label"] == "bound5"

    def test_defaults_for_optional_columns(self):
        result = parse_boundary_csv("1 2, 1")
        assert result[0]["boundn"] == ""
        assert result[0]["zfact"] == pytest.approx(1.0)
        assert result[0]["intpol"] == 1

    def test_invalid_ibtyp_raises(self):
        with pytest.raises(ValueError):
            parse_boundary_csv("1 2, not_a_number")
```

### Step 2: Write _safe_filename tests

```python
"""Tests for _safe_filename in home.py."""

from shyfem_ui.pages.home import _safe_filename


class TestSafeFilename:
    def test_normal_name(self):
        assert _safe_filename("my_project") == "my_project"

    def test_special_chars_replaced(self):
        result = _safe_filename("project@v1.0!")
        assert "@" not in result
        assert "!" not in result
        assert "_" in result

    def test_unicode_replaced(self):
        result = _safe_filename("café_résumé")
        # Non-ASCII letters replaced with _
        assert "é" not in result

    def test_hyphens_preserved(self):
        assert _safe_filename("my-project") == "my-project"

    def test_spaces_preserved_internally(self):
        assert _safe_filename("my project") == "my project"

    def test_leading_trailing_spaces_stripped(self):
        assert _safe_filename("  hello  ") == "hello"

    def test_empty_string(self):
        assert _safe_filename("") == ""

    def test_all_special_chars(self):
        result = _safe_filename("@#$%^&*()")
        assert result == "__________"

    def test_long_name_not_truncated(self):
        # Current implementation does NOT truncate — just documents behavior
        long_name = "a" * 200
        assert len(_safe_filename(long_name)) == 200
```

### Step 3: Run tests

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boundary_editor.py tests/test_safe_filename.py -v`
Expected: All ~22 tests PASS

### Step 4: Commit

```bash
git add tests/test_boundary_editor.py tests/test_safe_filename.py
git commit -m "test: add boundary editor and _safe_filename tests (Phase 35)

Cover generate_bound_text(), parse_boundary_csv(), and _safe_filename()
with ~22 tests for text generation, CSV parsing, and filename sanitization."
```

---

## Task 4: Phase 36 — CeleryJobQueue Mock Tests

**Files:**
- Create: `tests/test_job_celery.py`
- Read: `shyfem_ui/services/job_celery.py` (class under test)
- Read: `shyfem_ui/services/job_queue.py` (JobInfo, JobSpec, JobStatus)

### Step 1: Write the test file

```python
"""Tests for CeleryJobQueue with mocked Redis and Celery."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus
from shyfem_ui.services.job_celery import (
    CeleryJobQueue,
    _store_job_info,
    _load_job_info,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job_info(job_id="job-1", status=JobStatus.PENDING, **kwargs):
    defaults = dict(
        id=job_id, name="test_job", tool_name="shyfem", args=["input.str"],
        working_dir="/tmp/work", status=status, created_at=datetime(2026, 2, 19, 12, 0, 0),
        metadata={},
    )
    defaults.update(kwargs)
    return JobInfo(**defaults)


def _job_info_to_json(job_info: JobInfo) -> str:
    return json.dumps({
        "id": job_info.id, "name": job_info.name, "tool_name": job_info.tool_name,
        "args": job_info.args, "working_dir": job_info.working_dir,
        "status": job_info.status.value, "progress": job_info.progress,
        "progress_message": job_info.progress_message,
        "created_at": job_info.created_at.isoformat() if job_info.created_at else None,
        "queued_at": job_info.queued_at.isoformat() if job_info.queued_at else None,
        "started_at": job_info.started_at.isoformat() if job_info.started_at else None,
        "completed_at": job_info.completed_at.isoformat() if job_info.completed_at else None,
        "return_code": job_info.return_code, "error_message": job_info.error_message,
        "stdout_file": job_info.stdout_file, "stderr_file": job_info.stderr_file,
        "output_files": job_info.output_files, "simulation_id": job_info.simulation_id,
        "metadata": job_info.metadata,
    })


@pytest.fixture
def mock_redis():
    rc = MagicMock()
    rc.ping.return_value = True
    return rc


@pytest.fixture
def mock_task():
    task = MagicMock()
    task.apply_async.return_value = MagicMock(id="celery-task-1")
    return task


@pytest.fixture
def mock_celery_app(mock_task):
    app = MagicMock()
    app.control.revoke = MagicMock()
    return app


@pytest.fixture
def queue(tmp_path, mock_redis, mock_celery_app, mock_task):
    q = CeleryJobQueue(shyfem_dir=tmp_path, redis_url="redis://fake:6379/0")
    q._redis_client = mock_redis
    q._celery_app = mock_celery_app
    q._task = mock_task
    return q


@pytest.fixture
def job_spec(tmp_path):
    return JobSpec(
        name="test_job", tool_name="shyfem", args=["input.str"],
        working_dir=tmp_path / "work",
    )


# ---------------------------------------------------------------------------
# _store_job_info / _load_job_info helpers
# ---------------------------------------------------------------------------

class TestRedisHelpers:
    def test_store_calls_hset_and_zadd(self, mock_redis):
        job = _make_job_info()
        _store_job_info(mock_redis, job)
        mock_redis.hset.assert_called_once()
        mock_redis.zadd.assert_called_once()

    def test_load_returns_job_info(self, mock_redis):
        job = _make_job_info(status=JobStatus.RUNNING)
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = _load_job_info(mock_redis, "job-1")
        assert result is not None
        assert result.id == "job-1"
        assert result.status == JobStatus.RUNNING

    def test_load_returns_none_when_missing(self, mock_redis):
        mock_redis.hget.return_value = None
        assert _load_job_info(mock_redis, "nonexistent") is None


# ---------------------------------------------------------------------------
# CeleryJobQueue.submit
# ---------------------------------------------------------------------------

class TestCelerySubmit:
    @pytest.mark.asyncio
    async def test_submit_returns_job_id(self, queue, job_spec):
        job_id = await queue.submit(job_spec)
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_submit_dispatches_celery_task(self, queue, job_spec, mock_task):
        await queue.submit(job_spec)
        mock_task.apply_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_stores_in_redis(self, queue, job_spec, mock_redis):
        await queue.submit(job_spec)
        # hset called twice: once for PENDING, once for QUEUED
        assert mock_redis.hset.call_count == 2

    @pytest.mark.asyncio
    async def test_submit_mpi_metadata(self, queue, tmp_path, mock_redis):
        spec = JobSpec(
            name="mpi_job", tool_name="shyfem", args=["input.str"],
            working_dir=tmp_path / "work", mpi_enabled=True, mpi_np=4,
        )
        await queue.submit(spec)
        # Check last hset call contains mpi metadata
        call_args = mock_redis.hset.call_args_list[-1]
        stored = json.loads(call_args[0][2])
        assert stored["metadata"]["mpi_enabled"] is True
        assert stored["metadata"]["mpi_np"] == 4


# ---------------------------------------------------------------------------
# CeleryJobQueue.cancel
# ---------------------------------------------------------------------------

class TestCeleryCancel:
    @pytest.mark.asyncio
    async def test_cancel_active_job(self, queue, mock_redis, mock_celery_app):
        job = _make_job_info(status=JobStatus.RUNNING)
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = await queue.cancel("job-1")
        assert result is True
        mock_celery_app.control.revoke.assert_called_once_with("job-1", terminate=True)

    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_false(self, queue, mock_redis):
        job = _make_job_info(status=JobStatus.COMPLETED)
        mock_redis.hget.return_value = _job_info_to_json(job)
        assert await queue.cancel("job-1") is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, queue, mock_redis):
        mock_redis.hget.return_value = None
        assert await queue.cancel("nonexistent") is False


# ---------------------------------------------------------------------------
# CeleryJobQueue.get_status
# ---------------------------------------------------------------------------

class TestCeleryGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_returns_job(self, queue, mock_redis):
        job = _make_job_info(status=JobStatus.QUEUED)
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = await queue.get_status("job-1")
        assert result is not None
        assert result.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, queue, mock_redis):
        mock_redis.hget.return_value = None
        assert await queue.get_status("nonexistent") is None


# ---------------------------------------------------------------------------
# CeleryJobQueue.list_jobs
# ---------------------------------------------------------------------------

class TestCeleryListJobs:
    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, queue, mock_redis):
        mock_redis.zrevrange.return_value = []
        result = await queue.list_jobs()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_jobs_returns_all(self, queue, mock_redis):
        job1 = _make_job_info("job-1", JobStatus.COMPLETED)
        job2 = _make_job_info("job-2", JobStatus.RUNNING)
        mock_redis.zrevrange.return_value = [b"job-1", b"job-2"]
        mock_redis.hget.side_effect = lambda _k, jid: _job_info_to_json(
            job1 if jid == "job-1" else job2
        )
        result = await queue.list_jobs()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_filter_status(self, queue, mock_redis):
        job1 = _make_job_info("job-1", JobStatus.COMPLETED)
        job2 = _make_job_info("job-2", JobStatus.RUNNING)
        mock_redis.zrevrange.return_value = [b"job-1", b"job-2"]
        mock_redis.hget.side_effect = lambda _k, jid: _job_info_to_json(
            job1 if jid == "job-1" else job2
        )
        result = await queue.list_jobs(status=JobStatus.RUNNING)
        assert len(result) == 1
        assert result[0].id == "job-2"

    @pytest.mark.asyncio
    async def test_list_jobs_filter_session_id(self, queue, mock_redis):
        job = _make_job_info("job-1", metadata={"session_id": "sess-abc"})
        mock_redis.zrevrange.return_value = [b"job-1"]
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = await queue.list_jobs(session_id="sess-abc")
        assert len(result) == 1
        result2 = await queue.list_jobs(session_id="sess-other")
        assert len(result2) == 0

    @pytest.mark.asyncio
    async def test_list_jobs_limit(self, queue, mock_redis):
        jobs = {f"job-{i}": _make_job_info(f"job-{i}") for i in range(5)}
        mock_redis.zrevrange.return_value = [f"job-{i}".encode() for i in range(5)]
        mock_redis.hget.side_effect = lambda _k, jid: _job_info_to_json(jobs[jid])
        result = await queue.list_jobs(limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# CeleryJobQueue.get_output
# ---------------------------------------------------------------------------

class TestCeleryGetOutput:
    @pytest.mark.asyncio
    async def test_get_output_nonexistent_job(self, queue, mock_redis):
        mock_redis.hget.return_value = None
        result = await queue.get_output("nonexistent")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_output_no_file(self, queue, mock_redis):
        job = _make_job_info(stdout_file=None)
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = await queue.get_output("job-1")
        assert result == ""

    @pytest.mark.asyncio
    @patch("shyfem_ui.services.job_celery.tail_file", return_value="line1\nline2")
    async def test_get_output_reads_file(self, mock_tail, queue, mock_redis):
        job = _make_job_info(stdout_file="/tmp/job-1.stdout")
        mock_redis.hget.return_value = _job_info_to_json(job)
        result = await queue.get_output("job-1")
        assert result == "line1\nline2"
        mock_tail.assert_called_once_with("/tmp/job-1.stdout", tail=100)


# ---------------------------------------------------------------------------
# CeleryJobQueue.health_check
# ---------------------------------------------------------------------------

class TestCeleryHealthCheck:
    @pytest.mark.asyncio
    async def test_health_redis_ok(self, queue, mock_redis, mock_celery_app):
        inspect = MagicMock()
        inspect.ping.return_value = {"worker1": {"ok": "pong"}}
        inspect.active.return_value = {"worker1": []}
        inspect.scheduled.return_value = {"worker1": []}
        inspect.reserved.return_value = {"worker1": []}
        mock_celery_app.control.inspect.return_value = inspect

        result = await queue.health_check()
        assert result["redis_connected"] is True
        assert "worker1" in result["workers"]

    @pytest.mark.asyncio
    async def test_health_redis_down(self, queue, mock_redis, mock_celery_app):
        mock_redis.ping.side_effect = ConnectionError("refused")
        result = await queue.health_check()
        assert result["redis_connected"] is False
        assert result["workers"] == []

    @pytest.mark.asyncio
    async def test_health_active_task_count(self, queue, mock_redis, mock_celery_app):
        inspect = MagicMock()
        inspect.ping.return_value = {"w1": {"ok": "pong"}}
        inspect.active.return_value = {"w1": ["task1", "task2"]}
        inspect.scheduled.return_value = None
        inspect.reserved.return_value = None
        mock_celery_app.control.inspect.return_value = inspect

        result = await queue.health_check()
        assert result["active_tasks"] == 2


# ---------------------------------------------------------------------------
# CeleryJobQueue.cleanup_old_jobs
# ---------------------------------------------------------------------------

class TestCeleryCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_removes_old_inactive(self, queue, mock_redis):
        old_job = _make_job_info(status=JobStatus.COMPLETED)
        mock_redis.zrangebyscore.return_value = [b"job-1"]
        mock_redis.hget.return_value = _job_info_to_json(old_job)
        removed = await queue.cleanup_old_jobs(days=7)
        assert removed == 1
        mock_redis.hdel.assert_called_once()
        mock_redis.zrem.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_skips_active(self, queue, mock_redis):
        active_job = _make_job_info(status=JobStatus.RUNNING)
        mock_redis.zrangebyscore.return_value = [b"job-1"]
        mock_redis.hget.return_value = _job_info_to_json(active_job)
        removed = await queue.cleanup_old_jobs(days=7)
        assert removed == 0
        mock_redis.hdel.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_empty(self, queue, mock_redis):
        mock_redis.zrangebyscore.return_value = []
        removed = await queue.cleanup_old_jobs(days=7)
        assert removed == 0
```

### Step 2: Run tests

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_celery.py -v`
Expected: All ~25 tests PASS

### Step 3: Commit

```bash
git add tests/test_job_celery.py
git commit -m "test: add CeleryJobQueue mock tests (Phase 36)

Cover submit, cancel, get_status, list_jobs, get_output, health_check,
and cleanup_old_jobs with ~25 tests using mocked Redis and Celery."
```

---

## Task 5: Final Verification & TODO_NEXT Update

### Step 1: Run full test suite

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q`
Expected: ~585+ passed, 0 failed

### Step 2: Update TODO_NEXT.md with Phase 34-36 completion

Add the three phases as complete with checkbox items matching the design doc.

### Step 3: Commit

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phases 34-36 complete in TODO_NEXT.md"
```

---

## Summary

| Task | Phase | Tests | Key Decisions |
|------|-------|-------|---------------|
| 1 | 34: STR Validation | ~40 | Test existing pure functions directly |
| 2 | 35: Extract functions | 0 | Refactor closures → module-level for testability |
| 3 | 35: Boundary + Filename | ~22 | Test extracted pure functions |
| 4 | 36: CeleryJobQueue | ~25 | Mock Redis + Celery, mirror LocalJobQueue patterns |
| 5 | Final | 0 | Full suite run + docs update |

**Total new tests: ~87**
**Expected final count: ~585+**
