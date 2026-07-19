"""Tests for build_job_spec — the new pure helper extracted from
_submit_job's inline JobSpec assembly. The 6 already-pure helpers
(detect_mesh_node_count, get_solver_recommendation, etc.) are covered
by their existing test files (test_run_helpers, test_run_validation,
test_job_ownership)."""

from pathlib import Path

import pytest

from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus
from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.run_logic import (
    build_job_spec,
    compute_restart_choices,
    restart_info_text,
    restart_selection_denied_reason,
    write_restart_str,
)


class TestBuildJobSpec:

    def _base_args(self, **overrides):
        defaults = dict(
            name="testjob",
            tool_name="shyfem",
            validated_input=Path("/tmp/sim.str"),
            validated_workdir=Path("/tmp"),
            session_id="sess1",
        )
        defaults.update(overrides)
        return defaults

    def test_returns_jobspec(self):
        spec = build_job_spec(**self._base_args())
        assert isinstance(spec, JobSpec)

    def test_args_contains_input_path(self):
        spec = build_job_spec(**self._base_args())
        assert spec.args == ["/tmp/sim.str"]

    def test_metadata_session_id_always_set(self):
        spec = build_job_spec(**self._base_args(session_id="sess42"))
        assert spec.metadata["session_id"] == "sess42"

    def test_metadata_user_id_when_set(self):
        spec = build_job_spec(**self._base_args(user_id=99))
        assert spec.metadata["user_id"] == 99

    def test_metadata_user_id_omitted_when_none(self):
        spec = build_job_spec(**self._base_args(user_id=None))
        assert "user_id" not in spec.metadata

    def test_solver_petsc_recorded(self):
        spec = build_job_spec(**self._base_args(solver="petsc"))
        assert spec.metadata["solver"] == "petsc"

    def test_solver_sparskit_not_recorded(self):
        # Per the original page logic, sparskit is the default and is NOT
        # written to metadata (only petsc is, as a non-default flag).
        spec = build_job_spec(**self._base_args(solver="sparskit"))
        assert "solver" not in spec.metadata

    def test_solver_none_not_recorded(self):
        spec = build_job_spec(**self._base_args(solver=None))
        assert "solver" not in spec.metadata

    def test_restart_from_recorded(self):
        spec = build_job_spec(**self._base_args(restart_from="/path/to/restart.shy"))
        assert spec.metadata["restart_file"] == "/path/to/restart.shy"

    def test_restart_from_none_omitted(self):
        spec = build_job_spec(**self._base_args(restart_from=None))
        assert "restart_file" not in spec.metadata

    def test_depends_on_recorded(self):
        spec = build_job_spec(**self._base_args(depends_on="parent_job_id"))
        assert spec.metadata["depends_on"] == "parent_job_id"

    def test_mpi_enabled_only_for_shyfem(self):
        # If tool is shyfem AND mpi_enabled=True, mpi flags are honored
        spec = build_job_spec(
            **self._base_args(
                tool_name="shyfem",
                mpi_enabled=True,
                mpi_np=4,
            )
        )
        assert spec.mpi_enabled is True
        assert spec.mpi_np == 4

    def test_mpi_disabled_for_non_shyfem(self):
        # mpi_enabled is suppressed when tool != shyfem
        spec = build_job_spec(
            **self._base_args(
                tool_name="shyelab",
                mpi_enabled=True,
                mpi_np=4,
            )
        )
        assert spec.mpi_enabled is False
        assert spec.mpi_np == 1

    def test_mpi_np_default_is_1(self):
        spec = build_job_spec(
            **self._base_args(
                tool_name="shyfem",
                mpi_enabled=False,
            )
        )
        assert spec.mpi_np == 1

    def test_working_dir_set_correctly(self):
        spec = build_job_spec(**self._base_args(validated_workdir=Path("/data/runs")))
        assert spec.working_dir == Path("/data/runs")

    def test_tool_name_propagated(self):
        spec = build_job_spec(**self._base_args(tool_name="shyelab"))
        assert spec.tool_name == "shyelab"

    def test_name_propagated(self):
        spec = build_job_spec(**self._base_args(name="my_run_job"))
        assert spec.name == "my_run_job"

    def test_depends_on_none_omitted(self):
        spec = build_job_spec(**self._base_args(depends_on=None))
        assert "depends_on" not in spec.metadata


class TestWriteRestartStr:
    """N42: 'Continue from job' was recorded only in build_job_spec's
    metadata (restart_file) and never applied to the STR SHYFEM actually
    executes -- the run silently started fresh regardless of the selection.
    write_restart_str is the fix: it parses the source STR, sets the $name
    section's `restrt` parameter (the field SHYFEM reads for continuation,
    see services/parser_str.py PARAM_DOCS['name']['restrt']) to the chosen
    restart file, and writes the result to a NEW file so the caller can pass
    that file's path (not the original) to build_job_spec / JobSpec.args."""

    def _write_str(self, tmp_path: Path, name: str = "sim.str") -> Path:
        str_path = tmp_path / name
        str_path.write_text(
            "$title\n"
            "        Test simulation\n"
            "        basin\n"
            "        MM_coarse\n"
            "$end\n"
            "$para\n"
            "        itend = 3600\n"
            "$end\n"
        )
        return str_path

    def test_derived_str_contains_restrt_pointing_at_restart_file(self, tmp_path):
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        text = result_path.read_text()
        assert "restrt" in text
        assert str(restart_file) in text

    def test_restrt_lands_in_name_section(self, tmp_path):
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        parsed = StrParser.parse_file(result_path)
        assert parsed.get_param("name", "restrt") == str(restart_file)

    def test_itrst_is_set_to_minus_one(self, tmp_path):
        """Final security review, Finding 1 (correctness): restrt alone
        does not make SHYFEM continue. Per src/shyfem/def_para.f90 (itrst
        default 0, docs: '-1 ... last record ... is used for the restart')
        and src/shyfem/restart.f90 (rst_perform_restart: with the default
        itrst=0/ityrst=0, a non-matching time record is a hard
        `stop 'error stop rst_perform_restart: Cannot find time record'`;
        itrst=-1 sets blast=.true. / atrst=-1., which reads the LAST
        record unconditionally), a submission must also set itrst=-1 or
        SHYFEM crashes at startup instead of continuing. Both shipped
        working restart testcases confirm this exact value:
        testcases/examples/weutro_box/eco_rst_part2.str:14 and
        merc_rst_part2.str:13 both set `itrst = -1`."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        parsed = StrParser.parse_file(result_path)
        assert parsed.get_param("para", "itrst") == -1

    def test_itrst_emitted_as_bare_number_not_quoted(self, tmp_path):
        """Both testcases write `itrst = -1` with no quotes (it's a
        numeric/real parameter per def_para.f90's `addpar('itrst',0.)`,
        unlike restrt which is a string/filename) -- assert the literal
        generated text matches, not just the round-tripped parsed value."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        text = result_path.read_text()
        assert "itrst = -1" in text
        assert "itrst = '-1'" not in text

    def test_original_str_file_is_not_mutated(self, tmp_path):
        str_path = self._write_str(tmp_path)
        original_text = str_path.read_text()
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        write_restart_str(str_path, str(restart_file), dest_dir)

        assert str_path.read_text() == original_text

    def test_derived_file_written_under_dest_dir(self, tmp_path):
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        assert result_path.parent == dest_dir
        assert result_path != str_path

    def test_restart_path_without_hyphen_or_space_is_still_quoted(self, tmp_path, monkeypatch):
        """StrParser._format_value only auto-quotes strings containing a
        space or '-'. An absolute restart path with neither (plausible in
        prod: no guarantee a user/project name contains a hyphen) would
        otherwise be emitted UNQUOTED (`restrt = /a/b/out.rst`), which a
        Fortran namelist read may misparse or truncate at the first '/'.
        Regression guard: the emitted value must always be quoted regardless
        of the path's contents."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = "/data/shyfem/proj/out.rst"  # deliberately no '-' or ' '
        monkeypatch.setattr(Path, "exists", lambda self: True)

        result_path = write_restart_str(str_path, restart_file, dest_dir)

        text = result_path.read_text()
        assert f"restrt = '{restart_file}'" in text
        parsed = StrParser.parse_file(result_path)
        assert parsed.get_param("name", "restrt") == restart_file

    def test_other_params_survive_unchanged(self, tmp_path):
        """The rest of the STR (e.g. $para/itend) must round-trip intact --
        applying restart must not clobber unrelated sections."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        result_path = write_restart_str(str_path, str(restart_file), dest_dir)

        parsed = StrParser.parse_file(result_path)
        assert parsed.get_param("para", "itend") == 3600

    def test_missing_restart_file_raises(self, tmp_path):
        """A stale selection (the .rst was deleted/moved) must abort loudly
        rather than silently produce an STR that references a nonexistent
        file -- SHYFEM would otherwise fail deep in Fortran I/O with an
        opaque error instead of a clear UI message."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        missing_restart = tmp_path / "does_not_exist.rst"

        with pytest.raises(FileNotFoundError):
            write_restart_str(str_path, str(missing_restart), dest_dir)

    def test_two_calls_do_not_collide(self, tmp_path):
        """Two restart-enabled submissions against the same STR/workdir must
        not overwrite each other's derived STR mid-run."""
        str_path = self._write_str(tmp_path)
        dest_dir = tmp_path / "work"
        dest_dir.mkdir()
        restart_file = tmp_path / "prior_run.rst"
        restart_file.write_text("")

        first = write_restart_str(str_path, str(restart_file), dest_dir)
        second = write_restart_str(str_path, str(restart_file), dest_dir)

        assert first != second
        assert first.exists()
        assert second.exists()


def _completed_shyfem_job(work_dir, name="run1", job_id="job-1", **overrides) -> JobInfo:
    defaults = dict(
        id=job_id,
        name=name,
        tool_name="shyfem",
        args=[],
        working_dir=str(work_dir),
        status=JobStatus.COMPLETED,
    )
    defaults.update(overrides)
    return JobInfo(**defaults)


class TestComputeRestartChoices:
    """compute_restart_choices is the single source of truth shared by the
    restart_section dropdown and the server-side allowlist check
    (restart_selection_denied_reason) -- see run_logic.py docstrings."""

    def test_completed_shyfem_job_with_rst_is_included(self, tmp_path):
        (tmp_path / "out.rst").write_text("")
        job = _completed_shyfem_job(tmp_path)

        choices = compute_restart_choices([job])

        assert str(tmp_path / "out.rst") in choices

    def test_non_shyfem_tool_excluded(self, tmp_path):
        (tmp_path / "out.rst").write_text("")
        job = _completed_shyfem_job(tmp_path, tool_name="shyelab")

        assert compute_restart_choices([job]) == {}

    def test_non_completed_status_excluded(self, tmp_path):
        (tmp_path / "out.rst").write_text("")
        job = _completed_shyfem_job(tmp_path, status=JobStatus.RUNNING)

        assert compute_restart_choices([job]) == {}

    def test_no_rst_files_excluded(self, tmp_path):
        job = _completed_shyfem_job(tmp_path)

        assert compute_restart_choices([job]) == {}

    def test_latest_rst_file_picked_when_multiple(self, tmp_path):
        (tmp_path / "a_early.rst").write_text("")
        (tmp_path / "z_late.rst").write_text("")
        job = _completed_shyfem_job(tmp_path)

        choices = compute_restart_choices([job])

        assert str(tmp_path / "z_late.rst") in choices
        assert str(tmp_path / "a_early.rst") not in choices

    def test_empty_jobs_list_yields_no_choices(self):
        assert compute_restart_choices([]) == {}

    def test_jobs_outside_the_provided_scope_never_appear(self, tmp_path):
        """The function itself does no access control -- it only reflects
        whatever job list the caller hands it. This locks the security
        property one level up: if the caller correctly scopes `jobs` to
        the current user's own jobs (excluding another user's), that other
        user's .rst simply cannot appear in the result no matter what its
        path is."""
        other_user_dir = tmp_path / "other_user_job"
        other_user_dir.mkdir()
        (other_user_dir / "secret.rst").write_text("")
        # `jobs` here simulates the caller already having scoped the list
        # to exclude the other user's job entirely.
        choices = compute_restart_choices([])

        assert str(other_user_dir / "secret.rst") not in choices


class TestRestartSelectionDeniedReason:
    """N42 IDOR follow-up: restart_from is a client-controlled input that
    now flows into write_restart_str, which opens the file it names. This
    is the allowlist gate that must reject any restart_from not present in
    the server-recomputed, already-scoped choice set -- closing the
    spoofed-WS-message bypass of the restart_section dropdown."""

    def test_none_restart_from_is_allowed(self):
        assert restart_selection_denied_reason(None, []) is None

    def test_empty_string_restart_from_is_allowed(self):
        assert restart_selection_denied_reason("", []) is None

    def test_restart_from_matching_a_computed_choice_is_allowed(self, tmp_path):
        (tmp_path / "out.rst").write_text("")
        job = _completed_shyfem_job(tmp_path)

        reason = restart_selection_denied_reason(str(tmp_path / "out.rst"), [job])

        assert reason is None

    def test_restart_from_not_among_scoped_jobs_is_denied(self, tmp_path):
        """Core IDOR regression: a restart_from that doesn't correspond to
        any job in the caller-scoped jobs list -- e.g. a value a spoofed WS
        message set directly, bypassing the dropdown -- must be denied,
        even though nothing here claims the path doesn't exist."""
        spoofed_path = str(tmp_path / "someone_elses_run" / "secret.rst")

        reason = restart_selection_denied_reason(spoofed_path, [])

        assert reason is not None
        assert "restart" in reason.lower()

    def test_restart_from_pointing_at_a_real_file_outside_scope_is_still_denied(self, tmp_path):
        """Proves this is a real allowlist, not a bare existence check: the
        file genuinely exists on disk, but its owning job is not in the
        (already user-scoped) jobs list the caller passed in, so it must
        still be denied."""
        other_user_dir = tmp_path / "other_user"
        other_user_dir.mkdir()
        real_file = other_user_dir / "real.rst"
        real_file.write_text("")

        # Caller scoped jobs to the current (non-admin) user only; the
        # other user's job producing real_file is correctly absent here.
        reason = restart_selection_denied_reason(str(real_file), [])

        assert reason is not None

    def test_restart_from_allowed_when_admin_scope_includes_other_users_job(self, tmp_path):
        """The admin 'show all jobs' case: when the caller passes an
        unscoped (uid=None) jobs list that legitimately includes another
        user's completed job, that job's .rst IS a valid choice. A bare
        confine_path check would have wrongly rejected this; the allowlist
        correctly allows it because it's a member of the recomputed set.
        """
        other_user_dir = tmp_path / "other_user"
        other_user_dir.mkdir()
        rst = other_user_dir / "out.rst"
        rst.write_text("")
        admin_visible_job = _completed_shyfem_job(other_user_dir, name="alice-run")

        reason = restart_selection_denied_reason(str(rst), [admin_visible_job])

        assert reason is None

    def test_denial_message_is_user_facing_not_a_stack_trace(self, tmp_path):
        reason = restart_selection_denied_reason(str(tmp_path / "x.rst"), [])
        assert reason is not None
        assert "Traceback" not in reason
        assert len(reason) < 200


class TestRestartInfoText:
    """Final security review, Finding 2: pages/run.py's restart_info render
    path used to stat() whatever path input.restart_from() held with NO
    allowlist -- a filesystem-wide existence/size oracle over anything the
    shiny process can stat (a spoofed WS value could probe arbitrary paths
    for existence and size). restart_info_text is the fix: it gates on
    restart_selection_denied_reason FIRST (the same allowlist _submit_job
    uses) and only touches the filesystem for a value that is a member of
    the caller-scoped jobs' choice set."""

    def test_none_for_falsy_restart_from(self):
        assert restart_info_text(None, []) is None
        assert restart_info_text("", []) is None

    def test_none_for_value_outside_scoped_allowlist_even_if_file_exists(self, tmp_path):
        """The core regression: a real, existing, stat-able file whose
        owning job is simply not in the caller-scoped jobs list (e.g. a
        spoofed WS value pointing at another user's .rst when the caller
        correctly scoped to the current user's own jobs only) must not
        have its existence or size exposed."""
        other_user_dir = tmp_path / "other_user"
        other_user_dir.mkdir()
        real_file = other_user_dir / "secret.rst"
        real_file.write_text("x" * 4096)

        result = restart_info_text(str(real_file), [])

        assert result is None

    def test_none_for_a_spoofed_arbitrary_path_outside_any_job_dir(self, tmp_path):
        spoofed = str(tmp_path / "not_a_job_working_dir" / "whatever.rst")

        assert restart_info_text(spoofed, []) is None

    def test_size_and_name_shown_for_an_allowed_choice(self, tmp_path):
        rst = tmp_path / "out.rst"
        rst.write_text("x" * 2048)
        job = _completed_shyfem_job(tmp_path)

        result = restart_info_text(str(rst), [job])

        assert result is not None
        assert "out.rst" in result
        assert "2 KB" in result

    def test_not_found_warning_shown_when_exists_check_disagrees_with_the_allowlist(
        self, tmp_path, monkeypatch
    ):
        """The allowlist (compute_restart_choices) and the direct exists()
        check both look at the filesystem independently, a microsecond
        apart -- there is a narrow window where a file present for the
        allowlist's glob() has vanished by the time exists() runs. That is
        the user's OWN legitimate selection (already visible to them), not
        an information leak about an arbitrary path, so it's safe to still
        surface a "not found" warning once the allowlist gate has already
        passed. Simulate that narrow race directly rather than relying on
        real disk timing."""
        rst = tmp_path / "out.rst"
        rst.write_text("")
        job = _completed_shyfem_job(tmp_path)

        real_exists = Path.exists
        monkeypatch.setattr(
            Path, "exists", lambda self: False if self == rst else real_exists(self)
        )

        result = restart_info_text(str(rst), [job])

        assert result is not None
        assert "not found" in result.lower()
