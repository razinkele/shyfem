---
name: build-and-test
description: Build SHYFEM in a given mode (serial, MPI, PETSc, PGO) and run the mar_menor verification test
---

# Build and Test SHYFEM

Build the SHYFEM binary in the requested mode and verify it runs correctly using the mar_menor test case.

## Arguments

The user may specify a build mode. If not specified, default to `serial`.

| Mode | Description |
|------|-------------|
| `serial` | Standard serial build (default) |
| `mpi` | MPI parallel build with OpenMPI and METIS |
| `petsc` | PETSc solver build |
| `pgo-gen` | PGO instrumentation build (step 1) |
| `pgo-use` | PGO optimized build (step 2, requires prior pgo-gen run) |
| `speed` | Optimized serial build with -O3 and vectorization |

## Build Commands

### Serial (default)
```bash
cd /home/razinka/shyfem
make clean && make fem
```

### MPI
```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr
```

### PETSc
```bash
cd /home/razinka/shyfem
make clean && make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real
```

### Speed
```bash
cd /home/razinka/shyfem
make clean && make fem COMPILER_PROFILE=SPEED
```

### PGO Generate
```bash
cd /home/razinka/shyfem
make clean && make fem COMPILER_PROFILE=SPEED_PGO_GEN
```

### PGO Use
```bash
cd /home/razinka/shyfem
make clean && make fem COMPILER_PROFILE=SPEED_PGO_USE
```

## Verification Test

After a successful build, run the mar_menor test case:

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
make init
```

### Serial/Speed/PETSc/PGO run:
```bash
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str 2>&1
```

### MPI run:
```bash
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1
```

## Verification Criteria

The test passes if:
1. The run completes without errors (exit code 0)
2. No `NaN` values appear in the output
3. All timesteps complete (look for the final timestep message)
4. No `error stop` or `SIGFPE` in the output

Report the total wall time from the output.
