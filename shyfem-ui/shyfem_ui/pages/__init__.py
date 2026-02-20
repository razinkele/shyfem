"""UI pages for SHYFEM UI application.

Page modules are lazy-loaded on first access to avoid importing heavy
dependencies (plotly, numpy, shinywidgets) at startup.
"""

import importlib

__all__ = [
    "home",
    "grid_prep",
    "partitioning",
    "simulation",
    "run",
    "postprocess",
    "visualize",
    "compare",
    "ensemble",
    "tutorial",
    "files",
]

_modules: dict = {}


def __getattr__(name: str):
    if name in __all__:
        if name not in _modules:
            _modules[name] = importlib.import_module(f"shyfem_ui.pages.{name}")
        return _modules[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
