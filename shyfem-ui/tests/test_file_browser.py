"""Tests for file browser upload validation."""

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
