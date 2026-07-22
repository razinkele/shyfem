# Beaching UI Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the Eulerian tracer-beaching feature (`ibeach` 0–3 + scalar `beachrate`/`burryrate`) in the SHYFEM Shiny UI's physics Tracers panel.

**Architecture:** Add three `$para` params to the UI metadata (`parser_str.py`), register them in the `tracers` panel so the existing save loop auto-wires read/write-back, and render an `ibeach` select plus two rate numeric inputs in `panel_tracers()`. No new save mechanism, no new widget pattern.

**Tech Stack:** Python, py-shiny (Shiny for Python), pytest. Spec: `docs/superpowers/specs/2026-07-22-ui-beaching-design.md`.

## Global Constraints

- Run pytest with `CONDA_PREFIX=""` (shiny conda env convention).
- Core parameter name is `burryrate` (double-r, single-y as core spells it) — copy verbatim, do not "correct" to `burialrate`/`buryrate`.
- `ibeach` is the **Eulerian tracer** path; do NOT touch `lbeach` (the existing Lagrangian particle probability in the IBM section).
- Scalar rates only — no per-area-code array editor (out of scope).
- `PHYSICS_PANELS` length must stay 21 (adding params to an existing panel, not a new panel).
- Params live under `COMMON_PARAMS["para"]`; the `tracers` panel maps them to section `"para"`.

---

### Task 1: Parser metadata for ibeach/beachrate/burryrate

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (add 3 entries after `idecay`, currently line 471, in the `"para"` group)
- Test: `shyfem-ui/tests/test_parser_str.py`

**Interfaces:**
- Consumes: `_p(desc, ptype, default, units, options)` helper and `COMMON_PARAMS["para"]` dict (existing).
- Produces: `COMMON_PARAMS["para"]["ibeach"]` (int, default 0), `["beachrate"]` (float, default 0.0), `["burryrate"]` (float, default 0.0) — consumed by Task 2's panel registration and `build_panel_params`.

- [ ] **Step 1: Write the failing test**

Add to `shyfem-ui/tests/test_parser_str.py`, inside the `COMMON_PARAMS` test class (near line 409, alongside `test_common_params_has_para`):

```python
    def test_common_params_has_beaching(self):
        """Eulerian beaching params are registered in $para."""
        for p in ("ibeach", "beachrate", "burryrate"):
            assert p in COMMON_PARAMS["para"], f"Missing {p} in $para"
        assert COMMON_PARAMS["para"]["ibeach"][1] == "int"
        assert COMMON_PARAMS["para"]["beachrate"][1] == "float"
        assert COMMON_PARAMS["para"]["burryrate"][1] == "float"

    def test_parse_beaching_params(self):
        """A $para block with ibeach=3 + rates parses to int/float."""
        content = "$para\n    ibeach = 3\n    beachrate = 0.3\n    burryrate = 0.1\n$end\n"
        para = StrParser.parse(content).sections["para"].parameters
        assert para["ibeach"] == 3 and isinstance(para["ibeach"], int)
        assert para["beachrate"] == pytest.approx(0.3)
        assert para["burryrate"] == pytest.approx(0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd shyfem-ui && CONDA_PREFIX="" python -m pytest tests/test_parser_str.py -k beaching -v`
Expected: `test_common_params_has_beaching` FAILs (`Missing ibeach in $para`). `test_parse_beaching_params` may already pass (the parser is generic) — that is fine; it locks the round-trip.

- [ ] **Step 3: Write minimal implementation**

In `shyfem-ui/shyfem_ui/services/parser_str.py`, in the `"para"` group right after the `idecay` line (currently line 471), add:

```python
        "ibeach": _p("Tracer beaching/burial mode", "int", 0, "",
                     "0=off,1=Curonian,2=Danube,3=STR rates"),
        "beachrate": _p("Beaching rate (surface loss/step)", "float", 0.0, "",
                        "used when ibeach=3"),
        "burryrate": _p("Burial rate (bottom loss/step)", "float", 0.0, "",
                        "used when ibeach=3"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd shyfem-ui && CONDA_PREFIX="" python -m pytest tests/test_parser_str.py -k beaching -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/parser_str.py shyfem-ui/tests/test_parser_str.py
git commit -m "feat(ui): register Eulerian beaching params in STR metadata

ibeach + scalar beachrate/burryrate under \$para (core PR #60).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Physics Tracers panel — register + render beaching widgets

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` — `PHYSICS_PANELS["tracers"]["params"]` (currently ~line 155) and `panel_tracers()` (insert after the `idecay` row, currently ends ~line 2020)
- Test: `shyfem-ui/tests/test_physics_page.py`

**Interfaces:**
- Consumes: `COMMON_PARAMS["para"]["ibeach"|"beachrate"|"burryrate"]` (Task 1); `build_panel_params(str_file, "tracers")`, `PHYSICS_PANELS`, `panel_tracers()` (existing). Widgets auto-wired via the existing `save_file`/`_read_input_and_set` loop over `PHYSICS_PANELS["tracers"]["params"]`.
- Produces: three new inputs `ibeach` (select), `beachrate`/`burryrate` (numeric) rendered in the Tracers panel and persisted to `$para` on save.

- [ ] **Step 1: Write the failing test**

Add to `shyfem-ui/tests/test_physics_page.py`, in `TestPhysicsPanels`:

```python
    def test_tracers_panel_has_beaching(self):
        params = PHYSICS_PANELS["tracers"]["params"]
        for p in ("ibeach", "beachrate", "burryrate"):
            assert p in params, f"Missing {p} in tracers panel"
            assert params[p] == "para"
```

And a render + round-trip test in `TestBuildPanelParams` (or a new `TestTracersBeaching` class):

```python
    def test_tracers_beaching_roundtrip(self):
        content = "$para\n    iconz = 2\n    ibeach = 3\n    beachrate = 0.3\n    burryrate = 0.1\n$end\n"
        parsed = StrParser.parse(content)
        result = build_panel_params(parsed, "tracers")
        assert result["ibeach"] == 3
        assert result["beachrate"] == pytest.approx(0.3)
        assert result["burryrate"] == pytest.approx(0.1)

    def test_panel_tracers_renders_beaching_inputs(self):
        import inspect
        from shyfem_ui.pages import physics
        src = inspect.getsource(physics)
        assert '"ibeach"' in src, "ibeach input not rendered"
        assert '"beachrate"' in src, "beachrate input not rendered"
        assert '"burryrate"' in src, "burryrate input not rendered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd shyfem-ui && CONDA_PREFIX="" python -m pytest tests/test_physics_page.py -k "beaching or tracers_beaching or renders_beaching" -v`
Expected: FAILs — `Missing ibeach in tracers panel` and the source assertions fail.

- [ ] **Step 3a: Register the params**

In `shyfem-ui/shyfem_ui/pages/physics.py`, in the `"tracers"` entry of `PHYSICS_PANELS`, add to the `params` dict after `"chpar": "para",`:

```python
            "ibeach": "para",
            "beachrate": "para",
            "burryrate": "para",
```

- [ ] **Step 3b: Render the widgets**

In `panel_tracers()`, immediately after the `ui.row(...)` that closes the `idecay` select (the row ending right before the `conref`/`chpar` row), insert a new row:

```python
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ibeach",
                        "Tracer beaching/burial",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Curonian preset",
                            "2": "2 - Danube preset",
                            "3": "3 - Rates from STR",
                        },
                        selected=str(params.get("ibeach", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "beachrate",
                        "Beaching rate (mode 3)",
                        value=float(params.get("beachrate", 0) or 0),
                        min=0,
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "burryrate",
                        "Burial rate (mode 3)",
                        value=float(params.get("burryrate", 0) or 0),
                        min=0,
                        step=0.01,
                    ),
                ),
            ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd shyfem-ui && CONDA_PREFIX="" python -m pytest tests/test_physics_page.py -k "beaching or tracers_beaching or renders_beaching" -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_page.py
git commit -m "feat(ui): expose Eulerian beaching in physics Tracers panel

ibeach select + scalar beachrate/burryrate inputs, wired via the tracers
panel registry (auto read/write-back). Distinct from Lagrangian lbeach.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Full-suite validation, review-in-loop, PR

**Files:** none (validation + review + PR).

- [ ] **Step 1: Run the full UI suite**

Run: `cd shyfem-ui && CONDA_PREFIX="" python -m pytest tests/ -q`
Expected: all pass (no regressions; new tests green). If any pre-existing E2E/Playwright tests are environment-gated, note but do not treat as regressions.

- [ ] **Step 2: Review-in-loop**

Dispatch the `ui-security-reviewer` agent on the diff (`git diff main...feat/ui-beaching -- shyfem-ui/`). Scope note for the reviewer: this is param-metadata + widgets only — no auth, path-confinement, DB, or reactive-self-write surface; confirm no dead/unwired control and no accidental `lbeach` interaction. Address any confirmed findings.

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/ui-beaching
gh pr create --title "feat(ui): expose Eulerian beaching (ibeach + rates) in physics Tracers panel" --body "<summary + test plan; references core PR #60 and spec>"
```

Expected: PR opens with green CI. Note in the PR that this is slice 1 of 3 (beaching → heat-flux imetout → assimilation).

---

## Self-Review

**Spec coverage:**
- `ibeach`/`beachrate`/`burryrate` metadata → Task 1. ✓
- Panel registration (write-back wiring) → Task 2 Step 3a. ✓
- Widget rendering (select + 2 numerics, placement after idecay) → Task 2 Step 3b. ✓
- Tests (parser parse + metadata; panel membership + round-trip + render) → Tasks 1–2. ✓
- `lbeach` untouched, scalar-only, no conditionalPanel → enforced by Global Constraints + reviewer step. ✓
- Full-suite + ui-security review + PR → Task 3. ✓

**Placeholder scan:** PR body text in Task 3 Step 3 is the only free-form element (a summary the implementer writes at PR time); all code steps carry complete code. No TBD/TODO in code.

**Type consistency:** `ibeach` int / `beachrate`,`burryrate` float consistent across Task 1 metadata, Task 2 widgets (`input_select` reads/writes string-of-int; `input_numeric` float), and the auto-typing `_read_input_and_set`. Param names spelled `burryrate` verbatim throughout.
