"""Grid preparation page - shypre/shybas interface."""

import shutil
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.components.file_browser import file_browser_server, file_browser_ui
from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.plot_widget import plot_widget_server, plot_widget_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


@module.ui
def grid_prep_ui():
    """Grid preparation page UI."""
    return ui.div(
        ui.h3("Grid Preparation"),
        ui.p("Convert .grd files to .bas format and analyze grid quality.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # File selection
                ui.h5("Input Grid"),
                file_browser_ui(
                    "grd_file",
                    label="Select .grd File",
                    accept=[".grd"],
                ),
                ui.hr(),
                # Or use path input
                ui.input_text(
                    "grd_path",
                    "Or enter path:",
                    placeholder="/path/to/grid.grd",
                ),
                ui.input_action_button(
                    "load_path_btn",
                    "Load from Path",
                    class_="btn-outline-primary btn-sm mt-1",
                ),
                ui.hr(),
                # shypre options
                ui.h5("shypre Options"),
                ui.input_checkbox("opti", "Optimize (-opti)", value=True),
                ui.input_checkbox("renumber", "Renumber (-renumber)", value=False),
                ui.hr(),
                # Output directory
                ui.input_text(
                    "output_dir",
                    "Output Directory",
                    placeholder="/path/to/output",
                ),
                ui.hr(),
                # Actions
                ui.input_action_button(
                    "run_shypre_btn",
                    "Run shypre",
                    class_="btn-primary w-100 mb-2",
                ),
                ui.input_action_button(
                    "run_shybas_btn",
                    "Run shybas",
                    class_="btn-secondary w-100",
                ),
                width=300,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "Interactive Map",
                    grid_map_ui("grid_map"),
                ),
                ui.nav_panel(
                    "Static Plot",
                    plot_widget_ui("grid_plot"),
                ),
                ui.nav_panel(
                    "Statistics",
                    ui.output_ui("grid_stats"),
                ),
                ui.nav_panel(
                    "Node Inspector",
                    ui.output_ui("node_inspector"),
                ),
                ui.nav_panel(
                    "Log",
                    log_viewer_ui("command_log"),
                ),
            ),
        ),
    )


@module.server
def grid_prep_server(
    input,
    output,
    session,
    config: Config,
):
    """Grid preparation page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # State
    current_grd = reactive.value(None)  # GrdFile object
    current_grd_path = reactive.value(None)  # Path to loaded file
    log_content = reactive.value("")
    output_files = reactive.value([])

    def _handle_file_upload(files):
        """Handle uploaded .grd file."""
        if not files:
            return

        file_info = files[0]
        temp_path = Path(file_info["datapath"])

        try:
            grd = GrdParser.parse_file(temp_path)
            current_grd.set(grd)
            current_grd_path.set(temp_path)
            log_content.set(f"Loaded grid: {file_info['name']}\n"
                          f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}")
        except Exception as e:
            log_content.set(f"Error loading grid: {e}")

    # Initialize child modules
    file_browser_server("grd_file", on_file_selected=_handle_file_upload)
    log_viewer_server("command_log", log_content)
    plot_widget_server("grid_plot", current_grd)
    grid_map_server("grid_map", grd_file=current_grd)

    @reactive.effect
    @reactive.event(input.load_path_btn)
    def _load_from_path():
        path_str = input.grd_path()
        if not path_str:
            return

        try:
            path = config.validate_path(path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            log_content.set(f"Error: {e}")
            return

        try:
            grd = GrdParser.parse_file(path)
            current_grd.set(grd)
            current_grd_path.set(path)
            log_content.set(f"Loaded grid: {path.name}\n"
                          f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}")
        except Exception as e:
            log_content.set(f"Error loading grid: {e}")

    @reactive.effect
    @reactive.event(input.run_shypre_btn)
    async def _run_shypre():
        grd_path = current_grd_path.get()
        if not grd_path:
            log_content.set("Error: No grid file loaded")
            return

        # Determine output directory
        output_dir = input.output_dir() or str(grd_path.parent)
        try:
            output_path = config.validate_path(output_dir)
        except ValueError as e:
            log_content.set(f"Error: {e}")
            return
        output_path.mkdir(parents=True, exist_ok=True)

        # Copy grid file to output directory if needed
        if grd_path.parent != output_path:
            dest_grd = output_path / grd_path.name
            shutil.copy2(grd_path, dest_grd)
            grd_path = dest_grd

        # Build options
        options = []
        if input.opti():
            options.append("-opti")
        if input.renumber():
            options.append("-renumber")

        log_content.set(f"Running shypre on {grd_path.name}...\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            result = await wrapper.run_shypre(
                grd_path,
                output_path,
                options,
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() +
                    f"\n*** shypre completed successfully ***\n"
                    f"Output files: {', '.join(result.output_files)}\n"
                )
                output_files.set(result.output_files)
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** shypre failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    @reactive.effect
    @reactive.event(input.run_shybas_btn)
    async def _run_shybas():
        # Find .bas file
        out_files = output_files.get()
        bas_files = [f for f in out_files if f.endswith(".bas")]

        if not bas_files:
            # Try to find in output directory
            output_dir = input.output_dir()
            if output_dir:
                bas_files = list(Path(output_dir).glob("*.bas"))
                if bas_files:
                    bas_files = [str(bas_files[0])]

        if not bas_files:
            log_content.set("Error: No .bas file found. Run shypre first.")
            return

        bas_path = Path(bas_files[0])
        log_content.set(f"Running shybas on {bas_path.name}...\n")

        def update_log(line):
            current = log_content.get()
            log_content.set(current + line + "\n")

        try:
            result = await wrapper.run_shybas(
                bas_path,
                bas_path.parent,
                ["-quality", "-info"],
                output_callback=update_log,
            )

            if result.success:
                log_content.set(
                    log_content.get() +
                    "\n*** shybas completed successfully ***\n"
                )
            else:
                log_content.set(
                    log_content.get() +
                    f"\n*** shybas failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )

        except Exception as e:
            log_content.set(log_content.get() + f"\nError: {e}\n")

    @render.ui
    def grid_stats():
        grd = current_grd.get()
        if grd is None:
            return ui.p("Load a grid file to see statistics.", class_="text-muted")

        stats = GrdParser.get_statistics(grd)

        return ui.div(
            ui.h5("Grid Statistics"),
            ui.tags.table(
                ui.tags.tbody(
                    ui.tags.tr(
                        ui.tags.th("Nodes"),
                        ui.tags.td(f"{stats['num_nodes']:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Elements"),
                        ui.tags.td(f"{stats['num_elements']:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Triangles"),
                        ui.tags.td(f"{stats['num_triangles']:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Quads"),
                        ui.tags.td(f"{stats['num_quads']:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Boundary Lines"),
                        ui.tags.td(f"{stats['num_lines']:,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Bounds (X)"),
                        ui.tags.td(
                            f"{stats['bounds']['xmin']:.2f} to {stats['bounds']['xmax']:.2f}"
                        ),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Bounds (Y)"),
                        ui.tags.td(
                            f"{stats['bounds']['ymin']:.2f} to {stats['bounds']['ymax']:.2f}"
                        ),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Domain Size"),
                        ui.tags.td(
                            f"{stats['bounds']['width']:.2f} x {stats['bounds']['height']:.2f}"
                        ),
                    ),
                ),
                class_="table table-sm",
            ),
            ui.h6("Depth Range", class_="mt-3"),
            ui.p(
                f"Min: {stats['depth']['min']:.2f}, Max: {stats['depth']['max']:.2f}"
                if stats['depth']['min'] is not None
                else "No depth data"
            ),
            ui.h6("Node Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats['node_types']) or "None"),
            ui.h6("Element Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats['element_types']) or "None"),
            ui.h6("Line Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats['line_types']) or "None"),
        )

    @render.ui
    def node_inspector():
        grd = current_grd.get()
        if grd is None:
            return ui.p("Load a grid file to inspect nodes and elements.", class_="text-muted")

        # Build a searchable node/element summary
        return ui.div(
            ui.h5("Node & Element Inspector"),
            ui.p("Use the Interactive Map tab with 'Nodes' enabled to hover/inspect.",
                 class_="text-muted small"),
            ui.row(
                ui.column(6,
                    ui.h6("Sample Nodes (first 20)"),
                    ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("ID"), ui.tags.th("X"), ui.tags.th("Y"),
                                ui.tags.th("Depth"), ui.tags.th("Type"),
                            ),
                        ),
                        ui.tags.tbody(
                            *[ui.tags.tr(
                                ui.tags.td(str(nid)),
                                ui.tags.td(f"{n.x:.4f}"),
                                ui.tags.td(f"{n.y:.4f}"),
                                ui.tags.td(f"{n.depth:.2f}" if n.depth is not None else "-"),
                                ui.tags.td(str(n.node_type)),
                            ) for nid, n in list(grd.nodes.items())[:20]]
                        ),
                        class_="table table-sm table-striped",
                    ),
                ),
                ui.column(6,
                    ui.h6("Sample Elements (first 20)"),
                    ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("ID"), ui.tags.th("Type"),
                                ui.tags.th("Nodes"), ui.tags.th("Shape"),
                            ),
                        ),
                        ui.tags.tbody(
                            *[ui.tags.tr(
                                ui.tags.td(str(eid)),
                                ui.tags.td(str(e.elem_type)),
                                ui.tags.td(" ".join(str(n) for n in e.nodes)),
                                ui.tags.td("Tri" if e.is_triangle else "Quad" if e.is_quad else f"{len(e.nodes)}-gon"),
                            ) for eid, e in list(grd.elements.items())[:20]]
                        ),
                        class_="table table-sm table-striped",
                    ),
                ),
            ),
        )

    return {
        "current_grd": current_grd,
        "output_files": output_files,
    }
