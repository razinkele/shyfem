"""Physics configuration page -- guided SHYFEM parameter setup.

Complements the simulation page (raw STR editor) with structured
accordion panels for each physics module. Reads/writes the same
STR files.
"""

import copy
import logging
import math
import re

from shiny import module, reactive, render, ui
from shiny.types import SilentException

from shyfem_ui.components.project_select import (
    default_project_file,
    project_file_select,
)
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.parser_str import COMMON_PARAMS, StrFile, StrParser
from shyfem_ui.services.str_validator import validate_str

logger = logging.getLogger(__name__)

PHYSICS_PANELS = {
    "timing": {
        "label": "Simulation Timing",
        "icon": "bi-clock",
        "params": {
            "itanf": "para",
            "itend": "para",
            "idt": "para",
            "date": "para",
            "time": "para",
            "tz": "para",
        },
    },
    "hydrodynamics": {
        "label": "Hydrodynamics",
        "icon": "bi-water",
        "params": {
            "ilin": "para",
            "itlin": "para",
            "iclin": "para",
            "itsplt": "para",
            "coumax": "para",
            "idtsyn": "para",
            "icor": "para",
            "dlat": "para",
            "isphe": "para",
            "hzmin": "para",
            "hzoff": "para",
            "hzon": "para",
            "rtide": "para",
        },
    },
    "advanced_hydro": {
        "label": "Advanced Hydrodynamics",
        "icon": "bi-sliders2",
        "params": {
            "azpar": "para",
            "ampar": "para",
            "afpar": "para",
            "atpar": "para",
            "adpar": "para",
            "aapar": "para",
            "href": "para",
            "hmin": "para",
            "hmax": "para",
            "rlin": "para",
            "rowass": "para",
            "roluft": "para",
        },
    },
    "vertical": {
        "label": "Vertical Structure",
        "icon": "bi-layers",
        "params": {
            "dzreg": "para",
            "ilytyp": "para",
            "hlvmin": "para",
            "nzadapt": "para",
            "nsigma": "para",
            "hsigma": "para",
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
            "iturb": "para",
            "difmol": "para",
            "vismol": "para",
            "diftur": "para",
            "vistur": "para",
            "idhtyp": "para",
            "ahpar": "para",
            "dhpar": "para",
            "itvd": "para",
            "itvdv": "para",
            "noslip": "para",
        },
    },
    "heat": {
        "label": "Heat Flux",
        "icon": "bi-thermometer-sun",
        "params": {
            "iheat": "para",
            "ihtype": "para",
            "hdecay": "para",
            "albedo": "para",
            "ievap": "para",
            "irain": "para",
        },
    },
    "wind": {
        "label": "Wind & Forcing",
        "icon": "bi-wind",
        "params": {
            "iwtype": "para",
            "dragco": "para",
            "wsmax": "para",
            "rfact": "para",
        },
    },
    "temperature_salinity": {
        "label": "Temperature & Salinity",
        "icon": "bi-droplet-half",
        "params": {
            "ibarcl": "para",
            "itemp": "para",
            "isalt": "para",
            "temref": "para",
            "salref": "para",
            "thpar": "para",
            "shpar": "para",
            "idtcon": "para",
            "icon_av": "para",
        },
    },
    "ecology": {
        "label": "Ecology",
        "icon": "bi-tree",
        "params": {"ibio": "para", "imerc": "para"},
        "section": "bfmsc",
    },
    "tracers": {
        "label": "Tracers / Concentration",
        "icon": "bi-droplet",
        "params": {
            "iconz": "para",
            "iage": "para",
            "idecay": "para",
            "conref": "para",
            "chpar": "para",
            "wsettl": "para",
            "ibeach": "para",
            "beachrate": "para",
            "burryrate": "para",
        },
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
        "params": {
            "ilagr": "para",
            "icnn": "connec",
            "radcnn": "connec",
            "ppscnn": "connec",
            "pldcnn": "connec",
            "idtcnn": "connec",
        },
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
        # composite panel: reads/writes numbered $assimil sections
        # directly, nothing registered for the generic save loop
        "params": {},
    },
    "renewal_time": {
        "label": "Water Renewal Time",
        "icon": "bi-clock-history",
        "section": "wrt",
        "params": {},
    },
    "input_files": {
        "label": "Input Files",
        "icon": "bi-folder2-open",
        "section": "name",
        "params": {},
    },
    "nonhydrostatic": {
        "label": "Non-Hydrostatic",
        "icon": "bi-box-arrow-up",
        "section": "nonhyd",
        "params": {},
    },
    "boundary": {
        "label": "Boundary Conditions",
        "icon": "bi-border-outer",
        "section": "bound",
        "params": {},
    },
    "output": {
        "label": "Output & Restart",
        "icon": "bi-save",
        "params": {
            "idtout": "para",
            "idtext": "para",
            "idtcon": "para",
            "idtflx": "para",
            "idtres": "para",
            "idtrst": "para",
            "idtrms": "para",
            "idtvol": "para",
            "idtmet": "para",
            "idtstb": "para",
            "netcdf": "para",
            "iout_av": "para",
            "icon_av": "para",
            "itrst": "para",
            "itmrst": "para",
            "ityrst": "para",
            "idtoff": "para",
            "itmoff": "para",
        },
    },
}


def build_panel_params(str_file: StrFile, panel_id: str) -> dict:
    """Extract current parameter values for a panel from a parsed StrFile.

    Returns dict of param_name -> current_value (or default from COMMON_PARAMS).
    """
    panel = PHYSICS_PANELS[panel_id]
    result = {}

    for param, section in panel["params"].items():
        value = str_file.get_param(section, param)
        if value is None:
            sec_params = COMMON_PARAMS.get(section, {})
            info = sec_params.get(param)
            value = info[2] if info else None
        result[param] = value

    # Include params from a dedicated section (e.g. sedtr, lagrg, nduge)
    dedicated = panel.get("section")
    if dedicated and dedicated in COMMON_PARAMS:
        for param, info in COMMON_PARAMS[dedicated].items():
            if param not in result:
                value = str_file.get_param(dedicated, param)
                if value is None:
                    value = info[2]
                result[param] = value

    return result


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
    return sum(int(bool(flags.get(f))) * 10**i for i, f in enumerate(_IMETOUT_FIELDS))


def _scalar_or_none(raw: object) -> float | None:
    """Return *raw* as a float if it is a single clean scalar, else None.

    ``beachrate``/``burryrate`` are per-area-code arrays in the core. A
    multi-area value like ``0.3, 0.25, 0.1`` is truncated by the parser to
    the string ``"0.3,"`` (PARAM_PATTERN stops at whitespace), which is not a
    clean scalar. Returning None for such values lets the caller show a note
    instead of an editable field, so the array is never flattened on save.
    """
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rate_field(input_id: str, label: str, raw: object) -> ui.Tag:
    """A beaching-rate column: an editable numeric for a scalar value, or a
    static note for a per-area-code array (edited directly in the STR).

    When the note is shown the ``input_id`` control is intentionally not
    created, so the save loop's ``input[input_id]()`` read fails and the raw
    STR line is preserved verbatim rather than overwritten with a scalar.
    """
    val = _scalar_or_none(raw)
    if val is None:
        return ui.help_text(f"{label}: per-area rates set in the STR — edit the file directly.")
    return ui.input_numeric(input_id, label, value=val, min=0, step=0.01)


_ASSIMIL_NAME = re.compile(r"^assimil(\d+)$")
# Any section the user meant as an assimilation block, including the
# numberless and zero forms the core rejects (read_assimil error-stops
# on num <= 0, assimil_admin.f90) — the panel must name them rather
# than leave them invisible next to an offer to create $assimil1.
_ASSIMIL_ANY_NAME = re.compile(r"^assimil(\d*)$")

# Numbered $assimil sections (assimil_admin.f90): one section per
# assimilated variable, single values broadcast to all nobs stations.
_ASSIMIL_NUMERIC_FIELDS = (
    "nobs",
    "mode",
    "tau",
    "corlength",
    "maxlength",
    "sigobs",
    "sigback",
    "layer",
    "vcorlength",
)
_ASSIMIL_INT_FIELDS = {"nobs", "mode", "layer"}
_ASSIMIL_FILE_FIELDS = ("filecoords", "fileobs")
# Must hold a value for the core to accept an enabled section; the other
# numerics ("optional") default to 0 in the core, so a cleared input
# becomes an explicit 0 rather than an error.
_ASSIMIL_REQUIRED_FIELDS = ("nobs", "corlength", "sigobs", "sigback")
_ASSIMIL_OPTIONAL_FIELDS = ("tau", "maxlength", "layer", "vcorlength")
# Prefills for a freshly enabled block; corlength/sigobs/sigback must be
# > 0 for the core to accept the section, and tau must be > 0 in nudging
# mode (mode=0) or the core error-stops mid-run at the first observation.
_ASSIMIL_DEFAULTS = {
    "nobs": 1,
    "mode": 0,
    "tau": 1800.0,
    "corlength": 1000.0,
    "maxlength": 0.0,
    "sigobs": 0.1,
    "sigback": 1.0,
    "layer": 0,
    "vcorlength": 0.0,
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
    used = {int(m.group(1)) for m in (_ASSIMIL_NAME.match(n) for n in sf.get_section_names()) if m}
    num = preferred
    while num in used:
        num += 1
    return f"assimil{num}"


# An assignment anywhere on a line. The lookbehind keeps "corlength"
# from matching inside "vcorlength", which would freeze the wrong field.
_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9_])(\w+)\s*=\s*")


def _assimil_other_sections(sf: StrFile, adopted) -> tuple[list[str], list[str]]:
    """($assimilN sections the panel does not own, ones the core rejects)."""
    others: list[str] = []
    invalid: list[str] = []
    for name in sf.get_section_names():
        if name in adopted or not _ASSIMIL_ANY_NAME.match(name):
            continue
        numbered = _ASSIMIL_NAME.match(name)
        if numbered and int(numbered.group(1)) > 0:
            others.append(name)
        else:
            invalid.append(name)
    return others, invalid


def _assimil_is_array(sf: StrFile, name: str | None, param: str) -> bool:
    """True when *param* carries more than one value token in the raw STR.

    PARAM_PATTERN truncates a space-separated per-station array
    (``corlength = 2000. 3000.``) to a clean first-token scalar, so the
    parsed value alone cannot reveal it — scan the section's raw lines.
    An array is not necessarily alone on its line: the core takes every
    unnamed number following an assignment as a further value of that
    parameter, whether it sits after another ``key = value`` on the same
    line or on a following line, since its whitespace skip crosses lines
    and ignores blanks and comment-only ones (nls.f90 nls_next_item /
    nls_next_line). Trailing ``!``/``#`` comments are not values, so they
    are cut first.

    Multi-token remainders are treated as arrays conservatively: the
    field goes read-only and the raw line survives; never a partial
    rewrite of station 1 only.
    """
    if name is None or name not in sf.sections:
        return False
    lines = sf.sections[name].raw_lines
    for index, line in enumerate(lines):
        code = StrParser._split_comment(line)[0]
        assignments = list(_ASSIGNMENT.finditer(code))
        for pos, match in enumerate(assignments):
            if match.group(1).lower() != param.lower():
                continue
            end = assignments[pos + 1].start() if pos + 1 < len(assignments) else len(code)
            if len(code[match.end() : end].replace(",", " ").split()) > 1:
                return True
            if pos + 1 < len(assignments):
                return False  # value ends where the next key starts
            return _continues_on_next_line(lines[index + 1 :])
    return False


def _continues_on_next_line(following: list[str]) -> bool:
    """True when the next data line extends the previous value list."""
    for line in following:
        code = StrParser._split_comment(line)[0].strip()
        if not code:
            continue  # blanks and comment-only lines do not end a value list
        return not _ASSIGNMENT.match(code)
    return False


def _assimil_apply(
    sf: StrFile, ivar: int, preferred: int, on: bool, values: dict
) -> tuple[str | None, list[str]]:
    """Write one assimilation block into *sf*; returns (name, errors).

    On any error NOTHING is written and the messages are returned for the
    caller to surface — a rejected value must never be silently replaced
    by the old one, since a saved STR that differs from the panel state
    means a run with parameters the user never saw.

    Disabled: set nobs = 0 only (the core ignores and logs such sections;
    the stored tuning survives for re-enabling). Enabled: write every
    field present in *values*; a field absent from *values* (its input
    was never created — the per-station-array case) keeps its raw STR
    line, which also satisfies the required-field checks. A field present
    but blank was cleared in the UI: required fields error, optional
    tuning becomes an explicit 0 (the core default). File fields are
    stored pre-quoted because _format_value's quoting is applied on
    emit while these values also round-trip through the panel inputs;
    a value whose contents (after stripping one optional surrounding
    quote pair -- the round-trip shape _assimil_block re-renders into
    the input from a prior save) contain a quote or any
    newline/carriage-return is an error, since it could either smuggle
    STR structure (a fake $end/$section) or emit an unbalanced quote.
    """
    name = _assimil_find(sf, ivar)
    if not on:
        if name is not None:
            if _assimil_is_array(sf, name, "nobs"):
                # Writing 0 would overlay the first token only, leaving
                # the rest of the value list behind.
                return name, ["nobs: is a value list in the STR — disable the block there"]
            sf.set_param(name, "nobs", 0)
        return name, []

    new_section = name is None
    target = _assimil_new_name(sf, preferred) if new_section else name
    errors: list[str] = []
    staged: dict[str, object] = {"ivar": ivar}

    for param in _ASSIMIL_NUMERIC_FIELDS:
        if param not in values:
            continue  # input never created -> raw line survives
        raw = "" if values[param] is None else str(values[param]).strip()
        if raw == "":
            if param in _ASSIMIL_OPTIONAL_FIELDS:
                staged[param] = 0 if param in _ASSIMIL_INT_FIELDS else 0.0
            else:
                errors.append(f"{param}: a value is required")
            continue
        try:
            num: float | int = float(raw)
        except (TypeError, ValueError, OverflowError):
            errors.append(f"{param}: {raw!r} is not a valid number")
            continue
        if not math.isfinite(num):
            errors.append(f"{param}: value must be finite")
            continue
        if param in _ASSIMIL_INT_FIELDS:
            if not num.is_integer():
                errors.append(f"{param}: must be a whole number (got {raw})")
                continue
            num = int(num)
        staged[param] = num

    for param in _ASSIMIL_FILE_FIELDS:
        if param not in values:
            if new_section:
                errors.append(f"{param}: an observation file is required")
            continue  # existing raw line survives
        raw = str(values[param] or "").strip()
        if not raw:
            errors.append(
                f"{param}: a file is required while assimilation is enabled "
                "(disable the block to stop assimilating)"
            )
            continue
        inner = raw[1:-1] if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'") else raw
        if any(ch in inner for ch in ("'", '"', "\n", "\r")):
            errors.append(f"{param}: path must not contain quotes or newlines")
            continue
        staged[param] = f"'{inner}'"

    def _effective(param: str) -> float | None:
        """Numeric value the section would end up with, or None."""
        if param in staged:
            return float(staged[param])  # staged values are already numeric
        if not new_section:
            try:
                return float(sf.get_param(target, param))
            except (TypeError, ValueError):
                return None
        return None

    for param in _ASSIMIL_REQUIRED_FIELDS:
        if _effective(param) is None and not any(e.startswith(f"{param}:") for e in errors):
            errors.append(f"{param}: a value is required")

    nobs_eff = _effective("nobs")
    if nobs_eff is not None and nobs_eff < 1:
        errors.append("nobs: must be >= 1 while assimilation is enabled (0 disables the block)")

    mode_eff = _effective("mode") or 0
    tau_eff = _effective("tau") or 0
    if mode_eff == 0 and tau_eff <= 0:
        errors.append(
            "tau: must be > 0 for nudging (mode = 0) — the core error-stops "
            "at the first observation time"
        )

    if errors:
        return (None if new_section else target), errors

    for param, value in staged.items():
        sf.set_param(target, param, value)
    return target, []


def _purge_nduge(sf: StrFile) -> bool:
    """Drop the dead $nduge section the old UI used to write.

    No core code reads it and iostr.f90 hard-stops on unknown sections,
    so any STR carrying it cannot run. generate() skips the stale
    _structure entry once the section is gone. Every occurrence has to
    go: one surviving block still stops the run.
    """
    return sf.remove_sections("nduge")


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


def _assimil_mode_field(prefix: str, raw: object, is_array: bool = False) -> ui.Tag:
    """Application-mode column: the dropdown, or a static note.

    The core accepts only 0 and 1 (assimil_admin.f90) and stops on
    anything else, naming the offending value. Coercing a stored 2 into
    the dropdown would write 0 back and erase the mistake the user needs
    to see — but offering no control at all is worse: validate_str errors
    on the bad value and save_file aborts on any error, so the page could
    not save ANY edit while it sat in the file. An out-of-range scalar is
    therefore offered as its own preselected choice (an untouched save
    writes it back verbatim) alongside the two the core accepts.

    A per-station list or an unparseable value still renders without a
    control: rewriting either would clobber the raw line.
    """
    try:
        stored = 0 if raw is None else int(raw)  # absent -> the core's default
    except (TypeError, ValueError):
        stored = None
        is_array = True  # not a clean scalar -> never rewrite the line
    if is_array or stored is None:
        shown = "per-station values" if raw is None or is_array else f"mode = {raw}"
        return ui.help_text(
            f"Application mode: {shown} is not editable here — the core accepts "
            "only 0 (nudging) or 1 (direct insertion). Edit the file directly."
        )
    choices = {"0": "0 - Nudging", "1": "1 - Direct insertion"}
    if stored not in (0, 1):
        choices = {str(stored): f"{stored} - invalid, the core rejects it", **choices}
    return ui.input_select(
        f"assim_{prefix}_mode",
        "Application mode",
        choices=choices,
        selected=str(stored),
    )


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

    return ui.div(
        ui.h6(f"{title} (ivar {ivar})", class_="text-muted mt-3"),
        ui.input_checkbox(f"assim_{prefix}_on", f"Assimilate {title.lower()}", value=enabled),
        ui.row(
            ui.column(4, num("nobs", "Observation stations", min=1, step=1)),
            ui.column(
                4,
                _assimil_mode_field(
                    prefix, raw("mode"), is_array=_assimil_is_array(sf, name, "mode")
                ),
            ),
            ui.column(4, num("tau", "Timescale tau (s)", min=0, step=60.0)),
        ),
        ui.row(
            ui.column(4, num("corlength", "Correlation length (m)", min=1.0, step=100.0)),
            ui.column(
                4, num("maxlength", "Max influence radius (m, 0 = no cutoff)", min=0, step=100.0)
            ),
            ui.column(4, num("sigobs", "Observation error sigma", min=1e-6, step=0.05)),
        ),
        ui.row(
            ui.column(4, num("sigback", "Background error sigma", min=1e-6, step=0.05)),
            ui.column(4, num("layer", "Observation layer (0 = uniform column)", min=0, step=1)),
            ui.column(
                4, num("vcorlength", "Vertical corr. length (m, 0 = uniform)", min=0, step=0.5)
            ),
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


# Map of input IDs that differ from the STR param name.
# key = input_id used in the UI, value = (section, param_name).
_INPUT_ID_REMAP: dict[str, tuple[str, str]] = {
    "idtcon_out": ("para", "idtcon"),
    "icon_av_out": ("para", "icon_av"),
}
# Add name_ prefixed input IDs for $name section params
for _np in COMMON_PARAMS.get("name", {}):
    _INPUT_ID_REMAP[f"name_{_np}"] = ("name", _np)


_INPUT_ABSENT = object()


def _read_input(inputs, input_id: str, errors: list[str]) -> object:
    """Read one panel input, or _INPUT_ABSENT when it was never rendered.

    SilentException is Shiny's "value not set" signal — raised for every
    input of a panel the user has not opened — and KeyError covers a
    lookup that never resolves; both are normal here and stay silent.
    Anything else is a defect (input-id drift after a rename, module
    namespace bug) that would otherwise turn Save into a silent no-op:
    the panel is edited, the save reports success, the STR never
    changes. Those are logged with a traceback and reported.
    """
    try:
        return inputs[input_id]()
    except (SilentException, KeyError):
        return _INPUT_ABSENT
    except Exception as exc:
        logger.exception("Failed to read panel input %r", input_id)
        errors.append(f"{input_id}: input could not be read ({type(exc).__name__}) — not applied")
        return _INPUT_ABSENT


def _collect_panel_values(inputs, sf: StrFile) -> tuple[list[str], bool]:
    """Read all panel input values and update *sf* before saving.

    Returns (field errors, $nduge purged). On any error the offending
    block was NOT applied and the caller must not report the save as
    successful. The purge is reported rather than announced here: this
    runs on Preview and on the save-abort path too, where nothing is
    written, so only the caller knows whether the removal reached disk.
    """
    errors: list[str] = []

    for panel in PHYSICS_PANELS.values():
        # --- params explicitly listed in the panel definition ---
        for param, section in panel["params"].items():
            _read_input_and_set(inputs, sf, param, section, param, errors)

        # --- params from a dedicated section (sedtr, lagrg, nduge) ---
        dedicated = panel.get("section")
        if dedicated and dedicated in COMMON_PARAMS:
            for param in COMMON_PARAMS[dedicated]:
                if param not in panel["params"]:
                    _read_input_and_set(inputs, sf, param, dedicated, param, errors)

    # --- handle remapped input IDs (duplicates across panels) ---
    for input_id, (section, param) in _INPUT_ID_REMAP.items():
        _read_input_and_set(inputs, sf, input_id, section, param, errors)

    # --- composite param: imetout <- 5 meteo-output checkboxes ---
    # All-or-nothing: imetout is one packed integer, so encoding a
    # partial read would silently zero streams nobody touched.
    flags: dict[str, bool] = {}
    for f in _IMETOUT_FIELDS:
        raw = _read_input(inputs, f"imetout_{f}", errors)
        if raw is _INPUT_ABSENT:
            break  # heat panel not rendered (or a failed read) -> imetout untouched
        flags[f] = bool(raw)
    else:
        sf.set_param("para", "imetout", _imetout_encode(flags))

    # --- composite sections: $assimilN <- T/S assimilation blocks ---
    for prefix, ivar, preferred, label in (
        ("t", 12, 1, "Temperature"),
        ("s", 11, 2, "Salinity"),
    ):
        block_errors: list[str] = []
        on_raw = _read_input(inputs, f"assim_{prefix}_on", block_errors)
        if on_raw is _INPUT_ABSENT:
            errors.extend(block_errors)
            continue  # panel not rendered -> sections untouched
        values: dict[str, object] = {}
        for param in _ASSIMIL_NUMERIC_FIELDS + _ASSIMIL_FILE_FIELDS:
            raw = _read_input(inputs, f"assim_{prefix}_{param}", block_errors)
            if raw is _INPUT_ABSENT:
                continue  # array-note field: input never created
            # A rendered-but-blank input means the user cleared it;
            # pass it through so _assimil_apply can error on required
            # fields instead of silently keeping the old value.
            values[param] = raw if raw is not None else ""
        if block_errors:
            # The panel state is unknown, so applying it would write a
            # half-read block — report and leave the sections alone.
            errors.extend(block_errors)
            continue
        _, errs = _assimil_apply(sf, ivar, preferred, bool(on_raw), values)
        errors.extend(f"{label} assimilation — {e}" for e in errs)

    # --- purge the dead $nduge section on every save: the core
    # hard-stops on it, so an STR carrying it can never run ---
    return errors, _purge_nduge(sf)


def _collect_into_copy(inputs, sf: StrFile) -> tuple[StrFile, list[str], bool]:
    """Apply the panel values to a copy of *sf*; returns it with the collect result.

    Preview writes nothing and an aborted save writes nothing, so neither
    may leave the shared StrFile half-updated — the next successful save
    would persist that partial state without the user ever seeing it.
    """
    working = copy.deepcopy(sf)
    errors, purged = _collect_panel_values(inputs, working)
    return working, errors, purged


def _unwritable_fields(sf: StrFile) -> list[str]:
    """`$section param` for each edited value the STR writer must reject.

    _format_value refuses a value holding both quote characters, since
    the core's reader is delimiter-matched with no escape mechanism. Its
    message names the value but not the field, and the panel has some
    200 of them.
    """
    return [
        f"${name} {param}"
        for name, section in sf.sections.items()
        for param in sorted(section._modified_params)
        if isinstance(section.parameters.get(param), str)
        and "'" in section.parameters[param]
        and '"' in section.parameters[param]
    ]


def _preview_content(sf: StrFile) -> tuple[str | None, str | None]:
    """(STR text, error message) — generation must not escape the caller.

    An unhandled exception inside a reactive effect kills the session,
    and a value the writer rejects is a user-input problem, not a bug.
    """
    try:
        return StrParser.generate(sf), None
    except ValueError as exc:
        logger.exception("Generating the STR preview failed")
        fields = _unwritable_fields(sf)
        where = f" — check {', '.join(fields)}" if fields else ""
        return None, f"Cannot write this STR: {exc}{where}"


def _read_input_and_set(
    inputs,
    sf: StrFile,
    input_id: str,
    section: str,
    param: str,
    errors: list[str],
) -> None:
    """Try reading a single input value and write it into *sf*."""
    raw = _read_input(inputs, input_id, errors)
    if raw is _INPUT_ABSENT or raw is None:
        return

    raw_str = str(raw).strip()
    if not raw_str:
        return

    try:
        if "." in raw_str or "e" in raw_str.lower():
            value: object = float(raw_str)
        else:
            value = int(raw_str)
    except ValueError:
        value = raw_str

    sf.set_param(section, param, value)


@module.ui
def physics_ui() -> ui.Tag:
    """Physics configuration page UI."""
    return ui.div(
        ui.h3("Physics Configuration"),
        ui.p(
            "Configure simulation physics modules. " "Load a .str file, adjust settings, and save.",
            class_="text-muted",
        ),
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Parameter File"),
                ui.output_ui("str_path_picker"),
                ui.div(
                    ui.input_action_button(
                        "load_btn",
                        "Load",
                        class_="btn-outline-primary btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "save_btn",
                        "Save",
                        class_="btn-outline-success btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "preview_btn",
                        "Preview STR",
                        class_="btn-outline-secondary btn-sm",
                    ),
                    class_="mt-2",
                ),
                ui.hr(),
                ui.h5("Active Modules"),
                ui.output_ui("module_badges"),
                ui.hr(),
                ui.h5("Validation"),
                ui.output_ui("validation_status"),
                width=280,
            ),
            ui.output_ui("panels_accordion"),
        ),
    )


@module.server
def physics_server(
    input, output, session, config: Config, active_project=None, current_user=None
) -> None:
    """Physics configuration page server."""

    @render.ui
    def str_path_picker():
        proj = active_project.get() if active_project is not None else None
        usr = current_user() if current_user is not None else None
        return project_file_select(
            "str_path",
            "STR File (.str)",
            (".str",),
            proj=proj,
            user=usr,
            config=config,
            selected=default_project_file(proj, "str"),
        )

    str_data: reactive.Value[StrFile] = reactive.value(StrFile())

    @reactive.effect
    @reactive.event(input.load_btn)
    def load_file():
        # Confine the user-supplied path to the requesting user's sandbox
        # (cross-user .str read IDOR — review H1).
        _usr = current_user() if current_user is not None else None
        try:
            path = config.confine_path(input.str_path(), _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return
        if path.suffix == ".str":
            try:
                parsed = StrParser.parse_file(path)
                str_data.set(parsed)
                ui.notification_show(f"Loaded {path.name}", type="message", duration=3)
            except Exception as e:
                ui.notification_show(f"Parse error: {e}", type="error")
        else:
            ui.notification_show("File not found or not .str", type="warning")

    @reactive.effect
    @reactive.event(input.save_btn)
    def save_file():
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        path_str = input.str_path()
        if not path_str:
            ui.notification_show("No file path specified", type="warning")
            return
        # Reject path traversal: an editor must not write outside the work dir
        # (mirrors simulation._confirm_save). Resolves symlinks + null bytes.
        try:
            path = config.confine_path(path_str, _usr, for_write=True)
        except ValueError as e:
            logger.exception("Invalid save path %r for STR file", path_str)
            ui.notification_show(str(e), type="error", duration=6)
            return
        working: StrFile | None = None
        try:
            working, panel_errors, nduge_purged = _collect_into_copy(input, str_data.get())
            if panel_errors:
                for e in panel_errors:
                    ui.notification_show(e, type="error", duration=8)
                ui.notification_show(
                    "Not saved — fix the reported panel fields first.",
                    type="warning",
                    duration=8,
                )
                return
            # Cross-parameter validation BEFORE the write (mirrors
            # str_editor): error-level findings block the save so an
            # invalid STR never lands on disk; warnings don't.
            msgs = validate_str(working.sections)
            errors = [m for m in msgs if m.level == "error"]
            warnings = [m for m in msgs if m.level == "warning"]
            if errors:
                for m in errors:
                    ui.notification_show(f"Error: {m.message}", type="error", duration=8)
                ui.notification_show(
                    "Not saved — fix the errors first.", type="warning", duration=8
                )
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            StrParser.save(working, path)
            # The panel state is on disk now, so it becomes the shared
            # model (badges and validation follow it). No self-write loop:
            # reactive.event isolates this body, so the .get() above takes
            # no dependency on the value being set here.
            str_data.set(working)
            for m in warnings:
                ui.notification_show(f"Warning: {m.message}", type="warning", duration=6)
            if nduge_purged:
                # Only now is the removal real on disk.
                ui.notification_show(
                    "Removed dead $nduge section (the core rejects it).",
                    type="message",
                    duration=6,
                )
            ui.notification_show(f"Saved to {path}", type="message", duration=3)
        except Exception as e:
            logger.exception("Saving STR file to %s failed", path)
            fields = _unwritable_fields(working) if working is not None else []
            where = f" — check {', '.join(fields)}" if fields else ""
            ui.notification_show(f"Save error: {e}{where}", type="error", duration=10)

    @reactive.effect
    @reactive.event(input.preview_btn)
    def preview_str():
        # Read-only: render the STR that the current panel values would generate,
        # without writing to disk (so no editor permission gate). Mirrors what
        # save_file serializes via StrParser.generate.
        working, panel_errors, _purged = _collect_into_copy(input, str_data.get())
        for e in panel_errors:
            # Rejected assimilation fields were NOT applied: the preview
            # shows the last valid state for those, so say why.
            ui.notification_show(e, type="error", duration=8)
        content, gen_error = _preview_content(working)
        if gen_error is not None:
            ui.notification_show(gen_error, type="error", duration=10)
            return
        ui.modal_show(
            ui.modal(
                ui.tags.pre(
                    content,
                    style="max-height:60vh;overflow:auto;white-space:pre-wrap;"
                    "font-family:var(--bs-font-monospace,monospace);font-size:0.85rem;",
                ),
                title="STR Preview",
                size="l",
                easy_close=True,
                footer=ui.modal_button("Close"),
            )
        )

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
            (
                "Sediment",
                (sf.get_param("para", "issedi", 0) or 0) > 0
                or sf.get_param("sedtr", "isedi", 0) == 1,
                None,
            ),
            ("Lagrangian", "lagrg" in sf.sections, None),
            ("Ice", sf.get_param("para", "icemod", 0) == 1, None),
            ("Waves", (sf.get_param("para", "iwave", 0) or 0) > 0, None),
            ("Assimilation", any(_ASSIMIL_NAME.match(n) for n in sf.get_section_names()), None),
            ("Tracers", (sf.get_param("para", "iconz", 0) or 0) > 0, None),
            ("Wind", (sf.get_param("para", "iwtype", 0) or 0) > 1, None),
            ("WRT", "wrt" in sf.sections, None),
            ("Non-hydro", (sf.get_param("nonhyd", "inohyd", 0) or 0) > 0, None),
        ]
        for label, active, detail in checks:
            if active:
                text = f"{label}: {detail}" if detail else label
                badges.append(ui.span(text, class_="badge bg-primary me-1 mb-1"))
        if not badges:
            return ui.p("No modules active", class_="text-muted small")
        return ui.div(*badges)

    @render.ui
    def validation_status():
        sf = str_data.get()
        msgs = validate_str(sf.sections)
        errors = [m for m in msgs if m.level == "error"]
        warnings = [m for m in msgs if m.level == "warning"]
        infos = [m for m in msgs if m.level == "info"]
        if not msgs:
            return ui.span("All checks passed", class_="badge bg-success")
        parts = []
        if errors:
            parts.append(ui.span(f"{len(errors)} error(s)", class_="badge bg-danger me-1 mb-1"))
            for m in errors:
                parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-x-circle text-danger me-1"),
                        ui.span(m.message, class_="small"),
                        class_="ms-1",
                    )
                )
        if warnings:
            parts.append(
                ui.span(f"{len(warnings)} warning(s)", class_="badge bg-warning me-1 mb-1")
            )
            for m in warnings:
                parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-exclamation-triangle text-warning me-1"),
                        ui.span(m.message, class_="small"),
                        class_="ms-1",
                    )
                )
        if infos:
            for m in infos:
                parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-info-circle text-info me-1"),
                        ui.span(m.message, class_="small text-muted"),
                        class_="ms-1",
                    )
                )
        return ui.div(*parts)

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

    # --- Panel render functions (one per physics module) ---

    @render.ui
    def panel_timing():
        params = build_panel_params(str_data.get(), "timing")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "itanf",
                        "Start time",
                        value=str(params.get("itanf", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "itend",
                        "End time",
                        value=str(params.get("itend", "") or ""),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idt",
                        "Time step (s)",
                        value=str(params.get("idt", "") or ""),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "date",
                        "Reference date (YYYYMMDD)",
                        value=str(params.get("date", "") or ""),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "time",
                        "Reference time (HHMMSS)",
                        value=str(params.get("time", "") or ""),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "tz",
                        "Time zone offset (h)",
                        value=int(params.get("tz", 0) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_hydrodynamics():
        params = build_panel_params(str_data.get(), "hydrodynamics")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ilin",
                        "Advective terms",
                        choices={"0": "0 - Linear", "1": "1 - Nonlinear"},
                        selected=str(params.get("ilin", 1) or 1),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "itlin",
                        "Advection scheme",
                        choices={"0": "0 - Finite Element", "1": "1 - Semi-Lagrangian"},
                        selected=str(params.get("itlin", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "iclin",
                        "Linearize continuity",
                        choices={"0": "0 - Nonlinear", "1": "1 - Linear"},
                        selected=str(params.get("iclin", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "itsplt",
                        "Time step mode",
                        choices={
                            "0": "0 - Constant",
                            "1": "1 - Splitting mode 1",
                            "2": "2 - Splitting mode 2",
                            "3": "3 - Fractional step",
                        },
                        selected=str(params.get("itsplt", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "coumax",
                        "Max Courant number",
                        value=float(params.get("coumax", 1.0) or 1.0),
                        min=0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "idtsyn",
                        "Sync interval (s)",
                        value=int(params.get("idtsyn", 0) or 0),
                        min=0,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "icor",
                        "Coriolis force",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Beta-plane",
                            "2": "2 - F-plane",
                        },
                        selected=str(params.get("icor", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "dlat",
                        "Latitude (deg N)",
                        value=float(params.get("dlat", 100.0) or 100.0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "isphe",
                        "Coordinate system",
                        choices={
                            "-1": "-1 - Auto-detect",
                            "0": "0 - Cartesian",
                            "1": "1 - Spherical",
                        },
                        selected=str(
                            params.get("isphe", -1) if params.get("isphe") is not None else -1
                        ),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "hzmin",
                        "Min water depth (m)",
                        value=float(params.get("hzmin", 0.01) or 0.01),
                        min=0,
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hzoff",
                        "Drying threshold (m)",
                        value=float(params.get("hzoff", 0.05) or 0.05),
                        min=0,
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hzon",
                        "Rewetting threshold (m)",
                        value=float(params.get("hzon", 0.10) or 0.10),
                        min=0,
                        step=0.01,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "rtide",
                        "Tidal forcing",
                        value=float(params.get("rtide", 0) or 0),
                        step=0.1,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_vertical():
        params = build_panel_params(str_data.get(), "vertical")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "dzreg",
                        "Regular layer spacing (m)",
                        value=float(params.get("dzreg", 0) or 0),
                        min=0,
                        step=0.5,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "ilytyp",
                        "Bottom layer treatment",
                        choices={
                            "0": "0 - None",
                            "1": "1 - Delete",
                            "2": "2 - Delete if thin",
                            "3": "3 - Merge",
                        },
                        selected=str(params.get("ilytyp", 3) or 3),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hlvmin",
                        "Min bottom layer fraction",
                        value=float(params.get("hlvmin", 0.25) or 0.25),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "nzadapt",
                        "Moving surface layers (z-star)",
                        choices={"0": "0 - Z-layers only", "1": "1 - Enabled"},
                        selected=str(params.get("nzadapt", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "nsigma",
                        "Number of sigma layers",
                        value=int(params.get("nsigma", 0) or 0),
                        min=0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hsigma",
                        "Sigma-zeta transition depth (m)",
                        value=float(params.get("hsigma", 10000.0) or 10000.0),
                        min=0,
                        step=1.0,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_friction():
        params = build_panel_params(str_data.get(), "friction")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ireib",
                        "Bottom friction type",
                        choices={
                            "0": "0 - None",
                            "1": "1 - Chezy law",
                            "2": "2 - Strickler",
                            "3": "3 - Chezy coeff",
                            "4": "4 - Linear",
                            "5": "5 - Quadratic drag",
                            "6": "6 - Roughness z0",
                            "7": "7 - Strickler+drag",
                            "8": "8 - Sediment z0",
                            "9": "9 - Fluid mud",
                            "10": "10 - Hybrid quad-linear",
                        },
                        selected=str(params.get("ireib", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "czdef",
                        "Friction coefficient",
                        value=float(params.get("czdef", 0) or 0),
                        min=0,
                        step=0.001,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "iczv",
                        "Variable friction flag",
                        value=int(params.get("iczv", 1) or 1),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_turbulence():
        params = build_panel_params(str_data.get(), "turbulence")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "iturb",
                        "Turbulence closure",
                        choices={
                            "0": "0 - None",
                            "1": "1 - GOTM",
                            "2": "2 - k-epsilon",
                            "3": "3 - Munk-Anderson",
                        },
                        selected=str(params.get("iturb", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "difmol",
                        "Molecular diffusivity (m2/s)",
                        value=float(params.get("difmol", 1.0e-6) or 1.0e-6),
                        min=0,
                        step=1e-7,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "vismol",
                        "Molecular viscosity (m2/s)",
                        value=float(params.get("vismol", 1.0e-6) or 1.0e-6),
                        min=0,
                        step=1e-7,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "diftur",
                        "Turbulent diffusivity (m2/s)",
                        value=float(params.get("diftur", 0) or 0),
                        min=0,
                        step=0.001,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "vistur",
                        "Turbulent viscosity (m2/s)",
                        value=float(params.get("vistur", 0) or 0),
                        min=0,
                        step=0.001,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "idhtyp",
                        "Horizontal diffusion type",
                        choices={
                            "0": "0 - Constant",
                            "1": "1 - Area-weighted",
                            "2": "2 - Smagorinsky",
                        },
                        selected=str(params.get("idhtyp", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "ahpar",
                        "Horizontal viscosity (m2/s)",
                        value=float(params.get("ahpar", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "dhpar",
                        "Horizontal diffusion (m2/s)",
                        value=float(params.get("dhpar", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "noslip",
                        "Boundary condition",
                        choices={
                            "0": "0 - Free-slip",
                            "1": "1 - No-slip",
                        },
                        selected=str(params.get("noslip", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "itvd",
                        "Horizontal advection (scalars)",
                        choices={
                            "0": "0 - Upwind",
                            "1": "1 - TVD mode 1",
                            "2": "2 - TVD mode 2",
                        },
                        selected=str(params.get("itvd", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "itvdv",
                        "Vertical advection (scalars)",
                        choices={
                            "0": "0 - Upwind",
                            "1": "1 - TVD",
                        },
                        selected=str(params.get("itvdv", 0) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_heat():
        params = build_panel_params(str_data.get(), "heat")
        # imetout is a composite param (not in the panel registry), so read it
        # straight from the StrFile — build_panel_params would always return 0.
        _met = _imetout_decode(str_data.get().get_param("para", "imetout"))
        return ui.div(
            ui.row(
                ui.column(
                    12,
                    ui.tags.label("Meteo output (imetout)", class_="fw-semibold"),
                ),
            ),
            ui.row(
                ui.column(
                    2,
                    ui.input_checkbox("imetout_wind", "Wind", value=_met["wind"]),
                ),
                ui.column(
                    2,
                    ui.input_checkbox("imetout_heat", "Heat", value=_met["heat"]),
                ),
                ui.column(
                    2,
                    ui.input_checkbox("imetout_rain", "Rain", value=_met["rain"]),
                ),
                ui.column(
                    2,
                    ui.input_checkbox("imetout_ice", "Ice", value=_met["ice"]),
                ),
                ui.column(
                    4,
                    ui.input_checkbox("imetout_hflx", "Heat fluxes", value=_met["hflx"]),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "iheat",
                        "Heat flux algorithm",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - AREG",
                            "2": "2 - POM bulk",
                            "3": "3 - Gill",
                            "4": "4 - Dejak",
                            "5": "5 - GOTM",
                            "6": "6 - COARE 3.0",
                            "7": "7 - Read from file",
                            "8": "8 - MFS bulk",
                        },
                        selected=str(params.get("iheat", 1) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "ihtype",
                        "Water vapor input type",
                        choices={
                            "1": "1 - Relative humidity (%)",
                            "2": "2 - Wet-bulb temperature",
                            "3": "3 - Dew-point temperature",
                            "4": "4 - Specific humidity",
                        },
                        selected=str(params.get("ihtype", 1) or 1),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hdecay",
                        "Radiation penetration depth (m)",
                        value=float(params.get("hdecay", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "albedo",
                        "Surface albedo",
                        value=float(params.get("albedo", 0.06) or 0.06),
                        min=0,
                        max=1,
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "ievap",
                        "Evaporation mass flux",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("ievap", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "irain",
                        "Precipitation mass flux",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("irain", 1) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_temperature_salinity():
        params = build_panel_params(str_data.get(), "temperature_salinity")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ibarcl",
                        "Baroclinic mode",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Diagnostic",
                            "2": "2 - T/S diagnostic",
                            "3": "3 - Prognostic",
                            "4": "4 - Nudging",
                            "5": "5 - Assimilation",
                        },
                        selected=str(params.get("ibarcl", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "itemp",
                        "Compute temperature",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("itemp", 1) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "isalt",
                        "Compute salinity",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("isalt", 1) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "temref",
                        "Reference temperature (C)",
                        value=float(params.get("temref", 0) or 0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "salref",
                        "Reference salinity (PSU)",
                        value=float(params.get("salref", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "thpar",
                        "Temp horiz. diffusion",
                        value=float(
                            params.get("thpar", -1) if params.get("thpar") is not None else -1
                        ),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "shpar",
                        "Salt horiz. diffusion",
                        value=float(
                            params.get("shpar", -1) if params.get("shpar") is not None else -1
                        ),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "icon_av",
                        "Scalar output averaging",
                        choices={
                            "0": "0 - Instantaneous",
                            "1": "1 - Time-averaged",
                            "2": "2 - Vert+time-averaged",
                        },
                        selected=str(params.get("icon_av", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtcon",
                        "Scalar output interval",
                        value=str(params.get("idtcon", "0") or "0"),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_ecology():
        params = build_panel_params(str_data.get(), "ecology")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ibio",
                        "Biological module",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - WEUTRO",
                            "2": "2 - AQUABC",
                        },
                        selected=str(params.get("ibio", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "imerc",
                        "Mercury contamination",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("imerc", 0) or 0),
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("BFM Biogeochemical Model", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ibfm",
                        "BFM model",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("ibfm", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "ibtanf",
                        "BFM start time",
                        value=str(params.get("ibtanf", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "ibtend",
                        "BFM end time",
                        value=str(params.get("ibtend", "0") or "0"),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "itmbfm",
                        "BFM output start time",
                        value=str(
                            params.get("itmbfm", "-1") if params.get("itmbfm") is not None else "-1"
                        ),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtbfm",
                        "BFM output interval (s)",
                        value=str(params.get("idtbfm", "0") or "0"),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_sediment():
        params = build_panel_params(str_data.get(), "sediment")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "issedi",
                        "Sediment module (para)",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("issedi", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "isedi",
                        "Full sediment transport",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("isedi", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "sedgrs",
                        "Grain sizes (mm, space-sep)",
                        value=str(params.get("sedgrs", "") or ""),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "percin",
                        "Grain size fractions",
                        value=str(params.get("percin", "") or ""),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "tauin",
                        "Critical erosion stress (Pa)",
                        value=str(params.get("tauin", "") or ""),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "sedref",
                        "Ref sediment conc (kg/m3)",
                        value=float(params.get("sedref", 0) or 0),
                        min=0,
                        step=0.001,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "sedhpar",
                        "Sediment horiz. diffusion (m2/s)",
                        value=float(params.get("sedhpar", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "adjtime",
                        "Morphology equil. time (s)",
                        value=float(
                            params.get("adjtime", -1) if params.get("adjtime") is not None else -1
                        ),
                        step=1.0,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtsed",
                        "Sediment output interval",
                        value=str(params.get("idtsed", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "itmsed",
                        "Sediment output start time",
                        value=str(
                            params.get("itmsed", "-1") if params.get("itmsed") is not None else "-1"
                        ),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_lagrangian():
        params = build_panel_params(str_data.get(), "lagrangian")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ilagr",
                        "Lagrangian mode",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Surface",
                            "2": "2 - 2D",
                            "3": "3 - 3D",
                        },
                        selected=str(params.get("ilagr", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "nbdy",
                        "Particles per release",
                        value=int(params.get("nbdy", 0) or 0),
                        min=0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "nbdymax",
                        "Max particles",
                        value=int(
                            params.get("nbdymax", -1) if params.get("nbdymax") is not None else -1
                        ),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "rwhpar",
                        "Horiz. diffusion (m2/s)",
                        value=float(params.get("rwhpar", 0) or 0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "idtl",
                        "Release interval (s)",
                        value=int(params.get("idtl", 0) or 0),
                        min=0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "ipvert",
                        "Vertical distribution",
                        value=int(params.get("ipvert", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "lbeach",
                        "Beaching probability",
                        value=float(params.get("lbeach", 0) or 0),
                        min=0,
                        max=1,
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "ldecay",
                        "Decay time (s)",
                        value=float(params.get("ldecay", 0) or 0),
                        min=0,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "ioil",
                        "Oil spill simulation",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("ioil", 0) or 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ilarv",
                        "Larval behavior",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("ilarv", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "stkpar",
                        "Stokes drift calibration",
                        value=float(params.get("stkpar", 0) or 0),
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "dripar",
                        "Drifter inertia multiplier",
                        value=float(params.get("dripar", 1.0) or 1.0),
                        min=0,
                        step=0.1,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "idtlgr",
                        "Lagrangian output interval (s)",
                        value=int(params.get("idtlgr", 0) or 0),
                        min=0,
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("Connectivity Analysis", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "icnn",
                        "Connectivity stations",
                        value=int(params.get("icnn", 0) or 0),
                        min=0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "radcnn",
                        "Release radius (m)",
                        value=float(params.get("radcnn", 0) or 0),
                        min=0,
                        step=10.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "ppscnn",
                        "Particles/s/station",
                        value=float(params.get("ppscnn", 0) or 0),
                        min=0,
                        step=0.1,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "pldcnn",
                        "Pelagic larval duration (days)",
                        value=float(params.get("pldcnn", 0) or 0),
                        min=0,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "idtcnn",
                        "Connectivity output interval (s)",
                        value=int(params.get("idtcnn", 0) or 0),
                        min=0,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_ice():
        params = build_panel_params(str_data.get(), "ice")
        return ui.div(
            ui.row(
                ui.column(
                    6,
                    ui.input_select(
                        "icemod",
                        "Ice model",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("icemod", 0) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_waves():
        params = build_panel_params(str_data.get(), "waves")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "iwave",
                        "Wave coupling mode",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Constant file",
                            "2": "2 - WWMIII rad + SHYFEM wind",
                            "3": "3 - WWMIII vort + SHYFEM wind",
                            "4": "4 - WWMIII rad + WWM wind",
                            "5": "5 - WWMIII vort + WWM wind",
                        },
                        selected=str(params.get("iwave", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "dtwave",
                        "Coupling time step (s)",
                        value=float(params.get("dtwave", 0) or 0),
                        min=0,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "itdrag",
                        "Drag calculation type",
                        value=int(params.get("itdrag", 0) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_assimilation():
        sf = str_data.get()
        adopted = {_assimil_find(sf, 12), _assimil_find(sf, 11)}
        others, invalid = _assimil_other_sections(sf, adopted)
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
        if invalid:
            children.append(
                ui.div(
                    ", ".join(f"${n}" for n in invalid)
                    + ": the core rejects an assimilation section without a positive "
                    "number — renumber it ($assimil1, $assimil2, …) in the STR.",
                    class_="text-danger small",
                )
            )
        children.append(_assimil_block(sf, "Temperature", "t", 12))
        children.append(_assimil_block(sf, "Salinity", "s", 11))
        return ui.div(*children)

    @render.ui
    def panel_output():
        params = build_panel_params(str_data.get(), "output")
        return ui.div(
            ui.h6("Output Intervals", class_="text-muted mt-1"),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtout",
                        "Hydrodynamic output",
                        value=str(params.get("idtout", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtext",
                        "Extra point time series",
                        value=str(params.get("idtext", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtcon_out",
                        "Scalar/concentration",
                        value=str(params.get("idtcon", "0") or "0"),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtflx",
                        "Flux/discharge",
                        value=str(params.get("idtflx", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtres",
                        "Residual data",
                        value=str(params.get("idtres", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtrms",
                        "RMS velocity",
                        value=str(params.get("idtrms", "0") or "0"),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtvol",
                        "Volume monitoring",
                        value=str(params.get("idtvol", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtmet",
                        "Meteo variables",
                        value=str(params.get("idtmet", "0") or "0"),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "idtstb",
                        "Stability index",
                        value=str(params.get("idtstb", "0") or "0"),
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("Format & Averaging", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "netcdf",
                        "Output format",
                        choices={"0": "0 - Fortran", "1": "1 - NetCDF"},
                        selected=str(params.get("netcdf", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "iout_av",
                        "Hydro output averaging",
                        choices={
                            "0": "0 - Instantaneous",
                            "1": "1 - Time-averaged",
                        },
                        selected=str(params.get("iout_av", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "icon_av_out",
                        "Scalar output averaging",
                        choices={
                            "0": "0 - Instantaneous",
                            "1": "1 - Time-averaged",
                            "2": "2 - Vert+time-averaged",
                        },
                        selected=str(params.get("icon_av", 0) or 0),
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("Restart", class_="text-muted"),
            ui.row(
                ui.column(
                    3,
                    ui.input_text(
                        "idtrst",
                        "Restart file interval (s)",
                        value=str(params.get("idtrst", "0") or "0"),
                    ),
                ),
                ui.column(
                    3,
                    ui.input_text(
                        "itrst",
                        "Restart write interval",
                        value=str(params.get("itrst", "0") or "0"),
                    ),
                ),
                ui.column(
                    3,
                    ui.input_text(
                        "itmrst",
                        "Restart output start time",
                        value=str(
                            params.get("itmrst", "-1") if params.get("itmrst") is not None else "-1"
                        ),
                    ),
                ),
                ui.column(
                    3,
                    ui.input_select(
                        "ityrst",
                        "Restart mode",
                        choices={
                            "0": "0 - Strict match",
                            "1": "1 - Cold-start if missing",
                            "2": "2 - Closest time",
                        },
                        selected=str(params.get("ityrst", 1) or 0),
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("Offline Mode", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "idtoff",
                        "Offline mode",
                        choices={
                            "0": "0 - Off",
                            "1": "1 - Write hydro",
                            "-1": "-1 - Read hydro",
                            "-2": "-2 - Read T/S",
                            "-4": "-4 - Read turbulence",
                            "-3": "-3 - Read hydro+T/S",
                            "-7": "-7 - Read all",
                        },
                        selected=str(
                            params.get("idtoff", 0) if params.get("idtoff") is not None else 0
                        ),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "itmoff",
                        "Offline start time",
                        value=str(
                            params.get("itmoff", "-1") if params.get("itmoff") is not None else "-1"
                        ),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_tracers():
        params = build_panel_params(str_data.get(), "tracers")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "iconz",
                        "Number of tracers",
                        choices={str(i): str(i) for i in range(6)},
                        selected=str(params.get("iconz", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "iage",
                        "Water age tracer",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("iage", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "idecay",
                        "Tracer decay type",
                        choices={
                            "0": "0 - None",
                            "1": "1 - Exponential",
                            "2": "2 - Chapra",
                        },
                        selected=str(params.get("idecay", 0) or 0),
                    ),
                ),
            ),
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
                    _rate_field(
                        "beachrate",
                        "Beaching rate (mode 3)",
                        params.get("beachrate", 0),
                    ),
                ),
                ui.column(
                    4,
                    _rate_field(
                        "burryrate",
                        "Burial rate (mode 3)",
                        params.get("burryrate", 0),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "conref",
                        "Reference concentration",
                        value=float(params.get("conref", 0) or 0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "chpar",
                        "Horiz. diffusion (m2/s)",
                        value=float(
                            params.get("chpar", -1) if params.get("chpar") is not None else -1
                        ),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "wsettl",
                        "Settling velocity (m/s)",
                        value=float(params.get("wsettl", 0) or 0),
                        min=0,
                        step=0.001,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_wind():
        params = build_panel_params(str_data.get(), "wind")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "iwtype",
                        "Wind input type",
                        choices={
                            "1": "1 - Constant",
                            "2": "2 - Variable (file)",
                            "3": "3 - Wind field",
                            "4": "4 - Spatially varying",
                            "5": "5 - Coupled model",
                        },
                        selected=str(params.get("iwtype", 1) or 1),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "dragco",
                        "Drag coefficient",
                        value=float(params.get("dragco", 2.5e-3) or 2.5e-3),
                        min=0,
                        step=0.0001,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "wsmax",
                        "Max wind speed (m/s)",
                        value=float(params.get("wsmax", 50) or 50),
                        min=0,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "rfact",
                        "Wind stress scaling factor",
                        value=float(params.get("rfact", 1.0) or 1.0),
                        min=0,
                        step=0.01,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_input_files():
        params = build_panel_params(str_data.get(), "input_files")
        groups = {
            "Forcing": ["wind", "rain", "qflux", "ice"],
            "Initial Conditions": ["zinit", "tempin", "saltin", "conzin"],
            "Restart": ["restrt"],
            "Observations": ["tempobs", "saltobs"],
            "Turbulence": ["gotmpa"],
            "System": ["basnam"],
            "Ecology": ["bioin", "biosin", "biocon", "biolight", "mercin", "bfmini"],
            "Sediment": ["sedp", "sedt", "sedcon"],
            "Lagrangian / Nudging": ["lgrlin", "lgrtrj", "statcnn", "surfvel"],
            "Boundary Conditions": ["saltn", "tempn", "conzn"],
        }
        name_meta = COMMON_PARAMS.get("name", {})
        elements = []
        for group_label, keys in groups.items():
            elements.append(ui.hr())
            elements.append(ui.h6(group_label, class_="text-muted"))
            row_cols = []
            for k in keys:
                info = name_meta.get(k)
                label = info[0] if info else k
                row_cols.append(
                    ui.column(
                        4,
                        ui.input_text(
                            f"name_{k}",
                            label,
                            value=str(params.get(k, "") or ""),
                        ),
                    )
                )
                if len(row_cols) == 3:
                    elements.append(ui.row(*row_cols))
                    row_cols = []
            if row_cols:
                elements.append(ui.row(*row_cols))
        return ui.div(*elements)

    @render.ui
    def panel_advanced_hydro():
        params = build_panel_params(str_data.get(), "advanced_hydro")
        return ui.div(
            ui.h6("Semi-Implicit Weights", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "azpar",
                        "Transport weighting",
                        value=float(params.get("azpar", 0.5) or 0.5),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "ampar",
                        "Pressure weighting",
                        value=float(params.get("ampar", 0.5) or 0.5),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "afpar",
                        "Coriolis weighting",
                        value=float(params.get("afpar", 0.5) or 0.5),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "atpar",
                        "Vert. viscosity weighting",
                        value=float(params.get("atpar", 1.0) or 1.0),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "adpar",
                        "Vert. diffusion weighting",
                        value=float(params.get("adpar", 1.0) or 1.0),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "aapar",
                        "Vert. advection weighting",
                        value=float(params.get("aapar", 1.0) or 1.0),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
            ),
            ui.hr(),
            ui.h6("Depth & Density", class_="text-muted"),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "href",
                        "Reference depth correction (m)",
                        value=float(params.get("href", 0) or 0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hmin",
                        "Minimum basin depth (m)",
                        value=float(
                            params.get("hmin", -99999) if params.get("hmin") is not None else -99999
                        ),
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "hmax",
                        "Maximum basin depth (m)",
                        value=float(
                            params.get("hmax", 99999) if params.get("hmax") is not None else 99999
                        ),
                        step=1.0,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "rlin",
                        "Non-linear term strength",
                        value=float(params.get("rlin", 1.0) or 0),
                        min=0,
                        max=1,
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "rowass",
                        "Water density (kg/m3)",
                        value=float(params.get("rowass", 1025.0) or 1025.0),
                        min=0,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "roluft",
                        "Air density (kg/m3)",
                        value=float(params.get("roluft", 1.225) or 1.225),
                        min=0,
                        step=0.001,
                    ),
                ),
            ),
        )

    @render.ui
    def panel_renewal_time():
        params = build_panel_params(str_data.get(), "renewal_time")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_text(
                        "idtwrt",
                        "Reset interval (s)",
                        value=str(
                            params.get("idtwrt", "-1") if params.get("idtwrt") is not None else "-1"
                        ),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "c0",
                        "Initial tracer concentration",
                        value=float(params.get("c0", 1.0) or 1.0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "iaout",
                        "Outside area code",
                        value=int(
                            params.get("iaout", -1) if params.get("iaout") is not None else -1
                        ),
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "percmin",
                        "Completion threshold (%)",
                        value=float(params.get("percmin", 0) or 0),
                        min=0,
                        max=100,
                        step=1.0,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "iret",
                        "Return flow",
                        choices={"0": "0 - Explicit zero", "1": "1 - Return"},
                        selected=str(params.get("iret", 1) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_nonhydrostatic():
        params = build_panel_params(str_data.get(), "nonhydrostatic")
        return ui.div(
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "inohyd",
                        "Non-hydrostatic mode",
                        choices={
                            "0": "0 - Hydrostatic",
                            "1": "1 - Non-hydrostatic",
                        },
                        selected=str(params.get("inohyd", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "aqpar",
                        "Implicit parameter",
                        value=float(params.get("aqpar", 0.5) or 0.5),
                        min=0,
                        max=1,
                        step=0.05,
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "islope",
                        "Poisson grid type",
                        value=int(params.get("islope", 0) or 0),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "ivwadv",
                        "Vert. advection of vert. momentum",
                        choices={"0": "0 - Off", "1": "1 - On"},
                        selected=str(params.get("ivwadv", 0) or 0),
                    ),
                ),
            ),
        )

    @render.ui
    def panel_boundary():
        params = build_panel_params(str_data.get(), "boundary")
        return ui.div(
            ui.p(
                "Boundary conditions are typically defined per-boundary in "
                "$bound1, $bound2, etc. The defaults below apply to all boundaries.",
                class_="text-muted small",
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_select(
                        "ibtyp",
                        "Boundary type",
                        choices={
                            "1": "1 - Water level",
                            "2": "2 - Discharge",
                            "3": "3 - Volume inlet",
                            "4": "4 - Momentum",
                            "5": "5 - Fixed scalar",
                            "31": "31 - Radiation / zero-gradient",
                        },
                        selected=str(params.get("ibtyp", 1) or 1),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_select(
                        "intpol",
                        "Interpolation",
                        choices={"1": "1 - Linear", "2": "2 - Spline"},
                        selected=str(params.get("intpol", 1) or 1),
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "boundn",
                        "Boundary file",
                        value=str(params.get("boundn", "") or ""),
                        placeholder="timeseries.dat",
                    ),
                ),
            ),
            ui.row(
                ui.column(
                    4,
                    ui.input_numeric(
                        "zfact",
                        "Scaling factor",
                        value=float(params.get("zfact", 1.0) or 1.0),
                        step=0.1,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_numeric(
                        "ztilt",
                        "Water level tilt (m)",
                        value=float(params.get("ztilt", 0.0) or 0.0),
                        step=0.01,
                    ),
                ),
                ui.column(
                    4,
                    ui.input_text(
                        "kbound",
                        "Boundary nodes",
                        value=str(params.get("kbound", "") or ""),
                        placeholder="Node numbers",
                    ),
                ),
            ),
        )
