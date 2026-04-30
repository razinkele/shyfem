"""Smoke test: each silent-page module has a properly-named logger.

This guards against accidental removal of the module-level logger by a future
refactor. It does NOT verify specific log calls — those can be hand-tested.
"""
import importlib

import pytest


@pytest.mark.parametrize(
    "page", ["home", "simulation", "grid_prep", "partitioning"]
)
def test_page_has_module_logger(page):
    mod = importlib.import_module(f"shyfem_ui.pages.{page}")
    assert hasattr(mod, "logger"), (
        f"{page}.py must define a module-level logger; was previously silent"
    )
    assert mod.logger.name == f"shyfem_ui.pages.{page}", (
        f"logger name should be {f'shyfem_ui.pages.{page}'!r}, got {mod.logger.name!r}"
    )
