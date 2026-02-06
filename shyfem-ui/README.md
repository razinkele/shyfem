# SHYFEM UI

A modern Python Shiny web application providing a unified interface for the SHYFEM hydrodynamic simulation workflow.

## Features

- **Grid Preparation**: Convert .grd files to .bas format using shypre/shybas
- **Mesh Partitioning**: Partition meshes for MPI parallel execution with shyparts
- **Simulation Configuration**: Edit .str parameter files with syntax highlighting
- **Job Management**: Submit, monitor, and manage simulation jobs
- **Post-Processing**: Process output files with shyelab
- **Visualization**: Interactive plots of grids and simulation results

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

# Start the application
shyfem-ui
```

### Docker Deployment

```bash
# Build and start with Docker Compose
SHYFEM_DIR=/path/to/shyfem docker-compose up -d
```

## Configuration

Configuration can be set via environment variables or command-line arguments.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SHYFEM_UI_SHYFEM_DIR` | `/home/razinka/shyfem` | SHYFEM installation directory |
| `SHYFEM_UI_HOST` | `127.0.0.1` | Host to bind to |
| `SHYFEM_UI_PORT` | `8000` | Port to bind to |
| `SHYFEM_UI_DEPLOYMENT_MODE` | `local` | `local` or `server` |
| `SHYFEM_UI_WORK_DIR` | `~/.shyfem-ui/projects` | Working directory for projects |
| `SHYFEM_UI_DATABASE_URL` | `sqlite:///./shyfem_ui.db` | Database connection URL |
| `SHYFEM_UI_USE_CELERY` | `false` | Use Celery for job queue |
| `SHYFEM_UI_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `SHYFEM_UI_MAX_WORKERS` | `4` | Maximum concurrent jobs |
| `SHYFEM_UI_THEME` | `flatly` | Shinyswatch theme name |

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

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run with coverage
pytest --cov=shyfem_ui tests/
```

### Code Formatting

```bash
# Format code
black shyfem_ui/

# Check linting
ruff check shyfem_ui/
```

## Architecture

```
shyfem-ui/
├── shyfem_ui/
│   ├── app.py                # Main Shiny application
│   ├── config.py             # Pydantic configuration
│   ├── pages/                # UI pages (one per workflow phase)
│   │   ├── home.py           # Dashboard
│   │   ├── grid_prep.py      # shypre/shybas
│   │   ├── partitioning.py   # shyparts
│   │   ├── simulation.py     # .str editor
│   │   ├── run.py            # Job queue
│   │   ├── postprocess.py    # shyelab
│   │   └── visualize.py      # Plots
│   ├── components/           # Reusable widgets
│   │   ├── file_browser.py
│   │   ├── job_status.py
│   │   ├── log_viewer.py
│   │   ├── str_editor.py
│   │   └── plot_widget.py
│   ├── services/             # Backend logic
│   │   ├── shyfem_wrapper.py # Fortran CLI wrappers
│   │   ├── job_queue.py      # Abstract queue interface
│   │   ├── job_local.py      # Multiprocessing queue
│   │   ├── job_celery.py     # Redis/Celery queue
│   │   ├── parser_str.py     # .str file parser
│   │   └── parser_grd.py     # .grd file parser
│   ├── models/               # SQLAlchemy models
│   │   └── project.py
│   └── db/
│       └── base.py
└── tests/
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

## License

GPL-3.0 (same as SHYFEM)

## Links

- [SHYFEM Project](https://github.com/shyfem/shyfem)
- [SHYFEM Documentation](https://shyfem.readthedocs.io/)
- [Python Shiny](https://shiny.posit.co/py/)
