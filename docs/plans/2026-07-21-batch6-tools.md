# Batch 6: Tools — Fortran & C Utilities — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. No unit-test framework for these tools — verification is: C tools compile + ASan smoke on crafted inputs; Fortran tools exercised on a real mar_menor output file. Where a fix touches subtle format logic, verify against an actual file the model produces.

**Goal:** Fix 13 tool findings (N06, N07, N08, N30-N36, F12, F39, F40, F43) + the safe subset of Batch-5-discovered findings. Themes: C memory safety (buffer overflows, format strings, unchecked realloc/malloc), Fortran tool correctness (array striding, OOB writes, stray control flow, header consistency), and a compile-restore (intgrd/maskgrd don't build at HEAD).

**Tech stack:** C (gcc, ASan available via `-fsanitize=address`), Fortran 90/fixed-form. Tools build per-subdir: `cd /home/razinka/shyfem/src/tools/<dir> && PATH=/usr/bin:$PATH make` (or `make fem`). The model binary (for producing test files) is already built at repo HEAD. mar_menor output files (.shy, .ext, .fem) are produced by running `shyfem mm_hyd_00.str` in `testcases/examples/mar_menor` (already available from prior batches).

## Global Constraints

- C fixes: prefer `snprintf(buf, sizeof(buf), ...)` + length check over `strcpy`/`sprintf`/`strcat`. Compile the touched tool with `-fsanitize=address -g` and run it on a crafted input that would have triggered the overflow — confirm ASan reports NO error after the fix (and reproduce the pre-fix overflow first where feasible).
- Fortran fixes: match fixed-form (`.f`) vs free-form (`.f90`) style per file; tab/column conventions as the file uses.
- Never touch/stage `src/tools/shynetcdf/nc_domain.f90`/`nc_util.f90` (pre-existing user WIP) EXCEPT nc2fem.f90 which is a legitimate Batch-6 target (N36) — commit nc2fem.f90 only, leave nc_domain/nc_util alone.
- Branch `fix/b6-tools` off `fix/b5-fortran-tail` (stacked #40←…←#45←this). One commit per task.
- Finding details: `docs/reviews/2026-07-18-full-codebase-deep-review.md` §2-3.

---

### Task 0: Branch + tool-build baseline + test files

- [ ] `cd /home/razinka/shyfem && git checkout -b fix/b6-tools`
- [ ] Establish which tools currently build: `cd src/tools/shyelab && PATH=/usr/bin:$PATH make 2>&1 | tail`; same for shybas, mesh, grid, postscript, femutil. Record which build clean and which fail (intgrd/maskgrd are known to fail — N06). Produce a mar_menor `.shy` output file (run the model if not present) for later Fortran-tool exercise. No commit.

### Task 1: N31 + F12 + N30 — C filename/format buffer overflows

**Files:** `src/tools/mesh/{exgrd,maskgrd,intgrd,spgrd,meshfi}.c`, `src/tools/grid/gridfi.c` (N31/F12: `sfile[80]` strcpy/strcat), `src/tools/grid/gridma2.c:272` (N30: `sprintf("%f")` into `s[20]`)

- N31/F12: five mesh tools + gridfi.c strcpy a user-controlled filename into a fixed `char sfile[80]` then strcat an extension → stack overflow on a long filename. Fix: replace each `strcpy(sfile,name); strcat(sfile,ext);` with a bounded form — either `snprintf(sfile, sizeof(sfile), "%s%s", name, ext)` with a length check that errors if truncated, OR a small central helper (a `safe_grdname()` in a shared grd util if the tools share one — check `grdio`/`grdut`; if no shared util, a per-file snprintf is fine). Report which approach.
- N30: `sprintf(s,"%f",pn->coord.x)` into `char s[20]` overflows for large coords (a `%f` of a big double can exceed 19 chars). Fix: `snprintf(s, sizeof(s), "%f", ...)` at all such sites in gridma2.c.
- [ ] **Verify (ASan):** compile ONE affected mesh tool (e.g. exgrd) with `-fsanitize=address -g` (its Makefile CFLAGS + the sanitizer). Craft an input with a >80-char filename (for N31) — confirm the PRE-fix binary ASan-aborts (stack-buffer-overflow) and the POST-fix binary does not. For N30, a crafted grd with a huge coordinate value. Report the ASan before/after.
- [ ] Commit ONLY the touched C files. Message: `fix(tools): bounded filename/coordinate formatting in mesh/grid tools (N31, F12, N30)`.

### Task 2: F39 + F40 + F43 — C format-string, realloc, record-length

**Files:** `src/tools/femutil/unform/unformatted.c` (F39 ~486, F43 ~232), `src/tools/postscript/psgraph.c:657` (F40)

- F39: `Error()` uses an uninitialized `int dummy` as a printf arg with the caller string as the FORMAT: `fprintf(stderr, string, dummy)` — a format-string bug (if `string` contains `%s`/`%n`, UB/crash). Fix: `fprintf(stderr, "%s", string)` (drop the uninitialized arg; the caller message is data, not a format).
- F40: `PsInitColorTable` does `CT = realloc(CT, ...)` (self-assignment leaks on failure) with no NULL check before deref. Fix: `tmp = realloc(CT, ...); if(!tmp){ <handle/abort> } CT = tmp;` for each of CT1/CT2/CT3.
- F43: `unformatted.c` reads a file-supplied record length `nrec1` and passes it to malloc/fread with no bound → a crafted file drives a huge allocation / over-read. Fix: bound `nrec1` against the actual remaining file size (fstat/ftell) before malloc/fread; error on an implausible length.
- [ ] **Verify (ASan):** compile unformatted.c + psgraph.c users with ASan. F39: feed a "filename" or message containing `%s` and confirm no crash/UB after fix. F43: craft a truncated file claiming a huge record length → confirm the fix rejects it cleanly (no huge malloc / over-read; ASan clean). Report before/after.
- [ ] Commit. Message: `fix(tools): format-string, realloc NULL-check, bounded record length (F39, F40, F43)`.

### Task 3: N06 — restore intgrd/maskgrd compile + NULL-guard InterpolateDepth

**Files:** `src/tools/mesh/intgrd.c`, `src/tools/mesh/maskgrd.c`

- PREREQUISITE (real): both fail to compile — `ReadStandard(s,G)` is called with 2 args but `grdio.h:47` declares `void ReadStandard(char *fname, Grid_type *G, char *ext)` (3 args). Fix the calls to pass the 3rd `ext` argument. Determine the correct `ext` value: read how ReadStandard uses `ext` (grdio.c) and what other callers pass (grep `ReadStandard(` across src/tools) — likely a default extension string or NULL. Apply so both tools compile.
- N06 proper: after the compile fix, `intgrd.c:131-133` does `ped = FindElement(GD,xm,ym); pe->depth = InterpolateDepth(GD,ped,xm,ym)` — FindElement returns NULL for an out-of-coverage centroid, and InterpolateDepth dereferences `ped` → NULL deref. Guard: if `ped == NULL`, warn (fprintf stderr naming the point) and SKIP that centroid (don't set pe->depth from a NULL element), continuing the loop. Verdict is PLAUSIBLE/low — but the compile-restore alone is high-value.
- [ ] **Verify:** both tools now compile (`cd src/tools/mesh && make intgrd maskgrd`). Run intgrd on a small grd + a background grd where at least one centroid falls outside coverage — confirm it warns+skips instead of crashing (ASan-compiled run for the NULL-deref path). If constructing an out-of-coverage case is hard, verify the NULL guard by inspection + an ASan run on a normal case (no false abort). Report.
- [ ] Commit ONLY intgrd.c, maskgrd.c. Message: `fix(tools): restore intgrd/maskgrd compile (ReadStandard 3-arg) + NULL-guard InterpolateDepth (N06)`.

### Task 4: N07 + N08 — femelab/shyelab correctness

**Files:** `src/tools/shyelab/femelab1.f90:937` (N07), `src/tools/shyelab/shyelab1.f90:554` (N08)

- N07: `-write`/`-condense` use a PER-VARIABLE lmax as the array leading dimension, so a mixed 2D/3D FEM file (different lmax per variable) is mis-strided → wrong output. Fix: use the FILE-GLOBAL vertical dimension (the max lmax across variables, or the file's declared nlv) as the leading dimension for the read/write buffers. Read how the FEM file records lmax per variable and where the global dimension is available.
- N08: `-vorticity` writes NODAL vorticity data but with a stale `belem=.true.` (element flag), so it's written as an element record (wrong), and for fem/gis/nc output formats it silently writes nothing. Fix: set `belem=.false.` for the nodal vorticity record; for the unsupported fem/gis/nc formats, hard-error (clear message) instead of silently writing nothing.
- [ ] **Verify:** exercise femelab `-write` on a real mixed-2D/3D FEM file if one exists (or construct a minimal one); confirm output striding is correct. shyelab `-vorticity` on a mar_menor .shy → confirm the record is nodal (not element) and unsupported formats error clearly. If a mixed FEM file is hard to produce, verify N07 by code trace + a uniform-lmax file (no regression) and note it. Report.
- [ ] Commit. Message: `fix(tools): femelab file-global lmax striding; shyelab vorticity nodal record + unsupported-format error (N07, N08)`.

### Task 5: N34 + N35 — extelab stats + shy_util2 OOB

**Files:** `src/tools/shyelab/extelab1.f90:387` (N34), `src/tools/shyelab/shy_util2.f:310` (N35)

- N34: `extelab -write` prints hydro statistics from an UNINITIALIZED/stale buffer due to an `ivar==0` vs `ivar==1` convention mismatch (the stats buffer is filled under one convention but read under the other). Initialize the stats buffer and fix the condition so hydro stats come from the CURRENT record.
- N35: `read_records` writes `ivars(:,0)` OUT OF BOUNDS when a zeta record (`ivar=-1`) leads a shy time record (the index computed from ivar hits 0, below the array's lower bound 1). Guard the `ivar=-1` leading-record case so index 0 is never written.
- [ ] **Verify:** run extelab `-write` on a real mar_menor .ext file (produce one — mar_menor writes extra-point time series if configured; check the STR for `extra`/points, or construct a minimal .ext). shy_util2: run a shyelab operation on a .shy whose first record is zeta (ivar=-1) — confirm no OOB (ASan-compiled or bounds-checked `-fcheck=bounds` build catches it). Report before/after (the -fcheck=bounds build should abort pre-fix on N35).
- [ ] Commit. Message: `fix(tools): extelab stats-buffer init/convention; shy_util2 guard zeta-leading ivars index (N34, N35)`.

### Task 6: N32 + N33 — shybas interpolation

**Files:** `src/tools/shybas/basutil_interp.f:690` (N32), `:368` (N33)

- N32: `interpola` (shybas `-bmode 3`) has an UNCONDITIONAL `cycle` in the point loop that skips EVERY bathymetry point → the mode always produces nothing/aborts. Remove the stray `cycle` (read the loop to confirm it's genuinely unconditional and unintended — not gated by a condition that's just hard to see).
- N33: `interpole`/`interpola` use a scratch array `ok(nel)` sized by element count, but in NODE-mode interpolation (nkn > nel meshes) it's indexed by node → overflow. Size it `max(nel,nkn)`.
- [ ] **Verify:** run `shybas -bmode 3` (interpolation) on a mar_menor .bas — confirm bmode-3 now processes points (produces interpolated output, not empty/abort). For N33, a mesh with nkn>nel (most meshes: nkn>nel is typical) node-mode interpolation — `-fcheck=bounds` build should abort pre-fix on the ok() overflow, clean post-fix. Report. Add a smoke check that bmode-3 output is non-empty.
- [ ] Commit. Message: `fix(tools): shybas bmode-3 stray cycle; size interp scratch array max(nel,nkn) (N32, N33)`.

### Task 7: N36 — nc2fem header lmax consistency

**Files:** `src/tools/shynetcdf/nc2fem.f90:988` (commit ONLY nc2fem.f90 — leave nc_domain/nc_util alone)

- N36: `nc2fem` clobbers the header `lmax` with a per-data-record lmax, producing an internally-inconsistent `out.fem` when a data record's vertical dimension `nz1` differs from the header `nz`. Fix: preserve the header `lmax`; if a data record's lmax EXCEEDS the header lmax, ERROR (clear message) instead of silently rewriting the header.
- [ ] **Verify:** nc2fem needs a NetCDF input. If a test NetCDF is available (check testcases), run nc2fem and confirm the header lmax is preserved and a mismatched record errors. If no NetCDF input is readily available, verify by code trace + build-clean and note the runtime-verification gap. Report.
- [ ] Commit ONLY nc2fem.f90. Message: `fix(tools): nc2fem preserves header lmax, errors on oversized record (N36)`.

### Task 8: Batch-5-discovered safe closes

**Files:** `src/contrib/ecological/mercury/merc_sed4sed.f90` (massert), `src/utils/shympi/mpi_node.f90` (N28-class automatics), `src/utils/generic/convert.f90` (istod exponent underflow)

Three cheap, safe closes surfaced during Batch 5 (recorded in the ledger). Do the mechanical/safe ones; do NOT attempt the kepsilon.f90:505 cold-start SIGFPE (that needs real numerical investigation — leave it as a documented follow-up).

- massert: `merc_sed4sed.f90:480` `stop 'error stop massert: assertion violated'` is in an MPI-active path (called from `sed4merc_sed`). Convert to `call shympi_abort_internal(...)` (same message), matching Batch 5's F09 sweep.
- mpi_node.f90 N28-class: `shympi_check_3d_node_r`/`_3d0_node_r` have global-mesh-sized AUTOMATIC arrays (same crash class as N28). Convert to allocatable + stat + abort + deallocate. (These are debug/check routines — lower frequency, but same fix.)
- istod exponent underflow: `convert.f90` `10.**(kexp*iesign)` uses a single-precision literal `10.` so extreme exponents underflow to 0 in the double result. Change to `10.d0**(kexp*iesign)` (double-precision base) so `3.456e-102` yields the true value, not 0. Verify with a driver (reuse Task 6's N53 driver approach from Batch 5): `3.456e-102` now parses to ~3.456e-102, not 0.
- [ ] **Verify:** build serial + MPI (`make fem` / `... PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr`) — clean, libmpi.so.40. mar_menor regression byte-identical. istod driver shows the exponent fix. Report.
- [ ] Commit. Message: `fix: close Batch-5-discovered items — massert abort, mpi_node check-array alloc, istod exponent precision`.

### Task 9: Verify + roadmap tick + final review + PR

- [ ] Build all touched tools clean; ASan smoke on the C tools passes on crafted inputs (Tasks 1-3 evidence); Fortran tools exercised on real mar_menor files (Tasks 4-7). Model build matrix (serial/MPI) still green (Task 8 touched shared files).
- [ ] Tick Batch 6 in the roadmap (` — DONE`); note any runtime-verification gaps (nc2fem NetCDF, mixed-FEM file). Commit.
- [ ] (Controller) final whole-branch review (most capable model) + fortran-reviewer agent pass (for the Fortran-tool + Task-8 changes); one fix subagent for combined findings.
- [ ] (Controller) push + `gh pr create --base fix/b5-fortran-tail`.

## Self-review notes

- Coverage: N31+F12+N30→T1, F39+F40+F43→T2, N06→T3, N07+N08→T4, N34+N35→T5, N32+N33→T6, N36→T7, Batch-5-discovered→T8.
- C memory-safety tasks (T1/T2/T3) get ASan before/after evidence — this is the exit criterion for C tools.
- Fortran-tool tasks (T4-T7) get real-file exercise; where a specific input (mixed-FEM, NetCDF) is hard to produce, code-trace + no-regression + a stated gap is acceptable.
- kepsilon.f90:505 cold-start SIGFPE is DEFERRED (real numerical bug, not a mechanical close) — documented as a follow-up, not attempted here.
