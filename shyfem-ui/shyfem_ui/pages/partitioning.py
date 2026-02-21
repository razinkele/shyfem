"""Mesh partitioning page - shyparts interface."""

from pathlib import Path

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

# Reuse the partition color palette from grid_map
from shyfem_ui.components.grid_map import PARTITION_COLORS, grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


@module.ui
def partitioning_ui():
    """Mesh partitioning page UI."""
    return ui.div(
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
):
    """Mesh partitioning page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        work = proj["work_dir"]
        if proj["grids"]:
            grid = proj["grids"][0]
            if grid.get("bas_file"):
                ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
            if grid.get("grd_file"):
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))

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
            log_content.set(f"Error loading grid: {e}")

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

        np_val = input.num_partitions()

        log_content.set(f"Running shyparts with {np_val} partitions...\n")
        log_content.set(log_content.get() + f"Input: {bas_file}\n")
        log_content.set(log_content.get() + f"Output: {output_path}\n\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            result = await wrapper.run_shyparts(
                bas_file,
                output_path,
                np=np_val,
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
            log_content.set(log_content.get() + f"\nError: {e}\n")

    def _analyze_partitions(output_dir: Path, np_val: int):
        """Analyze partition files for statistics and build partition map."""
        stats = {
            "num_partitions": np_val,
            "partition_files": [],
            "elements_per_partition": [],
        }

        pmap = {}
        for i in range(np_val):
            par_file = output_dir / f"partition.{i:04d}.par"
            if par_file.exists():
                stats["partition_files"].append(str(par_file))
                try:
                    with open(par_file) as f:
                        elem_lines = f.readlines()
                    stats["elements_per_partition"].append(len(elem_lines))
                    # Build partition map: each line contains an element ID
                    for line in elem_lines:
                        line = line.strip()
                        if line:
                            try:
                                elem_id = int(line.split()[0])
                                pmap[elem_id] = i
                            except (ValueError, IndexError):
                                continue
                except Exception:
                    stats["elements_per_partition"].append(0)

        partition_stats_data.set(stats)
        if pmap:
            partition_map_data.set(pmap)

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
                log_content.set(log_content.get() + f"  {path.name}: {size:,} bytes - OK\n")
            else:
                log_content.set(log_content.get() + f"  {path.name}: MISSING\n")

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
        if not elements:
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

        n_parts = len(elements)
        avg = sum(elements) / n_parts if n_parts > 0 else 0
        labels = [f"P{i}" for i in range(n_parts)]
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

        imbalance = (max(elements) - min(elements)) / avg * 100 if avg > 0 else 0
        fig.update_layout(
            title=f"Load Balance ({n_parts} partitions, imbalance: {imbalance:.1f}%)",
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

        total = sum(elements)
        avg = total / len(elements) if elements else 0
        min_el = min(elements) if elements else 0
        max_el = max(elements) if elements else 0
        imbalance = (max_el - min_el) / avg * 100 if avg > 0 else 0

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
