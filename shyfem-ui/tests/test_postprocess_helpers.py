"""Tests for helper functions in pages/postprocess.py."""

from shyfem_ui.pages.postprocess import _parse_shyelab_info


SAMPLE_SHYELAB_OUTPUT = """\
 Information on shy file
 filename: test_output.shy
 nvers: 72
 ftype: 15
 nkn: 3489
 nel: 6456
 nlv: 10
 nvar: 3
 date: 20190101
 time: 0
 title: Mar Menor test simulation
 femver: 7.5.71

 nkn = 3489   nel = 6456   mbw = 127

 Total number of available variables: 3
 varnum  varid  description
      1     11  water level
      2     21  velocity (x-component)
      3     22  velocity (y-component)

 levels:   10
    0.00    1.00    2.00    3.00    5.00
    7.00   10.00   15.00   20.00   30.00
"""


class TestParseShyelabInfo:
    """Tests for _parse_shyelab_info()."""

    def test_parses_filename(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["File Name"] == "test_output.shy"

    def test_parses_version(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Version"] == "72"

    def test_parses_file_type(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["File Type"] == "15"

    def test_parses_node_count(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Nodes"] == "3489"

    def test_parses_element_count(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Elements"] == "6456"

    def test_parses_layer_count(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Layers"] == "10"

    def test_parses_title(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Title"] == "Mar Menor test simulation"

    def test_parses_basin_info(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["nkn"] == "3489"
        assert info["nel"] == "6456"
        assert info["mbw"] == "127"

    def test_parses_total_variables(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Total Variables"] == "3"

    def test_parses_variable_names(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        names = info["Variable Names"]
        assert "water level" in names
        assert "velocity (x-component)" in names
        assert "velocity (y-component)" in names

    def test_parses_level_count(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        assert info["Levels"] == "10"

    def test_parses_layer_depths(self):
        info = _parse_shyelab_info(SAMPLE_SHYELAB_OUTPUT)
        depths = info["Layer Depths"]
        assert "0.00" in depths
        assert "30.00" in depths

    def test_empty_input(self):
        info = _parse_shyelab_info("")
        assert isinstance(info, dict)
        assert len(info) == 0

    def test_boolean_conversion(self):
        """Fortran T/.TRUE. → Yes, F/.FALSE. → No."""
        output = " isphe: T\n dirn: .FALSE."
        info = _parse_shyelab_info(output)
        # isphe maps to a custom key in key_map (not listed, so raw key)
        # dirn maps to raw key
        assert "Yes" in str(info.values()) or "No" in str(info.values())
