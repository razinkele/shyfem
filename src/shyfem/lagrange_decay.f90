
!--------------------------------------------------------------------------
!
!    Copyright (C) 2009-2010,2012,2014-2015,2018-2019  Georg Umgiesser
!    Copyright (C) 2012  Michol Ghezzo
!    Copyright (C) 2012  Francesca De Pascalis
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

! decay of particles
!
! revision log :
!
! 05.02.2009	ggu	copied from other files
! 23.03.2010	ggu	changed v6.1.1
! 16.02.2012	mcg&fdp	new way to kill particles...
! 08.10.2012	ggu	changed VERS_6_1_58
! 25.10.2012	ggu	changed VERS_6_1_59
! 28.03.2014	ggu	new version of decay (for all particles)
! 05.05.2014	ggu	changed VERS_6_1_74
! 12.12.2014	ggu	changed VERS_7_0_9
! 19.12.2014	ggu	changed VERS_7_0_10
! 21.05.2015	ggu	changed VERS_7_1_11
! 16.11.2015	ggu	changed VERS_7_3_14
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 13.03.2019	ggu	changed VERS_7_5_61
!
!**********************************************************************

        subroutine lagr_func(n)

! handles decay of particles

	use femtime

        use para
        implicit none
        
        integer n
        
        
        integer, save :: lcall = 0

        if( lcall .lt. 0 ) return

        if( lcall .eq. 0 ) then
          lcall = nint(getpar('lcust'))
          if( lcall .le. 0 ) lcall = -1
        end if

        if( lcall .eq.  1 ) call lagr_decay(n)   
        if( lcall .eq.  2 ) call lagr_conc(n)
        if( lcall .eq.  3 ) call lagr_surv(n)

        end

!**********************************************************************

        subroutine lagrange_decay(ldecay)

! applies decay to all particles
!
! decay with the e-folding time ldecay [s] (#246): in each time step a
! particle decays with the probability 1 - exp(-dta/ldecay), dta the part
! of the step it has lived (the step dt_act, or its age t_act - init%time
! if it was released inside the step), so that after a time t since its
! release a particle has survived with the probability exp(-t/ldecay)
! whatever the time step. The test is the particle's own draw (#225):
! lgr_random_dp, keyed on its id, the time step and the site
! lgr_rnd_decay, in double precision (the probability of a step can lie
! below the 2**-23 that a single precision draw resolves). Before #246
! every step tested the survival of the particle's whole age,
! exp(-age/ldecay), with a new draw, so the survival after t was about
! exp(-t**2/(2*ldecay*dt)) and depended on the time step.
!
! a decayed particle keeps its last element with a negative sign
! (ie = -abs(ie)), as a particle that left the basin and one that died in
! lagr_surv: it is not tracked any more and the output writes its last
! position in the exited block (#226; before, ie = 0 made the output read
! the coordinates of element 0)

	use mod_lagrange
	use femtime, only : t_act,dt_act
	use mod_lagrange_random, only : lgr_random_dp, lgr_rnd_decay

        implicit none

	real, intent(in) :: ldecay	!e-folding time of the decay [s]

	double precision dta	!part of the step the particle has lived [s]
	double precision pdec	!probability to decay in this step
        integer i

	integer, save :: iwarn1 = 0

        if( ldecay .le. 0. ) then
          if( iwarn1 == 0 ) then
            write(6,*) 'lagrange_decay: ldecay <= 0, decay disabled'
            iwarn1 = 1
          end if
          return
        end if

        do i=1,nbdy
	  if( lgr_ar(i)%actual%ie <= 0 ) cycle	!already out, no draw
          dta = min(dt_act,t_act-lgr_ar(i)%init%time)
	  if( dta <= 0.d0 ) cycle		!released at the end of the step
          pdec = 1.d0 - exp(-dta/ldecay)
          if( lgr_random_dp(lgr_ar(i)%id,lgr_rnd_decay,0) < pdec ) then
	    lgr_ar(i)%actual%ie = -abs(lgr_ar(i)%actual%ie)	!out of domain
	  end if
        end do

        end

!**********************************************************************

        subroutine lagr_decay(n)

! in funzione di un decadimento esponenziale con
! tempo di dimezzamento TDC particella n-esima
! di eta' pari a Dt sara' soggetta dopo un
! intervallo di tempo TIME ad una % di sopravvivenza
! RDC pari a 1-(1/(e^(TIME/Dt))).
! Con Random Walk determino numero casuale tra 0-1,
! se tale numero cade nell'intervallo di mortalita'
! allora la particella sparisce dal calcolo

	use mod_lagrange
	use femtime
	use mod_lagrange_random, only : lgr_random, lgr_rnd_decay

        implicit none

	real rdc    !tasso di mortalita'
        real dt     !eta' della particella n-esima

        real nmb
        real tdd
        integer n,i

	integer, save :: iwarn2 = 0

        if( tdecay .le. 0. ) then
          if( iwarn2 == 0 ) then
            write(6,*) 'lagr_decay: tdecay <= 0, decay disabled'
            iwarn2 = 1
          end if
          return
        end if

        dt=it-lgr_ar(n)%init%time
        tdd=exp(dt/tdecay)

        rdc=1-(1/tdd)

        nmb=lgr_random(lgr_ar(n)%id,lgr_rnd_decay,0)	!own draw (#225)

        if(nmb.le.rdc) then			! set as if out of domain
	  lgr_ar(n)%actual%ie = -abs(lgr_ar(n)%actual%ie)	! last element (#226)
	end if

        end

!*********************************************************************

        subroutine lagr_conc(i)

	use mod_lagrange
	use femtime
	use mod_physical_constants, only : pi => pi_sp

        implicit none

        integer i

        real time,a,b,c,di

        real, save :: m = 150000	!mg/l

        if(it.le.lgr_ar(i)%init%time) return

        time=it-lgr_ar(i)%init%time
        a=2*sqrt(pi*time*rwhpar)
        b=m/a
        di=b*exp(-1.)
        lgr_ar(i)%custom(1)=di

        end 
                
!**********************************************************************

	subroutine lagr_surv(i)

! particles older than tdead are eliminated

	use mod_lagrange
	use femtime

        implicit none

	integer, save :: icount = 0

	integer i
	integer, save :: icall = 0

	real t	    !time of simulation
	real ts	    !start time of particle
	real deltat !t-ts age of the particle
	real tdead  !time to live

	real pdead,psurv !death or survival probability 
	
	!tdead = 0 
	!tdead = 30.5*86400
	!tdead = 45*86400
	!tdead = 65*86400
	tdead = pld_day ![sec]

	if( icall .eq. 0 ) then
	  write(6,*) 'WARNING tdead (lagrange_decay):',tdead
	  icall=1
	endif

	if( tdead .le. 0 ) return

	t = it 
	ts = lgr_ar(i)%init%time

	deltat = t-ts		!age of particle

	pdead = deltat/tdead
	psurv = 1-pdead

	if( psurv .le. 0 ) then	!particle is dead
	  icount = icount+1 
!	  write(77,*) it,i,icount,deltat
	  lgr_ar(i)%actual%ie = -abs(lgr_ar(i)%actual%ie)	!stays out (#226)
	endif

	end 

!**********************************************************************

