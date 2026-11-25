
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
! the vertical walk makes at most lgr_nvdiff_max calls of lgr_diff_vert
! in a step (#261). A call ends at dtvd or where the particle reaches an
! interface of its layer, so the calls of a step grow with the
! diffusivity, not only with T/dtvd (at most 150 at T = 300 s: dtvd >= 2
! s): in mm_hyd_41 with ilagr = 3 (one day, GOTM gives up to 49 m2/s) a
! step needs up to about 19000 calls (481 before #284, which counts less
! time for a call that stops at an interface), and one step of 777212
! reaches the cap (142 s of 300 s not diffused). A step that reaches the
! cap stops there. The time of a call that stops at an interface can fall
! below the resolution of the single-precision time left, which then does
! not change: such a call is counted and the walk goes on (it moved the
! particle onto the interface, and the next call has the whole next layer
! before it), but a second such call in a row ends the step (a thin layer
! crossed in less than that resolution) instead of letting it burn the
! cap. The steps stopped at the cap and those ended so are counted with
! the time not diffused (OMP atomic, as the calls and draws of every step)
! and written once at the end by lgr_vdiff_stats; nothing is written in
! the loop. Until #261 the cap was 100 calls, and every step that reached
! it wrote a line from inside the particle loop (59859 lines, 7.7 % of
! the particle steps of that case, 87 s of 300 s not diffused on average)

        use mod_lagrange
        use mod_lagrange_mpi, only : lgr_test_vdiff_end
        use basin

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

	integer			:: mode 	!type of diffusion scheme
	real 			:: dtime
	real 			:: dtold	!time left before the call
        integer 		:: n		!calls left (#261)
        integer 		:: ncall	!calls made in the step
        integer 		:: nzero	!calls that used no time
        integer 		:: nzrow	!of those, the last ones in a row
        double precision 	:: xx,yy,zz
        logical			:: bstall	!ended by two such calls in a row
        logical			:: btend	!walk ended by the test hook

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
	  mode = 3
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
            call lgr_diff_vert(mode,id,iel,lb,zz,dtime,ndraw)
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
	  call xy2xi(abs(iel),xx,yy,xi)
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
! Vertical diffusion of body id
! Get vertical diffusion velocity
! Mode: 1 naive random walk
!       2 diffusive random walk (Visser 1997)
!       3 Milstein scheme (Grawe 2010)

	subroutine lgr_diff_vert(mode,id,iel,lb,z,time,ndraw)

! the random draws are the particle's own (#225): lgr_random keyed on id,
! the time step and the site lgr_rnd_vdiff, numbered by ndraw
!
! an internal-error guard recorded inside the particle loop (#256:
! lgr_internal_error here or in diff_get_vert) returns time = 0 (the
! caller's loop ends) with defined values; the run stops after the loop.
! The values of the guard here (z outside 0..1) and in diff_get_vert (no
! such layer) go to lgr_event (lgr_ev_vd_depth, lgr_ev_vd_layer), which
! writes them at once where lgr_internal_error aborts at once (outside an
! active parallel region) and keeps them for lgr_events otherwise; until
! #288 they were written from inside the loop. The
! debug lines (bdebug) are off at compile time: until #288 bdebug was
! true for a particle with id 0, which no release gives (ids start at
! 1), and it was set through the module variable blgrdebug, written by
! every thread of the loop
!
! a call moves the particle with the velocity w of diff_get_vert for dt =
! min(dtvd,time), or until it reaches an interface of its layer (or the
! surface or bottom) after the time tv < dt, where it stops. Two
! corrections keep the walk well mixed (#284):
! - a particle that starts on an interface and moves into the next layer
!   moves with the thickness of the layer it enters (hda, hdb of
!   diff_get_vert); it used that of the layer it left (hd), so in Mar
!   Menor, where the layers thicken downward, particles drifted down;
! - a call that stops at an interface after the time tv has moved w tv,
!   with the variance 2 K tv**2/dt (w has the variance 2 K/dt), which a
!   Brownian path with the diffusivity K would reach in the time
!   tv**2/dt: that is the time it now counts (it counted tv, the time in
!   which such a path reaches 2 K tv). This keeps a uniform distribution
!   uniform, but it is not an exact time: the walk still spreads the
!   particles more slowly than K (the variance of their hourly
!   displacement far from the surface and bottom is about 0.75 of 2 K T
!   in the case below, before and after #284; issue #287).
!   Alone, the first defect drove particles down and the second up, so
!   the second partly masked the first.
! Mar Menor, mm_hyd_41 without tilt in still water, K = diftur = 1e-2
! m2/s over the whole column, 39960 particles released uniformly over the
! depth, one day (check_lgr_wellmixed.sh): mean chi-square of 20 bins of
! relative depth over hours 12 to 24 (19 +- 6 if well mixed) 331 and 313
! before (lgrseed 1, 2; 11 % too few particles in the upper 15 % of the
! column, 10 % too many in the lower 15 %), with the thickness alone 54
! and 56, with the time alone 606 and 563, with both 20 and 19. Not well
! mixed yet where K changes smoothly over the depth (#286)

	use mod_lagrange
	use mod_lagrange_random, only : lgr_random, lgr_rnd_vdiff

	implicit none

	integer, intent(in)		:: mode !type of diffusion scheme
	integer, intent(in)		:: id	!id of particle
	integer, intent(in)     	:: iel	!element
	integer, intent(inout)		:: lb	!level
	double precision, intent(inout) :: z	!rel vert pos: 0=top, 1=bottom
	real, intent(inout)		:: time	!travel time of particle
	integer, intent(inout)		:: ndraw !draws of the particle's
						 !vertical diffusion in the step

	real              		:: dt	!random walk time step
	double precision 		:: w	!vertical velocity
        double precision                :: wd   !vertical velocity from diffusivity
        double precision                :: hd   !layer thickness
        double precision                :: hda  !thickness of layer above
        double precision                :: hdb  !thickness of layer below
	double precision 		:: dz	!vertical displacement
	double precision 		:: dv	!potential vertical dispacement
	double precision 		:: t,tv,tt
	real				:: rr
	logical, parameter 		:: bdebug = .false. !debug lines (#288)
	logical 			:: bsurf,bbott
	integer 			:: lmax
	integer 			:: lborig
	logical				:: lgr_internal_failed

	lborig = lb
	dz = 0.d0			!defined for the guard below

        call diff_get_vert(mode,id,iel,lb,z,time,dt,lmax,hd,hda,hdb	&
     &				,wd,ndraw)
	if( lgr_internal_failed() ) then	!recorded in the loop (#256)
	  time = 0.
	  return
	end if
	w = wd					!vertical velocity due to diffusion

	!-----------------------------------------------
	! handle particles on surface or on bottom
	!-----------------------------------------------

	bsurf = lb == 1 .and. z == 0.d0		!particle on surface
	bbott = lb == lmax .and. z == 1.d0	!particle on bottom

        if( bsurf .and. w > 0.d0 ) w = -w       !reflection at surface
        if( bbott .and. w < 0.d0 ) w = -w       !reflection at bottom

	if ( w > 0.d0 .and. z == 0.d0 ) then
	  lb = lb - 1
	  z  = 1.d0
	  hd = hda		!the thickness of the layer entered (#284)
	end if
	if ( w < 0.d0 .and. z == 1.d0 ) then
	  lb = lb + 1
	  z  = 0.d0
	  hd = hdb		!the thickness of the layer entered (#284)
	end if

	!-----------------------------------------------
	! determine time to leave layer (tv)
	!-----------------------------------------------

	tv = 2.*dt

	if( w /= 0. ) then
	  if( w > 0. ) then
	    dv = hd*z
	    tv = dv / w
	  else
	    dv = hd*(1.-z)
	    tv = dv / (-w)
	  end if
	else
	  dv = 0.
	end if

	!-----------------------------------------------
	! what happens first? (tt is total time available)
	!-----------------------------------------------

	tt = time
	t = dt
	if( tv > 0. ) t = min(t,tv)

	if( bdebug ) then
	  write(6,*) 'times for diffusion'
	  write(6,*) tv,tt
	end if

	!-----------------------------------------------
	! handle vertical diffusion
	!-----------------------------------------------

	if( tv == 0. ) then		!body not moving
	  !
	else if( tv > t ) then		!body remains in layer
	  dz = w*t/hd
	  z = z - dz
	else
	  if ( lmax == 1 ) then		!in case of 1 layer z = random(0,1)
            rr = lgr_random(id,lgr_rnd_vdiff,ndraw)
	    ndraw = ndraw + 1
	    z = rr
	    t = tt
	  else
	    t = tv*tv/dt	!stopped at tv: the time of its variance (#284)
 	    if( w > 0. ) then
	      if( lb > 1 ) then
	        lb = lb - 1
	        z = 1.
	      else
	        z = 0.
	      end if
	    else
	      if( lb < lmax ) then
	        lb = lb + 1
	        z = 0.
	      else
	        z = 1.
	      end if
	    end if
	  end if
	end if

	if( bdebug ) then
	  write(6,*) 'after vertical diffusion'
	  write(6,*) iel
	  write(6,*) lborig,lb,lmax
	  write(6,*) w,z
	end if

	!-----------------------------------------------
	! compute remaining time and check for error
	!-----------------------------------------------

	time = tt - t

	if( bdebug ) then
	  write(6,*) 'final time: ',time
	  write(6,*) iel,lb,z
	  write(6,*) 'lgr_diff_vert end debugging'
	end if

	if( z < 0. .or. z > 1. ) then
	  call lgr_event(lgr_ev_vd_depth,id,(/id,iel,lb,lmax/)		&
     &			,(/tv,t,dz,w,hd,z/))
	  call lgr_internal_error(					&
     &		'error stop lgr_diff_vert: internal error (2)')
	  z = min(max(z,0.d0),1.d0)	!recorded in the loop
	  time = 0.
	  return
	end if

	!-----------------------------------------------
	! end of routine
	!-----------------------------------------------

	end subroutine lgr_diff_vert

!************************************************************
! Compute vertical velocity due to diffusivity 
! Mode: 1 naive random walk
!       2 diffusive random walk (Visser 1997)
!       3 Milstein scheme (Grawe 2010)

        subroutine diff_get_vert(mode,id,iel,lb,z,time,dt,lmax,hd,hda,hdb	&
     &				,wd,ndraw)

! the random draws are the particle's own (#225): lgr_random keyed on id,
! the time step and the site lgr_rnd_vdiff, numbered by ndraw
!
! the guard of the layer goes through lgr_internal_error (#256), its
! values through lgr_event (lgr_ev_vd_layer, #288)
!
! hda and hdb are the thicknesses of the layers above and below lb (0 at
! the surface and at the bottom), for a particle of lgr_diff_vert that
! leaves its interface into one of them (#284)

        use levels, only : nlvdi,nlv
        use basin
        use mod_lagrange
        use mod_lagrange_random, only : lgr_random, lgr_rnd_vdiff

        implicit none

	integer, intent(in)		:: mode !type of diffusion scheme
        integer, intent(in)		:: id   !id of particle
        integer, intent(in)		:: iel  !element number
        integer, intent(in)		:: lb   !layer
	double precision, intent(in)    :: z	!rel vert pos: 0=top, 1=bottom
        real, intent(in) 	        :: time	!time step 
	real, intent(out)		:: dt	!random walk time step
        integer, intent(out)		:: lmax !maximum layers in element
        double precision, intent(out)	:: hd   !layer thickness
        double precision, intent(out)	:: hda  !thickness of layer above
        double precision, intent(out)	:: hdb  !thickness of layer below
        double precision, intent(out)  	:: wd  	!vertical velocity due to diffusion
	integer, intent(inout)		:: ndraw !draws of the particle's
						 !vertical diffusion in the step

        real            	:: rnd		!random number
        real			:: hl(nlv)      !layer thickness
        real			:: hle(0:nlv)   !layer structures
        real 			:: htot         !total depth without zeta
        real                    :: htotz        !total depth with zeta 
	real			:: zp		!depth at which estimate diffusivity
        real                  	:: wdr(0:nlv)  	!vertical diffusivity [real]
	real			:: wdzp		!vertical diffusivity at zp
	double precision	:: dwd		!first derivative of diffusivity 
        integer 		:: iact         !element closest to xe
        integer 		:: nmax         !points given to exxpp
        real 			:: exxpp        !extrapolated values
	real			:: rs		!random number per sigma

        integer			:: ii,k,l

	!-----------------------------------------------
	! get layer structures and depths
	!-----------------------------------------------
        lmax = nlv
        call lagr_layer_thickness(iel,lmax,hl,htot,htotz)

	hle(0) = 0.
	do l = 1,lmax
	  hle(l) = hle(l-1) + hl(l)
	end do

        if( lb > lmax ) then
          call lgr_event(lgr_ev_vd_layer,id,(/id,iel,lb,lmax/))
          call lgr_internal_error(					&
     &		'error stop diff_get_vert: no such layer')
          dt = 0.			!recorded in the loop (#256): defined
          hd = hl(lmax)			!values, the caller stops the particle
          hda = hd
          hdb = hd
          wd = 0.d0
          return
        end if

	!-----------------------------------------------
	! get derivative of diffusivity on layer lb
	!-----------------------------------------------
        hd = hl(lb)
	hda = 0.d0
	if( lb > 1 ) hda = hl(lb-1)
	hdb = 0.d0
	if( lb < lmax ) hdb = hl(lb+1)
	dwd = (wde(lb,iel) - wde(lb-1,iel)) / hd

	!-----------------------------------------------
	! Get random walk time step 
	!-----------------------------------------------
        dt = min(dtvd(iel),time)

	!-----------------------------------------------
	! estimate diffusivity at z (+ 0.5*dwd*dt)
	!-----------------------------------------------
	zp = hle(lb-1) + z*hd
	if ( mode == 2 ) zp = zp + 0.5*dwd*dt
	zp = min(zp,htotz)
	zp = max(zp,0.)

	! exxpp is given the nmax = lmax + 1 interfaces hle(0:lmax) of the
	! element, from the surface to the bottom, with the diffusivities
	! wdr(0:lmax) there, and interpolates linearly between the two
	! interfaces around zp (0 <= zp <= htotz = hle(lmax)). Until #231 it
	! was given nmax = lmax: the bottom interface was not used, so in the
	! bottom layer the diffusivity was extrapolated from the two
	! interfaces above (it could be negative, and its square root below
	! stopped the run), and in an element with one layer the window
	! started one point before hle(0) and read the words before hle and
	! wdr (a division by zero in intp_neville)
	nmax = lmax + 1
	wdr(0:lmax) = wde(0:lmax,iel)
	iact = 0
	wdzp = exxpp(2,nmax,hle,wdr,zp,iact)

	! guard: an interpolation between the non-negative diffusivities of
	! two interfaces is not negative; a negative value (none in the test
	! cases; counted in lgr_nvdiff_neg and written at the end of the
	! particle run by lgr_vdiff_stats) is taken as 0, no random step
	if( wdzp < 0. ) then
!$OMP ATOMIC
	  lgr_nvdiff_neg = lgr_nvdiff_neg + 1
	  wdzp = 0.
	end if

	!-----------------------------------------------
	! compute vertical velocity due to diffusion
	! vertical velocity is > 0 if directed upward
	!-----------------------------------------------
        rnd = lgr_random(id,lgr_rnd_vdiff,ndraw)
        ndraw = ndraw + 1
        rnd = (rnd-0.5)/0.5		!normal distribution [-1, 1]
	wd = rnd*sqrt(6.*wdzp/dt)
	if ( mode == 2 ) wd = wd - dwd

	!-----------------------------------------------
	! Milstein scheme 
	!-----------------------------------------------
	if ( mode == 3 ) then
	  call rgauss(1.,rnd,id,ndraw)	!gaussian distribution
	  rs = rnd*sqrt(dt)
	  wd = -0.5*dwd*(rs*rs)/dt - 0.5*dwd + rs*sqrt(2.*wdzp)/dt
	end if

        end subroutine diff_get_vert


!******************************************************************

        subroutine lgr_vdiff_stats

! writes once, at the end of the particle run, how often diff_get_vert
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
! lgr_random: with at most lgr_nvdiff_max calls of 1 uniform draw and 2
! per trial of rgauss, 4/pi trials on average, about 3.55 per call), the
! particle steps stopped at the cap and those ended by two calls in a
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

	implicit none

        integer                 :: ie,ii,k,l
	real			:: time		!simulation time step
        real                    :: hl(nlv)      !layer thickness
        real                    :: hle(0:nlv)   !layer structures
        real                    :: htot         !total depth without zeta
        real                    :: htotz        !total depth with zeta 
        real                    :: wdl
        double precision        :: dwd2(nlv)    !second derivative of diffusivity 
        real                    :: dmax
	logical			:: bzero	!a layer of zero thickness
	real			:: dtd		!random walk time step
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
	  ! diff_get_vert). An element with a layer of zero thickness gets
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

!******************************************************************
!Generate random distribution with 0 mean and standard deviation SIGMA.
!Returns one (two) gaussian random number from the same distribution. 
!The uniform draws are those of particle id (#225): lgr_random keyed on
!id, the time step and the site lgr_rnd_vdiff, numbered by ndraw.

        subroutine rgauss(sigma, y1, id, ndraw)

        use mod_lagrange_random, only : lgr_random, lgr_rnd_vdiff

        implicit none

        real, intent(in)        :: sigma   !standard deviation of distribution
        real, intent(out)       :: y1      !random number
        integer, intent(in)     :: id      !id of particle
        integer, intent(inout)  :: ndraw   !draws of the particle's
                                           !vertical diffusion in the step
        real                    :: y2      !second random number

        real                    :: rnd
        real*8                  :: x1, x2, w

        x1 = 0.
        x2 = 0.
	w  = 0.

        do while ( (w .ge. 1.0) .or. (w .eq. 0.0) )
          rnd = lgr_random(id,lgr_rnd_vdiff,ndraw)
          x1 = 2.0 * rnd - 1.0
          rnd = lgr_random(id,lgr_rnd_vdiff,ndraw+1)
          x2 = 2.0 * rnd - 1.0
          ndraw = ndraw + 2
          w = x1 * x1 + x2 * x2
        end do

	w = sigma*sqrt( (-2.0 * log( w ) ) / w )
	y1 = x1 * w
	y2 = x2 * w

	end subroutine rgauss

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
