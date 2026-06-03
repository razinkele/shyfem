"""Tests for tutorial content structure and completeness."""

import pytest


class TestTutorialContentStructure:
    """Validate the TUTORIAL_CONTENT data structure."""

    def test_has_six_phases(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        assert len(TUTORIAL_CONTENT) == 6

    def test_phase_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            assert "id" in phase
            assert "title" in phase
            assert "description" in phase
            assert "simulations" in phase
            assert len(phase["simulations"]) > 0

    def test_simulation_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                assert "name" in sim
                assert "str_file" in sim
                assert "title" in sim
                assert "summary" in sim
                assert "steps" in sim
                assert len(sim["steps"]) > 0

    def test_step_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    assert "title" in step
                    assert "content" in step

    def test_all_str_files_exist_in_mar_menor(self):
        """Every referenced .str file must exist in the testcases source."""
        from pathlib import Path

        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        mar_menor = Path("/home/razinka/shyfem/testcases/examples/mar_menor")
        if not mar_menor.is_dir():
            pytest.skip("Mar Menor testcase directory not found")
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                str_path = mar_menor / sim["str_file"]
                assert str_path.exists(), f"Missing: {sim['str_file']}"

    def test_total_simulation_count(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        total = sum(len(p["simulations"]) for p in TUTORIAL_CONTENT)
        assert total == 14

    def test_new_params_are_dicts(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                if "new_params" in sim:
                    assert isinstance(sim["new_params"], dict)


class TestActionFields:
    """Validate the new actions/expected/screenshot fields."""

    def test_every_step_has_actions(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    assert "actions" in step, (
                        f"Step '{step['title']}' in {sim['name']} missing actions"
                    )
                    assert isinstance(step["actions"], list)
                    assert len(step["actions"]) > 0

    def test_actions_are_nonempty_strings(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    for action in step.get("actions", []):
                        assert isinstance(action, str)
                        assert len(action.strip()) > 0

    def test_every_step_has_expected(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    assert "expected" in step, (
                        f"Step '{step['title']}' in {sim['name']} missing expected"
                    )
                    assert isinstance(step["expected"], str)
                    assert len(step["expected"].strip()) > 0

    def test_screenshot_is_string_when_present(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    screenshot = step.get("screenshot")
                    if screenshot is not None:
                        assert isinstance(screenshot, str)
                        assert screenshot.endswith(".png")

    def test_at_least_some_steps_have_screenshots(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        screenshots = []
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    if "screenshot" in step:
                        screenshots.append(step["screenshot"])
        assert len(screenshots) >= 5, "Expected at least 5 screenshot references"

    def test_screenshot_filenames_are_unique(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        filenames = []
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    if "screenshot" in step:
                        filenames.append(step["screenshot"])
        assert len(filenames) == len(set(filenames)), "Duplicate screenshot filenames"


class TestBuildTutorialContext:
    """Test the build_tutorial_context() helper."""

    def test_valid_sim_returns_dict(self):
        from shyfem_ui.tutorial_content import build_tutorial_context
        ctx = build_tutorial_context("mm_hyd_00", "/tmp/work", "Grid Prep")
        assert ctx is not None
        assert isinstance(ctx, dict)
        assert ctx["sim_name"] == "mm_hyd_00"
        assert ctx["str_file"] == "mm_hyd_00.str"
        assert ctx["work_dir"] == "/tmp/work"
        assert ctx["grd_file"] == "GRID/MM_coarse.grd"
        assert ctx["target_tab"] == "Grid Prep"

    def test_invalid_sim_returns_none(self):
        from shyfem_ui.tutorial_content import build_tutorial_context
        assert build_tutorial_context("nonexistent", "/tmp", "Run") is None

    def test_all_sims_produce_valid_context(self):
        from shyfem_ui.tutorial_content import build_tutorial_context, get_all_sim_names
        for name in get_all_sim_names():
            ctx = build_tutorial_context(name, "/work", "Simulation")
            assert ctx is not None, f"build_tutorial_context failed for {name}"
            assert "str_file" in ctx
            assert "work_dir" in ctx
            assert "grd_file" in ctx

    def test_target_tab_preserved(self):
        from shyfem_ui.tutorial_content import build_tutorial_context
        ctx = build_tutorial_context("mm_hyd_02", "/work", "Post-Process")
        assert ctx["target_tab"] == "Post-Process"

    def test_returns_all_expected_keys(self):
        from shyfem_ui.tutorial_content import build_tutorial_context
        ctx = build_tutorial_context("mm_hyd_01", "/work", "Run")
        expected_keys = {"sim_name", "str_file", "work_dir", "grd_file", "target_tab"}
        assert set(ctx.keys()) == expected_keys


class TestHelpers:
    """Test helper functions."""

    def test_get_phase_by_id(self):
        from shyfem_ui.tutorial_content import get_phase
        phase = get_phase("phase1")
        assert phase is not None
        assert phase["title"].startswith("Phase 1")

    def test_get_phase_missing(self):
        from shyfem_ui.tutorial_content import get_phase
        assert get_phase("nonexistent") is None

    def test_get_simulation(self):
        from shyfem_ui.tutorial_content import get_simulation
        sim = get_simulation("mm_hyd_00")
        assert sim is not None
        assert sim["name"] == "mm_hyd_00"

    def test_get_simulation_missing(self):
        from shyfem_ui.tutorial_content import get_simulation
        assert get_simulation("nonexistent") is None

    def test_get_all_sim_names(self):
        from shyfem_ui.tutorial_content import get_all_sim_names
        names = get_all_sim_names()
        assert "mm_hyd_00" in names
        assert "mm_hyd_43" in names
        assert len(names) == 14
