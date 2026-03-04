# Design: SHYFEM UI Physics & Workflow Gap Closure

**Date:** 2026-03-04
**Status:** Approved
**Scope:** All three tiers of UI gaps identified in Fortran-vs-UI analysis

## Problem Statement

The SHYFEM UI exposes ~80 of 308+ Fortran simulation parameters. The simulation page's Quick Settings has only 4 fields. Entire physics modules (ecology, ice, oil spill, wave coupling) have no UI path. Boundary conditions show 3 of 8+ types. Post-processing wraps only 1 of 10+ tools. Restart and offline workflows have no UI support.

## Audience

Both research scientists (need parameter completeness) and engineering practitioners (need guided configuration with presets).

## Architecture

Three-layer approach:

1. **Data Foundation** — Expand `COMMON_PARAMS` / `COMMON_SECTIONS` in `parser_str.py`
2. **Physics Configuration Page** — New `pages/physics.py` with guided panels
3. **Workflow Enhancements** — Restart chains, offline mode, boundary editor, post-processing tools

The physics page complements (not replaces) the existing simulation page. Both edit STR files. The simulation page remains the raw/advanced editor; the physics page provides guided configuration.

## Layer 1: Data Foundation (parser_str.py)

### New Sections in COMMON_PARAMS

#### $sedtr — Sediment Transport
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| isedi | int | 0 | | Enable full sediment: 0=off, 1=on |
| sedgrs | string | "" | mm | Grain sizes (space-separated, fine→coarse) |
| percin | string | "" | | Initial grain size fractions (must sum to 1.0) |
| tauin | string | "" | Pa | Critical erosion stress per grain class |
| irocks | int | -1 | | Element type excluded from erosion (-1=none) |
| sedref | float | 0.0 | kg/m³ | Initial reference concentration |
| sedhpar | float | 0.0 | m²/s | Sediment horizontal diffusion |
| adjtime | float | -1.0 | s | Morphology equilibration time (-1=off) |
| idtsed | int | 0 | s | Sediment output interval |
| itmsed | int | -1 | s | Sediment output start time |

#### $lagrg — Lagrangian Particle Tracking
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| ilagr | int | 0 | | Mode: 0=off, 1=surface, 2=2D, 3=3D |
| nbdy | int | 0 | | Particles per release event |
| nbdymax | int | -1 | | Max particles in domain (-1=unlimited) |
| rwhpar | float | 0.0 | m²/s | Horizontal diffusion (-1=local value) |
| idtl | int | 0 | s | Particle release interval |
| ipvert | int | 0 | | Vertical dist: 0=surface, >0=regular, <0=random |
| lbeach | float | 0.0 | | Beaching probability [0-1] |
| ldecay | float | 0.0 | s | Particle decay time (0=no decay) |
| ioil | int | 0 | | Oil spill simulation: 0=off, 1=on |
| ilarv | int | 0 | | Larval behavior: 0=off, 1=on |
| stkpar | float | 0.0 | | Stokes drift calibration |
| dripar | float | 1.0 | | Drifter inertia multiplier |
| itlanf | int | -1 | | Lagrangian start time (-1=use itanf) |
| itlend | int | -1 | | Lagrangian end time (-1=use itend) |
| idtlgr | int | 0 | s | Lagrangian output interval |

#### $connec — Connectivity Analysis
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| icnn | int | 0 | | Number of connectivity stations |
| radcnn | float | 0.0 | m | Release area radius |
| ppscnn | float | 0.0 | 1/s | Particles per second per station |
| pldcnn | float | 0.0 | days | Pelagic larval duration |
| idtcnn | int | 0 | s | Connectivity output interval |

#### $bfmsc — BFM Biogeochemical Model
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| ibfm | int | 0 | | Enable BFM: 0=off, 1=on |
| ibtanf | int | 0 | | BFM start time |
| ibtend | int | 0 | | BFM end time |
| itmbfm | int | -1 | | BFM output start time |
| idtbfm | int | 0 | s | BFM output interval |

#### $nduge — Data Assimilation / Nudging
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| nvars | int | 0 | | Number of observation stations (max 50) |
| tramp | float | 0.0 | s | Nudging ramp-up time |
| ttau | float | 0.0 | s | Relaxation time constant |
| sigma | float | 0.0 | m | Spatial influence radius (Gaussian) |
| bmulti | int | 1 | | Multi-station nudging: 0=off, 1=on |

### Expanded $para Parameters
| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| imerc | int | 0 | | Mercury contamination: 0=off, 1=on |
| iwave | int | 0 | | Wave coupling: 0=off, 1=file, 2-5=WWMIII modes |
| dtwave | float | 0.0 | s | Wave-current coupling time step |
| idtoff | int | 0 | | Offline mode: >0=write, -1=read hydro, -2=read T/S, -4=read turb, -3/-7=combos |
| itmoff | int | -1 | | Offline start time |
| itrst | int | 0 | s | Restart write interval (-1=last step only) |
| itmrst | int | -1 | | Restart output start time |
| ityrst | int | 1 | | Restart mode: 0=strict, 1=cold-start fallback, 2=closest-time |

### Expanded $name Files
| Parameter | Description |
|-----------|-------------|
| bioin | Initial pelagic ecology state |
| biosin | Initial sediment ecology state |
| biocon | Biogeochemical constants file |
| biolight | Light extinction data |
| sedp | Spatially varying sediment distribution |
| sedt | Spatially varying critical erosion stress |
| sedcon | Sediment model constants file |
| lgrlin | Lagrangian release area lines |
| lgrtrj | Drifter trajectory file |
| statcnn | Connectivity station coordinates |
| surfvel | Surface velocity nudging file |
| mercin | Initial mercury concentrations |
| bfmini | Initial BFM state |
| saltn | Boundary salinity time series |
| tempn | Boundary temperature time series |
| conzn | Boundary concentration time series |

### Updated Parameter Descriptions

**ireib** (bottom friction): `"0=none, 1=Chezy law, 2=Strickler, 3=Chezy coeff, 4=linear, 5=quadratic drag, 6=roughness z0, 7=Strickler+drag, 8=sediment z0, 9=fluid mud, 10=hybrid quad-linear"`

**iheat** (heat flux): `"0=off, 1=AREG, 2=POM bulk, 3=Gill, 4=Dejak, 5=GOTM, 6=COARE 3.0, 7=read from file, 8=MFS bulk"`

**ibtyp** (boundary type): `"-1=closed, 0=off, 1=water level, 2=discharge, 3=volume inlet, 4=momentum, 5=fixed scalar, 31=radiation/zero-gradient, 32=special"`

**ibarcl** (baroclinic mode): `"0=off, 1=diagnostic, 2=T/S diagnostic, 3=prognostic, 4=nudging, 5=new assimilation"`

### New COMMON_SECTIONS Entries
```python
"sedtr": "Sediment transport configuration (grain sizes, erosion thresholds)",
"lagrg": "Lagrangian particle tracking (IBM, oil spill, connectivity)",
"connec": "Particle connectivity analysis (source-destination tracking)",
"bfmsc": "BFM biogeochemical flux model",
"nduge": "Data assimilation via zeta/velocity nudging",
```

## Layer 2: Physics Configuration Page

### File: pages/physics.py

**Navigation placement:** Prepare group, after Partitioning:
```
Prepare → Mesh Builder → Grid Prep → Partitioning → Physics Config
```

**Layout:**
- Sidebar: STR file path, Load/Save/Preview buttons, active module summary badges
- Main area: Accordion panels (collapsed by default, expand on click)

### Panel Specifications

#### Panel 1: Hydrodynamics
- Advection: `ilin` toggle (linear/nonlinear), `itlin` select (FE/semi-Lagrangian)
- Time stepping: `itsplt` select (constant/splitting/fractional), `coumax` numeric, `idtsyn` text
- Coriolis: `icor` select (off/beta-plane/f-plane), `dlat` numeric
- Wetting-drying: `hzmin`/`hzoff`/`hzon` numerics with validation (hzmin < hzoff < hzon)
- Coordinates: `isphe` select (auto/Cartesian/spherical)

#### Panel 2: Vertical Structure
- Layer mode: radio (z-layers / sigma / hybrid / z-star adaptive)
- z-layers: `dzreg` numeric OR explicit `$levels` text input
- Sigma: `nsigma` numeric
- Hybrid: `hsigma` numeric (transition depth)
- Adaptive: `nzadapt` numeric
- Bottom treatment: `ilytyp` select (0-3 with descriptions)

#### Panel 3: Bottom Friction
- Model selector: dropdown with all 11 ireib options + 1-line description each
- Coefficient: `czdef` numeric (label changes per model: "Chezy coeff" / "Manning n" / "z₀ roughness" / "drag Cd")
- Help text: Brief guidance on which model suits which scenario

#### Panel 4: Turbulence & Mixing
- Vertical closure: `iturb` select (none/GOTM/k-ε/Munk-Anderson)
- Molecular: `difmol`, `vismol` numerics
- Turbulent (manual): `diftur`, `vistur` numerics (shown when iturb=0)
- GOTM config: `gotmpa` file picker (shown when iturb=1)
- Horizontal type: `idhtyp` select (constant/area-weighted/Smagorinsky)
- Horizontal coeffs: `ahpar`, `dhpar` numerics
- Scalar advection: `itvd` select (upwind/TVD), `itvdv` select (upwind/TVD)

#### Panel 5: Heat Flux
- Algorithm: `iheat` select (8 options) with scenario guidance tooltip:
  - "COARE 3.0 (iheat=6): Modern bulk formula, recommended for open ocean"
  - "MFS (iheat=8): Optimized for Mediterranean"
  - "Read from file (iheat=7): Pre-computed flux components"
- Vapor input: `ihtype` select (RH% / wet-bulb / dew-point / specific humidity)
- Solar penetration: `isolp` select (exponential/Jerlov), `iwtyp` select when Jerlov (10 water types)
- Evaporation: `ievap` toggle
- Precipitation: `irain` toggle
- Skin temp output: `iskin` toggle
- File: `qflux` file picker

#### Panel 6: Temperature & Salinity
- Mode: `ibarcl` select (off/diagnostic/prognostic/nudging/assimilation) with descriptions
- Compute toggles: `itemp`, `isalt`
- Initial values: `temref`, `salref` numerics
- Horizontal diffusion: `thpar`, `shpar` numerics (-1 = use dhpar)
- Observation files: `tempobs`, `saltobs` file pickers (shown when ibarcl >= 2)
- Output: `idtcon` text, `icon_av` select (instant/time-avg/vert+time-avg)

#### Panel 7: Ecology
- Model selector: radio (none / WEUTRO / BFM / AQUABC / Mercury)
- WEUTRO panel (when ibio=1):
  - State variables listed (NH3, NO3, OPO4, PHYT, CBOD, DO, ON, OP, ZOO)
  - Initial values display (editable)
  - File pickers: `bioin`, `biosin`, `biocon`, `biolight`
  - Sub-modules: ulva toggle, shellfish toggle, sediment-ecology coupling toggle
- BFM panel (when ibfm=1):
  - `$bfmsc` params: start/end time, output interval
  - File picker: `bfmini`
  - Note: "Requires BFM library compiled with SHYFEM"
- Mercury panel (when imerc=1):
  - File picker: `mercin`

#### Panel 8: Sediment Transport
- Mode selector: radio (off / simple / full)
- Simple (issedi=1): Activation only, no additional params
- Full ($sedtr section):
  - Grain sizes: text input for `sedgrs` (e.g., "0.063 0.125 0.25 0.5")
  - Fractions: text input for `percin` (must sum to 1.0, validated)
  - Erosion stress: text input for `tauin`
  - Diffusion: `sedhpar` numeric
  - Morpho acceleration: adjtime numeric
  - File pickers: `sedp`, `sedt`, `sedcon`
  - Rock exclusion: `irocks` numeric

#### Panel 9: Lagrangian / IBM
- Mode: `ilagr` select (off/surface/2D/3D)
- Particles: `nbdy` numeric (per release), `nbdymax` numeric (max total)
- Release: `idtl` text (interval), `itlanf`/`itlend` text (time window)
- Diffusion: `rwhpar` numeric
- Vertical: `ipvert` select (surface/regular/random)
- Beaching: `lbeach` slider [0-1]
- Decay: `ldecay` text (time constant)
- Oil spill: `ioil` toggle → shows additional oil params
- Larvae: `ilarv` toggle
- Connectivity section (shown when icnn > 0):
  - Station count: `icnn` numeric
  - Radius: `radcnn` numeric
  - Release rate: `ppscnn` numeric
  - PLD: `pldcnn` numeric
  - File: `statcnn` file picker
- File pickers: `lgrlin`, `lgrtrj`

#### Panel 10: Ice Model
- Enable: `icemod` toggle
- Time step: `idtice` text
- Ice-free area: `iaicef` numeric
- File: `ice` file picker
- Requirements checklist (read-only): "Requires: cloud cover, solar radiation, precipitation, humidity, air temp, wind speed in meteo forcing"

#### Panel 11: Wave Coupling
- Mode: `iwave` select (off / constant file / WWMIII radiation+SHYFEM wind / WWMIII vortex+SHYFEM wind / WWMIII radiation+WWM wind / WWMIII vortex+WWM wind)
- Coupling dt: `dtwave` text
- Bottom drag: `itdrag` select (with note: "itdrag=3 requires iwave≥2")
- Note: "WWMIII modes require compiled wave model coupling"

#### Panel 12: Data Assimilation
- Zeta nudging: `nvars` numeric (station count)
- Parameters: `tramp` (ramp time), `ttau` (relaxation), `sigma` (influence radius)
- Multi-station: `bmulti` toggle
- Velocity nudging: `surfvel` file picker
- Note: "Requires ibarcl ≥ 4 for T/S nudging; set in Temperature & Salinity panel"

#### Panel 13: Output & Restart
- Output intervals (all in one place):
  - `idtout` (hydro), `idtext` (extra nodes), `idtcon` (scalars), `idtflx` (fluxes)
  - `idtres` (residual), `idtrms` (RMS), `idtvol` (volume), `idtmet` (meteo), `idtstb` (stability)
- Format: `netcdf` toggle (0=Fortran binary, 1=NetCDF)
- Averaging: `iout_av` select, `icon_av` select
- Restart section:
  - Write interval: `itrst` text (-1=last step)
  - Start time: `itmrst` text
  - Mode: `ityrst` select (strict / cold-start fallback / closest-time)
  - Restart file: `restrt` file picker
- Offline section:
  - Mode: `idtoff` select (off / write hydro / read hydro / read T-S / read turb / combos)
  - Start time: `itmoff` text

### STR Generation Logic

Each panel writes to a shared in-memory `StrFile` object. On "Save":
1. Merge all panel changes into the StrFile
2. Preserve sections/params not managed by any panel (user's custom content)
3. Write to disk via StrParser

On "Load":
1. Parse STR file
2. Populate each panel's reactive values from parsed params
3. Set panel status badges (Active/Not configured)

## Layer 3: Workflow Enhancements

### 3a. Boundary Editor (boundary_editor.py)

Update ibtyp choices dict:
```python
BOUNDARY_TYPES = {
    -1: "Closed Wall",
    0:  "Off / Inactive",
    1:  "Water Level (elevation)",
    2:  "Discharge (volume flux)",
    3:  "Internal Volume Inlet",
    4:  "Momentum Input",
    5:  "Fixed Scalar (no flux)",
    31: "Radiation / Zero Gradient",
}
```

Add conditional scalar boundary file fields per boundary entry:
- `saltn` text input (shown when ibarcl > 0)
- `tempn` text input (shown when ibarcl > 0 and itemp=1)
- `conzn` text input (shown when iconz > 0)

### 3b. Templates (simulation.py)

**Fix existing:**
- Rename `lagrangian` → `eulerian_tracer` (it sets iconz/iage, not ilagr)

**Add new templates:**

| Key | Name | Key Params |
|-----|------|-----------|
| `thermal` | Thermal / Heat Exchange | iheat=6, ibarcl=1, itemp=1, isalt=1, ievap=1, iturb=1, $levels, qflux file |
| `ice_model` | Ice Model | icemod=1, idtice=300, ibarcl=1, itemp=1, isalt=1, iheat=1, $levels |
| `oil_spill` | Oil Spill (Lagrangian) | $lagrg: ilagr=2, ioil=1, nbdy=1000, ldecay=86400, lbeach=0.5 |
| `lagrangian` | Lagrangian Particle Tracking | $lagrg: ilagr=2, nbdy=100, idtl=3600, rwhpar=1.0 |
| `data_assimilation` | Data Assimilation | ibarcl=4, $nduge: nvars=3, ttau=3600, sigma=5000, tramp=86400 |
| `offline_tracer` | Offline Tracer Run | idtoff=-1, iconz=1, iage=1 (with commented offline file path) |
| `wave_coupled` | Wave-Coupled Storm Surge | iwave=2, itdrag=3, iwtype=3, wsmax=60, hzoff=0.05, hzon=0.10, $levels |

### 3c. Run Page — Restart Workflow (run.py)

Add to job submit form:
- "Continue from previous job" dropdown: lists completed jobs that produced .rst files
- On selection: auto-fill `restrt` path, suggest `itanf` from checkpoint time
- Auto-set `ityrst=2` in the STR file

### 3d. Run Page — Offline Mode Workflow

Add to WORKFLOW_TEMPLATES in workflow.py:
```python
"offline_tracer": {
    "name": "Offline Tracer Analysis",
    "description": "Run hydrodynamics first, then run tracers on saved flow fields",
    "steps": [
        {"tool": "shyfem", "description": "Hydrodynamic run (writes offline data)", "params": {"idtoff": ">0"}},
        {"tool": "shyfem", "description": "Tracer run (reads offline hydro)", "params": {"idtoff": "-1"}},
    ],
}
```

### 3e. Post-Processing Expansion (postprocess.py)

Add to SHYELAB_OPERATIONS:
```python
"flux": {
    "label": "Flux / Transport Analysis",
    "flags": ["-flux"],
    "description": "Compute integrated transport at cross-sections",
},
```

Add to Run page tool_select:
```python
"exgrd": "exgrd (Grid Extraction)",
"shyadj": "shyadj (Mesh Adjustment)",
"nc_elab": "nc_elab (NetCDF Elaboration)",
```

## Implementation Phases

### Phase A: Data Foundation
**Files:** `parser_str.py`
**Effort:** Medium
**Steps:**
1. Add 5 new section dicts to COMMON_PARAMS ($sedtr, $lagrg, $connec, $bfmsc, $nduge)
2. Add 17 new params to $para section
3. Add 16 new file entries to $name section
4. Update ireib/iheat/ibtyp/ibarcl description strings
5. Add 5 new entries to COMMON_SECTIONS
6. Add tests: parse round-trip for each new section

### Phase B: Boundary Editor
**Files:** `boundary_editor.py`
**Effort:** Small
**Steps:**
1. Replace ibtyp choices with full BOUNDARY_TYPES dict
2. Add scalar boundary file inputs (saltn, tempn, conzn) with conditional visibility
3. Update CSV import/export format to support new types
4. Add tests: all boundary types render, CSV round-trip

### Phase C: Templates
**Files:** `simulation.py`
**Effort:** Small-Medium
**Steps:**
1. Rename lagrangian → eulerian_tracer
2. Add 7 new templates (thermal, ice, oil_spill, lagrangian, data_assimilation, offline_tracer, wave_coupled)
3. Update template_select choices dict
4. Add tests: each template generates valid parseable STR

### Phase D: Physics Configuration Page
**Files:** `pages/physics.py` (new), `app.py` (nav entry)
**Effort:** Large
**Steps:**
1. Create page skeleton with sidebar (STR load/save) + accordion layout
2. Implement panels 1-4 (Hydrodynamics, Vertical, Friction, Turbulence) — core hydro
3. Implement panels 5-6 (Heat Flux, T/S) — thermal
4. Implement panels 7-8 (Ecology, Sediment) — biogeochemistry
5. Implement panels 9-11 (Lagrangian, Ice, Waves) — specialized
6. Implement panels 12-13 (Data Assimilation, Output/Restart) — workflows
7. Wire STR load/save: parse → populate panels → modify → serialize
8. Add panel status badges
9. Add to app.py sidebar navigation
10. Add tests per panel: rendering, validation, STR generation

### Phase E: Run Page Workflows
**Files:** `run.py`, `workflow.py`
**Effort:** Medium
**Steps:**
1. Add restart dropdown to job submit form
2. Implement restart auto-population logic
3. Add offline tracer workflow template
4. Add tests: restart chain, offline workflow

### Phase F: Post-Processing
**Files:** `postprocess.py`, `run.py`
**Effort:** Small
**Steps:**
1. Add flux operation to SHYELAB_OPERATIONS
2. Add tools to run page tool selector
3. Add tests: new operations generate correct CLI flags

## Recommended Build Order

1. **Phase A** (Data Foundation) — everything else depends on this
2. **Phase B** (Boundary Editor) — small, immediate value
3. **Phase C** (Templates) — small, immediate value
4. **Phase D** (Physics Page) — large, built incrementally panel-by-panel
5. **Phase E** (Run Workflows) — medium, depends on Phase A for restart params
6. **Phase F** (Post-Processing) — small, independent

## Testing Strategy

- **Unit tests** for parser_str.py: each new section parses and serializes correctly
- **Component tests** for physics.py: each panel renders without errors, form validation works
- **Integration tests**: load STR → modify via physics page → save → reload → content preserved
- **Template tests**: each template generates STR that parses with no warnings
- **Boundary tests**: all ibtyp values, scalar file conditional visibility

## Files Modified/Created

| File | Action | Phase |
|------|--------|-------|
| `services/parser_str.py` | Modify (expand COMMON_PARAMS/SECTIONS) | A |
| `components/boundary_editor.py` | Modify (full ibtyp list, scalar files) | B |
| `pages/simulation.py` | Modify (rename template, add 7 templates) | C |
| `pages/physics.py` | **Create** (new physics configuration page) | D |
| `app.py` | Modify (add nav entry for physics page) | D |
| `pages/run.py` | Modify (restart dropdown, offline workflow) | E |
| `services/workflow.py` | Modify (add offline_tracer template) | E |
| `pages/postprocess.py` | Modify (add flux operation) | F |
| `tests/test_parser_str.py` | Modify (new section tests) | A |
| `tests/test_physics.py` | **Create** (physics page tests) | D |
| `tests/test_boundary_editor.py` | Modify (new ibtyp tests) | B |
| `tests/test_templates.py` | **Create** or modify (template validation) | C |
