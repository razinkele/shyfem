# Heat-flux `imetout` UI Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the `imetout` meteo-output selector (5-digit bitmask) as five checkboxes in the physics Heat Flux panel.

**Architecture:** Two pure encode/decode helpers convert between the `imetout` integer and five stream flags (wind/heat/rain/ice/heat-fluxes). Five checkboxes in `panel_heat()` show the decoded state; a dedicated composite step in `_collect_panel_values` encodes them back into `imetout` on save. `imetout` is deliberately NOT a 1:1 registered param.

**Tech Stack:** Python, py-shiny, pytest. Spec: `docs/superpowers/specs/2026-07-23-ui-heatflux-imetout-design.md`.

## Global Constraints

- Run pytest with `CONDA_PREFIX=""` using `/opt/micromamba/envs/shiny/bin/python`.
- Run `black --check shyfem_ui/` and `ruff check` before any push (CI Lint gate).
- `imetout` digit map (position→place→stream): 1→1s→wind, 2→10s→heat, 3→100s→rain, 4→1000s→ice, 5→10000s→heat-fluxes. "On" = digit 1; core reads digit `> 0`.
- `imetout` must NOT be added to `PHYSICS_PANELS["heat"]["params"]` (no `input.imetout`; composite handling instead).
- `PHYSICS_PANELS` length stays 21.
- Param lives under `COMMON_PARAMS["para"]`.

---

### Task 1: Parser metadata for imetout

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (add one `_p()` entry in the `"para"` group, near the heat params ~line 411)
- Test: `shyfem-ui/tests/test_parser_str.py`

**Interfaces:**
- Consumes: `_p(...)`, `COMMON_PARAMS["para"]`.
- Produces: `COMMON_PARAMS["para"]["imetout"]` (int, default 0) — consumed by Task 2's decode/render and `build_panel_params`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_parser_str.py` in `TestCommonParams`:

```python
    def test_common_params_has_imetout(self):
        """imetout meteo-output selector is registered in $para."""
        assert "imetout" in COMMON_PARAMS["para"]
        assert COMMON_PARAMS["para"]["imetout"][1] == "int"

    def test_parse_imetout(self):
        content = "$para\n    imetout = 10010\n$end\n"
        para = StrParser.parse(content).sections["para"].parameters
        assert para["imetout"] == 10010 and isinstance(para["imetout"], int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py -k imetout -v`
Expected: `test_common_params_has_imetout` FAILs (`KeyError`/assert). `test_parse_imetout` may already pass (generic parser).

- [ ] **Step 3: Write minimal implementation** — in `parser_str.py`, in the `"para"` group near the heat params, add:

```python
        "imetout": _p("Meteo output streams (bitmask)", "int", 0, "",
                      "digits: 1s=wind,10s=heat,100s=rain,1000s=ice,10000s=heat-fluxes"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py -k imetout -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/parser_str.py shyfem-ui/tests/test_parser_str.py
git commit -m "feat(ui): register imetout meteo-output param in STR metadata

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: imetout encode/decode helpers, Heat panel checkboxes, composite save

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` — add helpers (after `build_panel_params`, ~line 280), five checkboxes in `panel_heat()` (~line 1119), composite step in `_collect_panel_values` (after the `_INPUT_ID_REMAP` loop, ~line 451)
- Test: `shyfem-ui/tests/test_physics_page.py`

**Interfaces:**
- Consumes: `COMMON_PARAMS["para"]["imetout"]` (Task 1); `build_panel_params`, `panel_heat`, `_collect_panel_values`, `input`, `StrFile.set_param`.
- Produces: `_IMETOUT_FIELDS`, `_imetout_decode(value) -> dict[str,bool]`, `_imetout_encode(flags) -> int`; five `imetout_*` checkbox inputs; `imetout` written to `$para` on save.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_physics_page.py` in `TestPhysicsPanels`:

```python
    def test_imetout_decode_encode_roundtrip(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        flags = _imetout_decode(10010)  # heat (10s) + heat-fluxes (10000s)
        assert flags == {"wind": False, "heat": True, "rain": False,
                         "ice": False, "hflx": True}
        assert _imetout_encode(flags) == 10010

    def test_imetout_decode_zero_and_encode_empty(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        assert _imetout_decode(0) == {f: False for f in
                                      ("wind", "heat", "rain", "ice", "hflx")}
        assert _imetout_encode({}) == 0

    def test_imetout_normalizes_digit_gt_one(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        # heat place = 3 (>1) decodes as "on", re-encodes as 1 -> 10
        assert _imetout_encode(_imetout_decode(30)) == 10

    def test_imetout_decode_handles_garbage(self):
        from shyfem_ui.pages.physics import _imetout_decode

        assert _imetout_decode("x") == {f: False for f in
                                        ("wind", "heat", "rain", "ice", "hflx")}

    def test_panel_heat_renders_imetout_checkboxes(self):
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        for f in ("imetout_wind", "imetout_heat", "imetout_rain",
                  "imetout_ice", "imetout_hflx"):
            assert f'"{f}"' in src, f"{f} checkbox not rendered"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -k imetout -v`
Expected: FAIL (`ImportError` on `_imetout_decode`, source assertions fail).

- [ ] **Step 3a: Add the helpers** — in `physics.py`, immediately after the `build_panel_params` function (before `_scalar_or_none`, ~line 280):

```python
_IMETOUT_FIELDS = ("wind", "heat", "rain", "ice", "hflx")  # imetout positions 1..5


def _imetout_decode(value: object) -> dict[str, bool]:
    """Split the imetout integer into its 5 meteo-output stream flags.

    Each decimal digit (position 1..5 = wind/heat/rain/ice/heat-fluxes) is
    "on" when > 0 (matching the core's bit10_extract_value > 0 test). A
    non-integer value is treated as 0 (all off) rather than raising.
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return {f: (v // 10**i) % 10 > 0 for i, f in enumerate(_IMETOUT_FIELDS)}


def _imetout_encode(flags: dict[str, bool]) -> int:
    """Compose the 5 stream flags back into the imetout integer (on -> 1)."""
    return sum(
        int(bool(flags.get(f))) * 10**i for i, f in enumerate(_IMETOUT_FIELDS)
    )
```

- [ ] **Step 3b: Render the checkboxes** — in `panel_heat()`, insert a new row as the first child of the returned `ui.div`, i.e. change:

```python
        params = build_panel_params(str_data.get(), "heat")
        return ui.div(
            ui.row(
```

to:

```python
        params = build_panel_params(str_data.get(), "heat")
        _met = _imetout_decode(params.get("imetout", 0))
        return ui.div(
            ui.row(
                ui.column(
                    12,
                    ui.tags.label("Meteo output (imetout)", class_="fw-semibold"),
                ),
            ),
            ui.row(
                ui.column(2, ui.input_checkbox("imetout_wind", "Wind", value=_met["wind"])),
                ui.column(2, ui.input_checkbox("imetout_heat", "Heat", value=_met["heat"])),
                ui.column(2, ui.input_checkbox("imetout_rain", "Rain", value=_met["rain"])),
                ui.column(2, ui.input_checkbox("imetout_ice", "Ice", value=_met["ice"])),
                ui.column(4, ui.input_checkbox("imetout_hflx", "Heat fluxes", value=_met["hflx"])),
            ),
            ui.row(
```

- [ ] **Step 3c: Add the composite save step** — in `_collect_panel_values`, immediately after the `_INPUT_ID_REMAP` loop (~line 451):

```python
        # --- composite param: imetout <- 5 meteo-output checkboxes ---
        try:
            flags = {f: bool(input[f"imetout_{f}"]()) for f in _IMETOUT_FIELDS}
        except Exception:
            flags = None  # heat panel not rendered -> leave imetout untouched
        if flags is not None:
            sf.set_param("para", "imetout", _imetout_encode(flags))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -k imetout -v`
Expected: all PASS.

- [ ] **Step 5: Run the whole physics + parser files (no structural break)**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py tests/test_parser_str.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_page.py
git commit -m "feat(ui): expose imetout meteo-output streams as checkboxes in Heat panel

Five wind/heat/rain/ice/heat-fluxes checkboxes decode from and encode back
into the imetout 5-digit bitmask via a composite save step; not a 1:1 param.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Format, full-suite validation, review-in-loop, PR

**Files:** none (format + validation + review + PR).

- [ ] **Step 1: Format check**

Run: `cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/ && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/services/parser_str.py shyfem_ui/pages/physics.py`
Then commit any black changes: `git commit -am "style(ui): black-format imetout additions" ...`

- [ ] **Step 2: Full UI suite**

Run: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q --ignore=tests/test_playwright_physics_picker.py -p no:cacheprovider`
Expected: all pass, no regressions.

- [ ] **Step 3: Review-in-loop**

Dispatch `ui-security-reviewer` on `git diff main...feat/ui-heatflux-imetout -- shyfem-ui/`. Scope: composite-param wiring correctness (encode/decode, save step preserves imetout when panel unrendered), no dead control, no reactive self-write, no interaction with other heat params. Address confirmed findings.

- [ ] **Step 4: Push + PR**

```bash
git push -u origin feat/ui-heatflux-imetout
gh pr create --title "feat(ui): expose imetout meteo-output streams in Heat Flux panel" --body "<summary + test plan; references core PR #55 and spec; slice 2 of 3>"
```

Expected: green CI. Leave merge to the user (UI deploys to laguna).

---

## Self-Review

**Spec coverage:** parser metadata → Task 1; encode/decode helpers → Task 2 Step 3a; checkboxes → 3b; composite save → 3c; tests (decode/encode, zero, normalization, garbage, render) → Task 2 Step 1; format/suite/review/PR → Task 3. ✓

**Placeholder scan:** only the PR body in Task 3 Step 4 is author-filled at PR time; all code steps carry complete code. ✓

**Type consistency:** `_IMETOUT_FIELDS` tuple, `_imetout_decode(value)->dict[str,bool]`, `_imetout_encode(flags)->int`, and `imetout_<f>` input IDs are identical across helpers, widgets, save step, and tests. `imetout` int throughout. ✓
