"""Layer building for the results map: mesh geometry, node colours, legend
and current arrows. Pure functions (numpy in, deck.gl layer dicts out); no
Shiny and no file access."""

from __future__ import annotations

import html
import math

import numpy as np
from shiny_deckgl import (
    custom_geometry,
    encode_binary_attribute,
    path_layer,
    simple_mesh_layer,
)

from shyfem_ui.components.grid_map import PALETTES

RESULTS_LAYER_ID = "results-mesh"
ARROWS_LAYER_ID = "results-arrows"

_M_PER_DEG_LON = 111_320.0  # times cos(lat)
_M_PER_DEG_LAT = 110_540.0
_NAN_GREY = (0.78, 0.78, 0.78)
_ARROW_FRACTION = 0.03  # default arrow length: share of the mesh extent
_BARB_FRACTION = 0.3  # barb length relative to the shaft
_BARB_ANGLE = math.radians(25.0)


class NeedsProjection(ValueError):
    """The mesh is in projected coordinates and no EPSG code was given."""


def is_geographic(rf) -> bool:
    """True when every node lies within |x| <= 180, |y| <= 90 (lon/lat)."""
    x = np.asarray(rf.node_x, dtype=np.float64)
    y = np.asarray(rf.node_y, dtype=np.float64)
    return bool(np.all(np.abs(x) <= 180) and np.all(np.abs(y) <= 90))


def mesh_lonlat(rf, epsg: int | None) -> np.ndarray:
    """``(n_node, 2)`` lon/lat of the mesh nodes.

    Coordinates that all fall within |x| <= 180, |y| <= 90 are lon/lat;
    anything else is projected and needs ``epsg``.
    """
    x = np.asarray(rf.node_x, dtype=np.float64)
    y = np.asarray(rf.node_y, dtype=np.float64)
    if is_geographic(rf):
        return np.column_stack([x, y])
    if epsg is None:
        raise NeedsProjection("Choose the mesh projection (EPSG) to place it on the map")
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(int(epsg), 4326, always_xy=True).transform(x, y)
    lon, lat = np.asarray(lon), np.asarray(lat)
    if not (
        np.all(np.isfinite(lon))
        and np.all(np.isfinite(lat))
        and np.all(np.abs(lon) <= 180)
        and np.all(np.abs(lat) <= 90)
    ):
        raise NeedsProjection(
            "The chosen projection does not place the mesh on Earth; choose another EPSG"
        )
    return np.column_stack([lon, lat])


def _centre(lonlat: np.ndarray) -> tuple[float, float]:
    return (
        float((lonlat[:, 0].min() + lonlat[:, 0].max()) / 2),
        float((lonlat[:, 1].min() + lonlat[:, 1].max()) / 2),
    )


def mesh_geometry(lonlat: np.ndarray, faces: np.ndarray) -> dict:
    """Indexed mesh (one vertex per node) in metres from the mesh centre."""
    ctr_lon, ctr_lat = _centre(lonlat)
    m_lon = _M_PER_DEG_LON * math.cos(math.radians(ctr_lat))
    n = len(lonlat)
    positions = np.zeros((n, 3), dtype=np.float32)
    positions[:, 0] = (lonlat[:, 0] - ctr_lon) * m_lon
    positions[:, 1] = (lonlat[:, 1] - ctr_lat) * _M_PER_DEG_LAT
    normals = np.zeros((n, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    return {
        "positions": positions,
        "normals": normals,
        "indices": np.ascontiguousarray(faces, dtype=np.uint32).ravel(),
        "center": [ctr_lon, ctr_lat],
    }


def _stops(palette: str) -> np.ndarray:
    return np.asarray(PALETTES[palette], dtype=np.float64)[:, :3] / 255.0


def node_colors(values: np.ndarray, vmin: float, vmax: float, palette: str) -> np.ndarray:
    """Per-node RGB (float32, 0-1); NaN nodes are grey."""
    vals = np.asarray(values, dtype=np.float64)
    stops = _stops(palette)
    if np.isfinite(vmin) and np.isfinite(vmax) and vmax > vmin:
        t = np.clip((vals - vmin) / (vmax - vmin), 0.0, 1.0)
    else:
        t = np.full(vals.shape, 0.5)
    grid = np.linspace(0.0, 1.0, len(stops))
    out = np.empty((len(vals), 3), dtype=np.float32)
    for ch in range(3):
        out[:, ch] = np.interp(np.nan_to_num(t, nan=0.0), grid, stops[:, ch])
    out[np.isnan(vals)] = _NAN_GREY
    return out


def mesh_layer(geometry: dict, colors: np.ndarray) -> dict:
    """The full mesh layer (geometry and colours), for a layer ``update``."""
    return simple_mesh_layer(
        RESULTS_LAYER_ID,
        **custom_geometry({**geometry, "colors": colors}),
        pickable=False,
    )


def color_patch(colors: np.ndarray) -> dict:
    """Per-frame ``patch_layer`` payload: new colours, cached geometry kept."""
    return {"_meshColors": encode_binary_attribute(np.asarray(colors).astype(np.float32))}


def arrow_paths(
    lonlat: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    *,
    speed_max: float,
    max_arrows: int = 400,
    length_m: float | None = None,
) -> list[dict]:
    """Thinned current arrows as polylines (shaft plus two barbs).

    Length is ``length_m * speed / speed_max`` so a fixed ``speed_max`` keeps
    the scale steady between frames.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    speed = np.hypot(u, v)
    ok = np.isfinite(speed) & (speed > 0)
    if not ok.any() or not speed_max > 0:
        return []

    lon, lat = lonlat[:, 0], lonlat[:, 1]
    lon0, lon1, lat0, lat1 = lon.min(), lon.max(), lat.min(), lat.max()
    mid_lat = (lat0 + lat1) / 2
    if length_m is None:
        width = (lon1 - lon0) * _M_PER_DEG_LON * math.cos(math.radians(mid_lat))
        height = (lat1 - lat0) * _M_PER_DEG_LAT
        length_m = _ARROW_FRACTION * max(width, height)

    # first valid node per cell of an n x n grid over the mesh bounds
    n = max(1, int(math.isqrt(max(1, max_arrows))))
    cx = np.minimum(((lon - lon0) / max(lon1 - lon0, 1e-12) * n).astype(int), n - 1)
    cy = np.minimum(((lat - lat0) / max(lat1 - lat0, 1e-12) * n).astype(int), n - 1)
    idx = np.flatnonzero(ok)
    _, first = np.unique((cy * n + cx)[idx], return_index=True)
    chosen = idx[np.sort(first)]

    paths: list[dict] = []
    for i in chosen:
        sp = speed[i]
        length = length_m * sp / speed_max
        ux, uy = u[i] / sp, v[i] / sp  # unit direction (east, north)
        m_lon = _M_PER_DEG_LON * math.cos(math.radians(lat[i]))

        def pt(dx: float, dy: float, *, lo=lon[i], la=lat[i], m=m_lon) -> list[float]:
            return [float(lo + dx / m), float(la + dy / _M_PER_DEG_LAT)]

        tip = (ux * length, uy * length)
        barbs = []
        for sign in (1, -1):
            c, s = math.cos(sign * _BARB_ANGLE), math.sin(sign * _BARB_ANGLE)
            bx, by = -ux * c + uy * s, -uy * c - ux * s  # back along the shaft, rotated
            barbs.append(
                pt(tip[0] + bx * length * _BARB_FRACTION, tip[1] + by * length * _BARB_FRACTION)
            )
        tip_pt = pt(*tip)
        paths.append({"path": [pt(0.0, 0.0), tip_pt, barbs[0], tip_pt, barbs[1]]})
    return paths


def arrows_layer(paths: list[dict]) -> dict:
    return path_layer(
        ARROWS_LAYER_ID,
        paths,
        getPath="@@d.path",
        getColor=[20, 20, 20, 200],
        widthMinPixels=1,
        pickable=False,
    )


def legend_html(palette: str, vmin: float, vmax: float, units: str, label: str) -> str:
    """A small colour bar with the range end-points and units."""
    stops = ", ".join(
        f"rgb({int(round(r))},{int(round(g))},{int(round(b))})" for r, g, b in _stops(palette) * 255
    )
    lo, hi = f"{vmin:.4g}", f"{vmax:.4g}"
    return (
        '<div class="results-legend" style="font-size:12px;min-width:140px">'
        f'<div style="font-weight:600">{html.escape(label)}'
        f" ({html.escape(units)})</div>"
        f'<div style="height:10px;border-radius:2px;'
        f'background:linear-gradient(to right, {stops})"></div>'
        '<div style="display:flex;justify-content:space-between">'
        f"<span>{html.escape(lo)}</span><span>{html.escape(hi)}</span></div></div>"
    )
