"""Interactive grid map component using deck.gl (via shiny_deckgl).

Provides zoomable/pannable mesh visualization with:
- Mesh wireframe via path_layer (deduplicated edges)
- Filled triangles via simple_mesh_layer (depth, quality, partitions, boundaries)
- Clickable nodes via scatterplot_layer
- Boundary line highlighting via path_layer
- Tooltip HTML on all features
"""

from __future__ import annotations

import asyncio
import html
import logging
import math

import numpy as np

try:
    from pyproj import CRS, Transformer
except ImportError:
    CRS = Transformer = None

try:
    from shiny_deckgl import (
        CARTO_DARK,
        CARTO_POSITRON,
        COORDINATE_SYSTEM,
        OSM_LIBERTY,
        PALETTE_CHLOROPHYLL,
        PALETTE_OCEAN,
        PALETTE_PLASMA,
        PALETTE_THERMAL,
        PALETTE_VIRIDIS,
        color_bins,
        custom_geometry,
        path_layer,
        polygon_layer,
        scatterplot_layer,
        simple_mesh_layer,
        tile_layer,
    )
except ImportError:
    CARTO_DARK = CARTO_POSITRON = OSM_LIBERTY = PALETTE_CHLOROPHYLL = None
    PALETTE_OCEAN = PALETTE_PLASMA = PALETTE_THERMAL = PALETTE_VIRIDIS = None
    COORDINATE_SYSTEM = None
    color_bins = custom_geometry = path_layer = polygon_layer = None
    scatterplot_layer = simple_mesh_layer = tile_layer = None

from shyfem_ui.services.parser_grd import GrdFile

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------

BOUNDARY_COLORS: list[list[int]] = [
    [231, 76, 60, 255],  # red
    [46, 204, 113, 255],  # green
    [243, 156, 18, 255],  # orange
    [155, 89, 182, 255],  # purple
    [26, 188, 156, 255],  # teal
    [230, 126, 34, 255],  # dark orange
    [52, 152, 219, 255],  # blue
    [233, 30, 99, 255],  # pink
]

PARTITION_COLORS: list[list[int]] = [
    [31, 119, 180, 200],
    [255, 127, 14, 200],
    [44, 160, 44, 200],
    [214, 39, 40, 200],
    [148, 103, 189, 200],
    [140, 86, 75, 200],
    [227, 119, 194, 200],
    [127, 127, 127, 200],
    [188, 189, 34, 200],
    [23, 190, 207, 200],
    [174, 199, 232, 200],
    [255, 187, 120, 200],
    [152, 223, 138, 200],
    [255, 152, 150, 200],
    [197, 176, 213, 200],
    [196, 156, 148, 200],
    [247, 182, 210, 200],
    [199, 199, 199, 200],
    [219, 219, 141, 200],
    [158, 218, 229, 200],
]

# Diverging blue -> white -> red (ColorBrewer RdBu, 7 classes, reversed).
# Seven stops so that a symmetric scale with an odd bin count puts the
# white stop exactly on the bin that straddles zero (see ``value_colors``).
PALETTE_DIVERGING: list[list[int]] = [
    [33, 102, 172],
    [103, 169, 207],
    [209, 229, 240],
    [247, 247, 247],
    [253, 219, 199],
    [239, 138, 98],
    [178, 24, 43],
]

# Map from user-facing palette name to shiny_deckgl palette
PALETTES: dict[str, list[list[int]]] = {
    "viridis": PALETTE_VIRIDIS,
    "plasma": PALETTE_PLASMA,
    "ocean": PALETTE_OCEAN,
    "thermal": PALETTE_THERMAL,
    "chlorophyll": PALETTE_CHLOROPHYLL,
    "diverging": PALETTE_DIVERGING,
}

# Map from user-facing basemap name to URL
BASEMAPS: dict[str, str] = {
    "positron": CARTO_POSITRON,
    "dark": CARTO_DARK,
    "osm": OSM_LIBERTY,
}

# RdYlGn-like palette for quality coloring (red=bad, green=good)
_QUALITY_PALETTE: list[list[int]] = [
    [215, 48, 39],  # 0.0 - red (bad)
    [253, 174, 97],  # ~0.2
    [254, 224, 139],  # ~0.4
    [217, 239, 139],  # ~0.6
    [145, 207, 96],  # ~0.8
    [26, 152, 80],  # 1.0 - green (good)
]


# ---------------------------------------------------------------------------
# Coordinate reprojection helpers
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)

# Deduplication set for the "could not determine projection" warning.
# build_layers() invokes _get_lonlat() up to 5 times per render (once per
# builder), so without this every map render would emit 4-5 identical
# warnings. Keyed on (id(grd), epsg) — a (grd, epsg) pair won't change its
# detect result mid-session. Capped to prevent unbounded growth.
_warned_unprojected: set[tuple[int, int | None]] = set()
_WARNED_MAX = 256


def _is_geographic(grd: GrdFile) -> bool:
    """Return ``True`` if the grid appears to use geographic (lon/lat) coords.

    SHYFEM grids are typically in projected metre coordinates (UTM,
    Gauss-Boaga).  We detect geographic coordinates when ALL node
    positions fall within the WGS84 range (|x| <= 180, |y| <= 90).
    """
    if not grd.nodes:
        return True
    return all(abs(n.x) <= 180 and abs(n.y) <= 90 for n in grd.nodes.values())


def _detect_projected_crs(grd: GrdFile) -> int | None:
    """Try to auto-detect the EPSG code for a projected SHYFEM grid.

    Detectable projections:

    * **Gauss-Boaga** (Italy): easting 1.4M-2.1M → fuse West (EPSG:3003),
      easting 2.4M-3.1M → fuse East (EPSG:3004).
    * **UTM**: cannot be determined from coordinates alone (the UTM zone
      is metadata that lives in the STR ``$proj`` section).  Returns
      ``None`` — the caller must supply the EPSG via the UI.

    Returns ``None`` when the projection cannot be determined.
    """
    if not grd.nodes:
        return None
    xs = [n.x for n in grd.nodes.values()]
    cx = sum(xs) / len(xs)

    # Gauss-Boaga (Italy) — distinctive false eastings
    if 1_400_000 < cx < 2_100_000:
        _logger.info("Auto-detected Gauss-Boaga West (EPSG:3003)")
        return 3003
    if 2_400_000 < cx < 3_100_000:
        _logger.info("Auto-detected Gauss-Boaga East (EPSG:3004)")
        return 3004

    # UTM-like (easting 100k-900k) — zone is ambiguous without metadata
    return None


def _get_lonlat(
    grd: GrdFile,
    epsg: int | None = None,
) -> dict[int, list[float]]:
    """Return ``{node_id: [lon, lat]}`` for every node in *grd*.

    Parameters
    ----------
    grd
        Parsed grid file.
    epsg
        Source EPSG code for reprojection (e.g. 32630 for UTM 30N).
        If ``None``, auto-detection is attempted (works for Gauss-Boaga;
        UTM requires explicit EPSG).
    """
    if not grd.nodes:
        return {}

    if _is_geographic(grd) and epsg is None:
        return {nid: [float(node.x), float(node.y)] for nid, node in grd.nodes.items()}

    # Projected grid — use explicit EPSG or try auto-detection
    source_epsg = epsg or _detect_projected_crs(grd)
    if source_epsg is None:
        key = (id(grd), epsg)
        if key not in _warned_unprojected:
            _logger.warning(
                "Could not determine projection for grid; "
                "using raw coordinates (set EPSG in map controls)"
            )
            if len(_warned_unprojected) >= _WARNED_MAX:
                _warned_unprojected.clear()
            _warned_unprojected.add(key)
        return {nid: [float(node.x), float(node.y)] for nid, node in grd.nodes.items()}

    t = Transformer.from_crs(source_epsg, 4326, always_xy=True)
    # One call over arrays: a per-node transform costs ~3 us each (V-06).
    n = len(grd.nodes)
    xs = np.fromiter((node.x for node in grd.nodes.values()), dtype=float, count=n)
    ys = np.fromiter((node.y for node in grd.nodes.values()), dtype=float, count=n)
    lngs, lats = t.transform(xs, ys)
    return {
        nid: [lng, lat]
        for nid, lng, lat in zip(grd.nodes, lngs.tolist(), lats.tolist(), strict=True)
    }


def node_positions(grd: GrdFile, epsg: int | None = None) -> dict[int, list[float]]:
    """Return ``{node_id: [lon, lat]}`` for every node in *grd*.

    This is the supported entry point for pages that need node
    coordinates in the map's frame (for example to place the STR
    ``kbound`` nodes of a boundary, or to trace a box-section interface
    through its nodes). It is a thin public wrapper of the private
    :func:`_get_lonlat` and follows the same rules: geographic grids are
    returned as-is, projected grids are reprojected to WGS84 using
    *epsg* (or auto-detection when *epsg* is ``None``).
    """
    return _get_lonlat(grd, epsg=epsg)


# ---------------------------------------------------------------------------
# Task 2: _build_edge_data
# ---------------------------------------------------------------------------


def _build_edge_data(
    grd: GrdFile, epsg: int | None = None, lonlat: dict[int, list[float]] | None = None
) -> list[dict]:
    """Build deduplicated wireframe edges for all elements.

    Shared edges between adjacent elements appear only once.

    Returns
    -------
    list[dict]
        Each dict has ``{"path": [[lon1, lat1], [lon2, lat2]]}``.
    """
    if not grd.elements:
        return []

    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)
    # Each element side (closing back to its first node), as (a, b) in
    # element order; a shared side is kept where it first appears (V-06:
    # vectorised, it was a per-side Python loop).
    elems = [e.nodes for e in grd.elements.values() if e.nodes]
    if not elems:
        return []
    a = np.fromiter((nid for nodes in elems for nid in nodes), dtype=np.int64)
    counts = np.fromiter((len(nodes) for nodes in elems), dtype=np.int64, count=len(elems))
    first = np.concatenate(([0], np.cumsum(counts)[:-1]))
    nxt = np.arange(len(a)) + 1
    nxt[first + counts - 1] = first
    b = a[nxt]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = (lo - lo.min()) * (int(hi.max()) + 1) + hi  # one int per unordered side
    _, where = np.unique(key, return_index=True)
    where.sort()
    return [
        {"path": [lonlat[i], lonlat[j]]}
        for i, j in zip(a[where].tolist(), b[where].tolist(), strict=True)
        if i in lonlat and j in lonlat
    ]


# ---------------------------------------------------------------------------
# Task 3: _build_triangle_data + helpers
# ---------------------------------------------------------------------------


def _compute_quality(coords: list[list[float]]) -> float:
    """Compute element quality as min(side) / max(side).

    Parameters
    ----------
    coords
        List of ``[x, y]`` vertex coordinates (at least 3).

    Returns
    -------
    float
        Quality ratio in ``[0, 1]``.  1.0 = equilateral, 0.0 = degenerate.
    """
    n = len(coords)
    sides: list[float] = []
    for i in range(n):
        j = (i + 1) % n
        dx = coords[j][0] - coords[i][0]
        dy = coords[j][1] - coords[i][1]
        sides.append(math.sqrt(dx * dx + dy * dy))
    max_side = max(sides)
    if max_side == 0.0:
        return 0.0
    return min(sides) / max_side


def _depth_to_colors(
    depths: list[float],
    palette_name: str,
) -> list[list[int]]:
    """Map depth values to RGBA colors using ``color_bins()``.

    Parameters
    ----------
    depths
        Scalar depth values (one per element).
    palette_name
        Key into :data:`PALETTES` (falls back to viridis).

    Returns
    -------
    list[list[int]]
        One ``[R, G, B, A]`` per input depth.
    """
    if not depths:
        return []
    palette = PALETTES.get(palette_name, PALETTE_VIRIDIS)
    return color_bins(depths, n_bins=6, palette=palette)


_NON_FINITE_COLOR: list[int] = [200, 200, 200]


def value_colors(
    values: list[float | None],
    palette: str = "viridis",
    n_bins: int = 6,
    *,
    symmetric: bool = False,
) -> tuple[list[list[int]], list[tuple[float, float, list[int]]]]:
    """Map scalar *values* to RGB colors plus a legend.

    Non-finite entries (``None``, ``NaN``, ``+/-inf`` — box-model series
    routinely have gaps) are coloured neutral grey ``[200, 200, 200]`` and
    excluded from both the color-bin computation and the legend range, so
    a single missing value can't blow up ``color_bins()`` for the rest of
    the series. The returned color list is position-preserving: it has
    the same length as *values*, with grey standing in for every
    non-finite position.

    Parameters
    ----------
    values
        Scalar values (one per feature) to colour. May contain ``None``,
        ``NaN``, or ``inf`` for missing/undefined entries.
    palette
        Key into :data:`PALETTES` (falls back to viridis).
    n_bins
        Number of equal-width color bins.
    symmetric
        When true the bins span ``[-m, +m]`` with ``m = max(|finite|)``
        (``[-1, 1]`` when every finite value is zero) instead of
        ``[min, max]``, so a difference of zero always maps to the centre
        of the palette. An even *n_bins* is bumped to the next odd count
        so that one bin straddles zero rather than zero sitting on a bin
        edge between two tints. Meant for the ``"diverging"`` palette.

    Returns
    -------
    tuple[list[list[int]], list[tuple[float, float, list[int]]]]
        Per-value ``[R, G, B]`` colors (grey at non-finite positions), and
        legend bins as ``(lo, hi, [R, G, B])`` tuples computed from the
        finite values only. Bins are empty when ``shiny_deckgl`` is
        unavailable (``color_bins`` is ``None``) or no finite values remain.
    """
    if color_bins is None or not values:
        # Same neutral grey as every other "no colour to give" path: two
        # different greys for the same meaning is just a bug waiting to be
        # read as a signal.
        return [list(_NON_FINITE_COLOR) for _ in values], []

    finite_idx: list[int] = []
    finite_vals: list[float] = []
    for i, v in enumerate(values):
        try:
            fv = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            finite_idx.append(i)
            finite_vals.append(fv)

    if not finite_vals:
        return [list(_NON_FINITE_COLOR)] * len(values), []

    pal = PALETTES.get(palette, PALETTE_VIRIDIS)
    if symmetric:
        if n_bins % 2 == 0:
            n_bins += 1
        m = max(abs(v) for v in finite_vals) or 1.0
        lo, hi = -m, m
        # ``color_bins`` derives its range from min/max of what it is
        # given, so pad with the two bounds as sentinels and drop their
        # colours again: the result stays position-preserving.
        binned = color_bins([*finite_vals, lo, hi], n_bins=n_bins, palette=pal)
        finite_colors = [list(c[:3]) for c in binned[: len(finite_vals)]]
    else:
        finite_colors = [list(c[:3]) for c in color_bins(finite_vals, n_bins=n_bins, palette=pal)]
        lo, hi = min(finite_vals), max(finite_vals)
    colors = [list(_NON_FINITE_COLOR) for _ in values]
    for i, c in zip(finite_idx, finite_colors, strict=True):
        colors[i] = c

    step = (hi - lo) / n_bins if hi > lo else 1.0
    idx = [int(round((i / max(n_bins - 1, 1)) * (len(pal) - 1))) for i in range(n_bins)]
    bins = [(lo + i * step, lo + (i + 1) * step, list(pal[j][:3])) for i, j in enumerate(idx)]
    return colors, bins


def build_box_layers(
    polygons: dict[int, list[list[float]]],
    values: dict[int, float] | None,
    *,
    palette: str = "viridis",
    label: str = "",
    posts: list[dict] | None = None,
    selected: int | None = None,
    symmetric: bool = False,
) -> tuple[list[dict], list[tuple[float, float, list[int]]]]:
    """Build a box-polygon layer (coloured by *values*) plus optional posts.

    Parameters
    ----------
    polygons
        ``{box_id: [[lon, lat], ...]}`` closed outer rings, e.g. from
        ``load_box_polygons``/``dissolve_boxes_from_grid``.
    values
        ``{box_id: value}`` to colour boxes by. When ``None`` (or empty),
        boxes are rendered outline-only (``filled=False``) and no legend
        bins are returned.
    palette
        Key into :data:`PALETTES` (falls back to viridis).
    label
        Value label used in the tooltip HTML (e.g. ``"salt"``).
    posts
        Optional list of ``{"site", "lon", "lat", "value"}`` monitoring
        posts rendered as a ``scatterplot_layer``.
    selected
        Box id to highlight (full opacity); other boxes are dimmed.
    symmetric
        Forwarded to :func:`value_colors`: colour scale ``[-m, +m]``
        centred on zero (for difference maps with ``palette="diverging"``).

    Returns
    -------
    tuple[list[dict], list[tuple[float, float, list[int]]]]
        ``(layers, legend_bins)`` — ``layers`` is empty when
        ``shiny_deckgl`` is unavailable.
    """
    if polygon_layer is None:
        return [], []
    # Every tooltip built here is rendered by deck.gl as innerHTML
    # (``tooltip={"html": "{tooltip_html}"}``), so caller-supplied text --
    # a site name straight out of sites.csv, a variable label -- is an XSS
    # sink. Escape at the sink: a shared project's sites.csv is written by
    # one user and rendered in every collaborator's browser.
    safe_label = html.escape(str(label))
    boxes = sorted(polygons)
    if values:
        vals = [float(values.get(b, float("nan"))) for b in boxes]
        finite = [v for v in vals if v == v]
        colors, bins = (
            value_colors(finite, palette=palette, symmetric=symmetric) if finite else ([], [])
        )
        it = iter(colors)
        data = []
        for b, v in zip(boxes, vals, strict=True):
            rgb = next(it) if v == v else [200, 200, 200]
            alpha = 255 if (selected is None or b == selected) else 170
            txt = f"{v:.3f}" if v == v else "n/a"
            data.append(
                {
                    "polygon": polygons[b],
                    "box": b,
                    "value": v if v == v else None,
                    "color": [*rgb, alpha],
                    "tooltip_html": f"<b>box {b}</b><br>{safe_label}: {txt}",
                }
            )
        layer = polygon_layer(
            "boxes",
            data,
            getPolygon="@@d.polygon",
            getFillColor="@@d.color",
            getLineColor=[40, 40, 40, 200],
            lineWidthMinPixels=1,
            filled=True,
            stroked=True,
            pickable=True,
        )
    else:
        bins = []
        data = [
            {
                "polygon": polygons[b],
                "box": b,
                "value": None,
                "color": [0, 0, 0, 0],
                "tooltip_html": f"<b>box {b}</b>",
            }
            for b in boxes
        ]
        layer = polygon_layer(
            "boxes",
            data,
            getPolygon="@@d.polygon",
            getLineColor=[40, 40, 40, 220],
            lineWidthMinPixels=1,
            filled=False,
            stroked=True,
            pickable=True,
        )
    layers = [layer]
    if posts:
        pdata = [
            {
                "position": [p["lon"], p["lat"]],
                "site": p["site"],
                "value": p.get("value"),
                "tooltip_html": f"<b>{html.escape(str(p['site']))}</b>"
                + (f"<br>{p['value']:.3f}" if p.get("value") is not None else ""),
            }
            for p in posts
        ]
        layers.append(
            scatterplot_layer(
                "posts",
                pdata,
                getPosition="@@d.position",
                getFillColor=[255, 60, 60, 230],
                radiusMinPixels=5,
                pickable=True,
            )
        )
    return layers, bins


# Colours of the Setup-tab layers (box-model PR 3). Module constants so the
# page and the tests refer to the same values.
SETUP_INTERFACE_COLOR: list[int] = [110, 110, 110, 220]  # interior section: grey
SETUP_OPEN_INTERFACE_COLOR: list[int] = [41, 128, 185, 240]  # open boundary: blue
SETUP_KIND_COLORS: dict[str, list[int]] = {
    "level": [41, 128, 185, 235],  # blue
    "discharge": [39, 174, 96, 235],  # green
    "unknown": [140, 140, 140, 235],  # grey
}
_SETUP_NODE_RADIUS_PX = 5
_SETUP_NODE_RADIUS_SELECTED_PX = 9


def build_setup_layers(
    interfaces: list[dict],
    boundary_points: list[dict],
    *,
    selected_boundary: int | None = None,
) -> list[dict]:
    """Build the Setup-tab overlay: section interfaces and boundary nodes.

    Parameters
    ----------
    interfaces
        Records ``{"section": int, "from_box": int, "to_box": int,
        "open_boundary": int | None, "path": [[lon, lat], ...]}`` (from
        ``boxmodel_setup.section_interfaces``). ``open_boundary`` is the
        ``$bound<k>`` number ``k`` for an open-boundary section and
        ``None`` for an interior one. Paths with fewer than two points
        are dropped.
    boundary_points
        Records ``{"node": int, "lon": float, "lat": float, "boundary":
        int, "title": str, "kind": "level" | "discharge" | "unknown",
        "boundn": str | None}`` -- one per STR ``kbound`` node.
    selected_boundary
        ``$bound<k>`` number whose nodes are drawn with a larger radius.

    Returns
    -------
    list[dict]
        Up to three layers, in draw order and only when they have data:
        ``setup_interfaces`` (interior sections, grey ``path_layer``),
        ``setup_open_interfaces`` (open-boundary sections, blue and
        wider ``path_layer``) and ``setup_boundary_nodes`` (a
        ``scatterplot_layer`` coloured by ``kind``). Empty when both
        inputs are empty or when ``shiny_deckgl`` is unavailable.

    Notes
    -----
    Every ``tooltip_html`` is rendered by deck.gl as innerHTML, and the
    boundary ``title`` and ``boundn`` come straight out of the STR (user
    text). This builder is the sink: they are escaped here and only here.
    Numbers are rendered through ``int()`` and ``kind`` is reduced to one
    of the three canonical names, so nothing else reaches the HTML.
    The records carry ``node``/``boundary``/``section`` ids but never
    ``box`` or ``node_id`` -- the keys ``grid_map_server``'s click handler
    branches on -- so clicking them selects nothing.
    """
    if path_layer is None or scatterplot_layer is None:
        return []

    interior: list[dict] = []
    opened: list[dict] = []
    for rec in interfaces:
        path = rec.get("path") or []
        if len(path) < 2:
            continue
        sec = int(rec["section"])
        a = int(rec["from_box"])
        b = int(rec["to_box"])
        k = rec.get("open_boundary")
        entry = {
            "path": [[float(x), float(y)] for x, y in path],
            "section": sec,
            "from_box": a,
            "to_box": b,
            "open_boundary": None if k is None else int(k),
        }
        if k is None:
            entry["tooltip_html"] = f"section {sec}: box {a} \u2192 box {b}"
            interior.append(entry)
        else:
            entry["tooltip_html"] = f"section {sec}: open boundary {int(k)} \u2192 box {b}"
            opened.append(entry)

    layers: list[dict] = []
    if interior:
        layers.append(
            path_layer(
                "setup_interfaces",
                interior,
                getPath="@@d.path",
                getColor=list(SETUP_INTERFACE_COLOR),
                widthMinPixels=2,
                pickable=True,
            )
        )
    if opened:
        layers.append(
            path_layer(
                "setup_open_interfaces",
                opened,
                getPath="@@d.path",
                getColor=list(SETUP_OPEN_INTERFACE_COLOR),
                widthMinPixels=4,
                pickable=True,
            )
        )

    ndata: list[dict] = []
    for p in boundary_points:
        node = int(p["node"])
        bnum = int(p["boundary"])
        kind = p.get("kind")
        if kind not in SETUP_KIND_COLORS:
            kind = "unknown"
        title = html.escape(str(p.get("title") or "")) or f"boundary {bnum}"
        boundn = p.get("boundn")
        tip = f"<b>{title}</b><br>boundary {bnum} \u00b7 node {node}<br>{kind}"
        if boundn:
            tip += f"<br>file: {html.escape(str(boundn))}"
        ndata.append(
            {
                "position": [float(p["lon"]), float(p["lat"])],
                "node": node,
                "boundary": bnum,
                "kind": kind,
                "color": list(SETUP_KIND_COLORS[kind]),
                "radius": (
                    _SETUP_NODE_RADIUS_SELECTED_PX
                    if selected_boundary is not None and bnum == selected_boundary
                    else _SETUP_NODE_RADIUS_PX
                ),
                "tooltip_html": tip,
            }
        )
    if ndata:
        layers.append(
            scatterplot_layer(
                "setup_boundary_nodes",
                ndata,
                getPosition="@@d.position",
                getFillColor="@@d.color",
                getRadius="@@d.radius",
                radiusUnits="pixels",
                radiusMinPixels=_SETUP_NODE_RADIUS_PX,
                radiusMaxPixels=_SETUP_NODE_RADIUS_SELECTED_PX,
                stroked=True,
                getLineColor=[255, 255, 255, 220],
                lineWidthMinPixels=1,
                pickable=True,
            )
        )
    return layers


def _bounds_from_layers(layers: list[dict]) -> list[list[float]] | None:
    """Compute ``[[xmin, ymin], [xmax, ymax]]`` from layer feature data.

    Scans each layer's ``data`` entries for a ``polygon`` ring or a
    ``position`` point (as produced by :func:`build_box_layers`). Used to
    fit the map to box layers when there is no grid loaded to derive
    bounds from.
    """
    lons: list[float] = []
    lats: list[float] = []
    for lyr in layers:
        for item in lyr.get("data") or []:
            for lon, lat in item.get("polygon") or []:
                lons.append(lon)
                lats.append(lat)
            pos = item.get("position")
            if pos:
                lons.append(pos[0])
                lats.append(pos[1])
    if not lons or not lats:
        return None
    return [[min(lons), min(lats)], [max(lons), max(lats)]]


def _quality_to_colors(qualities: list[float]) -> list[list[int]]:
    """Map quality ratios ``[0..1]`` to RGBA using a RdYlGn palette.

    Parameters
    ----------
    qualities
        Quality ratios (one per element).

    Returns
    -------
    list[list[int]]
        One ``[R, G, B, A]`` per input quality.
    """
    if not qualities:
        return []
    return color_bins(qualities, n_bins=6, palette=_QUALITY_PALETTE)


def _build_triangle_data(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
) -> list[dict]:
    """Build filled polygon data for deck.gl ``polygon_layer``.

    Parameters
    ----------
    grd
        Parsed grid.
    mode
        One of ``"mesh"``, ``"depth"``, ``"depth_3d"``, ``"quality"``,
        ``"partitions"``, ``"boundaries"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    elevation_scale
        Multiplier for 3-D elevation (used only when *mode* = ``"depth_3d"``).
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.

    Returns
    -------
    list[dict]
        Each dict contains at minimum: ``polygon``, ``fill_color``,
        ``elem_id``, ``depth``, ``quality``, ``tooltip_html``.
        ``"depth_3d"`` mode also adds ``elevation``.
    """
    if mode == "mesh":
        return []

    if mode == "partitions" and not partition_map:
        return []

    if not grd.elements or not grd.nodes:
        return []

    lonlat = _get_lonlat(grd, epsg=epsg)

    # Gather per-element data
    records: list[dict] = []
    all_depths: list[float] = []
    all_qualities: list[float] = []

    for elem in grd.elements.values():
        coords = []
        node_depths: list[float] = []
        for nid in elem.nodes:
            if nid not in lonlat:
                break
            coords.append(lonlat[nid])
            node = grd.nodes.get(nid)
            d = node.depth if (node and node.depth is not None) else 0.0
            node_depths.append(d)
        else:
            # All nodes resolved
            avg_depth = sum(node_depths) / len(node_depths) if node_depths else 0.0
            quality = _compute_quality(coords)
            records.append(
                {
                    "polygon": coords,
                    "elem_id": elem.id,
                    "depth": round(avg_depth, 6),
                    "quality": round(quality, 6),
                    "node_depths": node_depths,
                }
            )
            all_depths.append(avg_depth)
            all_qualities.append(quality)

    if not records:
        return []

    # Compute colors based on mode
    if mode in ("depth", "depth_3d"):
        colors = _depth_to_colors(all_depths, colorscale)
    elif mode == "quality":
        colors = _quality_to_colors(all_qualities)
    elif mode == "partitions":
        colors = []
        for rec in records:
            part = partition_map.get(rec["elem_id"], 0)  # type: ignore[union-attr]
            colors.append(PARTITION_COLORS[part % len(PARTITION_COLORS)])
    elif mode == "boundaries":
        colors = [[200, 200, 200, 80]] * len(records)
    else:
        colors = [[200, 200, 200, 255]] * len(records)

    # Build final output
    result: list[dict] = []
    for i, rec in enumerate(records):
        entry: dict = {
            "polygon": rec["polygon"],
            "fill_color": colors[i],
            "elem_id": rec["elem_id"],
            "depth": rec["depth"],
            "quality": rec["quality"],
            "tooltip_html": _triangle_tooltip(rec, mode),
        }
        if mode == "depth_3d":
            # Use abs() so negative depths (below sea level) produce positive
            # elevations — deck.gl extrudes downward for negative values, making
            # them invisible even with pitch=45.
            entry["elevation"] = abs(rec["depth"]) * elevation_scale
        result.append(entry)

    return result


def _build_mesh_geometry(
    grd: GrdFile,
    mode: str = "depth",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
    lonlat: dict[int, list[float]] | None = None,
) -> dict:
    """Convert a :class:`GrdFile` into indexed mesh geometry for ``simple_mesh_layer``.

    Vertex positions are in **metres** relative to the mesh centre, using
    the deck.gl ``METER_OFFSETS`` coordinate system.  Vertices are duplicated
    per element so that per-element coloring is preserved.

    Parameters
    ----------
    grd
        Parsed grid.
    mode
        Coloring mode: ``"depth"``, ``"depth_3d"``, ``"quality"``,
        ``"partitions"``, ``"boundaries"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    elevation_scale
        Vertical exaggeration for ``"depth_3d"`` mode.
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.
    epsg
        Source EPSG code for coordinate reprojection.

    Returns
    -------
    dict
        Keys: ``positions``, ``normals``, ``colors`` (flat float lists),
        ``indices`` (flat int list), ``center`` (``[lon, lat]``),
        ``n_vertices``, ``n_triangles``.
    """
    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)

    # Node table: one row per node, in lonlat order.
    row = {nid: i for i, nid in enumerate(lonlat)}
    node_ll = np.array(list(lonlat.values()), dtype=float).reshape(-1, 2)
    node_depth = np.array(
        [
            node.depth if (node := grd.nodes.get(nid)) and node.depth is not None else 0.0
            for nid in lonlat
        ],
        dtype=float,
    )

    # Compute centre in lon/lat
    ctr_lon = (node_ll[:, 0].min() + node_ll[:, 0].max()) / 2 if len(node_ll) else 0.0
    ctr_lat = (node_ll[:, 1].min() + node_ll[:, 1].max()) / 2 if len(node_ll) else 0.0
    ctr_lon, ctr_lat = float(ctr_lon), float(ctr_lat)

    # Metres-per-degree at centre latitude
    m_per_deg_lon = 111_320 * math.cos(math.radians(ctr_lat))
    m_per_deg_lat = 110_540

    z_scale = elevation_scale if mode == "depth_3d" else 0.0

    # Per-element data, vectorised (same rules as _build_triangle_data): an
    # element with a node that has no position is skipped.
    elems = [e for e in grd.elements.values() if e.nodes]
    counts = np.fromiter((len(e.nodes) for e in elems), dtype=np.int64, count=len(elems))
    flat = np.fromiter(
        (row.get(nid, -1) for e in elems for nid in e.nodes), dtype=np.int64, count=counts.sum()
    )
    elem_of = np.repeat(np.arange(len(elems)), counts)
    kept = np.ones(len(elems), dtype=bool)
    kept[elem_of[flat < 0]] = False

    empty = {
        "positions": [],
        "normals": [],
        "colors": [],
        "indices": [],
        "center": [round(ctr_lon, 5), round(ctr_lat, 5)],
        "n_vertices": 0,
        "n_triangles": 0,
    }
    if not kept.any():
        return empty

    rows = flat[kept[elem_of]]
    n_verts = counts[kept]
    first = np.concatenate(([0], np.cumsum(n_verts)[:-1]))
    coords = node_ll[rows]
    depths = node_depth[rows]
    kept_ids = [elems[i].id for i in np.flatnonzero(kept)]

    avg_depths = np.add.reduceat(depths, first) / n_verts
    # Quality = shortest side / longest side, sides wrapping to the first node.
    nxt = np.arange(len(rows)) + 1
    nxt[first + n_verts - 1] = first
    sides = np.hypot(*(coords[nxt] - coords).T)
    longest = np.maximum.reduceat(sides, first)
    qualities = np.where(
        longest == 0.0,
        0.0,
        np.minimum.reduceat(sides, first) / np.where(longest == 0.0, 1.0, longest),
    )

    # Compute per-element RGBA colors (int 0-255)
    if mode in ("depth", "depth_3d"):
        elem_colors = _depth_to_colors(avg_depths.tolist(), colorscale)
    elif mode == "quality":
        elem_colors = _quality_to_colors(qualities.tolist())
    elif mode == "partitions":
        elem_colors = [
            PARTITION_COLORS[(partition_map or {}).get(eid, 0) % len(PARTITION_COLORS)]
            for eid in kept_ids
        ]
    else:  # boundaries
        elem_colors = [[200, 200, 200, 80]] * len(kept_ids)

    # Geometry with duplicated vertices per element, in numpy (V-06: the
    # per-vertex Python loop and its round() calls took seconds on 50k nodes).
    pos = np.empty((len(coords), 3))
    pos[:, 0] = (coords[:, 0] - ctr_lon) * m_per_deg_lon
    pos[:, 1] = (coords[:, 1] - ctr_lat) * m_per_deg_lat
    pos[:, 2] = np.abs(depths) * z_scale

    rgb = np.asarray([c[:3] for c in elem_colors], dtype=float) / 255.0
    colors = np.round(np.repeat(rgb, n_verts, axis=0), 3)

    # Element i's first triangle (0,1,2) if it has 3+ vertices, then (0,2,3)
    # for a quad, in element order.
    tris = first[:, None, None] + np.array([[0, 1, 2], [0, 2, 3]])
    keep = np.stack([n_verts >= 3, n_verts == 4], axis=1)
    indices = tris[keep].reshape(-1)

    # Per-vertex normals: the sum of adjacent face normals, normalised.
    faces = indices.reshape(-1, 3)
    face_normals = np.cross(
        pos[faces[:, 1]] - pos[faces[:, 0]], pos[faces[:, 2]] - pos[faces[:, 0]]
    )
    normals = np.zeros_like(pos)
    for k in range(3):
        np.add.at(normals, faces[:, k], face_normals)
    length = np.linalg.norm(normals, axis=1)
    length[length == 0.0] = 1.0
    normals = np.round(normals / length[:, None], 4)

    return {
        "positions": np.round(pos, 2).reshape(-1).tolist(),
        "normals": normals.reshape(-1).tolist(),
        "colors": colors.reshape(-1).tolist(),
        "indices": indices.tolist(),
        "center": [round(ctr_lon, 5), round(ctr_lat, 5)],
        "n_vertices": len(pos),
        "n_triangles": len(faces),
    }


def _triangle_tooltip(rec: dict, mode: str) -> str:
    """Build tooltip HTML for a triangle element."""
    parts = [f"<b>Elem {rec['elem_id']}</b>"]
    if mode in ("depth", "depth_3d", "boundaries"):
        parts.append(f"Depth: {rec['depth']:.2f}")
    if mode == "quality":
        parts.append(f"Quality: {rec['quality']:.3f}")
    if mode == "partitions":
        parts.append(f"Depth: {rec['depth']:.2f}")
    return "<br>".join(parts)


# ---------------------------------------------------------------------------
# Task 4: _build_boundary_data + _build_node_data
# ---------------------------------------------------------------------------


def _build_boundary_data(
    grd: GrdFile, epsg: int | None = None, lonlat: dict[int, list[float]] | None = None
) -> dict[int, list[dict]]:
    """Build boundary line data grouped by line type.

    Parameters
    ----------
    grd
        Parsed grid.

    Returns
    -------
    dict[int, list[dict]]
        ``{line_type: [{"path": [[lon,lat],...], "line_id": int,
        "tooltip_html": str}, ...]}``
    """
    if not grd.lines:
        return {}

    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)
    grouped: dict[int, list[dict]] = {}

    for line in grd.lines.values():
        path: list[list[float]] = []
        for nid in line.nodes:
            if nid in lonlat:
                path.append(lonlat[nid])
        if len(path) < 2:
            continue

        tooltip = (
            f"<b>Boundary {line.id}</b><br>"
            f"Type: {line.line_type}<br>"
            f"Nodes: {len(line.nodes)}"
        )

        entry = {
            "path": path,
            "line_id": line.id,
            "tooltip_html": tooltip,
        }

        if line.line_type not in grouped:
            grouped[line.line_type] = []
        grouped[line.line_type].append(entry)

    return grouped


def _build_node_data(
    grd: GrdFile, epsg: int | None = None, lonlat: dict[int, list[float]] | None = None
) -> list[dict]:
    """Build node data for deck.gl ``scatterplot_layer``.

    Parameters
    ----------
    grd
        Parsed grid.

    Returns
    -------
    list[dict]
        Each dict: ``{"position": [lon,lat], "node_id": int,
        "depth": float, "node_type": int, "tooltip_html": str}``.
    """
    if not grd.nodes:
        return []

    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)
    result: list[dict] = []

    for nid, node in grd.nodes.items():
        depth = node.depth if node.depth is not None else 0.0
        pos = lonlat[nid]

        parts = [f"<b>Node {nid}</b>"]
        parts.append(f"Lon: {pos[0]:.6f}")
        parts.append(f"Lat: {pos[1]:.6f}")
        if node.depth is not None:
            parts.append(f"Depth: {node.depth:.2f}")
        else:
            parts.append("No depth")
        parts.append(f"Type: {node.node_type}")
        tooltip = "<br>".join(parts)

        result.append(
            {
                "position": pos,
                "node_id": nid,
                "depth": float(depth),
                "node_type": node.node_type,
                "tooltip_html": tooltip,
            }
        )

    return result


# ---------------------------------------------------------------------------
# EMODnet bathymetry WMS base layer
# ---------------------------------------------------------------------------

EMODNET_WMS_URL = (
    "https://ows.emodnet-bathymetry.eu/wms?"
    "SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
    "&FORMAT=image/png&TRANSPARENT=true"
    "&LAYERS=emodnet:mean_atlas_land"
    "&CRS=EPSG:3857&WIDTH=256&HEIGHT=256"
    "&BBOX={bbox-epsg-3857}"
)


def _build_emodnet_layer() -> dict:
    """Build an EMODnet bathymetry WMS tile layer."""
    return tile_layer(
        "emodnet",
        EMODNET_WMS_URL,
        minZoom=0,
        maxZoom=18,
        tileSize=256,
        opacity=0.6,
        pickable=False,
    )


# ---------------------------------------------------------------------------
# Task 5: build_layers
# ---------------------------------------------------------------------------


def build_layers(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
    lonlat: dict[int, list[float]] | None = None,
) -> list[dict]:
    """Assemble deck.gl layers for the given grid and display mode.

    Parameters
    ----------
    grd
        Parsed grid file.
    mode
        Display mode: ``"mesh"``, ``"depth"``, ``"depth_3d"``,
        ``"boundaries"``, ``"quality"``, ``"partitions"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    elevation_scale
        Multiplier for 3-D extrusion (``"depth_3d"`` mode only).
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.
    epsg
        Source EPSG code for coordinate reprojection (e.g. 32630 for
        UTM zone 30N).  ``None`` means auto-detect.

    Returns
    -------
    list[dict]
        Layer definitions suitable for ``shiny_deckgl.output_deckgl``.
    """
    # Empty grid => no layers
    if not grd.nodes:
        return []

    # Reproject once; every builder below reuses it (V-06).
    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)
    layers: list[dict] = []

    # --- EMODnet bathymetry base layer (rendered below everything else) ---
    layers.append(_build_emodnet_layer())

    has_elements = bool(grd.elements)

    # --- Wireframe edge data (reused across modes, only if elements exist) ---
    edge_data = _build_edge_data(grd, epsg=epsg, lonlat=lonlat) if has_elements else []

    # --- Build layers per mode (element-based modes need elements) ---

    if mode == "mesh" and has_elements:
        # Wireframe only, blue edges
        layers.append(
            path_layer(
                "wireframe",
                edge_data,
                getPath="@@d.path",
                getColor=[45, 156, 186, 255],
                widthMinPixels=1,
                pickable=False,
            )
        )

    elif mode == "depth" and has_elements:
        # Filled mesh + thin gray wireframe
        mesh_data = _build_mesh_geometry(
            grd,
            mode=mode,
            colorscale=colorscale,
            epsg=epsg,
            lonlat=lonlat,
        )
        layers.append(
            simple_mesh_layer(
                "triangles",
                **custom_geometry(mesh_data),
                pickable=True,
                wireframe=False,
            )
        )
        layers.append(
            path_layer(
                "wireframe",
                edge_data,
                getPath="@@d.path",
                getColor=[150, 150, 150, 80],
                widthMinPixels=0.5,
                pickable=False,
            )
        )

    elif mode == "depth_3d" and has_elements:
        # Filled mesh with Z elevation, NO wireframe
        mesh_data = _build_mesh_geometry(
            grd,
            mode=mode,
            colorscale=colorscale,
            elevation_scale=elevation_scale,
            epsg=epsg,
            lonlat=lonlat,
        )
        layers.append(
            simple_mesh_layer(
                "triangles",
                **custom_geometry(mesh_data),
                pickable=True,
                wireframe=False,
            )
        )

    elif mode == "boundaries" or (not has_elements and grd.lines):
        # Bold boundary lines (+ light mesh if elements exist)
        if has_elements:
            mesh_data = _build_mesh_geometry(
                grd,
                mode="boundaries",
                colorscale=colorscale,
                epsg=epsg,
                lonlat=lonlat,
            )
            layers.append(
                simple_mesh_layer(
                    "triangles",
                    **custom_geometry(mesh_data),
                    pickable=True,
                    wireframe=False,
                )
            )
            layers.append(
                path_layer(
                    "wireframe",
                    edge_data,
                    getPath="@@d.path",
                    getColor=[150, 150, 150, 80],
                    widthMinPixels=0.5,
                    pickable=False,
                )
            )
        # Add bold boundary path_layers
        boundary_data = _build_boundary_data(grd, epsg=epsg, lonlat=lonlat)
        for btype, blines in boundary_data.items():
            color = BOUNDARY_COLORS[btype % len(BOUNDARY_COLORS)]
            layers.append(
                path_layer(
                    f"boundary_{btype}",
                    blines,
                    getPath="@@d.path",
                    getColor=color,
                    widthMinPixels=3,
                    pickable=True,
                )
            )

    elif mode == "quality" and has_elements:
        # Filled mesh + thin wireframe
        mesh_data = _build_mesh_geometry(
            grd,
            mode=mode,
            colorscale=colorscale,
            epsg=epsg,
            lonlat=lonlat,
        )
        layers.append(
            simple_mesh_layer(
                "triangles",
                **custom_geometry(mesh_data),
                pickable=True,
                wireframe=False,
            )
        )
        layers.append(
            path_layer(
                "wireframe",
                edge_data,
                getPath="@@d.path",
                getColor=[150, 150, 150, 80],
                widthMinPixels=0.5,
                pickable=False,
            )
        )

    elif mode == "partitions" and has_elements:
        # Filled mesh only (no wireframe)
        mesh_data = _build_mesh_geometry(
            grd,
            mode=mode,
            colorscale=colorscale,
            partition_map=partition_map,
            epsg=epsg,
            lonlat=lonlat,
        )
        layers.append(
            simple_mesh_layer(
                "triangles",
                **custom_geometry(mesh_data),
                pickable=True,
                wireframe=False,
            )
        )

    # --- Optional boundary overlay (not in boundaries mode, already done) ---
    if mode != "boundaries" and has_elements:
        boundary_data = _build_boundary_data(grd, epsg=epsg, lonlat=lonlat)
        for btype, blines in boundary_data.items():
            color = BOUNDARY_COLORS[btype % len(BOUNDARY_COLORS)]
            layers.append(
                path_layer(
                    f"boundary_{btype}",
                    blines,
                    getPath="@@d.path",
                    getColor=color,
                    widthMinPixels=3,
                    pickable=True,
                )
            )

    # --- Node overlay ---
    node_data = _build_node_data(grd, epsg=epsg, lonlat=lonlat)
    layers.append(
        scatterplot_layer(
            "nodes",
            node_data,
            getPosition="@@d.position",
            getFillColor=[255, 60, 60, 220],
            radiusMinPixels=3,
            radiusMaxPixels=6,
            pickable=True,
        )
    )

    return layers


# ---------------------------------------------------------------------------
# Task 6: _compute_view_state
# ---------------------------------------------------------------------------


def _compute_view_state(
    grd: GrdFile,
    is_3d: bool = False,
    epsg: int | None = None,
    lonlat: dict[int, list[float]] | None = None,
) -> dict:
    """Compute an initial deck.gl view state that fits the grid bounds.

    Parameters
    ----------
    grd
        Parsed grid file.
    is_3d
        If ``True``, tilt the camera for 3-D perspective.
    epsg
        Source EPSG code for coordinate reprojection.

    Returns
    -------
    dict
        View state with ``longitude``, ``latitude``, ``zoom``,
        ``pitch``, ``bearing``, and ``bounds``.
    """
    if not grd.nodes:
        return {
            "longitude": 0,
            "latitude": 0,
            "zoom": 2,
            "pitch": 0,
            "bearing": 0,
            "bounds": [[-180, -90], [180, 90]],
        }

    # Use reprojected lon/lat (handles projected grids when EPSG is set)
    if lonlat is None:
        lonlat = _get_lonlat(grd, epsg=epsg)
    lons = [pos[0] for pos in lonlat.values()]
    lats = [pos[1] for pos in lonlat.values()]
    xmin, xmax = min(lons), max(lons)
    ymin, ymax = min(lats), max(lats)

    # Safety: if still outside WGS84 range (projection failed), use defaults
    if abs(ymin) > 90 or abs(ymax) > 90 or abs(xmin) > 180 or abs(xmax) > 180:
        return {
            "longitude": 0,
            "latitude": 0,
            "zoom": 2,
            "pitch": 0,
            "bearing": 0,
            "bounds": [[-180, -90], [180, 90]],
        }

    center_lon = (xmin + xmax) / 2.0
    center_lat = (ymin + ymax) / 2.0

    dx = max(xmax - xmin, 1e-6)
    dy = max(ymax - ymin, 1e-6)
    extent = max(dx, dy)
    zoom = math.log2(360.0 / extent)
    zoom = max(0, min(20, zoom))

    pitch = 45 if is_3d else 0
    bearing = -30 if is_3d else 0

    return {
        "longitude": center_lon,
        "latitude": center_lat,
        "zoom": zoom,
        "pitch": pitch,
        "bearing": bearing,
        "bounds": [[xmin, ymin], [xmax, ymax]],
    }


# ---------------------------------------------------------------------------
# Backward-compatibility stubs (removed when migration is complete)
# ---------------------------------------------------------------------------


def _build_edge_arrays(grd: GrdFile):
    """Legacy Plotly edge builder -- kept for backward compatibility.

    Returns (edge_x, edge_y, x, y, node_ids, node_map).
    """
    import numpy as np

    node_ids = sorted(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    edge_x: list = []
    edge_y: list = []
    for elem in grd.elements.values():
        indices = [node_map.get(nid) for nid in elem.nodes]
        indices = [i for i in indices if i is not None]
        if len(indices) < 3:
            continue
        for i in range(len(indices)):
            j = (i + 1) % len(indices)
            edge_x.extend([float(x[indices[i]]), float(x[indices[j]]), None])
            edge_y.extend([float(y[indices[i]]), float(y[indices[j]]), None])

    return edge_x, edge_y, x, y, node_ids, node_map


def build_mesh_figure(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "Viridis",
    show_boundaries: bool = True,
    show_nodes: bool = False,
    partition_map: dict[int, int] | None = None,
):
    """Legacy Plotly figure builder -- kept for backward compatibility.

    Will be removed when the full deck.gl migration is complete (Task 7+).
    """
    import numpy as np  # noqa: E402
    import plotly.graph_objects as go  # noqa: E402

    if not grd.nodes:
        fig = go.Figure()
        fig.add_annotation(
            text="No grid data loaded",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font_size=18,
            font_color="gray",
        )
        fig.update_layout(height=600)
        return fig

    edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)
    fig = go.Figure()

    if mode == "mesh":
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="#2D9CBA", width=0.5),
                hoverinfo="skip",
                name="Mesh",
            )
        )
    elif mode == "depth":
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="rgba(200,200,200,0.3)", width=0.3),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        depths = np.array(
            [grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0 for nid in node_ids]
        )
        if not np.all(depths == 0):
            fig.add_trace(
                go.Scattergl(
                    x=x.tolist(),
                    y=y.tolist(),
                    mode="markers",
                    marker=dict(
                        size=4,
                        color=depths.tolist(),
                        colorscale=colorscale,
                        colorbar=dict(title="Depth", thickness=15),
                        showscale=True,
                    ),
                    hoverinfo="text",
                    name="Depth",
                )
            )
    elif mode == "quality":
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="rgba(200,200,200,0.3)", width=0.3),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        qualities, cx_arr, cy_arr = [], [], []
        for elem in grd.elements.values():
            if not elem.is_triangle:
                continue
            indices = [node_map.get(nid) for nid in elem.nodes]
            if any(i is None for i in indices):
                continue
            ex, ey = x[indices], y[indices]
            sides = [
                np.sqrt((ex[(i + 1) % 3] - ex[i]) ** 2 + (ey[(i + 1) % 3] - ey[i]) ** 2)
                for i in range(3)
            ]
            q = min(sides) / max(sides) if max(sides) > 0 else 0
            qualities.append(q)
            cx_arr.append(float(np.mean(ex)))
            cy_arr.append(float(np.mean(ey)))
        if qualities:
            fig.add_trace(
                go.Scattergl(
                    x=cx_arr,
                    y=cy_arr,
                    mode="markers",
                    marker=dict(
                        size=5,
                        color=qualities,
                        colorscale="RdYlGn",
                        cmin=0,
                        cmax=1,
                        colorbar=dict(title="Quality", thickness=15),
                        showscale=True,
                    ),
                    hoverinfo="text",
                    name="Quality",
                )
            )
    elif mode == "boundaries":
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="rgba(200,200,200,0.4)", width=0.3),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        show_boundaries = True
    elif mode == "partitions" and partition_map:
        num_parts = max(partition_map.values()) + 1 if partition_map else 1
        _pcolors = [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ]
        part_edges: dict[int, tuple[list, list]] = {p: ([], []) for p in range(num_parts)}
        for elem in grd.elements.values():
            part = partition_map.get(elem.id, 0)
            indices = [node_map.get(nid) for nid in elem.nodes]
            indices = [i for i in indices if i is not None]
            if len(indices) < 3:
                continue
            for i in range(len(indices)):
                j = (i + 1) % len(indices)
                part_edges[part][0].extend([float(x[indices[i]]), float(x[indices[j]]), None])
                part_edges[part][1].extend([float(y[indices[i]]), float(y[indices[j]]), None])
        for p in range(num_parts):
            color = _pcolors[p % len(_pcolors)]
            if part_edges[p][0]:
                fig.add_trace(
                    go.Scattergl(
                        x=part_edges[p][0],
                        y=part_edges[p][1],
                        mode="lines",
                        line=dict(color=color, width=0.7),
                        hoverinfo="skip",
                        name=f"P{p}",
                    )
                )
    else:
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="#2D9CBA", width=0.5),
                hoverinfo="skip",
                name="Mesh",
            )
        )

    if show_boundaries and grd.lines:
        _bcolors = [
            "#e74c3c",
            "#2ecc71",
            "#f39c12",
            "#9b59b6",
            "#1abc9c",
            "#e67e22",
            "#3498db",
            "#e91e63",
        ]
        line_types = sorted(grd.get_line_types())
        for lt_idx, lt in enumerate(line_types):
            bx, by = [], []
            for line in grd.lines.values():
                if line.line_type != lt:
                    continue
                indices = [node_map.get(nid) for nid in line.nodes]
                indices = [i for i in indices if i is not None]
                if len(indices) < 2:
                    continue
                for i in range(len(indices) - 1):
                    bx.extend([float(x[indices[i]]), float(x[indices[i + 1]]), None])
                    by.extend([float(y[indices[i]]), float(y[indices[i + 1]]), None])
            if bx:
                color = _bcolors[lt_idx % len(_bcolors)]
                fig.add_trace(
                    go.Scattergl(
                        x=bx,
                        y=by,
                        mode="lines",
                        line=dict(color=color, width=3),
                        hoverinfo="skip",
                        name=f"Boundary type {lt}",
                    )
                )

    if show_nodes:
        fig.add_trace(
            go.Scattergl(
                x=x.tolist(),
                y=y.tolist(),
                mode="markers",
                marker=dict(size=3, color="red"),
                hoverinfo="text",
                name="Nodes",
            )
        )

    fig.update_layout(
        xaxis=dict(scaleanchor="y", scaleratio=1, title="X"),
        yaxis=dict(title="Y"),
        hovermode="closest",
        showlegend=True,
        margin=dict(l=50, r=20, t=60, b=50),
        height=600,
        dragmode="pan",
    )
    return fig


# ---------------------------------------------------------------------------
# Shiny module: grid_map_ui + grid_map_server (Task 7 — deck.gl)
# ---------------------------------------------------------------------------

from collections.abc import Callable  # noqa: E402

from shiny import module, reactive, render, ui  # noqa: E402

try:
    from shiny_deckgl import (  # noqa: E402
        MapWidget,
        fullscreen_widget,
        layer_legend_widget,
        legend_control,
        screenshot_widget,
        zoom_widget,
    )
except ImportError:
    MapWidget = fullscreen_widget = layer_legend_widget = None
    legend_control = screenshot_widget = zoom_widget = None

# View-mode choices for the dropdown
_VIEW_MODES: dict[str, str] = {
    "mesh": "Mesh",
    "depth": "Depth",
    "depth_3d": "Depth 3D",
    "boundaries": "Boundaries",
    "quality": "Quality",
}

# User-facing palette names (keys of PALETTES dict defined above)
_PALETTE_CHOICES: dict[str, str] = {
    "viridis": "Viridis",
    "plasma": "Plasma",
    "ocean": "Ocean",
    "thermal": "Thermal",
    "chlorophyll": "Chlorophyll",
}

# User-facing basemap names (keys of BASEMAPS dict defined above)
_BASEMAP_CHOICES: dict[str, str] = {
    "positron": "Positron",
    "dark": "Dark",
    "osm": "OSM",
}


def _build_label_map(layers: list[dict], mode: str = "mesh") -> dict[str, str]:
    """Build a layer-ID -> friendly-name map for layer_legend_widget."""
    triangles_label = mode.replace("_", " ").title() if mode != "mesh" else "Triangles"
    _STATIC_LABELS = {
        "emodnet": "EMODnet Bathy",
        "wireframe": "Wireframe",
        "triangles": triangles_label,
        "nodes": "Nodes",
        "boxes": "Boxes",
        "posts": "Monitoring posts",
        "setup_interfaces": "Section interfaces",
        "setup_open_interfaces": "Open-boundary interfaces",
        "setup_boundary_nodes": "Boundary nodes",
    }
    label_map: dict[str, str] = {}
    for layer in layers:
        lid = layer.get("id", "")
        if lid in _STATIC_LABELS:
            label_map[lid] = _STATIC_LABELS[lid]
        elif lid.startswith("boundary_"):
            btype = lid.split("_", 1)[1]
            label_map[lid] = btype.replace("_", " ").title()
    return label_map


@module.ui
def grid_map_ui(height: str = "600px"):
    """Deck.gl interactive grid map UI.

    Includes map controls (view mode, palette, basemap, elevation slider,
    boundary/node toggles) and the MapWidget output.
    """
    # MapWidget uses a raw HTML id (not auto-namespaced by @module.ui),
    # so we must resolve the module namespace manually.
    if MapWidget is None:
        return ui.div(
            ui.div(
                ui.tags.i(class_="bi bi-exclamation-triangle me-2"),
                "Interactive map requires the ",
                ui.tags.code("shiny_deckgl"),
                " package. Install it with: ",
                ui.tags.code("pip install shiny-deckgl"),
                class_="alert alert-warning",
            ),
            style=f"height: {height};",
        )

    _map = MapWidget(
        id=module.resolve_id("deckgl_map"),
        tooltip={"html": "{tooltip_html}"},
        picking_radius=5,
    )

    return ui.div(
        # Controls row
        ui.div(
            ui.div(
                ui.input_select(
                    "map_mode",
                    "View",
                    choices=_VIEW_MODES,
                    selected="mesh",
                    width="120px",
                ),
                ui.input_select(
                    "map_colors",
                    "Colors",
                    choices=_PALETTE_CHOICES,
                    selected="viridis",
                    width="120px",
                ),
                ui.input_select(
                    "map_basemap",
                    "Basemap",
                    choices=_BASEMAP_CHOICES,
                    selected="positron",
                    width="120px",
                ),
                ui.panel_conditional(
                    "input.map_mode === 'depth_3d'",
                    ui.input_slider(
                        "elevation_scale",
                        "Elevation",
                        min=1,
                        max=50,
                        value=10,
                        width="140px",
                    ),
                ),
                ui.input_select(
                    "grid_epsg",
                    "CRS",
                    choices={
                        "": "Auto",
                        "32629": "UTM 29N",
                        "32630": "UTM 30N",
                        "32631": "UTM 31N",
                        "32632": "UTM 32N",
                        "32633": "UTM 33N",
                        "32634": "UTM 34N",
                        "32635": "UTM 35N",
                        "32636": "UTM 36N",
                        "3003": "GB West",
                        "3004": "GB East",
                    },
                    selected="",
                    width="120px",
                ),
                class_="d-flex flex-wrap align-items-end gap-2",
            ),
            class_="mb-2",
        ),
        # Map widget
        _map.ui(width="100%", height=height),
        # Inspection info panel (click feedback)
        ui.output_ui("inspect_info"),
        class_="grid-map-component",
    )


def _fit_key(grd: GrdFile, epsg: int | None, is_3d: bool) -> tuple:
    """What the view is fitted to: the grid object, its EPSG, and 2-D vs 3-D
    (3-D tilts the camera). Nothing else may move the user's view."""
    return (grd, epsg, is_3d)


def _needs_refit(last: tuple | None, key: tuple) -> bool:
    """Whether ``key`` differs from the last fit. The grid is compared by
    identity: the key holds the grid itself, so its id cannot be reused."""
    return last is None or last[0] is not key[0] or last[1:] != key[1:]


def _build_map(grd, mode, colorscale, elevation_scale, partition_map, epsg, is_3d):
    """Layers and view state for one render (pure; runs in a worker thread)."""
    lonlat = _get_lonlat(grd, epsg=epsg)
    layers = build_layers(
        grd,
        mode=mode,
        colorscale=colorscale,
        elevation_scale=elevation_scale,
        partition_map=partition_map,
        epsg=epsg,
        lonlat=lonlat,
    )
    return layers, _compute_view_state(grd, is_3d=is_3d, epsg=epsg, lonlat=lonlat)


@module.server
def grid_map_server(
    input,
    output,
    session,
    grd_file: reactive.Value,
    partition_map: reactive.Value | None = None,
    on_node_click: Callable[[int], None] | None = None,
    *,
    extra_layers: reactive.Value | None = None,
    on_box_click: Callable[[int], None] | None = None,
):
    """Deck.gl interactive grid map server logic.

    Parameters
    ----------
    input, output, session
        Shiny module server arguments (injected by ``@module.server``).
    grd_file
        Reactive value holding the current ``GrdFile`` (or ``None``).
    partition_map
        Optional reactive value holding ``{elem_id: partition_index}`` or ``None``.
    on_node_click
        Optional callback invoked with the clicked node ID.
    extra_layers
        Optional reactive value holding a list of additional deck.gl layer
        dicts (e.g. from :func:`build_box_layers`) to overlay on the map.
        Read (not written) by the render effect, so it may safely be
        updated from the calling page without causing a reactive loop.
        Callers should always pair ``extra_layers`` with a real
        ``grd_file``: when ``grd_file.get()`` is ``None``, the map still
        renders ``extra_layers`` and fits bounds to them, but falls back
        to a minimal widget set (no basemap style, no layer-legend
        widget) — that state is only meant to be transient, not a
        supported box-only view.
    on_box_click
        Optional callback invoked with the clicked box id.
    """
    # Create MapWidget with the RESOLVED id (module namespace prefix).
    if MapWidget is None:
        return

    map_id = module.resolve_id("deckgl_map")
    _map = MapWidget(
        id=map_id,
        tooltip={"html": "{tooltip_html}"},
        picking_radius=5,
    )

    selected_node: reactive.Value[int | None] = reactive.value(None)
    selected_box: reactive.Value[int | None] = reactive.value(None)
    # The _fit_key the view was last fitted to. A plain cell, not a reactive
    # value: _update_map reads reactives and must not write one (self-write
    # loop). A palette, mode or partition change keeps the user's zoom.
    last_fit: list[tuple | None] = [None]

    @reactive.effect
    async def _set_basemap():
        """A basemap change restyles the map; it rebuilds no layers."""
        basemap_url = BASEMAPS.get(input.map_basemap(), BASEMAPS["positron"])
        await _map.set_style(session, basemap_url)

    @reactive.effect
    async def _update_map():
        """Rebuild layers and push to the map when inputs change."""
        grd = grd_file.get()
        if grd is None:
            last_fit[0] = None
            # Clear the map, but keep showing extra (e.g. box) layers if present.
            extra = list(extra_layers.get() or []) if extra_layers is not None else []
            await _map.update(
                session,
                layers=extra,
                widgets=[
                    zoom_widget(),
                    fullscreen_widget(placement="top-right"),
                ],
            )
            await _map.set_controls(session, [])
            if extra:
                bounds = _bounds_from_layers(extra)
                if bounds:
                    await _map.fit_bounds(
                        session,
                        bounds=bounds,
                        max_zoom=18,
                        duration=800,
                    )
            return

        mode = input.map_mode()
        colorscale = input.map_colors()

        # EPSG for coordinate reprojection:
        # 1. UI dropdown selection takes priority
        # 2. Fall back to grd.epsg (set by loader, e.g. sample data)
        # 3. None → auto-detect (works for Gauss-Boaga only)
        epsg_str = input.grid_epsg()
        epsg_val: int | None = int(epsg_str) if epsg_str else None
        if epsg_val is None and hasattr(grd, "epsg") and grd.epsg is not None:
            epsg_val = grd.epsg

        # Elevation scale — only read when mode is depth_3d
        elev_scale = 1.0
        if mode == "depth_3d":
            try:
                elev_scale = float(input.elevation_scale())
            except Exception:
                elev_scale = 10.0

        # Partition map
        pmap = None
        if partition_map is not None:
            pmap = partition_map.get()

        # If mode is "partitions" but there's a partition map, use it
        actual_mode = mode
        if pmap and mode == "mesh":
            actual_mode = "partitions"

        extra = list(extra_layers.get() or []) if extra_layers is not None else []

        # Every reactive read is above: the build runs in a thread, so a large
        # grid (seconds of work) never blocks the event loop.
        layers, vs = await asyncio.to_thread(
            _build_map, grd, actual_mode, colorscale, elev_scale, pmap, epsg_val, mode == "depth_3d"
        )
        layers = layers + extra

        # Re-centre (view state + fit) only for a new grid, EPSG or 2-D/3-D.
        key = _fit_key(grd, epsg_val, mode == "depth_3d")
        refit = _needs_refit(last_fit[0], key)
        last_fit[0] = key

        label_map = _build_label_map(layers, mode=actual_mode)
        await _map.update(
            session,
            layers=layers,
            view_state=vs if refit else None,
            transition_duration=500,
            widgets=[
                zoom_widget(),
                fullscreen_widget(placement="top-right"),
                screenshot_widget(placement="top-right"),
                layer_legend_widget(
                    auto_introspect=True,
                    show_checkbox=True,
                    label_map=label_map,
                    placement="bottom-right",
                    title="Layers",
                ),
            ],
        )

        bounds = vs.get("bounds")
        if refit and bounds:
            await _map.fit_bounds(
                session,
                bounds=bounds,
                max_zoom=18,
                duration=800,
            )

    # Handle click events — use bare ID; module input auto-namespaces.
    @reactive.effect
    def _handle_click():
        click_data = input["deckgl_map_click"]()
        if click_data is None:
            return
        obj = click_data.get("object") if isinstance(click_data, dict) else None
        # Box polygons (build_box_layers) are checked first and are
        # mutually exclusive with node clicks: a clicked object carries
        # either "box" (box layer) or "node_id" (node layer), never both.
        if obj and "box" in obj:
            bid = int(obj["box"])
            selected_box.set(bid)
            if on_box_click is not None:
                on_box_click(bid)
            return
        # Extract node_id from the clicked object
        if obj and "node_id" in obj:
            nid = int(obj["node_id"])
            selected_node.set(nid)
            if on_node_click is not None:
                on_node_click(nid)

    @render.ui
    def inspect_info():
        """Display selected node info as a badge."""
        nid = selected_node.get()
        if nid is None:
            return ui.div()
        grd = grd_file.get()
        if grd is None or nid not in grd.nodes:
            return ui.div()
        node = grd.nodes[nid]
        depth_str = f"{node.depth:.2f}" if node.depth is not None else "N/A"
        return ui.div(
            ui.span(
                f"Node {nid}",
                class_="badge bg-primary me-1",
            ),
            ui.span(
                f"({node.x:.6f}, {node.y:.6f})",
                class_="badge bg-secondary me-1",
            ),
            ui.span(
                f"Depth: {depth_str}",
                class_="badge bg-info",
            ),
            class_="mt-2",
        )

    return {"selected_node": selected_node, "selected_box": selected_box}
