"""Unit tests for _safe_filename() from shyfem_ui.pages.home."""

from shyfem_ui.pages.home import _safe_filename


class TestSafeFilename:
    """Tests for the _safe_filename() sanitizer."""

    def test_normal_name_unchanged(self):
        """Alphanumeric-only names pass through unchanged."""
        assert _safe_filename("my_project") == "my_project"

    def test_special_chars_replaced(self):
        """Special characters like @ and ! are replaced with underscores."""
        assert _safe_filename("test@project!") == "test_project_"

    def test_unicode_alphanumeric_preserved(self):
        """Unicode alphanumeric chars are preserved (Python isalnum is unicode-aware)."""
        assert _safe_filename("projet_été") == "projet_été"

    def test_hyphens_preserved(self):
        """Hyphens are kept as-is."""
        assert _safe_filename("my-project") == "my-project"

    def test_spaces_preserved_internally(self):
        """Internal spaces are preserved."""
        assert _safe_filename("my project") == "my project"

    def test_leading_trailing_spaces_stripped(self):
        """Leading and trailing spaces are stripped."""
        assert _safe_filename("  my_project  ") == "my_project"

    def test_empty_string(self):
        """Empty input returns empty string."""
        assert _safe_filename("") == ""

    def test_all_special_chars(self):
        """String of all special characters becomes all underscores."""
        assert _safe_filename("@#$%") == "____"

    def test_long_name_not_truncated(self):
        """Long names are not truncated (current behavior)."""
        long_name = "a" * 300
        assert _safe_filename(long_name) == long_name
