
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015,2019  Georg Umgiesser
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
! 10.07.2015	ggu	changed VERS_7_1_50
! 16.02.2019	ggu	changed VERS_7_5_60
! 21.05.2019	ggu	changed VERS_7_5_62
! 03.09.2024	ggu	new data structures
! 23.09.2024	ggu	new array itvdup()

!**************************************************************************

!==================================================================
        module mod_tvd
!==================================================================

        implicit none

        integer, private, save :: nel_tvd = 0

	integer, save :: itvd_type = 0

        real, allocatable, save :: xtvdup(:,:,:)	!x-coordinate
        real, allocatable, save :: ytvdup(:,:,:)	!y-coordinate
        integer, allocatable, save :: ietvdup(:,:,:)	!internal element number
        integer, allocatable, save :: ieetvdup(:,:,:)	!external elem number
        integer, allocatable, save :: iatvdup(:,:,:)	!domain of element
        integer, allocatable, save :: ltvdup(:,:,:)	!lmax of element
        integer, allocatable, save :: itvdup(:,:,:)	!index into array

! error record of tvd_get_upwind_c (#317): a worker thread of the OpenMP
! tasks of conz3d_omp may neither write nor abort, so an error is
! recorded here (the first one in full) and checked by tvd_check_error
! (tvd_admin.f90): at the end of conz3d_omp when that runs outside a
! parallel region, otherwise on the master thread after the TASKWAIT that
! closes the transport tasks of the time step (tvd_check_error(.true.)
! in shyfem_subs.f90). The record and the flag tvd_err_reported are
! read and written under the critical section tvd_error_record, so that
! only one check reports it (transports run concurrently as sibling
! tasks and share the record).

	integer, save :: tvd_err_n = 0		!number of errors recorded
	logical, save :: tvd_err_reported = .false.	!claimed by one check
	integer, save :: tvd_err_ie = 0		!element of the flux
	integer, save :: tvd_err_ienew = 0	!upwind element
	integer, save :: tvd_err_l = 0		!layer
	integer, save :: tvd_err_code = 0	!code of the first error
	double precision, save :: tvd_err_x = 0.d0	!point of the first error
	double precision, save :: tvd_err_y = 0.d0

! test hook TVD_TEST_ERROR=K (read once in tvd_init, on the master
! process only): K = 1 forces the error of xy2xi (code 1), K = 2 the
! lremote error (code 4), in the first call of tvd_get_upwind_c that
! reaches the check, K = 3 the xy2xi error in EVERY such call (several
! transports then fail at once); inert (0) when not set

	integer, save :: tvd_test_event = 0
	integer, save :: tvd_test_left = 0	!1 until the hook has fired

!==================================================================
	contains
!==================================================================

        subroutine tvd_error_record(ie,ienew,l,code,x,y)

! records an error of tvd_get_upwind_c; safe inside an OpenMP task

        integer, intent(in) :: ie,ienew,l,code
        double precision, intent(in) :: x,y

!$OMP CRITICAL (tvd_error_record)
        tvd_err_n = tvd_err_n + 1
        if( tvd_err_n == 1 ) then
          tvd_err_ie = ie
          tvd_err_ienew = ienew
          tvd_err_l = l
          tvd_err_code = code
          tvd_err_x = x
          tvd_err_y = y
        end if
!$OMP END CRITICAL (tvd_error_record)

        end subroutine tvd_error_record

!==================================================================

        function tvd_test_take(kind)

! .true. once, for the call that fires the test hook of kind kind

        logical :: tvd_test_take
        integer, intent(in) :: kind

        tvd_test_take = .false.
        if( tvd_test_event == 3 .and. kind == 1 ) then	!every call
          tvd_test_take = .true.
          return
        end if
        if( tvd_test_event /= kind ) return

!$OMP CRITICAL (tvd_test_take)
        if( tvd_test_left > 0 ) then
          tvd_test_left = 0
          tvd_test_take = .true.
        end if
!$OMP END CRITICAL (tvd_test_take)

        end function tvd_test_take

!==================================================================

        subroutine mod_tvd_init(nel)

        integer nel
        integer ierr

        if( nel == nel_tvd ) return

        if( nel_tvd > 0 ) then
          deallocate(xtvdup)
          deallocate(ytvdup)
          deallocate(ietvdup)
          deallocate(ieetvdup)
          deallocate(iatvdup)
          deallocate(ltvdup)
          deallocate(itvdup)
        end if

        nel_tvd = nel

        if( nel == 0 ) return

        allocate(xtvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(ytvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(ietvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(ieetvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(iatvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(ltvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(itvdup(3,3,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'

	write(6,*) 'mod_tvd_init successfully called ',nel

        end subroutine mod_tvd_init

!==================================================================
        end module mod_tvd
!==================================================================

