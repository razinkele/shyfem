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
