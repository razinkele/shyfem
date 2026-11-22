
!--------------------------------------------------------------------------
!
!    Copyright (C) 2018-2019  Georg Umgiesser
!    Copyright (C) 2018  Christian Ferrarin
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

! lagrangian stokes drift due to waves
!
! revision log :
!
! 19.06.2018	ccf	written from scratch
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 13.03.2019	ggu	changed VERS_7_5_61
!
! note :
!
! TO BE IMPROVED IN THE HYDRO-WAVE COUPLING
!
!************************************************************

        subroutine lag_stk(i,id,ty,x,y,xi,iel,lb,time,bresume,bpark)

! the Stokes drift step of one particle: displacement by the wind, the
! element search of the new point, and lag_stk_end. On several processes
! the search is lgr_mpi_locate, which can park the particle (bpark true:
! both points are stored in its slot, x, y, iel and xi are unchanged, the
! caller stops); a serial run searches with find_elem_from_old as always
! (at levdbg >= 3 lgr_mpi_relocate_check checks the result, changing
! nothing). A parked particle is resumed with bresume true: nothing before
! the search is made again (the entry tests passed, the displacement is
! in the stored new point), lag_stk_end runs with the outcome of the
! resolution (lgr_mpi_resolve): lgr_park_ie(i) > 0 the local element
! found, 0 no element (the fallback runs on iel); x, y are the old point

        use mod_lagrange
	use mod_lagrange_mpi, only : bmpi_lagr, blgr_dbg
	use mod_lagrange_mpi, only : lgr_mpi_locate, lgr_mpi_relocate_check
        use basin
        use mod_meteo

        implicit none

        integer, intent(in)     :: i            !particle number
        integer, intent(in)     :: id           !particle id
        integer, intent(in)	:: ty		!particle type
        real, intent(inout)     :: x            !x-coordinate
        real, intent(inout)     :: y            !y-coordinate
        double precision, intent(inout):: xi(3) !internal coordinates
        integer, intent(inout)  :: iel          !element number
        integer, intent(in)     :: lb   	!level
        real, intent(in)        :: time         !time to advect
        logical, intent(in)     :: bresume      !resume a parked particle
        logical, intent(out)    :: bpark        !parked in this call

        real                    :: ttime
        integer, save           :: icall = 0    !initialization parameter
        logical, save           :: bsphe
        integer                 :: isphe
	integer			:: k,ii
	real			:: wx,wy
        real                    :: dx,dy
        real                    :: xnew,ynew
        integer                 :: ienew
        double precision        :: ddx,ddy,xc,yc
        double precision        :: dlat0,dlon0  !center of projection

!---------------------------------------------------------------
! initialize
!---------------------------------------------------------------

	bpark = .false.

        if( icall == 0 ) then
          call get_coords_ev(isphe)
          bsphe = isphe .eq. 1
          icall = 1
        end if

	if( bresume ) then		!parked: resumes after the search
	  xnew = lgr_park_xy(3,i)
	  ynew = lgr_park_xy(4,i)
	  ienew = lgr_park_ie(i)
	  call lag_stk_end(ienew,iel,x,y,xnew,ynew,xi)
	  return
	end if

	if( lb > 1 .or. iel <= 0 .or. ty < 0) return !not in surface, out, or beached
	if( stkpar <= 0. ) return !no wind drag

        ttime = time
        dx = 0.
        dy = 0.
        ienew = 0

!---------------------------------------------------------------
! horizontal drift 
!---------------------------------------------------------------

        !-----------------------------------------------
        ! Compute wind on element
        !-----------------------------------------------
        wx = 0.
        wy = 0.
        do ii=1,3
          k = nen3v(ii,iel)
          wx = wx + wxv(k)
          wy = wy + wyv(k)
        end do
        wx = wx / 3.
        wy = wy / 3.

        !-----------------------------------------------
        ! Compute drift displacement and new coordinates
        !-----------------------------------------------
	dx = wx*stkpar*ttime
	dy = wy*stkpar*ttime

        xnew = x + dx
        ynew = y + dy

        if ( bsphe ) then
           ddx = dx
           ddy = dy
           dlon0 = x
           dlat0 = y
           call ev_c2g(ddx,ddy,xc,yc,dlon0,dlat0)
           xnew = xc
           ynew = yc
        end if

	if( bmpi_lagr ) then
	  call lgr_mpi_locate(i,2,iel,x,y,xnew,ynew,ienew,bpark)
	  if( bpark ) return	!parked: resumed with bresume
	else
          call find_elem_from_old(iel,xnew,ynew,ienew)
	  if( blgr_dbg ) call lgr_mpi_relocate_check(iel,xnew,ynew,ienew)
	end if

	call lag_stk_end(ienew,iel,x,y,xnew,ynew,xi)

!---------------------------------------------------------------
! end of routine
!---------------------------------------------------------------

        end subroutine lag_stk

!**********************************************************************

        subroutine lag_stk_end(ienew,iel,x,y,xnew,ynew,xi)

! the end of the Stokes drift step after the element search of the new
! point (xnew,ynew): ienew is the element found, 0 if none (then the
! fallback particle_on_side runs on iel, the element before the step);
! the particle takes the new point and element (no layer test in this
! step) and its internal coordinates there. Called by lag_stk for a
! particle that is not parked and for a parked one when it is resumed

        implicit none

        integer, intent(inout)  :: ienew        !element found, 0 none
        integer, intent(inout)  :: iel          !element (new on return)
        real, intent(inout)     :: x,y          !old point (new on return)
        real, intent(inout)     :: xnew,ynew    !new point
        double precision, intent(inout):: xi(3) !internal coordinates

        double precision        :: xx,yy

        if (ienew == 0 ) then
           ienew = iel
           call particle_on_side(ienew,x,y,xnew,ynew)
        end if

        !-----------------------------------------------
        ! Assign new coordinates and element to particle 
        !-----------------------------------------------
        x   = xnew
        y   = ynew
        iel = ienew

        !-----------------------------------------------
        ! From external to internal coordinates
        !-----------------------------------------------
        xx = x
        yy = y
        call xy2xi(abs(iel),xx,yy,xi)	!particle_on_side may set iel < 0

        end subroutine lag_stk_end

!**********************************************************************




