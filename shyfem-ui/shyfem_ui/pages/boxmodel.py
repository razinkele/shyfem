"""Box model page (spec §8): Map, Time-series and Compare tabs over the Parquet cache.

Everything below the page already exists as a reviewed service: the manifest
loader, the cache service (child-process builds + registry + two-step
publish), the skill metrics, the box polygons and the grid map's box layers.
This module is the integration layer, and it carries the page-level
obligations the reviews of those services handed forward:

* every manifest / observation / polygon / cache failure becomes a page
  message -- no exception ever escapes a render or an effect;
* no raw absolute host path reaches the browser: every user-facing
  string from a service -- exception text via :func:`_safe_error`, and
  ``CacheStatus.message`` via :func:`_safe_text` -- has its path-looking
  tokens rewritten with ``config.display_path``;
* all manifest-, label- and site-supplied text is emitted through
  ``ui.tags`` (never ``ui.HTML``), so it is escaped; the one place text
  reaches raw HTML is the deck.gl tooltip, and that is escaped where the
  HTML is built, in ``build_box_layers`` -- escaping it here as well
  would double-escape an ampersand in a legitimate site name;
* writes (build / cancel) are gated by ``editor_denied_reason`` *inside*
  the handler -- hiding a button is only cosmetic;
* builds run with a bounded timeout (``config.command_timeout_seconds``
  defaults to ``None`` = unbounded);
* ``reconcile_tmp_dirs`` runs at page load inside a ``try``;
* the status poller owns its own trigger: it re-arms itself only while a
  build is live and never reads anything it writes, so there is no
  reactive self-write loop; a separate slow watch (``_watch_published``)
  notices a cache republished by a build some other session started;
* the Parquet cache is read off the event loop (B-06): ``_load_cached_run``,
  ``_load_run_states`` and ``_load_hourly_window`` are async effects that
  hand the read to ``asyncio.to_thread`` and store the result, and the calcs
  the tabs read (``cached_result``, ``all_run_states_result``,
  ``hourly_window_result``) only look it up;
* the Compare tab (PR 2) works on ONE shared day set: ``cmp_days_result()``
  is the calc that computes it once (``common_days``), ``cmp_days()`` the
  accessor handing it to the difference map, the overlay plot and the
  skill/per-year tables, so the three can never silently describe different
  days; everything in it hangs off ``all_run_states_result()``
  (``cache_generation``), never the 2 s badge tick;
* the Setup tab (PR 3) is read-only and reads the STR and the forcing files
  through ``reactive.calc``s off ``manifest()`` (never per render); a
  ``boundn`` is never opened directly -- it goes through
  ``resolve_forcing_file`` (basename under the manifest's forcing dir, no
  symlinks, re-confined on every call) -- and no resolved path is ever
  rendered: the table shows ``boundn`` as written plus the resolver's note.
"""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import re
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget

from shyfem_ui.components.grid_map import (
    _detect_projected_crs,
    _is_geographic,
    build_box_layers,
    build_setup_layers,
    grid_map_server,
    grid_map_ui,
    node_positions,
)
from shyfem_ui.components.project_select import (
    analysis_root_dir_choices,
    project_dir_select,
    project_file_select,
    project_rel_dir_choices,
)
from shyfem_ui.components.themed_widget import render_widget
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.boxmodel_cache import (
    cache_dir_for,
    cache_status,
    cancel_build,
    get_registry,
    load_cache,
    load_cache_state,
    published_fingerprint,
    read_hourly_window,
    reconcile_tmp_dirs,
    start_build,
    tmp_age_cap_seconds,
)
from shyfem_ui.services.boxmodel_compare import (
    common_days,
    overlay_series,
    period_mean_diff,
    side_by_side,
)
from shyfem_ui.services.boxmodel_manifest import (
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    ManifestError,
    load_manifest,
    write_manifest,
)
from shyfem_ui.services.boxmodel_polygons import (
    PolygonError,
    dissolve_boxes_from_grid,
    grid_to_wgs84,
    load_box_polygons,
)
from shyfem_ui.services.boxmodel_setup import (
    StrSetupError,
    boundaries,
    kind,
    period_from_summary,
    read_forcing_series,
    read_str_tolerant,
    resolve_forcing_file,
    section_interfaces,
    str_summary,
)
from shyfem_ui.services.boxmodel_skill import (
    VARIABLE_COLUMNS,
    ObservationError,
    band_amplitude_ratios,
    load_observations,
    load_sites,
    model_series,
    per_year_table,
)
from shyfem_ui.services.boxmodel_skill import skill_table as compute_skill_table
from shyfem_ui.services.parser_grd import GrdParser

logger = logging.getLogger(__name__)

# The build registry is process-wide and owned by the cache service
# (``get_registry()``): every session on this worker shares the one instance,
# which is what makes the per-worker/per-user build caps meaningful.

# shiny 1.7 renamed @render.download to @render.download_button and the old
# name is deprecated; resolve whichever this shiny provides (mesh_builder.py).
_render_download = getattr(render, "download_button", None) or render.download

#: Fallback wall-clock cap for one cache build. ``Config.command_timeout_seconds``
#: defaults to ``None`` (unbounded) and ``start_build`` reads the timeout from
#: the Config it is handed, so the page supplies a bounded one.
BUILD_TIMEOUT_SECONDS = 30 * 60
POLL_SECONDS = 2
#: How often a page holding a loaded cache checks whether it was republished
#: by a build it did not start (another session, or another worker): one
#: ``stat`` of each manifest run's ``meta.json`` per tick (B-04).
WATCH_SECONDS = 10
#: Priority of the effects that read the cache off the loop (B-06): above the
#: outputs' default 0, so a read STARTS first. Shiny does not wait for an
#: async effect to finish (priority orders starts, not finishes), so the
#: consumers do run while a read is pending: they see the calcs' transient
#: and the map-layer effects skip pushing it (``_header_read_pending``).
LOADER_PRIORITY = 10
CACHE_REPUBLISHED_MESSAGE = (
    "Output-step detail: the cache was rebuilt since it was loaded; refreshing."
)
#: States in which no build is running, so the cache on disk is settled.
_TERMINAL_STATES = ("ready", "stale", "failed", "missing")
#: States in which a build is queued or running.
_LIVE_STATES = ("queued", "building")

VARIABLES = {"salt": "Salinity (psu)", "temp": "Temperature (°C)", "act_eta": "Water level (m)"}
#: Column order of the band-amplitude table, matching ``BANDS`` in
#: ``boxmodel_skill`` and the keys ``band_amplitude_ratios`` returns.
BAND_COLUMNS = ("2-4 d", "4-10 d", "10-30 d", "30-400 d")
BAND_NEEDS_DAYS = "needs \u2265 120 gap-free days"
NO_POLYGONS_MESSAGE = (
    "No box outlines: add boxes.polygons to the manifest or run the model "
    "with boxes_geom.txt output."
)
#: Everything a downloaded file name may contain; anything else is dropped.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
COLUMN_TO_VARIABLE = {v: k for k, v in VARIABLE_COLUMNS.items()}
#: Spec sec246: raw output-step detail only inside a window this wide,
#: counted inclusively, so 31 means 31 calendar days on screen.
HOURLY_WINDOW_DAYS = 31

#: ...and only when that window is actually a sane number of records. Days
#: alone do not bound the work: rows are days x boxes x 86400/step, so a run
#: with ``idtbox = 60`` would put 1.29M rows and 44,640 slider ticks inside a
#: 31-day window. The day cap keeps the slider usable; this keeps the read and
#: the plot usable.
HOURLY_MAX_RECORDS = 250_000


def _hourly_step(meta) -> timedelta | None:
    """The model's output step, or None when the cache does not record one.

    "Hourly" is the file's name, not a promise: the frame holds whatever
    ``idtbox`` produced. A hardcoded hour would land between stamps on any run
    with a coarser step and select nothing at all.
    """
    try:
        seconds = int((meta or {}).get("step_seconds") or 0)
    except (TypeError, ValueError):
        return None
    return timedelta(seconds=seconds) if seconds > 0 else None


def _hourly_usable(meta, period) -> bool:
    """True when this run has raw records AND the window is short enough.

    One rule in one place, used by the map and the series, so the two can never
    describe different data under the same period. False is the ordinary
    answer: most caches are daily-only, and that is a fallback, not an error.
    """
    step = _hourly_step(meta)
    if not (meta or {}).get("hourly") or step is None:
        return False
    if not period or period[0] is None or period[1] is None:
        return False
    days = (period[1] - period[0]).days + 1  # inclusive: one day picked is one day
    if days > HOURLY_WINDOW_DAYS:
        return False
    boxes = len((meta or {}).get("boxes") or ()) or 1
    per_day = 86400 / step.total_seconds()
    return days * boxes * per_day <= HOURLY_MAX_RECORDS


def _manifest_path_value(picked, project_dir) -> str:
    """How a picked path should be written in the manifest.

    Relative when it is inside the project -- that is what keeps a manifest
    portable, and the loader requires a relative value to stay inside -- and
    absolute otherwise, which is the normal case for a run directory under an
    analysis root. The pickers hand back absolute paths either way, so this is
    the one place that decides.

    Note that this NORMALISES: an absolute path that happens to point inside
    the project is rewritten relative. Deliberate -- a manifest that names its
    own project by absolute path cannot be moved or exported -- and harmless,
    since the loader resolves a relative value against the project directory.
    """
    if not picked:
        return ""
    path = Path(picked)
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.resolve().relative_to(Path(project_dir).resolve()))
    except (ValueError, OSError):
        return str(path)


def _new_run_rows(counters: dict, entries) -> list[dict]:
    """Rows for the runs table, with fresh keys from a monotonic counter.

    Never reused, deliberately. The Remove buttons are watched by one effect
    with a per-button ledger, so a key that came round again would be taken for
    a click already handled and that row's Remove would do nothing at all.
    """
    rows = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        counters["run_key"] = counters.get("run_key", 0) + 1
        rows.append(
            {
                "key": counters["run_key"],
                "id": str(entry.get("id") or ""),
                "label": str(entry.get("label") or ""),
                "dir": str(entry.get("dir") or ""),
                # Carried so a save keeps whatever else the entry holds.
                "raw": entry,
            }
        )
    return rows


def _manifest_picker_options(value, project_dir) -> tuple[str, dict]:
    """``(selected, extra)`` for a manifest path field's dropdown.

    A picker must ALWAYS offer the value it was given. A stored path the
    project listing does not contain -- a relative one the matcher resolves
    elsewhere, or a legal absolute one outside the project -- otherwise renders
    as an empty select, and the next save writes that emptiness back and
    deletes the key. That is a silent edit to a file the user may have written
    by hand, and it is why every field here injects its own current value.
    """
    if not value or not isinstance(value, str):
        return "", {}
    path = Path(value)
    absolute = str(path if path.is_absolute() else (Path(project_dir) / path))
    return absolute, {absolute: value}


#: Where each form field lives in the document, as a key path.
_MANIFEST_FIELDS = {
    "title": ("title",),
    "grd": ("grid", "grd"),
    "bas": ("grid", "bas"),
    "boxes_txt": ("grid", "boxes_txt"),
    "polygons": ("boxes", "polygons"),
    "layer": ("boxes", "layer"),
    "id_field": ("boxes", "id_field"),
    "str": ("str",),
    "forcing_dir": ("forcing", "dir"),
    "observations": ("observations", "file"),
    "sites": ("observations", "sites"),
}


def _manifest_document(raw: dict, values: dict, runs) -> dict:
    """The document a save should write: the form's values over ``raw``.

    Overlaid, not rebuilt, and taken from the RAW file rather than from a
    loaded ``BoxModelManifest``: that object's paths are resolved absolute, so
    rebuilding from it would silently rewrite every relative path in the file
    and destroy its portability. Keys this form knows nothing about -- a future
    schema's, or a human's -- survive untouched.

    A blank optional field removes its key, and a section left with nothing in
    it goes too: the loader reads "" as absent either way, but this file is
    meant to be opened by people.
    """
    doc = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    doc["schema"] = 1
    for field, path in _MANIFEST_FIELDS.items():
        value = (values.get(field) or "").strip() if values.get(field) is not None else ""
        *parents, leaf = path
        target = doc
        for name in parents:
            section = target.get(name)
            if not isinstance(section, dict):
                section = {}
                target[name] = section
            target = section
        if value:
            target[leaf] = value
        else:
            target.pop(leaf, None)
    for name in ("grid", "boxes", "forcing", "observations"):
        if isinstance(doc.get(name), dict) and not doc[name]:
            del doc[name]
    written = []
    for row in runs:
        entry = {"id": (row.get("id") or "").strip()}
        label = (row.get("label") or "").strip()
        if label:
            # The loader defaults label to id, so writing the same thing twice
            # is noise in a file people read.
            entry["label"] = label
        entry["dir"] = (row.get("dir") or "").strip()
        # Anything else the entry carried stays, the same promise the top-level
        # document gets. "key" and "raw" are the editor's own bookkeeping.
        for name, value in row.items():
            if name not in ("key", "raw", "id", "label", "dir"):
                entry[name] = value
        written.append(entry)
    doc["runs"] = written
    return doc


def _snap_to_stamp(frame, chosen):
    """The stamp in ``frame`` nearest ``chosen``.

    The slider steps by the output step, but its value can still land between
    records after a period change, and an exact match would select nothing and
    blank the map. Ties go to the earlier stamp.
    """
    stamps = frame["stamp"]
    return stamps.iloc[(stamps - pd.Timestamp(chosen)).abs().to_numpy().argmin()]


def _hourly_box_values(frame, chosen, column) -> tuple[dict, str]:
    """``{box: value}`` at one stamp, and the map's caption."""
    stamp = _snap_to_stamp(frame, chosen)
    selection = frame[frame["stamp"] == stamp]
    values = dict(zip(selection["box"].astype(int), selection[column].astype(float), strict=True))
    return values, f"{VARIABLES[column]} at {stamp:%Y-%m-%d %H:%M}"


def _hourly_series(frame, box: int, column: str):
    """One box's raw records as a time-indexed series."""
    rows = frame[frame["box"].astype("int64") == box]
    return pd.Series(
        rows[column].astype(float).to_numpy(), index=pd.Index(rows["stamp"])
    ).sort_index()


MAP_MODES = {
    "day": "Value on the selected day",
    "mean": "Period mean",
    "bias": "Bias vs observations (posts)",
}
#: Compare tab (spec §8): the state messages, each rendered as a muted
#: paragraph. Fixed text -- nothing from the manifest -- so no sanitising.
CMP_NEED_TWO_MESSAGE = "Compare needs at least two runs with a ready cache."
CMP_SELECT_RUNS_MESSAGE = "Select two to four runs to compare."
CMP_NO_COMMON_DAYS_MESSAGE = "The selected runs share no days in this period."
CMP_NO_OBSERVATIONS_MESSAGE = "No observations configured for this project."
CMP_NO_PROJECT_MESSAGE = "Open a project first."
CMP_SKILL_EMPTY_MESSAGE = "No target has 30 or more common days across the selected runs."
CMP_PER_YEAR_EMPTY_MESSAGE = "Per-year skill needs \u2265 60 matched days per year."
#: Side-by-side row labels, keyed by the ``skill_table`` metric name.
METRIC_LABELS = {
    "n": "n",
    "bias": "bias",
    "rmse": "RMSE",
    "r": "r",
    "r2": "R\u00b2",
    "sd_ratio": "sd_mod/sd_obs",
}
#: Setup tab (spec §8): fixed state messages and labels. Nothing from the
#: manifest or the STR is in them, so they need no sanitising.
SETUP_NO_PROJECT_MESSAGE = "Open a project first."
SETUP_NO_STR_MESSAGE = "Manifest has no STR"
SETUP_NEEDS_CACHE_MESSAGE = (
    "Section interfaces and per-box meteo need a ready cache; " "boundaries are drawn from the STR."
)
SETUP_ORPHANS_LABEL = "Keys outside any section (ignored by SHYFEM)"
SETUP_NO_RIVERS_MESSAGE = "No discharge boundary with a readable .txt forcing file."
SETUP_NO_METEO_MESSAGE = "Per-box meteo needs a ready cache."
SETUP_NO_METEO_ROWS_MESSAGE = "No meteo rows for this box and period."
SETUP_DEFAULT_METEO_VARIABLE = "tair"
#: What the STR summary rows are called; unknown keys fall back to the key.
SETUP_SUMMARY_LABELS = {
    "title": "title",
    "itanf": "itanf (start)",
    "itend": "itend (end)",
    "idt": "idt (time step)",
    "idtbox": "idtbox (box output)",
    "idtflx": "idtflx (flux output)",
    "idtext": "idtext (extra output)",
    "date": "date (reference)",
    "time": "time (reference)",
    "ireib": "ireib (friction law)",
    "czdef": "czdef (friction)",
    "ibarcl": "ibarcl (baroclinic)",
    "iheat": "iheat (heat flux)",
    "ievap": "ievap (evaporation)",
    "iturb": "iturb (turbulence)",
    "isalt": "isalt",
    "itemp": "itemp",
    "nomp": "nomp (OMP threads)",
}
_STATE_BADGE = {
    "ready": "success",
    "stale": "warning",
    "building": "info",
    "queued": "info",
    "failed": "danger",
    "missing": "secondary",
}

# An absolute-path-looking token: a "/" that does NOT continue a word,
# followed by one or more segments. The lookbehind is what keeps ordinary
# prose intact -- in "3/24 rows" and "wind in m/s" the slash follows a word
# character, so neither is a path and neither is rewritten -- while a
# genuine single-segment root ("/etc", "/tmp") is still caught.
_ABS_PATH_RE = re.compile(r"(?<![\w])/[\w.@+~-]+(?:/[\w.@+~-]*)*")


def _safe_text(text: str, config, user) -> str:
    """Rewrite every absolute-path-looking token in ``text`` for display.

    ``Config.display_path`` reduces a server-mode path to ``~/rel`` or to its
    basename, and leaves a local-mode (single-user desktop) path alone. The
    surrounding words -- the part that says *what* is wrong -- are kept, so
    the message stays actionable.

    Use this for **any** service-provided string that reaches the browser,
    not just exceptions: ``CacheStatus.message`` carries the failed build
    child's own error text (e.g. a ``FileNotFoundError`` naming the absolute
    run directory), and it is rendered as the status badge's tooltip.
    """
    return _ABS_PATH_RE.sub(lambda m: config.display_path(m.group(0), user), str(text))


def _safe_error(exc: BaseException, config, user) -> str:
    """:func:`_safe_text` for an exception.

    ``ManifestError`` (and the ``ValueError`` ``confine_path`` raises inside
    ``load_manifest``/``start_build``) embeds the raw absolute path it
    rejected.
    """
    return _safe_text(str(exc), config, user)


def _build_timeout_seconds(config) -> int:
    """The wall-clock bound a cache build actually gets here.

    The same number ``_bounded_timeout_config`` hands ``start_build``, without
    copying the Config: the reaper's age cap is derived from it, so the two
    must not drift.
    """
    return config.command_timeout_seconds or BUILD_TIMEOUT_SECONDS


def _bounded_timeout_config(config: Config) -> Config:
    """Return a Config whose ``command_timeout_seconds`` is bounded.

    ``start_build`` passes ``config.command_timeout_seconds`` straight to
    ``asyncio.wait_for``; ``None`` there means a wedged build occupies a
    worker slot forever. Never mutate the shared Config (one instance backs
    every session on this worker) -- hand ``start_build`` a copy instead.
    An operator-configured value is respected as-is; only the ``None``
    default is replaced.
    """
    if config.command_timeout_seconds is not None:
        return config
    return config.model_copy(update={"command_timeout_seconds": BUILD_TIMEOUT_SECONDS})


def _fmt(x, nd: int = 3) -> str:
    """Format a metric, rendering None/NaN as an empty cell."""
    if x is None:
        return ""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return ""
    if value != value:  # NaN
        return ""
    return f"{value:.{nd}f}"


def _bias_cell(variable: str, bias) -> str:
    """Level skill is computed on anomalies (both reference scripts do this),
    so a level row's bias is structurally ~0 and means nothing. Show a dash
    rather than a number a reader would take for a real offset.
    """
    return "—" if variable == "level" else _fmt(bias)


def _band_ratio_rows(cached_run, obs, sites, start, end) -> list[dict]:
    """One row per LEVEL target (a site with a mapped box and level
    observations) with its band amplitude ratios, for the table beside the
    skill table (spec sec7).

    ``{"site": str, "ratios": dict | None}``; ``ratios`` is ``None`` when
    :func:`band_amplitude_ratios` cannot be computed -- it needs at least 120
    gap-free (one-per-calendar-day) common days, which is a much stronger
    requirement than the skill table's 30 matched days, so a run can have a
    full skill row and no band ratios at all.

    Module-level and reactive-free so it can be tested without a session.
    """
    rows: list[dict] = []
    if obs is None or sites is None or cached_run is None:
        return rows
    low, high = pd.Timestamp(start), pd.Timestamp(end)
    for _, site in sites.dropna(subset=["box"]).iterrows():
        picked = obs[(obs["site"] == site["site"]) & (obs["variable"] == "level")]
        picked = picked[(picked["date"] >= low) & (picked["date"] <= high)]
        if not len(picked):
            continue
        box = int(site["box"])
        observed = pd.Series(
            picked["value"].to_numpy(), index=pd.Index(picked["date"])
        ).sort_index()
        model = model_series(cached_run, box, VARIABLE_COLUMNS["level"], start, end)
        rows.append({"site": str(site["site"]), "ratios": band_amplitude_ratios(observed, model)})
    return rows


def _no_polygons_message(manifest_obj, cached_run) -> str | None:
    """The message for a project that has no box outlines at all.

    A manifest without ``boxes.polygons`` falls back to dissolving the boxes
    out of the grid, which needs ``meta["element_box"]`` -- i.e. the run must
    have been written with ``boxes_geom.txt``. With neither, the map is blank
    and nothing said why. Returns ``None`` while there is no cache yet: that
    is not "no outlines", it is "not known yet".
    """
    if manifest_obj is None or manifest_obj.polygons is not None:
        return None
    if cached_run is None or cached_run.meta.get("element_box"):
        return None
    return NO_POLYGONS_MESSAGE


def _series_filename(data) -> str:
    """Download name built from the box/variable ``series()`` actually
    resolved, not from the raw inputs.

    ``input.box()``/``input.variable()`` are client-supplied strings that
    reach a Content-Disposition header; ``series()`` has already validated
    both (``int(selected)``, ``column in VARIABLES``). Everything outside
    ``[A-Za-z0-9_-]`` is dropped as a second line of defence.
    """
    if not data:
        return "box_series.csv"
    box = _FILENAME_UNSAFE.sub("", str(data.get("box", ""))) or "x"
    variable = _FILENAME_UNSAFE.sub("", str(data.get("variable", ""))) or "series"
    return f"box{box}_{variable}.csv"


def _int_cell(x) -> str:
    """Format a count that ``side_by_side`` pivoted into a float column
    (``n`` is NaN where a run has no row)."""
    if x is None:
        return ""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return ""
    if value != value:  # NaN
        return ""
    return str(int(value))


def _compare_filename(variable, a, b) -> str:
    """Download name for the Compare CSV, built from the VALIDATED variable
    key and run ids (``cmp_runs_selected()``), never the raw inputs; anything
    outside ``[A-Za-z0-9_-]`` is dropped as a second line of defence."""
    if not variable or not a or not b:
        return "compare.csv"
    clean = [_FILENAME_UNSAFE.sub("", str(part)) for part in (variable, a, b)]
    if not all(clean):
        return "compare.csv"
    return f"compare_{clean[0]}_{clean[1]}_vs_{clean[2]}.csv"


def _validate_compare_runs(chosen, b, states: dict) -> tuple[list[str], str] | None:
    """Validate the Compare selection against the ready runs.

    ``chosen`` is the selectize value in SELECTION order (the shiny select
    binding returns ``selectize.items``), so A is the first entry. Ids that
    are not (or no longer) in ``states`` are dropped rather than fatal -- a
    cache can go away under a live selection -- and duplicates count once.
    B is ``b`` when it is one of the chosen runs other than A, else the
    second run. ``None`` unless 2..4 runs remain.
    """
    if not chosen:
        return None
    ids: list[str] = []
    for run_id in chosen:
        if run_id in states and run_id not in ids:
            ids.append(run_id)
    if not 2 <= len(ids) <= 4:
        return None
    if b not in ids or b == ids[0]:
        b = ids[1]
    return ids, b


def _compare_bounds(states: dict, chosen) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """The period Compare works in: the header period clamped to the compared
    runs' widest span, or that span when the header period is unset or falls
    entirely outside it.

    The clamp matches ``_period()`` on the Time-series tab. Without it the
    header ``input_date_range`` -- which reads (today, today) until the
    header run's cache fills it, and that run need not be one of the compared
    runs or ready at all -- would make the day intersection empty for ever.
    """
    if not states:
        return None
    low = min(pd.Timestamp(r.state_daily["date"].min()) for r in states.values())
    high = max(pd.Timestamp(r.state_daily["date"].max()) for r in states.values())
    if chosen and chosen[0] is not None and chosen[1] is not None:
        start = max(low, pd.Timestamp(chosen[0]))
        end = min(high, pd.Timestamp(chosen[1]))
        if start <= end:
            return start, end
    return low, high


def _empty_day_set() -> pd.DatetimeIndex:
    """The "no days at all" value every Compare consumer already handles."""
    return common_days({}, pd.Timestamp.min, pd.Timestamp.max)


def _compare_day_set(states: dict, chosen, err) -> tuple[pd.DatetimeIndex, str | None]:
    """``(the shared Compare day set, a page message)``: the runs' common days
    inside ``_compare_bounds``, or an empty day set and a message.

    ``err`` renders an exception for the browser; the page passes its own
    ``_err`` (which sanitises host paths out of the text).

    ``state_daily`` comes off disk. ``load_cache_state`` normalises its
    ``date`` column but validates nothing else, so a foreign or hand-edited
    cache can reach ``_compare_bounds``/``common_days`` with no ``date``
    column at all, or one pandas cannot compare. Reading it inside the try
    turns that into a page message -- the way ``cached_result`` does -- rather
    than an exception out of a reactive calc: today that is an error box in
    every Compare output, and a dead session the day any effect consumes the
    chain without its own try.
    """
    if not states:
        return _empty_day_set(), None
    try:
        bounds = _compare_bounds(states, chosen)
        if bounds is None:
            return _empty_day_set(), None
        return common_days(states, *bounds), None
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("boxmodel: compare day set unavailable: %s", exc)
        return _empty_day_set(), f"Compare: {err(exc)}"


def _load_compare_state(cache_dir, run_id: str, err):
    """``(the run's state_daily CachedRun, a page message)``.

    One place for every off-disk read of one run's state, so what the whole
    Compare chain assumes is checked where it can be tested.
    ``load_cache_state`` normalises the ``date`` column and validates nothing
    else, so a foreign or hand-edited cache can reach ``_cmp_box`` /
    ``period_mean_diff`` with no ``box`` column at all (``cached_result``
    makes the same check for the other tabs), and ``pd.to_datetime`` raises
    ``TypeError``, not ``ValueError``, on a ``date`` column of the wrong kind
    altogether.

    An unreadable run is DROPPED from the comparison, which is why the message
    matters: without it the tab reports "select at least two runs" while the
    Runs list still shows both as ready, blaming the user for a broken cache.
    """
    try:
        state = load_cache_state(cache_dir, run_id)
        if "box" not in state.state_daily.columns:
            raise KeyError("state_daily has no 'box' column")
        return state, None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("boxmodel: run %s state cache unreadable: %s", run_id, exc)
        return None, f"{run_id}: {err(exc)}"


def _read_cached_run(cache_dir, run_id: str):
    """Load the selected run's cache and validate what every consumer assumes.

    Blocking (several Parquet files): the page runs it via
    ``asyncio.to_thread`` (B-06). ``cache_status()`` reports "ready" for any
    ``meta.json`` that merely parses as JSON, so a hand-edited or foreign cache
    dir can reach this point without a period or a box column. Touching both
    here turns that into a page message instead of a ``KeyError`` raised later
    from inside an effect (which kills the session) or from inside a render.
    Raises ``OSError``/``ValueError``/``KeyError``/``TypeError``.
    """
    cached_run = load_cache(cache_dir, run_id)
    _cache_period(cached_run)
    if "box" not in cached_run.state_daily.columns:
        raise KeyError("state_daily has no 'box' column")
    return cached_run


def _read_run_states(work_dir, runs, registry, tmp_age_cap, err) -> tuple[dict, list[str]]:
    """``({run_id: CachedRun}, [messages])`` for every run whose cache is
    ready/stale -- the Compare tab's input. Blocking (one Parquet per run, and
    a ``stat`` walk per run for its status): run via ``asyncio.to_thread``
    (B-06). ``err`` turns an exception into a sanitised page message."""
    work_dir = Path(work_dir)
    states: dict = {}
    problems: list[str] = []
    for run in runs:
        try:
            st = cache_status(work_dir, run.id, run.dir, registry, tmp_age_cap)
        except (ValueError, OSError):
            continue
        if st.state not in ("ready", "stale"):
            continue
        state, problem = _load_compare_state(cache_dir_for(work_dir, run.id), run.id, err)
        if state is None:
            problems.append(problem)
        else:
            states[run.id] = state
    return states, problems


def _read_hourly_window_checked(cache_dir, fingerprint, period) -> tuple:
    """``(frame | None, message | None)``: the raw records of ``period`` from
    the build the page holds (``fingerprint``), or nothing.

    The window is read off disk NOW, the meta it is interpreted with was read
    at load time: if a build has published over the cache since (before or
    during this read), they describe different builds -- say so, and
    ``_watch_published`` reloads the whole run shortly. Blocking: run via
    ``asyncio.to_thread`` (B-06). Raises what ``read_hourly_window`` raises.
    """
    if published_fingerprint(cache_dir) != fingerprint:
        return None, CACHE_REPUBLISHED_MESSAGE
    frame = read_hourly_window(
        cache_dir,
        pd.Timestamp(period[0]),
        pd.Timestamp(period[1]) + timedelta(days=1) - timedelta(seconds=1),
    )
    if published_fingerprint(cache_dir) != fingerprint:
        return None, CACHE_REPUBLISHED_MESSAGE
    return (None if frame.empty else frame), None


def _interfaces_on_map(interfaces: list[dict], grd) -> list[dict]:
    """Section interfaces moved into the map's lon/lat frame (B-01).

    SHYFEM writes a section's nodes with the grid's own x/y, and the cache
    keeps them as written, so on a projected grid they are metres. They are
    reprojected by the rule the dissolved box outlines use (the EPSG the grid
    map would use, then ``grid_to_wgs84``'s fallbacks), so each interface
    lands on the boundary between its two boxes. A geographic grid, or no
    parsed grid at all, leaves them as they are; a projected grid whose CRS
    cannot be resolved drops them -- metres drawn as degrees would put the
    lines somewhere else on the planet.
    """
    if grd is None or not interfaces or _is_geographic(grd):
        return interfaces
    to_wgs84 = grid_to_wgs84(grd, _detect_projected_crs(grd))
    if to_wgs84 is None:
        logger.warning("boxmodel: section interfaces dropped: the grid's CRS is unknown")
        return []
    out = []
    for rec in interfaces:
        path = [[float(c) for c in to_wgs84(x, y)] for x, y in rec["path"]]
        out.append({**rec, "path": path})
    return out


def _reconcile_cache_dir(config, user, work_dir, project_name=None, project_id=None) -> str | None:
    """Publish finished builds and clear dead tmp dirs -- if the caller may write.

    Returns a page notice, or ``None`` when there is nothing to report.

    ``reconcile_tmp_dirs`` RENAMES and DELETES inside the project, so it needs
    the WRITE confinement, not the read one the manifest load uses:
    ``for_write=False`` also admits a shared-project viewer and an
    analysis-root reader, and this page server is mounted for every session. A
    viewer has nothing to reconcile, so failing the write check just skips it,
    silently -- it is not an error the viewer could act on.

    The registry and ``project_id`` are handed over so the reconcile can tell
    a build running in THIS worker from an abandoned directory: without them
    it decides purely on ``progress.json``'s age, and a page load during a
    long, quiet build phase would delete that build's own output directory.

    Module-level and dependency-free (it takes the config, the user and the
    directory) so the gate can be tested without a live Shiny session.
    """
    try:
        config.confine_path(Path(work_dir), user, must_exist=True, for_write=True)
    except (ValueError, OSError) as exc:
        logger.info("boxmodel: skipping cache reconcile (no write access): %s", exc)
        return None
    try:
        for msg in reconcile_tmp_dirs(
            Path(work_dir),
            registry=get_registry(),
            project_id=project_id,
            # The cap must come from the timeout that actually bounds a build
            # here, or the reaper could delete a healthy build's directory
            # before the parent would have killed it: an operator-set
            # command_timeout_seconds is respected as-is (see
            # _bounded_timeout_config) and this project's jobs legitimately
            # run longer than the cap's own floor.
            max_tmp_age=tmp_age_cap_seconds(_build_timeout_seconds(config)),
        ):
            logger.info("boxmodel cache reconcile (%s): %s", project_name, msg)
    except Exception as exc:  # noqa: BLE001 - page load must never die here
        logger.warning("boxmodel: cache reconcile failed: %s", exc, exc_info=True)
        return "Could not tidy the cache directory; a build may need to be re-run."
    return None


def _published_changed(published: dict, loaded: list, seen: dict) -> bool:
    """Has any run's published cache changed since this page looked? (B-04)

    ``published`` is ``{run_id: published_fingerprint}`` for every manifest
    run, as it is on disk now. ``loaded`` lists ``(run_id, fingerprint)`` for
    every frame the page holds -- the header run and each Compare run -- and
    those are what a change is measured against. A run the page holds nothing
    for is measured against ``seen`` (the previous tick's ``published``), so a
    cache that appears, disappears or is rebuilt for it is noticed too; on the
    first sighting there is nothing to compare with, and a cache that will not
    load (it is reported once, as a page message) is not re-read every tick.
    """
    held = {run_id for run_id, _fp in loaded}
    for run_id, fingerprint in loaded:
        if run_id in published and published[run_id] != fingerprint:
            return True
    return any(
        run_id not in held and run_id in seen and seen[run_id] != fingerprint
        for run_id, fingerprint in published.items()
    )


def _watch_decision(
    published: dict,
    *,
    states: list,
    held_run,
    pending: bool,
    seen: dict,
    since_bump: float | None,
) -> str:
    """What ``_watch_published`` does this tick: ``"skip"`` (measure nothing
    and keep ``seen``), ``"bump"`` (reload) or ``"none"``.

    ``states`` is ``[(run_id, fingerprint)]`` for the settled Compare runs;
    ``held_run`` is ``(run_id, fingerprint, is_live_fallback)`` for the
    settled header run, or None. ``since_bump`` is the seconds since this
    watch last bumped (None: never).

    * A read pending -> skip: the calcs still hold the previous build, and
      measuring that against the new fingerprint bumps again; the read
      landing re-runs the watch.
    * The header run shown from the live-build fallback is NOT held: the
      fallback is by design the previous build, so it is measured only
      tick-to-tick (``seen``), like a run the page holds nothing for.
      Measured against ``published`` it bumped forever (B-04 review).
    * A change within ``WATCH_SECONDS`` of the last bump -> skip, so any
      mis-measure costs one reload per tick, never a spin.
    """
    if pending:
        return "skip"
    loaded = list(states)
    if held_run is not None and not held_run[2]:
        loaded.append((held_run[0], held_run[1]))
    if not _published_changed(published, loaded, seen):
        return "none"
    if since_bump is not None and since_bump < WATCH_SECONDS:
        return "skip"
    return "bump"


def _settled_result(stored, current_key):
    """The result in a loader's ``(key, result)`` store if it answers
    ``current_key``, else None (nothing stored, or a newer read pending)."""
    if stored is None or stored[0] != current_key:
        return None
    return stored[1]


def _remember_good(last: dict, project_id, run_id: str, cached_run) -> None:
    """Remember a successfully loaded run, KEYED by the run it belongs to."""
    last["good"] = (project_id, run_id, cached_run)


def _pick_live_fallback(last: dict, project_id, run_id: str):
    """The previously loaded run to keep showing during a rebuild -- but only
    if it is the run currently selected.

    The slot must be keyed. Unkeyed, this sequence silently shows the wrong
    data: run A ready -> Build A -> switch to run B (ready, so B is loaded and
    remembered) -> switch back to A while A is still building -> the live
    branch hands back B's frame while the Run select and the badge both say A,
    so the map, the series and the skill table are all B's.
    """
    stored = last.get("good")
    if not stored:
        return None
    stored_project, stored_run, cached_run = stored
    if stored_project == project_id and stored_run == run_id:
        return cached_run
    return None


def _cache_period(cached_run) -> tuple:
    meta = cached_run.meta.get("period") or {}
    return pd.Timestamp(meta["start"]).date(), pd.Timestamp(meta["end"]).date()


# --- Setup tab helpers (module-level, reactive-free, tested directly) --------


def _meteo_variables(frame) -> dict[str, str]:
    """Select choices for the per-box meteo plot: every ``meteo_daily`` column
    other than ``date``/``box``, ``tair`` first when present, otherwise in
    column order. ``{}`` for no frame or no meteo columns (a run without
    ``boxes_meteo.txt`` has the two key columns and nothing else)."""
    if frame is None:
        return {}
    names = [str(c) for c in frame.columns if str(c) not in ("date", "box")]
    if SETUP_DEFAULT_METEO_VARIABLE in names:
        names.remove(SETUP_DEFAULT_METEO_VARIABLE)
        names.insert(0, SETUP_DEFAULT_METEO_VARIABLE)
    return {name: name for name in names}


def _boundary_rows(bounds, notes: dict) -> list[dict]:
    """One display row per STR ``$bound<k>`` for the boundaries table.

    ``notes`` is ``rivers_result()``'s ``{k: (series | None, note | None)}``;
    only the NOTE is taken from it -- the row shows ``boundn`` exactly as the
    STR wrote it plus the resolver's note, never a resolved path. Numbers are
    formatted here (``zfact`` with ``:g`` so ``0.25`` and ``1`` read
    naturally); the text fields are raw and are sanitised/escaped by the
    render.
    """
    rows: list[dict] = []
    for b in bounds:
        _series, note = notes.get(b.number, (None, None))
        rows.append(
            {
                "number": b.number,
                "title": b.title or "",
                "kind": kind(b),
                "ibtyp": "" if b.ibtyp is None else str(b.ibtyp),
                "nodes": len(b.kbound),
                "zfact": f"{b.zfact:g}",
                "boundn": b.boundn or "",
                "note": note or "",
                "other_files": ", ".join(f"{k}: {v}" for k, v in b.other_files.items()),
            }
        )
    return rows


def _restrict_series(series, bounds):
    """Restrict a forcing series to ``bounds = (start, end)``.

    ``bounds`` is ``period_from_summary`` (Timestamps; a date-only ``itend``
    stamps midnight) or the cache period (``date`` objects). An end with no
    time of day is taken as the WHOLE end day -- ``itend = '2009-01-11'`` keeps
    the 06:00 row of the 11th -- while a timed end (``'::06:00'``) is exact.
    ``None`` bounds return the series untouched.
    """
    if bounds is None:
        return series
    start, end = pd.Timestamp(bounds[0]), pd.Timestamp(bounds[1])
    if end == end.normalize():
        end = end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return series[(series.index >= start) & (series.index <= end)]


def _missing_nodes_message(missing) -> str | None:
    """The Setup message for STR ``kbound`` node ids the grid does not have."""
    ids = sorted({int(n) for n in missing})
    if not ids:
        return None
    return "STR boundary nodes not in the grid: " + ", ".join(str(n) for n in ids)


@module.ui
def boxmodel_ui() -> ui.Tag:
    """Box-model page UI: run/variable/period controls plus the Map,
    Time-series and Compare tabs."""
    return ui.div(
        ui.h3("Box model"),
        ui.p(
            "Aggregated box output for this project's runs: maps of a box variable "
            "and per-box time series against observations.",
            class_="text-muted",
        ),
        ui.output_ui("manifest_error"),
        ui.layout_columns(
            ui.input_select("run", "Run", choices={}),
            ui.input_select("variable", "Variable", choices=VARIABLES),
            ui.input_date_range("period", "Period"),
            ui.div(
                ui.output_ui("cache_state"),
                ui.input_action_button("build", "Build cache", class_="btn-primary btn-sm me-1"),
                ui.input_action_button("cancel", "Cancel", class_="btn-outline-secondary btn-sm"),
                ui.input_checkbox("hourly", "Include output-step detail", value=False),
                ui.div(
                    "Adds the raw records to the cache, so the map and the series can "
                    f"step through a window of up to {HOURLY_WINDOW_DAYS} days. Several "
                    "times larger than the daily cache, and it counts against the "
                    "project's storage quota.",
                    class_="form-text",
                ),
            ),
            col_widths=(3, 2, 4, 3),
        ),
        ui.navset_card_tab(
            ui.nav_panel(
                "Map",
                ui.layout_columns(
                    ui.div(
                        ui.input_select("map_mode", "Colour by", MAP_MODES),
                        ui.output_ui("day_slider"),
                    ),
                    grid_map_ui("boxmap", height="540px"),
                    ui.output_ui("map_legend"),
                    col_widths=(3, 7, 2),
                ),
            ),
            ui.nav_panel(
                "Time series",
                ui.layout_columns(
                    ui.input_select("box", "Box", choices={}),
                    ui.download_button(
                        "download_csv", "Export CSV", class_="btn-outline-primary btn-sm mt-4"
                    ),
                    col_widths=(3, 3),
                ),
                output_widget("ts_plot"),
                ui.output_ui("skill_table"),
                ui.output_ui("band_ratios"),
            ),
            ui.nav_panel(
                "Compare",
                ui.p(
                    "Two to four runs on the days they all share: the map shows B \u2212 A "
                    "of the period mean, the plot overlays the selected box's series, and "
                    "the tables put the fit statistics side by side.",
                    class_="text-muted small",
                ),
                ui.output_ui("cmp_controls"),
                ui.layout_columns(
                    grid_map_ui("cmpmap", height="440px"),
                    ui.output_ui("cmp_legend"),
                    col_widths=(9, 3),
                ),
                output_widget("cmp_plot"),
                ui.output_ui("cmp_skill"),
                ui.output_ui("cmp_per_year"),
                ui.download_button(
                    "cmp_download",
                    "Download comparison CSV",
                    class_="btn-outline-primary btn-sm mt-2",
                ),
            ),
            ui.nav_panel(
                "Manifest",
                ui.p(
                    "What this project's boxmodel.json says: the mesh, the box outlines, "
                    "the STR, the forcing directory, the observations and the runs to "
                    "analyse. Editing it here is the alternative to writing the file by "
                    "hand. Saving validates first, so a rejected change never reaches "
                    "the file.",
                    class_="text-muted small",
                ),
                ui.output_ui("manifest_form"),
                ui.hr(),
                ui.output_ui("manifest_runs"),
            ),
            ui.nav_panel(
                "Setup",
                ui.p(
                    "What the run was set up with: the STR's open boundaries on the mesh "
                    "(nodes coloured by type, section interfaces from the cache), the river "
                    "discharge files named by boundn, per-box meteo from the cache and the "
                    "STR summary. Read-only.",
                    class_="text-muted small",
                ),
                ui.output_ui("setup_message"),
                ui.layout_columns(
                    grid_map_ui("setupmap", height="440px"),
                    ui.output_ui("setup_summary"),
                    col_widths=(8, 4),
                ),
                ui.output_ui("setup_boundaries"),
                output_widget("setup_rivers"),
                ui.layout_columns(
                    ui.output_ui("setup_meteo_controls"),
                    output_widget("setup_meteo"),
                    col_widths=(3, 9),
                ),
            ),
            id="tabs",
        ),
    )


@module.server
def boxmodel_server(
    input,
    output,
    session,
    config: Config,
    active_project: reactive.Value,
    tutorial_context=None,
    current_user=None,
) -> dict:
    """Box-model page server."""
    extra_layers: reactive.Value = reactive.value([])
    legend_bins: reactive.Value = reactive.value([])
    # Compare map: written ONLY by _cmp_layers, read by grid_map_server and
    # the legend render (same discipline as extra_layers/legend_bins).
    cmp_layers: reactive.Value = reactive.value([])
    cmp_legend_bins: reactive.Value = reactive.value([])
    # Setup map: written ONLY by _setup_layers; setup_selected_boundary is
    # written by the per-row "select" links (see _register_setup_pick).
    setup_layers: reactive.Value = reactive.value([])
    setup_selected_boundary: reactive.Value = reactive.value(None)
    _setup_pick_registered: set[int] = set()
    grd_file: reactive.Value = reactive.value(None)
    grd_error: reactive.Value = reactive.value(None)
    selected_box: reactive.Value = reactive.value(None)
    # Three write-only-for-their-writer values, deliberately kept apart:
    #
    # * poll_kick     -- written ONLY by the build/cancel handlers, read ONLY
    #                    by the poller (so a fresh build restarts polling);
    # * status_tick   -- written ONLY by the poller, read ONLY by status(),
    #                    which only the badge renders. It ticks every 2 s
    #                    during a build so the records/expected progress
    #                    moves;
    # * cache_generation -- written ONLY by the poller, and only when the
    #                    cache's *contents* can actually have changed (a
    #                    terminal state reached or left). Everything
    #                    expensive hangs off THIS, not off status_tick:
    #                    cached_result -> polygons_result/series/skill.
    #                    Coupling them would re-run load_box_polygons (a
    #                    fiona re-open, on the event loop) and push a fresh
    #                    layer set every 2 s while a build runs -- the map
    #                    would flicker and the worker would do real work per
    #                    tick for nothing.
    #
    # No value here is ever read by the effect that writes it: a read-then-write
    # on the same reactive pegs the worker at 100% CPU and freezes every output
    # (see the shiny reactive-loop postmortem).
    poll_kick: reactive.Value = reactive.value(0)
    status_tick: reactive.Value = reactive.value(0)
    cache_generation: reactive.Value = reactive.value(0)
    # Plain (non-reactive) per-session bookkeeping, deliberately not
    # reactive.Values: read-then-write on a reactive from the same effect is
    # exactly the loop above.
    counters = {"kick": 0, "tick": 0, "generation": 0, "manifest": 0, "run_key": 0}
    last = {
        "state": None,
        "runs": None,
        "boxes": None,
        "period": None,
        "grd": False,
        "good": None,
        "project": None,
        # {run_id: published_fingerprint} as the watch last saw it (B-04).
        "published": {},
        # The cached_store key under which the loader stored a live-build
        # fallback (the previous build, shown during a rebuild), else None.
        "live_fallback": None,
        # time.monotonic() of the watch's last cache_generation bump.
        "watch_bump": None,
        # Remove buttons are watched by one effect, so it needs to remember
        # which clicks it has already acted on.
        "removed": {},
    }

    def _user():
        return current_user() if current_user is not None else None

    def _project():
        return active_project.get() if active_project is not None else None

    def _err(exc: BaseException) -> str:
        return _safe_error(exc, config, _user())

    def _text(text: str) -> str:
        """Sanitise a service-provided string before it reaches the browser."""
        return _safe_text(text, config, _user())

    def _kick_poller() -> None:
        counters["kick"] += 1
        poll_kick.set(counters["kick"])

    def _bump_status() -> None:
        """Badge-only refresh (build progress). Cheap: nothing heavy reads it."""
        counters["tick"] += 1
        status_tick.set(counters["tick"])

    def _bump_cache_generation() -> None:
        """The cache's contents may have changed -- re-read it and everything
        derived from it. Only ever called on a terminal-state transition."""
        counters["generation"] += 1
        cache_generation.set(counters["generation"])

    # --- manifest ---------------------------------------------------------

    #: Bumped by a successful manifest save. Read by ``manifest_result`` so the
    #: run selector, the tabs and the cache badge follow a save immediately --
    #: including the first save of all, which turns "boxmodel.json not found"
    #: into a working page without a reload.
    manifest_generation: reactive.Value = reactive.value(0)

    @reactive.calc
    def manifest_result() -> tuple:
        """``(manifest, error, notice)`` -- never raises.

        The project's work_dir is routed through ``confine_path`` before it
        reaches ``load_manifest`` (the loader confines the paths *inside* the
        manifest but not the project directory it is handed -- that is the
        caller's job).
        """
        manifest_generation.get()
        proj = _project()
        if proj is None:
            return None, "Open a project first.", None
        usr = _user()
        try:
            project_dir = config.confine_path(
                Path(proj["work_dir"]), usr, must_exist=True, for_write=False
            )
        except (ValueError, OSError) as exc:
            logger.warning("boxmodel: project directory rejected: %s", exc)
            return None, _err(exc), None
        try:
            manifest_obj = load_manifest(project_dir, config, usr)
        except ManifestError as exc:
            return None, _err(exc), None
        except (OSError, ValueError) as exc:
            logger.warning("boxmodel: manifest could not be read: %s", exc)
            return None, _err(exc), None

        # Publish any build that finished while nobody was watching and clear
        # dead tmp dirs -- before anything reads the cache status, so a
        # just-finished build shows as "ready" straight away. Gated on the
        # WRITE confinement and never raising; see _reconcile_cache_dir.
        notice = _reconcile_cache_dir(
            config, usr, proj["work_dir"], proj.get("name"), proj.get("id")
        )
        return manifest_obj, None, notice

    def manifest():
        return manifest_result()[0]

    @reactive.effect
    def _forget_cached_run_on_project_change():
        """Drop the remembered run when the project changes.

        ``_pick_live_fallback`` already refuses to hand back a run that is not
        the selected one, so this is not what makes the fallback correct -- it
        is so a session that moves to another project stops holding the old
        project's DataFrames.
        """
        proj = _project()
        project_id = proj["id"] if proj else None
        if project_id != last["project"]:
            last["project"] = project_id
            last["good"] = None

    @reactive.effect
    def _fill_runs():
        manifest_obj = manifest()
        choices = {r.id: r.label for r in manifest_obj.runs} if manifest_obj is not None else {}
        if choices == last["runs"]:
            return
        last["runs"] = choices
        ui.update_select("run", choices=choices, selected=next(iter(choices), None))

    @reactive.effect
    def _load_grd():
        """Parse the manifest's .grd once per manifest change.

        ``grid_map_server`` expects a parsed ``GrdFile`` in its ``grd_file``
        reactive, not a path, and the box layers must always be paired with a
        real grid (the no-grid path in grid_map renders no basemap and no
        legend).
        """
        manifest_obj = manifest()
        path = str(manifest_obj.grd) if manifest_obj is not None else None
        if last["grd"] and path == last.get("grd_path"):
            return
        last["grd"] = True
        last["grd_path"] = path
        if path is None:
            grd_file.set(None)
            grd_error.set(None)
            return
        try:
            grd_file.set(GrdParser.parse_file(Path(path)))
            grd_error.set(None)
        except Exception as exc:  # noqa: BLE001 - any parser failure is a page message
            logger.warning("boxmodel: grid could not be parsed: %s", exc)
            grd_file.set(None)
            grd_error.set(f"Grid: {_err(exc)}")

    def _tmp_age_cap() -> float:
        """The reaper's absolute age cap for this deployment.

        Derived from the same bounded config ``start_build`` gets, so status
        and the reaper agree with the timeout that actually bounds a build:
        with the cap on its own floor and an operator-raised timeout, a page
        load could otherwise judge a healthy build dead hours before the
        parent would have killed it.
        """
        return tmp_age_cap_seconds(_build_timeout_seconds(config))

    def _run_entry():
        manifest_obj = manifest()
        run_id = input.run()
        runs = manifest_obj.runs if manifest_obj is not None else []
        return next((r for r in runs if r.id == run_id), None)

    # --- cache status and the poller --------------------------------------

    def _status_now():
        """Current cache status, deliberately independent of ``status_tick``.

        Both the poller and ``cached_result`` call this rather than
        ``status()``: the poller so that bumping the tick cannot re-trigger
        itself, and ``cached_result`` so that the 2 s badge tick does not drag
        the whole parquet/polygon/layer chain along with it.
        """
        manifest_obj = manifest()
        run = _run_entry()
        proj = _project()
        if manifest_obj is None or run is None or proj is None:
            return None
        try:
            return cache_status(
                Path(proj["work_dir"]), run.id, run.dir, get_registry(), _tmp_age_cap()
            )
        except (OSError, ValueError) as exc:
            logger.warning("boxmodel: cache status failed: %s", exc)
            return None

    @reactive.calc
    def status():
        status_tick.get()
        return _status_now()

    @reactive.effect
    def _poll():
        """Poller-owned trigger: re-arm only while a build is actually live.

        Reads ``poll_kick`` (bumped by the build/cancel handlers) so a fresh
        build starts it; writes ``status_tick`` and ``cache_generation``,
        neither of which it reads, so refreshing the UI cannot refresh the
        poller. Once no build is queued or building, it publishes the
        terminal state once and stops. (The only timer on an idle page is
        ``_watch_published``'s ``stat`` of each run's ``meta.json``.)

        The two writes are deliberately not the same signal. ``status_tick``
        fires on every 2 s tick, because the badge shows live
        records/expected progress. ``cache_generation`` fires only when the
        state crosses into or out of a terminal state -- i.e. only when the
        cache on disk can actually have changed -- because everything
        expensive (re-reading the parquet, re-opening the polygons with
        fiona, rebuilding the map layers) hangs off it.
        """
        poll_kick.get()
        current = _status_now()
        state = current.state if current is not None else None
        previous = last["state"]
        changed = previous != state
        last["state"] = state
        live = state in _LIVE_STATES
        if changed:
            _bump_status()
            # A terminal state was reached, or one was left: the published
            # cache may be new (or gone). This is the ONLY path that
            # invalidates the cached run and everything derived from it.
            if state in _TERMINAL_STATES or previous in _TERMINAL_STATES:
                _bump_cache_generation()
        if not live:
            return
        # Tick the badge every poll, not only on a state change: the
        # records/expected numbers move while the state stays "building".
        if not changed:
            _bump_status()
        reactive.invalidate_later(POLL_SECONDS)

    @reactive.effect
    def _watch_published():
        """Notice a cache republished by a build this session did not start (B-04).

        ``_poll`` runs only after this session's own Build or Cancel, so a
        rebuild started in another session -- or by another worker -- was
        invisible until the run was re-selected: the page went on showing the
        old build, and an hourly window read off disk would have paired the
        NEW build's records with the OLD build's meta. While the manifest has
        runs this re-arms every ``WATCH_SECONDS`` and stats each run's
        ``meta.json`` -- nothing else -- and bumps ``cache_generation`` only
        when a fingerprint differs from what the page holds
        (``_published_changed``). What to measure is ``_watch_decision``:
        nothing while a read is pending (B-06), the live-build fallback only
        tick-to-tick (it is by design not the published build -- measured
        against it, this bumped, the loader re-stored the same fallback and
        this re-ran: a self-write loop for the whole build), and at most one
        bump per ``WATCH_SECONDS``. The reload a bump leads to re-runs this
        once it lands, finds them equal, and writes nothing.
        """
        manifest_obj = manifest()
        proj = _project()
        if manifest_obj is None or proj is None or not manifest_obj.runs:
            return
        reactive.invalidate_later(WATCH_SECONDS)
        work_dir = Path(proj["work_dir"])
        try:
            published = {
                run.id: published_fingerprint(cache_dir_for(work_dir, run.id))
                for run in manifest_obj.runs
            }
        except ValueError as exc:  # a run id the cache layout refuses
            logger.warning("boxmodel: cache watch skipped: %s", exc)
            return
        # Reads both stores (so a read landing re-runs this) but the keys
        # under isolate: this effect bumps cache_generation, which they hold.
        stored_run = cached_store.get()
        stored_states = run_states_store.get()
        with reactive.isolate():
            run_settled = _settled_result(stored_run, _cached_key())
            states_settled = _settled_result(stored_states, _run_states_key())
        held_run = None
        if run_settled is not None and run_settled[0] is not None:
            held_run = (
                run_settled[0].run_id,
                run_settled[0].fingerprint,
                stored_run[0] == last["live_fallback"],
            )
        decision = _watch_decision(
            published,
            states=[(r.run_id, r.fingerprint) for r in (states_settled or ({}, []))[0].values()],
            held_run=held_run,
            pending=run_settled is None or states_settled is None,
            seen=last["published"],
            since_bump=(
                None if last["watch_bump"] is None else time.monotonic() - last["watch_bump"]
            ),
        )
        if decision == "skip":
            return  # `seen` kept: re-measured when the read lands / next tick
        last["published"] = published
        if decision == "bump":
            logger.info("boxmodel: a cache was republished elsewhere; reloading")
            last["watch_bump"] = time.monotonic()
            _bump_status()
            _bump_cache_generation()

    @render.ui
    def cache_state():
        current = status()
        if current is None:
            return ui.tags.span("no run selected", class_="text-muted")
        text = current.state
        progress = current.progress or {}
        if current.state in _LIVE_STATES and progress:
            text = f"{text} {progress.get('records', 0)}/{progress.get('expected', '?')}"
        return ui.tags.span(
            text,
            class_=f"badge bg-{_STATE_BADGE.get(current.state, 'secondary')}",
            # CacheStatus.message carries the failed build child's own
            # error text, which can name the absolute run directory.
            title=_text(current.message or ""),
        )

    # --- build / cancel (writes: gated inside the handler) -----------------

    @reactive.effect
    @reactive.event(input.build)
    async def _build():
        proj = _project()
        run = _run_entry()
        usr = _user()
        if proj is None or run is None:
            ui.notification_show("Select a run first.", type="warning", duration=5)
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        try:
            await start_build(
                get_registry(),
                project=proj,
                run_id=run.id,
                run_dir=run.dir,
                user=usr,
                config=_bounded_timeout_config(config),
                hourly=bool(input.hourly()),
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            ui.notification_show(_err(exc), type="error", duration=8)
            return
        ui.notification_show(f"Building cache for {run.label}", type="message", duration=4)
        _kick_poller()

    @reactive.effect
    @reactive.event(input.cancel)
    async def _cancel():
        proj = _project()
        run = _run_entry()
        usr = _user()
        if proj is None or run is None:
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        try:
            cancelled = await cancel_build(
                get_registry(), (int(proj["id"]), run.id), project=proj, user=usr
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            ui.notification_show(_err(exc), type="error", duration=8)
            return
        ui.notification_show(
            "Build cancelled" if cancelled else "No build to cancel", type="message", duration=4
        )
        _kick_poller()

    # --- cached run -------------------------------------------------------

    # Every cache read below runs in a thread (B-06): an async effect reads
    # what it needs on the loop, hands the read to ``asyncio.to_thread``, and
    # stores ``(key, result)``; a thin calc hands the result out while its key
    # is current. The worker's one event loop serves every session, so a read
    # left on it froze everyone else's page for as long as it took. The
    # loaders start before the outputs (higher priority), but Shiny does not
    # wait for their async part, so consumers DO run while a read is pending
    # and see the calc's fallback (a key from an earlier request) until the
    # read lands and re-runs them; the map-layer effects skip that transient
    # rather than push it (``_header_read_pending``).
    cached_store: reactive.Value = reactive.value(None)

    def _cached_key() -> tuple:
        proj = _project()
        run = _run_entry()
        return (
            proj["id"] if proj is not None else None,
            run.id if run is not None else None,
            cache_generation.get(),
        )

    @reactive.effect(priority=LOADER_PRIORITY)
    async def _load_cached_run():
        """Read the selected run's cache off the loop into ``cached_store``.

        Depends on ``cache_generation`` and NOT on ``status_tick``: this is
        the head of the expensive chain (parquet read -> polygons -> layers
        -> series -> skill), so it must not re-run on the poller's 2 s badge
        tick. ``_status_now()`` is the non-reactive status probe for the same
        reason. Writes ``cached_store`` and never reads it.
        """
        key = _cached_key()
        proj = _project()
        run = _run_entry()
        current = _status_now()
        state = current.state if current is not None else None
        last["live_fallback"] = None
        if proj is None or run is None:
            last["good"] = None
            cached_store.set((key, (None, None)))
            return
        if state in _LIVE_STATES:
            # A rebuild is running. cache_status() reports the registry
            # handle before the published cache, so the state is "building"
            # even though last build's parquet is still on disk and still
            # valid -- keep showing it rather than blanking map, series and
            # skill table for the whole rebuild. The badge still says
            # building, with progress. Only ever the run that is actually
            # selected: see _pick_live_fallback.
            # Marked, so the republish watch does not measure it: it is by
            # design NOT the published build (see _watch_decision).
            last["live_fallback"] = key
            cached_store.set((key, (_pick_live_fallback(last, proj["id"], run.id), None)))
            return
        if state not in ("ready", "stale"):
            last["good"] = None
            cached_store.set((key, (None, None)))
            return
        cache_dir = cache_dir_for(Path(proj["work_dir"]), run.id)
        try:
            cached_run = await asyncio.to_thread(_read_cached_run, cache_dir, run.id)
        except Exception as exc:  # noqa: BLE001 - an escaping exception ends the session
            logger.warning("boxmodel: cache could not be loaded: %s", exc)
            last["good"] = None
            cached_store.set((key, (None, f"Cache: {_err(exc)}")))
            return
        _remember_good(last, proj["id"], run.id, cached_run)
        cached_store.set((key, (cached_run, None)))

    @reactive.calc
    def cached_result() -> tuple:
        """The loaded cache, and a page message if it could not be read.

        Read by ``_load_cached_run`` off the loop. While a newer request is
        still being read, the previous result is kept if it is for the same
        project and run (a reload of the same run), and nothing otherwise.
        """
        stored = cached_store.get()
        if stored is None:
            return None, None
        key, result = stored
        return result if key[:2] == _cached_key()[:2] else (None, None)

    def cached():
        return cached_result()[0]

    def _header_read_pending() -> bool:
        """True while the selected run's cache is still being read (B-06).

        Reactive on ``cached_store`` and the key, so a caller re-runs when
        the read lands. The map-layer effects return early on it: pushing
        the transient sent the map a layer set without the boxes and cost a
        second full mesh build once the read landed.
        """
        stored = cached_store.get()
        return stored is None or stored[0] != _cached_key()

    @reactive.effect
    def _fill_period_and_boxes():
        cached_run = cached()
        if cached_run is None:
            return
        start, end = _cache_period(cached_run)
        if (start, end) != last["period"]:
            last["period"] = (start, end)
            ui.update_date_range("period", start=start, end=end, min=start, max=end)
        boxes = {
            str(b): f"box {b}"
            for b in sorted(int(b) for b in cached_run.state_daily["box"].unique())
        }
        if boxes != last["boxes"]:
            last["boxes"] = boxes
            ui.update_select("box", choices=boxes, selected=next(iter(boxes), None))

    def _period():
        """The selected period, clamped to what the cache actually covers.

        ``input_date_range`` starts on today/today, so before
        ``update_date_range`` lands the raw input would select nothing at
        all; an out-of-range pick would do the same.
        """
        cached_run = cached()
        if cached_run is None:
            return None
        low, high = _cache_period(cached_run)
        chosen = input.period()
        if chosen and chosen[0] is not None and chosen[1] is not None:
            start, end = max(low, chosen[0]), min(high, chosen[1])
            if start <= end:
                return start, end
        return low, high

    # --- observations and polygons ---------------------------------------

    @reactive.calc
    def observations_result() -> tuple:
        manifest_obj = manifest()
        if manifest_obj is None or not manifest_obj.observations or not manifest_obj.sites:
            return None, None, None
        try:
            obs, report = load_observations(manifest_obj.observations)
            sites = load_sites(manifest_obj.sites)
        except (ObservationError, OSError, ValueError) as exc:
            logger.warning("boxmodel: observations could not be loaded: %s", exc)
            return None, None, f"Observations: {_err(exc)}"
        if report.get("dropped_nonfinite") or report.get("dropped_level_le0"):
            logger.info("boxmodel observations report: %s", report)
        return obs, sites, None

    def observations():
        obs, sites, _error = observations_result()
        return obs, sites

    @reactive.calc
    def polygons_result() -> tuple:
        manifest_obj = manifest()
        if manifest_obj is None:
            return {}, None
        cached_run = cached()
        try:
            # Inside the try: meta["boxes"] comes off disk, so a foreign or
            # hand-edited cache can hand us entries without a "box" key.
            expected = None
            if cached_run is not None:
                expected = {int(b["box"]) for b in cached_run.meta.get("boxes", [])} or None
            if manifest_obj.polygons is not None:
                return (
                    load_box_polygons(
                        manifest_obj.polygons,
                        manifest_obj.polygons_layer,
                        manifest_obj.id_field,
                        expected_boxes=expected,
                    ),
                    None,
                )
            if cached_run is not None and cached_run.meta.get("element_box"):
                # Hand the dissolve the EPSG the grid map itself would use:
                # a geographic grid needs none, a projected one must not be
                # silently treated as lon/lat.
                grd = grd_file.get()
                epsg = None if (grd is None or _is_geographic(grd)) else _detect_projected_crs(grd)
                return (
                    dissolve_boxes_from_grid(
                        # The parsed grid this page already holds (the EPSG
                        # decision just above needs it). The parser memoises 8
                        # grids, so the path form was usually a cache hit, not
                        # a second parse; what this guarantees is that the
                        # outlines and the map describe the same grid. A grid
                        # that failed to parse leaves the reactive None, and
                        # the manifest path still works.
                        grd if grd is not None else manifest_obj.grd,
                        cached_run.meta["element_box"],
                        epsg=epsg,
                    ),
                    None,
                )
        except (PolygonError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("boxmodel: box polygons unavailable: %s", exc)
            return {}, f"Box polygons: {_err(exc)}"
        # Neither source of outlines exists: without this the map renders
        # blank and says nothing about why (Review Important 6). The message
        # is fixed text -- no path, nothing from the manifest -- so it needs
        # no sanitising.
        return {}, _no_polygons_message(manifest_obj, cached_run)

    def polygons():
        return polygons_result()[0]

    # --- page messages ----------------------------------------------------

    @render.ui
    def manifest_error():
        """Every page-level message in one place; all text via ui.tags."""
        _manifest_obj, error, notice = manifest_result()
        blocks = []
        if error:
            blocks.append(
                ui.div(
                    ui.tags.strong("Box model: "),
                    ui.tags.span(error),
                    class_="alert alert-warning",
                )
            )
        for message in (
            grd_error.get(),
            observations_result()[2],
            polygons_result()[1],
            cached_result()[1],
            hourly_window_result()[1],
        ):
            if message:
                blocks.append(ui.div(ui.tags.span(message), class_="alert alert-warning"))
        if notice:
            blocks.append(ui.div(ui.tags.span(notice), class_="alert alert-info"))
        return ui.div(*blocks) if blocks else None

    # --- manifest editing ---------------------------------------------------

    #: The runs table being edited: {"key", "id", "label", "dir", "raw"}.
    #: Keys are monotonic and NEVER reused -- a reused key would collide with
    #: the per-button ledger below and leave that row's Remove dead.
    runs_rows: reactive.Value = reactive.value([])

    def _coerce_section(doc: dict, name: str) -> dict:
        """A manifest section as a dict, whatever the file actually holds.

        The loader's ``_section`` refuses a wrongly-typed section with a clear
        error; the form has to keep rendering anyway, because replacing a
        broken manifest is exactly what it is for.
        """
        value = doc.get(name)
        return value if isinstance(value, dict) else {}

    @reactive.calc
    def raw_manifest() -> dict:
        """The manifest document as it is ON DISK, or ``{}`` when there is none.

        Raw on purpose: the form edits the file's own values, not the resolved
        paths of a loaded ``BoxModelManifest``. An unreadable, oversized or
        invalid file also gives ``{}`` -- the loader's error is already on the
        page, and an empty form is what lets the user replace it.
        """
        manifest_generation.get()
        proj = _project()
        if proj is None:
            return {}
        try:
            project_dir = config.confine_path(
                Path(proj["work_dir"]), _user(), must_exist=True, for_write=False
            )
            path = Path(project_dir) / MANIFEST_NAME
            if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
                return {}
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as exc:
            logger.info("boxmodel: manifest not readable for editing: %s", exc)
            return {}
        return doc if isinstance(doc, dict) else {}

    @reactive.effect
    def _seed_runs_rows():
        """Refill the runs table from the file whenever the file changes."""
        runs_rows.set(_new_run_rows(counters, raw_manifest().get("runs")))

    def _harvest_rows() -> list[dict]:
        """The rows as the user currently has them on screen.

        Called before any structural change: the row inputs are recreated from
        ``runs_rows`` on every re-render, so a mutation that did not harvest
        first would silently revert whatever the user had typed.
        """
        harvested = []
        for row in runs_rows.get():
            updated = dict(row)
            for field in ("id", "label", "dir"):
                input_id = f"run_{row['key']}_{field}"
                if input_id in input:
                    updated[field] = str(input[input_id]() or "").strip()
            harvested.append(updated)
        return harvested

    def _run_dir_choices(current: str) -> dict:
        """Project directories, analysis-root directories, and the row's own
        value. The last one matters: the live manifest's dirs are absolute
        under a root, and a select that does not list the current value renders
        empty -- then a save would write that emptiness back."""
        proj = _project()
        choices: dict[str, str] = {}
        for rel in project_rel_dir_choices(proj, _user(), config):
            choices[rel] = rel
        for absolute in analysis_root_dir_choices(config, _user()):
            choices[absolute] = absolute
        if current and current not in choices:
            choices[current] = current
        return choices

    @render.ui
    def manifest_form():
        """The scalar half of the form. Separate from the runs table so that
        adding or removing a run does not re-render these inputs and revert
        whatever the user has typed into them."""
        proj = _project()
        if proj is None:
            return ui.p("Open a project first.", class_="text-muted")
        doc = raw_manifest()
        grid = _coerce_section(doc, "grid")
        boxes = _coerce_section(doc, "boxes")
        forcing = _coerce_section(doc, "forcing")
        obs = _coerce_section(doc, "observations")
        usr = _user()
        project_dir = Path(proj["work_dir"])

        def _picker(input_id, label, exts, value):
            """A file picker that ALWAYS offers the value it was given.

            Without the injection a stored path the project listing does not
            contain -- a relative one that the matcher resolves elsewhere, or a
            legal absolute one outside the project -- renders as an empty
            select, and the next save writes that emptiness back, deleting the
            key. That is a silent edit to a file the user may have written by
            hand, so it is guarded here rather than trusted.
            """
            selected, extra = _manifest_picker_options(value, project_dir)
            return project_file_select(
                input_id,
                label,
                exts,
                proj=proj,
                user=usr,
                config=config,
                selected=selected or None,
                extra=extra or None,
            )

        forcing_abs, forcing_extra = _manifest_picker_options(forcing.get("dir"), project_dir)
        return ui.div(
            ui.input_text("mf_title", "Title", value=str(doc.get("title") or "")),
            ui.layout_columns(
                _picker("mf_grd", "Mesh (.grd)", [".grd"], grid.get("grd")),
                _picker("mf_bas", "Basin (.bas, optional)", [".bas"], grid.get("bas")),
                _picker("mf_boxes_txt", "Box index (optional)", [".txt"], grid.get("boxes_txt")),
                col_widths=(4, 4, 4),
            ),
            ui.layout_columns(
                _picker(
                    "mf_polygons",
                    "Box outlines (optional)",
                    [".gpkg", ".geojson", ".json", ".shp"],
                    boxes.get("polygons"),
                ),
                ui.input_text(
                    "mf_layer", "Outline layer (optional)", value=str(boxes.get("layer") or "")
                ),
                ui.input_text(
                    "mf_id_field", "Box id field", value=str(boxes.get("id_field") or "box")
                ),
                col_widths=(4, 4, 4),
            ),
            ui.layout_columns(
                _picker("mf_str", "STR (optional)", [".str"], doc.get("str")),
                project_dir_select(
                    "mf_forcing_dir",
                    "Forcing directory (optional)",
                    proj=proj,
                    user=usr,
                    config=config,
                    selected=forcing_abs or None,
                    extra=forcing_extra or None,
                    default_label="(none)",
                ),
                col_widths=(6, 6),
            ),
            ui.layout_columns(
                _picker("mf_observations", "Observations (optional)", [".csv"], obs.get("file")),
                _picker("mf_sites", "Sites (optional)", [".csv"], obs.get("sites")),
                col_widths=(6, 6),
            ),
        )

    @render.ui
    def manifest_runs():
        if _project() is None:
            return None
        rows = []
        for row in runs_rows.get():
            rows.append(
                ui.div(
                    ui.layout_columns(
                        ui.input_text(f"run_{row['key']}_id", "Run id", value=row["id"]),
                        ui.input_text(f"run_{row['key']}_label", "Label", value=row["label"]),
                        ui.input_select(
                            f"run_{row['key']}_dir",
                            "Directory",
                            choices=_run_dir_choices(row["dir"]),
                            selected=row["dir"] or None,
                        ),
                        ui.input_action_button(
                            f"run_{row['key']}_remove",
                            "Remove",
                            class_="btn-outline-danger btn-sm mt-4",
                        ),
                        col_widths=(3, 3, 4, 2),
                    ),
                    class_="border rounded p-2 mb-2",
                )
            )
        return ui.div(
            ui.tags.strong("Runs"),
            ui.p(
                "At least one. A run directory is usually outside the project, under a "
                "directory an administrator has opened for reading.",
                class_="text-muted small",
            ),
            ui.div(*rows) if rows else ui.p("No runs yet.", class_="text-muted small"),
            ui.input_action_button("mf_add_run", "Add run", class_="btn-outline-primary btn-sm"),
            ui.hr(),
            ui.input_action_button("mf_save", "Save manifest", class_="btn-primary"),
        )

    @reactive.effect
    @reactive.event(input.mf_add_run)
    def _add_run_row():
        rows = _harvest_rows()
        counters["run_key"] += 1
        rows.append({"key": counters["run_key"], "id": "", "label": "", "dir": "", "raw": {}})
        runs_rows.set(rows)  # a NEW list: Value.set dedups by identity

    @reactive.effect
    def _remove_run_row():
        """One watcher for every row's Remove button.

        The ledger is keyed by button id and the row keys are monotonic, so a
        key is never reused and a click is never mistaken for an older one.
        """
        rows = _harvest_rows()
        for row in rows:
            button = f"run_{row['key']}_remove"
            if button in input and input[button]() and not last["removed"].get(button):
                last["removed"][button] = True
                runs_rows.set([r for r in rows if r["key"] != row["key"]])
                return

    def _collect_runs() -> list[dict]:
        """The runs table as the user has it, carrying each entry's other keys."""
        project_dir = Path(_project()["work_dir"])
        out = []
        for row in _harvest_rows():
            entry = dict(row.get("raw") or {})
            entry["id"] = row["id"]
            entry["label"] = row["label"]
            entry["dir"] = _manifest_path_value(row["dir"], project_dir)
            out.append(entry)
        return out

    @reactive.effect
    @reactive.event(input.mf_save)
    def _save_manifest():
        proj = _project()
        usr = _user()
        if proj is None:
            ui.notification_show("Open a project first.", type="warning", duration=5)
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        project_dir = Path(proj["work_dir"])
        values = {
            "title": input.mf_title() if "mf_title" in input else "",
            "layer": input.mf_layer() if "mf_layer" in input else "",
            "id_field": input.mf_id_field() if "mf_id_field" in input else "",
        }
        for field, input_id in (
            ("grd", "mf_grd"),
            ("bas", "mf_bas"),
            ("boxes_txt", "mf_boxes_txt"),
            ("polygons", "mf_polygons"),
            ("str", "mf_str"),
            ("forcing_dir", "mf_forcing_dir"),
            ("observations", "mf_observations"),
            ("sites", "mf_sites"),
        ):
            picked = input[input_id]() if input_id in input else ""
            values[field] = _manifest_path_value(picked, project_dir)
        doc = _manifest_document(raw_manifest(), values, _collect_runs())
        try:
            write_manifest(project_dir, doc, config, usr)
        except (ManifestError, OSError) as exc:
            ui.notification_show(_err(exc), type="error", duration=10)
            return
        ui.notification_show("Manifest saved.", type="message", duration=4)
        counters["manifest"] += 1
        manifest_generation.set(counters["manifest"])

    # --- map --------------------------------------------------------------

    hourly_store: reactive.Value = reactive.value(None)

    def _hourly_request():
        """``(key, cache_dir)`` of the window the page shows now; ``cache_dir``
        is None when the daily frames are used (no run, no hourly cache, or a
        window wider than ``HOURLY_WINDOW_DAYS``)."""
        cached_run = cached()
        period = _period()
        proj = _project()
        run = _run_entry()
        if cached_run is None or period is None or proj is None or run is None:
            return None, None
        key = (proj["id"], run.id, cached_run.fingerprint, tuple(period))
        if not _hourly_usable(cached_run.meta, period):
            return key, None
        return key, cache_dir_for(Path(proj["work_dir"]), run.id)

    @reactive.effect(priority=LOADER_PRIORITY)
    async def _load_hourly_window():
        """Read the visible window's raw records off the loop (B-06).

        Reading happens here, once per (run, build, period), so a slider tick
        is a lookup rather than a disk read -- and only the window is read,
        never the whole frame (see ``read_hourly_window``). Writes
        ``hourly_store`` and never reads it.
        """
        key, cache_dir = _hourly_request()
        if cache_dir is None:
            hourly_store.set((key, (None, None)))
            return
        try:
            result = await asyncio.to_thread(_read_hourly_window_checked, cache_dir, key[2], key[3])
        except Exception as exc:  # noqa: BLE001 - an escaping exception ends the session
            # A cache that HAS the file and cannot be read is a broken cache,
            # not a daily one: falling back silently would leave the user with
            # a "Day" slider they did not ask for and no idea why.
            logger.warning("boxmodel: hourly window unreadable: %s", exc)
            result = (None, f"Output-step detail: {_err(exc)}")
        hourly_store.set((key, result))

    @reactive.calc
    def hourly_window_result() -> tuple:
        """The raw output-step records for the visible window, or None.

        None means "use the daily frames", which is the ordinary case: the run
        may have no hourly cache, or the window may be wider than
        ``HOURLY_WINDOW_DAYS``. Read by ``_load_hourly_window`` off the loop
        and checked there against the build the page holds; a window still
        being read shows as daily, never as another window's records.
        """
        stored = hourly_store.get()
        if stored is None:
            return None, None
        key, result = stored
        return result if key == _hourly_request()[0] else (None, None)

    def hourly_window():
        """The raw records for the visible window, or None for the daily path."""
        return hourly_window_result()[0]

    @render.ui
    def day_slider():
        cached_run = cached()
        period = _period()
        if cached_run is None or period is None or input.map_mode() != "day":
            return None
        frame = hourly_window()
        if frame is not None:
            low = frame["stamp"].min().to_pydatetime()
            high = frame["stamp"].max().to_pydatetime()
            return ui.input_slider(
                "day",
                "Time (model output step)",
                min=low,
                max=high,
                value=low,
                step=_hourly_step(cached_run.meta),
                width="100%",
            )
        return ui.input_slider(
            "day",
            "Day",
            min=period[0],
            max=period[1],
            value=period[0],
            step=timedelta(days=1),
            width="100%",
        )

    @reactive.calc
    def box_values() -> tuple:
        cached_run = cached()
        period = _period()
        column = input.variable()
        if cached_run is None or period is None or column not in VARIABLES:
            return None, ""
        state_daily = cached_run.state_daily
        mode = input.map_mode()
        if mode == "day":
            frame = hourly_window()
            if frame is not None:
                chosen = input.day() if "day" in input else frame["stamp"].min()
                return _hourly_box_values(frame, chosen, column)
            # A day slider and a time slider share one input id, so the value
            # can be a datetime here right after the window widens. Normalise
            # before comparing, or date-vs-datetime raises.
            day = pd.Timestamp(input.day()) if "day" in input else pd.Timestamp(period[0])
            day = min(max(day, pd.Timestamp(period[0])), pd.Timestamp(period[1])).normalize()
            selection = state_daily[state_daily["date"] == day]
            values = dict(
                zip(selection["box"].astype(int), selection[column].astype(float), strict=True)
            )
            return values, f"{VARIABLES[column]} on {day.date()}"
        window = state_daily[
            (state_daily["date"] >= pd.Timestamp(period[0]))
            & (state_daily["date"] <= pd.Timestamp(period[1]))
        ]
        if mode == "mean":
            grouped = window.groupby("box")[column].mean()
            return {int(k): float(v) for k, v in grouped.items()}, f"mean {VARIABLES[column]}"
        obs, sites = observations()
        if obs is None or sites is None:
            return {}, "bias (no observations)"
        try:
            table = compute_skill_table({cached_run.run_id: cached_run}, obs, sites, *period)
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: skill table failed: %s", exc)
            return {}, "bias (unavailable)"
        variable = COLUMN_TO_VARIABLE[column]
        table = table[table["variable"] == variable]
        values = {int(b): float(v) for b, v in zip(table["box"], table["bias"], strict=True)}
        label = f"bias of {VARIABLES[column]}"
        if variable == "level":
            label += " (anomaly: ~0 by construction)"
        return values, label

    @reactive.calc
    def posts() -> list[dict]:
        _obs, sites = observations()
        values, _label = box_values()
        if sites is None:
            return []
        out = []
        for _, site in sites.iterrows():
            if not (pd.notna(site["lat"]) and pd.notna(site["lon"])):
                continue
            box = site["box"]
            value = values.get(int(box)) if (values and pd.notna(box)) else None
            out.append(
                {
                    # Passed through raw on purpose. This ends up in a
                    # deck.gl tooltip rendered as innerHTML, and sites.csv is
                    # user-supplied -- but the escaping belongs to the code
                    # that builds the HTML (``build_box_layers``), which does
                    # escape it. Escaping here too would double-escape, so a
                    # site legitimately named "Smith & Co" would render as
                    # "Smith &amp; Co".
                    "site": str(site["site"]),
                    "lon": float(site["lon"]),
                    "lat": float(site["lat"]),
                    "value": value,
                }
            )
        return out

    @reactive.effect
    def _layers():
        """Rebuild the box layers. Writes ``extra_layers``/``legend_bins`` and
        reads neither, so pushing new layers can never re-trigger this effect
        (``grid_map_server`` only reads them).

        The upstream calls are inside the ``try`` as well: an exception
        escaping a ``reactive.effect`` ends the session, so any failure here
        has to degrade to empty layers plus a log line.
        """
        if _header_read_pending():
            return  # the read landing re-runs this
        try:
            polys = polygons()
            values, label = box_values()
            layers, bins = build_box_layers(
                polys,
                values if polys else None,
                label=label,
                posts=posts(),
                selected=selected_box.get(),
            )
        except Exception as exc:  # noqa: BLE001 - a layer failure must not kill the session
            logger.warning("boxmodel: box layers could not be built: %s", exc, exc_info=True)
            layers, bins = [], []
        extra_layers.set(layers)
        legend_bins.set(bins)

    @render.ui
    def map_legend():
        bins = legend_bins.get()
        if not bins:
            return None
        rows = [
            ui.tags.div(
                ui.tags.span(
                    style=(
                        "display:inline-block;width:14px;height:14px;"
                        f"background:rgb({r},{g},{b});margin-right:6px"
                    )
                ),
                ui.tags.span(f"{low:.3g} – {high:.3g}"),
            )
            for (low, high, (r, g, b)) in bins
        ]
        return ui.tags.div(ui.tags.strong("Legend"), *rows, class_="small")

    def _on_box(box: int) -> None:
        """Box click from the map.

        ``update_select`` is given this page's ``session`` explicitly: this
        callback runs inside the grid map module's own session scope, so the
        default would resolve the id against ``boxmodel-boxmap-`` instead of
        ``boxmodel-``.
        """
        if selected_box.get() != box:
            selected_box.set(box)
        ui.update_select("box", selected=str(box), session=session)

    grid_map_server("boxmap", grd_file, extra_layers=extra_layers, on_box_click=_on_box)

    # --- time series ------------------------------------------------------

    @reactive.calc
    def series():
        cached_run = cached()
        period = _period()
        column = input.variable()
        selected = input.box()
        if cached_run is None or period is None or not selected or column not in VARIABLES:
            return None
        try:
            box = int(selected)
        except (TypeError, ValueError):
            return None
        state_daily = cached_run.state_daily
        frame = hourly_window()
        if frame is not None:
            # The raw records ARE the detail, so there is no daily min/max band
            # to draw around them -- the band exists only to show what a daily
            # mean hides.
            model = _hourly_series(frame, box, column)
            low = high = None
        else:
            model = model_series(cached_run, box, column, *period)
            low = (
                model_series(cached_run, box, f"{column}_min", *period)
                if f"{column}_min" in state_daily
                else None
            )
            high = (
                model_series(cached_run, box, f"{column}_max", *period)
                if f"{column}_max" in state_daily
                else None
            )
        obs, sites = observations()
        observed = None
        if obs is not None and sites is not None:
            mapped = sites.dropna(subset=["box"])
            names = mapped[mapped["box"].astype("int64") == box]["site"].tolist()
            rows = obs[obs["site"].isin(names) & (obs["variable"] == COLUMN_TO_VARIABLE[column])]
            rows = rows[
                (rows["date"] >= pd.Timestamp(period[0]))
                & (rows["date"] <= pd.Timestamp(period[1]))
            ]
            if len(rows):
                observed = pd.Series(
                    rows["value"].to_numpy(), index=pd.Index(rows["date"])
                ).sort_index()
        return {
            "box": box,
            # The VALIDATED variable key (column in VARIABLES), which is what
            # the download name is built from -- never the raw input.
            "variable": column,
            "model": model,
            "low": low,
            "high": high,
            "obs": observed,
            "label": VARIABLES[column],
        }

    @render_widget
    def ts_plot():
        figure = go.Figure()
        data = series()
        if data is None:
            figure.add_annotation(
                text="Select a run with a ready cache",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            figure.update_layout(height=420)
            return figure
        if data["low"] is not None and data["high"] is not None:
            figure.add_trace(
                go.Scatter(
                    x=data["high"].index,
                    y=data["high"].values,
                    line={"width": 0},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            figure.add_trace(
                go.Scatter(
                    x=data["low"].index,
                    y=data["low"].values,
                    fill="tonexty",
                    line={"width": 0},
                    name="daily min–max",
                    opacity=0.3,
                )
            )
        figure.add_trace(
            go.Scatter(
                x=data["model"].index,
                y=data["model"].values,
                name=f"model box {data['box']}",
                mode="lines",
            )
        )
        if data["obs"] is not None:
            figure.add_trace(
                go.Scatter(
                    x=data["obs"].index,
                    y=data["obs"].values,
                    name="observed",
                    mode="markers",
                    marker={"size": 5},
                )
            )
        figure.update_layout(
            height=420,
            yaxis_title=data["label"],
            margin={"l": 40, "r": 20, "t": 30, "b": 40},
        )
        return figure

    @render.ui
    def skill_table():
        cached_run = cached()
        period = _period()
        obs, sites = observations()
        if cached_run is None or period is None or obs is None or sites is None:
            return ui.tags.p("No observations configured for this project.", class_="text-muted")
        try:
            table = compute_skill_table({cached_run.run_id: cached_run}, obs, sites, *period)
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: skill table failed: %s", exc)
            return ui.tags.p(f"Skill table: {_err(exc)}", class_="text-muted")
        if table.empty:
            return ui.tags.p(
                "No target has 30 or more common days in this period.", class_="text-muted"
            )
        head = ui.tags.tr(
            *[
                ui.tags.th(c)
                for c in (
                    "site",
                    "variable",
                    "box",
                    "n",
                    "bias",
                    "RMSE",
                    "r",
                    "R²",
                    "sd_mod/sd_obs",
                )
            ]
        )
        body = [
            ui.tags.tr(
                ui.tags.td(str(row.site)),
                ui.tags.td(str(row.variable)),
                ui.tags.td(str(row.box)),
                ui.tags.td(str(row.n)),
                ui.tags.td(_bias_cell(row.variable, row.bias)),
                ui.tags.td(_fmt(row.rmse)),
                ui.tags.td(_fmt(row.r, 2)),
                ui.tags.td(_fmt(row.r2, 2)),
                ui.tags.td(_fmt(row.sd_ratio, 2)),
            )
            for row in table.itertuples()
        ]
        return ui.tags.div(
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "Judge amplitude by sd_mod/sd_obs (1.00 is right) and phase by r; R² is shown "
                "but is not the headline. Level skill is computed on anomalies, so a level "
                "row has no meaningful bias (—).",
                class_="text-muted small",
            ),
        )

    run_states_store: reactive.Value = reactive.value(None)

    def _run_states_key() -> tuple:
        manifest_obj = manifest()
        proj = _project()
        return (
            proj["id"] if proj is not None else None,
            tuple(r.id for r in manifest_obj.runs) if manifest_obj is not None else (),
            cache_generation.get(),
        )

    @reactive.effect(priority=LOADER_PRIORITY)
    async def _load_run_states():
        """Read every ready run's ``state_daily`` off the loop (B-06).

        Depends on ``cache_generation`` (so a finished rebuild refreshes it)
        but reads only ``state_daily``, so loading every run stays cheap.
        Writes ``run_states_store`` and never reads it.
        """
        key = _run_states_key()
        manifest_obj = manifest()
        proj = _project()
        if manifest_obj is None or proj is None:
            run_states_store.set((key, ({}, [])))
            return
        usr = _user()

        def err(exc: BaseException) -> str:
            # Runs in the reader's thread: plain arguments, no reactive reads.
            return _safe_error(exc, config, usr)

        try:
            result = await asyncio.to_thread(
                _read_run_states,
                Path(proj["work_dir"]),
                list(manifest_obj.runs),
                get_registry(),
                _tmp_age_cap(),
                err,
            )
        except Exception as exc:  # noqa: BLE001 - an escaping exception ends the session
            logger.warning("boxmodel: run states could not be read: %s", exc)
            result = ({}, [f"Compare: {_err(exc)}"])
        run_states_store.set((key, result))

    @reactive.calc
    def all_run_states_result() -> tuple[dict, list[str]]:
        """``({run_id: CachedRun}, [messages])`` for every manifest run whose
        cache is ready/stale -- the multi-run skill comparison input, plus one
        message per run that could not be read (see ``_load_compare_state``).

        Read by ``_load_run_states`` off the loop; while a newer request is
        being read the project's previous result is kept (each run in it is
        still one consistent build).
        """
        stored = run_states_store.get()
        if stored is None:
            return {}, []
        key, result = stored
        return result if key[0] == _run_states_key()[0] else ({}, [])

    def all_run_states() -> dict:
        """``{run_id: CachedRun}`` for the runs that could be read."""
        return all_run_states_result()[0]

    def run_state_problems() -> list[str]:
        """One message per manifest run whose cache could not be read."""
        return all_run_states_result()[1]

    # --- Compare (spec §8) -------------------------------------------------
    #
    # Everything here hangs off all_run_states() (cache_generation) and the
    # header/compare inputs -- never off status()/status_tick. One day set,
    # cmp_days(), is shared by the map, the overlay and the tables.

    def _run_labels() -> dict:
        manifest_obj = manifest()
        return {r.id: r.label for r in manifest_obj.runs} if manifest_obj is not None else {}

    def _cmp_choices(states: dict, current) -> dict:
        """Selectize choices: ready runs in manifest order -- except that the
        CURRENT selection comes first, in its own order. ``selected=`` marks
        ``<option selected>`` in choices order and selectize initialises its
        items in DOM order, so after a re-render (a build finishing) A would
        otherwise silently become whichever chosen run the manifest lists
        first, flipping the sign of B - A."""
        labels = _run_labels()
        ordered = [r for r in current if r in states]
        ordered += [r for r in labels if r in states and r not in ordered]
        ordered += [r for r in states if r not in ordered]
        return {r: _text(labels.get(r, r)) for r in ordered}

    @render.ui
    def cmp_controls():
        """The run multi-select. Rendered (not ``update_selectize``d from an
        effect) so the ready-run set is the only thing that re-renders it;
        the user's current choice is read under ``reactive.isolate()`` and
        re-applied when still valid -- reading it reactively would re-render
        the selectize on every pick (the self-write loop) and lose the
        dropdown mid-selection. The B select is a nested output because ITS
        choices do depend on ``input.cmp_runs()``.
        """
        if manifest() is None:
            return ui.tags.p(CMP_NO_PROJECT_MESSAGE, class_="text-muted")
        states = all_run_states()
        if len(states) < 2:
            return ui.tags.p(CMP_NEED_TWO_MESSAGE, class_="text-muted")
        with reactive.isolate():
            current = tuple(input.cmp_runs() or ()) if "cmp_runs" in input else ()
        choices = _cmp_choices(states, current)
        selected = [r for r in current if r in choices][:4] or list(choices)[:2]
        return ui.layout_columns(
            ui.input_selectize(
                "cmp_runs",
                "Runs (2\u20134, A = first)",
                choices=choices,
                selected=selected,
                multiple=True,
                options={"maxItems": 4},
            ),
            ui.output_ui("cmp_b_control"),
            ui.output_ui("cmp_message"),
            col_widths=(5, 3, 4),
        )

    @render.ui
    def cmp_b_control():
        """B over the chosen runs minus A. Depends reactively on
        ``input.cmp_runs()`` (so it follows the selection) and reads its own
        current value under ``reactive.isolate()`` so re-rendering it can
        never re-trigger itself."""
        states = all_run_states()
        chosen = tuple(input.cmp_runs() or ()) if "cmp_runs" in input else ()
        with reactive.isolate():
            current_b = input.cmp_b() if "cmp_b" in input else None
        validated = _validate_compare_runs(chosen, current_b, states)
        if validated is None:
            return None
        ids, b = validated
        labels = _run_labels()
        choices = {r: _text(labels.get(r, r)) for r in ids[1:]}
        return ui.input_select(
            "cmp_b", "B (difference map shows B \u2212 A)", choices=choices, selected=b
        )

    @reactive.calc
    def cmp_runs_selected() -> tuple[dict, str] | None:
        """``({run_id: CachedRun} in A-first order, b_id)`` for a valid
        selection of 2..4 ready runs, else ``None``."""
        states = all_run_states()
        chosen = tuple(input.cmp_runs() or ()) if "cmp_runs" in input else ()
        b = input.cmp_b() if "cmp_b" in input else None
        validated = _validate_compare_runs(chosen, b, states)
        if validated is None:
            return None
        ids, b = validated
        return {run_id: states[run_id] for run_id in ids}, b

    @reactive.calc
    def cmp_days_result() -> tuple:
        """``(day set, page message)`` -- see ``_compare_day_set``, which reads
        the off-disk ``state_daily`` frames inside a try so a broken cache
        becomes the tab's message instead of an exception out of this calc."""
        picked = cmp_runs_selected()
        if picked is None:
            return _empty_day_set(), None
        selected, _b = picked
        return _compare_day_set(selected, input.period(), _err)

    def cmp_days() -> pd.DatetimeIndex:
        """THE shared day set: intersection of the selected runs' days within
        the header period (clamped to the runs' span, see _compare_bounds)."""
        return cmp_days_result()[0]

    def _cmp_message() -> str | None:
        """The state message for the whole tab, or ``None`` when there is
        something to show."""
        if manifest() is None:
            return CMP_NO_PROJECT_MESSAGE
        if len(all_run_states()) < 2:
            # A run whose cache could not be read is missing from the runs the
            # comparison can offer, so "pick two" would blame the user for it.
            problems = run_state_problems()
            if problems:
                return "Compare: " + "; ".join(problems)
            return CMP_NEED_TWO_MESSAGE
        if cmp_runs_selected() is None:
            return CMP_SELECT_RUNS_MESSAGE
        days, days_error = cmp_days_result()
        if days_error:
            # A cache the day set could not be read out of: say what went
            # wrong rather than blaming the period for having no common days.
            return days_error
        if len(days) == 0:
            return CMP_NO_COMMON_DAYS_MESSAGE
        return None

    @render.ui
    def cmp_message():
        message = _cmp_message()
        return ui.tags.p(message, class_="text-muted") if message else None

    @reactive.calc
    def cmp_diff() -> tuple:
        """``(values, label)`` for the difference map: B - A of the period
        mean of the header variable per box, over exactly ``cmp_days()``."""
        picked = cmp_runs_selected()
        column = input.variable()
        if picked is None or column not in VARIABLES:
            return None, ""
        selected, b = picked
        days = cmp_days()
        ids = list(selected)
        if len(days) == 0:
            return None, ""
        values = period_mean_diff(selected[ids[0]], selected[b], column, days)
        labels = _run_labels()
        # Run labels come from the manifest: path-looking tokens are rewritten
        # here (_text); HTML escaping happens at the tooltip sink.
        label_b, label_a = _text(labels.get(b, b)), _text(labels.get(ids[0], ids[0]))
        return values, f"\u0394 {VARIABLES[column]}: {label_b} \u2212 {label_a}"

    @reactive.effect
    def _cmp_layers():
        """Rebuild the Compare map layers. Writes ``cmp_layers`` and
        ``cmp_legend_bins`` and reads neither; every upstream call is inside
        the ``try`` (an exception escaping an effect ends the session)."""
        try:
            polys = polygons()
            values, label = cmp_diff()
            layers, bins = build_box_layers(
                polys,
                values if polys else None,
                label=label,
                posts=None,
                selected=selected_box.get(),
                palette="diverging",
                symmetric=True,
            )
        except Exception as exc:  # noqa: BLE001 - a layer failure must not kill the session
            logger.warning("boxmodel: compare layers could not be built: %s", exc, exc_info=True)
            layers, bins = [], []
        cmp_layers.set(layers)
        cmp_legend_bins.set(bins)

    @render.ui
    def cmp_legend():
        """Diverging legend beside the difference map -- or, when there are no
        layers, the tab's state message, so the map is never a bare mesh with
        nothing said."""
        bins = cmp_legend_bins.get()
        if not bins:
            message = _cmp_message()
            if message is None and not polygons():
                # Runs and days are fine but there is nothing to colour: say
                # why here too (the page-top alert already carries the detail).
                message = polygons_result()[1] or NO_POLYGONS_MESSAGE
            return ui.tags.p(message, class_="text-muted") if message else None
        rows = [
            ui.tags.div(
                ui.tags.span(
                    style=(
                        "display:inline-block;width:14px;height:14px;"
                        f"background:rgb({r},{g},{b});margin-right:6px"
                    )
                ),
                ui.tags.span(f"{low:+.3g} \u2013 {high:+.3g}"),
            )
            for (low, high, (r, g, b)) in bins
        ]
        return ui.tags.div(ui.tags.strong("B \u2212 A"), *rows, class_="small")

    grid_map_server("cmpmap", grd_file, extra_layers=cmp_layers, on_box_click=_on_box)

    def _cmp_box(selected: dict) -> int | None:
        """The box the overlay shows: the Time-series tab's box select (shared
        with the maps through _on_box), else the last map click, else A's
        first box. The header select belongs to the header run, which need
        not be one of the compared runs, so a box A does not have falls
        through to the next candidate."""
        first = next(iter(selected.values()))
        known = {int(b) for b in first.state_daily["box"].unique()}
        if not known:
            return None
        raw = input.box() if "box" in input else None
        for candidate in (raw, selected_box.get()):
            try:
                box = int(candidate)
            except (TypeError, ValueError):
                continue
            if box in known:
                return box
        return min(known)

    @reactive.calc
    def cmp_overlay() -> dict | None:
        """Series for the overlay plot: one per run plus the mapped post's
        observations of the same box, all restricted to ``cmp_days()``."""
        picked = cmp_runs_selected()
        column = input.variable()
        if picked is None or column not in VARIABLES:
            return None
        selected, _b = picked
        days = cmp_days()
        if len(days) == 0:
            return None
        box = _cmp_box(selected)
        if box is None:
            return None
        lines = overlay_series(selected, box, column, days)
        obs, sites = observations()
        observed = None
        if obs is not None and sites is not None:
            mapped = sites.dropna(subset=["box"])
            names = mapped[mapped["box"].astype("int64") == box]["site"].tolist()
            rows = obs[obs["site"].isin(names) & (obs["variable"] == COLUMN_TO_VARIABLE[column])]
            rows = rows[rows["date"].isin(days)]
            if len(rows):
                observed = pd.Series(
                    rows["value"].to_numpy(), index=pd.Index(rows["date"])
                ).sort_index()
        return {"box": box, "lines": lines, "obs": observed, "label": VARIABLES[column]}

    @render_widget
    def cmp_plot():
        figure = go.Figure()
        data = cmp_overlay()
        if data is None or not any(line.notna().any() for line in data["lines"].values()):
            figure.add_annotation(
                text=_cmp_message() or "Nothing to overlay for this box and period",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            figure.update_layout(height=360)
            return figure
        labels = _run_labels()
        for run_id, line in data["lines"].items():
            figure.add_trace(
                go.Scatter(
                    x=line.index,
                    y=line.values,
                    name=_text(labels.get(run_id, run_id)),
                    mode="lines",
                )
            )
        if data["obs"] is not None:
            figure.add_trace(
                go.Scatter(
                    x=data["obs"].index,
                    y=data["obs"].values,
                    name="observed",
                    mode="markers",
                    marker={"size": 5},
                )
            )
        figure.update_layout(
            height=360,
            yaxis_title=data["label"],
            title={"text": f"box {data['box']}", "font": {"size": 13}},
            margin={"l": 40, "r": 20, "t": 30, "b": 40},
        )
        return figure

    @reactive.calc
    def cmp_skill_frames() -> tuple:
        """``(side_by_side_df, per_year_df, error)`` over ``cmp_days()``; both
        frames ``None`` (with a message) when there is nothing to compute.
        ``skill_table`` intersects days itself; it is handed the bounds of the
        shared day set so it lands on the same days as the map and overlay."""
        obs, sites = observations()
        picked = cmp_runs_selected()
        if obs is None or sites is None or picked is None:
            return None, None, None
        selected, _b = picked
        days = cmp_days()
        if len(days) == 0:
            return None, None, None
        start, end = days.min(), days.max()
        try:
            skill = compute_skill_table(selected, obs, sites, start=start, end=end)
            wide = side_by_side(skill, list(selected), _run_labels())
            yearly = per_year_table(selected, obs, sites, start, end)
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: compare skill failed: %s", exc)
            return None, None, f"Compare: {_err(exc)}"
        return wide, yearly, None

    def _cmp_table_gate():
        """The message that pre-empts both tables, or ``None``."""
        if manifest() is None:
            return CMP_NO_PROJECT_MESSAGE
        obs, sites = observations()
        if obs is None or sites is None:
            return CMP_NO_OBSERVATIONS_MESSAGE
        return _cmp_message()

    @render.ui
    def cmp_skill():
        """Skill side by side: one column per run (A first), one row per
        (site, variable, metric), over the shared days."""
        gate = _cmp_table_gate()
        if gate:
            return ui.tags.p(gate, class_="text-muted")
        wide, _yearly, error = cmp_skill_frames()
        if error:
            return ui.tags.p(error, class_="text-muted")
        if wide is None or wide.empty:
            return ui.tags.p(CMP_SKILL_EMPTY_MESSAGE, class_="text-muted")
        head = ui.tags.tr(
            ui.tags.th("site"),
            ui.tags.th("variable"),
            ui.tags.th("metric"),
            *[ui.tags.th(_text(str(column))) for column in wide.columns],
        )

        def _cell(variable, metric, value):
            if metric == "n":
                return _int_cell(value)
            if metric == "bias":
                return _bias_cell(variable, value)
            return _fmt(value, 3 if metric == "rmse" else 2)

        body = [
            ui.tags.tr(
                ui.tags.td(str(site)),
                ui.tags.td(str(variable)),
                ui.tags.td(METRIC_LABELS.get(metric, metric)),
                *[ui.tags.td(_cell(variable, metric, value)) for value in row],
            )
            for (site, variable, metric), row in zip(
                wide.index, wide.to_numpy().tolist(), strict=True
            )
        ]
        return ui.tags.div(
            ui.tags.strong("Skill side by side"),
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "All runs are compared on the days they all produced within the period. "
                "Aim for lower RMSE, sd_mod/sd_obs near 1.00, and higher r; R\u00b2 is shown "
                "but is not the headline. Level skill is computed on anomalies, so a level "
                "row has no meaningful bias (\u2014).",
                class_="text-muted small",
            ),
            class_="mt-3",
        )

    @render.ui
    def cmp_per_year():
        gate = _cmp_table_gate()
        if gate:
            return None  # cmp_skill already says it
        _wide, yearly, error = cmp_skill_frames()
        if error:
            return None
        if yearly is None or yearly.empty:
            return ui.tags.p(CMP_PER_YEAR_EMPTY_MESSAGE, class_="text-muted")
        labels = _run_labels()
        yearly = yearly.sort_values(["year", "site", "variable", "run"])
        head = ui.tags.tr(
            *[
                ui.tags.th(c)
                for c in (
                    "year",
                    "run",
                    "site",
                    "variable",
                    "n",
                    "bias",
                    "RMSE",
                    "r",
                    "R\u00b2",
                    "sd",
                )
            ]
        )
        body = [
            ui.tags.tr(
                ui.tags.td(str(row.year)),
                ui.tags.td(_text(labels.get(row.run, row.run))),
                ui.tags.td(str(row.site)),
                ui.tags.td(str(row.variable)),
                ui.tags.td(str(row.n)),
                ui.tags.td(_bias_cell(row.variable, row.bias)),
                ui.tags.td(_fmt(row.rmse)),
                ui.tags.td(_fmt(row.r, 2)),
                ui.tags.td(_fmt(row.r2, 2)),
                ui.tags.td(_fmt(row.sd_ratio, 2)),
            )
            for row in yearly.itertuples()
        ]
        return ui.tags.div(
            ui.tags.strong("Per-year skill"),
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "One row per calendar year with at least 60 matched days; sd is sd_mod/sd_obs.",
                class_="text-muted small",
            ),
            class_="mt-3",
        )

    def _cmp_download_name() -> str:
        picked = cmp_runs_selected()
        column = input.variable()
        if picked is None or column not in VARIABLES:
            return _compare_filename(None, None, None)
        selected, b = picked
        return _compare_filename(column, next(iter(selected)), b)

    @_render_download(filename=_cmp_download_name)
    def cmp_download():
        wide, yearly, _error = cmp_skill_frames()
        buffer = io.StringIO()
        if wide is not None:
            wide.to_csv(buffer)
        buffer.write("\n")
        if yearly is not None:
            yearly.to_csv(buffer, index=False)
        yield buffer.getvalue()

    # --- Setup (spec §8, PR 3) ---------------------------------------------
    #
    # Read-only. The STR and the forcing files are read in reactive.calcs off
    # manifest() (never per render); interfaces and meteo come from cached()
    # (cache_generation). Nothing here reads status()/status_tick.

    @reactive.calc
    def str_setup_result() -> tuple:
        """``(StrSetup | None, message | None)`` for the manifest's STR."""
        manifest_obj = manifest()
        if manifest_obj is None:
            return None, SETUP_NO_PROJECT_MESSAGE
        path = manifest_obj.str_path
        if path is None:
            return None, SETUP_NO_STR_MESSAGE
        try:
            return read_str_tolerant(Path(path)), None
        except (StrSetupError, OSError, ValueError) as exc:
            logger.warning("boxmodel: STR could not be read: %s", exc)
            return None, f"STR: {_err(exc)}"

    @reactive.calc
    def boundaries_calc() -> tuple:
        """``(list[Boundary], message | None)`` -- ``boundaries`` raises for a
        ``zfact`` that is not a number."""
        setup, _error = str_setup_result()
        if setup is None:
            return [], None
        try:
            return boundaries(setup), None
        except StrSetupError as exc:
            logger.warning("boxmodel: STR boundaries unusable: %s", exc)
            return [], f"STR boundaries: {_err(exc)}"

    @reactive.calc
    def summary_calc() -> dict:
        setup, _error = str_setup_result()
        return str_summary(setup) if setup is not None else {}

    def _river_bounds():
        """The window the river series are restricted to: the STR's own
        ``itanf``/``itend`` when both are ISO dates, else the loaded cache's
        period, else ``None`` (the whole file)."""
        bounds = period_from_summary(summary_calc())
        if bounds is not None:
            return bounds
        cached_run = cached()
        return _cache_period(cached_run) if cached_run is not None else None

    @reactive.calc
    def rivers_result() -> dict:
        """``{boundary number: (series | None, note | None)}`` for every
        boundary that names a ``boundn``.

        The resolver runs for each of them (so the table can say "not read
        (.fem)" for a level boundary); the file is READ only for discharge
        boundaries (``ibtyp`` 2/3) whose ``boundn`` resolved to a path. The
        resolved path never leaves this calc.
        """
        manifest_obj = manifest()
        bounds, _error = boundaries_calc()
        if manifest_obj is None or not bounds:
            return {}
        usr = _user()
        window = _river_bounds()
        out: dict = {}
        for b in bounds:
            if not b.boundn:
                continue
            path, note = resolve_forcing_file(b.boundn, manifest_obj.forcing_dir, config, usr)
            if path is None:
                out[b.number] = (None, note)
                continue
            if kind(b) != "discharge":
                out[b.number] = (None, None)
                continue
            try:
                series_b = read_forcing_series(path)
            except (StrSetupError, OSError, ValueError) as exc:
                logger.warning("boxmodel: forcing file unreadable: %s", exc)
                out[b.number] = (None, _err(exc))
                continue
            out[b.number] = (_restrict_series(series_b, window), None)
        return out

    @reactive.calc
    def interfaces_calc() -> list[dict]:
        """Section interfaces from the cache ``meta.json`` (needs a ready cache)."""
        cached_run = cached()
        if cached_run is None:
            return []
        try:
            return _interfaces_on_map(section_interfaces(cached_run.meta), grd_file.get())
        except (TypeError, ValueError, KeyError, PolygonError) as exc:
            logger.warning("boxmodel: section interfaces unavailable: %s", exc)
            return []

    @reactive.calc
    def boundary_points_calc() -> tuple:
        """``(points, missing)``: one record per STR ``kbound`` node placed on
        the grid (``node_positions``, same frame as the polygons path) and the
        node ids the grid does not have. Title/boundn are passed RAW -- the
        tooltip HTML is escaped in ``build_setup_layers``, the sink."""
        grd = grd_file.get()
        bounds, _error = boundaries_calc()
        if grd is None or not bounds:
            return [], []
        try:
            positions = node_positions(grd)
        except Exception as exc:  # noqa: BLE001 - projection detection can fail on odd grids
            logger.warning("boxmodel: node positions unavailable: %s", exc)
            return [], []
        points: list[dict] = []
        missing: list[int] = []
        for b in bounds:
            b_kind = kind(b)
            for node in b.kbound:
                pos = positions.get(int(node))
                if pos is None:
                    missing.append(int(node))
                    continue
                points.append(
                    {
                        "node": int(node),
                        "lon": float(pos[0]),
                        "lat": float(pos[1]),
                        "boundary": b.number,
                        "title": b.title,
                        "kind": b_kind,
                        "boundn": b.boundn,
                    }
                )
        return points, missing

    @reactive.effect
    def _setup_layers():
        """Rebuild the Setup map layers: box outlines plus the interfaces and
        boundary nodes. Writes ``setup_layers`` only and reads nothing it
        writes; every upstream call is inside the ``try`` (an exception
        escaping an effect ends the session)."""
        if _header_read_pending():
            return  # the read landing re-runs this
        try:
            polys = polygons()
            layers, _bins = build_box_layers(polys, None) if polys else ([], [])
            points, _missing = boundary_points_calc()
            layers = list(layers) + build_setup_layers(
                interfaces_calc(),
                points,
                selected_boundary=setup_selected_boundary.get(),
            )
        except Exception as exc:  # noqa: BLE001 - a layer failure must not kill the session
            logger.warning("boxmodel: setup layers could not be built: %s", exc, exc_info=True)
            layers = []
        setup_layers.set(layers)

    grid_map_server("setupmap", grd_file, extra_layers=setup_layers, on_box_click=_on_box)

    @render.ui
    def setup_message():
        """Every Setup-level message in one place, all text via ui.tags."""
        _setup, error = str_setup_result()
        blocks = []
        if error:
            blocks.append(ui.tags.p(error, class_="text-muted"))
        _bounds, bounds_error = boundaries_calc()
        if bounds_error:
            blocks.append(ui.div(ui.tags.span(bounds_error), class_="alert alert-warning"))
        if error is None and cached() is None:
            blocks.append(ui.tags.p(SETUP_NEEDS_CACHE_MESSAGE, class_="text-muted"))
        _points, missing = boundary_points_calc()
        missing_message = _missing_nodes_message(missing)
        if missing_message:
            blocks.append(ui.div(ui.tags.span(missing_message), class_="alert alert-warning"))
        return ui.div(*blocks) if blocks else None

    @render.ui
    def setup_summary():
        """Two-column table of ``str_summary``; the orphan assignments as ONE
        muted row, comma-joined and untruncated. Values are STR text, so they
        go through ``_text`` (an absolute path in a foreign STR is rewritten)
        and ``ui.tags`` (escaped)."""
        setup, _error = str_setup_result()
        if setup is None:
            return None  # setup_message says why
        summary = summary_calc()
        if not summary:
            return ui.tags.p("The STR has no &para section to summarise.", class_="text-muted")
        rows = []
        for key, value in summary.items():
            if key == "orphans":
                continue
            rows.append(
                ui.tags.tr(
                    ui.tags.td(SETUP_SUMMARY_LABELS.get(key, key)),
                    ui.tags.td(_text(value)),
                )
            )
        if summary.get("orphans"):
            rows.append(
                ui.tags.tr(
                    ui.tags.td(SETUP_ORPHANS_LABEL),
                    ui.tags.td(_text(summary["orphans"])),
                    class_="text-muted",
                )
            )
        return ui.tags.div(
            ui.tags.strong("STR summary"),
            ui.tags.span(f" ({_text(setup.path_name)})", class_="text-muted small"),
            ui.tags.table(ui.tags.tbody(*rows), class_="table table-sm"),
        )

    def _register_setup_pick(number: int) -> None:
        """Register the "select" handler for one boundary row -- once per
        boundary per session (the dedup idiom of pages/admin.py and home.py),
        so a re-render of the table never stacks a second listener."""
        if number in _setup_pick_registered:
            return
        _setup_pick_registered.add(number)

        @reactive.effect
        @reactive.event(input[f"setup_pick_{number}"])
        def _pick():
            if setup_selected_boundary.get() != number:
                setup_selected_boundary.set(number)

    @render.ui
    def setup_boundaries():
        """The boundaries table: one ``tbody`` row per ``$bound<k>``; the file
        column shows ``boundn`` as written (sanitised) and the resolver's note,
        never a path. Does not read ``setup_selected_boundary``: the selection
        is shown on the map (node radius), so a click never re-renders the
        table."""
        setup, error = str_setup_result()
        if setup is None:
            return None  # setup_message says why
        bounds, _bounds_error = boundaries_calc()
        if not bounds:
            return ui.tags.p("The STR has no $bound sections.", class_="text-muted")
        rows = _boundary_rows(bounds, rivers_result())
        head = ui.tags.tr(
            *[
                ui.tags.th(c)
                for c in (
                    "",
                    "boundary",
                    "title",
                    "type",
                    "ibtyp",
                    "nodes",
                    "zfact",
                    "boundn (as written)",
                    "other files",
                )
            ]
        )
        body = []
        for row in rows:
            _register_setup_pick(row["number"])
            file_cell = [ui.tags.code(_text(row["boundn"]))] if row["boundn"] else []
            if row["note"]:
                file_cell.append(ui.tags.span(f" {_text(row['note'])}", class_="text-muted"))
            body.append(
                ui.tags.tr(
                    ui.tags.td(
                        ui.input_action_link(
                            f"setup_pick_{row['number']}", "select", class_="small"
                        )
                    ),
                    ui.tags.td(str(row["number"])),
                    ui.tags.td(_text(row["title"])),
                    ui.tags.td(row["kind"]),
                    ui.tags.td(row["ibtyp"]),
                    ui.tags.td(str(row["nodes"])),
                    ui.tags.td(row["zfact"]),
                    ui.tags.td(*file_cell),
                    ui.tags.td(_text(row["other_files"])),
                )
            )
        return ui.tags.div(
            ui.tags.strong("Open boundaries"),
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "Forcing files are looked up by basename under the project's forcing "
                "directory; only .txt time series are read (.fem files are named only). "
                "Select a boundary to enlarge its nodes on the map.",
                class_="text-muted small",
            ),
            class_="mt-3",
        )

    @render_widget
    def setup_rivers():
        """One trace per discharge boundary whose file was read; the raw file
        values, with ``zfact`` noted in the trace name when it is not 1."""
        figure = go.Figure()
        bounds, _error = boundaries_calc()
        rivers = rivers_result()
        by_number = {b.number: b for b in bounds}
        drawn = 0
        for number, (series_b, _note) in rivers.items():
            if series_b is None or not len(series_b):
                continue
            b = by_number.get(number)
            if b is None:
                continue
            name = _text(b.title) or f"boundary {number}"
            if b.zfact != 1:
                name += f" (\u00d7{b.zfact:g})"
            figure.add_trace(
                go.Scatter(x=series_b.index, y=series_b.values, name=name, mode="lines")
            )
            drawn += 1
        if not drawn:
            figure.add_annotation(
                text=SETUP_NO_RIVERS_MESSAGE,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            figure.update_layout(height=300)
            return figure
        figure.update_layout(
            height=320,
            yaxis_title="discharge (m\u00b3/s)",
            title={
                "text": "River discharge (file values; \u00d7zfact applied by SHYFEM)",
                "font": {"size": 13},
            },
            margin={"l": 40, "r": 20, "t": 30, "b": 40},
        )
        return figure

    @render.ui
    def setup_meteo_controls():
        """The meteo variable select, rendered (so the cache's column set is
        the only thing that re-renders it); its current value is read under
        ``reactive.isolate()`` and kept when still valid."""
        cached_run = cached()
        if cached_run is None:
            return ui.tags.p(SETUP_NO_METEO_MESSAGE, class_="text-muted")
        choices = _meteo_variables(cached_run.meteo_daily)
        if not choices:
            return ui.tags.p("This run has no meteo output (boxes_meteo.txt).", class_="text-muted")
        with reactive.isolate():
            current = input.setup_meteo_var() if "setup_meteo_var" in input else None
        selected = current if current in choices else next(iter(choices))
        return ui.input_select(
            "setup_meteo_var", "Meteo variable", choices=choices, selected=selected
        )

    @render_widget
    def setup_meteo():
        """Per-box daily meteo from the cache for the shared box select over
        the header period."""
        figure = go.Figure()

        def _empty(text: str, height: int = 300):
            figure.add_annotation(
                text=text, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False
            )
            figure.update_layout(height=height)
            return figure

        cached_run = cached()
        period = _period()
        if cached_run is None or period is None:
            return _empty(SETUP_NO_METEO_MESSAGE)
        variable = input.setup_meteo_var() if "setup_meteo_var" in input else None
        choices = _meteo_variables(cached_run.meteo_daily)
        if not choices:
            return _empty("This run has no meteo output (boxes_meteo.txt).")
        if variable not in choices:
            variable = next(iter(choices))
        selected = input.box() if "box" in input else None
        try:
            box = int(selected)
        except (TypeError, ValueError):
            return _empty("Select a box on the Time-series tab or the map.")
        frame = cached_run.meteo_daily
        try:
            # meteo_daily comes off disk and nothing validates it: a foreign or
            # hand-edited cache can lack the 'box'/'date' pair, and _meteo_
            # variables offers every other column with no dtype filter, so the
            # selected variable can be strings that .astype(float) rejects.
            # Both are this plot's message, not a raise out of the render --
            # which is why the VALUES are read in here too, not just the mask.
            rows = frame[
                (frame["box"].astype("int64") == box)
                & (frame["date"] >= pd.Timestamp(period[0]))
                & (frame["date"] <= pd.Timestamp(period[1]))
            ]
            x_values = rows["date"]
            y_values = rows[variable].astype(float)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("boxmodel: setup meteo frame unreadable: %s", exc)
            return _empty(f"Meteo: {_err(exc)}")
        if not len(rows):
            return _empty(SETUP_NO_METEO_ROWS_MESSAGE)
        figure.add_trace(go.Scatter(x=x_values, y=y_values, name=variable, mode="lines"))
        figure.update_layout(
            height=320,
            yaxis_title=variable,
            title={"text": f"box {box}: {variable} (daily mean)", "font": {"size": 13}},
            margin={"l": 40, "r": 20, "t": 30, "b": 40},
        )
        return figure

    @render.ui
    def band_ratios():
        """Band amplitude ratios beside the skill table (spec sec7).

        Depends on the cache through ``cached()`` -- i.e. on
        ``cache_generation`` -- and never on ``status_tick``: an FFT per level
        target must not re-run on the poller's 2 s badge tick.
        """
        cached_run = cached()
        period = _period()
        obs, sites = observations()
        if cached_run is None or period is None or obs is None or sites is None:
            return None
        try:
            rows = _band_ratio_rows(cached_run, obs, sites, *period)
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("boxmodel: band ratios failed: %s", exc)
            return ui.tags.p(f"Band amplitude: {_err(exc)}", class_="text-muted small")
        if not rows:
            return None
        head = ui.tags.tr(*[ui.tags.th(c) for c in ("site", *BAND_COLUMNS)])

        def _cells(ratios):
            """One row's band cells -- or a single spanning cell saying why
            there are none (the 120-gap-free-day rule)."""
            if not ratios:
                return [ui.tags.td(BAND_NEEDS_DAYS, colspan=str(len(BAND_COLUMNS)))]
            return [ui.tags.td(_fmt(ratios.get(column), 2)) for column in BAND_COLUMNS]

        if all(row["ratios"] is None for row in rows):
            # Nothing to compare anywhere: say it once rather than repeating
            # the same explanation on every site row.
            body = [ui.tags.tr(ui.tags.td("—"), *_cells(None))]
        else:
            body = [ui.tags.tr(ui.tags.td(row["site"]), *_cells(row["ratios"])) for row in rows]
        return ui.tags.div(
            ui.tags.strong("Band amplitude (model / observed), water level"),
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "1.00 means the model reproduces that period band's amplitude; matching the "
                "total variance can still hide compensating errors between bands. Needs at "
                "least 120 gap-free common days.",
                class_="text-muted small",
            ),
            class_="mt-3",
        )

    @_render_download(filename=lambda: _series_filename(series()))
    def download_csv():
        data = series()
        if data is None:
            yield ""
            return
        frame = pd.DataFrame({"date": data["model"].index, "model": data["model"].values})
        if data["obs"] is not None:
            frame = frame.merge(
                pd.DataFrame({"date": data["obs"].index, "observed": data["obs"].values}),
                on="date",
                how="left",
            )
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        yield buffer.getvalue()

    return {"selected_box": selected_box}
