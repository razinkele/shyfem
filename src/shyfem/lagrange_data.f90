
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015-2020  Georg Umgiesser
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
! 16.11.2015	ggu	changed VERS_7_3_14
! 19.02.2016	ggu	changed VERS_7_5_2
! 31.03.2017	ggu	changed VERS_7_5_24
! 09.05.2017	ggu	changed VERS_7_5_26
! 11.07.2017	ggu	changed VERS_7_5_30
! 05.12.2017	ggu	changed VERS_7_5_39
! 13.07.2018	ggu	changed VERS_7_4_1
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 21.05.2019	ggu	changed VERS_7_5_62
! 31.01.2020	ggu	integrated parts from connectivity

!**************************************************************************

!==================================================================
        module mod_lagrange
!==================================================================

        implicit none

	!---------------------------------------------
	! internal parameters
	!---------------------------------------------

        integer, private, save :: nel_lagr = 0
        integer, private, save :: nlv_lagr = 0
        integer, private, save :: nbdy_lagr = 0

        integer*8 :: bm_kind			!indicates size of bitmap

        integer, save :: nbdymax = 0		!max number of particles
        integer, save :: ncust = 1		!number of custom properties

	!---------------------------------------------
	! particle info
	!---------------------------------------------

	type :: lagr_body
          double precision :: xi(3)             !internal coordinate
          double precision :: time		!time in seconds
	  real :: z				!z-coordinate
	  integer :: ie				!element number (local)
	  integer :: ie_global			!global element number (for MPI)
	  integer :: l				!layer number
	end type lagr_body

	type :: lagr_entry
          integer(kind(bm_kind)) :: bitmap_in,bitmap_out  !for connectivity
	  double precision :: sinking		!sinking velocity
	  real, allocatable :: custom(:)	!custom properties
	  integer :: id				!id of particle
	  integer :: type			!type of particle
	  type(lagr_body) :: init		!initial properties
	  type(lagr_body) :: actual		!run time properties
	end type lagr_entry
	  
        type(lagr_entry), save, allocatable :: lgr_ar(:)

	!output record of one particle (lgr_output_record, lgr_output_fill,
	!lgr_output_write, lgr_mpi_output): the values of the three Fortran
	!records a particle has in the lgr file, as double precision (exact
	!for every value written): 1 id, 2 type, 3 time, 4 sinking,
	!5 element, 6 x, 7 y, 8 z, 9 layer, 10 hl, then the ncust custom
	!values in lgr_orec_base+1 ... lgr_orec_base+ncust
	integer, parameter :: lgr_orec_base = 10

	!element crossings used in the last time step, one per slot of lgr_ar
	!(set to 0 by track_single and to the count by track_body_xi, on the
	!process where the particle ends its step the count of the whole
	!step; read by the debug dump)
        integer, save, allocatable :: lgr_ncross(:)

	!hand-over mark, one per slot of lgr_ar (several processes only):
	! 0 nothing pending
	! 1 the particle stopped on a cut-off side in this time step and goes
	!   on on another process (set by lgr_mpi_mark_side)
	! 2 parked in the horizontal diffusion step, 3 parked in the Stokes
	!   drift step: the new point of the step lies in no element this
	!   process may decide alone (lgr_mpi_park); resolved collectively
	! 4, 5 parked in the diffusion (4) or Stokes (5) step and resolved
	!   (lgr_park_ie holds the outcome): resumed in the same round
	!(cleared by track_single, for an arriving particle and before a
	!resume; written only for the own slot inside the parallel loop of
	!drogue). Moves with its particle.
        integer, save, allocatable :: lgr_marked(:)

	!a parked particle (lgr_marked 2 to 5), one per slot of lgr_ar, moves
	!with its particle: lgr_park_xy(1:4,i) the old x, y and the new x, y
	!of the parked move as the single precision values the step had;
	!lgr_park_ie(i) after the resolution: > 0 the local element the
	!particle goes on in, 0 no element contains the new point (the
	!fallback runs), -1 the element found lacks the particle's layer
	!(diffusion step only: the particle keeps its old position)
	real, save, allocatable :: lgr_park_xy(:,:)
        integer, save, allocatable :: lgr_park_ie(:)

	!---------------------------------------------
	! parameters
	!---------------------------------------------

        logical, parameter :: blgrxi = .true.   !new version with xi coords

        logical, save :: blgrdebug = .false.
        logical, save :: blgrsurf = .false.
        logical, save :: blgr2d = .false.
        logical, save :: bconnect = .false.
        logical, save :: bcount = .false.	!counts particles in elements
        logical, save :: bsedim = .false.	!sediment 
        logical, save :: blarvae = .false.	!larvae 
        logical, save :: boilsim = .false.	!oil simulation
        logical, save :: bcompress = .false.	!compress particle numbers 
        logical, save :: bvdiff = .true.	!compute vertical diffusion
        logical, save :: bhdiff = .true.	!compute horizontal diffusion
        logical, save :: bbeach = .false.	!allow particle to beach on the shore

        integer, save :: ilagr                  !type of lagrangian simulation
        integer, save :: nbdy                   !total number of particles
        integer, save :: idbdy                  !max id used
        integer, save :: lgr_step = 0           !time step number (vertex pick)
	integer, save :: lunit                  !unit for messages
        integer, save :: ipvert                 !vertical release
        integer, save :: linbot                 !bottom layer for vert release
        integer, save :: lintop                 !surface layer for vert release
        real, save :: dripar                    !drifter parameter for inertia
        real, save :: stkpar                    !stokes drift parameter

        integer, save :: artype                 !special element type

        real, save :: azlgr                     !az parameter
        real, save :: tdecay                    !decay time - do not use
        real, save :: fall                      !vertical sinking velocity
        real, save :: rwhpar                    !horizontal diffusivity
        real, save :: lbeach                    !factor for particle beaching

	!---------------------------------------------
	! horizontal diffusivity
	!---------------------------------------------

        real, save, allocatable :: rwhvar(:)    !horizontal diffusivity (vary)

        !---------------------------------------------
        ! vertical diffusivity
        !---------------------------------------------

        real, save, allocatable :: wde(:,:)	!vertical diffusivity on elems
        real, save, allocatable :: dtvd(:)	!vertical random walk time step

	!---------------------------------------------
	! backtracking
	!---------------------------------------------

        integer, save :: nback
        logical, save :: bback

        integer, save, allocatable :: ie_back(:) !backtracking element number
        real, save, allocatable :: u_lag(:)      !backtracking x-velocity
        real, save, allocatable :: v_lag(:)      !backtracking y-velocity
        real, save, allocatable :: x_back(:)     !backtracking x-coordinate
        real, save, allocatable :: y_back(:)     !backtracking y-coordinate
        real, save, allocatable :: z_back(:)     !backtracking z-coordinate

	!--------------------------------------------------
	! fluxes and velocities
	!--------------------------------------------------

        real, save, allocatable :: flux2d(:,:)      !fluxes of sides
        real, save, allocatable :: flux3d(:,:,:)    !fluxes of sides (3d)
        real, save, allocatable :: vel_ie(:,:)      !velocities of sides
        real, save, allocatable :: vel3d_ie(:,:,:)  !velocities of sides (3d)
        real, save, allocatable :: dvert(:,:)

	!--------------------------------------------------
	! connectivity
	!--------------------------------------------------

        integer, save, allocatable :: i_count(:)
        double precision, save, allocatable :: t_count(:)
	real, save :: pld_day = 0.

!==================================================================
        contains
!==================================================================

        subroutine mod_lagrange_init(nel,nlv)

	integer nel,nlv
	integer ierr

        if( nel == nel_lagr .and. nlv == nlv_lagr ) return

        if( nel > 0 .or. nlv > 0 ) then
          if( nel == 0 .or. nlv == 0 ) then
            write(6,*) 'nel,nlv: ',nel,nlv
	    stop 'error stop mod_lagrange_init: incompatible parameters'
          end if
        end if

        if( nel_lagr > 0 ) then
          deallocate(rwhvar)
          deallocate(ie_back)
          deallocate(u_lag)
          deallocate(v_lag)
          deallocate(x_back)
          deallocate(y_back)
          deallocate(z_back)
          deallocate(flux2d)
          deallocate(flux3d)
          deallocate(vel_ie)
          deallocate(vel3d_ie)
          deallocate(dvert)
          deallocate(i_count)
          deallocate(t_count)
          deallocate(wde)
          deallocate(dtvd)
	end if

        nel_lagr = nel
        nlv_lagr = nlv

        if( nel == 0 ) return

        allocate(rwhvar(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(ie_back(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(u_lag(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(v_lag(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(x_back(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(y_back(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(z_back(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

        allocate(flux2d(3,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(flux3d(nlv,3,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(vel_ie(3,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(vel3d_ie(nlv,3,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(dvert(3,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

        allocate(i_count(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(t_count(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

        allocate(wde(0:nlv,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
        allocate(dtvd(nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

        end subroutine mod_lagrange_init

!******************************************************************

        subroutine mod_lagrange_handle_alloc(nbdy)

	integer nbdy

        if( nbdy_lagr == 0 ) then
	  call mod_lagrange_init_body(max(nbdy,1024))
        else if( nbdy < nbdy_lagr/3 ) then
	  call mod_lagrange_init_body(nbdy_lagr/2)
	else if( nbdy > nbdy_lagr ) then
	  call mod_lagrange_init_body(max(nbdy,nbdy_lagr*2))
	end if

	end subroutine mod_lagrange_handle_alloc

!******************************************************************

        subroutine mod_lagrange_init_body(nbdy)

	integer nbdy

	integer ndim
	integer ierr
	real time1,time2
	type(lagr_entry), allocatable :: paux(:)
	integer, allocatable :: iaux(:)
	real, allocatable :: raux(:,:)

        if( nbdy == nbdy_lagr ) return

	call cpu_time(time1)

	if( nbdy_lagr == 0 ) then		!first time
	  nbdy_lagr = nbdy
	  allocate(lgr_ar(nbdy),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	  allocate(lgr_ncross(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_ncross')
	  lgr_ncross = 0
	  allocate(lgr_marked(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_marked')
	  lgr_marked = 0
	  allocate(lgr_park_xy(4,nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_park_xy')
	  lgr_park_xy = 0.
	  allocate(lgr_park_ie(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_park_ie')
	  lgr_park_ie = 0
        else if( nbdy == 0 ) then		!last time
	  deallocate(lgr_ar)
	  deallocate(lgr_ncross)
	  deallocate(lgr_marked)
	  deallocate(lgr_park_xy)
	  deallocate(lgr_park_ie)
	else
          ndim = min(nbdy,nbdy_lagr)
          allocate(paux(nbdy),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
          paux(1:ndim) = lgr_ar(1:ndim)
          call move_alloc(paux,lgr_ar)
	  allocate(iaux(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_ncross')
	  iaux = 0
	  iaux(1:ndim) = lgr_ncross(1:ndim)
	  call move_alloc(iaux,lgr_ncross)
	  allocate(iaux(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_marked')
	  iaux = 0
	  iaux(1:ndim) = lgr_marked(1:ndim)
	  call move_alloc(iaux,lgr_marked)
	  allocate(raux(4,nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_park_xy')
	  raux = 0.
	  raux(:,1:ndim) = lgr_park_xy(:,1:ndim)
	  call move_alloc(raux,lgr_park_xy)
	  allocate(iaux(nbdy),stat=ierr)
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'mod_lagrange_init_body: allocation of lgr_park_ie')
	  iaux = 0
	  iaux(1:ndim) = lgr_park_ie(1:ndim)
	  call move_alloc(iaux,lgr_park_ie)
	end if

	call cpu_time(time2)
	!write(lunit,*) 'alloc_lagr: ',nbdy,nbdy_lagr,time2-time1
	write(6,*) 'alloc_lagr: ',nbdy,nbdy_lagr,time2-time1

        nbdy_lagr = nbdy

        end subroutine mod_lagrange_init_body

!==================================================================
        end module mod_lagrange
!==================================================================

