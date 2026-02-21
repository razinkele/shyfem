# Mar Menor Tutorial Guidance — Design Document

**Date:** 2026-02-19
**Status:** Approved

## Problem

The tutorial project creation copies Mar Menor example files and registers simulations in the database, but provides zero guidance afterward. Users don't know which tab to go to, what order to follow, or what each simulation teaches.

## Solution

A dedicated **Tutorial tab** that appears when a tutorial project is active, providing step-by-step guidance through all 6 phases of the Mar Menor tutorial.

## Architecture

### New Files

1. **`shyfem_ui/tutorial_content.py`** — Tutorial text content as a Python data structure. Each phase contains ordered steps with titles, explanations, STR parameter annotations, expected outcomes, and navigation targets.

2. **`shyfem_ui/pages/tutorial.py`** — Shiny UI module for the Tutorial tab. Contains `tutorial_ui()` and `tutorial_server()`.

### Modified Files

3. **`shyfem_ui/app.py`** — Add Tutorial tab to the navset (conditionally visible when tutorial project is active).

4. **`shyfem_ui/pages/home.py`** — After tutorial project creation, navigate to the Tutorial tab instead of Grid Prep.

### No New Dependencies

Uses only existing Shiny UI components (cards, accordions, tags, navs).

## Tutorial Content Structure

```python
# tutorial_content.py

TUTORIAL_STEPS = {
    "phase1": {
        "title": "Phase 1: Basic Hydrodynamics",
        "description": "Learn the minimal SHYFEM setup...",
        "simulations": [
            {
                "name": "mm_hyd_00",
                "title": "Minimal Simulation",
                "steps": [
                    {
                        "title": "Prepare the grid",
                        "content": "Before running any simulation...",
                        "nav_target": "Grid Prep",  # tab to link to
                        "params_introduced": {},     # no new params
                    },
                    {
                        "title": "Understand the STR file",
                        "content": "The .str file controls...",
                        "params_introduced": {
                            "itanf/itend": "Simulation start/end dates",
                            "idt": "Time step (300s = 5 minutes)",
                            "ilin": "Linearized equations (1=yes)",
                        },
                        "str_file": "mm_hyd_00.str",
                    },
                    {
                        "title": "Run the simulation",
                        "content": "Navigate to the Run tab...",
                        "nav_target": "Run",
                    },
                    {
                        "title": "Check results",
                        "content": "The simulation produces...",
                        "nav_target": "Post-Process",
                    },
                ],
            },
            {
                "name": "mm_hyd_01",
                "title": "Adding Output Points",
                "diff_from": "mm_hyd_00",
                "steps": [...],
            },
            ...
        ],
    },
    ...
}
```

## UI Layout

```
+------------------------------------------------------------------+
| Tutorial: Mar Menor                              [Overall: 2/14] |
+------------------------------------------------------------------+
| Phase Navigator (1/3)  |  Step Content (2/3)                     |
|                        |                                         |
| [=] Phase 1 (4 sims)  |  Phase 1: Basic Hydrodynamics           |
|   > mm_hyd_00  [done]  |                                         |
|   > mm_hyd_01  [curr]  |  mm_hyd_01 — Adding Output Points       |
|   > mm_hyd_02          |                                         |
|   > mm_hyd_03          |  What's new compared to mm_hyd_00:      |
|                        |  +-------------------------------+      |
| [ ] Phase 2 (3 sims)  |  | idtout = '3h'   # output freq |      |
| [ ] Phase 3 (3 sims)  |  | idtext = '300s'  # extra freq  |      |
| [ ] Phase 4 (1 sim)   |  | $extra section   # monitor pts |      |
| [ ] Phase 5 (2 sims)  |  +-------------------------------+      |
| [ ] Phase 6 (1 sim)   |                                         |
|                        |  Step 1: Understand output params        |
|                        |  idtout controls how often SHYFEM writes |
|                        |  to the .shy output file...              |
|                        |                                         |
|                        |  Step 2: Run the simulation              |
|                        |  [Go to Run tab ->]                     |
|                        |                                         |
|                        |  Step 3: Examine extra point output      |
|                        |  The $extra section defines monitoring   |
|                        |  points where time series are extracted..|
|                        |  [Go to Post-Process tab ->]            |
+------------------------------------------------------------------+
```

### Phase Navigator

- Vertical accordion (one phase expanded at a time)
- Each phase shows its simulations as a clickable list
- Icons: check-circle (done), arrow-right (current), circle (pending)
- Overall progress counter at the top

### Step Content

- Header: phase title + simulation name + short description
- "What's new" diff box: highlighted parameters that changed from previous simulation
- Ordered steps with educational text, parameter tables, and navigation buttons
- Navigation buttons use `nav_callback` to switch tabs (same pattern as `_activate_project`)

## Content Per Phase (Summary)

### Phase 1: Basic Hydrodynamics (4 simulations)
- **mm_hyd_00** — Minimal: `$title`, `$para` basics (itanf, itend, idt, ilin)
- **mm_hyd_01** — Output: adds `idtout`, `idtext`, `$extra` monitor points
- **mm_hyd_02** — Wind: adds `iwtype=3`, `dragco`, wind file in `$name`
- **mm_hyd_03** — Friction: adds `ireib=5`, `czdef` (Chezy friction)

### Phase 2: Tidal Boundaries (3 simulations)
- **mm_hyd_11** — Boundary: adds `$bound1` with `kbound`, `boundn` (level data)
- **mm_hyd_12** — Variations: two boundary configs (12a, 12b)
- **mm_hyd_13** — Refinement: adjusted boundary params

### Phase 3: Coriolis & Rivers (3 simulations)
- **mm_hyd_21** — Coriolis: adds `icor=1`, `dlat=38`; river via `$bound2` (ibtyp=3)
- **mm_hyd_22** — Advection variations (22, 22a, 22b)
- **mm_hyd_23** — Diffusion: adds horizontal diffusion params

### Phase 4: Salinity (1 simulation)
- **mm_hyd_31** — 3D baroclinic: `ibarcl=3`, `isalt=1`, `salref=35`, boundary salinity

### Phase 5: Temperature (2 simulations)
- **mm_hyd_41** — Full 3D: adds `itemp=1`, `$levels`, turbulence (`iturb=1`), heat flux
- **mm_hyd_42** — Turbulence variations

### Phase 6: Advanced Numerics (1 simulation)
- **mm_hyd_43** — Non-linear: `ilin=0`, `coumax=0.8`, Smagorinsky (`idhtyp=2`, `ahpar`)

## Progress Tracking

Tutorial progress is **client-side only** — stored as a Shiny reactive value (set of completed simulation names). No database changes needed. Progress resets when the session ends, which is acceptable for a tutorial.

## Conditional Tab Visibility

The Tutorial tab appears in the navset only when:
1. An active project exists, AND
2. The active project's description contains "tutorial" (matching the string set during creation)

When no tutorial project is active, the tab is hidden.

## Testing

- Unit tests for `tutorial_content.py` — validate structure, all STR files referenced exist
- Page tests for `tutorial.py` — render with mock project context, verify navigation links
