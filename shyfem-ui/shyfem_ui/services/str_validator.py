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
