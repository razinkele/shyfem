# Phase 32: STR Template Library Expansion — Design

**Date:** 2026-02-18
**Status:** Design approved

## Scope

Enhance 2 existing templates and add 3 new ones to cover SHYFEM's main
simulation scenarios. All templates are raw .str strings in `generate_template()`.

## Template Changes

### 32.1 — Enhance `wind_driven` (existing)

Current template is minimal (just a wind file reference). Enhance with:
- `icor = 1` (beta-plane Coriolis)
- `dlat = 45` (mid-latitude default)
- `idhtyp = 2` (Smagorinsky horizontal diffusion)
- `ahpar = 1.0` (diffusion coefficient)
- Explicit comment: "2D barotropic wind-driven circulation"

### 32.2 — New `tidal_estuary` template

Distinct from existing basic `tidal` (which is 2D-only). This is a full
3D tidal estuary setup:
- `nlv = 10` with layer depths
- `ibarcl = 1`, `isalt = 1`, `itemp = 1` (baroclinic)
- `salref = 35.0`, `temref = 15.0`
- `iturb = 1` (GOTM turbulence)
- `$bound` section with tidal + river inflow boundaries
- Wind forcing file reference

### 32.3 — New `sediment_transport` template

Uses the simple sediment module (simpler than full `$sedtr`):
- `issedi = 1` (simple sedimentation)
- 3D setup with levels
- `ibarcl = 1` (density coupling)
- Commented `$sedtr` section showing full module params for advanced users

### 32.4 — New `water_quality` template

Activates the WASP/EUTRO 9-variable eutrophication model:
- `ibio = 1` (water quality reactor)
- `ibarcl = 1`, `itemp = 1`, `isalt = 1`
- 3D with levels
- `$name` references for bio2dn (boundary) and bioin (initial conditions)

### 32.5 — New `storm_surge` template

2D barotropic storm surge with wetting/drying:
- `hzoff = 0.05`, `hzon = 0.10` (wetting/drying thresholds)
- `iwtype = 3` (speed + direction wind input)
- `itdrag = 2` (Wu 1982 drag formula)
- `idt = '60s'` (high-resolution timestep)
- `icor = 1` (Coriolis)
- Atmospheric pressure via wind file 3rd column (commented)
- `isphe = 1` (spherical coordinates)

## Files Modified

1. `shyfem_ui/pages/simulation.py`
   - Lines 77-88: Add 3 new entries to dropdown `choices` dict
   - Lines 460-716: Enhance `wind_driven`, add 3 new templates in `generate_template()`
2. `tests/test_str_templates.py` — New: parse-validates all 9 templates

## Testing

- Each template parses without error via `StrParser.parse()`
- Each template has expected sections ($title, $para at minimum)
- New templates have their distinguishing parameters
- Dropdown has 9 entries (6 existing + 3 new)
