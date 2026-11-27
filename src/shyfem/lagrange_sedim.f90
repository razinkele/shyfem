
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015,2018-2019  Georg Umgiesser
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

! simulates lagrangian sediment transport
!
! revision log :
!
! 06.05.2015	ccf	written from scratch
! 21.05.2015	ggu	changed VERS_7_1_11
! 17.07.2015	ggu	changed VERS_7_1_80
! 20.07.2015	ggu	changed VERS_7_1_81
! 16.11.2015	ggu	changed VERS_7_3_14
! 19.05.2017	ccf	include deposition and resuspension dynamics
! 25.10.2018	ggu	changed VERS_7_5_51
! 14.02.2019	ggu	changed VERS_7_5_56
! 16.02.2019	ggu	changed VERS_7_5_60
!
!*******************************************************************
!================================================================
        module lgr_sedim_module
!================================================================

        implicit none
        save

        integer                       :: nls     !number of sediment classes
        real, allocatable             :: gs(:)   !particle grain size [mm]
        real, allocatable             :: fr(:)   !fraction of sediment type [0-1]
        double precision, allocatable :: ws(:)   !particle settling velocity [mm/s]
        real, allocatable             :: tcd(:)  !critical stress deposition [N/m**2]
        real                          :: tce     !critical threshold for erosion [N/m**2]
        real, parameter               :: rfa = 0.5 !probabilistic factor [0.3-0.5]

!================================================================
        contains
!================================================================
!*******************************************************************
! initialize sediment classes, settling velocities and grainsizes
! still set by hand

        subroutine lgr_sedim_init

        implicit none

	integer ierr
	real                    :: maxtcd
        nls = 3
        !nls = 1

        allocate (gs(nls),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate (ws(nls),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate (fr(nls),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate (tcd(nls),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'

               ! clay  silt  sand
        !gs = (/0.004, 0.015, 0.1/)
        !ws = (/0.0001, 0.0010, 0.01/)
        !fr = (/0.2, 0.3, 0.5/)

        gs = (/0.001, 0.005, 0.010/)
        fr = (/0.34,0.33,0.33/)
        ws = (/0.003, 0.01, 0.03/)	!mm/s 
        ws = ws*0.001           	!from mm/s to m/s

        tce = 0.2
	tcd = 0.5*2800.*ws**1.03	!from sedtrans05

        maxtcd = maxval(tcd)
        if ( maxtcd > tce ) then
          write(6,*) 'maxtcd,tce: ',maxtcd,tce
          write(6,*) 'maxtcd must be < tce'
          stop 'error stop lgr_sedim_init'
	end if

        end subroutine lgr_sedim_init

!*******************************************************************
! the deposition test of a particle at the bed (#311), the one place of it
! (called by track_finish where the settling brings a particle to the bed,
! and by lgr_sediment for a particle at z = 1): the bottom stress tau at
! the position xi in the element ie and the draw r of the particle id in
! this step (lgr_random, site lgr_rnd_sedim, keyed on id and step: the
! same value wherever it is called in the step), and bdep, true if
! tau < tcd(nr) and r**(tau/tcd(nr)) >= rfa (probability 1 - rfa**(tcd/tau)
! for 0 < tau < tcd, 1 for tau = 0). nr is the sediment class, 1 ... nls.
! Reads module data only, so it can be called from the OpenMP particle loop

        subroutine lgr_dep_test(id,nr,ie,xi,tau,r,bdep)

        use basin, only : nen3v
        use mod_bstress, only : taubot
        use mod_lagrange_random, only : lgr_random, lgr_rnd_sedim

        implicit none

        integer, intent(in)           :: id	!id of the particle
        integer, intent(in)           :: nr	!sediment class
        integer, intent(in)           :: ie	!element (local, > 0)
        double precision, intent(in)  :: xi(3)	!internal coordinates
        real, intent(out)             :: tau	!bottom stress at the particle
        real, intent(out)             :: r	!the draw of the particle
        logical, intent(out)          :: bdep	!deposition test passed

        integer                       :: ii(3)
        real                          :: tcdp,perc

        tcdp = tcd(nr)			!deposition threshold
        ii   = nen3v(:,ie)
        tau  = sum(taubot(ii)*xi)	!bottom stress at particle position
        r    = lgr_random(id,lgr_rnd_sedim,0)	!random number
        bdep = .false.
        if( tau < tcdp ) then
          perc = r**(tau/tcdp)
          bdep = ( perc >= rfa )
        end if

        end subroutine lgr_dep_test

!*******************************************************************
! assign sediment class, settlign velocity and grainsize to particle
! called by subroutine lgr_set_properties
! the class is the particle's own draw (#225): lgr_random keyed on its id,
! the time step and the site lgr_rnd_sedclass

        subroutine lgr_set_sedim(id,sc,sv,sg,nc)

        use mod_lagrange_random, only : lgr_random, lgr_rnd_sedclass

        implicit none

        integer, intent(in)           :: id	!id of the particle
        integer, intent(out)          :: sc	!sediment class
        double precision, intent(out) :: sv	!settling velocity [m/s]
	real, intent(out)             :: sg	!sediment grainsize
	integer, intent(out)          :: nc	!number of custom properties

	real                          :: r
	integer                       :: nr,na
	integer, parameter            :: nperc=100
	integer, allocatable          :: array(:)
	integer                       :: n,n1,n2
	integer                       :: ierr

!----------------------------------------------------------------
! Create array with index values according to fractions
!----------------------------------------------------------------

        allocate(array(nperc),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'

	n1 = 0
	n2 = 0
	do n = 1,nls
	  if (n .eq. 1) then
	    n1 = 1
	  else
	    n1 = n1 + fr(n-1) * nperc
	  end if
	  n2 = n2 + fr(n) * nperc
	  array(n1:n2) = n
	end do

!----------------------------------------------------------------
! Get random weighted index from array
!----------------------------------------------------------------

        r = lgr_random(id,lgr_rnd_sedclass,0)
	na = r*nperc + 1
	na = min(nperc,na)
	nr = array(na)

!----------------------------------------------------------------
! Set properties
!----------------------------------------------------------------

	sv = ws(nr)
	sg = ws(nr)
	sg = gs(nr)
	sc = nr

	nc = 1

	end subroutine lgr_set_sedim

!================================================================
        end module lgr_sedim_module
!================================================================

!*******************************************************************
! Sediment dynamics (must be that tcd < tce)
! if tau < tcd       particle sinks and could deposit  
! if tcd < tau < tce particle stays in suspension 
! if tau > tce       particle on bottom could be resuspended 
!
! Probablility of deposition/erosion is function of tau
!
! the draw of a particle is its own (#225): lgr_random keyed on its id, the
! time step and the site lgr_rnd_sedim
!
! the type of a particle is its sediment class (1 ... nls, lgr_set_sedim);
! a deposited particle has the layer -1, not another type. A negative type
! marks a beached particle (lag_beach sets ty = -ty): it sits on the shore
! and moves no more (track_body_xi, diff_body and lag_stk skip it), so it
! neither deposits nor is eroded and is skipped here. Before, its negative
! type was used as the class and tcd(nr) was read outside the array (a
! run-time error with -fcheck=bounds, a value from outside tcd otherwise).
! Any other type outside 1 ... nls (a particle file of a run without
! sediment read with lgrini) stops the run.

	subroutine lgr_sediment

        use basin
        use mod_diff_visc_fric
	use mod_lagrange
	use lgr_sedim_module
	use levels

	implicit none

	integer                 :: i,ie,l
	integer			:: lb,lmax
	real                    :: z
	integer, save           :: icall = 0 
        integer                 :: nr
	double precision	:: sv
	real		        :: tau
	real                    :: r,perc
	logical			:: bdep
	integer			:: id
        double precision 	:: xi(3)

!-----------------------------------------------------
! initialization
!-----------------------------------------------------

	if( icall .eq. 0 ) then
	  write(6,*)'Initialization on lagrangian sediment model'
	  bcompress = .false.
	  icall = 1
	end if

!-----------------------------------------------------
! the bottom shear stress is computed once per step by lagrange, before
! the tracking (#311: track_finish needs it)
!-----------------------------------------------------

!-----------------------------------------------------
! Loop over particles
!-----------------------------------------------------

	do i = 1,nbdy
          id = lgr_ar(i)%id
	  ie   = lgr_ar(i)%actual%ie
          if ( ie < 1 ) cycle
	  nr   = lgr_ar(i)%type		!sediment class id, < 0 if beached
	  if ( nr < 0 ) cycle		!beached: on the shore (see above)
          lmax = ilhv(ie)
	  lb   = lgr_ar(i)%actual%l		!layer were particle is located
	  if ( lb > 0 .and. lb /= lmax ) cycle	!skip if particle is not on bottom layer 
	  sv   = lgr_ar(i)%sinking
	  if ( sv == 0.d0 ) cycle	!skip if it has settling velocity = 0
          z    = lgr_ar(i)%actual%z	!rel. depth   0=surface  1=bottom
	  if ( nr < 1 .or. nr > nls ) then
	    write(6,*) 'lgr_sediment: particle ',id,' has the type ',nr	&
     &			,', not a sediment class 1 ... ',nls
	    call shympi_abort_internal('error stop lgr_sediment: particle'	&
     &		//' type is not a sediment class')
	  end if
          xi   = lgr_ar(i)%actual%xi(:)
	  call lgr_dep_test(id,nr,ie,xi,tau,r,bdep)	!stress, draw, test

!         -----------------------------------------------------
!         Deposition of particle 
!         -----------------------------------------------------
          if ( tau < tcd(nr) ) then
            if ( lb /= -1 .and. z == 1. .and. bdep ) then 
               lgr_ar(i)%actual%l = -1    		!particle reached bottom
            end if

!         -----------------------------------------------------
!         Erosion of particle, otherwise keep in suspension
!         -----------------------------------------------------
          else if ( tau > tce ) then
            perc = r**(tce/tau)
            if ( lb == -1 .and. perc >= rfa ) then
	      lgr_ar(i)%actual%l = lmax
	      lgr_ar(i)%actual%z = 0.7**((perc-rfa)/(1.-rfa)) !between 0.7 and 1
            end if

          end if

        end do

!----------------------------------------------------------------
! end of routine
!----------------------------------------------------------------

	end subroutine lgr_sediment

!*******************************************************************
