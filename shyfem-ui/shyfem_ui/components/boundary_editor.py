"""Boundary condition editor component.

Provides a structured UI for defining $bound sections in .str files:
- Add/remove boundary conditions
- Set boundary type (elevation, velocity, discharge)
- Assign nodes, time series files, and scaling factors
- Import boundary definitions from CSV
- Auto-generate $bound section text
"""

from collections.abc import Callable, Sequence

from shiny import module, reactive, render, ui

from shyfem_ui.components.project_select import str_file_selectize
from shyfem_ui.services.parser_str import StrFile, format_param_display

# The core's intpol (bnd_admin.f90 addpar('intpol',0.)): the number of time
# records interpolated between, 0 = auto (cubic for a water-level boundary,
# else linear). "" = not in the file, so nothing is written.
INTPOL_CHOICES = {
    "": "(not set) - core default",
    "0": "0 - Auto (cubic for water level, else linear)",
    "1": "1 - Stepwise",
    "2": "2 - Linear",
    "4": "4 - Cubic",
}


def _intpol_choices(current: int | None) -> dict[str, str]:
    """INTPOL_CHOICES plus the boundary's own value if it is not listed (3)."""
    key = "" if current is None else str(current)
    if key in INTPOL_CHOICES:
        return INTPOL_CHOICES
    return {**INTPOL_CHOICES, key: f"{key} (from file)"}


def _optional_int(value) -> int | None:
    """An int, or None for an absent parameter."""
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value) -> float | None:
    """A float, or None for an absent parameter."""
    if value is None or value == "":
        return None
    return float(value)


def _csv_cell(parts: list[str], lineno: int, index: int, name: str, convert, default):
    """``convert(parts[index])``, *default* when the column is absent.

    A cell that does not convert raises a ValueError naming the line, the
    column and the cell, which the import shows to the user.
    """
    if len(parts) <= index:
        return default
    try:
        return convert(parts[index])
    except ValueError:
        raise ValueError(
            f"line {lineno}, column {index + 1} ({name}): {parts[index]!r} is not a number"
        ) from None


def parse_boundary_csv(csv_text: str, start_id: int = 1) -> list[dict]:
    """Parse CSV text into boundary definitions.

    CSV format: nodes,ibtyp[,boundn][,zfact][,intpol]
    A missing or blank intpol leaves it unset (the core default).
    Lines starting with # are comments. Blank lines are skipped.
    Minimum 2 columns required (nodes + ibtyp).

    Raises:
        ValueError: a numeric cell does not convert; the message names the
            line, the column and the cell, for the user.

    Args:
        csv_text: Raw CSV text
        start_id: Starting boundary ID

    Returns:
        List of boundary dicts with keys: id, label, nodes, ibtyp, boundn, zfact, intpol
    """
    imported = []
    bid = start_id
    for lineno, line in enumerate(csv_text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue

        entry = {
            "id": bid,
            "label": f"bound{bid}",
            "nodes": parts[0],
            "ibtyp": _csv_cell(parts, lineno, 1, "ibtyp", int, 1),
            "boundn": parts[2] if len(parts) > 2 else "",
            "zfact": _csv_cell(parts, lineno, 3, "zfact", _optional_float, None),
            "intpol": _csv_cell(parts, lineno, 4, "intpol", _optional_int, None),
        }
        imported.append(entry)
        bid += 1

    return imported


def generate_bound_text(boundaries: list[dict]) -> str:
    """Generate $bound section text from boundary definitions.

    Args:
        boundaries: List of dicts with keys: label, nodes, ibtyp, boundn, zfact, intpol

    Returns:
        Multi-line string with $bound sections
    """
    if not boundaries:
        return "! No boundaries defined"

    lines = []
    for b in boundaries:
        section_name = b["label"]
        lines.append(f"${section_name}")
        if b.get("nodes"):
            lines.append(f"        kbound = {b['nodes']}")
        lines.append(f"        ibtyp = {b['ibtyp']}")
        if b.get("boundn"):
            lines.append(f"        boundn = '{b['boundn']}'")
        for scalar_key in ("saltn", "tempn", "conzn"):
            val = b.get(scalar_key, "")
            if val:
                lines.append(f"        {scalar_key} = '{val}'")
        # Whenever it is set, as with intpol: an explicit 1.0 from the file
        # must survive a regenerate.
        if b.get("zfact") is not None:
            lines.append(f"        zfact = {b['zfact']}")
        # Whenever it is set: 1 (stepwise) is not the core default, and an
        # explicit value from the file must survive.
        if b.get("intpol") is not None:
            lines.append(f"        intpol = {b['intpol']}")
        lines.append("$end")
        lines.append("")

    return "\n".join(lines)


@module.ui
def boundary_editor_ui():
    """Boundary editor component UI."""
    return ui.div(
        ui.h5("Boundary Conditions"),
        ui.p("Define open boundaries for the simulation.", class_="text-muted small"),
        # Boundary list
        ui.output_ui("boundary_list"),
        # Add boundary controls
        ui.div(
            ui.input_action_button(
                "add_boundary_btn",
                "+ Add Boundary",
                class_="btn-sm btn-outline-primary me-2",
            ),
            ui.input_action_button(
                "import_csv_btn",
                "Import CSV",
                class_="btn-sm btn-outline-secondary me-2",
            ),
            ui.input_action_button(
                "generate_str_btn",
                "Generate $bound",
                class_="btn-sm btn-success",
            ),
            class_="mt-2 mb-3",
        ),
        # Generated output
        ui.output_ui("generated_bound_section"),
        # CSV import modal content
        ui.output_ui("csv_import_area"),
        class_="boundary-editor-component",
    )


@module.server
def boundary_editor_server(
    input,
    output,
    session,
    parsed_str: reactive.Value[StrFile | None] = None,
    on_boundaries_changed: Callable[[list[dict]], None] | None = None,
    file_choices: Callable[[], Sequence[str]] | None = None,
):
    """Boundary editor component server logic.

    Args:
        parsed_str: Reactive StrFile to read/write boundary sections from/to
        on_boundaries_changed: Callback when boundaries are modified
        file_choices: Callable returning project-relative data-file paths
            offered by each boundary's time-series field (selectize with
            create; any name can still be typed). None -> free text only.
    """
    # Each boundary: {"id": int, "nodes": str, "ibtyp": int, "boundn": str,
    #                  "zfact": float, "intpol": int | None, "label": str}
    boundaries = reactive.value([])
    show_csv_import = reactive.value(False)
    generated_text = reactive.value("")
    _next_id = reactive.value(1)

    # Load existing boundaries from parsed STR file
    @reactive.effect
    def _load_from_str():
        sf = parsed_str.get() if parsed_str else None
        if sf is None:
            return

        loaded = []
        bid = 1
        for section_name, section in sf.sections.items():
            if not section_name.startswith("bound"):
                continue
            params = section.parameters
            values = {}
            for name, convert, default in (
                ("ibtyp", int, 1),
                ("zfact", _optional_float, None),
                ("intpol", _optional_int, None),
            ):
                raw = params.get(name)
                try:
                    values[name] = default if raw is None else convert(raw)
                except (TypeError, ValueError):
                    # Raised in this effect, it closed the user's session.
                    # Show no boundaries rather than some the editor cannot
                    # write back faithfully.
                    ui.notification_show(
                        f"Boundaries not loaded: ${section_name} {name} = "
                        f"{format_param_display(raw)!r} is not a number",
                        type="error",
                        duration=10,
                    )
                    return
            entry = {
                "id": bid,
                "label": section_name,
                # A node run parses to a list ("kbound = 1855 1856 1882
                # 1883"); str() would show "[1855, 1856, 1882, 1883]" and
                # generate_bound_text writes this field back verbatim, so
                # that repr would ship an .str line the core hard-stops on.
                "nodes": format_param_display(section.parameters.get("kbound")),
                "ibtyp": values["ibtyp"],
                "boundn": format_param_display(section.parameters.get("boundn")),
                "zfact": values["zfact"],
                "intpol": values["intpol"],
                "saltn": format_param_display(section.parameters.get("saltn")),
                "tempn": format_param_display(section.parameters.get("tempn")),
                "conzn": format_param_display(section.parameters.get("conzn")),
            }
            loaded.append(entry)
            bid += 1

        if loaded:
            boundaries.set(loaded)
            _next_id.set(bid)

    @reactive.effect
    @reactive.event(input.add_boundary_btn)
    def _add_boundary():
        current = boundaries.get()
        bid = _next_id.get()
        new_entry = {
            "id": bid,
            "label": f"bound{bid}",
            "nodes": "",
            "ibtyp": 1,
            "boundn": "",
            "zfact": None,
            "intpol": None,
            "saltn": "",
            "tempn": "",
            "conzn": "",
        }
        _next_id.set(bid + 1)
        # Copy-on-write (N41): reactive.Value.set() short-circuits with
        # `self._value is value` and skips invalidation when passed the SAME
        # object reference. Mutating `current` in place and calling
        # boundaries.set(current) is therefore a silent no-op -- boundary_list
        # and the remove-handler registration effect never re-run. Building a
        # new list here guarantees a distinct identity so the set() actually
        # registers as a change.
        boundaries.set([*current, new_entry])

    # Dynamic remove handlers for remove_bound_{bid} buttons. This effect re-runs
    # every time `boundaries` changes; a reactive.effect registered inside it is
    # not destroyed on re-run, so without the dedup guard each boundary's
    # remove_bound_<id> handler would stack a new copy on every change, firing
    # _remove N times. Register each boundary id's handler at most once.
    _registered_remove_bids: set[int] = set()

    @reactive.effect
    def _register_remove_handlers():
        bounds = boundaries.get()
        for b in bounds:
            _make_remove_bound(b["id"])

    def _make_remove_bound(bid: int):
        if bid in _registered_remove_bids:
            return  # handler already live for this boundary — don't stack another
        _registered_remove_bids.add(bid)

        @reactive.effect
        @reactive.event(input[f"remove_bound_{bid}"])
        def _remove():
            current = boundaries.get()
            boundaries.set([x for x in current if x["id"] != bid])

    @reactive.effect
    @reactive.event(input.import_csv_btn)
    def _toggle_csv_import():
        show_csv_import.set(not show_csv_import.get())

    @reactive.effect
    @reactive.event(input.do_csv_import_btn)
    def _import_csv():
        csv_text = input.csv_input()
        if not csv_text:
            ui.notification_show("No CSV data provided", type="warning")
            return

        try:
            imported = parse_boundary_csv(csv_text, _next_id.get())
        except ValueError as e:
            # Raised in this effect, it closed the user's session.
            ui.notification_show(f"CSV not imported: {e}", type="error", duration=10)
            return

        if imported:
            current = boundaries.get()
            # Copy-on-write (N41) -- see _add_boundary for why in-place
            # extend() + set(current) is a silent no-op.
            boundaries.set([*current, *imported])
            _next_id.set(imported[-1]["id"] + 1)
            show_csv_import.set(False)
            ui.notification_show(f"Imported {len(imported)} boundaries", type="message")
        else:
            ui.notification_show("No valid boundary data found in CSV", type="warning")

    @reactive.effect
    @reactive.event(input.generate_str_btn)
    def _generate_bound():
        bounds = boundaries.get()
        if not bounds:
            generated_text.set("! No boundaries defined")
            return

        # Collect updated values from form inputs
        updated = []
        for b in bounds:
            bid = b["id"]
            # None = the card's field has not reported yet; "" = cleared.
            zfact_raw = input[f"bound_zfact_{bid}"]()
            try:
                zfact = b.get("zfact") if zfact_raw is None else _optional_float(zfact_raw)
            except ValueError:
                # It used to keep the old value silently.
                ui.notification_show(
                    f"Not generated: ${b['label']} zfact = {zfact_raw!r} is not a number",
                    type="error",
                    duration=10,
                )
                return
            try:
                intpol_raw = input[f"bound_intpol_{bid}"]()
                # {**b}: saltn/tempn/conzn have no card field and were dropped.
                entry = {
                    **b,
                    "nodes": input[f"bound_nodes_{bid}"]() or b["nodes"],
                    "ibtyp": int(input[f"bound_type_{bid}"]() or b["ibtyp"]),
                    "boundn": input[f"bound_file_{bid}"]() or b["boundn"],
                    "zfact": zfact,
                    "intpol": (
                        b.get("intpol") if intpol_raw is None else _optional_int(intpol_raw)
                    ),
                }
                updated.append(entry)
            except Exception:
                updated.append(b)

        boundaries.set(updated)

        text = generate_bound_text(updated)
        generated_text.set(text)

        if on_boundaries_changed:
            on_boundaries_changed(updated)

    @render.ui
    def boundary_list():
        bounds = boundaries.get()
        if not bounds:
            return ui.p(
                "No boundaries defined. Click '+ Add Boundary' to start.", class_="text-muted small"
            )

        choices = list(file_choices()) if file_choices is not None else []
        cards = []
        for b in bounds:
            bid = b["id"]
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

            cards.append(
                ui.div(
                    ui.div(
                        ui.span(
                            f"${b['label']}",
                            class_="badge bg-danger me-2",
                            style="font-family: monospace;",
                        ),
                        ui.input_action_button(
                            f"remove_bound_{bid}",
                            "x",
                            class_="btn-sm btn-outline-danger py-0 px-1 float-end",
                        ),
                        class_="card-header py-1",
                    ),
                    ui.div(
                        ui.row(
                            ui.column(
                                6,
                                ui.div(
                                    ui.span("Nodes", class_="small fw-bold"),
                                    ui.input_text(
                                        f"bound_nodes_{bid}",
                                        "",
                                        value=b["nodes"],
                                        placeholder="1 2 3 or 1-10",
                                    ),
                                ),
                            ),
                            ui.column(
                                6,
                                ui.div(
                                    ui.span("Type", class_="small fw-bold"),
                                    ui.input_select(
                                        f"bound_type_{bid}",
                                        "",
                                        choices=type_choices,
                                        selected=str(b["ibtyp"]),
                                    ),
                                ),
                            ),
                        ),
                        ui.row(
                            ui.column(
                                6,
                                ui.div(
                                    ui.span("Time series file", class_="small fw-bold"),
                                    str_file_selectize(
                                        f"bound_file_{bid}", "", b["boundn"], choices
                                    ),
                                ),
                            ),
                            ui.column(
                                3,
                                ui.div(
                                    ui.span("Scale factor", class_="small fw-bold"),
                                    ui.input_text(
                                        f"bound_zfact_{bid}",
                                        "",
                                        value=format_param_display(b.get("zfact")),
                                    ),
                                ),
                            ),
                            ui.column(
                                3,
                                ui.div(
                                    ui.span("Interpolation", class_="small fw-bold"),
                                    ui.input_select(
                                        f"bound_intpol_{bid}",
                                        "",
                                        choices=_intpol_choices(b.get("intpol")),
                                        selected=format_param_display(b.get("intpol")),
                                    ),
                                ),
                            ),
                        ),
                        class_="card-body py-2",
                    ),
                    class_="card mb-2",
                )
            )

        return ui.div(*cards)

    @render.ui
    def csv_import_area():
        if not show_csv_import.get():
            return None

        return ui.div(
            ui.h6("Import Boundaries from CSV"),
            ui.p(
                "Format: nodes, type, file, zfact, intpol (one boundary per line)",
                class_="text-muted small",
            ),
            ui.input_text_area(
                "csv_input",
                "",
                placeholder="1 2 3, 1, INPUT/tide.txt, 1.0, 4\n4 5 6, 3, INPUT/river.txt, 1.0, 2",
                height="100px",
            ),
            ui.input_action_button(
                "do_csv_import_btn",
                "Import",
                class_="btn-sm btn-primary mt-1",
            ),
            class_="p-2 border rounded bg-light mt-2 mb-2",
        )

    @render.ui
    def generated_bound_section():
        text = generated_text.get()
        if not text:
            return None

        return ui.div(
            ui.h6("Generated $bound sections"),
            ui.pre(
                text,
                class_="small p-2 bg-light",
                style="max-height: 200px; overflow-y: auto; font-family: monospace;",
            ),
            class_="mt-2",
        )

    return {
        "boundaries": boundaries,
        "generated_text": generated_text,
    }
