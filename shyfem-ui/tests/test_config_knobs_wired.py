"""P3 of the 2026-06-08 unwired audit: dead config knobs honored or removed.

- mpi_default_np: now the default for the run-page MPI inputs (was hardcoded 4).
- mpirun_path: now passed to the MPI wrappers (was the literal "mpirun").
- theme: removed (dead; theming is via data-bs-theme + plotly_theme.py).
"""

import inspect


def test_run_page_uses_configured_mpi_default_np():
    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    # the server-side MPI process count input defaults from config
    # (wf_mpi_np lives in the static run_ui, which has no config in scope)
    assert "value=config.mpi_default_np" in src


def test_job_queues_use_configured_mpirun_path():
    from shyfem_ui.services import job_celery, job_local

    for mod in (job_local, job_celery):
        src = inspect.getsource(mod)
        assert "get_config().mpirun_path" in src, f"{mod.__name__} ignores config.mpirun_path"
        assert 'mpirun_path="mpirun"' not in src, f"{mod.__name__} still hardcodes mpirun"


def test_theme_field_removed():
    from shyfem_ui.config import Config

    assert "theme" not in Config.model_fields
