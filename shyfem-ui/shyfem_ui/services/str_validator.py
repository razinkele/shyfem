"""Cross-parameter validation for SHYFEM STR files.

Checks Fortran parameter interdependencies and reports
errors (missing required params) and warnings (likely misconfigurations).
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    message: str
    param: str = ""


_ASSIMIL_NUM = re.compile(r"^assimil(\d+)$")

# nls.f90:398 error-stops on any STR line with len_trim(line) > 80.
_STR_LINE_MAX = 80
# parser_str._generate_section writes a param as `        key = value`.
_EMIT_INDENT = len("        ")


def _normalize_sections(sections: dict) -> tuple[dict, set]:
    """Accept both plain nested dicts and StrFile.sections.

    Page call sites pass StrFile.sections (name -> StrSection dataclass);
    the validator's own tests pass plain {name: {param: value}} dicts.
    Returns (params_by_section, names_of_sections_with_any_content) — the
    second set is needed because a parsed section can be non-empty while
    holding only raw lines (e.g. $levels depths carry no key=value pairs).
    """
    params: dict = {}
    present: set = set()
    for name, sec in sections.items():
        if hasattr(sec, "parameters"):
            params[name] = sec.parameters
            if sec.parameters or getattr(sec, "raw_lines", None):
                present.add(name)
        else:
            params[name] = sec or {}
            if sec:
                present.add(name)
    return params, present


def _num(sections: dict, section: str, param: str, default: Any = None) -> Any:
    """_get restricted to numeric results.

    idt*/interval params legitimately hold duration strings ('1h', '30m')
    that _get cannot convert; a `> 0` comparison on one raises TypeError,
    which would crash the whole validator. Non-numeric values fall back
    to *default* — the rules using this helper are numeric sanity checks,
    not format checks.
    """
    val = _get(sections, section, param, default)
    return val if isinstance(val, (int, float)) else default


def _get(sections: dict, section: str, param: str, default: Any = None) -> Any:
    """Get param value from nested section dict."""
    sec = sections.get(section, {})
    val = sec.get(param, default)
    if val is None:
        return default
    if isinstance(val, str):
        # STR values are often quoted (apply_quick_settings writes e.g. "'0'");
        # strip surrounding matching quotes so numeric sanity checks still apply.
        s = val.strip()
        if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
            s = s[1:-1]
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
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
    raw_sections = sections  # keeps raw_lines, which the line-length rule measures
    sections, present = _normalize_sections(sections)
    para = sections.get("para", {})

    # --- Required timing params ---
    if "itend" not in para or para["itend"] is None:
        msgs.append(ValidationMessage("error", "itend (end time) is required", "itend"))
    if "idt" not in para or para["idt"] is None:
        msgs.append(ValidationMessage("error", "idt (time step) is required", "idt"))

    # --- Timing sanity checks ---
    idt = _get(sections, "para", "idt")
    if idt is not None and isinstance(idt, (int, float)) and idt <= 0:
        msgs.append(ValidationMessage("error", "idt (time step) must be > 0", "idt"))
    itanf = _get(sections, "para", "itanf", 0)
    itend = _get(sections, "para", "itend")
    if itend is not None and itanf is not None:
        if isinstance(itend, (int, float)) and isinstance(itanf, (int, float)):
            if itend <= itanf:
                msgs.append(
                    ValidationMessage(
                        "error",
                        "itend must be greater than itanf",
                        "itend",
                    )
                )

    # --- Dependency: iturb=1 (GOTM) needs gotmpa file ---
    iturb = _get(sections, "para", "iturb", 0)
    if iturb == 1:
        gotmpa = _get(sections, "name", "gotmpa")
        if not gotmpa:
            msgs.append(
                ValidationMessage(
                    "warning",
                    "iturb=1 (GOTM) typically requires gotmpa file in $name section",
                    "iturb",
                )
            )

    # --- Dependency: ibarcl>0 needs itemp or isalt ---
    ibarcl = _get(sections, "para", "ibarcl", 0)
    if ibarcl in (1, 3):
        itemp = _get(sections, "para", "itemp", 1)
        isalt = _get(sections, "para", "isalt", 1)
        if itemp == 0 and isalt == 0:
            msgs.append(
                ValidationMessage(
                    "warning",
                    f"ibarcl={ibarcl} (baroclinic) but both itemp=0 and isalt=0 — no T/S computed",
                    "ibarcl",
                )
            )

    # --- Dependency: iheat>0 needs ibarcl>0 ---
    iheat = _num(sections, "para", "iheat", 0)
    if iheat > 0 and ibarcl == 0:
        msgs.append(
            ValidationMessage(
                "warning",
                f"iheat={iheat} active but ibarcl=0 — heat flux has no effect without baroclinic mode",
                "iheat",
            )
        )

    # --- Dependency: issedi=1 needs $sedtr section ---
    issedi = _get(sections, "para", "issedi", 0)
    if issedi == 1:
        isedi = _get(sections, "sedtr", "isedi", 0)
        if "sedtr" not in present or isedi == 0:
            msgs.append(
                ValidationMessage(
                    "warning",
                    "issedi=1 in $para but $sedtr section missing or isedi=0",
                    "issedi",
                )
            )

    # --- Dependency: ilagr>0 needs $lagrg section ---
    ilagr = _num(sections, "para", "ilagr")
    if ilagr is None:
        ilagr = _num(sections, "lagrg", "ilagr", 0)
    if ilagr and ilagr > 0:
        if "lagrg" not in present:
            msgs.append(
                ValidationMessage(
                    "warning",
                    f"ilagr={ilagr} active but $lagrg section missing",
                    "ilagr",
                )
            )

    # --- Dependency: iturb valid range (turbulence.f90:105-114) ---
    if iturb is not None and isinstance(iturb, int) and iturb not in (0, 1, 2, 3):
        msgs.append(
            ValidationMessage(
                "error",
                f"iturb={iturb} is invalid — must be 0 (off), 1 (GOTM), 2 (k-epsilon), or 3 (Munk-Anderson)",
                "iturb",
            )
        )

    # --- Dependency: ibarcl valid range (baroclinic.f90:307-312) ---
    if ibarcl is not None and isinstance(ibarcl, int) and ibarcl not in (0, 1, 2, 3, 4, 5):
        msgs.append(
            ValidationMessage(
                "error",
                f"ibarcl={ibarcl} is invalid — must be 0-5",
                "ibarcl",
            )
        )

    # --- Dependency: iwave valid range (waves_admin.f90:1227-1229) ---
    iwave = _num(sections, "para", "iwave", 0)
    if iwave is not None and isinstance(iwave, int) and iwave not in (0, 1, 2, 3, 4, 5):
        msgs.append(
            ValidationMessage(
                "error",
                f"iwave={iwave} is invalid — must be 0 (off), 1-5 (coupling modes)",
                "iwave",
            )
        )

    # --- Dependency: itdrag=3 requires iwave>=2 (waves_admin.f90:190-193) ---
    itdrag = _get(sections, "para", "itdrag", 0)
    if itdrag == 3 and (iwave is None or iwave < 2):
        msgs.append(
            ValidationMessage(
                "error",
                "itdrag=3 (wave-coupled drag) requires iwave>=2 (WWMIII coupling)",
                "itdrag",
            )
        )

    # --- Dependency: iconz>0 but no conzin or boundary file ---
    iconz = _num(sections, "para", "iconz", 0)
    if iconz and iconz > 0:
        conzin = _get(sections, "name", "conzin")
        conzn = _get(sections, "name", "conzn")
        conref = _get(sections, "para", "conref", 0)
        if not conzin and not conzn and (conref is None or conref == 0):
            msgs.append(
                ValidationMessage(
                    "info",
                    f"iconz={iconz} active but no conzin, conzn file, or conref set — tracers start at zero",
                    "iconz",
                )
            )

    # --- Level system consistency (initialize.f90:476-555) ---
    has_levels = "levels" in present
    nsigma = _num(sections, "para", "nsigma", 0) or 0
    dzreg = _num(sections, "para", "dzreg", 0) or 0
    hsigma = _num(sections, "para", "hsigma", 0) or 0

    if has_levels and dzreg > 0:
        msgs.append(
            ValidationMessage(
                "error",
                "Cannot set dzreg>0 when explicit $levels section is present",
                "dzreg",
            )
        )
    if has_levels and nsigma > 0:
        # Sigma + explicit levels only valid as hybrid (needs hsigma)
        if hsigma <= 0:
            msgs.append(
                ValidationMessage(
                    "error",
                    "nsigma>0 with $levels requires hsigma>0 for hybrid coordinates",
                    "hsigma",
                )
            )
    if nsigma > 0 and dzreg > 0 and hsigma <= 0:
        msgs.append(
            ValidationMessage(
                "error",
                "Hybrid levels (nsigma>0, dzreg>0) requires hsigma>0",
                "hsigma",
            )
        )

    # --- GOTM turbulence without T/S is ineffective ---
    itemp = _get(sections, "para", "itemp", 1)
    isalt = _get(sections, "para", "isalt", 1)
    if iturb == 1 and itemp == 0 and isalt == 0:
        msgs.append(
            ValidationMessage(
                "warning",
                "iturb=1 (GOTM) with itemp=0 and isalt=0 — turbulence model has no T/S gradients",
                "iturb",
            )
        )

    # --- Physical constants sanity (common misconfiguration) ---
    rowass = _get(sections, "para", "rowass")
    if rowass is not None and isinstance(rowass, (int, float)):
        if rowass < 990 or rowass > 1040:
            msgs.append(
                ValidationMessage(
                    "warning",
                    f"rowass={rowass} outside typical range [990-1040 kg/m³]",
                    "rowass",
                )
            )

    roluft = _get(sections, "para", "roluft")
    if roluft is not None and isinstance(roluft, (int, float)):
        if roluft < 0.9 or roluft > 1.4:
            msgs.append(
                ValidationMessage(
                    "warning",
                    f"roluft={roluft} outside typical air density range [0.9-1.4 kg/m³]",
                    "roluft",
                )
            )

    # --- Output interval without active module ---
    # _num: idtcon commonly holds a duration string ('1h'); treat that as
    # "set but not numerically comparable" and skip this info-level rule.
    idtcon = _num(sections, "para", "idtcon", 0)
    if idtcon and idtcon > 0 and iconz == 0 and ibarcl == 0:
        msgs.append(
            ValidationMessage(
                "info",
                "idtcon>0 but no scalars active (iconz=0, ibarcl=0) — output will be empty",
                "idtcon",
            )
        )

    # --- Data assimilation sections (assimil_admin.f90 / assimil.f90) ---
    msgs.extend(_validate_assimil(sections, ibarcl, itemp, isalt))

    # --- Fortran reader's hard 80-char line cap (nls.f90:398) ---
    msgs.extend(_validate_line_length(raw_sections))

    return msgs


def _line_length_for(param: str, value: str, raw_lines: list, modified: set) -> int:
    """Length of the line ``param`` will occupy once written.

    Mirrors _generate_section: an existing param is rebuilt in place
    inside its raw line, and only a param with no raw line of its own is
    appended using the generator's own indent.
    """
    for line in raw_lines:
        span = _assignment_span(param, line)
        if span is None:
            continue
        if param not in modified:
            return len(line)
        start, end = span
        return len(line) - (end - start) + _assignment_length(param, value)
    return _emitted_length(param, value)


def _assignment_span(param: str, line: str) -> tuple[int, int] | None:
    """Span of ``param``'s `key = value` assignment in *line*, if present."""
    m = re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(param)}\s*=\s*('[^']*'|\"[^\"]*\"|\S+)",
        line,
    )
    return (m.start(), m.end()) if m else None


def _assignment_length(param: str, value: str) -> int:
    """Length of the `param = value` text the editor would write.

    Mirrors parser_str._format_value's quoting instead of importing it:
    that function raises on some inputs, and an exception escaping
    validate_str turns validation into an app-wide no-op. A character
    value is wrapped in quotes unless it already carries a matching
    pair; a file path never matches _format_value's bare-numeric
    passthrough, so that branch cannot apply here.
    """
    already_quoted = len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]
    return len(param) + len(" = ") + len(value) + (0 if already_quoted else 2)


def _emitted_length(param: str, value: str) -> int:
    """Length of a freshly appended line, at the generator's own indent."""
    return _EMIT_INDENT + _assignment_length(param, value)


def _validate_line_length(sections: dict) -> list[ValidationMessage]:
    """Flag character values (file paths) that make the STR fatal to read.

    The core hard-stops on any line over 80 chars, so a long
    filecoords/fileobs/wind path saved by the editor kills the run at
    STR read time with a message that names no parameter.

    Only character values are measured: numbers cannot approach the cap,
    and `_`-prefixed keys ($extra/$title standalone entries) hold lists
    that _generate_section emits in its own format.

    A param that already exists in the file is emitted inside its own raw
    line, so that line is measured directly (verbatim when the param is
    unmodified, otherwise with the assignment span swapped) — assuming
    the generator's 8-space indent instead would cry wolf on the 1- and
    7-space indents used throughout the existing STR corpus, blocking
    saves and job submission for files that are perfectly legal.
    """
    msgs: list[ValidationMessage] = []
    for name, sec in sections.items():
        params = getattr(sec, "parameters", sec) or {}
        raw_lines = getattr(sec, "raw_lines", None) or []
        modified = getattr(sec, "_modified_params", None) or set()
        for param, value in params.items():
            if param.startswith("_") or not isinstance(value, str):
                continue
            length = _line_length_for(param, value, raw_lines, modified)
            if length > _STR_LINE_MAX:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"{param} in ${name} needs a {length}-character line — the core "
                        f"error-stops on any STR line longer than {_STR_LINE_MAX} chars; "
                        "shorten the path or move the file closer to the run directory",
                        param,
                    )
                )
    return msgs


def _validate_assimil(
    sections: dict, ibarcl: Any, itemp: Any, isalt: Any
) -> list[ValidationMessage]:
    """Rules for numbered $assimilN sections.

    Mirrors the core's acceptance checks (read_assimil error-stops on
    num<=0; init error-stops on missing files or non-positive tuning;
    scalar_assimilation error-stops MID-RUN on mode=0 with tau<=0) plus
    the one gate the core never checks: ibarcl<=0 means barocl() — and
    with it assimil_ts — is never called, so assimilation is silently
    skipped while the run completes normally (baroclinic.f90).
    """
    msgs: list[ValidationMessage] = []
    seen_ivars: dict[Any, str] = {}
    enabled_any = False

    # `param` is the field-highlighting key, so it always names a
    # PARAMETER (never the section — the message text carries that).
    # The two section-identity rules below have no offending field and
    # so leave it empty.
    for name in sections:
        if name == "assimil":
            msgs.append(
                ValidationMessage(
                    "error",
                    "$assimil must be numbered ($assimil1, $assimil2, ...) — "
                    "the core error-stops on an unnumbered section",
                )
            )
            continue
        m = _ASSIMIL_NUM.match(name)
        if not m:
            continue
        if int(m.group(1)) <= 0:
            msgs.append(
                ValidationMessage(
                    "error",
                    f"${name} is invalid — assimil sections must be numbered from 1 "
                    "(the core error-stops on num <= 0)",
                )
            )
            continue

        # The core defaults nobs and ivar to -1 and error-stops on either
        # being unset (assimil_admin.f90) BEFORE the nobs=0 skip — a
        # missing nobs is fatal, not "disabled".
        nobs = _get(sections, name, "nobs")
        if nobs is None:
            msgs.append(
                ValidationMessage(
                    "error",
                    f"nobs is required in ${name} — the core error-stops when unset",
                    "nobs",
                )
            )
            continue
        if not isinstance(nobs, (int, float)):
            msgs.append(ValidationMessage("error", f"nobs in ${name} is not a number", "nobs"))
            continue
        if nobs < 0:
            msgs.append(ValidationMessage("error", f"nobs must be >= 0 in ${name}", "nobs"))
            continue
        if nobs == 0:
            if _get(sections, name, "ivar") is None:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"ivar is required in ${name} even when disabled (nobs = 0) — "
                        "the core error-stops when unset",
                        "ivar",
                    )
                )
            else:
                msgs.append(
                    ValidationMessage(
                        "info",
                        f"${name} is disabled (nobs = 0) — the core will skip it",
                        "nobs",
                    )
                )
            continue
        enabled_any = True

        ivar = _get(sections, name, "ivar")
        if ivar is None:
            msgs.append(ValidationMessage("error", f"ivar is required in ${name}", "ivar"))
        elif not isinstance(ivar, (int, float)) or isinstance(ivar, bool):
            # ivar names the assimilated variable, so it is one number. A run
            # ("ivar = 12 13") now parses as a list, which reached the
            # duplicate check below and raised "unhashable type: 'list'" --
            # a traceback where the user needs a message (mirrors nobs).
            msgs.append(ValidationMessage("error", f"ivar in ${name} is not a number", "ivar"))
        else:
            if ivar in seen_ivars:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"ivar = {ivar} in ${name} duplicates ${seen_ivars[ivar]} — "
                        "the core error-stops on duplicate ivars",
                        "ivar",
                    )
                )
            else:
                seen_ivars[ivar] = name
            # itemp/isalt live in $para; ivar is the field in *this*
            # section the user has to change (same convention as the
            # iheat/ibarcl rule above).
            if ivar == 12 and itemp == 0:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"${name} assimilates temperature (ivar = 12) but itemp = 0 — "
                        "T is never computed, assimilation silently skipped",
                        "ivar",
                    )
                )
            if ivar == 11 and isalt == 0:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"${name} assimilates salinity (ivar = 11) but isalt = 0 — "
                        "S is never computed, assimilation silently skipped",
                        "ivar",
                    )
                )

        mode = _get(sections, name, "mode", 0) or 0
        if mode not in (0, 1):
            msgs.append(
                ValidationMessage(
                    "error",
                    f"mode = {mode} in ${name} is invalid — 0 (nudging) or 1 (direct insertion)",
                    "mode",
                )
            )
        tau = _get(sections, name, "tau", 0) or 0
        if mode == 0 and (not isinstance(tau, (int, float)) or tau <= 0):
            msgs.append(
                ValidationMessage(
                    "error",
                    f"tau must be > 0 in ${name} for nudging (mode = 0) — "
                    "the core error-stops at the first observation time",
                    "tau",
                )
            )

        for p in ("corlength", "sigobs", "sigback"):
            v = _get(sections, name, p)
            # Any of these may legally carry ONE VALUE PER OBSERVATION --
            # "corlength = 100. 200." -- which is what physics.py's
            # _assimil_is_array renders as an array field. Since a run of
            # numbers now parses as a list (issue #86), check every element
            # rather than the container: treating the list itself as
            # non-numeric made the validator reject files the editor offers
            # as valid.
            values = list(v) if isinstance(v, (list, tuple)) else [v]
            if not values or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in values
            ):
                msgs.append(ValidationMessage("error", f"{p} must be > 0 in ${name}", p))

        for p in ("filecoords", "fileobs"):
            v = _get(sections, name, p)
            blank = v is None or (isinstance(v, str) and not v.strip().strip("'\""))
            if blank:
                msgs.append(ValidationMessage("error", f"{p} is required in ${name}", p))

    if enabled_any and (not isinstance(ibarcl, (int, float)) or ibarcl <= 0):
        msgs.append(
            ValidationMessage(
                "error",
                "data assimilation is configured but ibarcl = 0 — barocl() never runs, "
                "so assimilation is silently skipped; set ibarcl = 3 (prognostic T/S)",
                "ibarcl",
            )
        )

    return msgs
