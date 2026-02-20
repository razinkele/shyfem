# SHYFEM User Manual

**System of HydroDYnamic Finite Element Modules**
**Version 8.1.1 — Sankt Antonius stable edition**

Copyright (C) 1985-2025 Georg Umgiesser and contributors
Licensed under the GNU General Public License v3.0

---

## Table of Contents

1. [Overview](#1-overview)
2. [Installation and Compilation](#2-installation-and-compilation)
3. [Grid Preparation](#3-grid-preparation)
4. [Parameter File (STR) Format](#4-parameter-file-str-format)
5. [Running the Model](#5-running-the-model)
6. [Boundary Conditions](#6-boundary-conditions)
7. [Physical Models](#7-physical-models)
8. [Output and Post-Processing Tools](#8-output-and-post-processing-tools)
9. [MPI Parallel Computing](#9-mpi-parallel-computing)
10. [File Formats](#10-file-formats)
11. [SHYFEM-UI Web Interface](#11-shyfem-ui-web-interface)
12. [Parameter Reference](#12-parameter-reference)
13. [Troubleshooting and FAQ](#13-troubleshooting-and-faq)

---

## 1. Overview

### 1.1 What is SHYFEM?

SHYFEM is a finite element program package for resolving hydrodynamic equations in lagoons, coastal seas, estuaries, and lakes. It uses unstructured triangular finite elements with a semi-implicit time integration scheme, making it especially suitable for domains with complicated geometry and bathymetry.

Key capabilities:

- **2D and 3D hydrodynamics** — Solves the oceanographic primitive equations with both two- and three-dimensional formulations
- **Variable resolution** — Unstructured triangular mesh allows fine resolution where needed, coarse elsewhere
- **Wetting and drying** — Mass-conserving treatment of tidal flats that alternately flood and dry
- **Baroclinic dynamics** — Full density-driven circulation from temperature and salinity gradients
- **Turbulence closure** — GOTM library integration, k-epsilon, and Munk-Anderson schemes
- **Scalar transport** — Temperature, salinity, and arbitrary tracer transport with TVD advection
- **Lagrangian particles** — 3D particle tracking for dispersion studies
- **Sediment transport** — Multi-class sediment erosion, transport, and deposition
- **Wave coupling** — Interface with WWMIII and WaveWatch III spectral wave models
- **Ecological models** — EUTRO (WASP-derived), AQUABC, and BFM biogeochemical models
- **Water renewal time** — Built-in computation of residence and renewal times
- **MPI parallelization** — Domain decomposition via METIS for large-scale simulations
- **OpenMP parallelization** — Task-based parallelism for scalar transport

### 1.2 Technical Characteristics

| Feature | Description |
|---------|-------------|
| Numerical method | Unstructured triangular finite elements |
| Time integration | Semi-implicit (explicit advection, implicit barotropic) |
| Vertical discretization | Z-layers, sigma layers, or hybrid z-sigma |
| Primary language | Fortran 90/95+ (~1,087 files), C (~285 files) |
| Build system | GNU Make with recursive Makefiles |
| Parallelization | MPI (domain decomposition) + OpenMP (task-based) |
| License | GNU General Public License v3.0 |

### 1.3 Directory Structure

```
shyfem/
├── bin/          Executables and helper scripts
├── docs/         LaTeX documentation source, PDF manual
├── include/      Fortran include files (.h)
├── lib/          Compiled libraries and .mod files
├── src/
│   ├── shyfem/   Main model source (135 files)
│   ├── utils/    Utility libraries
│   │   ├── generic/     Self-sufficient utilities
│   │   ├── modules/     Module definitions
│   │   ├── shympi/      MPI implementation (18 files)
│   │   ├── shyutil/     Basic functionality
│   │   └── shyutilmpi/  MPI-dependent utilities
│   ├── tools/    Pre/post-processing tools
│   │   ├── grid/        Grid visualization (X11)
│   │   ├── mesh/        Mesh generator
│   │   ├── shypre/      Preprocessor (.grd → .bas)
│   │   ├── shybas/      Basin file utilities
│   │   ├── shyparts/    MPI partitioning
│   │   ├── shyelab/     Output elaboration
│   │   ├── shyplot/     Plotting
│   │   └── shynetcdf/   NetCDF interface
│   ├── contrib/  Contributed components (ecological models)
│   └── external/ Third-party code (GOTM, SparsKit)
├── testcases/    Test cases and validation examples
├── Rules.make    Compiler and build configuration
├── Makefile      Top-level build orchestration
└── shyfem-ui/    Web-based user interface (Python/Flask)
```

### 1.4 SHYFEM Consortium

SHYFEM is maintained by a consortium of institutions:

- **CNR-ISMAR** (Venice, Italy) — System engineering, hydrodynamics, assimilation
- **CNR-IAS** — Lagrangian model, renewal times
- **INOGS** — Ecological modeling, OMP parallelization
- **Klaipeda University MRI** — Ecological modeling, AquaBC
- **Istanbul University** — Ecological modeling, AquaBC
- **CMCC** — MPI parallelization

Contact: Georg Umgiesser — georg.umgiesser@ismar.cnr.it

---

## 2. Installation and Compilation

### 2.1 Prerequisites

SHYFEM runs on Linux operating systems. The following software must be installed:

- **Fortran compiler** — GFortran (recommended), Intel ifort/ifx, PGI/NVIDIA nvfortran, or IBM xlf
- **C compiler** — GCC, Intel icc/icx, or IBM xlc
- **GNU Make**
- **X11 libraries** — Required for the `grid` visualization tool
- **NetCDF libraries** (optional) — For NetCDF output format
- **METIS library** (optional) — Required for MPI domain decomposition
- **OpenMPI** (optional) — For MPI parallel runs

On Debian/Ubuntu systems:

```bash
sudo apt install gfortran gcc make libx11-dev
# Optional:
sudo apt install libnetcdf-dev libnetcdff-dev libmetis-dev openmpi-bin libopenmpi-dev
```

Run the setup check script to verify your environment:

```bash
cd femcheck
./check_setup.sh
```

### 2.2 Compiler Configuration

Edit `Rules.make` to select your compiler and options:

```makefile
# Fortran compiler: GNU_GFORTRAN, INTEL, PORTLAND, IBM, PGI
FORTRAN_COMPILER = GNU_GFORTRAN

# C compiler: GNU_GCC, INTEL, IBM, PGI
C_COMPILER = GNU_GCC

# Compiler profile: NORMAL, CHECK, SPEED
COMPILER_PROFILE = NORMAL
```

Compiler profiles control optimization and debugging:

| Profile | Optimization | Debug Info | Bounds Check | Warnings |
|---------|-------------|------------|--------------|----------|
| NORMAL | `-O` | Yes | No | Yes |
| CHECK | None | Yes | Yes | Yes |
| SPEED | `-O3` | No | No | No |

### 2.3 Build Commands

```bash
# Build everything (model + tools)
make fem

# Build with MPI support (requires OpenMPI and METIS)
# For gfortran, ensure OpenMPI is used (not Intel MPI):
PATH=/usr/bin:$PATH make fem

# Build only the main model
cd src/shyfem && make

# Clean and rebuild
make clean && make fem
# or for a complete clean:
make cleanall && make fem

# Build documentation (LaTeX → PDF)
make doc
```

### 2.4 Build Configuration Options

These options in `Rules.make` control optional features:

```makefile
# Parallelization
PARALLEL_OMP = false          # OpenMP (true/false)
PARALLEL_MPI = NODE           # MPI: NONE, NODE, ELEM

# Partitioning library (required for MPI)
PARTS = METIS                 # NONE, METIS, PARMETIS
METISDIR = /usr               # Path to METIS installation

# Matrix solver
SOLVER = SPARSKIT             # GAUSS, SPARSKIT, PARDISO, PETSC, PARALUTION

# NetCDF output
NETCDF = false                # true/false
NETCDFDIR = ...               # Path to NetCDF C library
NETCDFFDIR = ...              # Path to NetCDF Fortran library

# GOTM turbulence library (recommended for 3D)
GOTM = true                   # true/false

# Ecological models
ECOLOGICAL = NONE             # NONE, EUTRO, AQUABC, BFM

# Mercury module
MERCURY = false               # true/false

# Fluid mud module (experimental)
FLUID_MUD = false             # true/false

# Wave model coupling
WW3 = false                   # true/false (requires PARMETIS + MPI + NetCDF)

# NUOPC coupled framework
NUOPC = false                 # true/false
```

### 2.5 Verifying the Build

After building, executables are placed in `bin/`. Test with the Mar Menor example:

```bash
cd testcases/examples/mar_menor
make init
PATH=/path/to/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

---

## 3. Grid Preparation

### 3.1 Workflow Overview

The grid preparation workflow converts raw geographic data into the binary basin file that SHYFEM uses:

```
Coastline/bathymetry data
        │
        ▼
  ┌─────────────┐
  │  grid (X11)  │   Interactive editing of boundary lines
  └──────┬──────┘
         │ .grd file (nodes + lines)
         ▼
  ┌─────────────┐
  │    mesh      │   Triangular mesh generation
  └──────┬──────┘
         │ .grd file (nodes + elements)
         ▼
  ┌─────────────┐
  │   shypre     │   Preprocessing (renumbering, optimization)
  └──────┬──────┘
         │ .bas file (binary basin)
         ▼
       shyfem       Ready for simulation
```

### 3.2 The GRD File Format

The `.grd` file is a text-based format containing nodes, elements, and lines. Each line in the file starts with an item type code:

```
0  comment line (anything following is ignored)
1  n  t  x  y  [d]           — node definition
2  n  t  ntot  n1 n2 n3 [d]  — element definition (triangle)
3  n  t  ntot  n1 n2 ...  [d] — line definition
```

Fields:
- `n` — Item number (must be unique per item type)
- `t` — Type code (0 = default, 1 = external coastline, 2 = island, 4 = internal line)
- `x, y` — Coordinates (Cartesian or geographic)
- `d` — Depth (optional; -999 if not specified)
- `ntot` — Number of nodes in element/line
- `n1, n2, ...` — Node numbers defining the element or line

Example — one triangle element:

```
0 Example: three nodes forming one element

1 11 0 10. 10.
1 12 0 20. 20.
1 15 0 10. 20.

2 7 0 3 11 12 15
```

Rules:
- Lines may be split; continuation lines must start with a blank
- Depth `d` must not be on a separate line
- Item numbers need not be consecutive
- Items can appear in any order
- Closed lines (first node = last node) define polygons

### 3.3 Line Types for Mesh Generation

When preparing boundary lines for the mesh generator:

| Type | Description |
|------|-------------|
| 1 | External coastline (outermost boundary) |
| 2 | Internal islands (closed lines inside domain) |
| 4 | Internal constraint lines (elements do not cross) |

### 3.4 The `grid` Tool

`grid` is an interactive X11 program for viewing and editing GRD files:

```bash
grid mycoast.grd
```

Features:
- View nodes, lines, and elements
- Add, move, and delete nodes
- Create and edit boundary lines
- Show node/element numbers
- Zoom and pan

Requirements: X11 environment. If connecting via SSH, use `ssh -X`.

### 3.5 The `mesh` Tool

`mesh` generates a triangular finite element mesh from boundary lines:

```bash
mesh [-options] input.grd
```

Key options:
- `-g value` — Controls gradation (transition from boundary to interior node spacing)

The mesh generator creates triangular elements filling the domain defined by the boundary lines. Nodes on the boundary should have reasonable spacing — too fine relative to interior spacing can cause errors (CircumCircle errors).

Tips:
- If you get CircumCircle errors, increase boundary node spacing
- Internal islands are defined as closed lines with type 2
- Use the `-g` option to control mesh gradation near boundaries

### 3.6 The `shypre` Tool

`shypre` converts a GRD file (with elements and bathymetry) into the binary basin file (`.bas`) used by SHYFEM:

```bash
shypre input.grd
```

This produces `input.bas` containing:
- Renumbered and optimized mesh connectivity
- Nodal coordinates and bathymetry
- Element-node relationships

### 3.7 The `shybas` Tool

`shybas` provides information and operations on basin files:

```bash
# Display basin information
shybas basin.bas

# Write depth values
shybas -depth basin.bas

# Interpolate bathymetry
shybas -interp basin.bas
```

### 3.8 Interpolating Bathymetry

If your GRD file has nodes without depth values, bathymetry must be interpolated from external data:

1. Prepare bathymetric data points
2. Use `shybas` interpolation or external tools
3. Ensure all nodes have valid depth values before running the model

### 3.9 Converting from Other Mesh Formats

SHYFEM can import meshes from Gmsh (`.msh`) and GR3 formats. Conversion utilities are available in the tools directory.

---

## 4. Parameter File (STR) Format

### 4.1 Structure

The STR file is the main configuration file for SHYFEM simulations. It is an ASCII text file composed of named sections delimited by `$section_name` and `$end`:

```
$section_name
    parameter1 = value1
    parameter2 = value2
    ! This is a comment
    # This is also a comment
$end
```

Rules:
- Comments start with `!` or `#`
- Multiple parameters can appear on one line
- String values can be quoted with single quotes: `wind = 'mywind.fem'`
- Dates can be specified as strings: `itanf = '2021-01-01'`
- Time durations can use units: `idt = '30s'`, `idtout = '1h'`, `idtrst = '1d'`

### 4.2 Section Overview

| Section | Purpose |
|---------|---------|
| `$title` | Simulation title and grid reference (must be first) |
| `$para` | Main simulation parameters (time, physics, output) |
| `$levels` | Vertical layer depths (meters) |
| `$name` | Input/output file paths |
| `$bound1`, `$bound2`, ... | Boundary conditions |
| `$extra` | Extra output nodes for time series |
| `$flux` | Flux section definitions for discharge calculation |
| `$volume` | Volume monitoring polylines |
| `$wind` | Inline wind data (alternative to external file) |
| `$waves` | Wave model parameters |
| `$sedtr` | Sediment transport parameters |
| `$wrt` | Water renewal time parameters |
| `$lagrg` | Lagrangian particle tracking parameters |
| `$proj` | Coordinate projection parameters |

### 4.3 Section `$title`

Must be the first section. Contains exactly three lines:

```
$title
    Free one-line description of the simulation
    simulation_name
    basin_name
$end
```

- **Line 1:** Description (free text)
- **Line 2:** Simulation name — output files will use this as the base name
- **Line 3:** Basin name — the `.bas` file to use (without extension)

### 4.4 Section `$para`

Contains the main simulation parameters. See [Section 12](#12-parameter-reference) for the complete parameter reference table.

#### Required Parameters

```
$para
    itanf = '2021-01-01'    ! Start time
    itend = '2021-12-31'    ! End time
    idt = '30s'             ! Time step
    date = 20210101         ! Reference date (YYYYMMDD)
$end
```

#### Output Intervals

Output files are only written when their time step is set to a value greater than 0:

```
$para
    idtout = '1h'     ! Hydrodynamic output (.shy)
    idtext = '300s'   ! Extra point time series (.ext)
    idtcon = '1h'     ! Scalar/concentration output (.shy)
    idtrst = '1d'     ! Restart file (.rst)
    idtflx = '1h'     ! Flux/discharge output (.flx)
    idtres = '1h'     ! Residual data
    idtrms = '1h'     ! RMS velocity output
    idtvol = '1h'     ! Volume monitoring
$end
```

### 4.5 Section `$levels`

Specifies the bottom of each vertical layer in meters (for 3D simulations):

```
$levels
    1 2 3 4 5 7 10 15 20 30 50
$end
```

This creates layers with bottoms at 1m, 2m, 3m, ..., 50m. The first layer extends from the surface to 1m depth.

Alternatively, use `dzreg` in `$para` for regular layer spacing:

```
$para
    dzreg = 2.0    ! Create layers every 2 meters
$end
```

### 4.6 Section `$name`

Specifies input file paths for forcing, initial conditions, and other data:

```
$name
    wind = 'wind.fem'           ! Wind forcing file
    qflux = 'meteo.fem'         ! Heat flux data
    rain = 'rain.fem'           ! Precipitation
    tempin = 'temp_ic.fem'      ! Initial temperature (3D)
    saltin = 'salt_ic.fem'      ! Initial salinity (3D)
    restrt = 'sim.rst'          ! Restart file
    gotmpa = 'gotmturb.nml'     ! GOTM turbulence parameters
$end
```

### 4.7 Section `$extra`

Defines monitoring nodes where time series are written at high frequency:

```
$extra
    1001  'Station Alpha'
    1002  'Station Beta'
    1003  'Harbor entrance'
$end
```

Output is written to the `.ext` file with interval `idtext`.

### 4.8 Section `$flux`

Defines cross-sections for discharge computation:

```
$flux
    1001 1002 1004 'Inlet section'
    35 37 46 'Channel section'
    407 301 'Bridge section'
$end
```

Nodes in each section must be adjacent (form a continuous line). Each section is terminated by a description string. Output is written to the `.flx` file.

### 4.9 Full Example STR File

```
$title
    3D baroclinic simulation of coastal lagoon
    lagoon_sim
    lagoon_grid
$end

$para
    date = '2021-01-01'

    itanf = '2021-01-01'    itend = '2021-12-31'    idt = '30s'
    itmout = '2021-01-01'   idtout = '1h'
    itmflx = '2021-01-01'   idtflx = '1h'
    itmext = '2021-01-01'   idtext = '1h'
    itmcon = '2021-01-01'   idtcon = '1h'
    itmrst = '2021-01-01'   idtrst = '1d'

    ilin = 0               ! Include nonlinear advective terms
    itsplt = 2             ! Variable time step
    coumax = 0.90          ! Maximum Courant number
    idtsyn = '3600s'       ! Synchronize every hour
    idtmin = 0.1           ! Allow sub-second time steps

    ampar = 0.60    azpar = 0.60    aapar = 0

    icor = 1    dlat = 45.    isphe = 0

    ireib = 5   czdef = 0.002       ! Quadratic drag friction

    iwtype = 3  itdrag = 0  dragco = 0.00250

    ilytyp = 3  hlvmin = 0.5        ! Merge thin bottom layers

    ibarcl = 1  iturb = 1           ! Baroclinic + GOTM turbulence
    idhtyp = 2                      ! Smagorinsky horizontal diffusion
    itvd = 2    itvdv = 1   rstol = 0.85

    diftur = 0.001  vistur = 0.001

    salref = 35     temref = 18
    isalt = 1       itemp = 1
    thpar = 0.2     shpar = 0.2

    iheat = 0   hdecay = 2  botabs = 0
    ievap = 0
$end

$levels
    1 1.5 2 2.5 3 3.5 4 4.5 5 6 7 8 9 10 12 14 16 18 20 22 24 26 30 34
$end

$bound1     ! Open sea boundary
    kbound = 26861 26860 26859 26858 26857 26856 26855 26854 26853 26852
             26851 26850 26849 26848 26847 26846 26845 26844 26843 26842
             26841
    ibtyp = 1
    saltn = 'salt_bnd.fem'
    tempn = 'temp_bnd.fem'
    boundn = 'level.dat'
$end

$bound2     ! River input
    kbound = 34137 34132 34136
    ibtyp = 2
    zref = 140              ! Constant discharge (m3/s)
    salt = 0.
    temp = 23.8
$end

$name
    gotmpa = 'gotmturb.nml'
    saltin = 'salt_ic.fem'
    tempin = 'temp_ic.fem'
    wind = 'wind.fem'
    rain = 'rain.fem'
    qflux = 'meteo.fem'
    restrt = 'sim.rst'
$end
```

---

## 5. Running the Model

### 5.1 Basic Usage

```bash
shyfem simulation.str
```

The model reads the STR parameter file and begins the simulation. Output files are written to the current directory using the simulation name defined in `$title`.

### 5.2 Input Requirements

At minimum, SHYFEM requires:

1. **A basin file** (`.bas`) — Created by `shypre` from a `.grd` file
2. **A parameter file** (`.str`) — Simulation configuration
3. **Time parameters** — `itanf`, `itend`, `idt`, and `date` in `$para`

For physically meaningful simulations, you typically also need:

- Wind forcing data
- Open boundary conditions (water level or discharge)
- For 3D: vertical layer specification, initial T/S fields, turbulence parameters

### 5.3 Initial Conditions

Spatially constant initial conditions can be set in `$para`:

```
$para
    temref = 18.0     ! Initial temperature (°C)
    salref = 35.0     ! Initial salinity (PSU)
    conref = 0.0      ! Initial tracer concentration
$end
```

For spatially variable 3D initial conditions, provide FEM-format files in `$name`:

```
$name
    tempin = 'temp_initial.fem'
    saltin = 'salt_initial.fem'
    zinit = 'zeta_initial.fem'
    conzin = 'conz_initial.fem'
$end
```

### 5.4 Restart

To continue a simulation from a previous run:

1. **Generate restart file** — Set `idtrst` in the first run:
   ```
   idtrst = '1d'      ! Write restart every day
   ! or
   idtrst = -1        ! Write only at the last time step
   ```

2. **Use restart in next run** — Specify the restart file and time:
   ```
   $name
       restrt = 'previous_sim.rst'
   $end
   $para
       itrst = -1     ! Use last record in restart file
   $end
   ```

The `flgrst` parameter controls which variables are read from the restart:
- `1` — Hydro values
- `10` — Depth values
- `100` — T/S values
- `1000` — Tracer concentration
- `10000` — Vertical velocities
- `100000` — Ecological variables
- `-1` (default) — All variables (equivalent to `111111`)

### 5.5 Output Files

| Extension | Content | Controlled by |
|-----------|---------|---------------|
| `.shy` | Hydrodynamic output (water levels, velocities) | `idtout` |
| `.shy` | Scalar output (T, S, tracers) | `idtcon` |
| `.ext` | Time series at extra points | `idtext` |
| `.flx` | Flux/discharge through sections | `idtflx` |
| `.rst` | Restart file | `idtrst` |
| `.res` | Residual data | `idtres` |
| `.nc` | NetCDF output (when `netcdf = 1`) | various |

### 5.6 Offline Mode

SHYFEM can run in offline mode where hydrodynamic fields are read from a previous simulation, and only scalar transport is computed:

```
$para
    idtoff = -1        ! Read offline hydro data
$end
$name
    offlin = 'previous.off'
$end
```

To generate offline data from a full simulation:

```
$para
    idtoff = 3600      ! Write offline data every hour
$end
```

---

## 6. Boundary Conditions

### 6.1 Overview

Open boundary conditions are defined in numbered `$bound` sections. Each section describes one open boundary and specifies:

- Which nodes form the boundary
- The type of boundary condition
- The forcing data (from file or analytically)

### 6.2 Boundary Types

| `ibtyp` | Type | Units | Description |
|---------|------|-------|-------------|
| 0 | None | — | No boundary values specified |
| 1 | Water level | meters | Impose water surface elevation |
| 2 | Flux | m³/s | Impose total discharge through boundary |
| 3 | Internal flux | m³/s | Point source/sink (can be interior node) |
| 4 | Momentum | m⁴/s² | Force input (volume rate × velocity) |

### 6.3 Water Level Boundary

```
$bound1
    kbound = 23 25 28 30 32     ! Boundary nodes (anti-clockwise)
    ibtyp = 1                    ! Water level boundary
    boundn = 'tidal_levels.dat'  ! Time series file
$end
```

The boundary nodes must form a contiguous line with the domain (elements) to the left. This corresponds to anti-clockwise ordering. At least two nodes are required.

### 6.4 Flux/Discharge Boundary

```
$bound2
    kbound = 100 101 102
    ibtyp = 2                    ! Flux boundary
    boundn = 'river_discharge.dat'
$end
```

For a constant discharge, use `zref` instead of a file:

```
$bound2
    kbound = 100 101 102
    ibtyp = 2
    zref = 50.0                  ! Constant discharge of 50 m³/s
$end
```

### 6.5 Internal Point Sources

```
$bound3
    kbound = 500
    ibtyp = 3                    ! Internal point source
    zref = 5.0                   ! 5 m³/s added at this node
    salt = 0.0                   ! Freshwater input
    temp = 15.0                  ! At 15°C
$end
```

With `ibtyp = 3`, the specified discharge is added to each listed node individually (unlike `ibtyp = 2` where the total is distributed across the boundary).

### 6.6 Sinusoidal (Tidal) Boundary

For idealized tidal forcing without a data file:

```
$bound1
    kbound = 23 25 28
    ibtyp = 1
    ampli = 0.70         ! Amplitude ±0.70 m
    period = 43200       ! Period 12 hours (semi-diurnal)
    phase = 10800        ! Phase shift (starts at slack/high water)
    zref = 0.0           ! Mean water level
$end
```

### 6.7 Scalar Boundary Conditions

Temperature, salinity, and tracer concentrations at boundaries can be specified as:

**Constant values:**
```
$bound1
    ...
    temp = 18.0          ! Constant temperature
    salt = 35.0          ! Constant salinity
    conz = 0.0           ! Constant tracer concentration
$end
```

**Time-varying from files:**
```
$bound1
    ...
    tempn = 'temp_boundary.fem'
    saltn = 'salt_boundary.fem'
    conzn = 'conz_boundary.fem'
$end
```

**Ambient value:** Set to -999 to use the ambient water value near the boundary:
```
    temp = -999          ! Use ambient temperature
```

### 6.8 Boundary File Format

ASCII boundary files have two columns: time (seconds) and value:

```
0       0.50
3600    0.45
7200    0.30
10800   0.10
14400  -0.10
...
```

- Time values must be in increasing order
- Data must cover the entire simulation period
- The model interpolates between data points (linear by default, cubic for water levels)

### 6.9 Additional Boundary Options

| Parameter | Description |
|-----------|-------------|
| `zfact` | Scaling factor for boundary values (default 1.0) |
| `ztilt` | Water level tilt across boundary (meters) |
| `ktilt` | Boundary node around which tilting occurs |
| `intpol` | Interpolation order: 1=step, 2=linear, 4=cubic |
| `tramp` | Ramp-up time for discharge boundaries (seconds) |
| `levmin`, `levmax` | Restrict discharge to specific vertical layers |
| `nad` | Suppress nonlinear terms near boundary (number of nodes) |
| `igrad0` | Zero gradient boundary condition (0/1) |
| `tnudge` | Nudging relaxation time for velocity (seconds) |

---

## 7. Physical Models

### 7.1 Advection

By default, SHYFEM uses a linearized formulation (advective terms not included). To enable nonlinear advection:

```
$para
    ilin = 0          ! Include nonlinear advective terms
    itlin = 0         ! 0=FE discretization, 1=semi-Lagrangian
$end
```

When using nonlinear advection, variable time stepping is recommended:

```
$para
    itsplt = 2        ! Variable time step
    coumax = 0.9      ! Maximum Courant number
    idtsyn = 3600     ! Synchronize every hour
$end
```

### 7.2 Coriolis Force

```
$para
    icor = 1          ! 1=beta-plane, 2=f-plane, 0=off
    dlat = 45.0       ! Latitude (degrees N)
    isphe = 0         ! 0=Cartesian, 1=spherical, -1=auto
$end
```

With spherical coordinates (`isphe = 1`), Coriolis is always included regardless of `icor` (set `icor = -1` to suppress).

### 7.3 Bottom Friction

```
$para
    ireib = 5         ! Friction formulation type
    czdef = 0.002     ! Friction coefficient value
$end
```

| `ireib` | Formulation | λ represents | Typical values |
|---------|------------|--------------|----------------|
| 0 | No friction | — | — |
| 1 | Constant R = λ | Linear friction | 0.001–0.01 |
| 2 | Strickler | Strickler coeff. ks | 20–80 m^(1/3)/s |
| 3 | Chezy | Chezy coeff. C | 30–90 m^(1/2)/s |
| 4 | R = λ/H | Depth-dependent | 0.001–0.01 |
| 5 | Quadratic drag | Drag coeff. Cd | 0.001–0.005 |
| 6 | Roughness length | Bottom roughness z0 | 0.001–0.1 m |
| 7 | Auto | Strickler if λ≥1, drag if λ<1 | varies |

For 2D simulations, Strickler (2) or Chezy (3) formulations are preferred. For 3D, use drag coefficient (5) or roughness length (6).

Friction coefficients can also be specified per area code in the `$area` section.

### 7.4 Wetting and Drying

SHYFEM handles tidal flats through mass-conserving wetting and drying:

```
$para
    hzmin = 0.01      ! Minimum water depth retained (m)
    hzoff = 0.05      ! Depth threshold for drying (m)
    hzon = 0.10       ! Depth threshold for rewetting (m)
$end
```

When the total water depth at an element falls below `hzoff`, the element is removed from computation. It is re-inserted when water depth exceeds `hzon`.

### 7.5 Baroclinic Dynamics

Baroclinic dynamics (density-driven flow from T/S gradients) are activated with:

```
$para
    ibarcl = 1        ! Full baroclinic
    temref = 18.0     ! Initial temperature (°C)
    salref = 35.0     ! Initial salinity (PSU)
$end
```

| `ibarcl` | Mode | Description |
|----------|------|-------------|
| 0 | Off | No T/S computation |
| 1 | Full | Baroclinic pressure + T/S transport |
| 2 | Diagnostic | Baroclinic pressure, T/S read from file |
| 3 | Passive | T/S transport only, no feedback to circulation |
| 4 | Nudging | T/S nudged toward observations |
| 5 | Variable settling | Variable settling velocity |

For baroclinic simulations, you typically need:
- Heat flux forcing (meteo data file via `qflux`)
- Precipitation data (via `rain`)
- Initial T/S fields (constant or from file)
- Turbulence closure (`iturb > 0`)

### 7.6 Turbulence Closure

Vertical mixing in 3D simulations is controlled by the turbulence closure scheme:

```
$para
    iturb = 1         ! Turbulence model selection
$end
```

| `iturb` | Model | Description |
|---------|-------|-------------|
| 0 | None | Constant vertical viscosity/diffusivity (`vistur`, `diftur`) |
| 1 | GOTM | General Ocean Turbulence Model (recommended) |
| 2 | k-epsilon | Built-in k-epsilon closure |
| 3 | Munk-Anderson | Empirical stability-dependent mixing |

**GOTM setup** (recommended for 3D):

```
$para
    iturb = 1
$end
$name
    gotmpa = 'gotmturb.nml'     ! GOTM parameter file
$end
```

A default `gotmturb.nml` file is provided with the SHYFEM distribution.

**Constant vertical mixing** (simple alternative):

```
$para
    iturb = 0
    vistur = 0.001    ! Vertical turbulent viscosity (m²/s)
    diftur = 0.001    ! Vertical turbulent diffusivity (m²/s)
$end
```

Typical constant values range from 10⁻² (well-mixed) to 10⁻⁵ (stratified).

### 7.7 Horizontal Mixing

```
$para
    ahpar = 10.0      ! Horizontal viscosity (m²/s)
    dhpar = 5.0       ! Horizontal diffusivity (m²/s)
    idhtyp = 0        ! 0=constant, 1=area-weighted, 2=Smagorinsky
    noslip = 0        ! 0=free-slip, 1=no-slip at boundaries
$end
```

The Smagorinsky formulation (`idhtyp = 2`) computes horizontal diffusion as a function of the local velocity shear and element area, which is generally preferred for variable-resolution meshes.

### 7.8 Scalar Transport (Tracers)

Transport of conservative or decaying tracers:

```
$para
    iconz = 1         ! Number of tracers
    conref = 0.0      ! Initial concentration
    chpar = 5.0       ! Horizontal diffusion for tracers
    itvd = 2          ! TVD advection scheme (recommended)
    itvdv = 1         ! Vertical TVD scheme
$end
```

Tracer decay:

| `idecay` | Type |
|----------|------|
| 0 | No decay (conservative tracer) |
| 1 | Exponential decay (set `contau` for e-folding time in days) |
| 2 | Chapra formulation |

### 7.9 Temperature and Salinity

T/S are activated through the baroclinic module (`ibarcl > 0`). Individual components can be toggled:

```
$para
    ibarcl = 1
    itemp = 1         ! Compute temperature (0/1)
    isalt = 1         ! Compute salinity (0/1)
    temref = 18.0     ! Initial temperature (°C)
    salref = 35.0     ! Initial salinity (PSU)
    thpar = 0.2       ! Horizontal diffusion for temperature
    shpar = 0.2       ! Horizontal diffusion for salinity
$end
```

### 7.10 Heat Flux

The surface heat flux algorithm is controlled by `iheat`:

| `iheat` | Algorithm | Description |
|---------|-----------|-------------|
| 1 | AREG | Adriatic Regional model formulation |
| 2 | POM | Princeton Ocean Model formulation |
| 3 | Gill | Following A. Gill |
| 4 | Dejak | Following Dejak |
| 5 | GOTM | GOTM heat flux module |
| 6 | COARE | COARE 3.0 bulk formula |
| 7 | Direct | Read sensible, latent, longwave from file |
| 8 | MFS | Mediterranean Forecasting System bulk formulae |

Heat flux data file (specified as `qflux` in `$name`) must contain: short-wave solar radiation, air temperature, humidity/wet-bulb temperature, and cloud cover.

Related parameters:

```
$para
    iheat = 1
    hdecay = 2.0      ! Radiation penetration depth (m), 0=surface only
    albedo = 0.06     ! Surface albedo
    ievap = 1         ! Compute evaporation mass flux (0/1)
    irain = 1         ! Compute precipitation mass flux (0/1)
$end
```

### 7.11 Wind Forcing

Wind data can be provided via an external file or inline in the `$wind` section:

```
$name
    wind = 'wind.fem'
$end
$para
    iwtype = 3        ! Wind input format
    itdrag = 0        ! Drag coefficient formula
    dragco = 0.0025   ! Constant drag coefficient
    wsmax = 50.0      ! Maximum allowed wind speed (m/s)
$end
```

Wind input types (`iwtype`):

| Value | Format |
|-------|--------|
| 0 | No wind |
| 1 | Wind speed components (u, v) in m/s |
| 2 | Wind stress (τx, τy) directly specified |
| 3 | Wind speed (m/s) and direction (degrees, 0=N, 90=E) |
| 4 | Wind speed (knots) and direction |

Drag coefficient formulas (`itdrag`):

| Value | Formula |
|-------|---------|
| 0 | Constant (use `dragco`) |
| 1 | Smith and Banke (1975) |
| 2 | Large and Pond (1981) |
| 3 | Wave-dependent (requires WWMIII coupling) |
| 4 | Heat flux-dependent (requires `iheat = 6` or `8`) |

### 7.12 Vertical Layer Configuration

**Z-layers** (default):

```
$levels
    1 2 3 5 8 12 18 25 35 50 75 100
$end
```

**Regular z-layers:**
```
$para
    dzreg = 2.0       ! 2m layer spacing
$end
```

**Sigma layers:**
```
$para
    nsigma = 10       ! 10 equally-spaced sigma layers
$end
```

**Hybrid z-sigma:**
```
$para
    nsigma = 5
    hsigma = 20.0     ! Sigma above 20m, z-layers below
$end
```

Bottom layer treatment (`ilytyp`):

| Value | Treatment |
|-------|-----------|
| 0 | No adjustment (thin bottom layers allowed) |
| 1 | Delete last layer if not full thickness |
| 2 | Delete if thinner than `hlvmin` fraction |
| 3 | Merge into layer above if thinner than `hlvmin` (recommended) |

### 7.13 Sediment Transport

Activate the sediment module:

```
$sedtr
    isedi = 1
    sedgrs = '0.1 0.2 0.5 1.0'    ! Grain sizes (mm)
    sedref = 0.0                    ! Initial concentration (kg/m³)
    sedhpar = 5.0                   ! Diffusion coefficient
    idtsed = '1h'                   ! Output interval
    percin = 0.25 0.25 0.25 0.25   ! Initial distribution fractions
$end
```

Additional sediment parameters can be specified in an external file (`sedcon`). See the parameter reference for the full list of constants (erosion rates, flocculation, consolidation, etc.).

### 7.14 Wave Coupling

```
$waves
    iwave = 1         ! 1=parametric, 2-5=WWMIII, 11=WW3
    dtwave = 600      ! Coupling interval (s)
    idtwav = '1h'     ! Wave output interval
$end
```

### 7.15 Ecological Models

#### EUTRO (WASP-derived)

```
$para
    ibio = 1
$end
$bound1
    bio2dn = 'eco_boundary.fem'
$end
```

Simulates 11 state variables: dissolved oxygen, CBOD, phytoplankton, ammonia, nitrate, organic N/P, orthophosphate, zooplankton, and sediment N/P.

#### AQUABC

Focuses on cyanobacteria and nitrogen fixation with 23 state variables including multiple phytoplankton groups, zooplankton, nutrients (C, N, P, Si), dissolved organic matter, and sediment diagenesis.

#### BFM

The Biogeochemical Flux Model (experimental) — requires separate BFM library installation.

### 7.16 Lagrangian Particle Tracking

```
$lagrg
    ilagr = 3              ! 1=surface, 3=3D
    nbdymax = 100000       ! Maximum particles
    nbdy = 1000            ! Particles per release
    idtl = 3600            ! Release interval (s)
    idtlgr = 600           ! Output interval (s)
    rwhpar = 1.0           ! Horizontal diffusion (m²/s)
    lagra = 'release_area.grd'  ! Release area file
$end
```

Particles can also be released at open boundaries using `lgrpps` in the boundary section.

### 7.17 Water Renewal Time

```
$wrt
    idtwrt = 0         ! Reset interval (0=no reset, >0=interval in s)
    c0 = 1.0           ! Initial tracer concentration
    iaout = -1         ! Area code for external regions
    percmin = 0.0      ! Stop when concentration drops below this %
    iret = 1           ! 1=allow return flow, 0=force zero outside
$end
```

Output files:
- `.jas` — Time series of total tracer concentration and WRT
- `.wrt` — Nodal WRT values
- `.frq` — WRT frequency distributions

### 7.18 Tidal Potential

```
$para
    rtide = 1          ! Enable equilibrium tidal potential forcing
$end
```

### 7.19 Coordinate Projection

For basins in projected coordinates that need geographic reference:

```
$proj
    iproj = 2          ! UTM projection
    c_zone = 33        ! UTM zone
$end
```

| `iproj` | Projection |
|---------|------------|
| 0 | None |
| 1 | Gauss-Boaga |
| 2 | Universal Transverse Mercator (UTM) |
| 3 | Equidistant Cylindrical (CPP) |
| 4 | UTM non-standard |

---

## 8. Output and Post-Processing Tools

### 8.1 `shyelab` — Output Elaboration

`shyelab` is the main tool for inspecting and post-processing SHYFEM output files (`.shy`, `.ext`, `.flx`, `.lgr`):

```bash
# Display file information
shyelab file.shy

# Display with verbose time records
shyelab -verbose file.shy

# Write min/max of records
shyelab -write file.shy
```

**Time selection:**

```bash
# Process specific time range
shyelab -tmin '2021-06-01' -tmax '2021-06-30' file.shy

# Process specific records
shyelab -rmin 10 -rmax 100 file.shy

# Process every 5th record
shyelab -rfreq 5 file.shy
```

**Format conversion:**

```bash
# Convert to NetCDF
shyelab -out -outformat nc file.shy

# Convert to GIS format
shyelab -out -outformat gis file.shy

# Convert to FEM format
shyelab -out -outformat fem file.shy
```

**Data extraction:**

```bash
# Extract specific nodes
shyelab -node 1001,1002,1003 file.shy

# Extract nodes from file
shyelab -nodes nodelist.txt file.shy

# Split by variable
shyelab -split file.shy

# Extract specific coordinate
shyelab -coord 12.5,45.3 file.shy
```

**Statistical operations:**

```bash
# Time average
shyelab -out -aver file.shy

# Basin average
shyelab -out -averbas file.shy

# Standard deviation
shyelab -out -std file.shy

# Min/max of records
shyelab -out -min file.shy
shyelab -out -max file.shy

# Vertical average (3D to 2D)
shyelab -out -2d file.shy

# Compute vorticity
shyelab -out -vorticity file.shy
```

**Regular grid interpolation:**

```bash
# Interpolate to regular grid (dx=100m)
shyelab -out -reg 100 file.shy

# Interpolate to specific grid
shyelab -out -reg 100,100,x0,y0,x1,y1 file.shy
```

**File comparison:**

```bash
# Check if two files differ
shyelab -diff file1.shy file2.shy

# Check with tolerance
shyelab -diffeps 1e-6 -diff file1.shy file2.shy
```

### 8.2 `shyplot` — Plotting

`shyplot` produces PostScript plots from SHYFEM output files:

```bash
shyplot file.shy
```

Features include scalar field contours, velocity vectors, and section plots.

### 8.3 `shybas` — Basin Utilities

```bash
# Display basin information
shybas basin.bas

# Write depth values
shybas -depth basin.bas

# Regular output
shybas -reg basin.bas
```

### 8.4 `shyparts` — Mesh Partitioning

Partitions the mesh for MPI parallel runs:

```bash
# Partition into 4 subdomains
shyparts -n 4 basin.bas
```

Note: In recent versions, partitioning can also be done automatically at runtime (online partitioning).

### 8.5 Other Utilities

| Tool | Purpose |
|------|---------|
| `shyadj` | Grid adjustment utilities |
| `shynetcdf` | NetCDF format conversion library and utilities |
| `femutil` | FEM file manipulation utilities |
| `hcbs` | Hydrodynamic boundary utilities |
| `anim` | Animation utilities |
| `postscript` | PostScript output utilities |

---

## 9. MPI Parallel Computing

### 9.1 Overview

SHYFEM supports domain decomposition parallelization using MPI. The mesh is partitioned into subdomains using the METIS library, and each MPI rank handles one subdomain with ghost zone exchanges at boundaries.

### 9.2 Prerequisites

- METIS library (`libmetis-dev` on Debian/Ubuntu)
- OpenMPI (`openmpi-bin`, `libopenmpi-dev`)
- Build with MPI support

### 9.3 Building with MPI

Configure `Rules.make`:

```makefile
PARALLEL_MPI = NODE
PARTS = METIS
METISDIR = /usr
```

Build:

```bash
# Important: use OpenMPI, not Intel MPI (incompatible mpi.mod)
PATH=/usr/bin:$PATH make fem
```

### 9.4 Running with MPI

```bash
# Partitioning is done automatically at runtime
PATH=/path/to/shyfem/bin:/usr/bin:$PATH mpirun -np 4 shyfem simulation.str

# Or with oversubscribe if fewer physical cores
mpirun --oversubscribe -np 4 shyfem simulation.str
```

### 9.5 Partition Quality

The quality of the domain decomposition can be controlled:

```
$para
    ibasin = -1       ! Grid optimization (-1=none, 0=renumber, 1=optimize)
    pqual = 2.5       ! Maximum partition quality index
$end
```

### 9.6 MPI Capabilities

Currently supported in MPI mode:
- Hydrodynamic solver (explicit and semi-implicit)
- Area codes and wetting/drying
- Nonlinear advective terms
- Tracer, T/S, baroclinic dynamics
- 2D, 3D zeta-layers, 3D sigma-layers
- GOTM turbulence closure
- TVD advection schemes
- Horizontal diffusion
- Open boundary conditions across domains
- Output writing

Not yet supported in MPI:
- Lagrangian particle tracking (serial only)

### 9.7 MPI Notes

- `-fopenmp` must be in link flags unconditionally (some `omp_*` calls exist even without OpenMP enabled)
- Intel MPI's `mpi.mod` is incompatible with gfortran — always use OpenMPI with gfortran
- Hybrid MPI+OpenMP is not recommended (MPI initialized with `MPI_THREAD_SERIALIZED`)
- Stack overflow with MPI: run `ulimit -s unlimited` before execution

---

## 10. File Formats

### 10.1 GRD File (Grid)

See [Section 3.2](#32-the-grd-file-format) for the complete GRD format specification. Extension: `.grd`.

### 10.2 BAS File (Basin)

Binary file produced by `shypre` containing the preprocessed mesh. Contains:
- Node coordinates, depths, connectivity
- Element definitions
- Internal numbering

Extension: `.bas`. Use `shybas` to inspect.

### 10.3 STR File (Parameters)

ASCII parameter file. See [Section 4](#4-parameter-file-str-format). Extension: `.str`.

### 10.4 SHY File (Model Output)

Binary unformatted file storing SHYFEM output. Uses optimized storage where only existing layers are written (saving space for z-coordinate grids where deep layers don't exist in shallow areas).

Structure:
```
Header record:
    idshy (=1617), nvers (=12)
    ftype                        ! 1=hydro, 2=scalar/node, 3=scalar/element
    nkn, nel, npr, nlv, nvar
    date, time
    title (80 chars)
    femver (80 chars)
    nen3v, ipev, ipv, iarv, iarnv
    xgv, ygv, hm3v, hlv, ilhv, ilhkv

Time records (repeated):
    For each variable:
        dtime, ivar, n, m, lmax
        data values (compressed for 3D)
```

Use `shyelab` to inspect and convert SHY files.

### 10.5 FEM File (Forcing/BC)

ASCII or binary files used for forcing data (wind, heat flux, initial conditions, boundary data). Can contain regular or irregular grids with time-varying data. Used for files specified in `$name` section (wind, qflux, tempin, saltin, etc.).

### 10.6 EXT File (Extra Points)

Time series output at monitoring nodes defined in `$extra`. Contains water level, velocity, temperature, salinity, and tracer values at selected nodes.

### 10.7 FLX File (Flux)

Discharge data through cross-sections defined in `$flux`.

### 10.8 RST File (Restart)

Binary restart file containing the full model state for continuation runs.

### 10.9 NetCDF Output

When `netcdf = 1` is set in `$para`, output is written in NetCDF format (`.nc`) instead of the native SHY format. Requires SHYFEM to be compiled with NetCDF support.

### 10.10 Time Series File Format

ASCII time series files (used for boundary conditions, wind inline, etc.) have two or more columns:

```
time_in_seconds   value1   [value2   ...]
```

- First column: time in seconds from simulation reference time
- Subsequent columns: data values
- Times must be monotonically increasing
- Data must cover the full simulation period

Starting from v7.1, dates can also be specified as ISO strings and durations with unit suffixes (`'30s'`, `'1h'`, `'1d'`).

---

## 11. SHYFEM-UI Web Interface

### 11.1 Overview

SHYFEM-UI is a web-based graphical interface for configuring and managing SHYFEM simulations. It provides:

- Interactive STR file editing with parameter validation
- Grid/basin visualization
- Simulation management (start, stop, monitor)
- Output visualization
- Tutorial-guided workflow for learning SHYFEM

### 11.2 Architecture

SHYFEM-UI is a Python/Flask application located in `shyfem-ui/`:

```
shyfem-ui/
├── shyfem_ui/
│   ├── app.py            Main Flask application
│   ├── config.py         Configuration
│   ├── pages/            Page modules (editor, viewer, etc.)
│   ├── services/         Backend services
│   │   └── parser_str.py STR file parser with parameter metadata
│   ├── components/       UI components
│   ├── models/           Data models
│   ├── db/               Database
│   ├── tutorial_content.py  Tutorial walkthrough content
│   └── www/              Static web assets
└── scripts/              Helper scripts
```

### 11.3 Key Features

- **STR Editor** — Form-based editing of all STR parameters with descriptions, types, defaults, and valid ranges
- **Parameter Validation** — Real-time validation against known parameter metadata
- **Grid Viewer** — Visualization of the mesh and bathymetry
- **Simulation Runner** — Launch and monitor SHYFEM simulations
- **Tutorial Mode** — Step-by-step guided walkthrough using the Mar Menor example

### 11.4 Parameter Metadata

The UI maintains a comprehensive parameter database (`COMMON_PARAMS` in `parser_str.py`) with metadata for each parameter including:

- Description
- Type (int, float, string)
- Default value
- Units
- Valid range or allowed values

This metadata is used for both the UI forms and parameter validation.

---

## 12. Parameter Reference

### 12.1 Section `$para` — Timing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `itanf` | string | `0` | Start time of simulation |
| `itend` | string | — | End time of simulation |
| `idt` | string | — | Time step of integration (e.g., `'30s'`) |
| `date` | int | -1 | Reference date (YYYYMMDD) |
| `time` | int | 0 | Reference time (HHMMSS) |
| `tz` | int | 0 | Time zone (0=GMT, 1=MET, 2=MEST) |

### 12.2 Section `$para` — Output Intervals

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `idtout` | string | `0` | Hydrodynamic output interval |
| `idtext` | string | `0` | Extra point time series interval |
| `idtrst` | string | `0` | Restart file interval (-1=last step only) |
| `idtres` | string | `0` | Residual data interval |
| `idtrms` | string | `0` | RMS velocity output interval |
| `idtflx` | string | `0` | Flux/discharge output interval |
| `idtcon` | string | `0` | Scalar/concentration output interval |
| `idtvol` | string | `0` | Volume monitoring interval |
| `idtmet` | string | `0` | Meteo variable output interval |
| `idtstb` | string | `0` | Stability index output interval |
| `netcdf` | int | 0 | Output format (0=Fortran, 1=NetCDF) |
| `ishyff` | int | 1 | File format version (0=old, 1=new SHY) |
| `iout_av` | int | 0 | Hydro output averaging (0=instant, 1=time-avg) |
| `icon_av` | int | 0 | Scalar output averaging (0=instant, 1=time-avg, 2=vert+time-avg) |

### 12.3 Section `$para` — Advection and Time Stepping

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ilin` | int | 1 | Advective terms (0=nonlinear, 1=linearized/off) |
| `itlin` | int | 0 | Advection scheme (0=FE, 1=semi-Lagrangian) |
| `iclin` | int | 0 | Continuity linearization (0=nonlinear, 1=linear) |
| `itsplt` | int | 0 | Time step mode (0=constant, 1=splitting, 2=free, 3=fractional) |
| `coumax` | float | 1.0 | Maximum Courant number |
| `idtsyn` | int | 0 | Synchronization interval for `itsplt=2` (s) |
| `idtmin` | float | 1.0 | Minimum time step allowed (s) |

### 12.4 Section `$para` — Semi-Implicit Weighting

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `azpar` | float | 0.5 | Transport term weighting [0,1] |
| `ampar` | float | 0.5 | Pressure term weighting [0,1] |
| `afpar` | float | 0.5 | Coriolis term weighting [0,1] |
| `atpar` | float | 1.0 | Vertical viscosity weighting [0,1] |
| `adpar` | float | 1.0 | Vertical diffusion weighting [0,1] |
| `aapar` | float | 1.0 | Vertical advection weighting [0,1] |

### 12.5 Section `$para` — Coriolis and Coordinates

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `icor` | int | 0 | Coriolis (0=off, 1=beta-plane, 2=f-plane, -1=force off) |
| `dlat` | float | 100.0 | Latitude for Coriolis (deg N) |
| `isphe` | int | -1 | Coordinates (-1=auto, 0=Cartesian, 1=spherical) |

### 12.6 Section `$para` — Depth and Wetting/Drying

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `href` | float | 0.0 | Reference depth correction (m) |
| `hzmin` | float | 0.01 | Minimum water depth for drying (m) |
| `hzoff` | float | 0.05 | Depth threshold for drying (m) |
| `hzon` | float | 0.10 | Depth threshold for rewetting (m) |
| `hmin` | float | -99999 | Minimum basin depth (m) |
| `hmax` | float | 99999 | Maximum basin depth (m) |

### 12.7 Section `$para` — Bottom Friction

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ireib` | int | 0 | Friction type (0=none, 1=constant, 2=Strickler, 3=Chezy, 5=drag, 6=roughness) |
| `czdef` | float | 0.0 | Friction coefficient λ |
| `iczv` | int | 1 | Evaluate friction at every timestep (0/1) |

### 12.8 Section `$para` — Wind

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iwtype` | int | 1 | Wind input type (0=none, 1=u,v m/s, 2=stress, 3=speed+dir, 4=knots+dir) |
| `itdrag` | int | 0 | Drag formula (0=constant, 1=Smith-Banke, 2=Large-Pond, 3=wave, 4=heat) |
| `dragco` | float | 2.5e-3 | Wind drag coefficient |
| `wsmax` | float | 50.0 | Maximum wind speed (m/s) |
| `rfact` | float | 1.0 | Wind stress scaling factor |

### 12.9 Section `$para` — Heat Flux

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iheat` | int | 1 | Heat flux algorithm (1=AREG, 2=POM, 3=Gill, 4=Dejak, 5=GOTM, 6=COARE, 7=direct, 8=MFS) |
| `ihtype` | int | 1 | Water vapor input (1=RH%, 2=Tw, 3=Td, 4=q) |
| `hdecay` | float | 0.0 | Radiation penetration depth (m), 0=surface |
| `albedo` | float | 0.06 | Surface albedo [0,1] |
| `ievap` | int | 0 | Compute evaporation mass flux (0/1) |
| `irain` | int | 1 | Compute precipitation mass flux (0/1) |

### 12.10 Section `$para` — Physical Constants

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rowass` | float | 1025.0 | Water density (kg/m³) |
| `roluft` | float | 1.225 | Air density (kg/m³) |
| `grav` | float | 9.81 | Gravitational acceleration (m/s²) |

### 12.11 Section `$para` — Vertical Structure

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dzreg` | float | 0.0 | Regular layer spacing (m), 0=use `$levels` |
| `ilytyp` | int | 3 | Bottom layer treatment (0=none, 1=delete, 2=delete if thin, 3=merge) |
| `hlvmin` | float | 0.25 | Minimum bottom layer thickness (fraction) |
| `nzadapt` | int | 0 | Z-star moving surface layers (0=fixed z-layers) |
| `nsigma` | int | 0 | Number of sigma layers |
| `hsigma` | float | 10000.0 | Sigma-zeta transition depth (m) |

### 12.12 Section `$para` — Vertical Mixing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iturb` | int | 0 | Turbulence model (0=none, 1=GOTM, 2=k-epsilon, 3=Munk-Anderson) |
| `difmol` | float | 1.0e-6 | Molecular vertical diffusivity (m²/s) |
| `diftur` | float | 0.0 | Turbulent vertical diffusivity (m²/s) |
| `vismol` | float | 1.0e-6 | Molecular vertical viscosity (m²/s) |
| `vistur` | float | 0.0 | Turbulent vertical viscosity (m²/s) |

### 12.13 Section `$para` — Horizontal Mixing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `idhtyp` | int | 0 | Horizontal diffusion type (0=constant, 1=area-weighted, 2=Smagorinsky) |
| `ahpar` | float | 0.0 | Horizontal viscosity (m²/s) |
| `dhpar` | float | 0.0 | Horizontal diffusion (m²/s) |
| `noslip` | int | 0 | Boundary condition (0=free-slip, 1=no-slip) |

### 12.14 Section `$para` — Scalar Transport

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `itvd` | int | 0 | Horizontal advection scheme (0=upwind, 1-2=TVD) |
| `itvdv` | int | 0 | Vertical advection scheme (0=upwind, 1=TVD) |
| `rstol` | float | 1.0 | Courant number limit for scalar transport |

### 12.15 Section `$para` — Temperature and Salinity

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ibarcl` | int | 0 | Baroclinic mode (0=off, 1=full, 2=diagnostic, 3=passive, 4=nudging, 5=variable settling) |
| `itemp` | int | 1 | Compute temperature (0/1) |
| `isalt` | int | 1 | Compute salinity (0/1) |
| `temref` | float | 0.0 | Initial temperature (°C) |
| `salref` | float | 0.0 | Initial salinity (PSU) |
| `tstrat` | float | 0.0 | Initial temperature stratification (°C/km) |
| `sstrat` | float | 0.0 | Initial salinity stratification (PSU/km) |
| `thpar` | float | -1.0 | Temperature horizontal diffusion (-1=use dhpar) |
| `shpar` | float | -1.0 | Salinity horizontal diffusion (-1=use dhpar) |

### 12.16 Section `$para` — Tracers

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iconz` | int | 0 | Number of tracers (0=off) |
| `idecay` | int | 0 | Decay type (0=none, 1=exponential, 2=Chapra) |
| `iage` | int | 0 | Water age tracer (0/1) |
| `conref` | float | 0.0 | Initial concentration |
| `contau` | float | 0.0 | Decay e-folding time (days) |
| `chpar` | float | -1.0 | Tracer horizontal diffusion (-1=use dhpar) |

### 12.17 Section `$para` — Module Activation

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ihydro` | int | 1 | Compute hydrodynamics (0/1) |
| `ibio` | int | 0 | Biological/ecological module (0/1) |
| `issedi` | int | 0 | Sediment module (0/1) |
| `rtide` | int | 0 | Tidal potential forcing (0/1) |
| `icemod` | int | 0 | Ice model (0/1) |

### 12.18 Section `$para` — Restart

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `itrst` | int/string | — | Time record for restart (-1=last record) |
| `ityrst` | int | 0 | Restart type (0=error if missing, 1=error if time not found, 2=use nearest) |
| `flgrst` | int | -1 | Restart variable flags (-1=all, binary flags: 1=hydro, 10=depth, 100=TS, ...) |

### 12.19 Section `$para` — Grid/Partition

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ibasin` | int | -1 | Grid optimization (-1=none, 0=renumber, 1=optimize) |
| `pqual` | float | 2.5 | Maximum partition quality index |

### 12.20 Section `$name` — File Paths

| Parameter | Description |
|-----------|-------------|
| `basnam` | Grid/basin file name |
| `wind` | Wind forcing time series file |
| `rain` | Precipitation forcing file |
| `qflux` | Heat flux data file |
| `ice` | Ice forcing file |
| `zinit` | Initial water level file |
| `tempin` | Initial temperature file |
| `saltin` | Initial salinity file |
| `conzin` | Initial concentration file |
| `restrt` | Restart file |
| `tempobs` | Temperature observations (for nudging) |
| `saltobs` | Salinity observations (for nudging) |
| `temptau` | Temperature nudging time scale file |
| `salttau` | Salinity nudging time scale file |
| `gotmpa` | GOTM turbulence parameters file |
| `offlin` | Offline data file |
| `surfvel` | Surface velocity observations (assimilation) |

### 12.21 Section `$bound` — Boundary Conditions

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kbound` | int list | — | Boundary node numbers |
| `ibtyp` | int | 1 | Boundary type (1=level, 2=flux, 3=internal, 4=momentum) |
| `boundn` | string | — | Boundary time series file |
| `zfact` | float | 1.0 | Scaling factor |
| `ztilt` | float | 0.0 | Water level tilt (m) |
| `ktilt` | int | 0 | Tilt reference node |
| `intpol` | int | 2/4 | Interpolation (1=step, 2=linear, 4=cubic) |
| `ampli` | float | 0.0 | Sinusoidal amplitude |
| `period` | float | 43200 | Sinusoidal period (s) |
| `phase` | float | 0.0 | Sinusoidal phase shift (s) |
| `zref` | float | 0.0 | Reference level or constant value |
| `temp` | float | 0.0 | Constant boundary temperature |
| `salt` | float | 0.0 | Constant boundary salinity |
| `conz` | float | 0.0 | Constant boundary concentration |
| `tempn` | string | — | Temperature boundary file |
| `saltn` | string | — | Salinity boundary file |
| `conzn` | string | — | Concentration boundary file |
| `vel3dn` | string | — | Velocity boundary file |
| `tnudge` | float | -1 | Velocity nudging time (s), -1=off, 0=impose |
| `tramp` | float | 0.0 | Ramp-up time for discharge (s) |
| `levmin` | int | 0 | Minimum level for discharge distribution |
| `levmax` | int | 0 | Maximum level for discharge distribution |
| `nad` | int | 0 | Nodes to suppress nonlinear terms near boundary |
| `igrad0` | int | 0 | Zero gradient boundary (0/1) |
| `bio2dn` | string | — | Ecological model boundary file |
| `sed2dn` | string | — | Sediment boundary file |
| `lgrpps` | float | 0 | Lagrangian particles per second at boundary |

---

## 13. Troubleshooting and FAQ

### 13.1 Compilation Issues

**Q: `make: command not found` (Cygwin/WSL)**

Install build tools. On Cygwin, re-run the installer and add the `make`, `gcc`, and `gfortran` packages. Run `femcheck/check_setup.sh` to identify missing dependencies.

**Q: Build fails with MPI errors**

Intel MPI's `mpi.mod` is incompatible with gfortran. Use OpenMPI instead:

```bash
PATH=/usr/bin:$PATH make fem
```

This ensures the system OpenMPI is used rather than any Intel MPI in the path.

**Q: Segmentation fault with OpenMP**

Increase the stack size:

```bash
ulimit -s unlimited
# Or for Intel compiler:
export KMP_STACKSIZE=32M
```

### 13.2 Grid Preparation

**Q: `grid` gives segmentation fault**

Two common causes:
1. Not running in an X11 environment (start X11 first, or use `startx` on Cygwin)
2. SSH without X forwarding — use `ssh -X hostname`

**Q: `mesh` gives CircumCircle error**

The boundary node spacing is too fine relative to interior spacing. Increase the spacing between boundary nodes (e.g., from 10m to 20m).

**Q: How to include internal islands?**

Add islands as closed lines with type 2 inside the external coastline (type 1):

```
3 1 1 5 101 102 103 104 101    ! External coastline (type 1)
3 2 2 4 201 202 203 201        ! Island (type 2)
```

**Q: DOS vs. Unix file format**

GRD files in DOS format (with `\r\n` line endings) can cause problems. Convert with:

```bash
d2u filename.grd    # DOS to Unix
u2d filename.grd    # Unix to DOS
```

### 13.3 Running Simulations

**Q: The parameter `itsplt` doesn't seem to work**

Time step splitting only activates when there is a stability violation. With the default linearized equations (`ilin=1`), most terms are implicit and unconditionally stable. Enable one of:
- `ilin = 0` (nonlinear advective terms)
- `ahpar > 0` (horizontal viscosity)

**Q: How to adjust `Rules.make`?**

The main settings to change are:
1. **Compiler** — `FORTRAN_COMPILER` and `C_COMPILER`
2. **Dimensions** — No longer needed in modern versions (arrays are allocatable)
3. Other options (solver, parallelization) only if needed

**Q: Is there a Windows version?**

No native Windows version. Use WSL (Windows Subsystem for Linux) or Cygwin to run SHYFEM on Windows.

### 13.4 Physical Setup

**Q: What should I use for surface heat flux?**

The `qflux` file must contain time series of meteorological variables (solar radiation, air temperature, humidity, cloud cover). The exact columns depend on the `iheat` algorithm. Check `ihtype` for whether to use relative humidity (default), wet-bulb temperature, dew-point temperature, or specific humidity.

**Q: How to set up a 3D simulation?**

1. Define vertical layers in `$levels`
2. Enable baroclinic dynamics: `ibarcl = 1`
3. Set initial T/S: `temref`, `salref`
4. Enable turbulence closure: `iturb = 1` with GOTM parameter file
5. Provide heat flux and wind forcing files
6. Use nonlinear advection with variable time step

**Q: Which bottom friction formulation should I use?**

- 2D simulations: Strickler (`ireib=2`) or Chezy (`ireib=3`)
- 3D simulations: Drag coefficient (`ireib=5`) or roughness length (`ireib=6`)

### 13.5 Post-Processing

**Q: How to convert output to NetCDF?**

Either set `netcdf = 1` in the STR file to write directly, or convert afterwards:

```bash
shyelab -out -outformat nc output.shy
```

**Q: How to extract time series at specific locations?**

Use the `$extra` section to define monitoring nodes, or extract afterwards:

```bash
shyelab -node 1001,1002 output.shy
```

### 13.6 Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "basin file not found" | Missing `.bas` file | Run `shypre` on your GRD file |
| "time step too large" | CFL violation | Reduce `idt` or enable `itsplt` |
| "node not found in basin" | Wrong node number in `$bound` or `$extra` | Check node numbers match the GRD/BAS file |
| "no data for boundary" | Boundary file missing or too short | Ensure boundary files cover the simulation period |
| "allocation error" | Insufficient memory | Use MPI to distribute across nodes, or reduce resolution |
| "segmentation fault" | Stack overflow or array bounds | Run `ulimit -s unlimited` or compile with `COMPILER_PROFILE=CHECK` |

---

## Appendix A: Quick Start Guide

### Step 1: Prepare the Grid

```bash
# Edit coastline
grid coast.grd

# Generate mesh
mesh coast.grd         # produces coast.grd with elements

# Create basin file
shypre coast.grd       # produces coast.bas
```

### Step 2: Create the STR File

Start with the Mar Menor example as a template:

```bash
cp testcases/examples/mar_menor/mm_hyd_00.str my_simulation.str
# Edit to match your basin and time period
```

### Step 3: Run the Simulation

```bash
shyfem my_simulation.str
```

### Step 4: Inspect Results

```bash
# View output info
shyelab output.shy

# Convert to NetCDF
shyelab -out -outformat nc output.shy
```

---

## Appendix B: Version History

| Version | Date | Highlights |
|---------|------|------------|
| 8.1.1 | Jun 2025 | Stable edition, variable settling velocity, PETSC fix |
| 8.1.0 | Nov 2024 | First stable version from merge party |
| 8.0.4 | Mar 2024 | First full community edition |
| 7.5.0 | Jan 2016 | New develop branch, many features |
| 7.4.0 | Jan 2016 | Stable major version |
| 7.1.0 | Jan 2015 | New time management, fractional time steps |
| 7.0.0 | Jul 2014 | Major version, new file format |

For the complete version history, see `RELEASE_NOTES` in the repository.

---

## Appendix C: References and Further Reading

- **PDF Manual:** `docs/shyfem_manual.pdf` — Full LaTeX-generated manual
- **Developer Guide:** `DEVELOPER_GUIDE.md` — Architecture, modules, coding conventions
- **Test Cases:** `testcases/examples/` — Example simulations including Mar Menor
- **GOTM Documentation:** http://www.gotm.net — GOTM turbulence model manual
- **SHYFEM GitHub Wiki:** https://github.com/georgu/shyfemcm-ismar/wiki/Test-cases

---

*This manual corresponds to SHYFEM v8.1.1 (Sankt Antonius stable edition). For the latest documentation, see the repository at the SHYFEM project page.*
