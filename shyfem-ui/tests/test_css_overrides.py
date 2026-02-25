"""Verify shyfem.css overrides all Bootstrap utility classes used by pages."""

from pathlib import Path

CSS_PATH = Path(__file__).resolve().parent.parent / "shyfem_ui" / "www" / "css" / "shyfem.css"

REQUIRED_SELECTORS = [
    ".bg-light",
    ".bg-dark",
    ".text-primary",
    ".text-success",
    ".text-danger",
    ".text-warning",
    ".text-info",
    ".text-muted",
    ".border-primary",
]


def test_ocean_overrides_present():
    css = CSS_PATH.read_text()
    missing = [sel for sel in REQUIRED_SELECTORS if sel not in css]
    assert not missing, f"Missing ocean overrides for: {missing}"


def test_dark_mode_text_overrides():
    css = CSS_PATH.read_text()
    for sel in [".text-primary", ".text-success", ".text-danger", ".text-warning", ".text-info"]:
        assert f'[data-bs-theme="dark"] {sel}' in css, f"Missing dark-mode override for {sel}"
