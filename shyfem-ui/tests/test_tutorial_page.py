"""Tests for Tutorial page rendering helpers."""

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


class TestMdToHtml:
    """Test the _md_to_html helper function."""

    def test_bold_conversion(self):
        from shyfem_ui.pages.tutorial import _md_to_html
        assert _md_to_html("Click **Submit**") == "Click <strong>Submit</strong>"

    def test_code_conversion(self):
        from shyfem_ui.pages.tutorial import _md_to_html
        assert _md_to_html("Set `ilin = 0`") == "Set <code>ilin = 0</code>"

    def test_mixed_bold_and_code(self):
        from shyfem_ui.pages.tutorial import _md_to_html
        result = _md_to_html("Click **Load** and select `mm_hyd_00.str`.")
        assert "<strong>Load</strong>" in result
        assert "<code>mm_hyd_00.str</code>" in result

    def test_no_markdown(self):
        from shyfem_ui.pages.tutorial import _md_to_html
        text = "Plain text with no formatting."
        assert _md_to_html(text) == text

    def test_multiple_bold(self):
        from shyfem_ui.pages.tutorial import _md_to_html
        result = _md_to_html("**A** then **B**")
        assert result == "<strong>A</strong> then <strong>B</strong>"


class TestRenderStep:
    """Test _render_step function."""

    def test_render_step_basic(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Test Step",
            "content": "Do this thing.",
            "actions": ["Click **Submit**."],
            "expected": "Job completes.",
        }
        result = _render_step(step, step_num=1)
        assert result is not None
        assert isinstance(result, ui.Tag)

    def test_render_step_contains_title(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Wind stress physics",
            "content": "Some content.",
            "actions": ["Do something."],
            "expected": "Result.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Wind stress physics" in rendered

    def test_render_step_contains_step_number(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Step Title",
            "content": "Content text.",
            "actions": ["Action."],
            "expected": "Result.",
        }
        result = _render_step(step, step_num=3)
        rendered = str(result)
        assert "3" in rendered

    def test_render_step_contains_content(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Title",
            "content": "Do this specific thing.",
            "actions": ["Action."],
            "expected": "Result.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Do this specific thing." in rendered

    def test_render_step_with_nav_target(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Run it",
            "content": "Click run.",
            "actions": ["Click **Run**."],
            "expected": "Job starts.",
            "nav_target": "Run",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert result is not None
        assert "Run" in rendered

    def test_render_step_without_nav_target(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "No nav",
            "content": "Plain step.",
            "actions": ["Action."],
            "expected": "Result.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        # Should not contain a "Go to" nav button
        assert "Go to" not in rendered

    def test_render_step_with_actions_list(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Configure",
            "content": "Educational content.",
            "actions": [
                "Navigate to the **Simulation** tab.",
                "Click **Load** and select `mm_hyd_00.str`.",
                "Verify `ilin = 1`.",
            ],
            "expected": "Parameters visible.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        # Actions card should be present
        assert "Actions" in rendered
        assert "bi-list-check" in rendered
        # Markdown should be converted to HTML
        assert "<strong>Simulation</strong>" in rendered
        assert "<strong>Load</strong>" in rendered
        assert "<code>mm_hyd_00.str</code>" in rendered
        # Ordered list
        assert "<ol>" in rendered

    def test_render_step_with_expected_result(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Verify Output",
            "content": "Check results.",
            "actions": ["Do a thing."],
            "expected": "Statistics tab shows ~1,300 nodes.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Expected Result" in rendered
        assert "bi-check2-square" in rendered
        assert "1,300 nodes" in rendered
        assert "border-success" in rendered

    def test_render_step_with_screenshot(self):
        from shyfem_ui.pages.tutorial import _WWW_DIR, _render_step

        # Create a temporary screenshot file so the existence check passes
        img_path = _WWW_DIR / "tutorial" / "grid_prep_stats.png"
        img_path.parent.mkdir(parents=True, exist_ok=True)
        existed = img_path.exists()
        if not existed:
            img_path.write_bytes(b"fake png")
        try:
            step = {
                "title": "Grid Prep",
                "content": "Check the grid.",
                "actions": ["Click **Run shypre**."],
                "expected": "Grid loaded.",
                "screenshot": "grid_prep_stats.png",
            }
            result = _render_step(step, step_num=1)
            rendered = str(result)
            assert "tutorial/grid_prep_stats.png" in rendered
            assert "img-fluid" in rendered
        finally:
            if not existed:
                img_path.unlink(missing_ok=True)

    def test_render_step_screenshot_skipped_when_missing(self):
        """Screenshot field present but file doesn't exist => no <img> tag."""
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "Missing image",
            "content": "No file on disk.",
            "actions": ["Action."],
            "expected": "Result.",
            "screenshot": "nonexistent_file_xyz.png",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "<img" not in rendered

    def test_render_step_without_screenshot(self):
        from shyfem_ui.pages.tutorial import _render_step

        step = {
            "title": "No image",
            "content": "No screenshot.",
            "actions": ["Action."],
            "expected": "Result.",
        }
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "<img" not in rendered

    def test_render_step_without_optional_fields(self):
        """Step with no actions/expected/screenshot still renders."""
        from shyfem_ui.pages.tutorial import _render_step

        step = {"title": "Minimal", "content": "Just content."}
        result = _render_step(step, step_num=1)
        rendered = str(result)
        assert "Minimal" in rendered
        assert "Just content." in rendered
        assert "Actions" not in rendered
        assert "Expected Result" not in rendered


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


class TestTabNameMap:
    """Test the _TAB_NAME_MAP used for navigation."""

    def test_map_has_all_targets(self):
        from shyfem_ui.pages.tutorial import _TAB_NAME_MAP
        expected = {"run", "post_process", "simulation", "grid_prep", "visualize", "compare"}
        assert set(_TAB_NAME_MAP.keys()) == expected

    def test_post_process_uses_hyphen(self):
        from shyfem_ui.pages.tutorial import _TAB_NAME_MAP
        assert _TAB_NAME_MAP["post_process"] == "Post-Process"

    def test_all_values_match_app_tab_labels(self):
        """Every mapped value must match a tab label in app.py."""
        from shyfem_ui.pages.tutorial import _TAB_NAME_MAP
        # These are the exact tab labels from app.py _build_ui()
        valid_labels = {
            "Dashboard", "Tutorial", "Grid Prep", "Partitioning",
            "Simulation", "Run", "Post-Process", "Visualize",
            "Compare", "Ensemble",
        }
        for target, label in _TAB_NAME_MAP.items():
            assert label in valid_labels, (
                f"_TAB_NAME_MAP['{target}'] = '{label}' not in app tab labels"
            )

    def test_run_maps_to_run(self):
        from shyfem_ui.pages.tutorial import _TAB_NAME_MAP
        assert _TAB_NAME_MAP["run"] == "Run"

    def test_grid_prep_maps_correctly(self):
        from shyfem_ui.pages.tutorial import _TAB_NAME_MAP
        assert _TAB_NAME_MAP["grid_prep"] == "Grid Prep"
