# SHYFEM — Copilot Instructions

SHYFEM (System of HydroDYnamic Finite Element Modules) is a finite-element hydrodynamic
model for lagoons, coastal seas, estuaries, and lakes. Two independently versioned parts
live in one repo:

- **Core** (Fortran 90/95+, ~1000 files) — `src/`, built with GNU Make. Version `VERSION`.
- **Web UI** (`shyfem-ui/`, Python Shiny) — versioned separately in `shyfem-ui/pyproject.toml`.

## Build & test — Fortran core

```bash
make fem                                                  # serial-style NODE build
PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr   # MPI
make clean && make fem                                    # clean rebuild
make fem COMPILER_PROFILE=SPEED                           # -O3 -march=native (NORMAL default)
```

Run the verification test case (the standard regression check):

```bash
cd testcases/examples/mar_menor
make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str  # serial
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

CI (`.github/workflows/fortran-ci.yml`) builds the NODE binary, runs mar_menor, and runs
static lint gates:

```bash
./bin/check_implicit_none.py src/shyfem --max-violations 0   # src/shyfem, src/tools must stay clean
./bin/check_implicit_none.py src/utils  --max-violations 31  # src/utils ratchet — never regress
```

**MPI gotcha (critical):** a bare `make fem` silently links Intel MPI on the dev box and the
binary crashes at startup inside `MPI_Init` even though it compiled and linked cleanly.
Always build *and* run MPI with `PATH=/usr/bin:$PATH` to force OpenMPI. Verify with
`ldd src/shyfem/shyfem | grep mpi` → must show `libmpi.so.40` (OpenMPI), not `libmpi.so.12`
(Intel). "Build compiles" ≠ "build runs."

## Build & test — Python UI (`shyfem-ui/`)

```bash
cd shyfem-ui
pip install -e ".[dev]"           # or: micromamba create -f environment.yml && micromamba activate shiny
make lint                         # ruff check + black --check (line length 100)
make format                       # black + ruff --fix
make test                         # pytest tests/  (387+ tests)
make coverage
make e2e                          # Playwright browser tests (auto-installs Chromium)
```

Run a single test / single case:

```bash
CONDA_PREFIX="" python -m pytest tests/test_access_control.py -v
CONDA_PREFIX="" python -m pytest tests/test_access_control.py::test_name -v
```

- Use `CONDA_PREFIX=""` when running pytest inside the shiny env.
- Playwright tests are ignored by default (`--ignore-glob=tests/test_playwright_*.py`); E2E
  only runs on `pull_request`, never on pushes to `main` — open a PR to exercise them.
- UI tests can pass locally but fail in CI because a checked-out `shyfem-ui/.env` overrides
  config defaults a fresh CI checkout lacks. To reproduce CI: move `.env` aside first
  (`mv shyfem-ui/.env /tmp/ && <pytest…>; mv /tmp/.env shyfem-ui/`).

## Architecture — big picture

- Main loop: `src/shyfem/shyfem_subs.f90`; hydrodynamics: `src/shyfem/hydrodynamic.f90`;
  scalar transport: `src/shyfem/concentration.f90` (+ `concentration_omp.f90`).
- MPI layer: `src/utils/shympi/` (18 files). SHYFEM is fundamentally an MPI-NODE codebase —
  there is no maintained pure-serial path (`lagrange_mpi.f90` calls MPI collectives directly);
  "serial" means running the NODE binary single-process.
- Runtime parameters: `src/utils/generic/para.f90` — module `para` exposes `getpar`/`dgetpar`.
- Physical constants: `src/shyfem/mod_physical_constants.f90`.
- Build config: `Rules.make` (profiles, MPI/OMP/PETSc switches); recursive Makefiles under `src/`.
- UI layout (`shyfem-ui/shyfem_ui/`): `pages/` one module per tab, `components/` reusable Shiny
  modules, `services/` backend logic (parsers, job queue, wrapper, reports),
  `models/` SQLAlchemy models, `db/` engine + Alembic migrations.

## Conventions — Fortran (enforced; see `.claude/skills/fortran-conventions/SKILL.md`)

Do:
- `implicit none` in every program unit; `intent(in/out/inout)` on all arguments.
- `allocate(..., stat=ierr)` with error check; `open(newunit=iu, ..., iostat=ierr)` — never
  hardcoded unit numbers.
- `use para` for `getpar`/`dgetpar` (module functions); `use mod_physical_constants` for
  pi/gravity/vonkarman.
- Single-line save init: `integer, save :: icall = 0`.
- Structured control flow (`do/exit/cycle`, `if/else`, `select case`).

Don't:
- `real getpar` / `double precision dgetpar` external declarations; GOTO; hardcoded unit
  numbers; local pi/grav/vonkarman constants; three-line `save`/`data` init; bare `stop` in
  MPI paths (use `shympi_abort_internal`).

## Conventions — Python UI

- Black (line length 100) + Ruff (E, F, W, I, UP, B); type hints throughout, `X | None` over
  `Optional[X]`.
- Recurring security/reactive failure modes to avoid (see `.claude/agents/ui-security-reviewer.md`):
  `get_current_user()` returns `None` across the Shiny reactive/WebSocket layer — never gate a
  read/write on an inline `if user:` (fails open in prod); route through
  `services/access_control.py`. `input.current_user_role()` is client-spoofable — cosmetic only,
  never an authorization boundary. Confine user file paths to the requesting user's home, not the
  shared `work_dir` (IDOR). Never call `Shiny.setInputValue(...)` synchronously in a
  `shiny:connected` handler (kills the session). Prefer a user-facing error over a silent
  fallback that yields wrong results.

## Versioning & git

- Core: `make bump-patch|bump-minor|bump-major` bumps `VERSION` + `src/utils/shyutil/version.f90`,
  commits, and tags `vX.Y.Z` (UI untouched).
- UI releases independently: edit `shyfem-ui/pyproject.toml`, `pip install -e shyfem-ui`, tag
  `shyfem-ui-vX.Y.Z`.
- Conventional commits (`feat:`, `fix:`, `docs:`). Docs-only (`**/*.md`) changes skip CI.
- After editing Fortran, verify `make fem` still compiles; after editing UI, run `make test`.

## Reference docs

`DEVELOPER_GUIDE.md` (architecture, modules, build system) · `CODEBASE_ANALYSIS.md` ·
`shyfem-ui/CONTRIBUTING.md` · `docs/shyfem_manual.pdf`.
