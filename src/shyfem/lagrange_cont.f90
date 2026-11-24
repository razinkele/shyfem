
!--------------------------------------------------------------------------
!
!    Copyright (C) 2007-2012,2014-2015,2018-2019  Georg Umgiesser
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
! 12.06.2008	ggu	initialize also z
! 28.08.2009	ggu	new call to find_elems_to_segment (before line_elems)
! 23.03.2010	ggu	changed v6.1.1
! 16.12.2011	ggu	new routine lagr_continuous_release_ppv()
! 23.01.2012	ggu	new routine for release in point, connectivity
! 25.01.2012	ggu	changed VERS_6_1_42
! 29.08.2012	ggu	changed VERS_6_1_56
! 23.10.2012	ggu	do not call connectivity here anymore
! 28.03.2014	ggu	new routine lagr_continuous_release_pps_ppv()
! 05.05.2014	ggu	changed VERS_6_1_74
! 07.07.2014	ggu	changed VERS_6_1_79
! 19.01.2015	ggu	changed VERS_7_1_3
! 01.04.2015	ggu	changed VERS_7_1_7
! 23.04.2015	ggu	changed VERS_7_1_8
! 21.05.2015	ggu	changed VERS_7_1_11
! 17.07.2015	ggu	changed VERS_7_1_80
! 20.07.2015	ggu	changed VERS_7_1_81
! 16.11.2015	ggu	changed VERS_7_3_14
! 20.11.2015	ggu	changed VERS_7_3_15
! 03.04.2018	ggu	changed VERS_7_5_43
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
!
!*******************************************************************

	subroutine lagr_continuous_release_shell

	implicit none

	!call lagr_continuous_release_pps
	!call lagr_continuous_release_ppv
	call lagr_continuous_release_pps_ppv

	end

!*******************************************************************

	subroutine lagr_continuous_release_ppv

! continuous release - number of particles depends on volume flux

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random_release

	implicit none

	integer k1,k2
	integer ibc,nk,i,ibtyp,np
	real dt
	real q,ppv

	logical bdebug
	integer nbnds,nkbnds,kbnds,nbc
	integer nptot,iptot
	real rp

	real get_bflux_ppv

	call get_timestep(dt)

	bdebug = .false.

	nbc = nbnds()

	do ibc=1,nbc

	  nk = nkbnds(ibc)
	  call get_bnd_ipar(ibc,'ibtyp',ibtyp)
	  call get_bnd_par(ibc,'lgrppv',ppv)

	  if( ibtyp .eq. 1 ) then	!only for level boundaries

	    iptot = 0
	    rp = lgr_random_release()	! vary starting point of particles
	    do i=2,nk
	      k1 = kbnds(ibc,i-1)
	      k2 = kbnds(ibc,i)
	      q = get_bflux_ppv(k1,k2)
	      q = max(q,0.)
	      rp = rp + q*ppv*dt
	      np = rp
	      if( np .gt. 0 ) then
		rp = rp - np
		iptot = iptot + np
	        call create_parts(ibc,np,k1,k2)
	      end if
	    end do

	    !if( iptot .ne. 0 ) then
	    !  write(lunit,*) 'number of particles released: ',ibc,iptot
	    !end if

	  end if

	end do

	end

!*******************************************************************

	subroutine lagr_continuous_release_pps

! continuous release - number of particles is independent of boundary length

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random_release

	implicit none

	integer k1,k2
	integer ibc,nk,i,ibtyp,np
	real totdist,dxy,part,dt

	integer nbnds,nkbnds,kbnds,nbc
	integer iptot
	real rp,pps,q
	real dist_node

	call get_timestep(dt)

	nbc = nbnds()

	do ibc=1,nbc

	  nk = nkbnds(ibc)
	  call get_bnd_ipar(ibc,'ibtyp',ibtyp)
	  call get_bnd_par(ibc,'lgrpps',pps)

	  if( ibtyp .eq. 1 ) then	!only for level boundaries

	    call dist_total(ibc,totdist)

	    iptot = 0
	    rp = lgr_random_release()	! vary starting point of particles
	    do i=2,nk
	      k1 = kbnds(ibc,i-1)
	      k2 = kbnds(ibc,i)
	      dxy = dist_node(k1,k2)
	      q = dxy/totdist
	      rp = rp + q*pps*dt
	      np = rp
	      if( np .gt. 0 ) then
		rp = rp - np
		iptot = iptot + np
	        call create_parts(ibc,np,k1,k2)
	      end if
	    end do

	    !if( iptot .ne. 0 ) then
	    !  write(lunit,*) 'number of particles released: ',iptot
	    !end if

	  end if

	end do

	end

!*******************************************************************

	subroutine lagr_continuous_release_pps_ppv

! continuous release - works both for pps and ppv
!
! replaces the routines above
!
! along a level or flux boundary the particles are released on the sides
! of the basin boundary between consecutive nodes of kbound. Two
! consecutive nodes that are not the ends of such a side (the list leaves
! out boundary nodes between them: the side joining them is an inner side
! of the mesh, or no side joins them; the Mar Menor sea boundary of the
! test cases leaves out the nodes 13 and 14) are skipped: no particles
! are released between them and, for lgrpps > 0, their distance is left
! out of the length the release is spread over, so the boundary releases
! the particles per second it is given. The first call writes a warning
! for every pair skipped, and stops the run if a boundary with lgrpps has
! two nodes or more and no side of the basin boundary between them
! (lgr_release_line, #254). The hydrodynamics runs with such a list (the
! Mar Menor cases do; the open boundary, bndo, only needs every node to
! have a neighbour on the basin boundary in the list), so it is not
! rejected

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random_release

	implicit none

	integer k,k1,k2
	integer ibc,nk,i,ibtyp,np
	real totdist,dxy,part,dt

	logical bflux,bfirst
	integer nbnds,nkbnds,kbnds,nbc
	integer iptot
	integer ie,ne
	real rp,pps,q

	real dist_node
	real get_bflux_ppv

	integer, save :: icall = 0

	bfirst = ( icall == 0 )		!warnings of lgr_release_line
	icall = 1

	call get_timestep(dt)

	nbc = nbnds()

	do ibc=1,nbc

	  nk = nkbnds(ibc)
	  call get_bnd_ipar(ibc,'ibtyp',ibtyp)
	  call get_bnd_par(ibc,'lgrpps',pps)

	  bflux = pps .lt. 0.	!if pps is negative it stands for parts per vol
	  pps = abs(pps)

	  if( pps .gt. 0. ) then
	   if( ibtyp .eq. 1 .or. ibtyp .eq. 2 ) then	!level or flux bnds

	    call lgr_release_line(ibc,bfirst,totdist)

	    iptot = 0
	    rp = lgr_random_release()	! vary starting point of particles
	    do i=2,nk
	      k1 = kbnds(ibc,i-1)
	      k2 = kbnds(ibc,i)
	      call lgr_segment_elem(k1,k2,ie,ne)
	      if( ne /= 1 ) cycle	!no side of the basin boundary: skipped
	      if( bflux ) then
		q = get_bflux_ppv(k1,k2)
	      else
	        q = dist_node(k1,k2) / totdist
	      end if
	      q = max(q,0.)
	      rp = rp + q*pps*dt
	      np = rp
	      if( np .gt. 0 ) then
		rp = rp - np
		iptot = iptot + np
	        call create_parts(ibc,np,k1,k2)
	      end if
	    end do

	   else if( ibtyp .eq. 3 ) then		!release on nodes

	    iptot = 0
	    rp = lgr_random_release()	! vary starting point of particles
	    do i=1,nk
	      k = kbnds(ibc,i)
	      if( bflux ) then
		call get_bnd_par(ibc,'zval',q)
	      else
	        q = 1
	      end if
	      rp = rp + q*pps*dt 
	      call release_on_node(ibc,rp,k,np)
	      rp = rp - np
	      iptot = iptot + np
	    end do

	   end if
	  end if

	  !if( pps .ne. 0 ) then
	  !  write(lunit,*) 'particles released: ',bflux,ibc,pps,iptot
	  !end if

	end do

	end

!*******************************************************************

	subroutine create_parts(ity,np,k1,k2)

! the place on the segment and the time in the step are the draws of the
! particle(s) insert_particle_3d releases next (#225): lgr_random keyed on
! the first id it gives (idbdy+1; continuous release is serial only)
!
! k1-k2 must be a side of the basin boundary; the particles start in its
! element (lgr_segment_elem, #254). lagr_continuous_release_pps_ppv
! passes no other pair, so the stop is an internal error

	use basin
	use mod_lagrange, only : idbdy
	use mod_lagrange_random, only : lgr_random
	use mod_lagrange_random, only : lgr_rnd_relpos, lgr_rnd_reltime

	implicit none

	integer, intent(in) :: ity		!type of the particles
	integer, intent(in) :: np		!number of particles
	integer, intent(in) :: k1,k2		!nodes of the side

	integer i,ie1,ne
	real x1,y1,x2,y2,dx,dy
	real rl,rt,x,y
	integer ipext

	if( np .le. 0 ) return

	x1 = xgv(k1)
	y1 = ygv(k1)
	x2 = xgv(k2)
	y2 = ygv(k2)

	dx = x2 - x1
	dy = y2 - y1

	call lgr_segment_elem(k1,k2,ie1,ne)
	if( ne /= 1 ) then
	  write(6,*) 'create_parts: nodes ',ipext(k1),ipext(k2)		&
     &		,' elements with both nodes ',ne
	  call shympi_abort_internal('error stop create_parts: error in'	&
     &		//' boundary')
	end if
	  
	!write(6,*) 'create_parts: ',np,k1,k2,ie1

	do i=1,np
	  rl = lgr_random(idbdy+1,lgr_rnd_relpos,0)
	  rt = lgr_random(idbdy+1,lgr_rnd_reltime,0)
	  x = x1 + rl*dx
	  y = y1 + rl*dy
	  call insert_particle_3d(ie1,ity,rt,x,y)
	  !write(6,*) i,rl,x,y,ie1
	end do

	end

!*******************************************************************

	function get_bflux_ppv(k1,k2)

! flux into the basin over the side k1-k2 of the basin boundary: flux2d
! of its element (lgr_segment_elem, #254) over the side opposite the
! vertex that is neither k1 nor k2, whichever way the list runs.
! lagr_continuous_release_pps_ppv passes no other pair, so the stop is an
! internal error

	use mod_lagrange
	use basin, only : nen3v

	implicit none

	real get_bflux_ppv
	integer, intent(in) :: k1,k2		!nodes of the side

	integer ie1,ne,ii,i
	integer ipext

	call lgr_segment_elem(k1,k2,ie1,ne)

	if( ne /= 1 ) then
	  write(6,*) 'get_bflux_ppv: nodes ',ipext(k1),ipext(k2)		&
     &		,' elements with both nodes ',ne
	  call shympi_abort_internal('error stop get_bflux_ppv: nodes'	&
     &		//' not at boundary')
	end if

	ii = 0
	do i=1,3
	  if( nen3v(i,ie1) /= k1 .and. nen3v(i,ie1) /= k2 ) ii = i
	end do

	get_bflux_ppv = flux2d(ii,ie1)
	
	end

!*******************************************************************
!*******************************************************************
!*******************************************************************

	subroutine release_on_node(ity,ppts,k,n)

! release on node

	use basin

	implicit none

	integer ity		!type of particle
	real ppts		!particles to be released per time step
	integer k		!node where particle is released
	integer n

	integer ie
	real x,y

	call find_elem_to_node(k,ie,x,y)
	!write(6,*) 'inserting... ',k,ie,x,y

	call release_on_point(ity,ppts,ie,x,y,n)

	end

!*******************************************************************

	subroutine find_elem_to_node(k,iee,x,y)

	use basin
	use mod_lagrange_random, only : lgr_random_release

! be sure particle is in an element
! (the element is drawn from the release stream of the step, #225)

	implicit none

	integer k
	integer iee
	real x,y

	integer ie,ii,kk,n,i
	real xs,ys,alpha
	integer ielist(ngr)

	n = 0
	alpha = 0.99

	do ie=1,nel
	  do ii=1,3
	    kk = nen3v(ii,ie)
	    if( kk .eq. k ) then
	      n = n + 1
	      if( n > ngr ) call shympi_abort_internal(			&
     &		'error stop find_elem_to_node: internal')
	      ielist(n) = ie
	    end if
	  end do
	end do

	if( n == 0 ) call shympi_abort_internal(				&
     &		'error stop find_elem_to_node: internal 2')

	i = 1 + n*lgr_random_release()
	if( i > n ) i = n

	iee = ielist(i)
	ie = iee

	xs = 0.
	ys = 0.
	n = 0
	do ii=1,3
	  kk = nen3v(ii,ie)
	  if( k /= kk ) then
	    xs = xs + xgv(kk)
	    ys = ys + ygv(kk)
	  else
	    n = n + 1
	  end if
	end do

	if( n /= 1 ) call shympi_abort_internal(				&
     &		'error stop find_elem_to_node: internal 3')

	xs = xs / 2.
	ys = ys / 2.

	x = alpha*xgv(k) + (1.-alpha)*xs
	y = alpha*ygv(k) + (1.-alpha)*ys
	
	end

!*******************************************************************

	subroutine release_on_point(ity,ppts,ie,x,y,n)

! release from one point - works for 2D
!
! the number of particles is drawn from the release stream of the step,
! the time in the step of each particle with the first id that
! insert_particle_3d gives it (idbdy+1) (#225; serial only)

	use mod_lagrange, only : idbdy
	use mod_lagrange_random, only : lgr_random, lgr_random_release
	use mod_lagrange_random, only : lgr_rnd_reltime

	implicit none

	integer ity		!type of particle
	real ppts		!particles to be released per time step
	integer ie		!element where particle is released
	real x,y		!coordinates where to release
	integer n		!number of particles released (return)

	integer i
	real rt

	n = ppts + lgr_random_release()		!particles to release

	do i=1,n
	  rt = lgr_random(idbdy+1,lgr_rnd_reltime,0)	!vary time
	  call insert_particle_3d(ie,ity,rt,x,y)
	  !write(55,*) 'gguuyy particle: ',ie,rt,x,y
	end do

	end

!*******************************************************************

	subroutine lgr_segment_elem(k1,k2,ie,ne)

! the elements of the basin that have both nodes k1 and k2 (internal
! numbers): ne of them, 0 if no side joins the two nodes, 1 if k1-k2 is a
! side of the basin boundary (ie is then its element), 2 if it is an
! inner side; ie = 0 unless ne = 1. Found from nen3v among the elements
! around k1 (get_elems_around), not with find_elems_to_segment, which
! until #252 paired an index into the lists of k1 with the lists of k2
! and gave the element of the neighbouring segment (#254)

	use basin, only : nen3v, ngr

	implicit none

	integer, intent(in) :: k1,k2		!nodes of the segment
	integer, intent(out) :: ie		!element of a boundary side, else 0
	integer, intent(out) :: ne		!elements with both nodes

	integer j,n,iee
	integer elems(ngr)

	ie = 0
	ne = 0
	call get_elems_around(k1,ngr,n,elems)
	do j=1,n
	  iee = elems(j)
	  if( any( nen3v(:,iee) == k2 ) ) then
	    ne = ne + 1
	    ie = iee
	  end if
	end do
	if( ne /= 1 ) ie = 0

	end

!*******************************************************************

	subroutine lgr_release_line(ibc,bwarn,totdist)

! the length totdist of the sides of the basin boundary between
! consecutive nodes of the level or flux boundary ibc (a pair of nodes
! that is not the two ends of such a side is left out, lgr_segment_elem).
! With bwarn (the first call of the release) it writes a warning for each
! pair left out (external node numbers), and stops the run with a clear
! message if the boundary has two nodes or more and no pair is a side of
! the basin boundary: nothing could be released on it (#254). The sum
! runs over the nodes in their order, so a list made of sides of the
! basin boundary gives the length dist_total gave before

	implicit none

	integer, intent(in) :: ibc		!boundary
	logical, intent(in) :: bwarn		!write the warnings, check
	real, intent(out) :: totdist		!length of the boundary sides

	integer nk,i,k1,k2,ie,ne,nside
	integer nkbnds,kbnds,ipext
	real dist_node

	nk = nkbnds(ibc)

	totdist = 0.
	nside = 0
	do i=2,nk
	  k1 = kbnds(ibc,i-1)
	  k2 = kbnds(ibc,i)
	  call lgr_segment_elem(k1,k2,ie,ne)
	  if( ne == 1 ) then
	    totdist = totdist + dist_node(k1,k2)
	    nside = nside + 1
	  else if( bwarn ) then
	    write(6,'(a,i0,a,i0,a,i0,a)') ' warning lagrange: boundary ',ibc	&
     &		,' with lgrpps: nodes ',ipext(k1),' and ',ipext(k2)		&
     &		,' of kbound are not the ends of one side of the basin'	&
     &		//' boundary'
	    if( ne == 2 ) then
	      write(6,'(a)') '   (they are joined by an inner side: the list'	&
     &		//' leaves out the boundary nodes between them);'
	    else
	      write(6,'(a)') '   (no side joins them);'
	    end if
	    write(6,'(a)') '   no particles are released between them, lgrpps'	&
     &		//' applies to the other sides of the list'
	  end if
	end do

	if( bwarn .and. nk > 1 .and. nside == 0 ) then
	  write(6,'(a,i0,a)') ' lagrange: boundary ',ibc,' has lgrpps but no'	&
     &		//' side of the basin boundary between consecutive nodes'	&
     &		//' of kbound: nothing can be released on it'
	  call shympi_abort_internal('error stop lgr_release_line: no'	&
     &		//' boundary side to release on')
	end if

	end

!*******************************************************************
!*******************************************************************
!*******************************************************************

