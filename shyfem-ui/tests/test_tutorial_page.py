"""Tests for Tutorial page rendering helpers."""

import pytest
from shiny import ui


class TestTutorialRenderHelpers:
    """Test pure rendering functions from tutorial page."""

    def test_render_phase_nav_item_returns_tag(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(
            phase, current_sim="mm_hyd_00", completed=set()
        )
        assert result is not None
        assert isinstance(result, ui.Tag)

    def test_render_phase_nav_item_current_sim_highlighted(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(
            phase, current_sim="mm_hyd_00", completed=set()
        )
        rendered = str(result)
        # The current sim should have an arrow icon
        assert "arrow-right-circle-fill" in rendered

    def test_render_phase_nav_item_pending_icons(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(
            phase, current_sim="mm_hyd_00", completed=set()
        )
        rendered = str(result)
        # Non-current, non-completed sims should have a circle (pending) icon
        assert "bi-circle" in rendered

    def test_render_phase_nav_completed_icons(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        completed = {"mm_hyd_00", "mm_hyd_01", "mm_hyd_02", "mm_hyd_03"}
        result = _render_phase_nav_item(
            phase, current_sim=None, completed=completed
        )
        rendered = str(result)
        assert "check-circle-fill" in rendered

    def test_render_phase_nav_no_current_sim(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(
            phase, current_sim=None, completed=set()
        )
        assert result is not None
        rendered = str(result)
        # All should be pending (circle icon), none should be arrow
        assert "arrow-right-circle-fill" not in rendered

    def test_render_phase_nav_contains_sim_names(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(
            phase, current_sim="mm_hyd_00", completed=set()
        )
        rendered = str(result)
        assert "mm_hyd_00" in rendered
        assert "mm_hyd_01" in rendered
        assert "mm_hyd_02" in rendered
        assert "mm_hyd_03" in rendered

    def test_render_phase_nav_mixed_status(self):
        """Phase with some completed, one current, some pending."""
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        phase = TUTORIAL_CONTENT[0]
        completed = {"mm_hyd_00", "mm_hyd_01"}
        result = _render_phase_nav_item(
            phase, current_sim="mm_hyd_02", completed=completed
        )
        rendered = str(result)
        assert "check-circle-fill" in rendered
        assert "arrow-right-circle-fill" in rendered
        assert "bi-circle" in rendered


class TestRenderStep:
    """Test _render_step function."""

    def test_render_step_basic(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "Test Step", "content": "Do this thing."}
        result = _render_step(step, step_num=1)
        assert result is not None
        assert isinstance(result, ui.Tag)

    def test_render_step_contains_title(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "Wind stress physics", "content": "Some content."}
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Wind stress physics" in rendered

    def test_render_step_contains_step_number(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "Step Title", "content": "Content text."}
        result = _render_step(step, step_num=3)
        rendered = str(result)
        assert "3" in rendered

    def test_render_step_contains_content(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "Title", "content": "Do this specific thing."}
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Do this specific thing." in rendered

    def test_render_step_with_nav_target(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Run it",
            "content": "Click run.",
            "nav_target": "Run",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert result is not None
        assert "Run" in rendered

    def test_render_step_without_nav_target(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "No nav", "content": "Plain step."}
        result = _render_step(step, step_num=1)
        rendered = str(result)
        # Should not contain a "Go to" nav button
        assert "Go to" not in rendered


class TestRenderNewParams:
    """Test _render_new_params function."""

    def test_render_new_params_table(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        params = {
            "iwtype": "Wind type (3 = speed/direction)",
            "dragco": "Wind drag coefficient",
        }
        result = _render_new_params(params)
        assert result is not None
        assert isinstance(result, ui.Tag)

    def test_render_new_params_contains_param_names(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        params = {
            "iwtype": "Wind type (3 = speed/direction)",
            "dragco": "Wind drag coefficient",
        }
        result = _render_new_params(params)
        rendered = str(result)
        assert "iwtype" in rendered
        assert "dragco" in rendered

    def test_render_new_params_contains_descriptions(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        params = {"ireib": "Bottom friction formulation."}
        result = _render_new_params(params)
        rendered = str(result)
        assert "Bottom friction formulation." in rendered

    def test_render_new_params_empty_returns_none(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        result = _render_new_params({})
        assert result is None

    def test_render_new_params_single_param(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        params = {"zconst": "Initial water level offset"}
        result = _render_new_params(params)
        assert result is not None
        rendered = str(result)
        assert "zconst" in rendered

    def test_render_new_params_has_table_structure(self):
        from shyfem_ui.pages.tutorial import _render_new_params

        params = {"param1": "desc1", "param2": "desc2"}
        result = _render_new_params(params)
        rendered = str(result)
        # Should contain table elements
        assert "table" in rendered.lower()


class TestRenderSimHeader:
    """Test _render_sim_header function."""

    def test_render_sim_header_basic(self):
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import get_simulation

        sim = get_simulation("mm_hyd_01")
        result = _render_sim_header(sim)
        assert result is not None
        assert isinstance(result, ui.Tag)

    def test_render_sim_header_contains_title(self):
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import get_simulation

        sim = get_simulation("mm_hyd_01")
        result = _render_sim_header(sim)
        rendered = str(result)
        assert "Adding Output" in rendered

    def test_render_sim_header_contains_summary(self):
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import get_simulation

        sim = get_simulation("mm_hyd_01")
        result = _render_sim_header(sim)
        rendered = str(result)
        assert "monitor nodes" in rendered

    def test_render_sim_header_contains_name(self):
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import get_simulation

        sim = get_simulation("mm_hyd_00")
        result = _render_sim_header(sim)
        rendered = str(result)
        assert "mm_hyd_00" in rendered

    def test_render_sim_header_all_simulations(self):
        """Every simulation in the content should produce a valid header."""
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                result = _render_sim_header(sim)
                assert result is not None, f"Header failed for {sim['name']}"


class TestRenderProgressBar:
    """Test _render_progress_bar function."""

    def test_progress_zero(self):
        from shyfem_ui.pages.tutorial import _render_progress_bar

        result = _render_progress_bar(0, 14)
        assert result is not None
        rendered = str(result)
        assert "0" in rendered

    def test_progress_partial(self):
        from shyfem_ui.pages.tutorial import _render_progress_bar

        result = _render_progress_bar(7, 14)
        assert result is not None
        rendered = str(result)
        assert "7" in rendered
        assert "14" in rendered

    def test_progress_complete(self):
        from shyfem_ui.pages.tutorial import _render_progress_bar

        result = _render_progress_bar(14, 14)
        assert result is not None
        rendered = str(result)
        assert "14" in rendered


class TestTutorialUI:
    """Test that tutorial_ui module function returns valid Tag."""

    def test_tutorial_ui_returns_tag(self):
        from shyfem_ui.pages.tutorial import tutorial_ui

        result = tutorial_ui("test_tutorial")
        assert result is not None

    def test_tutorial_ui_contains_phase_header(self):
        from shyfem_ui.pages.tutorial import tutorial_ui

        result = tutorial_ui("test_tutorial")
        rendered = str(result)
        assert "Tutorial Phases" in rendered

    def test_tutorial_ui_has_two_column_layout(self):
        from shyfem_ui.pages.tutorial import tutorial_ui

        result = tutorial_ui("test_tutorial")
        rendered = str(result)
        # layout_columns with col_widths generates Bootstrap col classes
        assert "col" in rendered.lower()
