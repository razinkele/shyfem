
!--------------------------------------------------------------------------
!
!    Copyright (C) 2017-2019  Georg Umgiesser
!
!    This file is part of SHYFEM.
!
!    SHYFEM is free software: you can redistribute it and/or modify
!    it under the terms of the GNU General Public License as published by
!    the Free Software Foundation, either version 3 of the License, or
!    (at your option) any later version.
!
!    SHYFEM is distributed in the hope that it will be useful,
!    but WITHOUT ANY WARRANTY; without even the implied warranty of
!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
!    GNU General Public License for more details.
!
!    You should have received a copy of the GNU General Public License
!    along with SHYFEM. Please see the file COPYING in the main directory.
!    If not, see <http://www.gnu.org/licenses/>.
!
!    Contributions to this file can be found below in the revision log.
!
!--------------------------------------------------------------------------

! revision log :
!
! 05.12.2017	ggu	changed VERS_7_5_39
! 19.04.2018	ggu	changed VERS_7_5_45
! 18.12.2018	ggu	changed VERS_7_5_52
! 21.05.2019	ggu	changed VERS_7_5_62

!--------------------------------------------------------------------------

	subroutine mpi_init(ierr)
	implicit none
	integer ierr
	ierr = 0
	end

	subroutine mpi_comm_rank(comm,my_id,ierr)
	implicit none
	integer comm,my_id,ierr
	my_id = 0
	ierr = 0
	end

	subroutine mpi_comm_size(comm,n_threads,ierr)
	implicit none
	integer comm,n_threads,ierr
	n_threads = 1
	ierr = 0
	end

	subroutine mpi_barrier(comm,ierr)
	implicit none
	integer comm,ierr
	ierr = 0
	end

	subroutine mpi_finalize
	implicit none
	end

	subroutine mpi_irecv
	implicit none
	end

	subroutine mpi_isend
	implicit none
	end

	subroutine mpi_waitall
	implicit none
	end

	subroutine mpi_abort
	implicit none
	end

	subroutine mpi_scatter
	implicit none
	end

	subroutine mpi_gather
	implicit none
	end

	subroutine mpi_allgather
	implicit none
	end

	subroutine mpi_bcast
	implicit none
	end

	subroutine mpi_allreduce(what,val)
	implicit none
	integer what,val
	end

	subroutine mpi_wtime
	implicit none
	end
