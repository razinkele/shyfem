
#------------------------------------------------------------------------
#
#    Copyright (C) 1985-2020  Georg Umgiesser
#
#    This file is part of SHYFEM.
#
#------------------------------------------------------------------------


FEMDIR    = ..
FEMBIN    = $(FEMDIR)/bin

FEMDIRS   = mpi

#-----------------------------------------------------------------------

.PHONY: default fem mpi regress list depend clean cleanall save zip

default: mpi

fem: mpi

mpi:
	mpif90 mpi_test.f
	/usr/bin/mpirun -np 4 a.out

regress:

list:
	pwd; ls

depend:

clean:
	-rm -f a.out

cleanall: clean

save:

zip:

#-----------------------------------------------------------------------

