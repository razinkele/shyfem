"""Configuration management using Pydantic settings."""

import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
        default="local", description="Deployment mode: 'local' for desktop, 'server' for multi-user"
    )
    host: str = Field(default="127.0.0.1", description="Host to bind to")
    port: int = Field(default=8000, description="Port to bind to")

    # SHYFEM paths
    shyfem_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2],
        description="Path to SHYFEM installation directory",
    )
    work_dir: Path = Field(
        default=Path.home() / ".shyfem-ui" / "projects",
        description="Working directory for projects and outputs",
    )

    # Per-user data directories
    user_data_root: Path = Field(
        default=Path("/data/shyfem"),
        description="Root directory under which per-user home dirs are created: {user_data_root}/{username}/",
    )

    # Database settings
    #
    # F25: the old default ("sqlite:///./shyfem_ui.db") is a relative path
    # that SQLite resolves against the process's CWD at connect time, not
    # against this package. A worker started from a different directory would
    # silently create/open a *different* database file. Anchor it to this
    # package's own location instead -- shyfem-ui/shyfem_ui.db -- which is
    # the same physical file laguna prod already resolves to today (the app
    # is started from the shyfem-ui git checkout), so this is CWD-independent
    # without changing prod's behavior. SHYFEM_UI_DATABASE_URL/DATABASE_URL
    # still override (pydantic env-var precedence beats the Field default).
    database_url: str = Field(
        default_factory=lambda: (
            f"sqlite:///{(Path(__file__).resolve().parents[1] / 'shyfem_ui.db')}"
        ),
        description="SQLAlchemy database URL",
    )
    job_state_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / ".job_state",
        description=(
            "Server-only directory for the local queue's job supervisor records "
            "(launch, pid and exit records; J-01). Must not be inside any user's "
            "data root: the server acts on these files. Created with mode 0700."
        ),
    )
    db_pool_size: int = Field(
        default=5, description="SQLAlchemy connection pool size (PostgreSQL only)"
    )
    db_pool_overflow: int = Field(
        default=10, description="Max overflow connections beyond pool_size (PostgreSQL only)"
    )
    db_pool_recycle: int = Field(
        default=3600, description="Seconds before recycling idle connections (PostgreSQL only)"
    )

    # Periodic maintenance (server mode): prune old jobs + expired sessions/tokens
    maintenance_interval_seconds: int = Field(
        default=3600,
        ge=0,
        description=(
            "Interval (s) between maintenance passes that prune old jobs and "
            "expired auth sessions/WS tokens. 0 disables the scheduler. Server "
            "mode only."
        ),
    )
    job_retention_days: int = Field(
        default=30,
        gt=0,
        description="Age (days) beyond which completed jobs are pruned by maintenance.",
    )
    audit_retention_days: int = Field(
        default=365,
        gt=0,
        description=(
            "Age (days) beyond which audit_log entries are pruned by maintenance. "
            "Kept longer than jobs (audit trail), but bounded so the table can't "
            "grow without limit."
        ),
    )
    feedback_retention_days: int = Field(
        default=180,
        gt=0,
        description=(
            "Age (days) beyond which feedbacks entries are pruned by maintenance "
            "(F52). Longer than job retention since triage can lag, shorter than "
            "the audit trail since feedback isn't a compliance record."
        ),
    )

    # Job queue settings
    use_celery: bool = Field(
        default=False, description="Use Celery/Redis for job queue (server mode)"
    )
    max_workers: int = Field(default=4, description="Maximum concurrent jobs (local mode)")
    command_timeout_seconds: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Wall-clock timeout (s) for a single SHYFEM tool subprocess. None "
            "disables it (default — preserves long-running simulations). Must be "
            "positive when set (0 is rejected, not silently disabled). Set it to "
            "free the worker if a tool hangs; size it to your longest job."
        ),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0", description="Redis URL for Celery broker"
    )

    # MPI settings
    mpi_enabled: bool = Field(default=True, description="Enable MPI support")
    mpi_default_np: int = Field(default=4, description="Default MPI processes")
    mpirun_path: str = Field(default="mpirun", description="Path to mpirun executable")

    # Solver settings
    solver_node_threshold: int = Field(
        default=50000, description="Node count threshold for recommending PETSc over SPARSKIT"
    )

    # UI behavior
    whats_new_enabled: bool = Field(
        default=True,
        description="Show the 'what's new' changelog modal on first visit (per browser)",
    )

    # Authentication (server mode only)
    auth_enabled: bool | None = Field(
        default=None,
        description="Enable basic auth (auto-enabled in server mode, default off in local)",
    )
    auth_username: str = Field(default="admin", description="Basic auth username")
    auth_password: str = Field(
        default="", description="Basic auth password (required if auth_enabled)"
    )
    auth_session_ttl_hours: int = Field(default=24, description="Session cookie lifetime in hours")
    use_secure_cookies: bool = Field(
        default=False,
        description="Set Secure flag on session cookies (enable when behind HTTPS)",
    )
    default_admin_username: str = Field(
        default="admin", description="Default admin username created on first run"
    )
    default_admin_password: str = Field(
        default="", description="Default admin password (required for server mode first run)"
    )
    default_user_username: str = Field(default="user", description="Default tutorial user username")
    default_user_password: str = Field(
        default="", description="Default tutorial user password (set to enable)"
    )

    # Debug settings
    log_level: str = Field(
        default="INFO",
        description=(
            "Level for the shyfem_ui package logger, applied wherever the app is "
            "built (see app.configure_logging). Under Shiny Server nothing else "
            "configures logging, so this is what decides whether INFO breadcrumbs "
            "reach the worker log."
        ),
    )
    debug: bool = Field(
        default=False, description="Enable debug mode (verbose WebSocket logging, etc.)"
    )

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, v: str) -> str:
        """Reject a typo instead of silently logging nothing.

        ``logging.getLevelName`` maps an unknown NAME to the string
        ``"Level <name>"``, so a misspelt level would be accepted and then set
        no threshold at all.
        """
        name = str(v).strip().upper()
        if name not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level {v!r}")
        return name

    # UI settings
    log_refresh_interval: int = Field(
        default=5, description="Log viewer refresh interval in seconds"
    )

    # Report settings
    report_plotly_mode: Literal["cdn", "inline"] = Field(
        default="cdn",
        description=(
            "How to embed Plotly JS in generated HTML reports. "
            "'cdn' — link to plot.ly CDN (small files, requires net). "
            "'inline' — bundle Plotly JS in each report (~3MB per file, "
            "offline-capable)."
        ),
    )

    @field_validator("shyfem_dir", "work_dir", mode="before")
    @classmethod
    def resolve_path(cls, v):
        """Convert string paths to Path objects and resolve."""
        if isinstance(v, str):
            v = Path(v)
        return v.expanduser().resolve()

    @model_validator(mode="after")
    def _check_server_mode_passwords(self):
        """Require an admin password when running in server mode and auto-enable auth."""
        if self.auth_enabled is None:
            self.auth_enabled = self.deployment_mode == "server"
        if self.deployment_mode == "server":
            if not self.default_admin_password and not self.auth_password:
                raise ValueError(
                    "Server mode requires either SHYFEM_UI_DEFAULT_ADMIN_PASSWORD or "
                    "SHYFEM_UI_AUTH_PASSWORD to be set."
                )
            # Server mode is HTTPS (nginx terminates TLS); default Secure cookies
            # ON so session/CSRF cookies are never sent in clear. Explicit
            # override still honoured (e.g. SHYFEM_UI_USE_SECURE_COOKIES=false).
            if "use_secure_cookies" not in self.model_fields_set:
                self.use_secure_cookies = True
            # Server mode always sits behind the local nginx -> Shiny Server
            # proxy, which sets X-Forwarded-For and forwards it to the worker;
            # the worker's direct peer is therefore always loopback. Trusting
            # loopback lets the rate limiter recover the real client IP from XFF
            # (per-client, not per-server) — and it stays spoof-safe because the
            # rightmost-untrusted walk skips the loopback hops to the real
            # client IP nginx appended. Without this the limiter collapses every
            # user into one bucket. Explicit override still honoured.
            if "trusted_proxies" not in self.model_fields_set:
                self.trusted_proxies = ["127.0.0.0/8", "::1/128"]
        return self

    @model_validator(mode="after")
    def _check_analysis_roots(self):
        """Resolve and vet analysis roots (server mode only; local mode never uses them).

        The accepted, resolved list is written ONLY to ``self._vetted_analysis_roots``
        (a private attr), never back to ``self.analysis_roots`` (the user-supplied
        field). ``deployment_mode`` can be mutated after construction (no
        ``validate_assignment``), so validated-ness must live on a separate
        attribute that a later mode flip cannot retroactively make "true" for
        roots this validator never actually vetted. See ``resolved_analysis_roots``.
        """
        if self.deployment_mode != "server" or not self.analysis_roots:
            return self
        forbidden = [
            # "/" is protected via the equality arm below only (the spec's
            # separate "/ is rejected" clause) -- it can never also match via
            # the containment arms, since every resolved root is an absolute
            # path already rooted at "/". Do not "optimize" this away.
            Path("/"),
            Path("/tmp").resolve(),
            self.user_data_root.resolve(),
            Path(self.work_dir).resolve(),
            Path(self.shyfem_dir).resolve(),
        ]
        if self.database_url.startswith("sqlite:///"):
            forbidden.append(Path(self.database_url[len("sqlite:///") :]).resolve().parent)
        resolved: list[str] = []
        for raw in self.analysis_roots:
            try:
                root = Path(raw).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as e:
                raise ValueError(
                    f"analysis_roots: {raw!r} does not resolve to an existing directory"
                ) from e
            if not root.is_dir():
                raise ValueError(f"analysis_roots: {raw!r} is not a directory")
            for f in forbidden:
                if (
                    root == f
                    or str(root).startswith(str(f) + "/")
                    or str(f).startswith(str(root) + "/")
                ):
                    raise ValueError(f"analysis_roots: {raw!r} overlaps a protected location ({f})")
            resolved.append(str(root))
        self._vetted_analysis_roots = resolved
        logger.warning(
            "analysis_roots enabled (read-only for all authenticated users): %s", resolved
        )
        return self

    def resolved_analysis_roots(self) -> list[Path]:
        """The validated roots as Paths.

        Backed by ``_vetted_analysis_roots``, populated only by
        ``_check_analysis_roots`` at construction time -- never derived from
        ``analysis_roots``/``deployment_mode`` at call time, so a Config that
        was never validated in server mode (built local then mutated) fails
        closed to ``[]`` rather than surfacing its raw, unvetted strings.
        """
        return [Path(p) for p in self._vetted_analysis_roots]

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
        default=120, description="Max requests per minute per session (server mode)"
    )

    # Upload limits
    max_upload_size_mb: int = Field(default=500, description="Maximum file upload size in MB")
    max_project_storage_mb: int = Field(
        default=5000, description="Maximum total storage per project in MB"
    )
    max_export_bytes: int = Field(
        default=2 * 1024 * 1024 * 1024,
        description="Maximum total uncompressed project size (bytes) allowed for ZIP export",
    )

    # Proxy settings (server mode)
    root_path: str = Field(
        default="", description="ASGI root_path for reverse proxy deployment (e.g., '/shyfem-ui')"
    )
    trusted_proxies: list[str] = Field(
        default_factory=list,
        description="Trusted proxy CIDR ranges for X-Forwarded-For (e.g., ['127.0.0.1/8', '10.0.0.0/8'])",
    )

    analysis_roots: list[str] = Field(
        default_factory=list,
        description=(
            "Admin-declared directories readable (never writable) by EVERY authenticated "
            "user in server mode, for box-model run outputs kept outside the sandbox. "
            "JSON array in the environment, e.g. SHYFEM_UI_ANALYSIS_ROOTS='[\"/data/runs\"]'. "
            "Each must exist and must not overlap the user data root, the work dir, the "
            "SHYFEM dir, the database directory or /tmp. Ignored in local mode."
        ),
    )
    # Resolved/accepted analysis_roots, populated ONLY by _check_analysis_roots
    # below. Deliberately NOT derived from analysis_roots + deployment_mode at
    # read time: mode is mutable post-construction (model_config has no
    # validate_assignment), so a Config built in local mode and later flipped
    # to server mode (e.g. app.py's --mode server path) must not suddenly
    # treat its never-vetted analysis_roots as accepted. This private attr is
    # the only source of truth for resolved_analysis_roots() -- an
    # unvalidated config fails closed to [].
    _vetted_analysis_roots: list[str] = PrivateAttr(default_factory=list)

    # Static asset caching
    static_cache_max_age: int = Field(
        default=86400,
        description="Cache-Control max-age for static assets in seconds (0 = disabled)",
    )

    # Email / SMTP notifications
    smtp_host: str = Field(default="", description="SMTP host for notifications (empty = disabled)")
    smtp_port: int = Field(default=587, description="SMTP port (587=STARTTLS, 465=SSL)")
    smtp_user: str = Field(default="", description="SMTP login username")
    smtp_password: str = Field(default="", description="SMTP login password")
    smtp_from: str = Field(
        default="SHYFEM UI <noreply@localhost>",
        description="From address for notification emails",
    )
    smtp_timeout_seconds: int = Field(
        default=10,
        gt=0,
        description="Socket timeout for SMTP connect/login/send — bounds a slow "
        "or dead mail relay so it cannot hang the job-completion path.",
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
            resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots
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
            raise ValueError(f"Save path '{resolved}' must be within work directory: {work_root}")

        return resolved

    def display_path(self, path: Path | str, user: dict | None) -> str:
        """Return a user-facing display string for a project path that does not
        leak the absolute host layout in server mode.

        Server mode: a path inside the user's home is shown relative as
        ``~/<rel>``; any other (legacy/foreign) absolute path is reduced to its
        basename so the host filesystem layout is not exposed. Local mode
        (single-user desktop) shows the absolute path unchanged.
        """
        if self.deployment_mode != "server":
            return str(path)

        resolved = Path(path)
        if user is not None:
            home = self.user_data_root / user["username"]
            try:
                rel = resolved.relative_to(home)
            except ValueError:
                rel = None
            if rel is not None:
                return "~" if str(rel) == "." else f"~/{rel}"
        # No identity, or path outside the user's home: show only the basename.
        return resolved.name

    def confine_path(
        self,
        path: Path | str,
        user: dict | None,
        *,
        must_exist: bool = False,
        for_write: bool = False,
        session_factory=None,
    ) -> Path:
        """Resolve ``path`` and confine it to the requesting user's sandbox.

        Security boundary for the cross-user file-read / IDOR fix: unlike
        ``validate_path`` (which allows the shared work_dir/shyfem_dir/tmp),
        this restricts server-mode reads/writes to ``user_data_root/{username}/``.

        Args:
            path: User-supplied path.
            user: Server-validated user dict (from ``current_user()``), or None.
            must_exist: If True, also require the resolved path to exist.
            for_write: If True, the read-only bundled asset roots
                (testcases/examples, bin) are NOT allowed — a write must land in
                the user's own home, never in shared tutorial assets. Writes are
                confined to the user's own home for everyone; the N44
                shared-project widening below applies to READS only.
            session_factory: Optional SQLAlchemy session factory (testing);
                forwarded to the shared-project permission query. Defaults to
                the global factory.

        Raises:
            ValueError: If the path escapes the user's home directory (or, in
                server mode, if the identity is unresolved / contains null bytes).
            FileNotFoundError: If ``must_exist`` and the path does not exist.
        """
        if "\x00" in str(path):
            raise ValueError("Path contains null bytes")

        # Local mode is single-user desktop with no auth; keep the shared-root
        # behavior so existing local workflows are unaffected.
        if self.deployment_mode != "server":
            return self.validate_path(path, must_exist=must_exist)

        # Server mode: fail closed on an unresolved identity (mirrors
        # access_control.identity_denied_reason).
        if user is None:
            raise ValueError(
                "Session identity could not be verified. "
                "Please reload the page and sign in again."
            )

        # Defense-in-depth: usernames are regex-validated at creation
        # (AuthService.create_user), but re-check here too (single source of
        # truth: shyfem_ui.models.user.validate_username) so a bad value
        # (however it got into the session/DB) cannot widen confinement.
        # This also closes N43: a username of '.' resolves
        # (user_data_root / '.') == user_data_root, which the old
        # 'home != root' escape guard below treated as "no escape" -- i.e.
        # it silently collapsed confinement to the entire data root.
        #
        # Imported locally, not at module scope: shyfem_ui.db.base (imported
        # transitively by shyfem_ui.models.user) imports shyfem_ui.config at
        # module load time, so a top-level import here would be circular.
        # By the time confine_path() actually runs, this module is fully
        # loaded, so the import below is safe.
        from shyfem_ui.models.user import ROLE_ADMIN, validate_username

        username = user.get("username") if isinstance(user, dict) else None
        if not isinstance(username, str):
            raise ValueError("Invalid user session: unsafe username")
        validate_username(username)

        # Resolve the home with an explicit escape guard so a malicious username
        # cannot widen confinement above user_data_root.
        root = self.user_data_root.resolve()
        home = (root / username).resolve()
        if home != root and not str(home).startswith(str(root) + "/"):
            raise ValueError("User home escapes the data root")

        allowed_roots = [home]
        if not for_write:
            # Read-only bundled assets stay reachable for reads (tutorials/examples),
            # plus the admin-declared analysis roots (box-model run outputs).
            allowed_roots += [self.testcases_dir.resolve(), self.bin_dir.resolve()]
            allowed_roots += self.resolved_analysis_roots()
        # An admin's Dashboard lists every project, so an admin may read and
        # write (e.g. run a model in) every project folder: both
        # project-storage roots, never beyond them, and never the bundled
        # assets above. ``role`` is re-read from the DB on every
        # current_user() call.
        if user.get("role") == ROLE_ADMIN:
            allowed_roots += [self.user_data_root.resolve(), self.work_dir.resolve()]

        resolved = Path(path).expanduser().resolve()
        if resolved.exists():
            resolved = resolved.resolve(strict=True)

        def _within(roots) -> bool:
            return any(
                resolved == root_ or str(resolved).startswith(str(root_) + "/") for root_ in roots
            )

        if not _within(allowed_roots):
            # N44: for READS, also allow the work_dir of any project the acting
            # user holds an accepted ProjectPermission grant on (e.g. the
            # admin-owned "Mar Menor Tutorial" shared to the tutorial user).
            # WRITES stay home-only. The permission set is derived server-side
            # from the DB keyed on the validated identity (never a client
            # signal). The DB is queried only when the path is NOT already
            # within the user's own home / bundled assets, so the common
            # in-home file op never touches the database (each out-of-home
            # tutorial read still costs one query — caching is a follow-up).
            shared_ok = False
            if not for_write:
                from shyfem_ui.services.access_control import accessible_shared_work_dirs

                # Defense-in-depth: a project's stored work_dir is only honored
                # as a read root if it is itself contained within a trusted
                # project-storage root -- config.work_dir (bootstrap / clone /
                # legacy projects) or config.user_data_root (new / imported /
                # F15-relocated projects). This mirrors the explicit escape
                # guard on ``home`` and drops a pathological stored path
                # ('/', '', '.', '/etc', ...) rather than resolving it as an
                # allowlisted read root. Fail-closed: a work_dir outside both
                # roots is silently skipped (never becomes readable).
                #
                # Strictly BELOW a trusted base, never equal to one -- mirrors
                # the ``home != root`` equality guard above. A project whose
                # stored work_dir IS a trusted base itself (config.work_dir or
                # config.user_data_root exactly) must not become a read root:
                # ``_within`` would then treat every path under that base as
                # "inside", granting read of the ENTIRE shared tree (every
                # other project / every other user's home), far beyond the
                # single project this grant is for.
                trusted_bases = [self.work_dir.resolve(), self.user_data_root.resolve()]
                shared_roots = [
                    wd
                    for wd in accessible_shared_work_dirs(user, session_factory=session_factory)
                    if any(str(wd).startswith(str(base) + "/") for base in trusted_bases)
                ]
                shared_ok = _within(shared_roots)
            if not shared_ok:
                raise ValueError(f"Path '{resolved}' is outside your home directory: {home}")

        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"Path not found: {resolved}")

        return resolved

    def new_project_path(self, name: str, user: dict | None) -> Path:
        """Return the folder for a new project called ``name`` (H-03).

        ``name`` is typed by the user, so it must be one plain folder name:
        no separator, no leading dot (which also refuses ``.`` and ``..``),
        no NUL, at most 255 bytes. It is refused rather than rewritten, so
        ``'../x'`` never quietly becomes a legal name. Anything already
        there under that name, a dangling symlink included, is refused
        rather than followed. Server mode roots the folder in the owner's
        home and confines it there; local mode roots it in ``work_dir``.
        Messages never contain a host path.

        Raises:
            ValueError: If the name is unsafe, taken, or the folder escapes
                its root.
        """
        name = name.strip()
        if (
            not name
            or name.startswith(".")
            or name != Path(name).name
            or "\\" in name
            or "\x00" in name
        ):
            raise ValueError(
                f"Invalid project name {name!r}: use a plain folder name "
                "without '/', '\\' or a leading '.'"
            )
        if len(name.encode("utf-8", "surrogatepass")) > 255:
            raise ValueError("Project name is too long (at most 255 bytes)")
        if self.deployment_mode == "server":
            if user is None:
                raise ValueError(
                    "Session identity could not be verified. "
                    "Please reload the page and sign in again."
                )
            candidate = self.user_data_root / str(user.get("username")) / name
        else:
            candidate = self.work_dir / name
        if os.path.lexists(candidate):
            raise ValueError(f"A file or folder named {name!r} already exists")
        try:
            if self.deployment_mode == "server":
                return self.confine_path(candidate, user, for_write=True)
            return self.validate_save_path(candidate)
        except (ValueError, OSError) as e:
            # confine_path/validate_save_path messages name host paths.
            logger.warning("Refused new project folder %s: %s", candidate, e)
            raise ValueError(f"A project named {name!r} cannot be created here") from e


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
