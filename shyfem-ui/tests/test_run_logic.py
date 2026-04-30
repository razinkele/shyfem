"""Tests for build_job_spec — the new pure helper extracted from
_submit_job's inline JobSpec assembly. The 6 already-pure helpers
(detect_mesh_node_count, get_solver_recommendation, etc.) are covered
by their existing test files (test_run_helpers, test_run_validation,
test_job_ownership)."""
from pathlib import Path

import pytest

from shyfem_ui.services.run_logic import build_job_spec
from shyfem_ui.services.job_queue import JobSpec


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
        spec = build_job_spec(**self._base_args(
            tool_name="shyfem", mpi_enabled=True, mpi_np=4,
        ))
        assert spec.mpi_enabled is True
        assert spec.mpi_np == 4

    def test_mpi_disabled_for_non_shyfem(self):
        # mpi_enabled is suppressed when tool != shyfem
        spec = build_job_spec(**self._base_args(
            tool_name="shyelab", mpi_enabled=True, mpi_np=4,
        ))
        assert spec.mpi_enabled is False
        assert spec.mpi_np == 1

    def test_mpi_np_default_is_1(self):
        spec = build_job_spec(**self._base_args(
            tool_name="shyfem", mpi_enabled=False,
        ))
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
