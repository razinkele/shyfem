"""Tests for IBM page module."""

import inspect

import pytest
from shiny.ui import Tag

from shyfem_ui.pages import ibm

pytest.importorskip("shiny_deckgl")


def test_ibm_ui_renders():
    """ibm_ui() returns a non-None Shiny Tag."""
    tag = ibm.ibm_ui("ibm_test")
    assert tag is not None
    assert isinstance(tag, Tag)


def test_no_demo_constants():
    """_DEMO_PARTICLES and _DEMO_TRACKS must not exist in ibm.py."""
    source = inspect.getsource(ibm)
    assert "_DEMO_PARTICLES" not in source, "Remove _DEMO_PARTICLES from ibm.py"
    assert "_DEMO_TRACKS" not in source, "Remove _DEMO_TRACKS from ibm.py"


def test_no_coming_soon_notification():
    """The demo 'coming soon' notification text must be removed."""
    source = inspect.getsource(ibm)
    assert "full simulation integration coming soon" not in source


def test_ibm_status_not_hardcoded_demo():
    """ibm_status must not contain the hardcoded 'Demo mode' badge text."""
    source = inspect.getsource(ibm)
    assert '"Demo mode"' not in source
    assert "'Demo mode'" not in source


def test_lgr_path_input_present():
    """UI must include a .lgr file path input."""
    source = inspect.getsource(ibm)
    assert '"lgr_path"' in source or "'lgr_path'" in source


def test_load_btn_present():
    """UI must include a load trajectories button."""
    source = inspect.getsource(ibm)
    assert '"load_btn"' in source or "'load_btn'" in source
