# Follow-up: Fully Deduplicate iso8601 / subiso8601

**Blocking reason:** The netcdf-tools `Makefile` at
`src/tools/femutil/netcdf/Makefile:67,148` compiles `subiso8601.f90`
locally into `iso8601.mod`. Deletion requires modifying that Makefile
to either vpath-compile the canonical source or link the top-level
library.

**Completed 2026-04-19 (partial):** back-ported the 2024 YYYY-M-D fix
so both copies behave identically.

**Note on actual divergence found:** The task description assumed
`iso8601.f90` (canonical) had the fix and `subiso8601.f90` was missing
it. Inspection revealed the opposite: `subiso8601.f90` already had the
corrected parse_time code, while `iso8601.f90` still had the old buggy
version. Both changes were applied: the code fix was ported into
`iso8601.f90`, and the revision-log comment was added to
`subiso8601.f90`. The parse_time subroutines are now byte-identical.

**TODO:** Edit `src/tools/femutil/netcdf/Makefile` to drop `subiso8601.o`
from `OBJS_TIME` and add a rule like:

```make
iso8601.o: ../../../utils/generic/iso8601.f90
	$(F90) $(FFLAGS) -c $< -o $@
```

Then `git rm src/tools/femutil/netcdf/subiso8601.f90` and verify
`make` in that dir succeeds.
