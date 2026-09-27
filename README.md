# SHYFEM

**System of HydrodYnamic Finite Element Modules**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![SHYFEM core](https://img.shields.io/badge/SHYFEM%20core-8.4.1-green)](https://github.com/razinkele/shyfem/releases/tag/v8.4.1)
[![shyfem-ui](https://img.shields.io/badge/shyfem--ui-0.6.0-blue)](https://github.com/razinkele/shyfem/releases/tag/shyfem-ui-v0.6.0)
![Fortran](https://img.shields.io/badge/Fortran-90%2F95%2B-purple)

A finite element model for hydrodynamic simulation of lagoons, coastal seas, estuaries, and lakes. SHYFEM solves the oceanographic primitive equations in both 2D and 3D using an unstructured triangular mesh with a semi-implicit time-stepping algorithm.

---

## Features

- **Unstructured mesh** --- triangular finite elements adapt to complex coastlines and bathymetry
- **2D / 3D** --- shallow-water or full baroclinic with arbitrary vertical levels
- **Wetting and drying** --- mass-conserving tidal flat simulation
- **Turbulence** --- GOTM coupling (k-epsilon, Munk-Anderson, etc.)
- **Transport** --- advection-diffusion for temperature, salinity, and passive tracers
- **Lagrangian tracking** --- particle transport with MPI support
- **Sediment transport** --- two-way coupling with hydrodynamics
- **Ecological models** --- BFM, EUTRO, AquaBC
- **Parallel execution** --- MPI domain decomposition + OpenMP shared-memory
- **PETSc solver** --- optional iterative solver for large meshes (100k+ nodes)
- **Web UI** --- browser-based simulation setup, run management, and post-processing

## Quick Start

### Prerequisites

| Dependency | Required | Notes |
|---|---|---|
| `gfortran` | Yes | GCC Fortran compiler |
| `gcc` | Yes | C compiler |
| `make` | Yes | GNU Make |
| `libopenmpi-dev` | For MPI | OpenMPI (not Intel MPI) |
| `libmetis-dev` | For MPI | Mesh partitioning |
| `libpetsc-dev` | For PETSc | Optional iterative solver |
| `libnetcdf-dev` | Optional | NetCDF output |
| `libgotm-dev` | Optional | GOTM turbulence (bundled) |

### Build

```bash
# Clone and build (serial)
git clone https://github.com/SHYFEM-model/shyfem.git
cd shyfem
make fem

# MPI build (OpenMPI required)
PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr

# Hybrid MPI+OpenMP
PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr

# PETSc solver
make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real
```

### Run a Test Case

```bash
cd testcases/examples/mar_menor
make init
shyfem mm_hyd_00.str

# MPI (4 processes)
mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

### Build Profiles

| Profile | Flag | Use Case |
|---|---|---|
| `NORMAL` (default) | `-O2`, FPE traps | Development |
| `CHECK` | `-O0 -g -fcheck=all` | Debugging |
| `SPEED` | `-O3 -march=native` | Production benchmarks |
| `SPEED_PGO_GEN` | Instrumented | PGO training pass |
| `SPEED_PGO_USE` | Profile-optimized | PGO production |

```bash
make fem COMPILER_PROFILE=SPEED
```

## Web UI

SHYFEM includes a browser-based interface for simulation management:

```bash
cd shyfem-ui
pip install -e .
python -m shyfem_ui.app
```

Features: grid visualization (deck.gl), physics configuration, parameter validation, job queue, ensemble runs, post-processing, and Lagrangian particle visualization.

See [shyfem-ui/README.md](shyfem-ui/README.md) for details.

## Directory Structure

```
src/
  shyfem/       Main model source (hydrodynamics, transport, turbulence)
  tools/        Pre/post-processing tools (mesh, plotting, partitioning)
  utils/        Shared utilities (MPI layer, I/O, numerics)
  external/     Third-party code (GOTM, SPARSKIT)
  contrib/      Ecological models (BFM, EUTRO, AquaBC)
testcases/      Validation and example cases
shyfem-ui/      Web UI application
docs/           Documentation and manuals
bin/            Executables and helper scripts
```

## Documentation

- **[User Manual](docs/shyfem_manual.pdf)** --- comprehensive guide to model setup and usage
- **[Developer Guide](DEVELOPER_GUIDE.md)** --- architecture, coding conventions, build system
- **[Changelog](CHANGELOG.md)** --- version history and release notes
- **[Codebase Analysis](CODEBASE_ANALYSIS.md)** --- technical analysis and improvement status

## Versioning

SHYFEM uses [Semantic Versioning](https://semver.org/). The Fortran **core** and the Python **UI** are versioned **independently**.

**Core** --- currently `8.4.1`, tag `v8.4.1`:

- `VERSION` --- primary version record
- `src/utils/shyutil/version.f90` --- compiled into the binary

```bash
# Bumps VERSION + version.f90, commits, and tags vX.Y.Z (UI untouched):
make bump-patch   # 8.4.1 -> 8.4.2
make bump-minor   # 8.4.1 -> 8.5.0
make bump-major   # 8.4.0 -> 9.0.0
```

**UI** --- currently `0.6.0`, tag `shyfem-ui-v0.6.0`:

- `shyfem-ui/pyproject.toml` --- single source of truth; `shyfem_ui.__version__` derives from it via package metadata

The UI releases on its own cadence (not touched by `make bump-*`): edit `pyproject.toml`, run `pip install -e shyfem-ui` to refresh the metadata, then tag `shyfem-ui-vX.Y.Z`.

## Performance

Benchmarks on the Mar Menor test case (1152 timesteps):

| Configuration | Time | Speedup |
|---|---|---|
| Serial | 2.78 s | 1.0x |
| MPI 4 processes | 1.70 s | 1.6x |
| MPI 4P + OMP 2T | 1.67 s | 1.7x |

Larger meshes (100k+ elements, 50+ levels) show significantly better scaling.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Follow the [coding conventions](DEVELOPER_GUIDE.md#coding-conventions)
4. Run tests (`cd testcases/examples/mar_menor && make init && shyfem mm_hyd_00.str`)
5. Submit a pull request

## License

SHYFEM is free software under the [GNU General Public License v3.0](COPYING).

Copyright (C) The Shyfem Team 1985-2025.

## Contact

Georg Umgiesser
Oceanography, ISMAR-CNR
Arsenale Tesa 104, Castello 2737/F
30122 Venezia, Italy

E-Mail: georg.umgiesser@ismar.cnr.it

## Citation

If you use SHYFEM in your research, please cite:

> Umgiesser, G., Melaku Canu, D., Cucco, A., and Solidoro, C. (2004).
> A finite element model for the Venice Lagoon. Development, set up, calibration and validation.
> *Journal of Marine Systems*, 51(1-4), 123-145.
