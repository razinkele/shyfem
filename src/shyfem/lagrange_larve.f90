
!--------------------------------------------------------------------------
!
!    Copyright (C) 2007,2010,2015,2018-2019  Georg Umgiesser
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

! simulates continuous release over open boundaries
!
! revision log :
!
! 12.12.2007	ggu	written from scratch
! 23.03.2010	ggu	changed v6.1.1
! 21.05.2015	ggu	changed VERS_7_1_11
! 16.11.2015	ggu	changed VERS_7_3_14
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
!
!*******************************************************************

	subroutine lgr_larvae

! manages larvae

	use mod_lagrange

	implicit none

	integer i,ie,ii
	real rlinit,x,y,z,rl
        double precision xx,yy
        double precision xi(3)
	integer ierr


	integer, save :: icall = 0

	if( icall .eq. 0 ) then
	  rlinit = 0.
	  do i=1,nbdy
	    lgr_ar(i)%custom(1) = rlinit
	  end do
	end if

	icall = icall + 1

	do i=1,nbdy
          do ii=1,3
            xi(ii) = lgr_ar(i)%actual%xi(ii)
          end do
	  ie = lgr_ar(i)%actual%ie
          z  = lgr_ar(i)%actual%z	!rel. depth   0=surface  1=bottom
	  rl = lgr_ar(i)%custom(1)
          call xi2xy_ierr(abs(ie),xx,yy,xi,ierr)
	  if( ierr /= 0 ) then		!a bare stop in xi2xy until #305
	    call xi2xy_write_error(abs(ie),xi)
	    call shympi_abort_internal('error stop lgr_larvae:'		&
     &		//' error of xi2xy')
	  end if
          x   = xx
          y   = yy
	  
	  if( ie .gt. 0 ) then
	    call treat_larva(lgr_ar(i)%id,x,y,z,ie,rl)
	  end if

	  lgr_ar(i)%custom(1) = rl
          lgr_ar(i)%actual%z = z
	end do

!----------------------------------------------------------------
! end of routine
!----------------------------------------------------------------

	end

!*******************************************************************

	subroutine treat_larva(id,x,y,z,ie,rl)

! the draw is the particle's own (#225): lgr_random keyed on its id, the
! time step and the site lgr_rnd_larva

	use mod_lagrange_random, only : lgr_random, lgr_rnd_larva

	implicit none

	integer, intent(in) :: id	!id of the particle
	real x,y,z
	integer ie
	real rl,r,perc

	perc = 0.1
	perc = 0.
	r = lgr_random(id,lgr_rnd_larva,0)

	if( r .lt. perc ) z = 1.0

	end

!*******************************************************************

