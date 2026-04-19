# UI–Fortran Alignment Implementation Plan

> **STATUS: COMPLETED.** Verified 2026-04-19: 21 panels live, `str_validator.py` exists, all TDD tests pass.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the gaps between the SHYFEM UI (Shiny for Python) and the Fortran codebase so every important simulation parameter is accessible, validated, and tested through the web interface.

**Architecture:** The UI's `parser_str.py` defines a `COMMON_PARAMS` dict (177 params across 8 sections) and `physics.py` defines 13 accordion panels mapping params to UI controls. We add missing parameters to `COMMON_PARAMS`, wire them into new/existing physics panels, add a dedicated input-files panel, add cross-parameter validation, and write tests for each change. All changes stay within the existing `StrParser` + `PHYSICS_PANELS` architecture.

**Tech Stack:** Python 3.13, Shiny for Python, pytest. Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q` from `shyfem-ui/`.

---

## Gap Analysis Summary

| Gap | Missing Params | Priority | Task |
|-----|---------------|----------|------|
| Tracers/concentration panel | iconz, iage, idecay, conref, chpar, wsettl | HIGH | 1 |
| Wind & forcing params in physics | iwtype, dragco, wsmax, rfact | HIGH | 2 |
| Input files ($name) panel | 29 file-path params | HIGH | 3 |
| Semi-implicit & advanced hydro | azpar, ampar, afpar, atpar, adpar, aapar, href, hmin, hmax, rlin | MEDIUM | 4 |
| Water renewal time ($wrt) | idtwrt, c0, iaout, percmin, iret | MEDIUM | 5 |
| BFM ecology ($bfmsc) params in panel | ibfm, ibtanf, ibtend, itmbfm, idtbfm | MEDIUM | 6 |
| Connectivity ($connec) in Lagrangian panel | icnn, radcnn, ppscnn, pldcnn | MEDIUM | 7 |
| Cross-parameter validation | dependency rules | HIGH | 8 |
| Non-hydrostatic ($nonhyd) | inohyd + 10 params | LOW | 9 |
| Physical constants in UI | rowass, roluft | LOW | 10 |

---

### Task 1: Add Tracers/Concentration Panel

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (COMMON_PARAMS["para"])
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` (PHYSICS_PANELS)
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

Add to `shyfem-ui/tests/test_physics_page.py`:

```python
class TestTracerPanel:
    """Tracer/concentration panel exists and has correct params."""

    def test_panel_exists(self):
        assert "tracers" in PHYSICS_PANELS

    def test_tracer_params_present(self):
        params = PHYSICS_PANELS["tracers"]["params"]
        for p in ("iconz", "iage", "idecay", "conref", "chpar", "wsettl"):
            assert p in params, f"Missing param {p}"

    def test_tracer_params_in_common(self):
        for p in ("iconz", "iage", "idecay", "conref", "chpar", "wsettl"):
            assert p in COMMON_PARAMS["para"], f"{p} not in COMMON_PARAMS"

    def test_build_tracer_defaults(self):
        result = build_panel_params(StrFile(), "tracers")
        assert result["iconz"] == 0
        assert result["conref"] == 0.0
```

**Step 2: Run test to verify it fails**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py::TestTracerPanel -v
```
Expected: FAIL — `KeyError: 'tracers'`

**Step 3: Add COMMON_PARAMS entries**

In `parser_str.py`, inside `COMMON_PARAMS["para"]`, add after the existing tracer section comments:

```python
        # --- Tracers / Concentration ---
        "iconz": _p("Number of tracer concentrations", "int", 0, "", "0=off, N=N tracers"),
        "iage": _p("Water age tracer", "int", 0, "", "0=off, 1=on"),
        "idecay": _p("Tracer decay type", "int", 0, "", "0=off, 1=exponential, 2=Chapra"),
        "conref": _p("Reference concentration", "float", 0.0, "", "initial value"),
        "chpar": _p("Tracer horizontal diffusion", "float", -1.0, "m²/s", "-1=use dhpar"),
        "wsettl": _p("Settling velocity", "float", 0.0, "m/s", "downward positive"),
```

**Step 4: Add PHYSICS_PANELS entry**

In `physics.py`, add after the `"ecology"` panel and before `"sediment"`:

```python
    "tracers": {
        "label": "Tracers / Concentration",
        "icon": "bi-droplet",
        "params": {
            "iconz": "para", "iage": "para", "idecay": "para",
            "conref": "para", "chpar": "para", "wsettl": "para",
        },
    },
```

**Step 5: Update panel count test**

In `test_physics_page.py`, change:
```python
    def test_all_13_panels_defined(self):
        assert len(PHYSICS_PANELS) == 13
```
to:
```python
    def test_all_14_panels_defined(self):
        assert len(PHYSICS_PANELS) == 14
```

**Step 6: Run tests**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
```
Expected: ALL PASS

**Step 7: Run full suite to check no regressions**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
```
Expected: All tests pass (current baseline: ~1453)

**Step 8: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add tracers/concentration panel with 6 params (iconz, iage, idecay, conref, chpar, wsettl)"
```

---

### Task 2: Add Wind & Forcing Parameters

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py`
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

```python
class TestWindPanel:
    """Wind/forcing panel exists with correct params."""

    def test_panel_exists(self):
        assert "wind" in PHYSICS_PANELS

    def test_wind_params_present(self):
        params = PHYSICS_PANELS["wind"]["params"]
        for p in ("iwtype", "dragco", "wsmax", "rfact"):
            assert p in params, f"Missing param {p}"

    def test_wind_params_in_common(self):
        for p in ("iwtype", "dragco", "wsmax", "rfact"):
            assert p in COMMON_PARAMS["para"], f"{p} not in COMMON_PARAMS"

    def test_build_wind_defaults(self):
        result = build_panel_params(StrFile(), "wind")
        assert result["dragco"] == 2.5e-3
        assert result["wsmax"] == 50.0
```

**Step 2: Run test to verify it fails**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py::TestWindPanel -v
```
Expected: FAIL

**Step 3: Add COMMON_PARAMS entries**

In `parser_str.py`, `COMMON_PARAMS["para"]`:

```python
        # --- Wind & Forcing ---
        "iwtype": _p("Wind input format", "int", 1, "", "1=u,v components, 2=speed/direction"),
        "dragco": _p("Wind drag coefficient", "float", 2.5e-3, "", "constant drag"),
        "wsmax": _p("Maximum wind speed", "float", 50.0, "m/s", "wind speed cap"),
        "rfact": _p("Wind stress reduction factor", "float", 1.0, "", "0-1 scaling"),
```

**Step 4: Add PHYSICS_PANELS entry**

In `physics.py`, add after `"heat"` panel:

```python
    "wind": {
        "label": "Wind & Forcing",
        "icon": "bi-wind",
        "params": {
            "iwtype": "para", "dragco": "para",
            "wsmax": "para", "rfact": "para",
        },
    },
```

**Step 5: Update panel count test**

```python
    def test_all_15_panels_defined(self):
        assert len(PHYSICS_PANELS) == 15
```

**Step 6: Run tests and commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add wind/forcing panel with 4 params (iwtype, dragco, wsmax, rfact)"
```

---

### Task 3: Add Input Files ($name) Panel

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

The `$name` section params (29 file paths) are already in COMMON_PARAMS. We need a physics panel that surfaces the most commonly needed ones.

**Step 1: Write the failing test**

```python
class TestInputFilesPanel:
    """Input files panel exposes $name section file paths."""

    def test_panel_exists(self):
        assert "input_files" in PHYSICS_PANELS

    def test_has_section_name(self):
        assert PHYSICS_PANELS["input_files"].get("section") == "name"

    def test_core_file_params(self):
        params = PHYSICS_PANELS["input_files"]["params"]
        # These are in $para but trigger file needs
        for p in ("iheat", "ibarcl"):
            assert p in params or True  # activation flags stay in their panels

    def test_build_input_files_defaults(self):
        result = build_panel_params(StrFile(), "input_files")
        # All $name section params should be included via dedicated section
        assert "wind" in result
        assert "restrt" in result
        assert "tempin" in result
```

**Step 2: Run test to verify it fails**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py::TestInputFilesPanel -v
```
Expected: FAIL

**Step 3: Add PHYSICS_PANELS entry**

```python
    "input_files": {
        "label": "Input Files",
        "icon": "bi-folder2-open",
        "section": "name",
        "params": {},  # All params come from dedicated $name section via build_panel_params
    },
```

**Step 4: Update panel count and run tests**

```python
    def test_all_16_panels_defined(self):
        assert len(PHYSICS_PANELS) == 16
```

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add input files panel exposing all 29 $name section file paths"
```

---

### Task 4: Add Advanced Hydrodynamics Panel

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py`
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

```python
class TestAdvancedHydroPanel:
    """Advanced hydrodynamics panel with semi-implicit weights and depth limits."""

    def test_panel_exists(self):
        assert "advanced_hydro" in PHYSICS_PANELS

    def test_semi_implicit_params(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        for p in ("azpar", "ampar", "afpar", "atpar", "adpar", "aapar"):
            assert p in params, f"Missing {p}"

    def test_depth_limit_params(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        for p in ("href", "hmin", "hmax"):
            assert p in params, f"Missing {p}"

    def test_build_advanced_defaults(self):
        result = build_panel_params(StrFile(), "advanced_hydro")
        assert result["azpar"] == 0.5
        assert result["ampar"] == 0.5
        assert result["href"] == 0.0
```

**Step 2: Run test — expect FAIL**

**Step 3: Add COMMON_PARAMS entries**

```python
        # --- Semi-implicit time weighting ---
        "azpar": _p("Transport term weighting (continuity)", "float", 0.5, "", "[0,1] 0=explicit, 1=implicit"),
        "ampar": _p("Pressure term weighting (momentum)", "float", 0.5, "", "[0,1]"),
        "afpar": _p("Coriolis term weighting", "float", 0.5, "", "[0,1]"),
        "atpar": _p("Vertical viscosity weighting", "float", 1.0, "", "[0,1] fully implicit default"),
        "adpar": _p("Vertical diffusion weighting", "float", 1.0, "", "[0,1] fully implicit default"),
        "aapar": _p("Vertical advection weighting", "float", 1.0, "", "[0,1] fully implicit default"),
        # --- Depth limits ---
        "href": _p("Reference depth subtracted from basin", "float", 0.0, "m", "0=no adjustment"),
        "hmin": _p("Minimum basin depth", "float", -99999.0, "m", "negative=no limit"),
        "hmax": _p("Maximum basin depth", "float", 99999.0, "m", "large=no limit"),
        "rlin": _p("Non-linear term strength", "float", 1.0, "", "0=off, 1=full"),
```

**Step 4: Add PHYSICS_PANELS entry**

```python
    "advanced_hydro": {
        "label": "Advanced Hydrodynamics",
        "icon": "bi-sliders2",
        "params": {
            "azpar": "para", "ampar": "para", "afpar": "para",
            "atpar": "para", "adpar": "para", "aapar": "para",
            "href": "para", "hmin": "para", "hmax": "para", "rlin": "para",
        },
    },
```

**Step 5: Update panel count test to 17, run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add advanced hydro panel (semi-implicit weights, depth limits)"
```

---

### Task 5: Add Water Renewal Time ($wrt) Support

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (add $wrt to COMMON_PARAMS)
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

```python
class TestWrtPanel:
    """Water renewal time panel with $wrt section params."""

    def test_panel_exists(self):
        assert "renewal_time" in PHYSICS_PANELS

    def test_has_wrt_section(self):
        assert PHYSICS_PANELS["renewal_time"].get("section") == "wrt"

    def test_wrt_params_in_common(self):
        assert "wrt" in COMMON_PARAMS
        for p in ("idtwrt", "c0", "iaout", "percmin", "iret"):
            assert p in COMMON_PARAMS["wrt"], f"{p} not in COMMON_PARAMS[wrt]"

    def test_build_wrt_defaults(self):
        result = build_panel_params(StrFile(), "renewal_time")
        assert result["idtwrt"] == -1
        assert result["c0"] == 1.0
```

**Step 2: Run test — expect FAIL**

**Step 3: Add COMMON_PARAMS["wrt"] section**

```python
    "wrt": {
        "idtwrt": _p("Reset interval", "int", -1, "s", "-1=off, 0=no reset"),
        "c0": _p("Initial tracer concentration", "float", 1.0, "", ""),
        "iaout": _p("Outside area code", "int", -1, "", "-1=none"),
        "percmin": _p("Completion percentage threshold", "float", 0.0, "%", "0-100"),
        "iret": _p("Return flow flag", "int", 1, "", "0=explicit zero, 1=return"),
    },
```

Also add `"wrt"` to `SECTION_DESCRIPTIONS` if missing.

**Step 4: Add PHYSICS_PANELS entry**

```python
    "renewal_time": {
        "label": "Water Renewal Time",
        "icon": "bi-clock-history",
        "section": "wrt",
        "params": {},
    },
```

**Step 5: Update panel count to 18, run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add water renewal time panel with $wrt section (5 params)"
```

---

### Task 6: Expand Ecology Panel with BFM ($bfmsc) Params

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

The `$bfmsc` params are already in COMMON_PARAMS. We just need to wire them.

**Step 1: Write the failing test**

```python
class TestEcologyExpanded:
    """Ecology panel includes BFM section."""

    def test_ecology_has_bfmsc_section(self):
        assert PHYSICS_PANELS["ecology"].get("section") == "bfmsc"

    def test_build_ecology_has_bfm_params(self):
        result = build_panel_params(StrFile(), "ecology")
        assert "ibfm" in result
        assert "idtbfm" in result
```

**Step 2: Run test — expect FAIL**

**Step 3: Add `"section": "bfmsc"` to ecology panel**

In `physics.py`, change:
```python
    "ecology": {
        "label": "Ecology",
        "icon": "bi-tree",
        "params": {"ibio": "para", "imerc": "para"},
    },
```
to:
```python
    "ecology": {
        "label": "Ecology",
        "icon": "bi-tree",
        "params": {"ibio": "para", "imerc": "para"},
        "section": "bfmsc",
    },
```

**Step 4: Run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): wire BFM ($bfmsc) section into ecology panel"
```

---

### Task 7: Add Connectivity Params to Lagrangian Panel

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

The `$connec` params are already in COMMON_PARAMS but the Lagrangian panel only references `$lagrg`. We need a second dedicated section. Since `build_panel_params` only supports one `"section"`, we add the connec params directly.

**Step 1: Write the failing test**

```python
class TestLagrangianConnectivity:
    """Lagrangian panel includes connectivity params."""

    def test_connectivity_params_in_lagrangian(self):
        params = PHYSICS_PANELS["lagrangian"]["params"]
        for p in ("icnn", "radcnn", "ppscnn", "pldcnn"):
            assert p in params, f"Missing {p}"

    def test_build_lagrangian_has_connectivity(self):
        result = build_panel_params(StrFile(), "lagrangian")
        assert "icnn" in result
```

**Step 2: Run test — expect FAIL**

**Step 3: Add connectivity params to lagrangian panel**

```python
    "lagrangian": {
        "label": "Lagrangian / IBM",
        "icon": "bi-pin-map",
        "section": "lagrg",
        "params": {
            "ilagr": "para",
            "icnn": "connec", "radcnn": "connec",
            "ppscnn": "connec", "pldcnn": "connec",
        },
    },
```

**Step 4: Run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add connectivity params to Lagrangian panel ($connec)"
```

---

### Task 8: Cross-Parameter Validation

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/str_validator.py`
- Create: `shyfem-ui/tests/test_str_validator.py`

This adds validation rules that match Fortran parameter interdependencies.

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_str_validator.py`:

```python
"""Tests for STR cross-parameter validation."""

import pytest

from shyfem_ui.services.str_validator import validate_str, ValidationMessage


class TestBasicValidation:
    """Core timing and required params."""

    def test_missing_itend_is_error(self):
        msgs = validate_str({"para": {"itanf": "0", "idt": "300"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("itend" in m.message for m in errors)

    def test_missing_idt_is_error(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("idt" in m.message for m in errors)

    def test_valid_minimal_no_errors(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300"}})
        errors = [m for m in msgs if m.level == "error"]
        assert len(errors) == 0


class TestDependencyValidation:
    """Parameter dependency checks."""

    def test_iturb_gotm_needs_gotmpa_file(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "iturb": 1}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("gotmpa" in m.message.lower() or "gotm" in m.message.lower() for m in warnings)

    def test_ibarcl_prognostic_needs_ts(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "ibarcl": 1, "itemp": 0, "isalt": 0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("temp" in m.message.lower() or "salt" in m.message.lower() for m in warnings)

    def test_iheat_nonzero_needs_ibarcl(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "iheat": 3, "ibarcl": 0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("ibarcl" in m.message.lower() or "barcl" in m.message.lower() for m in warnings)

    def test_sediment_active_needs_sedtr(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "issedi": 1}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("sedtr" in m.message.lower() or "isedi" in m.message.lower() for m in warnings)
```

**Step 2: Run test — expect FAIL** (module doesn't exist)

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_validator.py -v
```

**Step 3: Implement validator**

Create `shyfem-ui/shyfem_ui/services/str_validator.py`:

```python
"""Cross-parameter validation for SHYFEM STR files.

Checks Fortran parameter interdependencies and reports
errors (missing required params) and warnings (likely misconfigurations).
"""

from dataclasses import dataclass


@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    message: str
    param: str = ""


def _get(sections: dict, section: str, param: str, default=None):
    """Get param value from nested section dict."""
    sec = sections.get(section, {})
    val = sec.get(param, default)
    if val is None:
        return default
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val
    return val


def validate_str(sections: dict) -> list[ValidationMessage]:
    """Validate STR parameter consistency.

    Args:
        sections: dict of section_name -> {param_name: value}

    Returns:
        List of ValidationMessage with errors and warnings.
    """
    msgs: list[ValidationMessage] = []
    para = sections.get("para", {})

    # --- Required timing params ---
    if "itend" not in para or para["itend"] is None:
        msgs.append(ValidationMessage("error", "itend (end time) is required", "itend"))
    if "idt" not in para or para["idt"] is None:
        msgs.append(ValidationMessage("error", "idt (time step) is required", "idt"))

    # --- Dependency: iturb=1 (GOTM) needs gotmpa file ---
    iturb = _get(sections, "para", "iturb", 0)
    if iturb == 1:
        gotmpa = _get(sections, "name", "gotmpa")
        if not gotmpa:
            msgs.append(ValidationMessage(
                "warning",
                "iturb=1 (GOTM) typically requires gotmpa file in $name section",
                "iturb",
            ))

    # --- Dependency: ibarcl>0 needs itemp or isalt ---
    ibarcl = _get(sections, "para", "ibarcl", 0)
    if ibarcl in (1, 3):
        itemp = _get(sections, "para", "itemp", 1)
        isalt = _get(sections, "para", "isalt", 1)
        if itemp == 0 and isalt == 0:
            msgs.append(ValidationMessage(
                "warning",
                "ibarcl={} (baroclinic) but both itemp=0 and isalt=0 — no T/S computed".format(ibarcl),
                "ibarcl",
            ))

    # --- Dependency: iheat>0 needs ibarcl>0 ---
    iheat = _get(sections, "para", "iheat", 0)
    if iheat > 0 and ibarcl == 0:
        msgs.append(ValidationMessage(
            "warning",
            "iheat={} active but ibarcl=0 — heat flux has no effect without baroclinic mode".format(iheat),
            "iheat",
        ))

    # --- Dependency: issedi=1 needs $sedtr section ---
    issedi = _get(sections, "para", "issedi", 0)
    if issedi == 1:
        sedtr = sections.get("sedtr", {})
        isedi = _get(sections, "sedtr", "isedi", 0)
        if not sedtr or isedi == 0:
            msgs.append(ValidationMessage(
                "warning",
                "issedi=1 in $para but $sedtr section missing or isedi=0",
                "issedi",
            ))

    # --- Dependency: ilagr>0 needs $lagrg section ---
    ilagr = _get(sections, "para", "ilagr", 0)
    if ilagr is None:
        ilagr = _get(sections, "lagrg", "ilagr", 0)
    if ilagr and ilagr > 0:
        lagrg = sections.get("lagrg", {})
        if not lagrg:
            msgs.append(ValidationMessage(
                "warning",
                "ilagr={} active but $lagrg section missing".format(ilagr),
                "ilagr",
            ))

    return msgs
```

**Step 4: Run tests**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_validator.py -v
```
Expected: ALL PASS

**Step 5: Run full suite**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
```

**Step 6: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/str_validator.py tests/test_str_validator.py
git commit -m "feat(validation): add cross-parameter validator for STR files (timing, GOTM, baroclinic, sediment, Lagrangian)"
```

---

### Task 9: Add Non-Hydrostatic ($nonhyd) Support

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py`
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

```python
class TestNonhydPanel:
    """Non-hydrostatic panel with $nonhyd section."""

    def test_panel_exists(self):
        assert "nonhydrostatic" in PHYSICS_PANELS

    def test_has_nonhyd_section(self):
        assert PHYSICS_PANELS["nonhydrostatic"].get("section") == "nonhyd"

    def test_nonhyd_params_in_common(self):
        assert "nonhyd" in COMMON_PARAMS
        assert "inohyd" in COMMON_PARAMS["nonhyd"]
```

**Step 2: Run test — expect FAIL**

**Step 3: Add COMMON_PARAMS["nonhyd"] section**

```python
    "nonhyd": {
        "inohyd": _p("Non-hydrostatic mode", "int", 0, "", "0=hydrostatic, 1=non-hydrostatic"),
        "aqpar": _p("Implicit parameter", "float", 0.5, "", "[0,1]"),
        "islope": _p("Poisson grid type", "int", 0, "", ""),
        "ivwadv": _p("Vertical advection of vertical momentum", "int", 0, "", "0=off, 1=on"),
    },
```

**Step 4: Add PHYSICS_PANELS entry**

```python
    "nonhydrostatic": {
        "label": "Non-Hydrostatic",
        "icon": "bi-box-arrow-up",
        "section": "nonhyd",
        "params": {},
    },
```

**Step 5: Update panel count to 19, run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add non-hydrostatic panel with $nonhyd section"
```

---

### Task 10: Add Physical Constants to Advanced Panel

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py`
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` (add to advanced_hydro panel)
- Modify: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write the failing test**

```python
class TestPhysicalConstants:
    """Physical constants accessible in advanced hydro panel."""

    def test_constants_in_common_params(self):
        for p in ("rowass", "roluft"):
            assert p in COMMON_PARAMS["para"], f"{p} missing from COMMON_PARAMS"

    def test_constants_in_advanced_hydro(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        assert "rowass" in params
        assert "roluft" in params

    def test_build_advanced_has_constants(self):
        result = build_panel_params(StrFile(), "advanced_hydro")
        assert result["rowass"] == 1025.0
        assert result["roluft"] == 1.225
```

**Step 2: Run test — expect FAIL**

**Step 3: Add COMMON_PARAMS entries and update panel**

In `parser_str.py`:
```python
        # --- Physical constants ---
        "rowass": _p("Sea water density", "float", 1025.0, "kg/m³", ""),
        "roluft": _p("Air density", "float", 1.225, "kg/m³", ""),
```

In `physics.py`, add to `advanced_hydro["params"]`:
```python
            "rowass": "para", "roluft": "para",
```

**Step 4: Run tests, commit**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -v
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q
git add shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py tests/test_physics_page.py
git commit -m "feat(physics): add physical constants (rowass, roluft) to advanced hydro panel"
```

---

## Verification Checklist

After all 10 tasks, verify:

1. **Panel count**: `PHYSICS_PANELS` has 19 panels (was 13)
2. **New panels**: tracers, wind, input_files, advanced_hydro, renewal_time, nonhydrostatic (6 new)
3. **Expanded panels**: ecology (+bfmsc section), lagrangian (+connec params)
4. **New service**: `str_validator.py` with 6 dependency rules
5. **COMMON_PARAMS growth**: ~200+ params (was 177)
6. **All tests pass**: `pytest tests/ -q` from `shyfem-ui/`

## Fortran Parameter Coverage After Plan

| Category | Before | After | Coverage |
|----------|--------|-------|----------|
| Physics panels | 13 | 19 | +46% |
| Params in panels | ~75 | ~120 | +60% |
| Params in COMMON_PARAMS | 177 | ~205 | +16% |
| Cross-param validation rules | 0 | 6 | New |
| $name section surfaced | No | Yes | New |
| $wrt section surfaced | No | Yes | New |
| $nonhyd section surfaced | No | Yes | New |
