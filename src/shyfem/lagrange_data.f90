
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
	!spherical coordinates (get_coords_ev): set once by lagr_init_common
	!at start-up, outside any parallel region; only read by the steps
	!(lag_stk, lag_diff_hor) inside the particle loop of drogue
        logical, save :: blgr_sphe = .false.
	!negative vertical diffusivities set to 0 by diff_get_vert (OMP
	!atomic in the particle loop; written once at the end of the particle
	!run by lgr_vdiff_stats, #231)
        integer(kind=8), save :: lgr_nvdiff_neg = 0
	!random walk time step of lag_vdiff_ele over the elements and steps
	!of the particle run (outside any parallel region; written once at
	!the end by lgr_vdiff_stats, #257): smallest dtvd, sum of the step a
	!particle uses (dtvd, at most the model step), sum of the sub-steps
	!that makes in a model step, number of element steps and of those
	!with dtvd below the model step (until #261 also of those with more
	!than 100 sub-steps, then the cap of the calls of a particle step)
        real, save :: lgr_dtvd_min = huge(1.)
        double precision, save :: lgr_dtvd_sum = 0.d0
        integer(kind=8), save :: lgr_dtvd_nstep = 0
        integer(kind=8), save :: lgr_dtvd_n = 0, lgr_dtvd_nsub = 0
	!the vertical walk of a particle step (diff_body, #261): at most
	!lgr_nvdiff_max calls of lgr_diff_vert (100 until #261, which stopped
	!about 8 % of the particle steps of the ilagr = 3 reproducer short of
	!the step, each with a line written from inside the particle loop).
	!Counted in the particle loop (OMP atomic) and written once at the
	!end by lgr_vdiff_stats: the particle steps and calls, the most calls
	!and the most random draws in one particle step (the draws of a step
	!are numbered in a block of 2**24, lgr_random), the steps that reached
	!the cap and those ended by two calls in a row that left the time
	!unchanged (their time below the resolution of the single-precision
	!time left), each with the time it did not diffuse, and all calls
	!that left it unchanged
	integer, parameter :: lgr_nvdiff_max = 10000
        integer(kind=8), save :: lgr_nvdiff_steps = 0
        integer(kind=8), save :: lgr_nvdiff_calls = 0
        integer, save :: lgr_nvdiff_mcall = 0
        integer, save :: lgr_nvdiff_mdraw = 0
        integer(kind=8), save :: lgr_nvdiff_cap = 0
        double precision, save :: lgr_tvdiff_cap = 0.d0
        integer(kind=8), save :: lgr_nvdiff_stall = 0
        double precision, save :: lgr_tvdiff_stall = 0.d0
        integer(kind=8), save :: lgr_nvdiff_zero = 0
	!true while the OpenMP particle loop of drogue runs (set and cleared
	!by drogue, outside the parallel region); read by lgr_internal_error
	!(#256) and lgr_event (#288, #294): there a team of more than one
	!thread records, anywhere else they write or abort at once. Here and
	!not in mod_lagrange_mpi since #294, so that lgr_event (below) can
	!read it; mod_lagrange_mpi passes it on to its users
	logical, save :: lgr_omp_loop = .false.
	!events of the tracker found by the particles in the particle loop
	!of drogue, which until #288 (the vertical walk) and #294 (the
	!advection, the layers, the connectivity, the element search) wrote
	!their lines from the worker threads. lgr_event records one: it is
	!counted (OMP atomic, lgr_ev_n) and the values of the event of its
	!kind with the lowest key are kept (the key is the id of the
	!particle, so the event of the lowest id; the slot for 1, 2 and 21,
	!so the first in the order of a serial loop; the element for 11) in
	!the critical section lgr_ev, entered only for an event: up to
	!lgr_ev_ni integer values (lgr_ev_ival), lgr_ev_nd real
	!values (lgr_ev_dval) and a text (lgr_ev_text). lgr_events writes,
	!for each kind with events, one line with the events of the pass and
	!the values of the first, and clears them: once per pass, at its end
	!(lagrange, after the particle loop and the hand-over), and before
	!the run stops (lgr_mpi_list_check, and lgr_event for a kind that
	!stops the run when its error aborts at once). Each process writes
	!its own lines, on several processes with its rank, and makes no
	!collective call. lgr_ev_ntot sums each kind over the run. What each
	!kind writes is in lgr_event_desc. The kinds (in parentheses the
	!line each wrote until then; "stops" marks an internal error, after
	!which lgr_internal_error stops the run):
	! 1, 2 diff_body: the walk ended with time left, the particle out of
	!      the domain ("loosing particle dif") or the cause unknown
	!      ("unknown error dif")
	! 3    lgr_diff_vert: a depth outside 0..1, stops
	! 4    diff_get_vert: a layer below the bottom of the element, stops
	! 5    track_body_xi: the element crossings used up with time left
	!      ("warning particle adv")
	! 6    track_body_xi: out of the domain with time left ("loosing
	!      particle adv")
	! 7    track_body_xi: time left, the cause unknown ("unknown error
	!      adv")
	! 8    track_xi_get_flux: a flux over a wall side, set to 0
	!      ("material boundary:")
	! 9    track_xi: a negative velocity ("vel < 0")
	! 10   track_xi_adjust_layer: a layer below the bottom of the element
	!      entered, set to its bottom layer ("warning: wrong layer")
	! 11   lagr_layer_thickness: incompatible layers, stops
	! 12   track_xi: internal error (3), stops
	! 13   track_xi: a depth outside 0..1, internal error (2), stops
	! 14   track_xi_next_element: erroneous xi, stops
	! 15   track_xi_next_element: erroneous xi sanity, stops
	! 16   track_xi_next_element: erroneous ieltv, stops
	! 17   track_xi_get_vertical: no such layer, stops
	! 18   track_xi_check: wrong xi, stops
	! 19   lagr_connect_count: time is nan, stops
	! 20   lagr_connect_count: particle not coming from a source, stops
	! 21   lgr_mpi_locate: no old element, stops
	! 22   track_advect, track_finish, track_body_xi: the error of
	!      xi2xy_ierr (the determinant too small), stops
	! 23   diff_body, lag_stk_end: the error of xy2xi_ierr (element out of
	!      range, xi that cannot be adjusted), stops
	! 24   track_xi: the error of xit_start_end_ierr, stops
	! 25   track_xi: the error of xi_dist_ierr, stops
	!(22 to 25 stopped with a bare stop in the utilities until #294)
	!For the kinds that do not stop the run the counts and the events
	!kept are the same on any number of threads (the key orders them; the
	!events of one particle come from one thread, in order). For those
	!that stop it not: after the first internal error the other threads
	!leave their particles (lgr_internal_failed), so the count and the
	!event kept depend on the scheduling (on one thread the run aborts
	!at the first one in the order of the loop), which is harmless, as
	!the run stops
	integer, parameter :: lgr_ev_vd_lost = 1
	integer, parameter :: lgr_ev_vd_unknown = 2
	integer, parameter :: lgr_ev_vd_depth = 3
	integer, parameter :: lgr_ev_vd_layer = 4
	integer, parameter :: lgr_ev_adv_cross = 5
	integer, parameter :: lgr_ev_adv_lost = 6
	integer, parameter :: lgr_ev_adv_unknown = 7
	integer, parameter :: lgr_ev_wall_flux = 8
	integer, parameter :: lgr_ev_vel_neg = 9
	integer, parameter :: lgr_ev_wrong_layer = 10
	integer, parameter :: lgr_ev_layers = 11
	integer, parameter :: lgr_ev_xi_int3 = 12
	integer, parameter :: lgr_ev_xi_depth = 13
	integer, parameter :: lgr_ev_next_xi = 14
	integer, parameter :: lgr_ev_next_sanity = 15
	integer, parameter :: lgr_ev_next_ieltv = 16
	integer, parameter :: lgr_ev_vert_layer = 17
	integer, parameter :: lgr_ev_xi_check = 18
	integer, parameter :: lgr_ev_conn_nan = 19
	integer, parameter :: lgr_ev_conn_source = 20
	integer, parameter :: lgr_ev_locate = 21
	integer, parameter :: lgr_ev_xi2xy = 22
	integer, parameter :: lgr_ev_xy2xi = 23
	integer, parameter :: lgr_ev_xit = 24
	integer, parameter :: lgr_ev_xidist = 25
	integer, parameter :: lgr_nev = 25		!kinds
	integer, parameter :: lgr_ev_ni = 9		!integer values of a kind
	integer, parameter :: lgr_ev_nd = 6		!real values of a kind
        integer, save :: lgr_ev_n(lgr_nev) = 0
        integer(kind=8), save :: lgr_ev_ntot(lgr_nev) = 0
        integer, save :: lgr_ev_key(lgr_nev) = huge(1)
        integer, save :: lgr_ev_ival(lgr_ev_ni,lgr_nev) = 0
        double precision, save :: lgr_ev_dval(lgr_ev_nd,lgr_nev) = 0.d0
        character(len=40), save :: lgr_ev_text(lgr_nev) = ' '
	!particles not released because their release point lies in no
	!element (insert_particle_3d, insert_particle; #247): counted, the
	!release that asked for them reports the number (lgr_init_traj)
        integer, save :: nlgr_outside = 0

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
	    call shympi_abort_internal(					&
     &		'error stop mod_lagrange_init: incompatible parameters')
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
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(ie_back(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(u_lag(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(v_lag(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(x_back(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(y_back(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(z_back(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')

        allocate(flux2d(3,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(flux3d(nlv,3,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(vel_ie(3,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(vel3d_ie(nlv,3,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(dvert(3,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')

        allocate(i_count(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(t_count(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')

        allocate(wde(0:nlv,nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
        allocate(dtvd(nel),stat=ierr)
	if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')

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
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
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
	  if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
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

!******************************************************************

        subroutine lgr_event(kind,key,ival,dval,text)

! records an event of the tracker (#288, #294; the kinds and the arrays
! are described above at lgr_ev_n): called by any thread, inside the
! particle loop of drogue or outside any parallel region; writes nothing
! there, except for a kind that stops the run outside an active parallel
! region (see below). The event is counted (OMP atomic); its values
! replace those kept for its kind if its key is lower (critical section
! lgr_ev, entered only for an event, which is rare). lgr_events writes
! them at the end of the pass.
! A kind that stops the run is followed by lgr_internal_error, which
! aborts at once outside an active parallel region (outside the loop, or
! a loop on one thread, run by the main thread): there the events are
! written at once (lgr_events), as their lines were before #288 and #294
! Must not be called inside the critical section lgr_ev

        implicit none

        integer, intent(in)			:: kind	!1 ... lgr_nev
        integer, intent(in)			:: key	!lowest kept
        integer, intent(in)			:: ival(:) !integer values
        double precision, intent(in), optional	:: dval(:) !real values
        character(len=*), intent(in), optional	:: text	!text of the site

        integer				:: ni,nd
        logical				:: brun,bfix,bnow
        character(len=32)		:: chead
        character(len=80)		:: ctext
        character(len=20)		:: cname(lgr_ev_ni+lgr_ev_nd)
        logical				:: openmp_in_parallel

!$OMP ATOMIC
        lgr_ev_n(kind) = lgr_ev_n(kind) + 1

!$OMP CRITICAL (lgr_ev)
        if( key < lgr_ev_key(kind) ) then
          lgr_ev_key(kind) = key
          lgr_ev_ival(:,kind) = 0
          ni = min(size(ival),lgr_ev_ni)
          lgr_ev_ival(1:ni,kind) = ival(1:ni)
          lgr_ev_dval(:,kind) = 0.d0
          if( present(dval) ) then
            nd = min(size(dval),lgr_ev_nd)
            lgr_ev_dval(1:nd,kind) = dval(1:nd)
          end if
          lgr_ev_text(kind) = ' '
          if( present(text) ) lgr_ev_text(kind) = text
        end if
!$OMP END CRITICAL (lgr_ev)

        call lgr_event_desc(kind,chead,ctext,brun,ni,nd,cname,bfix)
        if( brun ) return		!written at the end of the pass
        bnow = .not. lgr_omp_loop
        if( .not. bnow ) bnow = .not. openmp_in_parallel()
        if( bnow ) call lgr_events	!lgr_internal_error aborts next

        end subroutine lgr_event

!******************************************************************

        subroutine lgr_event_desc(kind,chead,ctext,brun,ni,nd,cname,bfix)

! what lgr_events writes for an event of kind (#288, #294): the line is
!   "<chead>:[ rank R:] <ctext>[ (<text of the site>)]: N in the step
!   to TIME[, M in the run (P % of the I particles released)]; first:
!   <name> <value>, <name> <value>, ..."
! with N the events of the pass and the values of the first event kept;
! the part in the run (the events of the run, their percentage in the
! particles released, idbdy) only for a kind that does not stop the run
! (brun). The values are the ni integer values, then the nd real values
! (with three decimals if bfix, else in full precision, g0), named by
! cname(1:ni+nd); a value named "of" follows the one before with no comma
! (layer L of N). The lines of the kinds 1 to 4 are those of #288

        implicit none

        integer, intent(in)		:: kind
        character(len=*), intent(out)	:: chead	!what found it
        character(len=*), intent(out)	:: ctext	!the event
        logical, intent(out)		:: brun		!the run goes on
        integer, intent(out)		:: ni		!integer values
        integer, intent(out)		:: nd		!real values
        character(len=*), intent(out)	:: cname(:)	!their names
        logical, intent(out)		:: bfix		!real values with f.3

        character(len=*), parameter	:: cadv = 'lgr advection'
        character(len=*), parameter	:: cvd = 'lgr vertical diffusion'

        chead = cadv
        brun = .false.
        ni = 0
        nd = 0
        cname = ' '
        bfix = .false.

        select case( kind )
        case( lgr_ev_vd_lost, lgr_ev_vd_unknown, lgr_ev_adv_cross	&
     &		, lgr_ev_adv_lost, lgr_ev_adv_unknown )
          brun = .true.
          ni = 3
          nd = 1
          bfix = .true.
          cname(1:4) = [character(len=20) :: 'id','element'		&
     &			,'calls left','time left [s]']
          select case( kind )
          case( lgr_ev_vd_lost )
            chead = cvd
            ctext = 'lost with time left'
          case( lgr_ev_vd_unknown )
            chead = cvd
            ctext = 'walk ended with time left, cause unknown'
          case( lgr_ev_adv_cross )
            ctext = 'element crossings used up with time left'
          case( lgr_ev_adv_lost )
            ctext = 'lost with time left'
          case default
            ctext = 'advection ended with time left, cause unknown'
          end select
          if( kind >= lgr_ev_adv_cross ) cname(3) = 'crossings left'
        case( lgr_ev_vd_depth, lgr_ev_xi_depth )
          ni = 4
          nd = 6
          cname(1:10) = [character(len=20) :: 'id','element','layer'	&
     &			,'of','tv','t','dz','w','hd','z']
          if( kind == lgr_ev_vd_depth ) then
            chead = cvd
            ctext = 'depth outside 0..1 after a call of lgr_diff_vert'
          else
            ctext = 'depth outside 0..1 in track_xi'
          end if
        case( lgr_ev_vd_layer, lgr_ev_vert_layer )
          ni = 4
          cname(1:4) = [character(len=20) :: 'id','element','layer','of']
          if( kind == lgr_ev_vd_layer ) then
            chead = cvd
            ctext = 'no such layer in diff_get_vert'
          else
            ctext = 'no such layer in track_xi_get_vertical'
          end if
        case( lgr_ev_wall_flux )
          brun = .true.
          ni = 4
          nd = 1
          cname(1:5) = [character(len=20) :: 'id','element','layer'	&
     &			,'side','flux']
          ctext = 'flux over a wall side set to 0'
        case( lgr_ev_vel_neg )
          brun = .true.
          ni = 4
          nd = 4
          cname(1:8) = [character(len=20) :: 'id','element','layer'	&
     &			,'of','vel','flux 1','flux 2','flux 3']
          ctext = 'negative velocity in track_xi'
        case( lgr_ev_wrong_layer )
          brun = .true.
          ni = 4
          cname(1:4) = [character(len=20) :: 'id','element','layer','of']
          ctext = 'layer below the bottom of the element entered,'	&
     &		//' put in its bottom layer'
        case( lgr_ev_layers )
          chead = 'lgr layers'
          ni = 4
          cname(1:4) = [character(len=20) :: 'element','nlev','lmax'	&
     &			,'lmax_act']
          ctext = 'incompatible layers in lagr_layer_thickness'
        case( lgr_ev_xi_int3 )
          ni = 2
          nd = 5
          cname(1:7) = [character(len=20) :: 'id','element','s','t'	&
     &			,'th','ds','sorig']
          ctext = 'internal error (3) of track_xi'
        case( lgr_ev_next_xi, lgr_ev_next_sanity, lgr_ev_next_ieltv )
          nd = 3
          if( kind == lgr_ev_next_xi ) then
            ni = 4
            ctext = 'erroneous xi in track_xi_next_element'
          else if( kind == lgr_ev_next_sanity ) then
            ni = 5
            ctext = 'erroneous xi sanity in track_xi_next_element'
          else
            ni = 9
            ctext = 'erroneous ieltv in track_xi_next_element'
          end if
          cname(1:9) = [character(len=20) :: 'id','element','in','it'	&
     &			,'ia1','ieb','ieltv 1','ieltv 2','ieltv 3']
          cname(ni+1:ni+3) = [character(len=20) :: 'xi 1','xi 2','xi 3']
        case( lgr_ev_xi_check )
          ni = 1
          nd = 3
          cname(1:4) = [character(len=20) :: 'id','xi 1','xi 2','xi 3']
          ctext = 'wrong xi in track_xi_check'
        case( lgr_ev_conn_nan )
          chead = 'lgr connectivity'
          ni = 3
          nd = 1
          cname(1:4) = [character(len=20) :: 'id','slot','element'	&
     &			,'time']
          ctext = 'time is nan in lagr_connect_count'
        case( lgr_ev_conn_source )
          chead = 'lgr connectivity'
          ni = 5
          cname(1:5) = [character(len=20) :: 'id','slot'		&
     &			,'element of origin','external element','station']
          ctext = 'particle not coming from a source in'		&
     &		//' lagr_connect_count'
        case( lgr_ev_locate )
          chead = 'lgr element search'
          ni = 3
          cname(1:3) = [character(len=20) :: 'slot','phase','element']
          ctext = 'no old element in lgr_mpi_locate'
        case( lgr_ev_xi2xy )
          ni = 2
          nd = 3
          cname(1:5) = [character(len=20) :: 'id','element','xi 1'	&
     &			,'xi 2','xi 3']
          ctext = 'determinant too small in xi2xy'
        case( lgr_ev_xy2xi )
          ni = 3
          nd = 2
          cname(1:5) = [character(len=20) :: 'id','element','error'	&
     &			,'x','y']
          ctext = 'xy2xi failed (error -1: element out of range,'	&
     &		//' 1 or 3: xi cannot be adjusted)'
        case( lgr_ev_xit )
          ni = 4
          nd = 4
          cname(1:8) = [character(len=20) :: 'id','element','iflux'	&
     &			,'error','alpha','xi 1','xi 2','xi 3']
          ctext = 'internal error of xit_start_end in track_xi'
        case( lgr_ev_xidist )
          ni = 3
          nd = 6
          cname(1:9) = [character(len=20) :: 'id','element','error'	&
     &			,'xis 1','xis 2','xis 3','xie 1','xie 2','xie 3']
          ctext = 'error of xi_dist in track_xi (1: a point not on a'	&
     &		//' side, 2: impossible)'
        case default
          ctext = 'unknown kind of event'
        end select

        end subroutine lgr_event_desc

!******************************************************************

        subroutine lgr_events

! writes the events of the tracker recorded by lgr_event (#288, #294;
! the line of a kind: lgr_event_desc) and clears the counts of the pass;
! writes nothing when nothing was recorded. Called by the main thread
! outside any parallel region: by lagrange once per pass, at its end
! (after the particle loop of drogue and the hand-over), by
! lgr_mpi_list_check before it stops the run (after an internal error
! found in the particle loop), and by lgr_event before an internal error
! aborts at once.
! No collective call: each process writes its own events, on several
! processes with its rank, so a process with none writes nothing and
! waits for nobody

        use shympi, only : my_id, shympi_is_parallel

        implicit none

        integer				:: k,j,ni,nd
        logical				:: brun,bfix
        double precision		:: dtime
        double precision		:: perc
        character(len=20)		:: aline
        character(len=24)		:: crank
        character(len=32)		:: cnum
        character(len=32)		:: chead
        character(len=80)		:: ctext
        character(len=20)		:: cname(lgr_ev_ni+lgr_ev_nd)
        character(len=1024)		:: line

        if( all( lgr_ev_n == 0 ) ) return

        call get_act_dtime(dtime)
        call get_timeline(dtime,aline)
        crank = ' '
        if( shympi_is_parallel() ) write(crank,'(a,i0,a)') ' rank ',my_id,':'

        do k=1,lgr_nev
          if( lgr_ev_n(k) == 0 ) cycle
          call lgr_event_desc(k,chead,ctext,brun,ni,nd,cname,bfix)
          lgr_ev_ntot(k) = lgr_ev_ntot(k) + lgr_ev_n(k)
          line = ' '//trim(chead)//':'//trim(crank)//' '//trim(ctext)
          if( lgr_ev_text(k) /= ' ' ) then
            line = trim(line)//' ('//trim(lgr_ev_text(k))//')'
          end if
          write(cnum,'(i0)') lgr_ev_n(k)
          line = trim(line)//': '//trim(cnum)//' in the step to '	&
     &		//trim(aline)
          if( brun ) then
            perc = 0.d0
            if( idbdy > 0 ) perc = (100.d0*lgr_ev_ntot(k))/idbdy
            write(cnum,'(i0)') lgr_ev_ntot(k)
            line = trim(line)//', '//trim(cnum)//' in the run ('
            write(cnum,'(f16.2)') perc
            line = trim(line)//trim(adjustl(cnum))//' % of the '
            write(cnum,'(i0)') idbdy
            line = trim(line)//' '//trim(cnum)//' particles released)'
          end if
          line = trim(line)//'; first:'
          do j=1,ni+nd
            if( j <= ni ) then
              write(cnum,'(i0)') lgr_ev_ival(j,k)
            else if( bfix ) then
              write(cnum,'(f16.3)') lgr_ev_dval(j-ni,k)
            else
              write(cnum,'(g0)') lgr_ev_dval(j-ni,k)
            end if
            if( j > 1 ) then
              if( cname(j) /= 'of' ) line = trim(line)//','
            end if
            line = trim(line)//' '//trim(cname(j))//' '			&
     &		//trim(adjustl(cnum))
          end do
          write(6,'(a)') trim(line)
        end do
        flush(6)

        lgr_ev_n = 0
        lgr_ev_key = huge(1)

        end subroutine lgr_events

!==================================================================
        end module mod_lagrange
!==================================================================

