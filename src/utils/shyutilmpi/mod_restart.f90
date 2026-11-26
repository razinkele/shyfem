
!--------------------------------------------------------------------------
!
!    Copyright (C) 2004,2006,2008-2012,2014-2015,2014-2015  Georg Umgiesser
!    Copyright (C) 2017-2020  Georg Umgiesser
!    Copyright (C) 2012  Andrea Cucco
!    Copyright (C) 2014  Christian Ferrarin
!    Copyright (C) 2018  Marco Bajo
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

! modules for restart routines
!
! 08.03.2025    ggu     extract module for restart routines
! 24.11.2026    arb     gathered arrays labelled for the ghost check (#268)
! 26.11.2026    arb     version 20 (#303 #304)
! 26.11.2026    arb     btool_rst, iheatflag_rst: the tools on version 20
!
! notes :
!
!  |--------|---------|------------|--------------|--------------|
!  | ityrst | no file | file empty ! itrec/=itrst ! itrec==itrst !
!  |--------|---------|------------|--------------|--------------|
!  |   0    |  error  |   error    |     error    |    warm      |
!  |--------|---------|------------|--------------|--------------|
!  |   1    |  cold   |   error    |     error    |    warm      |
!  |--------|---------|------------|--------------|--------------|
!  |   2    |  cold   |   cold     |     warm     |    warm      |
!  |--------|---------|------------|--------------|--------------|
!
! versions :
!
! <3	not supported
! 3	write hydro
! 4	write hm3v
! 5	write saltv,tempv,rhov
! 6	write conv (tracer)
! 7	write wlnv (vertical velocity)
! 8	write ecological variables
! 9	write date,time
! 10	write hlv
! 11	write atime, write idfile (regular header)
! 12	mercury restart
! 13	write ilhv and ilhkv
! 14	write vertical only for nlv > 1
! 15	write gotm arrays
! 16	adapted for mpi
! 17	write bfm restart
! 18	read only: upstream shyfemcm layout (iwetv, zov, zeov after vtlnv)
! 19	write simple-sediment bed mass (conza) (N25)
! 20	write iwetv, evapv, windcd, heat flag, tws, dtw after vtlnv; with
!	iturb = 2, write tken, eps, visv, difv after iturb
!
!*********************************************************************

!=====================================================================
	module mod_restart
!=====================================================================

	implicit none

	logical, save :: bok_rst = .false.	!restart file has been read
	integer, save :: nvers_rst = 0
	integer, save :: iflag_want_rst  = -1
	integer, save :: iflag_avail_rst = -1

	integer, save :: idfrst = 749652	!id for restart file

	! version history (fork): 17 = last common version with upstream;
	! 18 = READ-ONLY, upstream shyfemcm layout (old-time-level hydro:
	! iwetv, zov, zeov) - never written by this fork (the fork briefly
	! wrote 18 with the ssedi layout 2026-07-21/22 only; such files
	! fail to read and must be regenerated); 19 = ssedi bed-mass block;
	! 20 = the hydro block also holds iwetv, evapv, windcd, a heat flag
	! and tws/dtw, and the turbulence block of a k-epsilon run (iturb =
	! 2) tken, eps, visv and difv (this fork, what we write, #303 #304)
	integer, save :: nvmax = 20		!last version of file
	integer, parameter :: nidmax = 10

	integer, save :: id_hydro_rst = 1	!1		hydro
	integer, save :: id_depth_rst = 2	!10		depth
	integer, save :: id_barcl_rst = 3	!100		t/s/rho
	integer, save :: id_conz_rst  = 4	!1000		tracer
	integer, save :: id_wvert_rst = 5	!10000		vertical vel.
	integer, save :: id_eco_rst   = 6	!100000		ecology
	integer, save :: id_merc_rst  = 7	!1000000	mercury
	integer, save :: id_gotm_rst  = 8	!10000000	gotm
	integer, save :: id_bfm_rst   = 9	!100000000	bfm
	integer, save :: id_ssedi_rst = 10	!1000000000	sediment bed mass

	integer, save :: ibarcl_rst = 0
	integer, save :: iconz_rst  = 0
	integer, save :: iwvert_rst = 0
	integer, save :: ieco_rst   = 0
	integer, save :: imerc_rst  = 0
	integer, save :: iturb_rst  = 0		!the writer's iturb (v >= 15):
						!the turbulence block holds
						!GOTM's arrays only if 1 (#304);
						!also set by rst_skip_record
	integer, save :: iheatflag_rst = 0	!the writer's heat flag (v20:
						!1 if qflux3d ran), set by
						!rst_skip_record (rstinf), 0
						!before version 20

	logical, save :: bsetweg_rst = .false.	!the record read restored
						!iwetv (v20): reset the
						!setweg clock (#303)
	logical, save :: btool_rst = .false.	!a tool (rst2shy) reads the
						!file: no parameter table and
						!no meteo arrays, so
						!rst_read_hydro_v20 reads its
						!records past, never applies
						!them (rst_read_keps does so
						!when id 8 is not wanted)

	character*20, save :: descript_rst(nidmax) = (/    &
     &		 'hydrodynamics       '    &
     &		,'depth               '    &
     &		,'T/S/rho             '    &
     &		,'tracer concentration'    &
     &		,'vertical velocities '    &
     &		,'ecological model    '    &
     &		,'mercury model       '    &
     &		,'gotm turb model     '    &
     &		,'bfm model           '    &
     &		,'sediment bed mass   '    &
     &						/)

	real, save, allocatable :: hlvrst(:)
	integer, save, allocatable :: ilhrst(:)
	integer, save, allocatable :: ilhkrst(:)

	logical, save :: bmaster = .false.
	integer, save :: nitem_rst = 0	!arrays gathered in this record (#268)

        INTERFACE restart_write_value
        MODULE PROCEDURE   restart_write_value_scalar_i  &
     &                    ,restart_write_value_scalars_i &
     &                    ,restart_write_value_2d_i      &
     &                    ,restart_write_value_2d_r      &
     &                    ,restart_write_value_3d_r      &
     &                    ,restart_write_value_3d_d      &
     &                    ,restart_write_value_fix_r
        END INTERFACE

        INTERFACE restart_read_value
        MODULE PROCEDURE   restart_read_value_2d_i    &
     &                    ,restart_read_value_2d_r    &
     &                    ,restart_read_value_3d_r    &
     &                    ,restart_read_value_3d_d    &
     &                    ,restart_read_value_fix_r
        END INTERFACE

	private :: restart_check_ios

!=====================================================================
	contains
!=====================================================================

	function get_nv_global(nv_local)

	use shympi

	integer get_nv_global
	integer nv_local

	integer nv_global

	nv_global = nlv_global
        if( nv_local /= nlv_local ) then
          if( nv_local == nlv_local+1 ) then
            nv_global = nv_global + 1
          else
	    write(6,*) nv_local,nlv_local
            stop 'error stop get_nv_global: nv incompatible'
          end if
        end if

	get_nv_global = nv_global

	end function
	
!--------------------------------

	function get_nn_global(belem,nn)

	use shympi

	integer get_nn_global
	logical belem
	integer nn

	integer nn_global

        if( belem ) then
	  nn_global = nel_global
          if( nn /= nel_local ) goto 99
        else
	  nn_global = nkn_global
          if( nn /= nkn_local ) goto 99
        end if

	get_nn_global = nn_global

        return
   99   continue
        write(6,*) belem,nn,nel_local,nkn_local
        stop 'error stop get_nn_global: internal error'
	end function
	
!--------------------------------

	subroutine restart_write_start

! a restart record begins: its gathered arrays are counted again (#268)

	nitem_rst = 0

	end subroutine

!--------------------------------

	subroutine restart_gather_label(iu,label)

! names the next gathered array of the restart record, for the ghost
! check of the gather (shympi_l2g_array, #268): file and array number;
! blank when the check is off

	use shympi, only : shympi_ghost_check_on

	integer, intent(in) :: iu
	character*(*), intent(out) :: label

	integer ios,islash
	character*256 name
	character*300 aux		!long enough for any file name

	nitem_rst = nitem_rst + 1
	label = ' '
	if( .not. shympi_ghost_check_on() ) return	!no label needed

	name = ' '
	if( bmaster ) then		!only the master has the file open
	  inquire(unit=iu,name=name,iostat=ios)
	  if( ios /= 0 ) name = ' '
	end if
	islash = index(name,'/',back=.true.)
	write(aux,'(a,i0)') 'restart file ' // trim(name(islash+1:)) &
     &			// ' array ',nitem_rst
	label = aux			!as much as label holds

	end subroutine

!--------------------------------

	subroutine restart_write_value_scalar_i(iu,ival)

	integer iu
	integer ios
	integer ival

	if( bmaster ) then
	  write(iu,iostat=ios) ival
	  call restart_check_ios(ios,'restart_write_value_scalar_i ival',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_scalars_i(iu,n,ivals)

	integer iu
	integer ios
	integer n
	integer ivals(n)

	if( bmaster ) then
	  write(iu,iostat=ios) ivals
	  call restart_check_ios(ios,'restart_write_value_scalars_i ivals',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_2d_i(iu,belem,array)

	use shympi

	integer, intent(in) :: iu
	integer ios
	logical, intent(in) :: belem
	integer, intent(in) :: array(:)

	integer nn_global,nn
	integer ierr
	character*80 label
	integer, allocatable :: garray(:)

	if( bmpi ) then
	  nn = size(array)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  call restart_gather_label(iu,label)
	  call shympi_l2g_array(array,garray,label)
	  if( bmaster ) then
	    write(iu,iostat=ios) garray
	    call restart_check_ios(ios,'restart_write_value_2d_i garray',.true.)
	  end if
	else
	  write(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_write_value_2d_i array',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_2d_r(iu,belem,array)

	use shympi

	integer, intent(in) :: iu
	integer ios
	logical, intent(in) :: belem
	real, intent(in) :: array(:)

	integer nn_global,nn
	integer ierr
	character*80 label
	real, allocatable :: garray(:)

	if( bmpi ) then
	  nn = size(array)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  call restart_gather_label(iu,label)
	  call shympi_l2g_array(array,garray,label)
	  if( bmaster ) then
	    write(iu,iostat=ios) garray
	    call restart_check_ios(ios,'restart_write_value_2d_r garray',.true.)
	  end if
	else
	  write(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_write_value_2d_r array',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_3d_r(iu,belem,array)

	use shympi

	integer, intent(in) :: iu
	integer ios
	logical, intent(in) :: belem
	real, intent(in) :: array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	character*80 label
	real, allocatable :: garray(:,:)

	if( bmpi ) then
	  nn = size(array,2)
	  nv_global = get_nv_global(size(array,1))
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nv_global,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  call restart_gather_label(iu,label)
	  call shympi_l2g_array(array,garray,label)
	  if( bmaster ) then
	    write(iu,iostat=ios) garray
	    call restart_check_ios(ios,'restart_write_value_3d_r garray',.true.)
	  end if
	else
	  write(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_write_value_3d_r array',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_3d_d(iu,belem,array)

	use shympi

	integer, intent(in) :: iu
	integer ios
	logical, intent(in) :: belem
	double precision, intent(in) :: array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	character*80 label
	double precision, allocatable :: garray(:,:)

	if( bmpi ) then
	  nn = size(array,2)
	  nv_global = get_nv_global(size(array,1))
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nv_global,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  call restart_gather_label(iu,label)
	  call shympi_l2g_array(array,garray,label)
	  if( bmaster ) then
	    write(iu,iostat=ios) garray
	    call restart_check_ios(ios,'restart_write_value_3d_d garray',.true.)
	  end if
	else
	  write(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_write_value_3d_d array',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_write_value_fix_r(iu,belem,nfix,array)

	use shympi

	integer, intent(in) :: iu
	integer ios
	logical, intent(in) :: belem
	integer, intent(in) :: nfix
	real, intent(in) :: array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	character*80 label
	real, allocatable :: garray(:,:)

	if( bmpi ) then
	  if( size(array,1) /= nfix ) then
	    stop 'error stop restart_write_value_fix: nv incompatible'
	  end if
	  nn = size(array,2)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nfix,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  call restart_gather_label(iu,label)
	  call shympi_l2g_array(nfix,array,garray,label)
	  if( bmaster ) then
	    write(iu,iostat=ios) garray
	    call restart_check_ios(ios,'restart_write_value_fix_r garray',.true.)
	  end if
	else
	  write(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_write_value_fix_r array',.true.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_read_value_2d_i(iu,belem,array)

	use shympi

	integer iu
	integer ios
	logical belem
	integer array(:)

	integer nn_global,nn
	integer ierr
	integer, allocatable :: garray(:)

	if( bmpi ) then
	  nn = size(array)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  read(iu,iostat=ios) garray
	  call restart_check_ios(ios,'restart_read_value_2d_i garray',.false.)
	  call shympi_g2l_array(garray,array)
	else
	  read(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_read_value_2d_i array',.false.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_read_value_2d_r(iu,belem,array)

	use shympi

	integer iu
	integer ios
	logical belem
	real array(:)

	integer nn_global,nn
	integer ierr
	real, allocatable :: garray(:)

	if( bmpi ) then
	  nn = size(array)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  read(iu,iostat=ios) garray
	  call restart_check_ios(ios,'restart_read_value_2d_r garray',.false.)
	  call shympi_g2l_array(garray,array)
	else
	  read(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_read_value_2d_r array',.false.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_read_value_3d_r(iu,belem,array)

	use shympi

	integer iu
	integer ios
	logical belem
	real array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	real, allocatable :: garray(:,:)

	if( bmpi ) then
	  nn = size(array,2)
	  nv_global = get_nv_global(size(array,1))
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nv_global,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  read(iu,iostat=ios) garray
	  call restart_check_ios(ios,'restart_read_value_3d_r garray',.false.)
	  call shympi_g2l_array(garray,array)
	else
	  read(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_read_value_3d_r array',.false.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_read_value_3d_d(iu,belem,array)

	use shympi

	integer iu
	integer ios
	logical belem
	double precision array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	double precision, allocatable :: garray(:,:)

	if( bmpi ) then
	  nn = size(array,2)
	  nv_global = get_nv_global(size(array,1))
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nv_global,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  read(iu,iostat=ios) garray
	  call restart_check_ios(ios,'restart_read_value_3d_d garray',.false.)
	  call shympi_g2l_array(garray,array)
	else
	  read(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_read_value_3d_d array',.false.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_read_value_fix_r(iu,belem,nfix,array)

	use shympi

	integer iu
	integer ios
	logical belem
	integer nfix
	real array(:,:)

	integer nn_global,nv_global,nn
	integer ierr
	real, allocatable :: garray(:,:)

	if( bmpi ) then
	  if( size(array,1) /= nfix ) then
	    stop 'error stop restart_read_value_fix: nv incompatible'
	  end if
	  nn = size(array,2)
	  nn_global = get_nn_global(belem,nn)
	  allocate(garray(nfix,nn_global),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  read(iu,iostat=ios) garray
	  call restart_check_ios(ios,'restart_read_value_fix_r garray',.false.)
	  call shympi_g2l_array(garray,array)
	else
	  read(iu,iostat=ios) array
	  call restart_check_ios(ios,'restart_read_value_fix_r array',.false.)
	end if

	end subroutine

!--------------------------------

	subroutine restart_check_ios(ios,name,bwrite)

! aborts cleanly (collective-safe) if a bulk restart payload record
! could not be written or read, instead of an uncontrolled runtime
! crash - same diagnostics as rst_check_write/rst_check_read in
! restart.f90 (which this library module cannot call)

	integer, intent(in) :: ios
	character*(*), intent(in) :: name
	logical, intent(in) :: bwrite

	if( ios == 0 ) return

	if( bwrite ) then
	  write(6,*) 'error writing restart file record: ',trim(name)
	else
	  write(6,*) 'error reading restart file record: ',trim(name)
	end if
	write(6,*) 'iostat = ',ios
	if( .not. bwrite .and. ios < 0 ) then
	  write(6,*) 'unexpected end of file - restart record is truncated'
	end if

	flush(6)
	if( bwrite ) then
	  call shympi_abort_internal('restart: failed write of '//trim(name))
	else
	  call shympi_abort_internal('restart: failed read of '//trim(name))
	end if

	end subroutine restart_check_ios

!=====================================================================
	end module mod_restart
!=====================================================================

