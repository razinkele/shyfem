# SHYFEM results map on the Visualize page — design

Date: 2026-10-27. Status: owner decisions recorded; awaiting approval of this document.

## Intent

A user who has run a SHYFEM simulation in the UI (first case: the Curonian
Lagoon 29-box setup, georg's 2001 run) wants to **see the model's fields on a
map and watch them change in time**: water level, currents, salinity,
temperature on the computational mesh.

Today nothing in the UI can do that. The Visualize page's "NetCDF (.nc)"
data type is the only candidate, and it is broken (review finding V-01): it
builds a slider for every dimension — including the mesh-node dimension —
and slices each to one index, so every realistic variable reduces to a single
value and the plot fails ("list index out of range"). It also only knows
rectangular grids (heatmap/contour over the dimensions), while SHYFEM output
is an unstructured triangle mesh (UGRID: values on nodes, a triangle list).

The owner's first concrete question — modelled water level against the gauge
measurements — is already answered by the Box-model page's *Model vs
Measured* tab and is **not** part of this work.

## What the owner decided

- The map uses **shiny-deckgl**, the toolkit already installed in the
  `shiny` micromamba env (1.9.2) and already used by the app
  (`components/grid_map.py`).
- It **replaces the broken NetCDF data type** on the Visualize page; it is not
  a new page: the "NetCDF (.nc)" choice of the Data Type select becomes the
  SHYFEM-results map, and its **Plot** tab shows the map.
- Time is navigated **both** with a **slider** (step through output records)
  and with **play/animation**.
- All four quantities: **water level, currents, salinity, temperature**.
- **Smoothness:** about **2–4 frames per second** is enough, including for
  users connecting from outside; the server patches the mesh colours each
  frame (no up-front transfer of whole variable-years to the browser).
- **Current arrows** appear only with variables from the same file as the
  currents (water level, current speed): **one view reads one file**. No
  pairing of hydro and ts files.
- **Files:** the viewer opens **any SHYFEM mesh output** -- a `.shy` or a UGRID
  `.nc` that shyelab can convert (hydro, ts, conz, eco, Post-process
  averages/min/max; checked 2026-10-27: `.lgr.shy` and the sample `.fvl.shy`
  do not convert and get a clear error) -- with
  the variables discovered from the file (names, units, fill values). Anything
  else (e.g. ERA5 forcing NetCDF on a regular grid) is refused with a clear
  message.
- **Who converts:** anyone who can open the file can view it. A `.shy` is
  converted once and the NetCDF cached **in the viewer's own home**, counted
  against their storage like their other files.

## Goals

1. Pick a run's output file from the active project and see one variable on
   the mesh at one time record.
2. Move through time with a slider, step back/forward buttons, and a play /
   pause animation with adjustable speed; the current date-time is always
   shown.
3. Scalars (water level, salinity, temperature, current speed) colour the
   mesh. Currents can additionally be shown as arrows.
4. The colour scale stays fixed while the time changes, so frames are
   comparable.
5. Work on real runs: the Curonian 29-box (1309 nodes, 2027 triangles, 1460
   six-hourly records for a year) must play smoothly; Mar Menor too.

## Non-goals (this version)

- Comparing two runs or two dates side by side (the Visualize *Comparison*
  tab for NetCDF is part of V-01 too; see "Left to the builder").
- Vertical profiles / 3-D sections. The Curonian setup is 2-D; 3-D runs get a
  layer selector (surface by default) and nothing more.
- Exporting videos or images (the map's own screenshot widget is enough).
- Regular-grid (non-SHYFEM) NetCDF files.
- Writing a new Python reader for the `.shy` binary format.

## Anti-goals (failure even if it "works")

- Animation that rebuilds the whole map every frame (flashing, resetting the
  view, seconds per frame).
- A colour scale that jumps every frame.
- Writing anything into a folder the user may only read (shared project,
  bundled samples) — the app's confinement rules apply (writes only where
  `confine_path(..., for_write=True)` allows).
- Silent wrong results: a failed conversion or an unreadable file must say so,
  not show an empty or stale map.

## Constraints and facts (checked on laguna)

- **Data source.** SHYFEM writes `<run>.hydro.shy` (water level, u/v velocity)
  and `<run>.ts.shy` (temperature, salinity), plus others (`fvl`, ...).
  `shyelab -outformat nc <file>.shy` converts to UGRID NetCDF: dims
  `nMesh2_node`, `nMesh2_face`, `Three`, `level`, `time`; variables
  `Mesh2_node_x/y`, `Mesh2_face_nodes`, `total_depth`, `water_level(time,node)`,
  `u_velocity`/`v_velocity(time,node,level)`; and for ts files temperature and
  salinity. NetCDF support was enabled in laguna's SHYFEM build on 2026-10-26
  (PR #139). shyelab always names its result `out.nc` (the Post-process page
  now renames such outputs `<input>.<op>.nc`, PR #147) and truncates long
  input paths (pass the file relative to its working folder; PR #147 does this
  in `ShyfemWrapper.run_shyelab`).
- **Coordinates.** Curonian mesh nodes are lon/lat; Mar Menor's are UTM
  metres. `grid_map.py` already detects geographic vs projected
  (`_is_geographic`, `_detect_projected_crs`) and transforms to lon/lat.
- **Map toolkit.** shiny-deckgl 1.9.2 has `simple_mesh_layer` (already used to
  colour mesh triangles by depth/quality/partition), `path_layer`,
  `scatterplot_layer`, `MapWidget.partial_update` / `patch_layer`, and
  `encode_binary_attribute` — so a frame can be a colour-array patch of an
  existing layer rather than a new map.
- **Sizes.** One Curonian frame is 1309 node values (or 2027 per-triangle
  colours); a year is 1460 frames.
- **Shiny pitfalls in this codebase** (see memory/gotchas): an input inside a
  re-rendering output loses its value; a sync effect cannot await
  `send_custom_message`; `Value.set` dedups by identity, so compare before
  set; an exception escaping an effect closes the session.
- **Access.** Admins may read and write any project folder; other users their
  own home plus shared projects (read). Run outputs of another user's project
  are readable by grantees but not writable.

## The how — decided so far

- The Visualize Data Type "NetCDF (.nc)" becomes **"SHYFEM results
  (.shy/.nc)"**; its file picker lists the project's `.shy` and `.nc` files.
- Loading a `.shy` converts it once with `shyelab -outformat nc` and caches the
  NetCDF; loading a `.nc` reads it directly. (My call: reuse SHYFEM's own
  conversion, now available, rather than a new binary reader.)
- The **Plot** tab shows a shiny-deckgl map of the mesh coloured by the chosen
  variable at the chosen record, built on `grid_map.py`'s existing mesh
  geometry and colour helpers.
- Controls (sidebar, replacing the broken NetCDF controls): variable, layer
  (only if the file has more than one), time slider over the records, step
  back / play-pause / step forward, speed, colour range (auto = the variable's
  min–max over the whole run, or manual), palette, and an "arrows" toggle for
  currents.

## Calls made by the designer (check these)

- Reuse SHYFEM's own `shyelab -outformat nc` conversion instead of writing a
  `.shy` reader.
- The end-to-end test with a real `.shy` **skips when `shyelab` is absent**;
  CI covers the data layer with a small committed UGRID `.nc` fixture. No CI
  workflow change.

## Left to the builder

- The cache layout inside the viewer's home and when an entry is stale (keyed
  on the source `.shy` path + size + mtime), and how cache size is bounded.
- Node-coloured vs triangle-coloured rendering, and how arrows are drawn and
  thinned so they stay readable when zoomed out.
- How the animation is driven (server timer with `invalidate_later` patching
  the layer, or client-side deck.gl animation over pre-sent frames) — as long
  as it meets the anti-goals.
- What the Comparison and Vertical Profile tabs show for SHYFEM results in
  this version (a clear "not available yet" is acceptable; they must not
  error).
- Whether the existing Plotly NetCDF code is deleted or kept for non-UGRID
  files (non-goal: it must at least not be what SHYFEM results reach).
- Tests: unit tests for the data layer (conversion, caching, frame extraction,
  colour scaling) and an end-to-end test that loads a real `.shy`, moves the
  slider and plays a few frames.
