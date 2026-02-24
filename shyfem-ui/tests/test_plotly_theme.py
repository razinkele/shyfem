"""Tests for the custom Plotly theme module."""

from shyfem_ui.plotly_theme import (
    SHYFEM_CATEGORICAL_COLORS,
    SHYFEM_OCEAN_COLORSCALE,
    get_plotly_template,
    register_shyfem_template,
)


class TestGetPlotlyTemplate:
    def test_returns_dict(self):
        result = get_plotly_template(dark=False)
        assert isinstance(result, dict)

    def test_light_has_white_plot_bg(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["plot_bgcolor"] == "#FFFFFF"

    def test_light_has_sand_paper_bg(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["paper_bgcolor"] == "#F5F0E8"

    def test_dark_has_dark_plot_bg(self):
        t = get_plotly_template(dark=True)
        assert t["layout"]["plot_bgcolor"] == "#1A2332"

    def test_dark_has_dark_paper_bg(self):
        t = get_plotly_template(dark=True)
        assert t["layout"]["paper_bgcolor"] == "#2A3545"

    def test_font_family_is_inter(self):
        t = get_plotly_template(dark=False)
        assert "Inter" in t["layout"]["font"]["family"]

    def test_colorway_set(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["colorway"] == SHYFEM_CATEGORICAL_COLORS

    def test_margins_tight(self):
        t = get_plotly_template(dark=False)
        m = t["layout"]["margin"]
        assert m["l"] == 60
        assert m["r"] == 20
        assert m["t"] == 40
        assert m["b"] == 50


class TestColorscale:
    def test_ocean_colorscale_has_entries(self):
        assert len(SHYFEM_OCEAN_COLORSCALE) >= 6

    def test_ocean_colorscale_starts_at_zero(self):
        assert SHYFEM_OCEAN_COLORSCALE[0][0] == 0.0

    def test_ocean_colorscale_ends_at_one(self):
        assert SHYFEM_OCEAN_COLORSCALE[-1][0] == 1.0


class TestCategoricalColors:
    def test_has_six_colors(self):
        assert len(SHYFEM_CATEGORICAL_COLORS) == 6

    def test_all_are_hex(self):
        for c in SHYFEM_CATEGORICAL_COLORS:
            assert c.startswith("#") and len(c) == 7


class TestRegisterTemplate:
    def test_register_sets_default(self):
        register_shyfem_template(dark=False)
        import plotly.io as pio
        assert pio.templates.default == "shyfem"
        assert "shyfem" in pio.templates

    def test_register_dark_sets_default(self):
        register_shyfem_template(dark=True)
        import plotly.io as pio
        assert pio.templates.default == "shyfem"
