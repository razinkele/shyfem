
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
! lgr_internal_error, then lgr_internal_failed is true) returns at once;
! the warning counters nk, nl, nu are shared by the threads (OMP atomic)

        use mod_lagrange
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
        integer 		:: n
        real 			:: perc
        double precision 	:: xx,yy,zz

        integer			:: ndraw	!vertical draws made (#225)
        integer			:: nc		!the counter after this particle
        logical			:: lgr_internal_failed

        integer, save 		:: nk = 0
        integer, save 		:: nl = 0
        integer, save 		:: nu = 0

	bpark = .false.

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

        n = 100         !maximum loop count
        zz = z
	dtime = time

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
          do while ( dtime > 0. .and. n > 0 )
            call lgr_diff_vert(mode,id,iel,lb,zz,dtime,ndraw)
            if( lb < 1 ) exit
            n = n - 1                   !decrement loop counter
          end do
          z = zz 
          if( lgr_internal_failed() ) return	!recorded in the loop
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
          if( n == 0 ) then
!$OMP ATOMIC CAPTURE
            nk = nk + 1
            nc = nk
!$OMP END ATOMIC
            perc = 0.
            if( idbdy > 0 ) perc = (100.*nc)/idbdy
            write(6,1000) 'warning particle dif',id,iel,n,dtime,perc
            !iel = -iel
          else if( iel < 1 ) then
!$OMP ATOMIC CAPTURE
            nl = nl + 1
            nc = nl
!$OMP END ATOMIC
            perc = 0.
            if( idbdy > 0 ) perc = (100.*nc)/idbdy
            write(6,1000) 'loosing particle dif',id,iel,n,dtime,perc
          else
!$OMP ATOMIC CAPTURE
            nu = nu + 1
            nc = nu
!$OMP END ATOMIC
            perc = 0.
            if( idbdy > 0 ) perc = (100.*nc)/idbdy
            write(6,1000) 'unknown error dif',id,iel,n,dtime,perc
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

 1000   format(a,3i10,2f10.2)

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
! caller's loop ends) with defined values; the run stops after the loop

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
	double precision 		:: dz	!vertical displacement
	double precision 		:: dv	!potential vertical dispacement
	double precision 		:: t,tv,tt
	real				:: rr
	logical 			:: bdebug
	logical 			:: bsurf,bbott
	integer 			:: lmax
	integer 			:: lborig
	logical				:: lgr_internal_failed

	blgrdebug = id == 0
	bdebug = blgrdebug

	lborig = lb

        call diff_get_vert(mode,id,iel,lb,z,time,dt,lmax,hd,wd,ndraw)
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
	end if
	if ( w < 0.d0 .and. z == 1.d0 ) then
	  lb = lb + 1
	  z  = 0.d0
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
	  write(6,*) 'id,iel ',id,iel
	  write(6,*) 'tv,t ',tv,t
	  write(6,*) 'dz,w,hd: ',dz,w,hd
	  write(6,*) 'z,lb,lmax ',z,lb,lmax
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

        subroutine diff_get_vert(mode,id,iel,lb,z,time,dt,lmax,hd,wd,ndraw)

! the random draws are the particle's own (#225): lgr_random keyed on id,
! the time step and the site lgr_rnd_vdiff, numbered by ndraw
!
! the guard of the layer goes through lgr_internal_error (#256)

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
          write(6,*) 'id,iel,l,lmax: ',id,iel,lb,lmax
          call lgr_internal_error(					&
     &		'error stop diff_get_vert: no such layer')
          dt = 0.			!recorded in the loop (#256): defined
          hd = hl(lmax)			!values, the caller stops the particle
          wd = 0.d0
          return
        end if

	!-----------------------------------------------
	! get derivative of diffusivity on layer lb
	!-----------------------------------------------
        hd = hl(lb)
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
! set a negative interpolated vertical diffusivity to 0 (#231); only in
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
	real			:: dtd		!random walk time step
        real			:: hd		!layer thickness
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
	  !-----------------------------------------------
	  dtd = time
	  if ( lmax > 1 ) then
 	    do l = 1,lmax-1
              hd = hl(l)
	      dwd2(l) = (wde(l+1,ie) + 2.*wde(l,ie) + wde(l-1,ie))/(hd*hd)
	    end do
	!write(6,*) 'hl ',hl(1:lmax)
	!write(6,*) 'dwd2 ',dwd2(1:lmax)
            dwd2(lmax) = dwd2(lmax-1)
            if ( lmax > 2 ) dwd2(lmax) = dwd2(lmax-1) +  &
     &  		(dwd2(lmax-1)-dwd2(lmax-2))/hl(lmax-1)*hl(lmax)
  
	!write(6,*) 'dwd2 ',dwd2(1:lmax)
   	    dmax = maxval(abs(dwd2(1:lmax)))
  	    if ( dmax /= 0. ) dtd = 1./(100.*dmax)
            dtd = max(dtmin, dtd)
	  end if
	  dtvd(ie) = dtd
	end do

	end subroutine lag_vdiff_ele

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
