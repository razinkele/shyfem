"""Interactive grid map component using Plotly.

Provides zoomable/pannable mesh visualization with:
- Mesh wireframe and depth coloring
- Clickable nodes with info display
- Boundary line highlighting
- Partition overlay coloring
- Element quality heatmap
"""

from typing import Callable, Optional

import numpy as np
import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.services.parser_grd import GrdFile

# Color palette for partition coloring (20 distinct colors)
PARTITION_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]


def _build_edge_arrays(grd: GrdFile):
    """Build coordinate arrays for mesh edges and nodes.

    Returns (edge_x, edge_y, x, y, node_ids, node_map) where edge
    arrays use None separators between segments for efficient Plotly
    rendering as a single trace.
    """
    node_ids = sorted(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    edge_x, edge_y = [], []
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
    partition_map: Optional[dict[int, int]] = None,
) -> go.Figure:
    """Build a Plotly figure for grid visualization.

    Args:
        grd: Parsed grid file
        mode: View mode - "mesh", "depth", "boundaries", "quality", "partitions"
        colorscale: Plotly colorscale name for depth/quality coloring
        show_boundaries: Overlay boundary lines on the mesh
        show_nodes: Show clickable node markers
        partition_map: Element ID -> partition index mapping (for partition mode)
    """
    if not grd.nodes:
        fig = go.Figure()
        fig.add_annotation(
            text="No grid data loaded",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font_size=18, font_color="gray",
        )
        fig.update_layout(height=600)
        return fig

    edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)

    fig = go.Figure()

    if mode == "mesh":
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="#4a90d9", width=0.5),
            hoverinfo="skip",
            name="Mesh",
        ))

    elif mode == "depth":
        # Light mesh wireframe background
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="rgba(200,200,200,0.3)", width=0.3),
            hoverinfo="skip",
            showlegend=False,
        ))
        depths = np.array([
            grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0
            for nid in node_ids
        ])
        if not np.all(depths == 0):
            hover = [
                f"Node {nid}<br>Depth: {grd.nodes[nid].depth:.2f}"
                if grd.nodes[nid].depth is not None
                else f"Node {nid}<br>No depth"
                for nid in node_ids
            ]
            fig.add_trace(go.Scattergl(
                x=x.tolist(), y=y.tolist(),
                mode="markers",
                marker=dict(
                    size=4,
                    color=depths.tolist(),
                    colorscale=colorscale,
                    colorbar=dict(title="Depth", thickness=15),
                    showscale=True,
                ),
                text=hover,
                hoverinfo="text",
                name="Depth",
            ))
        else:
            fig.add_annotation(
                text="No depth data available",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font_size=14, font_color="gray",
            )

    elif mode == "quality":
        # Light mesh background
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="rgba(200,200,200,0.3)", width=0.3),
            hoverinfo="skip",
            showlegend=False,
        ))
        qualities, cx_arr, cy_arr, hover_text = [], [], [], []
        for elem in grd.elements.values():
            if not elem.is_triangle:
                continue
            indices = [node_map.get(nid) for nid in elem.nodes]
            if any(i is None for i in indices):
                continue
            ex = x[indices]
            ey = y[indices]
            sides = [
                np.sqrt((ex[(i + 1) % 3] - ex[i]) ** 2 + (ey[(i + 1) % 3] - ey[i]) ** 2)
                for i in range(3)
            ]
            q = min(sides) / max(sides) if max(sides) > 0 else 0
            qualities.append(q)
            cx_arr.append(float(np.mean(ex)))
            cy_arr.append(float(np.mean(ey)))
            hover_text.append(f"Elem {elem.id}<br>Quality: {q:.3f}")

        if qualities:
            fig.add_trace(go.Scattergl(
                x=cx_arr, y=cy_arr,
                mode="markers",
                marker=dict(
                    size=5,
                    color=qualities,
                    colorscale="RdYlGn",
                    cmin=0, cmax=1,
                    colorbar=dict(title="Quality", thickness=15),
                    showscale=True,
                ),
                text=hover_text,
                hoverinfo="text",
                name="Quality",
            ))

    elif mode == "boundaries":
        # Light mesh background
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="rgba(200,200,200,0.4)", width=0.3),
            hoverinfo="skip",
            showlegend=False,
        ))
        # Boundary lines are added below via the show_boundaries block,
        # but force it on for this mode
        show_boundaries = True

    elif mode == "partitions" and partition_map:
        num_parts = max(partition_map.values()) + 1 if partition_map else 1
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
            color = PARTITION_COLORS[p % len(PARTITION_COLORS)]
            if part_edges[p][0]:
                fig.add_trace(go.Scattergl(
                    x=part_edges[p][0], y=part_edges[p][1],
                    mode="lines",
                    line=dict(color=color, width=0.7),
                    hoverinfo="skip",
                    name=f"P{p}",
                ))

    else:
        # Fallback: mesh wireframe
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="#4a90d9", width=0.5),
            hoverinfo="skip",
            name="Mesh",
        ))

    # Overlay boundary lines
    if show_boundaries and grd.lines:
        boundary_colors = ["#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c",
                           "#e67e22", "#3498db", "#e91e63"]
        line_types = sorted(grd.get_line_types())
        for lt_idx, lt in enumerate(line_types):
            bx, by, hover = [], [], []
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
                color = boundary_colors[lt_idx % len(boundary_colors)]
                fig.add_trace(go.Scattergl(
                    x=bx, y=by,
                    mode="lines",
                    line=dict(color=color, width=3),
                    hoverinfo="skip",
                    name=f"Boundary type {lt}",
                ))

    # Overlay clickable node markers
    if show_nodes:
        hover_text = []
        for nid in node_ids:
            n = grd.nodes[nid]
            parts = [f"Node {nid}", f"x: {n.x:.4f}", f"y: {n.y:.4f}"]
            if n.depth is not None:
                parts.append(f"depth: {n.depth:.2f}")
            parts.append(f"type: {n.node_type}")
            hover_text.append("<br>".join(parts))
        fig.add_trace(go.Scattergl(
            x=x.tolist(), y=y.tolist(),
            mode="markers",
            marker=dict(size=3, color="red"),
            text=hover_text,
            hoverinfo="text",
            name="Nodes",
        ))

    # Layout
    title_parts = [f"{grd.num_nodes:,} nodes", f"{grd.num_elements:,} elements"]
    if grd.num_lines > 0:
        title_parts.append(f"{grd.num_lines:,} boundary lines")

    fig.update_layout(
        xaxis=dict(scaleanchor="y", scaleratio=1, title="X"),
        yaxis=dict(title="Y"),
        title=", ".join(title_parts),
        hovermode="closest",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=50, r=20, t=60, b=50),
        height=600,
        dragmode="pan",
    )

    return fig


@module.ui
def grid_map_ui(height: str = "600px"):
    """Interactive grid map component UI."""
    return ui.div(
        # Controls row
        ui.div(
            ui.div(
                ui.tags.label("View", class_="form-label small mb-0"),
                ui.input_select(
                    "map_mode", None,
                    choices={
                        "mesh": "Mesh",
                        "depth": "Depth",
                        "boundaries": "Boundaries",
                        "quality": "Quality",
                    },
                    width="120px",
                ),
                class_="me-2",
            ),
            ui.div(
                ui.tags.label("Colors", class_="form-label small mb-0"),
                ui.input_select(
                    "colorscale", None,
                    choices={
                        "Viridis": "Viridis",
                        "Plasma": "Plasma",
                        "Inferno": "Inferno",
                        "Cividis": "Cividis",
                        "RdBu": "Red-Blue",
                        "Jet": "Jet",
                    },
                    width="100px",
                ),
                class_="me-3",
            ),
            ui.input_checkbox("show_boundaries", "Boundaries", value=True),
            ui.input_checkbox("show_nodes", "Nodes", value=False),
            class_="d-flex align-items-end gap-2 mb-2",
        ),
        # Interactive Plotly figure
        output_widget("grid_plot"),
        # Node/element inspection panel
        ui.output_ui("inspect_info"),
        class_="grid-map-component",
    )


@module.server
def grid_map_server(
    input,
    output,
    session,
    grd_file: reactive.Value[Optional[GrdFile]],
    partition_map: Optional[reactive.Value[Optional[dict[int, int]]]] = None,
    on_node_click: Optional[Callable[[int], None]] = None,
):
    """Interactive grid map server logic.

    Args:
        grd_file: Reactive GrdFile to visualize
        partition_map: Optional reactive element-ID-to-partition mapping
        on_node_click: Callback when a node is clicked
    """
    selected_node = reactive.value(None)

    @render_widget
    def grid_plot():
        grd = grd_file.get()
        if grd is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Load a grid file to visualize",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font_size=16, font_color="gray",
            )
            fig.update_layout(height=600)
            return fig

        mode = input.map_mode()
        colorscale = input.colorscale()
        show_bounds = input.show_boundaries()
        show_nd = input.show_nodes()

        pmap = None
        if partition_map is not None:
            pmap = partition_map.get()
            if pmap and mode == "mesh":
                mode = "partitions"

        return build_mesh_figure(
            grd,
            mode=mode,
            colorscale=colorscale,
            show_boundaries=show_bounds,
            show_nodes=show_nd,
            partition_map=pmap,
        )

    @render.ui
    def inspect_info():
        nid = selected_node.get()
        if nid is None:
            return None
        grd = grd_file.get()
        if grd is None or nid not in grd.nodes:
            return None
        n = grd.nodes[nid]
        items = [f"Node: {nid}", f"X: {n.x:.6f}", f"Y: {n.y:.6f}"]
        if n.depth is not None:
            items.append(f"Depth: {n.depth:.4f}")
        items.append(f"Type: {n.node_type}")
        return ui.div(
            *[ui.span(s, class_="badge bg-info me-1") for s in items],
            class_="mt-2 p-2 bg-light border rounded small",
        )

    return {
        "selected_node": selected_node,
    }
