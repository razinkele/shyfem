
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015,2017,2019  Georg Umgiesser
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
! 18.09.2015	ggu	changed VERS_7_2_3
! 16.12.2015	ggu	changed VERS_7_3_16
! 12.01.2017	ggu	changed VERS_7_5_21
! 16.02.2019	ggu	changed VERS_7_5_60
! 21.05.2019	ggu	changed VERS_7_5_62
! 15.10.2022	ggu	bpresv deleted
! 15.10.2022	ggu	bpresxv,bpresyv deleted

!**************************************************************************

        module mod_ts

        implicit none

	integer, private, save :: nkn_ts = 0
	integer, private, save :: nlv_ts = 0

        real, allocatable, target, save :: rhov(:,:)
        real, allocatable, target, save :: saltv(:,:)
        real, allocatable, target, save :: tempv(:,:)

        real, allocatable, save :: sobsv(:,:)
        real, allocatable, save :: stauv(:,:)
        real, allocatable, save :: tobsv(:,:)
        real, allocatable, save :: ttauv(:,:)

        contains

!************************************************************

        subroutine mod_ts_init(nkn,nlv)

        integer nkn
        integer nlv
        integer ierr

        if( nkn == nkn_ts .and. nlv == nlv_ts) return

	if( nkn > 0 .or. nlv > 0 ) then
	  if( nkn == 0 .or. nlv == 0 ) then
	    write(6,*) 'nkn,nlv: ',nkn,nlv
	    stop 'error stop mod_ts_init: incompatible parameters'
	  end if
	end if

        if( nkn_ts > 0 ) then
          deallocate(rhov)
          deallocate(saltv)
          deallocate(tempv)
          deallocate(sobsv)
          deallocate(tobsv)
          deallocate(stauv)
          deallocate(ttauv)
        end if

        nkn_ts = nkn
	nlv_ts = nlv

        if( nkn == 0 ) return

          allocate(rhov(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(saltv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(tempv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(sobsv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(tobsv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(stauv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          allocate(ttauv(nlv,nkn),stat=ierr)
          if( ierr /= 0 ) stop 'error stop: allocation failed'

	rhov = 0.
	saltv = 0.
	tempv = 0.
	sobsv = 0.
	tobsv = 0.
	stauv = 0.
	ttauv = 0.

        end subroutine mod_ts_init

!************************************************************

        end module mod_ts

