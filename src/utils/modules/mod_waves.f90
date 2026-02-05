
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015-2017,2019  Georg Umgiesser
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

! revision log :
!
! 10.07.2015	ggu	changed VERS_7_1_50
! 15.04.2016	ggu	changed VERS_7_5_8
! 05.12.2017	ggu	changed VERS_7_5_39
! 16.02.2019	ggu	changed VERS_7_5_60
! 21.05.2019	ggu	changed VERS_7_5_62

!**************************************************************************

!==================================================================
        module mod_waves
!==================================================================

        implicit none

        integer, private, save  :: nkn_waves = 0
        integer, private, save  :: nlv_waves = 0
        integer, private, save  :: nel_waves = 0

        integer, save  :: iwave  = 0	! call parameter to the wave model
        integer, save  :: iwwm   = 0	! type of shyfem-wwm coupling
        integer, save  :: idcoup = 0	! shyfem-wwm coupling time step [s]

        real, allocatable, save :: waveh(:)  !significant wave height [m]
        real, allocatable, save :: wavep(:)  !wave mean period [s]
        real, allocatable, save :: wavepp(:) !wave peak period [s]
        real, allocatable, save :: waved(:)  !mean wave direction [deg]
        real, allocatable, save :: waveov(:) !wave bottom orbital velocity [m/s]

        real, allocatable, save :: wavefx(:,:)	! wave forcing term in x
        real, allocatable, save :: wavefy(:,:)	! wave forcing term in y

        double precision, save  :: da_wav(4) = 0

! --- Unit numbers for WWM pipe files (used with newunit=)
! --- Writing units (SHYFEM -> WWM)
        integer, save :: iu_velx = -1      ! p_velx.dat (unit 120)
        integer, save :: iu_vely = -1      ! p_vely.dat (unit 121)
        integer, save :: iu_lev = -1       ! p_lev.dat (unit 122)
        integer, save :: iu_bot = -1       ! p_bot.dat (unit 123)
        integer, save :: iu_windx = -1     ! p_windx.dat (unit 124)
        integer, save :: iu_windy = -1     ! p_windy.dat (unit 125)
        integer, save :: iu_zeta3d = -1    ! p_zeta3d.dat (unit 126)

! --- Reading units (WWM -> SHYFEM)
        integer, save :: iu_stressx = -1   ! p_stressx.dat (unit 101)
        integer, save :: iu_stressy = -1   ! p_stressy.dat (unit 102)
        integer, save :: iu_waveh = -1     ! p_waveh.dat (unit 103)
        integer, save :: iu_wavet = -1     ! p_wavet.dat (unit 104)
        integer, save :: iu_waved = -1     ! p_waved.dat (unit 105)
        integer, save :: iu_wtauw = -1     ! p_wtauw.dat (unit 106)
        integer, save :: iu_wavetp = -1    ! p_wavetp.dat (unit 107)
        integer, save :: iu_wavewl = -1    ! p_wavewl.dat (unit 108)
        integer, save :: iu_orbit = -1     ! p_orbit.dat (unit 109)
        integer, save :: iu_stokesx = -1   ! p_stokesx.dat (unit 110)
        integer, save :: iu_stokesy = -1   ! p_stokesy.dat (unit 111)
        integer, save :: iu_cd = -1        ! p_cd.dat (unit 114)
        integer, save :: iu_jpress = -1    ! p_jpress.dat (unit 115)
        integer, save :: iu_wdiss = -1     ! p_wdiss.dat (unit 116)
        integer, save :: iu_stresxy = -1   ! p_stresxy.dat (unit 142)

!==================================================================
        contains
!==================================================================

        subroutine mod_waves_init(nkn,nel,nlv)

        integer  :: nkn
        integer  :: nel
        integer  :: nlv
        integer  :: ierr

        if( nlv == nlv_waves .and. nel == nel_waves .and. nkn == nkn_waves ) return

        if( nlv > 0 .or. nel > 0 .or. nkn > 0 ) then
          if( nlv == 0 .or. nel == 0 .or. nkn == 0 ) then
            write(6,*) 'nlv,nel,nkn: ',nlv,nel,nkn
            stop 'error stop mod_waves_init: incompatible parameters'
          end if
        end if

        if( nkn_waves > 0 ) then
          deallocate(waveh)
          deallocate(wavep)
          deallocate(wavepp)
          deallocate(waved)
          deallocate(waveov)
          deallocate(wavefx)
          deallocate(wavefy)
        end if

        nlv_waves = nlv
        nel_waves = nel
        nkn_waves = nkn

        if( nkn == 0 ) return

        allocate(waveh(nkn),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(wavep(nkn),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(wavepp(nkn),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(waved(nkn),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(waveov(nkn),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(wavefx(nlv,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(wavefy(nlv,nel),stat=ierr)
        if( ierr /= 0 ) stop 'error stop: allocation failed'

	waveh = 0.
	wavep = 0.
	wavepp = 0.
	waved = 0.
	waveov = 0.
	wavefx = 0.
	wavefy = 0.

        end subroutine mod_waves_init

!==================================================================
        end module mod_waves
!==================================================================

