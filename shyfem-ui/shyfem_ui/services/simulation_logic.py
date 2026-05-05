"""Pure-logic helpers for the Simulation page.

Extracted from `pages/simulation.py` for unit-testability:
- generate_template: emit a SHYFEM .str file template by name
- apply_quick_settings: mutate a StrFile's `para` section with the
  4 quick-edit fields (start, end, dt, output interval); pure given
  the StrFile and 4 strings; the page wrapper still does I/O and
  reactive notification on top of this.
"""

from __future__ import annotations

from shyfem_ui.services.parser_str import StrFile


def generate_template(template_name: str) -> str:
    """Generate a template .str file by name.

    Returns the template body as a string. Unknown names return the
    'basic_2d' template (preserving the original page-level fallback).
    """
    templates = {
        "basic_2d": """
#------------------------------------------------------------------------
# Basic 2D Simulation Template
#------------------------------------------------------------------------

$title
        Basic 2D Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$extra
        1     'output node 1'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "basic_3d": """
#------------------------------------------------------------------------
# Basic 3D Simulation Template
#------------------------------------------------------------------------

$title
        Basic 3D Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D settings
        nlv = 10
        hlv = 1 2 3 4 5 6 8 10 15 20
$end

$extra
        1     'output node 1'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "wind_driven": """
#------------------------------------------------------------------------
# Wind-Driven Circulation Template
# 2D barotropic flow with Coriolis and Smagorinsky diffusion
#------------------------------------------------------------------------

$title
        Wind-Driven Circulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Coriolis (beta-plane)
        icor = 1
        dlat = 45.0

        ! Horizontal diffusion (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
$end

$extra
        1     'center'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
        "tidal": """
#------------------------------------------------------------------------
# Tidal Simulation Template
#------------------------------------------------------------------------

$title
        Tidal Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-03'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$bound
        ! Boundary conditions (type value)
        1  1  1  0.5    ! Open boundary with M2 tide
$end

$extra
        1     'tidal gauge'
$end

$name
        ! bound = 'INPUT/tide.txt'
$end
""",
        "baroclinic": """
#------------------------------------------------------------------------
# Baroclinic (Temperature/Salinity) Simulation Template
#------------------------------------------------------------------------

$title
        Baroclinic Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-10'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Baroclinic mode: full T/S coupling
        ibarcl = 1
        itemp = 1
        isalt = 1

        ! Initial conditions
        temref = 15.0
        salref = 35.0

        ! 3D vertical settings
        nlv = 10
        iturb = 1      ! GOTM turbulence
        difmol = 1.0e-6
        vismol = 1.0e-6

        ! Horizontal mixing
        idhtyp = 2     ! Smagorinsky
        ahpar = 1.0
        dhpar = 1.0

        ! Heat flux
        iheat = 1
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$extra
        1     'monitoring station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! tempin = 'INPUT/temp_init.shy'
        ! saltin = 'INPUT/salt_init.shy'
        ! qflux = 'INPUT/heatflux.txt'
$end
""",
        "eulerian_tracer": """
#------------------------------------------------------------------------
# Eulerian Tracer / Water Age Template
#------------------------------------------------------------------------

$title
        Eulerian Tracer
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-05'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Eulerian tracer (concentration)
        iconz = 1
        iage = 1       ! Water age tracer mode
        conref = 0.0

        ! Transport scheme
        itvd = 1       ! TVD for horizontal advection
        chpar = 1.0    ! Horizontal diffusion for tracers
$end

$extra
        1     'release point'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
        "lagrangian": """
#------------------------------------------------------------------------
# Lagrangian Particle Tracking Template
#------------------------------------------------------------------------

$title
        Lagrangian Particle Tracking
        lagrangian_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3
$end

$lagrg
        ilagr = 2
        nbdy = 100
        nbdymax = 10000
        idtl = 3600
        rwhpar = 1.0
        idtlgr = 3600
$end

$extra
        1       'release point'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "tidal_estuary": """
#------------------------------------------------------------------------
# Tidal Estuary Template
# 3D baroclinic with tidal boundary, river inflow, and salinity
#------------------------------------------------------------------------

$title
        Tidal Estuary
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-10'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D baroclinic mode
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence (GOTM)
        iturb = 1
        difmol = 1.0e-6
        vismol = 1.0e-6

        ! Horizontal mixing (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0

        ! Coriolis
        icor = 1
        dlat = 45.0
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$bound
        ! Open boundary: tidal forcing
        1  1  1  0.5    ! M2 tidal amplitude [m]
        ! River inflow boundary
        ! 2  3  0  100.0  ! Discharge [m3/s], salinity = 0
$end

$extra
        1     'estuary mouth'
        2     'upstream station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! bound = 'INPUT/tide.txt'
        ! saltin = 'INPUT/salt_init.shy'
$end
""",
        "sediment_transport": """
#------------------------------------------------------------------------
# Sediment Transport Template
# 3D with simple sedimentation module
#------------------------------------------------------------------------

$title
        Sediment Transport
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-05'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D setup
        nlv = 10
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Simple sedimentation module
        issedi = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
$end

$levels
        0.5
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
$end

$extra
        1     'monitoring point'
$end

$name
        wind = 'INPUT/wind.txt'
$end

! For full sediment transport, use the $sedtr section instead of issedi:
! $sedtr
!         isedi = 1
!         sedgrs = '0.063 0.125 0.25 0.5'
!         percin = '0.25 0.25 0.25 0.25'
! $end
""",
        "water_quality": """
#------------------------------------------------------------------------
# Water Quality (EUTRO) Template
# 3D baroclinic with 9-variable eutrophication model
#------------------------------------------------------------------------

$title
        Water Quality
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-30'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D baroclinic
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Water quality (WASP/EUTRO 9-variable model)
        ! Variables: NH3, NO3, OPO4, PHYT, CBOD, DO, ON, OP, ZOO
        ibio = 1

        ! Heat flux for temperature evolution
        iheat = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$extra
        1     'monitoring station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! bio2dn = 'INPUT/bio_boundary.txt'
        ! bioin = 'INPUT/bio_initial.shy'
$end
""",
        "storm_surge": """
#------------------------------------------------------------------------
# Storm Surge Template
# 2D barotropic with wetting/drying and meteorological forcing
#------------------------------------------------------------------------

$title
        Storm Surge
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-03'
        idt = '60s'
        idtout = '30m'
        idtext = '60s'

        date = 20200101

        ilin = 1

        ! Wind drag (Wu 1982 - speed-dependent)
        iwtype = 3
        itdrag = 2
        wsmax = 60

        ! Bottom friction
        ireib = 5      czdef = 2.5e-3

        ! Coriolis
        icor = 1
        dlat = 45.0

        ! Spherical coordinates (for real-world domains)
        ! isphe = 1

        ! Wetting and drying
        hzoff = 0.05
        hzon = 0.10
        hzmin = 0.01

        ! Horizontal diffusion
        idhtyp = 2
        ahpar = 1.0
$end

$extra
        1     'tide gauge 1'
        2     'tide gauge 2'
$end

$name
        ! Wind file with optional atmospheric pressure (3rd column)
        wind = 'INPUT/wind.txt'
$end
""",
        "thermal": """
#------------------------------------------------------------------------
# Thermal / Heat Exchange Simulation Template
#------------------------------------------------------------------------

$title
        Thermal / Heat Exchange Simulation
        thermal_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 1
        itemp = 1
        isalt = 0
        iheat = 6
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_init.txt'
$end
""",
        "ice_model": """
#------------------------------------------------------------------------
# Ice Model Simulation Template
#------------------------------------------------------------------------

$title
        Ice Model Simulation
        ice_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-04-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 1
        itemp = 1
        isalt = 1
        iheat = 6
        icemod = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_init.txt'
        saltn = 'INPUT/salt_init.txt'
$end
""",
        "oil_spill": """
#------------------------------------------------------------------------
# Oil Spill Simulation Template
#------------------------------------------------------------------------

$title
        Oil Spill Simulation
        oil_spill_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3
$end

$lagrg
        ilagr = 3
        nbdy = 1000
        nbdymax = 50000
        idtl = 3600
        rwhpar = 1.0
        ioil = 1
        lbeach = 0.5
        ldecay = 86400
        idtlgr = 3600
$end

$extra
        1       'spill source'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
        "data_assimilation": """
#------------------------------------------------------------------------
# Data Assimilation Simulation Template
#------------------------------------------------------------------------

$title
        Data Assimilation Simulation
        assim_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 4
        itemp = 1
        isalt = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$nduge
        nvars = 3
        tramp = 43200
        ttau = 3600
        sigma = 5000
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_obs.txt'
        saltn = 'INPUT/salt_obs.txt'
$end
""",
        "offline_tracer": """
#------------------------------------------------------------------------
# Offline Tracer Run Template
#------------------------------------------------------------------------

$title
        Offline Tracer Run
        offline_tracer_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1

        idtoff = -1
        iconz = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "wave_coupled": """
#------------------------------------------------------------------------
# Wave-Coupled Storm Surge Template
#------------------------------------------------------------------------

$title
        Wave-Coupled Storm Surge
        wave_coupled_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '60s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        iwave = 2
        dtwave = 300
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
    }

    return templates.get(template_name, templates["basic_2d"])


def _quote_value(val: str) -> str:
    """Strip existing quotes and wrap in single quotes.

    Used by the quick-settings flow which writes string-typed STR params.
    """
    val = val.strip().strip("'\"")
    return f"'{val}'"


def apply_quick_settings(
    str_file: StrFile | None,
    *,
    start: str = "",
    end: str = "",
    dt: str = "",
    output_int: str = "",
) -> StrFile:
    """Apply quick-edit settings to a StrFile's ``para`` section.

    Empty strings are skipped (the existing param is preserved).

    Args:
        str_file: Existing StrFile, or None to start from a fresh one.
        start: itanf value (start time).
        end: itend value (end time).
        dt: idt value (timestep).
        output_int: idtout value (output interval).

    Returns:
        The (possibly newly-constructed) StrFile with the requested
        para fields updated.
    """
    if str_file is None:
        str_file = StrFile()
    if start:
        str_file.set_param("para", "itanf", _quote_value(start))
    if end:
        str_file.set_param("para", "itend", _quote_value(end))
    if dt:
        str_file.set_param("para", "idt", _quote_value(dt))
    if output_int:
        str_file.set_param("para", "idtout", _quote_value(output_int))
    return str_file
