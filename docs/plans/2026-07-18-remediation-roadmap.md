# SHYFEM Review-Remediation Roadmap (2026-07-18)

> **For agentic workers:** This is the master index, not an executable plan. Each batch gets its own detailed TDD implementation plan (per superpowers:writing-plans) authored just-in-time before execution — Batch 1’s is already written: `docs/plans/2026-07-18-batch1-fortran-core-critical.md`. Execute batches in order; each is independently shippable as one PR.

**Source:** `docs/reviews/2026-07-18-full-codebase-deep-review.md` (N## = that report’s §2 table; F## = the 2026-06-20 review’s findings re-checked in §3).
**Plan-review:** both documents were adversarially reviewed by workflow `wf_8fb8c9c0-a50` (36 agents; 28 confirmed findings applied — Batch 1 plan is at rev 2, the prescription cells below carry the corrected N02/N06/N12/N14/N19/N23/N44/F28 text). Severity column shows original report severities; verifier-adjusted values are in report §2.

**Scope:** all 54 confirmed new findings + all 34 open / 4 partial prior findings = **92 items**, batched into 7 independently shippable batches, ordered by severity and blast radius.

## Global constraints (apply to every batch)

- Build/run with OpenMPI only: `PATH=/usr/bin:$PATH make …`; verify `ldd src/shyfem/shyfem | grep mpi` → `libmpi.so.40` (CLAUDE.md Intel-MPI trap).
- Fortran conventions (CLAUDE.md): implicit none, intent on args, `allocate(...,stat=)` checked, no bare `stop` in MPI paths, `newunit=` I/O, `use para`, `use mod_physical_constants`.
- UI: run `pytest tests/` with `CONDA_PREFIX=""`; ruff+black clean; new behavior needs a regression test in the same PR.
- After Fortran edits: `make fem` must compile AND the mar_menor case must run (build-and-test skill).
- One PR per batch, conventional commits, no force-push.
- After each batch merges: tick its items in the checklist below and update the review report’s §3-style status.

---

## Batch 1: Fortran core — critical/high correctness

**Branch:** `fix/b1-fortran-core-races` · OMP races from the save-caching remediations, PETSc convergence, femtime freeze, calm-wind guards, projection midpoint, MPI-debug regression. **Detailed TDD plan: `docs/plans/2026-07-18-batch1-fortran-core-critical.md` (written, execute first).**

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N01 | critical | conz3d_omp save-cached work arrays are shared across concurrent scalar tasks and deallocated mid-use | `src/shyfem/concentration_omp.f90:173` | Revert to per-call allocatables: drop `,save` from cn/co/cdiag/clow/chigh, replace lazy-init guards with one unconditional allocate (Batch 1 Task 1) |
| N03 | high | Wind-stress input (iwtype=2): division by zero wspeed at calm points | `src/shyfem/meteo_forcing.f90:924` | Guard `wspeed > 1.e-8` before dividing tx/ty by (cd*wspeed); zero wx/wy/ws at calm points (Batch 1 Task 7) |
| N04 | high | KSPSolve convergence never checked - diverged PETSc/AmgX solves silently accepted as zeta | `src/shyfem/mod_petsc_system.f90:602` | Call KSPGetConvergedReason after KSPSolve, abort via assert on reason<0; AmgX: check iters/residual finite (Batch 1 Task 5) |
| N05 | high | femtime `it` frozen at itanf (and `itend` never set) silently breaks lagrangian decay, mortality and connectivity | `src/shyfem/time_admin.f90:703` | Uncomment `itend=nint(dtend)` (time_admin.f90:359) and update `it=nint(t_act)` each step with 2^31 overflow guard (Batch 1 Task 6) |
| N09 | high | scal_adv save-cached boundary-condition arrays are shared across concurrent tracer tasks | `src/shyfem/concentration.f90:298` | Revert r3v/load/cobs/rtauv/wsinkv to per-call allocatables in scal_adv, scal_adv_nudge, scal_adv_fact (Batch 1 Task 2) |
| N10 | high | conzstab save-cached accumulation arrays race between concurrent stability checks, corrupting istot | `src/shyfem/concentration.f90:1722` | Revert cn/co/cdiag/clow/chigh/cwrite/c2write to per-call allocatables (Batch 1 Task 3) |
| N11 | high | MPI exchanges and reductions issued from concurrent OMP tasks violate MPI_THREAD_FUNNELED and de-synchronize collective order | `src/shyfem/concentration.f90:778` | Undefer scalar tasks under MPI (`IF(btask)`), generate them from `!$OMP MASTER` (not SINGLE) so MPI calls run on the MPI main thread, and gate the sediment scn_compute task region too — see Batch 1 plan Task 4 (rev 2) |
| N15 | high | proj_geo2cart uses half-range instead of midpoint for projection reference point | `src/utils/shyutilmpi/coordinates.f90:191` | Use midpoints: c_phi/c_lat0 = 0.5*(ymax+ymin), c_lon0 = 0.5*(xmax+xmin) (Batch 1 Task 9) |
| N20 | medium | hersbach_cd (itdrag=5) unguarded for calm wind: log(0) and negative-base power | `src/shyfem/meteo_forcing.f90:1653` | Floor wind speed: wxy_eff = max(wxy, 0.1 m/s) before computing R and A (Batch 1 Task 8) |
| N29 | medium | newunit= makes my_unit negative, silently disabling all my_unit>0 MPI debug guards | `src/utils/shympi/mpi_node.f90:693` | Change the four `my_unit > 0` guards to `my_unit /= 0` (mpi_ghost.f90:138,501; mpi_basin.f90:163,180) (Batch 1 Task 10) |

**Exit criteria:** Serial+OMP+MPI builds green; mar_menor serial/MPI regression unchanged; OMP 1-thread vs 4-thread tracer run agrees; iconz=2 OMP run stable under FPE traps.

---

## Batch 2: Build system truthfulness

**Branch:** `fix/b2-build-truthfulness` · Every documented build path either works or fails loudly: petsc target, vendor check coverage, MPI=/OMP= flags, Dockerfile, regress target, bump-version tagging.

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N02 | high | make petsc delivers a shyfem-petsc that is actually the SPARSKIT binary | `Makefile:149` | After building with SOLVER=PETSC (+PETSC_DIR), copy the DEREFERENCED binary (`cp -L src/shyfem/shyfem bin/shyfem-petsc`) BEFORE any clean/default rebuild — never `mv` the bin/shyfem symlink (both names dereference to the same, freshly-rebuilt SPARSKIT target). Verify with ldd/strings that bin/shyfem-petsc links PETSc. (Vendor-check/SOLVER validation routing is N17.) |
| N16 | medium | Dockerfile cannot build against MPI-default Rules.make, and CMD references a nonexistent script | `Dockerfile:29` | Install OpenMPI+METIS in the image (or pin serial Rules.make overrides) and fix CMD to an existing entrypoint; add CI docker-build of the runtime stage |
| N17 | medium | petsc target bypasses both check_mpi_vendor and the SOLVER=PETSC parameter validation (gap in the F13 fix) | `Makefile:146` | Route `petsc` target through check_mpi_vendor and SOLVER=PETSC validation like `fem` |
| N18 | medium | make regress silently succeeds without running any tests; other advertised targets reference deleted legacy directories | `Makefile:454` | Fail loudly when the test directory is absent; delete or fix dead advertised targets |
| N19 | medium | Documented build flags MPI=true/OMP=false are inert; no Makefile consumes them | `Rules.make:114` | Map MPI=true → PARALLEL_MPI=NODE and OMP=true/false → PARALLEL_OMP in Rules.make with value validation; hard-error on MPI=false with a message that no MPI-free build exists (PARALLEL_MPI=NONE is not viable — lagrange_mpi.f90 calls MPI unconditionally). Do NOT add a blanket error-out for these flags: fortran-ci.yml:89 and the CLAUDE.md build commands pass them today (CI edit lands in Batch 4/N49; coordinate) |

**Prior findings folded in:**

| ID | Status now | Fix |
|---|---|---|
| F42 | open | bump-version.sh: skip tagging when the commit was skipped, unless --tag-anyway is passed |

**Exit criteria:** `make petsc` produces a PETSc-linked binary (verify ldd/strings); passing MPI=true errors or works; Dockerfile builds in CI; `make regress` fails when tests are missing.

---

## Batch 3: UI job lifecycle & data integrity

**Branch:** `fix/b3-ui-jobs-data` · Job cancel/disconnect/restart lifecycle, init_db Alembic bootstrap, output-file discovery, reactive list bugs, restart wiring, persistence gaps, plus prior F17/F22/F24/F25/F48-F51.

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N12 | high | init_db's Alembic branch is dead code: alembic.ini looked up at the wrong path, so migrations/stamping never run | `shyfem-ui/shyfem_ui/db/base.py:97` | Change parents[1] → parents[2] in base.py:97 (alembic.ini lives at shyfem-ui/, one level ABOVE the shyfem_ui package — the path is already __file__-relative, just one level short); test that a fresh DB gets MIGRATED to head (all tables + alembic_version) and a legacy create_all DB gets STAMPED at head; handle the caveat that stamping an old-release create_all DB can skip needed migrations |
| N13 | high | Any WebSocket disconnect auto-cancels running jobs; local mode cancels ALL active jobs | `shyfem-ui/shyfem_ui/services/job_queue.py:102` | Remove disconnect→cancel coupling; jobs belong to users, not WS sessions; add explicit cancel UI only |
| N14 | high | Job cancellation never terminates the spawned subprocess | `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:204` | Spawn with start_new_session=True in run_command (jobs use asyncio.create_subprocess_exec and currently share the server process group — a bare killpg would take down the whole Shiny app); keep the live Process handle (persist pid only for orphan reconciliation, N46); add a finally/except-CancelledError block in run_command that SIGTERMs the child group, SIGKILLs after grace, and awaits proc.wait(); assert the child is gone in a live test |
| N40 | medium | jobs.output_files is never persisted or restored — the column added by migration 7e41388e2c8d is permanently empty and restarts lose output-file lists | `shyfem-ui/shyfem_ui/services/job_local.py:144` | Serialize output_files as JSON in _persist_job and restore it in _load_history_from_db (column exists via migration 7e41388e2c8d) |
| N41 | medium | Boundary editor Add/CSV-import mutate the list in place then set() the same object ref, so the UI never refreshes | `shyfem-ui/shyfem_ui/components/boundary_editor.py:198` | set() a NEW list object (copy-on-write) so Shiny reactivity sees the change |
| N42 | medium | Run page 'Continue from job' restart selection is recorded only in metadata and never applied, so restarts silently start fresh | `shyfem-ui/shyfem_ui/pages/run.py:678` | Actually wire the selected restart file into the generated STR ($name restrt) instead of only recording metadata |
| N46 | medium | Phantom RUNNING jobs after server restart are never reconciled and are immune to cleanup | `shyfem-ui/shyfem_ui/services/job_local.py:494` | On startup mark RUNNING rows without a live process as FAILED("orphaned at restart"); include them in cleanup |
| N47 | medium | export_project/import_project do unbounded synchronous CPU+disk work on the Shiny event loop | `shyfem-ui/shyfem_ui/services/project_export.py:29` | Offload both to asyncio.to_thread with a size cap and progress notification |
| N48 | medium | _find_output_files globs the whole working dir, so job results include pre-existing and other jobs' files | `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:269` | Snapshot the work dir before launch; return only files created/modified after job start |

**Prior findings folded in:**

| ID | Status now | Fix |
|---|---|---|
| F17 | open | Server-mode job listing filters by user_id, not ephemeral session_id (run.py:571) |
| F22 | partial | PARTIAL → finish: offload the remaining synchronous _persist_job call sites to asyncio.to_thread |
| F24 | partial | PARTIAL → finish: Alembic migration adding ondelete=CASCADE to project_permissions FKs (columns still bare) |
| F25 | open | Anchor default database_url to an absolute package/data path; require explicit DATABASE_URL in server mode |
| F48 | open | timeseries_loader: skip leading blank lines before header detection |
| F49 | open | run_shyfem: copy the options list (list(options or [])) instead of aliasing the caller’s |
| F50 | open | GRD parser: emit warnings when optional node-ID fields are dropped (replace silent except-pass) |
| F51 | open | Offload _load_history_from_db to a thread during JobQueue startup |

**Exit criteria:** Full pytest suite green (2137+ new tests); cancel kills the child process in a live test; restart reconciliation covered by tests; fresh-DB bootstrap test proves migrations run.

---

## Batch 4: UI security hardening & CI honesty

**Branch:** `fix/b4-ui-security-ci` · Username-slug validation, tutorial-project confinement, timing oracle, WS loopback fail-open, symlink TOCTOU, CSRF/XFF/feedback validation, FK-PRAGMA test integrity, resurrect dead tests, MPI run-smoke in CI, coverage gate.

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N43 | medium | Username '.' collapses per-user sandbox to the entire data root (cross-user read/write) | `shyfem-ui/shyfem_ui/config.py:422` | Validate username slug (^[A-Za-z0-9_][A-Za-z0-9_.-]*$, reject "." and "..") at creation AND in confine_path |
| N44 | medium | PR#29 confine_path makes the bootstrapped tutorial project (and pre-#29 projects under work_dir) unreachable in server mode | `shyfem-ui/shyfem_ui/config.py:426` | Make confinement shared-project-aware: allow paths under the work_dir of any project the acting user holds an accepted ProjectPermission on (read-only for tutorial/viewer roles), OR bootstrap a per-user tutorial copy under the user's own home. The relocation migration alone cannot fix this — it moves projects to their OWNER's home (admin), which stays outside the tutorial user's allowlist; run it only as the companion fix for legacy owner access (F15) |
| N45 | medium | Login timing oracle enables username and active-status enumeration | `shyfem-ui/shyfem_ui/services/auth_service.py:251` | Always verify against a dummy bcrypt hash when the user is missing/inactive so timing is constant |
| N49 | medium | mpi-build job compiles the MPI binary but never executes it — "build compiles" is certified, "build runs" is not | `.github/workflows/fortran-ci.yml:89` | Add an mpirun -np 2 mar_menor smoke step with the OpenMPI PATH pin ("build compiles" ≠ "build runs") |
| N50 | medium | Global Engine-class FK PRAGMA listener defeats test_db_fk.py's pin on production FK enforcement | `shyfem-ui/tests/conftest.py:31` | Scope the PRAGMA listener to test engines only; add a test asserting the production engine registers no such listener |
| N51 | medium | New CRS-failure regression test from HEAD fix commit is dead on arrival (placed in permanently-skipped class) | `shyfem-ui/tests/test_mesh_builder.py:1539` | Move the CRS test out of the permanently-skipped class (or add the data-dir fixture it needs) so it actually runs |
| N52 | medium | Entire Curonian integration block (10 tests) permanently skipped everywhere — data dir is a typo and was never committed | `shyfem-ui/tests/test_mesh_builder.py:1434` | Fix the data-dir typo or gate with an explicit skipif + CI check that the directory exists |

**Prior findings folded in:**

| ID | Status now | Fix |
|---|---|---|
| F14 | **not code-fixable (2026-07-19 investigation)** | The middleware WS branch gates the ASGI handshake, but Shiny Server's internal loopback WS presents NO credential there (`_wsauth` is a Shiny input pushed AFTER the socket opens; the proxy strips the query string) — closing it would 4001-reject every prod session. Downstream app-layer identity gates are already fail-closed on `user=None` in server mode, so the fail-open is not exploitable for authz. **Real fix is OPERATIONAL: network-confine the app (bind to loopback / firewall the port so only Shiny Server reaches it).** Optional defense-in-depth: an app-layer idle-unauthenticated-WS timeout (deferred). |
| F15 | partial | PARTIAL → finish: relocate remaining legacy shared-work_dir projects (pairs with N44) |
| F16 | **false positive (2026-07-19, empirically verified)** | Not a live vuln: `validate_path`/`validate_save_path` call `Path.resolve()` (strict=False) which on Python 3.10+ follows symlinks through existing path segments even when the leaf is absent, so a symlink-escape-to-nonexistent-leaf resolves to the escaped path and fails the containment check. Reproduced with real `os.symlink` (escapes rejected, legit new files accepted). The `if resolved.exists(): resolve(strict=True)` block is redundant defensive code, kept as-is. |
| F26 | open | Remove --reruns 2 from E2E, or record rerun statistics and fail when a test only passes on retry |
| F44 | open | home_dir containment via Path.is_relative_to instead of startswith (user.py:65) |
| F45 | open | Make logout a CSRF-protected POST (GET shows a confirm page) |
| F46 | open | Honor X-Forwarded-For only from a configured trusted-proxy list |
| F47 | open | Validate contact_email format and sanitize feedback content beyond length clipping |
| F52 | open | Add feedbacks pruning to the maintenance retention pipeline |
| F53 | open | Enforce coverage: --cov-fail-under pinned at the current baseline |

**Exit criteria:** ui-security-reviewer agent pass clean; resurrected tests run in CI; mpi smoke step green; coverage gate active.

---

## Batch 5: Fortran model tail — restart, transport, MPI hygiene, eco

**Branch:** `fix/b5-fortran-tail` · Restart robustness (iostat/validation/atomic write), transport mediums (intent UB, decay double-count, ts_shell counter), explicit-scheme guards, MPI bare-stops + ierr + buffer sizing, eco-model prior opens (STEELE, positivity, intents), parser fixes (istod, io_off), has_waves WW3.

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N21 | medium | has_waves() returns false for WW3 coupling (iwave=11/12), so turbulence ignores wave roughness | `src/shyfem/waves_admin.f90:1829` | Include iwave=11/12 in has_waves() so turbulence sees WW3 wave roughness |
| N22 | medium | set_advective ihwadv=1 reads ulov(0,ie)/vlov(0,ie) out of bounds at the surface layer | `src/shyfem/explicit.f90:841` | Guard the surface layer: use max(l-1,1) / skip the l=0 access in the vertical advection stencil |
| N23 | medium | Explicit zeta scheme aborts on any wetting/drying event; bare stop in MPI collective context deadlocks | `src/shyfem/simsys_spkaux.f90:643` | Replace the bare stops with collective-safe abort; fix the bsysexpl latch (system_set_explicit is set once and never unset, so iostr setimp/changeimp mid-run overrides fire the "non diag elems" stop with no drying involved); guard the rvec2d/raux2d division at simsys_spkaux.f90:489; document that the explicit scheme cannot dry (or implement drying). Add an explicit-weights (azpar=0, ampar=1) mini-case — mar_menor never exercises this path |
| N24 | medium | Restart read has no iostat past the first header record — a truncated final record aborts the run instead of falling back to the previous record | `src/shyfem/restart.f90:937` | Add iostat= to every record read; on truncation report the record name and abort cleanly instead of crashing |
| N25 | medium | Restart round-trip silently drops model state: simple-sediment bed mass (hooks exist but unwired) and k-eps turbulence | `src/shyfem/restart.f90:616` | Wire the existing simple-sediment bed-mass hooks into write/read; document remaining unsaved state explicitly |
| N26 | medium | Vertical layer structure in restart file (hlv/ilhv/ilhkv) is read but never validated against the run; rst_get_vertical is dead code | `src/shyfem/restart.f90:948` | Validate hlv/ilhv/ilhkv against the running basin after read; abort on mismatch |
| N27 | medium | Restart writes have no iostat anywhere, and single-record mode overwrites the only record in place — a failed write destroys the sole recovery point | `src/shyfem/restart.f90:516` | Add iostat= to restart writes; in single-record mode write to a temp file and rename to avoid destroying the only good record |
| N28 | medium | Global-mesh-sized automatic stack arrays in MPI setup path (shympi_setup, transfer_domain, handle_partition) crash on large basins | `src/utils/shympi/mpi_basin.f90:88` | Convert setup-path automatic arrays to allocatables with stat= checks |
| N37 | medium | Sediment deposition feedback writes through an intent(in) dummy chain (undefined behavior) | `src/shyfem/concentration_omp.f90:861` | Fix the intent chain to intent(inout) end-to-end (writing through intent(in) is undefined behavior) |
| N38 | medium | decay_conz_chapra double-counts settling and transfers concentration between layers without thickness weighting | `src/shyfem/conz_admin.f90:741` | Remove the settling term from the decay kernel (transport already applies wsink) and add the layer-thickness factor |
| N39 | medium | ts_shell accumulation counter nr is an unsaved local — averaging divisor is undefined between calls | `src/shyfem/conz_util.f90:385` | Make nr `integer, save :: nr = 0` (or module state) so the averaging divisor survives between calls |
| N53 | medium | istod accepts sign characters after digits, silently misparsing values like '3.456-102' | `src/utils/generic/convert.f90:211` | Reject sign characters after digits in the parser state machine; add unit checks for "3.456-102"-style inputs |
| N54 | medium | off_read_record misaligned for version-3 offline files: ile/ilk records consumed twice | `src/utils/shyutilmpi/io_off.f90:510` | Read ile/ilk exactly once per record in the version-3 branch; add an offline-file round-trip check |

**Prior findings folded in:**

| ID | Status now | Fix |
|---|---|---|
| F07 | open | Replace bare stops in conz3d_nodes (concentration_omp.f90:858,897) with collective-safe abort (error_stop → shympi_abort) |
| F08 | **open — owner decision (2026-07-21)** | Verified NOT redundant with bio3d (unlike F30): bio3d attenuates surface→top-of-layer, F08's `*h` would add top-of-layer→bottom layer-averaging (complementary, more accurate). But bio3d↔weutro carry only background extinction (`ke_bg`, no algal self-shading) and use top-of-layer light. A clean fix needs a coupled bio3d↔weutro redesign (no 2D/3D mode flag exists in weutro to gate on) — escalated for a conscious eco-model-owner decision rather than a guess. |
| F09 | open | Replace the 7 bare stops in active mercury sediment paths (merc_sed4sed.f90) with collective-safe abort |
| F10 | open | Positivity floor for ALL state variables in merc_euler (MIN_CONCENTRATION per AQUABC), not just C(1) |
| F11 | open | Replace the 25 bare allocation-failure stops in mpi_node_internal.f90 with shympi_abort |
| F27 | open | Replace the 9 bare stops in sparskit_admin.f90 with collective-safe abort |
| F28 | open | Match the original M17 remediation exactly: log count/minval of negatives BEFORE any clamp; keep the tiny-positive flush as `where(cnv > 0. .and. cnv < 1.e-15) cnv = 0.`; zero negatives only with the removed mass accounted (accumulate + report the correction) — do NOT relabel unaccounted negative-zeroing as "mass-conserving" |
| F29 | open | conz3d_element: abort on allocation failure instead of silent return (concentration_omp.f90:447) |
| F30 | **superseded (2026-07-21, oracle-verified)** | The 3D vertical light structure is already supplied EXTERNALLY by `bio3d.f90:562` (per-layer Beer-Lambert `qrad*exp(-ke_bg*depth_top)`, matches AQUABC). weutro's RLGHTS cascade (`iseg=1/ito=0` hardcoded) is dead in 3D; restoring it would DOUBLE-COUNT bio3d's attenuation. No fix — the finding is superseded by the bio3d path. |
| F31 | open | Add intent attributes to all ~27 mercury_react arguments (merc_water.f90:37) |
| F32 | open | Check ierr on all ghost-exchange MPI calls via a checking wrapper |
| F33 | open | Unify the buffer-size strategy between integer/real/double exchange paths |
| F34 | open | Document the non-deterministic float MPI_SUM; optionally add a fixed-order reduction mode for debugging |
| F37 | open | Floor friction velocity usr in COARE calm-wind branch (heat_coare.f90:801) |
| F38 | open | Replace bare stops in MPI-active turbulence/chezy routines with collective-safe abort |

**Exit criteria:** All builds green; mar_menor + restart round-trip test; weutro_box 6-gate suite green; MPI 4-rank run with deliberate failure aborts cleanly (no deadlock).

**Carried over from the Batch 1 final review (2026-07-19):** conzstab's icall-guarded save locals (rstol_c/iuinfo/da_out — mirror the limit_scalar_init named-CRITICAL pattern); route mod_petsc_system's `assert` through shympi_abort_internal when doing the bare-stop sweep; mirror the 2^31 guard onto `itend = nint(dtend)` (time_admin.f90:359); tighten the AmgX introspection check + delete the superseded commented block (mod_petsc_system.f90) and retype the dummy stubs' perr; add a small lat/lon (isphe=1) regression case so N15's projection fix is numerically exercised. **From Batch 2 final review (2026-07-19):** restrict the MPI=/OMP= mapping to command-line origin (`ifeq ($(origin MPI),command line)`) so exported env vars can't trigger it; decide the GNU `-fopenmp` policy (FFLAGS inherits LFLAGS's unconditional -fopenmp, making PARALLEL_OMP hollow for GNU compile flags — link-only flag vs documented always-on OMP).

---

## Batch 6: Tools — Fortran & C utilities

**Branch:** `fix/b6-tools` · shyelab/femelab/extelab/nc2fem/shybas correctness, shy_util2 OOB, C memory safety (strcpy/sprintf/realloc/malloc bounds, printf format, NULL derefs).

| ID | Sev | Finding | Location | Fix |
|---|---|---|---|---|
| N06 | high | InterpolateDepth dereferences NULL element on out-of-coverage centroid (supported workflow) | `src/tools/mesh/intgrd.c:289` | PREREQUISITE: intgrd.c/maskgrd.c do not compile at HEAD (ReadStandard/WriteStandard calls do not match the 3-arg grdio.h prototypes — see report §5) — restore compilation first, then check the FindElement result for NULL and warn+skip out-of-coverage centroids. Note: verdict is PLAUSIBLE (adj. low), the only non-CONFIRMED item in this roadmap — consider demoting to Batch 7 verify-then-fix |
| N07 | high | femelab -write/-condense use per-variable lmax as array leading dimension, mis-striding mixed 2D/3D FEM files | `src/tools/shyelab/femelab1.f90:937` | Use the file-global vertical dimension (not per-variable lmax) as the array leading dimension; add a mixed-2D/3D FEM regression file |
| N08 | high | shyelab -vorticity writes nodal data as an element record (stale belem) and silently writes nothing for fem/gis/nc | `src/tools/shyelab/shyelab1.f90:554` | Set belem=.false. for the nodal vorticity record; hard-error for unsupported fem/gis/nc outputs instead of writing nothing |
| N30 | medium | sprintf("%f", coord/depth) into char s[20] overflows on large grd values | `src/tools/grid/gridma2.c:272` | snprintf with sizeof(s) for coordinate/depth formatting |
| N31 | medium | Stack buffer overflow: filename strcpy into fixed sfile[80] in five mesh tools | `src/tools/mesh/exgrd.c:178` | Central bounded-filename helper (snprintf + length check) replacing strcpy/strcat in all five tools (covers prior F12) |
| N32 | medium | interpola (shybas -bmode 3) has an unconditional `cycle` that skips every bathymetry point - mode always aborts | `src/tools/shybas/basutil_interp.f:690` | Remove the stray cycle so bmode-3 interpolation actually processes points; add a smoke test |
| N33 | medium | interpole/interpola scratch array `ok(nel)` overflows when interpolating on nodes of a mesh with nkn > nel | `src/tools/shybas/basutil_interp.f:368` | Size the scratch array max(nel,nkn) (node-mode interpolation overruns nel-sized array) |
| N34 | medium | extelab -write prints hydro statistics from an uninitialized/stale buffer (ivar==0 vs ivar==1 convention mismatch) | `src/tools/shyelab/extelab1.f90:387` | Initialize the stats buffer and fix the ivar==0 vs ivar==1 condition so hydro stats come from the current record |
| N35 | medium | read_records writes ivars(:,0) out of bounds when a zeta record (ivar=-1) leads a shy time record | `src/tools/shyelab/shy_util2.f:310` | Guard the ivar=-1 (zeta) leading-record case so the 0 index is never written; add a shy file regression |
| N36 | medium | nc2fem clobbers header lmax with data-record lmax, producing inconsistent out.fem when nz1 /= nz | `src/tools/shynetcdf/nc2fem.f90:988` | Preserve the header lmax; error if a data record exceeds it instead of silently rewriting the header |

**Prior findings folded in:**

| ID | Status now | Fix |
|---|---|---|
| F12 | open | Folded into N31: bounded-filename helper replaces strcpy/strcat into sfile[80] in gridfi.c and the other mesh tools |
| F39 | open | Error(): drop the uninitialized printf arg — fprintf(stderr, "%s", string) (unformatted.c:486) |
| F40 | open | realloc into a temp var with NULL checks in PsInitColorTable (psgraph.c:657) |
| F43 | open | Bound file-supplied record length against actual file size before malloc/fread (unformatted.c:232) |

**Exit criteria:** Each fixed tool exercised on a real mar_menor output file; C tools pass an ASan-compiled smoke run on crafted inputs.

---

## Batch 7: Low-tier triage sweep

**Branch:** `fix/b7-low-tier` · The 46 unverified low-tier leads (report §4). Verify-then-fix: adversarially verify each lead first (workflow-assisted), fix the confirmed ones, close the rest as refuted.

No fixed item list — input is the 46 leads in report §4. Recommended: a verify-then-fix workflow (same adversarial pattern as the review) before touching code.

**Exit criteria:** Every §4 lead has a verdict recorded; confirmed ones fixed with tests.

---

## Progress checklist

- [x] **Batch 1 — Fortran core — critical/high correctness** (10 items: N01, N03, N04, N05, N09, N10, N11, N15, N20, N29) — DONE (commits 868569c..ccd1e33)
- [x] **Batch 2 — Build system truthfulness** (6 items: N02, N16, N17, N18, N19, F42) — DONE (commits f25f06f..b04d2aa)
- [x] **Batch 3 — UI job lifecycle & data integrity** (17 items: N12, N13, N14, N40, N41, N42, N46, N47, N48, F17, F22, F24, F25, F48, F49, F50, F51) — DONE (commits 8ef7321..b9c6395)
  - **Known limitations carried into Batch 4** (final-review): (1) **F17 (COMPLETED in Batch 4, PR forthcoming)** — job-list scoping fixed in run.py but home.py:371 / compare.py:136 / app.py:1012 still filter by `str(id(session))`; post-N13 (jobs survive disconnect) a user's own jobs drop off Dashboard/Compare/notifications after reconnect, and CPython `id()` reuse can surface a prior user's job *metadata* (name/status only — cancel/log reads are separately authz-gated) → migrate these three read paths to `user_id` scoping in Batch 4. (2) **N42 restart is not end-to-end warm-restart** — `restrt` is written, but `itanf`/`ityrst` alignment is unimplemented, so "Continue from job" can silently cold-start; treat as experimental until Batch 4 wires the time-window. (3) optional robustness: move the N12 logging guard into `migrations/env.py` as `fileConfig(..., disable_existing_loggers=False)`.
- [x] **Batch 4 — UI security hardening & CI honesty** (17 items: N43, N44, N45, N49, N50, N51, N52, F14, F15, F16, F26, F44, F45, F46, F47, F52, F53) — DONE (commits 03ccf86..28c75a8; F14 not-code-fixable, F16 false-positive — see notes)
- [x] **Batch 5 — Fortran model tail — restart, transport, MPI hygiene, eco** (28 items: N21, N22, N23, N24, N25, N26, N27, N28, N37, N38, N39, N53, N54, F07, F08, F09, F10, F11, F27, F28, F29, F30, F31, F32, F33, F34, F37, F38) — DONE (commits 4b279b6..da93d18; F30 superseded, F08+N23-latch escalated as owner decisions — see notes)
- [x] **Batch 6 — Tools — Fortran & C utilities** (14 items: N06, N07, N08, N30, N31, N32, N33, N34, N35, N36, F12, F39, F40, F43) — DONE (commits 3ab2e82..4e7249a; N06 compile-restore + NULL guard, all C tools ASan-verified)
- [x] **Batch 7 — Low-tier triage sweep** (46 unverified leads from report §4) — VERIFIED 2026-07-21 (workflow wf_6a941180-1b6, refute-by-default): 20 confirmed-fix / 4 defer / 5 trivial / 17 refuted-false-positive. Fixes in PR (forthcoming); defer/trivial/refuted recorded in .superpowers/sdd/progress.md B7 section.

## Explicitly out of scope

- The 16 refuted candidates (report §5) — verified false positives.
- Prior findings already verified **fixed** (report §3: F01–F06, F13, F18–F21, F23, F35, F36, F41, F54).
- F34-style determinism work beyond documentation (research-grade, not a defect fix).