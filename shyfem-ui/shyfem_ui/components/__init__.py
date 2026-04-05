"""Reusable UI components for SHYFEM UI.

Each component is a Shiny module with a ``_ui()`` function (returns UI elements)
and a ``_server()`` function (registers reactive logic).

Widgets:
    boundary_editor_ui / boundary_editor_server: CSV-based boundary condition editor.
    file_browser_ui / file_browser_server: File upload and path selection widget.
    file_picker_ui / file_picker_server: File picker dropdown with browse modal.
    grid_map_ui / grid_map_server: Interactive deck.gl mesh map with zoom, pan, hover.
    job_status_ui / job_status_server: Job progress badges, duration, status formatting.
    log_viewer_ui / log_viewer_server: Real-time log output viewer with auto-scroll.
    str_editor_ui / str_editor_server: Rich STR parameter editor (split/form views).
    plot_widget_ui / plot_widget_server: General-purpose Plotly figure container.
    sample_data_card_ui / get_progressive_str_files: Sample data guidance card.
    timeseries_ui / timeseries_server: Interactive time series with statistics overlay.
"""

import importlib

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

_MAPPING = {
    "boundary_editor_ui": "boundary_editor",
    "boundary_editor_server": "boundary_editor",
    "file_browser_ui": "file_browser",
    "file_browser_server": "file_browser",
    "file_picker_ui": "file_picker",
    "file_picker_server": "file_picker",
    "grid_map_ui": "grid_map",
    "grid_map_server": "grid_map",
    "job_status_ui": "job_status",
    "job_status_server": "job_status",
    "log_viewer_ui": "log_viewer",
    "log_viewer_server": "log_viewer",
    "str_editor_ui": "str_editor",
    "str_editor_server": "str_editor",
    "plot_widget_ui": "plot_widget",
    "plot_widget_server": "plot_widget",
    "sample_data_card_ui": "sample_data",
    "get_progressive_str_files": "sample_data",
    "timeseries_ui": "timeseries",
    "timeseries_server": "timeseries",
}

def __getattr__(name):
    if name in _MAPPING:
        mod = importlib.import_module(f".{_MAPPING[name]}", __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
