"""Ensemble / parameter sweep page - batch runs with varying parameters.

Features:
- Define parameter variations (single or multi-parameter sweeps)
- Batch submit jobs with parameter combinations
- Track ensemble progress as a group
- Aggregate results: mean, std, min/max envelope plots
"""

import itertools
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.job_status import format_datetime, format_duration, get_status_badge
from shyfem_ui.config import Config
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobQueueFactory, JobSpec, JobStatus
from shyfem_ui.services.parser_str import StrFile, StrParser

logger = logging.getLogger(__name__)


@module.ui
def ensemble_ui():
    """Ensemble / parameter sweep page UI."""
    return ui.div(
        ui.h3("Ensemble / Parameter Sweep"),
        ui.p(
            "Vary simulation parameters across multiple runs and compare results.",
            class_="text-muted",
        ),
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Base Configuration"),
                ui.input_text(
                    "base_str_file",
                    "Base STR File",
                    placeholder="/path/to/base.str",
                ),
                ui.input_text(
                    "working_dir",
                    "Working Directory",
                    placeholder="/path/to/ensemble_output",
                ),
                ui.input_text(
                    "ensemble_name",
                    "Ensemble Name",
                    placeholder="my_sweep",
                ),
                ui.input_select(
                    "tool_name",
                    "Tool",
                    choices={
                        "shyfem": "shyfem (Simulation)",
                        "shypre": "shypre (Grid Prep)",
                        "shyelab": "shyelab (Post-process)",
                    },
                ),
                ui.hr(),
                # MPI options
                ui.h6("MPI Options"),
                ui.input_checkbox("mpi_enabled", "Enable MPI", value=False),
                ui.panel_conditional(
                    "input.mpi_enabled",
                    ui.input_numeric("mpi_np", "Processes", value=4, min=2, max=128),
                ),
                ui.hr(),
                # Sweep mode
                ui.h6("Sweep Mode"),
                ui.input_radio_buttons(
                    "sweep_mode",
                    None,
                    choices={
                        "grid": "Grid (all combinations)",
                        "zip": "Zip (parallel variations)",
                    },
                    selected="grid",
                ),
                ui.hr(),
                ui.input_action_button(
                    "preview_btn",
                    "Preview Runs",
                    class_="btn-outline-primary btn-sm w-100 mb-2",
                ),
                ui.input_action_button(
                    "submit_btn",
                    "Submit Ensemble",
                    class_="btn-primary w-100",
                ),
                width=320,
            ),
            ui.navset_card_tab(
                ui.nav_panel(
                    "Parameters",
                    ui.output_ui("param_editor"),
                ),
                ui.nav_panel(
                    "Preview",
                    ui.output_ui("run_preview"),
                ),
                ui.nav_panel(
                    "Progress",
                    ui.output_ui("ensemble_progress"),
                ),
                ui.nav_panel(
                    "Results",
                    output_widget("results_plot"),
                ),
                ui.nav_panel(
                    "Summary",
                    ui.output_ui("ensemble_summary"),
                ),
            ),
        ),
    )


@module.server
def ensemble_server(
    input,
    output,
    session,
    config: Config,
    job_queue: JobQueue | None = None,
    active_project=None,
):
    """Ensemble page server logic."""
    if job_queue is None:
        queue_mode = "celery" if config.use_celery else "local"
        job_queue = JobQueueFactory.create(
            mode=queue_mode,
            shyfem_dir=config.shyfem_dir,
            max_workers=config.max_workers,
            redis_url=config.redis_url if config.use_celery else None,
        )

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("working_dir", value=str(Path(proj["work_dir"]) / "ensemble"))
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                ui.update_text("base_str_file", value=str(Path(proj["work_dir"]) / sim["str_file"]))

    # State
    param_variations = reactive.value(
        [
            {"section": "para", "param": "", "values": ""},
        ]
    )
    preview_runs = reactive.value([])
    ensemble_state = reactive.value(None)  # {id, name, job_ids, submitted_at}
    ensemble_jobs = reactive.value([])

    # ------- Parameter Editor -------

    @render.ui
    def param_editor():
        variations = param_variations.get()

        rows = []
        for i, var in enumerate(variations):
            rows.append(
                ui.div(
                    ui.div(
                        ui.input_text(
                            f"var_section_{i}",
                            "Section",
                            value=var["section"],
                            width="100%",
                        ),
                        class_="col-3",
                    ),
                    ui.div(
                        ui.input_text(
                            f"var_param_{i}",
                            "Parameter",
                            value=var["param"],
                            width="100%",
                        ),
                        class_="col-3",
                    ),
                    ui.div(
                        ui.input_text(
                            f"var_values_{i}",
                            "Values (comma-separated)",
                            value=var["values"],
                            width="100%",
                        ),
                        class_="col-5",
                    ),
                    ui.div(
                        (
                            ui.input_action_button(
                                f"remove_var_{i}",
                                "X",
                                class_="btn-sm btn-outline-danger mt-4",
                            )
                            if i > 0
                            else None
                        ),
                        class_="col-1",
                    ),
                    class_="row mb-2",
                )
            )

        return ui.div(
            ui.h5("Parameter Variations"),
            ui.p(
                "Specify which parameters to vary and their values. "
                "Use comma-separated values (e.g., 0.01, 0.02, 0.05).",
                class_="text-muted small",
            ),
            *rows,
            ui.div(
                ui.input_action_button(
                    "add_var_btn",
                    "+ Add Parameter",
                    class_="btn-sm btn-outline-secondary",
                ),
                class_="mt-2",
            ),
            ui.hr(),
            ui.h6("Quick Presets"),
            ui.div(
                ui.input_action_button(
                    "preset_friction",
                    "Friction Sweep",
                    class_="btn-sm btn-outline-info me-2",
                ),
                ui.input_action_button(
                    "preset_timestep",
                    "Timestep Sensitivity",
                    class_="btn-sm btn-outline-info me-2",
                ),
                ui.input_action_button(
                    "preset_viscosity",
                    "Viscosity Sweep",
                    class_="btn-sm btn-outline-info",
                ),
                class_="d-flex flex-wrap gap-1",
            ),
        )

    @reactive.effect
    @reactive.event(input.add_var_btn)
    def _add_variation():
        current = param_variations.get()
        updated = list(current) + [{"section": "para", "param": "", "values": ""}]
        param_variations.set(updated)

    # Dynamic remove handlers for remove_var_{i} buttons
    @reactive.effect
    def _register_remove_var_handlers():
        variations = param_variations.get()
        for i in range(1, len(variations)):  # i=0 has no remove button
            _make_remove_var(i)

    def _make_remove_var(index: int):
        @reactive.effect
        @reactive.event(input[f"remove_var_{index}"])
        def _remove():
            current = list(param_variations.get())
            if index < len(current):
                current.pop(index)
                param_variations.set(current)

    @reactive.effect
    @reactive.event(input.preset_friction)
    def _preset_friction():
        param_variations.set(
            [
                {"section": "para", "param": "czdef", "values": "0.02, 0.025, 0.03, 0.035, 0.04"},
            ]
        )

    @reactive.effect
    @reactive.event(input.preset_timestep)
    def _preset_timestep():
        param_variations.set(
            [
                {"section": "para", "param": "idt", "values": "10, 30, 60, 120, 300"},
            ]
        )

    @reactive.effect
    @reactive.event(input.preset_viscosity)
    def _preset_viscosity():
        param_variations.set(
            [
                {"section": "para", "param": "ahpar", "values": "1, 5, 10, 50, 100"},
                {"section": "para", "param": "dhpar", "values": "1, 5, 10, 50, 100"},
            ]
        )

    def _read_current_variations() -> list[dict]:
        """Read the current variation values from the dynamic inputs."""
        variations = param_variations.get()
        result = []
        for i, var in enumerate(variations):
            try:
                section = input[f"var_section_{i}"]()
            except Exception:
                logger.debug("Form field var_section_%d unavailable, using cached value", i)
                section = var["section"]
            try:
                param = input[f"var_param_{i}"]()
            except Exception:
                logger.debug("Form field var_param_%d unavailable, using cached value", i)
                param = var["param"]
            try:
                values_str = input[f"var_values_{i}"]()
            except Exception:
                logger.debug("Form field var_values_%d unavailable, using cached value", i)
                values_str = var["values"]

            if param and values_str:
                values = [v.strip() for v in values_str.split(",") if v.strip()]
                if values:
                    result.append(
                        {
                            "section": section or "para",
                            "param": param,
                            "values": values,
                        }
                    )
        return result

    def _build_combinations(variations: list[dict], mode: str) -> list[dict]:
        """Build parameter combinations from variations.

        Returns list of dicts, each mapping (section, param) -> value.
        """
        if not variations:
            return []

        if mode == "zip":
            # Parallel: zip all value lists (truncated to shortest)
            min_len = min(len(v["values"]) for v in variations)
            runs = []
            for i in range(min_len):
                combo = {}
                for var in variations:
                    combo[(var["section"], var["param"])] = var["values"][i]
                runs.append(combo)
            return runs
        else:
            # Grid: all combinations (cartesian product)
            keys = [(v["section"], v["param"]) for v in variations]
            value_lists = [v["values"] for v in variations]
            runs = []
            for combo_values in itertools.product(*value_lists):
                combo = dict(zip(keys, combo_values, strict=True))
                runs.append(combo)
            return runs

    # ------- Preview -------

    @reactive.effect
    @reactive.event(input.preview_btn)
    def _preview():
        variations = _read_current_variations()
        if not variations:
            ui.notification_show("Define at least one parameter variation", type="warning")
            preview_runs.set([])
            return

        mode = input.sweep_mode()
        combos = _build_combinations(variations, mode)

        if not combos:
            ui.notification_show("No valid parameter combinations", type="warning")
            preview_runs.set([])
            return

        if len(combos) > 200:
            ui.notification_show(
                f"Warning: {len(combos)} runs. Consider reducing parameters.",
                type="warning",
            )

        preview_runs.set(combos)
        ui.notification_show(f"{len(combos)} runs configured", type="message")

    @render.ui
    def run_preview():
        runs = preview_runs.get()
        if not runs:
            return ui.p(
                "Click 'Preview Runs' to see the parameter combinations.",
                class_="text-muted text-center mt-3",
            )

        # Build preview table
        if not runs:
            return ui.p("No runs to preview", class_="text-muted")

        # Get all parameter keys
        all_keys = []
        seen = set()
        for run in runs:
            for key in run:
                if key not in seen:
                    all_keys.append(key)
                    seen.add(key)

        header_cells = [ui.tags.th("#")]
        for section, param in all_keys:
            header_cells.append(
                ui.tags.th(
                    ui.div(
                        ui.code(param),
                        ui.br(),
                        ui.span(f"${section}", class_="text-muted small"),
                    )
                )
            )

        rows = []
        for i, run in enumerate(runs[:50]):  # Show max 50
            cells = [ui.tags.td(str(i + 1))]
            for key in all_keys:
                val = run.get(key, "-")
                cells.append(ui.tags.td(val))
            rows.append(ui.tags.tr(*cells))

        truncation_note = None
        if len(runs) > 50:
            truncation_note = ui.p(
                f"Showing 50 of {len(runs)} runs",
                class_="text-muted small text-center",
            )

        return ui.div(
            ui.p(
                f"{len(runs)} runs total | Mode: {input.sweep_mode()}",
                class_="fw-bold",
            ),
            ui.tags.table(
                ui.tags.thead(ui.tags.tr(*header_cells)),
                ui.tags.tbody(*rows),
                class_="table table-sm table-bordered table-hover",
            ),
            truncation_note,
        )

    # ------- Submit -------

    @reactive.effect
    @reactive.event(input.submit_btn)
    async def _submit_ensemble():
        base_str_path = input.base_str_file()
        working_dir_path = input.working_dir()
        name = input.ensemble_name() or f"ensemble_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if not base_str_path:
            ui.notification_show("Base STR file is required", type="error")
            return

        try:
            base_file = config.validate_path(base_str_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        if not working_dir_path:
            working_dir_path = str(base_file.parent / name)

        try:
            work_dir = config.validate_path(working_dir_path)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return

        variations = _read_current_variations()
        if not variations:
            ui.notification_show("Define at least one parameter variation", type="error")
            return

        mode = input.sweep_mode()
        combos = _build_combinations(variations, mode)
        if not combos:
            ui.notification_show("No valid parameter combinations", type="error")
            return

        # Parse the base STR file
        try:
            base_str = StrParser.parse_file(base_file)
        except Exception as e:
            ui.notification_show(f"Failed to parse STR file: {e}", type="error")
            return

        tool = input.tool_name()
        mpi_enabled = input.mpi_enabled() if tool == "shyfem" else False
        mpi_np = input.mpi_np() if (tool == "shyfem" and mpi_enabled) else 1

        ensemble_id = str(uuid.uuid4())[:8]
        job_ids = []

        work_dir_path = Path(work_dir)
        work_dir_path.mkdir(parents=True, exist_ok=True)

        for i, combo in enumerate(combos):
            # Create a modified STR file for this run
            modified_str = _apply_param_combo(base_str, combo)

            # Create run subdirectory
            run_label = _combo_label(combo, i)
            run_dir = work_dir_path / run_label
            run_dir.mkdir(parents=True, exist_ok=True)

            # Save modified STR file
            str_filename = base_file.name
            run_str_path = run_dir / str_filename
            StrParser.save(modified_str, run_str_path)

            # Submit job
            spec = JobSpec(
                name=f"{name}/{run_label}",
                tool_name=tool,
                args=[str(run_str_path)],
                working_dir=run_dir,
                mpi_enabled=mpi_enabled,
                mpi_np=mpi_np,
                metadata={
                    "ensemble_id": ensemble_id,
                    "ensemble_name": name,
                    "run_index": i,
                    "param_combo": {f"{s}.{p}": v for (s, p), v in combo.items()},
                },
            )

            try:
                job_id = await job_queue.submit(spec)
                job_ids.append(job_id)
            except Exception as e:
                ui.notification_show(f"Failed to submit run {i}: {e}", type="error")

        if job_ids:
            ensemble_state.set(
                {
                    "id": ensemble_id,
                    "name": name,
                    "job_ids": job_ids,
                    "submitted_at": datetime.now(),
                    "total": len(combos),
                    "combos": combos,
                }
            )
            ui.notification_show(
                f"Submitted {len(job_ids)}/{len(combos)} ensemble runs",
                type="message",
            )

    # ------- Progress Tracking -------

    @reactive.effect
    async def _poll_ensemble():
        state = ensemble_state.get()
        if not state:
            return

        try:
            jobs = []
            any_active = False
            for jid in state["job_ids"]:
                info = await job_queue.get_status(jid)
                if info:
                    jobs.append(info)
                    if info.is_active:
                        any_active = True

            ensemble_jobs.set(jobs)

            if any_active:
                reactive.invalidate_later(3)
        except Exception:
            logger.debug("Ensemble status poll failed, retrying in 5s", exc_info=True)
            reactive.invalidate_later(5)

    @reactive.effect
    @reactive.event(input.stop_all_btn)
    async def _stop_all_ensemble():
        state = ensemble_state.get()
        if not state:
            return
        cancelled = await _cancel_jobs(job_queue, state["job_ids"])
        total = len(state["job_ids"])
        ui.notification_show(
            f"Cancelled {cancelled} of {total} jobs",
            type="message" if cancelled > 0 else "warning",
        )

    @render.ui
    def ensemble_progress():
        state = ensemble_state.get()
        if not state:
            return ui.p(
                "Submit an ensemble to track progress.",
                class_="text-muted text-center mt-3",
            )

        jobs = ensemble_jobs.get()
        total = state["total"]

        # Count statuses
        completed = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        running = sum(1 for j in jobs if j.status == JobStatus.RUNNING)
        queued = sum(1 for j in jobs if j.status in (JobStatus.PENDING, JobStatus.QUEUED))

        overall_pct = int((completed + failed) / total * 100) if total > 0 else 0

        # Build progress display
        status_bar = ui.div(
            ui.div(
                ui.div(
                    f"{overall_pct}% ({completed + failed}/{total})",
                    class_="progress-bar" + (" bg-success" if failed == 0 else " bg-warning"),
                    style=f"width: {max(overall_pct, 2)}%",
                    role="progressbar",
                ),
                class_="progress mb-3",
                style="height: 25px;",
            ),
        )

        stat_badges = ui.div(
            _badge(f"Completed: {completed}", "bg-success"),
            _badge(f"Failed: {failed}", "bg-danger") if failed > 0 else None,
            _badge(f"Running: {running}", "bg-primary") if running > 0 else None,
            _badge(f"Queued: {queued}", "bg-info") if queued > 0 else None,
            _badge(f"Total: {total}", "bg-secondary"),
            class_="d-flex gap-2 mb-3",
        )

        stop_btn = (
            ui.input_action_button(
                "stop_all_btn",
                "Stop All Jobs",
                class_="btn-danger btn-sm mb-3",
            )
            if running > 0 or queued > 0
            else None
        )

        # Per-run rows
        rows = []
        for j in jobs:
            combo_str = ""
            param_combo = j.metadata.get("param_combo", {})
            if param_combo:
                parts = [f"{k}={v}" for k, v in param_combo.items()]
                combo_str = ", ".join(parts)

            rows.append(
                ui.tags.tr(
                    ui.tags.td(str(j.metadata.get("run_index", "?")), class_="text-center"),
                    ui.tags.td(get_status_badge(j.status)),
                    ui.tags.td(f"{int(j.progress * 100)}%"),
                    ui.tags.td(ui.code(combo_str, class_="small") if combo_str else "-"),
                    ui.tags.td(format_duration(j.duration) if j.duration else "-"),
                    ui.tags.td(
                        ui.span(
                            (
                                j.error_message[:60] + "..."
                                if j.error_message and len(j.error_message) > 60
                                else j.error_message or ""
                            ),
                            class_="text-danger small",
                        )
                        if j.error_message
                        else "-"
                    ),
                )
            )

        job_table = ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("#", style="width: 40px;"),
                    ui.tags.th("Status"),
                    ui.tags.th("Progress"),
                    ui.tags.th("Parameters"),
                    ui.tags.th("Duration"),
                    ui.tags.th("Error"),
                ),
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered table-hover",
        )

        return ui.div(
            ui.h5(f"Ensemble: {state['name']}"),
            ui.p(
                f"ID: {state['id']} | Submitted: {format_datetime(state['submitted_at'])}",
                class_="text-muted small",
            ),
            status_bar,
            stat_badges,
            stop_btn,
            job_table,
        )

    # ------- Results -------

    @render_widget
    def results_plot():
        state = ensemble_state.get()
        jobs = ensemble_jobs.get()

        if not state or not jobs:
            fig = go.Figure()
            fig.add_annotation(
                text="Submit an ensemble and wait for results",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=16,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        completed_jobs = [j for j in jobs if j.status == JobStatus.COMPLETED]
        if not completed_jobs:
            fig = go.Figure()
            fig.add_annotation(
                text="Waiting for completed runs...",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=16,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        # Try to load time series from each completed run
        run_data = []
        for j in completed_jobs:
            ts_files = [f for f in j.output_files if f.endswith((".ts", ".ext", ".csv"))]
            if ts_files:
                data = _load_ts(Path(ts_files[0]))
                if data:
                    combo = j.metadata.get("param_combo", {})
                    label = ", ".join(f"{k}={v}" for k, v in combo.items()) or j.name
                    run_data.append({"data": data, "label": label, "job": j})

        if not run_data:
            # Fall back to duration comparison bar chart
            return _build_duration_chart(completed_jobs)

        # Build overlaid time series + envelope
        return _build_ensemble_ts_plot(run_data)

    @render.ui
    def ensemble_summary():
        state = ensemble_state.get()
        jobs = ensemble_jobs.get()

        if not state or not jobs:
            return ui.p(
                "Submit an ensemble to see a summary.",
                class_="text-muted text-center mt-3",
            )

        completed = [j for j in jobs if j.status == JobStatus.COMPLETED]
        failed = [j for j in jobs if j.status == JobStatus.FAILED]

        parts = [
            ui.h5(f"Ensemble: {state['name']}"),
            ui.p(f"{len(completed)} completed, {len(failed)} failed out of {state['total']} runs"),
        ]

        # Duration statistics
        durations = [j.duration for j in completed if j.duration is not None]
        if durations:
            avg_dur = sum(durations) / len(durations)
            min_dur = min(durations)
            max_dur = max(durations)
            parts.append(ui.hr())
            parts.append(ui.h6("Runtime Statistics"))
            parts.append(
                ui.tags.table(
                    ui.tags.tbody(
                        ui.tags.tr(ui.tags.th("Average"), ui.tags.td(format_duration(avg_dur))),
                        ui.tags.tr(ui.tags.th("Fastest"), ui.tags.td(format_duration(min_dur))),
                        ui.tags.tr(ui.tags.th("Slowest"), ui.tags.td(format_duration(max_dur))),
                        ui.tags.tr(
                            ui.tags.th("Speedup Range"),
                            ui.tags.td(f"{max_dur / min_dur:.1f}x" if min_dur > 0 else "-"),
                        ),
                    ),
                    class_="table table-sm table-bordered",
                )
            )

        # Failed runs info
        if failed:
            parts.append(ui.hr())
            parts.append(ui.h6("Failed Runs"))
            for j in failed:
                combo = j.metadata.get("param_combo", {})
                combo_str = ", ".join(f"{k}={v}" for k, v in combo.items()) or "?"
                parts.append(
                    ui.div(
                        ui.span(f"Run {j.metadata.get('run_index', '?')}: ", class_="fw-bold"),
                        ui.code(combo_str),
                        ui.br(),
                        ui.span(j.error_message or "Unknown error", class_="text-danger small"),
                        class_="mb-2",
                    )
                )

        return ui.div(*parts)

    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_param_combo(base_str: StrFile, combo: dict) -> StrFile:
    """Apply a parameter combination to a copy of the base STR file.

    Creates a deep-enough copy so the original is not modified.
    """
    # Re-generate and re-parse to get a clean copy
    content = StrParser.generate(base_str)
    modified = StrParser.parse(content)
    modified.file_path = base_str.file_path

    for (section, param), value in combo.items():
        modified.set_param(section, param, _try_convert(value))

    return modified


def _try_convert(value: str) -> Any:
    """Try to convert a string value to int or float."""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        logger.debug("Value '%s' is not numeric, keeping as string", value)
    return value


def _combo_label(combo: dict, index: int) -> str:
    """Generate a short label for a parameter combination."""
    if not combo:
        return f"run_{index:03d}"

    parts = []
    for (_section, param), value in combo.items():
        # Shorten: use param name + value
        parts.append(f"{param}_{value}")

    label = "_".join(parts)
    # Sanitize for directory name
    label = label.replace(".", "p").replace("-", "m").replace(" ", "_")
    if len(label) > 60:
        label = label[:57] + f"_{index:03d}"
    return label


def _badge(text: str, bg_class: str) -> ui.Tag:
    """Create a small badge."""
    return ui.span(text, class_=f"badge {bg_class}")


async def _cancel_jobs(job_queue: JobQueue, job_ids: list[str]) -> int:
    """Cancel multiple jobs, returning count of successful cancellations."""
    cancelled = 0
    for job_id in job_ids:
        try:
            if await job_queue.cancel(job_id):
                cancelled += 1
        except Exception:
            logger.debug("Failed to cancel job %s", job_id, exc_info=True)
    return cancelled


def _load_ts(path: Path) -> list[list[float]]:
    """Load time series data as list of float rows."""
    if not path.exists():
        return []
    data = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                try:
                    data.append([float(p) for p in parts])
                except ValueError:
                    continue
    except Exception:
        logger.warning("Failed to load time series from %s", path, exc_info=True)
        return []
    return data


def _build_duration_chart(jobs: list[JobInfo]) -> go.Figure:
    """Build a bar chart comparing run durations."""
    fig = go.Figure()

    labels = []
    durations = []
    colors = []
    for j in jobs:
        combo = j.metadata.get("param_combo", {})
        label = ", ".join(f"{v}" for v in combo.values()) or j.name
        labels.append(label)
        durations.append(j.duration or 0)
        colors.append("#198754" if j.status == JobStatus.COMPLETED else "#dc3545")

    fig.add_trace(
        go.Bar(
            x=labels,
            y=durations,
            marker_color=colors,
            text=[format_duration(d) for d in durations],
            textposition="outside",
        )
    )

    fig.update_layout(
        title="Run Duration Comparison",
        xaxis_title="Parameter Values",
        yaxis_title="Duration (seconds)",
        height=500,
        showlegend=False,
    )
    return fig


def _build_ensemble_ts_plot(run_data: list[dict]) -> go.Figure:
    """Build overlaid time series with envelope (min/max shading)."""
    fig = go.Figure()

    # Plot individual runs
    for rd in run_data:
        data = rd["data"]
        if not data or len(data[0]) < 2:
            continue

        x = [row[0] for row in data]
        y = [row[1] for row in data]

        fig.add_trace(
            go.Scattergl(
                x=x,
                y=y,
                mode="lines",
                name=rd["label"],
                line=dict(width=1),
                opacity=0.7,
            )
        )

    # Compute and plot envelope if multiple runs with same time axis
    if len(run_data) >= 2:
        try:
            # Use the first run's x-axis as reference
            ref_x = [row[0] for row in run_data[0]["data"]]
            all_y = []
            for rd in run_data:
                y = [row[1] for row in rd["data"]]
                if len(y) == len(ref_x):
                    all_y.append(y)

            if len(all_y) >= 2:
                y_min = [min(vals) for vals in zip(*all_y, strict=True)]
                y_max = [max(vals) for vals in zip(*all_y, strict=True)]
                y_mean = [sum(vals) / len(vals) for vals in zip(*all_y, strict=True)]

                # Envelope shading
                fig.add_trace(
                    go.Scatter(
                        x=ref_x + ref_x[::-1],
                        y=y_max + y_min[::-1],
                        fill="toself",
                        fillcolor="rgba(100,100,200,0.15)",
                        line=dict(width=0),
                        name="Min/Max Envelope",
                        showlegend=True,
                        hoverinfo="skip",
                    )
                )

                # Mean line
                fig.add_trace(
                    go.Scattergl(
                        x=ref_x,
                        y=y_mean,
                        mode="lines",
                        name="Ensemble Mean",
                        line=dict(color="black", width=2, dash="dash"),
                    )
                )
        except Exception:
            logger.warning("Ensemble envelope computation failed", exc_info=True)

    fig.update_layout(
        title="Ensemble Time Series",
        xaxis_title="Time",
        yaxis_title="Value",
        height=500,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(rangeslider_visible=True)
    return fig
