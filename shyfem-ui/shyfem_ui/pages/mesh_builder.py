"""Mesh builder page — 5-step wizard for creating FEM meshes."""

import asyncio
import logging
from pathlib import Path

import numpy as np
from shiny import module, reactive, render, ui

from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.project_select import project_rel_file_choices, str_file_selectize
from shyfem_ui.config import Config
from shyfem_ui.services.mesh_builder import (
    _check_boundary_gates,
    _compute_depths_only,
    adjust_depths,
    check_bathy_extent,
    compute_mesh_stats,
    count_below_area,
    estimate_element_count,
    export_grd,
    import_boundaries,
    interpolate_bathymetry_shybas,
    load_bathymetry_contours,
    load_bathymetry_file,
    reduce_boundary,
    smooth_boundary,
    suggest_max_area_for_limit,
    summarize_depth_stats,
    triangulate,
    validate_boundary,
    warn_if_degenerate_bathy,
    warn_if_min_geq_max_area,
    warn_if_minimal_with_cap,
)
from shyfem_ui.services.parser_grd import GrdFile, Node
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

# shiny 1.7 renamed @render.download to @render.download_button and the old
# name warns at decoration time (once per session, straight into the worker
# log). CI still pins shiny 1.6, which only has the old name.
_render_download_button = getattr(render, "download_button", None) or render.download

logger = logging.getLogger(__name__)

# Step definitions for the wizard navigation
_STEPS = {
    "import": "1. Import Boundaries",
    "refine": "2. Refine Boundaries",
    "mesh": "3. Generate Mesh",
    "bathy": "4. Interpolate Bathymetry",
    "export": "5. Export",
}


# ---------------------------------------------------------------------------
# UI — all structural content is defined here (not in @render.ui)
# ---------------------------------------------------------------------------


def _step_import_panel() -> ui.Tag:
    """Step 1 UI — static panel content."""
    return ui.nav_panel(
        "import",
        ui.div(
            ui.h4("Step 1: Import Boundaries"),
            ui.p(
                "Upload a GeoJSON, Shapefile, or GeoPackage file containing "
                "coastline or domain boundary polygons.",
                class_="text-muted",
            ),
            ui.input_file(
                "boundary_file",
                "Upload Boundary File",
                accept=[
                    ".geojson",
                    ".json",
                    ".shp",
                    ".shx",
                    ".dbf",
                    ".prj",
                    ".cpg",
                    ".gpkg",
                    ".zip",
                    "application/geopackage+sqlite3",
                    "application/geo+json",
                ],
                multiple=True,
            ),
            ui.p(
                "For Shapefiles, select all companion files (.shp, .shx, .dbf, .prj) "
                "together, or upload a .zip archive containing them.",
                class_="text-muted small",
            ),
            ui.output_ui("import_result"),
        ),
        value="import",
    )


def _step_refine_panel() -> ui.Tag:
    """Step 2 UI — static panel content."""
    return ui.nav_panel(
        "refine",
        ui.div(
            ui.h4("Step 2: Refine Boundaries"),
            ui.output_ui("refine_controls"),
        ),
        value="refine",
    )


def _step_mesh_panel() -> ui.Tag:
    """Step 3 UI — static panel content."""
    return ui.nav_panel(
        "mesh",
        ui.div(
            ui.h4("Step 3: Generate Mesh"),
            ui.p(
                "Configure triangulation method, mesh density and quality constraints.",
                class_="text-muted",
            ),
            ui.output_ui("mesh_prereq_alert"),
            ui.input_radio_buttons(
                "mesh_method",
                "Triangulation Method",
                choices={
                    "delaunay_quality": "Quality mesh (area + angle constraints)",
                    "delaunay_conforming": "Conforming (angle only, no area limit)",
                    "delaunay_minimal": "Minimal (fewest triangles, no constraints)",
                },
                selected="delaunay_quality",
            ),
            ui.output_ui("mesh_method_controls"),
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
        ),
        value="mesh",
    )


def _step_bathy_panel() -> ui.Tag:
    """Step 4 UI — static panel content."""
    return ui.nav_panel(
        "bathy",
        ui.div(
            ui.h4("Step 4: Interpolate Bathymetry"),
            ui.p(
                "Upload depth data and interpolate values onto mesh nodes.",
                class_="text-muted",
            ),
            ui.output_ui("bathy_prereq_alert"),
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
            ui.output_ui("bathy_upload_controls"),
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
                    ui.tags.li(
                        ui.tags.strong("Linear"),
                        " — smooth, good general-purpose default.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("Nearest"),
                        " — fast, produces discontinuous steps between data points.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("Cubic"),
                        " — smooth but can overshoot between sparse data.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("IDW"),
                        " — inverse-distance weighted average of 8 nearest neighbors.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("RBF (thin-plate spline)"),
                        " — globally smooth surface that ",
                        ui.tags.em("naturally extrapolates"),
                        " beyond the data extent. Best for sparse bathymetry " "and coastal edges.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("Clough-Tocher (C1 cubic)"),
                        " — piecewise cubic with continuous first derivatives. "
                        "Smoother than Cubic with less overshoot. Falls back to "
                        "nearest-neighbor outside the data hull.",
                    ),
                    ui.tags.li(
                        ui.tags.strong("shybas"),
                        " — SHYFEM's built-in Fortran interpolation.",
                    ),
                    class_="small mb-1 ps-3",
                ),
                ui.tags.strong(
                    "Recommendation for contour isobaths:",
                    class_="d-block mt-2 mb-1",
                ),
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
            ui.output_ui("bathy_post_panel"),
        ),
        value="bathy",
    )


def _step_export_panel() -> ui.Tag:
    """Step 5 UI — static panel content."""
    return ui.nav_panel(
        "export",
        ui.div(
            ui.h4("Step 5: Export"),
            ui.output_ui("export_summary"),
            ui.output_ui("export_filename_picker"),
            ui.input_action_button(
                "save_to_project",
                "Save to Project Directory",
                class_="btn-primary w-100 mt-2 mb-2",
            ),
            ui.download_button(
                "download_grd",
                "Download .grd File",
                class_="btn-outline-primary w-100 mb-2",
            ),
            ui.output_ui("export_result"),
        ),
        value="export",
    )


@module.ui
def mesh_builder_ui() -> ui.Tag:
    """Mesh builder page UI — 5-step wizard."""
    return ui.div(
        ui.h3("Mesh Builder"),
        ui.p(
            "Create simulation-ready meshes from coastline data in 5 steps.",
            class_="text-muted",
        ),
        # Step navigation as horizontal pills
        ui.div(
            ui.input_radio_buttons(
                "wizard_step",
                "",
                choices=_STEPS,
                selected="import",
                inline=True,
            ),
            class_="mb-3",
        ),
        # Status bar
        ui.output_ui("status_summary"),
        ui.output_ui("operation_progress"),
        # Main content area — tabs for wizard / preview / log
        ui.navset_card_tab(
            ui.nav_panel(
                "Wizard",
                # Hidden navset switched by the radio buttons
                ui.navset_hidden(
                    _step_import_panel(),
                    _step_refine_panel(),
                    _step_mesh_panel(),
                    _step_bathy_panel(),
                    _step_export_panel(),
                    id="wizard_panels",
                    selected="import",
                ),
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
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def stage_boundary_upload(files: list[dict], work: Path) -> Path:
    """Stage uploaded boundary files into ``work`` and return the file to open.

    Boundary uploads arrive as a list of ``{"name", "datapath"}`` dicts that
    Shiny stored under opaque temp names; multi-file formats like Shapefiles
    need their companions (.shx/.dbf/.prj) alongside the .shp under the original
    names, so we copy them into ``work``. ``.zip`` archives are extracted.

    ``work`` is owned by the caller (a TemporaryDirectory) so the staged copies
    are cleaned up after import — previously this allocated its own ``mkdtemp``
    that was never removed, leaking a ``mesh_import_*`` dir per upload.
    """
    import shutil
    import zipfile

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

    # Find the primary file to open. For Shapefiles, also check that the
    # required companion files (.shx, .dbf) are present — GDAL refuses to
    # open a bare .shp with a cryptic "flags=68" error otherwise.
    shp_files = list(work.glob("*.shp"))
    if shp_files:
        primary = shp_files[0]
        stem = primary.stem
        present = {p.suffix.lower() for p in work.glob(f"{stem}.*")}
        required = {".shp", ".shx", ".dbf"}
        missing = sorted(required - present)
        if missing:
            raise ValueError(
                f"Shapefile incomplete — missing companion file(s): "
                f"{', '.join(missing)}. Re-select all files together "
                f"(.shp, .shx, .dbf, .prj) or upload them as a .zip archive."
            )
        return primary

    for ext in (".geojson", ".json", ".gpkg"):
        found = list(work.glob(f"*{ext}"))
        if found:
            return found[0]

    names = ", ".join(f["name"] for f in files)
    raise ValueError(
        f"Unrecognized boundary file format. Got: {names}. "
        "Accepted: .geojson, .json, .gpkg, .shp (with companions), or "
        ".zip containing one of the above."
    )


def _import_boundary_upload(files) -> tuple:
    """Stage, import and validate an uploaded boundary (blocking; run in a thread).

    Staged inside a TemporaryDirectory, so the copies (and any extracted
    archive) are removed once import_boundaries has read the data.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mesh_import_") as tmp:
        grd = import_boundaries(stage_boundary_upload(files, Path(tmp)))
    return grd, validate_boundary(grd)


def _load_contour_upload(files, depth_attr: str, sample_dist: float | None):
    """Stage an isobath upload and sample it to points (blocking; run in a thread)."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mesh_import_") as tmp:
        return load_bathymetry_contours(
            stage_boundary_upload(files, Path(tmp)),
            depth_attr=depth_attr,
            sample_distance=sample_dist,
        )


@module.server
def mesh_builder_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
    current_user=None,
) -> None:
    """Mesh builder page server logic.

    ``current_user`` is the server-validated WS identity resolver (returns the
    user dict bound to the ``_wsauth`` token, or None). It feeds the fail-closed
    ``editor_denied_reason`` gate in ``_on_save`` so a viewer / unresolved WS
    client cannot export a .grd into the project dir in server mode.
    """
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # --- State ---
    boundary_grd = reactive.value(None)  # After import
    refined_grd = reactive.value(None)  # After smooth/reduce
    mesh_grd = reactive.value(None)  # After triangulation
    final_grd = reactive.value(None)  # After bathymetry
    preview_grd = reactive.value(None)  # Currently shown in map
    log_content = reactive.value("")
    bathy_data = reactive.value(None)  # Loaded bathymetry points
    busy_message = reactive.value("")  # Non-empty string = busy with that message
    staged_grd = reactive.value(None)  # After interpolation, before Accept
    comparison_runs = reactive.value({})  # {label: GrdFile}, max 3 entries
    progress_value = reactive.value(0)  # 0-100 = percent; -1 = indeterminate
    progress_label = reactive.value("")  # empty = bar hidden

    # --- Initialize child modules ---
    log_viewer_server("build_log", log_content)
    grid_map_server("mesh_preview", grd_file=preview_grd)

    def _log(msg: str) -> None:
        log_content.set(log_content.get() + msg + "\n")

    # --- Sync radio buttons → hidden navset ---
    @reactive.effect
    @reactive.event(input.wizard_step)
    def _sync_wizard_panels():
        # `update_navset` is the shiny>=1.6 name; older shiny (e.g. 1.4 on some
        # deploys) only has `update_navs`. Use whichever exists so an unhandled
        # AttributeError here can't crash the whole session (it ran in a reactive
        # effect, which on error tears down the WebSocket → "application exited").
        _update = getattr(ui, "update_navset", None) or ui.update_navs
        _update("wizard_panels", selected=input.wizard_step())

    @render.ui
    def operation_progress():
        """Bootstrap progress bar shown during mesh gen and interpolation."""
        label = progress_label.get()
        if not label:
            return ui.div()
        pct = progress_value.get()
        if pct == -1:
            return ui.div(
                ui.tags.div(
                    ui.tags.div(
                        label,
                        class_="progress-bar progress-bar-striped progress-bar-animated",
                        role="progressbar",
                        style="width: 100%",
                    ),
                    class_="progress mb-2",
                ),
            )
        return ui.div(
            ui.tags.div(
                ui.tags.div(
                    f"{label} ({pct}%)",
                    class_="progress-bar",
                    role="progressbar",
                    style=f"width: {pct}%",
                    aria_valuenow=str(pct),
                    aria_valuemin="0",
                    aria_valuemax="100",
                ),
                class_="progress mb-2",
            ),
        )

    # --- Status summary (horizontal bar) ---
    @render.ui
    def status_summary():
        items = []
        bgrd = boundary_grd.get()
        if bgrd:
            items.append(
                ui.tags.span(
                    ui.tags.i(class_="bi bi-check-circle-fill text-success me-1"),
                    f"Boundary: {bgrd.num_nodes} nodes",
                    class_="me-3",
                )
            )
        rgrd = refined_grd.get()
        if rgrd and rgrd is not bgrd:
            items.append(
                ui.tags.span(
                    ui.tags.i(class_="bi bi-check-circle-fill text-success me-1"),
                    f"Refined: {rgrd.num_nodes} nodes",
                    class_="me-3",
                )
            )
        mgrd = mesh_grd.get()
        if mgrd:
            items.append(
                ui.tags.span(
                    ui.tags.i(class_="bi bi-check-circle-fill text-success me-1"),
                    f"Mesh: {mgrd.num_nodes} nodes, {mgrd.num_elements} elems",
                    class_="me-3",
                )
            )
        fgrd = final_grd.get()
        if fgrd:
            depths = [n.depth for n in fgrd.nodes.values() if n.depth is not None]
            if depths:
                items.append(
                    ui.tags.span(
                        ui.tags.i(class_="bi bi-check-circle-fill text-success me-1"),
                        f"Depth: {min(depths):.1f} — {max(depths):.1f}",
                    )
                )
        # Busy indicator
        msg = busy_message.get()
        if msg:
            items.append(
                ui.div(
                    ui.div(
                        ui.div(
                            class_="spinner-border spinner-border-sm text-primary me-2",
                            role="status",
                        ),
                        ui.tags.span(msg),
                        class_="d-flex align-items-center",
                    ),
                    class_="alert alert-warning py-2 px-3 small mb-2 d-inline-flex",
                )
            )

        if not items:
            return ui.span()
        return ui.div(*items, class_="small text-muted mb-2")

    # --- Step 1: Import Boundaries ---

    @reactive.effect
    @reactive.event(input.boundary_file)
    async def _on_boundary_upload():
        files = input.boundary_file()
        if not files:
            return
        try:
            # Reading a shapefile/GeoPackage can take seconds: in a thread (M-11).
            grd, issues = await asyncio.to_thread(_import_boundary_upload, files)
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

    @render.ui
    def refine_controls():
        grd = refined_grd.get()
        if grd is None:
            return ui.div(
                "Import boundaries first (Step 1).",
                class_="alert alert-info py-2 px-3 small",
            )
        line_choices = {
            str(lid): f"Line {lid} (type={line.line_type}, {len(line.nodes)} pts)"
            for lid, line in sorted(grd.lines.items())
        }
        all_choice = {"all": f"All lines ({len(grd.lines)} lines)"}
        all_choice.update(line_choices)
        return ui.div(
            ui.p("Smooth or simplify boundary lines.", class_="text-muted"),
            ui.input_select("refine_line", "Select Line", choices=all_choice),
            ui.row(
                ui.column(
                    6,
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
                    ui.input_slider(
                        "reduce_tolerance",
                        "Simplify Tolerance",
                        min=0.0,
                        max=1000.0,
                        value=0.0,
                        step=1.0,
                    ),
                    ui.input_action_button(
                        "apply_reduce",
                        "Apply Simplification",
                        class_="btn-outline-primary btn-sm mb-2",
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
        selection = input.refine_line()
        method = input.smooth_method()
        iterations = input.smooth_iterations()
        line_ids = list(grd.lines.keys()) if selection == "all" else [int(selection)]
        try:
            new_grd = grd
            for lid in line_ids:
                new_grd = smooth_boundary(new_grd, lid, method=method, iterations=iterations)
            refined_grd.set(new_grd)
            preview_grd.set(new_grd)
            if selection == "all":
                _log(f"Smoothed all {len(line_ids)} lines: {method}, {iterations} iters")
            else:
                lid = line_ids[0]
                _log(
                    f"Smoothed line {lid}: {method}, {iterations} iters -> {len(new_grd.lines[lid].nodes)} nodes"
                )
        except Exception as e:
            _log(f"Smoothing error: {e}")
            ui.notification_show(str(e), type="error", duration=3)

    @reactive.effect
    @reactive.event(input.apply_reduce)
    def _on_reduce():
        grd = refined_grd.get()
        if grd is None:
            return
        selection = input.refine_line()
        tolerance = input.reduce_tolerance()
        line_ids = list(grd.lines.keys()) if selection == "all" else [int(selection)]
        try:
            new_grd = grd
            for lid in line_ids:
                new_grd = reduce_boundary(new_grd, lid, tolerance=tolerance)
            refined_grd.set(new_grd)
            preview_grd.set(new_grd)
            if selection == "all":
                _log(
                    f"Reduced all {len(line_ids)} lines: tolerance={tolerance}, {new_grd.num_nodes} total nodes"
                )
            else:
                lid = line_ids[0]
                _log(
                    f"Reduced line {lid}: tolerance={tolerance} -> {len(new_grd.lines[lid].nodes)} nodes"
                )
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

    @render.ui
    def mesh_prereq_alert():
        if refined_grd.get() is None:
            return ui.div(
                "Import boundaries first (Steps 1-2).",
                class_="alert alert-info py-2 px-3 small",
            )
        return ui.span()

    @render.ui
    def mesh_method_controls():
        """Show/hide area and angle controls based on selected method."""
        method = input.mesh_method()
        controls = []
        if method == "delaunay_quality":
            controls.append(
                ui.row(
                    ui.column(
                        6,
                        ui.input_numeric(
                            "max_area",
                            "Max Triangle Area",
                            value=None,
                            min=0.001,
                        ),
                        ui.input_numeric(
                            "min_area",
                            "Min Triangle Area (warning only)",
                            value=None,
                            min=0.0,
                        ),
                        ui.output_ui("element_estimate"),
                        ui.output_ui("area_bounds_warning"),
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
                        ui.input_numeric(
                            "max_elements",
                            "Max Elements (cap, blank = no limit)",
                            value=None,
                            min=1,
                        ),
                    ),
                )
            )
        elif method == "delaunay_conforming":
            controls.append(
                ui.row(
                    ui.column(
                        6,
                        ui.input_slider(
                            "min_angle",
                            "Min Angle (degrees)",
                            min=10,
                            max=33,
                            value=20,
                        ),
                    ),
                    ui.column(
                        6,
                        ui.input_numeric(
                            "max_elements",
                            "Max Elements (cap, blank = no limit)",
                            value=None,
                            min=1,
                        ),
                    ),
                )
            )
        else:  # delaunay_minimal
            controls.append(
                ui.input_numeric(
                    "max_elements",
                    "Max Elements (cap, blank = no limit)",
                    value=None,
                    min=1,
                ),
            )
        return ui.div(*controls) if controls else ui.span()

    @render.ui
    def element_estimate():
        grd = refined_grd.get()
        area = input.max_area()
        if grd is None or area is None or area <= 0:
            return ui.p("Enter max area to see estimate.", class_="text-muted small")
        count = estimate_element_count(grd, area)
        return ui.p(f"Estimated elements: ~{count:,}", class_="small text-info")

    @render.ui
    def area_bounds_warning():
        # Only the quality method renders both inputs.
        if input.mesh_method() != "delaunay_quality":
            return ui.span()
        try:
            min_a = input.min_area()
            max_a = input.max_area()
        except Exception:
            return ui.span()
        msg = warn_if_min_geq_max_area(min_a, max_a)
        if msg is None:
            return ui.span()
        return ui.p(msg, class_="alert alert-warning py-2 px-3 small mb-2")

    def _safe_input(name: str):
        """Read a dynamically-rendered numeric input, returning None if it
        does not exist for the current method."""
        try:
            return input[name]()
        except Exception:
            return None

    @reactive.effect
    @reactive.event(input.generate_mesh)
    async def _on_generate_mesh():
        grd = refined_grd.get()
        if grd is None:
            ui.notification_show("No boundary data to mesh.", type="warning")
            return
        ok, reason = _check_boundary_gates(grd)
        if not ok:
            msg = f"Cannot generate mesh: {reason}. Fix Step 1/2 issues first."
            _log(msg)
            ui.notification_show(msg, type="error", duration=8)
            return
        method = input.mesh_method()

        # Read controls that exist for the selected method. Some inputs are
        # only mounted for certain methods, so use a tolerant accessor.
        if method == "delaunay_quality":
            eff_area = _safe_input("max_area")
            eff_angle = input.min_angle()
        elif method == "delaunay_conforming":
            eff_area = None
            eff_angle = input.min_angle()
        else:  # delaunay_minimal
            eff_area = None
            eff_angle = 0.0

        min_area_threshold = _safe_input("min_area")
        max_elements = _safe_input("max_elements")

        # Pre-flight: hard cap on element count (applies to all methods).
        if max_elements and max_elements > 0:
            estimate_pf = estimate_element_count(grd, eff_area) if eff_area else 0
            if estimate_pf > max_elements:
                suggested = suggest_max_area_for_limit(grd, max_elements)
                msg = (
                    f"Estimated {estimate_pf:,} elements exceeds the limit " f"of {max_elements:,}."
                )
                if suggested is not None:
                    msg += f" Increase Max Area to ≥ {suggested:.4f} or raise the cap."
                _log(msg)
                ui.notification_show(msg, type="warning", duration=8)
                return
            # If the cap is set but no max_area was given, the user needs at
            # least one of the two. For "minimal", element count is governed
            # entirely by boundary geometry — surface a clear note.
            if not eff_area and method != "delaunay_minimal":
                ui.notification_show(
                    "Set a Max Triangle Area so the element-count cap can be checked.",
                    type="warning",
                    duration=6,
                )
                return

            # Minimal mode does not honor max_area, so the cap can't be enforced.
            minimal_msg = warn_if_minimal_with_cap(method, max_elements)
            if minimal_msg:
                _log(minimal_msg)
                ui.notification_show(minimal_msg, type="warning", duration=8)

        _log(f"Generating mesh: method={method}, max_area={eff_area}, min_angle={eff_angle} deg...")
        busy_message.set("Generating mesh…")
        estimate = estimate_element_count(grd, eff_area) if eff_area else 0
        est_label = f" (~{estimate:,} elements estimated)" if estimate else ""
        progress_label.set(f"Generating mesh{est_label}…")
        progress_value.set(-1)
        await asyncio.sleep(0)  # yield so Shiny flushes the bar to the browser
        try:
            new_mesh = await asyncio.to_thread(
                triangulate, grd, max_area=eff_area, min_angle=eff_angle
            )
            mesh_grd.set(new_mesh)
            preview_grd.set(new_mesh)
            _log(f"Mesh generated: {new_mesh.num_nodes} nodes, {new_mesh.num_elements} elements")

            # Post-flight: warn (don't block) if the actual element count
            # exceeded the user's cap. The pre-flight estimate is a lower
            # bound — Triangle's quality refinement (when min_angle is set)
            # adds 30-60% to the boundary_area / max_area floor. Surface
            # the discrepancy so the user can choose to regenerate with a
            # larger Max Area or accept the overshoot.
            if max_elements and max_elements > 0 and new_mesh.num_elements > max_elements:
                overshoot = new_mesh.num_elements - max_elements
                pct = 100.0 * overshoot / max_elements
                warn = (
                    f"⚠ Generated {new_mesh.num_elements:,} elements — "
                    f"{overshoot:,} ({pct:.0f}%) over the {max_elements:,} cap. "
                    "Increase Max Area to reduce, or raise the cap."
                )
                _log(warn)
                ui.notification_show(warn, type="warning", duration=8)

            # Post-flight: warn (don't block) if min_area threshold was set
            # and slivers exist. Triangle has no native min-area constraint;
            # post-validation is the most we can do without changing topology.
            if min_area_threshold and min_area_threshold > 0:
                slivers = count_below_area(new_mesh, min_area_threshold)
                if slivers > 0:
                    warn = (
                        f"⚠ {slivers:,} triangle(s) below Min Triangle Area "
                        f"({min_area_threshold:g}). Increase Min Angle or "
                        "redesign the boundary to reduce slivers."
                    )
                    _log(warn)
                    ui.notification_show(warn, type="warning", duration=8)

            ui.notification_show(
                f"Generated {new_mesh.num_elements} elements",
                type="message",
                duration=3,
            )
        except Exception as e:
            _log(f"Mesh generation error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)
        finally:
            busy_message.set("")
            progress_label.set("")
            progress_value.set(0)

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
            rows.append(("Min Angle (min/mean)", f"{ang['min']:.1f} / {ang['mean']:.1f} deg"))
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

    @render.ui
    def bathy_prereq_alert():
        if mesh_grd.get() is None:
            return ui.div(
                "Generate a mesh first (Step 3).",
                class_="alert alert-info py-2 px-3 small",
            )
        return ui.span()

    @render.ui
    def bathy_upload_controls():
        """Show upload controls based on selected bathymetry source type."""
        source = input.bathy_source()
        if source == "contours":
            return ui.div(
                ui.input_file(
                    "bathy_contour_file",
                    "Upload Contour Isobaths",
                    accept=[
                        ".shp",
                        ".shx",
                        ".dbf",
                        ".prj",
                        ".cpg",
                        ".geojson",
                        ".json",
                        ".gpkg",
                        ".zip",
                    ],
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
            )
        return ui.div(
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
                        ui.tags.td(f"{data[:,0].min():.4f} -- {data[:,0].max():.4f}"),
                    ),
                    ui.tags.tr(
                        ui.tags.td("Y range", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{data[:,1].min():.4f} -- {data[:,1].max():.4f}"),
                    ),
                    ui.tags.tr(
                        ui.tags.td("Depth range", class_="pe-3 fw-bold"),
                        ui.tags.td(f"{data[:,2].min():.2f} -- {data[:,2].max():.2f}"),
                    ),
                ),
                class_="table table-sm table-borderless mb-0",
            ),
            class_="mt-2",
        )

    @reactive.effect
    @reactive.event(input.bathy_file)
    async def _on_bathy_upload():
        files = input.bathy_file()
        if not files:
            return
        file_info = files[0]
        temp_path = Path(file_info["datapath"])
        try:
            # A bathymetry survey can be millions of points: in a thread (M-11).
            data = await asyncio.to_thread(load_bathymetry_file, temp_path)
            mesh = mesh_grd.get()
            if mesh is not None:
                msg = check_bathy_extent(mesh, data)
                if msg is not None:
                    _log(f"Bathymetry warning: {msg}")
                    ui.notification_show(msg, type="warning", duration=10)
            bathy_data.set(data)
            _log(f"Loaded bathymetry points: {file_info['name']} ({len(data)} points)")
            _log(f"  {summarize_depth_stats(data)}")
            ui.notification_show(
                f"Loaded {len(data)} bathymetry points", type="message", duration=3
            )
            warn = warn_if_degenerate_bathy(data)
            if warn:
                _log(f"Bathymetry warning: {warn}")
                ui.notification_show(warn, type="warning", duration=8)
        except Exception as e:
            _log(f"Error loading bathymetry: {e}")
            ui.notification_show(f"Load error: {e}", type="error", duration=5)

    @reactive.effect
    @reactive.event(input.bathy_contour_file)
    async def _on_contour_upload():
        files = input.bathy_contour_file()
        if not files:
            return
        try:
            depth_attr = input.contour_depth_attr() or "depth"
            sample_dist = input.contour_sample_dist()
            sample_dist = sample_dist if sample_dist and sample_dist > 0 else None
            # Reading and sampling isobaths can take seconds: in a thread (M-11).
            data = await asyncio.to_thread(_load_contour_upload, files, depth_attr, sample_dist)
            mesh = mesh_grd.get()
            if mesh is not None:
                msg = check_bathy_extent(mesh, data)
                if msg is not None:
                    _log(f"Bathymetry warning: {msg}")
                    ui.notification_show(msg, type="warning", duration=10)
            bathy_data.set(data)
            names = ", ".join(f["name"] for f in files)
            _log(f"Loaded contour isobaths: {names} ({len(data)} points)")
            _log(f"  {summarize_depth_stats(data)}")
            ui.notification_show(
                f"Extracted {len(data)} points from contour isobaths",
                type="message",
                duration=3,
            )
            warn = warn_if_degenerate_bathy(data)
            if warn:
                _log(f"Bathymetry warning: {warn}")
                ui.notification_show(warn, type="warning", duration=8)
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
        msg = check_bathy_extent(grd, data)
        if msg is not None:
            _log(f"Bathymetry warning: {msg}")
            ui.notification_show(msg, type="warning", duration=10)
            # Non-blocking — let the user proceed if they understand the warning.
        method = input.bathy_method()
        boundary_zero = input.use_boundary_zero()
        _log(f"Interpolating bathymetry: method={method}, boundary_zero={boundary_zero}...")
        busy_message.set(f"Interpolating bathymetry ({method})...")
        await asyncio.sleep(0)  # yield so Shiny flushes the spinner to the browser
        try:
            if method == "shybas":
                result_grd = await interpolate_bathymetry_shybas(grd, data, wrapper)
            else:
                n_bathy = len(data)
                n_nodes = len(grd.nodes)
                # Phase 1: setup
                progress_value.set(5)
                progress_label.set(f"Preparing {n_bathy:,} bathymetry points…")
                await asyncio.sleep(0)
                # Phase 2: scipy model + evaluation in thread
                progress_value.set(10)
                progress_label.set(f"Running {method} on {n_nodes:,} nodes…")
                await asyncio.sleep(0)
                node_ids, depths = await asyncio.to_thread(
                    _compute_depths_only,
                    grd,
                    data,
                    method,
                    boundary_zero,
                )
                # Phase 3: assign depths in async chunks for smooth progress
                new_grd = GrdFile()
                chunk = 500
                for start in range(0, n_nodes, chunk):
                    end = min(start + chunk, n_nodes)
                    for i in range(start, end):
                        nid = node_ids[i]
                        node = grd.nodes[nid]
                        new_grd.nodes[nid] = Node(
                            id=nid,
                            node_type=node.node_type,
                            x=node.x,
                            y=node.y,
                            depth=float(depths[i]),
                        )
                    pct = min(99, 10 + int(end / n_nodes * 90))
                    progress_value.set(pct)
                    progress_label.set(f"Assigning depths… {end:,} / {n_nodes:,} nodes")
                    await asyncio.sleep(0)
                new_grd.elements = dict(grd.elements)
                new_grd.lines = dict(grd.lines)
                result_grd = new_grd
            staged_grd.set(result_grd)
            preview_grd.set(result_grd)
            depths = [n.depth for n in result_grd.nodes.values() if n.depth is not None]
            depth_info = ""
            if depths:
                dmin, dmax = min(depths), max(depths)
                depth_info = f" (min: {dmin:.1f}, max: {dmax:.1f} m)"
                _log(f"Bathymetry interpolated: depth {dmin:.2f} to {dmax:.2f}")
            # Store run in comparison_runs (max 3; oldest dropped)
            label = f"{method}{depth_info}"
            runs = dict(comparison_runs.get())
            runs[label] = result_grd
            if len(runs) > 3:
                oldest = next(iter(runs))
                del runs[oldest]
            comparison_runs.set(runs)
            ui.notification_show("Bathymetry interpolated", type="message", duration=3)
        except Exception as e:
            _log(f"Interpolation error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)
        finally:
            busy_message.set("")
            progress_label.set("")
            progress_value.set(0)

    @render.ui
    def bathy_stats_display():
        grd = staged_grd.get()
        if grd is None:
            return ui.p("Interpolate to see depth statistics.", class_="text-muted small")
        depths = [n.depth for n in grd.nodes.values() if n.depth is not None]
        if not depths:
            return ui.p("No depth data.", class_="text-muted small")
        darr = np.array(depths)
        return ui.tags.table(
            ui.tags.tbody(
                ui.tags.tr(
                    ui.tags.td("Min depth", class_="pe-3 fw-bold"),
                    ui.tags.td(f"{darr.min():.2f}"),
                ),
                ui.tags.tr(
                    ui.tags.td("Max depth", class_="pe-3 fw-bold"),
                    ui.tags.td(f"{darr.max():.2f}"),
                ),
                ui.tags.tr(
                    ui.tags.td("Mean depth", class_="pe-3 fw-bold"),
                    ui.tags.td(f"{darr.mean():.2f}"),
                ),
            ),
            class_="table table-sm table-borderless mb-0",
        )

    @render.ui
    def bathy_post_panel():
        """Renders comparison selector, depth adjustments, and Accept button.

        Shown only after a successful interpolation (staged_grd is not None).
        """
        if staged_grd.get() is None:
            return ui.div()

        # --- Comparison selector (only when >=2 runs exist) ---
        runs = comparison_runs.get()
        comparison_ui = ui.div()
        if len(runs) >= 2:
            newest_label = next(reversed(runs))
            comparison_ui = ui.div(
                ui.hr(),
                ui.h6("Compare Runs"),
                ui.input_radio_buttons(
                    "comparison_run",
                    "",
                    choices={k: k for k in runs},
                    selected=newest_label,
                    inline=False,
                ),
            )

        # --- Depth adjustments ---
        adjustments_ui = ui.div(
            ui.hr(),
            ui.h6("Depth Adjustments"),
            ui.p(
                "Leave blank to skip. Changes apply to the staged result.",
                class_="text-muted small mb-2",
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "adj_min_clamp",
                        "Clamp min (m)",
                        value=None,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "adj_max_clamp",
                        "Clamp max (m)",
                        value=None,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "adj_fill_value",
                        "Fill unmapped (m)",
                        value=None,
                    ),
                ),
            ),
            ui.input_action_button(
                "apply_adjustments_btn",
                "Apply Adjustments",
                class_="btn-outline-secondary btn-sm mt-1 mb-2 w-100",
            ),
        )

        # --- Accept button ---
        accept_ui = ui.div(
            ui.hr(),
            ui.input_action_button(
                "accept_depths_btn",
                "Accept Depths → Export",
                class_="btn-success w-100 mt-1",
            ),
        )

        return ui.div(comparison_ui, adjustments_ui, accept_ui)

    @reactive.effect
    @reactive.event(input.comparison_run)
    def _on_comparison_run():
        """Switch staged_grd and preview when user selects a different run."""
        label = input.comparison_run()
        runs = comparison_runs.get()
        if label in runs:
            staged_grd.set(runs[label])
            preview_grd.set(runs[label])

    @reactive.effect
    @reactive.event(input.apply_adjustments_btn)
    def _on_apply_adjustments():
        """Apply clamp/fill adjustments to staged_grd."""
        grd = staged_grd.get()
        if grd is None:
            return
        try:
            min_clamp = input.adj_min_clamp()
            max_clamp = input.adj_max_clamp()
            fill_val = input.adj_fill_value()
        except Exception:
            min_clamp = max_clamp = fill_val = None
        if min_clamp is None and max_clamp is None and fill_val is None:
            ui.notification_show("No adjustments specified.", type="warning", duration=3)
            return
        adjusted = adjust_depths(grd, min_clamp=min_clamp, max_clamp=max_clamp, fill_value=fill_val)
        staged_grd.set(adjusted)
        preview_grd.set(adjusted)
        parts = []
        if min_clamp is not None:
            parts.append(f"min clamp {min_clamp}")
        if max_clamp is not None:
            parts.append(f"max clamp {max_clamp}")
        if fill_val is not None:
            parts.append(f"fill {fill_val}")
        _log(f"Depths adjusted: {', '.join(parts)}")
        ui.notification_show("Adjustments applied", type="message", duration=3)

    @reactive.effect
    @reactive.event(input.accept_depths_btn)
    def _on_accept_depths():
        """Commit staged_grd to final_grd and navigate to Export step."""
        grd = staged_grd.get()
        if grd is None:
            return
        final_grd.set(grd)
        depths = [n.depth for n in grd.nodes.values() if n.depth is not None]
        if depths:
            _log(f"Depths accepted: {min(depths):.2f} to {max(depths):.2f}")
        ui.update_radio_buttons("wizard_step", selected="export")

    # --- Step 5: Export ---

    @render.ui
    def export_summary():
        best = final_grd.get() or mesh_grd.get()
        if best is None:
            return ui.div(
                "Generate a mesh first (Step 3).",
                class_="alert alert-info py-2 px-3 small",
            )
        has_depth = any(n.depth is not None for n in best.nodes.values())
        summary = f"{best.num_nodes:,} nodes, {best.num_elements:,} elements"
        if has_depth:
            depths = [n.depth for n in best.nodes.values() if n.depth is not None]
            summary += f", depth {min(depths):.1f}\u2013{max(depths):.1f}"
        return ui.p(f"Mesh ready: {summary}", class_="text-muted")

    @render.ui
    def export_filename_picker():
        """Project .grd files (a pick overwrites, as a project-relative path)
        or a typed new name."""
        proj = active_project.get() if active_project is not None else None
        usr = current_user() if current_user is not None else None
        return str_file_selectize(
            "export_filename",
            "Output Filename",
            "mesh_output.grd",
            project_rel_file_choices(proj, usr, config, (".grd",)),
            placeholder="pick a .grd to overwrite or type a new name",
        )

    @reactive.effect
    @reactive.event(input.save_to_project)
    def _on_save():
        grd = final_grd.get() or mesh_grd.get()
        if grd is None:
            ui.notification_show("No mesh to export.", type="warning")
            return
        # Fail-closed authorization: writing a .grd into the project dir is an
        # editor-level mutation. Re-check the server-validated WS identity (the
        # save button is live for any client that can address the page).
        from shyfem_ui.services.access_control import editor_denied_reason

        _usr = current_user() if current_user else None
        _proj = active_project.get() if active_project else None
        _denied = editor_denied_reason(_proj["id"] if _proj else None, _usr, min_role="editor")
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return
        filename = input.export_filename() or "mesh_output.grd"
        # Use active project dir if available, fallback to global work_dir
        project = active_project.get() if active_project else None
        if project and project.get("work_dir"):
            output_dir = Path(project["work_dir"])
        else:
            output_dir = Path(config.work_dir) / "mesh_builder"
        # Reject traversal: export_filename() is free text, so an absolute path
        # or '..' segments would escape the work tree. Confine the target to
        # work_dir before writing (mirrors physics/simulation save handlers).
        try:
            output_path = config.confine_path(output_dir / filename, _usr, for_write=True)
        except ValueError as e:
            _log(f"Invalid export path: {e}")
            ui.notification_show(str(e), type="error", duration=6)
            return
        try:
            # A picked/typed name may carry a subdirectory (GRID/x.grd); the
            # path is already confined to the work tree, so create the parent.
            output_path.parent.mkdir(parents=True, exist_ok=True)
            export_grd(grd, output_path)
            _log(f"Exported mesh to: {output_path}")
            ui.notification_show(f"Saved: {output_path}", type="message", duration=5)
        except Exception as e:
            _log(f"Export error: {e}")
            ui.notification_show(f"Error: {e}", type="error", duration=5)

    @_render_download_button(
        filename=lambda: Path(input.export_filename() or "mesh_output.grd").name
    )
    def download_grd():
        """Download .grd file to the browser."""
        import os
        import tempfile

        grd = final_grd.get() or mesh_grd.get()
        if grd is None:
            return
        # mkstemp creates the file atomically with a non-predictable name (no
        # TOCTOU race, unlike the deprecated tempfile.mktemp). We only need the
        # path; export_grd reopens it to write.
        fd, tmp_name = tempfile.mkstemp(suffix=".grd")
        os.close(fd)
        tmp = Path(tmp_name)
        export_grd(grd, tmp)
        return str(tmp)

    @render.ui
    def export_result():
        return None

    return {"mesh_grd": mesh_grd, "final_grd": final_grd}
