"""Configuration management using Pydantic settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration with environment variable support.

    All settings can be overridden via environment variables with SHYFEM_UI_ prefix.
    Example: SHYFEM_UI_DEPLOYMENT_MODE=server
    """

    model_config = SettingsConfigDict(
        env_prefix="SHYFEM_UI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Deployment settings
    deployment_mode: Literal["local", "server"] = Field(
        default="local",
        description="Deployment mode: 'local' for desktop, 'server' for multi-user"
    )
    host: str = Field(default="127.0.0.1", description="Host to bind to")
    port: int = Field(default=8000, description="Port to bind to")

    # SHYFEM paths
    shyfem_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2],
        description="Path to SHYFEM installation directory"
    )
    work_dir: Path = Field(
        default=Path.home() / ".shyfem-ui" / "projects",
        description="Working directory for projects and outputs"
    )

    # Database settings
    database_url: str = Field(
        default="sqlite:///./shyfem_ui.db",
        description="SQLAlchemy database URL"
    )

    # Job queue settings
    use_celery: bool = Field(
        default=False,
        description="Use Celery/Redis for job queue (server mode)"
    )
    max_workers: int = Field(
        default=4,
        description="Maximum concurrent jobs (local mode)"
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for Celery broker"
    )

    # MPI settings
    mpi_enabled: bool = Field(default=True, description="Enable MPI support")
    mpi_default_np: int = Field(default=4, description="Default MPI processes")
    mpirun_path: str = Field(default="mpirun", description="Path to mpirun executable")

    # Authentication (server mode only)
    auth_enabled: bool = Field(
        default=False,
        description="Enable basic auth (recommended for server mode)"
    )
    auth_username: str = Field(default="admin", description="Basic auth username")
    auth_password: str = Field(default="", description="Basic auth password (required if auth_enabled)")

    # Debug settings
    debug: bool = Field(
        default=False,
        description="Enable debug mode (verbose WebSocket logging, etc.)"
    )

    # UI settings
    theme: str = Field(default="flatly", description="Shinyswatch theme name")
    log_refresh_interval: int = Field(
        default=5,
        description="Log viewer refresh interval in seconds"
    )

    @field_validator("shyfem_dir", "work_dir", mode="before")
    @classmethod
    def resolve_path(cls, v):
        """Convert string paths to Path objects and resolve."""
        if isinstance(v, str):
            v = Path(v)
        return v.expanduser().resolve()

    @property
    def bin_dir(self) -> Path:
        """Path to SHYFEM binaries."""
        return self.shyfem_dir / "bin"

    @property
    def testcases_dir(self) -> Path:
        """Path to SHYFEM testcases/examples."""
        return self.shyfem_dir / "testcases" / "examples"

    def get_executable(self, name: str) -> Path:
        """Get full path to a SHYFEM executable."""
        exe = self.bin_dir / name
        if not exe.exists():
            # Try without bin/ (some may be in different locations)
            alt = self.shyfem_dir / name
            if alt.exists():
                return alt
        return exe

    def ensure_work_dir(self) -> Path:
        """Ensure working directory exists and return it."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return self.work_dir

    # Rate limiting (requests per minute per session, server mode)
    rate_limit_rpm: int = Field(
        default=120,
        description="Max requests per minute per session (server mode)"
    )

    # Upload limits
    max_upload_size_mb: int = Field(
        default=500,
        description="Maximum file upload size in MB"
    )

    # Proxy settings (server mode)
    trusted_proxies: list[str] = Field(
        default_factory=list,
        description="Trusted proxy CIDR ranges for X-Forwarded-For (e.g., ['127.0.0.1/8', '10.0.0.0/8'])"
    )

    def validate_path(self, path: Path | str, must_exist: bool = False) -> Path:
        """Validate that a user-supplied path is within allowed directories.

        Allowed directories: work_dir, shyfem_dir, and /tmp.
        Resolves symlinks to prevent traversal attacks.

        Args:
            path: User-supplied path to validate.
            must_exist: If True, also check that the path exists.

        Returns:
            Resolved Path object.

        Raises:
            ValueError: If the path is outside allowed directories or contains
                        null bytes / suspicious components.
            FileNotFoundError: If must_exist is True and the path does not exist.
        """
        path_str = str(path)

        # Reject null bytes and control characters
        if "\x00" in path_str:
            raise ValueError("Path contains null bytes")

        resolved = Path(path).expanduser().resolve()

        # Resolve symlinks if the target exists to prevent symlink traversal
        if resolved.exists():
            resolved = resolved.resolve(strict=True)

        allowed_roots = [
            self.work_dir.resolve(),
            self.shyfem_dir.resolve(),
            Path("/tmp").resolve(),
        ]

        if not any(
            resolved == root or str(resolved).startswith(str(root) + "/")
            for root in allowed_roots
        ):
            raise ValueError(
                f"Path '{resolved}' is outside allowed directories: "
                f"{', '.join(str(r) for r in allowed_roots)}"
            )

        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"Path not found: {resolved}")

        return resolved

    def validate_save_path(self, path: Path | str) -> Path:
        """Validate that a save path is within the work directory.

        Resolves symlinks to prevent traversal attacks.

        Args:
            path: User-supplied save path to validate.

        Returns:
            Resolved Path object.

        Raises:
            ValueError: If the path is outside work_dir or contains null bytes.
        """
        path_str = str(path)
        if "\x00" in path_str:
            raise ValueError("Path contains null bytes")

        resolved = Path(path).expanduser().resolve()

        # If path already exists, resolve symlinks strictly
        if resolved.exists():
            resolved = resolved.resolve(strict=True)

        work_root = self.work_dir.resolve()

        if resolved != work_root and not str(resolved).startswith(str(work_root) + "/"):
            raise ValueError(
                f"Save path '{resolved}' must be within work directory: {work_root}"
            )

        return resolved


# Global configuration instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
