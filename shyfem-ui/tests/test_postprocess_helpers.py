"""Tests for helper functions extracted to services/postprocess_logic.py."""

from shyfem_ui.services.postprocess_logic import (
    discover_shy_files as _discover_shy_files,
)
from shyfem_ui.services.postprocess_logic import (
    parse_shyelab_info as _parse_shyelab_info,
)

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


class TestDiscoverShyFiles:
    """Tests for _discover_shy_files()."""

    def test_empty_dir(self, tmp_path):
        result = _discover_shy_files(tmp_path)
        assert result == []

    def test_with_shy_files(self, tmp_path):
        (tmp_path / "output_a.shy").write_bytes(b"x" * 2048)
        (tmp_path / "output_b.shy").write_bytes(b"x" * 100)
        result = _discover_shy_files(tmp_path)
        assert len(result) == 2
        assert result[0]["name"] == "output_a.shy"
        assert result[1]["name"] == "output_b.shy"
        assert result[0]["path"] == str(tmp_path / "output_a.shy")

    def test_ignores_non_shy(self, tmp_path):
        (tmp_path / "data.nc").write_bytes(b"nc")
        (tmp_path / "log.txt").write_bytes(b"log")
        (tmp_path / "valid.shy").write_bytes(b"shy")
        result = _discover_shy_files(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "valid.shy"

    def test_nonexistent_dir(self):
        result = _discover_shy_files("/nonexistent/path/xyz")
        assert result == []

    def test_size_formatting_bytes(self, tmp_path):
        (tmp_path / "small.shy").write_bytes(b"x" * 500)
        result = _discover_shy_files(tmp_path)
        assert "500 B" == result[0]["size_str"]

    def test_size_formatting_kb(self, tmp_path):
        (tmp_path / "medium.shy").write_bytes(b"x" * 5120)
        result = _discover_shy_files(tmp_path)
        assert "5.0 KB" == result[0]["size_str"]

    def test_size_formatting_mb(self, tmp_path):
        (tmp_path / "large.shy").write_bytes(b"x" * (2 * 1024 * 1024))
        result = _discover_shy_files(tmp_path)
        assert "2.0 MB" == result[0]["size_str"]
