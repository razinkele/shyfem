#------------------------------------------------------------------------
# weutro / EUTRO ecological model test case
# Phase 0 of docs/plans/2026-06-03-weutro-eco-fixes-plan.md
#------------------------------------------------------------------------

DIR  = weutro_box
GRID = MM_coarse
BIN  = /home/razinka/shyfem/bin

.PHONY: default init run run2d run3d check clean cleanall

default:
	@echo "targets:"
	@echo "  init   build the basin (.bas) from the grid via shypre"
	@echo "  run    run both eco cases (2D + 3D)"
	@echo "  check  run the eco gate (build, run, validate no-NaN/positivity/DO-range)"
	@echo "  clean  remove run artifacts"
	@echo ""
	@echo "NOTE: needs an ECOLOGICAL=EUTRO build:"
	@echo "      (cd /home/razinka/shyfem && make fem ECOLOGICAL=EUTRO)"

init:
	cd GRID; PATH=$(BIN):/usr/bin:$$PATH shypre $(GRID).grd

run2d:
	PATH=$(BIN):/usr/bin:$$PATH shyfem eco_2d.str

run3d:
	PATH=$(BIN):/usr/bin:$$PATH shyfem eco_3d.str

run: run2d run3d

check:
	./check_eco.sh

check-restart:
	./check_restart.sh

check-omp:
	./check_omp.sh

check-all: check check-restart check-omp

clean:
	-rm -f *.shy *.inf *.run.log *.ext *.flx *.rst fort.* GRID/*.bas

cleanall: clean
