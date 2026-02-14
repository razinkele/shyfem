"""SQLAlchemy database models for SHYFEM UI.

Models:
    Project: A named project with work directory, containing grids and simulations.
    Grid: A computational grid (.grd/.bas files) with node/element statistics.
    Simulation: A simulation configuration (.str file) with MPI settings.
    Job: A tracked execution of a SHYFEM tool with status, progress, and output.
"""

from shyfem_ui.models.project import Grid, Job, Project, Simulation

__all__ = ["Project", "Grid", "Simulation", "Job"]
