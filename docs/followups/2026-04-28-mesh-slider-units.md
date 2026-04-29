# Follow-up: Unit-Aware Mesh Sliders

**Origin:** 2026-04-28 mesh-input validation audit — the two issues called out under "Out of scope" in `docs/superpowers/plans/2026-04-28-mesh-validation-hardening.md`.

**Problem.** Two sliders in the mesh-builder wizard accept values in the
source CRS's coordinate units, with no in-UI cue:

- `reduce_tolerance` (Step 2 — Refine boundary): range 0–1000. After
  `import_boundaries()` reprojects to WGS84, units are degrees; 1000° is
  meaningless. For a non-reprojected projected source, 1 unit ≈ 1 m.
- `contour_sample_dist` (Step 4 — Bathymetry contours): no upper bound;
  small values on long lines explode the point cloud (e.g. 0.001 sample
  on a 100 km line → 100M points).

**Why we deferred.** A clean fix is UX redesign, not pure validation:
- Option A — Dynamic labels keyed off `grd.epsg` after import
  ("Tolerance (degrees)" vs "Tolerance (meters)"), plus auto-scaling the
  slider max to a sensible fraction of boundary extent.
- Option B — Replace coordinate-unit sliders with percent-of-extent
  sliders (0–10 % of boundary diagonal) that translate to the right
  underlying units internally.

**Suggested next step.** Pick Option B for both sliders — it is unit-free
from the user's perspective, can't accept absurd values, and is one
arithmetic step (`tolerance = pct * boundary.diagonal_length`) inside
the existing handlers.

**Related code:**
- `shyfem-ui/shyfem_ui/pages/mesh_builder.py:622–625` (`reduce_tolerance` slider)
- `shyfem-ui/shyfem_ui/pages/mesh_builder.py` (`contour_sample_dist` numeric input — search `contour_sample_dist`)
- `shyfem-ui/shyfem_ui/services/mesh_builder.py:333` (`reduce_boundary`)
- `shyfem-ui/shyfem_ui/services/mesh_builder.py:805` (sample-dist branch in `load_bathymetry_contours`)
