"""Reusable UI components for SHYFEM UI.

Each component is a Shiny module with a ``_ui()`` function (returns UI elements)
and a ``_server()`` function (registers reactive logic).

Widgets:
    boundary_editor_ui / boundary_editor_server: CSV-based boundary condition editor.
    file_browser_ui / file_browser_server: File upload and path selection widget.
    file_picker_ui / file_picker_server: File picker dropdown with browse modal.
    grid_map_ui / grid_map_server: Interactive Plotly mesh map with zoom, pan, hover.
    job_status_ui / job_status_server: Job progress badges, duration, status formatting.
    log_viewer_ui / log_viewer_server: Real-time log output viewer with auto-scroll.
    str_editor_ui / str_editor_server: Rich STR parameter editor (split/form views).
    plot_widget_ui / plot_widget_server: General-purpose Plotly figure container.
    sample_data_card_ui / get_progressive_str_files: Sample data guidance card.
    timeseries_ui / timeseries_server: Interactive time series with statistics overlay.
"""

from shyfem_ui.components.boundary_editor import boundary_editor_server, boundary_editor_ui
from shyfem_ui.components.file_browser import file_browser_server, file_browser_ui
from shyfem_ui.components.file_picker import file_picker_server, file_picker_ui
from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
from shyfem_ui.components.job_status import job_status_server, job_status_ui
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.plot_widget import plot_widget_server, plot_widget_ui
from shyfem_ui.components.sample_data import get_progressive_str_files, sample_data_card_ui
from shyfem_ui.components.str_editor import str_editor_server, str_editor_ui
from shyfem_ui.components.timeseries import timeseries_server, timeseries_ui

__all__ = [
    "boundary_editor_ui",
    "boundary_editor_server",
    "file_browser_ui",
    "file_browser_server",
    "file_picker_ui",
    "file_picker_server",
    "grid_map_ui",
    "grid_map_server",
    "job_status_ui",
    "job_status_server",
    "log_viewer_ui",
    "log_viewer_server",
    "str_editor_ui",
    "str_editor_server",
    "plot_widget_ui",
    "plot_widget_server",
    "sample_data_card_ui",
    "get_progressive_str_files",
    "timeseries_ui",
    "timeseries_server",
]
