
!--------------------------------------------------------------------------
!
!    Copyright (C) 2009-2010,2014-2015,2017-2019  Georg Umgiesser
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

! general utilities for lagrangian model
!
! revision log :
!
! 05.02.2009	ggu	copied from other files
! 23.03.2010	ggu	changed v6.1.1
! 28.03.2014	ggu	compute total length of open boundary
! 05.05.2014	ggu	changed VERS_6_1_74
! 23.12.2014	ggu	changed VERS_7_0_11
! 19.01.2015	ggu	changed VERS_7_1_3
! 05.05.2015	ggu	changed VERS_7_1_10
! 17.07.2015	ggu	changed VERS_7_1_80
! 20.07.2015	ggu	changed VERS_7_1_81
! 31.03.2017	ggu	changed VERS_7_5_24
! 23.08.2018	ccf	include particle_on_side routine
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
!
!*******************************************************************

        function dist_node(k1,k2)

! returns distance between two nodes

	use basin

        implicit none

        real dist_node
        integer k1,k2

        real x1,y1,x2,y2,dx,dy

        x1 = xgv(k1)
        y1 = ygv(k1)
        x2 = xgv(k2)
        y2 = ygv(k2)

        dx = x1 - x2
        dy = y1 - y2

        dist_node = sqrt( dx*dx + dy*dy )

        end

!*******************************************************************

	subroutine dist_total(ibc,totdist)

! returns total length of open boundary

	implicit none

	integer ibc
	real totdist

	integer nk,i,k1,k2
	real dxy

	integer nkbnds,kbnds
	real dist_node

	nk = nkbnds(ibc)

        totdist = 0.
        do i=2,nk
          k1 = kbnds(ibc,i-1)
          k2 = kbnds(ibc,i)
          dxy = dist_node(k1,k2)
          totdist = totdist + dxy
        end do

	end

!*******************************************************************

	subroutine basin_center(xm,ym)

! returns center of gravity of total basin

	use basin

	implicit none

	real xm,ym

	call xy_center(nkn,xgv,ygv,xm,ym)

	end
	
!*******************************************************************

	subroutine compute_total_area(area)

	use evgeom
	use basin, only : nkn,nel,ngr,mbw

	implicit none

	real area

	integer ie
	double precision a,tot_area

	tot_area = 0.

	do ie=1,nel
	  a = ev(10,ie)
	  tot_area = tot_area + a
	end do

	area = 12. * tot_area

	end

!******************************************************************
! Fallback of the horizontal diffusion step (lag_diff_hor) and of the
! Stokes drift step (lag_stk) of a particle in element ie, called only
! when find_elem_from_old found no element for the new point (xn,yn).
! The particle moved from the old point (xo,yo), which lies in or on
! element ie (within the rounding of single precision), to (xn,yn).
!
! The side crossed is the side through which the move leaves element ie,
! and the point returned is where it leaves. With the area coordinates
! xi(ii) of a point in ie (xi(ii) = 0 on side ii, the side opposite vertex
! ii between the nodes nen3v(mod(ii,3)+1,ie) and nen3v(mod(ii+1,3)+1,ie))
! the move is xi(s) = xio + s*(xin-xio), 0 <= s <= 1, and the element is
! xi(ii) >= 0 for ii = 1,2,3: the move is inside for s from sin (where it
! enters, 0 if it starts in or on the element) to sout (where it leaves,
! the smallest s at which a side with xin(ii) < xio(ii) reaches 0). What
! is returned (lgr_ieltv(ii,ie) is the side table of the tracker):
!
!  - a move of zero length (xn,yn equal to xo,yo) changes nothing: the
!    arguments are returned as they came
!  - the move leaves through side ii at s = sout <= 1: the point on side
!    ii at sout is returned; at a wall (lgr_ieltv == 0), a neighbour
!    (> 0) or a cut-off side (<= -1000) ie is unchanged, at an open
!    boundary (-999 ... -1) the particle leaves with ie = -ie. A cut-off
!    side is treated like a side with a neighbour because in a serial run
!    that side has a neighbour element and this is what runs there.
!  - a move that starts on side ii and enters the element does not cross
!    side ii: it leaves through another side (above)
!  - a move that starts on side ii and goes straight out through it
!    (never inside) crosses side ii at its start: the old point is
!    returned exactly, and the kind of side ii decides as above (at an
!    open boundary the particle leaves)
!  - a move that runs along side ii (the old point and the new point both
!    within rounding of the line of side ii): side ii sets no limit, and
!    the move leaves where it reaches another side, at the end of side ii
!    (a vertex) through the side that meets side ii there (above)
!  - a move that leaves through a vertex (two sides within rounding of
!    the same s): the point there is returned; a side that keeps the
!    particle (wall, neighbour, cut-off side) wins over an open boundary,
!    so the particle leaves only if both sides are open boundaries
!  - the new point lies in element ie by this arithmetic (no side reached
!    before s = 1: a matter of rounding, or a move along side ii that ends
!    within rounding of its line): the new point is returned, ie
!    unchanged, no side is crossed
!  - a move that does not meet the element (the old point lies outside
!    the element by more than rounding and the move never gets inside, or
!    gets inside over no more than rounding): no side is crossed, the old
!    point is returned and ie is unchanged; the particle stays where it
!    was and the new point, outside the element, is never returned
!
! Rounding: the arithmetic is in double precision from the single
! precision coordinates. delta = 2 spacings of the largest coordinate of
! the move is the rounding distance: an old point within delta of the
! line of side ii counts as lying on side ii (its xi(ii) is set to 0;
! so is the new point's if it is also within delta: a move along side ii),
! the move must stay inside over more than delta to enter the element,
! and a side reached within delta of sout counts as reached at sout (a
! vertex). A point returned on a side lies on it within the rounding of
! single precision; xy2xi, which the callers apply next on element
! abs(ie), clips its area coordinates onto the element.
! Every side is computed from its own two nodes and the two
! points, never from another side, so which side is found does not
! depend on the numbering of the sides; only the order of the kinds at a
! vertex is a rule (keep over leave), and the outcome is the same for
! every side that keeps the particle. A degenerate element (zero area)
! returns the old point with ie unchanged.
! (issue #223: the nodes 1, 2, 3 of the mesh were used instead of those
! of element ie, and a side was picked by coordinate ranges for a move of
! zero length and by the order of the sides for a move starting on one)

        subroutine particle_on_side(ie,xo,yo,xn,yn)

        use basin
        use mod_lagrange_mpi, only : lgr_ieltv	!side table of the tracker

        implicit none

        integer, intent(inout)  :: ie           !element number
        real, intent(in)        :: xo,yo        !original coordinates
        real, intent(inout)     :: xn,yn        !new coordinates

        integer                 :: ii,i1,i2,iside
        logical                 :: bmeet
        double precision        :: xv(3),yv(3),area,hlen,band
        double precision        :: xio(3),xin(3),dxi(3),sout(3)
        double precision        :: delta,dlen,stol,sin,smin

        if( xo == xn .and. yo == yn ) return	!zero length: nothing changes

        do ii=1,3
          xv(ii) = xgv(nen3v(ii,ie))
          yv(ii) = ygv(nen3v(ii,ie))
        end do
        area = (xv(2)-xv(1))*(yv(3)-yv(1)) - (xv(3)-xv(1))*(yv(2)-yv(1))
        if( area == 0.d0 ) then			!degenerate element
          xn = xo
          yn = yo
          return
        end if

        delta = 2.d0 * spacing( max(abs(xo),abs(yo),abs(xn),abs(yn)) )
        dlen = sqrt( (dble(xn)-dble(xo))**2 + (dble(yn)-dble(yo))**2 )
        stol = delta / dlen			!delta as a fraction of the move

        !-----------------------------------------------
        ! where the move enters (sin) and leaves (sout) each side's line
        !-----------------------------------------------

        sin = 0.d0
        bmeet = .true.
        do ii=1,3
          i1 = mod(ii,3) + 1
          i2 = mod(i1,3) + 1
          xio(ii) = ( (xv(i1)-xo)*(yv(i2)-yo)				&
     &			- (xv(i2)-xo)*(yv(i1)-yo) ) / area
          xin(ii) = ( (xv(i1)-xn)*(yv(i2)-yn)				&
     &			- (xv(i2)-xn)*(yv(i1)-yn) ) / area
          hlen = sqrt( (xv(i2)-xv(i1))**2 + (yv(i2)-yv(i1))**2 )
          band = delta * hlen / abs(area)	!delta in units of xi(ii)
          if( abs(xio(ii)) <= band ) then	!old point on side ii
            xio(ii) = 0.d0
            if( abs(xin(ii)) <= band ) xin(ii) = 0.d0	!move along side ii
          end if
          dxi(ii) = xin(ii) - xio(ii)
          sout(ii) = 2.d0			!the move does not leave here
          if( dxi(ii) > 0.d0 ) then		!towards the inside of side ii
            sin = max( sin, -xio(ii)/dxi(ii) )
          else if( dxi(ii) < 0.d0 ) then	!towards the outside of side ii
            sout(ii) = xio(ii) / (-dxi(ii))
            if( sout(ii) < 0.d0 ) bmeet = .false.	!beyond it, moving away
          else if( xio(ii) < 0.d0 ) then	!along side ii, beyond it
            bmeet = .false.
          end if
        end do
        smin = minval(sout)

        !-----------------------------------------------
        ! a move that does not meet the element: the particle stays
        !-----------------------------------------------

        if( sin > 0.d0 ) then			!old point outside the element
          if( smin - sin <= stol ) bmeet = .false.
        end if
        if( .not. bmeet .or. sin > 1.d0 ) then
          xn = xo
          yn = yo
          return
        end if

        !-----------------------------------------------
        ! no side reached before the new point: it is in the element
        !-----------------------------------------------

        if( smin >= 1.d0 ) return

        !-----------------------------------------------
        ! the side crossed: reached at smin (within stol: a vertex, where
        ! a side that keeps the particle wins over an open boundary)
        !-----------------------------------------------

        iside = 0
        do ii=1,3
          if( sout(ii) <= smin + stol ) then
            if( iside == 0 ) then
              iside = ii
            else if( is_open(iside) .and. .not. is_open(ii) ) then
              iside = ii
            end if
          end if
        end do

        if( smin <= stol ) then			!at the start: the old point
          xn = xo
          yn = yo
        else
          xn = xo + smin * (dble(xn)-dble(xo))
          yn = yo + smin * (dble(yn)-dble(yo))
        end if

        if( is_open(iside) ) ie = -ie		!open boundary: particle leaves

        contains

          logical function is_open(is)
          integer, intent(in) :: is	!side of element ie
          is_open = ( lgr_ieltv(is,ie) < 0 .and. lgr_ieltv(is,ie) > -1000 )
          end function is_open

        end subroutine particle_on_side

!******************************************************************
