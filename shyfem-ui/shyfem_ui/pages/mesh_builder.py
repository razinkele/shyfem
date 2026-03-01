"""Mesh builder page — 5-step wizard for creating FEM meshes."""

import logging
from pathlib import Path

import numpy as np
from shiny import module, reactive, render, ui

from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.services.mesh_builder import (
    compute_mesh_stats,
    estimate_element_count,
    export_grd,
    extract_boundary_zero_points,
    import_boundaries,
    interpolate_bathymetry_scipy,
    interpolate_bathymetry_shybas,
    load_bathymetry_contours,
    load_bathymetry_file,
    reduce_boundary,
    smooth_boundary,
    triangulate,
    validate_boundary,
)
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@module.ui
def mesh_builder_ui():
    """Mesh builder page UI — 5-step wizard."""
    return ui.div(
        ui.h3("Mesh Builder"),
        ui.p(
            "Create simulation-ready meshes from coastline data in 5 steps.",
            class_="text-muted",
        ),
        ui.layout_sidebar(
            ui.sidebar(
                # Step navigation
                ui.h5("Steps"),
                ui.input_radio_buttons(
                    "wizard_step",
                    "",
                    choices={
                        "import": "1. Import Boundaries",
                        "refine": "2. Refine Boundaries",
                        "mesh": "3. Generate Mesh",
                        "bathy": "4. Interpolate Bathymetry",
                        "export": "5. Export",
                    },
                    selected="import",
                ),
                ui.hr(),
                # Status summary
                ui.output_ui("status_summary"),
                width=280,
            ),
            # Main content — one panel per step
            ui.navset_card_tab(
                ui.nav_panel(
                    "Wizard",
                    ui.output_ui("wizard_content"),
                ),
                ui.nav_panel(
                    "Preview",
                    grid_map_ui("mesh_preview"),
                ),
                ui.nav_panel(
                    "Log",
                    log_viewer_ui("build_log"),
                ),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


@module.server
def mesh_builder_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
):
    """Mesh builder page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # --- State ---
    boundary_grd = reactive.value(None)  # After import
    refined_grd = reactive.value(None)  # After smooth/reduce
    mesh_grd = reactive.value(None)  # After triangulation
    final_grd = reactive.value(None)  # After bathymetry
    preview_grd = reactive.value(None)  # Currently shown in map
    log_content = reactive.value("")
    bathy_data = reactive.value(None)  # Loaded bathymetry points

    # --- Initialize child modules ---
    log_viewer_server("build_log", log_content)
    grid_map_server("mesh_preview", grd_file=preview_grd)

    def _log(msg: str) -> None:
        log_content.set(log_content.get() + msg + "\n")

    def _prepare_upload_files(files: list[dict]) -> Path:
        """Reassemble uploaded files into a single directory for fiona.

        Shiny renames uploads to temp names (0.shp, 1.shx, etc.), breaking
        multi-file formats like Shapefiles.  This copies them into a temp
        directory with their original names so fiona can find companions.
        Also handles .zip archives.
        """
        import shutil
        import tempfile
        import zipfile

        work = Path(tempfile.mkdtemp(prefix="mesh_import_"))

        # Check for zip first
        for f in files:
            if f["name"].lower().endswith(".zip"):
                with zipfile.ZipFile(f["datapath"], "r") as zf:
                    zf.extractall(work)
                # Find the .shp inside
                shps = list(work.rglob("*.shp"))
                if shps:
                    return shps[0]
                # Maybe it's a GeoJSON or GPKG inside the zip
                for ext in (".geojson", ".json", ".gpkg"):
                    found = list(work.rglob(f"*{ext}"))
                    if found:
                        return found[0]
                raise ValueError("No .shp, .geojson, or .gpkg found inside zip")

        # Copy all files to work dir with original names
        for f in files:
            dest = work / f["name"]
            shutil.copy2(f["datapath"], dest)

        # Find the primary file to open
        for ext in (".shp", ".geojson", ".json", ".gpkg"):
            found = list(work.glob(f"*{ext}"))
            if found:
                return found[0]

        # Fallback: return the first file
        return work / files[0]["name"]

    # --- Status summary ---
    @render.ui
    def status_summary():
        items = []
        bgrd = boundary_grd.get()
        if bgrd:
            items.append(
                ui.div(
                    ui.tags.span("Boundary: ", class_="fw-bold"),
                    f"{bgrd.num_nodes} nodes, {bgrd.num_lines} lines",
                    class_="small mb-1",
                )
            )
        rgrd = refined_grd.get()
        if rgrd:
            items.append(
                ui.div(
                    ui.tags.span("Refined: ", class_="fw-bold"),
                    f"{rgrd.num_nodes} nodes",
                    class_="small mb-1",
                )
            )
        mgrd = mesh_grd.get()
        if mgrd:
            items.append(
                ui.div(
                    ui.tags.span("Mesh: ", class_="fw-bold"),
                    f"{mgrd.num_nodes} nodes, {mgrd.num_elements} elements",
                    class_="small mb-1",
                )
            )
        fgrd = final_grd.get()
        if fgrd:
            depths = [n.depth for n in fgrd.nodes.values() if n.depth is not None]
            if depths:
                items.append(
                    ui.div(
                        ui.tags.span("Bathymetry: ", class_="fw-bold"),
                        f"depth {min(depths):.1f} to {max(depths):.1f}",
                        class_="small mb-1",
                    )
                )
        if not items:
            return ui.p("No data loaded yet.", class_="text-muted small")
        return ui.div(*items)

    # --- Wizard content router ---
    @render.ui
    def wizard_content():
        step = input.wizard_step()
        if step == "import":
            return _step_import_ui()
        elif step == "refine":
            return _step_refine_ui()
        elif step == "mesh":
            return _step_mesh_ui()
        elif step == "bathy":
            return _step_bathy_ui()
        elif step == "export":
            return _step_export_ui()
        return ui.p("Select a step.")

    # --- Step 1: Import Boundaries ---
    def _step_import_ui():
        return ui.div(
            ui.h4("Step 1: Import Boundaries"),
            ui.p(
                "Upload a GeoJSON, Shapefile, or GeoPackage file containing "
                "coastline or domain boundary polygons.",
                class_="text-muted",
            ),
            ui.input_file(
                "boundary_file",
                "Upload Boundary File",
                accept=[".geojson", ".json", ".shp", ".shx", ".dbf", ".prj", ".cpg", ".gpkg", ".zip", "application/geopackage+sqlite3", "application/geo+json"],
                multiple=True,
            ),
            ui.p(
                "For Shapefiles, select all companion files (.shp, .shx, .dbf, .prj) "
                "together, or upload a .zip archive containing them.",
                class_="text-muted small",
            ),
            ui.output_ui("import_result"),
        )

    @reactive.effect
    @reactive.event(input.boundary_file)
    def _on_boundary_upload():
        files = input.boundary_file()
        if not files:
            return
        try:
            open_path = _prepare_upload_files(files)
            grd = import_boundaries(open_path)
            issues = validate_boundary(grd)
            boundary_grd.set(grd)
            refined_grd.set(grd)  # Start refine step with same data
            preview_grd.set(grd)
            names = ", ".join(f["name"] for f in files)
            _log(f"Imported boundary: {names}")
            _log(f"  Nodes: {grd.num_nodes}, Lines: {grd.num_lines}")
            if issues:
                for issue in issues:
                    _log(f"  {issue}")
            if grd.parse_warnings:
                for w in grd.parse_warnings:
                    _log(f"  Warning: {w}")
            ui.notification_show(
                f"Imported {grd.num_nodes} nodes, {grd.num_lines} boundary lines",
                type="message",
                duration=3,
            )
        except Exception as e:
            _log(f"Error importing boundary: {e}")
            ui.notification_show(f"Import error: {e}", type="error", duration=5)

    @render.ui
    def import_result():
        grd = boundary_grd.get()
        if grd is None:
            return ui.p("No boundary loaded.", class_="text-muted")
        issues = validate_boundary(grd)
        alerts = []
        for issue in issues:
            cls = "alert-danger" if issue.startswith("ERROR") else "alert-warning"
            alerts.append(ui.div(issue, class_=f"alert {cls} py-1 px-2 mb-1 small"))
        return ui.div(
            ui.div(
                ui.tags.strong(f"Loaded: {grd.num_nodes} nodes, {grd.num_lines} lines"),
                class_="mb-2",
            ),
            *alerts,
            ui.input_action_button(
                "next_to_refine",
                "Next: Refine Boundaries",
                class_="btn-primary mt-2",
            ),
        )

    @reactive.effect
    @reactive.event(input.next_to_refine)
    def _go_to_refine():
        ui.update_radio_buttons("wizard_step", selected="refine")

    # --- Step 2: Refine Boundaries ---
    def _step_refine_ui():
        grd = refined_grd.get()
        if grd is None:
            return ui.p("Import boundaries first (Step 1).", class_="text-muted")
        line_choices = {
            str(lid): f"Line {lid} (type={line.line_type}, {len(line.nodes)} pts)"
            for lid, line in sorted(grd.lines.items())
        }
        return ui.div(
            ui.h4("Step 2: Refine Boundaries"),
            ui.p("Smooth or simplify boundary lines.", class_="text-muted"),
            ui.row(
                ui.column(
                    6,
                    ui.input_select("refine_line", "Select Line", choices=line_choices),
                    ui.input_select(
                        "smooth_method",
                        "Smooth Method",
                        choices={"chaikin": "Chaikin (corner-cutting)", "gaussian": "Gaussian"},
                    ),
                    ui.input_slider("smooth_iterations", "Iterations", min=1, max=5, value=2),
                    ui.input_action_button(
                        "apply_smooth", "Apply Smoothing", class_="btn-outline-primary btn-sm mb-2"
                    ),
                ),
                ui.column(
                    6,
                    ui.input_slider("reduce_tolerance", "Simplify Tolerance", min=0.0, max=100.0, value=0.0, step=0.1),
                    ui.input_action_button(
                        "apply_reduce", "Apply Simplification", class_="btn-outline-primary btn-sm mb-2"
                    ),
                ),
            ),
            ui.input_action_button(
                "reset_refine", "Reset to Original", class_="btn-outline-secondary btn-sm me-2"
            ),
            ui.input_action_button(
                "next_to_mesh", "Next: Generate Mesh", class_="btn-primary mt-2"
            ),
        )

    @reactive.effect
    @reactive.event(input.apply_smooth)
    def _on_smooth():
        grd = refined_grd.get()
        if grd is None:
            return
        line_id = int(input.refine_line())
        method = input.smooth_method()
        iterations = input.smooth_iterations()
        try:
            new_grd = smooth_boundary(grd, line_id, method=method, iterations=iterations)
            refined_grd.set(new_grd)
            preview_grd.set(new_grd)
            new_count = len(new_grd.lines[line_id].nodes)
            _log(f"Smoothed line {line_id}: {method}, {iterations} iterations → {new_count} nodes")
        except Exception as e:
            _log(f"Smoothing error: {e}")
            ui.notification_show(str(e), type="error", duration=3)

    @reactive.effect
    @reactive.event(input.apply_reduce)
    def _on_reduce():
        grd = refined_grd.get()
        if grd is None:
            return
        line_id = int(input.refine_line())
        tolerance = input.reduce_tolerance()
        try:
            new_grd = reduce_boundary(grd, line_id, tolerance=tolerance)
            refined_grd.set(new_grd)
            preview_grd.set(new_grd)
            new_count = len(new_grd.lines[line_id].nodes)
            _log(f"Reduced line {line_id}: tolerance={tolerance} → {new_count} nodes")
        except Exception as e:
            _log(f"Reduction error: {e}")
            ui.notification_show(str(e), type="error", duration=3)

    @reactive.effect
    @reactive.event(input.reset_refine)
    def _on_reset_refine():
        bgrd = boundary_grd.get()
        if bgrd:
            refined_grd.set(bgrd)
            preview_grd.set(bgrd)
            _log("Reset boundaries to original import.")

    @reactive.effect
    @reactive.event(input.next_to_mesh)
    def _go_to_mesh():
        ui.update_radio_buttons("wizard_step", selected="mesh")

    # --- Step 3: Generate Mesh ---
    def _step_mesh_ui():
        grd = refined_grd.get()
        no_boundary = grd is None
        return ui.div(
            ui.h4("Step 3: Generate Mesh"),
            ui.p("Configure triangulation method, mesh density and quality constraints.", class_="text-muted"),
            ui.div(
                "Import boundaries first (Steps 1-2).",
                class_="alert alert-info py-2 px-3 small",
            ) if no_boundary else ui.span(),
            ui.input_select(
                "mesh_method",
                "Mesh Generation Method",
                choices={
                    "delaunay_quality": "Constrained Delaunay — quality mesh (Triangle)",
                    "delaunay_conforming": "Conforming Delaunay — no area constraint (Triangle)",
                    "delaunay_minimal": "Minimal Delaunay — fewest triangles (Triangle)",
                },
                selected="delaunay_quality",
            ),
            ui.row(
                ui.column(
                    6,
                    ui.input_numeric(
                        "max_area",
                        "Max Triangle Area",
                        value=None,
                        min=0.001,
                    ),
                    ui.output_ui("element_estimate"),
                ),
                ui.column(
                    6,
                    ui.input_slider(
                        "min_angle",
                        "Min Angle (degrees)",
                        min=10,
                        max=33,
                        value=20,
                    ),
                    ui.p(
                        "Higher values produce more uniform triangles but may "
                        "increase element count. Max theoretical limit is 33.9°.",
                        class_="text-muted small",
                    ),
                ),
            ),
            ui.input_action_button(
                "generate_mesh",
                "Generate Mesh",
                class_="btn-primary w-100 mt-2 mb-2",
            ),
            ui.output_ui("mesh_stats_display"),
            ui.input_action_button(
                "next_to_bathy",
                "Next: Interpolate Bathymetry",
                class_="btn-primary mt-2",
            ),
        )

    @render.ui
    def element_estimate():
        grd = refined_grd.get()
        area = input.max_area()
        if grd is None or area is None or area <= 0:
            return ui.p("Enter max area to see estimate.", class_="text-muted small")
        count = estimate_element_count(grd, area)
        return ui.p(f"Estimated elements: ~{count:,}", class_="small text-info")

    @reactive.effect
    @reactive.event(input.generate_mesh)
    def _on_generate_mesh():
        grd = refined_grd.get()
        if grd is None:
            ui.notification_show("No boundary data to mesh.", type="warning")
            return
        method = input.mesh_method()
        max_area = input.max_area()
        min_angle = input.min_angle()
        try:
            # Interpret method choice
            if method == "delaunay_minimal":
                # Minimal: PSLG only, no quality or area constraints
                eff_area = None
                eff_angle = 0.0
            elif method == "delaunay_conforming":
                # Conforming: quality constraint but no area limit
                eff_area = None
                eff_angle = min_angle
            else:
                # Quality: full constraints
                eff_area = max_area
                eff_angle = min_angle

            _log(f"Generating mesh: method={method}, max_area={eff_area}, min_angle={eff_angle}°...")
            new_mesh = triangulate(grd, max_area=eff_area, min_angle=eff_angle)
            mesh_grd.set(new_mesh)
            preview_grd.set(new_mesh)
            _log(f"Mesh generated: {new_mesh.num_nodes} nodes, {new_mesh.num_elements} elements")
            ui.notification_show(
                f"Generated {new_mesh.num_elements} elements",
                type="message",
                duration=3,
            )
        except Exception as e:
            _log(f"Mesh generation error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)

    @render.ui
    def mesh_stats_display():
        grd = mesh_grd.get()
        if grd is None:
            return ui.p("Generate a mesh to see statistics.", class_="text-muted small")
        stats = compute_mesh_stats(grd)
        rows = [
            ("Nodes", f"{stats['node_count']:,}"),
            ("Elements", f"{stats['elem_count']:,}"),
        ]
        if stats.get("quality"):
            q = stats["quality"]
            rows.append(("Quality (min/mean)", f"{q['min']:.3f} / {q['mean']:.3f}"))
        if stats.get("areas"):
            a = stats["areas"]
            rows.append(("Area (min/max)", f"{a['min']:.2f} / {a['max']:.2f}"))
        if stats.get("min_angles"):
            ang = stats["min_angles"]
            rows.append(("Min Angle (min/mean)", f"{ang['min']:.1f}° / {ang['mean']:.1f}°"))
        return ui.tags.table(
            ui.tags.tbody(
                *[
                    ui.tags.tr(
                        ui.tags.td(label, class_="pe-3 fw-bold"),
                        ui.tags.td(value),
                    )
                    for label, value in rows
                ]
            ),
            class_="table table-sm table-borderless mb-0",
        )

    @reactive.effect
    @reactive.event(input.next_to_bathy)
    def _go_to_bathy():
        ui.update_radio_buttons("wizard_step", selected="bathy")

    # --- Step 4: Interpolate Bathymetry ---
    def _step_bathy_ui():
        no_mesh = mesh_grd.get() is None
        return ui.div(
            ui.h4("Step 4: Interpolate Bathymetry"),
            ui.p(
                "Upload depth data and interpolate values onto mesh nodes.",
                class_="text-muted",
            ),
            ui.div(
                "Generate a mesh first (Step 3).",
                class_="alert alert-info py-2 px-3 small",
            ) if no_mesh else ui.span(),
            # --- Bathymetry source type ---
            ui.h5("Depth Data Source"),
            ui.input_radio_buttons(
                "bathy_source",
                "",
                choices={
                    "points": "Point cloud (CSV / XYZ / GeoTIFF)",
                    "contours": "Contour isobaths (SHP / GeoJSON / GPKG)",
                },
                selected="points",
                inline=True,
            ),
            # --- Point cloud upload ---
            ui.panel_conditional(
                "input.bathy_source === 'points'",
                ui.input_file(
                    "bathy_file",
                    "Upload Bathymetry Points",
                    accept=[".csv", ".xyz", ".txt", ".tif", ".tiff"],
                    multiple=False,
                ),
                ui.p(
                    "Format: one point per line as x, y, depth (comma or space separated). "
                    "GeoTIFF rasters are also supported.",
                    class_="text-muted small",
                ),
            ),
            # --- Contour isobath upload ---
            ui.panel_conditional(
                "input.bathy_source === 'contours'",
                ui.input_file(
                    "bathy_contour_file",
                    "Upload Contour Isobaths",
                    accept=[".shp", ".shx", ".dbf", ".prj", ".cpg",
                            ".geojson", ".json", ".gpkg", ".zip"],
                    multiple=True,
                ),
                ui.p(
                    "Vector file with LineString features and a depth attribute "
                    "(e.g. depth, elev, contour, z). For Shapefiles, select all "
                    "companion files together or upload a .zip.",
                    class_="text-muted small",
                ),
                ui.input_text(
                    "contour_depth_attr",
                    "Depth attribute name",
                    value="depth",
                    placeholder="depth, elev, z, contour...",
                ),
                ui.input_numeric(
                    "contour_sample_dist",
                    "Resample distance (0 = use vertices only)",
                    value=0,
                    min=0,
                ),
            ),
            ui.output_ui("bathy_loaded_info"),
            ui.hr(),
            # --- Interpolation method ---
            ui.h5("Interpolation Method"),
            ui.input_select(
                "bathy_method",
                "Method",
                choices={
                    "linear": "Linear (scipy griddata)",
                    "nearest": "Nearest neighbor (scipy)",
                    "cubic": "Cubic (scipy griddata)",
                    "idw": "IDW — inverse distance weighting (k=8 neighbors)",
                    "rbf": "RBF — thin-plate spline (smooth, extrapolates)",
                    "cloughtocher": "Clough-Tocher — C1 cubic (smooth, no overshoot)",
                    "shybas": "shybas -bfile (SHYFEM binary)",
                },
                selected="linear",
            ),
            ui.div(
                ui.tags.strong("Method guide", class_="d-block mb-1"),
                ui.tags.ul(
                    ui.tags.li(ui.tags.strong("Linear"), " — smooth, good general-purpose default."),
                    ui.tags.li(ui.tags.strong("Nearest"), " — fast, produces discontinuous steps between data points."),
                    ui.tags.li(ui.tags.strong("Cubic"), " — smooth but can overshoot between sparse data."),
                    ui.tags.li(ui.tags.strong("IDW"), " — inverse-distance weighted average of 8 nearest neighbors."),
                    ui.tags.li(
                        ui.tags.strong("RBF (thin-plate spline)"),
                        " — globally smooth surface that ",
                        ui.tags.em("naturally extrapolates"),
                        " beyond the data extent. Best for sparse bathymetry and coastal edges.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("Clough-Tocher (C1 cubic)"),
                        " — piecewise cubic with continuous first derivatives. "
                        "Smoother than Cubic with less overshoot. Falls back to "
                        "nearest-neighbor outside the data hull.",
                    ),
                    ui.tags.li(ui.tags.strong("shybas"), " — SHYFEM's built-in Fortran interpolation."),
                    class_="small mb-1 ps-3",
                ),
                ui.tags.strong("Recommendation for contour isobaths:", class_="d-block mt-2 mb-1"),
                ui.p(
                    "Use RBF + boundary zero for best results. RBF smoothly "
                    "interpolates between contour lines and extrapolates to the "
                    "shoreline, while the boundary = 0 constraint anchors the "
                    "coast. Use Clough-Tocher as a safer alternative if RBF "
                    "overshoots in deep basins with very sparse contours.",
                ),
                class_="alert alert-light border small py-2 px-3 mb-2",
            ),
            ui.input_checkbox(
                "use_boundary_zero",
                "Use boundary as depth = 0 (coastline constraint)",
                value=True,
            ),
            ui.p(
                "Injects coastline boundary nodes as depth = 0 points before "
                "interpolation, forcing the shoreline to zero depth and "
                "preventing unrealistic values near shore.",
                class_="text-muted small",
            ),
            ui.input_action_button(
                "interpolate_btn",
                "Interpolate Bathymetry",
                class_="btn-primary w-100 mt-2 mb-2",
            ),
            ui.output_ui("bathy_stats_display"),
            ui.input_action_button(
                "next_to_export",
                "Next: Export",
                class_="btn-primary mt-2",
            ),
        )

    @render.ui
    def bathy_loaded_info():
        data = bathy_data.get()
        if data is None:
            return ui.p("No depth points loaded yet.", class_="text-muted small")
        return ui.div(
            ui.tags.table(
                ui.tags.tbody(
                    ui.tags.tr(
                        ui.tags.td("Points loaded", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{len(data):,}"),
                    ),
                    ui.tags.tr(
                        ui.tags.td("X range", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{data[:,0].min():.4f} — {data[:,0].max():.4f}"),
                    ),
                    ui.tags.tr(
                        ui.tags.td("Y range", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{data[:,1].min():.4f} — {data[:,1].max():.4f}"),
                    ),
                    ui.tags.tr(
                        ui.tags.td("Depth range", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{data[:,2].min():.2f} — {data[:,2].max():.2f}"),
                    ),
                ),
                class_="table table-sm table-borderless mb-0",
            ),
            class_="mt-2",
        )

    @reactive.effect
    @reactive.event(input.bathy_file)
    def _on_bathy_upload():
        files = input.bathy_file()
        if not files:
            return
        file_info = files[0]
        temp_path = Path(file_info["datapath"])
        try:
            data = load_bathymetry_file(temp_path)
            bathy_data.set(data)
            _log(f"Loaded bathymetry points: {file_info['name']} ({len(data)} points)")
            _log(f"  Depth range: {data[:,2].min():.2f} to {data[:,2].max():.2f}")
            ui.notification_show(
                f"Loaded {len(data)} bathymetry points", type="message", duration=3
            )
        except Exception as e:
            _log(f"Error loading bathymetry: {e}")
            ui.notification_show(f"Load error: {e}", type="error", duration=5)

    @reactive.effect
    @reactive.event(input.bathy_contour_file)
    def _on_contour_upload():
        files = input.bathy_contour_file()
        if not files:
            return
        try:
            open_path = _prepare_upload_files(files)
            depth_attr = input.contour_depth_attr() or "depth"
            sample_dist = input.contour_sample_dist()
            sample_dist = sample_dist if sample_dist and sample_dist > 0 else None
            data = load_bathymetry_contours(
                open_path, depth_attr=depth_attr, sample_distance=sample_dist
            )
            bathy_data.set(data)
            names = ", ".join(f["name"] for f in files)
            _log(f"Loaded contour isobaths: {names} ({len(data)} points)")
            _log(f"  Depth range: {data[:,2].min():.2f} to {data[:,2].max():.2f}")
            ui.notification_show(
                f"Extracted {len(data)} points from contour isobaths",
                type="message",
                duration=3,
            )
        except Exception as e:
            _log(f"Error loading contours: {e}")
            ui.notification_show(f"Contour load error: {e}", type="error", duration=5)

    @reactive.effect
    @reactive.event(input.interpolate_btn)
    async def _on_interpolate():
        grd = mesh_grd.get()
        data = bathy_data.get()
        if grd is None or data is None:
            ui.notification_show("Load mesh and bathymetry data first.", type="warning")
            return
        method = input.bathy_method()
        boundary_zero = input.use_boundary_zero()
        try:
            _log(f"Interpolating bathymetry: method={method}, boundary_zero={boundary_zero}...")
            if method == "shybas":
                work_dir = Path(config.work_dir) / "mesh_builder"
                result_grd = await interpolate_bathymetry_shybas(
                    grd, Path("bathy_temp.xyz"), work_dir, wrapper
                )
            else:
                result_grd = interpolate_bathymetry_scipy(
                    grd, data, method=method, use_boundary_zero=boundary_zero
                )
            final_grd.set(result_grd)
            preview_grd.set(result_grd)
            depths = [n.depth for n in result_grd.nodes.values() if n.depth is not None]
            if depths:
                _log(f"Bathymetry interpolated: depth {min(depths):.2f} to {max(depths):.2f}")
            ui.notification_show("Bathymetry interpolated", type="message", duration=3)
        except Exception as e:
            _log(f"Interpolation error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)

    @render.ui
    def bathy_stats_display():
        grd = final_grd.get()
        if grd is None:
            return ui.p("Interpolate to see depth statistics.", class_="text-muted small")
        depths = [n.depth for n in grd.nodes.values() if n.depth is not None]
        if not depths:
            return ui.p("No depth data.", class_="text-muted small")
        darr = np.array(depths)
        return ui.tags.table(
            ui.tags.tbody(
                ui.tags.tr(ui.tags.td("Min depth", class_="pe-3 fw-bold"), ui.tags.td(f"{darr.min():.2f}")),
                ui.tags.tr(ui.tags.td("Max depth", class_="pe-3 fw-bold"), ui.tags.td(f"{darr.max():.2f}")),
                ui.tags.tr(ui.tags.td("Mean depth", class_="pe-3 fw-bold"), ui.tags.td(f"{darr.mean():.2f}")),
            ),
            class_="table table-sm table-borderless mb-0",
        )

    @reactive.effect
    @reactive.event(input.next_to_export)
    def _go_to_export():
        ui.update_radio_buttons("wizard_step", selected="export")

    # --- Step 5: Export ---
    def _step_export_ui():
        best = final_grd.get() or mesh_grd.get()
        if best is None:
            return ui.p("Generate a mesh first.", class_="text-muted")
        return ui.div(
            ui.h4("Step 5: Export"),
            ui.p("Save the mesh as a .grd file.", class_="text-muted"),
            ui.input_text(
                "export_filename",
                "Output Filename",
                value="mesh_output.grd",
            ),
            ui.input_action_button(
                "save_to_project",
                "Save to Project",
                class_="btn-primary w-100 mt-2 mb-2",
            ),
            ui.output_ui("export_result"),
        )

    @reactive.effect
    @reactive.event(input.save_to_project)
    def _on_save():
        grd = final_grd.get() or mesh_grd.get()
        if grd is None:
            ui.notification_show("No mesh to export.", type="warning")
            return
        filename = input.export_filename() or "mesh_output.grd"
        try:
            output_dir = Path(config.work_dir) / "mesh_builder"
            output_path = output_dir / filename
            export_grd(grd, output_path)
            _log(f"Exported mesh to: {output_path}")
            ui.notification_show(f"Saved: {output_path}", type="message", duration=5)
        except Exception as e:
            _log(f"Export error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)

    @render.ui
    def export_result():
        return None

    return {"mesh_grd": mesh_grd, "final_grd": final_grd}
