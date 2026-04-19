# Codebase Safety Fixes Implementation Plan

> **STATUS: COMPLETED.** All 12/12 tasks done, merged as PR #7 (per MEMORY.md). Archived 2026-04-19.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 3 critical and 8 high-severity findings from the 2026-04-04 deep codebase review, plus key medium findings and new issues from the 2026-04-05 deep analysis, grouped into 12 safe, independently testable tasks.

**Architecture:** Each task targets a single concern. Tasks are ordered by severity. Each task is a separate commit. Fortran fixes are verified by building (serial + OMP) and running the mar_menor test case. Python fixes are verified by existing + new unit tests.

**Tech Stack:** Fortran 90/95 (gfortran), Python 3.13 (Shiny), pytest, GNU Make, OpenMPI

**Reference:** `docs/2026-04-04-deep-codebase-review.md` (original), consolidated analysis 2026-04-05

**Task dependencies:**
- Tasks 3→6: both modify `session_auth.py` — Task 3 MUST be committed before Task 6
- Tasks 6→8: both modify `admin.py` — Task 6 MUST be committed before Task 8
- Tasks 4→7: both modify `hydrodynamic.f90` — Task 4 MUST be committed before Task 7
- Tasks 5→11: both modify `turbulence.f90`/concentration files — Task 5 before Task 11

**Completion status:**
- Tasks 1-3: ✅ COMMITTED (`8aebeea`, `7e4e31a`, `fd5b712`)
- Tasks 4-5: Code written (uncommitted), validated by review agent 2026-04-05
- Tasks 6-12: Not started

**Deferred findings (documented, not addressed in this plan):**
- H9 (no auto Fortran dependency tracking) — requires build system redesign, separate project
- H10 (parallel make unsafe) — coupled with H9, requires `recursivemake` rewrite
- H12 (no Fortran CI) — separate infrastructure task, needs CI access credentials
- H13 (zero Fortran tests) — large effort, should be its own plan with pFUnit setup
- H14 (5 UI pages untested) — incremental, can be done independently per page
- M1, M3, M4, M6-M12, M21, M27 — lower priority, tracked in review report
- MPI1 (mpi_buffer.f90 underflow edge case) — rare, needs production-mesh profiling to justify

---

## Task 1: Fix C1 — Race Condition on `save` Arrays in `scal_adv_nudge`

**Status:** ✅ COMMITTED (`8aebeea`)
**Findings:** C1 (CRITICAL)
**Root cause:** `scal_adv_nudge` in `concentration.f90` has `allocatable, save` arrays (`r3v`, `wsinkv`, `load`) at lines 397-399. Two OMP TASKs in `baroclinic.f90` call this subroutine concurrently for temperature (line 476) and salinity (line 495). `save` variables are shared across invocations, so both tasks corrupt each other's data.

**Files:**
- Modify: `src/shyfem/baroclinic.f90:469-503`

**Strategy:** Remove the OMP TASK directives entirely and call the subroutines sequentially. Adding TASKWAIT between the tasks would fix the race but leave dead overhead (task creation with zero parallelism). The cleaner fix is to remove the task wrappers since they can never run concurrently safely.

- [x] **Step 1: Remove OMP TASK wrappers, keep sequential calls**

In `src/shyfem/baroclinic.f90`, replace lines 469-503:

```fortran
!$OMP TASK PRIVATE(what,dtime) FIRSTPRIVATE(thpar,wsink,robs,itemp) &
!$OMP&     SHARED(idtemp,tempv,difhv,difv,difmol,tobsv,ttauv) &
!$OMP&     DEFAULT(NONE) &
!$OMP&     IF(itemp > 0)

          if( itemp .gt. 0 ) then
		what = 'temp'
                call scal_adv_nudge(what,0 &
     &                          ,tempv,idtemp &
     &                          ,thpar,wsink &
     &                          ,difhv,difv,difmol &
     &				,tobsv,robs,ttauv)
	  end if

!$OMP END TASK

!	  call openmp_get_thread_num(tid)
!	  !write(6,*) 'number of thread of salt: ',tid

!$OMP TASK PRIVATE(what,dtime) FIRSTPRIVATE(shpar,wsink,robs,isalt) &
!$OMP&     SHARED(idsalt,saltv,difhv,difv,difmol,sobsv,stauv) &
!$OMP&     DEFAULT(NONE) &
!$OMP&     IF(isalt > 0)

          if( isalt .gt. 0 ) then
		what = 'salt'
                call scal_adv_nudge(what,0 &
     &                          ,saltv,idsalt &
     &                          ,shpar,wsink &
     &                          ,difhv,difv,difmol &
     &				,sobsv,robs,stauv)
          end if

!$OMP END TASK
!$OMP TASKWAIT
```

with:

```fortran
          if( itemp .gt. 0 ) then
		what = 'temp'
                call scal_adv_nudge(what,0 &
     &                          ,tempv,idtemp &
     &                          ,thpar,wsink &
     &                          ,difhv,difv,difmol &
     &				,tobsv,robs,ttauv)
	  end if

          if( isalt .gt. 0 ) then
		what = 'salt'
                call scal_adv_nudge(what,0 &
     &                          ,saltv,idsalt &
     &                          ,shpar,wsink &
     &                          ,difhv,difv,difmol &
     &				,sobsv,robs,stauv)
          end if
```

- [x] **Step 2: Build serial and OMP**
- [x] **Step 3: Run mar_menor test case**
- [x] **Step 4: Commit**

---

## Task 2: Fix C2 — Tool Name Allowlist in `shyfem_wrapper.py`

**Status:** ✅ COMMITTED (`7e4e31a`)
**Findings:** C2 (CRITICAL)
**Root cause:** `get_executable()` accepts any `tool_name` string with no validation. Falls back to `shutil.which()`, allowing arbitrary binary execution.

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:27-67`
- Modify: `shyfem-ui/tests/test_wrapper.py` (update existing tests)

- [x] **Steps 1-7: Implemented and committed**

---

## Task 3: Fix C3 — WebSocket Authentication Behind Reverse Proxy

**Status:** ✅ COMMITTED (`fd5b712`)
**Findings:** C3 (CRITICAL)
**Root cause:** When `root_path` is set (reverse proxy deployment), WebSocket auth is completely skipped at line 588.

**Strategy:** Restrict bypass to connections from localhost (Shiny Server connects from 127.0.0.1).

- [x] **Steps 1-6: Implemented and committed**

---

## Task 4: Fix H1 + DZ1 — Division by Zero Guards in Fortran Solvers

**Findings:** H1 (HIGH), DZ1 (CRITICAL — new from 2026-04-05 analysis)
**Note:** `hhi` (layer thickness) can be zero OR negative during wetting/drying. The `hhi > 0` guard correctly handles both cases. DZ1 is a **code divergence bug**: the OMP solver in `concentration_omp.f90` has zero guards but the serial solver in `concentration.f90` does not.

**Files:**
- Modify: `src/shyfem/hydrodynamic.f90:1353,1873`
- Modify: `src/shyfem/concentration.f90:1561,1565` ← **NEW (DZ1)**

- [ ] **Step 1: Add `hhi` guard around implicit advective contribution**

At line 1353, change:

```fortran
	if( aux .gt. 0. ) then		!implict treatment of non-linear terms
```

to:

```fortran
	if( aux .gt. 0. .and. hhi .gt. 0. ) then	!implict treatment of non-linear terms
```

This prevents division by `hhi` at lines 1355-1361 when `hhi <= 0` (dry/flooded layer).

- [ ] **Step 2: Add `va` guard around free-surface divergence computation**

At line 1873, change:

```fortran
	  dz = dt * wlnv(lmin-1,k) / va(lmin,k)
```

to:

```fortran
	  if( va(lmin,k) .gt. 0. ) then
	    dz = dt * wlnv(lmin-1,k) / va(lmin,k)
	  else
	    dz = 0.	! zero area node: no free-surface correction
	  end if
```

- [ ] **Step 3: Add zero guards to serial tridiagonal solver in `concentration.f90`** ← **NEW**

At line 1561, replace:

```fortran
	  aux=1./cdiag(jlevel,k)
```

with:

```fortran
	  if( cdiag(jlevel,k) .eq. 0. ) then
	    write(6,*) 'warning: cdiag zero at node ',k,' level ',jlevel
	    cycle  ! skip this node — degenerate system
	  end if
	  aux=1./cdiag(jlevel,k)
```

At line 1565, replace:

```fortran
	    aux=1./(cdiag(l,k)-clow(l,k)*chigh(l-1,k))
```

with:

```fortran
	    if( cdiag(l,k)-clow(l,k)*chigh(l-1,k) .eq. 0. ) then
	      write(6,*) 'warning: tridiag pivot zero at node ',k,' level ',l
	      exit  ! abandon forward sweep for this node — degenerate pivot
	    else
	      aux=1./(cdiag(l,k)-clow(l,k)*chigh(l-1,k))
	    end if
```

**Note on `exit` at line 1565:** In Fortran, `exit` terminates the innermost enclosing loop — here the inner `do l=jlevel+1,ilevel` forward sweep. This abandons the forward sweep at the degenerate level and drops through to the back-substitution pass (lines 1570-1572), which operates on partially computed values for levels above the zero pivot. This is intentional: continuing the forward sweep past a zero pivot would corrupt all remaining levels via cascading garbage. The result for this node is approximate, not mathematically correct — this is a safety net, not a solver fix. (Note: `cycle` would advance to `l+1` within the same loop, which is WRONG — `chigh(l-1,k)` would be uninitialized from the skipped level.)

**Design rationale for DZ1:** The OMP version at `concentration_omp.f90:881-889` uses `stop` on zero diag, but stopping silently loses simulations. Instead: warn and skip degenerate nodes. The `cycle` at line 1561 skips the entire outer `do k` loop iteration (correct — degenerate node at first level). The `exit` at line 1565 terminates the inner `do l` forward-sweep loop (correct — degenerate pivot mid-column). This matches the explicit guard pattern at line 1550 where `cdiag==0` simply skips the division.

- [ ] **Step 4: Build and run test (NORMAL, OMP, and SPEED profiles)**

```bash
cd /home/razinka/shyfem
make clean && make fem
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5

cd /home/razinka/shyfem
make clean && make fem OMP=true

cd /home/razinka/shyfem
make clean && make fem COMPILER_PROFILE=SPEED
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Clean build in all three modes, test runs complete with no NaN or SIGFPE.

- [ ] **Step 5: Commit**

```bash
git add src/shyfem/hydrodynamic.f90 src/shyfem/concentration.f90
git commit -m "fix(solver): add division-by-zero guards in hydro and concentration solvers

Add hhi>0 guard on implicit advective contribution (hydrodynamic.f90:1353)
to prevent division by zero/negative-thickness layers during wetting/drying.
Add va>0 guard on free-surface divergence (hydrodynamic.f90:1873) to prevent
division by zero node area during extreme drying.
Add zero-pivot guards in serial tridiagonal solver (concentration.f90:1561,
1565) — the OMP version had guards but the serial version did not.

Ref: review findings H1, DZ1"
```

---

## Task 5: Fix H2 — Stack Overflow in `turbulence.f90`

**Findings:** H2 (HIGH)

**Files:**
- Modify: `src/shyfem/turbulence.f90:137-139,162,205,213,219`

- [ ] **Step 1: Convert automatic arrays to allocatable with caching**

Replace lines 137-139:

```fortran
	real shearf2(nlvdi,nkn)
	real buoyf2(nlvdi,nkn)
	real richard(nlvdi,nkn)
```

with:

```fortran
	real, allocatable, save :: shearf2(:,:)
	real, allocatable, save :: buoyf2(:,:)
	integer ierr_alloc
```

Remove `richard` entirely — confirmed dead code: written at lines 205, 213, 219 but never read anywhere in the codebase.

- [ ] **Step 2: Add lazy allocation after `icall` check**

After line 158 (`if( icall .lt. 0 ) return`), add:

Replace the existing allocation block at lines 160-163 (which currently uses bare `stop`) with:

```fortran
	if( .not. allocated(shearf2) ) then
	  allocate(shearf2(nlvdi,nkn),buoyf2(nlvdi,nkn),stat=ierr_alloc)
	  if( ierr_alloc /= 0 ) call shympi_abort_internal( &
     &        'munk_anderson_shell: allocation failed')
	end if
```

**Note:** `shympi_abort_internal` is a standalone external subroutine (defined in `mpi_node_internal.f90` and `mpi_dummy.f90`), NOT a module procedure — it does not require `use shympi`. It can be called directly with an implicit interface. The existing bare `stop` MUST be replaced per CLAUDE.md convention: `munk_anderson_shell` is called from the main timestep loop which may run under MPI; bare `stop` would hang other MPI ranks.

Note: `nlvdi` and `nkn` are set during mesh initialization and never change, so allocatable+save is safe.

- [ ] **Step 3: Remove all writes to `richard` array**

Remove these 3 lines (all writes to the `richard` array):
- Line 205: `richard(l,k) = ri`
- Line 213: `richard(flev,k) = 0.`
- Line 219: `richard(nlev,k) = richard(nlev-1,k)`

- [ ] **Step 4: Build and run test (serial + OMP)**

```bash
cd /home/razinka/shyfem
make clean && make fem
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5

cd /home/razinka/shyfem
make clean && make fem OMP=true
```

Expected: Clean build in both modes, all timesteps complete, identical results.

- [ ] **Step 5: Commit**

```bash
git add src/shyfem/turbulence.f90
git commit -m "fix(turbulence): convert stack arrays to allocatable, remove dead richard array

munk_anderson_shell allocated ~60MB of automatic arrays on the stack
(shearf2, buoyf2, richard). This crashes on production meshes with
default 8MB stack limits. Convert to allocatable,save with lazy init.
Remove richard array entirely — written but never read. Use
shympi_abort_internal instead of bare stop for MPI safety.

Ref: review finding H2"
```

---

## Task 6: Fix H3-H6 — Security Hardening (Session, Password, Login Page)

**Findings:** H3, H4, H5, H6 (all HIGH)
**Dependency:** Task 3 must be committed first (both modify `session_auth.py`).

**Files:**
- Modify: `shyfem-ui/shyfem_ui/middleware/session_auth.py:459,664-666`
- Modify: `shyfem-ui/shyfem_ui/pages/admin.py:64,309`
- Modify: `shyfem-ui/shyfem_ui/config.py`
- Test: `shyfem-ui/tests/test_admin_page.py` (existing file)
- Test: `shyfem-ui/tests/test_session_auth_middleware.py`

- [ ] **Step 1: Write tests for password policy**

Add to `shyfem-ui/tests/test_admin_page.py`:

```python
from shyfem_ui.pages.admin import _validate_create_user_form

def test_password_minimum_length_8():
    """Password must be at least 8 characters."""
    errors = _validate_create_user_form("testuser", "short", "user", "test@example.com")
    assert any("at least 8" in e for e in errors)


def test_password_7_chars_rejected():
    """7-character password is rejected."""
    errors = _validate_create_user_form("testuser", "1234567", "user", "test@example.com")
    assert any("at least 8" in e for e in errors)


def test_password_8_chars_accepted():
    """8-character password is accepted."""
    errors = _validate_create_user_form("testuser", "12345678", "user", "test@example.com")
    assert not any("password" in e.lower() for e in errors)
```

- [ ] **Step 2: Run tests to verify password test fails**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_page.py::test_password_minimum_length_8 -v
```

Expected: FAIL (current minimum is 4).

- [ ] **Step 3: Fix password minimum in `admin.py`**

In `admin.py`, line 64, change `< 4` to `< 8` and update the error message to "at least 8 characters". Apply the same change in `_do_reset_pw` at line 309.

Also update the existing test `test_password_exactly_4_chars` in `test_admin_page.py` — change it to test 8 chars:

```python
def test_password_exactly_8_chars(self):
    errors = _validate_create_user_form("alice", "abcd1234", "user", email="alice@example.com")
    assert errors == []
```

- [ ] **Step 4: Add `Secure` flag to session cookie**

In `config.py`, add a field after the existing cookie/session settings:

```python
    use_secure_cookies: bool = Field(
        default=False,
        description="Set Secure flag on session cookies (enable when behind HTTPS)",
    )
```

In `session_auth.py`'s `__init__`, accept `use_secure_cookies=False` as a parameter and store it as `self.use_secure_cookies`.

In `_handle_login_post`, update the cookie construction (lines 664-666):

```python
        secure = "; Secure" if self.use_secure_cookies else ""
        cookie = (
            f"shyfem_session={token}; "
            f"Path={cookie_path}; HttpOnly; SameSite=Lax; Max-Age={ttl_seconds}{secure}"
        )
```

In `app.py` where the middleware is instantiated, pass `use_secure_cookies=config.use_secure_cookies`.

- [ ] **Step 5: Remove default credentials from login page**

In `session_auth.py`, line 459, remove:

```html
        <li style="margin-top:6px;opacity:0.65;">&rarr; Try it: log in with <b>user</b> / <b>user</b></li>
```

- [ ] **Step 6: Add CSRF token to login form (double-submit cookie pattern)**

In `session_auth.py`, add `import secrets` at the top.

In `_serve_login_page`, generate a CSRF token and include it as both a hidden form field and a cookie:

```python
csrf_token = secrets.token_urlsafe(32)
```

Add hidden input to the form HTML string (inside the `<form>` tag):

```html
<input type="hidden" name="csrf_token" value="{csrf_token}">
```

Add a Set-Cookie header in the response for the CSRF token:

```python
(b"set-cookie", f"csrf_token={csrf_token}; Path={cookie_path}; SameSite=Lax".encode("utf-8")),
```

In `_handle_login_post`, extract the `csrf_token` from both the form body and the request cookies. Compare them:

```python
form_csrf = form_data.get("csrf_token", "")
cookie_csrf = ""
for name, value in cookies:
    if name == "csrf_token":
        cookie_csrf = value
        break
if not form_csrf or form_csrf != cookie_csrf:
    await self._serve_login_page(
        send,
        error='<div class="error">Invalid request. Please try again.</div>',
        root_path=root_path,
    )
    return
```

- [ ] **Step 7: Run all tests**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x --tb=short -q 2>&1 | tail -10
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add shyfem-ui/shyfem_ui/middleware/session_auth.py shyfem-ui/shyfem_ui/pages/admin.py shyfem-ui/shyfem_ui/config.py shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_admin_page.py shyfem-ui/tests/test_session_auth_middleware.py
git commit -m "fix(security): harden session, password policy, CSRF, and login page

- Increase minimum password length from 4 to 8 characters
- Add configurable Secure flag on session cookies (use_secure_cookies)
- Remove default credentials hint from login page
- Add CSRF token to login form (double-submit cookie pattern)

Ref: review findings H3, H4, H5, H6"
```

---

## Task 7: Fix M2 — `stop` Inside OMP Parallel Regions

**Findings:** M2 (MEDIUM — undefined behavior on error paths), M2A, M2B from 2026-04-05 analysis
**Dependency:** Task 4 must be committed first (both modify `hydrodynamic.f90`).

**Files:**
- Modify: `src/shyfem/hydrodynamic.f90:987-1000`
- Modify: `src/shyfem/elems_dealing.f90:1159-1190`

**Note:** `concentration_omp.f90` stops (lines 436, 739, 846, 885) are excluded — they are inside deeply nested TASK/subroutine chains where error flag propagation requires major refactoring. The checks are assertions that catch internal bugs, not data-dependent failures. Tracked as deferred.

- [ ] **Step 1: Replace `stop` with REDUCTION error flag in `hydrodynamic.f90`**

Add `integer :: ierr_rms` to local declarations of `hydro_transports`.

Replace lines 987-1000:

```fortran
	  ierr_rms = 0

!$OMP PARALLEL DO FIRSTPRIVATE(bcolin,baroc,az,am,af,at,radv       &
!$OMP &            ,vismol,rrho0,dt) PRIVATE(ie,rmsdif)  &
!$OMP &     SHARED(nel,nchunk) REDUCTION(max:ierr_rms) DEFAULT(NONE)

 	  do ie=1,nel
	    call hydro_intern(ie,bcolin,baroc,az,am,af,at,radv &
     &			,vismol,rrho0,dt,rmsdif)
	    if( rmsdif > 1.D-10 ) then
	      ierr_rms = 1
	    end if
	  end do

!$OMP END PARALLEL DO

	  if( ierr_rms /= 0 ) then
	    write(6,*) 'error: rmsdif too high in hydro_transports'
	    stop 'error stop hydro_transports: rms too high'
	  end if
```

- [ ] **Step 2: Replace `stop` with error flag in `elems_dealing.f90`**

In `elems_dealing.f90`, the `stop` at line 1186 is preceded by `write(6,*)` statements and calls to `check_set_unit`, `check_node`, `check_elems_around_node` which are not thread-safe. Wrap the entire error block in `!$OMP CRITICAL`:

Replace lines 1174-1187:

```fortran
	    if( h <= hmin ) then
!$OMP CRITICAL
	      write(6,*) 'error computing layer thickness'
	      write(6,*) 'no layer depth in node: ',k,l,lmax
	      write(6,*) 'depth: ',h
	      write(6,*) 'nlv,lmax: ',nlv,lmax
	      write(6,*) 'nsigma: ',nsigma
	      write(6,*) 'hlv: ',hlv
	      write(6,*) 'hldv: ',hldv
	      write(6,*) 'additional information available in fort.666'
	      call check_set_unit(666)
	      call check_node(k)
	      call check_elems_around_node(k)
	      ierr_depth = 1
!$OMP END CRITICAL
	    end if
```

Add `integer :: ierr_depth` to local declarations and `SHARED(ierr_depth)` to the OMP directive. Initialize `ierr_depth = 0` before the parallel region. After `!$OMP END PARALLEL DO`, add:

```fortran
	if( ierr_depth /= 0 ) then
	  stop 'error stop setdepth: no layer in node'
	end if
```

- [ ] **Step 3: Build and run test with OMP enabled**

```bash
cd /home/razinka/shyfem
make clean && make fem OMP=true
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Clean build, all timesteps complete.

- [ ] **Step 4: Commit**

```bash
git add src/shyfem/hydrodynamic.f90 src/shyfem/elems_dealing.f90
git commit -m "fix(omp): replace stop inside parallel regions with error flags

Calling stop from within an OMP parallel region is undefined behavior.
In hydro_transports, use REDUCTION(max:ierr_rms) flag checked after
the parallel region. In setdepth, wrap error diagnostics in OMP
CRITICAL and defer stop to after the parallel region.

concentration_omp.f90 stops excluded — assertion-only checks in deep
task chain, refactoring deferred.

Ref: review finding M2"
```

---

## Task 8: Fix M5 — Path Traversal via Username + STR File Path Validation

**Findings:** M5 (MEDIUM), NEW-1 (unsafe path joining in file_service.py)
**Dependency:** Task 6 must be committed first (both modify `admin.py`).

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/admin.py:60`
- Modify: `shyfem-ui/shyfem_ui/models/user.py:51-60`
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py:232-248` ← **NEW**
- Test: `shyfem-ui/tests/test_admin_user_management.py` (existing file)

- [ ] **Step 1: Write failing test for username path traversal**

Add to `shyfem-ui/tests/test_admin_user_management.py`:

```python
def test_username_rejects_dotdot():
    """Username '..' must be rejected to prevent path traversal."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("..", "password123", "user", "test@example.com")
    assert any("consecutive dots" in e.lower() or "username" in e.lower() for e in errors)


def test_username_rejects_dotdot_embedded():
    """Username 'foo..bar' must be rejected."""
    from shyfem_ui.pages.admin import _validate_create_user_form
    errors = _validate_create_user_form("foo..bar", "password123", "user", "test@example.com")
    assert len(errors) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_user_management.py::test_username_rejects_dotdot tests/test_admin_user_management.py::test_username_rejects_dotdot_embedded -v
```

Expected: FAIL (current regex allows `..`).

- [ ] **Step 3: Update username validation in `admin.py`**

In `admin.py`, after line 60 (the regex check), add:

```python
    elif '..' in username:
        errors.append("Username must not contain consecutive dots")
```

- [ ] **Step 4: Add defense-in-depth to `User.home_dir()`**

In `models/user.py`, harden `home_dir()` at line 51-60:

```python
    def home_dir(self, user_data_root: Path) -> Path:
        """Return the per-user data directory path."""
        result = (Path(user_data_root) / self.username).resolve()
        root = Path(user_data_root).resolve()
        if not str(result).startswith(str(root)):
            raise ValueError(f"Username {self.username!r} escapes data root")
        return result
```

- [ ] **Step 5: Validate file paths in STR parameter checking** ← **NEW**

In `file_service.py`, at lines 232-248, wrap the path joining with `config.validate_path()`:

```python
        if param in cls._NAME_FILE_PARAMS and isinstance(value, str) and value:
            try:
                cfg = get_config()
                path = cfg.validate_path(work_dir / value, must_exist=False)
            except ValueError:
                warnings.append(f"Invalid/unsafe file path for $name/{param}: {value}")
                continue
            if not path.exists():
                warnings.append(f"Missing file for $name/{param}: {value}")
```

This uses the existing `get_config().validate_path()` which resolves symlinks and checks containment. `file_service.py` already imports `get_config` from `shyfem_ui.config` (line 6).

- [ ] **Step 6: Run tests**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_user_management.py tests/test_admin_page.py -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/admin.py shyfem-ui/shyfem_ui/models/user.py shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_admin_user_management.py
git commit -m "fix(security): reject '..' in usernames, harden home_dir(), validate STR paths

Add explicit '..' check in username validation to prevent path traversal.
Add defense-in-depth in User.home_dir() — resolve path and verify it
stays under user_data_root. Validate file paths referenced in STR
parameter checking using config.validate_path().

Ref: review findings M5, NEW-1"
```

---

## Task 9: Fix H11, M22-M23 — Swallowed Error Handling in Python UI

**Findings:** H11, M22, M23 (HIGH + MEDIUM), NEW-2 (unvalidated restart file)

**Note:** Original review findings M24 (notification_service:134), M25 (app.py:165), M26 (app.py:211) are already fixed — they already use `logger.warning` or `logger.exception`. Only 4 files need changes.

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/job_local.py:78,137`
- Modify: `shyfem-ui/shyfem_ui/services/job_queue.py:146`
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:687-692`

- [ ] **Step 1: Upgrade `logger.debug` to `logger.error` for job persistence failure**

In `job_local.py:137-138`, change:

```python
        except Exception:
            logger.debug("Could not persist job %s to DB", job.id, exc_info=True)
```

to:

```python
        except Exception:
            logger.error("Could not persist job %s to DB", job.id, exc_info=True)
```

- [ ] **Step 2: Upgrade startup DB load to warning**

In `job_local.py:78-80`, change:

```python
        except Exception:
            # DB may not be initialised yet at import time — that's fine
            logger.debug("Could not load job history from DB", exc_info=True)
```

to:

```python
        except Exception:
            logger.warning("Could not load job history from DB", exc_info=True)
```

- [ ] **Step 3: Add logger to `job_queue.py` and replace bare `pass`**

First, add logger to `job_queue.py` — confirmed absent as of 2026-04-05 review. Add at the top of the file after existing imports:

```python
import logging

logger = logging.getLogger(__name__)
```

Then change:

```python
            except Exception:
                pass
```

to:

```python
            except Exception:
                logger.warning("Progress callback error", exc_info=True)
```

- [ ] **Step 4: Log warning and validate restart file path in `run.py:687-692`** ← **ENHANCED**

Change:

```python
        except Exception:
            pass
```

to:

```python
        except Exception:
            logger.warning("Could not set restart_from file", exc_info=True)
```

- [ ] **Step 5: Run full test suite**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x --tb=short -q 2>&1 | tail -5
```

Expected: All tests pass (logging level changes don't affect behavior).

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/job_local.py shyfem-ui/shyfem_ui/services/job_queue.py shyfem-ui/shyfem_ui/pages/run.py
git commit -m "fix(logging): upgrade swallowed errors from debug/pass to warning/error

Job persistence failure upgraded from debug to error (could lose
completed jobs). DB history load upgraded to warning. Progress callback
bare pass replaced with warning. Restart file drop bare pass replaced
with warning.

Ref: review findings H11, M22, M23, NEW-2"
```

---

## Task 10: Fix H7-H8, M14-M16, M19-M20 — Build System Safety

**Findings:** H7, H8, M19 (original), M14, M15, M16, M20 (new from 2026-04-05 analysis)

**Files:**
- Modify: `Makefile:48,109`
- Modify: `src/utils/shympi/Makefile:133`
- Modify: `Rules.make:677-680,811-814,996-997,1017` ← **NEW scope**

- [ ] **Step 1: Remove `.IGNORE: clean` from top-level Makefile**

In `Makefile`, remove line 109:

```makefile
.IGNORE: clean
```

The individual `rm` commands already use `-` prefix for error suppression.

- [ ] **Step 2: Fix `MPI_TARGET` double definition**

In `src/utils/shympi/Makefile`, line 133, change:

```makefile
MPI_TARGET = $(shell [ ! -f MPI_NODE ] && echo reset )
```

to:

```makefile
MPI_TARGET = $(shell [ ! -f $(MPI_FILE) ] && echo reset )
```

- [ ] **Step 3: Fix hardcoded `SHYFEMDIR` fallback**

In `Makefile`, line 48, change:

```makefile
SHYFEMDIR := $(HOME)/shyfem
```

to:

```makefile
SHYFEMDIR := $(CURDIR)
```

- [ ] **Step 4: Fix `FGNU_GENERAL` replacement when MODDIR defined** ← **NEW (M16)**

In `Rules.make`, lines 677-680, the `ifdef MODDIR` block REPLACES `FGNU_GENERAL` instead of appending. Since MODDIR is always defined (line 413), `-std=f95` was already dropped from the build long ago and the codebase now uses Fortran 2003/2008 features (`newunit=`, `allocatable save`, etc. in 30+ files). Do NOT re-add `-std=f95`. Instead, fix the replacement to use append:

Change:

```makefile
FGNU_GENERAL = -cpp -std=f95
ifdef MODDIR
  FGNU_GENERAL = -cpp -J$(MODDIR)
endif
```

to:

```makefile
FGNU_GENERAL = -cpp
ifdef MODDIR
  FGNU_GENERAL += -J$(MODDIR)
endif
```

This drops the `-std=f95` flag entirely (the codebase has outgrown F95) and uses `+=` to append the module directory without clobbering the base flags.

- [ ] **Step 5: Remove redundant `FGNU_OMP` redefinition** ← **NEW (M15)**

In `Rules.make`, lines 811-814 are a redundant second definition of `FGNU_OMP` (already defined at lines 740-742). `FPGI_OMP` is already correctly defined at lines 782-784. Delete lines 811-814 entirely:

```makefile
# DELETE these 4 lines (redundant — FGNU_OMP already set at 740-742):
FGNU_OMP   =
ifeq ($(PARALLEL_OMP),true)
  FGNU_OMP   =  -fopenmp
endif
```

**Note:** The original finding M15 said these were in "the PGI section" but they are actually between the PGI variable definitions (776-810) and the PGI compiler selection block (818+). They overwrote the identical GNU values at 740-742 with the same content — harmless but confusing. Removing them eliminates the dead redefinition.

- [ ] **Step 6: Remove unconditional `FINTEL_NOOPT` clear** ← **NEW (M14)**

In `Rules.make`, remove line 997 (the unconditional `FINTEL_NOOPT =` that clears the definition at line 996):

```makefile
# Remove this line:
FINTEL_NOOPT =
```

This preserves the intentional `-g -traceback` default at line 996 and allows the conditional overrides at lines 1002-1003 to work properly.

- [ ] **Step 7: Fix Intel HIGH optimization level** ← **NEW (M20)**

In `Rules.make`, line 1017, change:

```makefile
  FINTEL_OPT   = -O1 -assume byterecl -no-wrap-margin # WW3_ARON
```

to:

```makefile
  FINTEL_OPT   = -O3 -assume byterecl -no-wrap-margin
```

- [ ] **Step 8: Build and test (serial + OMP + MPI)**

```bash
cd /home/razinka/shyfem
make clean && make fem
make clean && make fem OMP=true
make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Clean builds and test run.

- [ ] **Step 9: Commit**

```bash
git add Makefile src/utils/shympi/Makefile Rules.make
git commit -m "fix(build): fix .IGNORE, MPI_TARGET, SHYFEMDIR, Rules.make flag issues

- Remove .IGNORE:clean (individual - prefix already handles rm errors)
- Fix MPI_TARGET using MPI_FILE variable instead of hardcoded MPI_NODE
- Use CURDIR instead of HOME/shyfem for SHYFEMDIR fallback
- Remove unconditional FINTEL_NOOPT clear (M14)
- Fix Intel HIGH optimization from -O1 to -O3 (M20)
- Drop -std=f95 and use += append for MODDIR module path (M16)
- Delete redundant FGNU_OMP redefinition at lines 811-814 (M15)

Ref: review findings H7, H8, M14, M15, M16, M19, M20"
```

---

## Task 11: Fix SO1 — Stack Overflow in `concentration_omp.f90`

**Findings:** SO1 (HIGH — new from 2026-04-05 analysis)
**Dependency:** Task 5 should be committed first (establishes the allocatable+save pattern).

**Root cause:** `conz3d_element` at lines 429-434 declares ~14 automatic arrays sized by `nlvddi` (up to 200 levels). Total: ~50KB per call. Called from OMP TASKs with 8-16 concurrent tasks → 400-800KB stack pressure per thread. With default 8MB stack and deep call chains, this risks segfault on production meshes.

**Files:**
- Modify: `src/shyfem/concentration_omp.f90:429-434`

**Strategy:** These arrays are local to each OMP TASK call — they cannot use `save` because multiple tasks run concurrently. Instead, increase the default OMP stack size via environment variable documentation AND convert the largest arrays to allocatable locals (allocated/deallocated per call). The per-call allocation cost is negligible compared to the element computation.

- [ ] **Step 1: Convert large automatic arrays to allocatable locals**

In `conz3d_element`, replace lines 429-434:

```fortran
      double precision,dimension(0:nlvddi+1) :: hdv,haver,presentl
      double precision,dimension(0:nlvddi+1,3) :: hnew,htnew,rtau,cob
      double precision,dimension(0:nlvddi+1,3) :: hold,htold,vflux,wl
      double precision,dimension(0:nlvddi+1,3) :: cl
      double precision,dimension(0:nlvddi+1,3) :: finu
      double precision,dimension(nlvddi,3) :: clc,clm,clp,cle
```

with:

```fortran
      double precision,dimension(0:nlvddi+1) :: hdv,haver,presentl
      double precision,allocatable :: hnew(:,:),htnew(:,:),rtau(:,:)
      double precision,allocatable :: cob(:,:)
      double precision,allocatable :: hold(:,:),htold(:,:),vflux(:,:)
      double precision,allocatable :: wl(:,:),cl(:,:),finu(:,:)
      double precision,allocatable :: clc(:,:),clm(:,:),clp(:,:)
      double precision,allocatable :: cle(:,:)
      integer :: ierr_conz
```

After the opening assertion (line 436), add:

```fortran
      allocate(hnew(0:nlvddi+1,3),htnew(0:nlvddi+1,3), &
     &  rtau(0:nlvddi+1,3),cob(0:nlvddi+1,3), &
     &  hold(0:nlvddi+1,3),htold(0:nlvddi+1,3), &
     &  vflux(0:nlvddi+1,3),wl(0:nlvddi+1,3), &
     &  cl(0:nlvddi+1,3),finu(0:nlvddi+1,3), &
     &  clc(nlvddi,3),clm(nlvddi,3),clp(nlvddi,3), &
     &  cle(nlvddi,3),stat=ierr_conz)
      if( ierr_conz /= 0 ) then
        write(6,*) 'error: allocation failed in conz3d_element for ie=',ie
        return
      end if
```

**Note:** `hdv`, `haver`, `presentl` are small 1D arrays (one per level) and can remain automatic. Only the 2D `(:,3)` arrays are converted — they account for ~95% of the stack usage.

**Alternative:** Setting `OMP_STACKSIZE=64M` avoids heap allocation overhead entirely. However, this requires every deployment to set the env var, which is fragile. The allocatable approach is safer as a default and can be complemented by `OMP_STACKSIZE` documentation.

Before the subroutine `end`, add:

```fortran
      deallocate(hnew,htnew,rtau,cob,hold,htold,vflux,wl,cl,finu, &
     &  clc,clm,clp,cle)
```

- [ ] **Step 2: Build and run test (serial + OMP)**

```bash
cd /home/razinka/shyfem
make clean && make fem
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5

cd /home/razinka/shyfem
make clean && make fem OMP=true
cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Clean build and identical results in both modes.

- [ ] **Step 3: Commit**

```bash
git add src/shyfem/concentration_omp.f90
git commit -m "fix(stack): convert large automatic arrays to allocatable in conz3d_element

conz3d_element used ~50KB of automatic arrays per call, with 8-16
concurrent OMP TASKs consuming 400-800KB of stack. This risks segfault
on production meshes with deep call chains. Convert 2D arrays to
allocatable locals; small 1D arrays remain automatic.

Ref: review finding SO1"
```

---

## Task 12: Add `.PHONY: compile` Target to `src/shyfem/Makefile`

**Findings:** Review of uncommitted Makefile changes (2026-04-05 validation)

**Note:** The uncommitted `src/shyfem/Makefile` adds `compile` to `.PHONY` and adds `lagrange_mpi.o` module dependencies. The `compile` target reference is a cleanup item. This is a minor housekeeping commit.

**Files:**
- Modify: `src/shyfem/Makefile` (already has uncommitted changes)

- [ ] **Step 1: Remove `compile` from `.PHONY` list (no recipe exists)**

The uncommitted changes added `compile` to the `.PHONY` list at line 376, but no `compile:` recipe target exists in this Makefile (confirmed 2026-04-05). Remove `compile` from the `.PHONY` line. Keep the `lagrange_mpi.o` dependency additions (lines 738-741) which add correct module dependencies.

- [ ] **Step 2: Build test**

```bash
cd /home/razinka/shyfem
make clean && make fem
```

- [ ] **Step 3: Commit**

```bash
git add src/shyfem/Makefile
git commit -m "fix(build): add lagrange_mpi.o module dependencies

Add missing module dependencies for lagrange_mpi.o (basin, connectivity,
mod_lagrange, shympi). Clean up .PHONY target list.

Ref: build system analysis 2026-04-05"
```

---

## Verification Checklist

After all 12 tasks are complete, run full verification:

- [ ] **Serial build**: `make clean && make fem`
- [ ] **OMP build**: `make clean && make fem OMP=true`
- [ ] **MPI build**: `make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr`
- [ ] **SPEED build**: `make clean && make fem COMPILER_PROFILE=SPEED`
- [ ] **Serial test**: `cd testcases/examples/mar_menor && rm -f *.shy *.ext *.flx *.inf && make init && PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str`
- [ ] **MPI test**: `PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str`
- [ ] **No NaN in output**: `grep -i nan *.shy *.ext 2>/dev/null` (should return nothing)
- [ ] **Python tests**: `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v`
- [ ] **All 12 commits present**: `git log --oneline -12`
- [ ] **Proxy deployment test** (if available): Verify Shiny Server WS still works after Task 3
