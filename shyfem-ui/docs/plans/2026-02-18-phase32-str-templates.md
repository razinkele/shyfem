# Phase 32: STR Template Library Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the STR template library from 6 to 9 templates covering all major SHYFEM simulation scenarios.

**Architecture:** All templates live as raw .str strings in `generate_template()` in `simulation.py`. The dropdown in `simulation_ui()` maps template keys to display names. Tests validate parsing via `StrParser`.

**Tech Stack:** Python, Shiny for Python, pytest

---

### Task 1: Write template parsing tests

**Files:**
- Create: `tests/test_str_templates.py`

**Step 1: Write the tests**

Create `tests/test_str_templates.py`:

```python
"""Tests for STR template library."""

import pytest

from shyfem_ui.pages.simulation import generate_template
from shyfem_ui.services.parser_str import StrParser


ALL_TEMPLATES = [
    "basic_2d",
    "basic_3d",
    "wind_driven",
    "tidal",
    "baroclinic",
    "lagrangian",
    "tidal_estuary",
    "sediment_transport",
    "water_quality",
    "storm_surge",
]


class TestTemplatesParse:
    """Every template must parse without error and have required sections."""

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_template_parses(self, name):
        content = generate_template(name)
        parsed = StrParser.parse(content)
        assert "title" in parsed.sections
        assert "para" in parsed.sections

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_template_not_empty(self, name):
        content = generate_template(name)
        assert len(content.strip()) > 50


class TestWindDriven:
    """Enhanced wind_driven template has Coriolis and diffusion."""

    def test_has_coriolis(self):
        content = generate_template("wind_driven")
        assert "icor" in content

    def test_has_smagorinsky(self):
        content = generate_template("wind_driven")
        assert "idhtyp" in content


class TestTidalEstuary:
    """Tidal estuary template is 3D with salinity."""

    def test_has_3d_levels(self):
        content = generate_template("tidal_estuary")
        assert "nlv" in content

    def test_has_salinity(self):
        content = generate_template("tidal_estuary")
        assert "isalt" in content

    def test_has_baroclinic(self):
        content = generate_template("tidal_estuary")
        assert "ibarcl" in content


class TestSedimentTransport:
    """Sediment transport template activates simple sedi module."""

    def test_has_issedi(self):
        content = generate_template("sediment_transport")
        assert "issedi" in content

    def test_has_3d(self):
        content = generate_template("sediment_transport")
        assert "nlv" in content


class TestWaterQuality:
    """Water quality template activates EUTRO module."""

    def test_has_ibio(self):
        content = generate_template("water_quality")
        assert "ibio" in content

    def test_has_baroclinic(self):
        content = generate_template("water_quality")
        assert "ibarcl" in content


class TestStormSurge:
    """Storm surge template has wetting/drying and Coriolis."""

    def test_has_wetting_drying(self):
        content = generate_template("storm_surge")
        assert "hzoff" in content
        assert "hzon" in content

    def test_has_coriolis(self):
        content = generate_template("storm_surge")
        assert "icor" in content

    def test_has_high_res_timestep(self):
        content = generate_template("storm_surge")
        parsed = StrParser.parse(content)
        idt = parsed.sections["para"].parameters.get("idt", "")
        # Should be <=60s for storm surge
        assert "60" in idt or "30" in idt
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_templates.py -v`
Expected: FAIL — templates `tidal_estuary`, `sediment_transport`, `water_quality`, `storm_surge` don't exist yet, and `wind_driven` lacks `icor`/`idhtyp`.

**Step 3: Commit test file**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/tests/test_str_templates.py
git commit -m "$(cat <<'EOF'
test: add STR template parsing tests for all 9 templates

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Enhance wind_driven template and add 3 new templates

**Files:**
- Modify: `shyfem_ui/pages/simulation.py:77-88` (dropdown choices)
- Modify: `shyfem_ui/pages/simulation.py:531-562` (wind_driven template)
- Modify: `shyfem_ui/pages/simulation.py:713-716` (add new templates before closing brace)

**Step 1: Update dropdown choices**

In `simulation.py`, replace the template dropdown choices (lines 80-88):

```python
                    choices={
                        "": "Select template...",
                        "basic_2d": "Basic 2D Simulation",
                        "basic_3d": "Basic 3D Simulation",
                        "wind_driven": "Wind-driven Flow",
                        "tidal": "Tidal Simulation",
                        "baroclinic": "Baroclinic (T/S)",
                        "lagrangian": "Lagrangian Tracking",
                    },
```

With:

```python
                    choices={
                        "": "Select template...",
                        "basic_2d": "Basic 2D Simulation",
                        "basic_3d": "Basic 3D Simulation",
                        "wind_driven": "Wind-Driven Circulation",
                        "tidal": "Tidal Simulation",
                        "tidal_estuary": "Tidal Estuary (3D)",
                        "baroclinic": "Baroclinic (T/S)",
                        "lagrangian": "Lagrangian Tracking",
                        "sediment_transport": "Sediment Transport",
                        "water_quality": "Water Quality (EUTRO)",
                        "storm_surge": "Storm Surge",
                    },
```

**Step 2: Enhance wind_driven template**

Replace the existing `wind_driven` template string (lines 531-562) with:

```python
        "wind_driven": """
#------------------------------------------------------------------------
# Wind-Driven Circulation Template
# 2D barotropic flow with Coriolis and Smagorinsky diffusion
#------------------------------------------------------------------------

$title
        Wind-Driven Circulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Coriolis (beta-plane)
        icor = 1
        dlat = 45.0

        ! Horizontal diffusion (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
$end

$extra
        1     'center'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
```

**Step 3: Add 3 new templates**

In `generate_template()`, before the closing `}` of the `templates` dict (line 714), add the three new templates:

```python
        "tidal_estuary": """
#------------------------------------------------------------------------
# Tidal Estuary Template
# 3D baroclinic with tidal boundary, river inflow, and salinity
#------------------------------------------------------------------------

$title
        Tidal Estuary
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-10'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D baroclinic mode
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence (GOTM)
        iturb = 1
        difmol = 1.0e-6
        vismol = 1.0e-6

        ! Horizontal mixing (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0

        ! Coriolis
        icor = 1
        dlat = 45.0
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$bound
        ! Open boundary: tidal forcing
        1  1  1  0.5    ! M2 tidal amplitude [m]
        ! River inflow boundary
        ! 2  3  0  100.0  ! Discharge [m3/s], salinity = 0
$end

$extra
        1     'estuary mouth'
        2     'upstream station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! bound = 'INPUT/tide.txt'
        ! saltin = 'INPUT/salt_init.shy'
$end
""",
        "sediment_transport": """
#------------------------------------------------------------------------
# Sediment Transport Template
# 3D with simple sedimentation module
#------------------------------------------------------------------------

$title
        Sediment Transport
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-05'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D setup
        nlv = 10
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Simple sedimentation module
        issedi = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
$end

$levels
        0.5
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
$end

$extra
        1     'monitoring point'
$end

$name
        wind = 'INPUT/wind.txt'
$end

! For full sediment transport, use the $sedtr section instead of issedi:
! $sedtr
!         isedi = 1
!         sedgrs = '0.063 0.125 0.25 0.5'
!         percin = '0.25 0.25 0.25 0.25'
! $end
""",
        "water_quality": """
#------------------------------------------------------------------------
# Water Quality (EUTRO) Template
# 3D baroclinic with 9-variable eutrophication model
#------------------------------------------------------------------------

$title
        Water Quality
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-30'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D baroclinic
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Water quality (WASP/EUTRO 9-variable model)
        ! Variables: NH3, NO3, OPO4, PHYT, CBOD, DO, ON, OP, ZOO
        ibio = 1

        ! Heat flux for temperature evolution
        iheat = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$extra
        1     'monitoring station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! bio2dn = 'INPUT/bio_boundary.txt'
        ! bioin = 'INPUT/bio_initial.shy'
$end
""",
        "storm_surge": """
#------------------------------------------------------------------------
# Storm Surge Template
# 2D barotropic with wetting/drying and meteorological forcing
#------------------------------------------------------------------------

$title
        Storm Surge
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-03'
        idt = '60s'
        idtout = '30m'
        idtext = '60s'

        date = 20200101

        ilin = 1

        ! Wind drag (Wu 1982 — speed-dependent)
        iwtype = 3
        itdrag = 2
        wsmax = 60

        ! Bottom friction
        ireib = 5      czdef = 2.5e-3

        ! Coriolis
        icor = 1
        dlat = 45.0

        ! Spherical coordinates (for real-world domains)
        ! isphe = 1

        ! Wetting and drying
        hzoff = 0.05
        hzon = 0.10
        hzmin = 0.01

        ! Horizontal diffusion
        idhtyp = 2
        ahpar = 1.0
$end

$extra
        1     'tide gauge 1'
        2     'tide gauge 2'
$end

$name
        ! Wind file with optional atmospheric pressure (3rd column)
        wind = 'INPUT/wind.txt'
$end
""",
```

**Step 4: Run all template tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_templates.py -v`
Expected: ALL PASSED (10 parametrized parse tests + individual feature tests)

**Step 5: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: all passed, 0 failed

**Step 6: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/simulation.py
git commit -m "$(cat <<'EOF'
feat: expand STR template library — enhance wind_driven, add 3 new templates

Enhance wind_driven with Coriolis and Smagorinsky diffusion.
Add tidal_estuary (3D baroclinic), sediment_transport (issedi),
water_quality (EUTRO ibio), and storm_surge (wetting/drying).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update TODO_NEXT.md

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md:322-342`

**Step 1: Update Phase 32 section**

Replace:

```markdown
## Phase 32: STR Template Library

> Only 3 simulation templates exist. SHYFEM supports many more scenarios.

- [ ] **32.1** Add Wind-Driven Circulation template
  - Pre-filled: wind forcing, Coriolis, constant depth, 2D barotropic

- [ ] **32.2** Add Tidal Estuary template
  - Pre-filled: tidal boundary, river inflow, salinity transport, 3D baroclinic

- [ ] **32.3** Add Sediment Transport template
  - Pre-filled: sediment module, settling velocity, erosion/deposition params

- [ ] **32.4** Add Water Quality template
  - Pre-filled: oxygen, nutrients, temperature, biological modules

- [ ] **32.5** Add Storm Surge template
  - Pre-filled: atmospheric pressure, wind fields, wetting/drying, high resolution
```

With:

```markdown
## Phase 32: STR Template Library

> Expanded template library covering all major SHYFEM simulation scenarios.

- [x] **32.1** Enhance Wind-Driven Circulation template — added Coriolis, Smagorinsky
  - Was minimal (wind file only). Now has `icor=1`, `idhtyp=2`, `dlat=45`

- [x] **32.2** Add Tidal Estuary template (3D) — new `tidal_estuary`
  - 3D baroclinic with salinity, GOTM turbulence, tidal + river boundaries
  - Separate from existing basic `tidal` (which stays 2D)

- [x] **32.3** Add Sediment Transport template — new `sediment_transport`
  - Simple sedi module (`issedi=1`) with 3D setup
  - Commented `$sedtr` section for advanced full-module usage

- [x] **32.4** Add Water Quality template — new `water_quality`
  - WASP/EUTRO 9-variable model (`ibio=1`), 3D baroclinic, heat flux
  - Bio boundary/initial condition file references

- [x] **32.5** Add Storm Surge template — new `storm_surge`
  - 2D barotropic, `idt=60s`, Wu drag (`itdrag=2`), wetting/drying
  - Coriolis, optional spherical coords, atmospheric pressure
```

**Step 2: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md
git commit -m "$(cat <<'EOF'
docs: mark Phase 32 complete in TODO_NEXT.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
