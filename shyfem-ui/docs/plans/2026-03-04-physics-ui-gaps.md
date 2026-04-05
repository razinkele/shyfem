# Physics UI Gap Closure — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all gaps between SHYFEM Fortran simulation capabilities and the UI by expanding parameter metadata, adding a physics configuration page, enhancing boundary/template/workflow support.

**Architecture:** Three-layer approach: (1) expand `COMMON_PARAMS` data in `parser_str.py` so the existing STR editor benefits immediately, (2) build a new `pages/physics.py` with 13 accordion panels for guided configuration, (3) enhance boundary editor, templates, run-page workflows, and post-processing.

**Tech Stack:** Python 3.13, Shiny for Python, parser_str.py (no external deps for data layer), pytest

**Test command:** `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -v`

**Baseline:** 1376 tests passing

---

## Task 1: Expand $para with missing module activation & restart params

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py:446-455` (after existing module activation params)
- Test: `shyfem-ui/tests/test_parser_str.py`

**Step 1: Write failing tests**

Add to `tests/test_parser_str.py` at end of `TestCommonParams` class:

```python
    def test_common_params_has_restart_params(self):
        """Restart and offline params are defined in $para."""
        for param in ("itrst", "itmrst", "ityrst", "idtoff", "itmoff"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"

    def test_common_params_has_wave_and_mercury(self):
        """Wave coupling and mercury params are defined in $para."""
        for param in ("iwave", "dtwave", "imerc"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"
```

**Step 2: Run tests — expect FAIL**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py::TestCommonParams::test_common_params_has_restart_params tests/test_parser_str.py::TestCommonParams::test_common_params_has_wave_and_mercury -v
```

Expected: FAIL — `AssertionError: Missing itrst`

**Step 3: Add the params to parser_str.py**

In `parser_str.py`, add after the `icemod` line (line ~451), before the `# --- Grid/partition ---` comment:

```python
        # --- Waves ---
        "iwave": _p(
            "Wave coupling mode", "int", 0, "",
            "0=off, 1=constant file, 2=WWMIII rad+SHYFEM wind, 3=WWMIII vort+SHYFEM wind, "
            "4=WWMIII rad+WWM wind, 5=WWMIII vort+WWM wind",
        ),
        "dtwave": _p("Wave-current coupling time step", "float", 0.0, "s", ">0 when iwave>0"),
        # --- Mercury ---
        "imerc": _p("Mercury contamination model", "int", 0, "", "0=off, 1=on"),
        # --- Restart ---
        "itrst": _p("Restart file write interval", "string", "0", "s", "-1=last step only"),
        "itmrst": _p("Restart output start time", "string", "-1", "", "date or seconds"),
        "ityrst": _p(
            "Restart mode", "int", 1, "",
            "0=strict match, 1=cold-start if missing, 2=closest time",
        ),
        # --- Offline mode ---
        "idtoff": _p(
            "Offline mode", "int", 0, "",
            "0=off, >0=write hydro, -1=read hydro, -2=read T/S, -4=read turb, -3/-7=combos",
        ),
        "itmoff": _p("Offline start time", "string", "-1", "", "date or seconds"),
```

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/parser_str.py tests/test_parser_str.py
git commit -m "feat(parser): add wave, mercury, restart, offline params to COMMON_PARAMS"
```

---

## Task 2: Update existing $para param descriptions (ireib, iheat, ibarcl, ibtyp)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py:372,382-388,426-428,479`
- Test: `shyfem-ui/tests/test_parser_str.py`

**Step 1: Write failing tests**

```python
    def test_ireib_description_has_all_models(self):
        """ireib description lists all 11 friction models (0-10)."""
        desc = COMMON_PARAMS["para"]["ireib"][4]  # options field
        for keyword in ("Chezy", "Strickler", "roughness", "fluid mud", "hybrid"):
            assert keyword.lower() in desc.lower(), f"ireib missing {keyword}"

    def test_iheat_description_has_coare(self):
        """iheat description includes COARE algorithm."""
        desc = COMMON_PARAMS["para"]["iheat"][4]
        assert "COARE" in desc

    def test_ibarcl_description_has_nudging(self):
        """ibarcl description includes nudging and assimilation modes."""
        desc = COMMON_PARAMS["para"]["ibarcl"][4]
        assert "nudging" in desc.lower()

    def test_bound_ibtyp_has_radiation(self):
        """ibtyp description includes radiation boundary type."""
        desc = COMMON_PARAMS["bound"]["ibtyp"][4]
        assert "radiation" in desc.lower() or "31" in desc
```

**Step 2: Run tests — expect FAIL**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py::TestCommonParams::test_ireib_description_has_all_models tests/test_parser_str.py::TestCommonParams::test_iheat_description_has_coare tests/test_parser_str.py::TestCommonParams::test_ibarcl_description_has_nudging tests/test_parser_str.py::TestCommonParams::test_bound_ibtyp_has_radiation -v
```

**Step 3: Update description strings**

Replace the following in `parser_str.py`:

`ireib` line (~372):
```python
        "ireib": _p(
            "Bottom friction type", "int", 0, "",
            "0=none, 1=Chezy law, 2=Strickler, 3=Chezy coeff, 4=linear, "
            "5=quadratic drag, 6=roughness z0, 7=Strickler+drag, "
            "8=sediment z0, 9=fluid mud, 10=hybrid quad-linear",
        ),
```

`iheat` line (~382-388):
```python
        "iheat": _p(
            "Heat flux algorithm", "int", 1, "",
            "0=off, 1=AREG, 2=POM bulk, 3=Gill, 4=Dejak, 5=GOTM, "
            "6=COARE 3.0, 7=read from file, 8=MFS bulk",
        ),
```

`ibarcl` line (~426-428):
```python
        "ibarcl": _p(
            "Baroclinic mode", "int", 0, "",
            "0=off, 1=diagnostic, 2=T/S diagnostic, 3=prognostic, 4=nudging, 5=assimilation",
        ),
```

`ibtyp` in `$bound` section (~479):
```python
        "ibtyp": _p(
            "Boundary type", "int", 1, "",
            "-1=closed, 0=off, 1=water level, 2=discharge, 3=volume inlet, "
            "4=momentum, 5=fixed scalar, 31=radiation/zero-gradient",
        ),
```

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/parser_str.py tests/test_parser_str.py
git commit -m "feat(parser): expand ireib/iheat/ibarcl/ibtyp descriptions with all options"
```

---

## Task 3: Add $name ecology/sediment/lagrangian file entries

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py:456-476` ($name section)
- Test: `shyfem-ui/tests/test_parser_str.py`

**Step 1: Write failing tests**

```python
    def test_common_params_name_has_ecology_files(self):
        """$name section has ecology input file entries."""
        for f in ("bioin", "biosin", "biocon", "biolight", "mercin", "bfmini"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_sediment_files(self):
        """$name section has sediment input file entries."""
        for f in ("sedp", "sedt", "sedcon"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_lagrangian_files(self):
        """$name section has lagrangian input file entries."""
        for f in ("lgrlin", "lgrtrj", "statcnn", "surfvel"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_scalar_boundary_files(self):
        """$name section has scalar boundary file entries."""
        for f in ("saltn", "tempn", "conzn"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"
```

**Step 2: Run tests — expect FAIL**

**Step 3: Add entries to `$name` section in parser_str.py**

After the existing `basnam` entry (~line 475), add:

```python
        # Ecology
        "bioin": _p("Initial pelagic ecology state file", "string", "", "", ""),
        "biosin": _p("Initial sediment ecology state file", "string", "", "", ""),
        "biocon": _p("Biogeochemical constants file", "string", "", "", ""),
        "biolight": _p("Light extinction data file", "string", "", "", ""),
        "mercin": _p("Initial mercury concentrations file", "string", "", "", ""),
        "bfmini": _p("Initial BFM state file", "string", "", "", ""),
        # Sediment
        "sedp": _p("Spatially varying sediment distribution file", "string", "", "", ""),
        "sedt": _p("Spatially varying critical erosion stress file", "string", "", "", ""),
        "sedcon": _p("Sediment model constants file", "string", "", "", ""),
        # Lagrangian / Nudging
        "lgrlin": _p("Lagrangian release area lines file", "string", "", "", ""),
        "lgrtrj": _p("Drifter trajectory file", "string", "", "", ""),
        "statcnn": _p("Connectivity station coordinates file", "string", "", "", ""),
        "surfvel": _p("Surface velocity nudging file", "string", "", "", ""),
        # Scalar boundary files
        "saltn": _p("Boundary salinity time series file", "string", "", "", ""),
        "tempn": _p("Boundary temperature time series file", "string", "", "", ""),
        "conzn": _p("Boundary concentration time series file", "string", "", "", ""),
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/parser_str.py tests/test_parser_str.py
git commit -m "feat(parser): add ecology, sediment, lagrangian, scalar boundary files to \$name"
```

---

## Task 4: Add new COMMON_PARAMS sections ($sedtr, $lagrg, $connec, $bfmsc, $nduge)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (after `$bound` section, ~line 484)
- Test: `shyfem-ui/tests/test_parser_str.py`

**Step 1: Write failing tests**

```python
    def test_common_params_has_sedtr_section(self):
        """COMMON_PARAMS has $sedtr section with key params."""
        assert "sedtr" in COMMON_PARAMS
        for p in ("isedi", "sedgrs", "percin", "tauin", "sedhpar"):
            assert p in COMMON_PARAMS["sedtr"], f"Missing {p} in $sedtr"

    def test_common_params_has_lagrg_section(self):
        """COMMON_PARAMS has $lagrg section with key params."""
        assert "lagrg" in COMMON_PARAMS
        for p in ("ilagr", "nbdy", "nbdymax", "ioil", "ilarv", "lbeach", "ldecay"):
            assert p in COMMON_PARAMS["lagrg"], f"Missing {p} in $lagrg"

    def test_common_params_has_connec_section(self):
        """COMMON_PARAMS has $connec section."""
        assert "connec" in COMMON_PARAMS
        for p in ("icnn", "radcnn", "ppscnn", "pldcnn"):
            assert p in COMMON_PARAMS["connec"], f"Missing {p} in $connec"

    def test_common_params_has_bfmsc_section(self):
        """COMMON_PARAMS has $bfmsc section."""
        assert "bfmsc" in COMMON_PARAMS
        assert "ibfm" in COMMON_PARAMS["bfmsc"]

    def test_common_params_has_nduge_section(self):
        """COMMON_PARAMS has $nduge data assimilation section."""
        assert "nduge" in COMMON_PARAMS
        for p in ("nvars", "tramp", "ttau", "sigma"):
            assert p in COMMON_PARAMS["nduge"], f"Missing {p} in $nduge"
```

**Step 2: Run tests — expect FAIL**

**Step 3: Add sections to COMMON_PARAMS**

After the closing `}` of the `"bound"` dict (line ~484), add:

```python
    "sedtr": {
        "isedi": _p("Enable full sediment transport", "int", 0, "", "0=off, 1=on"),
        "sedgrs": _p("Grain sizes (space-separated, fine to coarse)", "string", "", "mm", ""),
        "percin": _p("Initial grain size fractions (must sum to 1.0)", "string", "", "", ""),
        "tauin": _p("Critical erosion stress per grain class", "string", "", "Pa", ""),
        "irocks": _p("Element type excluded from erosion", "int", -1, "", "-1=none"),
        "sedref": _p("Initial reference sediment concentration", "float", 0.0, "kg/m3", ">=0"),
        "sedhpar": _p("Sediment horizontal diffusion", "float", 0.0, "m2/s", ">=0"),
        "adjtime": _p("Morphology equilibration time", "float", -1.0, "s", "-1=off"),
        "idtsed": _p("Sediment output interval", "int", 0, "s", ""),
        "itmsed": _p("Sediment output start time", "int", -1, "s", ""),
    },
    "lagrg": {
        "ilagr": _p("Lagrangian mode", "int", 0, "", "0=off, 1=surface, 2=2D, 3=3D"),
        "nbdy": _p("Particles per release event", "int", 0, "", ">=0"),
        "nbdymax": _p("Max particles in domain", "int", -1, "", "-1=unlimited"),
        "rwhpar": _p("Horizontal diffusion for particles", "float", 0.0, "m2/s", "-1=local"),
        "idtl": _p("Particle release interval", "int", 0, "s", ">0"),
        "ipvert": _p("Vertical distribution", "int", 0, "", "0=surface, >0=regular, <0=random"),
        "lbeach": _p("Beaching probability", "float", 0.0, "", "[0-1]"),
        "ldecay": _p("Particle decay time", "float", 0.0, "s", "0=no decay"),
        "ioil": _p("Oil spill simulation", "int", 0, "", "0=off, 1=on"),
        "ilarv": _p("Larval behavior module", "int", 0, "", "0=off, 1=on"),
        "stkpar": _p("Stokes drift calibration", "float", 0.0, "", ""),
        "dripar": _p("Drifter inertia multiplier", "float", 1.0, "", ">0"),
        "itlanf": _p("Lagrangian start time", "int", -1, "", "-1=use itanf"),
        "itlend": _p("Lagrangian end time", "int", -1, "", "-1=use itend"),
        "idtlgr": _p("Lagrangian output interval", "int", 0, "s", ">0"),
    },
    "connec": {
        "icnn": _p("Number of connectivity stations", "int", 0, "", ">=0"),
        "radcnn": _p("Release area radius", "float", 0.0, "m", ">0"),
        "ppscnn": _p("Particles per second per station", "float", 0.0, "1/s", ">0"),
        "pldcnn": _p("Pelagic larval duration", "float", 0.0, "days", ">0"),
        "idtcnn": _p("Connectivity output interval", "int", 0, "s", ">0"),
    },
    "bfmsc": {
        "ibfm": _p("Enable BFM biogeochemical model", "int", 0, "", "0=off, 1=on"),
        "ibtanf": _p("BFM start time", "int", 0, "", ""),
        "ibtend": _p("BFM end time", "int", 0, "", ""),
        "itmbfm": _p("BFM output start time", "int", -1, "", ""),
        "idtbfm": _p("BFM output interval", "int", 0, "s", ">0"),
    },
    "nduge": {
        "nvars": _p("Number of nudging observation stations", "int", 0, "", "0-50"),
        "tramp": _p("Nudging ramp-up time", "float", 0.0, "s", ">=0"),
        "ttau": _p("Relaxation time constant", "float", 0.0, "s", ">0"),
        "sigma": _p("Spatial influence radius (Gaussian)", "float", 0.0, "m", ">0"),
        "bmulti": _p("Multi-station nudging", "int", 1, "", "0=off, 1=on"),
    },
```

Also add to `COMMON_SECTIONS` (after line ~309):

```python
    "lagrg": "Lagrangian particle tracking (IBM, oil spill, connectivity)",
    "connec": "Particle connectivity analysis (source-destination tracking)",
    "bfmsc": "BFM biogeochemical flux model",
    "nduge": "Data assimilation via zeta/velocity nudging",
```

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/parser_str.py tests/test_parser_str.py
git commit -m "feat(parser): add \$sedtr, \$lagrg, \$connec, \$bfmsc, \$nduge sections"
```

---

## Task 5: Add parse round-trip tests for new sections

**Files:**
- Test: `shyfem-ui/tests/test_parser_str.py`

**Step 1: Write round-trip tests**

```python
class TestNewSectionRoundTrip:
    """Test that new sections can be parsed and re-generated."""

    def test_sedtr_roundtrip(self):
        content = """$sedtr
        isedi = 1
        sedgrs = '0.063 0.125 0.25 0.5'
        percin = '0.25 0.25 0.25 0.25'
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("sedtr", "isedi") == 1
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("sedtr", "isedi") == 1

    def test_lagrg_roundtrip(self):
        content = """$lagrg
        ilagr = 2
        nbdy = 100
        ioil = 1
        lbeach = 0.5
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ilagr") == 2
        assert parsed.get_param("lagrg", "ioil") == 1
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("lagrg", "ilagr") == 2

    def test_nduge_roundtrip(self):
        content = """$nduge
        nvars = 3
        ttau = 3600
        sigma = 5000
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("nduge", "nvars") == 3
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("nduge", "nvars") == 3

    def test_multi_section_str_with_new_sections(self):
        """Full STR with multiple new sections parses correctly."""
        content = """$para
        idt = 300
        ilagr = 2
$end
$lagrg
        ilagr = 2
        nbdy = 100
        idtl = 3600
$end
$sedtr
        isedi = 1
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "idt") == 300
        assert parsed.get_param("lagrg", "nbdy") == 100
        assert parsed.get_param("sedtr", "isedi") == 1
```

**Step 2: Run tests — expect PASS (parser already handles arbitrary sections)**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py::TestNewSectionRoundTrip -v
```

**Step 3: Commit**

```bash
cd shyfem-ui && git add tests/test_parser_str.py
git commit -m "test(parser): add round-trip tests for \$sedtr, \$lagrg, \$nduge sections"
```

---

## Task 6: Update boundary editor with full ibtyp list

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/boundary_editor.py:274-277`
- Test: `shyfem-ui/tests/test_boundary_editor.py`

**Step 1: Write failing tests**

Add to `tests/test_boundary_editor.py`:

```python
class TestBoundaryTypesComplete:
    """Boundary type choices cover all Fortran ibtyp values."""

    def test_radiation_boundary_generates(self):
        """ibtyp=31 (radiation) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=31)])
        assert "ibtyp = 31" in result

    def test_closed_wall_generates(self):
        """ibtyp=-1 (closed wall) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=-1)])
        assert "ibtyp = -1" in result

    def test_momentum_boundary_generates(self):
        """ibtyp=4 (momentum) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=4)])
        assert "ibtyp = 4" in result

    def test_csv_import_radiation_type(self):
        """CSV import handles ibtyp=31."""
        csv = "1 2 3, 31, INPUT/open.txt, 1.0, 1"
        result = parse_boundary_csv(csv)
        assert len(result) == 1
        assert result[0]["ibtyp"] == 31
```

**Step 2: Run tests — expect PASS (generate_bound_text already handles any integer ibtyp)**

These should pass since `generate_bound_text` just writes `ibtyp = {value}`. The real change is the UI dropdown. Verify they pass, then update the UI.

**Step 3: Update boundary_editor.py type_choices**

In `boundary_editor.py`, replace lines 274-277:

```python
            type_choices = {
                "1": "1 - Water level (elevation)",
                "2": "2 - Velocity",
                "3": "3 - Discharge",
            }
```

With:

```python
            type_choices = {
                "-1": "-1 - Closed wall",
                "0": "0 - Off / Inactive",
                "1": "1 - Water level (elevation)",
                "2": "2 - Discharge (volume flux)",
                "3": "3 - Internal volume inlet",
                "4": "4 - Momentum input",
                "5": "5 - Fixed scalar (no flux)",
                "31": "31 - Radiation / zero gradient",
            }
```

**Step 4: Run all boundary tests**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boundary_editor.py tests/test_boundary_remove.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/components/boundary_editor.py tests/test_boundary_editor.py
git commit -m "feat(boundary): expand ibtyp choices to include radiation, closed wall, momentum"
```

---

## Task 7: Add scalar boundary file fields to boundary editor

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/boundary_editor.py:326-358` (after existing row)
- Test: `shyfem-ui/tests/test_boundary_editor.py`

**Step 1: Write failing tests**

```python
class TestScalarBoundaryFiles:
    """Scalar file fields (saltn, tempn, conzn) in boundary text."""

    def test_saltn_in_bound_text(self):
        """saltn is emitted in $bound section when set."""
        b = _bound()
        b["saltn"] = "INPUT/salt.txt"
        result = generate_bound_text([b])
        assert "saltn = 'INPUT/salt.txt'" in result

    def test_tempn_in_bound_text(self):
        """tempn is emitted in $bound section when set."""
        b = _bound()
        b["tempn"] = "INPUT/temp.txt"
        result = generate_bound_text([b])
        assert "tempn = 'INPUT/temp.txt'" in result

    def test_empty_scalar_files_omitted(self):
        """Empty scalar file strings are not emitted."""
        b = _bound()
        b["saltn"] = ""
        b["tempn"] = ""
        b["conzn"] = ""
        result = generate_bound_text([b])
        assert "saltn" not in result
        assert "tempn" not in result
        assert "conzn" not in result
```

**Step 2: Run tests — expect FAIL**

**Step 3: Update generate_bound_text and boundary data structures**

In `boundary_editor.py`, modify `generate_bound_text()` function (~line 60-80) to emit scalar files after boundn:

After the `boundn` line emission (around line 78), add:

```python
        for scalar_key in ("saltn", "tempn", "conzn"):
            val = b.get(scalar_key, "")
            if val:
                lines.append(f"        {scalar_key} = '{val}'")
```

Update the default boundary dict creation (line ~181) to include:

```python
        "saltn": "",
        "tempn": "",
        "conzn": "",
```

Update `_from_section` parsing (~line 159) to read:

```python
        "saltn": str(section.parameters.get("saltn", "")),
        "tempn": str(section.parameters.get("tempn", "")),
        "conzn": str(section.parameters.get("conzn", "")),
```

Update the _sync function (~line 246) to collect scalar values:

```python
        "saltn": str(input[f"bound_saltn_{bid}"]()) if f"bound_saltn_{bid}" in input else b.get("saltn", ""),
        "tempn": str(input[f"bound_tempn_{bid}"]()) if f"bound_tempn_{bid}" in input else b.get("tempn", ""),
        "conzn": str(input[f"bound_conzn_{bid}"]()) if f"bound_conzn_{bid}" in input else b.get("conzn", ""),
```

Add UI input fields in the boundary card (~after line 358, before the closing card div):

```python
                        ui.row(
                            ui.column(
                                4,
                                ui.div(
                                    ui.span("Salinity file", class_="small fw-bold"),
                                    ui.input_text(
                                        f"bound_saltn_{bid}", "",
                                        value=b.get("saltn", ""),
                                        placeholder="INPUT/salt.txt",
                                    ),
                                ),
                            ),
                            ui.column(
                                4,
                                ui.div(
                                    ui.span("Temperature file", class_="small fw-bold"),
                                    ui.input_text(
                                        f"bound_tempn_{bid}", "",
                                        value=b.get("tempn", ""),
                                        placeholder="INPUT/temp.txt",
                                    ),
                                ),
                            ),
                            ui.column(
                                4,
                                ui.div(
                                    ui.span("Concentration file", class_="small fw-bold"),
                                    ui.input_text(
                                        f"bound_conzn_{bid}", "",
                                        value=b.get("conzn", ""),
                                        placeholder="INPUT/conz.txt",
                                    ),
                                ),
                            ),
                        ),
```

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boundary_editor.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/components/boundary_editor.py tests/test_boundary_editor.py
git commit -m "feat(boundary): add saltn/tempn/conzn scalar boundary file fields"
```

---

## Task 8: Rename lagrangian template to eulerian_tracer and add proper lagrangian

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/simulation.py:82-94,747-788` (template choices + generate_template)
- Test: `shyfem-ui/tests/test_str_templates.py`

**Step 1: Write failing tests**

In `tests/test_str_templates.py`, update `ALL_TEMPLATES` and add:

```python
ALL_TEMPLATES = [
    "basic_2d",
    "basic_3d",
    "wind_driven",
    "tidal",
    "baroclinic",
    "eulerian_tracer",   # was "lagrangian"
    "lagrangian",        # new proper lagrangian
    "tidal_estuary",
    "sediment_transport",
    "water_quality",
    "storm_surge",
    "thermal",
    "ice_model",
    "oil_spill",
    "data_assimilation",
    "offline_tracer",
    "wave_coupled",
]


class TestLagrangianTemplate:
    """Proper lagrangian template has $lagrg section."""

    def test_has_lagrg_section(self):
        content = generate_template("lagrangian")
        assert "$lagrg" in content

    def test_has_ilagr(self):
        content = generate_template("lagrangian")
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ilagr") == 2

    def test_has_nbdy(self):
        content = generate_template("lagrangian")
        assert "nbdy" in content


class TestEulerianTracer:
    """Renamed eulerian_tracer template has iconz and iage."""

    def test_has_iconz(self):
        content = generate_template("eulerian_tracer")
        assert "iconz" in content

    def test_has_iage(self):
        content = generate_template("eulerian_tracer")
        assert "iage" in content


class TestThermalTemplate:
    """Thermal template has heat flux and T/S."""

    def test_has_iheat(self):
        content = generate_template("thermal")
        assert "iheat" in content

    def test_has_baroclinic(self):
        content = generate_template("thermal")
        assert "ibarcl" in content

    def test_has_levels(self):
        content = generate_template("thermal")
        assert "$levels" in content


class TestOilSpillTemplate:
    """Oil spill template has $lagrg with ioil."""

    def test_has_lagrg(self):
        content = generate_template("oil_spill")
        assert "$lagrg" in content

    def test_has_ioil(self):
        content = generate_template("oil_spill")
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ioil") == 1


class TestDataAssimilationTemplate:
    """Data assimilation template has $nduge."""

    def test_has_nduge(self):
        content = generate_template("data_assimilation")
        assert "$nduge" in content

    def test_has_ibarcl_4(self):
        content = generate_template("data_assimilation")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "ibarcl") == 4


class TestOfflineTracerTemplate:
    """Offline tracer template has idtoff."""

    def test_has_idtoff(self):
        content = generate_template("offline_tracer")
        assert "idtoff" in content


class TestWaveCoupledTemplate:
    """Wave-coupled template has iwave."""

    def test_has_iwave(self):
        content = generate_template("wave_coupled")
        assert "iwave" in content


class TestIceModelTemplate:
    """Ice model template has icemod."""

    def test_has_icemod(self):
        content = generate_template("ice_model")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "icemod") == 1
```

**Step 2: Run tests — expect FAIL**

**Step 3: Update simulation.py**

Update template choices (~line 82-94):

```python
                    choices={
                        "": "Select template...",
                        "basic_2d": "Basic 2D Simulation",
                        "basic_3d": "Basic 3D Simulation",
                        "wind_driven": "Wind-Driven Circulation",
                        "tidal": "Tidal Simulation",
                        "tidal_estuary": "Tidal Estuary (3D)",
                        "baroclinic": "Baroclinic (T/S)",
                        "eulerian_tracer": "Eulerian Tracer / Water Age",
                        "lagrangian": "Lagrangian Particle Tracking",
                        "sediment_transport": "Sediment Transport",
                        "water_quality": "Water Quality (EUTRO)",
                        "storm_surge": "Storm Surge",
                        "thermal": "Thermal / Heat Exchange",
                        "ice_model": "Ice Model",
                        "oil_spill": "Oil Spill (Lagrangian)",
                        "data_assimilation": "Data Assimilation",
                        "offline_tracer": "Offline Tracer Run",
                        "wave_coupled": "Wave-Coupled Storm Surge",
                    },
```

In `generate_template()`, rename the existing `"lagrangian"` case to `"eulerian_tracer"`, then add new template cases. The complete template strings are in the design doc. Each template is a multiline STR string following the same pattern as existing templates.

For the new `"lagrangian"` case:

```python
    elif name == "lagrangian":
        return """$title
        Lagrangian Particle Tracking
        lagrangian_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3
$end

$lagrg
        ilagr = 2
        nbdy = 100
        nbdymax = 10000
        idtl = 3600
        rwhpar = 1.0
        idtlgr = 3600
$end

$extra
        1       'release point'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
"""
```

Follow the same pattern for `thermal`, `ice_model`, `oil_spill`, `data_assimilation`, `offline_tracer`, `wave_coupled`. Each should be a valid .str file string with appropriate sections and parameters as specified in the design doc.

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_templates.py -v
```

**Step 5: Run full test suite**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q
```

**Step 6: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/pages/simulation.py tests/test_str_templates.py
git commit -m "feat(templates): rename lagrangian->eulerian_tracer, add 7 new physics templates"
```

---

## Task 9: Add offline tracer workflow template

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/workflow.py:91-130` (WORKFLOW_TEMPLATES)
- Test: `shyfem-ui/tests/test_workflow.py`

**Step 1: Write failing test**

Add to `tests/test_workflow.py`:

```python
from shyfem_ui.services.workflow import WORKFLOW_TEMPLATES

class TestOfflineWorkflow:
    def test_offline_tracer_template_exists(self):
        assert "offline_tracer" in WORKFLOW_TEMPLATES

    def test_offline_tracer_has_two_steps(self):
        tpl = WORKFLOW_TEMPLATES["offline_tracer"]
        assert len(tpl["steps"]) == 2
```

**Step 2: Run test — expect FAIL**

**Step 3: Add to WORKFLOW_TEMPLATES in workflow.py**

After the last entry in `WORKFLOW_TEMPLATES` dict:

```python
    "offline_tracer": {
        "name": "Offline Tracer Analysis",
        "description": "Run hydrodynamics first (writes offline data), "
                       "then run tracers on saved flow fields",
        "steps": [
            WorkflowStep(
                name="Hydrodynamic run",
                tool_name="shyfem",
                args_template=["{input_str}"],
                options=["# Set idtoff > 0 in STR to write offline data"],
            ),
            WorkflowStep(
                name="Tracer run",
                tool_name="shyfem",
                args_template=["{input_str_tracer}"],
                input_from="Hydrodynamic run",
                options=["# Set idtoff = -1 in STR to read offline data"],
            ),
        ],
    },
```

**Step 4: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_workflow.py -v
```

**Step 5: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/services/workflow.py tests/test_workflow.py
git commit -m "feat(workflow): add offline tracer analysis workflow template"
```

---

## Task 10: Add flux operation to post-processing and tools to run page

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/postprocess.py:27-78` (SHYELAB_OPERATIONS)
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:155-165` (tool_select choices)
- Test: existing template parametrized tests cover this

**Step 1: Add flux operation to SHYELAB_OPERATIONS**

After the `"frequency"` entry in `postprocess.py`:

```python
    "flux": {
        "label": "Flux / Transport Analysis",
        "flags": ["-flux"],
        "description": "Compute integrated transport at flux sections",
    },
```

**Step 2: Add tools to run.py tool selector**

In `run.py` tool_select choices (~line 155-165), add after `shyplot`:

```python
                            "exgrd": "exgrd (Grid Extraction)",
                            "shyadj": "shyadj (Mesh Adjustment)",
```

**Step 3: Run full tests**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q
```

**Step 4: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/pages/postprocess.py shyfem_ui/pages/run.py
git commit -m "feat(ui): add flux analysis to post-process, exgrd/shyadj to run page tools"
```

---

## Task 11: Create physics configuration page skeleton

**Files:**
- Create: `shyfem-ui/shyfem_ui/pages/physics.py`
- Modify: `shyfem-ui/shyfem_ui/app.py:18-33,58,641-670,743-777` (import, nav, UI div, server call)
- Create: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write failing test**

Create `tests/test_physics_page.py`:

```python
"""Tests for physics configuration page."""

from shyfem_ui.pages.physics import (
    PHYSICS_PANELS,
    build_panel_params,
)


class TestPhysicsPanels:
    """Physics panel definitions are complete and valid."""

    def test_all_13_panels_defined(self):
        assert len(PHYSICS_PANELS) == 13

    def test_each_panel_has_required_keys(self):
        for pid, panel in PHYSICS_PANELS.items():
            assert "label" in panel, f"Panel {pid} missing label"
            assert "icon" in panel, f"Panel {pid} missing icon"
            assert "params" in panel, f"Panel {pid} missing params"

    def test_hydrodynamics_panel_params(self):
        params = PHYSICS_PANELS["hydrodynamics"]["params"]
        assert "ilin" in params
        assert "icor" in params
        assert "hzmin" in params

    def test_friction_panel_params(self):
        params = PHYSICS_PANELS["friction"]["params"]
        assert "ireib" in params
        assert "czdef" in params

    def test_ecology_panel_params(self):
        params = PHYSICS_PANELS["ecology"]["params"]
        assert "ibio" in params

    def test_lagrangian_panel_has_section(self):
        panel = PHYSICS_PANELS["lagrangian"]
        assert panel.get("section") == "lagrg" or "ilagr" in panel["params"]


class TestBuildPanelParams:
    """build_panel_params extracts params from StrFile."""

    def test_extracts_known_param(self):
        from shyfem_ui.services.parser_str import StrParser
        content = "$para\n    ireib = 5\n    czdef = 2.5e-3\n$end\n"
        parsed = StrParser.parse(content)
        result = build_panel_params(parsed, "friction")
        assert result["ireib"] == 5

    def test_returns_defaults_for_missing(self):
        from shyfem_ui.services.parser_str import StrFile
        result = build_panel_params(StrFile(), "friction")
        # Should return default values from COMMON_PARAMS
        assert "ireib" in result
```

**Step 2: Run test — expect FAIL**

**Step 3: Create pages/physics.py with panel definitions and helper**

```python
"""Physics configuration page — guided SHYFEM parameter setup.

Complements the simulation page (raw STR editor) with structured
accordion panels for each physics module. Reads/writes the same
STR files.
"""

import logging
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.services.parser_str import COMMON_PARAMS, StrFile, StrParser

logger = logging.getLogger(__name__)

# Panel definitions: id -> {label, icon, params: {param: section}, section (optional)}
# "params" maps param names to the STR section they belong to.
PHYSICS_PANELS = {
    "hydrodynamics": {
        "label": "Hydrodynamics",
        "icon": "bi-water",
        "params": {
            "ilin": "para", "itlin": "para", "iclin": "para",
            "itsplt": "para", "coumax": "para", "idtsyn": "para",
            "icor": "para", "dlat": "para", "isphe": "para",
            "hzmin": "para", "hzoff": "para", "hzon": "para",
        },
    },
    "vertical": {
        "label": "Vertical Structure",
        "icon": "bi-layers",
        "params": {
            "dzreg": "para", "ilytyp": "para", "hlvmin": "para",
            "nzadapt": "para", "nsigma": "para", "hsigma": "para",
        },
    },
    "friction": {
        "label": "Bottom Friction",
        "icon": "bi-arrow-down-square",
        "params": {"ireib": "para", "czdef": "para", "iczv": "para"},
    },
    "turbulence": {
        "label": "Turbulence & Mixing",
        "icon": "bi-tornado",
        "params": {
            "iturb": "para", "difmol": "para", "vismol": "para",
            "diftur": "para", "vistur": "para",
            "idhtyp": "para", "ahpar": "para", "dhpar": "para",
            "itvd": "para", "itvdv": "para", "noslip": "para",
        },
    },
    "heat": {
        "label": "Heat Flux",
        "icon": "bi-thermometer-sun",
        "params": {
            "iheat": "para", "ihtype": "para", "hdecay": "para",
            "albedo": "para", "ievap": "para", "irain": "para",
        },
    },
    "temperature_salinity": {
        "label": "Temperature & Salinity",
        "icon": "bi-droplet-half",
        "params": {
            "ibarcl": "para", "itemp": "para", "isalt": "para",
            "temref": "para", "salref": "para",
            "thpar": "para", "shpar": "para",
            "idtcon": "para", "icon_av": "para",
        },
    },
    "ecology": {
        "label": "Ecology",
        "icon": "bi-tree",
        "params": {"ibio": "para", "imerc": "para"},
    },
    "sediment": {
        "label": "Sediment Transport",
        "icon": "bi-reception-4",
        "params": {"issedi": "para"},
        "section": "sedtr",
    },
    "lagrangian": {
        "label": "Lagrangian / IBM",
        "icon": "bi-pin-map",
        "section": "lagrg",
        "params": {"ilagr": "para"},
    },
    "ice": {
        "label": "Ice Model",
        "icon": "bi-snow2",
        "params": {"icemod": "para"},
    },
    "waves": {
        "label": "Wave Coupling",
        "icon": "bi-soundwave",
        "params": {"iwave": "para", "dtwave": "para", "itdrag": "para"},
    },
    "assimilation": {
        "label": "Data Assimilation",
        "icon": "bi-bullseye",
        "section": "nduge",
        "params": {"ibarcl": "para"},
    },
    "output": {
        "label": "Output & Restart",
        "icon": "bi-save",
        "params": {
            "idtout": "para", "idtext": "para", "idtcon": "para",
            "idtflx": "para", "idtres": "para", "idtrms": "para",
            "idtvol": "para", "idtmet": "para", "idtstb": "para",
            "netcdf": "para", "iout_av": "para", "icon_av": "para",
            "itrst": "para", "itmrst": "para", "ityrst": "para",
            "idtoff": "para", "itmoff": "para",
        },
    },
}


def build_panel_params(str_file: StrFile, panel_id: str) -> dict:
    """Extract current parameter values for a panel from a parsed StrFile.

    Returns dict of param_name -> current_value (or default from COMMON_PARAMS).
    """
    panel = PHYSICS_PANELS[panel_id]
    result = {}

    # Params from $para (or other sections specified in panel["params"])
    for param, section in panel["params"].items():
        value = str_file.get_param(section, param)
        if value is None:
            # Fall back to COMMON_PARAMS default
            sec_params = COMMON_PARAMS.get(section, {})
            info = sec_params.get(param)
            value = info[2] if info else None  # index 2 = default
        result[param] = value

    # If panel has a dedicated section, include all its params
    dedicated = panel.get("section")
    if dedicated and dedicated in COMMON_PARAMS:
        for param, info in COMMON_PARAMS[dedicated].items():
            if param not in result:
                value = str_file.get_param(dedicated, param)
                if value is None:
                    value = info[2]  # default
                result[param] = value

    return result


@module.ui
def physics_ui():
    """Physics configuration page UI."""
    return ui.div(
        ui.h3("Physics Configuration"),
        ui.p(
            "Configure simulation physics modules. "
            "Load a .str file, adjust settings, and save.",
            class_="text-muted",
        ),
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Parameter File"),
                ui.input_text(
                    "str_path", "File Path (.str)",
                    placeholder="/path/to/simulation.str",
                ),
                ui.div(
                    ui.input_action_button(
                        "load_btn", "Load",
                        class_="btn-outline-primary btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "save_btn", "Save",
                        class_="btn-outline-success btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "preview_btn", "Preview STR",
                        class_="btn-outline-secondary btn-sm",
                    ),
                    class_="mt-2",
                ),
                ui.hr(),
                ui.h5("Active Modules"),
                ui.output_ui("module_badges"),
                width=280,
            ),
            ui.output_ui("panels_accordion"),
        ),
    )


@module.server
def physics_server(input, output, session, config: Config, active_project=None):
    """Physics configuration page server."""

    str_data: reactive.Value[StrFile] = reactive.Value(StrFile())

    @reactive.Effect
    @reactive.event(input.load_btn)
    def load_file():
        path = Path(input.str_path())
        if path.exists() and path.suffix == ".str":
            try:
                parsed = StrParser.parse_file(path)
                str_data.set(parsed)
                ui.notification_show(f"Loaded {path.name}", type="message", duration=3)
            except Exception as e:
                ui.notification_show(f"Parse error: {e}", type="error")
        else:
            ui.notification_show("File not found or not .str", type="warning")

    @reactive.Effect
    @reactive.event(input.save_btn)
    def save_file():
        path_str = input.str_path()
        if not path_str:
            ui.notification_show("No file path specified", type="warning")
            return
        try:
            StrParser.save(str_data.get(), Path(path_str))
            ui.notification_show(f"Saved to {path_str}", type="message", duration=3)
        except Exception as e:
            ui.notification_show(f"Save error: {e}", type="error")

    @render.ui
    def module_badges():
        sf = str_data.get()
        badges = []
        checks = [
            ("Hydro", sf.get_param("para", "ilin", 1) == 0, "Nonlinear"),
            ("3D", sf.get_param("para", "dzreg", 0) > 0 or "levels" in sf.sections, None),
            ("Baroclinic", (sf.get_param("para", "ibarcl", 0) or 0) > 0, None),
            ("Turbulence", (sf.get_param("para", "iturb", 0) or 0) > 0, None),
            ("Heat", (sf.get_param("para", "iheat", 0) or 0) > 0, None),
            ("Ecology", (sf.get_param("para", "ibio", 0) or 0) > 0, None),
            ("Sediment", (sf.get_param("para", "issedi", 0) or 0) > 0
                or sf.get_param("sedtr", "isedi", 0) == 1, None),
            ("Lagrangian", "lagrg" in sf.sections, None),
            ("Ice", sf.get_param("para", "icemod", 0) == 1, None),
            ("Waves", (sf.get_param("para", "iwave", 0) or 0) > 0, None),
            ("Nudging", "nduge" in sf.sections, None),
        ]
        for label, active, detail in checks:
            if active:
                text = f"{label}: {detail}" if detail else label
                badges.append(
                    ui.span(text, class_="badge bg-primary me-1 mb-1")
                )
        if not badges:
            return ui.p("No modules active", class_="text-muted small")
        return ui.div(*badges)

    @render.ui
    def panels_accordion():
        panels = []
        for pid, panel in PHYSICS_PANELS.items():
            panels.append(
                ui.accordion_panel(
                    ui.span(
                        ui.tags.i(class_=f"bi {panel['icon']} me-2"),
                        panel["label"],
                    ),
                    ui.p(
                        f"Configure {panel['label'].lower()} parameters. "
                        "Changes are applied when you click Save.",
                        class_="text-muted small",
                    ),
                    ui.output_ui(f"panel_{pid}"),
                    value=pid,
                )
            )
        return ui.accordion(*panels, id="physics_accordion", open=False)
```

**Step 4: Wire into app.py**

Add import:
```python
from shyfem_ui.pages import physics
```

Add nav entry in SIDEBAR_GROUPS under "Prepare" (after Partitioning):
```python
            {"label": "Physics Config", "icon": "bi-cpu", "value": "Physics"},
```

Add UI div:
```python
        ui.div(physics.physics_ui("physics"), id="sf-page-Physics", class_="sf-page"),
```

Add server call:
```python
    physics.physics_server("physics", config, active_project=active_project)
```

**Step 5: Run tests — expect PASS**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py tests/test_app_layout.py -v
```

**Step 6: Commit**

```bash
cd shyfem-ui && git add shyfem_ui/pages/physics.py shyfem_ui/app.py tests/test_physics_page.py
git commit -m "feat(ui): add physics configuration page skeleton with 13 panels"
```

---

## Task 12: Implement physics page panels (core hydro: panels 1-4)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` (add panel render functions)
- Test: `shyfem-ui/tests/test_physics_page.py`

This task adds the `@render.ui` functions for panels 1-4 (Hydrodynamics, Vertical Structure, Bottom Friction, Turbulence & Mixing) inside the `physics_server` function. Each panel renders form controls for its parameters.

**Implementation pattern for each panel:**

```python
    @render.ui
    def panel_hydrodynamics():
        params = build_panel_params(str_data.get(), "hydrodynamics")
        return ui.div(
            ui.row(
                ui.column(6,
                    ui.input_select("ilin", "Advection", choices={
                        "0": "Linear", "1": "Nonlinear"
                    }, selected=str(params.get("ilin", 1))),
                ),
                ui.column(6,
                    ui.input_select("itlin", "Scheme", choices={
                        "0": "Finite Element", "1": "Semi-Lagrangian"
                    }, selected=str(params.get("itlin", 0))),
                ),
            ),
            # ... more controls per the design doc Panel 1 spec ...
        )
```

Follow this pattern for each panel. Key points:
- Use `build_panel_params()` to get current values
- Use `ui.input_select` for enum params (ireib, iturb, etc.)
- Use `ui.input_numeric` for float/int params (czdef, difmol, etc.)
- Use `ui.input_text` for string params (time values)
- Group related params in `ui.row` / `ui.column` layout

**Test:** Each panel renders without error when given an empty StrFile.

**Commit:**

```bash
git commit -m "feat(physics): implement core hydro panels (hydro, vertical, friction, turbulence)"
```

---

## Task 13: Implement physics page panels (thermal: panels 5-6)

Same pattern as Task 12 for Heat Flux and Temperature & Salinity panels.

**Commit:**
```bash
git commit -m "feat(physics): implement thermal panels (heat flux, temperature & salinity)"
```

---

## Task 14: Implement physics page panels (biogeochemistry: panels 7-8)

Same pattern for Ecology and Sediment Transport panels.

**Commit:**
```bash
git commit -m "feat(physics): implement ecology and sediment transport panels"
```

---

## Task 15: Implement physics page panels (specialized: panels 9-11)

Same pattern for Lagrangian/IBM, Ice Model, and Wave Coupling panels.

**Commit:**
```bash
git commit -m "feat(physics): implement lagrangian, ice, and wave coupling panels"
```

---

## Task 16: Implement physics page panels (workflows: panels 12-13)

Same pattern for Data Assimilation and Output & Restart panels.

**Commit:**
```bash
git commit -m "feat(physics): implement data assimilation and output/restart panels"
```

---

## Task 17: Wire physics page save — collect panel values into StrFile

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Test: `shyfem-ui/tests/test_physics_page.py`

Add a reactive effect that collects all panel input values and writes them back to `str_data` on save. The pattern:

```python
    def _collect_panel_values() -> None:
        """Read all panel input values and update str_data."""
        sf = str_data.get()
        # For each panel, read reactive inputs and set_param
        for panel_id, panel in PHYSICS_PANELS.items():
            for param, section in panel["params"].items():
                input_id = param
                try:
                    raw = input[input_id]()
                    if raw is not None and str(raw).strip():
                        value = StrParser._convert_value(str(raw))
                        sf.set_param(section, param, value)
                except Exception:
                    pass  # Input not yet rendered
```

**Test:** Load STR → change a param via input → save → reload → verify change persisted.

**Commit:**
```bash
git commit -m "feat(physics): wire panel inputs to STR save/load round-trip"
```

---

## Task 18: Add restart dropdown to run page

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:178-179` (after solver options output_ui)
- Test: `shyfem-ui/tests/test_run_helpers.py`

**Step 1: Add UI elements**

After the existing `shyfem_options` output_ui in run.py, add:

```python
                    ui.hr(),
                    ui.h6("Restart"),
                    ui.input_select(
                        "restart_from",
                        "Continue from job",
                        choices={"": "Fresh start (no restart)"},
                    ),
                    ui.output_ui("restart_info"),
```

**Step 2: Add server logic**

Add an `@reactive.Effect` that populates the restart dropdown with completed jobs that have `.rst` files in their output directory. On selection, show the restart file path and suggest updating `itanf`.

**Step 3: Run tests**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q
```

**Step 4: Commit**

```bash
git commit -m "feat(run): add restart-from-job dropdown for continuation runs"
```

---

## Task 19: Final integration test and full suite verification

**Files:**
- Test: `shyfem-ui/tests/test_physics_page.py`

**Step 1: Write integration test**

```python
class TestPhysicsIntegration:
    """End-to-end: parse STR -> extract panel params -> modify -> serialize -> re-parse."""

    def test_full_roundtrip(self):
        content = """$para
        idt = 300
        ireib = 5
        czdef = 2.5e-3
        iturb = 1
        ibarcl = 1
$end
$lagrg
        ilagr = 2
        nbdy = 100
$end
"""
        parsed = StrParser.parse(content)

        # Extract friction panel
        friction = build_panel_params(parsed, "friction")
        assert friction["ireib"] == 5

        # Extract lagrangian panel
        lagr = build_panel_params(parsed, "lagrangian")
        assert lagr["ilagr"] == 2

        # Modify a value
        parsed.set_param("para", "ireib", 6)
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("para", "ireib") == 6
        # Unmodified params preserved
        assert reparsed.get_param("para", "iturb") == 1
        assert reparsed.get_param("lagrg", "nbdy") == 100
```

**Step 2: Run full test suite**

```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q
```

Expected: All tests pass (baseline 1376 + ~40 new tests).

**Step 3: Commit**

```bash
git commit -m "test(physics): add full integration round-trip test"
```

---

## Summary

| Task | Phase | Files | What |
|------|-------|-------|------|
| 1 | A | parser_str.py | Add wave/mercury/restart/offline params to $para |
| 2 | A | parser_str.py | Update ireib/iheat/ibarcl/ibtyp descriptions |
| 3 | A | parser_str.py | Add ecology/sediment/lagrangian files to $name |
| 4 | A | parser_str.py | Add $sedtr, $lagrg, $connec, $bfmsc, $nduge sections |
| 5 | A | tests only | Round-trip parse tests for new sections |
| 6 | B | boundary_editor.py | Expand ibtyp to 8 boundary types |
| 7 | B | boundary_editor.py | Add saltn/tempn/conzn scalar files |
| 8 | C | simulation.py | Rename lagrangian→eulerian_tracer, add 7 templates |
| 9 | E | workflow.py | Add offline tracer workflow template |
| 10 | F | postprocess.py, run.py | Add flux operation, exgrd/shyadj tools |
| 11 | D | physics.py, app.py | Physics page skeleton with 13 panel defs |
| 12 | D | physics.py | Core hydro panels (1-4) |
| 13 | D | physics.py | Thermal panels (5-6) |
| 14 | D | physics.py | Biogeochemistry panels (7-8) |
| 15 | D | physics.py | Specialized panels (9-11) |
| 16 | D | physics.py | Workflow panels (12-13) |
| 17 | D | physics.py | Save/load wiring |
| 18 | E | run.py | Restart dropdown |
| 19 | — | tests | Integration test + full suite verification |
