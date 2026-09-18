# SHYFEM UI

A modern Python Shiny web application providing a unified interface for the SHYFEM hydrodynamic simulation workflow: grid preparation, simulation configuration, job management, post-processing, and interactive visualization.

## Features

- **Grid Preparation** - Convert .grd files to .bas format using shypre/shybas, with interactive deck.gl mesh map (layer legend with visibility toggles, screenshot export)
- **Mesh Partitioning** - Partition meshes for MPI parallel execution with shyparts, load balance analysis
- **Simulation Configuration** - Rich STR parameter editor with split/form views, 100+ parameter database with tooltips, validation engine, boundary condition editor, template library
- **Job Management** - Submit, monitor, and manage jobs with real-time progress bars, job timeline, workflow chaining (multi-step pipelines), and Celery/Redis support for server deployments
- **Post-Processing** - Full shyelab integration with 10 operation modes, variable/layer selection, batch processing, output file browser
- **Visualization** - Interactive Plotly plots for grids, time series, NetCDF data (contour/heatmap/3D surface), vertical profiles, transects, and difference maps; animated particle trajectory viewer (trips_layer with playback controls)
- **IBM Explorer** - Lagrangian particle tracking visualization with animated trips, trail effects, start/end point markers, and screenshot export
- **Job Comparison** - Side-by-side runtime stats, parameter diffs, overlaid time series
- **Parameter Sweeps** - Ensemble runs with grid/zip sweep modes, result overlay with min/max envelope
- **Report Generation** - Self-contained HTML reports with embedded Plotly charts, simulation parameters, grid info, and runtime statistics
- **In-App Docs & Feedback** - Topbar buttons (left of the theme toggle) open About (README), Changelog, and a feedback form (bug reports / suggestions stored server-side, with an anonymous rate-limited `POST /api/feedback` for external submission)

## Installation

### Prerequisites

- Python 3.10 or later
- SHYFEM installation (for running simulations)

### Install from source

```bash
cd shyfem-ui
pip install -e .
```

### Install with server dependencies (Celery/Redis)

```bash
pip install -e ".[server]"
```

### Install with development dependencies

```bash
pip install -e ".[dev]"
```

## Quick Start

### Local Desktop Mode

```bash
# Set SHYFEM directory (if not default)
export SHYFEM_UI_SHYFEM_DIR=/path/to/shyfem

# Start the application
shyfem-ui
```

Then open http://127.0.0.1:8000 in your browser.

### Server Mode

```bash
# Configure for server deployment
export SHYFEM_UI_DEPLOYMENT_MODE=server
export SHYFEM_UI_HOST=0.0.0.0
export SHYFEM_UI_DATABASE_URL=postgresql://user:pass@localhost/shyfem_ui

# Optional: enable Celery for distributed job execution
export SHYFEM_UI_USE_CELERY=true
export SHYFEM_UI_REDIS_URL=redis://localhost:6379/0

# Optional: enable basic authentication
export SHYFEM_UI_AUTH_ENABLED=true
export SHYFEM_UI_AUTH_USERNAME=admin
export SHYFEM_UI_AUTH_PASSWORD=changeme

# Start the application
shyfem-ui
```

### Docker Deployment

```bash
# Build and start with Docker Compose
SHYFEM_DIR=/path/to/shyfem docker-compose up -d
```

### Starting Celery Workers (server mode)

```bash
celery -A shyfem_ui.services.job_celery worker --loglevel=info
```

## Configuration

All settings can be set via environment variables (with `SHYFEM_UI_` prefix), a `.env` file, or command-line arguments.

### Environment Variables

All variables use the `SHYFEM_UI_` prefix and can also be set in a `.env` file.

#### Core / Deployment

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_DEPLOYMENT_MODE` | `local` | `local` (single-user, no auth) or `server` (multi-user, auth required) |
| `SHYFEM_UI_HOST` | `127.0.0.1` | Host to bind to |
| `SHYFEM_UI_PORT` | `8000` | Port to bind to |
| `SHYFEM_UI_SHYFEM_DIR` | auto-detected | Path to SHYFEM installation directory |
| `SHYFEM_UI_WORK_DIR` | `~/.shyfem-ui/projects` | Working directory for projects and outputs |
| `SHYFEM_UI_USER_DATA_ROOT` | `/data/shyfem` | Root directory under which per-user home dirs are created: `{user_data_root}/{username}/` (server mode) |
| `SHYFEM_UI_DEBUG` | `false` | Enable debug mode (verbose WebSocket logging, etc.) |

#### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_DATABASE_URL` | `sqlite:///./shyfem_ui.db` | SQLAlchemy database URL. **Use an absolute path in production** (e.g. `sqlite:////var/lib/shyfem/shyfem_ui.db`) so it does not depend on cwd. |
| `SHYFEM_UI_DB_POOL_SIZE` | `5` | SQLAlchemy connection pool size (PostgreSQL only) |
| `SHYFEM_UI_DB_POOL_OVERFLOW` | `10` | Max overflow connections beyond pool_size (PostgreSQL only) |
| `SHYFEM_UI_DB_POOL_RECYCLE` | `3600` | Seconds before recycling idle connections (PostgreSQL only) |

#### Job Queue

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_USE_CELERY` | `false` | Use Celery/Redis for distributed job queue (server mode) |
| `SHYFEM_UI_MAX_WORKERS` | `4` | Maximum concurrent jobs (local mode, ignored when Celery is enabled) |
| `SHYFEM_UI_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery broker |

#### MPI

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_MPI_ENABLED` | `true` | Enable MPI support |
| `SHYFEM_UI_MPI_DEFAULT_NP` | `4` | Default MPI process count |
| `SHYFEM_UI_MPIRUN_PATH` | `mpirun` | Path to mpirun executable |

#### Solver

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_SOLVER_NODE_THRESHOLD` | `50000` | Node count above which PETSc is recommended over SPARSKIT |

#### Authentication (server mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_AUTH_ENABLED` | auto | Enable auth (`true` auto-set in server mode; `false` in local mode). Override explicitly to force. |
| `SHYFEM_UI_AUTH_USERNAME` | `admin` | Legacy basic auth username |
| `SHYFEM_UI_AUTH_PASSWORD` | (unset) | Legacy basic auth password |
| `SHYFEM_UI_AUTH_SESSION_TTL_HOURS` | `24` | Session cookie lifetime in hours |
| `SHYFEM_UI_USE_SECURE_COOKIES` | `false` | Set `Secure` flag on session cookies — **enable when behind HTTPS** |
| `SHYFEM_UI_DEFAULT_ADMIN_USERNAME` | `admin` | Bootstrap admin account name (server mode first run) |
| `SHYFEM_UI_DEFAULT_ADMIN_PASSWORD` | **(required in server mode)** | Bootstrap admin password — **server mode aborts at startup if unset** (and `AUTH_PASSWORD` is also unset) |
| `SHYFEM_UI_DEFAULT_USER_USERNAME` | `user` | Tutorial/demo user account name |
| `SHYFEM_UI_DEFAULT_USER_PASSWORD` | (unset) | Tutorial user password — leave unset to disable the tutorial account |

#### Reverse Proxy / TLS (server mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_ROOT_PATH` | (empty) | ASGI root_path for reverse proxy sub-path deployment (e.g., `/shyfem-ui`) |
| `SHYFEM_UI_TRUSTED_PROXIES` | `[]` | JSON list of trusted proxy CIDR ranges for `X-Forwarded-For` (e.g., `["127.0.0.1/8","10.0.0.0/8"]`) |

#### Box-Model Analysis (server mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_ANALYSIS_ROOTS` | `[]` | JSON array of admin-declared, read-only directories the Box model page may read run output from (server mode only) — see "Box-model analysis roots (server mode)" below |

#### Upload & Storage Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_MAX_UPLOAD_SIZE_MB` | `500` | Maximum single file upload size in MB |
| `SHYFEM_UI_MAX_PROJECT_STORAGE_MB` | `5000` | Maximum total storage per project in MB |
| `SHYFEM_UI_STATIC_CACHE_MAX_AGE` | `86400` | `Cache-Control max-age` for static assets in seconds (`0` disables caching) |
| `SHYFEM_UI_RATE_LIMIT_RPM` | `120` | Max requests per minute per session (server mode) |

#### SMTP / Email Notifications (server mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_SMTP_HOST` | (unset) | SMTP server hostname — leave empty to disable email notifications |
| `SHYFEM_UI_SMTP_PORT` | `587` | SMTP port (`587` = STARTTLS, `465` = implicit TLS) |
| `SHYFEM_UI_SMTP_USER` | (unset) | SMTP login username |
| `SHYFEM_UI_SMTP_PASSWORD` | (unset) | SMTP login password |
| `SHYFEM_UI_SMTP_FROM` | `SHYFEM UI <noreply@localhost>` | From address for notification emails |

#### UI

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_THEME` | `flatly` | Shinyswatch Bootstrap theme name |
| `SHYFEM_UI_LOG_REFRESH_INTERVAL` | `5` | Log viewer auto-refresh interval in seconds |

### Command-Line Arguments

```bash
shyfem-ui --help

Options:
  --host HOST           Host to bind to
  --port PORT           Port to bind to
  --shyfem-dir PATH     SHYFEM installation directory
  --mode {local,server} Deployment mode
  --reload              Enable auto-reload for development
  --workers N           Number of job queue workers
```

### Box-model analysis roots (server mode)

The **Box model** page analyses SHYFEM box-model (`idtbox`) output, which often lives outside a
user's own sandbox — a multi-decade run can be a gigabyte or more. In server mode, an admin can
declare extra read-only directories for the app to read such runs from:

```bash
export SHYFEM_UI_ANALYSIS_ROOTS='["/data/runs/curonian"]'   # JSON array; default []
```

Rules, enforced when the config loads (`shyfem_ui/config.py::_check_analysis_roots`):

- Server mode only — ignored in local mode.
- Each root must resolve to an existing directory, or startup fails.
- A root may not be `/`; may not be, contain, or be contained by `/tmp` (the whole subtree is off
  limits); and may not overlap `SHYFEM_UI_USER_DATA_ROOT`, `SHYFEM_UI_WORK_DIR`,
  `SHYFEM_UI_SHYFEM_DIR`, or the SQLite database's directory.
- The accepted, resolved list is logged at **WARNING** level at startup — declaring a root widens
  read access, so the log line is a deliberate paper trail.

Roots are **read-only**, but **readable by every authenticated user** through every read surface of
the app, not only the Box model page. Never point a root at anything user-writable: a hard link
placed inside the root by anyone with write access there cannot be resolved away by the app's path
confinement. Give the directory read-only ownership (e.g. a dedicated non-app user/group) before
declaring it.

A project opts in with a `boxmodel.json` manifest (schema 1) in its directory — see
`shyfem_ui/services/boxmodel_manifest.py` for the exact keys: `title`; `grid.grd` plus optional
`grid.bas`/`grid.boxes_txt`; optional `boxes.polygons` (when omitted, box outlines are dissolved
from the grid instead, which needs the grid's coordinate system to be known — a projected grid
with small, locally-referenced coordinates can look geographic to the auto-detection, so give such
a grid explicit `boxes.polygons`) plus `boxes.layer` and `boxes.id_field` (defaults to `box`);
`str`; `forcing.dir`; `runs[]` with `id`/`label`/`dir` (`id` must match `[a-z0-9_-]{1,64}`);
`observations.file`/`observations.sites`.
Relative manifest paths resolve against the project directory; absolute paths (e.g. a `runs[].dir`
kept outside the sandbox) must lie under an analysis root or the user's own sandbox. The manifest
is capped at 64 KB.

Input file caps: `observations.csv` needs columns `date, site, variable, value` (`variable` one of
`salinity`, `temperature`, `level`; level values are in cm and non-positive level rows are dropped),
up to 50 MB / 2,000,000 rows; `sites.csv` needs columns `site, lat, lon, box` (a blank `box` means
the site is unmapped — kept, but never matched to a skill target); a `boxes.polygons` file is
GeoPackage or GeoJSON, up to 50 MB, 1,000 features, 200,000 vertices.

Skill metrics on the Time-series tab follow the Curonian reference scripts: daily means are
computed by stamped date, then compared as bias, RMSE, r and R² (Nash–Sutcliffe form, which can go
negative) using population (ddof=0) moments, plus an sd ratio. A water-level series is compared as
an anomaly about its own mean, after converting cm to m, so a level row's bias is shown as "—". A
target needs at least 30 matched days (60 per calendar year for the per-year breakdown); band
amplitude ratios (2–4, 4–10, 10–30, 30–400 day periods) need at least 120 gap-free days. See
`docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md` §7 for the exact formulas.

Per-run Parquet caches are built on demand by a child process
(`python -m shyfem_ui.boxmodel_cache_cli`) into `<project>/.boxmodel_cache/<run_id>/`. Building
requires a project editor with write access to the project directory, is capped at 2 concurrent
builds per worker process and 1 per user, and a build is bounded by
`SHYFEM_UI_COMMAND_TIMEOUT_SECONDS` when set, else a 30-minute default. Cache bytes on disk count
toward the project's `SHYFEM_UI_MAX_PROJECT_STORAGE_MB` quota. A stale directory left by an
interrupted build is removed at page load by a project editor with write access to the project
directory; a *failed* build's directory is kept, so its error stays visible in the status badge,
until that run is rebuilt.

## Workflow

The application follows the typical SHYFEM simulation workflow:

1. **Grid Prep** - Load a `.grd` mesh file, inspect nodes/elements, convert to `.bas` with shypre
2. **Partitioning** - Partition the mesh for MPI parallel runs with shyparts, review load balance
3. **Simulation** - Configure parameters in the `.str` editor (split/form views), set boundary conditions, choose from templates (2D, Baroclinic, Lagrangian)
4. **Run** - Submit jobs (serial or MPI), monitor progress with real-time log streaming, use workflow pipelines for multi-step automation
5. **Post-Process** - Run shyelab operations (time series extraction, NetCDF export, spatial/temporal averaging, residual analysis)
6. **Visualize** - Interactive plots: grid meshes, time series with statistics, NetCDF contour/heatmap/surface, vertical profiles, transects, difference maps

Additional pages:

- **Compare** - Side-by-side job comparison (runtime stats, parameter diffs, overlaid time series)
- **Ensemble** - Parameter sweep manager (grid/zip modes, batch submit, result overlay with envelope)
- **Box model** - Map and time-series analysis of SHYFEM box output (`idtbox`) against observations, with a skill table

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run unit tests
make test

# Run with coverage
make coverage

# Run specific test file
pytest tests/test_parser_str.py -v
```

### Running E2E (Playwright) Tests

Browser tests require Playwright with Chromium installed:

```bash
# Install Playwright browsers (one-time)
make e2e-install

# Run E2E tests
make e2e
```

In CI environments, use `python -m playwright install chromium --with-deps` to
install Chromium and its OS-level dependencies automatically.

### Code Formatting

```bash
# Format code
black shyfem_ui/

# Check linting
ruff check shyfem_ui/
```

### Test Coverage

The test suite covers:
- **STR parser** - Section parsing, value conversion, round-trip, edge cases, COMMON_PARAMS database
- **GRD parser** - Node/element/line parsing, bounds, depth, coordinate system detection, UTM conversion
- **Tool wrapper** - Command execution, progress parsing, output file discovery, error handling
- **Local job queue** - Submit, cancel, status, listing, filtering, progress callbacks, cleanup, eviction
- **Workflow engine** - Templates, argument resolution, workflow lifecycle, step results, cancellation
- **Report builder** - HTML generation, sections, parameters, grid info, statistics, Plotly embedding, file I/O
- **Configuration** - Defaults, path validation (security), global config, path resolution

## Security

The UI includes several security measures for server deployments:

- **CSRF protection** — Login form uses a double-submit cookie pattern. A random token is set as both a cookie and a hidden form field; the server validates they match on POST.
- **Session cookies** — `HttpOnly`, `SameSite=Lax`, configurable `Secure` flag via `SHYFEM_UI_USE_SECURE_COOKIES` (enable when behind HTTPS/TLS).
- **Password policy** — Minimum 8 characters enforced on both user creation and password reset.
- **Tool allowlist** — `ShyfemWrapper` only executes known SHYFEM tools (`shyfem`, `shypre`, `shybas`, `shyparts`, `shyelab`, etc.), preventing arbitrary command execution.
- **Path validation** — Usernames reject `..` (path traversal). `User.home_dir()` resolves and validates containment under `user_data_root`. STR file references are validated with `config.validate_path()`.
- **WebSocket auth** — The Shiny Server proxy bypass is restricted to connections from `127.0.0.1` / `::1` only.
- **Error logging** — Job persistence and progress callback errors are logged at `warning`/`error` level instead of being silently swallowed.

## Architecture

```mermaid
graph TD
    A[app.py<br>ASGI + Middleware] --> P[pages/]
    A --> DB[(SQLite / PostgreSQL)]
    P --> C[components/]
    P --> S[services/]
    C --> S
    S --> Q[Job Queue]
    S --> FS[File System]
    Q --> CLI[SHYFEM CLI Tools]

    subgraph Pages
        P --> home.py
        P --> grid_prep.py
        P --> simulation.py
        P --> run.py
        P --> postprocess.py
        P --> visualize.py
    end

    subgraph Components
        C --> grid_map.py
        C --> str_editor.py
        C --> timeseries.py
        C --> boundary_editor.py
    end

    subgraph Services
        S --> parser_str.py
        S --> parser_grd.py
        S --> shyfem_wrapper.py
        S --> job_local.py
        S --> job_celery.py
        S --> workflow.py
    end
```

### Directory Layout

```
shyfem-ui/
├── shyfem_ui/
│   ├── app.py                  # Main Shiny application
│   ├── config.py               # Pydantic settings with env var support
│   ├── pages/                  # UI pages (one per workflow phase)
│   │   ├── home.py             # Dashboard
│   │   ├── grid_prep.py        # shypre/shybas + interactive mesh map
│   │   ├── partitioning.py     # shyparts + load balance analysis
│   │   ├── simulation.py       # STR editor + templates + boundaries
│   │   ├── run.py              # Job queue + progress + timeline
│   │   ├── postprocess.py      # shyelab operations + batch processing
│   │   ├── visualize.py        # Grid/TS/NetCDF/profile/transect plots
│   │   ├── compare.py          # Job comparison (stats, params, time series)
│   │   ├── ibm.py              # IBM particle tracking with animated trips
│   │   └── ensemble.py         # Parameter sweeps + batch runs
│   ├── components/             # Reusable Shiny module widgets
│   │   ├── boundary_editor.py  # Boundary condition editor
│   │   ├── file_browser.py     # File selection widget
│   │   ├── grid_map.py         # Interactive deck.gl mesh map with layer legend
│   │   ├── job_status.py       # Status badges and formatters
│   │   ├── log_viewer.py       # Real-time log viewer with streaming
│   │   ├── plot_widget.py      # Plotly visualization widget
│   │   ├── str_editor.py       # Rich STR parameter editor + validation
│   │   └── timeseries.py       # Interactive time series + statistics
│   ├── services/               # Backend logic
│   │   ├── shyfem_wrapper.py   # Async CLI wrapper for SHYFEM tools
│   │   ├── job_queue.py        # Abstract queue interface + factory
│   │   ├── job_local.py        # Local asyncio job queue
│   │   ├── job_celery.py       # Celery/Redis distributed queue
│   │   ├── workflow.py         # Multi-step workflow engine
│   │   ├── parser_str.py       # STR file parser + 100+ param database
│   │   ├── parser_grd.py       # GRD file parser + coordinate detection
│   │   └── report.py           # HTML report generator
│   ├── models/                 # SQLAlchemy models
│   │   └── project.py          # Project, Grid, Simulation, Job models
│   └── db/
│       └── base.py             # Database session management
├── tests/                      # Test suite (201 tests)
│   ├── test_parser_str.py      # STR parser tests
│   ├── test_parser_grd.py      # GRD parser tests
│   ├── test_wrapper.py         # Tool wrapper tests
│   ├── test_job_local.py       # Local job queue tests
│   ├── test_workflow.py        # Workflow engine tests
│   ├── test_report.py          # Report builder tests
│   └── test_config.py          # Configuration tests
└── TODO.md                     # Development roadmap
```

## SHYFEM Tools Wrapped

| Tool | Function | UI Page |
|------|----------|---------|
| `shypre` | Convert .grd to .bas | Grid Prep |
| `shybas` | Basin analysis | Grid Prep |
| `shyparts` | Mesh partitioning | Partitioning |
| `shyfem` | Run simulation | Run |
| `shyelab` | Post-process output | Post-Process |
| `shyplot` | Generate plots | Visualize |

## Troubleshooting

### MPI Build Issues
SHYFEM requires OpenMPI (not Intel MPI) when building with gfortran. Prefix commands with `PATH=/usr/bin:$PATH` to ensure the system OpenMPI is used. See `CLAUDE.md` for build details.

### Celery Workers Not Starting
Ensure Redis is running (`redis-cli ping`) and the `SHYFEM_UI_REDIS_URL` matches between the app and workers. Start workers with:
```bash
celery -A shyfem_ui.services.job_celery worker --loglevel=info
```

### Path Validation Errors
The application restricts file access to the work directory, SHYFEM directory, and `/tmp`. Set `SHYFEM_UI_WORK_DIR` to include your project directories.

## License

GPL-3.0 (same as SHYFEM)

## Links

- [SHYFEM Project](https://github.com/shyfem/shyfem)
- [SHYFEM Documentation](https://shyfem.readthedocs.io/)
- [Python Shiny](https://shiny.posit.co/py/)
