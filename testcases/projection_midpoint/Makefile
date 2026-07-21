#------------------------------------------------------------------------
#
#    Copyright (C) 1985-2020  Georg Umgiesser
#
#    This file is part of SHYFEM.
#
#------------------------------------------------------------------------
#
# Regression driver for the projection reference-point (midpoint) fix in
# src/utils/shyutilmpi/coordinates.f90 (subroutine proj_geo2cart).
#
# Usage:
#   make check     build the driver and run it (exit 0 = all tests passed)
#   make build     build only
#   make clean     remove build artifacts
#
#------------------------------------------------------------------------

FC     = gfortran
# projection.f90 is the unit under test; convert.f90 supplies to_upper()
# referenced by projection's s2i_proj (unused here, but needed to link)
SRC    = ../../src/utils/generic/projection.f90 \
	 ../../src/utils/generic/convert.f90
DRIVER = test_projection_midpoint.f90
EXE    = test_projection_midpoint

.PHONY: default check build clean

default: check

build: $(EXE)

$(EXE): $(SRC) $(DRIVER)
	$(FC) -o $(EXE) $(SRC) $(DRIVER)

check: $(EXE)
	./$(EXE)

clean:
	rm -f $(EXE) *.mod
