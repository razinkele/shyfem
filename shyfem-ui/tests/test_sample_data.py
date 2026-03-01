"""Tests for sample data guidance cards and progressive STR file list."""

import pytest

from shyfem_ui.components.sample_data import (
    PHASE_GUIDANCE,
    get_progressive_str_files,
    sample_data_card_ui,
)


class TestPhaseGuidance:
    """Validate the PHASE_GUIDANCE dictionary."""

    REQUIRED_PAGES = ("grid_prep", "simulation", "run", "postprocess")
    REQUIRED_FIELDS = ("icon", "title", "what", "inputs", "outputs", "key_params", "sample_desc")

    def test_has_all_four_pages(self):
        for page in self.REQUIRED_PAGES:
            assert page in PHASE_GUIDANCE, f"Missing page: {page}"

    def test_each_page_has_required_fields(self):
        for page in self.REQUIRED_PAGES:
            guidance = PHASE_GUIDANCE[page]
            for field in self.REQUIRED_FIELDS:
                assert field in guidance, f"Page '{page}' missing field '{field}'"
                assert isinstance(guidance[field], str)
                assert len(guidance[field].strip()) > 0

    def test_icons_are_nonempty(self):
        for page, guidance in PHASE_GUIDANCE.items():
            assert len(guidance["icon"]) > 0, f"Page '{page}' has empty icon"

    def test_no_extra_pages(self):
        assert set(PHASE_GUIDANCE.keys()) == set(self.REQUIRED_PAGES)


class TestGetProgressiveStrFiles:
    """Validate get_progressive_str_files() output."""

    def test_returns_list(self):
        result = get_progressive_str_files()
        assert isinstance(result, list)

    def test_returns_at_least_14_entries(self):
        result = get_progressive_str_files()
        assert len(result) >= 14

    def test_entries_have_required_keys(self):
        for entry in get_progressive_str_files():
            assert "name" in entry, f"Entry missing 'name': {entry}"
            assert "file" in entry, f"Entry missing 'file': {entry}"
            assert "label" in entry, f"Entry missing 'label': {entry}"
            assert "description" in entry, f"Entry missing 'description': {entry}"

    def test_entries_are_nonempty_strings(self):
        for entry in get_progressive_str_files():
            for key in ("name", "file", "label", "description"):
                assert isinstance(entry[key], str)
                assert len(entry[key].strip()) > 0, f"Empty {key} in {entry['name']}"

    def test_file_names_end_with_str(self):
        for entry in get_progressive_str_files():
            assert entry["file"].endswith(".str"), f"Bad file: {entry['file']}"

    def test_first_entry_is_mm_hyd_00(self):
        result = get_progressive_str_files()
        assert result[0]["name"] == "mm_hyd_00"
        assert result[0]["file"] == "mm_hyd_00.str"

    def test_last_entry_is_mm_hyd_43(self):
        result = get_progressive_str_files()
        assert result[-1]["name"] == "mm_hyd_43"
        assert result[-1]["file"] == "mm_hyd_43.str"

    def test_names_are_unique(self):
        names = [e["name"] for e in get_progressive_str_files()]
        assert len(names) == len(set(names)), "Duplicate names found"

    def test_files_are_unique(self):
        files = [e["file"] for e in get_progressive_str_files()]
        assert len(files) == len(set(files)), "Duplicate files found"

    def test_label_contains_name(self):
        for entry in get_progressive_str_files():
            assert entry["name"] in entry["label"], (
                f"Label '{entry['label']}' should contain name '{entry['name']}'"
            )

    def test_matches_tutorial_content_order(self):
        """STR file list order must match tutorial_content.py order."""
        from shyfem_ui.tutorial_content import get_all_sim_names

        str_names = [e["name"] for e in get_progressive_str_files()]
        tutorial_names = get_all_sim_names()
        assert str_names == tutorial_names


class TestSampleDataCardUi:
    """Validate sample_data_card_ui() renders for all pages."""

    def test_renders_grid_prep_card(self):
        card = sample_data_card_ui("grid_prep")
        html = str(card)
        assert "Grid Preparation" in html
        assert "load_sample_btn" in html
        assert "guidance-grid_prep" in html

    def test_renders_simulation_card(self):
        card = sample_data_card_ui("simulation")
        html = str(card)
        assert "Simulation Configuration" in html
        assert "load_sample_btn" in html
        assert "sample_str_select" in html
        assert "guidance-simulation" in html

    def test_renders_run_card(self):
        card = sample_data_card_ui("run")
        html = str(card)
        assert "Run Simulation" in html
        assert "load_sample_btn" in html
        assert "guidance-run" in html

    def test_renders_postprocess_card(self):
        card = sample_data_card_ui("postprocess")
        html = str(card)
        assert "Post-Processing" in html
        assert "load_sample_btn" in html
        assert "guidance-postprocess" in html

    def test_simulation_card_has_str_dropdown(self):
        """Only the simulation page should have the STR file dropdown."""
        sim_html = str(sample_data_card_ui("simulation"))
        assert "sample_str_select" in sim_html

        for page in ("grid_prep", "run", "postprocess"):
            html = str(sample_data_card_ui(page))
            assert "sample_str_select" not in html, (
                f"Page '{page}' should not have STR dropdown"
            )

    def test_all_cards_have_tutorial_link(self):
        for page in ("grid_prep", "simulation", "run", "postprocess"):
            html = str(sample_data_card_ui(page))
            assert "shyfemNavTo" in html
            assert "Tutorial" in html

    def test_all_cards_start_expanded(self):
        for page in ("grid_prep", "simulation", "run", "postprocess"):
            html = str(sample_data_card_ui(page))
            assert "collapse show" in html

    def test_invalid_page_raises_keyerror(self):
        with pytest.raises(KeyError):
            sample_data_card_ui("nonexistent")

    def test_card_has_info_border(self):
        for page in ("grid_prep", "simulation", "run", "postprocess"):
            html = str(sample_data_card_ui(page))
            assert "border-info" in html


class TestPageIntegration:
    """Verify that the 4 setup pages import and use sample_data_card_ui."""

    def test_grid_prep_imports_sample_data(self):
        import shyfem_ui.pages.grid_prep as gp
        # Verify the module can be imported without error
        assert hasattr(gp, "grid_prep_ui")
        assert hasattr(gp, "grid_prep_server")

    def test_simulation_imports_sample_data(self):
        import shyfem_ui.pages.simulation as sim
        assert hasattr(sim, "simulation_ui")
        assert hasattr(sim, "simulation_server")

    def test_run_imports_sample_data(self):
        import shyfem_ui.pages.run as run
        assert hasattr(run, "run_ui")
        assert hasattr(run, "run_server")

    def test_postprocess_imports_sample_data(self):
        import shyfem_ui.pages.postprocess as pp
        assert hasattr(pp, "postprocess_ui")
        assert hasattr(pp, "postprocess_server")

    def test_grid_prep_ui_contains_guidance_card(self):
        from shyfem_ui.pages.grid_prep import grid_prep_ui
        html = str(grid_prep_ui("test_gp"))
        assert "guidance-grid_prep" in html

    def test_simulation_ui_contains_guidance_card(self):
        from shyfem_ui.pages.simulation import simulation_ui
        html = str(simulation_ui("test_sim"))
        assert "guidance-simulation" in html

    def test_run_ui_contains_guidance_card(self):
        from shyfem_ui.pages.run import run_ui
        html = str(run_ui("test_run"))
        assert "guidance-run" in html

    def test_postprocess_ui_contains_guidance_card(self):
        from shyfem_ui.pages.postprocess import postprocess_ui
        html = str(postprocess_ui("test_pp"))
        assert "guidance-postprocess" in html
