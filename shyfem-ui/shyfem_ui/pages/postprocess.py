"""Post-processing page - full shyelab interface.

Features:
- All shyelab operation modes via GUI (extract, convert, statistics, split, info)
- Variable and layer selection from scanned file metadata
- Time range filtering
- Batch post-processing of multiple .shy files
- Output file browser with size, type, and quick actions
- Operation presets for common workflows
"""

import asyncio
import logging
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.next_step_card import NextStepLink, next_step_card
from shyfem_ui.components.project_select import project_dir_select, project_file_select
from shyfem_ui.components.sample_data import sample_data_card_ui
from shyfem_ui.components.timeseries import timeseries_server, timeseries_ui
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.postprocess_logic import (
    build_shyelab_options,
    discover_shy_files,
    format_size,
    parse_shyelab_info,
    preview_series_file,
    run_shyelab_and_name,
)
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
from shyfem_ui.services.timeseries_loader import load_timeseries

logger = logging.getLogger(__name__)

# Shyelab operation modes and their CLI flags
SHYELAB_OPERATIONS = {
    # Real shyelab options only (elabutil.f90 clo_add_option; `shyelab -h`).
    # -aver/-min/-max/-2d write a file only with -out, always named out.shy;
    # name_outputs() renames it after the input and the operation.
    "info": {
        "label": "File Info",
        "flags": ["-info"],
        "description": "Display file metadata, variables, layers, and time range",
    },
    "extract_ts": {
        "label": "Extract Time Series",
        "flags": ["-node"],
        "description": "Time series at the given nodes (one text file per variable and node)",
    },
    "extract_nc": {
        "label": "Convert to NetCDF",
        "flags": ["-outformat", "nc"],
        "description": "Convert .shy binary to NetCDF format",
    },
    "split_vars": {
        "label": "Split by Variable",
        "flags": ["-split"],
        "description": "Split output into separate files per variable",
    },
    "spatial_avg": {
        "label": "Basin Average",
        "flags": ["-averbas"],
        "description": "Average over the whole basin: one time series per variable",
    },
    "temporal_avg": {
        "label": "Time Average",
        "flags": ["-aver", "-out"],
        "description": "Average over all records at each node",
    },
    "time_min": {
        "label": "Minimum over Time",
        "flags": ["-min", "-out"],
        "description": "Minimum over all records at each node",
    },
    "time_max": {
        "label": "Maximum over Time",
        "flags": ["-max", "-out"],
        "description": "Maximum over all records at each node",
    },
    "residual": {
        "label": "Residual Currents",
        "flags": ["-aver", "-out"],
        "description": "Time-averaged currents: run on a .hydro.shy file",
    },
    "custom": {
        "label": "Custom Options",
        "flags": [],
        "description": "Specify custom shyelab command-line options",
    },
}

# Preset workflows: ordered sequences of operations
PRESETS = {
    "quick_extract": {
        "name": "Quick Extract (TS + NetCDF)",
        "description": "Extract time series and convert to NetCDF",
        "operations": ["extract_ts", "extract_nc"],
    },
    "full_analysis": {
        "name": "Full Analysis",
        "description": "Info, split by variable, time average, min and max over time",
        "operations": ["info", "split_vars", "temporal_avg", "time_min", "time_max"],
    },
    "netcdf_split": {
        "name": "NetCDF + Split",
        "description": "Convert to NetCDF with variable splitting",
        "operations": ["extract_nc", "split_vars"],
    },
}


@module.ui
def postprocess_ui() -> ui.Tag:
    """Post-processing page UI."""
    return ui.div(
        ui.h3("Post-Processing"),
        ui.p("Process SHYFEM output files using shyelab.", class_="text-muted"),
        sample_data_card_ui("postprocess"),
        # Next-step card shown after batch or single-run completion
        ui.output_ui("next_step_html_out"),
        ui.layout_sidebar(
            ui.sidebar(
                # Input files
                ui.h5("Input"),
                ui.output_ui("shy_path_picker"),
                ui.input_action_button(
                    "scan_btn",
                    "Scan File",
                    class_="btn-outline-primary btn-sm w-100 mb-2",
                ),
                ui.hr(),
                # Operation selection
                ui.h5("Operation"),
                ui.input_select(
                    "operation",
                    "Mode",
                    choices={k: v["label"] for k, v in SHYELAB_OPERATIONS.items()},
                    selected="extract_nc",
                ),
                ui.output_ui("operation_description"),
                ui.hr(),
                # Variable/layer selection (populated after scan)
                ui.h5("Filters"),
                ui.input_text(
                    "ts_nodes",
                    "Nodes (Extract Time Series)",
                    placeholder="e.g. 1823,1657 (external node numbers)",
                ),
                # Time range
                ui.input_text("tmin", "Start Time", placeholder="0 or 2020-01-01"),
                ui.input_text("tmax", "End Time", placeholder="86400 or 2020-01-02"),
                ui.hr(),
                # Output options
                ui.h5("Output"),
                ui.output_ui("output_dir_picker"),
                ui.output_ui("custom_options_field"),
                ui.hr(),
                # Actions
                ui.input_action_button(
                    "run_btn",
                    "Run shyelab",
                    class_="btn-primary w-100 mb-2",
                ),
                ui.hr(),
                # Presets
                ui.h5("Quick Presets"),
                ui.output_ui("preset_buttons"),
                # Batch mode
                ui.hr(),
                ui.h5("Batch Mode"),
                ui.output_ui("batch_paths_picker"),
                ui.input_action_button(
                    "batch_run_btn",
                    "Batch Process All",
                    class_="btn-outline-primary w-100",
                ),
                # Batch convert to NetCDF
                ui.hr(),
                ui.h5("Batch Convert to NetCDF"),
                ui.output_ui("shy_file_list"),
                ui.input_action_button(
                    "batch_convert_btn",
                    "Convert Selected to NetCDF",
                    class_="btn-outline-primary w-100 mt-2",
                ),
                width=320,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "File Info",
                    ui.output_ui("file_info"),
                ),
                ui.nav_panel(
                    "Output Files",
                    ui.output_ui("output_files"),
                ),
                ui.nav_panel(
                    "Batch Progress",
                    ui.output_ui("batch_progress"),
                ),
                ui.nav_panel(
                    "Time Series Preview",
                    timeseries_ui("ts_preview"),
                ),
                ui.nav_panel(
                    "Log",
                    log_viewer_ui("command_log"),
                ),
            ),
        ),
    )


@module.server
def postprocess_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
    current_user=None,
    project_files_rev=None,
) -> None:
    """Post-processing page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # Tracks the last-seen project id so _on_project_changed can
    # distinguish "metadata refresh of same project" (preserve user
    # input) from "user switched to different project" (force re-fill).
    last_project_id: reactive.Value[int | None] = reactive.value(None)

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            last_project_id.set(None)
            return
        last_project_id.set(proj.get("id"))

    def _ctx():
        proj = active_project.get() if active_project is not None else None
        usr = current_user() if current_user is not None else None
        return proj, usr

    def _files_rev():
        """Depend on finished runs so a picker lists the files they wrote."""
        return project_files_rev.get() if project_files_rev is not None else 0

    def _kept(input_id: str):
        """The picker's current value, kept across a rebuild."""
        with reactive.isolate():
            try:
                return getattr(input, input_id)()
            except Exception:
                return None

    @render.ui
    def shy_path_picker():
        """Dropdown of ``.shy``/``.nc`` output files from the project directory
        and every box-model run directory — no free-text path box."""
        proj, usr = _ctx()
        _files_rev()
        return project_file_select(
            "shy_path",
            "Output File (.shy/.nc)",
            (".shy", ".nc"),
            proj=proj,
            user=usr,
            config=config,
            selected=_kept("shy_path"),
            include_runs=True,
        )

    @render.ui
    def batch_paths_picker():
        """Multi-select of ``.shy``/``.nc`` files (project + run dirs) for
        batch processing; ``input.batch_paths()`` is a tuple of paths."""
        proj, usr = _ctx()
        _files_rev()
        return project_file_select(
            "batch_paths",
            "Files to process",
            (".shy", ".nc"),
            proj=proj,
            user=usr,
            config=config,
            selected=_kept("batch_paths"),
            include_runs=True,
            multiple=True,
        )

    @render.ui
    def output_dir_picker():
        proj, usr = _ctx()
        return project_dir_select(
            "output_dir",
            "Output Directory",
            proj=proj,
            user=usr,
            config=config,
            default_label="— same directory as the input file —",
        )

    # Auto-fill from tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Post-Process":
            return
        # No path box any more; the user picks an output from the dropdown.
        tutorial_context.set(None)

    # Load sample data handler
    @reactive.effect
    @reactive.event(input.load_sample_btn)
    def _load_sample_data():
        work_dir = config.testcases_dir / "mar_menor"
        if not work_dir.exists():
            ui.notification_show(
                f"Sample directory not found: {work_dir}", type="error", duration=6
            )
            return
        ui.notification_show(
            "Sample directory set. Run a simulation first to generate "
            ".shy output, then click Scan.",
            type="message",
            duration=4,
        )

    # State
    log_content = reactive.value("")
    file_info_data = reactive.value(None)
    generated_files = reactive.value([])
    scanned_variables = reactive.value([])
    scanned_layers = reactive.value([])
    batch_results = reactive.value([])
    next_step_html = reactive.value(None)

    # Time series preview data
    ts_preview_data = reactive.value(None)

    # Initialize log viewer
    log_viewer_server("command_log", log_content)

    # Initialize timeseries preview component
    timeseries_server(
        "ts_preview",
        ts_preview_data,
        config=config,
        current_user=current_user,
        active_project=active_project,
    )

    @render.ui
    def next_step_html_out():
        """Render the contextual next-step card after shyelab run, or nothing."""
        return next_step_html.get() or ui.span()

    @reactive.effect
    def _reset_next_step_on_project_change():
        """Clear the next-step card when the active project changes."""
        if active_project is not None:
            active_project.get()  # establishes reactive dependency
        next_step_html.set(None)

    @render.ui
    def operation_description():
        op = input.operation()
        info = SHYELAB_OPERATIONS.get(op, {})
        return ui.p(info.get("description", ""), class_="text-muted small")

    @render.ui
    def custom_options_field():
        if input.operation() != "custom":
            return ui.span()
        return ui.input_text(
            "custom_options",
            "Custom CLI Options",
            placeholder="-split -outformat nc -tmin 0",
        )

    @render.ui
    def preset_buttons():
        return ui.div(
            *[
                ui.input_action_button(
                    f"preset_{key}",
                    preset["name"],
                    class_="btn-sm btn-outline-info w-100 mb-1",
                )
                for key, preset in PRESETS.items()
            ],
        )

    # --- Scan file ---

    @reactive.effect
    @reactive.event(input.scan_btn)
    async def _scan_file():
        _usr = current_user() if current_user is not None else None
        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("No file specified", type="warning")
            return

        try:
            path = config.confine_path(shy_path, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        log_content.set(f"Scanning {path.name}...\n")

        try:
            result = await wrapper.run_command(
                "shyelab",
                ["-info", str(path)],
                path.parent,
            )

            if result.success:
                info = parse_shyelab_info(result.stdout)
                file_info_data.set(info)

                # Extract variables and layers from info
                var_names = info.get("Variable Names", "")
                if var_names:
                    scanned_variables.set([v.strip() for v in var_names.split(",") if v.strip()])

                layer_str = info.get("Layer Depths", "")
                if layer_str:
                    scanned_layers.set([d.strip() for d in layer_str.split(",") if d.strip()])

                log_content.set(
                    f"=== STDOUT ===\n{result.stdout}\n\n"
                    f"=== STDERR ===\n{result.stderr}\n\n"
                    f"*** Scan complete ***\n"
                )
                ui.notification_show("File scanned successfully", type="message", duration=4)
            else:
                log_content.set(
                    f"=== STDOUT ===\n{result.stdout}\n\n"
                    f"=== STDERR ===\n{result.stderr}\n\n"
                    f"*** shyelab -info failed (code {result.return_code}) ***\n"
                )
                ui.notification_show("Scan failed - check log", type="error", duration=6)

        except Exception as e:
            log_content.set(f"Error: {e}\n")
            ui.notification_show(f"Error: {e}", type="error", duration=6)

    # --- Run shyelab ---

    def _build_options() -> list[str]:
        """Build shyelab CLI options from current UI state."""
        op = input.operation()
        return _options_for(op, input.custom_options() if op == "custom" else "")

    def _options_for(op: str, custom: str = "") -> list[str]:
        """shyelab options for operation ``op`` (ValueError: missing nodes)."""
        return build_shyelab_options(
            operation=op,
            op_flags=SHYELAB_OPERATIONS.get(op, {}).get("flags", []),
            custom_options=custom,
            tmin=input.tmin(),
            tmax=input.tmax(),
            nodes=input.ts_nodes(),
        )

    @reactive.effect
    @reactive.event(input.run_btn)
    async def _run_shyelab():
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("No file specified", type="warning")
            return

        try:
            path = config.confine_path(shy_path, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.confine_path(output_dir, _usr, for_write=True)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            options = _build_options()
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        log_content.set(f"Running shyelab on {path.name}...\n" f"Options: {' '.join(options)}\n\n")

        try:
            # Shielded: Shiny 1.9 cancels this effect when the tab closes while it
            # waits, and the wrapper's cancel path kills shyelab half-way; the run
            # and the renaming of its outputs finish as one unit regardless.
            result = await asyncio.shield(
                run_shyelab_and_name(wrapper, path, output_path, options, input.operation())
            )

            stdout_section = f"=== STDOUT ===\n{result.stdout}" if result.stdout else ""
            stderr_section = f"\n\n=== STDERR ===\n{result.stderr}" if result.stderr else ""

            if result.success:
                generated_files.set(result.output_files)
                log_content.set(
                    f"{stdout_section}{stderr_section}\n\n"
                    f"*** shyelab completed successfully ***\n"
                    f"Output files: {len(result.output_files)}\n"
                    f"Duration: {result.duration:.1f}s\n"
                )
                ui.notification_show(
                    f"Done: {len(result.output_files)} files generated",
                    type="message",
                    duration=4,
                )
                next_step_html.set(
                    next_step_card(
                        title="Post-process complete — what next?",
                        links=[
                            NextStepLink(
                                "View results",
                                "Visualize",
                                "Inspect the processed outputs",
                            ),
                            NextStepLink(
                                "Compare runs",
                                "Compare",
                                "Diff this run against another",
                            ),
                        ],
                    )
                )
            else:
                log_content.set(
                    f"{stdout_section}{stderr_section}\n\n"
                    f"*** shyelab failed (code {result.return_code}) ***\n"
                )
                ui.notification_show("shyelab failed - check log", type="error", duration=6)

        except Exception as e:
            log_content.set(f"Error: {e}\n")
            ui.notification_show(f"Error: {e}", type="error", duration=6)

    # --- Presets ---

    for preset_key, preset_info in PRESETS.items():
        _register_preset(
            preset_key,
            preset_info,
            input,
            config,
            wrapper,
            log_content,
            generated_files,
            batch_results,
            active_project=active_project,
            current_user=current_user,
        )

    # --- Batch mode ---

    @reactive.effect
    @reactive.event(input.batch_run_btn)
    async def _batch_run():
        # Access check: require editor role (fail-closed in server mode).
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        paths = list(input.batch_paths() or ())
        if not paths:
            ui.notification_show("No batch files specified", type="warning")
            return

        try:
            options = _build_options()
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return
        results = []

        log_content.set(f"Batch processing {len(paths)} files...\n\n")

        for i, path_str in enumerate(paths):
            try:
                path = config.confine_path(path_str, _usr, must_exist=True)
            except (ValueError, FileNotFoundError) as e:
                results.append(
                    {
                        "file": path_str,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )
                continue

            output_dir = input.output_dir() or str(path.parent)
            try:
                output_path = config.confine_path(output_dir, _usr, for_write=True)
            except ValueError as e:
                results.append(
                    {
                        "file": path_str,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )
                continue

            output_path.mkdir(parents=True, exist_ok=True)

            try:
                # Several inputs into one folder: each out.* gets its input's name.
                # Shielded (see _run_shyelab): a closed tab finishes this file's
                # run and renaming, then the loop stops between files.
                result = await asyncio.shield(
                    run_shyelab_and_name(wrapper, path, output_path, options, input.operation())
                )

                results.append(
                    {
                        "file": path.name,
                        "status": "success" if result.success else "failed",
                        "message": f"code={result.return_code}, {len(result.output_files)} files",
                        "files": result.output_files,
                        "duration": result.duration,
                    }
                )

                current = log_content.get()
                log_content.set(
                    current + f"[{i+1}/{len(paths)}] {path.name}: "
                    f"{'OK' if result.success else 'FAILED'} "
                    f"({result.duration:.1f}s)\n"
                )

            except Exception as e:
                results.append(
                    {
                        "file": path_str,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )

        batch_results.set(results)

        # Collect all output files
        all_files = []
        for r in results:
            all_files.extend(r.get("files", []))
        generated_files.set(all_files)

        success_count = sum(1 for r in results if r["status"] == "success")
        log_content.set(
            log_content.get()
            + f"\n*** Batch complete: {success_count}/{len(paths)} succeeded ***\n"
        )
        ui.notification_show(
            f"Batch done: {success_count}/{len(paths)} succeeded",
            type="message" if success_count == len(paths) else "warning",
            duration=4,
        )
        next_step_html.set(
            next_step_card(
                title="Post-process complete — what next?",
                links=[
                    NextStepLink(
                        "View results",
                        "Visualize",
                        "Inspect the processed outputs",
                    ),
                    NextStepLink(
                        "Compare runs",
                        "Compare",
                        "Diff this run against another",
                    ),
                ],
            )
        )

    # --- Batch convert to NetCDF ---

    @render.ui
    def shy_file_list():
        work_dir = None
        if active_project is not None:
            proj = active_project.get()
            if proj is not None:
                work_dir = proj.get("work_dir")
        if work_dir is None:
            shy_path = input.shy_path()
            if shy_path:
                # Confine the fallback path so the listing cannot enumerate
                # another user's directory (IDOR). Re-confine the resolved base
                # dir in case the path's parent would escape the sandbox.
                _usr = current_user() if current_user is not None else None
                try:
                    p = config.confine_path(shy_path, _usr)
                    base = p if p.is_dir() else p.parent
                    work_dir = str(config.confine_path(base, _usr))
                except (ValueError, FileNotFoundError):
                    work_dir = None
        if work_dir is None:
            return ui.p(
                "No .shy files found. Enter a path or select a project.",
                class_="text-muted small",
            )
        files = discover_shy_files(work_dir)
        if files:
            return ui.input_checkbox_group(
                "batch_convert_files",
                "Select files:",
                choices={f["path"]: f"{f['name']} ({f['size_str']})" for f in files},
                selected=[f["path"] for f in files],
            )
        return ui.p(
            "No .shy files found. Enter a path or select a project.",
            class_="text-muted small",
        )

    @reactive.effect
    @reactive.event(input.batch_convert_btn)
    async def _batch_convert():
        # Access check: require editor role (fail-closed in server mode).
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        try:
            selected = input.batch_convert_files()
        except Exception:
            logger.debug("batch_convert_files input unavailable")
            selected = None
        if not selected:
            ui.notification_show("No files selected for conversion", type="warning")
            return

        results = []
        log_content.set(f"Converting {len(selected)} files to NetCDF...\n\n")

        for i, file_path in enumerate(selected):
            try:
                path = config.confine_path(file_path, _usr, must_exist=True)
            except (ValueError, FileNotFoundError) as e:
                results.append(
                    {
                        "file": file_path,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )
                continue

            output_dir = input.output_dir() or str(path.parent)
            try:
                output_path = config.confine_path(output_dir, _usr, for_write=True)
            except ValueError as e:
                results.append(
                    {
                        "file": file_path,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )
                continue

            output_path.mkdir(parents=True, exist_ok=True)

            try:
                # Shielded (see _run_shyelab).
                result = await asyncio.shield(
                    run_shyelab_and_name(
                        wrapper, path, output_path, ["-outformat", "nc"], "extract_nc"
                    )
                )

                results.append(
                    {
                        "file": path.name,
                        "status": "success" if result.success else "failed",
                        "message": f"code={result.return_code}, {len(result.output_files)} files",
                        "files": result.output_files,
                        "duration": result.duration,
                    }
                )

                current = log_content.get()
                log_content.set(
                    current + f"[{i+1}/{len(selected)}] {path.name}: "
                    f"{'OK' if result.success else 'FAILED'} "
                    f"({result.duration:.1f}s)\n"
                )

            except Exception as e:
                results.append(
                    {
                        "file": file_path,
                        "status": "error",
                        "message": str(e),
                        "files": [],
                    }
                )

        batch_results.set(results)

        # Collect all output files
        all_files = []
        for r in results:
            all_files.extend(r.get("files", []))
        generated_files.set(all_files)

        success_count = sum(1 for r in results if r["status"] == "success")
        log_content.set(
            log_content.get()
            + f"\n*** Batch convert complete: {success_count}/{len(selected)} succeeded ***\n"
        )
        ui.notification_show(
            f"Batch convert done: {success_count}/{len(selected)} succeeded",
            type="message" if success_count == len(selected) else "warning",
            duration=4,
        )

    # --- Render outputs ---

    @render.ui
    def file_info():
        info = file_info_data.get()
        if info is None:
            return ui.div(
                ui.p("No file scanned yet.", class_="text-muted"),
                ui.p("Enter a .shy file path and click 'Scan File' to see details."),
                ui.hr(),
                ui.h6("Supported Operations"),
                *[
                    ui.div(
                        ui.span(op["label"], class_="fw-bold"),
                        ui.span(f" - {op['description']}", class_="text-muted small"),
                        class_="mb-1",
                    )
                    for op in SHYELAB_OPERATIONS.values()
                ],
            )

        # Group info into categories
        basic_keys = ["File Name", "Version", "File Type", "Title", "SHYFEM Version"]
        grid_keys = ["Nodes", "Elements", "nkn", "nel", "Layers", "Levels"]
        time_keys = ["Reference Date", "Reference Time", "Averaging Period", "Min Depth / Offset"]
        var_keys = ["Variables", "Total Variables", "Variable Names"]

        def _render_section(title: str, keys: list[str]) -> ui.Tag | None:
            rows = []
            for key in keys:
                if key in info:
                    rows.append(
                        ui.tags.tr(
                            ui.tags.th(key, style="width: 180px;"),
                            ui.tags.td(str(info[key])),
                        )
                    )
            if not rows:
                return None
            return ui.div(
                ui.h6(title, class_="mt-2"),
                ui.tags.table(
                    ui.tags.tbody(*rows),
                    class_="table table-sm table-bordered",
                ),
            )

        # Render remaining keys not covered above
        covered = set(basic_keys + grid_keys + time_keys + var_keys)
        extra_keys = [k for k in info if k not in covered]

        sections = [
            _render_section("File", basic_keys),
            _render_section("Grid", grid_keys),
            _render_section("Time", time_keys),
            _render_section("Variables", var_keys),
            _render_section("Other", extra_keys) if extra_keys else None,
        ]

        return ui.div(*[s for s in sections if s is not None])

    @render.ui
    def output_files():
        files = generated_files.get()
        if not files:
            return ui.p("No output files generated yet.", class_="text-muted")

        file_cards = []
        total_size = 0

        for f in files:
            path = Path(f)
            try:
                size = path.stat().st_size if path.exists() else 0
            except Exception:
                logger.debug("Could not stat file %s", f)
                size = 0
            total_size += size

            size_str = format_size(size)

            ext = path.suffix.lower()
            type_labels = {
                ".nc": ("NetCDF", "bg-info"),
                ".txt": ("Text", "bg-secondary"),
                ".dat": ("Binary", "bg-dark"),
                ".shy": ("SHYFEM", "bg-primary"),
                ".ts": ("TimeSeries", "bg-success"),
                ".ext": ("ExtraNodes", "bg-success"),
                ".csv": ("CSV", "bg-warning"),
            }
            type_label, type_badge = type_labels.get(ext, ("File", "bg-secondary"))

            file_cards.append(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.span(type_label, class_=f"badge {type_badge} me-2"),
                            ui.span(path.name, class_="fw-bold"),
                            ui.span(f" ({size_str})", class_="text-muted small"),
                            class_="d-flex align-items-center",
                        ),
                        ui.div(
                            ui.code(str(path), class_="small text-break"),
                            class_="mt-1",
                        ),
                        class_="card-body py-2",
                    ),
                    class_="card mb-1",
                )
            )

        total_str = (
            f"{total_size / 1024 / 1024:.1f} MB"
            if total_size > 1024 * 1024
            else f"{total_size / 1024:.1f} KB"
        )

        return ui.div(
            ui.div(
                ui.span(f"{len(files)} files", class_="badge bg-primary me-2"),
                ui.span(f"Total: {total_str}", class_="badge bg-secondary"),
                class_="mb-2",
            ),
            *file_cards,
        )

    @render.ui
    def batch_progress():
        results = batch_results.get()
        if not results:
            return ui.p(
                "Use Batch Mode in the sidebar to process multiple files.",
                class_="text-muted text-center mt-3",
            )

        rows = []
        for i, r in enumerate(results):
            status_class = {
                "success": "table-success",
                "failed": "table-danger",
                "error": "table-warning",
            }.get(r["status"], "")

            rows.append(
                ui.tags.tr(
                    ui.tags.td(str(i + 1)),
                    ui.tags.td(r["file"]),
                    ui.tags.td(
                        ui.span(
                            r["status"].upper(),
                            class_=f"badge {'bg-success' if r['status'] == 'success' else 'bg-danger'}",
                        ),
                    ),
                    ui.tags.td(r["message"]),
                    ui.tags.td(f"{r.get('duration', 0):.1f}s" if r.get("duration") else "-"),
                    class_=status_class,
                )
            )

        success = sum(1 for r in results if r["status"] == "success")
        total = len(results)

        return ui.div(
            ui.h5("Batch Results"),
            ui.p(f"{success}/{total} succeeded", class_="fw-bold"),
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("#"),
                        ui.tags.th("File"),
                        ui.tags.th("Status"),
                        ui.tags.th("Details"),
                        ui.tags.th("Duration"),
                    ),
                ),
                ui.tags.tbody(*rows),
                class_="table table-sm table-bordered",
            ),
        )

    @reactive.effect
    def _auto_load_timeseries():
        """Auto-detect and load time series files after shyelab runs."""
        files = generated_files.get()
        if not files:
            return

        ts_file = preview_series_file(files)
        if ts_file is None:
            return
        ts_path = Path(ts_file)
        if not ts_path.exists():
            return

        try:
            loaded = load_timeseries(ts_path)
            if loaded["data"]:
                ts_preview_data.set(loaded)
        except Exception:
            logger.warning("Failed to load time series preview", exc_info=True)

    return {
        "generated_files": generated_files,
    }


def _register_preset(
    preset_key,
    preset_info,
    input,
    config,
    wrapper,
    log_content,
    generated_files,
    batch_results,
    active_project=None,
    current_user=None,
) -> None:
    """Register a preset button handler. Must be called in a loop to capture closure."""

    @reactive.effect
    @reactive.event(input[f"preset_{preset_key}"])
    async def _run_preset():
        # Access check: require editor role (fail-closed in server mode). A
        # preset runs a chained shyelab pipeline, as privileged as _run_shyelab.
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("Specify an input file first", type="warning")
            return

        try:
            path = config.confine_path(shy_path, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.confine_path(output_dir, _usr, for_write=True)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return
        output_path.mkdir(parents=True, exist_ok=True)

        ops = preset_info["operations"]
        log_content.set(
            f"Running preset: {preset_info['name']}\n" f"Operations: {', '.join(ops)}\n\n"
        )

        all_output = []
        for op_key in ops:
            op = SHYELAB_OPERATIONS.get(op_key, {})

            current = log_content.get()
            log_content.set(current + f"--- {op.get('label', op_key)} ---\n")

            try:
                flags = build_shyelab_options(
                    operation=op_key,
                    op_flags=op.get("flags", []),
                    tmin=input.tmin(),
                    tmax=input.tmax(),
                    nodes=input.ts_nodes(),
                )
            except ValueError as e:
                log_content.set(log_content.get() + f"  Skipped: {e}\n")
                continue

            try:
                # Each step's out.shy gets its own name instead of the next
                # step overwriting it. Shielded (see _run_shyelab).
                result = await asyncio.shield(
                    run_shyelab_and_name(wrapper, path, output_path, flags, op_key)
                )
                all_output.extend(result.output_files)

                status = "OK" if result.success else f"FAILED (code {result.return_code})"
                current = log_content.get()
                log_content.set(current + f"  {status} ({result.duration:.1f}s)\n")

            except Exception as e:
                current = log_content.get()
                log_content.set(current + f"  Error: {e}\n")

        generated_files.set(all_output)
        log_content.set(log_content.get() + f"\n*** Preset complete: {len(all_output)} files ***\n")
        ui.notification_show(
            f"Preset '{preset_info['name']}' done: {len(all_output)} files",
            type="message",
            duration=4,
        )
