# Batch 2: Build-System Truthfulness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every documented build path either works or fails loudly — fix the 6 Batch-2 items from the remediation roadmap: N02 (`make petsc` ships a SPARSKIT binary), N17 (petsc target bypasses vendor/solver validation), N19 (documented `MPI=`/`OMP=` flags are inert), N18 (`make regress` silently succeeds; dead advertised targets), N16 (Dockerfile can't build and CMD points at a nonexistent script), F42 (bump-version tags even when the commit was skipped).

**Architecture:** Point fixes in `Makefile`, `Rules.make`, `Dockerfile`, `bin/bump-version.sh`. No behavior change for any currently-working invocation: the canonical CI command (`make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr`) maps to what it already implied (NODE + no OMP) and must keep working.

**Tech Stack:** GNU Make, bash, Docker (multi-stage debian). Docker is NOT installed on this box — the Dockerfile task is verified structurally only (stated honestly in its report; a CI docker-build job would close the loop but .github/workflows edits require explicit user approval, so that is a noted follow-up, not part of this batch).

## Global Constraints

- Build/run with OpenMPI: prefix make with `PATH=/usr/bin:$PATH`. PETSc needs `PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real`.
- **cwd discipline:** every build command runs from `cd /home/razinka/shyfem` (the mar_menor Makefile has a do-nothing `fem` target).
- **The canonical commands must keep working unchanged:** `PATH=/usr/bin:$PATH make fem` and `PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr` (used by fortran-ci.yml:89 and CLAUDE.md — do NOT touch .github/workflows or CLAUDE.md in this batch).
- Makefile recipes use TAB indentation (make requirement); match surrounding style.
- Branch: `fix/b2-build-truthfulness` off `fix/b1-fortran-core-races` (stacked: PR #40 ← #41 ← this). One commit per task.
- Uncommitted user WIP in `src/tools/shynetcdf/` — never touch/stage. Untracked `testcases/examples/mar_menor/mm_hyd_conz.{str,inf}` from Batch 1 — leave alone.
- Line numbers refer to the tree at Batch-1 HEAD `66c66e1`; locate by quoted code.

---

### Task 0: Branch

- [ ] `cd /home/razinka/shyfem && git checkout -b fix/b2-build-truthfulness` (from fix/b1-fortran-core-races). `git status` must show only the known shynetcdf WIP + untracked test files. No commit.

---

### Task 1: N02 + N17 — make the `petsc` target deliver a PETSc binary and validate its inputs

**Files:**
- Modify: `Makefile:146-155` (`petsc` target)

**Why:** `bin/shyfem` is a SYMLINK to `src/shyfem/shyfem`. The current recipe `mv bin/shyfem bin/shyfem-petsc` renames the symlink, and the subsequent default rebuild replaces the symlink's target — so `bin/shyfem-petsc` dereferences to the fresh SPARSKIT binary. The fix copies the DEREFERENCED PETSc binary before any rebuild. The target also skips `check_mpi_vendor` and never validates `PETSC_DIR` (the Rules.make guard only fires when SOLVER=PETSC is set at top level, which this target does not do).

- [ ] **Step 1: Replace the target**

Current (Makefile:146-155):

```make
petsc: checkv libmod
	cd src; make SOLVER=PETSC PETSC_DIR=$(PETSC_DIR)
	@if [ -f bin/shyfem ]; then \
	  mv bin/shyfem bin/shyfem-petsc; \
	  echo "PETSc solver built as bin/shyfem-petsc"; \
	  echo "Rebuilding default SPARSKIT solver..."; \
	fi
	cd src/shyfem; make clean
	cd src; make
	@echo "Both solvers ready: bin/shyfem (SPARSKIT) and bin/shyfem-petsc (PETSc)"
```

New:

```make
petsc: checkv check_mpi_vendor libmod
	@if [ -z "$(PETSC_DIR)" ] || [ ! -d "$(PETSC_DIR)" ]; then \
	  echo "ERROR: PETSC_DIR is empty or not a directory (PETSC_DIR='$(PETSC_DIR)')"; \
	  echo "  e.g. make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real"; \
	  exit 1; \
	fi
	cd src; make SOLVER=PETSC PETSC_DIR=$(PETSC_DIR)
	@if [ -f src/shyfem/shyfem ]; then \
	  cp -L src/shyfem/shyfem bin/shyfem-petsc; \
	  echo "PETSc solver built as bin/shyfem-petsc"; \
	  echo "Rebuilding default SPARSKIT solver..."; \
	else \
	  echo "ERROR: PETSc build did not produce src/shyfem/shyfem"; \
	  exit 1; \
	fi
	cd src/shyfem; make clean
	cd src; make
	@echo "Both solvers ready: bin/shyfem (SPARSKIT) and bin/shyfem-petsc (PETSc)"
```

- [ ] **Step 2: Negative test** — `cd /home/razinka/shyfem && PATH=/usr/bin:$PATH make petsc` (no PETSC_DIR). Expected: the ERROR message, exit non-zero, no build started.

- [ ] **Step 3: Positive test** (two full builds, ~10 min; 600000 ms timeout):

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real
test ! -L bin/shyfem-petsc && echo "regular file OK"
ldd bin/shyfem-petsc | grep -i petsc          # MUST hit
ldd bin/shyfem | grep -i petsc || echo "default is SPARSKIT OK"   # must NOT hit
ldd bin/shyfem-petsc | grep libmpi            # libmpi.so.40
```

- [ ] **Step 4: Commit** — only `Makefile`; message: `fix(build): make petsc target deliver a real PETSc binary with input validation (N02, N17)` + body explaining the symlink bug.

---

### Task 2: N19 — map the documented `MPI=`/`OMP=` flags onto the real knobs

**Files:**
- Modify: `Rules.make` — insert directly after the `PARALLEL_MPI` default block (after line 115 `#PARALLEL_MPI = ELEM`)

- [ ] **Step 1: Insert the compatibility mapping**

```make
##############################################
# Compatibility mapping for the documented
# MPI=/OMP= command-line flags (they were inert)
##############################################

ifdef OMP
  ifeq ($(OMP),true)
    PARALLEL_OMP = true
  else ifeq ($(OMP),false)
    PARALLEL_OMP = false
  else
    $(error OMP must be true or false (got OMP=$(OMP)))
  endif
endif

ifdef MPI
  ifeq ($(MPI),true)
    PARALLEL_MPI = NODE
  else ifeq ($(MPI),false)
    $(error no MPI-free SHYFEM build exists (lagrange_mpi calls MPI unconditionally); the default NODE binary runs on 1 rank - just omit MPI=)
  else
    $(error MPI must be true (got MPI=$(MPI)))
  endif
endif
```

- [ ] **Step 2: Verify all five behaviors** (parse-time checks; `make -n` suffices for errors):

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make -n fem OMP=false MPI=true PARTS=METIS METISDIR=/usr >/dev/null && echo "CI command OK"
PATH=/usr/bin:$PATH make -n fem OMP=true 2>/dev/null | grep -m1 'gfortran.*-fopenmp.*-c' && echo "OMP=true maps OK"
PATH=/usr/bin:$PATH make -n fem MPI=false; echo "exit=$?"          # expect the no-MPI-free-build error, nonzero
PATH=/usr/bin:$PATH make -n fem MPI=bogus; echo "exit=$?"          # expect error
PATH=/usr/bin:$PATH make -n fem OMP=bogus; echo "exit=$?"          # expect error
```
(The `-fopenmp -c` compile-line grep discriminates: LFLAGS carries -fopenmp unconditionally on the LINK line, so only PARALLEL_OMP=true puts it on COMPILE lines.)

- [ ] **Step 3: Full-build sanity** — `PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr` completes and `ldd src/shyfem/shyfem | grep mpi` shows libmpi.so.40.

- [ ] **Step 4: Commit** — only `Rules.make`; message: `fix(build): map documented MPI=/OMP= flags onto PARALLEL_MPI/PARALLEL_OMP (N19)`.

---

### Task 3: N18 — `make regress` fails loudly; audit advertised targets

**Files:**
- Modify: `Makefile:454-456` (`regress` target) + any dead advertised target found by the audit

- [ ] **Step 1: Replace the silent guard**

Current:

```make
regress:
	if [ -d $(REGRESSDIR) ]; then SHYFEMDIR=$(PWD); \
		cd $(REGRESSDIR); make regress np=$(np); fi
```

New:

```make
regress:
	@if [ ! -d $(REGRESSDIR) ]; then \
	  echo "ERROR: regression suite directory '$(REGRESSDIR)' does not exist"; \
	  echo "  (femregress is not distributed with this repository)"; \
	  exit 1; \
	fi
	SHYFEMDIR=$(PWD); cd $(REGRESSDIR); make regress np=$(np)
```

- [ ] **Step 2: Audit the advertised targets** (bounded list from `make help` lines ~410-440): for each of `test_compile`, `compile_regress`, `test_stable`, `check_var` (scripts under `$(FEMCHECK)`) and `test_mpi` (`var/parallel`), check the referenced script/dir exists (`ls femcheck/...`, `ls var/parallel`). For each MISSING one, make the target fail with a clear one-line ERROR + exit 1 (same pattern as regress) — do NOT delete targets. List the audit results (target → exists|guarded) in the report.

- [ ] **Step 3: Test** — `make regress` → the ERROR + nonzero exit (femregress is absent here). Any newly-guarded target → its ERROR + nonzero. An existing-script target (e.g. `make check_var` if present) is NOT run — just confirmed to reference an existing file.

- [ ] **Step 4: Commit** — only `Makefile`; message: `fix(build): make regress and dead advertised targets fail loudly (N18)`.

---

### Task 4: N16 — Dockerfile: installable deps, real build, real CMD

**Files:**
- Modify: `Dockerfile`

**Why:** The builder installs no MPI/METIS, but the default Rules.make is `PARALLEL_MPI = NODE` → `make fem` cannot succeed. `CMD ./examples/mar_menor/run.sh` points at a path that does not exist (the case lives at `testcases/examples/mar_menor`, and has no `run.sh`).

- [ ] **Step 1: Fix the builder stage** — add MPI/METIS packages and build flags:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
	g++ \
	gfortran \
	libxt-dev \
	libx11-dev \
	make \
	openmpi-bin \
	libopenmpi-dev \
	libmetis-dev \
	&& rm -rf /var/lib/apt/lists/*
```

and change the build line to:

```dockerfile
# build model (NODE-MPI default; METIS partitioning)
RUN make clean && make fem PARTS=METIS METISDIR=/usr
```

- [ ] **Step 2: Fix the runtime stage** — add runtime libs:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
	libgfortran5 \
	libxt6 \
	libx11-6 \
	openmpi-bin \
	libopenmpi3 \
	libmetis5 \
	&& rm -rf /var/lib/apt/lists/*
```

and replace the CMD with a path that exists (single-rank smoke run of the shipped test case):

```dockerfile
CMD ["/bin/bash", "-lc", "cd testcases/examples/mar_menor && make init && shyfem mm_hyd_00.str"]
```

- [ ] **Step 3: Verify structurally** (docker is not installed here — say so in the report): every apt package name checked against Debian bookworm (`libopenmpi3`, `libmetis5`, `openmpi-bin`, `libmetis-dev`, `libopenmpi-dev` are the bookworm names); `testcases/examples/mar_menor/Makefile` has an `init` target; `mm_hyd_00.str` exists; `PATH` env line already puts `/root/shyfem/bin` first. Note in the report: full verification needs a docker build (CI job = follow-up requiring user approval for workflow edits).

- [ ] **Step 4: Commit** — only `Dockerfile`; message: `fix(build): Dockerfile installs MPI/METIS, builds NODE default, real CMD (N16)`.

---

### Task 5: F42 — bump-version.sh: no tag on a skipped commit

**Files:**
- Modify: `bin/bump-version.sh` (arg parsing ~lines 30-50; tag block ~lines 179-183; usage/help text)

- [ ] **Step 1: Add a `--tag-anyway` flag** — in the arg-parse `case`: `--tag-anyway)  TAG_ANYWAY=true ;;` with `TAG_ANYWAY=false` default beside the other flag defaults; add to both usage strings and the help text (`--tag-anyway  Tag even if --no-commit was given`).

- [ ] **Step 2: Guard the tag block** — replace:

```bash
if ! $NO_TAG; then
    cd "$FEMDIR"
    git tag -a "v${NEW_VERSION}" -m "SHYFEM ${NEW_VERSION}"
    echo "  Created tag: v${NEW_VERSION}"
fi
```

with:

```bash
if ! $NO_TAG; then
    if $NO_COMMIT && ! $TAG_ANYWAY; then
        echo "  Skipping tag: --no-commit was given, so v${NEW_VERSION} would point at the wrong commit"
        echo "  (pass --tag-anyway to override, or commit manually and tag afterwards)"
    else
        cd "$FEMDIR"
        git tag -a "v${NEW_VERSION}" -m "SHYFEM ${NEW_VERSION}"
        echo "  Created tag: v${NEW_VERSION}"
    fi
fi
```

- [ ] **Step 3: Test in a throwaway clone** (never run the script in the real repo):

```bash
mkdir -p /tmp/claude-1000/b2 && rm -rf /tmp/claude-1000/b2/clone
git clone -q /home/razinka/shyfem /tmp/claude-1000/b2/clone
cd /tmp/claude-1000/b2/clone
bash bin/bump-version.sh patch --no-commit            # expect: skip-tag message, NO new tag
git tag --contains HEAD | head; git status --short | head -5
git checkout -- .; bash bin/bump-version.sh patch --no-commit --tag-anyway   # expect: tag created
git tag -l 'v*' | tail -2
```
Paste raw outputs. Also `bash -n bin/bump-version.sh` for syntax. Clean up: `rm -rf /tmp/claude-1000/b2/clone`.

- [ ] **Step 4: Commit** — only `bin/bump-version.sh`; message: `fix(release): bump-version skips tagging when the commit was skipped (F42)`.

---

### Task 6: Verification + roadmap tick + stacked PR

- [ ] **Step 1:** Final builds from clean: `PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem` and the CI command variant; both green, ldd OpenMPI.
- [ ] **Step 2:** Tick Batch 2 in `docs/plans/2026-07-18-remediation-roadmap.md` progress checklist (append ` — DONE (commits <range>)`); commit `docs(plan): tick Batch 2 in remediation roadmap`.
- [ ] **Step 3:** (controller) final whole-branch review, then `git push -u origin fix/b2-build-truthfulness` and `gh pr create --base fix/b1-fortran-core-races` with summary + test plan.

## Self-review notes

- Coverage: N02+N17→T1, N19→T2, N18→T3, N16→T4, F42→T5. CI-workflow docker job explicitly OUT (needs user approval).
- The canonical CI/CLAUDE.md command is exercised in T2 Step 2/3 — mapping must be a no-op for it.
- All error paths tested negatively (petsc without PETSC_DIR, MPI=false/bogus, OMP=bogus, regress without femregress, no-commit tagging).
