"""Post-processing page - shyelab interface."""

from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


@module.ui
def postprocess_ui():
    """Post-processing page UI."""
    return ui.page_fluid(
        ui.h3("Post-Processing"),
        ui.p("Process SHYFEM output files using shyelab.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # Input file
                ui.h5("Input File"),
                ui.input_text(
                    "shy_path",
                    "Output File (.shy)",
                    placeholder="/path/to/output.shy",
                ),
                ui.input_action_button(
                    "scan_btn",
                    "Scan File",
                    class_="btn-outline-primary btn-sm mb-3",
                ),
                ui.hr(),
                # Time selection
                ui.h5("Time Range"),
                ui.input_text(
                    "tmin",
                    "Start Time",
                    placeholder="0 or 2020-01-01",
                ),
                ui.input_text(
                    "tmax",
                    "End Time",
                    placeholder="86400 or 2020-01-02",
                ),
                ui.hr(),
                # Variable selection
                ui.h5("Variables"),
                ui.input_checkbox_group(
                    "variables",
                    "Select Variables",
                    choices={
                        "zeta": "Water Level (zeta)",
                        "vel": "Velocity (u, v)",
                        "temp": "Temperature",
                        "salt": "Salinity",
                        "conz": "Concentration",
                    },
                ),
                ui.hr(),
                # Output options
                ui.h5("Output Options"),
                ui.input_select(
                    "output_format",
                    "Output Format",
                    choices={
                        "nc": "NetCDF (.nc)",
                        "txt": "Text (.txt)",
                        "dat": "Binary (.dat)",
                    },
                ),
                ui.input_checkbox("split", "Split by variable", value=True),
                ui.input_text(
                    "output_dir",
                    "Output Directory",
                    placeholder="/path/to/output",
                ),
                ui.hr(),
                # Actions
                ui.input_action_button(
                    "run_shyelab_btn",
                    "Run shyelab",
                    class_="btn-primary w-100 mb-2",
                ),
                ui.input_action_button(
                    "extract_ts_btn",
                    "Extract Time Series",
                    class_="btn-secondary w-100",
                ),
                width=300,
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

    # Initialize log viewer
    log_viewer_server("command_log", log_content)

    @reactive.effect
    @reactive.event(input.scan_btn)
    async def _scan_file():
        shy_path = input.shy_path()
        if not shy_path:
            log_content.set("Error: No file specified")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            log_content.set(f"Error: {e}")
            return

        log_content.set(f"Scanning {path.name}...\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            # Run shyelab with -info option
            result = await wrapper.run_command(
                "shyelab",
                ["-info", str(path)],
                path.parent,
                output_callback=update_log,
            )

            if result.success:
                # Parse output for file info
                info = _parse_shyelab_info(result.stdout)
                file_info_data.set(info)
                log_content.set(log_content.get() + "\n*** Scan complete ***\n")
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** shyelab failed ***\n{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    @reactive.effect
    @reactive.event(input.run_shyelab_btn)
    async def _run_shyelab():
        shy_path = input.shy_path()
        if not shy_path:
            log_content.set("Error: No file specified")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            log_content.set(f"Error: {e}")
            return

        # Build options
        options = []

        # Time range
        tmin = input.tmin()
        tmax = input.tmax()
        if tmin:
            options.extend(["-tmin", tmin])
        if tmax:
            options.extend(["-tmax", tmax])

        # Variables
        variables = input.variables()
        for var in variables:
            options.append(f"-{var}")

        # Output format
        fmt = input.output_format()
        if fmt == "nc":
            options.append("-outformat")
            options.append("nc")
        elif fmt == "txt":
            options.append("-outformat")
            options.append("txt")

        # Split
        if input.split():
            options.append("-split")

        # Output directory
        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            log_content.set(f"Error: {e}")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        log_content.set(f"Running shyelab on {path.name}...\n")
        log_content.set(log_content.get() + f"Options: {' '.join(options)}\n\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            result = await wrapper.run_shyelab(
                path,
                output_path,
                options,
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() +
                    f"\n*** shyelab completed successfully ***\n"
                    f"Output files: {', '.join(result.output_files)}\n"
                )
                generated_files.set(result.output_files)
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** shyelab failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    @reactive.effect
    @reactive.event(input.extract_ts_btn)
    async def _extract_time_series():
        shy_path = input.shy_path()
        if not shy_path:
            log_content.set("Error: No file specified")
            return

        try:
            path = config.validate_path(shy_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            log_content.set(f"Error: {e}")
            return

        output_dir = input.output_dir() or str(path.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            log_content.set(f"Error: {e}")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        log_content.set(f"Extracting time series from {path.name}...\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            # Extract time series at extra nodes
            options = ["-ts", "-split"]

            result = await wrapper.run_shyelab(
                path,
                output_path,
                options,
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() +
                    f"\n*** Time series extraction complete ***\n"
                )
                generated_files.set(result.output_files)
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** Extraction failed ***\n{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    @render.ui
    def file_info():
        info = file_info_data.get()
        if info is None:
            return ui.div(
                ui.p("No file scanned yet.", class_="text-muted"),
                ui.p("Enter a .shy file path and click 'Scan File' to see details."),
            )

        rows = []
        for key, value in info.items():
            rows.append(
                ui.tags.tr(
                    ui.tags.th(key),
                    ui.tags.td(str(value)),
                )
            )

        return ui.div(
            ui.h5("File Information"),
            ui.tags.table(
                ui.tags.tbody(*rows),
                class_="table table-sm",
            ),
        )

    @render.ui
    def output_files():
        files = generated_files.get()
        if not files:
            return ui.p("No output files generated yet.", class_="text-muted")

        file_cards = []
        for f in files:
            path = Path(f)
            size = path.stat().st_size if path.exists() else 0
            size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"

            # Determine file type icon
            ext = path.suffix.lower()
            if ext == ".nc":
                icon = "globe"  # NetCDF
            elif ext == ".txt":
                icon = "file-text"
            else:
                icon = "file"

            file_cards.append(
                ui.div(
                    ui.div(
                        ui.span(path.name, class_="fw-bold"),
                        ui.span(f" ({size_str})", class_="text-muted"),
                        class_="d-flex justify-content-between",
                    ),
                    ui.div(
                        ui.code(str(path), class_="small"),
                        class_="mt-1",
                    ),
                    class_="card-body py-2",
                ),
                class_="card mb-1",
            )

        return ui.div(
            ui.h5(f"Generated Files ({len(files)})"),
            *file_cards,
        )

    return {
        "generated_files": generated_files,
    }


def _parse_shyelab_info(output: str) -> dict:
    """Parse shyelab -info output into a dictionary."""
    info = {}

    lines = output.splitlines()
    for line in lines:
        line = line.strip()
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                info[key] = value
        elif "=" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                info[key] = value

    return info
