"""Post-processing page - full shyelab interface.

Features:
- All shyelab operation modes via GUI (extract, convert, statistics, split, info)
- Variable and layer selection from scanned file metadata
- Time range filtering
- Batch post-processing of multiple .shy files
- Output file browser with size, type, and quick actions
- Operation presets for common workflows
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.timeseries import timeseries_server, timeseries_ui
from shyfem_ui.config import Config
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


# Shyelab operation modes and their CLI flags
SHYELAB_OPERATIONS = {
    "info": {
        "label": "File Info",
        "flags": ["-info"],
        "description": "Display file metadata, variables, layers, and time range",
    },
    "extract_ts": {
        "label": "Extract Time Series",
        "flags": ["-ts", "-split"],
        "description": "Extract time series at extra nodes as separate files",
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
        "label": "Spatial Average",
        "flags": ["-aver"],
        "description": "Compute spatial averages over the domain",
    },
    "temporal_avg": {
        "label": "Time Average",
        "flags": ["-taver"],
        "description": "Compute time-averaged fields",
    },
    "minmax": {
        "label": "Min/Max",
        "flags": ["-minmax"],
        "description": "Compute min/max over time for each node",
    },
    "residual": {
        "label": "Residual Currents",
        "flags": ["-res"],
        "description": "Extract residual (time-averaged) current fields",
    },
    "frequency": {
        "label": "Frequency Analysis",
        "flags": ["-freq"],
        "description": "Frequency/spectral analysis of time series",
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
        "description": "Info, split by variable, time average, min/max",
        "operations": ["info", "split_vars", "temporal_avg", "minmax"],
    },
    "netcdf_split": {
        "name": "NetCDF + Split",
        "description": "Convert to NetCDF with variable splitting",
        "operations": ["extract_nc", "split_vars"],
    },
}


@module.ui
def postprocess_ui():
    """Post-processing page UI."""
    return ui.page_fluid(
        ui.h3("Post-Processing"),
        ui.p("Process SHYFEM output files using shyelab.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # Input files
                ui.h5("Input"),
                ui.input_text(
                    "shy_path",
                    "Output File (.shy)",
                    placeholder="/path/to/output.shy",
                ),
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
                ui.output_ui("variable_selector"),
                ui.output_ui("layer_selector"),

                # Time range
                ui.input_text("tmin", "Start Time", placeholder="0 or 2020-01-01"),
                ui.input_text("tmax", "End Time", placeholder="86400 or 2020-01-02"),
                ui.hr(),

                # Output options
                ui.h5("Output"),
                ui.input_text(
                    "output_dir",
                    "Output Directory",
                    placeholder="/path/to/output (default: same as input)",
                ),
                ui.panel_conditional(
                    "input.operation === 'custom'",
                    ui.input_text(
                        "custom_options",
                        "Custom CLI Options",
                        placeholder="-split -outformat nc -tmin 0",
                    ),
                ),
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
                ui.input_text_area(
                    "batch_paths",
                    "File Paths (one per line)",
                    placeholder="/path/to/file1.shy\n/path/to/file2.shy",
                    rows=3,
                ),
                ui.input_action_button(
                    "batch_run_btn",
                    "Batch Process All",
                    class_="btn-outline-primary w-100",
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
):
    """Post-processing page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # State
    log_content = reactive.value("")
    file_info_data = reactive.value(None)
    generated_files = reactive.value([])
    scanned_variables = reactive.value([])
    scanned_layers = reactive.value([])
    batch_results = reactive.value([])

    # Time series preview data
    ts_preview_data = reactive.value(None)

    # Initialize log viewer
    log_viewer_server("command_log", log_content)

    # Initialize timeseries preview component
    timeseries_server("ts_preview", ts_preview_data, config=config)

    @render.ui
    def operation_description():
        op = input.operation()
        info = SHYELAB_OPERATIONS.get(op, {})
        return ui.p(info.get("description", ""), class_="text-muted small")

    @render.ui
    def variable_selector():
        variables = scanned_variables.get()
        if not variables:
            return None
        choices = {v: v for v in variables}
        return ui.input_checkbox_group(
            "selected_vars",
            "Variables",
            choices=choices,
            selected=list(choices.keys()),
        )

    @render.ui
    def layer_selector():
        layers = scanned_layers.get()
        if not layers:
            return None
        choices = {str(i): f"Layer {i}: {d}" for i, d in enumerate(layers)}
        return ui.input_select(
            "selected_layer",
            "Layer",
            choices={"all": "All layers", **choices},
            selected="all",
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
        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("No file specified", type="warning")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        log_content.set(f"Scanning {path.name}...\n")

        try:
            result = await wrapper.run_command(
                "shyelab",
                ["-info", str(path)],
                path.parent,
            )

            if result.success:
                info = _parse_shyelab_info(result.stdout)
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
                ui.notification_show("File scanned successfully", type="message")
            else:
                log_content.set(
                    f"=== STDOUT ===\n{result.stdout}\n\n"
                    f"=== STDERR ===\n{result.stderr}\n\n"
                    f"*** shyelab -info failed (code {result.return_code}) ***\n"
                )
                ui.notification_show("Scan failed - check log", type="error")

        except Exception as e:
            log_content.set(f"Error: {e}\n")
            ui.notification_show(f"Error: {e}", type="error")

    # --- Run shyelab ---

    def _build_options() -> list[str]:
        """Build shyelab CLI options from current UI state."""
        op = input.operation()
        op_info = SHYELAB_OPERATIONS.get(op, {})

        if op == "custom":
            custom = input.custom_options()
            return custom.split() if custom else []

        options = list(op_info.get("flags", []))

        # Time range
        tmin = input.tmin()
        tmax = input.tmax()
        if tmin:
            options.extend(["-tmin", tmin])
        if tmax:
            options.extend(["-tmax", tmax])

        # Variable filter
        try:
            selected_vars = input.selected_vars()
            if selected_vars and len(selected_vars) < len(scanned_variables.get()):
                for var in selected_vars:
                    options.append(f"-{var}")
        except Exception:
            pass

        # Layer selection
        try:
            layer = input.selected_layer()
            if layer != "all":
                options.extend(["-layer", layer])
        except Exception:
            pass

        return options

    @reactive.effect
    @reactive.event(input.run_btn)
    async def _run_shyelab():
        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("No file specified", type="warning")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        options = _build_options()

        log_content.set(
            f"Running shyelab on {path.name}...\n"
            f"Options: {' '.join(options)}\n\n"
        )

        try:
            result = await wrapper.run_shyelab(
                path, output_path, options,
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
                )
            else:
                log_content.set(
                    f"{stdout_section}{stderr_section}\n\n"
                    f"*** shyelab failed (code {result.return_code}) ***\n"
                )
                ui.notification_show("shyelab failed - check log", type="error")

        except Exception as e:
            log_content.set(f"Error: {e}\n")
            ui.notification_show(f"Error: {e}", type="error")

    # --- Presets ---

    for preset_key, preset_info in PRESETS.items():
        _register_preset(
            preset_key, preset_info, input, config, wrapper,
            log_content, generated_files, batch_results,
        )

    # --- Batch mode ---

    @reactive.effect
    @reactive.event(input.batch_run_btn)
    async def _batch_run():
        paths_text = input.batch_paths()
        if not paths_text:
            ui.notification_show("No batch files specified", type="warning")
            return

        paths = [p.strip() for p in paths_text.strip().splitlines() if p.strip()]
        if not paths:
            ui.notification_show("No valid file paths", type="warning")
            return

        options = _build_options()
        results = []

        log_content.set(f"Batch processing {len(paths)} files...\n\n")

        for i, path_str in enumerate(paths):
            try:
                path = config.validate_path(path_str, must_exist=True)
            except (ValueError, FileNotFoundError) as e:
                results.append({
                    "file": path_str,
                    "status": "error",
                    "message": str(e),
                    "files": [],
                })
                continue

            output_dir = input.output_dir() or str(path.parent)
            try:
                output_path = config.validate_path(output_dir)
            except ValueError as e:
                results.append({
                    "file": path_str,
                    "status": "error",
                    "message": str(e),
                    "files": [],
                })
                continue

            output_path.mkdir(parents=True, exist_ok=True)

            try:
                result = await wrapper.run_shyelab(path, output_path, options)

                results.append({
                    "file": path.name,
                    "status": "success" if result.success else "failed",
                    "message": f"code={result.return_code}, {len(result.output_files)} files",
                    "files": result.output_files,
                    "duration": result.duration,
                })

                current = log_content.get()
                log_content.set(
                    current +
                    f"[{i+1}/{len(paths)}] {path.name}: "
                    f"{'OK' if result.success else 'FAILED'} "
                    f"({result.duration:.1f}s)\n"
                )

            except Exception as e:
                results.append({
                    "file": path_str,
                    "status": "error",
                    "message": str(e),
                    "files": [],
                })

        batch_results.set(results)

        # Collect all output files
        all_files = []
        for r in results:
            all_files.extend(r.get("files", []))
        generated_files.set(all_files)

        success_count = sum(1 for r in results if r["status"] == "success")
        log_content.set(
            log_content.get() +
            f"\n*** Batch complete: {success_count}/{len(paths)} succeeded ***\n"
        )
        ui.notification_show(
            f"Batch done: {success_count}/{len(paths)} succeeded",
            type="message" if success_count == len(paths) else "warning",
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

        def _render_section(title: str, keys: list[str]) -> Optional[ui.Tag]:
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
                size = 0
            total_size += size

            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / 1024 / 1024:.1f} MB"

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

        total_str = f"{total_size / 1024 / 1024:.1f} MB" if total_size > 1024 * 1024 else f"{total_size / 1024:.1f} KB"

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

        ts_files = [
            f for f in files
            if f.endswith((".ts", ".ext", ".csv"))
        ]
        if not ts_files:
            return

        # Load the first time series file found
        ts_path = Path(ts_files[0])
        if not ts_path.exists():
            return

        try:
            data = []
            columns = []
            with open(ts_path) as fh:
                for i, line in enumerate(fh):
                    parts = line.strip().split()
                    if not parts:
                        continue
                    # Check if first line is a header
                    if i == 0 and not parts[0].replace(".", "").replace("-", "").replace("+", "").replace("e", "").replace("E", "").isdigit():
                        columns = parts
                        continue
                    try:
                        data.append([float(p) for p in parts])
                    except ValueError:
                        continue

            if data:
                if not columns:
                    columns = [f"col{j}" for j in range(len(data[0]))]
                    if columns:
                        columns[0] = "time"
                ts_preview_data.set({
                    "columns": columns,
                    "data": data,
                })
        except Exception:
            pass

    return {
        "generated_files": generated_files,
    }


def _register_preset(preset_key, preset_info, input, config, wrapper,
                      log_content, generated_files, batch_results):
    """Register a preset button handler. Must be called in a loop to capture closure."""

    @reactive.effect
    @reactive.event(input[f"preset_{preset_key}"])
    async def _run_preset():
        shy_path = input.shy_path()
        if not shy_path:
            ui.notification_show("Specify an input file first", type="warning")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        ops = preset_info["operations"]
        log_content.set(f"Running preset: {preset_info['name']}\n"
                        f"Operations: {', '.join(ops)}\n\n")

        all_output = []
        for op_key in ops:
            op = SHYELAB_OPERATIONS.get(op_key, {})
            flags = list(op.get("flags", []))

            current = log_content.get()
            log_content.set(current + f"--- {op.get('label', op_key)} ---\n")

            try:
                result = await wrapper.run_shyelab(path, output_path, flags)
                all_output.extend(result.output_files)

                status = "OK" if result.success else f"FAILED (code {result.return_code})"
                current = log_content.get()
                log_content.set(current + f"  {status} ({result.duration:.1f}s)\n")

            except Exception as e:
                current = log_content.get()
                log_content.set(current + f"  Error: {e}\n")

        generated_files.set(all_output)
        log_content.set(
            log_content.get() +
            f"\n*** Preset complete: {len(all_output)} files ***\n"
        )
        ui.notification_show(
            f"Preset '{preset_info['name']}' done: {len(all_output)} files",
            type="message",
        )


def _parse_shyelab_info(output: str) -> dict:
    """Parse shyelab -info output into a structured dictionary.

    Handles the Fortran write(6,*) output format from io_shy.f90's shy_info
    subroutine, including:
    - Label: value pairs (main file info)
    - Basin info (nkn = N  nel = N format)
    - Variable descriptions table
    - Layer depth listings
    """
    info = {}
    lines = output.splitlines()
    i = 0

    variables = []
    layer_depths = []
    in_variables = False
    parsing_layer_values = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1

        if not stripped:
            in_variables = False
            parsing_layer_values = False
            continue

        # Detect section headers
        if "information on shy file" in stripped.lower():
            continue

        # Variable descriptions table
        if "total number of available variables" in stripped.lower():
            match = re.search(r"(\d+)", stripped)
            if match:
                info["Total Variables"] = match.group(1)
            continue

        if "varnum" in stripped.lower() and "varid" in stripped.lower():
            in_variables = True
            continue

        if in_variables:
            var_match = re.match(r"\s*(\d+)\s+(\d+)\s*(.*)", stripped)
            if var_match:
                var_name = var_match.group(3).strip()
                variables.append(var_name)
                continue
            else:
                in_variables = False

        # Layer depths header
        if re.match(r"levels\s*:", stripped, re.IGNORECASE):
            match = re.search(r":\s*(\d+)", stripped)
            if match:
                info["Levels"] = match.group(1)
            parsing_layer_values = True
            continue

        # Layer depth values
        if parsing_layer_values:
            floats = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", stripped)
            if floats:
                layer_depths.extend(floats)
                continue
            else:
                parsing_layer_values = False

        # Layer statistics table
        if "layer" in stripped.lower() and "count" in stripped.lower() and "accumulated" in stripped.lower():
            continue

        # Basin info: nkn = N   nel = N
        basin_match = re.findall(r"(\w+)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", stripped)
        if basin_match and len(basin_match) >= 2 and "=" in stripped:
            for key, value in basin_match:
                display_key = key.lower()
                if display_key in ("nkn", "nel", "mbw", "ngr", "isphe"):
                    info[display_key] = value
                elif display_key in ("dcor", "dirn"):
                    info[display_key] = value
                elif "min" in display_key or "max" in display_key:
                    info[display_key] = value
            continue

        # Label: value pairs (primary shy_info output)
        colon_match = re.match(r"\s*([\w/]+)\s*:\s+(.*)", stripped)
        if colon_match:
            key = colon_match.group(1).strip()
            value = colon_match.group(2).strip()
            key_map = {
                "filename": "File Name",
                "nvers": "Version",
                "ftype": "File Type",
                "nkn": "Nodes",
                "nel": "Elements",
                "nlv": "Layers",
                "nvar": "Variables",
                "date": "Reference Date",
                "time": "Reference Time",
                "title": "Title",
                "femver": "SHYFEM Version",
                "hzmin/off": "Min Depth / Offset",
                "dtaver": "Averaging Period",
            }
            display_key = key_map.get(key, key)
            if value in ("T", ".TRUE."):
                value = "Yes"
            elif value in ("F", ".FALSE."):
                value = "No"
            info[display_key] = value
            continue

    if variables:
        info["Variable Names"] = ", ".join(variables)
    if layer_depths:
        info["Layer Depths"] = ", ".join(layer_depths)

    return info
