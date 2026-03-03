# IBM Page & LGR Integration Design

**Date:** 2026-03-03
**Scope:** Two sequential plans — (1) commit pending unstaged work, (2) implement IBM page as Lagrangian trajectory explorer

---

## Background

The UI audit identified the following unimplemented functionality across 14 pages:

| Priority | Item | Status |
|---|---|---|
| P0 | Pending unstaged work (IBM wiring, responsive polish, grid prep fixes) | Ready to commit — 1285 tests pass |
| P1 | IBM page `Run IBM` button — demo stub, hardcoded fake data | Not implemented |
| P1 | IBM page `.lgr` file loading and trajectory display | Not implemented |
| P2 | Visualize page `.shy` data type — falls through to "Unsupported" error | Broken stub |
| P3 | Ensemble Results column/variable selector | Minor UX gap |
| P3 | Compare page time-series file picker | Minor UX gap |

This design covers P0 (commit plan) and P1+P2 (IBM + shy fix).

---

## Plan 1: Commit Pending Work

Single commit of all unstaged changes. All 1285 tests already pass.

**Files in commit:**
- `shyfem_ui/app.py` — IBM page wired into sidebar and server
- `shyfem_ui/pages/__init__.py` — `ibm` exported
- `shyfem_ui/pages/grid_prep.py` — running state indicators, better error messages
- `shyfem_ui/components/grid_map.py` — CRS reprojection improvements
- `shyfem_ui/services/mesh_builder.py` — mesh builder improvements
- `shyfem_ui/www/css/shyfem.css` — responsive CSS (tablet 768px breakpoint) + Bootstrap utility overrides
- `shyfem_ui/tests/test_app_layout.py` — hamburger and backdrop tests
- `shyfem_ui/tests/test_css_overrides.py` — new CSS override tests
- `shyfem_ui/tests/test_mesh_builder.py` — expanded mesh builder tests
- `testcases/examples/mar_menor/partition.4.txt` — updated partition data

**Commit message:**
```
feat(ui): add IBM page, responsive tablet layout, grid prep improvements

- Wire ibm.py into app sidebar and server
- Add tablet responsive CSS with hamburger + sidebar overlay at 768px
- Add missing Bootstrap utility overrides (text-*, bg-*, border-*) for ocean theme
- Add running state indicators and better error messages in grid_prep
- Improve CRS handling and reprojection in grid_map
- Improve mesh builder robustness
```

---

## Plan 2: IBM Page Integration

### Scope

**Post-processing explorer only.** The IBM page loads `.lgr` output files from completed IBM-enabled simulations, calls `lgrelab` to extract particle trajectories, and displays them on the deck.gl map.

Simulation submission stays on the Run page. The "Run IBM" button is replaced with an informational note pointing users to the Simulation + Run pages.

### Architecture

```
ibm.py (page)
├── services/lgr_service.py  [NEW]
│   ├── LgrService.load(lgr_path) → list[ParticleTrack]
│   ├── run lgrelab via ShyfemWrapper.run_command()
│   ├── parse whitespace-delimited text output (particle_id, time, lon, lat, depth)
│   └── group by particle_id into track objects
└── components/grid_map.py (existing)
    ├── path_layer("tracks", ...)
    ├── scatterplot_layer("starts", ...)
    └── scatterplot_layer("ends", ...)
```

### Data Flow

```
User provides .lgr path
  → LgrService.load(path)
      → ShyfemWrapper.run_command("lgrelab", ["-out", "text", str(path)], cwd)
      → parse stdout: particle_id | time | lon | lat | depth (per line)
      → group rows by particle_id
      → return [{id, path:[[lon,lat]], times:[], depths:[]}]
  → Python filters applied (time range, particle ID subset)
  → deck.gl layers rebuilt:
      path_layer     — trajectory polylines, color-by-time (viridis)
      scatterplot_layer — start points (green), end points (red)
  → map updated via _map.update(session, layers=..., view_state=...)
```

### Page Changes

**Remove:**
- `_DEMO_PARTICLES` and `_DEMO_TRACKS` constants
- `"Run IBM"` action button
- `ibm_status` hardcoded "Demo mode" badge

**Add:**
- `.lgr` file path input + "Load Trajectories" button
- Time range filter (min/max time slider, populated from loaded data)
- Particle ID filter (multi-select or "all", populated from loaded data)
- Color-by selector: Time | Depth | Particle ID
- IBM setup note (informational card pointing to Simulation + Run pages)
- `ibm_status` showing live stats: `N particles | T steps | duration`

**Sidebar layout:**
```
[.lgr File Path  ___________]
[Load Trajectories   btn    ]

[── Filters ──────────────]
[Time range: 0 ──── 24h   ]
[Particle IDs: all  ▼     ]
[Color by: Time ▼         ]

[── Display ──────────────]
[Show start points  ☑     ]
[Show end points    ☑     ]
[Show full tracks   ☑     ]
[EMODnet bathymetry ☑     ]

[── About IBM ────────────]
[ℹ Configure IBM params   ]
[  in Simulation page,    ]
[  then submit from Run.  ]
```

### `.shy` Fix in Visualize

Remove `"shy": "SHYFEM Output (.shy)"` from the `choices` dict in `visualize_ui()` (~line 168 of `pages/visualize.py`). Users already have the Post-Process page to convert `.shy → NetCDF` first.

### New File: `services/lgr_service.py`

```python
"""Lagrangian particle trajectory loader — wraps lgrelab CLI."""

from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

@dataclass
class ParticleTrack:
    id: int
    path: list[list[float]]   # [[lon, lat], ...]
    times: list[float]
    depths: list[float]

class LgrService:
    def __init__(self, wrapper):
        self._wrapper = wrapper  # ShyfemWrapper instance

    async def load(self, lgr_path: Path) -> list[ParticleTrack]:
        """Run lgrelab on lgr_path and parse trajectory output."""
        result = await self._wrapper.run_command(
            "lgrelab", ["-out", "text", str(lgr_path)], lgr_path.parent
        )
        if not result.success:
            raise RuntimeError(f"lgrelab failed: {result.stderr}")
        return _parse_lgrelab_output(result.stdout)

def _parse_lgrelab_output(text: str) -> list[ParticleTrack]:
    """Parse whitespace-delimited lgrelab text output into ParticleTrack list."""
    # Implementation: group lines by particle_id → ParticleTrack objects
    ...
```

### Testing

**`tests/test_lgr_service.py`** (~6 tests):
- `test_parse_empty_output` — returns empty list, no crash
- `test_parse_single_particle` — 1 particle, 3 timesteps → correct path shape
- `test_parse_multi_particle` — groups by particle ID correctly
- `test_filter_time_range` — time range filter trims tracks
- `test_filter_particle_ids` — particle ID filter works
- `test_lgrelab_not_found` — graceful error when binary missing

**`tests/test_ibm.py`** (~4 tests):
- `test_ibm_ui_renders` — module returns a Shiny Tag
- `test_no_demo_constants` — `_DEMO_PARTICLES`/`_DEMO_TRACKS` removed from source
- `test_no_demo_notification` — "coming soon" text removed from source
- `test_ibm_status_not_hardcoded` — "Demo mode" badge text removed

**`tests/test_visualize.py`** (~1 test):
- `test_shy_option_removed` — `"shy"` not a key in visualize data type choices

**Target:** ~11 new tests → ~1296 passing.

---

## Out of Scope (P3 items — deferred)

- Ensemble Results column/variable selector
- Compare page time-series file picker
- Interactive map click-to-place release points (future enhancement)
