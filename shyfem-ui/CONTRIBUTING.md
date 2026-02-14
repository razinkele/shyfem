# Contributing to SHYFEM UI

## Development Setup

```bash
# Clone and enter the UI directory
cd shyfem-ui

# Option A: Using micromamba (recommended)
micromamba create -f environment.yml
micromamba activate shiny

# Option B: Using pip
pip install -e ".[dev]"
```

## Running the App

```bash
# Local development mode
shyfem-ui --reload

# Or directly
python -m shyfem_ui.app
```

## Code Style

- **Formatter:** Black (line length 100)
- **Linter:** Ruff (rules: E, F, W, I, UP, B)
- **Type hints:** Use throughout, `X | None` preferred over `Optional[X]`

```bash
# Check lint
make lint

# Format code
make format
```

## Testing

```bash
# Unit tests
make test

# Unit tests with coverage
make coverage

# E2E browser tests (installs Chromium automatically)
make e2e
```

## Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run ruff, black, and basic file checks on every commit.

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `shyfem_ui/pages/` | One module per tab (home, grid_prep, simulation, etc.) |
| `shyfem_ui/components/` | Reusable Shiny modules (grid_map, str_editor, etc.) |
| `shyfem_ui/services/` | Backend logic (parsers, job queue, wrapper, reports) |
| `shyfem_ui/models/` | SQLAlchemy models (Project, Grid, Simulation, Job) |
| `shyfem_ui/db/` | Database engine, session management, Alembic migrations |
| `tests/` | pytest unit tests + Playwright E2E tests |

## Pull Request Checklist

- [ ] `make lint` passes with no errors
- [ ] `make test` passes (387+ tests, 0 new failures)
- [ ] New code has tests where applicable
- [ ] No secrets or credentials in committed files
- [ ] Commit messages follow conventional commits (`feat:`, `fix:`, `docs:`, etc.)

## Commit Message Convention

```
type: short description

Optional longer explanation.

Co-Authored-By: Your Name <email>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `ci`, `chore`

## Database Migrations

When modifying SQLAlchemy models:

```bash
# Generate a new migration
python -m alembic -c alembic.ini revision --autogenerate -m "description"

# Apply migrations
python -m alembic -c alembic.ini upgrade head
```

## Adding a New Page

1. Create `shyfem_ui/pages/mypage.py` with `mypage_ui()` and `mypage_server()` functions
2. Add the `ui.nav_panel` in `app.py:_build_ui()`
3. Call `mypage.mypage_server(...)` in `app.py:_build_server()`
4. Add tests in `tests/test_mypage.py`
