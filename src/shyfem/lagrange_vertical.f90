
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015-2019  Georg Umgiesser
!    Copyright (C) 2015,2017  Christian Ferrarin
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

! deal with vertical velocities
!
! revision log :
!
! 01.04.2015	ggu	changed VERS_7_1_7
! 23.04.2015	ggu	internal coodinates finished
! 06.05.2015	ccf	included settling velocity for lagrangian
! 08.05.2015	ggu&ccf	bug fix in track_xi_next_element
! 14.05.2015	ccf	bug fix in track_xi
! 21.05.2015	ggu	changed VERS_7_1_11
! 05.06.2015	ggu	changed VERS_7_1_12
! 17.07.2015	ggu	changed VERS_7_1_80
! 20.07.2015	ggu	changed VERS_7_1_81
! 16.11.2015	ggu	changed VERS_7_3_14
! 15.02.2016	ggu	handle particles on vertical wall gracefully
! 19.02.2016	ggu	changed VERS_7_5_3
! 22.02.2016	ggu	changed VERS_7_5_4
! 09.05.2017	ggu	changed VERS_7_5_26
! 26.05.2017	ccf	handle particles on open boundary
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 22.05.2023	ggu	get_layer_thickness() was missing an argument
! 05.06.2023    lrp     introduce z-star
! 28.09.2023    lrp     bug fix for zstar (wrong declaration nadapt/hadapt)

!
!******************************************************

	subroutine getzvel(ie,z0,l0,is_in,is_out,a_in,a_out,w)

! returns vertical velocity to be used in lagrangian model

	implicit none

	integer, intent(in) :: ie	!element number
	real, intent(in) :: z0		!depth of particle
	integer, intent(in) :: l0	!layer in which particle is in [1-nlv]
	integer, intent(in) :: is_in	!side from which particle comes [1-3]
	integer, intent(in) :: is_out	!side to which particle goes [1-3]
	real, intent(in) :: a_in	!relative postion of side is_in [0-1]
	real, intent(in) :: a_out	!relative postion of side is_out [0-1]
	real, intent(out) :: w		!computed vertical velocity for ie and l0 (return)

	integer ii
	real win,wout

!	-----------------------------------------------
!	velocity at entering and exiting point
!	-----------------------------------------------

	if( ie .le. 0 ) then
	  w = 0.
	  return
	end if

	ii = mod(is_in,3) + 1
	call getzvel_point(ie,l0,ii,a_in,win)

	ii = mod(is_out,3) + 1
	call getzvel_point(ie,l0,ii,a_out,wout)

!	-----------------------------------------------
!	average velocity in element
!	-----------------------------------------------

	w = 0.5 * ( win + wout )

!	-----------------------------------------------
!	end of routine
!	-----------------------------------------------

	end

!******************************************************

	subroutine getzvel_point(ie,l0,is,a,w)

! returns vertical velocity at point given by ie,l0,is,a

	use mod_hydro_vel
	use basin

	implicit none

	integer, intent(in) :: ie	!element number
	integer, intent(in) :: l0	!layer in which particle is in
	integer, intent(in) :: is	!side where particle is [1-3]
	real, intent(in) :: a		!relative postion of side
	real, intent(out) :: w		!computed vertical velocity for ie and l0 (return)

	integer ii,k1,k2
	real wo1,wo2,wn1,wn2
	real w1,w2

!	-----------------------------------------------
!	velocity at first node
!	-----------------------------------------------

	ii = is

	k1 = nen3v(ii,ie)
	wo1 = wlov(l0,k1) + wlov(l0-1,k1)
	wn1 = wlnv(l0,k1) + wlnv(l0-1,k1)
	w1 = 0.25 * ( wo1 + wn1 )

!	-----------------------------------------------
!	velocity at second node
!	-----------------------------------------------

	ii = mod(ii,3) + 1

	k2 = nen3v(ii,ie)
	wo2 = wlov(l0,k2) + wlov(l0-1,k2)
	wn2 = wlnv(l0,k2) + wlnv(l0-1,k2)
	w2 = 0.25 * ( wo2 + wn2 )

!	-----------------------------------------------
!	interpolate velocity
!	-----------------------------------------------

	w = (1.-a)*w1 + a*w2

!	-----------------------------------------------
!	end of routine
!	-----------------------------------------------

	end

!******************************************************

	subroutine lagr_layer_thickness(ie,lmax,hl,htot,htotz)

! computes layer thickness for element ie
!
! the guard goes through lgr_internal_error (#256): recorded inside the
! particle loop, the layers are limited to the dimension (defined values
! for the caller; the run stops after the loop); its values go to
! lgr_event (lgr_ev_layers, #294: until then written from inside the
! loop)

	use mod_depth
	use mod_hydro
	use levels
	use mod_lagrange, only : lgr_event, lgr_ev_layers

	implicit none

	integer, intent(in) :: ie		!element number
	integer, intent(inout) :: lmax		!max number of layers (dimension in, actual out)
	real, intent(out) :: hl(lmax)		!layer thickness (return)
	real, intent(out) :: htot,htotz		!total depth without and with zeta (return)

	integer nlev,nsigma,ii,lmax_act
	real hsigma
	real z,h
	integer nadapt(4)
	real hadapt(4)

        !call compute_sigma_info(nlev,hlv,nsigma,hsigma)
	call get_sigma_info(nlev,nsigma,hsigma)
        call get_zadapt_info(ie,nadapt,hadapt) 
	lmax_act = ilhv(ie)
	if( lmax_act > lmax .or. lmax_act > nlev ) then
	  call lgr_event(lgr_ev_layers,ie,(/ie,nlev,lmax,lmax_act/))
	  call lgr_internal_error(					&
     &		'error stop lagr_layer_thickness: incompatible layers')
	  lmax_act = min(lmax_act,lmax,nlev)	!recorded in the loop
	end if
	lmax = lmax_act

	h = hev(ie)
	z = 0.
	do ii=1,3
	  z = z + zenv(ii,ie) + zeov(ii,ie)
	end do
	z = z / 6.

	call get_layer_thickness(lmax,1,nsigma,nadapt(4), &
     &				 hsigma,hadapt(4),z,h,hlv,hl)
	htot = h
	htotz = h + z

	end

!*******************************************************************

        subroutine vertpos(zn0,deltat,layd,w,zn1,ztime,addl)

	implicit none

	real, intent(in) :: zn0		!initial relative vertical position in layer
	real, intent(in) :: deltat	!time spent in element(horizontal)
	real, intent(in) :: w		!average vertical velocity
	real, intent(out) :: zn1	!final relative vertical position in layer
	real, intent(out) :: ztime	!time spent in element (vertical)
        integer, intent(out) :: addl	!relative movement to next layer [-1,0,+1]
        real, intent(in) :: layd	!layer thickness

! return are zn1,ztime,addl

! lstd		max vertical distance to be traveled
! cpstd		computed distance to be traveled

	real cpdst,lstd

	lstd = 0
        if(w.gt.0) lstd=layd*(1-zn0)
        if(w.lt.0) lstd=-layd*zn0

        cpdst=deltat*w
        zn1=zn0+(cpdst/layd)
        
	if( w == 0 ) then
	  ztime = 2*deltat
	else
          ztime=lstd/w
	end if

        if(ztime.le.deltat)then
          if(w.gt.0)addl=1
          if(w.lt.0)addl=-1
        else
          addl=0
        end if
	
	if(zn1.gt.1)zn1=0
        if(zn1.lt.0)zn1=1

        end

!************************************************************

	subroutine getalfa(side,d,near,far,re)

	implicit none

        integer, intent(in) :: side	!number of side of element [1-3]
	real, intent(in) :: d		!relative distance from closest vertex
	integer, intent(in) :: near	!number of closest vertex [1-3]
	integer, intent(in) :: far	!to be deleted...
	real, intent(out) :: re		!relative distance to first point of side

	integer ind

        ind=mod(side,3)+1
	
	if(ind.eq.near)then
	  re=d
	else
	  re=1-d
	end if
	
	end 

!************************************************************
!************************************************************
!************************************************************
!
! z = 0		top of layer
! z = 1		bottom of layer
!
!************************************************************

	subroutine track_xi(id,iel,lb,sv,xi,z,time,ncross,icut)

! icut: if the particle stopped on a cut-off side of the MPI domain (side
! table lgr_ieltv <= -1000) and goes on on another process, the side of
! the element it started in (iel is then -that element, xi its position on
! the side, as at an open boundary); 0 otherwise
!
! an internal-error guard recorded inside the particle loop (#256: by
! lgr_internal_error here or in a routine called here, then
! lgr_internal_failed is true) ends the call with time = 0 and the values
! the particle has (all defined); the run stops after the loop. The
! values of the guards, and a negative velocity (which the computation
! of track_xi_get_flux never gives), go to lgr_event (#294: until then
! they were written from inside the loop). The errors of xit_start_end
! and xi_dist are guards of this kind too (their _ierr forms, #294:
! until then a write and a bare stop in the utility). The debug lines
! (bdebug) are off at compile time: until #294 bdebug was true for a
! particle with id 0, which no release gives (ids start at 1), and it
! was set through the module variable blgrdebug, written by every
! thread of the loop
!
! the bottom layer of a column of more than one layer (#299): the flow's
! vertical velocity there is linear in z, from wt (the element mean of
! the interface velocity at the layer top, old and new time level) to 0
! at the bed, and the settling velocity sv is not tapered:
! w(z) = wt*(1-z) - sv, integrated exactly over the time in the layer
! (lgr_bed_move, lgr_bed_exit). Before, the whole layer had the layer
! mean of w, which does not vanish at the bed: an upward mean lifted the
! particles off the bed, a downward one held them there, and the bottom
! 5 % of the column held about half its share of particles (0.49 in the
! closed forced case of check_lgr_bed.sh, 0.88 and 0.89 with this form).
! The bed condition belongs to the water; settling is the particle's
! motion relative to it (a tapered (wt-sv)*(1-z) would make a settling
! particle approach the bed exponentially, never reach it). One-layer
! columns and the layers above keep the layer mean, and a bottom layer
! of zero thickness keeps the path of before (tv = 0: not moving)

	use mod_lagrange
	use mod_hydro_vel, only : wlov,wlnv
	use basin, only : nen3v

	implicit none

	integer, intent(in) :: id		!id of particle
	integer, intent(inout) :: iel		!element (in and out)
	integer, intent(inout) :: lb		!level (in and out)
	double precision, intent(in) :: sv	!sinking velocity
	double precision, intent(inout) :: xi(3)	!natural coordinates in triangle
	double precision, intent(inout) :: z	!rel vert pos: 0=top, 1=bottom
	real, intent(inout) :: time
	integer, intent(in) :: ncross		!element crossings left in time step
	integer, intent(out) :: icut		!cut-off side reached (0: none)

	logical, parameter :: bdebug = .false.	!debug lines (#294)
	logical bsurf,bbott,bhas
	logical bbed			!w linear in the bottom layer (#299)
	logical bup			!leaving the layer upward
	integer iflux,lmax,iside
	integer ierr
	integer ieorig,lborig
	integer ii,k
	double precision s,alpha
	double precision dist,dh,dv,ds
	double precision t,th,tv,tt
	double precision vel,w
	double precision dz,hd
	double precision wt		!flow's w at the top of the bottom layer
	double precision tex,z1
	double precision xis(3)
	double precision xie(3)

	logical track_xi_on_material_boundary
	logical lgr_internal_failed

	icut = 0			!before the first return
	dz = 0.d0			!defined for the guard (2) below

	ieorig = iel
	lborig = lb

	!write(6,*) 'tracking particle: ',id,time
	call track_xi_check('start track_xi',id,xi)

	!-----------------------------------------------
	! get advection information
	!-----------------------------------------------

	call track_xi_get_vertical(id,iel,lb,lmax,hd,w)
	if( lgr_internal_failed() ) then	!recorded in the loop (#256)
	  time = 0.
	  return
	end if
	w = w - sv				!total vertical velocity

	!-----------------------------------------------
	! handle particles on surface or on bottom
	!-----------------------------------------------

	bsurf = lb .eq. 1 .and. z .eq. 0.d0	!particle on surface
	bbott = lb .eq. lmax .and. z .eq. 1.d0	!particle on bottom

	if( bsurf .and. w > 0.d0 ) w = 0.d0
	if( bbott .and. w < 0.d0 ) w = 0.d0
	if( blgrsurf .or. blgr2d ) w = 0.d0	!advection only in surface layer

	! a particle on an interface goes where w points; then w and hd are
	! those of the layer it enters (#299: until then those of the layer
	! it left). One switch per call: the else keeps the new layer's w from
	! sending the particle back at once (w = 0 for ilagr 1 and 2: never)
	if ( w > 0.d0 .and. z == 0.d0 ) then
	  lb = lb - 1
	  z  = 1.d0
	  call track_xi_get_vertical(id,iel,lb,lmax,hd,w)
	  w = w - sv
	else if ( w < 0.d0 .and. z == 1.d0 ) then
	  lb = lb + 1
	  z  = 0.d0
	  call track_xi_get_vertical(id,iel,lb,lmax,hd,w)
	  w = w - sv
	end if

	!-----------------------------------------------
	! bottom layer of a column of more than one layer (#299): w linear
	! in z, from wt at the layer top to 0 at the bed, sv not tapered
	!-----------------------------------------------

	bbed = .false.
	wt = 0.d0
	if( lb == lmax .and. lmax > 1 ) then
	  if( .not. ( blgrsurf .or. blgr2d ) ) then
	    if( hd > 0.d0 ) then		!hd of lb
	      do ii=1,3
	        k = nen3v(ii,iel)
	        wt = wt + 0.5d0*(wlov(lmax-1,k)+wlnv(lmax-1,k))
	      end do
	      wt = wt / 3.d0
	      w = wt*(1.d0-z) - sv		!at the particle
	      bbed = .true.
	    end if
	  end if
	end if

	!-----------------------------------------------
	! gets flux and vel information for element and layer
	!-----------------------------------------------

	call track_xi_get_flux(id,iel,lb,iflux,alpha,vel)

	if( vel < 0.d0 ) then		!counted (#294)
	  call lgr_event(lgr_ev_vel_neg,id,(/id,iel,lb,lmax/)		&
     &		,(/vel,dble(flux3d(lb,1,iel)),dble(flux3d(lb,2,iel))	&
     &		,dble(flux3d(lb,3,iel))/))
	end if

	!-----------------------------------------------
	! determine time to leave element (th)
	!-----------------------------------------------

	th = 2.*time

	if( bdebug ) then
	  write(6,*) '======================================='
	  write(6,*) 'track_xi start debugging: ',id
	  write(6,*) '======================================='
	  write(6,*) iel,lb,lmax,iflux
	  write(6,*) alpha,vel,z
	  write(6,*) xi
	  !call track_xi_info_element(iel)
	end if

	if( vel > 0. ) then
	  if( iflux > 0 ) then		!out of flux node
	    call xit_start_end_ierr(iflux,alpha,xi,xis,xie,s,ierr)
	  else if( iflux < 0 ) then	!into flux node
	    call xit_start_end_ierr(-iflux,alpha,xi,xie,xis,s,ierr)
	    s = 1.d0 - s
	  else
	    time = 0.
	    return
	    !goto 99
	  end if
	  if( ierr /= 0 ) then		!internal error (#294: was a stop)
	    call lgr_event(lgr_ev_xit,id,(/id,iel,iflux,ierr/)		&
     &			,(/alpha,xi(1),xi(2),xi(3)/))
	    call lgr_internal_error(					&
     &		'error stop track_xi: internal error of xit_start_end')
	    time = 0.			!recorded in the loop
	    return
	  end if
	  call xi_dist_ierr(iel,xis,xie,dist,ierr)
	  if( ierr /= 0 ) then		!internal error (#294: was a stop)
	    call lgr_event(lgr_ev_xidist,id,(/id,iel,ierr/)		&
     &			,(/xis(1),xis(2),xis(3),xie(1),xie(2),xie(3)/))
	    call lgr_internal_error(					&
     &		'error stop track_xi: error of xi_dist')
	    time = 0.			!recorded in the loop
	    return
	  end if
	  dh = dist*(1.d0 - s)		!distance to travel in element
	  th = dh / vel			!time to arrive at edge of element
	else
	  s = 1.
	  dist = 0.
	  dh = 0.
	  xis = xi
	  xie = xi
	end if

	!-----------------------------------------------
	! determine time to leave layer (tv)
	!-----------------------------------------------

	tv = 2.*time
	bup = ( w > 0.d0 )

	if( bbed ) then			!bottom layer (#299)
	  call lgr_bed_exit(wt,sv,hd,z,tex,bup)
	  if( tex < tv ) tv = tex	!huge (never) stays 2*time
	else if( w /= 0. ) then
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

	! a zero time to leave a layer of non-zero thickness is no vertical
	! motion in this call, as the rule bbott gives a particle on the bed
	! (w = 0, tv = 2*time): on the bed with sv > 0, at the top of the
	! bottom layer with wt-sv > 0 where the switch did not fire, after a
	! switch into a layer whose w points back. Left at 0, tv would make
	! the material-boundary rule below give th = 0 and t = 0, and a
	! particle on a wall side would be moved through it out of the basin
	! (#299). Before #299 tv = 0 needed hd = 0; that path is unchanged
	if( tv == 0.d0 ) then
	  if( hd > 0.d0 ) then
	    w = 0.d0
	    bbed = .false.
	    tv = 2.*time
	  end if
	end if

	!-----------------------------------------------
	! what happens first? (tt is total time available)
	!-----------------------------------------------

	tt = time
	t = tt
	if( th > 0. ) t = min(t,th)
	if( tv > 0. ) t = min(t,tv)
	!t = min(th,tv,tt)

	if( bdebug ) then
	  write(6,*) 'times for advection'
	  write(6,*) th,tv,tt
	  write(6,*) dist,s,dh
	  write(6,*) xis
	  write(6,*) xie
	end if

	!-----------------------------------------------
	! if landing on material boundary - artificially slow down particle
	!CCF IN THIS CASE WE DO NOT ALLOW BEACHING BY ADVECTION
	!-----------------------------------------------

	if( track_xi_on_material_boundary(iel,xie) ) then
	  th = 2.*min(tv,tt)	!longer than other times
	  t = min(th,tv,tt)
	  if( bdebug ) then
	    write(6,*) 'material boundary: ',id,iel,lb
	    write(6,*) th,tv,tt
	  end if
	end if

	!-----------------------------------------------
	! handle horizontal advection
	!-----------------------------------------------

	if( th == 0. ) then		!body not moving or laying on side
          if (vel > 0.) then
            xi = xie
            call track_xi_next_element(iel,xi,id,ncross,iside)    !for particles laying on side
	    call track_xi_side_test(ieorig,iel,iside,lb,bhas,icut)
	    if( .not. bhas ) then	!just do vert adv
	      iel = ieorig
	      xi = xie
            end if
          end if
	else if( th > t ) then		!body remains in element
	  ds = (1.-s)*t/th
	  s = s + ds
	  if( s > 1. ) then
	    call lgr_event(lgr_ev_xi_int3,id,(/id,iel/),(/s,t,th,ds,s-ds/))
	    call lgr_internal_error(					&
     &		'error stop track_xi: internal error (3)')
	    time = 0.			!recorded in the loop
	    return
	  end if
	  xi = (1.-s)*xis + s*xie
	  call track_xi_check('after advection track_xi 1',id,xi)
	else				!body reaches border of element
	  xi = xie
	  call track_xi_check('before advection track_xi 2',id,xi)
	  call track_xi_next_element(iel,xi,id,ncross,iside)
	  call track_xi_check('after advection track_xi 2',id,xi)
	  call track_xi_side_test(ieorig,iel,iside,lb,bhas,icut)
	  if( .not. bhas ) then	!just do vert adv
	    iel = ieorig
	    xi = xie
	    if( th == 0. ) then
	      t = min(tv,tt)	!just advect vertically
	      if( bdebug ) then
	        write(6,*) 'waiting for vertical: ',id
	        write(6,*) 'waiting... ',t,tt
	        write(6,*) 'waiting... ',iel,w
	        write(6,*) 'waiting... ',lb,z
	      end if
	    end if
	  end if
	end if

	call track_xi_check('after advection track_xi',id,xi)
	if( lgr_internal_failed() ) then	!recorded in the loop (#256)
	  time = 0.
	  return
	end if

	if( bdebug ) then
	  write(6,*) 'after horizontal advection'
	  write(6,*) ieorig,iel
	  write(6,*) lborig,lb,lmax
	  write(6,*) th,t,iel
	  write(6,*) s
	  write(6,*) xi
	end if

	!-----------------------------------------------
	! handle vertical advection
	!-----------------------------------------------

	if( tv == 0. ) then		!body not moving
	  !
	else if( tv > t ) then		!body remains in layer
	  if( bbed ) then		!bottom layer (#299)
	    call lgr_bed_move(wt,sv,hd,z,t,z1)
	    dz = z - z1
	    z = z1
	  else if( hd > 0.d0 ) then	!hd = 0 here only with w = 0: no motion
	    dz = w*t/hd
	    z = z - dz
	  end if
	else
	  if( bup ) then
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

	if( bdebug ) then
	  write(6,*) 'after vertical advection'
	  write(6,*) ieorig,iel
	  write(6,*) lborig,lb,lmax
	  write(6,*) w,z
	end if

	!-----------------------------------------------
	! compute remaining time and check for error
	!-----------------------------------------------

	if( iel .ne. ieorig .and. iel > 0 ) then
	  call track_xi_adjust_layer(id,ieorig,iel,lb,z)
	end if

	time = tt - t

	if( bdebug ) then
	  write(6,*) 'final time: ',time
	  write(6,*) iel,lb,z
	  write(6,*) 'track_xi end debugging'
	end if

	if( z < 0. .or. z > 1. ) then
	  call lgr_event(lgr_ev_xi_depth,id,(/id,iel,lb,lmax/)		&
     &			,(/tv,t,dz,w,hd,z/))
	  call lgr_internal_error('error stop track_xi: internal error (2)')
	  z = min(max(z,0.d0),1.d0)	!recorded in the loop
	  time = 0.
	  return
	end if

	!-----------------------------------------------
	! end of routine
	!-----------------------------------------------

	end

!************************************************************

	subroutine lgr_bed_move(wt,sv,hd,z0,t,z1)

! relative depth z1 after the time t of a particle at z0 in the bottom
! layer (thickness hd) of a column of more than one layer (#299, called
! by track_xi). The flow's vertical velocity is linear in z, from wt at
! the layer top to 0 at the bed, and the settling velocity sv is not
! tapered:
!
!	w(z) = wt*(1-z) - sv		(w > 0 upward; z = 0 top, 1 bed)
!
! With u = 1-z, du/dt = (wt*u - sv)/hd: u(t) = a + (u0-a)*exp(x) with
! a = sv/wt and x = wt*t/hd, u0 - sv*t/hd for wt = 0. It is computed as
!
!	u(t) = u0 + w0*(t/hd)*(exp(x)-1)/x	(w0 = wt*u0 - sv)
!
! the same function without a division by wt, so that a round-off wt
! keeps the settling exact (wt = 0 is the limit x = 0). Valid while the
! particle stays in the layer, t <= texit of lgr_bed_exit, as track_xi
! calls it (exp(x) is then at most the ratio of the speeds at the exit
! and at the start); z1 is kept in 0 ... 1. hd <= 0 (a layer of zero
! thickness) or w0 = 0 (at rest) is no motion: z1 = z0.
! Self-contained (no use): check_lgr_fixes.sh bed-w cuts it out and
! tests it on its own (it needs this end line)

	implicit none

	double precision, intent(in) :: wt	!flow's w at the layer top [m/s]
	double precision, intent(in) :: sv	!settling velocity [m/s], > 0 down
	double precision, intent(in) :: hd	!thickness of the layer [m]
	double precision, intent(in) :: z0	!relative depth: 0 top, 1 bed
	double precision, intent(in) :: t	!time [s]
	double precision, intent(out) :: z1	!relative depth after t

	double precision w0,x,phi

	z1 = z0
	if( hd <= 0.d0 ) return		!no motion, no division

	w0 = wt*(1.d0-z0) - sv		!w at the particle
	if( w0 == 0.d0 ) return		!at rest

	x = min(wt*t/hd,700.d0)		!exp(x) finite
	if( abs(x) < 1.d-4 ) then
	  phi = 1.d0 + x*(0.5d0 + x*(1.d0/6.d0 + x/24.d0))
	else
	  phi = (exp(x)-1.d0) / x
	end if

	z1 = z0 - w0*(t/hd)*phi		!z = 1 - u
	z1 = min(max(z1,0.d0),1.d0)

	end subroutine lgr_bed_move

!************************************************************

	subroutine lgr_bed_exit(wt,sv,hd,z0,texit,bup)

! time texit for a particle at z0 in the bottom layer (thickness hd) to
! reach the layer top (bup true) or the bed (bup false) with the w(z) of
! lgr_bed_move (#299, called by track_xi); huge(1.d0), bup false, if
! neither is ever reached
!
! The particle moves the way w0 = w(z0) points, over du = z0 up to the
! top or 1-z0 down to the bed. w is linear in z, so the particle reaches
! that boundary only if w1, w there (wt-sv at the top, -sv at the bed),
! points the same way; otherwise w vanishes on the way (at the
! equilibrium u = sv/wt) and the particle only approaches it. With the
! speeds s0 = |w0| and s1 = |w1| > 0 the time is du*hd over their
! logarithmic mean:
!
!	texit = hd*du * (log(s1)-log(s0))/(s1-s0)
!
! (a series of log(1+d)/d, d = (s1-s0)/s0, when s1 is close to s0: for
! wt = 0 the linear hd*du/sv). The edge returns: w0 = 0 (on the bed with
! sv = 0, or at the equilibrium) huge; on a boundary moving out (du = 0:
! at the top with wt-sv > 0, on the bed with sv > 0) 0, which track_xi
! takes as no vertical motion in the call, as its rule bbott stops a
! particle on the bed. No log of a number <= 0, no
! division by wt or by 0. hd <= 0 (a layer of zero thickness) is no
! motion: huge.
! Self-contained (no use): check_lgr_fixes.sh bed-w cuts it out and
! tests it on its own (it needs this end line)

	implicit none

	double precision, intent(in) :: wt	!flow's w at the layer top [m/s]
	double precision, intent(in) :: sv	!settling velocity [m/s], > 0 down
	double precision, intent(in) :: hd	!thickness of the layer [m]
	double precision, intent(in) :: z0	!relative depth: 0 top, 1 bed
	double precision, intent(out) :: texit	!time to the top or the bed [s]
	logical, intent(out) :: bup		!true: the top, false: the bed

	double precision w0,s0,s1,du,d,vm

	texit = huge(1.d0)
	bup = .false.
	if( hd <= 0.d0 ) return		!no motion, no division

	w0 = wt*(1.d0-z0) - sv		!w at the particle
	if( w0 > 0.d0 ) then		!up, to the top
	  du = z0
	  s0 = w0
	  s1 = wt - sv
	else if( w0 < 0.d0 ) then	!down, to the bed
	  du = 1.d0 - z0
	  s0 = -w0
	  s1 = sv
	else
	  return			!at rest
	end if
	if( s1 <= 0.d0 ) return		!w vanishes on the way: never

	bup = ( w0 > 0.d0 )
	if( du <= 0.d0 ) then		!on the boundary, moving out
	  texit = 0.d0
	  return
	end if

	if( abs(s1-s0) < 1.d-4*s0 ) then	!log(1+d)/d by its series
	  d = (s1-s0) / s0
	  vm = s0 / (1.d0 - d*(0.5d0 - d*(1.d0/3.d0 - d/4.d0)))
	else
	  vm = (s1-s0) / (log(s1)-log(s0))
	end if

	if( hd*du/huge(1.d0) < vm ) then
	  texit = hd*du / vm
	else				!speeds too small: never (huge)
	  bup = .false.
	end if

	end subroutine lgr_bed_exit

!************************************************************

	subroutine track_xi_next_element(ie,xi,id,ncross,iside)

! copies internal coordinates to new element - avoid falling on vertex
!
! neighbours from the side table of the tracker, lgr_ieltv: a side without
! a local neighbour (wall, open boundary, cut-off side <= -1000) is left
! with ie = -ie and xi on that side of the old element; iside returns the
! side used (for a particle on a vertex the one of the vertex pick), so
! that the caller can tell a cut-off side from the others
!
! a guard recorded inside the particle loop (lgr_internal_error, #256)
! returns ie = -ie (the particle leaves the domain) and iside = 0; the
! caller stops the particle (lgr_internal_failed), the run stops after the
! loop. The values of the guards go to lgr_event (#294: until then they
! were written from inside the loop); the debug lines are off at compile
! time (bdebug, see track_xi)

	use mod_lagrange
	use mod_lagrange_mpi, only : lgr_ieltv

	implicit none

	integer, intent(inout) :: ie
	double precision, intent(inout) :: xi(3)
	integer, intent(in) :: id		!id of particle
	integer, intent(in) :: ncross		!element crossings left in time step
	integer, intent(out) :: iside		!side of the old element used

	logical, parameter :: bdebug = .false.	!debug lines (#294)
	integer ii,in,it
	integer ia1,ia2,ia3
	integer ib1,ib2,ib3
	integer ieb
	double precision r,eps,u
	double precision xiaux(3)

	double precision track_xi_vertex_u

	eps = 1.e-5
	iside = 0

	!---------------------------------------
	! check xi - how many zeros
	!---------------------------------------

	in = 0
	it = 0
	do ii=1,3
	  if( xi(ii) == 0. ) then
	    in = in + 1
	    it = it + ii
	  end if
	end do

	if( bdebug ) then
	  write(6,*) 'track_xi_next_element: ',in,it
	end if

	!---------------------------------------
	! assign pointers - ia1 indicates side of particle
	!---------------------------------------

	if( in == 1 ) then	!normal mode - particle on side
	  ia1 = it
	  ia2 = mod(ia1,3) + 1
	  ia3 = mod(ia2,3) + 1
	else if( in == 2 ) then	!particle on vertex - must move
	  if( bdebug ) write(6,*) 'in==2 ',xi
	  u = track_xi_vertex_u(id,lgr_step,ncross)	!never 0.5, so r /= 0
	  r = eps*(u-0.5)
	  it = 6 - it
	  if( r < 0. ) then
	    ia1 = mod(it+1,3) + 1
	    ia2 = mod(ia1,3) + 1
	    ia3 = mod(ia2,3) + 1
	    xi(ia2) = 1. + r
	    xi(ia3) = -r
	  else
	    ia1 = mod(it,3) + 1
	    ia2 = mod(ia1,3) + 1
	    ia3 = mod(ia2,3) + 1
	    xi(ia2) = r
	    xi(ia3) = 1. - r
	  end if
	else				!xi not on side or impossible
	  call lgr_event(lgr_ev_next_xi,id,(/id,ie,in,it/),xi)
	  call lgr_internal_error(					&
     &		'error stop track_xi_next_element: erroneous xi')
	  ie = -ie			!recorded in the loop
	  return
	end if

	!---------------------------------------
	! sanity checks (may be removed)
	!---------------------------------------

	if( xi(ia1) /= 0. .or. abs(xi(ia2)+xi(ia3)-1.) > eps ) then
	  call lgr_event(lgr_ev_next_sanity,id,(/id,ie,in,it,ia1/),xi)
	  call lgr_internal_error(					&
     &		'error stop track_xi_next_element: erroneous xi sanity')
	  ie = -ie			!recorded in the loop
	  return
	end if

	!---------------------------------------
	! look for neighboring element
	!---------------------------------------

	iside = ia1
	ieb = lgr_ieltv(ia1,ie)
	if( ieb < 1 ) then	!no element or open boundary
	  ie = -ie
	  return
	end if

	if( bdebug ) then
	  write(6,*) ia1,ia2,ia3,ieb
	end if

	!---------------------------------------
	! look for side of particle in new element
	!---------------------------------------

	do ii=1,3
	  if( lgr_ieltv(ii,ieb) == ie ) exit
	end do
	if( ii > 3 ) then
	  call lgr_event(lgr_ev_next_ieltv,id,(/id,ie,in,it,ia1,ieb		&
     &		,lgr_ieltv(1,ieb),lgr_ieltv(2,ieb),lgr_ieltv(3,ieb)/),xi)
	  call lgr_internal_error(					&
     &		'error stop track_xi_next_element: erroneous ieltv')
	  ie = -ie			!recorded in the loop
	  iside = 0
	  return
	end if

	!---------------------------------------
	! copy xi to new elements
	!---------------------------------------

	ib1 = ii
	ib2 = mod(ib1,3) + 1
	ib3 = mod(ib2,3) + 1

	xiaux = xi

	xi(ib1) = 0.
	xi(ib2) = xiaux(ia3)
	xi(ib3) = xiaux(ia2)

	ie = ieb

	!---------------------------------------
	! end of routine
	!---------------------------------------

	end

!************************************************************

	function track_xi_vertex_u(id,istep,ncross)

! value in (0,1) that picks the side a particle on a vertex moves to
!
! This is not a random number, on purpose. It replaces random_number,
! whose generator was never seeded, so two runs of the same case
! picked differently. The value depends only on the particle id, the
! time step number and the crossings the particle has left in this
! time step: every run and every number of MPI processes makes the
! same pick, and two vertex events of one particle in one time step
! get different values, so the particle cannot cycle.
!
! Integer arithmetic modulo the prime m = 2**31-1 in integer*8: all
! products stay below 2**62, so no overflow and no floating point trap.
! Each step h -> (a*h+k)**5 mod m is one to one in k (gcd(5,m-1) = 1),
! so different crossing counts give different values.
! u = (h+1)/(m+2) with 0 <= h < m: 0 < u < 1, and u /= 0.5 since m+2 is odd.

	implicit none

	double precision track_xi_vertex_u
	integer, intent(in) :: id		!id of particle
	integer, intent(in) :: istep		!time step number
	integer, intent(in) :: ncross		!element crossings left in time step

	integer(kind=8), parameter :: m = 2147483647_8	!prime 2**31-1
	integer(kind=8), parameter :: a = 48271_8	!multiplier
	integer(kind=8) h,h2,h4
	integer(kind=8) k(2)
	integer i

	k(1) = modulo(int(istep,8),m)
	k(2) = modulo(int(ncross,8),m)

	h = modulo(int(id,8),m)
	do i=1,2
	  h = modulo(a*h+k(i),m)	!one to one in k(i)
	  h2 = modulo(h*h,m)
	  h4 = modulo(h2*h2,m)
	  h = modulo(h4*h,m)		!h**5, one to one, mixes the bits
	end do

	track_xi_vertex_u = dble(h+1) / dble(m+2)

	end

!************************************************************

	function track_xi_on_material_boundary(ie,xi)

! checks if particle is on material boundary (side table lgr_ieltv)

	use mod_lagrange_mpi, only : lgr_ieltv

	implicit none

	logical track_xi_on_material_boundary
	integer, intent(in) :: ie
	double precision, intent(in) :: xi(3)

	integer ii

	track_xi_on_material_boundary = .false.

	do ii=1,3
	  if( xi(ii) == 0. .and. lgr_ieltv(ii,ie) == 0 ) then
	    track_xi_on_material_boundary = .true.
	  end if
	end do

	end

!************************************************************

	function track_xi_has_layer(iel,lb)

	use levels

	implicit none

	logical track_xi_has_layer
	integer, intent(in) :: iel,lb

	if( iel < 1 ) then	!particle has left the domain: no layer to test
	  track_xi_has_layer = .true.
	else
	  track_xi_has_layer = ( ilhv(iel) >= lb )
	end if

	end

!************************************************************

	subroutine track_xi_side_test(ieorig,iel,iside,lb,bhas,icut)

! layer test of track_xi after track_xi_next_element moved a particle
! from ieorig through side iside to iel; bhas false means the particle is
! put back into ieorig (the caller does that)
!
! iel > 0: the element across has the layer (track_xi_has_layer)
! iel < 1 at a cut-off side (lgr_ieltv(iside,ieorig) <= -1000): the
!	element across is held by another process; its layers are
!	lgr_side_lmax(iside,ieorig). With the layer the particle goes on
!	there (icut = iside); without it it is put back as in a serial run
!	(counted in lgr_nputback)
! iel < 1 at any other side: the particle leaves the basin (bhas true)

	use mod_lagrange_mpi, only : lgr_ieltv, lgr_side_lmax, lgr_nputback

	implicit none

	integer, intent(in) :: ieorig		!element the particle left
	integer, intent(in) :: iel		!element from next_element
	integer, intent(in) :: iside		!side of ieorig it used
	integer, intent(in) :: lb		!layer of the particle
	logical, intent(out) :: bhas		!false: put the particle back
	integer, intent(inout) :: icut		!cut-off side (set if handed over)

	logical track_xi_has_layer

	if( iel < 1 .and. iside >= 1 .and. iside <= 3 ) then
	  if( lgr_ieltv(iside,ieorig) <= -1000 ) then	!cut-off side
	    bhas = ( lgr_side_lmax(iside,ieorig) >= lb )
	    if( bhas ) then
	      icut = iside
	    else
!$OMP ATOMIC
	      lgr_nputback = lgr_nputback + 1
	    end if
	    return
	  end if
	end if

	bhas = track_xi_has_layer(iel,lb)

	end

!************************************************************

	subroutine track_xi_adjust_layer(id,ieorig,iel,lb,z)

! adjusts layer when passing from one element to the next
!
! is only temporary - must also adjust w
!
! called inside the particle loop of drogue (track_xi) and by the
! hand-over (lgr_mpi_handover_round): a layer below the bottom of the
! element is an event of lgr_event (lgr_ev_wrong_layer: counted, the
! first kept, written at the end of the pass; #294: until then a line
! "warning: wrong layer" from inside the loop)

	use levels
	use mod_lagrange, only : lgr_event, lgr_ev_wrong_layer

	implicit none

	integer, intent(in) :: id
	integer, intent(in) :: ieorig
	integer, intent(in) :: iel
	integer, intent(inout) :: lb
	double precision, intent(inout) :: z

	integer lb2
	double precision z2

	integer lmax

	lmax = ilhv(iel)

	!call track_new_vert_pos(id,ieorig,iel,lb,lb2,z,z2)
	!lb = lb2
	!z = z2

	if( lb > lmax ) then
	  call lgr_event(lgr_ev_wrong_layer,id,(/id,iel,lb,lmax/))
	  lb = lmax
	  z = 1.
	end if

	end

!************************************************************
!************************************************************
!************************************************************

	subroutine track_new_vert_pos(id,ie1,ie2,lb1,lb2,z1,z2)

	use levels

	implicit none

	integer, intent(in) :: id
	integer, intent(in) :: ie1,ie2
	integer, intent(in) :: lb1
	integer, intent(out) :: lb2
	double precision, intent(in) :: z1
	double precision, intent(out) :: z2

	logical bdebug
	integer ierror
	integer nlvaux,nsigma
	integer lmax1,lmax2,l
	real hsigma
	real hl1(nlv)
	real hl2(nlv)
	real hp,hp1,hp2,hd
	real htot1,htot2,htotz1,htotz2

	real, parameter :: eps = 1.e-5

	call get_sigma_info(nlvaux,nsigma,hsigma)

	if( hsigma < 10000 ) then
	  stop 'error stop track_layer_thickness: hsigma'
	end if
	if( nsigma > 0 ) then
	  lb2 = lb1
	  z2 = z1
	  return
	end if

	bdebug = id == 341

	lmax1 = nlv
	call lagr_layer_thickness(ie1,lmax1,hl1,htot1,htotz1)

	ierror = 0

	if( lb1 > lmax1 .or. z1 < 0. .or. z1 > 1. ) then
	  ierror = 1
	else
	  hd = 0.
	  do l=1,lb1-1
	    hd = hd + hl1(l)
	  end do
	  hp1 = hd + hl1(lb1)*z1

	  lmax2 = nlv
	  call lagr_layer_thickness(ie2,lmax2,hl2,htot2,htotz2)

	  hp2 = hp1 * (htotz2/htotz1)

	  if( hp2 < 0 .or. hp2 > htot2 ) then
	    ierror = 2
	  else
	    hd = 0.
	    do l=1,lmax2
	      if( hd + hl2(l) >= hp2 ) exit
	      hd = hd + hl2(l)
	    end do

	    lb2 = l
	    if( lb2 > lmax2 ) then	!HACK
	      z2 = -1.
	    else
	      z2 = (hp2-hd)/hl2(l)
	    end if

	    if( lb2 > lmax2 .and. abs(z1-1.) < eps ) then
	      lb2 = lmax2
	      z2 = 0.
	    else if( z2 > 1. .and. abs(z1-1.) < eps ) then
	      z2 = 1.
	    end if
	    if( z2 > 1. .and. abs(z2-1.) < eps ) z2 = 1.

	    if( z2 < 0. .or. z2 > 1. ) ierror = 3
	    if( lb2 > lmax2 ) ierror = 3
	  end if
	end if

	if( ierror /= 0 ) then
	  write(6,*) 'debug track_new_vert_pos: ',id
	  write(6,*) ie1,lb1,lmax1,z1
	  write(6,*) ie2,lb2,lmax2,z2
	  if( ierror > 1 ) then
	    write(6,*) (hl1(l),l=1,lmax1)
	    write(6,*) (hl2(l),l=1,lmax2)
	    write(6,*) hd
	    write(6,*) hp1,htot1,htotz1
	    write(6,*) hp2,htot2,htotz2
	  end if
	  if( lb1 > lmax1 .or. lb2 > lmax2 ) ierror = 1
	  if( hp1 < 0. .or. hp1 > htotz1 ) ierror = 2
	  if( hp2 < 0. .or. hp2 > htotz2 ) ierror = 2
	  if( z1 < 0. .or. z1 > 1. ) ierror = 3
	  if( z2 < 0. .or. z2 > 1. ) ierror = 3
	  write(6,*) 'internal error: ',ierror
	  stop 'error stop track_new_vert_pos: internal error'
	end if

	end

!************************************************************
!************************************************************
!************************************************************

	subroutine track_xi_get_flux(id,iel,lb,iflux,alpha,vel)

! gets flux and vel information for element and layer (walls from the
! side table lgr_ieltv)
!
! a flux over a wall side is set to 0 and is an event of lgr_event
! (lgr_ev_wall_flux: counted, the first kept, written at the end of the
! pass; #294: until then a line "material boundary:" from inside the
! particle loop); the debug lines are off at compile time (bdebug, see
! track_xi)

	use mod_lagrange
	use mod_lagrange_mpi, only : lgr_ieltv
	use mod_hydro_vel

	implicit none

	integer, intent(in) :: id		!id of particle
	integer, intent(in) :: iel		!element number
	integer, intent(in) :: lb		!layer
	integer, intent(out) :: iflux		!node of flux line
	double precision, intent(out) :: alpha	!fraction of opsosite side
	double precision, intent(out) :: vel	!velocity in element (always positive)

	logical, parameter :: bdebug = .false.	!debug lines (#294)
	integer ii,in,io,nn,no,inext,imax
	real az,azt,u,v
	double precision flux(3)
	double precision fp,fm,fmmax,fact

	az = azlgr
	azt = 1. - az

	flux = flux3d(lb,:,iel)		!fluxes over side into element

	do ii=1,3
	  if( lgr_ieltv(ii,iel) .eq. 0 ) then	!closed boundary - set to 0
	    if( flux(ii) .ne. 0. ) then	!counted (#294)
	      call lgr_event(lgr_ev_wall_flux,id,(/id,iel,lb,ii/),(/flux(ii)/))
	      flux(ii) = 0.
	    end if
	  end if
	end do

	u = azt*ulov(lb,iel) + az*ulnv(lb,iel)
	v = azt*vlov(lb,iel) + az*vlnv(lb,iel)
	vel = sqrt(u*u+v*v)

	if( bdebug ) then
	  write(6,*) 'track_xi_get_flux: ',iel,lb
	  write(6,*) flux
	  write(6,*) vel
	end if

	in = 0
	io = 0
	nn = 0
	no = 0
	fp = 0.
	fm = 0.
	do ii=1,3
	  if( flux(ii) > 0. ) then	!flux into element
	    in = in + 1
	    nn = nn + ii
	    fp = fp + flux(ii)
	  else if( flux(ii) < 0. ) then
	    io = io + 1
	    no = no + ii
	    fm = fm - flux(ii)
	  end if
	end do

! fact is introduced to compense for flux if fp /= fm
! always scale to outgoing flux fm

	if( in == 1 .and. io > 0 ) then
	  iflux = -nn			!into this node
	  inext = mod(nn,3) + 1
	  fact = fm/fp
	  alpha = 1 + flux(inext)/fm
	else if( in == 2 .and. io > 0 ) then
	  iflux = 6 - nn		!out from this node
	  inext = mod(iflux,3) + 1
	  fact = fm/fp
	  alpha = 1 - flux(inext)/fp
	else if( io == 0 ) then		!only ingoing - do not advect
	  iflux = 0
	  alpha = 0.
	  vel = 0.
	  fact = 0.
	else if( in == 0 .and. io > 0 ) then	!only outgoing - special
	  imax = 0
	  fmmax = 0.
	  do ii=1,3
	    if( flux(ii) < fmmax ) then
	      fmmax = flux(ii)
	      imax = ii
	    end if
	  end do
	  iflux = imax
	  inext = mod(iflux,3) + 1
	  alpha = 1 - flux(inext)/fm
	  fact = 1.
	else				!just to be sure...
	  iflux = 0
	  alpha = 0.
	  vel = 0.
	  fact = 0.
	end if

	vel = vel * fact

	if( bdebug ) then
	  write(6,*) in,nn
	  write(6,*) iflux,inext
	  write(6,*) fp,fm,alpha
	  write(6,*) 'track_xi_get_flux end'
	end if

	if( bback ) iflux = -iflux

	alpha = dmin1(alpha,1.d0)
	alpha = dmax1(alpha,0.d0)

	end

!************************************************************

	subroutine track_xi_get_vertical(id,iel,lb,lmax,hd,w)

! the guard of the layer goes through lgr_internal_error (#256), its
! values through lgr_event (lgr_ev_vert_layer, #294)

	use mod_hydro_vel
	use levels, only : nlvdi,nlv
	use basin
	use mod_lagrange, only : lgr_event, lgr_ev_vert_layer

	implicit none

	integer, intent(in) :: id		!id of particle
	integer, intent(in) :: iel		!element number
	integer, intent(in) :: lb		!layer
	integer, intent(out) :: lmax		!maximum layers in element (return)
	double precision, intent(out) :: hd	!layer thickness (return)
	double precision, intent(out) :: w	!vertical velocity (return)

	integer ii,k
	real wo,wn
	real hl(nlv)
	real htot,htotz

	lmax = nlv
	call lagr_layer_thickness(iel,lmax,hl,htot,htotz)

	if( lb > lmax ) then
	  call lgr_event(lgr_ev_vert_layer,id,(/id,iel,lb,lmax/))
	  call lgr_internal_error(					&
     &		'error stop track_xi_get_vertical: no such layer')
	  hd = hl(lmax)			!recorded in the loop (#256): defined
	  w = 0.			!values, the caller stops the particle
	  return
	end if

	hd = hl(lb)

	w = 0.
	do ii=1,3
	  k = nen3v(ii,iel)
	  wo = wlov(lb,k) + wlov(lb-1,k)
	  wn = wlnv(lb,k) + wlnv(lb-1,k)
	  w = w + wo + wn
	end do

	w = w / 12.

	end

!************************************************************

	subroutine track_xi_check(text,id,xi)

! the guard of xi goes through lgr_internal_error (#256), its values and
! the text of the caller through lgr_event (lgr_ev_xi_check, #294)

	use mod_lagrange, only : lgr_event, lgr_ev_xi_check

	implicit none

	character*(*), intent(in) :: text
	integer, intent(in) :: id
	double precision, intent(in) :: xi(3)

	logical berror
	integer ii
	double precision tot,eps

	berror = .false.
	eps = 1.d-5

	tot = 0.d0
	do ii=1,3
	  tot = tot + xi(ii)
	  if( xi(ii) > 1.d0 ) berror = .true.
	  if( xi(ii) < 0.d0 ) berror = .true.
	end do
	if( abs(tot-1.d0) > eps ) berror = .true.

	if( berror ) then
	  call lgr_event(lgr_ev_xi_check,id,(/id/),xi,text)
	  ! recorded inside the particle loop (#256): the caller stops the
	  ! particle (lgr_internal_failed); elsewhere it aborts at once
	  call lgr_internal_error('error stop track_xi_check: wrong xi')
	end if

	end

!************************************************************

	subroutine track_xi_info_element(ie)

! prints information on element

	use mod_geom
	use mod_hydro_vel
	use levels, only : nlvdi,nlv
	use basin

	implicit none

	integer, intent(in) :: ie

	integer ii,k,lmax,l
	real hl(nlv)
	real htot,htotz

	write(6,*) 'info on element ',ie

	do ii=1,3
	  k = nen3v(ii,ie)
	  write(6,*) ii,k,xgv(k),ygv(k)
	end do

	write(6,*) (ieltv(ii,ie),ii=1,3)

	lmax = nlv
	call lagr_layer_thickness(ie,lmax,hl,htot,htotz)
	write(6,*) lmax,htot,htotz
	write(6,*) (hl(l),l=1,lmax)

	write(6,*) (ulov(l,ie),l=1,lmax)
	write(6,*) (vlov(l,ie),l=1,lmax)
	write(6,*) (ulnv(l,ie),l=1,lmax)
	write(6,*) (vlnv(l,ie),l=1,lmax)

	write(6,*) 'info on element end'

	end

!************************************************************

