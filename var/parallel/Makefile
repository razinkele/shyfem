
#------------------------------------------------------------------------
#
#    Copyright (C) 1985-2020  Georg Umgiesser
#
#    This file is part of SHYFEM.
#
#------------------------------------------------------------------------


.PHONY: default run mpi omp mix clean cleanzip zip

#--------------------------------------------------

default: run

run: mpi omp mix

#--------------------------------------------------

mpi:
	@-./hw_mpi.sh

omp:
	@-./hw_omp.sh

mix:
	@-./hw_mix.sh

#--------------------------------------------------

clean:
	-rm -f a.out

cleanzip:
	-rm -f parallel.zip

zip: clean cleanzip
	zip parallel *

#--------------------------------------------------

