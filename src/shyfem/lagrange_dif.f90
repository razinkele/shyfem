
!--------------------------------------------------------------------------
!
!    Copyright (C) 2005-2007,2010,2012-2015,2018-2019  Georg Umgiesser
!    Copyright (C) 2005-2007,2012  Andrea Cucco
!    Copyright (C) 2017  Christian Ferrarin
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

! lagrangian diffusion
!
! revision log :
!
! 01.10.2005	aac	written from scratch
! 07.11.2005	ggu	last version integrated in main tree
! 19.06.2006	aac	bugs in diffusion corrected
! 20.06.2006	aac	diffusion coefficient from str file 
! 29.11.2006	ggu	new version integrated into main model
! 14.09.2007	aac	new simplified version more efficient, ran9->1, ran9 del
! 10.11.2007	ggu	renamed random routine from ran1 to ran9 (conflict)
! 23.03.2010	ggu	changed v6.1.1
! 24.01.2012	ggu	changed VERS_6_1_41
! 24.10.2012	aac	do not kill particle if infinite loop -> leave it
! 25.01.2013	ggu	new formula for horizontal diffusivity
! 19.12.2014	ggu	changed VERS_7_0_10
! 16.11.2015	ggu	changed VERS_7_3_14
! 25.05.2017	ccf	vertical diffusion introduced
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 13.03.2019	ggu	changed VERS_7_5_61
! 11.09.2024    lrp     rename gasdev to shygasdev (compatibility with wrf) 
! 16.09.2024    ggu     for bhdiff use abs(ie) in call to xy2xi()
!
!************************************************************
!
! z = 0		top of layer
! z = 1		bottom of layer
!
!************************************************************

        subroutine diff_body(i,id,ty,x,y,z,xi,iel,lb,time,bresume,bpark)

! diffusion of one particle: internal coordinates for vertical
!                            external coordinates for horizontal
!
! on several processes the element search of the horizontal step can
! park the particle (lgr_mpi_locate): bpark is then true and diff_body
! returns at once, the caller stores the particle's state and skips the
! rest of the time step. The particle is resumed later (bresume true): the
! vertical step and the entry test are not made again (they ran before
! it was parked), the horizontal step continues after its search
! (lag_diff_hor_resume), and the statements after it run as for any
! other particle. Parking happens only on several processes, where
! ilagr is 1 or 2 (ilagr = 3 stops there) and so bvdiff is false.
!
! an internal-error guard recorded inside the particle loop (#256:
! lgr_internal_error, then lgr_internal_failed is true) returns at once.
! A walk that ended with time left, the particle out of the domain or
! the cause unknown (no run gets there: the walk ends only with no time
! left, at the cap or after two calls in a row that used no time, since
! lgr_diff_vert never sets lb < 1; the test hook LGR_TEST_VDIFF_END
! forces it), is an event of lgr_event (lgr_ev_vd_lost, lgr_ev_vd_unknown:
! counted, the first kept) and written at the end of the pass by
! lgr_events; until #288 each such particle step wrote a line from
! inside the loop
!
! the vertical walk (#286, #287) takes the layers of the particle's
! element once per step, before its loop (lagr_layer_thickness: the
! element does not change in the walk; only with vertical diffusion, so
! ilagr 1 and 2 and resumed particles do not pay for it), and makes at
! most lgr_nvdiff_max calls of lgr_diff_vert in a step (#261). Each call
! makes one displacement over exactly dt = min(dtvd, time left), across
! the layer interfaces, so a step takes T/dtvd calls rounded up (one more
! where the single-precision time left rounds): one at a constant
! diffusivity (dtvd is the model step there), at most 1500 (1501 with
! that rounding) at T = 300 s (the floor 0.2 s of the gradient term of
! dtvd, lag_vdiff_ele). The cap
! is reached only by a step longer than 2000 s where that floor binds; a
! step that reaches it stops there. Until #286 a call also ended where
! the particle reached an interface of its layer, so the calls of a step
! grew with the diffusivity: in mm_hyd_41 with ilagr = 3 (one day, GOTM
! gives up to 49 m2/s) up to about 19000 calls, and one step of 777212
! reached the cap (142 s of 300 s not diffused); such a call could take
! a time below the resolution of the single-precision time left, which
! then did not change. A call that leaves the time unchanged is still
! counted and the walk goes on, but a second such call in a row ends the
! step: with calls of exactly dt > 0 this cannot happen any more, and the
! rule is kept as a guard against a step that never ends (and keeps the
! log line the checks read). The steps stopped at the cap and those ended
! so are counted with the time not diffused (OMP atomic, as the calls and
! draws of every step) and written once at the end by lgr_vdiff_stats;
! nothing is written in the loop. Until #261 the cap was 100 calls, and
! every step that reached it wrote a line from inside the particle loop
! (59859 lines, 7.7 % of the particle steps of that case, 87 s of 300 s
! not diffused on average)

        use mod_lagrange
        use mod_lagrange_mpi, only : lgr_test_vdiff_end
        use basin
        use levels, only : nlv

        implicit none

        integer, intent(in)	:: i            !particle number
        integer, intent(in)	:: id           !particle id
        integer, intent(in)	:: ty           !particle type
        real, intent(inout)	:: x            !x-coordinate
        real, intent(inout)     :: y            !y-coordinate
        real, intent(inout)     :: z            !relative vertical position
        double precision, intent(inout):: xi(3) !internal coordinates
        integer, intent(inout)	:: iel          !element number
        integer, intent(inout)	:: lb           !layer 
        real, intent(in)	:: time         !time to diffuse
        logical, intent(in)	:: bresume      !resume a parked particle
        logical, intent(out)	:: bpark        !parked in this call

	real 			:: dtime
	real 			:: dtold	!time left before the call
	integer			:: lmax		!layers of the element
	integer			:: l
	real			:: hl(nlv)	!layer thickness
	real			:: hle(0:nlv)	!depth of the interfaces
	real			:: htot,htotz	!depth without and with zeta
        integer 		:: n		!calls left (#261)
        integer 		:: ncall	!calls made in the step
        integer 		:: nzero	!calls that used no time
        integer 		:: nzrow	!of those, the last ones in a row
        double precision 	:: xx,yy,zz
        logical			:: bstall	!ended by two such calls in a row
        logical			:: btend	!walk ended by the test hook
        integer			:: ierr		!error of xy2xi_ierr

        integer			:: ndraw	!vertical draws made (#225)
        logical			:: lgr_internal_failed

	bpark = .false.
	btend = .false.

	if( bresume ) then		!parked: no vertical step (bvdiff false)
	  if( bvdiff ) then
	    call lgr_internal_error(					&
     &		'diff_body: a parked particle with vertical diffusion')
	    return			!recorded in the loop
	  end if
	else
          if( iel <= 0 .or. ty < 0) return     !particle out of domain or beached
	end if

!---------------------------------------------------------------
! initialize
!---------------------------------------------------------------

        n = lgr_nvdiff_max	!maximum loop count (#261)
        zz = z
	dtime = time
	bstall = .false.
	nzero = 0
	nzrow = 0

!---------------------------------------------------------------
! vertical diffusion 
!---------------------------------------------------------------

        if( bvdiff ) then
	  ! the layers of the element, once per particle step (#286): its
	  ! guard records an internal error in the loop (#256)
	  lmax = nlv
	  call lagr_layer_thickness(iel,lmax,hl,htot,htotz)
	  if( lgr_internal_failed() ) return	!recorded in the loop
	  hle(0) = 0.
	  do l = 1,lmax
	    hle(l) = hle(l-1) + hl(l)
	  end do
	  ! the draws of the vertical diffusion of this particle in this step
	  ! are numbered from 0 (site lgr_rnd_vdiff of lgr_random): all of
	  ! them are made in this loop (a particle with vertical diffusion is
	  ! never parked: ilagr = 3 stops on several processes)
	  ndraw = 0
	  ! test hook LGR_TEST_VDIFF_END=N (#288): the walk of a particle
	  ! whose id is a multiple of N ends at once, with its time left
	  if( lgr_test_vdiff_end > 0 ) then
	    btend = ( mod(id,lgr_test_vdiff_end) == 0 )
	  end if
          do while ( dtime > 0. .and. n > 0 )
            if( btend ) exit		!test hook: time left (#288)
            dtold = dtime
            call lgr_diff_vert(id,iel,lmax,hl,hle,lb,zz,dtime,ndraw)
            if( lb < 1 ) exit
            n = n - 1                   !decrement loop counter
            if( dtime < dtold ) then
              nzrow = 0
            else			!no time used (#261): the second in a
              nzero = nzero + 1		!row ends the step
              nzrow = nzrow + 1
              if( nzrow >= 2 ) then
                bstall = .true.
                exit
              end if
            end if
          end do
          z = zz 
          if( lgr_internal_failed() ) return	!recorded in the loop
	  ! the calls and draws of this step (#261), written at the end
	  ! by lgr_vdiff_stats
          ncall = lgr_nvdiff_max - n
!$OMP ATOMIC
          lgr_nvdiff_steps = lgr_nvdiff_steps + 1
!$OMP ATOMIC
          lgr_nvdiff_calls = lgr_nvdiff_calls + ncall
!$OMP ATOMIC
          lgr_nvdiff_mcall = max(lgr_nvdiff_mcall,ncall)
!$OMP ATOMIC
          lgr_nvdiff_mdraw = max(lgr_nvdiff_mdraw,ndraw)
          if( nzero > 0 ) then
!$OMP ATOMIC
            lgr_nvdiff_zero = lgr_nvdiff_zero + nzero
          end if
          ! test hook (#288): an id that is also a multiple of 2N leaves
          ! the domain here
          if( btend ) then
            if( mod(id/lgr_test_vdiff_end,2) == 0 ) iel = -iel
          end if
        end if

!---------------------------------------------------------------
! horizontal diffusion 
!---------------------------------------------------------------

        if( bhdiff ) then
	  if( bresume ) then
	    call lag_diff_hor_resume(i,lb,iel,x,y)
	  else
	    call lag_diff_hor(i,id,time,lb,iel,x,y,bpark)
	    if( bpark ) return		!parked: finished by lgr_mpi_handover
	  end if
	  xx = x
	  yy = y
	  call xy2xi_ierr(abs(iel),xx,yy,xi,ierr)
	  if( ierr /= 0 ) then		!internal error (#294: was a stop)
	    call lgr_event(lgr_ev_xy2xi,id,(/id,iel,ierr/),(/xx,yy/))
	    call lgr_internal_error('error stop diff_body: error of xy2xi')
	    return			!recorded in the loop: left as it is
	  end if
	end if

!---------------------------------------------------------------
! special treatment after diffusion and finish up
!---------------------------------------------------------------

        if( bvdiff .and.  dtime > 0. ) then     !not finished diffusing
          if( bstall ) then		!no time used twice (#261): counted
!$OMP ATOMIC
            lgr_nvdiff_stall = lgr_nvdiff_stall + 1
!$OMP ATOMIC
            lgr_tvdiff_stall = lgr_tvdiff_stall + dtime
          else if( n == 0 ) then	!the cap (#261): counted only
!$OMP ATOMIC
            lgr_nvdiff_cap = lgr_nvdiff_cap + 1
!$OMP ATOMIC
            lgr_tvdiff_cap = lgr_tvdiff_cap + dtime
          else if( iel < 1 ) then	!out of the domain: counted (#288)
            call lgr_event(lgr_ev_vd_lost,i,(/id,iel,n/),(/dble(dtime)/))
          else				!cause unknown: counted (#288)
            call lgr_event(lgr_ev_vd_unknown,i,(/id,iel,n/)		&
     &			,(/dble(dtime)/))
          end if
        end if

        if( .not. bback ) then
          if( iel.gt.0 ) then		!lag_diff_hor may return iel < 0
            if( iarv(iel).eq.artype ) iel = -iel
          end if
        end if

!---------------------------------------------------------------
! end of routine
!---------------------------------------------------------------

        end subroutine diff_body

!**********************************************************************
! Vertical diffusion of body id: one step of the random walk (#286, #287)

	subroutine lgr_diff_vert(id,iel,lmax,hl,hle,lb,z,time,ndraw)

! one call makes one displacement of the particle id over dt =
! min(dtvd(iel),time), with the scheme of Visser (1997, Mar Ecol Prog Ser
! 158, 275-281, doi:10.3354/meps158275), in depth d (down from the
! surface) and with the velocity w of the walk upward:
!   d = d0 - w dt,  w = R sqrt(6 K(zp)/dt) - K',  zp = d0 + K' dt/2
! R uniform in -1 ... 1 (one draw), K' the slope of the diffusivity wde
! in the layer the particle starts in (0 in a layer of zero thickness),
! K(zp) the diffusivity at zp (clamped into the column), interpolated
! linearly between the interfaces of the layer that holds zp
! (lgr_walk_locate). The term -K' of w moves the particle toward higher
! K, the drift a random walk needs where K changes with depth to keep a
! well-mixed state well mixed. The displacement crosses the layer
! interfaces freely; the new depth is reflected at the surface and at
! the bed (folded into 0 ... H modulo 2 H) and its layer lb and relative
! depth z are found again (lgr_walk_fold). time is lowered by dt, so a
! step of the walk takes T/dtvd calls, rounded up. The same walk
! runs in every column, also in one with one layer. The layers hl and
! their interfaces hle(0:lmax) (depths, hle(0) = 0, hle(lmax) = H) are
! those of the element, taken once per particle step by diff_body. A
! layer of zero thickness (a z-level element whose deeper layers hold no
! water) is never divided by and never holds the particle; in a column of
! zero depth the particle stays at z = 0.5 of its bottom layer. The step
! dtvd (lag_vdiff_ele) is the smallest of the model step, the step of the
! curvature condition of Visser (1997) and that of a gradient condition
! of this code (#286), each with its floor.
!
! K is interpolated in the layer, not with exxpp: away from a layer of
! zero thickness the two agree, but on the duplicate interface of such a
! layer exxpp divides 0/0 (intp_neville), and the clamp of zp to H makes
! that exact case common next to a bed with such a layer.
!
! Until #286 a call stopped where the particle reached an interface of
! its layer (a particle in an element with one layer was put at a random
! depth there), with two corrections of the stop (#284: the thickness of
! the layer entered, and the time tv**2/dt counted for a stopped call),
! and used the Milstein scheme (Grawe 2010) with a gaussian draw (about
! 3.5 uniform draws per call). That walk spread the particles more
! slowly than K (#287: K_eff/K 0.14 ... 0.70 in layers 0.5 ... 2 m thick,
! about 0.76 at the levels of mm_hyd_41), and where K changes smoothly
! with depth it did not keep a well-mixed state well mixed (#286: mean
! chi-square of 20 bins of relative depth over the hours 12 ... 24, 19
! +- 6 if well mixed, 3198 for a linear and 148 for a parabolic K; 65 for
! the linear K even with a step of 5 s). Measured on the prototype of
! this walk (97a7ad46 with debug hooks) with the step rule of
! lag_vdiff_ele (gradient factor 0.07, floors 2 s and 0.2 s; the forced
! mm_hyd_41 with the particles not advected, 39960 particles, one day,
! seeds 1, 2, 3; check_lgr_wellmixed.sh): linear K 25.3, 21.8, 21.6,
! parabolic K 20.4, 20.6, 18.6, GOTM's K 18.7, 21.9, 19.5 (the top 5 % of
! the column 1.034 ... 1.052 of uniform with GOTM's K, a small surface
! excess not understood); K_eff/K 1.00 ... 1.02 in layers 0.5 m thick at
! a constant K. The same walk with the Milstein scheme failed the linear
! K with the same step rule (30.7, 33.2, 36.1).
!
! The random draws are the particle's own (#225): lgr_random keyed on id,
! the time step and the site lgr_rnd_vdiff, numbered by ndraw, one per
! call. The guard of the layer (lb > lmax, which no run reaches) goes
! through lgr_internal_error (#256), its values through lgr_event
! (lgr_ev_vd_layer, #288), and returns time = 0 (the caller's loop ends)
! with lb and z unchanged; the run stops after the loop. A negative
! interpolated diffusivity (none: an interpolation between non-negative
! interface values is not negative) is counted in lgr_nvdiff_neg (OMP
! atomic, written at the end of the particle run by lgr_vdiff_stats) and
! taken as 0. The routine runs inside the OpenMP particle loop of drogue:
! it writes nothing and changes no saved variable but that counter. Until
! #288 the guards here wrote their values from inside the loop

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random, lgr_rnd_vdiff

	implicit none

	integer, intent(in)		:: id		!id of particle
	integer, intent(in)     	:: iel		!element
	integer, intent(in)		:: lmax		!layers of the element
	real, intent(in)		:: hl(lmax)	!layer thickness
	real, intent(in)		:: hle(0:lmax)	!depth of the interfaces
	integer, intent(inout)		:: lb		!layer
	double precision, intent(inout) :: z	!rel vert pos: 0=top, 1=bottom
	real, intent(inout)		:: time	!time left to diffuse
	integer, intent(inout)		:: ndraw !draws of the particle's
						 !vertical diffusion in the step

	real				:: dt	!time of the call
	real				:: rnd	!uniform draw in -1 ... 1
	double precision		:: dk	!slope K' of the diffusivity in lb
	double precision		:: zp	!depth where K is taken
	double precision		:: zl	!relative depth of zp in layer l
	double precision		:: ak	!diffusivity at zp
	double precision		:: w	!velocity of the walk (upward)
	double precision		:: d	!depth after the displacement
	integer				:: l	!layer of zp

	if( lb > lmax ) then
	  call lgr_event(lgr_ev_vd_layer,id,(/id,iel,lb,lmax/))
	  call lgr_internal_error(					&
     &		'error stop lgr_diff_vert: no such layer')
	  time = 0.			!recorded in the loop (#256)
	  return
	end if

	!-----------------------------------------------
	! slope of the diffusivity in the layer and time of the call
	!-----------------------------------------------

	dk = 0.d0
	if( hl(lb) > 0. ) then
	  dk = (wde(lb,iel)-wde(lb-1,iel)) / dble(hl(lb))
	end if
	dt = min(dtvd(iel),time)

	!-----------------------------------------------
	! diffusivity at zp = d0 + K' dt/2, linear in the layer of zp
	!-----------------------------------------------

	zp = hle(lb-1) + z*hl(lb) + 0.5d0*dk*dt
	zp = min(max(zp,0.d0),dble(hle(lmax)))
	call lgr_walk_locate(lmax,hl,hle,zp,l,zl)
	ak = wde(l-1,iel) + zl*(wde(l,iel)-wde(l-1,iel))
	if( ak < 0.d0 ) then
!$OMP ATOMIC
	  lgr_nvdiff_neg = lgr_nvdiff_neg + 1
	  ak = 0.d0
	end if

	!-----------------------------------------------
	! displacement, reflected at the surface and at the bed
	!-----------------------------------------------

	rnd = 2.*lgr_random(id,lgr_rnd_vdiff,ndraw) - 1.
	ndraw = ndraw + 1
	w = rnd*sqrt(6.d0*ak/dt) - dk		!upward
	d = hle(lb-1) + z*hl(lb) - w*dt		!depth, downward
	call lgr_walk_fold(lmax,hl,hle,d,lb,z)

	time = time - dt

	end subroutine lgr_diff_vert

!******************************************************************

	subroutine lgr_walk_locate(lmax,hl,hle,d,lb,z)

! the layer lb and the relative depth z (0 at its top, 1 at its bottom)
! of the depth d (0 <= d <= hle(lmax)) in a column of lmax layers of
! thickness hl(l) and interfaces hle(0:lmax) (depths from the surface,
! hle(0) = 0), for the vertical random walk (lgr_diff_vert, #286, #287):
! lb is the first layer of non-zero thickness whose bottom is at or below
! d (lmax if every layer has zero thickness), z = (d - hle(lb-1))/hl(lb)
! within 0 ... 1, or 0.5 if hl(lb) is zero. A depth on an interface
! belongs to the layer above it, so a layer of zero thickness never gets
! the particle and nothing divides by a zero thickness. Self-contained
! (no module), so that check_lgr_fixes.sh walk-fold can compile and test
! it on its own.

	implicit none

	integer, intent(in)		:: lmax		!layers of the column
	real, intent(in)		:: hl(lmax)	!layer thickness
	real, intent(in)		:: hle(0:lmax)	!depth of the interfaces
	double precision, intent(in)	:: d		!depth, 0 ... hle(lmax)
	integer, intent(out)		:: lb		!layer of d
	double precision, intent(out)	:: z		!relative depth in lb

	integer l

	lb = lmax
	do l = 1,lmax
	  if( d <= hle(l) ) then
	    if( hl(l) > 0. ) then
	      lb = l
	      exit
	    end if
	  end if
	end do

	if( hl(lb) > 0. ) then
	  z = (d - hle(lb-1)) / hl(lb)
	  z = min(max(z,0.d0),1.d0)
	else
	  z = 0.5d0
	end if

	end subroutine lgr_walk_locate

!******************************************************************

	subroutine lgr_walk_fold(lmax,hl,hle,d,lb,z)

! the depth d of any value reflected at the surface (0) and at the bed
! (H = hle(lmax)): folded into 0 ... H modulo 2 H (0 in a column of zero
! depth), then located by lgr_walk_locate (layer lb, relative depth z),
! for the vertical random walk (lgr_diff_vert, #286, #287): a
! displacement that leaves the column through the surface or the bed
! comes back as reflected, however far it went. Self-contained (no
! module), so that check_lgr_fixes.sh walk-fold can compile and test it
! on its own.

	implicit none

	integer, intent(in)		:: lmax		!layers of the column
	real, intent(in)		:: hl(lmax)	!layer thickness
	real, intent(in)		:: hle(0:lmax)	!depth of the interfaces
	double precision, intent(in)	:: d		!depth, any value
	integer, intent(out)		:: lb		!layer of the folded d
	double precision, intent(out)	:: z		!relative depth in lb

	double precision :: h,p,dd

	h = hle(lmax)
	if( h > 0.d0 ) then
	  p = 2.d0*h
	  dd = modulo(d,p)
	  if( dd > h ) dd = p - dd
	else
	  dd = 0.d0
	end if
	call lgr_walk_locate(lmax,hl,hle,dd,lb,z)

	end subroutine lgr_walk_fold

!******************************************************************

        subroutine lgr_vdiff_stats

! writes once, at the end of the particle run, how often lgr_diff_vert
! set a negative interpolated vertical diffusivity to 0 (#231), and the
! random walk time step over the elements and steps of the run (#257):
! the smallest dtvd, the mean of the step a particle uses (dtvd, at most
! the model step), the mean number of sub-steps per model step, and the
! number of element steps with dtvd below the model step (until #261 also
! the element steps over 100 sub-steps, the cap of the calls of a
! particle step then; the cap is now on the next lines); and the vertical
! walk of the particle steps (#261, diff_body): their number, the calls of
! lgr_diff_vert, the most calls and the most random draws in one particle
! step (the draws of a step are numbered in a block of 2**24 of
! lgr_random: one uniform draw per call since #286, so at most
! lgr_nvdiff_max; until #286 also 2 per trial of rgauss, 4/pi trials on
! average, about 3.55 per call), the step rule's gradient term (#286),
! the particle steps stopped at the cap and those ended by two calls in a
! row that left the single-precision time unchanged, each with the time
! not diffused, and all calls that left it unchanged; only in
! a run with vertical diffusion (ilagr = 3, a serial run: ilagr = 3 stops
! on several processes). Called by lagrange outside any parallel region:
! after the step that reaches dtlend and at the first call after it (when
! no step ends exactly at dtlend); bdone keeps the second call silent

        use mod_lagrange

        implicit none

        logical, save :: bdone = .false.

        if( bdone .or. .not. bvdiff ) return
        bdone = .true.
        write(6,'(a,i0)') ' lgr vertical diffusion: negative'		&
     &		//' diffusivities set to 0: ',lgr_nvdiff_neg
	! the random walk time step of lag_vdiff_ele (#257)
	if( lgr_dtvd_n > 0 ) then
          write(6,'(a,g0.6,a,g0.6,a,f0.3,a,i0,a,i0)')			&
     &		' lgr vertical diffusion: random walk time step [s]'	&
     &		//' min ',lgr_dtvd_min					&
     &		,' mean ',lgr_dtvd_sum/lgr_dtvd_n			&
     &		,', sub-steps per step ',dble(lgr_dtvd_nstep)/lgr_dtvd_n	&
     &		,', element steps ',lgr_dtvd_n				&
     &		,' below the model step ',lgr_dtvd_nsub
	  write(6,'(a,i0,a,f3.1,a,i0)')					&
     &		' lgr vertical diffusion step rule: the gradient term'	&
     &		//' set the step in ',lgr_dtvd_ngrad			&
     &		,' element steps, its floor ',lgr_vdiff_dtming		&
     &		,' s in ',lgr_dtvd_nfloor
	end if
	! the vertical walk of the particle steps (#261)
	write(6,'(a,i0,a,i0,a,i0,a,i0)') ' lgr vertical diffusion:'	&
     &		//' particle steps: ',lgr_nvdiff_steps			&
     &		,', calls: ',lgr_nvdiff_calls				&
     &		,', most calls in a step: ',lgr_nvdiff_mcall		&
     &		,', most draws in a step: ',lgr_nvdiff_mdraw
	write(6,'(a,i0,a,i0,a,g0.6,a,i0,a,g0.6,a,i0)')			&
     &		' lgr vertical diffusion:'				&
     &		//' steps stopped at the cap of ',lgr_nvdiff_max		&
     &		,' calls: ',lgr_nvdiff_cap				&
     &		,', time not diffused [s]: ',lgr_tvdiff_cap		&
     &		,'; steps ended by 2 calls in a row that used no time: '	&
     &		,lgr_nvdiff_stall					&
     &		,', time not diffused [s]: ',lgr_tvdiff_stall		&
     &		,'; calls that used no time: ',lgr_nvdiff_zero

        end subroutine lgr_vdiff_stats

!******************************************************************
! Compute vertical diffusivity in element and random walk time step

        subroutine lag_vdiff_ele

        use basin
        use mod_lagrange
        use mod_diff_visc_fric, only : difv
        use levels
        use mod_lagrange_mpi, only : lgr_test_kprof

	implicit none

        integer                 :: ie,ii,k,l
	real			:: time		!simulation time step
        real                    :: hl(nlv)      !layer thickness
        real                    :: hle(0:nlv)   !layer structures
        real                    :: htot         !total depth without zeta
        real                    :: htotz        !total depth with zeta 
        real                    :: wdl
	real			:: s		!relative depth (test hook)
        double precision        :: dwd2(nlv)    !second derivative of diffusivity 
        real                    :: dmax
	logical			:: bzero	!a layer of zero thickness
	real			:: dtd		!random walk time step
	real			:: dtg		!step of the gradient term
	real			:: dtn		!step with the gradient term
        integer 		:: lmax 	!maximum layers in element
	real, parameter 	:: dtmin = 2.0	!minimum time step
	real, parameter 	:: difmol = 1.0e-06

	call get_timestep(time)

        do ie = 1,nel

	  !-----------------------------------------------
	  ! get layer structures and depths
	  !-----------------------------------------------
          lmax = nlv
          call lagr_layer_thickness(ie,lmax,hl,htot,htotz)
  
  	  hle(0) = 0.
  	  do l = 1,lmax
	    hle(l) = hle(l-1) + hl(l)
	  end do

	  !-----------------------------------------------
	  ! get diffusivity on elements
	  !-----------------------------------------------
	  do l = 0,lmax
	    wdl = difmol
            do ii=1,3
              k = nen3v(ii,ie)
              wdl = wdl + difv(l,k)
	    end do
            wde(l,ie) = wdl / 3.
          end do

	  !-----------------------------------------------
	  ! test hook LGR_TEST_KPROF (lgr_mpi_init, check_lgr_wellmixed.sh,
	  ! #286, #287): a fixed profile of the relative depth s of the
	  ! interfaces replaces the diffusivity, before the time step of the
	  ! walk is taken from it; a column of depth 0 keeps its diffusivity
	  !-----------------------------------------------
	  if( lgr_test_kprof > 0 ) then
	    if( hle(lmax) > 0. ) then
	      do l = 0,lmax
	        s = hle(l)/hle(lmax)
	        select case( lgr_test_kprof )
	        case( 1 )			!linear
	          wde(l,ie) = 1.e-3 + 2.e-2*s
	        case( 2 )			!parabolic
	          wde(l,ie) = 1.e-3 + 8.e-2*s*(1.-s)
	        case default			!3: constant
	          wde(l,ie) = 1.e-2
	        end select
	      end do
	    end if
	  end if

	!write(6,*) 'diffus gggguu'
	!write(6,*) ie,lmax
	!write(6,*) 'wde ',wde(0:lmax,ie)
	  !-----------------------------------------------
	  ! Compute random walk time step 1/(100*dwd2)
	  !
	  ! dwd2(l) is the second derivative K'' of the diffusivity K at the
	  ! interface l (lgr_vdiff_curvature, #257). Visser (1997, Mar Ecol
	  ! Prog Ser 158, 275-281, doi:10.3354/meps158275) requires the time
	  ! step of the random walk to be much smaller than min 1/|K''| over
	  ! the water column; this code takes 1/100 of that, 1/(100 max|K''|),
	  ! at least dtmin (and at most the model step where it is used,
	  ! lgr_diff_vert). An element with a layer of zero thickness gets
	  ! dtmin: K'' cannot be computed there (and across a jump of K over no
	  ! distance it is unbounded), so the smallest step is taken. Until #257
	  ! the "second derivative" was (K(l+1) + 2 K(l) + K(l-1))/hl(l)**2,
	  ! about 4 K/h**2, a sum of positive values instead of a curvature, so
	  ! the step was about h**2/(400 K) even where K is constant or linear
	  ! (mm_hyd_41 with ilagr = 3, one day: a mean step of 24.9 s and 98.4
	  ! sub-steps per 300 s step before, 33.5 s and 41.7 after).
	  !-----------------------------------------------
	  dtd = time
	  if ( lmax > 1 ) then
	    call lgr_vdiff_curvature(lmax,hl,wde(0:lmax,ie),dwd2,bzero)
	    if( bzero ) then
	      dtd = dtmin		!a layer of zero thickness
	    else
   	      dmax = maxval(abs(dwd2(1:lmax)))
  	      if ( dmax /= 0. ) dtd = 1./(100.*dmax)
              dtd = max(dtmin, dtd)
	    end if
	  end if

	  !-----------------------------------------------
	  ! gradient term (#286): the drift K' dt of the walk must stay small
	  ! against the scale K/K' of K, dt <= lgr_vdiff_facg Kmin/K'**2 over
	  ! the layers (lgr_vdiff_gradstep), at least lgr_vdiff_dtming. Also for
	  ! lmax = 1 and for a column with a layer of zero thickness (skipped)
	  !-----------------------------------------------
	  dtg = time
	  call lgr_vdiff_gradstep(lmax,hl,wde(0:lmax,ie),lgr_vdiff_facg,dtg)
	  if( dtg < dtd ) then
	    dtn = min(dtd,max(lgr_vdiff_dtming,dtg))
	    if( dtn < dtd ) then		!the gradient term lowered it
	      lgr_dtvd_ngrad = lgr_dtvd_ngrad + 1
	      if( dtn == lgr_vdiff_dtming ) lgr_dtvd_nfloor = lgr_dtvd_nfloor + 1
	    end if
	    dtd = dtn
	  end if
	  dtvd(ie) = dtd

	  ! statistics (#257): the step a particle uses, min(dtvd,time), and
	  ! the sub-steps lgr_diff_vert makes with it in a model step
	  lgr_dtvd_min = min(lgr_dtvd_min,dtd)
	  lgr_dtvd_sum = lgr_dtvd_sum + min(dtd,time)
	  lgr_dtvd_nstep = lgr_dtvd_nstep + ceiling(time/min(dtd,time))
	  lgr_dtvd_n = lgr_dtvd_n + 1
	  if( dtd < time ) lgr_dtvd_nsub = lgr_dtvd_nsub + 1
	end do

	end subroutine lag_vdiff_ele

!******************************************************************

	subroutine lgr_vdiff_curvature(lmax,hl,wd,dwd2,bzero)

! second derivative K'' of the diffusivity wd(0:lmax) of a column at its
! interfaces 1 ... lmax (#257), for the time step of the vertical random
! walk (lag_vdiff_ele). Interface l lies between the layers l and l+1, so
! the interfaces l-1, l, l+1 are spaced hl(l) and hl(l+1); for l = 1 ...
! lmax-1 the second difference over these unequal spacings
!   2/(hl(l)+hl(l+1)) * ( (K(l+1)-K(l))/hl(l+1) - (K(l)-K(l-1))/hl(l) )
! exact for a quadratic K ((K(l+1) - 2 K(l) + K(l-1))/h**2 for equal
! layers); at the bottom interface lmax the value is extrapolated linearly
! from the two interfaces above (the value at lmax-1 if lmax = 2). If a
! layer used has zero (or negative) thickness bzero is true and dwd2 is
! left at 0 (the caller then takes its smallest step): no division by a
! zero thickness. Needs lmax >= 2. Self-contained (no module), so that
! check_lgr_fixes.sh vdiff-dt can compile and test it on its own.

	implicit none

	integer, intent(in)		:: lmax		!layers of the column
	real, intent(in)		:: hl(lmax)	!layer thickness
	real, intent(in)		:: wd(0:lmax)	!diffusivity at interfaces
	double precision, intent(out)	:: dwd2(lmax)	!second derivative
	logical, intent(out)		:: bzero	!a layer of zero thickness

	integer l

	dwd2 = 0.d0
	bzero = .false.

	do l = 1,lmax
	  if( hl(l) <= 0. ) bzero = .true.
	end do
	if( bzero ) return

	do l = 1,lmax-1
	  dwd2(l) = 2.d0/(hl(l)+hl(l+1)) *				&
     &		( (wd(l+1)-wd(l))/hl(l+1) - (wd(l)-wd(l-1))/hl(l) )
	end do
	dwd2(lmax) = dwd2(lmax-1)
	if ( lmax > 2 ) dwd2(lmax) = dwd2(lmax-1) +			&
     &		(dwd2(lmax-1)-dwd2(lmax-2))/hl(lmax-1)*hl(lmax)

	end subroutine lgr_vdiff_curvature

!******************************************************************

	subroutine lgr_vdiff_gradstep(lmax,hl,wd,facg,dtg)

! gradient term of the time step of the vertical random walk (#286): per
! layer l with hl(l) > 0, K' = (K(l)-K(l-1))/hl(l) is the slope of the
! diffusivity wd(0:lmax) in the layer, and the drift K' dt of the walk must
! stay small against the scale K/K' of K, dt <= facg Kmin/K'**2 with Kmin
! the smaller interface value (at least 1e-6). dtg is lowered to the
! smallest of these; a layer of zero thickness is skipped (no division),
! and a layer with K' = 0 sets no limit. Self-contained (no module), so
! that check_lgr_fixes.sh vdiff-dt can compile and test it on its own.

	implicit none

	integer, intent(in)	:: lmax		!layers of the column
	real, intent(in)	:: hl(lmax)	!layer thickness
	real, intent(in)	:: wd(0:lmax)	!diffusivity at interfaces
	real, intent(in)	:: facg		!factor of the step
	real, intent(inout)	:: dtg		!time step, lowered

	integer l
	double precision :: dk,kmin,dtl

	do l = 1,lmax
	  if( hl(l) > 0. ) then
	    dk = (dble(wd(l))-dble(wd(l-1)))/hl(l)
	    kmin = max(1.d-6,dble(min(wd(l-1),wd(l))))
	    if( dk /= 0.d0 ) then
	      dtl = facg*kmin/(dk*dk)
	      if( dtl < dtg ) dtg = real(dtl)
	    end if
	  end if
	end do

	end subroutine lgr_vdiff_gradstep

!******************************************************************
! Horizontal diffusion of body id

        subroutine lag_diff_hor(i,id,time,lb,iel,x,y,bpark)

! the horizontal diffusion step: random displacement, element search of
! the new point, and lag_diff_hor_end. On several processes the search
! is lgr_mpi_locate, which can park the particle (bpark true: both points
! are stored in its slot, x, y and iel are unchanged, the caller stops);
! a serial run searches with find_elem_from_old as always (at levdbg >= 3
! lgr_mpi_relocate_check checks the result, changing nothing)

	use mod_lagrange
	use mod_lagrange_mpi, only : bmpi_lagr, blgr_dbg
	use mod_lagrange_mpi, only : lgr_mpi_locate, lgr_mpi_relocate_check
        use mod_diff_visc_fric, only : difhv

        implicit none
        
        integer, intent(in)             :: i    !particle number (slot)
        integer, intent(in)             :: id   !id of particle
        real, intent(in)		:: time !time to diffuse
	integer, intent(in)		:: lb	!level
        integer, intent(inout)          :: iel  !element
        real, intent(inout)		:: x    !x-coordinate
        real, intent(inout)		:: y    !y-coordinate
        logical, intent(out)		:: bpark !parked (several processes)

        real 				:: k     !diffusion coefficient 
        real				:: dx,dy !random displacement
	real				:: xnew,ynew
        integer				:: ieold,ienew
        double precision 		:: ddx,ddy,xc,yc
        double precision 		:: dlat0,dlon0  !center of projection
        logical				:: lgr_internal_failed

	! the type of coordinates, blgr_sphe, is set once by lagr_init_common
	! before the first particle loop: this routine runs inside the OpenMP
	! loop of drogue and writes no saved variable (#243)

	bpark = .false.

        if( iel <= 0 ) return     !particle out of domain

        !-----------------------------------------------
        ! Type of horizontal diffusion
        ! Mode: 1 Parameter rwhpar
        !       2 Function of type of diffusion (idhtyp)
        !-----------------------------------------------

	if ( rwhpar >= 0. ) then
            k = rwhpar  
	else
            k = -rwhpar*difhv(lb,iel)
        end if

        !-----------------------------------------------
        ! Initialize values
        !-----------------------------------------------
	dx = 0.
	dy = 0.
        ieold = iel

	ienew = 0

        !-----------------------------------------------
        ! Compute horizontal diffusion
        !-----------------------------------------------
	call lag_get_dxdy(id,time,k,dx,dy)
        xnew = x + dx
        ynew = y + dy

        if ( blgr_sphe ) then
           ddx = dx
	   ddy = dy
           dlon0 = x
           dlat0 = y
	   call ev_c2g(ddx,ddy,xc,yc,dlon0,dlat0)
           xnew = xc
           ynew = yc
	end if

	if( bmpi_lagr ) then
	  call lgr_mpi_locate(i,1,ieold,x,y,xnew,ynew,ienew,bpark)
	  if( bpark ) return	!parked: resumed by lag_diff_hor_resume
	  if( lgr_internal_failed() ) return	!the run stops after the loop
	else
          call find_elem_from_old(ieold,xnew,ynew,ienew)
	  if( blgr_dbg ) call lgr_mpi_relocate_check(ieold,xnew,ynew,ienew)
	end if

	call lag_diff_hor_end(ieold,lb,ienew,x,y,xnew,ynew,iel)

        end subroutine lag_diff_hor

!******************************************************************

        subroutine lag_diff_hor_end(ieold,lb,ienew,x,y,xnew,ynew,iel)

! the end of the horizontal diffusion step after the element search of
! the new point (xnew,ynew): ienew is the element found, 0 if none (then
! the fallback particle_on_side runs on the old element ieold); the
! particle takes the new point and element only if that element has its
! layer lb, otherwise it keeps x, y and iel. Called by lag_diff_hor and,
! for a parked particle, by lag_diff_hor_resume (several processes)

        implicit none

        integer, intent(in)		:: ieold     !element before the step
	integer, intent(in)		:: lb        !level
        integer, intent(inout)          :: ienew     !element found, 0 none
        real, intent(inout)		:: x,y       !old point (new on return)
        real, intent(inout)		:: xnew,ynew !new point
        integer, intent(inout)          :: iel       !element (new on return)

        logical				:: track_xi_has_layer

	if (ienew == 0 ) then
	   ienew = ieold
	   call particle_on_side(ienew,x,y,xnew,ynew)
	end if

        !-----------------------------------------------
        ! Return new coordinates and element
        !-----------------------------------------------
        if( track_xi_has_layer(abs(ienew),lb) ) then
          x   = xnew
          y   = ynew
          iel = ienew
	end if

        end subroutine lag_diff_hor_end

!******************************************************************

        subroutine lag_diff_hor_resume(i,lb,iel,x,y)

! the horizontal diffusion step of particle i, parked in its element
! search (lgr_mpi_locate) and resolved by position (lgr_mpi_resolve):
! continues after the search with the outcome in lgr_park_ie(i) and the
! new point in lgr_park_xy(3:4,i); x, y are the old point (lgr_park_xy
! (1:2,i), as the step had it) and iel the element it was parked in:
!  > 0  the element found (a local element) has the particle's layer
!       (tested by the asking process with the layer count of the
!       answer): the particle takes the new point and element, the
!       assignment of lag_diff_hor_end
!   0   no element of the mesh contains the new point: lag_diff_hor_end
!       with no element found (fallback on iel, then the layer test)
!  -1   the element found lacks the layer: x, y and iel stay, the branch
!       of lag_diff_hor_end that keeps them
! nothing is drawn again: the displacement is in the stored new point

	use mod_lagrange

        implicit none

        integer, intent(in)             :: i    !particle number (slot)
	integer, intent(in)		:: lb	!level
        integer, intent(inout)          :: iel  !element
        real, intent(inout)		:: x    !x-coordinate
        real, intent(inout)		:: y    !y-coordinate

	real				:: xnew,ynew
        integer				:: ieold,ienew

	xnew = lgr_park_xy(3,i)
	ynew = lgr_park_xy(4,i)
	ienew = lgr_park_ie(i)
	ieold = iel

	if( ienew > 0 ) then		!found, has the layer
          x   = xnew
          y   = ynew
          iel = ienew
	else if( ienew == 0 ) then	!no element: fallback, layer test
	  call lag_diff_hor_end(ieold,lb,ienew,x,y,xnew,ynew,iel)
	end if				!-1: lacks the layer, keeps x, y, iel

        end subroutine lag_diff_hor_resume

!******************************************************************
! Randow walk with rnd having uniform distribution between -1 and 1
!
! the two draws are the particle's own (#225): lgr_random keyed on id, the
! time step and the site lgr_rnd_hdiff, n = 0 for x and 1 for y; on
! several processes the particle makes them on the process where its
! advection ends, and a parked particle does not draw again when it
! resumes (lag_diff_hor_resume), so they are the serial draws

        subroutine lag_get_dxdy(id,time,k,dx,dy)

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random, lgr_rnd_hdiff

        implicit none
        
        integer, intent(in)		:: id   !id of particle
        real, intent(in)		:: time !time to diffuse
        real, intent(in)		:: k    !diffusion coefficient
        real, intent(out)		:: dx   !x-displacemnet
        real, intent(out)		:: dy   !y-displacement

	real				:: rnd,cf

        cf = sqrt(6.*k*time)

        rnd = lgr_random(id,lgr_rnd_hdiff,0)
        rnd = (rnd-0.5)/0.5
        dx = cf*rnd

        rnd = lgr_random(id,lgr_rnd_hdiff,1)
        rnd = (rnd-0.5)/0.5
        dy = cf*rnd

	end subroutine lag_get_dxdy

!*****************************************************************
!******************************************************************
!	OLD ROUTINES
!******************************************************************
!******************************************************************

        subroutine lag_diff(ie,bdy,x,y)

	use mod_lagrange
	use femtime

        implicit none
        
        
        real k ! coefficiente di diffusione        
        
        integer ie,nlp ! numero elemento in cui si trova il body
        real*8 dx,dy ! spostamento random
        real x,y ! posizione body
        integer bdy ! numero body
      
        real cy,cx,b ! coefficienti traiettoria  
       
	real dt,ttime
        real xold,yold,xnew,ynew,lt_ex
        integer ieold,ienew
	integer icount

        k=rwhpar  

	dx= 0
	dy= 0

	if( ie .le. 0 ) stop 'error stop lag_diff: internal error'

        xold=x
        yold=y
        ieold=ie
        call get_timestep(dt)
        ttime=dt

	ienew = 0
	icount = 20
	do while ( ienew .eq. 0 )

          call lag_rand(k,ttime,dx,dy) !calcolo spostamento 
          xnew=xold+dx
          ynew=yold+dy
          call find_elem_from_old(ieold,xnew,ynew,ienew)
	  icount = icount - 1
	  !if( icount .eq. 0 ) ienew = -ieold
	  if( icount .eq. 0 ) return	!return without diffusion

	end do

        x=xnew
        y=ynew
        ie=ienew
	 
        end 
!*******************************************************************
       
        subroutine lag_rand(k,ttime,dx,dy)

        implicit none

        real ttime
        real k
        real*8 dx,dy
        real a,b,cf
        real nmb 
        real shygasdev
        integer, save :: idum = 387
        cf=sqrt(2*k*ttime) 
	cf=sqrt(6*k*ttime)  !new formula 3d
        
        dx=cf*shygasdev(idum)
        dy=cf*shygasdev(idum)

        end

!*********************************************************************

        FUNCTION shygasdev(idum)

! Returns a normally distributed deviate with zero mean and unit variance
! using shyran1(idum) as the source of uniform deviates.

        implicit none

        INTEGER idum
        REAL shygasdev
        INTEGER, save :: iset = 0
        REAL fac,rsq,v1,v2,shyran1
        REAL, save :: gset

        if (idum.lt.0) iset=0
        if (iset.eq.0) then
         do
           v1=2.*shyran1(idum)-1.
           v2=2.*shyran1(idum)-1.
           rsq=v1**2+v2**2
           if(rsq.lt.1..and.rsq.ne.0.) exit
         end do
         fac=sqrt(-2.*log(rsq)/rsq)
         gset=v1*fac
         shygasdev=v2*fac
         iset=1
        else
         shygasdev=gset
         iset=0
        endif
        return
        END

!**************************************************************************
