"""Tutorial content data structure for the Mar Menor guided walkthrough.

This is a pure data module with NO UI imports. It defines the complete
tutorial content for the 14-simulation Mar Menor progression, organized
into 6 phases that build from a minimal setup to a full 3D baroclinic
non-linear simulation.

Each step may contain:
  - title: step heading
  - content: educational explanation (physics, theory)
  - actions: list of numbered UI instructions (what to click/do)
  - expected: what the user should see after completing the actions
  - screenshot: filename in www/tutorial/ showing the expected UI state
  - nav_target: tab name for the "Go to" navigation link
"""

from __future__ import annotations

TUTORIAL_CONTENT: list[dict] = [
    # -------------------------------------------------------------------------
    # Phase 1: Basic Hydrodynamics (mm_hyd_00 .. mm_hyd_03)
    # -------------------------------------------------------------------------
    {
        "id": "phase1",
        "title": "Phase 1: Basic Hydrodynamics",
        "description": (
            "Start with a minimal simulation and progressively add output, "
            "wind forcing, and bottom friction. These four runs establish the "
            "foundation every SHYFEM simulation needs."
        ),
        "simulations": [
            # -- mm_hyd_00 --
            {
                "name": "mm_hyd_00",
                "str_file": "mm_hyd_00.str",
                "title": "Minimal Simulation",
                "summary": (
                    "The absolute minimum SHYFEM run: a grid, a time window, "
                    "and linearized equations. No output files are written, no "
                    "forcing is applied. This verifies that the model starts, "
                    "runs, and finishes cleanly."
                ),
                "new_params": {},
                "steps": [
                    {
                        "title": "Prepare the Grid",
                        "content": (
                            "Every SHYFEM simulation needs a pre-processed "
                            "basin file (`.bas`). The raw mesh is in "
                            "`GRID/MM_coarse.grd` and must be converted with "
                            "the **shypre** preprocessor before the model can "
                            "use it."
                        ),
                        "actions": [
                            "Navigate to the **Grid Prep** tab.",
                            "The grid path should be auto-filled as " "`GRID/MM_coarse.grd`.",
                            "Click **Run shypre** in the sidebar.",
                            "Wait for the **Log** sub-tab to show completion.",
                        ],
                        "expected": (
                            "The Statistics sub-tab shows ~1,300 nodes and "
                            "~2,400 elements. The Interactive Map displays "
                            "the Mar Menor lagoon outline."
                        ),
                        "screenshot": "grid_prep_stats.png",
                        "nav_target": "Grid Prep",
                    },
                    {
                        "title": "Load and Inspect the STR File",
                        "content": (
                            "Every SHYFEM simulation is controlled by a "
                            "**parameter file** (`.str`). It is divided into "
                            "named sections delimited by `$section` ... `$end` "
                            "pairs.\n\n"
                            "The `$title` section identifies the simulation and "
                            "specifies the computational grid. The `$para` "
                            "section holds all runtime parameters."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_00.str`.",
                            "Open the **Sections** sub-tab to see `$title` " "and `$para`.",
                            "Verify `ilin = 1` (linearized equations) and "
                            "`idt = '300s'` (5-minute time step).",
                        ],
                        "expected": (
                            "The Sections sub-tab shows a `$title` section "
                            "referencing `GRID/MM_coarse` and a `$para` "
                            "section with time parameters."
                        ),
                        "screenshot": "simulation_sections.png",
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run the Minimal Simulation",
                        "content": (
                            "Three parameters define the simulation window:\n\n"
                            "- **itanf** = `'2009-01-01'` -- start date.\n"
                            "- **itend** = `'2009-01-05'` -- end date (4 days).\n"
                            "- **idt** = `'300s'` -- time step (5 minutes).\n\n"
                            "Setting **ilin = 1** solves the linearized "
                            "shallow water equations (no advective terms). "
                            "This is computationally stable and fast, ideal "
                            "for initial testing."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab.",
                            "Select `mm_hyd_00.str` from the STR file dropdown.",
                            "Click **Submit** to start the simulation.",
                            "Watch the **Log** output for progress messages.",
                        ],
                        "expected": (
                            "The simulation completes in a few seconds with "
                            "a clean exit (no errors or NaN warnings). No "
                            "output files are produced because no output "
                            "intervals were set."
                        ),
                        "screenshot": "run_completed.png",
                        "nav_target": "Run",
                    },
                ],
            },
            # -- mm_hyd_01 --
            {
                "name": "mm_hyd_01",
                "str_file": "mm_hyd_01.str",
                "title": "Adding Output",
                "summary": (
                    "Enables output writing so we can visualize results. Adds "
                    "monitor nodes at four strategic locations to track water "
                    "level and velocity time series."
                ),
                "new_params": {
                    "idtout": (
                        "Output interval for spatial fields (3 hours). "
                        "SHYFEM writes the full 2D/3D fields at this frequency."
                    ),
                    "idtext": (
                        "Output interval for monitor node time series "
                        "(300 seconds). These are extracted at the specific "
                        "nodes listed in the $extra section."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Output Parameters",
                        "content": (
                            "Two new parameters control how often results are "
                            "saved:\n\n"
                            "- **idtout** = `'3h'` -- spatial output every 3 "
                            "hours. This writes water level and velocity fields "
                            "over the entire mesh.\n"
                            "- **idtext** = `'300s'` -- time-series output every "
                            "5 minutes at selected monitor nodes.\n\n"
                            "Spatial output is expensive in disk space, so a "
                            "coarser interval (3h) is typical. Monitor node "
                            "output is cheap, so it can match the time step."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_01.str`.",
                            "Open the **Sections** sub-tab.",
                            "Locate `idtout` and `idtext` in the `$para` " "section.",
                            "Scroll down to find the `$extra` section listing "
                            "monitor node numbers (128, 58, 868, 441).",
                        ],
                        "expected": (
                            "The `$para` section now includes `idtout` and "
                            "`idtext`. The `$extra` section lists four node "
                            "numbers."
                        ),
                        "screenshot": "simulation_loaded.png",
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Inspect Output",
                        "content": (
                            "The `$extra` section lists node numbers where "
                            "time-series data is recorded:\n\n"
                            "- **Node 128** -- at the sea boundary (El Estacio "
                            "inlet).\n"
                            "- **Node 58** -- at the inlet channel.\n"
                            "- **Node 868** -- in the lagoon center.\n"
                            "- **Node 441** -- near the lagoon border.\n\n"
                            "Choosing monitor nodes at physically meaningful "
                            "locations helps diagnose whether the simulation "
                            "is behaving correctly."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_01.str`.",
                            "After completion, go to the **Post-Process** tab.",
                            "Click **Scan** to detect the `.shy` output file.",
                            "Use **Extract Time Series** to pull data from "
                            "the four monitor nodes.",
                        ],
                        "expected": (
                            "Post-Process File Info shows a `.shy` file. "
                            "Time series extraction produces `.ext` files "
                            "with water level data at all four nodes."
                        ),
                        "screenshot": "postprocess_scan.png",
                        "nav_target": "Post-Process",
                    },
                    {
                        "title": "Visualize Time Series",
                        "content": (
                            "With output files available, you can now create "
                            "your first plots. The `.ext` files contain "
                            "time-series data at the monitor nodes, perfect "
                            "for line plots showing how water level evolves."
                        ),
                        "actions": [
                            "Navigate to the **Visualize** tab.",
                            "Load the extracted `.ext` file.",
                            "Select **Line Plot** as the chart type.",
                            "All four monitor nodes should appear as " "separate lines.",
                        ],
                        "expected": (
                            "A time-series plot showing water level at the "
                            "four monitor nodes. Since there is no forcing, "
                            "values should be near zero or slowly drifting."
                        ),
                        "screenshot": "visualize_timeseries.png",
                        "nav_target": "Visualize",
                    },
                ],
            },
            # -- mm_hyd_02 --
            {
                "name": "mm_hyd_02",
                "str_file": "mm_hyd_02.str",
                "title": "Wind Forcing",
                "summary": (
                    "Adds wind stress as the primary driving force. Wind is the "
                    "dominant mechanism for water circulation in shallow lagoons "
                    "like Mar Menor."
                ),
                "new_params": {
                    "iwtype": (
                        "Wind stress formulation type. iwtype=3 computes wind "
                        "stress from speed and direction using a bulk "
                        "aerodynamic formula: tau = rho_air * Cd * |W| * W."
                    ),
                    "dragco": (
                        "Wind drag coefficient (2.5e-3). Controls how "
                        "efficiently wind momentum is transferred to the "
                        "water surface. Typical values range from 1e-3 to "
                        "3e-3."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Wind Parameters",
                        "content": (
                            "Wind is typically the most important forcing "
                            "mechanism in coastal lagoons. The wind stress "
                            "on the water surface is computed as:\n\n"
                            "**tau = rho_air * Cd * |W| * W**\n\n"
                            "where rho_air is air density (~1.225 kg/m3), "
                            "Cd is the drag coefficient, and W is the wind "
                            "velocity vector.\n\n"
                            "Setting **iwtype = 3** selects this quadratic "
                            "bulk formula. The drag coefficient **dragco = "
                            "2.5e-3** is a reasonable starting value."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_02.str`.",
                            "In the **Sections** sub-tab, find `iwtype` and "
                            "`dragco` in `$para`.",
                            "Scroll to the `$name` section and note "
                            "`wind = 'INPUT/wind_scir.txt'`.",
                        ],
                        "expected": (
                            "The `$para` section includes `iwtype = 3` and "
                            "`dragco = 2.5e-3`. The `$name` section "
                            "references the wind input file."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Compare with mm_hyd_01",
                        "content": (
                            "The `$name` section specifies the wind data "
                            "file:\n\n"
                            "```\nwind = 'INPUT/wind_scir.txt'\n```\n\n"
                            "This file contains time-series wind data applied "
                            "uniformly over the entire domain. For a lagoon "
                            "the size of Mar Menor (~170 km2), a single "
                            "station is usually adequate."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_02.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "Navigate to the **Visualize** tab and compare "
                            "the current fields with mm_hyd_01.",
                        ],
                        "expected": (
                            "Wind-driven currents are now visible. Water "
                            "levels at monitor nodes show oscillations driven "
                            "by the wind. Currents are much stronger than "
                            "the no-forcing case."
                        ),
                        "screenshot": "postprocess_timeseries.png",
                        "nav_target": "Run",
                    },
                ],
            },
            # -- mm_hyd_03 --
            {
                "name": "mm_hyd_03",
                "str_file": "mm_hyd_03.str",
                "title": "Bottom Friction",
                "summary": (
                    "Adds bottom friction to dissipate momentum, preventing "
                    "unrealistic current speeds. Bottom friction is essential "
                    "for any realistic shallow-water simulation."
                ),
                "new_params": {
                    "ireib": (
                        "Bottom friction formulation. ireib=5 selects a "
                        "quadratic drag law where bottom stress is "
                        "proportional to velocity squared."
                    ),
                    "czdef": (
                        "Bottom friction coefficient (2.5e-3). With ireib=5 "
                        "this is used as a dimensionless drag coefficient "
                        "in the formula: tau_b = rho * Cd * |u| * u."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Friction Parameters",
                        "content": (
                            "Without bottom friction, wind-driven currents "
                            "would accelerate indefinitely. Bottom friction "
                            "provides the energy sink that balances the "
                            "wind input, establishing a quasi-steady "
                            "circulation.\n\n"
                            "In shallow lagoons like Mar Menor (average "
                            "depth ~4 m), bottom friction is particularly "
                            "important because the entire water column "
                            "feels the frictional effect of the seabed."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_03.str`.",
                            "In the **Sections** sub-tab, find `ireib = 5` "
                            "and `czdef = 2.5e-3` in `$para`.",
                        ],
                        "expected": (
                            "The `$para` section includes `ireib = 5` and "
                            "`czdef = 2.5e-3` alongside the wind parameters "
                            "from mm_hyd_02."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Compare Currents",
                        "content": (
                            "Setting **ireib = 5** selects a quadratic "
                            "bottom drag law:\n\n"
                            "**tau_b = rho * Cd * |u| * u**\n\n"
                            "The coefficient **czdef = 2.5e-3** is a "
                            "typical value for sandy/muddy bottoms. "
                            "Rougher substrates may need larger values "
                            "(5e-3 or more)."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_03.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "Navigate to the **Compare** tab.",
                            "Select mm_hyd_02 and mm_hyd_03 to see how "
                            "friction reduces current speeds.",
                        ],
                        "expected": (
                            "Current speeds are noticeably lower than "
                            "mm_hyd_02 (wind only). The circulation pattern "
                            "is modified with friction providing energy "
                            "dissipation."
                        ),
                        "screenshot": "compare_params.png",
                        "nav_target": "Post-Process",
                    },
                ],
            },
        ],
    },
    # -------------------------------------------------------------------------
    # Phase 2: Open Boundaries (mm_hyd_11, mm_hyd_12a, mm_hyd_13)
    # -------------------------------------------------------------------------
    {
        "id": "phase2",
        "title": "Phase 2: Open Boundaries",
        "description": (
            "Connect the lagoon to the Mediterranean Sea through open "
            "boundaries. Learn how prescribed water levels drive tidal "
            "exchange through the inlet channels."
        ),
        "simulations": [
            # -- mm_hyd_11 --
            {
                "name": "mm_hyd_11",
                "str_file": "mm_hyd_11.str",
                "title": "Sea Level Boundary",
                "summary": (
                    "Introduces the first open boundary: a Dirichlet (water "
                    "level) condition along the Mediterranean connection. "
                    "This drives tidal exchange through the El Estacio inlet."
                ),
                "new_params": {
                    "ibtyp": (
                        "Boundary type. ibtyp=1 is a Dirichlet condition: "
                        "water levels are prescribed from a data file. The "
                        "model computes the resulting currents."
                    ),
                    "ztilt": (
                        "Tilt correction for the boundary (0.008 m). "
                        "Applies a linear spatial adjustment across the "
                        "boundary nodes to account for the geostrophic "
                        "tilt of the sea surface."
                    ),
                    "ktilt": (
                        "Reference node (130) for the tilt correction. "
                        "The tilt is applied relative to this node's "
                        "position along the boundary."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Inspect the Boundary",
                        "content": (
                            "Real water bodies exchange flow with their "
                            "surroundings. The `$bound1` section defines "
                            "the first open boundary: a line of 93 nodes "
                            "(85-177) representing the connection between "
                            "Mar Menor and the Mediterranean Sea.\n\n"
                            "Setting **ibtyp = 1** creates a **Dirichlet "
                            "boundary condition** where water levels are "
                            "prescribed from `INPUT/level_Mar_Menor.dat`."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_11.str`.",
                            "Open the **Boundaries** sub-tab.",
                            "Verify `$bound1` shows `ibtyp = 1` with "
                            "93 boundary nodes (85-177).",
                            "Note the tilt correction: `ztilt = 0.008` " "and `ktilt = 130`.",
                        ],
                        "expected": (
                            "The Boundaries sub-tab shows `$bound1` with "
                            "Dirichlet type and the list of boundary node "
                            "numbers."
                        ),
                        "screenshot": "simulation_boundaries.png",
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Observe Tidal Exchange",
                        "content": (
                            "The parameters **ztilt = 0.008** and **ktilt = "
                            "130** apply a linear tilt correction across "
                            "the open boundary to prevent spurious currents "
                            "from an unrealistically flat water surface.\n\n"
                            "With this boundary active, periodic water "
                            "level oscillations appear at the monitor nodes "
                            "as the tide propagates through the inlet."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_11.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "In **Visualize**, compare node 128 (sea "
                            "boundary) with node 868 (lagoon center).",
                        ],
                        "expected": (
                            "Water level time series show periodic tidal "
                            "oscillations. The lagoon signal (node 868) "
                            "is attenuated and delayed relative to the "
                            "sea boundary (node 128), reflecting the "
                            "choking effect of the narrow inlet."
                        ),
                        "nav_target": "Post-Process",
                    },
                ],
            },
            # -- mm_hyd_12a --
            {
                "name": "mm_hyd_12a",
                "str_file": "mm_hyd_12a.str",
                "title": "Initial Water Level Offset",
                "summary": (
                    "Explores the effect of a non-zero initial water level. "
                    "Setting zconst=+0.30 starts the lagoon with a 30 cm "
                    "elevation above the reference, causing an initial "
                    "outflow surge."
                ),
                "new_params": {
                    "zconst": (
                        "Initial constant water level offset (+0.30 m). "
                        "Sets the water surface elevation at the start "
                        "of the simulation across the entire domain."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Note the Initial Condition",
                        "content": (
                            "Setting **zconst = +0.30** raises the initial "
                            "water level in the entire lagoon by 30 cm "
                            "relative to the reference.\n\n"
                            "This creates an initial pressure gradient "
                            "between the lagoon (elevated) and the sea "
                            "boundary (at the prescribed level), causing "
                            "a strong outflow through the inlet."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_12a.str`.",
                            "In the **Sections** sub-tab, find `zconst = " "0.30` in `$para`.",
                        ],
                        "expected": (
                            "The `$para` section shows `zconst = 0.30` "
                            "alongside all the boundary parameters from "
                            "mm_hyd_11."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Compare Initial Surge",
                        "content": (
                            "The companion file `mm_hyd_12b.str` uses "
                            "**zconst = -0.30** (negative offset), creating "
                            "the opposite scenario: an initial inflow surge. "
                            "Running both variants verifies the model "
                            "responds symmetrically to perturbations."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_12a.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "In **Visualize**, look at the first few hours "
                            "to see the initial outflow surge decaying.",
                        ],
                        "expected": (
                            "Time series show a strong initial outflow "
                            "that gradually decays as the lagoon drains "
                            "toward equilibrium with the sea boundary."
                        ),
                        "nav_target": "Post-Process",
                    },
                ],
            },
            # -- mm_hyd_13 --
            {
                "name": "mm_hyd_13",
                "str_file": "mm_hyd_13.str",
                "title": "Adding a River Boundary",
                "summary": (
                    "Adds a second boundary for a river discharge (Los "
                    "Alcazares). This flux boundary (ibtyp=3) prescribes "
                    "flow rate rather than water level."
                ),
                "new_params": {
                    "ibtyp (bound2)": (
                        "Boundary type 3 = flux (Neumann) condition. "
                        "Instead of prescribing water level, flow rate "
                        "(m3/s) is prescribed from a time-series file."
                    ),
                    "intpol": (
                        "Interpolation type for boundary data (2 = "
                        "linear interpolation between data points)."
                    ),
                    "zfact": (
                        "Scaling factor (50) applied to the input "
                        "discharge values. This multiplies the raw "
                        "data to convert units or amplify the signal."
                    ),
                },
                "steps": [
                    {
                        "title": "Inspect the River Boundary",
                        "content": (
                            "The `$bound2` section adds a second boundary "
                            "at node 218 (Los Alcazares). Unlike the sea "
                            "boundary, this uses **ibtyp = 3**, a **flux "
                            "boundary condition** (Neumann type).\n\n"
                            "With a flux boundary, you prescribe the "
                            "volumetric flow rate (m3/s) rather than the "
                            "water level. This is the natural choice for "
                            "rivers and streams."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_13.str`.",
                            "Open the **Boundaries** sub-tab.",
                            "Verify `$bound2` shows `ibtyp = 3` at node " "218 with `zfact = 50`.",
                        ],
                        "expected": (
                            "The Boundaries sub-tab now shows two "
                            "boundaries: `$bound1` (sea level, Dirichlet) "
                            "and `$bound2` (river, flux)."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Observe River Effects",
                        "content": (
                            "The river boundary reads discharge data from "
                            "`INPUT/river.txt` with **intpol = 2** (linear "
                            "interpolation) and **zfact = 50** (scaling "
                            "factor).\n\n"
                            "A single node (218) is sufficient for a small "
                            "river input, while wider river mouths might "
                            "use multiple boundary nodes."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_13.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "In **Visualize**, compare with mm_hyd_11 to "
                            "see the river's effect on water levels.",
                        ],
                        "expected": (
                            "Water levels near the river node (441) show "
                            "increased variability from the freshwater "
                            "discharge. The tidal signal from bound1 is "
                            "still visible."
                        ),
                        "nav_target": "Run",
                    },
                ],
            },
        ],
    },
    # -------------------------------------------------------------------------
    # Phase 3: Coriolis and Advection (mm_hyd_21, mm_hyd_22, mm_hyd_23)
    # -------------------------------------------------------------------------
    {
        "id": "phase3",
        "title": "Phase 3: Coriolis and Advection",
        "description": (
            "Add rotational effects (Coriolis force) and switch from "
            "linearized to non-linear equations with advective transport "
            "and horizontal diffusion."
        ),
        "simulations": [
            # -- mm_hyd_21 --
            {
                "name": "mm_hyd_21",
                "str_file": "mm_hyd_21.str",
                "title": "Coriolis Force",
                "summary": (
                    "Enables the Coriolis effect, which deflects currents "
                    "to the right in the Northern Hemisphere. Important for "
                    "any basin wider than a few kilometers."
                ),
                "new_params": {
                    "icor": (
                        "Coriolis switch. icor=1 enables the Coriolis "
                        "acceleration term in the momentum equations."
                    ),
                    "dlat": (
                        "Reference latitude (38 degrees N) for computing "
                        "the Coriolis parameter f = 2 * omega * sin(lat). "
                        "Mar Menor is at approximately 37.7N."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Coriolis Parameters",
                        "content": (
                            "On a rotating Earth, moving water experiences "
                            "a fictitious force that deflects it to the "
                            "right in the Northern Hemisphere. This is the "
                            "**Coriolis force**, proportional to:\n\n"
                            "**f = 2 * omega * sin(lat)**\n\n"
                            "At Mar Menor's latitude of ~38N, "
                            "f ~ 8.9 x 10^-5 s^-1. The Rossby number "
                            "Ro ~ 0.06, meaning Coriolis has a significant "
                            "effect on the circulation."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_21.str`.",
                            "In the **Sections** sub-tab, find `icor = 1` "
                            "and `dlat = 38` in `$para`.",
                        ],
                        "expected": (
                            "The `$para` section includes `icor = 1` and "
                            "`dlat = 38` alongside the wind, friction, and "
                            "boundary parameters."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Observe Circulation Deflection",
                        "content": (
                            "Setting **icor = 1** and **dlat = 38** activates "
                            "the Coriolis term at the correct latitude.\n\n"
                            "You should see the current field rotate slightly "
                            "compared to the non-Coriolis runs: wind-driven "
                            "currents are deflected to the right."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_21.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "In **Visualize**, compare the current vectors "
                            "with mm_hyd_13 to see the deflection.",
                        ],
                        "expected": (
                            "Current vectors show a rightward deflection "
                            "compared to the non-Coriolis case. This is "
                            "most visible in the open areas of the lagoon."
                        ),
                        "nav_target": "Post-Process",
                    },
                ],
            },
            # -- mm_hyd_22 --
            {
                "name": "mm_hyd_22",
                "str_file": "mm_hyd_22.str",
                "title": "Non-linear Advection",
                "summary": (
                    "Switches from linearized to non-linear equations "
                    "(ilin=0). Advective momentum transport is now included, "
                    "capturing important physics like jet formation at inlets."
                ),
                "new_params": {
                    "ilin (changed)": (
                        "Changed from 1 to 0. Non-linear mode includes "
                        "the advective acceleration terms (u * du/dx) "
                        "in the momentum equations."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Note the Non-linear Switch",
                        "content": (
                            "Switching **ilin = 0** enables the full "
                            "non-linear shallow water equations. The key "
                            "difference is the **advective acceleration** "
                            "term (u * grad(u)).\n\n"
                            "Non-linear effects produce:\n\n"
                            "- **Tidal asymmetry** -- flood and ebb have "
                            "different durations.\n"
                            "- **Jet formation** -- fast currents through "
                            "narrow channels.\n"
                            "- **Residual circulation** -- time-averaged "
                            "flows."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_22.str`.",
                            "In the **Sections** sub-tab, verify " "`ilin = 0` in `$para`.",
                            "Note that the time step `idt` remains at " "`'300s'`.",
                        ],
                        "expected": (
                            "The `$para` section shows `ilin = 0` "
                            "(previously 1). All other parameters carry "
                            "over from mm_hyd_21."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Compare with Linear",
                        "content": (
                            "Non-linear equations are more demanding "
                            "numerically. The advective terms can cause "
                            "instabilities if the time step is too large "
                            "(the CFL condition). In this simulation, the "
                            "same time step (idt = 300s) is used."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_22.str`.",
                            "After completion, go to **Post-Process** and " "extract time series.",
                            "In **Compare**, select mm_hyd_21 (linear) and "
                            "mm_hyd_22 (non-linear) to see differences.",
                        ],
                        "expected": (
                            "Non-linear effects produce asymmetric tidal "
                            "signals and jet-like flow at the inlet. "
                            "Peak velocities may differ from the linear case."
                        ),
                        "nav_target": "Post-Process",
                    },
                ],
            },
            # -- mm_hyd_23 --
            {
                "name": "mm_hyd_23",
                "str_file": "mm_hyd_23.str",
                "title": "Adaptive Stepping and Diffusion",
                "summary": (
                    "Uses a smoothed grid, adaptive time-splitting, and "
                    "Smagorinsky horizontal diffusion. These stabilize the "
                    "non-linear simulation and prevent grid-scale noise."
                ),
                "new_params": {
                    "coumax": (
                        "Maximum Courant number (0.8). The adaptive "
                        "time-splitter adjusts sub-steps to keep the "
                        "Courant number below this limit."
                    ),
                    "itsplt": (
                        "Time-splitting mode (2 = automatic). The "
                        "model splits the advection step into smaller "
                        "sub-steps as needed for stability."
                    ),
                    "idtsyn": (
                        "Synchronization interval (1 hour). All "
                        "processes re-synchronize at this interval "
                        "after adaptive sub-stepping."
                    ),
                    "ahpar": (
                        "Horizontal diffusion coefficient (0.3). With "
                        "idhtyp=2 this is the Smagorinsky constant, "
                        "not a physical diffusivity."
                    ),
                    "idhtyp": (
                        "Horizontal diffusion type (2 = Smagorinsky). "
                        "Diffusivity scales with local element size "
                        "and velocity gradients."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Grid and Stepping",
                        "content": (
                            "This simulation switches to "
                            "`GRID/MM_coarse_smooth`, a version of the "
                            "mesh where bathymetry gradients have been "
                            "smoothed. Sharp depth changes can generate "
                            "spurious pressure gradients, especially with "
                            "non-linear terms active.\n\n"
                            "The base time step is reduced to **idt = "
                            "'30s'**, and the adaptive time-splitter is "
                            "enabled with **itsplt = 2** and **coumax = "
                            "0.8**."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_23.str`.",
                            "In the **Sections** sub-tab, note the grid "
                            "reference changed to `GRID/MM_coarse_smooth`.",
                            "Find `idt = '30s'`, `itsplt = 2`, and " "`coumax = 0.8` in `$para`.",
                        ],
                        "expected": (
                            "The `$title` section references the smooth "
                            "grid. The `$para` section has the reduced "
                            "time step and adaptive splitting parameters."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Understand Smagorinsky Diffusion",
                        "content": (
                            "Setting **idhtyp = 2** with **ahpar = 0.3** "
                            "activates the **Smagorinsky** horizontal "
                            "diffusion scheme:\n\n"
                            "**nu_h = (C_s * dx)^2 * |S|**\n\n"
                            "where C_s is the Smagorinsky constant (0.3) "
                            "and |S| is the strain rate. This provides "
                            "more diffusion where the flow is sheared "
                            "and less where it is uniform."
                        ),
                        "actions": [
                            "In the **Sections** sub-tab, find `idhtyp = 2` "
                            "and `ahpar = 0.3` in `$para`.",
                            "Also note `idtsyn = '1h'` which re-synchronizes "
                            "all processes hourly.",
                        ],
                        "expected": (
                            "All Smagorinsky and time-splitting parameters "
                            "are visible in `$para`."
                        ),
                    },
                    {
                        "title": "Run and Verify Stability",
                        "content": (
                            "The combination of smoothed grid, adaptive "
                            "stepping, and Smagorinsky diffusion should "
                            "produce a stable non-linear simulation without "
                            "grid-scale noise."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_23.str`.",
                            "Monitor the log for any CFL warnings.",
                            "After completion, go to **Post-Process** and "
                            "verify smooth current fields.",
                        ],
                        "expected": (
                            "The simulation runs without CFL warnings. "
                            "Current fields are smooth, with no "
                            "grid-scale oscillations or checkerboard "
                            "patterns."
                        ),
                        "nav_target": "Run",
                    },
                ],
            },
        ],
    },
    # -------------------------------------------------------------------------
    # Phase 4: 3D Baroclinic Salinity (mm_hyd_31)
    # -------------------------------------------------------------------------
    {
        "id": "phase4",
        "title": "Phase 4: 3D Baroclinic Salinity",
        "description": (
            "Transition to 3D mode with salinity transport. Density "
            "differences between river water and sea water drive "
            "baroclinic circulation patterns."
        ),
        "simulations": [
            # -- mm_hyd_31 --
            {
                "name": "mm_hyd_31",
                "str_file": "mm_hyd_31.str",
                "title": "Salinity-Driven Density Currents",
                "summary": (
                    "Enables 3D baroclinic mode with salinity transport. "
                    "Horizontal density gradients between salty lagoon "
                    "water and fresh river inflow create pressure gradients "
                    "that drive vertical circulation cells."
                ),
                "new_params": {
                    "ibarcl": (
                        "Baroclinic mode (3 = full baroclinic). Density "
                        "is computed from the salinity field using an "
                        "equation of state, and the resulting pressure "
                        "gradients drive additional currents."
                    ),
                    "isalt": (
                        "Salinity transport switch (1 = active). The "
                        "advection-diffusion equation for salinity is "
                        "solved at each time step."
                    ),
                    "salref": (
                        "Reference (initial) salinity (35 psu). The "
                        "entire domain starts at this value. Mar Menor "
                        "is hypersaline, typically 42-46 psu."
                    ),
                    "shpar": (
                        "Horizontal diffusion coefficient for salinity "
                        "(0.3). Controls how fast salt spreads laterally."
                    ),
                    "idtcon": (
                        "Output interval for concentration fields (3h). "
                        "Writes salinity (and temperature if active) at "
                        "this frequency."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Understand Baroclinic Mode",
                        "content": (
                            "In **barotropic** mode (all previous runs), "
                            "the water column has uniform density.\n\n"
                            "In **baroclinic** mode (**ibarcl = 3**), "
                            "density varies horizontally and vertically "
                            "due to salinity differences. These create "
                            "internal pressure gradients that drive "
                            "additional currents, often in opposite "
                            "directions at different depths."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_31.str`.",
                            "In the **Sections** sub-tab, find `ibarcl = 3`, "
                            "`isalt = 1`, and `salref = 35` in `$para`.",
                            "Note the extended end date: `itend = " "'2009-01-31'` (full month).",
                        ],
                        "expected": (
                            "The `$para` section shows baroclinic and "
                            "salinity parameters. The simulation period is "
                            "extended to 31 days."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run the Extended Simulation",
                        "content": (
                            "With **isalt = 1**, SHYFEM solves the "
                            "advection-diffusion equation for salinity. "
                            "The domain starts at **salref = 35** psu. "
                            "The sea boundary prescribes salinity from "
                            "`INPUT/S_MarMenor.txt`, while the river "
                            "injects freshwater with **salt = 0**."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_31.str`.",
                            "This run takes longer (full month). Watch the " "log for progress.",
                            "After completion, go to **Post-Process**.",
                        ],
                        "expected": (
                            "The simulation completes without errors. "
                            "Output includes both `.shy` (hydrodynamic) "
                            "and `.nos` or `.ous` (concentration) files."
                        ),
                        "nav_target": "Run",
                    },
                    {
                        "title": "Visualize Salinity Fields",
                        "content": (
                            "The new parameter **idtcon = '3h'** writes "
                            "salinity fields at the same interval as "
                            "hydrodynamic output. You can now map the "
                            "salinity distribution to see how freshwater "
                            "spreads from the river."
                        ),
                        "actions": [
                            "Navigate to the **Visualize** tab and choose "
                            "Data Type **SHYFEM results**.",
                            "Pick the run's `.ts.shy` file (or a `.nc` "
                            "from Post-Process) and press **Load Data**; a "
                            "`.shy` is converted once and cached.",
                            "Choose the variable **Salinity**.",
                            "Move the **Record** slider or press **Play** "
                            "to follow the salinity over time.",
                        ],
                        "expected": (
                            "The map shows salinity ~35 psu in "
                            "most of the lagoon, with a freshwater plume "
                            "near the river boundary (node 218)."
                        ),
                        "screenshot": "visualize_netcdf.png",
                        "nav_target": "Visualize",
                    },
                ],
            },
        ],
    },
    # -------------------------------------------------------------------------
    # Phase 5: Full 3D with Temperature (mm_hyd_41, mm_hyd_42)
    # -------------------------------------------------------------------------
    {
        "id": "phase5",
        "title": "Phase 5: Full 3D with Temperature",
        "description": (
            "Add temperature transport, turbulence modeling, and "
            "atmospheric heat exchange for a complete 3D simulation. "
            "Explicit vertical level definitions control the resolution."
        ),
        "simulations": [
            # -- mm_hyd_41 --
            {
                "name": "mm_hyd_41",
                "str_file": "mm_hyd_41.str",
                "title": "Temperature and Heat Fluxes",
                "summary": (
                    "Adds temperature transport, a turbulence closure "
                    "model (GOTM), evaporation, and atmospheric heat "
                    "fluxes. Also defines explicit vertical levels from "
                    "1 m to 80 m depth."
                ),
                "new_params": {
                    "itemp": (
                        "Temperature transport switch (1 = active). "
                        "Solves the heat equation alongside salinity."
                    ),
                    "temref": (
                        "Reference (initial) temperature (9 degrees C). "
                        "January in Mar Menor is cool, with water "
                        "temperatures around 9-12 degrees C."
                    ),
                    "thpar": (
                        "Horizontal diffusion coefficient for temperature "
                        "(0.3). Same as shpar for salinity."
                    ),
                    "iturb": (
                        "Turbulence model switch (1 = GOTM). Uses the "
                        "General Ocean Turbulence Model for vertical "
                        "mixing, which computes eddy viscosity/diffusivity "
                        "from turbulent kinetic energy equations."
                    ),
                    "ievap": (
                        "Evaporation switch (1 = active). Enables "
                        "evaporative water loss from the surface, which "
                        "increases salinity and cools the water."
                    ),
                    "hmin": (
                        "Minimum layer thickness (1 m). Prevents "
                        "layers from becoming too thin, which would "
                        "cause numerical instabilities."
                    ),
                    "aapar": (
                        "Constant vertical viscosity (0 = disabled). "
                        "Set to zero because GOTM provides the vertical "
                        "mixing."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Review Vertical Levels",
                        "content": (
                            "The `$levels` section defines the vertical "
                            "grid with 19 levels:\n\n"
                            "```\n1 2 3 4 5 6 7 8 9 10 12 15 20 30 40 "
                            "50 60 70 80\n```\n\n"
                            "Near the surface, layers are 1 m thick "
                            "(resolving the thermocline). Deeper layers "
                            "are progressively thicker. Most of Mar Menor "
                            "is 4-7 m deep, so only the first ~7 levels "
                            "are active over most of the domain."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_41.str`.",
                            "In the **Sections** sub-tab, find the "
                            "`$levels` section with 19 depth values.",
                            "Find `itemp = 1`, `temref = 9`, `iturb = 1`, "
                            "and `ievap = 1` in `$para`.",
                        ],
                        "expected": (
                            "The `$levels` section lists 19 depth values. "
                            "The `$para` section includes temperature, "
                            "turbulence, and evaporation parameters."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run with Full 3D Physics",
                        "content": (
                            "Setting **iturb = 1** activates **GOTM**, an "
                            "advanced turbulence closure that computes "
                            "vertical mixing from TKE equations. It "
                            "replaces constant vertical viscosity (hence "
                            "**aapar = 0**).\n\n"
                            "With **ievap = 1**, evaporative cooling and "
                            "water loss are computed. The wind file "
                            "switches to `INPUT/wind09.txt` with hourly "
                            "atmospheric data for heat flux computations."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_41.str`.",
                            "This is a longer 3D run. Monitor the log "
                            "for progress and any warnings.",
                            "After completion, go to **Post-Process**.",
                        ],
                        "expected": (
                            "The simulation completes cleanly. Output "
                            "includes hydrodynamic, salinity, and "
                            "temperature fields."
                        ),
                        "nav_target": "Run",
                    },
                    {
                        "title": "Visualize Temperature and Salinity",
                        "content": (
                            "The boundary prescribes temperature from "
                            "`INPUT/T_MarMenor.txt`. Additional heat "
                            "exchange files (qflux, rain) are in the "
                            "`$name` section. You can now visualize both "
                            "temperature and salinity fields."
                        ),
                        "actions": [
                            "In **Visualize**, choose Data Type **SHYFEM "
                            "results**, pick the run's `.ts.shy` file and "
                            "press **Load Data**.",
                            "Choose the variable **Temperature** and use the "
                            "**Record** slider or **Play**.",
                            "Switch the variable to **Salinity** and compare.",
                        ],
                        "expected": (
                            "Temperature shows ~9 degrees C with "
                            "slight warming from heat fluxes. Salinity "
                            "shows the freshwater plume near the river."
                        ),
                        "nav_target": "Visualize",
                    },
                ],
            },
            # -- mm_hyd_42 --
            {
                "name": "mm_hyd_42",
                "str_file": "mm_hyd_42.str",
                "title": "Diagnostic Baroclinic Mode",
                "summary": (
                    "Same as mm_hyd_41 but with ibarcl=1 (diagnostic "
                    "baroclinic). Density gradients drive currents but "
                    "are computed from the evolving T/S fields without "
                    "full feedback."
                ),
                "new_params": {
                    "ibarcl (changed)": (
                        "Changed from 3 to 1. Diagnostic baroclinic "
                        "mode: density is computed from T/S and affects "
                        "the pressure field, but the baroclinic pressure "
                        "gradient uses a simpler formulation."
                    ),
                },
                "steps": [
                    {
                        "title": "Load and Compare Baroclinic Modes",
                        "content": (
                            "SHYFEM offers different baroclinic modes:\n\n"
                            "- **ibarcl = 1** (diagnostic): Simplified "
                            "density-pressure coupling. Numerically stable, "
                            "suitable when baroclinic effects are secondary."
                            "\n\n"
                            "- **ibarcl = 3** (full prognostic): Complete "
                            "formulation. More accurate but can be sensitive "
                            "to grid quality."
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_42.str`.",
                            "In the **Sections** sub-tab, verify " "`ibarcl = 1` (changed from 3).",
                        ],
                        "expected": (
                            "The only change from mm_hyd_41 is `ibarcl = 1` "
                            "in `$para`. All other parameters are identical."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run and Compare with Prognostic Mode",
                        "content": (
                            "Run both mm_hyd_41 (ibarcl=3) and mm_hyd_42 "
                            "(ibarcl=1) and compare the fields. In many "
                            "shallow-water applications, differences are "
                            "small, and the diagnostic mode is preferred "
                            "for its stability."
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_42.str`.",
                            "After completion, go to the **Compare** tab.",
                            "Select mm_hyd_41 and mm_hyd_42 to see "
                            "parameter differences and field comparisons.",
                        ],
                        "expected": (
                            "Salinity and temperature fields are very "
                            "similar to mm_hyd_41. If mm_hyd_41 showed "
                            "noisy velocity fields near steep bathymetry, "
                            "mm_hyd_42 should be smoother."
                        ),
                        "nav_target": "Post-Process",
                    },
                ],
            },
        ],
    },
    # -------------------------------------------------------------------------
    # Phase 6: Non-linear Full Physics (mm_hyd_43)
    # -------------------------------------------------------------------------
    {
        "id": "phase6",
        "title": "Phase 6: Non-linear Full Physics",
        "description": (
            "The most complete simulation: non-linear advection, "
            "Smagorinsky diffusion, adaptive time-splitting, and full "
            "3D temperature/salinity transport. This is the production-"
            "ready configuration."
        ),
        "simulations": [
            # -- mm_hyd_43 --
            {
                "name": "mm_hyd_43",
                "str_file": "mm_hyd_43.str",
                "title": "Production Configuration",
                "summary": (
                    "Combines everything: non-linear equations, Smagorinsky "
                    "diffusion, adaptive time-splitting, 3D T/S transport, "
                    "GOTM turbulence, and atmospheric heat exchange. This "
                    "is the reference configuration for realistic Mar Menor "
                    "simulations."
                ),
                "new_params": {
                    "ilin (changed)": (
                        "Changed to 0 (non-linear). Full advective " "momentum transport is active."
                    ),
                    "idt (changed)": (
                        "Reduced to 30s (from 300s). Non-linear "
                        "advection with 3D tracer transport requires "
                        "a shorter base time step."
                    ),
                    "coumax": ("Maximum Courant number (0.8) for adaptive " "time-splitting."),
                    "itsplt": (
                        "Automatic time-splitting (2) subdivides " "the advection step as needed."
                    ),
                    "idtsyn": ("Synchronization interval (1 hour)."),
                    "ahpar": ("Smagorinsky constant (0.3) for horizontal " "diffusion."),
                    "idhtyp": ("Smagorinsky diffusion type (2)."),
                    "ibarcl (changed)": (
                        "Changed to 1 (diagnostic baroclinic). Chosen "
                        "for stability with non-linear terms active."
                    ),
                    "itend (changed)": (
                        "Shortened to 2009-01-25 (24 days). Non-linear "
                        "3D runs are computationally expensive."
                    ),
                },
                "steps": [
                    {
                        "title": "Load the Full-Physics Configuration",
                        "content": (
                            "This simulation combines every feature "
                            "introduced in the previous phases:\n\n"
                            "- Wind forcing with bottom friction\n"
                            "- Open boundary with tidal exchange\n"
                            "- River discharge\n"
                            "- Coriolis force\n"
                            "- Non-linear advection (ilin=0)\n"
                            "- Smagorinsky horizontal diffusion\n"
                            "- Adaptive time-splitting\n"
                            "- 3D salinity and temperature transport\n"
                            "- GOTM turbulence closure\n"
                            "- Atmospheric heat exchange and evaporation"
                        ),
                        "actions": [
                            "Navigate to the **Simulation** tab.",
                            "Click **Load** and select `mm_hyd_43.str`.",
                            "In the **Sections** sub-tab, verify `ilin = 0`, "
                            "`ibarcl = 1`, `itsplt = 2`, and `coumax = 0.8`.",
                            "Check `idt = '30s'` and " "`itend = '2009-01-25'`.",
                        ],
                        "expected": (
                            "The `$para` section shows the full set of "
                            "production parameters: non-linear, Smagorinsky, "
                            "adaptive stepping, 3D tracers, GOTM, and "
                            "heat exchange."
                        ),
                        "nav_target": "Simulation",
                    },
                    {
                        "title": "Run the Production Simulation",
                        "content": (
                            "The key to a stable non-linear 3D simulation "
                            "is the combination of:\n\n"
                            "1. **Short base time step** (idt = 30s)\n"
                            "2. **Adaptive splitting** (itsplt=2, "
                            "coumax=0.8)\n"
                            "3. **Smagorinsky diffusion** (idhtyp=2)\n"
                            "4. **Smoothed grid**\n"
                            "5. **Diagnostic baroclinic** (ibarcl=1)"
                        ),
                        "actions": [
                            "Navigate to the **Run** tab and submit " "`mm_hyd_43.str`.",
                            "This is the most expensive run. Monitor the "
                            "log carefully for any CFL warnings or "
                            "instabilities.",
                            "The simulation period is 24 days with a " "30-second time step.",
                        ],
                        "expected": (
                            "The simulation completes without CFL warnings "
                            "or numerical instabilities. Run time will be "
                            "longer than previous simulations."
                        ),
                        "nav_target": "Run",
                    },
                    {
                        "title": "Visualize Full 3D Results",
                        "content": (
                            "Output intervals remain at 3 hours for both "
                            "hydrodynamic (idtout) and tracer (idtcon) "
                            "fields. Monitor node output (idtext) at 300s "
                            "provides detailed time series for validation."
                            "\n\n"
                            "For production runs on larger domains, MPI "
                            "parallelization significantly reduces "
                            "wall-clock time."
                        ),
                        "actions": [
                            "In **Visualize**, choose Data Type **SHYFEM "
                            "results** and load the run's `.hydro.shy` "
                            "(water level, currents) and `.ts.shy` "
                            "(salinity, temperature) files.",
                            "Map each variable with the **Record** slider or "
                            "**Play**; tick **Current arrows** for the "
                            "hydro file.",
                            "Use time-series plots at monitor nodes for "
                            "validation against observations.",
                        ],
                        "expected": (
                            "Full 3D fields show realistic circulation "
                            "with wind-driven surface currents, tidal "
                            "exchange, river plume, and temperature/salinity "
                            "stratification."
                        ),
                        "nav_target": "Visualize",
                    },
                ],
            },
        ],
    },
]


def get_phase(phase_id: str) -> dict | None:
    """Return a phase dictionary by its id, or None if not found."""
    for phase in TUTORIAL_CONTENT:
        if phase["id"] == phase_id:
            return phase
    return None


def get_simulation(sim_name: str) -> dict | None:
    """Return a simulation dictionary by its name, or None if not found."""
    for phase in TUTORIAL_CONTENT:
        for sim in phase["simulations"]:
            if sim["name"] == sim_name:
                return sim
    return None


def build_tutorial_context(sim_name: str, work_dir: str, target_tab: str) -> dict | None:
    """Build a tutorial context dict for a given simulation.

    Returns None if the simulation name is not found in the tutorial content.
    """
    sim = get_simulation(sim_name)
    if sim is None:
        return None
    return {
        "sim_name": sim_name,
        "str_file": sim["str_file"],
        "work_dir": work_dir,
        "grd_file": "GRID/MM_coarse.grd",
        "target_tab": target_tab,
    }


def get_all_sim_names() -> list[str]:
    """Return a flat list of all simulation names in tutorial order."""
    names: list[str] = []
    for phase in TUTORIAL_CONTENT:
        for sim in phase["simulations"]:
            names.append(sim["name"])
    return names
