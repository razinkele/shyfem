"""Tests for log_viewer format_log_line function."""

import pytest

from shyfem_ui.components.log_viewer import LINE_TRUNCATE_LEN, format_log_line


# ── Plain text ───────────────────────────────────────────────────


def test_plain_text_passthrough():
    result = format_log_line("hello world")
    assert result == "hello world"


def test_empty_string():
    result = format_log_line("")
    assert result == ""


# ── HTML escaping / XSS ─────────────────────────────────────────


def test_xss_script_escaped():
    result = format_log_line("<script>alert('xss')</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_html_entities_escaped():
    result = format_log_line('a < b && c > "d"')
    assert "&lt;" in result
    assert "&amp;" in result
    assert "&gt;" in result
    assert "&quot;" in result


# ── Color highlighting ───────────────────────────────────────────


def test_error_line_red():
    result = format_log_line("ERROR: something failed")
    assert 'color: #f44747' in result
    assert "ERROR: something failed" in result


def test_warning_line_yellow():
    result = format_log_line("WARNING: low memory")
    assert 'color: #cca700' in result


def test_success_line_green():
    result = format_log_line("Task completed successfully")
    assert 'color: #4ec9b0' in result


def test_header_line_blue():
    result = format_log_line(">>> Starting phase 1")
    # ">>>" becomes "&gt;&gt;&gt;" after escaping, which triggers blue
    assert 'color: #569cd6' in result


def test_time_line_highlighted():
    result = format_log_line("time = 3600.0")
    assert 'color: #9cdcfe' in result


# ── Truncation ───────────────────────────────────────────────────


def test_short_line_not_truncated():
    line = "x" * 100
    result = format_log_line(line)
    assert "[truncated]" not in result


def test_long_line_truncated():
    line = "x" * (LINE_TRUNCATE_LEN + 100)
    result = format_log_line(line)
    assert "[truncated]" in result
    # Truncated output should not exceed original limit + marker length
    assert len(result) < LINE_TRUNCATE_LEN + 100


# ── Non-string input ────────────────────────────────────────────


def test_non_string_coerced():
    result = format_log_line(42)
    assert "42" in result


def test_none_coerced():
    result = format_log_line(None)
    assert "None" in result
