"""IBM (Individual Based Model) page - Lagrangian particle tracking.

Displays mean particle trajectories from .lgr output files using lgrelab -lgmean.
Simulation setup belongs on the Simulation + Run pages.
"""

import logging
import math
from pathlib import Path

from shiny import module, reactive, render, ui

try:
    from shiny_deckgl import (
        MapWidget,
        context_menu_widget,
        fullscreen_widget,
        info_widget,
        legend_control,
        scatterplot_layer,
        screenshot_widget,
        tile_layer,
        trips_layer,
        zoom_widget,
    )
    from shiny_deckgl.ibm import (
        format_trips,
        trips_animation_server,
        trips_animation_ui,
    )
except ImportError:
    MapWidget = context_menu_widget = fullscreen_widget = None
    info_widget = legend_control = screenshot_widget = None
    scatterplot_layer = tile_layer = trips_layer = zoom_widget = None
    format_trips = trips_animation_ui = trips_animation_server = None

from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
from shyfem_ui.components.grid_map import BASEMAPS, EMODNET_WMS_URL
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.lgr_service import LgrService, ParticleTrack
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)

# Viridis-inspired 10-stop palette for color-by-type
_TRACK_COLORS = [
    [68, 1, 84, 220],
    [72, 40, 120, 220],
    [62, 74, 137, 220],
    [49, 104, 142, 220],
    [38, 130, 142, 220],
    [31, 158, 137, 220],
    [53, 183, 121, 220],
    [110, 206, 88, 220],
    [181, 222, 43, 220],
    [253, 231, 37, 220],
]


def _tracks_to_trips(tracks: list[ParticleTrack]) -> list[dict]:
    """Convert ParticleTrack list to format_trips output for trips_layer."""
    if not tracks or format_trips is None:
        return []
    from datetime import datetime as _dt

    paths: list[list[list[float]]] = []
    timestamps: list[list[float]] = []
    properties: list[dict] = []
    for t in tracks:
        if not t.path:
            continue
        if not all(len(p) == 2 for p in t.path):
            raise ValueError(f"ParticleTrack paths must be 2-D [lon,lat], got {len(t.path[0])}-D")
        paths.append(t.path)
        timestamps.append([_dt.fromisoformat(ts).timestamp() for ts in t.times])
        properties.append({"color": _TRACK_COLORS[(t.type_id - 1) % len(_TRACK_COLORS)]})
    return format_trips(paths, timestamps=timestamps, properties=properties)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two lon/lat points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_track_stats(tracks: list) -> list[dict]:
    """Compute per-type statistics from ParticleTrack list.

    Returns list of dicts with keys: type_id, steps, displacement_km,
    mean_depth, max_depth, mean_age, end_lon, end_lat, duration.
    """
    stats = []
    for track in tracks:
        if not track.path or len(track.path) < 2:
            continue
        start_lon, start_lat = track.path[0]
        end_lon, end_lat = track.path[-1]
        disp = _haversine_km(start_lon, start_lat, end_lon, end_lat)
        depths = [d for d in track.depths if d is not None]
        ages = [a for a in track.ages if a is not None]
        duration = ""
        if len(track.times) >= 2:
            duration = f"{track.times[0]} → {track.times[-1]}"
        stats.append(
            {
                "type_id": track.type_id,
                "steps": len(track.path),
                "displacement_km": round(disp, 2),
                "end_lon": round(end_lon, 4),
                "end_lat": round(end_lat, 4),
                "mean_depth": round(sum(depths) / len(depths), 2) if depths else 0.0,
                "max_depth": round(max(depths), 2) if depths else 0.0,
                "mean_age": round(sum(ages) / len(ages), 2) if ages else 0.0,
                "duration": duration,
            }
        )
    return stats


@module.ui
def ibm_ui() -> ui.Tag:
    """IBM particle tracking page UI."""
    if MapWidget is None:
        return ui.div(
            ui.div(
                ui.tags.i(class_="bi bi-exclamation-triangle me-2"),
                "IBM page requires the ",
                ui.tags.code("shiny_deckgl"),
                " package. Install it with: ",
                ui.tags.code("pip install shiny-deckgl"),
                class_="alert alert-warning",
            ),
        )

    _map = MapWidget(
        id=module.resolve_id("ibm_map"),
        tooltip={"html": "{tooltip_html}"},
        picking_radius=8,
    )

    return ui.div(
        ui.h3(
            ui.tags.i(class_="bi bi-wind me-2"),
            "IBM - Particle Tracking",
        ),
        ui.p(
            "Load Lagrangian particle trajectories from a completed IBM simulation (.lgr file).",
            class_="text-muted",
        ),
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Trajectory File"),
                file_picker_ui("fp_lgr", label="Pick Lagrangian output from project"),
                ui.input_text(
                    "lgr_path",
                    "LGR File (.lgr)",
                    placeholder="/path/to/output.lgr",
                ),
                ui.input_action_button(
                    "load_btn",
                    "Load Trajectories",
                    class_="btn-primary btn-sm w-100 mb-2",
                ),
                ui.hr(),
                ui.h6("Basemap"),
                ui.input_select(
                    "ibm_basemap",
                    None,
                    choices={
                        "positron": "Positron",
                        "dark": "Dark",
                        "osm": "OSM",
                    },
                    selected="positron",
                    width="100%",
                ),
                ui.hr(),
                ui.h6("Animation"),
                (
                    trips_animation_ui("ibm_trips")
                    if trips_animation_ui
                    else ui.p("Animation requires shiny_deckgl", class_="text-muted small")
                ),
                ui.hr(),
                ui.h6("Display"),
                ui.input_checkbox("show_emodnet", "EMODnet Bathymetry", value=True),
                ui.input_checkbox("show_tracks", "Particle Tracks", value=True),
                ui.input_checkbox("show_starts", "Start Points", value=True),
                ui.input_checkbox("show_ends", "End Points", value=True),
                ui.hr(),
                ui.div(
                    ui.tags.i(class_="bi bi-info-circle me-1"),
                    ui.span("Configure IBM parameters in "),
                    ui.strong("Configuration"),
                    ui.span(", then submit from "),
                    ui.strong("Run"),
                    ui.span("."),
                    class_="small text-muted p-2 bg-light rounded",
                ),
                width=280,
            ),
            ui.div(
                _map.ui(width="100%", height="700px"),
                ui.output_ui("ibm_status"),
                ui.output_ui("ibm_stats_panel"),
                class_="p-0",
            ),
        ),
        class_="ibm-page p-3",
    )


@module.server
def ibm_server(
    input,
    output,
    session,
    config: Config,
    active_project: reactive.Value,
    tutorial_context=None,
    current_user=None,
) -> None:
    """IBM page server logic."""
    if MapWidget is None:
        return

    project_id_val: reactive.Value[int | None] = reactive.value(None)

    map_id = module.resolve_id("ibm_map")
    _map = MapWidget(
        id=map_id,
        tooltip={"html": "{tooltip_html}"},
        picking_radius=8,
    )

    if trips_animation_server is not None:
        anim = trips_animation_server("ibm_trips", widget=_map, session=session)
    else:
        anim = None

    wrapper = ShyfemWrapper(config.shyfem_dir)
    lgr_service = LgrService(wrapper)

    # State
    tracks_data: reactive.Value[list[ParticleTrack]] = reactive.value([])
    load_error: reactive.Value[str | None] = reactive.value(None)

    # Auto-fill from active project: prefer FileService-tracked .lgr
    # files surfaced via the picker, fall back to glob-search of
    # work_dir for .lgr files generated mid-run before the next scan.
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
        # Existing glob fallback - keep it for .lgr files that aren't
        # tracked in FileService (e.g., generated mid-run before scan).
        # Only fill if the input is empty so picker selections survive.
        with reactive.isolate():
            lgr_empty = not input.lgr_path()
        if lgr_empty:
            if work:
                lgr_files = sorted(Path(work).glob("*.lgr"))
                if lgr_files:
                    chosen = str(lgr_files[0])
                    # Section M.2: log provenance so ops can see when
                    # lgr_path comes from the work_dir glob (e.g. a
                    # mid-run generated file) rather than a picker
                    # click. Picker dropdown only lists FileService-
                    # tracked files; the glob can fill ahead of scan.
                    logger.info(
                        "ibm_server: filled lgr_path from work_dir glob "
                        "(file not yet tracked by FileService): %s",
                        chosen,
                    )
                    ui.update_text("lgr_path", value=chosen)

    # File picker delegates resolve/log/notify branching to
    # fill_picker_input (see its docstring in components/file_picker.py).
    file_picker_server(
        "fp_lgr",
        project_id=project_id_val,
        file_types=["lagrangian"],
        on_selected=lambda rel: fill_picker_input(
            "lgr_path", active_project.get() if active_project else None, rel
        ),
    )

    @reactive.effect
    @reactive.event(input.load_btn)
    async def _load_trajectories():
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get()
        if _proj is not None:
            _denied = editor_denied_reason(_proj["id"], _usr, min_role="editor")
            if _denied:
                ui.notification_show(_denied, type="error", duration=6)
                return

        path_str = input.lgr_path()
        if not path_str:
            ui.notification_show("Enter a .lgr file path", type="warning")
            return

        try:
            path = config.validate_path(path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            load_error.set(str(e))
            return

        try:
            tracks = await lgr_service.load(path)
            tracks_data.set(tracks)
            load_error.set(None)
            if tracks:
                total = sum(len(t.path) for t in tracks)
                ui.notification_show(
                    f"Loaded {len(tracks)} type(s), {total} total steps",
                    type="message",
                )
            else:
                ui.notification_show(
                    "No trajectories found — ensure the simulation used IBM and -lgmean is supported",
                    type="warning",
                )
        except Exception as e:
            logger.warning("Failed to load LGR file %s: %s", path_str, e, exc_info=True)
            load_error.set(str(e))
            ui.notification_show(f"Failed to load: {e}", type="error", duration=6)

    @reactive.effect
    async def _update_ibm_map():
        """Rebuild map layers whenever inputs or track data change."""
        basemap_key = input.ibm_basemap()
        show_emod = input.show_emodnet()
        show_trk = input.show_tracks()
        show_starts = input.show_starts()
        show_ends = input.show_ends()
        tracks = tracks_data.get()
        filtered = tracks  # trips_layer handles time via animation controls

        layers: list[dict] = []
        legend_entries: list[dict] = []

        if show_emod:
            layers.append(
                tile_layer(
                    "emodnet",
                    EMODNET_WMS_URL,
                    minZoom=0,
                    maxZoom=18,
                    tileSize=256,
                    opacity=0.6,
                    pickable=False,
                )
            )
            legend_entries.append(
                {
                    "layer_id": "emodnet",
                    "label": "EMODnet Bathy",
                    "color": [0, 100, 180],
                    "shape": "rect",
                }
            )

        starts, ends = [], []
        for track in filtered:
            if not track.path:
                continue
            t0 = track.times[0] if track.times else ""
            t1 = track.times[-1] if track.times else ""
            d0 = f"{track.depths[0]:.1f} m" if track.depths else ""
            d1 = f"{track.depths[-1]:.1f} m" if track.depths else ""
            starts.append(
                {
                    "position": track.path[0],
                    "tooltip_html": f"<b>Start type {track.type_id}</b><br>{t0}<br>Depth: {d0}",
                }
            )
            ends.append(
                {
                    "position": track.path[-1],
                    "tooltip_html": f"<b>End type {track.type_id}</b><br>{t1}<br>Depth: {d1}",
                }
            )

        if show_trk and filtered:
            trips_data = _tracks_to_trips(filtered)
            if trips_data:
                trail_len = anim.trail() if anim else 180
                layers.append(
                    trips_layer(
                        "particle-trips",
                        trips_data,
                        getColor="@@d.color",
                        trailLength=trail_len,
                        widthMinPixels=2,
                        pickable=True,
                    )
                )
                first_id = filtered[0].type_id
                legend_entries.append(
                    {
                        "layer_id": "particle-trips",
                        "label": "Tracks",
                        "color": _TRACK_COLORS[(first_id - 1) % len(_TRACK_COLORS)][:3],
                        "shape": "line",
                    }
                )

        if show_starts and starts:
            layers.append(
                scatterplot_layer(
                    "starts",
                    starts,
                    getPosition="@@d.position",
                    getFillColor=[0, 200, 100, 230],
                    radiusMinPixels=6,
                    radiusMaxPixels=12,
                    pickable=True,
                )
            )
            legend_entries.append(
                {"layer_id": "starts", "label": "Start", "color": [0, 200, 100], "shape": "circle"}
            )

        if show_ends and ends:
            layers.append(
                scatterplot_layer(
                    "ends",
                    ends,
                    getPosition="@@d.position",
                    getFillColor=[230, 50, 50, 230],
                    radiusMinPixels=6,
                    radiusMaxPixels=12,
                    pickable=True,
                )
            )
            legend_entries.append(
                {"layer_id": "ends", "label": "End", "color": [230, 50, 50], "shape": "circle"}
            )

        # Center on first loaded track, or default to Adriatic
        if filtered and filtered[0].path:
            lon, lat = filtered[0].path[0]
            zoom = 9
        else:
            lon, lat, zoom = 12.5, 45.5, 5

        await _map.update(
            session,
            layers=layers,
            view_state={"longitude": lon, "latitude": lat, "zoom": zoom, "pitch": 0, "bearing": 0},
            transition_duration=300,
            widgets=[
                zoom_widget(),
                fullscreen_widget(placement="top-right"),
                screenshot_widget(placement="top-right"),
                info_widget(placement="top-left"),
                context_menu_widget(),
            ],
        )
        controls = (
            [legend_control(legend_entries, position="bottom-right", title="Layers")]
            if legend_entries
            else []
        )
        await _map.set_controls(session, controls)
        await _map.set_style(session, BASEMAPS.get(basemap_key, BASEMAPS["positron"]))

    @render.ui
    def ibm_status():
        err = load_error.get()
        if err:
            return ui.span(
                ui.tags.i(class_="bi bi-exclamation-circle me-1"),
                f"Error: {err[:80]}",
                class_="text-danger small mt-2",
            )
        tracks = tracks_data.get()
        if not tracks:
            return ui.span("No trajectories loaded.", class_="text-muted small mt-2")
        total_steps = sum(len(t.path) for t in tracks)
        return ui.div(
            ui.span(f"{len(tracks)} type(s)", class_="badge bg-primary me-2"),
            ui.span(f"{total_steps} steps", class_="badge bg-info"),
            class_="mt-2",
        )

    @render.ui
    def ibm_stats_panel():
        tracks = tracks_data.get()
        if not tracks:
            return ui.div()
        stats = compute_track_stats(tracks)
        if not stats:
            return ui.div()
        rows = []
        for s in stats:
            color = _TRACK_COLORS[(s["type_id"] - 1) % len(_TRACK_COLORS)]
            rgb = f"rgb({color[0]},{color[1]},{color[2]})"
            rows.append(
                ui.tags.tr(
                    ui.tags.td(
                        ui.span(
                            "",
                            style=f"display:inline-block;width:12px;height:12px;border-radius:50%;background:{rgb};margin-right:6px;vertical-align:middle;",
                        ),
                        f"Type {s['type_id']}",
                    ),
                    ui.tags.td(str(s["steps"])),
                    ui.tags.td(f"{s['displacement_km']} km"),
                    ui.tags.td(f"{s['end_lon']}, {s['end_lat']}"),
                    ui.tags.td(f"{s['mean_depth']} m"),
                    ui.tags.td(f"{s['max_depth']} m"),
                    ui.tags.td(f"{s['mean_age']} s"),
                    ui.tags.td(s["duration"], class_="small"),
                )
            )
        return ui.div(
            ui.h6(
                ui.tags.i(class_="bi bi-bar-chart me-1"),
                "Particle Statistics",
                class_="mt-3 mb-2",
            ),
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Type"),
                        ui.tags.th("Steps"),
                        ui.tags.th("Displacement"),
                        ui.tags.th("Endpoint"),
                        ui.tags.th("Mean Depth"),
                        ui.tags.th("Max Depth"),
                        ui.tags.th("Mean Age"),
                        ui.tags.th("Duration"),
                    ),
                ),
                ui.tags.tbody(*rows),
                class_="table table-sm table-striped mt-1",
            ),
        )
