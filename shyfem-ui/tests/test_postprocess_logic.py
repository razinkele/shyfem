"""Tests for pure helpers extracted from pages/postprocess.py."""

from shyfem_ui.services.postprocess_logic import (
    build_shyelab_options,
    discover_shy_files,
    format_size,
    parse_shyelab_info,
)


class TestFormatSize:
    def test_zero_bytes(self):
        assert format_size(0) == "0 B"

    def test_under_1kb(self):
        assert format_size(512) == "512 B"
        assert format_size(1023) == "1023 B"

    def test_exactly_1kb(self):
        assert format_size(1024) == "1.0 KB"

    def test_kb_range(self):
        assert format_size(2048) == "2.0 KB"
        assert format_size(1024 * 1023) == "1023.0 KB"

    def test_exactly_1mb(self):
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_mb_range(self):
        assert format_size(5 * 1024 * 1024) == "5.0 MB"


class TestDiscoverShyFiles:
    def test_empty_dir(self, tmp_path):
        assert discover_shy_files(tmp_path) == []

    def test_missing_dir(self, tmp_path):
        assert discover_shy_files(tmp_path / "nope") == []

    def test_finds_shy_only(self, tmp_path):
        (tmp_path / "a.shy").write_bytes(b"x")
        (tmp_path / "b.shy").write_bytes(b"yy")
        (tmp_path / "ignore.txt").write_text("nope")
        results = discover_shy_files(tmp_path)
        names = [r["name"] for r in results]
        assert names == ["a.shy", "b.shy"]
        assert all("B" in r["size_str"] for r in results)

    def test_sorted_by_name(self, tmp_path):
        (tmp_path / "z.shy").write_bytes(b"x")
        (tmp_path / "a.shy").write_bytes(b"x")
        (tmp_path / "m.shy").write_bytes(b"x")
        names = [r["name"] for r in discover_shy_files(tmp_path)]
        assert names == ["a.shy", "m.shy", "z.shy"]

    def test_result_has_path_field(self, tmp_path):
        f = tmp_path / "data.shy"
        f.write_bytes(b"hello")
        results = discover_shy_files(tmp_path)
        assert len(results) == 1
        assert results[0]["path"] == str(f)
        assert results[0]["name"] == "data.shy"

    def test_accepts_string_path(self, tmp_path):
        (tmp_path / "s.shy").write_bytes(b"x")
        results = discover_shy_files(str(tmp_path))
        assert len(results) == 1


class TestBuildShyelabOptions:
    def test_custom_mode_splits_text(self):
        opts = build_shyelab_options(
            operation="custom",
            op_flags=[],
            custom_options="-foo 1 -bar baz",
        )
        assert opts == ["-foo", "1", "-bar", "baz"]

    def test_custom_mode_empty(self):
        opts = build_shyelab_options(
            operation="custom",
            op_flags=[],
            custom_options="",
        )
        assert opts == []

    def test_named_mode_uses_op_flags(self):
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
        )
        assert "-taver" in opts

    def test_time_range_added(self):
        opts = build_shyelab_options(
            operation="info",
            op_flags=["-info"],
            tmin="2020-01-01",
            tmax="2020-12-31",
        )
        assert "-tmin" in opts
        assert opts[opts.index("-tmin") + 1] == "2020-01-01"
        assert "-tmax" in opts
        assert opts[opts.index("-tmax") + 1] == "2020-12-31"

    def test_empty_tmin_tmax_not_added(self):
        opts = build_shyelab_options(
            operation="info",
            op_flags=["-info"],
            tmin="",
            tmax=None,
        )
        assert "-tmin" not in opts
        assert "-tmax" not in opts

    def test_subset_var_filter_passed_through(self):
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
            selected_vars=["temp", "salt"],
            scanned_vars_count=4,
        )
        assert "-temp" in opts
        assert "-salt" in opts

    def test_full_var_selection_omits_filter(self):
        # All 3 of 3 selected — no per-var flags emitted
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
            selected_vars=["a", "b", "c"],
            scanned_vars_count=3,
        )
        assert all(o not in opts for o in ["-a", "-b", "-c"])

    def test_empty_var_list_omits_filter(self):
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
            selected_vars=[],
            scanned_vars_count=3,
        )
        # No spurious -<var> flags
        assert opts == ["-taver"]

    def test_layer_specific(self):
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
            selected_layer="3",
        )
        assert "-layer" in opts
        assert opts[opts.index("-layer") + 1] == "3"

    def test_layer_all_omits_flag(self):
        opts = build_shyelab_options(
            operation="temporal_avg",
            op_flags=["-taver"],
            selected_layer="all",
        )
        assert "-layer" not in opts

    def test_custom_ignores_op_flags(self):
        # custom mode ignores op_flags entirely
        opts = build_shyelab_options(
            operation="custom",
            op_flags=["-taver"],
            custom_options="-myopt",
        )
        assert opts == ["-myopt"]
        assert "-taver" not in opts


class TestParseShyelabInfo:
    def test_empty_output_returns_empty_dict(self):
        assert parse_shyelab_info("") == {}

    def test_parses_colon_label_value_pairs(self):
        out = " nkn:           1234\n nel:           2345\n nlv:              5\n"
        info = parse_shyelab_info(out)
        # key_map remaps nkn->Nodes, nel->Elements, nlv->Layers
        assert info["Nodes"] == "1234"
        assert info["Elements"] == "2345"
        assert info["Layers"] == "5"

    def test_parses_basin_info_equals_format(self):
        out = "  nkn = 100   nel = 200\n"
        info = parse_shyelab_info(out)
        assert info.get("nkn") == "100"
        assert info.get("nel") == "200"

    def test_parses_variable_table(self):
        out = (
            " total number of available variables: 2\n"
            " varnum  varid\n"
            "     1      31  water level\n"
            "     2      27  temperature\n"
        )
        info = parse_shyelab_info(out)
        assert info["Total Variables"] == "2"
        assert "Variable Names" in info
        assert "water level" in info["Variable Names"]
        assert "temperature" in info["Variable Names"]

    def test_parses_levels_header(self):
        out = " levels: 5\n 1.0 5.0 10.0 20.0 50.0\n"
        info = parse_shyelab_info(out)
        assert info.get("Levels") == "5"
        assert "Layer Depths" in info
        assert "1.0" in info["Layer Depths"]

    def test_boolean_T_becomes_Yes(self):
        out = " isphe:          T\n"
        info = parse_shyelab_info(out)
        assert "Yes" in info.values()

    def test_boolean_F_becomes_No(self):
        out = " isphe:          F\n"
        info = parse_shyelab_info(out)
        assert "No" in info.values()

    def test_section_header_line_skipped(self):
        out = " Information on shy file\n nkn: 10\n"
        info = parse_shyelab_info(out)
        assert "Nodes" in info
        assert len(info) == 1
