"""Mesh partitioning page - shyparts interface."""

from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


@module.ui
def partitioning_ui():
    """Mesh partitioning page UI."""
    return ui.page_fluid(
        ui.h3("Mesh Partitioning"),
        ui.p("Partition mesh for MPI parallel execution using METIS.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # Input file
                ui.h5("Input Basin"),
                ui.input_text(
                    "bas_path",
                    "Basin File (.bas)",
                    placeholder="/path/to/basin.bas",
                ),
                ui.input_action_button(
                    "browse_bas_btn",
                    "Browse...",
                    class_="btn-outline-secondary btn-sm mb-3",
                ),
                ui.hr(),
                # Partitioning options
                ui.h5("Partitioning Options"),
                ui.input_numeric(
                    "num_partitions",
                    "Number of Partitions",
                    value=4,
                    min=2,
                    max=1024,
                    step=1,
                ),
                ui.input_select(
                    "partition_method",
                    "Partitioning Method",
                    choices={
                        "metis": "METIS (default)",
                        "manual": "Manual assignment",
                    },
                ),
                ui.input_checkbox(
                    "weighted",
                    "Use weighted partitioning",
                    value=True,
                ),
                ui.input_text(
                    "output_dir",
                    "Output Directory",
                    placeholder="/path/to/output",
                ),
                ui.hr(),
                # Actions
                ui.input_action_button(
                    "run_shyparts_btn",
                    "Run shyparts",
                    class_="btn-primary w-100 mb-2",
                ),
                ui.input_action_button(
                    "validate_btn",
                    "Validate Partitions",
                    class_="btn-outline-secondary w-100",
                ),
                width=300,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "Partition Info",
                    ui.output_ui("partition_info"),
                ),
                ui.nav_panel(
                    "Statistics",
                    ui.output_ui("partition_stats"),
                ),
                ui.nav_panel(
                    "Log",
                    log_viewer_ui("command_log"),
                ),
            ),
        ),
    )


@module.server
def partitioning_server(
    input,
    output,
    session,
    config: Config,
):
    """Mesh partitioning page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # State
    log_content = reactive.value("")
    partition_files = reactive.value([])
    partition_stats_data = reactive.value(None)

    # Initialize child modules
    log_viewer_server("command_log", log_content)

    @reactive.effect
    @reactive.event(input.run_shyparts_btn)
    async def _run_shyparts():
        bas_path = input.bas_path()
        if not bas_path:
            log_content.set("Error: No basin file specified")
            return

        try:
            bas_file = config.validate_path(bas_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            log_content.set(f"Error: {e}")
            return

        # Determine output directory
        output_dir = input.output_dir() or str(bas_file.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            log_content.set(f"Error: {e}")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        np = input.num_partitions()

        log_content.set(f"Running shyparts with {np} partitions...\n")
        log_content.set(log_content.get() + f"Input: {bas_file}\n")
        log_content.set(log_content.get() + f"Output: {output_path}\n\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            result = await wrapper.run_shyparts(
                bas_file,
                output_path,
                np=np,
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() +
                    f"\n*** shyparts completed successfully ***\n"
                    f"Output files: {', '.join(result.output_files)}\n"
                )
                partition_files.set(result.output_files)
                _analyze_partitions(output_path, np)
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** shyparts failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    def _analyze_partitions(output_dir: Path, np: int):
        """Analyze partition files for statistics."""
        stats = {
            "num_partitions": np,
            "partition_files": [],
            "elements_per_partition": [],
        }

        # Look for partition files
        for i in range(np):
            par_file = output_dir / f"partition.{i:04d}.par"
            if par_file.exists():
                stats["partition_files"].append(str(par_file))
                # Count elements (simple line count)
                try:
                    with open(par_file) as f:
                        lines = sum(1 for _ in f)
                    stats["elements_per_partition"].append(lines)
                except Exception:
                    stats["elements_per_partition"].append(0)

        partition_stats_data.set(stats)

    @reactive.effect
    @reactive.event(input.validate_btn)
    def _validate_partitions():
        files = partition_files.get()
        if not files:
            log_content.set("No partition files to validate. Run shyparts first.")
            return

        log_content.set("Validating partition files...\n\n")

        for f in files:
            path = Path(f)
            if path.exists():
                size = path.stat().st_size
                log_content.set(
                    log_content.get() +
                    f"  {path.name}: {size:,} bytes - OK\n"
                )
            else:
                log_content.set(
                    log_content.get() +
                    f"  {path.name}: MISSING\n"
                )

        log_content.set(log_content.get() + "\nValidation complete.\n")

    @render.ui
    def partition_info():
        files = partition_files.get()
        if not files:
            return ui.div(
                ui.p("No partition files generated yet.", class_="text-muted"),
                ui.p("Specify a basin file and run shyparts to partition the mesh."),
                ui.h6("Recommended Partitions:", class_="mt-3"),
                ui.tags.ul(
                    ui.tags.li("Small mesh (<10k elements): 2-4 partitions"),
                    ui.tags.li("Medium mesh (10k-100k elements): 4-16 partitions"),
                    ui.tags.li("Large mesh (>100k elements): 16-64 partitions"),
                ),
            )

        file_list = [
            ui.tags.li(ui.code(Path(f).name))
            for f in files
        ]

        return ui.div(
            ui.h5("Generated Partition Files"),
            ui.tags.ul(*file_list),
            ui.p(f"Total: {len(files)} partition files", class_="text-muted"),
        )

    @render.ui
    def partition_stats():
        stats = partition_stats_data.get()
        if stats is None:
            return ui.p("Run shyparts to generate partition statistics.", class_="text-muted")

        elements = stats.get("elements_per_partition", [])
        if not elements:
            return ui.p("No element data available.", class_="text-muted")

        total = sum(elements)
        avg = total / len(elements) if elements else 0
        min_el = min(elements) if elements else 0
        max_el = max(elements) if elements else 0
        imbalance = (max_el - min_el) / avg * 100 if avg > 0 else 0

        # Create bar chart representation
        bars = []
        for i, count in enumerate(elements):
            width_pct = count / max_el * 100 if max_el > 0 else 0
            bars.append(
                ui.div(
                    ui.span(f"P{i}", class_="me-2 small"),
                    ui.div(
                        ui.div(
                            style=f"width: {width_pct}%; height: 20px; background-color: #0d6efd;",
                        ),
                        class_="flex-grow-1",
                        style="background-color: #e9ecef; height: 20px;",
                    ),
                    ui.span(f"{count:,}", class_="ms-2 small"),
                    class_="d-flex align-items-center mb-1",
                )
            )

        return ui.div(
            ui.h5("Partition Statistics"),
            ui.tags.table(
                ui.tags.tbody(
                    ui.tags.tr(
                        ui.tags.th("Number of Partitions"),
                        ui.tags.td(str(stats["num_partitions"])),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Total Elements"),
                        ui.tags.td(f"{total:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Average per Partition"),
                        ui.tags.td(f"{avg:,.0f}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Min Elements"),
                        ui.tags.td(f"{min_el:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Max Elements"),
                        ui.tags.td(f"{max_el:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Load Imbalance"),
                        ui.tags.td(
                            f"{imbalance:.1f}%",
                            class_="text-success" if imbalance < 10 else "text-warning" if imbalance < 20 else "text-danger",
                        ),
                    ),
                ),
                class_="table table-sm",
            ),
            ui.h6("Elements per Partition", class_="mt-3"),
            ui.div(*bars, class_="mt-2"),
        )

    return {
        "partition_files": partition_files,
    }
