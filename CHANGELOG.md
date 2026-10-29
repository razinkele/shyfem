# Changelog

All notable changes to the SHYFEM project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Fixed — shyfem-ui
- **Visualize: the NetCDF data type is now "SHYFEM results", and it shows the results.** It opens a `.shy` file (converted once with shyelab and cached in your home, or the work folder when run locally, so the next load is immediate) or SHYFEM NetCDF, and shows the variable on the mesh map with a time slider, play/pause, a legend and, for a file with currents, optional current arrows. It replaces the plot that failed with "list index out of range" on every SHYFEM NetCDF file. The Vertical Profile and Comparison tabs say they are not available for SHYFEM results yet; Statistics shows the colour range of the variable on the map and the units of all variables. A Load that fails (a conversion error, or a file that is not a results file) says so and keeps the file already on the map. (V-01, 2026-10-19 UI review)
- **Jobs, local queue (the production default): a run no longer dies when the last browser tab closes.** Shiny Server stops an idle worker 5 s after its last connection, and the job ran inside that worker, so the shutdown killed `shyfem`/`mpirun` and recorded "Job was cancelled", with no email. A run only survived while some session kept the worker alive. Each job now runs under a small supervisor process (`python -m shyfem_ui.job_runner`) in its own session. The supervisor writes the tool's output straight to the job's `.stdout`/`.stderr` files, records the exit status, and ends the job's row and sends the email itself, even when no worker is running. The worker only watches the files; a worker stopping leaves the run alone. A user's cancel still kills the run. The supervisor's bookkeeping sits next to the logs as `<job>.job`, `<job>.pid` and `<job>.exit`; it is left out of exports and removed with the job. (J-01, 2026-10-19 UI review)
- **Jobs, restart:** a worker that starts while jobs are running watches them again instead of marking them "orphaned at server restart". This also covers the `restart.txt` overlap, where the previous worker is still serving (J-08). A job whose supervisor left an exit record but died before ending the row is reported from that record. Only a job with no live supervisor and no record is marked orphaned.
- **Runs and tools that stopped on an error no longer report success.** gfortran's `stop 'message'` exits with status 0, and the UI used the exit status alone, so a missing basin, an STR line over 80 characters, an end time before the start, or a flag a tool does not have all showed as COMPLETED or "completed successfully". A run now also fails when its output contains `STOP error stop`, `*** no such option` or `STOP clo_usage`, or, for shyfem, when it never printed its `simulation end:` line. The failure message names the line that stopped it. This covers jobs, workflows and the tool pages (Grid Prep, Partitioning, Post-process, Mesh Builder). Under `mpirun` only errors after MPI start-up exited non-zero before; STR and basin errors did not. (X-01, 2026-10-19 UI review)
- **Physics page: Save no longer changes physics nobody edited.** Panels showed `value or default`, so an explicit `0` showed as the default (`ilin = 0` as 1, `aapar = 0.` as 1.0, also `albedo`, `zfact` and others), and Save wrote every shown value back. A save with no edit therefore turned `ilin = 0` into `ilin = 1` (20 shipped STRs have `ilin = 0`) and added absent parameters at their defaults. Save now writes only the fields whose value differs from what the panel showed. An untouched parameter keeps its value and spelling, and an absent one stays absent; the meteo-output checkboxes (`imetout`) and the assimilation blocks follow the same rule. A select whose stored value is not one of its options (`iclin = 1.`, shown as "1.0") no longer shows the first option, which Save wrote back (`iclin = 0`). Every panel now re-renders on Load and Save, even while collapsed; a collapsed panel kept the previous file's values and Save wrote them into the new one. With every panel open and no edit, every shipped testcase STR saves back byte-identical. A panel that cannot show the loaded file (for example `vismol = 1.d-6`) now says so, and Save skips its fields; before, it kept the previous file's values and Save wrote them in. `idtsyn` and `idtlgr` are now text fields, because shipped STRs write them as intervals (`'1h'`), which broke the Hydrodynamics and Lagrangian panels for 23 of them. (S-01, 2026-10-19 UI review)
- **Physics page, Boundary Conditions:** opening the panel and saving no longer appends an unnumbered `$bound` section. The core stops on that section (`bnd: ibc out of bounds`). The panel cannot write `$bound1`, `$bound2`, … so an edit there is refused with a message pointing at the STR editor. The Physics page and the STR editor's Validate both reject an unnumbered `$bound`, and the editor's "insert section" template now inserts `$bound1`. (S-02)
- **Physics page, Lagrangian panel:** opening it and saving no longer writes `ilagr` into `$para`. `ilagr` belongs to `$lagrg`, and the core stops on it in `$para` (`nls_insert_variable: wrong section`), so the saved STR could not run.
- **Physics page:** `idtcon` and `icon_av` appear in two panels, and the copy that was not edited no longer overwrites the edited one. When the two copies hold different edits, the save is refused (S-08). Restart mode `ityrst` and boundary `intpol` now default to 0, the core's default (they were 1). The `intpol` choices are now the core's: 0 auto, 1 stepwise, 2 linear, 4 cubic (S-10). Text fields show a run of numbers (`sedgrs = 0.1 0.2 0.3`) as written, not as `[0.1, 0.2, 0.3]`.
- **Files: "Seed Tutorial Files" no longer overwrites a project's files.** Imported, cloned and new tutorial projects got no file rows, so the Files page listed nothing, showed 0 B, and offered the seed button; seeding then copied the tutorial over same-named files such as an edited `mm_hyd_00.str`. Seeding now refuses any project that has a file row or a project file on disk, and the button shows only for an empty project. Import, clone and the new Mar Menor tutorial project now register a row for each project file (the same files an export ships), so they are listed and count against the project storage limit; an import or clone over that limit is refused. This counts everything copied, run outputs included, which a project's own runs do not add to its usage, so a large project with big outputs may now be too large to clone. Import no longer extracts job logs and bookkeeping files (`.stdout`, `.stderr`, `.job`, `.pid`, `.exit`, `.project_summary.json`); they got no row, so they used disk space the limit did not see. A file type the user chose (for example `boundary`) now survives export, import and clone. Projects created before this fix still have no rows. (F-01, 2026-10-19 UI review)
- **Mar Menor tutorial project: the name no longer chooses where the copy lands.** The typed name was joined to the shared work folder and the tutorial copied there, so a name such as `../../somewhere` or `../users/<other user>/x` put a copy outside the work folder or in another user's home; any signed-in account could do it. The name must now be one plain folder name, without `/`, `\` or a leading `.`; anything else is refused with a message, not rewritten. In server mode the project now goes in its owner's home like other new projects. Before, it went in the shared work folder, where its owner's file pickers could not reach it. A folder or link that already has the name is refused, not followed. (H-03, tutorial half of F-02, 2026-10-19 UI review)
- **Admins can open every project's files.** An admin's Dashboard lists every project, but the file pickers only reached the admin's own home and projects shared to them, so another user's project showed "Project directory unavailable" (for example Grid Prep on the admin-owned Curonian 29-box, for a second admin account). Admins may now read and write any project folder under the user data root or the shared work folder, and nothing outside them or in the bundled examples. An admin can therefore run a model in another user's project; the run's outputs land in that project's folder, next to the owner's, under the STR's run name.
- **Simulation page, STR editor: the inline Save no longer writes into a project you can only read.** Load checks a file for reading, and Save checked only your role on the active project, so a file opened from a project shared to you as viewer (picked from the browser console), could be overwritten. The inline Save now checks the file as a write target, like Save As and the Physics Save (your own home; for an admin, any project folder); otherwise it says to use Save As.
- **Run page: progress and status now update while a run is going.** Two faults stacked. The progress parser looked for a `time = X of Y` line that shyfem never prints, so progress stayed at 0 % until the end; it now reads shyfem's per-step line (`<date> <seconds> <dt> <it> / <nits> <pct> %`) (R-05). And the local job queue handed the page the same job objects it updated in place, so the page's change check compared each job with itself and never redrew: the status badge, progress bar, history and job details stayed as first shown (R-04). The queue now returns copies. The "Continue from job" choice now survives the refreshes this enables (J-07).
- **Run page: the job log is readable.** Bootstrap colours `<pre>` text black in the light theme, so every plain log line was black on the log's dark background; only the coloured warning, error and step lines showed. The log text now uses the viewer's light colour.
- **Post-process and Visualize: a finished run's output files appear in the file pickers without a reload.** The pickers were built once per project, so one opened before a run ended kept showing no files. They now relist whenever a job finishes, and keep the file you had picked.
- **Post-process: "Convert to NetCDF" no longer reports success when nothing was written.** A SHYFEM build without NetCDF support prints "NETCDF support has not been enabled" for `shyelab -outformat nc`, writes no file, and exits 0; that now counts as a failure, with that line as the reason.
- **Clone: in server mode a cloned project goes in its owner's home,** like new and imported projects. It went in the shared work folder, where the owner's own runs, saves and tool outputs were then refused as "outside your home directory". Existing clones stay where they are. (F-02, 2026-10-19 UI review)
- **Admin: the last active admin can no longer be demoted, deactivated or deleted.** With one admin, a single click on "demote" or "deactivate" left the site with no admin: after a demotion the next app start failed for everyone (`Username already exists: admin`), and after a deactivation nobody could sign in as admin again. The Admin page now refuses the change and says to make another user an admin first; a deactivated admin no longer counts as one. If the database already has no active admin, the app restores the configured admin account at start-up (its password unchanged) instead of failing. (SEC-01, 2026-10-19 UI review)
- **Admins can open every project's files.** An admin's Dashboard lists every project, but the file pickers only reached the admin's own home and projects shared to them, so another user's project showed "Project directory unavailable" (for example Grid Prep on the admin-owned Curonian 29-box, for a second admin account). Admins may now read any project folder under the user data root or the shared work folder, and nothing outside them. Writes still go only to the admin's own home, so an output folder inside another user's project is still refused.
- **Simulation page, STR editor: the inline Save no longer writes into a project you can only read.** Load checks a file for reading, and Save checked only your role on the active project, so a file opened from a project shared to you as viewer (picked from the browser console), or, for an admin, from any project, could be overwritten. The inline Save now writes only into your own home, like Save As and the Physics Save; otherwise it says to use Save As.
- **Create Project: the folder must be one plain folder name in your home.** Typing `/` as the project folder made your whole home the project's folder; sharing that project then let the other user read every project you have. Typed paths such as `../x` were quietly turned into `x`. In server mode the folder name is now taken as typed and must be one plain name (no `/`, `\` or leading `.`); picking one of your existing folders still reuses it, but a link or a file is refused. A name over 255 bytes no longer closes the session, and errors no longer show server paths. (H-08, 2026-10-19 UI review)
- **Run page, "Continue from job": a continuation now runs and leaves the run it continues alone.** The derived STR kept the source's run name, so its outputs overwrote the source run's files in the same folder, including the restart file it read (J-02). It also kept the source's end time, so the continuation had nothing to run, and wrote the restart file's full path, which could exceed the core's 80-character line limit (R-03). A continuation now gets its own run name (`<name>_c1`, `_c2`, ...), starts where the source ended, runs to the new **Continue until** date (required), names the restart file relative to the run folder, and is checked like any STR before it is submitted. (J-02, R-03, 2026-10-19 UI review)
- **Dashboard: every project you can see is listed.** The list stopped at the 10 most recently updated, and the Dashboard is the only place to open a project, so an 11th project could not be opened again; the "Projects" count also stopped at 10. (H-01, 2026-10-19 UI review)
- **Post-process: the operations run.** The page sent shyelab options that do not exist (`-ts`, `-taver`, `-minmax`, `-res`, `-layer`, `-<variable>`), and "Spatial Average" sent the time average. Each operation now uses shyelab's real option: Basin Average (`-averbas`), Time Average, Minimum and Maximum over Time (`-aver`/`-min`/`-max` with `-out`), Residual Currents (the time average of a hydro file), Split by Variable, Convert to NetCDF, and Extract Time Series (`-node`, with a new Nodes field, e.g. `1823` for Klaipėda). The variable and layer pickers are gone (shyelab has no such selection). shyelab's real outputs are now found (`.shy`, `.fem`, `<var>.0d.0`, `<var>.2d.<n>`), so the page no longer says "0 files" after a run that worked, and its `out.shy`/`out.nc` results are renamed after the input and the operation, so preset steps and batch files no longer overwrite each other. A long file path no longer makes shyelab stop with "file not existing". (V-02, V-03, 2026-10-19 UI review)
- **Post-process: the Time Series Preview shows shyelab's series.** It looked only for `.ts`, `.ext` and `.csv` files, which shyelab never writes, so the tab stayed empty after every run. It now shows the series that Extract Time Series (`<var>.2d.<node>`) and Basin Average (`<var>.0d.0`) write: water level first, then salinity, then temperature, then the rest. The page reads them with the shared time-series reader, so the first record is kept, the `date::time` stamps become a real time axis, and the columns take the names in shyelab's `# date …` header (`minimum`, `average`, …). The `Infinity` that Basin Average writes for an undefined average is now shown as a gap. Vertical profiles (`.3d.<n>`) are not offered. (V-07, 2026-10-19 UI review)
- **Mesh Builder, Partitioning and Grid Prep: loading files no longer freezes the app.** Importing a boundary, loading bathymetry points or contour isobaths, loading a grid on Partitioning, and the Grid Prep Inspect statistics all ran while the app waited, so every user on that worker stopped responding for as long as they took. They now run in a background thread. (M-11, 2026-10-19 UI review)
- **Grid maps: faster, no freeze, and your zoom stays.** Drawing a large grid took the app 1-3 s on a 50,000-node mesh, and every user on that worker waited; any change of view mode, palette or basemap redrew everything and re-centred the map, losing your zoom. The map is now built in a background thread and about 3x faster (Depth on 50,000 nodes: 2.7 s to 0.9 s), a basemap change only swaps the background, and the map re-centres only for a new grid, a new projection, or a switch to or from 3-D. (V-06, 2026-10-19 UI review)
- **Uploads: two at once into one project can no longer both pass the storage limit.** With uploads moved to a background thread (F-05), two uploads into the same project at the same moment could each pass the storage-quota check before either was written. Uploads into one project now take turns from the quota check to the save.
- **Dashboard and Admin: Clone, opening a project, Details and the test email no longer freeze the app.** Cloning copied the whole project, opening a project and its Details scanned it for the project summary, and the admin "send test email" waited on the mail server, all while the app waited, so every page of every user on that worker stopped responding meanwhile. That work now runs in a background thread, and an opened project shows before its summary is refreshed. (H-07, 2026-10-19 UI review)
- **Files and Grid Prep: uploads no longer freeze the app.** The Files page read, checksummed and wrote an upload (up to 500 MB) while the app waited, and Grid Prep parsed an uploaded grid the same way, so every page of every user on that worker stopped responding until it finished. Both now do that work in a background thread. (F-05, 2026-10-19 UI review)
- **Files and Export: downloads no longer freeze the app.** A file download read the whole file, base64-encoded it and sent it to the browser down the websocket; a project export did the same with its ZIP (up to 2 GiB). While a large file was encoded, every page of every user on that worker stopped responding, the transfer was a third larger than the file, and each file download left a copy of the file in the page. The page now checks access as before and gives the browser a one-time link, and the browser fetches the file over HTTP, streamed in chunks. (F-06, F-07, 2026-10-19 UI review)
- **Database start-up: an older unversioned database is no longer marked current.** A database built without Alembic (`create_all`, as a pip install without Alembic does) has no `alembic_version` table. Start-up stamped any such database as the latest revision, so the migrations it lacked never ran, and the app later failed on missing tables or columns. It now stamps only a database that already has every table and column of this release. Otherwise start-up stops with a message that names what is missing and how to stamp the right revision. Databases that already carry a version (the laguna one does) and new empty databases start as before. (D-02, 2026-10-19 UI review)
- **Grid files: a line whose node list starts with node 1, 2 or 3 is read whole.** SHYFEM writes a line (or a long element) as a header, then rows of six node ids. The UI's GRD reader took any row starting with 1, 2 or 3 as a new record. So a row starting with node 1 replaced node 4's position and depth with the row's ids, and a row starting with 2 became a phantom element. In both cases the line lost those nodes. SHYFEM's own reader takes the rows after the header as ids until it has them all, and the UI now does the same. A depth after the last id of a continued element is now kept. One real case: `curonian/shyfem_box/line_boxes.grd` read 28 of its 29 lines plus an element that is not there; it now reads 29. (M-06, 2026-10-19 UI review)
- **Grid Prep: the shybas check runs.** It passed `-quality -info`, but shybas has no `-info` option (it prints the basin info by default), so it stopped with "no such option: info". Since the X-01 fix that showed as "shybas failed (exit code 0)". It now passes `-quality`, and prints the basin summary and the grid quality table. (M-02, 2026-10-19 UI review)
- **Jobs: shyelab progress no longer looks for a line shyelab never prints.** The pattern `processing record N of M` was invented. shyelab prints no record counter and no total, so a shyelab job now reports no percentage instead of a 0 % that never moved. (R-05, the shyelab half)
- **Ensemble: members run.** Each member runs in its own folder two levels below the base STR, where the base STR's relative paths (the basin, the forcing and boundary files) no longer resolved, so every member stopped at once. Each relative path that exists next to the base STR is now rewritten to reach it from the member's folder (the basin with its `.bas` extension, which the core needs), `boxes.txt` (read under that fixed name) is copied in, and each member's STR is checked as it will run. (R-02, 2026-10-19 UI review)
- **Time series without a header row keep their first record.** A file whose first line is already numbers (comma-, semicolon- or space-separated) lost that line to pandas' header detection, and its columns were named after the first record's values. A numeric first line is now data, with columns `col0`, `col1`, …, as the plain whitespace reader already did. SHYFEM's own `date::time value` files were not affected. (V-04, 2026-10-19 UI review)
- **Partitioning: shyparts runs and its results are shown.** The page passed the basin and an option that does not exist (`-weighted`, which makes shyparts print its usage); shyparts partitions a `.grd` (`shyparts -np N grid.grd`). It now runs on the selected grid, the basin picker and the "weighted" checkbox are gone, and the load-balance chart and map read shyparts' real output, `<grid>.<N>.elem.grd` (the page looked for `.par` files shyparts never writes). The partitioned grids, written next to the input grid, are moved into the chosen output folder. A run that ends with shyparts' "connectivity errors ... (errors can be ignored)", exit status 9, is no longer reported as failed. (M-01, 2026-10-19 UI review)
- **Mesh Builder, "shybas" bathymetry method: it now interpolates.** The loaded bathymetry was never given to shybas (the page passed a file name that did not exist), and the result was looked for under a name shybas does not write, so the mesh came back unchanged while the page said "Bathymetry interpolated". The points are now written in the form shybas reads (a GRD of depth points, without comment lines), shybas interpolates on the mesh nodes, and its result (`basbathy.grd`) is read back. It runs in a private temporary folder instead of a folder shared by all users, and if shybas produces nothing the page shows shybas's own message instead of claiming success. (M-03, 2026-10-19 UI review)
- **Mesh Builder, bathymetry (RBF and Clough-Tocher): dense isobaths are no longer thinned to a few points.** Near-duplicate points were removed by rounding coordinates to 2 decimals, which in the degree coordinates these methods always get is about 1 km: a 200-point isobath kept 31 points and a 400-point one 4. Only points within a few millimetres of each other (relative to the data's extent) are now merged. (M-04, 2026-10-19 UI review)
- **Jobs, failure message:** a failed job's message and its email now show the end of stderr, where the tool prints its fatal error, instead of the first 1000 characters (J-10).

---

## [8.5.2] — 2026-10-18

A core fix release. The main fix changes results for every 3D run with a
flux (`ibtyp=2`) or point-source (`ibtyp=3`) boundary, such as a river,
made since 2026-02-11. The vertical velocity had been zeroed at those
nodes, which broke their vertical mass balance; some runs blew up at the
source. GOTM also takes its bottom roughness from `czdef` under
`ireib=6`. Tagged `v8.5.2`.

### Fixed
- **Model, 3D flux and point-source boundaries (changes results for 3D runs with `ibtyp=2` or `ibtyp=3` boundaries since 2026-02-11):** the vertical velocity is zeroed only at level boundaries (`ibtyp=1`) again, as upstream does after its 2010 fix for `ibtyp=2`. Commit `4ae5c575` (shipped in #5) zeroed it wherever `iopbnd(k) > 0`, which is every boundary node, flux and point-source nodes included. Those boundaries enter as nodal volume sources that have to close through w, so the change broke the vertical mass balance there. In `mar_menor`, `mm_hyd_41`, `42` and `43` ran away at the river node within 4–5 hours (salinity 88, temperature 100 °C) on every version since. They run their full period again, and the CI battery is unchanged. Found by bisecting from v8.1.1, where the case ran.
- **Model, GOTM turbulence (changes results for `ireib=6` runs with `iturb=1`):** GOTM's bottom roughness length is now the one the momentum friction uses under `ireib=6`: an area-weighted node average of each element's roughness (`czv`, from `$area`, `czdef` by default). It used to be `z0bk`, which only the fluid-mud option (`ireib=9`) sets, so it stayed at the initial 0.9 mm whatever `czdef` said. The effect is negligible with GOTM's default Neumann wall conditions: no measurable change in the `channel_turb` benchmark. No shipped test case uses `ireib=6`; `venlag_smoke` and `mm_hyd_00` are byte-identical. (k-ε vs GOTM benchmark, decision 4)


### Changed
- **Turbulence, documentation:** GOTM (`iturb=1`) is recommended over the built-in k-epsilon (`iturb=2`) for 3D runs. In the `channel_turb` benchmark, `iturb=2` gives 1.5x the log-law eddy viscosity near the bed, against GOTM's roughly 0.8x (`docs/reviews/2026-10-18-keps-vs-gotm-benchmark.md`; redesign tracked in #125). A 3D run with `iturb=2` prints a start-up warning saying so, and each shipped `gotmturb.nml` now has a header saying which closure it configures. (#124, #126)
---

## [shyfem-ui 0.7.2] — 2026-10-18

Server (Celery) mode: a cancelled job now ends cancelled. Tagged
`shyfem-ui-v0.7.2`. The default local job queue is unchanged.

### Fixed — server (Celery) mode
- **Cancel:** a cancelled job reappeared as "running" after the cancel, and the lost-job reconcile later labelled it "lost". Cancelling revokes the task, which makes Celery stop the worker process with `SystemExit`. The run itself was stopped, but the task's cleanup wrote the job's old RUNNING status back over the cancel. It now records CANCELLED, in Redis and in the database, and sends no email. (#122)
- **Cancel vs. a worker stop:** a cancel is now told apart from the worker stopping the run on its own (a shutdown, for example) by a cancel marker written before the revoke. The job record can't be used for this, because the worker rewrites it on every progress line. A run stopped by its worker ends FAILED, "stopped: its Celery worker interrupted the job", and the user gets a failure email. A job cancelled while it is still queued is never started. (#122)
- **Robustness:** a Redis error while recording the end state no longer leaves the job "running", and the database row and the email still go out when Redis is down. (#122)

---


## [8.5.1] — 2026-10-17

A core fix release. Two fixes change results: k-epsilon (`iturb=2`) runs
work at all and use the right epsilon boundary condition, and decimal input
values are parsed exactly (a round-off-level change in every run). The rest
are clean aborts, restart-reader correctness and build checks. Tagged `v8.5.1`.

### Fixed
- **Model, turbulence (changes results):** k-epsilon (`iturb=2`) runs no longer die with SIGFPE at the first time step. `keps_shell` passed the density *anomaly* ρ′ to `keps` as ρ, which divides stress by it: 0/0 with `ibarcl=0`, a negative base under `**1.5` in water lighter than `rowass`. It now passes `rowass + rhov`, as `model3d_util` and `substress` already do. (#97)
- **Model, turbulence (changes results):** the k-epsilon epsilon boundary condition had the wrong units (`u*³·dh/κ` instead of `u*³/(κ·dh)`), because `dzk` already holds `1/dh`. Plus behaviour-neutral fixes on the same path: `n2` boundaries read uninitialised, an out-of-bounds `dzr(lmax+1)` write, `intent`s and bare `stop`s. (#98)
- **Model, input parsing (changes results at round-off level):** decimal numbers in STR and other input files are parsed exactly. `istod` scaled each fractional digit by a single-precision `0.1`, so every value with a decimal part was off by about 1.5×10⁻⁸ relative (`0.3` read as 0.30000000447). (#102)
- **Model, restart:** a truncated or unwritable restart file now aborts with a clear message instead of a Fortran runtime error. Every bulk payload read and write in `mod_restart.f90` and the skip reads in `rst_skip_record` check `iostat`. Also: the `is_offline` guard could never fire, and `dts_get_init_0` never set the minute. (#103)
- **Model, restart tools:** `rstinf` and `rst2shy` no longer overrun their skip buffers on a mesh with more nodes than elements; the `wlnv` record is read as a slice. (#110)
- **Model, restart:** a model built without EUTRO, reading a restart that carries eco data, used to skip none of those records and desync every later read; it now aborts with a clear message. The mercury reader skips its section correctly, the skip reads check `iostat`, and an abort before `MPI_Init` (as in `rstinf`) exits cleanly with code 33. (#111)
- **Model, WaveWatch III coupling (`WW3=true`):** the 29 allocations check their status before touching the array; the never-assigned `tramp` is defined as 0 (off, as in `waves_admin`); the stale `use shympi_aux` that stopped a `WW3=true` build is replaced. Not exercised by CI, which builds without WW3. (#114)

### Changed
- **Build:** `SOLVER=GAUSS`, `PARDISO`, `PARALUTION` and `PETSC_AmgX` are rejected with a clear message: their shared backend `simsys_lp.f90` no longer builds. Use `SPARSKIT` (the default) or `PETSC`. (#101)

---


## [shyfem-ui 0.7.1] — 2026-10-17

A fix release: open sessions now follow account changes, the STR editor keeps
what you type, a failed run no longer leaves its simulation running, and server
(Celery) mode gets job reconciliation, a worker that can start, job emails and a
real `/health` count. Tagged `shyfem-ui-v0.7.1`.

### Security
- **UI:** a role change, deactivation or logout now reaches sessions that are already open. The WebSocket identity was validated once at connect, so a deactivated editor could keep saving and a demoted admin kept admin rights until they reloaded. It is now re-validated at every decision, admin checks no longer fall back to the connect-time identity in server mode, and admin actions are audited under the live user. (#99)
- **UI:** a password reset signs out the user's open sessions and WebSocket tokens, so a tab or a stolen cookie from before the reset stops working. (#100)
- **UI, Run page:** workflow history is scoped per user. Every user's workflow IDs and names were listed to everyone; now each user sees their own, and an admin sees all only with the "All jobs" switch on. (#106)

### Fixed
- **UI, simulation runs:** a run that fails while its output is being read no longer leaves the simulation running. A failing log write (a full disk), a failing progress update, or an output line over 64 KiB used to report the job failed but never stop the shyfem/mpirun process group. Now the whole group is stopped, a failed progress update is logged once and the run continues, and the failure message keeps the tool's own error output. (#119)
- **UI, STR editor:** the raw text pane no longer empties itself. It sat inside a render that re-ran on every re-parse, so Apply's own echo replaced it with an empty box about 40 ms later, and a loaded file never reached it. (#108)
- **UI, STR editor:** Apply works on a copy, so a refused value no longer leaves the file half-edited; the parameter search box keeps its text; and a field hidden by the search is no longer written back over a newer value. (#109)
- **UI, Dashboard:** the project list follows a live deactivation, demotion, share or unshare within about 10 s, instead of only after a reload. (#112, #113)
- **UI:** a sign-in token is no longer lost to a race with Shiny's start-up. When the identity check answered before Shiny was ready, the token was dropped silently and the session stayed signed out (no projects, no Share button) until a reload. Static assets also get their own rate-limit bucket. (#107)
- **UI:** workflow rows a restarted server left "running" are reconciled to failed at start-up, and finished workflows are pruned with the job retention window. (#104)
- **UI:** a database migration can no longer silently switch off app logging; the trusted-proxy setting is pinned by a behavioural test. (#105)

### Fixed — server (Celery) mode
These paths are not used by the default local job queue.
- **Lost jobs:** a job whose Celery worker was killed mid-run stayed "running" forever and was never cleaned up. Each worker now records its name on the job, and a job is marked failed only when that worker replies, twice in a row, without it; a silent worker, a name two workers share, or no reply at all is never taken as evidence. (#115)
- **Worker start:** the documented `celery -A shyfem_ui.services.job_celery worker` could not start a worker at all; it now finds the app. (#116)
- **Job emails:** Celery workers never sent completion emails. A worker now builds its email service from its own config and logs which mail server and database it uses. (#117)
- **`/health`:** reports the real active-job count instead of `-1`, without blocking the app on Redis, and returns "degraded" (503) within 3 s when Redis is unreachable. A flood of `/health` requests shares one bounded probe. (#118)

---


## [shyfem-ui 0.7.0] — 2026-09-28

Completes the Box model analysis feature: a project's manifest and its raw
output records are both reachable from the page now, and the app finally says
what it is doing in the worker log. Tagged `shyfem-ui-v0.7.0`.

### Added
- **UI, Box model page:** a **Manifest** tab that creates and edits the project's `boxmodel.json`, which until now had to be written by hand before the page could be used at all. Every path is a dropdown, the runs are a table with add and remove, and a run directory may be picked from the admin-declared analysis roots as well as from the project, because a run usually lives outside it. Saving validates the document first and writes only if it parses, so a rejected edit never reaches the file; the write keeps an indent, keeps keys the form does not know about, and rewrites nothing it was not asked to — a path inside the project is stored relative so the manifest stays portable, one outside it stays absolute.
- **UI, Box model page:** the cache can now be built with the model's raw output records ("Include output-step detail"), and the Map and Time series use them inside a window of up to 31 days: the day slider becomes a time slider stepping by the run's own output step, and the series plots the records themselves instead of daily means. Off by default, because the raw frame is several times larger than the daily one and counts against the project's storage quota. A run without it, or a wider window, behaves exactly as before. Closes the last deferred item of the Box model feature (spec §8).

### Fixed
- **UI:** the app configures its own logging where it is built, so INFO reaches the worker log in production. `logging.basicConfig` sat inside `main()`, which only runs for `python -m shyfem_ui.app`; Shiny Server imports the app and calls `create_app()`, so the package was never configured at all and every INFO breadcrumb — cache reconciles, project opens, build starts — was dropped, while warnings still reached stderr through Python's last-resort handler, which is why nothing looked wrong. The level comes from the new `SHYFEM_UI_LOG_LEVEL` setting. (#94)
- **UI, Box model page:** opening the page no longer reads the whole raw-record frame into the worker. The published Curonian caches already carried `state_hourly.parquet` (183–207 MB), and `load_cache` materialised it on every session — 6,100,440 rows, about 250 MB, at the head of the page's expensive chain, for data nothing displayed. Only the visible window is read now, which the builder's per-day row groups make cheap: 20,909 rows in 0.33 s for a 31-day window on the 22-year run.

---


## [shyfem-ui 0.6.0] — 2026-09-27

Closes the Box model analysis feature and hardens the paths it added. Tagged `shyfem-ui-v0.6.0`.

### Fixed
- **UI, Box model cache:** a slow build could have its own output directory deleted while it was still running. The build child refreshed `progress.json` only every 500 records, and that file's age is the only liveness signal another worker has, so one long step -- a large Parquet write, the `run.log` tail -- could stay quiet past the 90 s reaper window and another session's page load would remove the directory, losing the whole build. The child now beats from a daemon thread, and because a *hung* child would beat forever, the reaper gained an absolute age cap derived from the configured build timeout. Four more in the same path: a short row in `boxes_stats.txt` was silent (pandas NaN-padded it, so a box was cached with no volume or depth) and is now named with its file and line; the project storage quota counted one run twice during the two-step publish, and charges each run once at its largest copy; a foreign or hand-edited cache raised out of a reactive calculation instead of becoming a message on the tab; and the grid is parsed once for the map and the box outlines instead of once each. (#92)
- **UI:** two custom messages the server sends were built and never sent, because `send_custom_message` is a coroutine and both call sites were synchronous reactive effects. The "go to this page" buttons on the Dashboard and the Tutorial therefore did nothing, and the what's-new modal came back for every user on every visit, intercepting the first click on the page until dismissed. (#93)
- **UI, STR parser:** `services/parser_str.py` silently misread real SHYFEM parameter files (#86). A run of numbers was truncated to its first token, so `kbound = 1855 1856 1882 1883` parsed as `1855` and boundaries lost most of their nodes; `&para … &end` sections and headers carrying trailing text (`$bound1     ---- Baltic sea ----`) were dropped entirely, which on the Curonian 29-box STR meant only 4 of its 11 sections parsed and the Physics page and STR editor showed no timing parameters and no boundaries for it; and a numbers-only continuation line was ignored. All four are read as SHYFEM reads them (`nls.f90`), the text after a section name is exposed as `StrSection.header_extra`, and `generate(parse(text))` is now byte-exact on that file and on every `testcases/examples/mar_menor/*.str` — none of which round-tripped before, because a blank line was appended after each `$end`. A parsed value is shown in a form field through `format_param_display` and read back through `parse_param_display`, its inverse: the STR editor's Form view, the Physics panels and the boundary editor each showed a value run as a Python list and wrote it back quoted, which the core rejects — in the Form view's case with no user edit at all.

### Added
- **UI, Box model page (PR 4 of 4, closes the feature):** the Curonian onboarding bundle script (`shyfem_box/export_ui_bundle.py` in the Curonian repo) and a committed cross-check of the package's skill metrics against that repo's reference scripts; admin onboarding docs. Project **import** now skips every member under `.boxmodel_cache/` and leaves them out of the archive size and file-count budgets, so a stale cache can neither be planted on disk nor spend the importing project's budget (the export side landed in PR 1).
- **UI, Box model page (PR 3 of 4):** the **Setup** tab — mesh with box outlines and section interfaces, open-boundary and river nodes from the STR `$bound*` `kbound` lists (coloured by `ibtyp`), a boundaries table with `zfact` and file names, river series from the `.txt` files named by `boundn`, per-box meteo from the cache, and an STR summary — built on a tolerant STR reader (`services/boxmodel_setup.py`) that accepts the real Curonian STR (`&para`, trailing header text, multi-pair lines, multi-line `kbound`, prose between sections) and lists orphan keys SHYFEM ignores. Closes the PR 1 deferral of section-interface lines.
- **UI, Box model page (PR 2 of 4):** the **Compare** tab — two to four runs from the manifest, a difference map (B − A of the period mean, diverging scale), overlaid daily series for the selected box, the skill table side by side per run plus the per-year table and a CSV download, all on the intersection of days the runs share. The build registry now lives in the cache service and the CLI/service share their atomic-JSON, run-id and symlink guards through `shyfem_ui/boxmodel_common.py`.

### Changed
- **UI:** every file/directory path box is a dropdown over the active project's directory (`components/project_select.py`); free text remains only for new names and STR-content fields (#79)

---


## [8.5.0] — 2026-09-18

### Added

- **Box model page (PR 1 of 4)** — analyse SHYFEM `idtbox` box output in the Workbench: a project `boxmodel.json` manifest (grid, box polygons or dissolved-from-grid boxes, forcing, runs, observations), a per-run Parquet cache built by a child process (`python -m shyfem_ui.boxmodel_cache_cli`, cache bytes counted against the project's storage quota), admin-declared read-only `SHYFEM_UI_ANALYSIS_ROOTS` for run output kept outside the per-user sandbox, box polygons on the map coloured by value/period mean/bias with a day slider, and per-box time series with observations and a skill table (bias, RMSE, r, R², sd ratio) as defined by the Curonian comparison scripts. Adds a `pyarrow>=15` dependency for the cache. Compare and Setup tabs follow in later PRs.
- **3D data assimilation completed** — the `$assimil` framework now works in 3D runs: the new `layer` and `vcorlength` section parameters place the observation on a model layer and spread the optimal-interpolation analysis increment over the water column with Gaussian vertical weights (`layer = 0` or `vcorlength = 0` applies it uniformly); applied per node only over existing layers. The 2D code path is byte-identical to before (verified by output fingerprint, serial and MPI). New 3D smoke test on the Venice lagoon shows the expected vertical localization; local overshoot near a deep mixing station is documented as inherent to increment spreading (`assimil.f90`, `assimil_admin.f90`, test case `venlag_assim.str`)
- **Beaching rates configurable from the STR** — `ibeach = 3` reads the per-area-code beaching/burial rates from the new `beachrate`/`burryrate` array parameters (one value for all area codes, or exactly one per code), so the algorithm works on any grid without code edits; the hardcoded Curonian/Danube presets (`ibeach` 1/2) remain. Negative rates are rejected, and a wrong value count aborts with a clear message. Verified bit-identical to the Danube preset on mar_menor, serial and MPI (`beaching.f90`, `def_para.f90`, test case `mm_hyd_beach_str.str`)

### Fixed

- **Saving an STR file with repeated sections no longer destroys the earlier blocks** — a `.str` may legitimately repeat a section (e.g. two `$color` colour tables; the core reads all of them), but the UI parser kept one entry per section name and re-emitted the survivor at every position, so a save through the physics or STR editor silently replaced the earlier blocks' content with the last one's. Every block is now written back as parsed; lookups and edits resolve to the first occurrence, and the `$nduge` purge drops every occurrence. (#70)

### Changed

- **UI CI runs on the shiny the laguna worker runs** — `shyfem-ui/environment.yml` pin raised from `shiny>=1.6,<1.7` to `shiny>=1.8,<1.9` (the worker's conda env is 1.8.0), so CI stops validating a version prod no longer uses. The cap stays: bump it deliberately when the worker env moves, after running the suite with `PYTHONNOUSERSITE=1` against that env.
- **Topbar About/Changelog split per package** — The About and Changelog topbar buttons are now dropdowns with separate SHYFEM (core) and SHYFEM UI entries: About shows the respective README (repo root vs `shyfem-ui/`) with the matching version in the title (core from `VERSION`, UI from package metadata), and Changelog shows only that package's sections of the shared CHANGELOG (`pages/about.py`, `changelog.py` — `filter_changelog`, `core_version`, allowlisted `read_repo_markdown`)

---

## [8.4.1] — 2026-07-22

Emergency patch: every 3D heat-forced simulation has been broken since February. Tagged `v8.4.1`.

### Fixed

- **Temperature surface-boundary sentinel restored — 3D heat-forced runs no longer explode** — a magic-number cleanup (2026-02-11) replaced the `ssurface = -999.` sentinel for temperature with `mkonst`'s `flag` (−9,988,765), which besides the intended "use ambient value" branch (`ssurf ≤ −990`) also trips `make_scal_flux`'s `≤ −5555` "difference" branch, injecting ~10⁷-degree water through the surface flux: the venice_lagoon example blew up to 234 °C within 4 simulated minutes, on every fork version since February. Found by bisect after test-running the example; unnoticed for five months because no mar_menor test exercises temperature transport. A committed 6-hour `venlag_smoke.str` now guards the 3D baroclinic + GOTM + wet/dry + heat path (`concentration.f90`, `testcases/examples/venice_lagoon/venlag_smoke.str`)


---

## [8.4.0] — 2026-07-22

Feature release for the Fortran core: the shyfemcm upstream port wave — tracer beaching/burial, optimal-interpolation data assimilation, heat fluxes in meteo output, and restart interoperability — plus the restart-v18 collision defusal and two rounds of upstream cherry-picks. Tagged `v8.4.0`.

### Fixed

- **ismar-branch cherry-picks** — from `georgu/shyfemcm-ismar` develop (newer than the pnrr branch): FPE-trap suspension around `MPI_Init` — OpenMPI 5 throws a floating-point exception inside `MPI_Init` when `-ffpe-trap` is armed; halting modes are saved, disabled for the init sequence, and restored (upstream re-enables unconditionally, which would arm trapping in builds that never requested it; our `MPI_INIT_THREAD` call is kept, upstream's switch to plain `MPI_INIT` is not taken). Also: `boxes_matrix.txt` output actually works again (`iu` was never assigned before the `open` — now `newunit=`), a spurious maybe-uninitialized warning silenced in the sediment D50 loop, and a defensive init in the ice model (`mpi_node_internal.f90`, `boxes.f90`, `sedim_admin.f90`, `icemodel.f90`)
- **Restart ssedi extension renumbered to version 19** — the fork's bed-mass restart block (N25) had claimed version 18, which upstream shyfemcm independently uses for old-time-level hydro state; the identical header version with different record layouts meant files from either side would be silently mis-parsed as garbage by the other. The ssedi block is now version 19, and version-18 files are refused with an explanatory error instead of being mis-read; fork-written v18 files (possible only 2026-07-21/22) must be regenerated (`mod_restart.f90`, `restart.f90`)
- **Upstream cherry-picks (shyfemcm pnrr)** — six small fixes ported: `lnkmpi.f90` guards `kantv` entries of 0 before indexing `id_node` (out-of-bounds read for MPI ghost boundary nodes); `baroclinic.f90` calls `ts_nudge` after the observation/relaxation arrays are zeroed (the zeroing silently wiped parameter-given nudging timescales) and confines the parameter reads to first call; shy files accept and write format version 15 (upstream's compatibility bump — no record change, but pre-bump binaries reject v15 files until rebuilt) with clearer version/type error messages; nc2fem reads long WRF-style variable names (15→80 chars), validates NetCDF-3/4 format up front with a conversion hint, tolerates `standard_name == 'unknown'` by falling through to `long_name`, and knows wave variable names (wheight/wper/wdir); parametric wave directions are averaged element→node as vectors via new `aver_wave_dir` (arithmetic averaging was wrong across the 0/360 wrap; `polar2xy`/`xy2polar`/`p2c` added to `geometrical.f90`); `gmsh2grd.pl` reads the `$MeshFormat` version and computes node-column offsets instead of hardcoding them

### Added

- **Restart interoperability with upstream shyfemcm** — restart files written by current upstream (version 18, old-time-level hydro state: `iwetv`, `zov`, `zeov`) are now read by the model (serial and MPI; values consumed for stream sync, `iwetv` restored, `zov`/`zeov` re-derived after restart); the fork keeps writing version 19. Two restart tools ported: `rstinf` (rewritten: record listing, flag display, NaN check option, and a two-file diff mode covering v18/v19 layouts) and the new `rst2shy` (converts restart files to shy format for plotting: water levels, transports, T/S, tracers). The tool ports fix upstream defects (uninitialized tracer count crashing on conz-bearing files, all tracers written as variable 301, gotm diff gate desyncing on k-eps files) and adapt to the fork's validating `rst_get_vertical` (`restart.f90`, `rstinf.f90`, `rst2shy.f90`, `mod_restart.f90`)
- **Heat fluxes in meteo output** — Ported from shyfemcm (pnrr): setting the new 10000 digit of `imetout` writes the computed sensible, latent, and long-wave heat fluxes plus evaporation (ivars 47/48/49/27) into the meteo output file; needs an active heat module (`iheat` > 0) and heat forcing. The port fixes upstream reading `imetout` where it meant `iheat` (neutering the heat-module guard) and keeps meteo output alive for barotropic runs — upstream moved the output call inside `barocl`, which returns early for `ibarcl` ≤ 0; we call it from the main time loop after the heat-flux computation instead (`mod_meteo.f90`, `heat_admin2.f90`, `meteo_forcing.f90`, `meteo_admin.f90`, `shyfem_subs.f90`, `def_para.f90`)
- **Data-assimilation framework (optimal interpolation)** — Ported from the shyfemcm community model (pnrr branch): station observations are assimilated into running simulations via numbered `$assimil` STR sections (one per variable; T = ivar 12, S = ivar 11 wired, generic 2D/3D entry points prepared). Per step, observations are time-interpolated, the background is evaluated at the stations, an optimal-interpolation analysis is computed (Gaussian covariance with per-station correlation lengths and obs/background error weighting, per-station `iuse` on/off), and applied by nudging (`mode=0`, timescale `tau`) or direct insertion (`mode=1`). Currently 2D/surface-only, as upstream. The port fixes six upstream defects in transit: the observation-window check was hidden inside a debug flag (interpolation ran outside the obs window), two or more `$assimil` sections aborted at STR read (`count_sections` whitelist), an empty coords file silently disabled all instances, `get_bobs` wrote out of bounds for fewer than 3 observations, the vertical-correlation Gaussian multiplied instead of divided by the correlation length, and `assimil_2dvars` passed a `(2,nvar)` array to a `(3,nvar)` dummy; plus convention hardening (collective-safe aborts, `newunit=`, checked allocations, opt-in debug file, O(nobs³) self-check off by default). New infra: `para_set_array_value`, `iff_file_has_data`, `has_sigma_levels` (`assimil.f90`, `assimil_admin.f90`, `suboi.f90`, `baroclinic.f90`, `iostr.f90`, `para.f90`, `intp_fem_file.f90`, `sigma.f90`, test case `mm_hyd_assim.str`)
- **WW3 switch-file build glue** — optional `WW3SWITCH` in `Rules.make` names the WW3 switch file whose switches are compiled into the binary as `__WW3_SWITCHES__` (with a fallback list matching the compiled flags), and the WW3 coupling setup guide `docs/modules_wind_wave.tex` is imported from upstream — fixing the manual's previously broken `\input` of that file (`src/shyfem/Makefile`, `Rules.make`)

- **Tracer beaching/burial algorithm** — Ported from the shyfemcm community model (pnrr branch): nodes on material (closed) boundaries lose a fraction of surface-layer tracer per time step into a per-node beach store, and nodes lose a fraction of bottom-layer tracer into a burial store, with rates looked up per element area code from presets; both stores are written as 2D scalar files (`beach`, `burry`) at the conz output frequency and reset per window. Activated by the new STR parameter `ibeach` (1 = Curonian lagoon preset, 2 = Danube delta preset; needs `iconz` ≥ 2) instead of upstream's hardcoded basin sniffing; the port also fixes upstream's out-of-bounds preset writes on grids without the expected area codes and a latent MPI deadlock in the debug path, and verifies serial ≡ MPI bit-identical output (`beaching.f90`, `def_para.f90`, `shyfem_subs.f90`, `geom.f90`, test case `mm_hyd_beach.str`, PR #51)


---

## [8.3.0] — 2026-07-22

Correctness and safety release for the Fortran core: the 2026-07-18 deep-review remediation batches (PRs #40–#47) plus the June fix wave. No new features; every change hardens existing behavior. Tagged `v8.3.0`.

### Fixed

- **OpenMP save-array caching races reverted** — `allocatable, save` work arrays in routines reachable from OMP tasks are thread-shared and raced under parallel sections; reverted to per-call allocation in `conz3d_omp`, `scal_adv`/`scal_adv_nudge`/`scal_adv_fact`, and `conzstab`, and guarded `limit_scalar` initialization (`concentration_omp.f90`, `concentration.f90` — N01, N09, N10, and the conzstab init race)
- **MPI collective-safe aborts** — error paths that previously called bare `stop` from one rank (hanging the other ranks in collectives) now abort collectively, preserving the original message text: conz3d_nodes, SPARSKIT, turbulence, chezy, mercury sediment, mpi_node allocation failures, wetting/drying, plus `flush(6)` inside `shympi_abort_internal` so diagnostics survive the abort (F07, F09, F11, F27, F38, N22, N23)
- **MPI ghost/setup hardening** — allocatable setup arrays, ghost-exchange `ierr` checks, unified buffer sizing, explicit-RHS ownership filter, ghost-node diagnostics, and documented non-deterministic reductions (N28, F32, F33, F34, L01, L05)
- **PETSc solver honesty** — the solve now aborts on KSP divergence instead of silently accepting garbage zeta (N04), and the zeta matrix is no longer double-assembled on the PETSc path (#33)
- **Numerics guards** — Munk-Anderson clamps Ri ≥ 0 to avoid NaN/SIGFPE (#34); `angle()` guarded against division by zero and acos domain errors (#39); COARE/hersbach drag formulas floor wind/friction velocity (N03, N20, F37); `istod` rejects trailing signs and keeps exponent precision (N53, N54)
- **Model-time bookkeeping** — femtime's `it` updates every step and `itend` is set/guarded, fixing stale end-time comparisons (N05, and the Batch-1 `itend` carry-over)
- **Restart correctness** — read/write paths check `iostat`, validate vertical structure, write single records atomically, wire simple-sediment bed mass into restart, and read `ile`/`ilk` exactly once for io_off v3 (N24–N27, N25, N54)
- **Transport correctness** — intent chain repaired, decay no longer double-counted, `ts_shell` counter fixed, clamping is mass-accounted, allocation failures abort (N37–N39, F28, F29); WW3 coupling recognized by `has_waves` (N21)
- **Tools hardening** — nc2fem preserves header `lmax`, errors on oversized records, fixes direction handling, and accepts valid `nz1<nz` input (N36, F43); shyelab/femelab/extelab striding, vorticity records, stats-buffer conventions (N07, N08, N34, N35); shybas bmode-3 and interpolation scratch sizing (N32, N33); mesh/grid tools get bounded filename/coordinate formatting, realloc NULL-checks, and InterpolateDepth guards (F12, F39, F40, N06, N30, N31); femfile EOF handling, grd `nvert` guard, dts integer overflow (L20–L25, L29)

### Changed

- **Documented build flags actually work** — `MPI=`/`OMP=` on the make command line now map onto `PARALLEL_MPI`/`PARALLEL_OMP` as the docs claim (N19, `Rules.make`)
- **CI skips docs-only builds** — The Fortran and UI build workflows ignore markdown-only changes via a trailing `!**/*.md` path-filter negation, so a docs/changelog PR runs only the review check (`.github/workflows/fortran-ci.yml`, `.github/workflows/ui-ci.yml`)

### Documentation

- **OpenMPI build/run requirement** — Documented that a bare `make fem` silently links Intel MPI (first in `PATH` on the dev box) and crashes inside `MPI_Init`; build and run with OpenMPI (`PATH=/usr/bin:$PATH`) and verify with `ldd … | grep mpi` → `libmpi.so.40` (`CLAUDE.md`)

---

## [shyfem-ui 0.4.0] — 2026-07-22

Session-freeze fix and a leaner docs/feedback entry point. Tagged `shyfem-ui-v0.4.0`.

### Fixed

- **Reactive flush loop froze whole sessions** — `run.py`'s `_auto_refresh` poll read `active_jobs_data` (and `selected_job` via the log refresher) and re-wrote them every cycle with freshly-built lists; `reactive.Value.set()` compares by identity, so the effect self-invalidated into an infinite flush loop (~7k iterations/s, worker pinned at 100 % CPU) that starved the first flush — every output in the session stayed blank (most visibly About/Changelog). Writes are now skipped when content is unchanged (dataclass equality, previous values read under `reactive.isolate()`), and the `_refresh_tick` bump isolates its own read (`pages/run.py`, PR #49)
- **"All jobs" toggle read no longer aborts the poll** — the switch renders only once the Run page is shown, so its `SilentException` is treated as the fail-closed default (own jobs) instead of failing the whole refresh cycle (`pages/run.py`)
- **MPI toggle actually reveals the process-count input** — the checkbox and the `input.mpi_enabled()` read lived in the same `@render.ui`, so toggling re-created the checkbox and reset its state; the count input now lives in its own `mpi_np_control` output (`pages/run.py`)

### Changed

- **About / Changelog / Feedback moved to the top bar** — the About sidebar page (tabbed README/Changelog/Feedback) is replaced by three icon buttons left of the theme toggle that open modals; modal content is plain `ui.markdown` built at show-time (`pages/about.py`, `app.py`)

### Testing

- **Browser tests exercise the real `run_server`** — the `_stub_run_server` workaround in `tests/_test_app.py` (which existed only to mask the flush-loop deadlock, tracked as followup Section M.1) is removed, making the whole E2E suite the regression gate; new `test_playwright_topbar_about.py` covers the three topbar modals including an end-to-end feedback submission

Also since 0.3.0 (unreleased in-between work): the 2026-07-18 deep-review remediation batches (PRs #40–#47) landed UI security and robustness fixes — user-owned jobs that survive WebSocket disconnects with orphan reconciliation and per-user listings, path-confinement and username-slug hardening, CSRF-safe logout, proxy-validated `X-Forwarded-For`, feedback content/email validation with retention pruning, restart-continuation (`itrst=-1`) correctness, and job outputs persisted across restarts.

---

## [shyfem-ui 0.3.0] — 2026-06-14

In-app documentation and a feedback channel. Tagged `shyfem-ui-v0.3.0`.

### Added

- **In-app documentation** — New "About" page (nav item) with tabs rendering `README.md` and `CHANGELOG.md` via `ui.markdown`, plus a dismissable "what's new" modal that shows the latest release notes once per browser (`pages/about.py`, `changelog.py`, `app.py`)
- **Feedback system** — Submit bug reports / suggestions (type, title, description, optional severity and contact email, auto-captured page + app version) from the About page. Stored in a new `feedbacks` table; an anonymous, rate-limited `POST /api/feedback` plus an admin-only `GET /api/feedback` for triage (`models/feedback.py`, `services/feedback_service.py`, `middleware/session_auth.py`, Alembic migration `ccde037a5855`)

### Fixed

- **Connect-time input send no longer breaks the session** — Deferred the what's-new version report so `Shiny.setInputValue` is not called synchronously in `shiny:connected`, which tripped a Shiny `ProtocolError` that tore down the WebSocket session before any output rendered (`app.py`)

---

## [shyfem-ui 0.2.0] — 2026-06-14

First independently-versioned release of the Python UI package, decoupled from the SHYFEM Fortran core (which stays at 8.2.0). Tagged `shyfem-ui-v0.2.0`.

### Added

- **IBM trips-layer trails respond to the time filter** — Particle trails now animate against the full run's clock, so a time-filtered window plays in its true sub-arc of the loop instead of re-stretching to fill it; closes the last deferred item of the 2026-06-08 unwired-UI audit. Verified against real lagrangian data (`pages/ibm.py` — `_tracks_to_trips` gains a global `extent` anchor via `_tracks_time_extent`/`global_time_extent`)

### Changed

- **shyfem-ui versioned independently of SHYFEM** — Restored `shyfem-ui/pyproject.toml` to its own version line and stopped `bin/bump-version.sh` from rewriting it, so a SHYFEM core release (e.g. 8.2.0) no longer bumps the Python UI package (`shyfem-ui/pyproject.toml`, `bin/bump-version.sh`)
- **shyfem-ui bumped to 0.2.0** — First independent minor of the Python UI package (`shyfem-ui/pyproject.toml`)
- **shyfem-ui `__version__` from package metadata** — `__version__` now derives from `importlib.metadata.version("shyfem-ui")`, making `pyproject.toml` the single source of truth; the `/health` test asserts against it rather than a literal (`shyfem_ui/__init__.py`, `tests/test_health.py`)

---

## [8.2.0] — 2026-06-13

### Added

- **deck.gl widget integration** — Layer legend widget and screenshot widget for grid map and IBM pages (`grid_map.py`, `ibm.py`)
- **Trips animation** — IBM particle tracking uses deck.gl TripsLayer with animated playback, replacing static PathLayer (`ibm.py`, `trips_animation_server.py`)
- **Physics configuration UI** — 13-panel form for STR parameter editing: timing, hydro, wind, turbulence, tracers, ecology, sediment, Lagrangian, boundary conditions, non-hydrostatic, physical constants, advanced hydro, water renewal (`physics.py`)
- **Cross-parameter validation** — Level-based validator with Fortran range checks for iturb, ibarcl, iwave, itdrag; GOTM/T+S dependency checks; timing validation rules (`validation.py`)
- **STR validation on save/submit** — Raw editor validates on save; job submission validates before run; ensemble validates parameter variants (`run.py`, `simulation.py`, `ensemble.py`)
- **Particle statistics panel** — Per-type metrics in IBM page with depth and displacement tooltips (`ibm.py`)
- **Boundary condition enhancements** — Expanded ibtyp choices, scalar boundary file fields, `$sedtr`/`$lagrg`/`$connec`/`$bfmsc`/`$nduge` parser sections (`parser.py`)
- **Workflow templates** — 7 new physics templates (offline tracer, eulerian tracer, etc.) and simulation template preview validation (`templates.py`, `simulation.py`)
- **Restart-from-job** — Dropdown to select a completed job for continuation runs (`run.py`)
- **Flux analysis** — Post-processing with exgrd/shyadj tool integration (`run.py`)
- **MPI Lagrangian tracking** — Particle transport works with domain decomposition (`lagrange_mpi.f90`)
- **Automatic versioning** — `make bump-patch/minor/major` targets with `bin/bump-version.sh` script to update all version files and create git tags
- **README.md** — Modern project README with badges, build matrix, feature list, and quick start guide
- **WS trusted-identity authentication** — Per-session WS-auth token (`WSAuthToken` model + migration) minted by `/api/whoami`, pushed to the client via `setInputValue`, and resolved server-side so WebSocket-scope mutations authorize against a server-validated identity (`auth_service.py`, `app.py`, `services/ws_identity.py`)
- **File picker across pages** — Project-aware file browser/picker wired for grid, bas, str, shy, and lgr inputs on Grid Prep, Partitioning, Physics, Simulation, Run, IBM, and Post-Process (`components/file_picker.py`, `services/file_service.py`)
- **IBM time-range filter** — Restrict the particle view to a time window via `filter_by_time` (`ibm.py`, `services/lgr_service.py`)
- **Project Details modal** — Surface grid/simulation metadata for a project from the dashboard (`home.py`)
- **Job authorization & cancel** — Jobs carry `project_id`/owner; cancel is authorized for owner/admin/editor, including per-job ensemble cancel (`run.py`, `ensemble.py`)
- **Periodic maintenance** — Scheduled pruning of old jobs and expired sessions (`app.py`)
- **Mesh-builder input validation** — Warnings for degenerate bathymetry, bathymetry/mesh extent mismatch, and inert or contradictory triangulation constraints (`mesh_builder.py`)
- **Selectable weutro calibration set** — Calibration parameters are configurable (was hardcoded Venice); the active set is logged and unknown sets guarded (`weutro.f90`)
- **weutro phytoplankton settling** — Settling flux wired (TR-05); `NUTLIM` defaults to the Liebig minimum (`weutro.f90`)

### Security

- **CSRF protection on login form** — Double-submit cookie pattern prevents cross-site request forgery (`session_auth.py`)
- **Secure cookie flag** — Configurable `SHYFEM_UI_USE_SECURE_COOKIES` for HTTPS deployments (`config.py`, `session_auth.py`)
- **Password minimum raised to 8 characters** — Was 4, now enforced in both create and reset flows (`admin.py`)
- **Default credentials removed from login page** — "Try it: user/user" hint no longer displayed
- **Tool name allowlist in ShyfemWrapper** — Only known SHYFEM tools can be invoked through the UI (`shyfem_wrapper.py`)
- **WebSocket auth bypass restricted to localhost** — Shiny Server proxy bypass only accepted from `127.0.0.1` / `::1` (`session_auth.py`)
- **Path traversal prevention** — Username `..` rejected; `User.home_dir()` validates containment; STR file paths checked with `config.validate_path()` (`admin.py`, `user.py`, `file_service.py`)
- **WebSocket auth-bypasses closed** — Write-path pages (home, files, run, physics, simulation, ensemble, grid_prep, partitioning, post-process, mesh_builder) now authorize against the **server-validated** WS identity instead of the unforwarded HTTP-scope user, closing fail-open guards (`app.py`, `pages/*.py`)
- **Fail-closed on unresolved identity** — Project create/import and other mutations deny when the WS identity is unresolved in server mode (`services/access_control.py`, `home.py`)
- **Tutorial read-only enforced centrally** — Tutorial accounts are blocked from every mutation gate via the server-validated role (`services/access_control.py`)
- **Job ownership from WS identity** — Job owner is stamped from the WS identity, not the HTTP-scope user (OWN-1); job-access IDOR closed; share-role escalation prevented (`run.py`, `sharing_service.py`)
- **More path-traversal guards** — `mesh_builder` save and `physics.save_file` validate the target against the project root (`mesh_builder.py`, `physics.py`)
- **Rate-limiter & cookie hardening** — `trusted_proxies` defaults to loopback in server mode (no per-client bucket collapse); secure-cookie flag honored (`middleware/rate_limit.py`, `config.py`)
- **Argon2 rehash on login** — Passwords are re-hashed when argon2 parameters change (`auth_service.py`)

### Fixed

- **Race condition in baroclinic T/S computation** — Removed unsafe concurrent OMP tasks sharing `save` arrays in `scal_adv_nudge` (`baroclinic.f90`)
- **Division-by-zero in hydrodynamic solver** — Added `hhi > 0` guard on implicit advective terms and `va > 0` guard on free-surface divergence (`hydrodynamic.f90`)
- **Division-by-zero in serial concentration solver** — Added zero-pivot guards matching OMP version; uses `cycle`/`exit` to skip degenerate nodes (`concentration.f90`)
- **Stack overflow in Munk-Anderson turbulence** — Converted `shearf2`/`buoyf2` from automatic (stack) to `allocatable, save` (heap); removed dead `richard` array (`turbulence.f90`)
- **Stack overflow in OMP concentration solver** — Converted ~50KB/task automatic arrays to allocatable locals in `conz3d_element` (`concentration_omp.f90`)
- **Undefined behavior: `stop` inside OMP parallel regions** — `hydro_transports` uses `REDUCTION(max:ierr_rms)` error flag; `setdepth` wraps diagnostics in `OMP CRITICAL` and defers `stop` (`hydrodynamic.f90`, `elems_dealing.f90`)
- **Swallowed errors in job queue** — Job persistence failure upgraded from `debug` to `error`; DB load upgraded to `warning`; bare `pass` in progress callbacks and restart file handling replaced with `warning` logging (`job_local.py`, `job_queue.py`, `run.py`)
- **13 pre-existing test failures resolved** — Fixed broken tests across the UI test suite
- **shiny_deckgl API imports** — Updated for v1.9.1 API changes
- **Fortran CI now passes** — It had never been green: moved `mod_physical_constants` to the layer compiled before `src/utils` (clean-build module ordering), built the real MPI-NODE binary in the "serial" job, and stopped a `tee` pipe from masking build failures; mar_menor exit-code expectation corrected to 0 (`src/utils/generic/`, `.github/workflows/fortran-ci.yml`, `util.sh`)
- **IBM particle trails actually animate** — Drive the trips-layer `currentTime` and supply `_tripsAnimation`; normalize epoch timestamps to the animation scale (`ibm.py`)
- **shiny 1.6 compatibility** — E2E tests (re)establish active-project state that 1.6's reliable `priority:'event'` reset clears; lifted the temporary `shiny<1.6` pin (`environment.yml`, `tests/test_playwright_workflows.py`)
- **Server-mode E2E reliability** — Auth/sharing E2E fixed: writable `user_data_root` in fixtures, anchor-only project selector, `dispatch_event` for the card-overlaid share button; 30s timeout + reruns for slow CI (`tests/conftest.py`, `tests/test_playwright_auth.py`)
- **weutro 3D correctness** — Per-layer segment flags + vertical light; removed racy OMP parallelization of bio advection; `stat=` guards on all allocations; bare `stop` → `shympi_abort_internal`; fixed-form `OPEN` continuations so EUTRO compiles (`weutro.f90`, `bio3d.f90`)
- **mercury restart** — Stop restart-stream desync; real bit-for-bit restart (`mercury.f90`)
- **UI data integrity & reliability** — SQLite foreign keys enforced; `mesh_builder` NaN-raster / OOM-cap / temp-dir-leak fixes; SMTP send can't block the event loop; `cleanup_old_jobs` deletes rows; `delete_user` orphans removed; `/health` returns 503 when degraded; reactive handlers dedup-guarded (`pages/*.py`, `services/*.py`)
- **Unwired controls connected** — Preview STR + Equal Aspect wired; `mpi_default_np`/`mpirun_path` honored; `Job.celery_task_id` populated; dead code removed (unwired-UI audit P1–P6) (`pages/*.py`)
- **lgrelab date parsing** — Parse lgrelab's actual `YYYY-MM-DD::HH:MM:SS` timestamp so real `.lgr` files load (`services/lgr_service.py`)

### Changed

- **Build: `.IGNORE: clean` removed** — Individual `rm -` prefix already handles errors; `.IGNORE` masked real failures (`Makefile`)
- **Build: `MPI_TARGET` uses `$(MPI_FILE)` variable** — Second definition at line 133 was hardcoded to `MPI_NODE`, now uses the variable (`src/utils/shympi/Makefile`)
- **Build: `SHYFEMDIR` fallback uses `$(CURDIR)`** — Was `$(HOME)/shyfem`, which fails if the repo is in a different location (`Makefile`)
- **Build: dropped `-std=f95`** — Codebase uses Fortran 2003/2008 features (`newunit=`, `allocatable save`); `-std=f95` was silently overridden anyway (`Rules.make`)
- **Build: removed redundant `FGNU_OMP` redefinition** — Duplicate of lines 740-742 removed (`Rules.make`)
- **Build: Intel `FINTEL_NOOPT` unconditional clear removed** — Preserves `-g -traceback` default (`Rules.make`)
- **Build: Intel HIGH optimization `-O1` → `-O3`** — Matches intent of HIGH profile (`Rules.make`)
- **Build: `lagrange_mpi.o` module dependencies added** — Missing `basin`, `connectivity`, `mod_lagrange`, `shympi` (`src/shyfem/Makefile`)
- **shiny pinned to `>=1.6,<1.7`** — A tested range; an open float silently broke CI on 1.6.3 (`environment.yml`)
- **`actions/checkout` v4 → v5** — Node 20 runtime is being removed from CI runners (`.github/workflows/`)
- **Template reads routed through `WorkflowEngine.list_templates`** — Removed the uncalled `run_shyplot` wrapper (`services/workflow_engine.py`)
- **eco coding-convention sweep** — `intent()` added across weutro/bio3d args (FC-01); GOTOs removed from the reaction kernel and reaeration (FC-03); `pi` from `mod_physical_constants` (FC-05) (`weutro.f90`, `bio3d.f90`)
- **CLAUDE.md** — Documented the `.env`-aside trick to reproduce CI-only UI test failures locally

---

## [8.1.1] — 2025-06-15

### Added

- Profile-Guided Optimization (PGO) build profiles (`SPEED_PGO_GEN`, `SPEED_PGO_USE`)
- Hybrid MPI+OpenMP builds (removed incompatibility guard)
- OpenMP parallelization for density computation (`baroclinic.f90`), depth setup (`elems_dealing.f90`), bottom friction (`chezy.f90`), diffusivity init (`diffusion_admin.f90`), Munk-Anderson turbulence (`turbulence.f90`)
- `!$OMP SIMD` hints on vertical level loops in `hydrodynamic.f90`, `turbulence.f90`
- Compiler optimization: `-O2` default, `-march=native -funroll-loops -ftree-vectorize` for SPEED profile
- Allocation caching in `hydro_vertical` (~4MB/timestep) and `conz3d_omp` (~10MB/timestep)
- Physical constants module (`mod_physical_constants.f90`): `pi`, `grav`, `vonkarman`, etc.
- `getpar`/`dgetpar` moved to `module para` with proper module interface (163 callers updated)
- PETSc solver support (`bin/shyfem-petsc`)
- SHYFEM UI web application (`shyfem-ui/`)

### Fixed

- 365+ `allocate()` calls now have `stat=` error checking
- 205 bare `stop` statements in MPI code paths replaced with `MPI_ABORT`
- All `open()` calls now have `iostat=` error handling
- 87 GOTO statements eliminated from 14 files
- Ghost exchange barriers reduced from 11 to 2
- Division-by-zero guards in `turbulence.f90`, `explicit.f90`, `wetdry.f90`
- Stack overflow in `concentration.f90` (automatic arrays → allocatable)
- Identical if/else branches in `waves_admin.f90`

### Changed

- `.PHONY` targets added to 68 Makefiles
- 246 three-line `save`/`data` patterns modernized to single-line initializers
- DOS/Lahey/g77 build remnants removed from `Rules.make`
- `newunit=` replaces 50+ hardcoded file unit numbers
