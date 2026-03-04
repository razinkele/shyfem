"""Physics configuration page -- guided SHYFEM parameter setup.

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
