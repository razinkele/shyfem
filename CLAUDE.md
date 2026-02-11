# CLAUDE.md - SHYFEM Project Instructions

## Project
SHYFEM (System of HydroDYnamic Finite Element Modules) v8.1.1 - Finite element hydrodynamic simulation for lagoons, coastal seas, and estuaries. Fortran 90/95+ with C utilities.

## Build Commands

```bash
# Serial build
make fem

# MPI build (must use OpenMPI, not Intel MPI)
PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr

# Clean build
make clean && make fem

# Run test case
cd testcases/examples/mar_menor
make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str

# MPI run
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

## Key Architecture

- Main loop: `src/shyfem/shyfem_subs.f90`
- Hydrodynamics: `src/shyfem/hydrodynamic.f90`
- Concentration: `src/shyfem/concentration.f90`, `concentration_omp.f90`
- MPI layer: `src/utils/shympi/` (18 files)
- Physical constants: `src/shyfem/mod_physical_constants.f90`
- Runtime parameters: `src/utils/generic/para.f90` (module `para`: `getpar`, `dgetpar`)
- Build config: `Rules.make`

## Coding Conventions

### Do
- Use `implicit none` in all program units
- Use `intent(in/out/inout)` on all subroutine arguments
- Use `allocate(..., stat=ierr)` with error checking on all allocations
- Use `open(newunit=iu, ..., iostat=ierr)` for file I/O
- Use `use para` to access `getpar`/`dgetpar` (they are module functions)
- Use `use mod_physical_constants` for pi, gravity, etc.
- Use `integer, save :: icall = 0` (single-line initialization, not separate save/data)
- Use structured control flow (`do/exit/cycle`, `if/else`, `select case`)
- Add `.PHONY` for non-file targets in Makefiles

### Don't
- Don't use `real getpar` external declarations (use the module)
- Don't use GOTO statements
- Don't use hardcoded file unit numbers (use `newunit=`)
- Don't use bare `stop` in MPI code paths (use `shympi_abort_internal`)
- Don't define local pi/grav constants (use the module)
- Don't use three-line `save`/`data` patterns

## MPI Build Notes

- Intel MPI's `mpi.mod` is incompatible with gfortran; prefix commands with `PATH=/usr/bin:$PATH` to use OpenMPI
- MPI requires: `libmetis-dev`, `PARTS=METIS`, `METISDIR=/usr`
- `-fopenmp` must be in LFLAGS unconditionally (non-conditional `omp_*` calls exist)

## Documentation
- `DEVELOPER_GUIDE.md` - Architecture, modules, build system, style guidelines
- `CODEBASE_ANALYSIS.md` - Bug/issue analysis with implementation plan (all phases complete)
- `docs/shyfem_manual.pdf` - User manual
