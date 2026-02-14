"""Plot widget component for displaying grid and simulation results."""

from collections.abc import Callable

import matplotlib

matplotlib.use("Agg")  # Use non-interactive backend

import matplotlib.pyplot as plt
import numpy as np
from shiny import module, reactive, render, ui

from shyfem_ui.services.parser_grd import GrdFile


@module.ui
def plot_widget_ui(height: str = "500px"):
    """Plot widget component UI.

    Args:
        height: CSS height for the plot container
    """
    return ui.div(
        # Controls
        ui.div(
            ui.input_select(
                "plot_type",
                "Plot Type",
                choices={
                    "mesh": "Mesh View",
                    "depth": "Depth Contour",
                    "boundaries": "Boundaries",
                    "quality": "Element Quality",
                },
                width="150px",
            ),
            ui.input_checkbox("show_nodes", "Show Nodes", value=False),
            ui.input_checkbox("show_labels", "Show Labels", value=False),
            ui.input_action_button(
                "export_btn",
                "Export PNG",
                class_="btn-sm btn-outline-secondary ms-2",
            ),
            class_="d-flex align-items-center gap-3 mb-2",
        ),
        # Plot area
        ui.div(
            ui.output_plot("main_plot", height=height),
            class_="plot-widget-area border rounded",
        ),
        # Statistics
        ui.output_ui("plot_stats"),
        class_="plot-widget-component",
    )


@module.server
def plot_widget_server(
    input,
    output,
    session,
    grd_file: reactive.Value[GrdFile | None],
    on_export: Callable[[plt.Figure], None] | None = None,
):
    """Plot widget component server logic.

    Args:
        grd_file: Reactive value containing the grid file data
        on_export: Callback when export is requested
    """

    @render.plot
    def main_plot():
        grd = grd_file.get()
        if grd is None or not grd.nodes:
            fig, ax = plt.subplots(figsize=(10, 8))
            ax.text(
                0.5, 0.5, "No grid data loaded",
                ha="center", va="center", fontsize=14, color="gray"
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig

        plot_type = input.plot_type()
        show_nodes = input.show_nodes()
        show_labels = input.show_labels()

        if plot_type == "mesh":
            return plot_mesh(grd, show_nodes, show_labels)
        elif plot_type == "depth":
            return plot_depth_contour(grd, show_nodes)
        elif plot_type == "boundaries":
            return plot_boundaries(grd, show_nodes)
        elif plot_type == "quality":
            return plot_element_quality(grd)
        else:
            return plot_mesh(grd, show_nodes, show_labels)

    @render.ui
    def plot_stats():
        grd = grd_file.get()
        if grd is None:
            return None

        depth_range = grd.get_depth_range()

        stats = [
            f"Nodes: {grd.num_nodes:,}",
            f"Elements: {grd.num_elements:,}",
            f"Triangles: {grd.num_triangles:,}",
            f"Quads: {grd.num_quads:,}",
            f"Lines: {grd.num_lines:,}",
        ]

        if depth_range[0] is not None:
            stats.append(f"Depth: {depth_range[0]:.1f} to {depth_range[1]:.1f}")

        return ui.div(
            *[ui.span(s, class_="badge bg-secondary me-2") for s in stats],
            class_="mt-2",
        )

    @reactive.effect
    @reactive.event(input.export_btn)
    def _handle_export():
        grd = grd_file.get()
        if grd and on_export:
            fig = plot_mesh(grd, input.show_nodes(), input.show_labels())
            on_export(fig)

    return {}


def plot_mesh(
    grd: GrdFile,
    show_nodes: bool = False,
    show_labels: bool = False,
) -> plt.Figure:
    """Plot the mesh structure."""
    fig, ax = plt.subplots(figsize=(10, 8))

    # Get node coordinates
    node_ids = list(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    # Plot elements
    for elem in grd.elements.values():
        try:
            indices = [node_map[nid] for nid in elem.nodes if nid in node_map]
            if len(indices) < 3:
                continue
            # Close the polygon
            indices.append(indices[0])
            ex = x[indices]
            ey = y[indices]
            ax.plot(ex, ey, "b-", linewidth=0.5, alpha=0.7)
        except (KeyError, IndexError):
            continue

    # Plot nodes
    if show_nodes:
        ax.scatter(x, y, s=2, c="red", zorder=5)

    # Plot labels
    if show_labels and len(node_ids) < 500:
        for nid in node_ids:
            node = grd.nodes[nid]
            ax.annotate(
                str(nid), (node.x, node.y),
                fontsize=6, alpha=0.7
            )

    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title(f"Mesh: {grd.num_nodes:,} nodes, {grd.num_elements:,} elements")

    fig.tight_layout()
    return fig


def plot_depth_contour(grd: GrdFile, show_nodes: bool = False) -> plt.Figure:
    """Plot depth as a filled contour."""
    fig, ax = plt.subplots(figsize=(10, 8))

    # Get node coordinates and depths
    node_ids = list(grd.nodes.keys())
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])
    depths = np.array([
        grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0
        for nid in node_ids
    ])

    if np.all(depths == 0):
        ax.text(
            0.5, 0.5, "No depth data available",
            ha="center", va="center", fontsize=14, color="gray",
            transform=ax.transAxes
        )
    else:
        # Use tricontourf for triangulated data
        from matplotlib.tri import Triangulation

        # Build triangulation from elements
        triangles = []
        node_map = {nid: i for i, nid in enumerate(node_ids)}

        for elem in grd.elements.values():
            if elem.is_triangle:
                try:
                    tri = [node_map[nid] for nid in elem.nodes]
                    triangles.append(tri)
                except KeyError:
                    continue

        if triangles:
            tri = Triangulation(x, y, triangles)
            contour = ax.tricontourf(tri, depths, levels=20, cmap="viridis")
            fig.colorbar(contour, ax=ax, label="Depth")
        else:
            # Fallback to scatter
            scatter = ax.scatter(x, y, c=depths, s=5, cmap="viridis")
            fig.colorbar(scatter, ax=ax, label="Depth")

    if show_nodes:
        ax.scatter(x, y, s=2, c="white", edgecolors="black", linewidths=0.5, zorder=5)

    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title("Depth Contour")

    fig.tight_layout()
    return fig


def plot_boundaries(grd: GrdFile, show_nodes: bool = False) -> plt.Figure:
    """Plot boundary lines with different colors for each type."""
    fig, ax = plt.subplots(figsize=(10, 8))

    # Get node coordinates
    node_ids = list(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    # Plot elements as background
    for elem in grd.elements.values():
        try:
            indices = [node_map[nid] for nid in elem.nodes if nid in node_map]
            if len(indices) < 3:
                continue
            indices.append(indices[0])
            ex = x[indices]
            ey = y[indices]
            ax.plot(ex, ey, "lightgray", linewidth=0.3, alpha=0.5)
        except (KeyError, IndexError):
            continue

    # Plot boundaries with colors
    line_types = grd.get_line_types()
    colors = plt.cm.Set1(np.linspace(0, 1, max(len(line_types), 1)))
    type_color_map = {lt: colors[i % len(colors)] for i, lt in enumerate(sorted(line_types))}

    for line in grd.lines.values():
        try:
            indices = [node_map[nid] for nid in line.nodes if nid in node_map]
            if len(indices) < 2:
                continue
            lx = x[indices]
            ly = y[indices]
            color = type_color_map.get(line.line_type, "blue")
            ax.plot(lx, ly, color=color, linewidth=2, label=f"Type {line.line_type}")
        except (KeyError, IndexError):
            continue

    # Add legend (deduplicated)
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    ax.legend(by_label.values(), by_label.keys(), loc="upper right")

    if show_nodes:
        ax.scatter(x, y, s=2, c="red", zorder=5)

    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title(f"Boundaries: {grd.num_lines:,} lines")

    fig.tight_layout()
    return fig


def plot_element_quality(grd: GrdFile) -> plt.Figure:
    """Plot element quality metrics."""
    fig, ax = plt.subplots(figsize=(10, 8))

    # Get node coordinates
    node_ids = list(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    # Calculate element qualities (aspect ratio for triangles)
    qualities = []
    centroids = []

    for elem in grd.elements.values():
        if not elem.is_triangle:
            continue

        try:
            indices = [node_map[nid] for nid in elem.nodes]
            ex = x[indices]
            ey = y[indices]

            # Calculate aspect ratio
            sides = []
            for i in range(3):
                j = (i + 1) % 3
                side_len = np.sqrt((ex[j] - ex[i])**2 + (ey[j] - ey[i])**2)
                sides.append(side_len)

            # Quality: ratio of smallest to largest side
            quality = min(sides) / max(sides) if max(sides) > 0 else 0
            qualities.append(quality)

            centroid_x = np.mean(ex)
            centroid_y = np.mean(ey)
            centroids.append((centroid_x, centroid_y))

        except (KeyError, IndexError):
            continue

    if qualities:
        centroids = np.array(centroids)
        scatter = ax.scatter(
            centroids[:, 0], centroids[:, 1],
            c=qualities, s=10, cmap="RdYlGn", vmin=0, vmax=1
        )
        fig.colorbar(scatter, ax=ax, label="Element Quality (0-1)")

    ax.set_aspect("equal")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_title(f"Element Quality ({len(qualities):,} triangles)")

    fig.tight_layout()
    return fig
