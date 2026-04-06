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

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_SHYFEM_DIR` | auto-detected | SHYFEM installation directory |
| `SHYFEM_UI_HOST` | `127.0.0.1` | Host to bind to |
| `SHYFEM_UI_PORT` | `8000` | Port to bind to |
| `SHYFEM_UI_DEPLOYMENT_MODE` | `local` | `local` or `server` |
| `SHYFEM_UI_WORK_DIR` | `~/.shyfem-ui/projects` | Working directory for projects |
| `SHYFEM_UI_DATABASE_URL` | `sqlite:///./shyfem_ui.db` | Database connection URL |
| `SHYFEM_UI_USE_CELERY` | `false` | Use Celery/Redis for job queue |
| `SHYFEM_UI_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `SHYFEM_UI_MAX_WORKERS` | `4` | Maximum concurrent jobs (local mode) |
| `SHYFEM_UI_MPI_ENABLED` | `true` | Enable MPI support |
| `SHYFEM_UI_MPI_DEFAULT_NP` | `4` | Default MPI process count |
| `SHYFEM_UI_MPIRUN_PATH` | `mpirun` | Path to mpirun executable |
| `SHYFEM_UI_AUTH_ENABLED` | `false` | Enable basic authentication |
| `SHYFEM_UI_AUTH_USERNAME` | `admin` | Basic auth username |
| `SHYFEM_UI_AUTH_PASSWORD` | (empty) | Basic auth password |
| `SHYFEM_UI_USE_SECURE_COOKIES` | `false` | Set `Secure` flag on session cookies (enable behind HTTPS) |
| `SHYFEM_UI_THEME` | `flatly` | Shinyswatch theme name |
| `SHYFEM_UI_LOG_REFRESH_INTERVAL` | `5` | Log viewer refresh interval (seconds) |
| `SHYFEM_UI_RATE_LIMIT_RPM` | `120` | Max requests per minute per session |

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
