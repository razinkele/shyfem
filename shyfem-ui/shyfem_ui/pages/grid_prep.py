"""Grid preparation page - shypre/shybas interface."""

import logging
import shutil
from pathlib import Path

import numpy as np
from shiny import module, reactive, render, ui

from shyfem_ui.components.file_browser import file_browser_server, file_browser_ui
from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.plot_widget import plot_widget_server, plot_widget_ui
from shyfem_ui.components.project_select import (
    default_project_file,
    project_dir_select,
    project_file_select,
)
from shyfem_ui.components.sample_data import sample_data_card_ui
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.grid_prep_logic import (  # re-exported for backward compat
    compute_boundary_summary,
    format_element_shape,
    grid_stats_to_json,
)
from shyfem_ui.services.mesh_builder import (  # re-exported for backward compat (test_grid_inspect)
    _get_triangle_vertices,  # noqa: F401
    compute_element_areas,
    compute_element_quality,
    compute_min_angles,
)
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)


@module.ui
def grid_prep_ui() -> ui.Tag:
    """Grid preparation page UI."""
    return ui.div(
        ui.h3("Grid Preparation"),
        ui.p("Convert .grd files to .bas format and analyze grid quality.", class_="text-muted"),
        sample_data_card_ui("grid_prep"),
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
                # Or pick a grid from the active project
                ui.output_ui("grd_path_picker"),
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
                ui.output_ui("output_dir_picker"),
                ui.hr(),
                # Actions + status
                ui.output_ui("shypre_action_area"),
                ui.output_ui("shybas_action_area"),
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
                    ui.input_action_button(
                        "export_stats_btn",
                        "Export Stats JSON",
                        class_="btn-outline-secondary btn-sm mt-2",
                    ),
                ),
                ui.nav_panel(
                    "Node Inspector",
                    ui.output_ui("node_inspector"),
                ),
                ui.nav_panel(
                    "Inspect",
                    ui.output_ui("grid_inspect"),
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
    active_project=None,
    tutorial_context=None,
    current_user=None,
) -> None:
    """Grid preparation page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # A grid path pushed from outside the dropdown's project scan (the bundled
    # Mar Menor sample, a tutorial asset) as ``(abs_path, option_label)``. It
    # cannot be pushed with ui.update_select (a value that is not one of the
    # options is a silent no-op, and the select may not exist yet), so the
    # sample/tutorial effects set this and the picker render injects it as an
    # extra option and preselects it.
    preselect_grd: reactive.Value[tuple[str, str] | None] = reactive.value(None)

    def _ctx():
        proj = active_project.get() if active_project is not None else None
        usr = current_user() if current_user is not None else None
        return proj, usr

    @render.ui
    def grd_path_picker():
        proj, usr = _ctx()
        pre = preselect_grd.get()
        # With no project the helper still offers a pushed sample/tutorial grid.
        return project_file_select(
            "grd_path",
            "Grid File (.grd)",
            (".grd",),
            proj=proj,
            user=usr,
            config=config,
            selected=pre[0] if pre is not None else default_project_file(proj, "grd"),
            extra={pre[0]: pre[1]} if pre is not None else None,
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
            default_label="— same directory as the grid file —",
        )

    # Preselect the tutorial's grid on tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Grid Prep":
            return
        path = Path(ctx["work_dir"]) / ctx["grd_file"]
        preselect_grd.set((str(path), f"Tutorial: {path.name}"))
        tutorial_context.set(None)

    # State
    current_grd = reactive.value(None)  # GrdFile object
    current_grd_path = reactive.value(None)  # Path to loaded file
    log_content = reactive.value("")
    output_files = reactive.value([])
    shypre_running = reactive.value(False)
    shybas_running = reactive.value(False)

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
            log_content.set(
                f"Loaded grid: {file_info['name']}\n"
                f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}"
            )
        except Exception as e:
            logger.exception("Failed to parse uploaded GRD file %r", file_info.get("name"))
            log_content.set(f"Error loading grid: {e}")

    # Initialize child modules
    file_browser_server("grd_file", on_file_selected=_handle_file_upload, accept=[".grd"])
    log_viewer_server("command_log", log_content)
    plot_widget_server("grid_plot", current_grd)
    grid_map_server("grid_map", grd_file=current_grd)

    # Load sample data handler
    @reactive.effect
    @reactive.event(input.load_sample_btn)
    def _load_sample_data():
        grd_path = config.testcases_dir / "mar_menor" / "GRID" / "MM_coarse.grd"
        if not grd_path.exists():
            ui.notification_show(f"Sample grid not found: {grd_path}", type="error", duration=6)
            return
        preselect_grd.set((str(grd_path), f"Sample: {grd_path.name}"))
        try:
            grd = GrdParser.parse_file(grd_path)
            # Mar Menor grid is in UTM zone 30N
            grd.epsg = 32630
            current_grd.set(grd)
            current_grd_path.set(grd_path)
            log_content.set(
                f"Loaded grid: {grd_path.name}\n"
                f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}\n"
                f"CRS: EPSG:32630 (UTM zone 30N)"
            )
            ui.notification_show(
                f"Sample loaded: Mar Menor grid "
                f"(~{grd.num_nodes:,} nodes, ~{grd.num_elements:,} elements)",
                type="message",
                duration=4,
            )
        except Exception as e:
            logger.exception("Failed to load sample Mar Menor grid")
            ui.notification_show(f"Error loading sample grid: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.load_path_btn)
    def _load_from_path():
        path_str = input.grd_path()
        if not path_str:
            return

        _usr = current_user() if current_user is not None else None
        try:
            path = config.confine_path(path_str, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            logger.exception("Invalid GRD file path %r", path_str)
            log_content.set(f"Error: {e}")
            return

        try:
            grd = GrdParser.parse_file(path)
            current_grd.set(grd)
            current_grd_path.set(path)
            log_content.set(
                f"Loaded grid: {path.name}\n"
                f"Nodes: {grd.num_nodes}, Elements: {grd.num_elements}"
            )
        except Exception as e:
            logger.exception("Failed to parse GRD file %s", path_str)
            log_content.set(f"Error loading grid: {e}")

    @reactive.effect
    @reactive.event(input.run_shypre_btn)
    async def _run_shypre():
        _usr = current_user() if current_user is not None else None
        logger.info("User running shypre on %r", str(current_grd_path.get()))
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        grd_path = current_grd_path.get()
        if not grd_path:
            log_content.set("Error: No grid file loaded")
            ui.notification_show(
                "No grid file loaded. Upload or select a .grd file first.",
                type="error",
                duration=5,
            )
            return

        # Determine output directory
        output_dir = input.output_dir() or str(grd_path.parent)
        try:
            output_path = config.confine_path(output_dir, _usr, for_write=True)
        except ValueError as e:
            logger.exception("Invalid shypre output directory %r", output_dir)
            log_content.set(f"Error: {e}")
            ui.notification_show(f"Invalid output directory: {e}", type="error", duration=5)
            return
        output_path.mkdir(parents=True, exist_ok=True)

        # Copy grid file to output directory if needed
        if grd_path.parent != output_path:
            try:
                dest_grd = output_path / grd_path.name
                shutil.copy2(grd_path, dest_grd)
                grd_path = dest_grd
            except OSError as e:
                logger.exception("Failed to copy GRD file to output directory %s", output_path)
                log_content.set(f"Error copying grid file: {e}")
                ui.notification_show(
                    f"Cannot copy grid to output directory: {e}",
                    type="error",
                    duration=5,
                )
                return

        # Build options
        options = []
        if input.opti():
            options.append("-opti")
        if input.renumber():
            options.append("-renumber")

        shypre_running.set(True)
        log_content.set(f"Running shypre on {grd_path.name}...\n")
        ui.notification_show(
            f"shypre started on {grd_path.name}",
            type="message",
            duration=3,
        )

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
                    log_content.get() + f"\n*** shypre completed successfully ***\n"
                    f"Output files: {', '.join(result.output_files)}\n"
                )
                output_files.set(result.output_files)
                ui.notification_show(
                    f"shypre completed — {len(result.output_files)} output file(s)",
                    type="message",
                    duration=5,
                )
            else:
                stderr_preview = (result.stderr or "Unknown error")[:200]
                log_content.set(
                    log_content.get() + f"\n*** shypre failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )
                ui.notification_show(
                    f"shypre failed (exit code {result.return_code}): {stderr_preview}",
                    type="error",
                    duration=8,
                )

        except FileNotFoundError:
            logger.exception("shypre executable not found")
            msg = (
                "shypre executable not found. "
                "Check that SHYFEM is built and the bin/ directory is accessible."
            )
            log_content.set(log_content.get() + f"\nError: {msg}\n")
            ui.notification_show(msg, type="error", duration=8)
        except Exception as e:
            logger.exception("Unexpected error running shypre on %s", grd_path)
            log_content.set(log_content.get() + f"\nError: {e}\n")
            ui.notification_show(f"shypre error: {e}", type="error", duration=8)
        finally:
            shypre_running.set(False)

    @reactive.effect
    @reactive.event(input.run_shybas_btn)
    async def _run_shybas():
        logger.info("User running shybas")
        # Access check: require editor role (fail-closed in server mode).
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return
        # Find .bas file
        out_files = output_files.get()
        bas_files = [f for f in out_files if f.endswith(".bas")]

        if not bas_files:
            # Try to find in output directory — confine to the user's sandbox so
            # the fallback cannot list/use another user's directory (IDOR).
            output_dir = input.output_dir()
            if output_dir:
                try:
                    safe_dir = config.confine_path(output_dir, _usr, for_write=True)
                except (ValueError, FileNotFoundError):
                    safe_dir = None
                if safe_dir is not None and safe_dir.exists():
                    found = list(safe_dir.glob("*.bas"))
                    if found:
                        bas_files = [str(found[0])]

        if not bas_files:
            log_content.set("Error: No .bas file found. Run shypre first.")
            ui.notification_show(
                "No .bas file found. Run shypre first to generate one.",
                type="error",
                duration=5,
            )
            return

        # Confine the resolved .bas before reading it / running the subprocess.
        try:
            bas_path = config.confine_path(bas_files[0], _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return
        shybas_running.set(True)
        log_content.set(f"Running shybas on {bas_path.name}...\n")
        ui.notification_show(
            f"shybas started on {bas_path.name}",
            type="message",
            duration=3,
        )

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
                log_content.set(log_content.get() + "\n*** shybas completed successfully ***\n")
                ui.notification_show(
                    "shybas completed successfully",
                    type="message",
                    duration=5,
                )
            else:
                stderr_preview = (result.stderr or "Unknown error")[:200]
                log_content.set(
                    log_content.get() + f"\n*** shybas failed (code {result.return_code}) ***\n"
                    f"{result.stderr}\n"
                )
                ui.notification_show(
                    f"shybas failed (exit code {result.return_code}): {stderr_preview}",
                    type="error",
                    duration=8,
                )

        except FileNotFoundError:
            logger.exception("shybas executable not found")
            msg = (
                "shybas executable not found. "
                "Check that SHYFEM is built and the bin/ directory is accessible."
            )
            log_content.set(log_content.get() + f"\nError: {msg}\n")
            ui.notification_show(msg, type="error", duration=8)
        except Exception as e:
            logger.exception("Unexpected error running shybas on %s", bas_path)
            log_content.set(log_content.get() + f"\nError: {e}\n")
            ui.notification_show(f"shybas error: {e}", type="error", duration=8)
        finally:
            shybas_running.set(False)

    @render.ui
    def shypre_action_area():
        """Dynamic shypre button — shows spinner while running."""
        running = shypre_running.get()
        if running:
            return ui.div(
                ui.div(
                    ui.tags.span(
                        class_="spinner-border spinner-border-sm me-2",
                        role="status",
                    ),
                    "Running shypre...",
                    class_="btn btn-primary w-100 mb-2 disabled d-flex align-items-center justify-content-center",
                ),
                ui.p(
                    "Check the Log tab for real-time output.",
                    class_="text-muted small mt-1 mb-0",
                ),
            )
        return ui.input_action_button(
            "run_shypre_btn",
            "Run shypre",
            class_="btn-primary w-100 mb-2",
        )

    @render.ui
    def shybas_action_area():
        """Dynamic shybas button — shows spinner while running."""
        running = shybas_running.get()
        if running:
            return ui.div(
                ui.div(
                    ui.tags.span(
                        class_="spinner-border spinner-border-sm me-2",
                        role="status",
                    ),
                    "Running shybas...",
                    class_="btn btn-secondary w-100 disabled d-flex align-items-center justify-content-center",
                ),
                ui.p(
                    "Check the Log tab for real-time output.",
                    class_="text-muted small mt-1 mb-0",
                ),
            )
        return ui.input_action_button(
            "run_shybas_btn",
            "Run shybas",
            class_="btn-secondary w-100",
        )

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
                if stats["depth"]["min"] is not None
                else "No depth data"
            ),
            ui.h6("Node Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats["node_types"]) or "None"),
            ui.h6("Element Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats["element_types"]) or "None"),
            ui.h6("Line Types", class_="mt-3"),
            ui.p(", ".join(str(t) for t in stats["line_types"]) or "None"),
        )

    @reactive.effect
    @reactive.event(input.export_stats_btn)
    async def _export_stats():
        grd = current_grd.get()
        if grd is None:
            ui.notification_show("No grid loaded", type="warning")
            return

        stats = GrdParser.get_statistics(grd)
        grid_name = getattr(grd, "filename", "grid") or "grid"
        if "/" in grid_name or "\\" in grid_name:
            grid_name = Path(grid_name).stem

        json_str = grid_stats_to_json(stats, grid_name)

        import base64

        b64 = base64.b64encode(json_str.encode("utf-8")).decode("ascii")
        filename = f"grid_stats_{grid_name}.json"
        await session.send_custom_message(
            "download_file",
            {"href": f"data:application/json;base64,{b64}", "filename": filename},
        )
        ui.notification_show(f"Exported {filename}", type="message", duration=3)

    @render.ui
    def node_inspector():
        grd = current_grd.get()
        if grd is None:
            return ui.p("Load a grid file to inspect nodes and elements.", class_="text-muted")

        # Build a searchable node/element summary
        return ui.div(
            ui.h5("Node & Element Inspector"),
            ui.p(
                "Use the Interactive Map tab with 'Nodes' enabled to hover/inspect.",
                class_="text-muted small",
            ),
            ui.row(
                ui.column(
                    6,
                    ui.h6("Sample Nodes (first 20)"),
                    ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("ID"),
                                ui.tags.th("X"),
                                ui.tags.th("Y"),
                                ui.tags.th("Depth"),
                                ui.tags.th("Type"),
                            ),
                        ),
                        ui.tags.tbody(
                            *[
                                ui.tags.tr(
                                    ui.tags.td(str(nid)),
                                    ui.tags.td(f"{n.x:.4f}"),
                                    ui.tags.td(f"{n.y:.4f}"),
                                    ui.tags.td(f"{n.depth:.2f}" if n.depth is not None else "-"),
                                    ui.tags.td(str(n.node_type)),
                                )
                                for nid, n in list(grd.nodes.items())[:20]
                            ]
                        ),
                        class_="table table-sm table-striped",
                    ),
                ),
                ui.column(
                    6,
                    ui.h6("Sample Elements (first 20)"),
                    ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("ID"),
                                ui.tags.th("Type"),
                                ui.tags.th("Nodes"),
                                ui.tags.th("Shape"),
                            ),
                        ),
                        ui.tags.tbody(
                            *[
                                ui.tags.tr(
                                    ui.tags.td(str(eid)),
                                    ui.tags.td(str(e.elem_type)),
                                    ui.tags.td(" ".join(str(n) for n in e.nodes)),
                                    ui.tags.td(format_element_shape(e)),
                                )
                                for eid, e in list(grd.elements.items())[:20]
                            ]
                        ),
                        class_="table table-sm table-striped",
                    ),
                ),
            ),
        )

    @render.ui
    def grid_inspect():
        grd = current_grd.get()
        if grd is None:
            return ui.p("Load a grid file to see inspection results.", class_="text-muted")

        sections = []

        # --- 1. Quality Summary ---
        qdata = compute_element_quality(grd)
        if qdata["stats"]:
            qs = qdata["stats"]
            # Text histogram
            bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
            hist, _ = np.histogram(qdata["qualities"], bins=bins)
            max_count = max(hist) if max(hist) > 0 else 1
            hist_lines = []
            for i in range(len(hist)):
                lo = bins[i]
                hi = bins[i + 1]
                bar_len = int(40 * hist[i] / max_count)
                label = f"{lo:.1f}-{min(hi, 1.0):.1f}"
                hist_lines.append(f"{label:>9s} |{'█' * bar_len} {hist[i]}")
            hist_text = "\n".join(hist_lines)

            status_class = (
                "text-success"
                if qs["below_03"] == 0
                else "text-warning" if qs["below_03"] < qs["count"] * 0.05 else "text-danger"
            )
            sections.append(
                ui.div(
                    ui.h5("Quality Summary (min/max side ratio)"),
                    ui.tags.table(
                        ui.tags.tbody(
                            ui.tags.tr(ui.tags.th("Count"), ui.tags.td(f"{qs['count']:,}")),
                            ui.tags.tr(ui.tags.th("Min"), ui.tags.td(f"{qs['min']:.4f}")),
                            ui.tags.tr(ui.tags.th("Max"), ui.tags.td(f"{qs['max']:.4f}")),
                            ui.tags.tr(ui.tags.th("Mean"), ui.tags.td(f"{qs['mean']:.4f}")),
                            ui.tags.tr(ui.tags.th("Median"), ui.tags.td(f"{qs['median']:.4f}")),
                            ui.tags.tr(ui.tags.th("Std Dev"), ui.tags.td(f"{qs['std']:.4f}")),
                            ui.tags.tr(
                                ui.tags.th("Below 0.3"),
                                ui.tags.td(
                                    ui.span(str(qs["below_03"]), class_=status_class),
                                    f" ({100 * qs['below_03'] / qs['count']:.1f}%)",
                                ),
                            ),
                            ui.tags.tr(
                                ui.tags.th("Below 0.5"),
                                ui.tags.td(
                                    f"{qs['below_05']} ({100 * qs['below_05'] / qs['count']:.1f}%)"
                                ),
                            ),
                        ),
                        class_="table table-sm",
                    ),
                    ui.h6("Distribution"),
                    ui.tags.pre(hist_text, style="font-size: 0.8rem;"),
                    class_="mb-4",
                )
            )
        else:
            sections.append(ui.p("No triangles found for quality analysis.", class_="text-muted"))

        # --- 2. Element Area Statistics ---
        adata = compute_element_areas(grd)
        if adata["stats"]:
            a_s = adata["stats"]
            # Detect units
            cs = grd.coordinate_system or grd.detect_coordinate_system()
            area_unit = "deg\u00b2" if cs.is_geographic else "m\u00b2"
            sections.append(
                ui.div(
                    ui.h5("Element Area Statistics"),
                    ui.tags.table(
                        ui.tags.tbody(
                            ui.tags.tr(ui.tags.th("Count"), ui.tags.td(f"{a_s['count']:,}")),
                            ui.tags.tr(
                                ui.tags.th("Min"), ui.tags.td(f"{a_s['min']:.6g} {area_unit}")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Max"), ui.tags.td(f"{a_s['max']:.6g} {area_unit}")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Mean"), ui.tags.td(f"{a_s['mean']:.6g} {area_unit}")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Median"), ui.tags.td(f"{a_s['median']:.6g} {area_unit}")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Std Dev"), ui.tags.td(f"{a_s['std']:.6g} {area_unit}")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Area Ratio (max/min)"),
                                ui.tags.td(f"{a_s['area_ratio']:.1f}x"),
                            ),
                        ),
                        class_="table table-sm",
                    ),
                    class_="mb-4",
                )
            )
        else:
            sections.append(ui.p("No triangles found for area analysis.", class_="text-muted"))

        # --- 3. Minimum Angle Analysis ---
        mdata = compute_min_angles(grd)
        if mdata["stats"]:
            ms = mdata["stats"]
            if ms["min"] >= 30:
                badge_cls = "bg-success"
                badge_text = "Excellent"
            elif ms["min"] >= 20:
                badge_cls = "bg-warning text-dark"
                badge_text = "Acceptable"
            else:
                badge_cls = "bg-danger"
                badge_text = "Poor"
            sections.append(
                ui.div(
                    ui.h5(
                        "Minimum Angle Analysis ",
                        ui.span(badge_text, class_=f"badge {badge_cls}"),
                    ),
                    ui.tags.table(
                        ui.tags.tbody(
                            ui.tags.tr(ui.tags.th("Count"), ui.tags.td(f"{ms['count']:,}")),
                            ui.tags.tr(ui.tags.th("Min"), ui.tags.td(f"{ms['min']:.2f}\u00b0")),
                            ui.tags.tr(ui.tags.th("Max"), ui.tags.td(f"{ms['max']:.2f}\u00b0")),
                            ui.tags.tr(ui.tags.th("Mean"), ui.tags.td(f"{ms['mean']:.2f}\u00b0")),
                            ui.tags.tr(
                                ui.tags.th("Median"), ui.tags.td(f"{ms['median']:.2f}\u00b0")
                            ),
                            ui.tags.tr(
                                ui.tags.th("Below 20\u00b0"),
                                ui.tags.td(
                                    f"{ms['below_20']} ({100 * ms['below_20'] / ms['count']:.1f}%)"
                                ),
                            ),
                        ),
                        class_="table table-sm",
                    ),
                    ui.p(
                        "FEM stability requires minimum angles above 20\u00b0; "
                        "angles above 30\u00b0 are preferred.",
                        class_="text-muted small",
                    ),
                    class_="mb-4",
                )
            )
        else:
            sections.append(ui.p("No triangles found for angle analysis.", class_="text-muted"))

        # --- 4. Boundary Assignments ---
        bdata = compute_boundary_summary(grd)
        if bdata:
            rows = [
                ui.tags.tr(
                    ui.tags.td(str(b["line_id"])),
                    ui.tags.td(str(b["line_type"])),
                    ui.tags.td(str(b["node_count"])),
                    ui.tags.td(b["node_range_str"]),
                )
                for b in bdata
            ]
            sections.append(
                ui.div(
                    ui.h5("Boundary Assignments"),
                    ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("Line ID"),
                                ui.tags.th("Type"),
                                ui.tags.th("Node Count"),
                                ui.tags.th("Node Range"),
                            ),
                        ),
                        ui.tags.tbody(*rows),
                        class_="table table-sm table-striped",
                    ),
                )
            )
        else:
            sections.append(
                ui.div(
                    ui.h5("Boundary Assignments"),
                    ui.p("No boundary lines defined in this grid.", class_="text-muted"),
                )
            )

        return ui.div(*sections)

    return {
        "current_grd": current_grd,
        "output_files": output_files,
    }
