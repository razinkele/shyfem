"""SHYFEM UI - Python Shiny web interface for SHYFEM hydrodynamic simulation."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the version declared in pyproject.toml, read from
    # the installed package metadata. Avoids a second hardcoded version string
    # here drifting out of sync with pyproject (run `pip install -e .` to refresh
    # after a bump).
    __version__ = version("shyfem-ui")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
