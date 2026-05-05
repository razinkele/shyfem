"""Mesh partitioning page - shyparts interface."""

import logging
from pathlib import Path

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

# Reuse the partition color palette from grid_map
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
from shyfem_ui.components.grid_map import PARTITION_COLORS, grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.middleware.session_auth import get_current_user
from shyfem_ui.services.access_control import check_project_access
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.partitioning_logic import (
    analyze_partitions,
    compute_load_balance,
    validate_partition_files,
)
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)


@module.ui
def partitioning_ui() -> ui.Tag:
    """Mesh partitioning page UI."""
    return ui.div(
        ui.h3("Mesh Partitioning"),
        ui.p("Partition mesh for MPI parallel execution using METIS.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # Input file
                ui.h5("Input Basin"),
                file_picker_ui("fp_bas", label="Pick basin from project"),
                ui.input_text(
                    "bas_path",
                    "Basin File (.bas)",
                    placeholder="/path/to/basin.bas",
                ),
                file_picker_ui("fp_grd", label="Pick grid from project"),
                ui.input_text(
                    "grd_path",
                    "Grid File (.grd) for visualization",
                    placeholder="/path/to/grid.grd (optional)",
                ),
                ui.input_action_button(
                    "load_grid_btn",
                    "Load Grid",
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
                ui.div(
                    ui.tags.label("Partitioning Method", class_="form-label"),
                    ui.tags.div("METIS", class_="form-control-plaintext"),
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
                    "Partition Map",
                    grid_map_ui("partition_map"),
                ),
                ui.nav_panel(
                    "Load Balance",
                    output_widget("balance_chart"),
                ),
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
    active_project=None,
    tutorial_context=None,
) -> None:
    """Mesh partitioning page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # Reactive value for picker project_id, updated inside _on_project_changed.
    # `reactive.value` is just an alias for the class `reactive.Value`
    # (verified -- `reactive.value is reactive.Value` returns True at runtime).
    # Use the capital-V class name in the annotation (canonical), and
    # the lowercase callable form for construction (idiomatic).
    project_id_val: reactive.Value[int | None] = reactive.value(None)

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            return
        project_id_val.set(proj.get("id"))
        work = proj["work_dir"]
        if proj["grids"]:
            grid = proj["grids"][0]
            # `reactive.isolate()` prevents `input.bas_path()` / `input.grd_path()`
            # from registering as dependencies of this effect -- without it,
            # every keystroke in those fields would re-run this effect and
            # clobber the user's edit. The intended trigger is
            # `active_project` changing only.
            # The empty-guard then prevents overwriting picker selections
            # when active_project re-emits without an actual project change.
            with reactive.isolate():
                bas_empty = not input.bas_path()
                grd_empty = not input.grd_path()
            if grid.get("bas_file") and bas_empty:
                ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
            if grid.get("grd_file") and grd_empty:
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))

    # File pickers delegate the resolve/log/notify branching to
    # fill_picker_input (see its docstring in components/file_picker.py).
    file_picker_server(
        "fp_bas",
        project_id=project_id_val,
        file_types=["basin"],
        on_selected=lambda rel: fill_picker_input(
            "bas_path",
            active_project.get() if active_project else None,
            rel,
        ),
    )
    file_picker_server(
        "fp_grd",
        project_id=project_id_val,
        file_types=["grid"],
        on_selected=lambda rel: fill_picker_input(
            "grd_path",
            active_project.get() if active_project else None,
            rel,
        ),
    )

    # State
    log_content = reactive.value("")
    partition_files = reactive.value([])
    partition_stats_data = reactive.value(None)
    current_grd = reactive.value(None)
    partition_map_data = reactive.value(None)  # {elem_id: partition_index}

    # Initialize child modules
    log_viewer_server("command_log", log_content)
    grid_map_server("partition_map", grd_file=current_grd, partition_map=partition_map_data)

    @reactive.effect
    @reactive.event(input.load_grid_btn)
    def _load_grid():
        grd_path = input.grd_path()
        if not grd_path:
            log_content.set("Error: No grid file path specified")
            return
        try:
            path = config.validate_path(grd_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            logger.exception("Invalid GRD path for partitioning: %r", grd_path)
            log_content.set(f"Error: {e}")
            return
        try:
            grd = GrdParser.parse_file(path)
            current_grd.set(grd)
            log_content.set(
                f"Loaded grid: {path.name}\n"
                f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}\n"
            )
        except Exception as e:
            logger.exception("Failed to parse GRD file %s for partitioning", grd_path)
            log_content.set(f"Error loading grid: {e}")

    @reactive.effect
    @reactive.event(input.run_shyparts_btn)
    async def _run_shyparts():
        _usr = get_current_user()
        logger.info(
            "User running shyparts on %r with %s partitions",
            input.bas_path(), input.num_partitions(),
        )
        if active_project is not None:
            _proj = active_project.get()
            if _proj is not None and (
                _usr is not None
                and check_project_access(_proj["id"], _usr, min_role="editor") is None
            ):
                ui.notification_show(
                    "Permission denied: editor role required to run partitioning",
                    type="error",
                    duration=6,
                )
                return

        bas_path = input.bas_path()
        if not bas_path:
            log_content.set("Error: No basin file specified")
            return

        try:
            bas_file = config.validate_path(bas_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            logger.exception("Invalid basin file path for shyparts: %r", bas_path)
            log_content.set(f"Error: {e}")
            return

        # Determine output directory
        output_dir = input.output_dir() or str(bas_file.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            logger.exception("Invalid shyparts output directory %r", output_dir)
            log_content.set(f"Error: {e}")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        np_val = input.num_partitions()

        log_content.set(f"Running shyparts with {np_val} partitions...\n")
        log_content.set(log_content.get() + f"Input: {bas_file}\n")
        log_content.set(log_content.get() + f"Output: {output_path}\n\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        weighted = input.weighted()
        options = ["-weighted"] if weighted else None

        try:
            result = await wrapper.run_shyparts(
                bas_file,
                output_path,
                np=np_val,
                options=options,
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() + f"\n*** shyparts completed successfully ***\n"
                    f"Output files: {', '.join(result.output_files)}\n"
                )
                partition_files.set(result.output_files)
                _analyze_partitions(output_path, np_val)
            else:
                log_content.set(
                    log_content.get() + f"\n*** shyparts failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )

        except Exception as e:
            logger.exception("Unexpected error running shyparts on %s", bas_path)
            log_content.set(log_content.get() + f"\nError: {e}\n")

    def _analyze_partitions(output_dir: Path, np_val: int):
        """Analyze partition files and update reactive state."""
        stats, pmap = analyze_partitions(output_dir, np_val)
        partition_stats_data.set(stats)
        if pmap:
            partition_map_data.set(pmap)

    @reactive.effect
    @reactive.event(input.validate_btn)
    def _validate_partitions():
        files = partition_files.get()
        logger.info("User validating %d partition files", len(files))
        if not files:
            log_content.set("No partition files to validate. Run shyparts first.")
            return

        log_content.set("Validating partition files...\n\n")
        for filename, status in validate_partition_files(files):
            log_content.set(log_content.get() + f"  {filename}: {status}\n")
        log_content.set(log_content.get() + "\nValidation complete.\n")

    @render_widget
    def balance_chart():
        """Plotly bar chart showing elements per partition."""
        stats = partition_stats_data.get()
        if stats is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Run shyparts to see load balance",
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

        elements = stats.get("elements_per_partition", [])
        metrics = compute_load_balance(elements)
        if metrics["is_empty"]:
            fig = go.Figure()
            fig.add_annotation(
                text="No partition data available",
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

        n_parts = metrics["n_parts"]
        avg = metrics["avg"]
        labels = metrics["labels"]
        colors = [PARTITION_COLORS[i % len(PARTITION_COLORS)] for i in range(n_parts)]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=labels,
                y=elements,
                marker_color=colors,
                text=[f"{c:,}" for c in elements],
                textposition="auto",
                hovertemplate="Partition %{x}<br>Elements: %{y:,}<extra></extra>",
            )
        )
        # Average line
        fig.add_hline(
            y=avg,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Avg: {avg:,.0f}",
            annotation_position="top right",
        )

        imbalance_pct = metrics["imbalance_pct"]
        fig.update_layout(
            title=f"Load Balance ({n_parts} partitions, imbalance: {imbalance_pct:.1f}%)",
            xaxis_title="Partition",
            yaxis_title="Elements",
            height=500,
            showlegend=False,
        )
        return fig

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

        file_list = [ui.tags.li(ui.code(Path(f).name)) for f in files]

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

        # Reuse compute_load_balance — single source of truth for these metrics.
        metrics = compute_load_balance(elements)
        total = sum(elements)
        avg = metrics["avg"]
        min_el = metrics["min"]
        max_el = metrics["max"]
        imbalance = metrics["imbalance_pct"]

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
                            class_=(
                                "text-success"
                                if imbalance < 10
                                else "text-warning" if imbalance < 20 else "text-danger"
                            ),
                        ),
                    ),
                ),
                class_="table table-sm",
            ),
        )

    return {
        "partition_files": partition_files,
    }
