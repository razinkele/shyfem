
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
! The old point (xo,yo) is where the particle was: in lag_diff_hor the
! position computed from its internal coordinates in ie, in lag_stk the
! x,y that the diffusion step left (this routine's own result included).
! It normally lies in or on element ie within the rounding distance delta
! (below); an old point outside the element by more than delta is
! handled as well (see the cases).
!
! The side crossed is the side through which the move leaves element ie,
! and the point returned is where it leaves. With the area coordinates
! xi(ii) of a point in ie (xi(ii) = 0 on side ii, the side opposite vertex
! ii between the nodes nen3v(mod(ii,3)+1,ie) and nen3v(mod(ii+1,3)+1,ie))
! the move is xi(s) = xio + s*(xin-xio), 0 <= s <= 1, and the element is
! xi(ii) >= 0 for ii = 1,2,3: the move is inside for s from s_in (where
! it enters, 0 if it starts in or on the element) to s_out (where it
! leaves: the smallest s at which a side with xin(ii) < xio(ii), a side
! the move leaves through, reaches 0). What is returned (lgr_ieltv(ii,ie)
! is the side table of the tracker):
!
!  - a move of zero length (xn,yn equal to xo,yo) changes nothing: the
!    arguments are returned as they came
!  - the move leaves through side ii at s = s_out < 1: the point on side
!    ii at s_out is returned; at a wall (lgr_ieltv == 0), a neighbour
!    (> 0) or a cut-off side (<= -1000) ie is unchanged, at an open
!    boundary (-999 ... -1) the particle leaves with ie = -ie. A cut-off
!    side is treated like a side with a neighbour because in a serial run
!    that side has a neighbour element and this is what runs there.
!  - a move that starts on side ii and enters the element does not cross
!    side ii: it leaves through another side (above)
!  - a move that starts on side ii and goes straight out through it
!    (never inside) crosses side ii at its start: the old point is
!    returned exactly, and the kind of side ii decides as above (at an
!    open boundary the particle leaves). The point returned jumps at the
!    edge of the band: a start within delta of side ii with an end more
!    than delta beyond it returns the start point, even on a long,
!    shallow move, while an end within delta (say 0.99 delta beyond)
!    returns the end projected on side ii (below)
!  - a move that leaves through a vertex (two sides it leaves through
!    reach 0 within delta of s_out): the point at s_out is returned; a
!    side that keeps the particle (wall, neighbour, cut-off side) wins
!    over an open boundary, so the particle leaves only if both sides
!    are open boundaries. A side the move does not leave through never
!    takes part, however short the move.
!  - the old point lies outside the element by more than delta and the
!    move enters it (inside over more than delta before it leaves): it
!    leaves at s_out as above, or ends inside (last case)
!  - a move that does not meet the element (the old point lies outside
!    by more than delta and the move never gets inside, or gets inside
!    over no more than delta before it leaves): no side is crossed, the
!    old point is returned and ie is unchanged
!  - a move that runs along side ii (the old point and the new point both
!    within delta of the line of side ii): side ii sets no limit, and the
!    move leaves where it reaches another side (above), at the end of
!    side ii through the side that meets it there. That other side alone
!    decides, not the rule that a side keeping the particle wins at a
!    vertex. A move to the same end point from a start more than delta
!    inside is decided by the side its segment reaches first: mostly that
!    same other side (the same outcome), side ii if it reaches side ii
!    first, and both sides together (a vertex, where a side that keeps
!    the particle wins) only if the segment passes through the vertex.
!    So the outcomes can differ in both directions: along a wall to its
!    corner with an open boundary the particle leaves, while a start
!    inside whose segment passes through the vertex keeps it; along an
!    open side to its corner with a wall the particle stays, while a
!    start inside that reaches the open side first leaves. All of these
!    lie within a few delta of the vertex. If it reaches no
!    other side (s_out >= 1) and the new point lies beyond the line of
!    side ii (its raw area coordinate xi(ii) < 0, by any amount):
!      - if the move goes outward (raw xi(ii) of the new point below that
!        of the old point) it crosses side ii at its end: the new point
!        projected on side ii is returned, and the kind of side ii
!        applies (an open boundary lets the particle leave)
!      - if it goes inward or exactly parallel (it ends beyond the line
!        only because it started beyond it) no side is crossed: the new
!        point projected on side ii is returned with ie unchanged,
!        whatever the kind of side ii
!    "Beyond" is any negative raw coordinate because a move that starts
!    more than delta inside side ii and ends at the same new point leaves
!    through side ii for any negative raw coordinate of its end (s_out is
!    then < 1) and does not for a coordinate >= 0, so for an outward move
!    the start point does not change whether side ii is crossed. It does
!    in two cases: a move that ends beyond the line only because it
!    started beyond it (inward or parallel: no crossing, because an exit
!    needs an outward move, the one outcome that cannot be undone), and
!    a move along two sides at once, at a vertex (the side the new point
!    is farther beyond is taken; at an exact tie a side that keeps the
!    particle), where a start more than delta inside would be decided by
!    the vertex rule above.
!  - no side reached before s = 1 otherwise: the new point lies in the
!    element by this arithmetic (all its raw area coordinates >= 0, or
!    within delta of the line of a side the move runs along and not
!    beyond it); it is returned with ie unchanged, no side is crossed
! A point returned lies beyond a side by no more than the rounding of
! single precision, with two exceptions: a crossing returned for a move
! that runs along a side inside the band and leaves through another side
! can lie beyond the side it runs along by up to the band plus that
! rounding (at most about 1.21 delta, 1.18 delta in geographic
! coordinates, as measured by the review), and the old point is returned
! as it is when it lies outside by more than delta.
!
! Rounding: the arithmetic is in double precision from the single
! precision coordinates. delta = lgr_side_delta (mod_lagrange_mpi) of the
! largest absolute coordinate of the two points, 2 spacings, is the
! rounding distance (the self-test takes its delta from the same
! function): an old point within delta of the line of side ii counts as
! lying on side ii (its xi(ii) is set to 0; so is the new point's if it
! is also within delta: a move along side ii), the move must stay inside
! over more than delta to enter the element, and sides the move leaves
! through within delta of s_out count as reached at s_out (a vertex). A
! point returned on a side lies on it within the rounding of single
! precision; xy2xi, which the callers apply next on element abs(ie),
! clips its area coordinates onto the element. Every side is computed
! from its own two nodes and the two points, never from another side, so
! which side is found does not depend on the numbering of the sides; only
! the order of the kinds at a vertex is a rule (keep over leave), and the
! outcome is the same for every side that keeps the particle. A
! degenerate element (zero area) returns the old point, ie unchanged.
! (issue #223: the nodes 1, 2, 3 of the mesh were used instead of those
! of element ie, and a side was picked by coordinate ranges for a move of
! zero length and by the order of the sides for a move starting on one)

        subroutine particle_on_side(ie,xo,yo,xn,yn)

        use basin
        use mod_lagrange_mpi, only : lgr_ieltv	!side table of the tracker
        use mod_lagrange_mpi, only : lgr_side_delta	!rounding distance

        implicit none

        integer, intent(inout)  :: ie           !element number
        real, intent(in)        :: xo,yo        !original coordinates
        real, intent(inout)     :: xn,yn        !new coordinates

        integer                 :: ii,i1,i2,iside,ialong
        logical                 :: bmeet
        logical                 :: bout(3),balong(3)
        double precision        :: xv(3),yv(3),area,hlen(3),band
        double precision        :: xior(3),xinr(3)	!raw area coordinates
        double precision        :: xio(3),xin(3),dxi(3),sout(3)
        double precision        :: delta,dlen,stol,s_in,smin
        double precision        :: t,dbeyond,dbest

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

        delta = lgr_side_delta( max(abs(xo),abs(yo),abs(xn),abs(yn)) )
        dlen = sqrt( (dble(xn)-dble(xo))**2 + (dble(yn)-dble(yo))**2 )
        stol = delta / dlen			!delta as a fraction of the move

        !-----------------------------------------------
        ! where the move enters (s_in) and leaves (sout) each side's line
        !-----------------------------------------------

        s_in = 0.d0
        smin = huge(1.d0)			!no side the move leaves through
        bmeet = .true.
        do ii=1,3
          i1 = mod(ii,3) + 1
          i2 = mod(i1,3) + 1
          xior(ii) = ( (xv(i1)-xo)*(yv(i2)-yo)				&
     &			- (xv(i2)-xo)*(yv(i1)-yo) ) / area
          xinr(ii) = ( (xv(i1)-xn)*(yv(i2)-yn)				&
     &			- (xv(i2)-xn)*(yv(i1)-yn) ) / area
          xio(ii) = xior(ii)
          xin(ii) = xinr(ii)
          hlen(ii) = sqrt( (xv(i2)-xv(i1))**2 + (yv(i2)-yv(i1))**2 )
          band = delta * hlen(ii) / abs(area)	!delta in units of xi(ii)
          balong(ii) = .false.
          if( abs(xio(ii)) <= band ) then	!old point on side ii
            xio(ii) = 0.d0
            if( abs(xin(ii)) <= band ) then	!move along side ii
              xin(ii) = 0.d0
              balong(ii) = .true.
            end if
          end if
          dxi(ii) = xin(ii) - xio(ii)
          bout(ii) = ( dxi(ii) < 0.d0 )		!leaves through side ii
          sout(ii) = 0.d0
          if( dxi(ii) > 0.d0 ) then		!towards the inside of side ii
            s_in = max( s_in, -xio(ii)/dxi(ii) )
          else if( bout(ii) ) then		!towards the outside of side ii
            sout(ii) = xio(ii) / (-dxi(ii))
            smin = min( smin, sout(ii) )
            if( sout(ii) < 0.d0 ) bmeet = .false.	!beyond it, moving away
          else if( xio(ii) < 0.d0 ) then	!along side ii, beyond it
            bmeet = .false.
          end if
        end do

        !-----------------------------------------------
        ! a move that does not meet the element: the particle stays
        !-----------------------------------------------

        if( s_in > 0.d0 ) then			!old point outside the element
          if( smin - s_in <= stol ) bmeet = .false.
        end if
        if( .not. bmeet .or. s_in > 1.d0 ) then
          xn = xo
          yn = yo
          return
        end if

        !-----------------------------------------------
        ! no side left before the new point: in the element, or beyond a
        ! side the move runs along (projected on that side)
        !-----------------------------------------------

        if( smin >= 1.d0 ) then
          ialong = 0
          dbest = 0.d0
          do ii=1,3
            if( balong(ii) .and. xinr(ii) < 0.d0 ) then
              dbeyond = -xinr(ii) * abs(area) / hlen(ii)	!distance beyond
              if( ialong == 0 .or. dbeyond > dbest ) then
                ialong = ii
                dbest = dbeyond
              else if( dbeyond == dbest .and. is_open(ialong)		&
     &			.and. .not. is_open(ii) ) then
                ialong = ii
              end if
            end if
          end do
          if( ialong == 0 ) return		!the new point is in the element
          i1 = mod(ialong,3) + 1
          i2 = mod(i1,3) + 1
          t = ( (dble(xn)-xv(i1))*(xv(i2)-xv(i1))			&
     &		+ (dble(yn)-yv(i1))*(yv(i2)-yv(i1)) ) / hlen(ialong)**2
          t = max( 0.d0, min( 1.d0, t ) )
          xn = xv(i1) + t * (xv(i2)-xv(i1))	!projected on side ialong
          yn = yv(i1) + t * (yv(i2)-yv(i1))
          if( xinr(ialong) < xior(ialong) ) then	!outward: crosses it
            if( is_open(ialong) ) ie = -ie	!open boundary: leaves
          end if
          return
        end if

        !-----------------------------------------------
        ! the side crossed: left through at smin (within stol: a vertex,
        ! where a side that keeps the particle wins over an open boundary)
        !-----------------------------------------------

        iside = 0
        do ii=1,3
          if( bout(ii) .and. sout(ii) <= smin + stol ) then
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
