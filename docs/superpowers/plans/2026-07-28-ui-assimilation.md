# Assimilation UI Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken Data Assimilation panel (dead `$nduge` writer that crashes the core) with a panel exposing the real `$assimilN` optimal-interpolation framework as fixed Temperature/Salinity blocks, and fix the `data_assimilation` simulation template the same way.

**Architecture:** Composite-panel pattern from slice 2 (imetout): the panel is registered with empty `params`, reads directly from the parsed `StrFile`, and a dedicated step in `_collect_panel_values` writes back. All section logic lives in pure module-level helpers (`_assimil_find` / `_assimil_nobs` / `_assimil_new_name` / `_assimil_apply` / `_purge_nduge`) so save semantics are unit-testable without a Shiny session.

**Tech Stack:** Python Shiny (module page), pytest. No Fortran changes.

**Spec:** `docs/superpowers/specs/2026-07-28-ui-assimilation-design.md`

## Global Constraints

- Work on branch `feat/ui-assimilation`.
- Test runs: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest <file> -q`
- Format gate is `black shyfem_ui/` ONLY — never run black on `tests/` wholesale (it reformats ~65 drifted files); format only the specific test files you touched, or none.
- The panel reads via `str_data.get()` / `sf.get_param(...)` — never `build_panel_params` (it only returns panel-registered params; slice-2 regression).
- Fields always render; the enable checkbox gates only save behavior (no `ui.panel_conditional` — its JS condition strings are not namespaced inside Shiny modules).
- Core contract (from `src/shyfem/assimil_admin.f90`): sections named `assimil<N>` (N ≥ 1 unique), `ivar` 12 = temperature / 11 = salinity, `nobs = 0` means "section ignored" (the sanctioned disabled state), single values broadcast to all stations, string params in STRs must be single-quoted.

---

### Task 1: Parser metadata + panel registry — drop `$nduge`, lock `$assimilN` round-trip

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/parser_str.py` (COMMON_SECTIONS entry ~line 326, COMMON_PARAMS block ~lines 642-648)
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` (registry entry ~lines 196-201)
- Test: `shyfem-ui/tests/test_parser_str.py`, `shyfem-ui/tests/test_physics_page.py`

The registry change ships in this task, not Task 3: removing
`COMMON_PARAMS["nduge"]` while `PHYSICS_PANELS["assimilation"]` still
carries `"section": "nduge"` makes the existing
`TestPhysicsPanelsConfig::test_dedicated_sections_exist_in_common_params`
(tests/test_physics_page.py:299-306) fail, which would leave the Task 1
and Task 2 commits red on the full suite (bisect hazard). Changing both
together also stops the UI writing `$nduge` from this commit onward.

**Interfaces:**
- Consumes: nothing.
- Produces: `COMMON_SECTIONS`/`COMMON_PARAMS` without `"nduge"`; `PHYSICS_PANELS["assimilation"]` as a composite panel (`"params": {}`, no `"section"` key); guarantees `$assimil1`-style sections parse as sections named `"assimil1"` and round-trip byte-identically when unmodified (later tasks rely on all three).

- [ ] **Step 1: Rewrite the nduge metadata test as its inverse, add round-trip tests**

In `shyfem-ui/tests/test_parser_str.py`, replace the existing test (lines ~529-533):

```python
    def test_common_params_has_nduge_section(self):
        """COMMON_PARAMS has $nduge data assimilation section."""
        assert "nduge" in COMMON_PARAMS
        for p in ("nvars", "tramp", "ttau", "sigma"):
            assert p in COMMON_PARAMS["nduge"], f"Missing {p} in $nduge"
```

with:

```python
    def test_nduge_metadata_removed(self):
        """$nduge is a fiction of the old UI: no core code reads it and
        iostr.f90 hard-stops on unknown sections, so the UI must never
        recreate it via the dedicated-section save path."""
        assert "nduge" not in COMMON_PARAMS
        assert "nduge" not in COMMON_SECTIONS
```

`COMMON_SECTIONS` may not be imported yet in the test module — extend the
existing `from shyfem_ui.services.parser_str import ...` line accordingly.
Leave `test_nduge_roundtrip` (~line 567) untouched: generic
unknown-section round-tripping is parser behavior that does not change.

In the same file, add to the class that holds `test_nduge_roundtrip`:

```python
    def test_assimil_numbered_sections_parse_distinct(self):
        content = (
            "$assimil1\n"
            "        nobs = 2\n"
            "        ivar = 12\n"
            "        corlength = 2000.\n"
            "$end\n"
            "\n"
            "$assimil2\n"
            "        nobs = 1\n"
            "        ivar = 11\n"
            "$end\n"
        )
        parsed = StrParser.parse(content)
        assert parsed.get_param("assimil1", "ivar") == 12
        assert parsed.get_param("assimil2", "ivar") == 11
        assert parsed.get_param("assimil1", "nobs") == 2

    def test_assimil_section_roundtrips_verbatim_when_unmodified(self):
        line = "        corlength = 2000. 3000."  # per-station array form
        content = f"$assimil1\n        nobs = 2\n        ivar = 12\n{line}\n$end\n"
        out = StrParser.generate(StrParser.parse(content))
        assert line in out.splitlines()
        # spec test 3: untouched load -> save is byte-identical. Single
        # section only: the generator's inter-section blank-line handling
        # precludes multi-section byte-identity, so per-section is the
        # guarantee.
        assert out == content
```

And add to `TestPhysicsPanels` in `shyfem-ui/tests/test_physics_page.py`:

```python
    def test_assimilation_panel_registry_is_composite(self):
        """No 1:1 registered params and no dedicated section: the old
        registry wrote a $nduge section the core hard-rejects."""
        from shyfem_ui.pages.physics import PHYSICS_PANELS

        panel = PHYSICS_PANELS["assimilation"]
        assert panel["params"] == {}
        assert "section" not in panel
```

- [ ] **Step 2: Run tests — new metadata + registry tests fail, round-trip tests pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py tests/test_physics_page.py -q`
Expected: `test_nduge_metadata_removed` FAILS (`"nduge" in COMMON_PARAMS`) and `test_assimilation_panel_registry_is_composite` FAILS (registry still carries `"section": "nduge"`); both new assimil round-trip tests PASS (parser already handles numbered sections — these are regression locks); everything else PASSES.

- [ ] **Step 3: Remove the nduge metadata and re-register the panel as composite**

In `shyfem-ui/shyfem_ui/pages/physics.py` replace:

```python
    "assimilation": {
        "label": "Data Assimilation",
        "icon": "bi-bullseye",
        "section": "nduge",
        "params": {"ibarcl": "para"},
    },
```

with:

```python
    "assimilation": {
        "label": "Data Assimilation",
        "icon": "bi-bullseye",
        # composite panel: reads/writes numbered $assimil sections
        # directly, nothing registered for the generic save loop
        "params": {},
    },
```

(The panel's render function still shows the old controls until Task 3;
with the registry emptied they become inert — nothing is written for
this panel, so `$nduge` can no longer be produced.)

In `shyfem-ui/shyfem_ui/services/parser_str.py` delete the
`COMMON_SECTIONS` entry:

```python
    "nduge": "Data assimilation via zeta/velocity nudging",
```

and the whole `COMMON_PARAMS` block:

```python
    "nduge": {
        "nvars": _p("Number of nudging observation stations", "int", 0, "", "0-50"),
        "tramp": _p("Nudging ramp-up time", "float", 0.0, "s", ">=0"),
        "ttau": _p("Relaxation time constant", "float", 0.0, "s", ">0"),
        "sigma": _p("Spatial influence radius (Gaussian)", "float", 0.0, "m", ">0"),
        "bmulti": _p("Multi-station nudging", "int", 1, "", "0=off, 1=on"),
    },
```

- [ ] **Step 4: Run both test files fully**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py tests/test_physics_page.py -q`
Expected: ALL PASS — including the pre-existing
`test_dedicated_sections_exist_in_common_params`, which stays green only
because the registry and metadata changed together. (If anything else
referenced `COMMON_PARAMS["nduge"]`, it surfaces here — fix by deleting
the reference, not by re-adding nduge.)

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/parser_str.py shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_parser_str.py shyfem-ui/tests/test_physics_page.py && git commit -m "feat(ui): drop dead \$nduge metadata + registry wiring, lock \$assimilN round-trip"
```

---

### Task 2: Pure assimilation helpers in physics.py

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` (module level, immediately after `_rate_field`, ~line 333)
- Test: `shyfem-ui/tests/test_physics_page.py`

**Interfaces:**
- Consumes: `StrFile.get_param/set_param/get_section_names`, `_scalar_or_none` (already in physics.py).
- Produces (used verbatim by Tasks 3-4):
  - `_ASSIMIL_NAME: re.Pattern` — matches `assimil<digits>`
  - `_ASSIMIL_NUMERIC_FIELDS: tuple[str, ...]`, `_ASSIMIL_INT_FIELDS: set[str]`, `_ASSIMIL_FILE_FIELDS: tuple[str, ...]`, `_ASSIMIL_DEFAULTS: dict[str, float | int]`
  - `_assimil_find(sf: StrFile, ivar: int) -> str | None`
  - `_assimil_nobs(sf: StrFile, name: str) -> int`
  - `_assimil_new_name(sf: StrFile, preferred: int) -> str`
  - `_assimil_is_array(sf: StrFile, name: str | None, param: str) -> bool`
  - `_assimil_apply(sf: StrFile, ivar: int, preferred: int, on: bool, values: dict) -> str | None`
  - `_purge_nduge(sf: StrFile) -> bool`

- [ ] **Step 1: Write the failing tests**

Add to `shyfem-ui/tests/test_physics_page.py`, inside `TestPhysicsPanels`
(follow the imetout tests' import-inside-test style):

```python
    def _assim_sf(self, extra=""):
        from shyfem_ui.services.parser_str import StrParser

        return StrParser.parse(
            "$para\n        ibarcl = 3\n$end\n\n"
            "$assimil7\n"
            "        nobs = 2\n"
            "        ivar = 12\n"
            "        mode = 1\n"
            "        tau = 1800.\n"
            "        corlength = 2000.\n"
            "        sigobs = 0.1\n"
            "        sigback = 1.0\n"
            "        filecoords = 'mm_assim_coords.dat'\n"
            "        fileobs = 'mm_assim_obs.dat'\n"
            "$end\n" + extra
        )

    def test_assimil_find_adopts_by_ivar_not_number(self):
        from shyfem_ui.pages.physics import _assimil_find

        sf = self._assim_sf()
        assert _assimil_find(sf, 12) == "assimil7"
        assert _assimil_find(sf, 11) is None

    def test_assimil_nobs_corrupt_reads_as_zero(self):
        from shyfem_ui.pages.physics import _assimil_nobs
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$assimil1\n        nobs = 2, 3\n        ivar = 12\n$end\n")
        assert _assimil_nobs(sf, "assimil1") == 0  # "2," is not a clean int

    def test_assimil_new_name_skips_taken_numbers(self):
        from shyfem_ui.pages.physics import _assimil_new_name
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$assimil1\n        ivar = 30\n$end\n")
        assert _assimil_new_name(sf, 1) == "assimil2"
        assert _assimil_new_name(sf, 2) == "assimil2"

    def test_assimil_is_array_detects_space_form(self):
        """Space-separated per-station arrays parse to a clean first-token
        scalar (PARAM_PATTERN truncation), so detection must come from the
        section's raw line, not the parsed value."""
        from shyfem_ui.pages.physics import _assimil_is_array
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse(
            "$assimil1\n        corlength = 2000. 3000.\n        tau = 1800.\n$end\n"
        )
        assert _assimil_is_array(sf, "assimil1", "corlength") is True
        assert _assimil_is_array(sf, "assimil1", "tau") is False
        assert _assimil_is_array(sf, None, "corlength") is False
        assert _assimil_is_array(sf, "missing", "corlength") is False

    def test_assimil_apply_creates_wellformed_section(self):
        from shyfem_ui.pages.physics import _assimil_apply
        from shyfem_ui.services.parser_str import StrFile, StrParser

        sf = StrFile()
        name = _assimil_apply(
            sf, 11, 2, True,
            {"nobs": 1, "mode": "0", "tau": 1800.0, "corlength": 2000.0,
             "sigobs": 0.1, "sigback": 1.0,
             "filecoords": "coords.dat", "fileobs": "obs.dat"},
        )
        assert name == "assimil2"
        assert sf.get_param("assimil2", "ivar") == 11
        assert sf.get_param("assimil2", "nobs") == 1
        assert sf.get_param("assimil2", "mode") == 0  # "0" coerced to int
        assert sf.get_param("assimil2", "filecoords") == "'coords.dat'"
        out = StrParser.generate(sf)
        assert "$assimil2" in out
        assert "filecoords = 'coords.dat'" in out  # quoted, not bare

    def test_assimil_apply_disable_touches_only_nobs(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        name = _assimil_apply(sf, 12, 1, False, {"corlength": 9999.0})
        assert name == "assimil7"
        assert sf.get_param("assimil7", "nobs") == 0
        assert sf.get_param("assimil7", "corlength") == 2000.0  # untouched
        assert sf.sections["assimil7"]._modified_params == {"nobs"}
        # disabled + no section for this ivar -> no-op, nothing created
        from shyfem_ui.services.parser_str import StrFile

        empty = StrFile()
        assert _assimil_apply(empty, 12, 1, False, {}) is None
        assert empty.get_section_names() == []

    def test_assimil_apply_skips_missing_fields(self):
        """A field absent from values (array-note case: no input was
        created) must not be written, so its raw line survives."""
        from shyfem_ui.pages.physics import _assimil_apply
        from shyfem_ui.services.parser_str import StrParser

        sf = self._assim_sf()
        _assimil_apply(sf, 12, 1, True, {"nobs": 2, "tau": 900.0})
        out = StrParser.generate(sf)
        assert "        corlength = 2000." in out.splitlines()
        assert sf.get_param("assimil7", "tau") == 900.0
        # write-back went to the adopted section's own name — no spurious
        # $assimil1 created alongside it
        assert "assimil1" not in sf.get_section_names()

    def test_purge_nduge(self):
        from shyfem_ui.pages.physics import _purge_nduge
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$nduge\n        nvars = 3\n$end\n\n$para\n        idt = 300\n$end\n")
        assert _purge_nduge(sf) is True
        assert "nduge" not in StrParser.generate(sf)
        assert _purge_nduge(sf) is False  # second call: nothing to do
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q -k "assim or nduge"`
Expected: all new tests FAIL with `ImportError: cannot import name '_assimil_find'` (etc.). (`-k "assim or nduge"` — not `-k assimil` — so `test_purge_nduge` is selected too; the Task 1 registry test also matches and stays green.)

- [ ] **Step 3: Implement the helpers**

In `shyfem-ui/shyfem_ui/pages/physics.py`: add `import re` to the imports
(after `import logging`), then insert after `_rate_field` (~line 333):

```python
_ASSIMIL_NAME = re.compile(r"^assimil(\d+)$")

# Numbered $assimil sections (assimil_admin.f90): one section per
# assimilated variable, single values broadcast to all nobs stations.
_ASSIMIL_NUMERIC_FIELDS = (
    "nobs", "mode", "tau", "corlength", "maxlength",
    "sigobs", "sigback", "layer", "vcorlength",
)
_ASSIMIL_INT_FIELDS = {"nobs", "mode", "layer"}
_ASSIMIL_FILE_FIELDS = ("filecoords", "fileobs")
# Prefills for a freshly enabled block; corlength/sigobs/sigback must be
# > 0 for the core to accept the section.
_ASSIMIL_DEFAULTS = {
    "nobs": 1, "mode": 0, "tau": 0.0, "corlength": 1000.0, "maxlength": 0.0,
    "sigobs": 0.1, "sigback": 1.0, "layer": 0, "vcorlength": 0.0,
}


def _assimil_find(sf: StrFile, ivar: int) -> str | None:
    """Name of the $assimilN section assimilating *ivar*, or None.

    Adoption is by ivar, not by section number: a hand-written $assimil7
    with ivar = 12 is the temperature section and is written back under
    its own name.
    """
    for name in sf.get_section_names():
        if not _ASSIMIL_NAME.match(name):
            continue
        try:
            if int(sf.get_param(name, "ivar")) == ivar:
                return name
        except (TypeError, ValueError):
            continue
    return None


def _assimil_nobs(sf: StrFile, name: str) -> int:
    """nobs of a section, 0 when absent or not a clean integer."""
    try:
        return int(sf.get_param(name, "nobs"))
    except (TypeError, ValueError):
        return 0


def _assimil_new_name(sf: StrFile, preferred: int) -> str:
    """assimil<preferred>, or the first free number above it."""
    used = {
        int(m.group(1))
        for m in (_ASSIMIL_NAME.match(n) for n in sf.get_section_names())
        if m
    }
    num = preferred
    while num in used:
        num += 1
    return f"assimil{num}"


def _assimil_is_array(sf: StrFile, name: str | None, param: str) -> bool:
    """True when *param*'s raw STR line carries more than one value token.

    PARAM_PATTERN truncates a space-separated per-station array
    (``corlength = 2000. 3000.``) to a clean first-token scalar, so the
    parsed value alone cannot reveal it — scan the section's raw line.
    Multi-token remainders are treated as arrays conservatively: the
    field goes read-only and the raw line survives; never a partial
    rewrite of station 1 only.
    """
    if name is None or name not in sf.sections:
        return False
    pat = re.compile(rf"^\s*{re.escape(param)}\s*=\s*(.+)$")
    for line in sf.sections[name].raw_lines:
        m = pat.match(line)
        if m:
            return len(m.group(1).split()) > 1
    return False


def _assimil_apply(
    sf: StrFile, ivar: int, preferred: int, on: bool, values: dict
) -> str | None:
    """Write one assimilation block into *sf*; returns the section touched.

    Disabled: set nobs = 0 only (the core ignores and logs such sections;
    the stored tuning survives for re-enabling). Enabled: write every
    field present in *values*; a missing field (its input was never
    created — the per-station-array case) keeps its raw STR line. File
    fields are stored pre-quoted because _format_value leaves bare
    dash-less filenames unquoted, which the Fortran namelist reader
    rejects for character parameters.
    """
    name = _assimil_find(sf, ivar)
    if not on:
        if name is not None:
            sf.set_param(name, "nobs", 0)
        return name
    if name is None:
        name = _assimil_new_name(sf, preferred)
    sf.set_param(name, "ivar", ivar)
    for param in _ASSIMIL_NUMERIC_FIELDS:
        if param not in values:
            continue
        try:
            num = (
                int(float(values[param]))
                if param in _ASSIMIL_INT_FIELDS
                else float(values[param])
            )
        except (TypeError, ValueError):
            continue
        sf.set_param(name, param, num)
    for param in _ASSIMIL_FILE_FIELDS:
        raw = str(values.get(param, "") or "").strip()
        if not raw:
            continue
        if not (raw.startswith("'") and raw.endswith("'")):
            raw = f"'{raw}'"
        sf.set_param(name, param, raw)
    return name


def _purge_nduge(sf: StrFile) -> bool:
    """Drop the dead $nduge section the old UI used to write.

    No core code reads it and iostr.f90 hard-stops on unknown sections,
    so any STR carrying it cannot run. generate() skips the stale
    _structure entry once the section is gone.
    """
    if "nduge" not in sf.sections:
        return False
    del sf.sections["nduge"]
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q -k "assim or nduge"`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_page.py && git commit -m "feat(ui): pure helpers for \$assimilN adoption, write-back and \$nduge purge"
```

---

### Task 3: Panel UI rewrite, registry, remap removal

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` — `_INPUT_ID_REMAP` (~line 447), `module_badges` "Nudging" row (~line 598), `panel_assimilation` (~lines 1808-1878), new block/field builders after `_purge_nduge` (the registry entry was already made composite in Task 1)
- Test: `shyfem-ui/tests/test_physics_page.py` (new tests + one stale hardcoded remap copy at ~lines 386-401)

**Interfaces:**
- Consumes: Task 2 helpers (`_assimil_find`, `_assimil_nobs`, `_assimil_is_array`, `_ASSIMIL_NAME`, `_ASSIMIL_DEFAULTS`, `_ASSIMIL_INT_FIELDS`), `_scalar_or_none`.
- Produces: input IDs read by Task 4's save step — `assim_t_on`, `assim_s_on`, and `assim_{t|s}_{nobs,mode,tau,corlength,maxlength,sigobs,sigback,layer,vcorlength,filecoords,fileobs}`. Module-level `_assimil_block(sf, title, prefix, ivar) -> ui.Tag` and `_assimil_num_field(prefix, param, label, raw, is_array=False, **kwargs) -> ui.Tag`.

- [ ] **Step 1: Write the failing tests**

Add to `TestPhysicsPanels` in `shyfem-ui/tests/test_physics_page.py`
(the registry-is-composite test already exists from Task 1):

```python
    def test_ibarcl_assim_remap_removed(self):
        """The baroclinic panel owns ibarcl; a duplicate select here was
        a last-writer-wins footgun (and offered only the wrong modes)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert "ibarcl_assim" not in src

    def test_panel_assimilation_renders_block_inputs(self):
        """Behavioral: render both blocks and check the namespaced ids in
        the HTML (the ids are f-string-built, so source-grepping for
        literals like "assim_t_on" would never match)."""
        from shyfem_ui.pages.physics import _assimil_block
        from shyfem_ui.services.parser_str import StrFile

        html = str(_assimil_block(StrFile(), "Temperature", "t", 12)) + str(
            _assimil_block(StrFile(), "Salinity", "s", 11)
        )
        for input_id in ("assim_t_on", "assim_s_on", "assim_t_nobs", "assim_s_fileobs"):
            assert input_id in html, f"missing {input_id}"

    def test_assimil_blocks_reflect_stored_values(self):
        """Spec test 1: an mm_hyd_assim-shaped STR (T + S sections) fills
        both blocks — checkbox from nobs, numerics and filenames from the
        adopted section."""
        from shyfem_ui.pages.physics import _assimil_block

        sf = self._assim_sf(
            "\n$assimil2\n        nobs = 0\n        ivar = 11\n        tau = 600.\n$end\n"
        )
        t_html = str(_assimil_block(sf, "Temperature", "t", 12))
        assert "checked" in t_html  # nobs = 2 -> enabled
        assert 'value="1800.0"' in t_html  # tau from $assimil7
        assert "mm_assim_coords.dat" in t_html  # filecoords, unquoted on load
        s_html = str(_assimil_block(sf, "Salinity", "s", 11))
        assert "checked" not in s_html  # nobs = 0 -> disabled
        assert 'value="600.0"' in s_html  # stored tuning still shown

    def test_assimil_block_space_separated_array_renders_note(self):
        """Spec test 4, space form: the parser truncates space-separated
        per-station values to a clean scalar, so the block must classify
        the field from its raw line and render the note, not an input."""
        from shyfem_ui.pages.physics import _assimil_block
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse(
            "$assimil1\n        nobs = 2\n        ivar = 12\n"
            "        corlength = 2000. 3000.\n$end\n"
        )
        html = str(_assimil_block(sf, "Temperature", "t", 12))
        assert "assim_t_corlength" not in html
        assert "set in the STR" in html

    def test_module_badges_key_assimilation_not_nduge(self):
        """The sidebar badge must reflect real $assimil sections, not the
        dead $nduge (which would advertise a guaranteed-fatal STR)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert '"nduge" in sf.sections' not in src
        assert '("Assimilation",' in src

    def test_assimil_block_reads_strfile_not_registry(self):
        """Slice-2 lesson: composite params must come from the StrFile
        (build_panel_params only returns registered params -> always 0)."""
        import inspect

        from shyfem_ui.pages.physics import _assimil_block

        sig = inspect.signature(_assimil_block)
        assert list(sig.parameters)[0] == "sf"

    def test_assimil_num_field_array_renders_note_not_input(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        note = _assimil_num_field("t", "corlength", "Correlation length (m)", "2000.,")
        assert "assim_t_corlength" not in str(note)
        assert "set in the STR" in str(note)

    def test_assimil_num_field_scalar_renders_input(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        tag = _assimil_num_field("t", "corlength", "Correlation length (m)", 2000.0)
        assert "assim_t_corlength" in str(tag)

    def test_assimil_num_field_absent_uses_default(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        tag = str(_assimil_num_field("s", "sigback", "Background error sigma", None))
        assert "assim_s_sigback" in tag
        assert 'value="1.0"' in tag  # _ASSIMIL_DEFAULTS["sigback"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q -k "assim or nduge"`
Expected: the nine new Task 3 tests FAIL — most with `ImportError: cannot import name '_assimil_block'`/`'_assimil_num_field'`; `test_ibarcl_assim_remap_removed` and `test_module_badges_key_assimilation_not_nduge` with AssertionError (`ibarcl_assim` and the nduge badge still present). Task 1/2 assimil tests stay green.

- [ ] **Step 3a: Remap, badge, and stale-test edits**

In `shyfem-ui/shyfem_ui/pages/physics.py` delete the remap entry:

```python
        "ibarcl_assim": ("para", "ibarcl"),
```

In the same file's `module_badges` checks list (~line 598) replace:

```python
            ("Nudging", "nduge" in sf.sections, None),
```

with:

```python
            (
                "Assimilation",
                any(_ASSIMIL_NAME.match(n) for n in sf.get_section_names()),
                None,
            ),
```

In `shyfem-ui/tests/test_physics_page.py`, `test_collect_remap_ids_are_valid`
(~lines 386-401) keeps a hardcoded copy of the remap dict — delete its
`"ibarcl_assim": ("para", "ibarcl"),` row so the copy matches the real
`_INPUT_ID_REMAP` again.

- [ ] **Step 3b: Field and block builders**

Insert after `_purge_nduge` (module level):

```python
def _assimil_num_field(
    prefix: str, param: str, label: str, raw: object, is_array: bool = False, **kwargs
) -> ui.Tag:
    """Numeric column for one OI parameter.

    Editable when the stored value is a clean scalar or absent (absent
    falls back to _ASSIMIL_DEFAULTS); a per-station array renders as a
    static note with NO input control, so the save step's read fails and
    the raw STR line survives verbatim (slice-1 pattern). Arrays arrive
    two ways: comma forms parse to a non-scalar string (caught here via
    _scalar_or_none), space forms parse to a clean first token and are
    flagged by the caller via is_array (raw-line detection).
    """
    val = _scalar_or_none(raw)
    if is_array or (raw is not None and val is None):
        return ui.help_text(f"{label}: per-station values set in the STR — edit the file directly.")
    if val is None:
        val = _ASSIMIL_DEFAULTS[param]
    if param in _ASSIMIL_INT_FIELDS:
        val = int(val)
    return ui.input_numeric(f"assim_{prefix}_{param}", label, value=val, **kwargs)


def _assimil_block(sf: StrFile, title: str, prefix: str, ivar: int) -> ui.Tag:
    """One variable block (Temperature or Salinity) of the panel.

    All fields always render; the checkbox gates only what the save step
    writes (ui.panel_conditional is avoided: its JS condition strings
    are not namespaced inside Shiny modules).
    """
    name = _assimil_find(sf, ivar)
    enabled = name is not None and _assimil_nobs(sf, name) > 0

    def raw(param: str) -> object:
        return sf.get_param(name, param) if name else None

    def num(param: str, label: str, **kwargs) -> ui.Tag:
        return _assimil_num_field(
            prefix,
            param,
            label,
            raw(param),
            is_array=_assimil_is_array(sf, name, param),
            **kwargs,
        )

    try:
        mode_sel = str(int(raw("mode")))
    except (TypeError, ValueError):
        mode_sel = "0"
    if mode_sel not in ("0", "1"):
        mode_sel = "0"

    return ui.div(
        ui.h6(f"{title} (ivar {ivar})", class_="text-muted mt-3"),
        ui.input_checkbox(f"assim_{prefix}_on", f"Assimilate {title.lower()}", value=enabled),
        ui.row(
            ui.column(4, num("nobs", "Observation stations", min=1, step=1)),
            ui.column(
                4,
                ui.input_select(
                    f"assim_{prefix}_mode",
                    "Application mode",
                    choices={"0": "0 - Nudging", "1": "1 - Direct insertion"},
                    selected=mode_sel,
                ),
            ),
            ui.column(4, num("tau", "Timescale tau (s)", min=0, step=60.0)),
        ),
        ui.row(
            ui.column(4, num("corlength", "Correlation length (m)", min=1.0, step=100.0)),
            ui.column(4, num("maxlength", "Max influence radius (m, 0 = no cutoff)", min=0, step=100.0)),
            ui.column(4, num("sigobs", "Observation error sigma", min=1e-6, step=0.05)),
        ),
        ui.row(
            ui.column(4, num("sigback", "Background error sigma", min=1e-6, step=0.05)),
            ui.column(4, num("layer", "Observation layer (0 = uniform column)", min=0, step=1)),
            ui.column(4, num("vcorlength", "Vertical corr. length (m, 0 = uniform)", min=0, step=0.5)),
        ),
        ui.row(
            ui.column(
                6,
                ui.input_text(
                    f"assim_{prefix}_filecoords",
                    "Station coordinates file",
                    value=str(raw("filecoords") or ""),
                ),
            ),
            ui.column(
                6,
                ui.input_text(
                    f"assim_{prefix}_fileobs",
                    "Observations file",
                    value=str(raw("fileobs") or ""),
                ),
            ),
        ),
    )
```

- [ ] **Step 3c: Replace panel_assimilation**

Replace the whole existing `panel_assimilation` render function (the one
rendering `ibarcl_assim`/`nvars`/`tramp`/`ttau`/`sigma`/`bmulti`) with:

```python
    @render.ui
    def panel_assimilation():
        sf = str_data.get()
        adopted = {_assimil_find(sf, 12), _assimil_find(sf, 11)}
        others = [
            n for n in sf.get_section_names()
            if _ASSIMIL_NAME.match(n) and n not in adopted
        ]
        children = [
            ui.help_text(
                "Optimal-interpolation assimilation runs in prognostic "
                "baroclinic mode (ibarcl = 3, set in the Baroclinic panel)."
            ),
        ]
        if others:
            children.append(
                ui.help_text(
                    "Other $assimil sections present (edited in the STR): "
                    + ", ".join(f"${n}" for n in others)
                )
            )
        children.append(_assimil_block(sf, "Temperature", "t", 12))
        children.append(_assimil_block(sf, "Salinity", "s", 11))
        return ui.div(*children)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q`
Expected: ALL PASS (whole file — catches any old test of the removed panel; if one asserts `nduge`/`ibarcl_assim` behavior, delete it, it tests the bug).

- [ ] **Step 5: Commit**

(The spec's panel_conditional line was already amended to always-render
during plan review — no spec edit needed here.)

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_page.py && git commit -m "feat(ui): rebuild Data Assimilation panel on \$assimilN T/S blocks"
```

---

### Task 4: Composite save step + $nduge purge in _collect_panel_values

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py` — `_collect_panel_values` (after the imetout composite block, ~line 481)
- Test: `shyfem-ui/tests/test_physics_page.py`

**Interfaces:**
- Consumes: Task 2 `_assimil_apply`/`_purge_nduge`/`_ASSIMIL_NUMERIC_FIELDS`/`_ASSIMIL_FILE_FIELDS`; Task 3 input IDs (`assim_{t|s}_...`).
- Produces: save behavior only; no new names.

- [ ] **Step 1: Write the failing tests**

Add to `TestPhysicsPanels`:

```python
    def test_collect_panel_values_wires_assimil_and_nduge_purge(self):
        """Regression locks on the composite save step: per-block guarded
        checkbox read, per-field guarded input reads feeding
        _assimil_apply, and the unconditional $nduge purge."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        collect = src[src.index("def _collect_panel_values") : src.index("def _read_input_and_set")]
        assert "_assimil_apply(" in collect
        assert "_purge_nduge(" in collect
        assert 'input[f"assim_{prefix}_on"]' in collect
        assert 'input[f"assim_{prefix}_{param}"]' in collect
```

(The behavioral semantics — create/adopt/disable/skip-missing — are
already unit-tested against `_assimil_apply` in Task 2; this test locks
the glue that a Shiny session would exercise.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q -k "wires_assimil"`
Expected: FAIL (`_assimil_apply(` not in `_collect_panel_values`).

- [ ] **Step 3: Implement the composite step**

In `_collect_panel_values`, immediately after the imetout composite
block (after `sf.set_param("para", "imetout", _imetout_encode(flags))`),
add:

```python
        # --- composite sections: $assimilN <- T/S assimilation blocks ---
        for prefix, ivar, preferred in (("t", 12, 1), ("s", 11, 2)):
            try:
                on = bool(input[f"assim_{prefix}_on"]())
            except Exception:
                continue  # panel not rendered -> sections untouched
            values: dict[str, object] = {}
            for param in _ASSIMIL_NUMERIC_FIELDS + _ASSIMIL_FILE_FIELDS:
                try:
                    raw = input[f"assim_{prefix}_{param}"]()
                except Exception:
                    continue  # array-note field: input never created
                if raw is None or str(raw).strip() == "":
                    continue
                values[param] = raw
            _assimil_apply(sf, ivar, preferred, on, values)

        # --- purge the dead $nduge section on every save: the core
        # hard-stops on it, so an STR carrying it can never run ---
        if _purge_nduge(sf):
            ui.notification_show(
                "Removed dead $nduge section (the core rejects it).",
                type="message",
                duration=6,
            )
```

- [ ] **Step 4: Run the whole physics test file**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_page.py -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_page.py && git commit -m "feat(ui): composite save for \$assimilN blocks, purge dead \$nduge on save"
```

---

### Task 5: Fix the data_assimilation simulation template

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/simulation_logic.py` (`data_assimilation` template, ~lines 728-771)
- Test: `shyfem-ui/tests/test_str_templates.py` (~lines 173-184), `shyfem-ui/tests/test_simulation_logic.py` (~line 104)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent — the template is a string).
- Produces: a `data_assimilation` template the core can actually run.

- [ ] **Step 1: Rewrite the template tests**

In `shyfem-ui/tests/test_str_templates.py` replace the class body:

```python
class TestDataAssimilationTemplate:
    """Data assimilation template has $nduge."""

    def test_has_nduge(self):
        content = generate_template("data_assimilation")
        assert "$nduge" in content

    def test_has_ibarcl_4(self):
        content = generate_template("data_assimilation")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "ibarcl") == 4
```

with:

```python
class TestDataAssimilationTemplate:
    """Data assimilation template uses the real $assimil framework.

    The old template emitted a $nduge section no core code reads —
    iostr.f90 hard-stops on unknown sections, so every simulation
    created from it crashed at STR read."""

    def test_has_assimil_sections_not_nduge(self):
        content = generate_template("data_assimilation")
        assert "nduge" not in content
        parsed = StrParser.parse(content)
        assert parsed.get_param("assimil1", "ivar") == 12
        assert parsed.get_param("assimil2", "ivar") == 11
        for name in ("assimil1", "assimil2"):
            assert parsed.get_param(name, "nobs") == 1
            assert parsed.get_param(name, "corlength") > 0
            assert parsed.get_param(name, "sigobs") > 0
            assert parsed.get_param(name, "sigback") > 0
            assert parsed.get_param(name, "filecoords")
            assert parsed.get_param(name, "fileobs")

    def test_has_ibarcl_3(self):
        """assimil_ts runs under the active-transport branch: prognostic
        baroclinic (ibarcl = 3) required."""
        content = generate_template("data_assimilation")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "ibarcl") == 3
```

In `shyfem-ui/tests/test_simulation_logic.py` replace:

```python
    def test_data_assimilation_has_nduge(self):
        assert "$nduge" in generate_template("data_assimilation")
```

with:

```python
    def test_data_assimilation_has_assimil(self):
        out = generate_template("data_assimilation")
        assert "$assimil1" in out
        assert "$nduge" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_templates.py tests/test_simulation_logic.py -q -k "assimil or nduge"`
Expected: new tests FAIL (template still contains `$nduge`, `ibarcl = 4`).

- [ ] **Step 3: Rewrite the template**

In `shyfem-ui/shyfem_ui/services/simulation_logic.py`, inside the
`data_assimilation` template string: change `ibarcl = 4` to
`ibarcl = 3`, delete the `$name` entries `tempn`/`saltn` (they feed the
dead ibarcl=4 nudging path), and replace the block:

```
$nduge
        nvars = 3
        tramp = 43200
        ttau = 3600
        sigma = 5000
$end
```

with:

```
$assimil1
        nobs = 1
        ivar = 12
        mode = 0
        tau = 1800.
        corlength = 2000.
        sigobs = 0.1
        sigback = 1.0
        filecoords = 'INPUT/assim_coords.dat'
        fileobs = 'INPUT/assim_obs_temp.dat'
$end

$assimil2
        nobs = 1
        ivar = 11
        mode = 0
        tau = 1800.
        corlength = 2000.
        sigobs = 0.1
        sigback = 1.0
        filecoords = 'INPUT/assim_coords.dat'
        fileobs = 'INPUT/assim_obs_salt.dat'
$end
```

(the `$name` section keeps `wind = 'INPUT/wind.txt'`).

- [ ] **Step 4: Run both template test files fully**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_templates.py tests/test_simulation_logic.py -q`
Expected: ALL PASS (generic template-validity tests in these files must
also still pass).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/simulation_logic.py shyfem-ui/tests/test_str_templates.py shyfem-ui/tests/test_simulation_logic.py && git commit -m "fix(ui): data_assimilation template emits \$assimil sections, not dead \$nduge"
```

---

### Task 6: Format, full suite, review, PR

**Files:**
- Possibly modify: files black reformats under `shyfem_ui/` only.

**Interfaces:** none — gate task.

- [ ] **Step 1: Format check (CI scope only)**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/ && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/`
Expected: black reformats 0-2 of the touched files at most; ruff clean. Commit any reformat as `style(ui): black-format assimilation additions`. Do NOT run black on `tests/`.

- [ ] **Step 2: Full UI suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX= /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 0 failures. E2E tests requiring a browser follow their existing markers/skips; anything newly failing is this slice's regression — fix before proceeding.

- [ ] **Step 3: Review-in-loop**

Dispatch the `ui-security-reviewer` agent on the branch diff (`git diff main...feat/ui-assimilation`) plus `pr-review-toolkit:code-reviewer`. Address confirmed findings; re-run the affected test files after each fix.

- [ ] **Step 4: Push + PR**

```bash
cd /home/razinka/shyfem && git push -u origin feat/ui-assimilation
gh pr create --title "feat(ui): Data Assimilation panel for the \$assimil OI framework" --body "$(cat <<'EOF'
## Summary
- Replaces the broken Data Assimilation panel: the old one wrote a $nduge section no core code reads (iostr.f90 hard-stops on unknown sections), so saving from it produced STRs that crash shyfem at startup
- New panel exposes the real numbered $assimil sections (PRs #54/#61) as fixed Temperature/Salinity blocks with uniform per-section OI values, adoption by ivar, nobs=0 disable semantics, and slice-1 array preservation
- Fixes the data_assimilation simulation template the same way ($assimil1/2, ibarcl 4 -> 3) and purges $nduge from loaded STRs on save
- Spec: docs/superpowers/specs/2026-07-28-ui-assimilation-design.md

## Test plan
- [ ] Unit: helper suite (adopt-by-ivar, free-number allocation, disable touches only nobs, array-note fields survive verbatim, $nduge purge)
- [ ] Template: $assimil1/$assimil2 well-formed, ibarcl = 3, no nduge anywhere
- [ ] Full UI suite green locally; Lint/Unit/E2E/Docker green in CI (E2E runs on the PR)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review + review-in-loop (3 verifier agents, 2026-07-28)

- **Spec coverage:** registry/metadata → T1; helpers/adoption/save → T2+T4; panel UI + badge → T3; nduge purge + notify → T2 (pure) + T4 (glue/notification); template → T5; testing list items 1-9 → item 1 T3 (`test_assimil_blocks_reflect_stored_values`), 2 T2 (find + own-name write-back assert), 3 T1 (byte-identical single-section), 4 T2/T3 (comma AND space forms), 5-7 T2, 8 T5, 9 T1; gates → T6.
- **Review-in-loop fixes applied:** literal-ID source assertions replaced with behavioral block rendering (blocker); space-separated array detection added via `_assimil_is_array` raw-line scan (silent partial-rewrite hazard); registry change moved to T1 (mid-plan red-suite bisect hazard); `-k "assim or nduge"` selectors; `module_badges` nduge row replaced; stale remap-copy test row deleted; `'value="1.0"'` attribute-anchored asserts; disable-no-op and own-name write-back asserts added. Spec amendments (always-render, space-form arrays, template `$name` trim, purge-on-collect, per-section byte-identity) applied directly to the spec.
- **Type consistency:** `_assimil_apply(sf, ivar, preferred, on, values)` used identically in T2 tests and T4 glue; input IDs `assim_{prefix}_{param}` consistent between T3 builders and T4 reads; `_assimil_num_field(..., is_array=False, ...)` matches the `num()` closure's call; `_purge_nduge -> bool` consumed by T4's notification gate.
