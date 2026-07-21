# Batch 5: Fortran Model Tail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. The Fortran core has NO unit-test framework — each task's verification is **build + the relevant run** (mar_menor, weutro_box, or a restart round-trip) + code inspection. Report "test evidence" = the build result + run output. Where a fix touches subtle science (eco light formulas), validate against the AQUABC oracle or ESCALATE rather than guess.

**Goal:** Fix 12 new findings (N21-N28, N37-N39, N53, N54) + 15 prior opens (F07-F11, F27-F34, F37, F38) + the Batch 1/2 final-review carry-overs. Themes: restart robustness, transport correctness, explicit-scheme guards, MPI bare-stop/ierr/buffer hygiene, eco-model opens, parser fixes.

**Tech stack:** Fortran 90 (gfortran), OpenMPI, OpenMP, GNU Make. Builds: `cd /home/razinka/shyfem && PATH=/usr/bin:$PATH make fem` (+ knobs `PARALLEL_OMP=true`, `PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr` for MPI). Collective-safe abort primitive = `shympi_abort_internal(message)` (in both mpi_node_internal.f90 and mpi_dummy.f90, so it works serial-NODE and real-MPI). Eco run: `weutro_box` suite. Restart: run mar_menor with a restart write, then read it back.

## Global Constraints

- Build/run OpenMPI only (`PATH=/usr/bin:$PATH`); verify `ldd src/shyfem/shyfem | grep mpi` → `libmpi.so.40`. STR runs need `nomp = -1` for real OMP threads (see [[nomp-omp-trap]]).
- **cwd discipline:** builds from `cd /home/razinka/shyfem`; runs from `cd /home/razinka/shyfem/testcases/examples/mar_menor`. The mar_menor Makefile has a do-nothing `fem` target.
- Tab indentation; keep each file's existing style. Bare-stop → `call shympi_abort_internal('<same message>')`; add `use shympi` only if the routine lacks it AND it doesn't create a circular dep (check; if it does, escalate the specific file).
- **Eco science (F08, F30):** the AQUABC oracle is `/home/razinka/AQUABCv0.2` (double-prec, per-layer light/segments). If the correct 2D-vs-3D formula selection is ambiguous, ESCALATE (NEEDS_CONTEXT) with the oracle comparison — do not ship a guess at wrong science.
- Never touch/stage `src/tools/shynetcdf/` or `testcases/examples/mar_menor/mm_hyd_conz.*`.
- Branch `fix/b5-fortran-tail` off `fix/b4-ui-security-ci` (stacked #40←#41←#42←#43←#44←this). One commit per task.
- Finding details: `docs/reviews/2026-07-18-full-codebase-deep-review.md` §2-3 — read the row before implementing.

---

### Task 0: Branch + baselines

- [ ] `cd /home/razinka/shyfem && git checkout -b fix/b5-fortran-tail`
- [ ] Build default + run mar_menor serial → capture `/tmp/claude-1000/b5/base_00.log` (regression ref). Build MPI (NODE+METIS), run 4-rank → confirm clean. Build OMP, run → confirm. Record all three green.

### Task 1: N22 + N23 — explicit-scheme surface-layer OOB + wetting/drying abort

**Files:** `src/shyfem/explicit.f90:841` (N22), `src/shyfem/simsys_spkaux.f90:643,489,166` (N23)

- N22: `set_advective` with `ihwadv=1` reads `ulov(0,ie)`/`vlov(0,ie)` (layer 0, out of bounds) at the surface. Guard the surface layer — use `max(l-1,1)` or skip the `l=0` access in the vertical-advection stencil so the surface term uses a valid layer.
- N23: the explicit zeta scheme's bare `stop` on the "non diag elems" path (simsys_spkaux.f90:643) deadlocks under MPI. Root cause per finding: `bsysexpl` is latched by `system_set_explicit` (hydrodynamic.f90:354-358) and never unset, while iostr `setimp`/`changeimp` can force implicit weights mid-run → the stop fires WITHOUT any drying. Fix: replace the bare `stop`(s) with `shympi_abort_internal`; track/un-latch `bsysexpl` against the actual azpar/ampar of each step (or force implicit assembly while setimp/changeimp overrides are active); guard the `rvec2d/raux2d` division at simsys_spkaux.f90:489 (div-by-zero); document that the explicit scheme cannot dry.
- [ ] Build (serial+MPI) + mar_menor regression (must match base_00.log mod timing). If mar_menor's default semi-implicit path doesn't exercise N23, add a tiny explicit-weights case (`azpar=0 ampar=1`) to prove the abort path is collective-safe (2-rank run with the condition forced aborts cleanly, no hang). Commit `fix(fortran): explicit-scheme surface-layer bounds + collective-safe wetting/drying abort (N22, N23)`.

### Task 2: N24 + N26 + N27 — restart I/O robustness

**Files:** `src/shyfem/restart.f90` (reads ~937/948, writes ~516)

- N24: restart READ has no `iostat=` past the first header record → a truncated final record crashes. Add `iostat=` to every record read; on truncation, report the record name and abort cleanly (`shympi_abort_internal`) instead of an uncontrolled crash.
- N26: `hlv/ilhv/ilhkv` (vertical layer structure) are read but never validated against the running basin; `rst_get_vertical` is dead code. Validate after read (dimensions + values); abort on mismatch with a clear message. Wire or remove the dead `rst_get_vertical`.
- N27: restart WRITES have no `iostat=`, and single-record mode overwrites the only record in place — a failed write destroys the sole recovery point. Add `iostat=` to writes; in single-record mode write to a temp file and `rename` into place on success.
- [ ] Build + a RESTART ROUND-TRIP test: run mar_menor writing a restart, then start a run reading it back — must succeed and continue. Corrupt/truncate a restart file and confirm the read aborts cleanly (clear message, no garbage). Commit `fix(fortran): restart read/write iostat, vertical-structure validation, atomic single-record write (N24, N26, N27)`.

### Task 3: N25 — restart state completeness

**Files:** `src/shyfem/restart.f90:616` + the simple-sediment module hooks

- Simple-sediment bed mass has write/read HOOKS that exist but are unwired, and k-eps turbulence state is dropped — a restart silently loses this state. Wire the existing simple-sediment bed-mass hooks into the restart write+read symmetrically. For state that genuinely can't be saved yet (k-eps), DOCUMENT it explicitly (a comment listing unsaved state + a runtime warning when such a module is active and a restart is written). Do NOT invent new serialization for k-eps if the hooks don't exist — document that gap.
- [ ] Build + restart round-trip with simple sediment active (if a testcase exercises it; else verify the hooks are symmetric by inspection + a targeted write/read of the bed-mass array). Commit `fix(fortran): wire simple-sediment bed mass into restart; document remaining unsaved state (N25)`.

### Task 4: N37 + N38 + N39 + F28 + F29 — transport correctness

**Files:** `src/shyfem/concentration_omp.f90` (N37 ~861, F29 ~447), `src/shyfem/conz_admin.f90:741` (N38), `src/shyfem/conz_util.f90:385` (N39), `src/shyfem/concentration.f90:747` (F28)

- N37: sediment-deposition feedback writes through an `intent(in)` dummy chain (undefined behavior). Trace the chain and change the relevant dummies to `intent(inout)` end-to-end.
- N38: `decay_conz_chapra` double-counts settling (transport already applies `wsink`) AND transfers concentration between layers without thickness weighting. Remove the settling term from the decay kernel; add the layer-thickness factor to the inter-layer transfer.
- N39: `ts_shell`'s accumulation counter `nr` is an unsaved local → the averaging divisor is undefined between calls. Make it `integer, save :: nr = 0`.
- F28: match the original M17 remediation exactly at concentration.f90:747 — log count/minval of negatives BEFORE any clamp; keep the tiny-positive flush as `where(cnv > 0. .and. cnv < 1.e-15) cnv = 0.`; zero negatives only with the removed mass ACCOUNTED (accumulate + report the correction). Do NOT relabel unaccounted negative-zeroing as "mass-conserving."
- F29: `conz3d_element` currently does `write(6,*)…; return` on allocation failure → wrong system silently. Abort instead (`shympi_abort_internal`).
- [ ] Build (serial+OMP+MPI) + mar_menor with a tracer (reuse the iconz config pattern) — results consistent; the F28 clamp path logs when it fires. Commit `fix(fortran): transport correctness — intent chain, decay double-count, ts_shell counter, mass-accounted clamp, alloc abort (N37, N38, N39, F28, F29)`.

### Task 5: F31 + F10 + F08 + F30 — eco-model opens (F08/F30 with oracle-or-escalate)

**Files:** mercury `merc_water.f90:37` (F31), `mercury.f90:800` (F10); weutro `weutro.f90:1831` (F08), `:673` (F30)

- F31 (SAFE, mechanical): add `intent` attributes to all ~27 `mercury_react` arguments per their actual use (in/out/inout).
- F10 (SAFE): `merc_euler` positivity floor for ALL state variables (MIN_CONCENTRATION per the AQUABC oracle), not just C(1).
- F08 (SCIENCE — validate against AQUABC oracle `/home/razinka/AQUABCv0.2` or ESCALATE): the STEELE light formula at weutro.f90:1831 has `temp1 = ske * h` immediately overwritten by `temp1 = ske  !$WRONG_FORMULA`, plus a `!2D_FORMULA` RLIGHT override. Determine from the oracle whether the layer-thickness (`*h`) factor and the 3D RLIGHT formula are correct for the 3D path, and whether the 2D overrides are meant to be mode-gated (2D vs 3D) rather than unconditional. If the correct fix is a clean mode gate, apply it; if the 2D/3D selection is ambiguous, ESCALATE (NEEDS_CONTEXT) with the oracle comparison — do NOT ship a guess.
- F30 (SCIENCE — same oracle-or-escalate): the inter-layer light chain is dead because `iseg=1, ito=0` are hardcoded at weutro.f90:673-675, so `RLGHTS(ITO,2)=RLGHTS(ISEG,2)*TEMP3` never propagates between real layers. Wire per-layer ISEG/ITO through the 3D coupling per the oracle. If wiring requires structural changes beyond the finding's scope, ESCALATE with the specifics.
- [ ] Build + `weutro_box` 6-gate suite must stay green (this is the eco regression gate). Commit `fix(eco): mercury intents + positivity floor; weutro STEELE/inter-layer light per AQUABC (F31, F10, F08, F30)` — or split the escalated science items into a follow-up and commit only the safe ones (F31, F10), noting the escalation.

### Task 6: N53 + N54 — parser fixes

**Files:** `src/utils/generic/convert.f90:211` (N53 istod), `src/utils/shyutilmpi/io_off.f90:510` (N54)

- N53: `istod` accepts sign chars AFTER digits, silently misparsing `'3.456-102'`. Fix the parser state machine to reject a sign that follows a digit (unless it's an exponent sign immediately after `e`/`E`/`d`/`D`). Add targeted checks for `'3.456-102'`-style inputs (a small test program or an assertion path).
- N54: `off_read_record` is misaligned for version-3 offline files — `ile`/`ilk` records are consumed twice. Read them exactly once per record in the v3 branch.
- [ ] Build. N53: verify with a small driver that `'3.456-102'` is now rejected/flagged and valid `'3.456e-102'`/`'3.456'`/`'-3.456'` still parse. N54: an offline-file round-trip (write a v3 offline file, read it back — records align). Commit `fix(fortran): istod rejects trailing sign; io_off v3 reads ile/ilk once (N53, N54)`.

### Task 7: N21 + F37 — forcing guards

**Files:** `src/shyfem/waves_admin.f90:1829` (N21), `src/shyfem/heat_coare.f90:801` (F37)

- N21: `has_waves()` returns false for WW3 coupling (`iwave=11/12`), so turbulence ignores wave roughness. Include `iwave=11/12` in `has_waves()`.
- F37: COARE bulk flux divides by friction velocity `usr` which can be 0 in calm wind. Floor `usr` (e.g. `max(usr, 1.e-4)`) before the divisions at heat_coare.f90:801-802.
- [ ] Build + mar_menor regression (F37 branch not exercised → compile+neutrality; N21 changes has_waves logic — confirm mar_menor without WW3 is unchanged). Commit `fix(fortran): has_waves recognizes WW3; COARE floors friction velocity (N21, F37)`.

### Task 8: N28 + F32 + F33 + F34 — MPI hygiene

**Files:** `src/utils/shympi/mpi_basin.f90:88` (N28), `src/utils/shympi/mpi_node_internal.f90` (F32 ierr ~558-2150, F33 buffer ~535-659, F34 doc ~1777)

- N28: global-mesh-sized AUTOMATIC (stack) arrays in `shympi_setup`/`transfer_domain`/`handle_partition` crash on large basins. Convert them to `allocatable` with `stat=` checks (+ abort on failure).
- F32: ghost-exchange point-to-point MPI calls don't check `ierr`. Add a checking wrapper (a small helper that asserts `ierr==MPI_SUCCESS` and aborts otherwise) and route the exchange calls through it (or add inline `if(ierr/=0) call shympi_abort_internal` after each).
- F33: unify the buffer-size strategy between the integer/double and real exchange paths (they compute `nb` inconsistently — pick one correct formula, apply to all).
- F34 (DOC): document the non-deterministic float `MPI_SUM` reductions at 1777/1807 (result varies with rank count/order). Optionally add a fixed-order reduction mode behind a debug flag — but the required deliverable is the documenting comment.
- [ ] Build MPI + 4-rank mar_menor (must stay clean; N28's allocatables must not change results). Commit `fix(mpi): allocatable setup arrays, ghost-exchange ierr checks, unified buffer sizing, document non-deterministic reductions (N28, F32, F33, F34)`.

### Task 9: Bare-stop sweep A — Fortran core

**Files:** `src/shyfem/concentration_omp.f90` (F07: conz3d_nodes ~858,897), `src/shyfem/sparskit_admin.f90` (F27: 9 sites), `src/shyfem/turbulence.f90` + `src/shyfem/chezy.f90` (F38: MPI-active routines)

Replace bare `stop '<msg>'` with `call shympi_abort_internal('<msg>')` in MPI-active code paths (chezy/turbulence already `use shympi` in most routines — add it where a target routine lacks it, checking for circular deps). Keep the same message text. Do NOT touch stops in clearly non-MPI utility routines if adding `use shympi` would create a cycle — list any such site you skip and why.
- [ ] Build (serial+MPI). A deliberate-failure smoke: force one of the converted conditions (e.g. temporarily) under a 2-rank run and confirm it aborts cleanly (all ranks down, no hang), then revert the forcing. Commit `fix(mpi): collective-safe abort in conz3d_nodes, sparskit, turbulence, chezy (F07, F27, F38)`.

### Task 10: Bare-stop sweep B — MPI layer + mercury

**Files:** `src/utils/shympi/mpi_node_internal.f90` (F11: 25 allocation-failure stops), mercury `merc_sed4sed.f90` (F09: bare stops in active sediment paths)

- F11: replace the 25 bare `stop 'error stop: allocation failed'` (and similar) in the collective/exchange routines with `shympi_abort_internal`. This file DEFINES `shympi_abort_internal` — call it directly (no `use` needed).
- F09: replace the bare stops in merc_sed4sed.f90's active sediment paths with `shympi_abort_internal` (add `use shympi` — check for circular dep; mercury is contrib, likely fine).
- [ ] Build MPI + 4-rank mar_menor clean. Commit `fix(mpi): collective-safe abort on allocation failure in mpi_node_internal and mercury sediment (F11, F09)`.

### Task 11: Batch 1/2 carry-overs

**Files:** `src/shyfem/concentration.f90` (conzstab save locals), `src/shyfem/mod_petsc_system.f90` (assert→abort, AmgX tighten), `src/shyfem/time_admin.f90:359` (itend guard), `src/utils/shyutilmpi/coordinates.f90` + a testcase (N15 lat/lon), `Rules.make` (MPI=/OMP= origin)

- conzstab save locals (`rstol_c`/`iuinfo`/`da_out`): wrap the racy getpar/getinfo first-call reads in the `limit_scalar_init`-style named CRITICAL (da_out is master-only, leave it; guard rstol_c/iuinfo).
- petsc: route `mod_petsc_system`'s `assert` failure through `shympi_abort_internal` (currently bare stop); tighten the AmgX introspection check and DELETE the superseded commented residual-loop block; retype the dummy stubs' `perr` to `PetscErrorCode` for consistency.
- itend guard: mirror the 2^31 overflow guard onto `itend = nint(dtend)` at time_admin.f90:359 (Batch 1 guarded `it` but not `itend`).
- N15 lat/lon test: add a small spherical (`isphe=1`) regression case so the projection-midpoint fix is numerically exercised (a mini basin with lat/lon coords; assert cartesian distances are sane).
- Rules.make MPI=/OMP= origin: restrict the Batch-2 mapping to command-line origin — `ifeq ($(origin MPI),command line)` / `ifeq ($(origin OMP),command line)` — so an exported bare `MPI`/`OMP` env var can't trigger it.
- [ ] Build (serial+OMP+MPI+PETSc) + mar_menor. The `make -n fem MPI=true` still maps; `MPI=true make -n fem` via ENV export does NOT (origin test). Commit `fix(fortran): Batch 1/2 carry-overs — conzstab init race, petsc abort/AmgX, itend guard, N15 test, MPI/OMP origin (carry-overs)`.

### Task 12: Verify + roadmap tick + final review + PR

- [ ] Full build matrix (serial/OMP/MPI/PETSc) green; mar_menor serial + 4-rank + restart round-trip; `weutro_box` 6-gate green; a deliberate-failure MPI run aborts cleanly (no deadlock).
- [ ] Tick Batch 5 in the roadmap (` — DONE`); note any ESCALATED eco item (F08/F30) status. Commit.
- [ ] (Controller) final whole-branch review (most capable model) + fortran-reviewer agent pass; one fix subagent for combined findings.
- [ ] (Controller) push + `gh pr create --base fix/b4-ui-security-ci`.

## Self-review notes

- Coverage: N22+N23→T1, N24+N26+N27→T2, N25→T3, N37+N38+N39+F28+F29→T4, F31+F10+F08+F30→T5, N53+N54→T6, N21+F37→T7, N28+F32+F33+F34→T8, F07+F27+F38→T9, F11+F09→T10, carry-overs→T11.
- Highest-risk / escalation-eligible: T5 F08/F30 (subtle 3D eco science — oracle-or-escalate, the eco review shipped no fixes here for good reason). T1 N23 (bsysexpl latch — subtle). T3 N25 (don't invent k-eps serialization).
- Verification is build+run (no Fortran unit tests). The restart round-trip (T2/T3) and weutro_box (T5) and a deliberate-failure MPI abort (T9/T10) are the load-bearing behavioral checks.
