# Phase 8 Optimization Design — Profile-Guided Optimization (PGO)

**Date**: 2026-02-21
**Status**: Proposed
**Approach**: Add PGO build profiles to Rules.make for gfortran

## Context

Phases 3-7 applied algorithmic optimizations, compiler flags, allocation caching, SIMD directives, hybrid MPI+OpenMP, and OpenMP loop parallelization. The codebase is well-optimized at the source level.

This proposal targets compiler-level optimization via PGO — a two-pass build technique where GCC instruments the binary during a training run, then uses the collected branch/loop profile data to optimize the production build.

## How PGO Works

1. **Generate pass**: Build with `-fprofile-generate`. GCC inserts instrumentation code that records branch frequencies, loop trip counts, and call patterns into `.gcda` files during execution.
2. **Training run**: Execute the instrumented binary on a representative workload (e.g., mar_menor test case).
3. **Use pass**: Rebuild with `-fprofile-use -fprofile-correction`. GCC reads the `.gcda` files and optimizes:
   - Branch prediction (hot/cold paths)
   - Function inlining decisions
   - Loop unrolling heuristics
   - Basic block reordering for cache locality

`-fprofile-correction` handles slight profile mismatches when the production workload differs from the training workload (e.g., different timestep count).

## Change: Add PGO Profiles to Rules.make

**File**: `Rules.make`

### New Profiles

Add two new `COMPILER_PROFILE` options after the existing `SPEED` block (line 567):

- `SPEED_PGO_GEN` — identical to SPEED but adds `-fprofile-generate` to compile and link flags
- `SPEED_PGO_USE` — identical to SPEED but adds `-fprofile-use -fprofile-correction`

### Variables Modified

- New variable `PGO_FLAGS` (empty by default, set by PGO profiles)
- `FGNU_OPT`: append `$(PGO_FLAGS)` so PGO flags are included in compilation
- `LFLAGS`: append `$(PGO_FLAGS)` so PGO flags are included in linking
- Error message at line 571: update to list all valid profiles

### Workflow

```bash
# Step 1: Build instrumented binary
make clean
PATH=/usr/bin:$PATH make fem COMPILER_PROFILE=SPEED_PGO_GEN OMP=true MPI=true PARTS=METIS METISDIR=/usr

# Step 2: Run representative workload (generates .gcda files in source dirs)
cd testcases/examples/mar_menor
PATH=/path/to/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str

# Step 3: Rebuild with profile data (make clean removes .o but NOT .gcda)
cd /path/to/shyfem
make clean
PATH=/usr/bin:$PATH make fem COMPILER_PROFILE=SPEED_PGO_USE OMP=true MPI=true PARTS=METIS METISDIR=/usr

# Step 4: Run optimized binary
cd testcases/examples/mar_menor
PATH=/path/to/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str
```

**Note**: `make clean` between steps 2 and 3 removes `*.o` files but not `*.gcda` profile data files, which is the correct behavior.

### Risk

None. No Fortran code is modified. Existing NORMAL/CHECK/SPEED profiles are untouched. PGO profiles are opt-in only.

### Expected Speedup

5-15% over SPEED profile. Benefits:
- Branch-heavy code: turbulence dispatch, friction type selection (chezy.f90), concentration substep control flow
- Loop trip count optimization: vertical level loops with dynamic `lmax` bounds
- Hot/cold path separation: error handling paths moved out of hot loops

## Verification Plan

1. Build with `SPEED_PGO_GEN` — must compile successfully
2. Run mar_menor — must generate `.gcda` files in source directories
3. Build with `SPEED_PGO_USE` — must compile successfully (reads `.gcda`)
4. Run mar_menor — 1152 timesteps, no errors
5. Compare wall times: SPEED vs SPEED_PGO_USE

## Summary

| Change | File | Risk | Expected Speedup |
|--------|------|------|-----------------|
| Add `PGO_FLAGS` variable + two profile blocks | `Rules.make` | None | — |
| Append `$(PGO_FLAGS)` to FGNU_OPT and LFLAGS | `Rules.make` | None | 5-15% over SPEED |
