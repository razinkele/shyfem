---
name: fortran-conventions
description: SHYFEM Fortran coding conventions to enforce when editing .f90 or .f files
user-invocable: false
---

# SHYFEM Fortran Coding Conventions

When editing any Fortran file (.f90, .f, .F90, .F) in this project, enforce these conventions:

## Required Patterns

1. **`implicit none`** in every program unit (module, subroutine, function, program)
2. **`intent(in/out/inout)`** on all subroutine and function arguments
3. **`allocate(..., stat=ierr)`** with error checking on every allocation:
   ```fortran
   allocate(arr(n), stat=ierr)
   if (ierr /= 0) stop 'error stop routine_name: cannot allocate arr'
   ```
4. **`open(newunit=iu, ..., iostat=ierr)`** for all file I/O — never use hardcoded unit numbers
5. **`use para`** to access `getpar`/`dgetpar` — they are module functions, not externals
6. **`use mod_physical_constants`** for pi, gravity, vonkarman, etc. — never define local constants
7. **Single-line save initialization**: `integer, save :: icall = 0` — never the three-line save/data pattern
8. **Structured control flow**: `do/exit/cycle`, `if/else`, `select case` — never GOTO

## Forbidden Patterns

- `real getpar` or `double precision dgetpar` external declarations (use the module)
- `goto` statements (restructure with do/exit/cycle)
- Bare `stop` in MPI code paths (use `shympi_abort_internal` or `stop 'error stop ...'`)
- Hardcoded file unit numbers like `open(42, ...)`
- Local definitions of pi, grav, gravity, vonkarman
- Three-line save/data initialization:
  ```fortran
  ! BAD - don't do this
  integer :: icall
  save icall
  data icall /0/
  ```

## Performance Patterns

- Cache `getpar`/`dgetpar` calls for frequently accessed parameters:
  ```fortran
  integer, save :: icall = 0
  real, save :: cached_val
  if (icall == 0) then
      cached_val = getpar('param')
      icall = 1
  end if
  ```
- Use `!$OMP SIMD` hints on tight vertical-level loops
- Use allocation caching with `allocatable, save` for arrays allocated every timestep

## When Reviewing Changes

Before completing any Fortran edit, verify:
- [ ] No new GOTO statements introduced
- [ ] All new allocations have `stat=` checking
- [ ] All new subroutine arguments have `intent`
- [ ] No hardcoded physical constants
- [ ] No external getpar/dgetpar declarations
