# Follow-up: Fully Deduplicate iso8601 / subiso8601

**STATUS: COMPLETED 2026-04-19.**

The netcdf-tools `Makefile` (`src/tools/femutil/netcdf/Makefile`) now compiles
the canonical `src/utils/generic/iso8601.f90` directly into a local `iso8601.o`
via a vpath-style rule. The redundant `subiso8601.f90` copy has been deleted.

**Changes:**

1. `OBJS_TIME` now lists `iso8601.o` instead of `subiso8601.o`.
2. New rule:
   ```make
   iso8601.o: ../../../utils/generic/iso8601.f90
       $(F77) -c $(FFLAGS) $< -o $@
   ```
3. Module dependency line updated: `iso8601.mod: iso8601.o` (was `subiso8601.o`).
4. `src/tools/femutil/netcdf/subiso8601.f90` removed.

**Verification:** Compiling with `make iso8601.o ncf_tutil.o subdts.o` from
the netcdf-tools dir succeeds — `gfortran -c -g -O ../../../utils/generic/iso8601.f90 -o iso8601.o`,
and `ncf_tutil.f90` (which depends on `iso8601.mod`) builds cleanly. Full
SHYFEM `make fem` build remains clean. (The full link of `ncinfo`/`ncbgc`/`ncelab`
requires libnetcdff.a, not installed in this dev environment, but is unaffected
by this change since the same `iso8601.mod` is produced.)

**Earlier partial step (2026-04-19):** prior to this dedup, the 2024 YYYY-M-D
parse fix was synced between the two copies so both behaved identically. With
the local copy now removed, that synchronization is no longer necessary —
everything reads from the canonical source.
