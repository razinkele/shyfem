"""Cross-parameter validation for SHYFEM STR files.

Checks Fortran parameter interdependencies and reports
errors (missing required params) and warnings (likely misconfigurations).
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    message: str
    param: str = ""


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
    iheat = _get(sections, "para", "iheat", 0)
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
        sedtr = sections.get("sedtr", {})
        isedi = _get(sections, "sedtr", "isedi", 0)
        if not sedtr or isedi == 0:
            msgs.append(
                ValidationMessage(
                    "warning",
                    "issedi=1 in $para but $sedtr section missing or isedi=0",
                    "issedi",
                )
            )

    # --- Dependency: ilagr>0 needs $lagrg section ---
    ilagr = _get(sections, "para", "ilagr", 0)
    if ilagr is None:
        ilagr = _get(sections, "lagrg", "ilagr", 0)
    if ilagr and ilagr > 0:
        lagrg = sections.get("lagrg", {})
        if not lagrg:
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
    iwave = _get(sections, "para", "iwave", 0)
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
    iconz = _get(sections, "para", "iconz", 0)
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
    has_levels = "levels" in sections and sections["levels"]
    nsigma = _get(sections, "para", "nsigma", 0) or 0
    dzreg = _get(sections, "para", "dzreg", 0) or 0
    hsigma = _get(sections, "para", "hsigma", 0) or 0

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
    idtcon = _get(sections, "para", "idtcon", 0)
    if idtcon and idtcon > 0 and iconz == 0 and ibarcl == 0:
        msgs.append(
            ValidationMessage(
                "info",
                "idtcon>0 but no scalars active (iconz=0, ibarcl=0) — output will be empty",
                "idtcon",
            )
        )

    return msgs
