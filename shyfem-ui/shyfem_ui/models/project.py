"""Database models for projects, grids, simulations, and jobs."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shyfem_ui.db.base import Base
from shyfem_ui.services.job_queue import JobStatus


class Project(Base):
    """A SHYFEM project containing grids and simulations."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    work_dir: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    grids: Mapped[list["Grid"]] = relationship(
        "Grid", back_populates="project", cascade="all, delete-orphan"
    )
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def work_path(self) -> Path:
        """Return work_dir as a Path object."""
        return Path(self.work_dir)

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}')>"


class Grid(Base):
    """A computational grid (.grd/.bas files)."""

    __tablename__ = "grids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # File paths (relative to project work_dir)
    grd_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    bas_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Grid statistics
    num_nodes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    num_elements: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    num_layers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="grids")
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="grid"
    )

    def __repr__(self) -> str:
        return f"<Grid(id={self.id}, name='{self.name}', nodes={self.num_nodes})>"


class Simulation(Base):
    """A SHYFEM simulation configuration and results."""

    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    grid_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("grids.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Configuration files (relative to project work_dir)
    str_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    output_dir: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Simulation parameters (cached from .str file)
    start_time: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    end_time: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    time_step: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # MPI configuration
    mpi_enabled: Mapped[bool] = mapped_column(Integer, default=False)
    mpi_np: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="simulations")
    grid: Mapped[Optional["Grid"]] = relationship("Grid", back_populates="simulations")
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="simulation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Simulation(id={self.id}, name='{self.name}')>"


class Job(Base):
    """A job representing execution of a SHYFEM tool."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_simulation_id", "simulation_id"),
        Index("ix_jobs_job_uuid", "job_uuid", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True
    )  # UUID string from JobQueue
    simulation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("simulations.id"), nullable=True
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Shiny session ID for multi-user filtering

    # Job identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # shypre, shybas, shyparts, shyfem, shyelab, shyplot

    # Command execution
    command: Mapped[str] = mapped_column(Text, nullable=False, default="")
    working_dir: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Status tracking
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.PENDING, nullable=False
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_message: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Output
    stdout_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    stderr_file: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    return_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Celery task ID (server mode)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    simulation: Mapped[Optional["Simulation"]] = relationship(
        "Simulation", back_populates="jobs"
    )

    @property
    def duration(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_active(self) -> bool:
        """Check if job is currently active (pending, queued, or running)."""
        return self.status in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, name='{self.name}', status={self.status.value})>"
