
!--------------------------------------------------------------------------
!
!    Copyright (C) 2026  SHYFEM Contributors
!
!    This file is part of SHYFEM.
!
!    SHYFEM is free software: you can redistribute it and/or modify
!    it under the terms of the GNU General Public License as published by
!    the Free Software Foundation, either version 3 of the License, or
!    (at your option) any later version.
!
!--------------------------------------------------------------------------

! MPI support for Lagrangian particle tracking
!
! contents :
!
! lgr_mpi_check_supported	options not supported on several processes stop
! lgr_mpi_init			initialize MPI buffers
! lgr_mpi_topology_init	lists of elements shared with other ranks
! lgr_mpi_side_table		side table of the tracker (lgr_ieltv, lgr_side_lmax)
! lgr_mpi_side_record		first error of the side table on this rank
! lgr_mpi_side_fail		collective: abort if a rank found an error
! lgr_mpi_node_elems		node to element lists of a mesh
! lgr_mpi_side_other		elements other than a given one at a side
! lgr_mpi_flux_sum_3d		sum of partial side fluxes flux3d across ranks
! lgr_mpi_flux_sum_2d		sum of partial side fluxes flux2d across ranks
! lgr_mpi_flux_sum		common part of the two flux sums
! lgr_mpi_lookup_init		sorted global numbers, node to element lists
! lgr_mpi_mark_side		mark a particle stopped on a cut-off side
! lgr_mpi_grow_export		enlarge the lists of marks
! lgr_mpi_list_fail		record a failure of the lists found in the particle loop
! lgr_mpi_list_check		abort on a recorded failure (main thread, after the loop)
! lgr_mpi_test_internal		test hook of the internal-error guards (#256)
! lgr_mpi_test_event		test hook of the events of the tracker (#305)
! lgr_mpi_search_key		place of an element in find_elem_from_old's search
! lgr_mpi_selftest_key		self-test of the key against that search
! lgr_mpi_clear_of_sides	point clear of an element's sides by the margin
! lgr_mpi_locate		element search of the diffusion and Stokes steps
! lgr_mpi_park			park a particle whose new element is undecided
! lgr_mpi_grow_park		enlarge the list of parked particles
! lgr_mpi_relocate_check	serial self-check of the search (levdbg >= 3)
! lgr_mpi_pack_particle		serialize the whole particle record to a double buffer
! lgr_mpi_unpack_particle	deserialize the whole particle record
! lgr_mpi_remove_particle	remove a particle from the array (last one moves up)
! lgr_mpi_remove_list		remove several particles (highest slot first)
! lgr_mpi_selftest_pack		self-test of record and removal (levdbg >= 3)
! lgr_mpi_selftest_side		self-test of particle_on_side (levdbg >= 3)
! lgr_side_delta		rounding distance of particle_on_side and its self-test
! lgr_mpi_find_elem		local element of a global element, 0 if not held
! lgr_mpi_find_node		local node of a global node, 0 if not held
! lgr_mpi_handover		hand-over of the marked particles, in rounds
! lgr_mpi_handover_round	one round of the hand-over
! lgr_mpi_handover_stats	totals of the hand-over (levdbg >= 3)
! lgr_mpi_check_consistency	built-in check of the particle state (levdbg >= 2)
! lgr_mpi_resolve		resolution of the parked particles by position
! lgr_mpi_relocate_step		parkings of a step (levdbg >= 3)
! lgr_mpi_relocate_stats	counts of the element search (levdbg >= 3)
! lgr_mpi_output		particle file on several processes, written by rank 0
! lgr_mpi_gather_records	records of all processes on rank 0
! lgr_mpi_keep_release		release records of a seeding call for the output
! lgr_mpi_reduce_connect	reduce connectivity matrices
! lgr_mpi_global_count		sum of an integer over all processes (drogue)
! lgr_mpi_gather_global		global array on rank 0 from the owned entries
! lgr_mpi_global_area		total basin area as in a serial run
! lgr_mpi_global_center		basin centre as in a serial run
! lgr_mpi_assign_ids		ids of a release as in a serial run, limit nbdymax
! lgr_mpi_debug_dump		text dump of particles, fluxes, node arrays
! lgr_mpi_debug_open		open one debug dump file
! lgr_mpi_ghost_nodes		number of vertices of an element owned elsewhere
! lgr_mpi_bisect		position of a key in a sorted list
!
! outside the module (#256):
!
! lgr_internal_error		internal-error guard: record in the loop, else abort
! lgr_internal_failed		an internal error was recorded in the loop

	module mod_lagrange_mpi

	use mod_lagrange

	implicit none

	! record of one particle on the wire, double precision values:
	!  1- 3 actual%xi    4 actual%time   5 actual%z   6 actual%l
	!       7 actual%ie_global
	!  8-10 init%xi     11 init%time    12 init%z    13 init%l
	!      14 init%ie_global
	! 15 id   16 type   17 sinking
	! 18,19 bitmap_in (low, high 32 bits)   20,21 bitmap_out (low, high)
	! 22 number of custom values (must equal ncust)   23.. custom values
	! the local element numbers ie do not travel (resolved by the receiver)
	integer, parameter :: lgr_pack_base = 22  !base fields per particle
	integer, save :: lgr_pack_size = 0        !total fields (base + ncust)

	! hand-over at a cut-off side (lgr_mpi_handover): behind the record
	! of a particle travel lgr_hand_extra double precision values:
	!  1 global element left   2, 3 global end nodes of the side
	!  4, 5 the particle's weights (xi) at the two end nodes
	!  6 t_left   7 n_left   8 phase (0: advection goes on)
	!  9 d_start: the distance from the nearest vertex at the start of the
	!    step, which the node-sink test of track_body_xi compares with the
	!    end of the base budget (#315: so the process across decides as a
	!    serial run; until then it took its arrival point)
	integer, parameter :: lgr_hand_extra = 9
	integer, parameter :: lgr_hand_tag = 21706  !message tag

	! marks of the hand-over (lgr_mpi_mark_side), n_export of them; the
	! lists are written only inside the critical section lgr_export or
	! outside the parallel region
	integer, save :: n_export = 0
	integer, save :: n_export_grow = 0     !how often the lists were enlarged
	logical, save :: blgr_dbg = .false.    !levdbg >= 3
	integer, save, allocatable :: export_dest(:)    !destination rank
	integer, save, allocatable :: export_idx(:)     !particle index (slot)
	integer, save, allocatable :: export_elem(:)    !element it is leaving
	integer, save, allocatable :: export_side(:)    !side of that element
	integer, save, allocatable :: export_nleft(:)   !crossings left
	real, save, allocatable :: export_tleft(:)      !time left
	double precision, save, allocatable :: export_dstart(:) !d_start (#315)

	! totals of the hand-over on this process (lgr_mpi_handover_stats)
	integer, save :: lgr_nhand = 0       !particles sent at a cut-off side
					     !(by position: lgr_nres_sent)
	integer, save :: lgr_nround_max = 0  !most hand-overs at a side of one
					     !particle in a step: the last round
					     !of a step with a side mark, largest
					     !over the steps (lgr_mpi_handover)
	integer, save :: lgr_nputback = 0    !put back at a cut-off side for
					     !lack of a layer (OMP atomic)
	integer, save :: lgr_nhand3(2) = 0   !hand-overs (1 at a side, 2 by
					     !position) that start in an element
					     !held by three processes
					     !(id_elem(0,ie) == 3)
	integer, save :: lgr_nsent_round = 0 !particles this process sent in
					     !the last round (side and position)
	integer, save :: lgr_nchg_max = 0    !most particles changing process
					     !in one step (all processes; the same
					     !on every process)
	double precision, save :: lgr_tchg_max = 0.d0 !end of that step
	integer, save :: lgr_ndry(2) = 0     !at levdbg >= 3, element-steps:
					     !1 dry elements (iwegv /= 0) this
					     !process is the main owner of, 2 dry
					     !held elements with a cut-off side
					     !on this process (lgr_mpi_handover)

	! hand-over by position (lgr_mpi_locate, lgr_mpi_park, lgr_mpi_resolve):
	! the end of the horizontal diffusion step and of the Stokes drift step
	! look for the element of the new point (find_elem_from_old). On
	! several processes a process decides alone only if the point is in
	! the old element or in a held element and clear of its three sides by
	! the margin lgr_park_rel times the longest side of that element
	! (lgr_mpi_clear_of_sides); every other point is parked and resolved
	! by all processes together after the particle loop. Parked particles
	! of this process: n_park, park_idx (slot), park_class (3 local hit
	! within the margin, 4 failed local search); written only inside the
	! critical section lgr_export or outside the parallel region
	double precision, parameter :: lgr_park_rel = 2.d0**(-12)
	integer, save :: n_park = 0
	integer, save, allocatable :: park_idx(:)
	integer, save, allocatable :: park_class(:)

	! particles of this process that go to another process by position
	! in a round (lgr_mpi_resolve, in slot order): slot, destination rank,
	! global number of the element found
	integer, save, allocatable :: pos_idx(:), pos_dest(:), pos_elem(:)

	! behind the record of a particle handed over by position travel
	! lgr_hand_extra values too (phase 1 or 2 in the last one):
	!  1 global element found   2, 3 old x, y   4, 5 new x, y
	!  6 crossings used in the step (lgr_ncross)   7 unused (0)   8 phase
	!  9 unused (0): the advection of the step is over, d_start has no
	!    reader after a parking

	! counts of the re-location of this process, at levdbg >= 3 (OMP
	! atomic inside the particle loop): lgr_nreloc(1:4) by class (1 in the
	! old element, 2 hit clear of the margin, 3 hit within the margin,
	! 4 failed search); serial self-check (lgr_mpi_relocate_check):
	! compared, differing, clear hits in a second element, points in two
	! or more elements (where the order of the search decides);
	! by position (lgr_mpi_resolve): parked per phase (1, 2) and per class
	! (3, 4); outcomes: accepted on this process, kept for lack of a
	! layer, sent, nobody answered, class 3 and nobody answered; offers
	! outside the bounding box of the mesh; most parked in one step,
	! rounds with a resolution, time spent in it
	integer, save :: lgr_nreloc(4) = 0
	integer, save :: lgr_nchk_comp = 0, lgr_nchk_diff = 0
	integer, save :: lgr_nchk_clear2 = 0, lgr_nchk_multi = 0
	integer, save :: lgr_nkey_walk = 0, lgr_nkey_wrong = 0 !key self-test
	integer, save :: lgr_npark_ph(2) = 0, lgr_npark_cl(3:4) = 0
	integer, save :: lgr_nres_stay = 0, lgr_nres_layer = 0
	integer, save :: lgr_nres_sent = 0, lgr_nres_none = 0
	integer, save :: lgr_nres_hitnone = 0, lgr_nres_outbox = 0
	integer, save :: lgr_npark_step = 0, lgr_npark_step_max = 0
	integer, save :: lgr_nreloc34_prev = 0
	integer, save :: lgr_nres_round = 0
	double precision, save :: lgr_tres = 0.d0

	logical, save :: bmpi_lagr = .false.      !true if MPI active for lagrange

	! lgr_mpi_check_consistency is active (set by lgr_mpi_init: several
	! processes, levdbg >= 2)
	logical, save :: blgr_chk = .false.

	! test hooks of lgr_mpi_check_consistency (read once by lgr_mpi_init;
	! inactive unless the environment variable names this process):
	! LGR_TEST_DROP=R: process R skips its first arrival at a side in
	! lgr_mpi_handover_round (the particle is lost); LGR_TEST_DUP=R:
	! process R keeps the first particle it sends at a side (a copy stays
	! in its slot, mark cleared). Each fires once in the whole run.
	logical, save :: lgr_test_drop = .false.
	logical, save :: lgr_test_dup = .false.

	! test hook of the error path of the lists (read once by lgr_mpi_init,
	! several processes only; mpirun passes it with -x NAME):
	! LGR_TEST_GROW_FAIL=export or =park makes the first enlargement of
	! that list on every process take the path of a failed allocate,
	! once (read and cleared inside the critical section lgr_export)
	logical, save :: lgr_test_grow_export = .false.
	logical, save :: lgr_test_grow_park = .false.

	! a failure of the lists of marks or of parked particles found where
	! the list grows or is appended to, which can be inside the OpenMP
	! particle loop of drogue (#242). MPI is initialised with
	! MPI_THREAD_FUNNELED, so a worker thread must not call MPI_ABORT: the
	! routine that finds the failure records it (lgr_mpi_list_fail, inside
	! the critical section lgr_export; the first failure of the process),
	! appends nothing and leaves the particle out of the rest of the step;
	! the main thread aborts with the message in lgr_mpi_list_check, after
	! the particle loop and before every collective call of the
	! hand-over. lgr_list_fail: 0 none, 1 allocation in
	! lgr_mpi_grow_export, 2 allocation in lgr_mpi_grow_park, 3 argument
	! check of lgr_mpi_mark_side, 4 argument check of lgr_mpi_park, 5 an
	! internal-error guard of the tracker (lgr_internal_error, #256: its
	! message in lgr_list_msg); lgr_list_info: the slot of the particle,
	! four values of the message and the OpenMP thread that found it
	integer, save :: lgr_list_fail = 0
	integer, save :: lgr_list_info(6) = 0
	character(len=80), save :: lgr_list_msg = ' '

	! internal-error guards of the tracker reached inside the OpenMP
	! particle loop of drogue (#256): lgr_omp_loop (in mod_lagrange since
	! #294, passed on by this module) is true while that loop runs (set
	! and cleared by drogue, outside the parallel region); a guard hit
	! there by a team of more than one thread is recorded by
	! lgr_internal_error (kind 5 above, and lgr_internal_flag = 1, written
	! and read with OMP ATOMIC: lgr_internal_failed) and the run stops in
	! lgr_mpi_list_check after the loop; anywhere else the guard aborts at
	! once, as before, after writing the events of the pass (#305)
	integer, save :: lgr_internal_flag = 0

	! test hook of the internal-error guards (read once by lgr_mpi_init,
	! also in a serial run; mpirun passes it with -x NAME):
	! LGR_TEST_INTERNAL_FAIL=1 gives the first particle that a thread other
	! than 0 of the particle loop takes on each process (thread 0 if the
	! loop runs on one thread) a negative travel time, so that the guard of
	! track_single fires once (lgr_mpi_test_internal, #256)
	logical, save :: lgr_test_internal = .false.
	integer, save :: lgr_test_internal_n = 0

	! test hook of the vertical walk of diff_body (read once by
	! lgr_mpi_init, also in a serial run; never written after that):
	! LGR_TEST_VDIFF_END=N (N >= 1) ends the walk of a particle whose id
	! is a multiple of N at once, in every step, with all its time left,
	! as a walk that left its layers would end (the exit lb < 1 of
	! diff_body); if its id is also a multiple of 2N the particle leaves
	! the domain there (iel = -iel). This reaches the two branches of
	! diff_body for a walk that ended with time left (the particle out of
	! the domain, "loosing particle dif", and the cause unknown, "unknown
	! error dif"), which no run reaches: since #261 the walk ends only
	! with no time left, at the cap of its calls or by two calls in a row
	! that used no time, and lgr_diff_vert never sets lb < 1 (#288). 0:
	! off. The particles are chosen by their id, so the same ones on any
	! number of threads; with ilagr 1 or 2 (no vertical walk) it does
	! nothing
	integer, save :: lgr_test_vdiff_end = 0

	! test hooks of the acceptance checks of the vertical walk of ilagr =
	! 3 (check_lgr_wellmixed.sh, #286, #287; read once by lgr_mpi_init,
	! also in a serial run; never written after that):
	! LGR_TEST_KPROF=N sets the vertical diffusivity of the particles in
	! every element (wde of lag_vdiff_ele, right after it is computed and
	! before the time step of the walk is taken from it) to a profile of
	! the relative depth s = hle(l)/hle(lmax) of the interfaces of the
	! column (only where the column depth hle(lmax) is above 0): 1 linear,
	! 1e-3 + 2e-2 s; 2 parabolic, 1e-3 + 8e-2 s (1 - s); 3 constant,
	! 1e-2 [m**2/s]. Any other value leaves it off (0)
	integer, save :: lgr_test_kprof = 0
	! LGR_TEST_NOADV=1: the particles are not advected (track_single
	! skips track_advect); the steps after the advection (vertical walk,
	! horizontal diffusion, Stokes drift, beaching) run as before
	logical, save :: lgr_test_noadv = .false.

	! test hook of the events of the tracker (#305; read once by
	! lgr_mpi_init, also in a serial run; never written after that):
	! LGR_TEST_EVENT=K (K = 1 ... lgr_nev) records an event of kind K for
	! the particle in slot 1 in the first pass (lgr_step = 1) on each
	! process, with fixed values, and for a kind that stops the run then
	! calls lgr_internal_error (lgr_mpi_test_event, called by track_single
	! at its start); for kind 23 the error of xy2xi_ierr in diff_body is
	! forced instead (error 1), so that the path after an error recorded
	! there runs (track_finish returns). 0: off. This reaches every kind
	! and the three ways the run stops after one (at once on one thread,
	! through lgr_mpi_list_check on several threads, each process with its
	! rank), which no normal run reaches (check_lgr_fixes.sh events)
	integer, save :: lgr_test_event = 0

	! limit nbdymax on several processes: insert_particle does not stop
	! there, it only records that this process passed the limit by itself;
	! lgr_mpi_assign_ids decides for all processes after the release
	logical, save :: lgr_nbdymax_passed = .false.

	! release records for the particle file on several processes
	! (lgr_mpi_output): a particle can be handed over before the first
	! output after its release to a process that does not hold its
	! release element, so the process that releases it keeps, from the
	! release on (lgr_mpi_keep_release, called by lgr_mpi_assign_ids), its
	! id and its release record init (with ie the local release element,
	! positive) until the next output, which writes and clears them:
	! rel_id(1:n_rel), rel_body(1:n_rel). Kept only if the particle file
	! is written (blgr_file, set by lagrange when it opens the file).
	! lgr_nrel_total counts every release record taken on this process;
	! its sum over the processes equals the global number of particles
	! (nothing removes a particle on several processes; lgr_mpi_output
	! stops the run if it does not)
	logical, save :: blgr_file = .false.
	integer, save :: n_rel = 0
	integer, save :: lgr_nrel_total = 0
	integer, save, allocatable :: rel_id(:)
	type(lagr_body), save, allocatable :: rel_body(:)

	! lookups (lgr_mpi_lookup_init): ip_int_elem and ip_int_node sorted,
	! with the local numbers in the same order; elements of local node k:
	! lgr_ne_list(lgr_ne_ptr(k)+1:lgr_ne_ptr(k+1))
	integer, save, allocatable :: lgr_elem_key(:), lgr_elem_loc(:)
	integer, save, allocatable :: lgr_node_key(:), lgr_node_loc(:)
	integer, save, allocatable :: lgr_ne_ptr(:), lgr_ne_list(:)

	! lists of local elements shared with other ranks (lgr_mpi_topology_init):
	! shared with rank r: lgr_share_elem(lgr_share_ptr(r)+1:lgr_share_ptr(r+1)),
	! sorted by ip_int_elem; lgr_nshare(r) = length of that stretch
	integer, save, allocatable :: lgr_nshare(:)       !(0:nproc-1)
	integer, save, allocatable :: lgr_share_ptr(:)     !(0:nproc)
	integer, save, allocatable :: lgr_share_elem(:)    !local element numbers

	! side table of the tracker (lgr_mpi_side_table), in every particle
	! run (ilagr /= 0); read only after start-up. lgr_ieltv(ii,ie): > 0
	! local neighbour, 0 wall, -1 ... -999 open boundary, <= -1000 cut-off
	! side with destination rank -lgr_ieltv-1000 (equal to ieltv in a
	! serial run). lgr_side_lmax(ii,ie): layers (ilhv) of the element
	! across a cut-off side, 0 for every other side
	integer, save, allocatable :: lgr_ieltv(:,:)       !(3,nel)
	integer, save, allocatable :: lgr_side_lmax(:,:)   !(3,nel)

	! length of an error record of the side table (lgr_mpi_side_record)
	integer, parameter :: lgr_side_nfo = 14

	contains

!*******************************************************************

	subroutine lgr_mpi_check_supported

! on more than one process, the options of the particle module that are
! not supported there stop the run at start-up, before any particle is
! tracked (called by lagrange in its first call, after ilagr is read and
! before lgr_mpi_topology_init, the first release, lgr_input_shell (file
! lgrini) and lagr_init_common (file lgrtrj)). For each option that is
! set rank 0 writes "Lagrangian option NAME is not supported with MPI" and
! "run on one process, or remove NAME"; after all options are tested, a
! flush and a barrier, every process stops through shympi_abort_internal.
! A serial run is not affected (returns at once).
!
! every value is read as the model reads it, from the STR file that every
! process parses itself before the first call of lagrange, so that all
! processes see the same value and make the same decision (no process
! can be left in the barrier alone):
!   ilagr = 3     getpar('ilagr'), section $lagrg (vertical advection and
!                 diffusion: the hand-over keeps z only in single precision)
!   lbeach > 0    getpar('lbeach'), $lagrg (beaching)
!   artype /= -1  getpar('artype'), $lagrg (transit time of an area)
!   ldecay > 0    getpar('ldecay'), $lagrg (decay of particles)
!   lgrini        getfnm('lgrini'), $lagrg, not blank (initial distribution
!                 from a file)
!   ised > 0      getpar('ised'), $lagrg (sediment module)
!   ilarv > 0     getpar('ilarv'), $lagrg (larvae module)
!   icnn /= 0     getpar('icnn'), section $connec (connectivity, switched
!                 on by any value other than 0: its counts at a hand-over
!                 are not made and the release element is not held on every
!                 process)
!   lgrpps /= 0   get_bnd_par(ibc,'lgrpps') on any of the nbc boundaries
!                 (continuous release at a boundary)
!   lgrtrj        getfnm('lgrtrj'), $lagrg, not blank (release along a
!                 drifter trajectory)
!   rwhpar < 0    getpar('rwhpar'), $lagrg (horizontal diffusivity from
!                 the local diffusivity difhv of the element, lag_diff_hor;
!                 untested on several processes)
!   ipvert < -1   nint(getpar('ipvert')), $lagrg, as lagrange reads it
!                 (random vertical release: insert_particle_3d draws a
!                 random depth for each of the abs(ipvert) particles of a
!                 release point when the basin has more than one layer and
!                 ilagr = 2 (ilagr = 3 stops above), keyed on the id the
!                 particle receives, also through lgr_mpi_assign_ids
!                 (#225); in a 2D basin or with ilagr = 1 nothing is drawn,
!                 but the value stops the run there too; untested on
!                 several processes)

	use shympi, only : my_id, shympi_is_parallel
	use para, only : getpar
	use mod_bnd, only : nbc

	implicit none

	include 'mpif.h'

	integer :: nbad, ierr, ibc
	real :: pps
	character(len=256) :: fname

	if( .not. shympi_is_parallel() ) return

	nbad = 0

	if( nint(getpar('ilagr')) == 3 ) call lgr_mpi_unsupported('ilagr = 3')
	if( getpar('lbeach') > 0. ) call lgr_mpi_unsupported('lbeach')
	if( int(getpar('artype')) /= -1 ) call lgr_mpi_unsupported('artype')
	if( getpar('ldecay') > 0. ) call lgr_mpi_unsupported('ldecay')
	call getfnm('lgrini',fname)
	if( len_trim(fname) > 0 ) call lgr_mpi_unsupported('lgrini')
	if( nint(getpar('ised')) > 0 ) call lgr_mpi_unsupported('ised')
	if( nint(getpar('ilarv')) > 0 ) call lgr_mpi_unsupported('ilarv')
	if( nint(getpar('icnn')) /= 0 ) call lgr_mpi_unsupported('icnn')
	do ibc = 1, nbc
	  call get_bnd_par(ibc,'lgrpps',pps)
	  if( pps /= 0. ) then
	    call lgr_mpi_unsupported('lgrpps')
	    exit
	  end if
	end do
	call getfnm('lgrtrj',fname)
	if( len_trim(fname) > 0 ) call lgr_mpi_unsupported('lgrtrj')
	if( getpar('rwhpar') < 0. ) call lgr_mpi_unsupported('rwhpar < 0')
	if( nint(getpar('ipvert')) < -1 )				&
     &		call lgr_mpi_unsupported('ipvert < -1')

	if( nbad == 0 ) return

	if( my_id == 0 ) flush(6)
	! the MPI_Barrier calls before an abort are not checked: a barrier that
	! fails right before the abort changes nothing (here and at the others)
	call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written
	call shympi_abort_internal('error stop lagrange: option not'	&
     &		//' supported with MPI')

	contains

	subroutine lgr_mpi_unsupported(name)

! counts the option and lets rank 0 name it

	implicit none

	character(len=*), intent(in) :: name

	nbad = nbad + 1
	if( my_id == 0 ) then
	  write(6,'(a)') ' Lagrangian option '//trim(name)//' is not'	&
     &		//' supported with MPI'
	  write(6,'(a)') ' run on one process, or remove '//trim(name)
	end if

	end subroutine lgr_mpi_unsupported

	end subroutine lgr_mpi_check_supported

!*******************************************************************

	subroutine lgr_mpi_init

! initializes the MPI buffers of the Lagrangian module; needs ncust and
! the allocated particle array (called after the first
! particles are read), runs the self-tests of the particle record, of
! the side fallback particle_on_side and of find_elems_to_segment
! (lgr_selftest_segments, #252) at levdbg >= 3
!
! the lists of marks and of parked particles start with 1024 entries per
! process, whatever nbdymax (the global limit of the release), and double
! when full (lgr_mpi_grow_export, lgr_mpi_grow_park, inside the critical
! section lgr_export)
!
! test hook: if the environment variable LGR_TEST_SMALL_EXPORT is set to 1
! the lists start with 2 entries instead of 1024, so that their growth is
! exercised by a small run; LGR_TEST_GROW_FAIL=export or =park makes the
! first growth of that list on every process take the path of a failed
! allocate once (lgr_mpi_grow_export, lgr_mpi_grow_park: the run stops
! through lgr_mpi_list_check on the main thread, #242)
!
! test hook LGR_TEST_INTERNAL_FAIL=1, read here once, in a serial run too:
! makes the internal-error guard of track_single fire once per process
! (lgr_mpi_test_internal, #256)
!
! test hook LGR_TEST_VDIFF_END=N, read here once, in a serial run too:
! ends the vertical walk of the particles whose id is a multiple of N
! with their time left (lgr_test_vdiff_end, diff_body, #288); the master
! writes a line when it is on
!
! test hooks LGR_TEST_KPROF=N (N = 1, 2 or 3) and LGR_TEST_NOADV=1, read
! here once, in a serial run too: the vertical diffusivity of the
! particles is the fixed profile N (lgr_test_kprof, lag_vdiff_ele), and
! the particles are not advected (lgr_test_noadv, track_single); the
! master writes a line for each hook that is on (check_lgr_wellmixed.sh
! looks for these lines, #286, #287)
!
! test hook LGR_TEST_EVENT=K (K = 1 ... lgr_nev), read here once, in a
! serial run too: an event of kind K for the particle in slot 1 in the
! first pass (lgr_test_event, lgr_mpi_test_event, #305); the master
! writes a line when it is on
!
! test hooks of lgr_mpi_check_consistency, read here once (several
! processes only): LGR_TEST_DROP=R and LGR_TEST_DUP=R arm the fault on
! the process whose rank is R (lgr_test_drop, lgr_test_dup; see
! lgr_mpi_check_consistency); every other process ignores them
!
! decides at start-up whether lgr_mpi_check_consistency is active
! (blgr_chk): several processes and levdbg >= 2. The releases that give
! out no global ids (file lgrini or lgrtrj, lgrpps /= 0 on a boundary)
! never get here on several processes: lgr_mpi_check_supported has
! stopped the run before

	use shympi
	use para, only : getpar

	implicit none

	integer :: ierr, ndim, ist, ios, ir
	character(len=16) :: sval

	lgr_pack_size = lgr_pack_base + ncust
	bmpi_lagr = shympi_is_parallel()
	blgr_dbg = nint(getpar('levdbg')) >= 3

	call lgr_mpi_selftest_pack		!only at levdbg >= 3
	call lgr_mpi_selftest_side		!only at levdbg >= 3
	call lgr_mpi_selftest_key		!only at levdbg >= 3
	call lgr_selftest_segments		!only at levdbg >= 3

	call get_environment_variable('LGR_TEST_INTERNAL_FAIL',sval	&
     &			,status=ist)
	lgr_test_internal = ( ist == 0 .and. trim(sval) == '1' )

	call get_environment_variable('LGR_TEST_VDIFF_END',sval,status=ist)
	if( ist == 0 ) then
	  read(sval,*,iostat=ios) ir
	  if( ios == 0 ) lgr_test_vdiff_end = max(ir,0)
	end if
	if( lgr_test_vdiff_end > 0 .and. shympi_is_master() ) then
	  write(6,'(a,i0,a)') ' test hook LGR_TEST_VDIFF_END: the vertical'	&
     &		//' walk of the particles whose id is a multiple of '	&
     &		,lgr_test_vdiff_end,' ends at once with its time left'
	end if

	call get_environment_variable('LGR_TEST_KPROF',sval,status=ist)
	if( ist == 0 ) then
	  read(sval,*,iostat=ios) ir
	  if( ios == 0 ) then
	    if( ir >= 1 .and. ir <= 3 ) lgr_test_kprof = ir
	  end if
	end if
	if( lgr_test_kprof > 0 .and. shympi_is_master() ) then
	  write(6,'(a,i0)') ' test hook LGR_TEST_KPROF: the vertical'	&
     &		//' diffusivity of the particles is profile ',lgr_test_kprof
	end if

	call get_environment_variable('LGR_TEST_NOADV',sval,status=ist)
	lgr_test_noadv = ( ist == 0 .and. trim(sval) == '1' )
	if( lgr_test_noadv .and. shympi_is_master() ) then
	  write(6,'(a)') ' test hook LGR_TEST_NOADV: particles are not'	&
     &		//' advected'
	end if

	call get_environment_variable('LGR_TEST_EVENT',sval,status=ist)
	if( ist == 0 ) then
	  read(sval,*,iostat=ios) ir
	  if( ios == 0 ) then
	    if( ir >= 1 .and. ir <= lgr_nev ) lgr_test_event = ir
	  end if
	end if
	if( lgr_test_event > 0 .and. shympi_is_master() ) then
	  write(6,'(a,i0,a)') ' test hook LGR_TEST_EVENT: an event of kind '	&
     &		,lgr_test_event,' for the particle in slot 1 in the first'	&
     &		//' pass'
	end if

	if( .not. bmpi_lagr ) return

	ndim = 1024
	call get_environment_variable('LGR_TEST_SMALL_EXPORT',sval,	&
     &			status=ist)
	if( ist == 0 .and. trim(sval) == '1' ) ndim = 2

	allocate(export_dest(ndim), export_idx(ndim), export_elem(ndim)	&
     &		, export_side(ndim), export_nleft(ndim), export_tleft(ndim)	&
     &		, export_dstart(ndim), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_init: allocation')
	allocate(park_idx(ndim), park_class(ndim), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_init: allocation')

	n_export = 0
	n_export_grow = 0
	n_park = 0

	call get_environment_variable('LGR_TEST_DROP',sval,status=ist)
	if( ist == 0 ) then
	  read(sval,*,iostat=ios) ir
	  if( ios == 0 ) lgr_test_drop = ( ir == my_id )
	end if
	call get_environment_variable('LGR_TEST_DUP',sval,status=ist)
	if( ist == 0 ) then
	  read(sval,*,iostat=ios) ir
	  if( ios == 0 ) lgr_test_dup = ( ir == my_id )
	end if
	call get_environment_variable('LGR_TEST_GROW_FAIL',sval,status=ist)
	if( ist == 0 ) then
	  lgr_test_grow_export = ( trim(sval) == 'export' )
	  lgr_test_grow_park = ( trim(sval) == 'park' )
	end if

	blgr_chk = nint(getpar('levdbg')) >= 2

	end subroutine lgr_mpi_init

!*******************************************************************

	subroutine lgr_mpi_topology_init

! builds the side table of the tracker (lgr_mpi_side_table) and the
! lookups of the hand-over (lgr_mpi_lookup_init) in a particle run
! (ilagr /= 0, serial too) and, for every other rank r, the list of
! local elements shared with r (r is among id_elem(1:id_elem(0,ie),ie)),
! sorted by ip_int_elem
!
! The particle module calls this routine at its start-up, before the
! first particle step. lgr_mpi_flux_sum calls it on demand, also in a run
! without particles (semi-Lagrangian advection, itlin = 1, through
! back_trace): there only the lists are built, no side table (the old
! tracker of that path does not read it).
!
! at levdbg >= 3 the lists are checked: the length and the sum of
! ip_int_elem of the list of q for r must equal those of r for q

	use shympi
	use basin, only : nel
	use para, only : getpar

	implicit none

	include 'mpif.h'

	integer :: ie, j, r, q, ip, ierr, nproc, ntot, ibad
	integer :: nd2, nd3, nd2g, nd3g, ntmp
	logical :: bbad
	integer, allocatable :: ifill(:), ikey(:), iperm(:)
	integer, allocatable :: nall(:,:)
	integer(kind=8), allocatable :: csum(:), csall(:,:)

	nproc = n_threads

	! particle run: the test of lagrange (ilagr = 0 switches it off)
	if( nint(getpar('ilagr')) /= 0 ) then
	  call lgr_mpi_side_table
	  call lgr_mpi_lookup_init
	end if

	if( nproc <= 1 ) return

	if( allocated(lgr_nshare) ) deallocate(lgr_nshare)
	if( allocated(lgr_share_ptr) ) deallocate(lgr_share_ptr)
	if( allocated(lgr_share_elem) ) deallocate(lgr_share_elem)

	allocate(lgr_nshare(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')
	allocate(lgr_share_ptr(0:nproc), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')
	allocate(ifill(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')

	!-----------------------------------------------
	! count, then fill
	!-----------------------------------------------

	! the filter on r below (0 <= r < nproc, r /= my_id) is repeated in
	! lgr_mpi_flux_sum (lowest other holder rmin): keep the two in step,
	! or the own value there is added 0 or 2 times

	lgr_nshare = 0
	do ie = 1, nel
	  do j = 1, id_elem(0,ie)
	    r = id_elem(j,ie)
	    if( r >= 0 .and. r < nproc .and. r /= my_id ) then
	      lgr_nshare(r) = lgr_nshare(r) + 1
	    end if
	  end do
	end do

	lgr_share_ptr(0) = 0
	do r = 0, nproc-1
	  lgr_share_ptr(r+1) = lgr_share_ptr(r) + lgr_nshare(r)
	end do
	ntot = lgr_share_ptr(nproc)

	allocate(lgr_share_elem(max(ntot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')

	ifill = 0
	do ie = 1, nel
	  do j = 1, id_elem(0,ie)
	    r = id_elem(j,ie)
	    if( r >= 0 .and. r < nproc .and. r /= my_id ) then
	      ifill(r) = ifill(r) + 1
	      lgr_share_elem(lgr_share_ptr(r)+ifill(r)) = ie
	    end if
	  end do
	end do

	!-----------------------------------------------
	! sort every stretch by ip_int_elem
	!-----------------------------------------------

	do r = 0, nproc-1
	  ntmp = lgr_nshare(r)
	  if( ntmp < 2 ) cycle
	  allocate(ikey(ntmp), iperm(ntmp), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')
	  do j = 1, ntmp
	    iperm(j) = lgr_share_elem(lgr_share_ptr(r)+j)
	    ikey(j) = ip_int_elem(iperm(j))
	  end do
	  call lgr_mpi_sort_by_key(ntmp,ikey,iperm)
	  do j = 1, ntmp
	    lgr_share_elem(lgr_share_ptr(r)+j) = iperm(j)
	  end do
	  deallocate(ikey,iperm)
	end do

	deallocate(ifill)

	!-----------------------------------------------
	! consistency check
	!-----------------------------------------------

	if( nint(getpar('levdbg')) < 3 ) return

	allocate(csum(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')
	allocate(nall(0:nproc-1,0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')
	allocate(csall(0:nproc-1,0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_topology_init: allocation')

	csum = 0
	do r = 0, nproc-1
	  do j = lgr_share_ptr(r)+1, lgr_share_ptr(r+1)
	    csum(r) = csum(r) + int(ip_int_elem(lgr_share_elem(j)),8)
	  end do
	end do

	! column q of nall/csall = what rank q has for every rank
	call MPI_Allgather(lgr_nshare,nproc,MPI_INTEGER,			&
     &			nall,nproc,MPI_INTEGER,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_topology_init: MPI_Allgather')
	call MPI_Allgather(csum,nproc,MPI_INTEGER8,			&
     &			csall,nproc,MPI_INTEGER8,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_topology_init: MPI_Allgather')

	bbad = .false.
	do q = 0, nproc-1
	  do ip = q+1, nproc-1
	    if( nall(ip,q) /= nall(q,ip) .or.				&
     &		csall(ip,q) /= csall(q,ip) ) then
	      bbad = .true.
	      ibad = ip
	      exit
	    end if
	  end do
	  if( bbad ) exit
	end do

	if( bbad ) then
	  if( my_id == 0 ) then
	    write(6,*) 'lgr topology: shared lists differ for ranks ',	&
     &		q,ibad,' lengths ',nall(ibad,q),nall(q,ibad),		&
     &		' checksums ',csall(ibad,q),csall(q,ibad)
	  end if
	  call shympi_abort_internal					&
     &		('lgr_mpi_topology_init: shared lists differ')
	end if

	! count elements shared by two and by three ranks (on the main owner)

	nd2 = 0
	nd3 = 0
	do ie = 1, nel
	  if( id_elem(1,ie) /= my_id ) cycle
	  if( id_elem(0,ie) == 2 ) nd2 = nd2 + 1
	  if( id_elem(0,ie) == 3 ) nd3 = nd3 + 1
	end do
	call MPI_Allreduce(nd2,nd2g,1,MPI_INTEGER,MPI_SUM,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_topology_init: MPI_Allreduce')
	call MPI_Allreduce(nd3,nd3g,1,MPI_INTEGER,MPI_SUM,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_topology_init: MPI_Allreduce')

	if( my_id == 0 ) then
	  write(6,*) 'lgr topology: shared element lists consistent'
	  write(6,*) 'lgr topology: elements shared by 2 ranks: ',nd2g,	&
     &		' by 3 ranks: ',nd3g
	end if

	deallocate(csum,nall,csall)

	end subroutine lgr_mpi_topology_init

!*******************************************************************

	subroutine lgr_mpi_side_table

! side table of the tracker: lgr_ieltv(3,nel) and lgr_side_lmax(3,nel)
! (meaning: see the module data); called by lgr_mpi_topology_init in
! every particle run, before the first particle step
!
! serial run: lgr_ieltv = ieltv and lgr_side_lmax = 0
!
! several processes: lgr_ieltv starts from ieltv. A wall side (ieltv = 0)
! whose two end nodes are in another element of the global mesh
! (nen3v_global) is a cut-off side that set_geom_mpi left unmarked (it
! does not mark a side between two basin boundary nodes); it is set to
! -1000 - r, r the owner of one of its end nodes (the lower rank if the
! two end nodes have different owners). Marks <= -1000 are kept. Open
! boundary sides (-1 ... -999) are kept as they are: update_ielt sets -1
! on every side between two open boundary nodes, in a serial run too.
!
! Every cut-off side is checked from both sides: the rank r it names gets
! the global numbers of the two end nodes and of the element on this
! side, and answers with the global number and the layers (ilhv) of its
! local element that has both nodes and is not that element. The answer
! must be the element across the side in the global mesh, and that
! element must not be held here, or rank 0 writes the side and every
! rank aborts; lgr_side_lmax takes the layers. Every rank takes part in
! every collective call once, whatever the number of its cut-off sides
! (zero included): the pairs that exchange messages are known from an
! exchange of counts, empty pairs are skipped on both sides.
!
! at levdbg >= 3 lgr_side_lmax is also compared with the layers of the
! element across in a global array that does not go through the side
! exchange: ilhv gathered once from the main owner of every element
! (lgr_mpi_gather_global, keyed by ip_int_elem, every element exactly
! once) and broadcast; a mismatch aborts as above. Rank 0 then writes the
! global totals (a cut-off side counted once per rank that has it)

	use shympi
	use basin, only : nkn, nel, nen3v
	use levels, only : ilhv
	use mod_geom, only : ieltv, iboundv
	use para, only : getpar

	implicit none

	include 'mpif.h'

	integer, parameter :: itagq = 21704	!message tag of the queries
	integer, parameter :: itaga = 21705	!message tag of the answers

	integer :: nproc, ierr, ie, ii, iv, j, jj, r, n, nget, k
	integer :: k1, k2, kg1, kg2, ieg, ieo, nf, iex, o1, o2
	integer :: ga, la, ncut, nqtot, nrtot, nreq, nrecv
	integer :: lmin, lmax, lming, lmaxg
	integer :: ival(6), ivalg(6)
	integer :: info(lgr_side_nfo)
	logical :: bdbg				!levdbg >= 3
	integer :: nq(0:n_threads-1), nr(0:n_threads-1)
	integer :: qoff(0:n_threads), roff(0:n_threads)
	integer :: ifill(0:n_threads-1)
	integer :: ireq(2*n_threads)
	integer :: istat(MPI_STATUS_SIZE,2*n_threads)
	integer(kind=8) :: hash, hmin, hmax
	double precision :: t0, dt, dtmax
	integer, allocatable :: igptr(:), iglist(:)	!global node -> elems
	integer, allocatable :: ilptr(:), illist(:)	!local node -> elems
	integer, allocatable :: kgl(:)		!global node -> local, 0 if none
	integer, allocatable :: kel(:)		!global elem -> local, 0 if none
	integer, allocatable :: cie(:), cii(:)	!cut-off sides: element, side
	integer, allocatable :: cdest(:), cgx(:) !destination, element across
	integer, allocatable :: iord(:)		!cut-off side of each query
	integer, allocatable :: sbuf(:), rbuf(:), abuf(:), qans(:)
	integer, allocatable :: iglob(:)	!main owner's elements: global
	double precision, allocatable :: vloc(:), vglob(:) !their ilhv
	integer, allocatable :: ilhvg(:)	!ilhv of every global element

	! ival: 1 cut-off sides, 2 added, 3 added between two boundary
	! nodes, 4 open boundary sides with an element across not held
	! here, 5 sides looked up, 6 cut-off sides with a shallower neighbour

	nproc = n_threads

	!-----------------------------------------------
	! every run: copy of ieltv
	!-----------------------------------------------

	if( allocated(lgr_ieltv) ) deallocate(lgr_ieltv)
	if( allocated(lgr_side_lmax) ) deallocate(lgr_side_lmax)
	allocate(lgr_ieltv(3,nel), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')
	allocate(lgr_side_lmax(3,nel), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')

	lgr_ieltv = ieltv
	lgr_side_lmax = 0

	if( nproc <= 1 ) return

	t0 = MPI_Wtime()
	info = 0
	ival = 0

	!-----------------------------------------------
	! nen3v_global: present, the same on every rank (hash of the whole
	! array), and equal to the local elements, vertex by vertex
	!-----------------------------------------------

	hash = -1
	if( allocated(nen3v_global) ) then
	  if( size(nen3v_global,1) == 3 .and.				&
     &		size(nen3v_global,2) == nel_global ) then
	    hash = 0
	    do ie = 1, nel_global
	      do ii = 1, 3
	        hash = modulo(hash*48271_8 + int(nen3v_global(ii,ie),8)	&
     &			,2147483647_8)
	      end do
	    end do
	  end if
	end if
	call MPI_Allreduce(hash,hmin,1,MPI_INTEGER8,MPI_MIN,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	call MPI_Allreduce(hash,hmax,1,MPI_INTEGER8,MPI_MAX,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	if( hmin < 0 .or. hmin /= hmax ) then
	  if( my_id == 0 ) then
	    write(6,*) 'lgr side table: nen3v_global missing or not the'	&
     &		,' same on every rank, hash min, max: ',hmin,hmax
	    flush(6)
	  end if
	  call MPI_Barrier(MPI_COMM_WORLD,ierr)
	  call shympi_abort_internal					&
     &		('lgr_mpi_side_table: nen3v_global')
	end if

	do ie = 1, nel
	  ieg = ip_int_elem(ie)
	  do ii = 1, 3
	    if( nen3v_global(ii,ieg) /= ip_int_node(nen3v(ii,ie)) ) then
	      call lgr_mpi_side_record(info,1,ie,ii,0,0,0,0,0,0,0)
	    end if
	  end do
	end do
	call lgr_mpi_side_fail(info)

	!-----------------------------------------------
	! node to element lists of the global and of the local mesh,
	! global to local node and element numbers
	!-----------------------------------------------

	call lgr_mpi_node_elems(nkn_global,nel_global,nen3v_global	&
     &				,igptr,iglist)
	call lgr_mpi_node_elems(nkn,nel,nen3v,ilptr,illist)

	allocate(kgl(nkn_global), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')
	allocate(kel(nel_global), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')
	kgl = 0
	do k = 1, nkn
	  kgl(ip_int_node(k)) = k
	end do
	kel = 0
	do ie = 1, nel
	  kel(ip_int_elem(ie)) = ie
	end do

	!-----------------------------------------------
	! cut-off sides: marks of set_geom_mpi and walls with an element
	! across in the global mesh
	!-----------------------------------------------

	allocate(cie(3*nel), cii(3*nel), cdest(3*nel), cgx(3*nel)	&
     &		, stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')

	ncut = 0
	do ie = 1, nel
	  ieg = ip_int_elem(ie)
	  do ii = 1, 3
	    iv = ieltv(ii,ie)
	    if( iv > 0 ) cycle			!local neighbour
	    ival(5) = ival(5) + 1
	    k1 = nen3v(mod(ii,3)+1,ie)		!end nodes of side ii
	    k2 = nen3v(mod(ii+1,3)+1,ie)
	    kg1 = ip_int_node(k1)
	    kg2 = ip_int_node(k2)
	    call lgr_mpi_side_other(kg1,kg2,ieg,nkn_global,nel_global	&
     &			,nen3v_global,igptr,iglist,ieo,nf)
	    if( nf > 1 ) then		!more than two elements at the side
	      call lgr_mpi_side_record(info,2,ie,ii,iv,0,0,0,0,ieo,nf)
	      cycle
	    end if
	    if( iv == 0 ) then			!wall in ieltv
	      if( nf == 0 ) cycle		!wall in the global mesh too
	      o1 = id_node(k1)
	      o2 = id_node(k2)
	      r = min(o1,o2)
	      if( o1 == my_id .or. o2 == my_id ) then
	        call lgr_mpi_side_record(info,3,ie,ii,iv,r,0,0,0,ieo,nf)
	        cycle
	      end if
	      lgr_ieltv(ii,ie) = -1000 - r
	      ival(2) = ival(2) + 1
	      if( iboundv(k1) > 0 .and. iboundv(k2) > 0 ) then
	        ival(3) = ival(3) + 1
	      end if
	    else if( iv > -1000 ) then		!open boundary: kept
	      if( nf > 0 ) then
	        call lgr_mpi_side_other(k1,k2,ie,nkn,nel,nen3v		&
     &			,ilptr,illist,j,n)
	        if( n == 0 ) ival(4) = ival(4) + 1
	      end if
	      cycle
	    else				!mark of set_geom_mpi: kept
	      r = -iv - 1000
	      if( nf == 0 ) then
	        call lgr_mpi_side_record(info,4,ie,ii,iv,r,0,0,0,ieo,nf)
	        cycle
	      end if
	    end if
	    if( r < 0 .or. r >= nproc .or. r == my_id ) then
	      call lgr_mpi_side_record(info,5,ie,ii,lgr_ieltv(ii,ie),r	&
     &			,0,0,0,ieo,nf)
	      cycle
	    end if
	    if( kel(ieo) /= 0 ) then		!element across is held here
	      call lgr_mpi_side_record(info,9,ie,ii,lgr_ieltv(ii,ie),r	&
     &			,0,0,0,ieo,nf)
	      cycle
	    end if
	    ncut = ncut + 1
	    cie(ncut) = ie
	    cii(ncut) = ii
	    cdest(ncut) = r
	    cgx(ncut) = ieo
	  end do
	end do
	ival(1) = ncut

	call lgr_mpi_side_fail(info)

	!-----------------------------------------------
	! counts: queries to every rank, from every rank
	!-----------------------------------------------

	nq = 0
	do j = 1, ncut
	  nq(cdest(j)) = nq(cdest(j)) + 1
	end do
	call MPI_Alltoall(nq,1,MPI_INTEGER,nr,1,MPI_INTEGER		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Alltoall')

	qoff(0) = 0
	roff(0) = 0
	do r = 0, nproc-1
	  qoff(r+1) = qoff(r) + nq(r)
	  roff(r+1) = roff(r) + nr(r)
	end do
	nqtot = qoff(nproc)
	nrtot = roff(nproc)

	allocate(iord(max(nqtot,1)), sbuf(max(3*nqtot,1))		&
     &		, qans(max(3*nqtot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')
	allocate(rbuf(max(3*nrtot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')
	allocate(abuf(max(3*nrtot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_side_table: allocation')

	! queries in the order of the destination ranks: global end nodes
	! and global element on this side

	ifill = 0
	do j = 1, ncut
	  r = cdest(j)
	  ifill(r) = ifill(r) + 1
	  jj = qoff(r) + ifill(r)
	  iord(jj) = j
	  ie = cie(j)
	  ii = cii(j)
	  sbuf(3*jj-2) = ip_int_node(nen3v(mod(ii,3)+1,ie))
	  sbuf(3*jj-1) = ip_int_node(nen3v(mod(ii+1,3)+1,ie))
	  sbuf(3*jj) = ip_int_elem(ie)
	end do

	!-----------------------------------------------
	! queries: all receives, all sends, one wait
	!-----------------------------------------------

	nreq = 0
	do r = 0, nproc-1
	  if( nr(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Irecv(rbuf(3*roff(r)+1),3*nr(r),MPI_INTEGER,r,itagq	&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Irecv')
	end do
	nrecv = nreq
	do r = 0, nproc-1
	  if( nq(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Isend(sbuf(3*qoff(r)+1),3*nq(r),MPI_INTEGER,r,itagq	&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Isend')
	end do
	if( nreq > 0 ) then
	  call MPI_Waitall(nreq,ireq,istat,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Waitall')
	end if
	jj = 0
	do r = 0, nproc-1
	  if( nr(r) == 0 ) cycle
	  jj = jj + 1
	  call MPI_Get_count(istat(:,jj),MPI_INTEGER,nget,ierr)
	  if( ierr /= MPI_SUCCESS .or. nget /= 3*nr(r) ) then
	    write(6,*) 'lgr_mpi_side_table: rank ',my_id,' from rank ',r	&
     &		,' expected ',3*nr(r),' values, received ',nget
	    call shympi_abort_internal					&
     &		('lgr_mpi_side_table: message length')
	  end if
	end do
	if( jj /= nrecv ) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: internal error (receives)')

	!-----------------------------------------------
	! answers: the local element with both end nodes that is not the
	! element of the asking rank (global number, layers, how many);
	! zeros if there is none (the asking rank then fails the side)
	!-----------------------------------------------

	abuf = 0
	do jj = 1, nrtot
	  kg1 = rbuf(3*jj-2)
	  kg2 = rbuf(3*jj-1)
	  ieg = rbuf(3*jj)
	  if( kg1 < 1 .or. kg1 > nkn_global ) cycle
	  if( kg2 < 1 .or. kg2 > nkn_global ) cycle
	  k1 = kgl(kg1)
	  k2 = kgl(kg2)
	  if( k1 == 0 .or. k2 == 0 ) cycle
	  iex = 0
	  if( ieg >= 1 .and. ieg <= nel_global ) iex = kel(ieg)
	  call lgr_mpi_side_other(k1,k2,iex,nkn,nel,nen3v			&
     &			,ilptr,illist,ieo,nf)
	  if( nf == 0 ) cycle
	  abuf(3*jj-2) = ip_int_elem(ieo)
	  abuf(3*jj-1) = ilhv(ieo)
	  abuf(3*jj) = nf
	end do

	nreq = 0
	do r = 0, nproc-1
	  if( nq(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Irecv(qans(3*qoff(r)+1),3*nq(r),MPI_INTEGER,r,itaga	&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Irecv')
	end do
	nrecv = nreq
	do r = 0, nproc-1
	  if( nr(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Isend(abuf(3*roff(r)+1),3*nr(r),MPI_INTEGER,r,itaga	&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Isend')
	end do
	if( nreq > 0 ) then
	  call MPI_Waitall(nreq,ireq,istat,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Waitall')
	end if
	jj = 0
	do r = 0, nproc-1
	  if( nq(r) == 0 ) cycle
	  jj = jj + 1
	  call MPI_Get_count(istat(:,jj),MPI_INTEGER,nget,ierr)
	  if( ierr /= MPI_SUCCESS .or. nget /= 3*nq(r) ) then
	    write(6,*) 'lgr_mpi_side_table: rank ',my_id,' from rank ',r	&
     &		,' expected ',3*nq(r),' values, received ',nget
	    call shympi_abort_internal					&
     &		('lgr_mpi_side_table: message length')
	  end if
	end do
	if( jj /= nrecv ) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: internal error (receives)')

	!-----------------------------------------------
	! check: exactly one element across, the one of the global mesh
	!-----------------------------------------------

	do jj = 1, nqtot
	  j = iord(jj)
	  ie = cie(j)
	  ii = cii(j)
	  ga = qans(3*jj-2)
	  la = qans(3*jj-1)
	  nf = qans(3*jj)
	  if( nf /= 1 .or. la < 1 ) then
	    call lgr_mpi_side_record(info,6,ie,ii,lgr_ieltv(ii,ie)		&
     &			,cdest(j),ga,la,nf,cgx(j),1)
	  else if( ga /= cgx(j) ) then
	    call lgr_mpi_side_record(info,7,ie,ii,lgr_ieltv(ii,ie)		&
     &			,cdest(j),ga,la,nf,cgx(j),1)
	  else
	    lgr_side_lmax(ii,ie) = la
	  end if
	end do

	call lgr_mpi_side_fail(info)

	dt = MPI_Wtime() - t0		!the table, without the check below

	bdbg = nint(getpar('levdbg')) >= 3

	!-----------------------------------------------
	! levdbg >= 3: lgr_side_lmax against the layers of the element across
	! (global number returned by the exchange) in a global array that does
	! not go through the side exchange: ilhv of every element from its
	! main owner, gathered on rank 0 by global number (every element
	! exactly once, else abort) and broadcast
	!-----------------------------------------------

	if( bdbg ) then
	  allocate(iglob(max(nel,1)), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: allocation')
	  allocate(vloc(max(nel,1)), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: allocation')
	  allocate(vglob(nel_global), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: allocation')
	  allocate(ilhvg(nel_global), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: allocation')

	  n = 0
	  do ie = 1, nel
	    if( id_elem(1,ie) /= my_id ) cycle	!main owner only
	    n = n + 1
	    iglob(n) = ip_int_elem(ie)
	    vloc(n) = dble(ilhv(ie))
	  end do
	  call lgr_mpi_gather_global(n,iglob,vloc,nel_global,vglob,'ilhv')
	  ilhvg = 0
	  if( my_id == 0 ) ilhvg = nint(vglob)
	  call MPI_Bcast(ilhvg,nel_global,MPI_INTEGER,0,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Bcast')

	  do jj = 1, nqtot
	    j = iord(jj)
	    ie = cie(j)
	    ii = cii(j)
	    ga = qans(3*jj-2)		!element across (checked: = cgx(j))
	    if( lgr_side_lmax(ii,ie) /= ilhvg(ga) ) then
	      call lgr_mpi_side_record(info,8,ie,ii,lgr_ieltv(ii,ie)	&
     &		,cdest(j),ga,lgr_side_lmax(ii,ie),qans(3*jj),cgx(j),1	&
     &		,lg=ilhvg(ga))
	    end if
	  end do

	  call lgr_mpi_side_fail(info)

	  deallocate(iglob,vloc,vglob,ilhvg)
	end if

	deallocate(igptr,iglist,ilptr,illist,kgl,kel)
	deallocate(cie,cii,cdest,cgx)
	deallocate(iord,sbuf,qans,rbuf,abuf)

	if( .not. bdbg ) return

	!-----------------------------------------------
	! global totals, written by rank 0 (from the finished table)
	!-----------------------------------------------

	lmin = huge(lmin)
	lmax = 0
	ncut = 0
	do ie = 1, nel
	  do ii = 1, 3
	    if( lgr_ieltv(ii,ie) > -1000 ) cycle
	    ncut = ncut + 1
	    lmin = min(lmin,lgr_side_lmax(ii,ie))
	    lmax = max(lmax,lgr_side_lmax(ii,ie))
	    if( lgr_side_lmax(ii,ie) < ilhv(ie) ) ival(6) = ival(6) + 1
	  end do
	end do
	if( ncut /= ival(1) ) call shympi_abort_internal			&
     &		('lgr_mpi_side_table: internal error (count)')

	call MPI_Allreduce(ival,ivalg,6,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	call MPI_Allreduce(lmin,lming,1,MPI_INTEGER,MPI_MIN		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	call MPI_Allreduce(lmax,lmaxg,1,MPI_INTEGER,MPI_MAX		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	call MPI_Allreduce(dt,dtmax,1,MPI_DOUBLE_PRECISION,MPI_MAX	&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_table: MPI_Allreduce')
	if( ivalg(1) == 0 ) lming = 0

	if( my_id == 0 ) then
	  write(6,'(a,i0,a,i0,a)') ' lgr side table: ',ivalg(1)		&
     &		,' cut-off sides, ',ivalg(2)				&
     &		,' added to the marks of set_geom_mpi'
	  write(6,'(a,i0,a,i0,a,i0)') ' lgr side table: layers across'	&
     &		//' the cut-off sides: min ',lming,' max ',lmaxg		&
     &		,', sides with a shallower neighbour: ',ivalg(6)
	  write(6,'(a,i0,a,i0,a,i0,a,f0.4,a)') ' lgr side table: added'	&
     &		//' between two basin boundary nodes: ',ivalg(3)		&
     &		,', open boundary sides with an element across held'	&
     &		//' elsewhere: ',ivalg(4),', sides looked up: ',ivalg(5)	&
     &		,', time: ',dtmax,' s'
	  write(6,'(a)') ' lgr side table: layer counts across cut-off'	&
     &		//' sides agree with the global layer counts'
	end if

	end subroutine lgr_mpi_side_table

!*******************************************************************

	subroutine lgr_mpi_side_record(info,icode,ie,ii,iv,r,ga,la,nfa	&
     &					,gx,nfx,lg)

! keeps the first error of the side table found on this rank in info
! (later errors are not recorded); info(1) = 0 means no error

	use shympi, only : my_id, ip_int_node, ip_int_elem
	use basin, only : nen3v

	implicit none

	integer, intent(inout) :: info(lgr_side_nfo)	!error record
	integer, intent(in) :: icode		!error code (> 0)
	integer, intent(in) :: ie, ii		!local element, side
	integer, intent(in) :: iv		!mark of the side
	integer, intent(in) :: r		!destination rank
	integer, intent(in) :: ga, la, nfa	!answer: element, layers, found
	integer, intent(in) :: gx, nfx		!element across, found (global)
	integer, intent(in), optional :: lg	!layers of ga, global array

	if( info(1) /= 0 ) return

	info(1) = icode
	info(2) = my_id
	info(3) = ip_int_elem(ie)
	info(4) = ii
	info(5) = ip_int_node(nen3v(mod(ii,3)+1,ie))
	info(6) = ip_int_node(nen3v(mod(ii+1,3)+1,ie))
	info(7) = iv
	info(8) = r
	info(9) = ga
	info(10) = la
	info(11) = nfa
	info(12) = gx
	info(13) = nfx
	info(14) = 0
	if( present(lg) ) info(14) = lg

	end subroutine lgr_mpi_side_record

!*******************************************************************

	subroutine lgr_mpi_side_fail(info)

! collective, called by every rank: returns if no rank has an error in
! its record info (lgr_mpi_side_record); otherwise rank 0 writes the
! record of the lowest rank with an error and every rank aborts

	use shympi

	implicit none

	include 'mpif.h'

	integer, intent(in) :: info(lgr_side_nfo)	!error record of this rank

	integer :: ic, irmin, ierr
	integer :: iall(lgr_side_nfo)
	integer :: iexte, iext1, iext2
	character(len=80) :: text

	ic = n_threads
	if( info(1) /= 0 ) ic = my_id
	call MPI_Allreduce(ic,irmin,1,MPI_INTEGER,MPI_MIN			&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_fail: MPI_Allreduce')
	if( irmin >= n_threads ) return

	iall = info
	call MPI_Bcast(iall,lgr_side_nfo,MPI_INTEGER,irmin,MPI_COMM_WORLD	&
     &			,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_side_fail: MPI_Bcast')

	select case( iall(1) )
	case( 1 )
	  text = 'nen3v_global differs from a local element'
	case( 2 )
	  text = 'more than two elements at a side of the global mesh'
	case( 3 )
	  text = 'cut-off side with an end node owned by this rank'
	case( 4 )
	  text = 'marked side without an element across in the global mesh'
	case( 5 )
	  text = 'destination of a cut-off side is not another rank'
	case( 6 )
	  text = 'cut-off side not seen from both sides (not found)'
	case( 7 )
	  text = 'cut-off side not seen from both sides (other element)'
	case( 8 )
	  text = 'layer count across a cut-off side differs from the'	&
     &		//' global layer count'
	case( 9 )
	  text = 'element across a cut-off side is held by this rank'
	case default
	  text = 'unknown error'
	end select

	if( my_id == 0 ) then
	  iexte = 0
	  iext1 = 0
	  iext2 = 0
	  if( iall(3) >= 1 .and. iall(3) <= nel_global )			&
     &		iexte = ip_ext_elem(iall(3))
	  if( iall(5) >= 1 .and. iall(5) <= nkn_global )			&
     &		iext1 = ip_ext_node(iall(5))
	  if( iall(6) >= 1 .and. iall(6) <= nkn_global )			&
     &		iext2 = ip_ext_node(iall(6))
	  write(6,*) 'lgr side table: ',trim(text)
	  write(6,*) 'lgr side table: rank, element (external), side: '	&
     &		,iall(2),iall(3),iexte,iall(4)
	  write(6,*) 'lgr side table: end nodes (external): '		&
     &		,iall(5),iall(6),iext1,iext2
	  write(6,*) 'lgr side table: mark, destination: ',iall(7),iall(8)
	  write(6,*) 'lgr side table: answer element, layers, found: '	&
     &		,iall(9),iall(10),iall(11)
	  write(6,*) 'lgr side table: element across in the global mesh'	&
     &		,', found: ',iall(12),iall(13)
	  if( iall(1) == 8 ) then
	    write(6,*) 'lgr side table: layer counts, exchange and global:'	&
     &		,iall(10),iall(14)
	  end if
	  flush(6)
	end if
	call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written

	call shympi_abort_internal('lgr_mpi_side_table: '//trim(text))

	end subroutine lgr_mpi_side_fail

!*******************************************************************

	subroutine lgr_mpi_node_elems(nk,ne,nen,iptr,ilist)

! node to element lists of a mesh with nk nodes and ne elements nen(3,ne):
! the elements of node k are ilist(iptr(k)+1:iptr(k+1)), in increasing
! element number

	implicit none

	integer, intent(in) :: nk, ne
	integer, intent(in) :: nen(3,ne)
	integer, allocatable, intent(out) :: iptr(:)	!(nk+1)
	integer, allocatable, intent(out) :: ilist(:)	!(3*ne)

	integer :: ie, ii, k, ierr
	integer, allocatable :: icur(:)

	allocate(iptr(nk+1), ilist(max(3*ne,1)), icur(nk), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_node_elems: allocation')

	iptr = 0
	do ie = 1, ne
	  do ii = 1, 3
	    k = nen(ii,ie)
	    if( k < 1 .or. k > nk ) then
	      write(6,*) 'lgr_mpi_node_elems: ie,ii,k,nk: ',ie,ii,k,nk
	      call shympi_abort_internal('lgr_mpi_node_elems: node')
	    end if
	    iptr(k+1) = iptr(k+1) + 1
	  end do
	end do
	do k = 1, nk
	  iptr(k+1) = iptr(k+1) + iptr(k)
	end do

	icur(1:nk) = iptr(1:nk)
	do ie = 1, ne
	  do ii = 1, 3
	    k = nen(ii,ie)
	    icur(k) = icur(k) + 1
	    ilist(icur(k)) = ie
	  end do
	end do

	deallocate(icur)

	end subroutine lgr_mpi_node_elems

!*******************************************************************

	subroutine lgr_mpi_side_other(ka,kb,iexcl,nk,ne,nen,iptr,ilist	&
     &					,ieo,nf)

! the elements other than iexcl of a mesh nen(3,ne) that have both nodes
! ka and kb: nf of them, ieo the first (0 if none); iptr, ilist are the
! node to element lists of the mesh (lgr_mpi_node_elems)

	implicit none

	integer, intent(in) :: ka, kb		!end nodes of the side
	integer, intent(in) :: iexcl		!element left out (0: none)
	integer, intent(in) :: nk, ne
	integer, intent(in) :: nen(3,ne)
	integer, intent(in) :: iptr(nk+1)
	integer, intent(in) :: ilist(*)
	integer, intent(out) :: ieo		!first element found
	integer, intent(out) :: nf		!number of elements found

	integer :: j, ie

	ieo = 0
	nf = 0
	do j = iptr(ka)+1, iptr(ka+1)
	  ie = ilist(j)
	  if( ie == iexcl ) cycle
	  if( nen(1,ie) == kb .or. nen(2,ie) == kb .or.			&
     &		nen(3,ie) == kb ) then
	    nf = nf + 1
	    if( ieo == 0 ) ieo = ie
	  end if
	end do

	end subroutine lgr_mpi_side_other

!*******************************************************************

	subroutine lgr_mpi_sort_by_key(n,key,idx)

! sorts idx(1:n) by increasing key(1:n) (shell sort); keys are unique

	implicit none

	integer, intent(in) :: n
	integer, intent(inout) :: key(n)
	integer, intent(inout) :: idx(n)

	integer :: gap, i, j, kt, it

	gap = n / 2
	do while( gap > 0 )
	  do i = gap+1, n
	    kt = key(i)
	    it = idx(i)
	    j = i
	    do while( j > gap )
	      if( key(j-gap) <= kt ) exit
	      key(j) = key(j-gap)
	      idx(j) = idx(j-gap)
	      j = j - gap
	    end do
	    key(j) = kt
	    idx(j) = it
	  end do
	  gap = gap / 2
	end do

	end subroutine lgr_mpi_sort_by_key

!*******************************************************************

	function lgr_mpi_bisect(n,key,ival)

! position of ival in key(1:n) (increasing, unique), 0 if it is absent

	implicit none

	integer :: lgr_mpi_bisect
	integer, intent(in) :: n
	integer, intent(in) :: key(n)
	integer, intent(in) :: ival

	integer :: lo, hi, mid

	lgr_mpi_bisect = 0
	lo = 1
	hi = n
	do while( lo <= hi )
	  mid = (lo + hi) / 2
	  if( key(mid) == ival ) then
	    lgr_mpi_bisect = mid
	    return
	  else if( key(mid) < ival ) then
	    lo = mid + 1
	  else
	    hi = mid - 1
	  end if
	end do

	end function lgr_mpi_bisect

!*******************************************************************

	subroutine lgr_mpi_lookup_init

! lookups of lgr_mpi_find_elem, lgr_mpi_find_node and the hand-over:
! the global numbers of the local elements (ip_int_elem) and nodes
! (ip_int_node) sorted, with the local numbers in the same order, for
! bisection; the node to element lists of the local mesh. Called by
! lgr_mpi_topology_init in every particle run (serial too), before the
! first particle step

	use shympi, only : ip_int_elem, ip_int_node
	use basin, only : nkn, nel, nen3v

	implicit none

	integer :: ie, k, ierr

	if( allocated(lgr_elem_key) ) deallocate(lgr_elem_key,lgr_elem_loc)
	if( allocated(lgr_node_key) ) deallocate(lgr_node_key,lgr_node_loc)
	if( allocated(lgr_ne_ptr) ) deallocate(lgr_ne_ptr)
	if( allocated(lgr_ne_list) ) deallocate(lgr_ne_list)

	allocate(lgr_elem_key(nel), lgr_elem_loc(nel), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_lookup_init: allocation')
	allocate(lgr_node_key(nkn), lgr_node_loc(nkn), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_lookup_init: allocation')

	do ie = 1, nel
	  lgr_elem_key(ie) = ip_int_elem(ie)
	  lgr_elem_loc(ie) = ie
	end do
	call lgr_mpi_sort_by_key(nel,lgr_elem_key,lgr_elem_loc)

	do k = 1, nkn
	  lgr_node_key(k) = ip_int_node(k)
	  lgr_node_loc(k) = k
	end do
	call lgr_mpi_sort_by_key(nkn,lgr_node_key,lgr_node_loc)

	! bisection needs distinct keys
	do ie = 2, nel
	  if( lgr_elem_key(ie) <= lgr_elem_key(ie-1) ) then
	    call shympi_abort_internal					&
     &		('lgr_mpi_lookup_init: global element numbers repeat')
	  end if
	end do
	do k = 2, nkn
	  if( lgr_node_key(k) <= lgr_node_key(k-1) ) then
	    call shympi_abort_internal					&
     &		('lgr_mpi_lookup_init: global node numbers repeat')
	  end if
	end do

	call lgr_mpi_node_elems(nkn,nel,nen3v,lgr_ne_ptr,lgr_ne_list)

	end subroutine lgr_mpi_lookup_init

!*******************************************************************

	subroutine lgr_mpi_flux_sum_3d(flux)

! adds the partial side fluxes of the ranks that hold an element
! (layers 1..ilhv(ie)); returns at once in a serial run

	use levels, only : nlvdi
	use basin, only : nel

	implicit none

	real, intent(inout) :: flux(nlvdi,3,nel)

	call lgr_mpi_flux_sum(nlvdi,.true.,flux)

	end subroutine lgr_mpi_flux_sum_3d

!*******************************************************************

	subroutine lgr_mpi_flux_sum_2d(flux)

! adds the partial side fluxes of the ranks that hold an element (2D);
! returns at once in a serial run

	use basin, only : nel

	implicit none

	real, intent(inout) :: flux(3,nel)

	call lgr_mpi_flux_sum(1,.false.,flux)

	end subroutine lgr_mpi_flux_sum_2d

!*******************************************************************

	subroutine lgr_mpi_flux_sum(nlvd,b3d,flux)

! sum of the partial side fluxes across the ranks that hold an element
!
! In the node loop every rank adds only the contributions of its own
! nodes, so a shared element holds a partial value on each of its holders.
! To every rank r it shares elements with (lgr_share_elem), a rank sends
! its own partial values and receives those of r. Message: the shared
! elements in list order, for each ii = 1..3, l = 1..nl with nl = ilhv(ie)
! in 3D and nl = 1 in 2D. ilhv(ie) depends only on the element (hm3v, hlv),
! so both ranks of a pair know the length; nlvdi may differ between ranks.
! The received length is checked. Every send is packed before anything is
! added. The partial values are then added in increasing rank order
! starting from zero, so all holders of an element get the same sum.

	use shympi
	use levels, only : ilhv
	use basin, only : nel

	implicit none

	include 'mpif.h'

	integer, intent(in) :: nlvd		!first dimension of flux
	logical, intent(in) :: b3d		!true: layers 1..ilhv(ie), else 1
	real, intent(inout) :: flux(nlvd,3,nel)

	integer, parameter :: itag3 = 21703	!message tag in 3D
	integer, parameter :: itag2 = 21702	!message tag in 2D

	integer :: nproc, r, q, ir, j, jj, ie, ii, l, nl, ip, n, ierr
	integer :: itag, nreq, nrecv, ntot, nget, rmin
	integer :: noff(0:n_threads)		!offset of rank r in the buffers
	integer :: ireq(2*n_threads)
	integer :: istat(MPI_STATUS_SIZE,2*n_threads)
	real, allocatable :: sbuf(:), rbuf(:)

	nproc = n_threads

	if( nproc <= 1 ) return

	if( .not. allocated(lgr_nshare) ) call lgr_mpi_topology_init

	itag = itag2
	if( b3d ) itag = itag3

	!-----------------------------------------------
	! offsets and buffers
	!-----------------------------------------------

	noff(0) = 0
	do r = 0, nproc-1
	  n = 0
	  do j = lgr_share_ptr(r)+1, lgr_share_ptr(r+1)
	    ie = lgr_share_elem(j)
	    nl = 1
	    if( b3d ) nl = ilhv(ie)
	    if( nl < 1 .or. nl > nlvd ) then
	      write(6,*) 'lgr_mpi_flux_sum: ie,nl,nlvd: ',ie,nl,nlvd
	      call shympi_abort_internal('lgr_mpi_flux_sum: layers')
	    end if
	    n = n + 3*nl
	  end do
	  noff(r+1) = noff(r) + n
	end do
	ntot = noff(nproc)

	allocate(sbuf(max(ntot,1)), rbuf(max(ntot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal				&
     &		('lgr_mpi_flux_sum: allocation')

	!-----------------------------------------------
	! pack own partial values (before anything is added)
	!-----------------------------------------------

	ip = 0
	do j = 1, lgr_share_ptr(nproc)
	  ie = lgr_share_elem(j)
	  nl = 1
	  if( b3d ) nl = ilhv(ie)
	  do ii = 1, 3
	    do l = 1, nl
	      ip = ip + 1
	      sbuf(ip) = flux(l,ii,ie)
	    end do
	  end do
	end do

	!-----------------------------------------------
	! exchange: all receives, all sends, one wait
	!-----------------------------------------------

	nreq = 0
	do r = 0, nproc-1
	  n = noff(r+1) - noff(r)
	  if( n == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Irecv(rbuf(noff(r)+1),n,MPI_REAL,r,itag		&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_flux_sum: MPI_Irecv')
	end do
	nrecv = nreq

	do r = 0, nproc-1
	  n = noff(r+1) - noff(r)
	  if( n == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Isend(sbuf(noff(r)+1),n,MPI_REAL,r,itag		&
     &		,MPI_COMM_WORLD,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_flux_sum: MPI_Isend')
	end do

	if( nreq > 0 ) then
	  call MPI_Waitall(nreq,ireq,istat,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_flux_sum: MPI_Waitall')
	end if

	! the receives are requests 1..nrecv, in increasing rank order
	jj = 0
	do r = 0, nproc-1
	  n = noff(r+1) - noff(r)
	  if( n == 0 ) cycle
	  jj = jj + 1
	  call MPI_Get_count(istat(:,jj),MPI_REAL,nget,ierr)
	  if( ierr /= MPI_SUCCESS .or. nget /= n ) then
	    write(6,*) 'lgr_mpi_flux_sum: rank ',my_id,' from rank ',r	&
     &		,' expected ',n,' values, received ',nget
	    call shympi_abort_internal					&
     &		('lgr_mpi_flux_sum: message length')
	  end if
	end do
	if( jj /= nrecv ) call shympi_abort_internal			&
     &		('lgr_mpi_flux_sum: internal error (receives)')

	!-----------------------------------------------
	! sum in increasing rank order, starting from zero
	!-----------------------------------------------

	do j = 1, lgr_share_ptr(nproc)
	  ie = lgr_share_elem(j)
	  nl = 1
	  if( b3d ) nl = ilhv(ie)
	  flux(1:nl,:,ie) = 0.
	end do

	do r = 0, nproc-1
	  if( r == my_id ) then
	    ! own values, once per element: from the stretch of the
	    ! lowest other holder rmin (the same rule that built the lists)
	    ! the filter on ir repeats the one in lgr_mpi_topology_init
	    ! (count and fill loops): keep the two in step, or the own
	    ! value is added 0 or 2 times
	    do q = 0, nproc-1
	      ip = noff(q)
	      do j = lgr_share_ptr(q)+1, lgr_share_ptr(q+1)
	        ie = lgr_share_elem(j)
	        nl = 1
	        if( b3d ) nl = ilhv(ie)
	        rmin = nproc
	        do jj = 1, id_elem(0,ie)
	          ir = id_elem(jj,ie)
	          if( ir >= 0 .and. ir < nproc .and. ir /= my_id ) then
	            rmin = min(rmin,ir)
	          end if
	        end do
	        if( rmin == q ) then
	          do ii = 1, 3
	            do l = 1, nl
	              flux(l,ii,ie) = flux(l,ii,ie) + sbuf(ip+(ii-1)*nl+l)
	            end do
	          end do
	        end if
	        ip = ip + 3*nl
	      end do
	    end do
	  else
	    ip = noff(r)
	    do j = lgr_share_ptr(r)+1, lgr_share_ptr(r+1)
	      ie = lgr_share_elem(j)
	      nl = 1
	      if( b3d ) nl = ilhv(ie)
	      do ii = 1, 3
	        do l = 1, nl
	          ip = ip + 1
	          flux(l,ii,ie) = flux(l,ii,ie) + rbuf(ip)
	        end do
	      end do
	    end do
	  end if
	end do

	deallocate(sbuf,rbuf)

	end subroutine lgr_mpi_flux_sum

!*******************************************************************

	subroutine lgr_mpi_mark_side(i, ie, iside, t_left, n_left, d_start)

! records that particle i stopped on side iside of local element ie, a
! cut-off side, with the time t_left and the crossings n_left still to do
! and the distance d_start from the nearest vertex at the start of its step
! (#315, for the node-sink test of the process across);
! it goes to rank -lgr_ieltv(iside,ie) - 1000. Sets lgr_marked(i) (the
! particle's own slot); the shared lists are read and written only inside
! the critical section lgr_export and grow when full (the argument test
! reads only values fixed after start-up: lgr_ieltv, bmpi_lagr, which is
! true exactly when the lists are allocated). Called by the tracker,
! inside the parallel loop of drogue or outside any parallel region.
! A failed argument test or a failed growth is recorded
! (lgr_mpi_list_fail) instead of aborting here, which can be a worker
! thread: nothing is appended, the particle stays marked (the caller
! stops its step) and the main thread aborts in lgr_mpi_list_check (#242)

	use shympi, only : my_id, n_threads

	implicit none

	integer, intent(in) :: i		!particle (slot)
	integer, intent(in) :: ie		!local element it is leaving
	integer, intent(in) :: iside		!side of ie (1..3)
	real, intent(in) :: t_left		!time still to advect
	integer, intent(in) :: n_left		!crossings still allowed
	double precision, intent(in) :: d_start	!d at the start of the step

	integer :: r
	logical :: bok

	r = -lgr_ieltv(iside,ie) - 1000

	lgr_marked(i) = 1		!also on a failure: the caller stops

!$OMP CRITICAL (lgr_export)
	if( r < 0 .or. r >= n_threads .or. r == my_id			&
     &		.or. .not. bmpi_lagr ) then
	  call lgr_mpi_list_fail(3,i,ie,iside,lgr_ieltv(iside,ie),0)
	else
	  bok = .true.
	  if( n_export + 1 > size(export_idx) ) then
	    call lgr_mpi_grow_export(i,bok)
	  end if
	  if( bok ) then
	    n_export = n_export + 1
	    export_idx(n_export) = i
	    export_dest(n_export) = r
	    export_elem(n_export) = ie
	    export_side(n_export) = iside
	    export_nleft(n_export) = n_left
	    export_tleft(n_export) = t_left
	    export_dstart(n_export) = d_start
	  end if
	end if
!$OMP END CRITICAL (lgr_export)

	end subroutine lgr_mpi_mark_side

!*******************************************************************

	subroutine lgr_mpi_grow_export(i,bok)

! doubles the size of the lists of marks (new lists, copy of the n_export
! entries in use, move_alloc); called inside the critical section
! lgr_export of lgr_mpi_mark_side, possibly by a worker thread. If the
! allocation fails (or the test hook LGR_TEST_GROW_FAIL=export takes this
! path once) the lists stay as they are, the failure is recorded
! (lgr_mpi_list_fail; lgr_mpi_list_check aborts on the main thread with
! the message 'lgr_mpi_grow_export: allocation') and bok is false: the
! caller appends nothing

	use shympi, only : my_id

	implicit none

	integer, intent(in) :: i		!slot of the particle to append
	logical, intent(out) :: bok		!the lists have grown

	integer :: ierr, nnew, ith
	integer, allocatable :: idest(:), iidx(:), ielem(:), iside(:)
	integer, allocatable :: inleft(:)
	real, allocatable :: rtleft(:)
	double precision, allocatable :: rdstart(:)

	nnew = 2*max(size(export_idx), 1)

	if( lgr_test_grow_export ) then	!test hook: a failed allocate, once
	  lgr_test_grow_export = .false.
	  ierr = -1
	else
	  allocate(idest(nnew), iidx(nnew), ielem(nnew), iside(nnew)	&
     &		, inleft(nnew), rtleft(nnew), rdstart(nnew), stat=ierr)
	end if
	if( ierr /= 0 ) then
	  call lgr_mpi_list_fail(1,i,nnew,ierr,size(export_idx),0)
	  bok = .false.
	  return
	end if

	idest(1:n_export) = export_dest(1:n_export)
	iidx(1:n_export) = export_idx(1:n_export)
	ielem(1:n_export) = export_elem(1:n_export)
	iside(1:n_export) = export_side(1:n_export)
	inleft(1:n_export) = export_nleft(1:n_export)
	rtleft(1:n_export) = export_tleft(1:n_export)
	rdstart(1:n_export) = export_dstart(1:n_export)
	call move_alloc(rdstart,export_dstart)
	call move_alloc(idest,export_dest)
	call move_alloc(iidx,export_idx)
	call move_alloc(ielem,export_elem)
	call move_alloc(iside,export_side)
	call move_alloc(inleft,export_nleft)
	call move_alloc(rtleft,export_tleft)

	n_export_grow = n_export_grow + 1
	if( blgr_dbg ) then
	  call openmp_get_thread_num(ith)
	  write(6,*) 'lgr_mpi_grow_export: rank ',my_id,		&
     &		' new size ',nnew,' growth number ',n_export_grow	&
     &		,' OpenMP thread ',ith
	end if
	bok = .true.

	end subroutine lgr_mpi_grow_export

!*******************************************************************

	subroutine lgr_mpi_list_fail(kind,i,i1,i2,i3,i4,msg)

! records a failure of the lists of marks or of parked particles, or an
! internal-error guard of the tracker (kind: see lgr_list_fail at the top
! of the module) found for the particle in slot i, with four values for
! the message, the OpenMP thread that found it and, for kind 5, the
! message the guard aborts with (msg); only the first failure of this
! process is kept. Called inside the critical section lgr_export, inside
! the particle loop of drogue or outside any parallel region; it makes no
! MPI call (#242: a worker thread must not, MPI_THREAD_FUNNELED).
! lgr_mpi_list_check reports and aborts

	implicit none

	integer, intent(in) :: kind		!1 to 5
	integer, intent(in) :: i		!particle (slot)
	integer, intent(in) :: i1, i2, i3, i4	!values of the message
	character(len=*), intent(in), optional :: msg	!abort message (kind 5)

	integer :: ith

	if( lgr_list_fail /= 0 ) return		!the first one is reported
	call openmp_get_thread_num(ith)
	lgr_list_fail = kind
	lgr_list_info = (/ i, i1, i2, i3, i4, ith /)
	lgr_list_msg = ' '
	if( present(msg) ) lgr_list_msg = msg

	end subroutine lgr_mpi_list_fail

!*******************************************************************

	subroutine lgr_mpi_list_check(where)

! called by the main thread outside any parallel region: by drogue right
! after its particle loop (before the global count, its first collective
! call) and by lgr_mpi_handover before the collective call of every
! round (the marks and parkings of the step 5 of the round before). If a
! failure of the lists, or an internal-error guard of the tracker hit in
! the particle loop (kind 5, #256), was recorded on this process
! (lgr_mpi_list_fail), writes what failed and stops every process
! through shympi_abort_internal with the message of the routine that
! found it; the other processes wait in their next collective call until
! MPI_ABORT ends them. Before that it writes the events of the tracker
! recorded in the pass (lgr_events, #288, #294: among them the values of
! the internal error). Nothing is recorded in a run that works: then it
! returns at once and changes nothing (#242)

	use shympi, only : my_id

	implicit none

	character(len=*), intent(in) :: where	!caller, for the message

	integer :: k(6)

	if( lgr_list_fail == 0 ) return

	call lgr_events			!the events of the pass (#294)

	k = lgr_list_info
	select case( lgr_list_fail )
	case( 1 )
	  write(6,'(a,i0,a,i0,a,i0,a,i0,a,i0,a,i0,a)') ' lgr_mpi_list_check:'	&
     &		//' rank ',my_id,' ('//where//'): the list of marks at'	&
     &		//' cut-off sides could not grow from ',k(4),' to ',k(2)	&
     &		,' entries (allocate stat ',k(3),'); particle slot ',k(1)	&
     &		,' was left out of the step (found by OpenMP thread ',k(6)	&
     &		,')'
	  flush(6)
	  call shympi_abort_internal('lgr_mpi_grow_export: allocation')
	case( 2 )
	  write(6,'(a,i0,a,i0,a,i0,a,i0,a,i0,a,i0,a)') ' lgr_mpi_list_check:'	&
     &		//' rank ',my_id,' ('//where//'): the list of parked'	&
     &		//' particles could not grow from ',k(4),' to ',k(2)	&
     &		,' entries (allocate stat ',k(3),'); particle slot ',k(1)	&
     &		,' was left out of the step (found by OpenMP thread ',k(6)	&
     &		,')'
	  flush(6)
	  call shympi_abort_internal('lgr_mpi_grow_park: allocation')
	case( 3 )
	  write(6,'(a,i0,a)') ' lgr_mpi_list_check: rank ',my_id		&
     &		,' ('//where//'): a mark at a side that is not a cut-off'	&
     &		//' side of a parallel run'
	  write(6,*) 'lgr_mpi_mark_side: i,ie,iside,mark: ',k(1:4)
	  flush(6)
	  call shympi_abort_internal('lgr_mpi_mark_side: not a cut-off'	&
     &		//' side of a parallel run')
	case( 4 )
	  write(6,'(a,i0,a)') ' lgr_mpi_list_check: rank ',my_id		&
     &		,' ('//where//'): a parking that is not one of a parallel'	&
     &		//' run'
	  write(6,*) 'lgr_mpi_park: rank,i,phase,class: ',my_id,k(1:3)
	  flush(6)
	  call shympi_abort_internal('lgr_mpi_park: not a parking of a'	&
     &		//' parallel run')
	case( 5 )
	  write(6,'(a,i0,a,i0,a)') ' lgr_mpi_list_check: rank ',my_id		&
     &		,' ('//where//'): an internal error found in the particle'	&
     &		//' loop by OpenMP thread ',k(6),', the run stops with its'	&
     &		//' message:'
	  flush(6)
	  call shympi_abort_internal(trim(lgr_list_msg))
	case default
	  write(6,*) 'lgr_mpi_list_check: rank ',my_id,' kind '		&
     &		,lgr_list_fail
	  call shympi_abort_internal('lgr_mpi_list_check: internal error')
	end select

	end subroutine lgr_mpi_list_check

!*******************************************************************

	subroutine lgr_mpi_test_internal(tmax)

! test hook LGR_TEST_INTERNAL_FAIL=1 (lgr_test_internal, read once by
! lgr_mpi_init; never written after that): called by track_single, inside
! the particle loop of drogue, with the travel time of the particle. The
! first particle a thread other than 0 takes on this process (in a loop
! run by one thread: the first particle) gets tmax = -1, so that the
! internal-error guard of track_single fires once per process; the count
! of takers is an OMP atomic capture. A run without the hook returns at
! once (#256)

	implicit none

	real, intent(inout) :: tmax		!travel time of the particle

	integer :: ith, n
	logical :: openmp_in_parallel

	if( .not. lgr_test_internal ) return

	call openmp_get_thread_num(ith)
	if( ith == 0 .and. openmp_in_parallel() ) return

!$OMP ATOMIC CAPTURE
	n = lgr_test_internal_n
	lgr_test_internal_n = lgr_test_internal_n + 1
!$OMP END ATOMIC

	if( n == 0 ) then
	  write(6,'(a,i0)') ' lgr_mpi_test_internal: travel time set'	&
     &		//' negative by OpenMP thread ',ith
	  tmax = -1.
	end if

	end subroutine lgr_mpi_test_internal

!*******************************************************************

	subroutine lgr_mpi_test_event(i)

! test hook LGR_TEST_EVENT=K (lgr_test_event, read once by lgr_mpi_init;
! never written after that), #305: called by track_single at its start,
! inside the particle loop of drogue, before the particle's own early
! returns. In the first pass (lgr_step = 1) the particle in slot 1 of
! this process records an event of kind K (lgr_event) with fixed values:
! key 0 (kept before any event of a particle), the integer values 1 ...
! lgr_ev_ni, the real values 0.5, 1.5, ... (lgr_ev_nd of them) and, for
! kind 18 (lgr_ev_xi_check, whose sites name themselves), the text
! LGR_TEST_EVENT; lgr_events writes what the kind's descriptor takes of
! them (lgr_event_desc). For a kind that stops the run it then calls
! lgr_internal_error with the message "error stop lgr_mpi_test_event:
! kind K", which aborts at once outside an active parallel region and
! records the error inside one (the caller returns after it). Kind 23 is
! not recorded here: diff_body forces the error of its xy2xi_ierr for
! that particle instead. The slot and the pass are read-only state, so
! the same particle fires on any number of threads, and nothing saved is
! written here. A run without the hook returns at once

	implicit none

	integer, intent(in) :: i		!particle (slot)

	integer :: j,ni,nd
	logical :: brun,bfix
	integer :: ival(lgr_ev_ni)
	double precision :: dval(lgr_ev_nd)
	character(len=32) :: chead
	character(len=80) :: ctext
	character(len=20) :: cname(lgr_ev_ni+lgr_ev_nd)
	character(len=40) :: cmsg

	if( lgr_test_event <= 0 ) return
	if( lgr_test_event == lgr_ev_xy2xi ) return	!forced in diff_body
	if( i /= 1 ) return
	if( lgr_step /= 1 ) return

	do j=1,lgr_ev_ni
	  ival(j) = j
	end do
	do j=1,lgr_ev_nd
	  dval(j) = j - 0.5d0
	end do
	if( lgr_test_event == lgr_ev_xi_check ) then
	  call lgr_event(lgr_test_event,0,ival,dval,'LGR_TEST_EVENT')
	else
	  call lgr_event(lgr_test_event,0,ival,dval)
	end if

	call lgr_event_desc(lgr_test_event,chead,ctext,brun,ni,nd,cname,bfix)
	if( brun ) return			!the run goes on
	write(cmsg,'(a,i0)') 'error stop lgr_mpi_test_event: kind '	&
     &		,lgr_test_event
	call lgr_internal_error(trim(cmsg))

	end subroutine lgr_mpi_test_event

!*******************************************************************

	pure function lgr_mpi_search_key(ie, ieold, n)

! the place of element ie in the search of find_elem_from_old
! (src/utils/shyutil/find.f90) from element ieold in a mesh of n elements,
! as one integer: 0 for ieold, which is tested first; then the search
! tests in step k = 1 .. n-1 first ieold-k (downward walk) and then
! ieold+k (upward walk), each walk wrapping around at 1 and at n. Element
! ie is reached by the downward walk in step d = mod(ieold-ie,n) and by
! the upward walk in step u = n-d, so its key is min(2*d-1, 2*u). The
! element that search returns for a point is the one with the smallest
! key among the elements that contain the point; distinct elements have
! distinct keys. On several processes all numbers are global
! (ip_int_elem, n = nel_global). ie, ieold in 1..n.

	implicit none

	integer :: lgr_mpi_search_key
	integer, intent(in) :: ie		!element tested
	integer, intent(in) :: ieold		!element the search starts from
	integer, intent(in) :: n		!number of elements

	integer :: id, iu

	if( ie == ieold ) then
	  lgr_mpi_search_key = 0
	else
	  id = modulo(ieold-ie,n)		!step of the downward walk
	  iu = n - id				!step of the upward walk
	  lgr_mpi_search_key = min(2*id-1,2*iu)
	end if

	end function lgr_mpi_search_key

!*******************************************************************

	subroutine lgr_mpi_selftest_key

! self-test of lgr_mpi_search_key at levdbg >= 3 (called by lgr_mpi_init
! on every process; prints nothing, the result goes into the lines of
! lgr_mpi_relocate_stats): for every mesh size n = 1 .. 30 and every
! start element, and for n = nel_global with five start elements (1, 2,
! n/2, n-1, n, each put into 1..n, so a mesh of one or two elements has
! repeated starts), the walk of find_elem_from_old (find.f90) is repeated
! statement for statement (downward and upward counters, wrap-around,
! loop test) and the order in which it first reaches the elements is
! compared with the order of their keys: the start element must have key
! 0, every other element must be reached, and the keys must increase
! along the walk. A walk takes at most n-1 steps; it stops after n steps
! in any case and is then counted as wrong, as is a start outside 1..n.
! Counts the walks (lgr_nkey_walk) and those with an error
! (lgr_nkey_wrong). The test meshes never have a point in two elements
! (lgr_mpi_relocate_check counts them), so the order of the key is tested
! here and not by the runs.

	use shympi, only : nel_global

	implicit none

	integer :: n, nn, ieold, j, ierr
	integer :: istart(5)
	integer, allocatable :: ifirst(:), ibyrank(:)

	lgr_nkey_walk = 0
	lgr_nkey_wrong = 0
	if( .not. blgr_dbg ) return

	nn = max(30,nel_global)
	allocate(ifirst(nn), ibyrank(0:2*nn), stat=ierr)	!2 visits a step
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_selftest_key: allocation')

	do n = 1, 30
	  do ieold = 1, n
	    call one_walk(n,ieold)
	  end do
	end do

	n = nel_global
	istart = (/ 1, 2, n/2, n-1, n /)
	do j = 1, 5
	  call one_walk(n,min(n,max(1,istart(j))))	!start in 1..n
	end do

	deallocate(ifirst,ibyrank)

	contains

	  subroutine one_walk(n,ieold)

	  integer, intent(in) :: n, ieold

	  integer :: iem, iep, irank, ie, kprev, k, jj
	  logical :: bbad, bover

	  lgr_nkey_walk = lgr_nkey_walk + 1
	  if( n < 1 .or. ieold < 1 .or. ieold > n ) then	!no walk to make
	    lgr_nkey_wrong = lgr_nkey_wrong + 1
	    return
	  end if

	  ifirst(1:n) = 0
	  irank = 0
	  ifirst(ieold) = -1			!the start: tested first
	  iem = ieold-1				!the walk of find_elem_from_old
	  if( iem .lt. 1 ) iem = n
	  iep = ieold+1
	  if( iep .gt. n ) iep = 1
	  bover = .false.
	  do while( iem .ne. ieold .and. iep .ne. ieold )
	    if( irank >= 2*n ) then		!n-1 steps at most: never here
	      bover = .true.
	      exit
	    end if
	    irank = irank + 1
	    if( ifirst(iem) == 0 ) ifirst(iem) = irank
	    iem = iem - 1
	    if( iem .lt. 1 ) iem = n
	    irank = irank + 1
	    if( ifirst(iep) == 0 ) ifirst(iep) = irank
	    iep = iep + 1
	    if( iep .gt. n ) iep = 1
	  end do

	  bbad = bover .or. ( lgr_mpi_search_key(ieold,ieold,n) /= 0 )
	  ibyrank(0:irank) = 0
	  do ie = 1, n
	    if( ie == ieold ) cycle
	    if( ifirst(ie) <= 0 ) then		!never reached
	      bbad = .true.
	    else
	      ibyrank(ifirst(ie)) = ie
	    end if
	  end do
	  kprev = 0
	  do jj = 1, irank
	    ie = ibyrank(jj)
	    if( ie == 0 ) cycle			!a second visit
	    k = lgr_mpi_search_key(ie,ieold,n)
	    if( k <= kprev ) bbad = .true.
	    kprev = k
	  end do

	  if( bbad ) lgr_nkey_wrong = lgr_nkey_wrong + 1

	  end subroutine one_walk

	end subroutine lgr_mpi_selftest_key

!*******************************************************************

	function lgr_mpi_clear_of_sides(ie, xp, yp)

! true if the point (xp,yp) lies in local element ie at a distance of at
! least lgr_park_rel (2**-12) times the longest side of ie from each of
! its three sides; the distances are computed in double precision from
! the single precision coordinates (their rounding, about 1e-16 of the
! coordinates, is far below the margin). Decides only whether a process
! may accept a local hit alone (lgr_mpi_locate), never which element a
! point is in.
!
! Why the margin is safe on both sides. in_element (find.f90) is a test
! of the bounding box and then intri (regular.f90), which subtracts the
! coordinates in single precision and forms the products of a side in
! double precision. Its rounding in the distance of a point p from a side
! of an element B is at most about 2.9 u |p - v| (u = 2**-24, v the
! first vertex of the side), so at most about 4 u diam(B) for a point in
! the bounding box of B (no other point reaches intri). (In the test
! meshes the two coordinates of every subtraction are within a factor
! of two of each other, so the subtractions are exact by Sterbenz's
! lemma, the products exact in double precision, and intri decides
! exactly.) A point clear of the sides of ie by m has a disc of radius m
! around it inside ie; no other element B overlaps ie, so the point lies
! outside B by at least m, and beyond one side line of B by at least
! m sin(a/2), a the smallest angle of B. Then intri of B answers
! "outside" if m sin(a/2) > 4 u diam(B): with m = 2**-12 L, L the
! longest side of ie, if diam(B) < 2**10 sin(a/2) L, for example 89 L at
! a = 10 degrees. On the other side m is about 2.4e-4 L, far below the
! size of an element: a fraction of about 2 m / r of the points of an
! element lies within m of a side (r its inscribed radius; 1.7e-3 for an
! equilateral triangle). In a serial run at levdbg >= 3
! lgr_mpi_relocate_check counts the clear hits for which a second element
! contains the point too (must be 0).

	use basin, only : nen3v, xgv, ygv

	implicit none

	logical :: lgr_mpi_clear_of_sides
	integer, intent(in) :: ie		!local element
	real, intent(in) :: xp, yp		!point

	integer :: ii, i2
	double precision :: xv(3), yv(3), hl(3), hmax, scal

	lgr_mpi_clear_of_sides = .false.

	do ii = 1, 3
	  xv(ii) = xgv(nen3v(ii,ie))
	  yv(ii) = ygv(nen3v(ii,ie))
	end do
	hmax = 0.d0
	do ii = 1, 3
	  i2 = mod(ii,3) + 1
	  hl(ii) = sqrt( (xv(i2)-xv(ii))**2 + (yv(i2)-yv(ii))**2 )
	  hmax = max(hmax,hl(ii))
	end do

	do ii = 1, 3
	  i2 = mod(ii,3) + 1
	  ! side ii -> i2 as in intri: scal/hl(ii) is the distance of the
	  ! point from the side, positive on the inside
	  scal = (xv(i2)-xv(ii))*(dble(yp)-yv(ii))				&
     &		- (yv(i2)-yv(ii))*(dble(xp)-xv(ii))
	  if( scal < lgr_park_rel*hmax*hl(ii) ) return
	end do

	lgr_mpi_clear_of_sides = ( hmax > 0.d0 )

	end function lgr_mpi_clear_of_sides

!*******************************************************************

	subroutine lgr_mpi_locate(i,phase,ieold,xo,yo,xn,yn,ienew,bpark)

! the element search at the end of the horizontal diffusion step (phase
! 1, lag_diff_hor) or of the Stokes drift step (phase 2, lag_stk) on
! several processes, for particle i in local element ieold, with the old
! point (xo,yo) and the new point (xn,yn) of the step. The local search
! is the serial one, find_elem_from_old, over the elements this process
! holds. The process decides alone (bpark false, ienew the result) when
! the point is in ieold (class 1: tested first, as in a serial run) or in
! a held element and clear of its three sides by the margin (class 2,
! lgr_mpi_clear_of_sides: no other element of the mesh contains the point
! then, so a serial search returns that element). Otherwise, a hit
! within the margin (class 3) or no held element containing the point
! (class 4), the particle is parked (lgr_mpi_park): bpark is true and
! ienew is 0 (not to be used). At levdbg >= 3 the classes are counted.
! Called inside the parallel loop of drogue or outside any parallel
! region.
!
! the guard of the old element cannot fire (both callers return on an
! element <= 0 before); it goes through lgr_internal_error (#294: until
! then a write and shympi_abort_internal, from a worker thread inside
! the loop) with its values through lgr_event: recorded in the loop it
! returns ienew = 0 and bpark false, and the callers leave the particle
! (lgr_internal_failed); the run stops after the loop

	implicit none

	integer, intent(in) :: i		!particle (slot)
	integer, intent(in) :: phase		!1 diffusion, 2 Stokes drift
	integer, intent(in) :: ieold		!local element of the particle
	real, intent(in) :: xo, yo		!old point
	real, intent(in) :: xn, yn		!new point
	integer, intent(out) :: ienew		!element found (if not parked)
	logical, intent(out) :: bpark		!parked

	integer :: iclass

	if( ieold < 1 ) then
	  call lgr_event(lgr_ev_locate,i,(/i,phase,ieold/))
	  call lgr_internal_error('error stop lgr_mpi_locate: no old element')
	  ienew = 0			!recorded in the loop: the callers
	  bpark = .false.		!leave the particle
	  return
	end if

	call find_elem_from_old(ieold,xn,yn,ienew)

	if( ienew == ieold ) then
	  iclass = 1
	else if( ienew > 0 ) then
	  if( lgr_mpi_clear_of_sides(ienew,xn,yn) ) then
	    iclass = 2
	  else
	    iclass = 3
	  end if
	else
	  iclass = 4
	end if

	if( blgr_dbg ) then
!$OMP ATOMIC
	  lgr_nreloc(iclass) = lgr_nreloc(iclass) + 1
	end if

	bpark = ( iclass >= 3 )
	if( bpark ) then
	  ienew = 0
	  call lgr_mpi_park(i,phase,iclass,xo,yo,xn,yn)
	end if

	end subroutine lgr_mpi_locate

!*******************************************************************

	subroutine lgr_mpi_park(i,phase,iclass,xo,yo,xn,yn)

! parks particle i in the element search of phase 1 (horizontal
! diffusion step) or 2 (Stokes drift step): both points of the move go
! into its slot as they are (lgr_park_xy), the mark becomes 1 + phase
! (lgr_marked: own slot), and the slot with the class (3 hit within the
! margin, 4 failed local search) goes into the list of parked particles
! (critical section lgr_export; grown when full). The caller stores the
! particle's element, xi, depth, layer and type in lgr_ar(i) and skips
! the rest of track_finish; lgr_mpi_handover resolves it by position
! (lgr_mpi_resolve) and resumes it. Several processes only.
! A failed argument test or a failed growth is recorded
! (lgr_mpi_list_fail) instead of aborting here, which can be a worker
! thread: nothing is appended, the caller (lgr_mpi_locate, bpark true)
! stops the particle's step, and the main thread aborts in
! lgr_mpi_list_check (#242)

	use shympi, only : my_id

	implicit none

	integer, intent(in) :: i		!particle (slot)
	integer, intent(in) :: phase		!1 diffusion, 2 Stokes drift
	integer, intent(in) :: iclass		!3 or 4
	real, intent(in) :: xo, yo		!old point
	real, intent(in) :: xn, yn		!new point

	logical :: bok

	if( .not. bmpi_lagr .or. phase < 1 .or. phase > 2			&
     &		.or. iclass < 3 .or. iclass > 4 ) then
!$OMP CRITICAL (lgr_export)
	  call lgr_mpi_list_fail(4,i,phase,iclass,0,0)
!$OMP END CRITICAL (lgr_export)
	  return
	end if

	lgr_park_xy(1,i) = xo
	lgr_park_xy(2,i) = yo
	lgr_park_xy(3,i) = xn
	lgr_park_xy(4,i) = yn
	lgr_park_ie(i) = 0
	lgr_marked(i) = 1 + phase

!$OMP CRITICAL (lgr_export)
	bok = .true.
	if( n_park + 1 > size(park_idx) ) call lgr_mpi_grow_park(i,bok)
	if( bok ) then
	  n_park = n_park + 1
	  park_idx(n_park) = i
	  park_class(n_park) = iclass
	end if
!$OMP END CRITICAL (lgr_export)

	end subroutine lgr_mpi_park

!*******************************************************************

	subroutine lgr_mpi_grow_park(i,bok)

! doubles the size of the list of parked particles (new lists, copy of
! the n_park entries in use, move_alloc); called inside the critical
! section lgr_export of lgr_mpi_park, possibly by a worker thread. If the
! allocation fails (or the test hook LGR_TEST_GROW_FAIL=park takes this
! path once) the lists stay as they are, the failure is recorded
! (lgr_mpi_list_fail; lgr_mpi_list_check aborts on the main thread with
! the message 'lgr_mpi_grow_park: allocation') and bok is false: the
! caller appends nothing

	use shympi, only : my_id

	implicit none

	integer, intent(in) :: i		!slot of the particle to append
	logical, intent(out) :: bok		!the lists have grown

	integer :: ierr, nnew, ith
	integer, allocatable :: iidx(:), icls(:)

	nnew = 2*max(size(park_idx), 1)

	if( lgr_test_grow_park ) then	!test hook: a failed allocate, once
	  lgr_test_grow_park = .false.
	  ierr = -1
	else
	  allocate(iidx(nnew), icls(nnew), stat=ierr)
	end if
	if( ierr /= 0 ) then
	  call lgr_mpi_list_fail(2,i,nnew,ierr,size(park_idx),0)
	  bok = .false.
	  return
	end if

	iidx(1:n_park) = park_idx(1:n_park)
	icls(1:n_park) = park_class(1:n_park)
	call move_alloc(iidx,park_idx)
	call move_alloc(icls,park_class)

	if( blgr_dbg ) then
	  call openmp_get_thread_num(ith)
	  write(6,*) 'lgr_mpi_grow_park: rank ',my_id,' new size ',nnew	&
     &		,' OpenMP thread ',ith
	end if
	bok = .true.

	end subroutine lgr_mpi_grow_park

!*******************************************************************

	subroutine lgr_mpi_relocate_check(ieold,xn,yn,ienew)

! self-check of the element search of the diffusion and Stokes steps in
! a serial run at levdbg >= 3 (called by lag_diff_hor and lag_stk after
! find_elem_from_old; changes nothing). It counts the class of the
! re-location as lgr_mpi_locate would classify it (1 in the old element,
! 2 a hit clear of the margin, 3 a hit within it, 4 no element). For
! every re-location that leaves the old element (classes 2, 3, 4) it
! finds by brute force over all elements the element with the smallest
! search key (lgr_mpi_search_key) that contains the point, 0 if none, and
! compares it with ienew, the element find_elem_from_old returned: a
! difference is a defect of the key or of the search. For class 2 it
! counts whether a second element contains the point too (the premise of
! the margin, lgr_mpi_clear_of_sides), and for all of them whether two or
! more elements contain the point (only there can a wrong key show: with
! one element the brute force agrees with any order). In a serial run the local element
! numbers are the global ones. Inside the parallel loop of drogue: the
! counts are atomic.

	use basin, only : nel

	implicit none

	integer, intent(in) :: ieold		!element before the step
	real, intent(in) :: xn, yn		!new point
	integer, intent(in) :: ienew		!result of find_elem_from_old

	integer :: iclass, ie, k, kbest, iebest, nin
	logical :: in_element

	if( ienew == ieold ) then
	  iclass = 1
	else if( ienew > 0 ) then
	  if( lgr_mpi_clear_of_sides(ienew,xn,yn) ) then
	    iclass = 2
	  else
	    iclass = 3
	  end if
	else
	  iclass = 4
	end if

!$OMP ATOMIC
	lgr_nreloc(iclass) = lgr_nreloc(iclass) + 1

	if( iclass == 1 ) return

	kbest = huge(kbest)
	iebest = 0
	nin = 0
	do ie = 1, nel
	  if( in_element(ie,xn,yn) ) then
	    nin = nin + 1
	    k = lgr_mpi_search_key(ie,ieold,nel)
	    if( k < kbest ) then
	      kbest = k
	      iebest = ie
	    end if
	  end if
	end do

!$OMP ATOMIC
	lgr_nchk_comp = lgr_nchk_comp + 1
	if( iebest /= ienew ) then
!$OMP ATOMIC
	  lgr_nchk_diff = lgr_nchk_diff + 1
	end if
	if( iclass == 2 .and. nin > 1 ) then
!$OMP ATOMIC
	  lgr_nchk_clear2 = lgr_nchk_clear2 + 1
	end if
	if( nin > 1 ) then
!$OMP ATOMIC
	  lgr_nchk_multi = lgr_nchk_multi + 1
	end if

	end subroutine lgr_mpi_relocate_check

!*******************************************************************

	subroutine lgr_mpi_pack_particle(p, buf)

! serialize the whole particle record into a double precision buffer
! (layout: see the top of the module); the 64 bit bitmaps travel as two
! 32 bit halves each, which a double holds exactly; the number of custom
! values is ncust, the same for every particle of a run

	implicit none

	type(lagr_entry), intent(in) :: p
	double precision, intent(out) :: buf(lgr_pack_base+ncust)

	integer :: j

	if( allocated(p%custom) ) then
	  if( size(p%custom) /= ncust ) then
	    write(6,*) 'lgr_mpi_pack_particle: custom count,ncust: ',	&
     &		size(p%custom),ncust
	    call shympi_abort_internal					&
     &		('lgr_mpi_pack_particle: custom count')
	  end if
	end if

	buf(1:3) = p%actual%xi
	buf(4)  = p%actual%time
	buf(5)  = dble(p%actual%z)
	buf(6)  = dble(p%actual%l)
	buf(7)  = dble(p%actual%ie_global)
	buf(8:10) = p%init%xi
	buf(11) = p%init%time
	buf(12) = dble(p%init%z)
	buf(13) = dble(p%init%l)
	buf(14) = dble(p%init%ie_global)
	buf(15) = dble(p%id)
	buf(16) = dble(p%type)
	buf(17) = p%sinking
	buf(18) = dble(iand(p%bitmap_in,4294967295_8))
	buf(19) = dble(ishft(p%bitmap_in,-32))
	buf(20) = dble(iand(p%bitmap_out,4294967295_8))
	buf(21) = dble(ishft(p%bitmap_out,-32))
	buf(22) = dble(ncust)

	do j = 1, ncust
	  if( allocated(p%custom) ) then
	    buf(lgr_pack_base + j) = dble(p%custom(j))
	  else
	    buf(lgr_pack_base + j) = 0.d0
	  end if
	end do

	end subroutine lgr_mpi_pack_particle

!*******************************************************************

	subroutine lgr_mpi_unpack_particle(buf, p)

! deserialize a particle record from a double precision buffer
!
! the local element numbers do not travel: actual%ie is set to 0 (the
! caller resolves it); init%ie is looked up from init%ie_global
! (lgr_mpi_find_elem, bisection) and is 0 if this process does not hold
! that element (init%ie is only valid on a process that holds the
! element, the global number is always kept); aborts if the number of
! custom values in the record differs from ncust

	implicit none

	double precision, intent(in) :: buf(lgr_pack_base+ncust)
	type(lagr_entry), intent(out) :: p

	integer :: j, nc, ierr
	integer(kind(p%bitmap_in)) :: lo, hi

	nc = nint(buf(22))
	if( nc /= ncust ) then
	  write(6,*) 'lgr_mpi_unpack_particle: custom count in record,'	&
     &		//' ncust: ',nc,ncust
	  call shympi_abort_internal					&
     &		('lgr_mpi_unpack_particle: custom count')
	end if

	p%actual%xi    = buf(1:3)
	p%actual%time  = buf(4)
	p%actual%z     = real(buf(5))
	p%actual%l     = nint(buf(6))
	p%actual%ie_global = nint(buf(7))
	p%actual%ie    = 0		!resolved by caller

	p%init%xi      = buf(8:10)
	p%init%time    = buf(11)
	p%init%z       = real(buf(12))
	p%init%l       = nint(buf(13))
	p%init%ie_global = nint(buf(14))
	p%init%ie      = lgr_mpi_find_elem(p%init%ie_global)

	p%id           = nint(buf(15))
	p%type         = nint(buf(16))
	p%sinking      = buf(17)

	lo = nint(buf(18),kind(lo))
	hi = nint(buf(19),kind(hi))
	p%bitmap_in    = ior(ishft(hi,32),lo)
	lo = nint(buf(20),kind(lo))
	hi = nint(buf(21),kind(hi))
	p%bitmap_out   = ior(ishft(hi,32),lo)

	allocate(p%custom(nc), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_unpack: allocation')
	do j = 1, nc
	  p%custom(j) = real(buf(lgr_pack_base + j))
	end do

	end subroutine lgr_mpi_unpack_particle

!*******************************************************************

	subroutine lgr_mpi_remove_particle(i)

! removes particle i from the particle array: the last entry (nbdy) is
! moved into slot i with all its fields (also lgr_ncross, lgr_marked,
! lgr_park_xy and lgr_park_ie), nbdy is reduced by one; the custom values
! of the vacated last slot are freed (insert allocates them again). To
! remove several particles use lgr_mpi_remove_list.

	implicit none

	integer, intent(in) :: i

	if( i < 1 .or. i > nbdy ) then
	  write(6,*) 'lgr_mpi_remove_particle: i,nbdy: ',i,nbdy
	  call shympi_abort_internal('lgr_mpi_remove_particle: index')
	end if

	if( i /= nbdy ) then
	  lgr_ar(i) = lgr_ar(nbdy)
	  lgr_ncross(i) = lgr_ncross(nbdy)
	  lgr_marked(i) = lgr_marked(nbdy)
	  lgr_park_xy(:,i) = lgr_park_xy(:,nbdy)
	  lgr_park_ie(i) = lgr_park_ie(nbdy)
	end if

	if( allocated(lgr_ar(nbdy)%custom) ) deallocate(lgr_ar(nbdy)%custom)
	lgr_ncross(nbdy) = 0
	lgr_marked(nbdy) = 0
	lgr_park_xy(:,nbdy) = 0.
	lgr_park_ie(nbdy) = 0
	nbdy = nbdy - 1

	end subroutine lgr_mpi_remove_particle

!*******************************************************************

	subroutine lgr_mpi_remove_list(n, idx)

! removes the n particles in the slots idx(1:n) (any order, each slot at
! most once) from the particle array, highest slot first: when slot i is
! removed, every listed slot above i is already gone, so the entry that
! lgr_mpi_remove_particle moves from the end into slot i is never one of
! the list, and the slots still to remove stay valid

	implicit none

	integer, intent(in) :: n
	integer, intent(in) :: idx(n)

	integer :: j, ierr
	integer, allocatable :: key(:), isort(:)

	if( n <= 0 ) return

	allocate(key(n), isort(n), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_remove_list: allocation')

	key = idx
	isort = idx
	call lgr_mpi_sort_by_key(n,key,isort)
	do j = 2, n
	  if( isort(j) == isort(j-1) ) then
	    write(6,*) 'lgr_mpi_remove_list: slot listed twice: ',isort(j)
	    call shympi_abort_internal('lgr_mpi_remove_list: slot twice')
	  end if
	end do

	do j = n, 1, -1
	  call lgr_mpi_remove_particle(isort(j))
	end do

	deallocate(key,isort)

	end subroutine lgr_mpi_remove_list

!*******************************************************************

	function lgr_mpi_diff_field(a, b)

! first field of the wire record in which a and b differ (0 = none);
! the numbers are those of lgr_mpi_field_name

	implicit none

	integer :: lgr_mpi_diff_field
	type(lagr_entry), intent(in) :: a, b

	integer :: j

	lgr_mpi_diff_field = 0

	if( any(a%actual%xi /= b%actual%xi) ) then
	  lgr_mpi_diff_field = 1
	else if( a%actual%time /= b%actual%time ) then
	  lgr_mpi_diff_field = 2
	else if( a%actual%z /= b%actual%z ) then
	  lgr_mpi_diff_field = 3
	else if( a%actual%l /= b%actual%l ) then
	  lgr_mpi_diff_field = 4
	else if( a%actual%ie_global /= b%actual%ie_global ) then
	  lgr_mpi_diff_field = 5
	else if( any(a%init%xi /= b%init%xi) ) then
	  lgr_mpi_diff_field = 6
	else if( a%init%time /= b%init%time ) then
	  lgr_mpi_diff_field = 7
	else if( a%init%z /= b%init%z ) then
	  lgr_mpi_diff_field = 8
	else if( a%init%l /= b%init%l ) then
	  lgr_mpi_diff_field = 9
	else if( a%init%ie_global /= b%init%ie_global ) then
	  lgr_mpi_diff_field = 10
	else if( a%id /= b%id ) then
	  lgr_mpi_diff_field = 11
	else if( a%type /= b%type ) then
	  lgr_mpi_diff_field = 12
	else if( a%sinking /= b%sinking ) then
	  lgr_mpi_diff_field = 13
	else if( a%bitmap_in /= b%bitmap_in ) then
	  lgr_mpi_diff_field = 14
	else if( a%bitmap_out /= b%bitmap_out ) then
	  lgr_mpi_diff_field = 15
	else if( allocated(a%custom) .neqv. allocated(b%custom) ) then
	  lgr_mpi_diff_field = 16
	else if( allocated(a%custom) ) then
	  if( size(a%custom) /= size(b%custom) ) then
	    lgr_mpi_diff_field = 16
	  else
	    do j = 1, size(a%custom)
	      if( a%custom(j) /= b%custom(j) ) lgr_mpi_diff_field = 16
	    end do
	  end if
	end if

	end function lgr_mpi_diff_field

!*******************************************************************

	subroutine lgr_mpi_selftest_pack

! self-test of the particle record and of lgr_mpi_remove_particle, run once
! at levdbg >= 3 (called by lgr_mpi_init), on every process
!
! a particle with distinct values in every field (a bitmap above 2**32,
! init%time, init%ie_global, three custom values) is packed and unpacked
! and every field is compared; then three particles are put behind the
! nbdy particles present, the first is removed, and the former last one
! must sit in its slot with all fields and its lgr_ncross, lgr_park_ie and
! lgr_park_xy values, nbdy one less. Then six particles are put behind the
! nbdy present, three of them are marked (lgr_marked), the last one of the
! array among them, and removed in one go with lgr_mpi_remove_list (list
! not sorted): exactly the three unmarked ones must remain, each once,
! with all its fields, its lgr_ncross, lgr_park_ie and lgr_park_xy values
! and no mark. Particle array, the per-slot values, nbdy and ncust are
! restored. Rank 0 prints one line when all processes agree; otherwise
! every process aborts naming the first field that differs. Prints and
! changes nothing at levdbg < 3.

	use shympi
	use para, only : getpar

	implicit none

	include 'mpif.h'

	integer, parameter :: nfield = 24
	character(len=24), parameter :: fname(nfield) = (/		&
     &		'actual%xi               ',				&
     &		'actual%time             ',				&
     &		'actual%z                ',				&
     &		'actual%l                ',				&
     &		'actual%ie_global        ',				&
     &		'init%xi                 ',				&
     &		'init%time               ',				&
     &		'init%z                  ',				&
     &		'init%l                  ',				&
     &		'init%ie_global          ',				&
     &		'id                      ',				&
     &		'type                    ',				&
     &		'sinking                 ',				&
     &		'bitmap_in               ',				&
     &		'bitmap_out              ',				&
     &		'custom                  ',				&
     &		'actual%ie (must be 0)   ',				&
     &		'init%ie                 ',				&
     &		'remove: particle moved  ',				&
     &		'remove: ncross, park    ',				&
     &		'remove: nbdy            ',				&
     &		'remove list: particles  ',				&
     &		'remove list: ncross etc.',				&
     &		'remove list: nbdy       ' /)

	integer, parameter :: nlist = 6		!particles of the list test
	integer :: ierr, ifield, ifmax, ncust_save, npack_save
	integer :: n0, j, jj, k
	double precision, allocatable :: buf(:)
	type(lagr_entry) :: p, q
	type(lagr_entry) :: psave(nlist), pnew(nlist)
	integer :: isave(nlist), msave(nlist), nfound(nlist)
	integer :: ksave(nlist)
	real :: xysave(4,nlist)
	integer :: imark(3)
	logical :: bmarked

	if( nint(getpar('levdbg')) < 3 ) return

	ifield = 0
	n0 = nbdy
	ncust_save = ncust
	npack_save = lgr_pack_size
	ncust = 3
	lgr_pack_size = lgr_pack_base + ncust

	allocate(buf(lgr_pack_size), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_selftest_pack: allocation')

	!-----------------------------------------------
	! pack and unpack
	!-----------------------------------------------

	call lgr_mpi_selftest_fill(p,1)
	call lgr_mpi_pack_particle(p,buf)
	call lgr_mpi_unpack_particle(buf,q)

	ifield = lgr_mpi_diff_field(p,q)
	if( ifield == 0 .and. q%actual%ie /= 0 ) ifield = 17
	if( ifield == 0 .and.						&
     &		q%init%ie /= lgr_mpi_find_elem(p%init%ie_global) ) then
	  ifield = 18
	end if

	!-----------------------------------------------
	! removal of a particle (behind the n0 present ones)
	!-----------------------------------------------

	if( ifield == 0 ) then
	  if( n0 + 3 > size(lgr_ar) ) call mod_lagrange_handle_alloc(n0+3)
	  do j = 1, 3
	    psave(j) = lgr_ar(n0+j)
	    isave(j) = lgr_ncross(n0+j)
	    ksave(j) = lgr_park_ie(n0+j)
	    xysave(:,j) = lgr_park_xy(:,n0+j)
	    call lgr_mpi_selftest_fill(pnew(j),j)
	    lgr_ar(n0+j) = pnew(j)
	    lgr_ncross(n0+j) = 10*j
	    lgr_park_ie(n0+j) = 100*j
	    lgr_park_xy(:,n0+j) = (/ 1.5*j, 2.5*j, 3.5*j, 4.5*j /)
	  end do
	  nbdy = n0 + 3
	  call lgr_mpi_remove_particle(n0+1)
	  if( nbdy /= n0 + 2 ) then
	    ifield = 21
	  else if( lgr_mpi_diff_field(lgr_ar(n0+1),pnew(3)) /= 0 ) then
	    ifield = 19
	  else if( lgr_ar(n0+1)%actual%ie /= pnew(3)%actual%ie		&
     &		.or. lgr_ar(n0+1)%init%ie /= pnew(3)%init%ie ) then
	    ifield = 19
	  else if( lgr_ncross(n0+1) /= 30 .or. lgr_park_ie(n0+1) /= 300 ) then
	    ifield = 20
	  else if( any( lgr_park_xy(:,n0+1) /= (/ 4.5, 7.5, 10.5, 13.5 /) ) ) then
	    ifield = 20
	  end if
	  nbdy = n0
	  do j = 1, 3
	    lgr_ar(n0+j) = psave(j)
	    lgr_ncross(n0+j) = isave(j)
	    lgr_park_ie(n0+j) = ksave(j)
	    lgr_park_xy(:,n0+j) = xysave(:,j)
	  end do
	end if

	!-----------------------------------------------
	! removal of several marked particles in one go: six particles
	! behind the n0 present ones, the slots n0+3, n0+6 (the last one)
	! and n0+1 marked and listed in that order; 2, 4, 5 must remain
	!-----------------------------------------------

	if( ifield == 0 ) then
	  if( n0 + nlist > size(lgr_ar) ) then
	    call mod_lagrange_handle_alloc(n0+nlist)
	  end if
	  do j = 1, nlist
	    psave(j) = lgr_ar(n0+j)
	    isave(j) = lgr_ncross(n0+j)
	    msave(j) = lgr_marked(n0+j)
	    ksave(j) = lgr_park_ie(n0+j)
	    xysave(:,j) = lgr_park_xy(:,n0+j)
	    call lgr_mpi_selftest_fill(pnew(j),j)
	    lgr_ar(n0+j) = pnew(j)
	    lgr_ncross(n0+j) = 10*j
	    lgr_marked(n0+j) = 0
	    lgr_park_ie(n0+j) = 100*j
	    lgr_park_xy(:,n0+j) = (/ 1.5*j, 2.5*j, 3.5*j, 4.5*j /)
	  end do
	  imark = (/ n0+3, n0+nlist, n0+1 /)
	  do j = 1, 3
	    lgr_marked(imark(j)) = 1
	  end do
	  nbdy = n0 + nlist
	  call lgr_mpi_remove_list(3,imark)
	  if( nbdy /= n0 + nlist - 3 ) then
	    ifield = 24
	  else
	    nfound = 0
	    do jj = n0+1, nbdy
	      k = lgr_ar(jj)%id - 987654	!test particle k (selftest_fill)
	      bmarked = .true.
	      if( k >= 1 .and. k <= nlist ) bmarked = any( imark == n0+k )
	      if( bmarked ) then		!marked, or not a test particle
	        ifield = 22
	      else if( nfound(k) > 0 ) then	!twice
	        ifield = 22
	      else if( lgr_mpi_diff_field(lgr_ar(jj),pnew(k)) /= 0 ) then
	        ifield = 22
	      else if( lgr_ar(jj)%actual%ie /= pnew(k)%actual%ie		&
     &		.or. lgr_ar(jj)%init%ie /= pnew(k)%init%ie ) then
	        ifield = 22
	      else if( lgr_ncross(jj) /= 10*k .or. lgr_marked(jj) /= 0 ) then
	        ifield = 23
	      else if( lgr_park_ie(jj) /= 100*k ) then
	        ifield = 23
	      else if( any( lgr_park_xy(:,jj) /=				&
     &		(/ 1.5*k, 2.5*k, 3.5*k, 4.5*k /) ) ) then
	        ifield = 23
	      end if
	      if( ifield /= 0 ) exit
	      nfound(k) = 1
	    end do
	  end if
	  nbdy = n0
	  do j = 1, nlist
	    lgr_ar(n0+j) = psave(j)
	    lgr_ncross(n0+j) = isave(j)
	    lgr_marked(n0+j) = msave(j)
	    lgr_park_ie(n0+j) = ksave(j)
	    lgr_park_xy(:,n0+j) = xysave(:,j)
	  end do
	end if

	ncust = ncust_save
	lgr_pack_size = npack_save
	deallocate(buf)

	!-----------------------------------------------
	! all processes agree
	!-----------------------------------------------

	call MPI_Allreduce(ifield,ifmax,1,MPI_INTEGER,MPI_MAX,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_selftest_pack: MPI_Allreduce')

	if( ifmax > 0 ) then
	  if( ifield > 0 ) then
	    write(6,*) 'lgr pack self-test: rank ',my_id,		&
     &		' differs in ',trim(fname(ifield))
	  end if
	  call shympi_abort_internal('lgr pack self-test failed in '	&
     &		//trim(fname(ifmax)))
	end if

	if( my_id == 0 ) write(6,*) 'lgr pack self-test: ok'

	end subroutine lgr_mpi_selftest_pack

!*******************************************************************

	subroutine lgr_mpi_selftest_fill(p, k)

! test particle number k (k >= 1, id 987654 + k) with values in every
! field that differ from those of every other k, three custom values
! (the caller has set ncust = 3)

	implicit none

	type(lagr_entry), intent(out) :: p
	integer, intent(in) :: k

	integer :: ierr

	p%actual%xi = (/ 0.125d0*k, 0.3d0, 1.d0 - 0.125d0*k - 0.3d0 /)
	p%actual%time = 456.25d0 + k
	p%actual%z = 0.37 + 0.01*k
	p%actual%ie = 5 + k
	p%actual%ie_global = 1234 + k
	p%actual%l = 3 + k
	p%init%xi = (/ 0.2d0, 0.25d0*k, 0.75d0 - 0.25d0*k /)
	p%init%time = 123.d0 + k - 1
	p%init%z = 0.11 + 0.01*k
	p%init%ie = 2 + k
	p%init%ie_global = 77 + k - 1
	p%init%l = 2 + k
	p%id = 987654 + k
	p%type = 3 + k
	p%sinking = -1.5d-3*k
	p%bitmap_in = 2_8**40 + 5 + k - 1
	p%bitmap_out = ior(ishft(1_8,63),int(9*k,8))	!sign bit set
	allocate(p%custom(3), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_selftest_fill: allocation')
	p%custom = (/ 0.5*k, -2.25, 1.0e6 + k /)

	end subroutine lgr_mpi_selftest_fill

!*******************************************************************

	function lgr_side_delta(c)

! rounding distance of the side fallback particle_on_side
! (lagrange_util.f90) and of its self-test lgr_mpi_selftest_side: two
! spacings of the single precision value c, the largest absolute
! coordinate involved (the one expression both use)

	implicit none

	double precision :: lgr_side_delta
	real, intent(in) :: c

	lgr_side_delta = 2.d0 * spacing(c)

	end function lgr_side_delta

!*******************************************************************

	subroutine lgr_mpi_selftest_side

! self-test of particle_on_side (lagrange_util.f90), the fallback of the
! diffusion and Stokes drift steps when no element contains the new
! position, run once at levdbg >= 3 (called by lgr_mpi_init), on every
! process. It never stops the run.
!
! Test elements, chosen on each process among the elements it holds whose
! shortest altitude is at least 10 delta (delta = lgr_side_delta of the
! largest absolute corner coordinate plus the longest side; no test point
! lies farther from a corner than the longest side): for each kind of side
! of the side table lgr_ieltv (neighbour, wall, open boundary, cut-off
! side), the element with the largest smallest interior angle that has a
! side of that kind (at equal angles the lowest global element number).
! A kind the process holds no such element of is not tested there.
!
! Side ii is the side opposite vertex ii. At a neighbour, a wall or a
! cut-off side (lgr_ieltv <= -1000, treated like a side with a neighbour)
! ie must come back unchanged, at an open boundary (-999 <= lgr_ieltv
! <= -1) as -ie when the particle leaves. The checks, for each test
! element (the side kind a check is counted under in brackets):
!  1. from the centre through the middle of side ii and beyond (kind of
!     side ii): the point where the move leaves, kind of side ii
!  2. from the centre half way to vertex 1 (none): the new point, exactly
!  3. zero length, from a point just outside the element beside vertex 2
!     at its y (none): the arguments as they came, exactly
!  4. from the middle of side ii towards the middle of side jj and beyond,
!     all six pairs (kind of side jj): where the move leaves through jj
!  5. from the middle of side ii straight out (kind of side ii): the start
!     point, exactly; kind of side ii
!  6. from the centre through vertex k (none): the point at the vertex;
!     ie flipped only if both sides at vertex k are open boundaries
!  7. from the middle of side ii along it past its end node nen3v(i2,ie)
!     (kind of side i1, the other side at that vertex): where the move
!     reaches side i1, kind of side i1
!  8. along side ii from about 0.4 delta inside its line to about 0.85
!     delta beyond it, outward (kind of side ii): the end projected on
!     side ii, kind of side ii (an open boundary lets the particle leave)
!  9. along side ii from about 0.85 delta to about 0.6 delta beyond its
!     line, inward (kind of side ii): the end projected on side ii, ie
!     unchanged
! 10. open sides: a move of at most delta/2 from about 0.75 delta beyond
!     the line to more than delta beyond it (open): the start point,
!     exactly; the particle leaves
!
! Before a move is made, its geometry is verified in double precision
! from the single precision points actually passed (after placement and
! rounding), in units of the routine's own delta for that move
! (lgr_side_delta of its largest absolute coordinate), by clipping the
! exact segment against the triangle. A move whose geometry does not
! match what its expected result assumes is not made and is counted as
! skipped for its side kind. Margins are 2 delta where the comparison
! allows it; comparisons inside the band (|distance| <= delta) use the
! margins listed below. What each check verifies:
!  1: the start at least 2 delta inside every side; the exact segment
!     leaves through side ii, at least 2 delta from both its vertices, at
!     least 2 delta after the start and before the end, and at least
!     2 delta before it would cross any other side
!  2: both points at least 2 delta inside every side
!  3: the point outside the element (the result does not depend on it)
!  4: the start within 0.5 delta of side ii and at least 2 delta inside
!     the other sides; the end at least 2 delta further inside side ii
!     than the start; the exact segment leaves through side jj as in 1
!  5: the start within 0.5 delta of side ii, at least 3 delta inside the
!     other sides and at least 2 delta from both vertices of side ii; the
!     end at least 3 delta beyond side ii; any other side the move goes
!     out of crossed at least 3 delta after the start
!  6: the start at least 2 delta inside every side; the exact segment
!     crosses the two sides at vertex k within 0.5 delta of each other
!     (the routine treats crossings within delta as a vertex), at least
!     2 delta after the start, before the end and before side k
!  7: both points within 0.5 delta of side ii (the move runs along it);
!     the start at least 2 delta inside the other sides; with side ii set
!     aside the exact segment leaves through side i1, at least 2 delta
!     after the start, before the end and before side i2
!  8: the start within 0.9 delta of side ii, the end 0.6 to 0.97 delta
!     beyond it and at least 0.1 delta farther out than the start; both
!     points at least 2 delta inside the other sides and projected on
!     side ii at least 2 delta from both its vertices
!  9: the start at most 0.97 delta beyond side ii, the end at least
!     0.5 delta beyond it and at least 0.1 delta nearer than the start;
!     otherwise as 8
! 10: the start 0.05 to 0.95 delta beyond the open side, the end more
!     than 1.05 delta beyond it, the move no longer than delta/2; both
!     points at least 2 delta inside the other sides and projected on the
!     side at least 2 delta from both its vertices
! A point expected "where the move leaves" is the exact crossing of the
! segment, compared within 0.5 delta in each coordinate (rounding of the
! returned point to single precision). "Projected on side ii" (8, 9) is
! met by a point within 0.45 delta of the line and within 0.6 delta of
! the exact projection in each coordinate; the end itself lies at least
! 0.5 delta beyond the line.
!
! A failed check prints, on the process that found it, one line naming
! the check, the element (global number), the side and its kind, the two
! points of the move and the point and the signed global element
! returned against those expected. All processes then sum their counts
! and rank 0 prints one line, "lgr side fallback self-test: ok" or
! "lgr side fallback self-test: FAILED (n)", followed by the checks run
! and skipped per side kind over all processes. particle_on_side changes
! only its arguments: the test leaves no trace. Nothing is printed or
! changed at levdbg < 3.

	use shympi
	use basin, only : nel, nen3v, xgv, ygv
	use para, only : getpar

	implicit none

	include 'mpif.h'

	integer, parameter :: ncheck = 10
	character(len=30), parameter :: cname(ncheck) = [		&
     &		character(len=30) ::					&
     &		'through the middle of a side',				&
     &		'inside the element',					&
     &		'zero length',						&
     &		'across from a side',					&
     &		'straight out of its start side',			&
     &		'through a vertex',					&
     &		'along a side past its end',				&
     &		'along a side, out past it',				&
     &		'along a side, inward, ends out',			&
     &		'short move out of an open side' ]
	character(len=9), parameter :: kname(0:4) = [			&
     &		character(len=9) ::					&
     &		'none', 'neighbour', 'wall', 'open', 'cut-off' ]

	integer :: ietest(4)			!per kind 1..4, see side_kc
	double precision :: abest(4)
	integer :: nrun(0:4), nskip(0:4), nfail
	integer :: ibuf(11), isum(11)
	integer :: ierr, j, ie, ii, jj, i1, i2, k, kk, isg, mx, my, kc
	logical :: bopen(3), bok, bokb
	real :: xc(3), yc(3), xs(3), ys(3)
	real :: xm, ym, xp, yp, xq, eps
	real :: xa, ya, xb, yb, xbt, ybt
	double precision :: area, hl(3), amin, ximin, xibest, xil, dbest
	character(len=24) :: cnum(10)
	! results of clip, for the move it was last called with
	integer :: iex				!side the segment leaves through
	double precision :: dm			!the routine's delta of the move
	double precision :: da(3), db(3)	!beyond each side, in delta
	double precision :: dlen		!length of the move, in delta
	double precision :: sin1, sx, sgap	!entry, exit, gap to the next
	double precision :: xx, yx		!exit point
	double precision :: dv1, dv2		!exit from the vertices, in delta
	double precision :: sk(3)		!crossing of each side, or huge

	if( nint(getpar('levdbg')) < 3 ) return


	!-----------------------------------------------
	! test elements: per side kind the one with the largest smallest
	! angle among the elements that are not very thin
	!-----------------------------------------------

	ietest = 0
	abest = -1.d0
	do ie = 1, nel
	  if( .not. wide_element(ie,amin) ) cycle
	  do ii = 1, 3
	    kc = side_kc(lgr_ieltv(ii,ie))
	    if( amin > abest(kc) ) then
	      abest(kc) = amin
	      ietest(kc) = ie
	    else if( amin == abest(kc) ) then
	      if( ip_int_elem(ie) < ip_int_elem(ietest(kc)) ) ietest(kc) = ie
	    end if
	  end do
	end do

	!-----------------------------------------------
	! the moves of each test element
	!-----------------------------------------------

	nrun = 0
	nskip = 0
	nfail = 0

	do kk = 1, 4
	  ie = ietest(kk)
	  if( ie == 0 ) cycle
	  if( any( ietest(1:kk-1) == ie ) ) cycle	!tested already
	  call test_element
	end do

	!-----------------------------------------------
	! all processes sum their counts; rank 0 prints one line
	!-----------------------------------------------

	ibuf(1) = nfail
	ibuf(2:6) = nrun(0:4)
	ibuf(7:11) = nskip(0:4)
	call MPI_Allreduce(ibuf,isum,11,MPI_INTEGER,MPI_SUM,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_selftest_side: MPI_Allreduce')

	if( my_id == 0 ) then
	  do k = 0, 4
	    write(cnum(k+1),'(i0,a,i0)') isum(2+k),'/',isum(7+k)
	  end do
	  if( isum(1) == 0 ) then
	    write(6,'(a,10(a,a,a,a))') 'lgr side fallback self-test: ok'	&
     &		,' run/skipped:'					&
     &		,(' ',trim(kname(k)),' ',trim(cnum(k+1))//sep(k),k=0,4)
	  else
	    write(cnum(6),'(i0)') isum(1)
	    write(6,'(a,10(a,a,a,a))') 'lgr side fallback self-test: FAILED ('&
     &		//trim(cnum(6))//')',' run/skipped:'			&
     &		,(' ',trim(kname(k)),' ',trim(cnum(k+1))//sep(k),k=0,4)
	  end if
	end if

	contains

!-----------------------------------------------------------------------

	function sep(kk)

! separator after the counts of kind kk

	character(len=1) :: sep
	integer, intent(in) :: kk

	sep = ','
	if( kk == 4 ) sep = ' '

	end function sep

!-----------------------------------------------------------------------

	subroutine test_element

! all checks for element ie

	integer :: ia, ib, ic

	do ii = 1, 3
	  xc(ii) = xgv(nen3v(ii,ie))
	  yc(ii) = ygv(nen3v(ii,ie))
	end do
	area = (dble(xc(2))-xc(1))*(dble(yc(3))-yc(1))			&
     &		- (dble(xc(3))-xc(1))*(dble(yc(2))-yc(1))
	xm = (xc(1) + xc(2) + xc(3)) / 3.	!centre of the element
	ym = (yc(1) + yc(2) + yc(3)) / 3.
	do ii = 1, 3
	  i1 = mod(ii,3) + 1			!end nodes of side ii
	  i2 = mod(i1,3) + 1
	  xs(ii) = 0.5 * (xc(i1) + xc(i2))	!middle of side ii
	  ys(ii) = 0.5 * (yc(i1) + yc(i2))
	  hl(ii) = sqrt( (dble(xc(i2))-xc(i1))**2 + (dble(yc(i2))-yc(i1))**2 )
	  bopen(ii) = ( side_kc(lgr_ieltv(ii,ie)) == 3 )
	end do

	! 1. from the centre through the middle of each side
	do ii = 1, 3
	  kc = side_kc(lgr_ieltv(ii,ie))
	  xb = 2.*xs(ii) - xm
	  yb = 2.*ys(ii) - ym
	  call clip(xm,ym,xb,yb,0)
	  if( maxval(da) <= -2.d0 .and. leaves_clean(ii) ) then
	    call one_move(1,kc,ii,xm,ym,xb,yb,real(xx),real(yx)		&
     &			,kind_ie(bopen(ii)),2)
	  else
	    nskip(kc) = nskip(kc) + 1
	  end if
	end do

	! 2. from the centre half way to vertex 1: stays inside
	xp = 0.5 * (xm + xc(1))
	yp = 0.5 * (ym + yc(1))
	call clip(xm,ym,xp,yp,0)
	if( maxval(da) <= -2.d0 .and. maxval(db) <= -2.d0 ) then
	  call one_move(2,0,0,xm,ym,xp,yp,xp,yp,ie,1)
	else
	  nskip(0) = nskip(0) + 1
	end if

	! 3. zero length, just outside beside vertex 2 at its y: of the
	!    points vertex 2 +- (eps,0) the one farther outside is used
	eps = 0.01 * sqrt( (xc(2)-xm)**2 + (yc(2)-ym)**2 )
	xibest = 1.d0
	xq = xc(2)
	do isg = -1, 1, 2
	  xp = xc(2) + isg*eps
	  ximin = 1.d0
	  do ii = 1, 3
	    i1 = mod(ii,3) + 1
	    i2 = mod(i1,3) + 1
	    xil = ( (dble(xc(i1))-xp)*(dble(yc(i2))-yc(2))			&
     &		- (dble(xc(i2))-xp)*(dble(yc(i1))-yc(2)) ) / area
	    ximin = min(ximin,xil)
	  end do
	  if( ximin < xibest ) then
	    xibest = ximin
	    xq = xp
	  end if
	end do
	if( xibest < 0.d0 ) then		!outside the element
	  call one_move(3,0,0,xq,yc(2),xq,yc(2),xq,yc(2),ie,1)
	else
	  nskip(0) = nskip(0) + 1
	end if

	! 4. from the middle of side ii across to the middle of side jj
	do ii = 1, 3
	  do jj = 1, 3
	    if( jj == ii ) cycle
	    kc = side_kc(lgr_ieltv(jj,ie))
	    xb = xs(ii) + 2.*(xs(jj)-xs(ii))
	    yb = ys(ii) + 2.*(ys(jj)-ys(ii))
	    call clip(xs(ii),ys(ii),xb,yb,0)
	    bok = ( abs(da(ii)) <= 0.5d0 .and. db(ii) <= da(ii) - 2.d0 )
	    do j = 1, 3
	      if( j /= ii .and. da(j) > -2.d0 ) bok = .false.
	    end do
	    if( bok .and. leaves_clean(jj) ) then
	      call one_move(4,kc,jj,xs(ii),ys(ii),xb,yb,real(xx),real(yx)	&
     &			,kind_ie(bopen(jj)),2)
	    else
	      nskip(kc) = nskip(kc) + 1
	    end if
	  end do
	end do

	! 5. from the middle of side ii straight out: the start point
	do ii = 1, 3
	  kc = side_kc(lgr_ieltv(ii,ie))
	  xb = 2.*xs(ii) - xm
	  yb = 2.*ys(ii) - ym
	  call clip(xs(ii),ys(ii),xb,yb,0)
	  bok = ( abs(da(ii)) <= 0.5d0 .and. db(ii) >= 3.d0 )
	  do j = 1, 3
	    if( j == ii ) cycle
	    if( da(j) > -3.d0 ) bok = .false.
	    if( db(j) > da(j) ) then		!goes out of side j: sk(j) set
	      if( sk(j)*dlen < 3.d0 ) bok = .false.
	    end if
	  end do
	  if( bok ) bok = along_ok(ii,xs(ii),ys(ii))
	  if( bok ) then
	    call one_move(5,kc,ii,xs(ii),ys(ii),xb,yb,xs(ii),ys(ii)	&
     &			,kind_ie(bopen(ii)),1)
	  else
	    nskip(kc) = nskip(kc) + 1
	  end if
	end do

	! 6. from the centre through vertex k (sides ia, ib meet there)
	do k = 1, 3
	  ia = mod(k,3) + 1
	  ib = mod(ia,3) + 1
	  xb = 2.*xc(k) - xm
	  yb = 2.*yc(k) - ym
	  call clip(xm,ym,xb,yb,0)
	  bok = ( maxval(da) <= -2.d0 )
	  if( bok ) bok = ( db(ia) > da(ia) .and. db(ib) > da(ib) )
	  if( bok ) then
	    sx = min( sk(ia), sk(ib) )
	    bok = ( abs(sk(ia)-sk(ib))*dlen <= 0.5d0			&
     &		.and. sx*dlen >= 2.d0 .and. (1.d0-sx)*dlen >= 2.d0 )
	    if( db(k) > da(k) ) then
	      if( (sk(k)-sx)*dlen < 2.d0 ) bok = .false.
	    end if
	  end if
	  if( bok ) then
	    xx = xm + sx*(dble(xb)-xm)
	    yx = ym + sx*(dble(yb)-ym)
	    call one_move(6,0,k,xm,ym,xb,yb,real(xx),real(yx)		&
     &			,kind_ie(bopen(ia).and.bopen(ib)),2)
	  else
	    nskip(0) = nskip(0) + 1
	  end if
	end do

	! 7. from the middle of side ii along it past vertex i2
	do ii = 1, 3
	  i1 = mod(ii,3) + 1
	  i2 = mod(i1,3) + 1
	  kc = side_kc(lgr_ieltv(i1,ie))
	  xb = 2.*xc(i2) - xs(ii)
	  yb = 2.*yc(i2) - ys(ii)
	  call clip(xs(ii),ys(ii),xb,yb,ii)
	  bok = ( abs(da(ii)) <= 0.5d0 .and. abs(db(ii)) <= 0.5d0		&
     &		.and. da(i1) <= -2.d0 .and. da(i2) <= -2.d0 )
	  if( bok ) bok = ( iex == i1 )	!then sx and sgap are set
	  if( bok ) bok = ( sx*dlen >= 2.d0 .and. (1.d0-sx)*dlen >= 2.d0	&
     &		.and. sgap >= 2.d0 )
	  if( bok ) then
	    call one_move(7,kc,i1,xs(ii),ys(ii),xb,yb,real(xx),real(yx)	&
     &			,kind_ie(bopen(i1)),2)
	  else
	    nskip(kc) = nskip(kc) + 1
	  end if
	end do

	! 8., 9., 10. along side ii and out of an open side
	do ii = 1, 3
	  kc = side_kc(lgr_ieltv(ii,ie))
	  ia = mod(ii,3) + 1
	  ib = mod(ia,3) + 1

	  ! 8. outward, ending beyond side ii within the band
	  call place(ii,0.3,-0.40,xa,ya,bok)
	  call place(ii,0.7,0.85,xb,yb,bokb)
	  call clip(xa,ya,xb,yb,ii)
	  if( bok .and. bokb ) bok = ( abs(da(ii)) <= 0.9d0		&
     &		.and. db(ii) >= 0.6d0 .and. db(ii) <= 0.97d0			&
     &		.and. db(ii) - da(ii) >= 0.1d0 )
	  if( bok .and. bokb ) bok = others_inside(ii)			&
     &		.and. along_ok(ii,xa,ya) .and. along_ok(ii,xb,yb)
	  if( bok .and. bokb ) then
	    call projection(ii,xb,yb,xx,yx)
	    call one_move(8,kc,ii,xa,ya,xb,yb,real(xx),real(yx)		&
     &			,kind_ie(bopen(ii)),3)
	  else
	    nskip(kc) = nskip(kc) + 1
	  end if

	  ! 9. inward, ending beyond side ii within the band
	  call place(ii,0.3,0.85,xa,ya,bok)
	  call place(ii,0.7,0.60,xb,yb,bokb)
	  call clip(xa,ya,xb,yb,ii)
	  if( bok .and. bokb ) bok = ( da(ii) <= 0.97d0			&
     &		.and. db(ii) >= 0.5d0 .and. da(ii) - db(ii) >= 0.1d0 )
	  if( bok .and. bokb ) bok = others_inside(ii)			&
     &		.and. along_ok(ii,xa,ya) .and. along_ok(ii,xb,yb)
	  if( bok .and. bokb ) then
	    call projection(ii,xb,yb,xx,yx)
	    call one_move(9,kc,ii,xa,ya,xb,yb,real(xx),real(yx),ie,3)
	  else
	    nskip(kc) = nskip(kc) + 1
	  end if

	  ! 10. open side: a short move from inside the band out past it
	  if( bopen(ii) ) then
	    call place(ii,0.5,0.75,xa,ya,bok)
	    dbest = huge(1.d0)
	    do my = -1, 1
	      do mx = -40, 40
	        xbt = xa + mx*spacing(xa)
	        ybt = ya + my*spacing(ya)
	        if( xbt == xa .and. ybt == ya ) cycle
	        call clip(xa,ya,xbt,ybt,0)
	        if( dlen <= 0.5d0 .and. da(ii) > 0.05d0			&
     &		    .and. da(ii) <= 0.95d0 .and. db(ii) > 1.05d0		&
     &		    .and. dlen < dbest ) then
	          dbest = dlen
	          xb = xbt
	          yb = ybt
	        end if
	      end do
	    end do
	    if( bok .and. dbest < huge(1.d0) ) then
	      call clip(xa,ya,xb,yb,0)
	      bok = others_inside(ii) .and. along_ok(ii,xa,ya)		&
     &		.and. along_ok(ii,xb,yb)
	    else
	      bok = .false.
	    end if
	    if( bok ) then
	      call one_move(10,3,ii,xa,ya,xb,yb,xa,ya,-ie,1)
	    else
	      nskip(3) = nskip(3) + 1
	    end if
	  end if
	end do

	end subroutine test_element

!-----------------------------------------------------------------------

	function kind_ie(bflip)

! ie expected after the call: -ie if the particle leaves, else ie

	integer :: kind_ie
	logical, intent(in) :: bflip

	kind_ie = ie
	if( bflip ) kind_ie = -ie

	end function kind_ie

!-----------------------------------------------------------------------

	function side_kc(ivs)

! kind of a side from its entry in lgr_ieltv: 1 neighbour, 2 wall,
! 3 open boundary, 4 cut-off side (0 is used for checks of no side)

	integer :: side_kc
	integer, intent(in) :: ivs

	if( ivs > 0 ) then
	  side_kc = 1
	else if( ivs == 0 ) then
	  side_kc = 2
	else if( ivs > -1000 ) then
	  side_kc = 3
	else
	  side_kc = 4
	end if

	end function side_kc

!-----------------------------------------------------------------------

	function wide_element(iel,amin)

! true if the shortest altitude of element iel is at least 10 delta,
! delta = lgr_side_delta of the largest absolute corner coordinate plus
! the longest side; amin returns its smallest interior angle (degrees)

	use mod_physical_constants, only : pi_dp

	logical :: wide_element
	integer, intent(in) :: iel
	double precision, intent(out) :: amin

	integer :: kk, k1, k2
	real :: x(3), y(3), cmax
	double precision :: ar, hmax, delta, e1x, e1y, e2x, e2y, ang

	do kk = 1, 3
	  x(kk) = xgv(nen3v(kk,iel))
	  y(kk) = ygv(nen3v(kk,iel))
	end do
	ar = abs( (dble(x(2))-x(1))*(dble(y(3))-y(1))			&
     &		- (dble(x(3))-x(1))*(dble(y(2))-y(1)) )
	hmax = 0.d0
	cmax = 0.
	amin = 180.d0
	do kk = 1, 3
	  k1 = mod(kk,3) + 1
	  k2 = mod(k1,3) + 1
	  hmax = max( hmax, sqrt( (dble(x(k2))-x(k1))**2			&
     &				+ (dble(y(k2))-y(k1))**2 ) )
	  cmax = max( cmax, abs(x(kk)), abs(y(kk)) )
	  e1x = dble(x(k1)) - x(kk)		!angle at vertex kk
	  e1y = dble(y(k1)) - y(kk)
	  e2x = dble(x(k2)) - x(kk)
	  e2y = dble(y(k2)) - y(kk)
	  ang = atan2( abs(e1x*e2y-e1y*e2x), e1x*e2x+e1y*e2y )
	  amin = min( amin, ang * 180.d0 / pi_dp )
	end do
	delta = lgr_side_delta( real(cmax + hmax) )
	wide_element = .false.
	if( hmax > 0.d0 ) wide_element = ( ar / hmax >= 10.d0 * delta )

	end function wide_element


!-----------------------------------------------------------------------

	function sdist(is,xpp,ypp)

! signed distance of the point (xpp,ypp) from the line of side is of the
! element under test, positive beyond the side (outside)

	double precision :: sdist
	integer, intent(in) :: is
	real, intent(in) :: xpp, ypp

	integer :: k1, k2
	double precision :: cr

	k1 = mod(is,3) + 1
	k2 = mod(k1,3) + 1
	cr = (dble(xc(k1))-xpp)*(dble(yc(k2))-ypp)				&
     &		- (dble(xc(k2))-xpp)*(dble(yc(k1))-ypp)
	sdist = - sign(1.d0,area) * cr / hl(is)

	end function sdist

!-----------------------------------------------------------------------

	subroutine clip(xa,ya,xb,yb,iign)

! the exact segment (xa,ya)-(xb,yb) against the element under test, side
! iign set aside (0: none), in units of dm = lgr_side_delta of the move:
! da, db the distances of the two points beyond each side, dlen the
! length, sk(j) the s (0 at a, 1 at b) at which the segment crosses the
! line of side j going out (huge if it does not go out of side j), iex
! the side it leaves through first (smallest sk, 0 if none) at sx, sgap
! the distance in delta from there to the next crossing going out,
! (xx,yx) that point, dv1, dv2 its distances from the two vertices of
! side iex, sin1 where the segment enters (0 if it starts inside)

	real, intent(in) :: xa, ya, xb, yb
	integer, intent(in) :: iign

	integer :: jj2, k1, k2
	double precision :: s2

	dm = lgr_side_delta( max(abs(xa),abs(ya),abs(xb),abs(yb)) )
	dlen = sqrt( (dble(xb)-xa)**2 + (dble(yb)-ya)**2 ) / dm
	sin1 = 0.d0
	sk = huge(1.d0)
	do jj2 = 1, 3
	  da(jj2) = sdist(jj2,xa,ya) / dm
	  db(jj2) = sdist(jj2,xb,yb) / dm
	  if( jj2 == iign ) cycle
	  if( db(jj2) > da(jj2) ) then			!goes out of side jj2
	    sk(jj2) = -da(jj2) / (db(jj2) - da(jj2))
	  else if( db(jj2) < da(jj2) .and. da(jj2) > 0.d0 ) then
	    sin1 = max( sin1, da(jj2) / (da(jj2) - db(jj2)) )
	  end if
	end do
	iex = 0
	sx = huge(1.d0)
	s2 = huge(1.d0)
	do jj2 = 1, 3
	  if( sk(jj2) < sx ) then
	    s2 = sx
	    sx = sk(jj2)
	    iex = jj2
	  else if( sk(jj2) < s2 ) then
	    s2 = sk(jj2)
	  end if
	end do
	if( iex == 0 ) return
	sgap = huge(1.d0)
	if( s2 < huge(1.d0) ) sgap = (s2 - sx) * dlen
	xx = xa + sx * (dble(xb)-xa)
	yx = ya + sx * (dble(yb)-ya)
	k1 = mod(iex,3) + 1
	k2 = mod(k1,3) + 1
	dv1 = sqrt( (xx-xc(k1))**2 + (yx-yc(k1))**2 ) / dm
	dv2 = sqrt( (xx-xc(k2))**2 + (yx-yc(k2))**2 ) / dm

	end subroutine clip

!-----------------------------------------------------------------------

	function leaves_clean(is)

! after clip: the segment starts inside or enters, leaves through side
! is at least 2 delta from both its vertices, at least 2 delta after it
! entered and before the end, and 2 delta before any other crossing

	logical :: leaves_clean
	integer, intent(in) :: is

	leaves_clean = ( iex == is )
	if( .not. leaves_clean ) return
	leaves_clean = ( sx > 0.d0 .and. (sx-sin1)*dlen >= 2.d0		&
     &		.and. (1.d0-sx)*dlen >= 2.d0 .and. sgap >= 2.d0		&
     &		.and. dv1 >= 2.d0 .and. dv2 >= 2.d0 )

	end function leaves_clean

!-----------------------------------------------------------------------

	function others_inside(is)

! after clip: both points at least 2 delta inside every side but is

	logical :: others_inside
	integer, intent(in) :: is

	integer :: jj2

	others_inside = .true.
	do jj2 = 1, 3
	  if( jj2 == is ) cycle
	  if( da(jj2) > -2.d0 .or. db(jj2) > -2.d0 ) others_inside = .false.
	end do

	end function others_inside

!-----------------------------------------------------------------------

	function along_ok(is,xpp,ypp)

! the projection of (xpp,ypp) on side is lies on the side at least
! 2 delta (dm of the last clip) from both its vertices

	logical :: along_ok
	integer, intent(in) :: is
	real, intent(in) :: xpp, ypp

	integer :: k1, k2
	double precision :: t

	k1 = mod(is,3) + 1
	k2 = mod(k1,3) + 1
	t = ( (dble(xpp)-xc(k1))*(dble(xc(k2))-xc(k1))			&
     &	    + (dble(ypp)-yc(k1))*(dble(yc(k2))-yc(k1)) ) / hl(is)**2
	along_ok = ( t*hl(is) >= 2.d0*dm .and. (1.d0-t)*hl(is) >= 2.d0*dm )

	end function along_ok

!-----------------------------------------------------------------------

	subroutine projection(is,xpp,ypp,xpr,ypr)

! the exact projection of (xpp,ypp) on the line of side is

	integer, intent(in) :: is
	real, intent(in) :: xpp, ypp
	double precision, intent(out) :: xpr, ypr

	integer :: k1, k2
	double precision :: t

	k1 = mod(is,3) + 1
	k2 = mod(k1,3) + 1
	t = ( (dble(xpp)-xc(k1))*(dble(xc(k2))-xc(k1))			&
     &	    + (dble(ypp)-yc(k1))*(dble(yc(k2))-yc(k1)) ) / hl(is)**2
	xpr = xc(k1) + t*(dble(xc(k2))-xc(k1))
	ypr = yc(k1) + t*(dble(yc(k2))-yc(k1))

	end subroutine projection

!-----------------------------------------------------------------------

	subroutine place(is,t0,off,xpp,ypp,bok)

! a point near the fraction t0 along side is, off delta beyond its line
! (negative: inside), on the single precision grid: of the points near
! the target (positions t0-0.10 ... t0+0.10 along the side, a few grid
! steps around each) the one whose measured distance is nearest to off
! delta, its position along the side kept within 0.12 of t0; bok is
! false if none is within 0.1 delta of the target

	integer, intent(in) :: is
	real, intent(in) :: t0, off
	real, intent(out) :: xpp, ypp
	logical, intent(out) :: bok

	integer :: k1, k2, kx, ky, kt
	real :: x0, y0, xt, yt
	double precision :: ax, ay, bx, by, nx, ny, dc, err, ebest, t, tc

	k1 = mod(is,3) + 1
	k2 = mod(k1,3) + 1
	ax = xc(k1)
	ay = yc(k1)
	bx = xc(k2)
	by = yc(k2)
	nx = (by-ay) / hl(is)			!a normal of side is
	ny = -(bx-ax) / hl(is)
	if( nx*(xc(is)-ax) + ny*(yc(is)-ay) > 0.d0 ) then
	  nx = -nx				!pointing outside
	  ny = -ny
	end if
	x0 = ax + t0*(bx-ax)
	y0 = ay + t0*(by-ay)
	dc = lgr_side_delta( max(abs(x0),abs(y0)) )
	ebest = huge(1.d0)
	xpp = x0
	ypp = y0
	do kt = -10, 10
	  t = t0 + 0.01d0*kt
	  x0 = ax + t*(bx-ax) + off*dc*nx
	  y0 = ay + t*(by-ay) + off*dc*ny
	  do ky = -2, 2
	    do kx = -40, 40
	      xt = x0 + kx*spacing(x0)
	      yt = y0 + ky*spacing(y0)
	      tc = ( (dble(xt)-ax)*(bx-ax) + (dble(yt)-ay)*(by-ay) )		&
     &		/ hl(is)**2
	      if( abs(tc-t0) > 0.12d0 ) cycle
	      err = abs( sdist(is,xt,yt) - off*dc )
	      if( err < ebest ) then
	        ebest = err
	        xpp = xt
	        ypp = yt
	      end if
	    end do
	  end do
	end do
	bok = ( ebest <= 0.1d0 * dc )

	end subroutine place

!-----------------------------------------------------------------------

	subroutine one_move(icheck,kcs,is,xa,ya,xb,yb,xe,ye,ieexp,mode)

! one call of particle_on_side for element ie, a move from (xa,ya) to
! (xb,yb), counted as run under side kind kcs; expected: the point
! (xe,ye) and ieexp; mode 1: the point exactly, 2: within 0.5 dm in each
! coordinate, 3: on side is (within 0.45 dm of its line and within
! 0.6 dm of (xe,ye) in each coordinate); dm of the last clip. A failure
! is counted and printed in one line.

	integer, intent(in) :: icheck		!check, see cname
	integer, intent(in) :: kcs		!side kind it is counted under
	integer, intent(in) :: is		!side (vertex in check 6)
	real, intent(in) :: xa, ya, xb, yb	!the move
	real, intent(in) :: xe, ye		!the point expected
	integer, intent(in) :: ieexp		!ie expected
	integer, intent(in) :: mode		!how the point is compared

	integer :: iet, ige, igr
	real :: xn, yn
	logical :: bbad

	nrun(kcs) = nrun(kcs) + 1
	xn = xb
	yn = yb
	iet = ie
	call particle_on_side(iet,xa,ya,xn,yn)

	if( mode == 1 ) then
	  bbad = ( xn /= xe .or. yn /= ye )
	else if( mode == 2 ) then
	  bbad = ( abs(xn-xe) > 0.5d0*dm .or. abs(yn-ye) > 0.5d0*dm )
	else
	  bbad = ( abs(sdist(is,xn,yn)) > 0.45d0*dm			&
     &	    .or. abs(xn-xe) > 0.6d0*dm .or. abs(yn-ye) > 0.6d0*dm )
	end if
	if( iet /= ieexp ) bbad = .true.
	if( .not. bbad ) return

	nfail = nfail + 1
	ige = sign( ip_int_elem(ie), ieexp )
	igr = sign( ip_int_elem(ie), iet )
	write(6,'(a,i0,3a,i0,a,i0,3a,4(1x,g0),a,2(1x,g0),a,i0,a,2(1x,g0),a,i0)')	&
     &		'lgr side fallback self-test: FAILED check ',icheck		&
     &		,' (',trim(cname(icheck)),'), element ',ip_int_elem(ie)	&
     &		,' side ',is,' (',trim(kname(kcs)),'): move',xa,ya,xb,yb	&
     &		,'; expected',xe,ye,' element ',ige			&
     &		,'; returned',xn,yn,' element ',igr

	end subroutine one_move

!-----------------------------------------------------------------------

	end subroutine lgr_mpi_selftest_side

!*******************************************************************

	function lgr_mpi_find_elem(ie_global)

! local element number of global element ie_global, 0 if this process does
! not hold it (or ie_global <= 0); bisection in the sorted copy of
! ip_int_elem (lgr_mpi_lookup_init)

	implicit none

	integer :: lgr_mpi_find_elem
	integer, intent(in) :: ie_global

	integer :: j

	lgr_mpi_find_elem = 0
	if( ie_global <= 0 ) return

	if( .not. allocated(lgr_elem_key) ) call shympi_abort_internal	&
     &		('lgr_mpi_find_elem: lookup not built')
	j = lgr_mpi_bisect(size(lgr_elem_key),lgr_elem_key,ie_global)
	if( j > 0 ) lgr_mpi_find_elem = lgr_elem_loc(j)

	end function lgr_mpi_find_elem

!*******************************************************************

	function lgr_mpi_find_node(k_global)

! local node number of global node k_global, 0 if this process does not
! hold it (or k_global <= 0); bisection in the sorted copy of ip_int_node
! (lgr_mpi_lookup_init)

	implicit none

	integer :: lgr_mpi_find_node
	integer, intent(in) :: k_global

	integer :: j

	lgr_mpi_find_node = 0
	if( k_global <= 0 ) return

	if( .not. allocated(lgr_node_key) ) call shympi_abort_internal	&
     &		('lgr_mpi_find_node: lookup not built')
	j = lgr_mpi_bisect(size(lgr_node_key),lgr_node_key,k_global)
	if( j > 0 ) lgr_mpi_find_node = lgr_node_loc(j)

	end function lgr_mpi_find_node

!*******************************************************************

	subroutine lgr_mpi_handover(dtime)

! hand-over of the particles marked in this time step, in rounds
! (lgr_mpi_handover_round): those marked at a cut-off side
! (lgr_mpi_mark_side) finish the step on the process across, with the
! time and the crossings they have left; those parked in the element
! search of the diffusion or Stokes step (lgr_mpi_park) are resolved by
! position and finish the step from where they were parked, in the
! element a serial search finds, on a process that holds it. Every
! process takes part in every round, and a round is made while the
! global number of marks of either kind is not zero (one collective
! decision per round on both counts). A particle marked in a round goes
! in the next one: an arrival at a side can reach another cut-off side or
! park in either step, a particle resumed from the diffusion step can
! park in the Stokes step, one resumed from the Stokes step finishes.
!
! Bound: every hand-over at a side uses one crossing of the particle's
! budget for the step (lgr_ncross_max, n_left; #315: the base budget and
! the extra crossings), so a particle is handed over at a side at most
! lgr_ncross_max times in a step; it parks at most twice (once in each
! step, and a resumed particle does no more advection, so no side mark
! follows a park). A round takes every marked particle one event
! further, so after lgr_ncross_max + 2 rounds nothing is marked; one
! round more is an internal error, decided alike on every process (the
! counts are global), and every process aborts.
!
! called after drogue, outside any parallel region, on every process
!
! statistics (lgr_mpi_handover_stats): the particles that change process
! in the step, summed over the processes and the rounds (the number each
! process sent in a round travels in the next round's reduction, so the
! last one in the reduction that ends the loop), and their largest number
! in one step; at levdbg >= 3 the dry elements of the step (iwegv /= 0,
! counted once by the main owner) and the dry held elements that have a
! cut-off side on this process (lgr_ndry)

	use shympi, only : n_threads, my_id, id_elem
	use basin, only : nel
	use mod_geom_dynamic, only : iwegv

	implicit none

	include 'mpif.h'

	double precision, intent(in) :: dtime

	integer, parameter :: nround_cap = lgr_ncross_max + 2 !crossings, 2 parks
	integer :: nloc(3), nglob(3), nround, nround_side, nchg, ie, ierr

	if( n_threads <= 1 ) return

	if( blgr_dbg ) then			!dry elements of the step
	  do ie = 1, nel
	    if( iwegv(ie) == 0 ) cycle
	    if( id_elem(1,ie) == my_id ) lgr_ndry(1) = lgr_ndry(1) + 1
	    if( any( lgr_ieltv(:,ie) <= -1000 ) ) then
	      lgr_ndry(2) = lgr_ndry(2) + 1
	    end if
	  end do
	end if

	nround = 0
	nround_side = 0
	nchg = 0
	lgr_npark_step = 0
	lgr_nsent_round = 0
	do
	  call lgr_mpi_list_check('hand-over')	!before the collective call
	  nloc(1) = n_export
	  nloc(2) = n_park
	  nloc(3) = lgr_nsent_round		!sent in the round before
	  lgr_nsent_round = 0
	  call MPI_Allreduce(nloc,nglob,3,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover: MPI_Allreduce')
	  nchg = nchg + nglob(3)
	  if( nglob(1) == 0 .and. nglob(2) == 0 ) exit
	  nround = nround + 1
	  if( nround > nround_cap ) call shympi_abort_internal		&
     &		('lgr_mpi_handover: more rounds than a step allows')
	  if( nglob(1) > 0 ) nround_side = nround
	  lgr_npark_step = lgr_npark_step + nglob(2)
	  call lgr_mpi_handover_round(dtime,nglob(2) > 0)
	end do

	! a particle's k-th hand-over at a side is in round k (its side
	! marks come before its parks): the last round with a side mark
	lgr_nround_max = max(lgr_nround_max,nround_side)
	lgr_npark_step_max = max(lgr_npark_step_max,lgr_npark_step)
	if( nchg > lgr_nchg_max ) then
	  lgr_nchg_max = nchg
	  lgr_tchg_max = dtime
	end if

	end subroutine lgr_mpi_handover

!*******************************************************************

	subroutine lgr_mpi_handover_round(dtime,bres)

! one round of the hand-over (lgr_mpi_handover), on every process:
! 0. if bres (some process has parked particles): the parked particles
!    are resolved by position (lgr_mpi_resolve); those that stay on this
!    process get their outcome in lgr_park_ie and the mark 4 or 5, those
!    that go to another process are listed (pos_idx, pos_dest, pos_elem)
! 1. the marks at sides are sorted by particle slot (the threads fill the
!    list in the order they arrive) and merged with the position list (a
!    slot is in at most one of the two); the particles to send are
!    counted per destination; the counts are exchanged (MPI_Alltoall), so
!    both sides know every message length
! 2. each particle to send is packed, per destination in slot order: its
!    record and the hand-over fields (layout at the top of the module):
!    at a side the element it is leaving, the end nodes of the side and
!    its weights there, t_left, n_left, phase 0 and d_start (#315); by
!    position the element
!    found, both points of the parked move, the crossings used in the
!    step and the phase of the parking (1 or 2); the messages are sent and
!    received, their lengths checked
! 3. the sent particles of both kinds are removed (one call of
!    lgr_mpi_remove_list), the lists are emptied; a particle that stays
!    may move to another slot, with its per-slot values and mark
! 4. the arrivals are appended in a fixed order (by sending process, then
!    in the sender's order). An arrival at a side is put into the local
!    element across the side, the one that has both end nodes and is not
!    the element left, with the weights at the two end nodes and zero at
!    the third vertex: the values track_xi_next_element copies in a
!    serial run. Then the layer adjustment that track_xi applies after a
!    crossing (track_xi_adjust_layer), which the sender did not run. An
!    arrival by position is put into the element found (this process is
!    its main owner), with both points of its move, its crossing count
!    and the mark 4 or 5 (resolved); nothing of its step is made again
! 5. the particles resolved in this round are resumed: the slots 1..nbdy
!    are scanned for the marks 4 and 5 (those that stayed, wherever step
!    3 moved them, and the arrivals by position), and each is finished
!    from where it was parked (track_finish with phase 1 or 2), in slot
!    order. Then each arrival at a side goes on with track_advect, with
!    the time, crossings and d_start that travelled (the start-of-step tests of
!    track_single were applied where the step began) and, unless it is
!    marked again, track_finish (phase 0) once. Marks made here (at a
!    side, or a parking) go in the next round.
!
! the record travels whole and unchanged: actual%time still holds the
! start of the step, as track_finish needs it

	use shympi
	use basin, only : nen3v, nel

	implicit none

	include 'mpif.h'

	double precision, intent(in) :: dtime
	logical, intent(in) :: bres		!resolve parked particles first

	interface
	  subroutine track_advect(i,t_left,n_left,d_start,dtime)
	    implicit none
	    integer, intent(in) :: i
	    real, intent(inout) :: t_left
	    integer, intent(inout) :: n_left
	    double precision, intent(in) :: d_start
	    double precision, intent(in) :: dtime
	  end subroutine track_advect
	  subroutine track_finish(i,phase,dtime)
	    implicit none
	    integer, intent(in) :: i
	    integer, intent(in) :: phase
	    double precision, intent(in) :: dtime
	  end subroutine track_finish
	  subroutine track_xi_adjust_layer(id,ieorig,iel,lb,z)
	    implicit none
	    integer, intent(in) :: id
	    integer, intent(in) :: ieorig
	    integer, intent(in) :: iel
	    integer, intent(inout) :: lb
	    double precision, intent(inout) :: z
	  end subroutine track_xi_adjust_layer
	end interface

	integer :: nproc, lrecp, lrec, nside, npos, nmark, j, jj, i, k, r
	integer :: ie, iside, ia2, ia3, ip, ierr, nreq, nrecv, nget
	integer :: nstot, nrtot, nside_in, nrem
	integer :: iega, kg1, kg2, kl1, kl2, ieb, nf, phase, lb, iw
	integer :: nsend(0:n_threads-1), nrcv(0:n_threads-1)
	integer :: soff(0:n_threads), roff(0:n_threads)
	integer :: ifill(0:n_threads-1)
	integer :: ireq(2*n_threads)
	integer :: istat(MPI_STATUS_SIZE,2*n_threads)
	integer, allocatable :: key(:), iord(:), islot(:), inleft(:)
	integer, allocatable :: ckind(:), cj(:), cdest(:)
	real, allocatable :: rtleft(:)
	double precision, allocatable :: rdstart(:)	!d_start (#315)
	double precision, allocatable :: sbuf(:), rbuf(:)
	double precision :: w1, w2, zz
	double precision :: xi(3)

	nproc = n_threads
	lrecp = lgr_pack_base + ncust		!record of a particle
	lrec = lrecp + lgr_hand_extra		!record and hand-over fields

	!-----------------------------------------------
	! 0. resolution by position
	!-----------------------------------------------

	npos = 0
	if( bres ) call lgr_mpi_resolve(npos)

	!-----------------------------------------------
	! 1. marks sorted by slot and merged, counted per destination,
	!    counts exchanged
	!-----------------------------------------------

	nside = n_export
	nmark = nside + npos

	allocate(key(max(nmark,1)), iord(max(nmark,1))			&
     &		, ckind(max(nmark,1)), cj(max(nmark,1)), cdest(max(nmark,1))	&
     &		, stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: allocation')

	do j = 1, nside
	  key(j) = export_idx(j)
	  iord(j) = j
	end do
	do j = 1, npos
	  key(nside+j) = pos_idx(j)
	  iord(nside+j) = nside + j
	end do
	call lgr_mpi_sort_by_key(nmark,key,iord)
	do j = 2, nmark
	  if( key(j) == key(j-1) ) then
	    write(6,*) 'lgr_mpi_handover_round: slot marked twice: ',key(j)
	    call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: slot marked twice')
	  end if
	end do
	do jj = 1, nmark
	  j = iord(jj)
	  if( j <= nside ) then			!at a side
	    ckind(jj) = 0
	    cj(jj) = j
	    cdest(jj) = export_dest(j)
	  else					!by position
	    ckind(jj) = 1
	    cj(jj) = j - nside
	    cdest(jj) = pos_dest(j-nside)
	  end if
	end do

	nsend = 0
	do jj = 1, nmark
	  r = cdest(jj)
	  if( r < 0 .or. r >= nproc .or. r == my_id ) then
	    write(6,*) 'lgr_mpi_handover_round: destination: ',r
	    call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: destination')
	  end if
	  nsend(r) = nsend(r) + 1
	end do

	call MPI_Alltoall(nsend,1,MPI_INTEGER,nrcv,1,MPI_INTEGER		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_round: MPI_Alltoall')

	soff(0) = 0
	roff(0) = 0
	do r = 0, nproc-1
	  soff(r+1) = soff(r) + nsend(r)
	  roff(r+1) = roff(r) + nrcv(r)
	end do
	nstot = soff(nproc)
	nrtot = roff(nproc)

	allocate(sbuf(max(lrec*nstot,1)), rbuf(max(lrec*nrtot,1))	&
     &		, stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: allocation')

	!-----------------------------------------------
	! 2. pack, per destination in slot order, and exchange
	!-----------------------------------------------

	ifill = 0
	do jj = 1, nmark
	  r = cdest(jj)
	  i = key(jj)
	  j = cj(jj)
	  ip = lrec*(soff(r) + ifill(r))
	  ifill(r) = ifill(r) + 1
	  if( ckind(jj) == 0 ) then		!at a side
	    ie = export_elem(j)
	    iside = export_side(j)
	    if( lgr_ar(i)%actual%ie /= ie .or. lgr_marked(i) /= 1 		&
     &		.or. lgr_ar(i)%actual%xi(iside) /= 0.d0 ) then
	      write(6,*) 'lgr_mpi_handover_round: i,ie,iside,actual ie,'	&
     &		//'mark,xi: ',i,ie,iside,lgr_ar(i)%actual%ie		&
     &		,lgr_marked(i),lgr_ar(i)%actual%xi
	      call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: marked particle changed')
	    end if
	    if( id_elem(0,ie) == 3 ) lgr_nhand3(1) = lgr_nhand3(1) + 1
	    call lgr_mpi_pack_particle(lgr_ar(i),sbuf(ip+1:ip+lrecp))
	    ia2 = mod(iside,3) + 1		!end nodes of side iside
	    ia3 = mod(ia2,3) + 1
	    ip = ip + lrecp
	    sbuf(ip+1) = dble(ip_int_elem(ie))
	    sbuf(ip+2) = dble(ip_int_node(nen3v(ia2,ie)))
	    sbuf(ip+3) = dble(ip_int_node(nen3v(ia3,ie)))
	    sbuf(ip+4) = lgr_ar(i)%actual%xi(ia2)
	    sbuf(ip+5) = lgr_ar(i)%actual%xi(ia3)
	    sbuf(ip+6) = dble(export_tleft(j))
	    sbuf(ip+7) = dble(export_nleft(j))
	    sbuf(ip+8) = 0.d0			!phase 0: advection goes on
	    sbuf(ip+9) = export_dstart(j)	!d_start (#315)
	  else					!by position
	    if( lgr_marked(i) /= 2 .and. lgr_marked(i) /= 3 ) then
	      write(6,*) 'lgr_mpi_handover_round: i,mark: ',i,lgr_marked(i)
	      call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: parked particle changed')
	    end if
	    phase = lgr_marked(i) - 1
	    ie = lgr_ar(i)%actual%ie		!element it was parked in
	    if( ie >= 1 .and. ie <= nel ) then	!(lgr_mpi_resolve tested it)
	      if( id_elem(0,ie) == 3 ) lgr_nhand3(2) = lgr_nhand3(2) + 1
	    end if
	    call lgr_mpi_pack_particle(lgr_ar(i),sbuf(ip+1:ip+lrecp))
	    ip = ip + lrecp
	    sbuf(ip+1) = dble(pos_elem(j))	!global element found
	    do k = 1, 4			!old x, y, new x, y
	      sbuf(ip+1+k) = dble(lgr_park_xy(k,i))
	    end do
	    sbuf(ip+6) = dble(lgr_ncross(i))
	    sbuf(ip+7) = 0.d0
	    sbuf(ip+8) = dble(phase)		!1 diffusion, 2 Stokes drift
	    sbuf(ip+9) = 0.d0			!no advection after a parking
	  end if
	end do

	nreq = 0
	do r = 0, nproc-1
	  if( nrcv(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Irecv(rbuf(lrec*roff(r)+1),lrec*nrcv(r)			&
     &		,MPI_DOUBLE_PRECISION,r,lgr_hand_tag,MPI_COMM_WORLD	&
     &		,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_round: MPI_Irecv')
	end do
	nrecv = nreq
	do r = 0, nproc-1
	  if( nsend(r) == 0 ) cycle
	  nreq = nreq + 1
	  call MPI_Isend(sbuf(lrec*soff(r)+1),lrec*nsend(r)			&
     &		,MPI_DOUBLE_PRECISION,r,lgr_hand_tag,MPI_COMM_WORLD	&
     &		,ireq(nreq),ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_round: MPI_Isend')
	end do
	if( nreq > 0 ) then
	  call MPI_Waitall(nreq,ireq,istat,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_round: MPI_Waitall')
	end if
	jj = 0
	do r = 0, nproc-1
	  if( nrcv(r) == 0 ) cycle
	  jj = jj + 1
	  call MPI_Get_count(istat(:,jj),MPI_DOUBLE_PRECISION,nget,ierr)
	  if( ierr /= MPI_SUCCESS .or. nget /= lrec*nrcv(r) ) then
	    write(6,*) 'lgr_mpi_handover_round: rank ',my_id,' from rank '	&
     &		,r,' expected ',lrec*nrcv(r),' values, received ',nget
	    call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: message length')
	  end if
	end do
	if( jj /= nrecv ) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: internal error (receives)')

	!-----------------------------------------------
	! 3. remove the sent particles, empty the lists
	!-----------------------------------------------

	nrem = nmark
	if( lgr_test_dup ) then		!test hook: keep one particle sent
	  do jj = 1, nmark		!the first one sent at a side
	    if( ckind(jj) == 0 ) exit
	  end do
	  if( jj <= nmark ) then
	    lgr_test_dup = .false.
	    i = key(jj)
	    lgr_marked(i) = 0		!the copy stays, not marked
	    write(6,*) 'LGR_TEST_DUP: rank ',my_id,' keeps a copy of id '	&
     &		,lgr_ar(i)%id,' sent at a side, time ',dtime
	    key(jj:nmark-1) = key(jj+1:nmark)
	    nrem = nmark - 1
	  end if
	end if
	call lgr_mpi_remove_list(nrem,key)	!key: the slots sent
	lgr_nhand = lgr_nhand + nside
	lgr_nsent_round = nmark			!read by lgr_mpi_handover
	n_export = 0

	!-----------------------------------------------
	! 4. append the arrivals: by sending process, then the sender's order
	!-----------------------------------------------

	if( nbdy + nrtot > size(lgr_ar) ) then
	  call mod_lagrange_handle_alloc(nbdy+nrtot)
	end if

	allocate(islot(max(nrtot,1)), inleft(max(nrtot,1))		&
     &		, rtleft(max(nrtot,1)), rdstart(max(nrtot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: allocation')

	nside_in = 0
	do j = 1, nrtot
	  ip = lrec*(j-1)
	  if( lgr_test_drop ) then	!test hook: lose one arrival
	    if( nint(rbuf(ip+lrecp+8)) == 0 ) then	!the first at a side
	      lgr_test_drop = .false.
	      write(6,*) 'LGR_TEST_DROP: rank ',my_id,' drops the arrival'	&
     &		//' of id ',nint(rbuf(ip+15)),' at a side, time ',dtime
	      cycle
	    end if
	  end if
	  nbdy = nbdy + 1
	  i = nbdy
	  call lgr_mpi_unpack_particle(rbuf(ip+1:ip+lrecp),lgr_ar(i))
	  ip = ip + lrecp
	  phase = nint(rbuf(ip+8))

	  if( phase == 1 .or. phase == 2 ) then	!by position
	    iw = nint(rbuf(ip+1))
	    ie = lgr_mpi_find_elem(iw)
	    if( ie <= 0 ) then
	      write(6,*) 'lgr_mpi_handover_round: rank ',my_id,' id '	&
     &		,lgr_ar(i)%id,' element found ',iw,' not held'
	      call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: element found not held')
	    end if
	    lgr_ar(i)%actual%ie = ie
	    do k = 1, 4			!old x, y, new x, y
	      lgr_park_xy(k,i) = real(rbuf(ip+1+k))
	    end do
	    lgr_ncross(i) = nint(rbuf(ip+6))
	    lgr_park_ie(i) = ie
	    lgr_marked(i) = 3 + phase		!resolved: resumed in step 5
	    cycle
	  else if( phase /= 0 ) then
	    write(6,*) 'lgr_mpi_handover_round: phase ',phase
	    call shympi_abort_internal('lgr_mpi_handover_round: phase')
	  end if

	  iega = nint(rbuf(ip+1))		!at a side
	  kg1 = nint(rbuf(ip+2))
	  kg2 = nint(rbuf(ip+3))
	  w1 = rbuf(ip+4)
	  w2 = rbuf(ip+5)
	  nside_in = nside_in + 1
	  rtleft(nside_in) = real(rbuf(ip+6))
	  inleft(nside_in) = nint(rbuf(ip+7))
	  rdstart(nside_in) = rbuf(ip+9)	!d_start, unchanged (#315)

	  ! local element across: both end nodes, not the element left
	  kl1 = lgr_mpi_find_node(kg1)
	  kl2 = lgr_mpi_find_node(kg2)
	  ieb = 0
	  nf = 0
	  if( kl1 > 0 .and. kl2 > 0 ) then
	    do k = lgr_ne_ptr(kl1)+1, lgr_ne_ptr(kl1+1)
	      ie = lgr_ne_list(k)
	      if( ip_int_elem(ie) == iega ) cycle	!the element left
	      if( nen3v(1,ie) == kl2 .or. nen3v(2,ie) == kl2 .or.	&
     &		nen3v(3,ie) == kl2 ) then
	        nf = nf + 1
	        if( ieb == 0 ) ieb = ie
	      end if
	    end do
	  end if
	  if( nf /= 1 ) then
	    write(6,*) 'lgr_mpi_handover_round: rank ',my_id,' id '	&
     &		,lgr_ar(i)%id,' element left ',iega,' side nodes '	&
     &		,kg1,kg2,' local ',kl1,kl2,' elements found ',nf
	    call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: element across not found')
	  end if

	  do k = 1, 3
	    if( nen3v(k,ieb) == kl1 ) then
	      xi(k) = w1
	    else if( nen3v(k,ieb) == kl2 ) then
	      xi(k) = w2
	    else
	      xi(k) = 0.d0
	    end if
	  end do

	  lgr_ar(i)%actual%ie = ieb
	  lgr_ar(i)%actual%xi = xi
	  lb = lgr_ar(i)%actual%l
	  zz = lgr_ar(i)%actual%z
	  call track_xi_adjust_layer(lgr_ar(i)%id,0,ieb,lb,zz)
	  lgr_ar(i)%actual%l = lb
	  lgr_ar(i)%actual%z = real(zz)
	  lgr_ncross(i) = lgr_ncross_max - inleft(nside_in) !crossings so far
	  lgr_marked(i) = 0
	  islot(nside_in) = i
	end do

	!-----------------------------------------------
	! 5. the resolved particles finish their step from where they were
	!    parked; the arrivals at a side go on: advection, then the rest
	!-----------------------------------------------

	do i = 1, nbdy
	  if( lgr_marked(i) == 4 .or. lgr_marked(i) == 5 ) then
	    phase = lgr_marked(i) - 3
	    lgr_marked(i) = 0
	    call track_finish(i,phase,dtime)
	  end if
	end do

	do j = 1, nside_in
	  i = islot(j)
	  call track_advect(i,rtleft(j),inleft(j),rdstart(j),dtime)
	  if( lgr_marked(i) == 0 ) call track_finish(i,0,dtime)
	end do

	deallocate(key,iord,ckind,cj,cdest,sbuf,rbuf,islot,inleft,rtleft)
	deallocate(rdstart)

	end subroutine lgr_mpi_handover_round

!*******************************************************************

	subroutine lgr_mpi_handover_stats

! at levdbg >= 3, on several processes, collective: rank 0 writes the
! totals of the hand-over over all processes: particles handed over at a
! cut-off side (lgr_nhand) and by position (lgr_nres_sent, those that went
! to another process in lgr_mpi_resolve), the most hand-overs at a side of
! one particle in one time step, and the particles put back at a cut-off
! side for lack of a layer (track_xi_side_test).
! The most hand-overs at a side of one particle in a step is the last
! round of a step with a side mark (lgr_nround_max): a particle's side
! marks come before its parkings and a round takes every marked particle
! one event further, so a particle sent at a side in round k is handed
! over at a side for the k-th time in that step; rounds that only resolve
! parked particles do not count.
! The line goes on with the hand-overs (at a side, by position) that
! start in an element held by three processes (id_elem(0,ie) == 3: the
! element left at a side, the element a parked particle was in;
! lgr_nhand3). A second line gives the most particles that changed
! process in one step (both kinds, all processes and rounds; lgr_nchg_max)
! and the end of that step; a third the dry element-steps (iwegv /= 0)
! counted by the main owner, and the dry held elements with a cut-off side
! (element-steps summed over the processes: an element shared by two
! processes with a cut-off side on each counts twice; lgr_ndry).
! A fourth line counts the particles that have left the basin (ie < 0;
! such a particle stays in the array of the process that carried it when
! it left, with ie = -(the local element it left); a decayed particle
! would count here too, ie = -abs(ie) since #226, but ldecay stops on
! several processes, #228) and, of them, those
! whose element left has another process as its main owner
! (id_elem(1,-ie) /= my_id: a mixed element held here but owned
! elsewhere; spec section 7, case 4), counted on the particle array now.
!
! called by lagrange after the step that reaches the end of the particle
! run and at the first call after it; only the first call writes (every
! process makes the same calls, so all take part in the same reduction)

	use shympi, only : my_id, n_threads, id_elem

	implicit none

	include 'mpif.h'

	integer, parameter :: nv = 9
	integer :: ival(nv), ivalg(nv), nrmax, ierr
	integer :: i, ie
	logical, save :: bdone = .false.	!totals written

	if( .not. blgr_dbg .or. n_threads <= 1 ) return
	if( bdone ) return
	bdone = .true.

	ival(1) = lgr_nhand
	ival(2) = lgr_nputback
	ival(3) = lgr_nres_sent
	ival(4:5) = lgr_nhand3(1:2)
	ival(6:7) = lgr_ndry(1:2)
	ival(8:9) = 0			!left the basin: all, main owner elsewhere
	do i=1,nbdy
	  ie = lgr_ar(i)%actual%ie
	  if( ie < 0 ) then
	    ival(8) = ival(8) + 1
	    if( id_elem(1,-ie) /= my_id ) ival(9) = ival(9) + 1
	  end if
	end do
	call MPI_Allreduce(ival,ivalg,nv,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_stats: MPI_Allreduce')
	call MPI_Allreduce(lgr_nround_max,nrmax,1,MPI_INTEGER,MPI_MAX	&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_stats: MPI_Allreduce')

	if( my_id == 0 ) then
	  write(6,'(a,i0,a,i0,a,i0,a,i0,a,i0,a,i0)') ' lgr hand-over:'	&
     &		//' particles handed over at a cut-off side: ',ivalg(1)	&
     &		,', by position: ',ivalg(3)				&
     &		,', most hand-overs at a side of one particle in one step: '	&
     &		,nrmax,', put back at a cut-off side for lack of a layer: '	&
     &		,ivalg(2),', starting in an element held by three'		&
     &		//' processes: at a side ',ivalg(4),', by position ',ivalg(5)
	  write(6,'(a,i0,a,f0.1)') ' lgr hand-over: most particles'	&
     &		//' changing process in one step: ',lgr_nchg_max		&
     &		,', step ending at time ',lgr_tchg_max
	  write(6,'(a,i0,a,i0)') ' lgr dry elements: element-steps dry'	&
     &		//' (counted by the main owner) ',ivalg(6)			&
     &		,', dry with a cut-off side ',ivalg(7)
	  write(6,'(a,i0,a,i0)') ' lgr left the basin: particles '	&
     &		,ivalg(8),', from an element whose main owner is another'	&
     &		//' process: ',ivalg(9)
	end if

	end subroutine lgr_mpi_handover_stats

!*******************************************************************

	subroutine lgr_mpi_check_consistency(dtime)

! built-in check of the particle state on several processes, active at
! levdbg >= 2 (blgr_chk, decided by lgr_mpi_init); a no-op on one process
! and at levdbg < 2, so a serial run is not changed. Called by lagrange
! once per time step on every process, right after lgr_mpi_handover (the
! rounds of the hand-over have ended). Collective: every process makes
! the same calls in the same order, also one without particles, and every
! decision is taken on reduced values, the same on every process. Checks:
! (a) particle count: the slots 1..nbdy of all processes, by class: in
!     the domain (actual%ie > 0, beached ones included), left the basin
!     (ie < 0: through an open boundary or into a transit element; a
!     decayed particle also keeps -abs(ie) since #226, but ldecay stops on
!     several processes, #228) and without an element (ie = 0: inserted
!     outside the mesh), summed over the processes, equal the number of
!     particles released so
!     far, the ids given out (idbdy, global since lgr_mpi_assign_ids, the
!     same on every process). A slot is removed only by the hand-over,
!     which appends the particle on the receiving process in the same
!     round; the particles put back at a cut-off side (lgr_nputback) stay
!     in the domain, it counts events, not a class.
! (b) every particle in the domain sits in an element this process holds
!     (a local element number 1..nel), and every slot 1..nbdy holds a
!     particle record (its custom values allocated: lgr_mpi_remove_particle
!     frees them in the slot it vacates); and no slot carries a mark of the
!     hand-over (lgr_marked /= 0: at a side or parked) after the rounds.
! (c) no id occurs on two processes, and no id twice on one process. Exact:
!     every process counts its slots per id over the ids given out so far,
!     1..nid with nid = idbdy (the largest over the processes), in an array
!     whose last entry nid+1 counts the ids outside 1..nid; the arrays are
!     summed (MPI_Allreduce), an id with a sum above 1 is a duplicate, and
!     an id outside 1..nid, which was never given out, is reported as out
!     of range. Cost per step: two integer arrays of length nid+1 per
!     process (allocated and freed in the call), one MPI_Allreduce of nid+1
!     integers and two of a few integers.
! (a), (b) and (c) are evaluated every time. If any fails, rank 0 writes
! every failing message with its numbers (the per-process values gathered
! to rank 0), flushes, and after a barrier every process stops through
! shympi_abort_internal; no process stops alone. Unlike the self-tests,
! which only report, this check aborts: it compares exact counts of the
! real particle state, so it has no false failure; a failure means the
! state is wrong.
!
! test hooks (environment variables read once by lgr_mpi_init, inactive
! unless set; mpirun passes a variable to the processes only with
! -x NAME): LGR_TEST_DROP=R, LGR_TEST_DUP=R with R a rank number; process
! R injects the fault once in the whole run, at its first hand-over at a
! side, and writes one line when it does; every other process ignores the
! variable. DROP: R skips its first arrival at a side in
! lgr_mpi_handover_round (the particle is lost; (a) fails). DUP: R keeps
! the first particle it sends at a side; the copy stays in its slot on the
! side with its mark cleared ((a) and (c) fail).
!
! a release that gives out no global ids (lgrini, lgrtrj, lgrpps on a
! boundary) is stopped at start-up by lgr_mpi_check_supported

	use shympi, only : my_id, n_threads
	use basin, only : nel

	implicit none

	include 'mpif.h'

	double precision, intent(in) :: dtime

	integer, parameter :: nv = 5		!counts summed over processes
	integer, parameter :: ninf = 12		!per process, for the messages
	integer, parameter :: ndl = 10		!duplicate ids listed
	integer :: ival(nv), ivalg(nv), imx(2), imxg(2), info(ninf)
	integer :: ldup(ndl), cdup(ndl)
	integer :: i, ie, id, k, r, n, nid, ndup, nl, nheld, idbmin, idbmax
	integer :: nout, ierr
	integer, allocatable :: icnt(:), icntg(:), infog(:,:), cdupg(:,:)
	logical :: bfa, bfb1, bfb2, bfc1, bfc2
	character(len=1000) :: line
	character(len=16) :: buf

	if( .not. blgr_chk ) return

	!-----------------------------------------------
	! own slots: classes and (b)
	!-----------------------------------------------

	ival = 0
	info = 0
	imx(1) = idbdy
	imx(2) = -idbdy
	do i = 1, nbdy
	  ie = lgr_ar(i)%actual%ie
	  id = lgr_ar(i)%id
	  if( ie > 0 ) then
	    ival(1) = ival(1) + 1
	  else if( ie < 0 ) then
	    ival(2) = ival(2) + 1
	  else
	    ival(3) = ival(3) + 1
	  end if
	  if( ie > nel .or. .not. allocated(lgr_ar(i)%custom) ) then
	    ival(4) = ival(4) + 1
	    if( ival(4) == 1 ) then
	      info(5) = id
	      info(6) = ie
	    end if
	  end if
	  if( lgr_marked(i) /= 0 ) then
	    ival(5) = ival(5) + 1
	    if( ival(5) == 1 ) then
	      info(8) = id
	      info(9) = lgr_marked(i)
	    end if
	  end if
	end do
	info(1:3) = ival(1:3)
	info(4) = ival(4)
	info(7) = ival(5)
	info(12) = idbdy

	call MPI_Allreduce(ival,ivalg,nv,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_check_consistency: MPI_Allreduce')
	call MPI_Allreduce(imx,imxg,2,MPI_INTEGER,MPI_MAX			&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_check_consistency: MPI_Allreduce')
	idbmax = imxg(1)
	idbmin = -imxg(2)

	!-----------------------------------------------
	! (c) slots per id, summed over the processes
	!-----------------------------------------------

	nid = max(idbmax,1)		!the same on every process
	allocate(icnt(nid+1), icntg(nid+1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_check_consistency: allocation')
	icnt = 0
	do i = 1, nbdy
	  id = lgr_ar(i)%id
	  if( id >= 1 .and. id <= nid ) then
	    icnt(id) = icnt(id) + 1
	  else				!never given out
	    icnt(nid+1) = icnt(nid+1) + 1
	    if( icnt(nid+1) == 1 ) info(11) = id
	  end if
	end do
	info(10) = icnt(nid+1)
	call MPI_Allreduce(icnt,icntg,nid+1,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_check_consistency: MPI_Allreduce')
	nout = icntg(nid+1)
	ndup = 0
	nl = 0
	ldup = 0
	do id = 1, nid
	  if( icntg(id) > 1 ) then
	    ndup = ndup + 1
	    if( nl < ndl ) then
	      nl = nl + 1
	      ldup(nl) = id
	    end if
	  end if
	end do

	!-----------------------------------------------
	! decisions on reduced values only
	!-----------------------------------------------

	nheld = ivalg(1) + ivalg(2) + ivalg(3)
	bfa = ( nheld /= idbmax .or. idbmin /= idbmax )
	bfb1 = ( ivalg(4) > 0 )
	bfb2 = ( ivalg(5) > 0 )
	bfc1 = ( ndup > 0 )
	bfc2 = ( nout > 0 )

	if( .not. ( bfa .or. bfb1 .or. bfb2 .or. bfc1 .or. bfc2 ) ) then
	  deallocate(icnt,icntg)
	  return
	end if

	!-----------------------------------------------
	! a check failed: gather the details to rank 0, write, abort
	!-----------------------------------------------

	cdup = 0
	do i = 1, nbdy
	  id = lgr_ar(i)%id
	  do k = 1, nl
	    if( id == ldup(k) ) cdup(k) = cdup(k) + 1
	  end do
	end do

	allocate(infog(ninf,0:n_threads-1), cdupg(ndl,0:n_threads-1)	&
     &		, stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_check_consistency: allocation')
	call MPI_Gather(info,ninf,MPI_INTEGER,infog,ninf,MPI_INTEGER	&
     &			,0,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_check_consistency: MPI_Gather')
	call MPI_Gather(cdup,ndl,MPI_INTEGER,cdupg,ndl,MPI_INTEGER		&
     &			,0,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_check_consistency: MPI_Gather')

	if( my_id == 0 ) then
	  if( bfa ) then
	    write(6,'(a,f0.1,a,i0,a,i0,a,i0,a,i0,a,i0)')			&
     &		' lgr_mpi_check_consistency: particle count: time ',dtime	&
     &		,', released (ids given out) ',idbmax,', held ',nheld	&
     &		,' = in the domain ',ivalg(1),' + left ',ivalg(2)		&
     &		,' + without an element ',ivalg(3)
	    if( idbmin /= idbmax ) then
	      write(6,'(a,i0,a,i0)') ' lgr_mpi_check_consistency: particle'	&
     &		//' count: the ids given out differ between the processes: '	&
     &		,idbmin,' to ',idbmax
	    end if
	    do r = 0, n_threads-1
	      write(6,'(a,i0,a,i0,a,i0,a,i0,a,i0)') ' lgr_mpi_check_consistency:'	&
     &		//' particle count: process ',r,': in the domain '		&
     &		,infog(1,r),', left ',infog(2,r),', without an element '	&
     &		,infog(3,r),', ids given out ',infog(12,r)
	    end do
	  end if
	  if( bfb1 ) then
	    write(6,'(a,f0.1,a,i0,a)') ' lgr_mpi_check_consistency: particle'	&
     &		//' in an element not held: time ',dtime,', ',ivalg(4)	&
     &		,' particles in the domain beyond the held elements or in'	&
     &		//' slots without a particle record'
	    do r = 0, n_threads-1
	      if( infog(4,r) == 0 ) cycle
	      write(6,'(a,i0,a,i0,a,i0,a,i0)') ' lgr_mpi_check_consistency:'	&
     &		//' particle in an element not held: process ',r,': '	&
     &		,infog(4,r),', the first id ',infog(5,r),' element '	&
     &		,infog(6,r)
	    end do
	  end if
	  if( bfb2 ) then
	    write(6,'(a,f0.1,a,i0,a)') ' lgr_mpi_check_consistency: mark'	&
     &		//' left after the hand-over: time ',dtime,', ',ivalg(5)	&
     &		,' slots'
	    do r = 0, n_threads-1
	      if( infog(7,r) == 0 ) cycle
	      write(6,'(a,i0,a,i0,a,i0,a,i0)') ' lgr_mpi_check_consistency:'	&
     &		//' mark left after the hand-over: process ',r,': '		&
     &		,infog(7,r),', the first id ',infog(8,r),' mark ',infog(9,r)
	    end do
	  end if
	  if( bfc1 ) then
	    write(6,'(a,f0.1,a,i0,a,i0,a)') ' lgr_mpi_check_consistency:'	&
     &		//' duplicate id: time ',dtime,', ',ndup,' ids occur more'	&
     &		//' than once (the first ',nl,' listed)'
	    do k = 1, nl
	      line = ' '
	      do r = 0, n_threads-1
	        do n = 1, cdupg(k,r)
	          write(buf,'(1x,i0)') r
	          line = trim(line)//trim(buf)
	        end do
	      end do
	      write(6,'(a,i0,a,a)') ' lgr_mpi_check_consistency: duplicate'	&
     &		//' id ',ldup(k),' on processes',trim(line)
	    end do
	  end if
	  if( bfc2 ) then
	    write(6,'(a,f0.1,a,i0,a,i0,a)') ' lgr_mpi_check_consistency: id'	&
     &		//' out of range: time ',dtime,', ',nout,' particles with'	&
     &		//' an id below 1 or above the ids given out (',idbmax,')'
	    do r = 0, n_threads-1
	      if( infog(10,r) == 0 ) cycle
	      write(6,'(a,i0,a,i0,a,i0)') ' lgr_mpi_check_consistency: id'	&
     &		//' out of range: process ',r,': ',infog(10,r)		&
     &		,', the first id ',infog(11,r)
	    end do
	  end if
	  flush(6)
	end if

	call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written
	call shympi_abort_internal('error stop lgr_mpi_check_consistency:'	&
     &		//' the particle state is inconsistent')

	end subroutine lgr_mpi_check_consistency

!*******************************************************************

	subroutine lgr_mpi_resolve(npos)

! resolution by position of the parked particles (lgr_mpi_park), on every
! process (collective, also with nothing parked on this process); called
! by lgr_mpi_handover_round when some process has parked particles:
! 1. the own list is sorted by slot (the threads fill it in the order
!    they arrive); each parked particle offers its new point (x, y, the
!    single precision values of its step), the global number of its old
!    element (ip_int_elem), its layer and its phase; all offers go to all
!    processes (MPI_Allgather of the counts, MPI_Allgatherv)
! 2. every process tests every offered point against the elements it is
!    the main owner of (id_elem(1,ie) == my_id: every element of the mesh
!    on exactly one process), with in_element as a serial search does,
!    and keeps the element with the smallest search key
!    (lgr_mpi_search_key, global numbers, wrap-around at nel_global) and
!    its number of layers. A point outside the bounding box of the owned
!    elements is in none of them (in_element tests the box of an element
!    first), so those are not tested.
! 3. the smallest key over all processes and the process that has it
!    (MPI_MINLOC on the keys), then that process's element and layer
!    count (MPI_MAX over values only it sets): the element a serial
!    search returns (find_elem_from_old, P1 of the plan); no key at all:
!    no element of the mesh contains the point
! 4. the asking process decides for each own parked particle, in slot
!    order: nobody answered: it stays, lgr_park_ie = 0 (the fallback runs
!    when it is resumed); in the diffusion step an element with fewer
!    layers than the particle's layer: it stays unmoved, lgr_park_ie = -1
!    (the layer test of lag_diff_hor_end, with the layer count of the
!    answer); otherwise, if this process holds the element: it stays,
!    lgr_park_ie = the local element; if not: it goes to the process that
!    answered (pos_idx, pos_dest, pos_elem; npos of them, in slot order).
!    Those that stay get the mark 4 or 5 (resolved), those that go keep
!    2 or 3 until they are sent. The list of parked particles is emptied.
! Each offer is decided by its own reductions, so the result does not
! depend on the order of the offers. The counts of lgr_mpi_relocate_stats
! are kept here.

	use shympi
	use basin, only : nel, nkn, nen3v, xgv, ygv
	use levels, only : ilhv

	implicit none

	include 'mpif.h'

	integer, intent(out) :: npos		!particles that go elsewhere

	integer, parameter :: noff = 5		!values of an offer
	integer :: knone			!no element: no key
	integer :: nproc, nown, ntot, j, jj, i, ie, ii, k, kb, ieb, nlb
	integer :: io, ierr, iclass, phase, lb, iw, iel, joff, r
	integer :: ncnt(0:n_threads-1), idsp(0:n_threads-1)
	integer :: ncntd(0:n_threads-1), idspd(0:n_threads-1)
	integer, allocatable :: key(:), iord(:), kl(:,:), klg(:,:)
	integer, allocatable :: ians(:,:), iansg(:,:)
	double precision, allocatable :: obuf(:), abuf(:)
	double precision :: t0
	real :: xp, yp, gloc(2), gglob(2)
	logical :: in_element
	logical, save :: binit = .false.
	logical, save :: bown = .false.		!this process owns an element
	real, save :: bx(4)			!box of the owned elements
	real, save :: gx(4)			!box of the mesh
	! boxes: xmin, xmax, ymin, ymax

	t0 = MPI_Wtime()
	nproc = n_threads
	knone = huge(knone)

	!-----------------------------------------------
	! boxes of the owned elements and of the mesh (once, collective)
	!-----------------------------------------------

	if( .not. binit ) then
	  binit = .true.
	  bx = (/ huge(1.), -huge(1.), huge(1.), -huge(1.) /)
	  do ie = 1, nel
	    if( id_elem(1,ie) /= my_id ) cycle
	    bown = .true.
	    do ii = 1, 3
	      k = nen3v(ii,ie)
	      bx(1) = min(bx(1),xgv(k))
	      bx(2) = max(bx(2),xgv(k))
	      bx(3) = min(bx(3),ygv(k))
	      bx(4) = max(bx(4),ygv(k))
	    end do
	  end do
	  gloc(1) = minval(xgv(1:nkn))
	  gloc(2) = minval(ygv(1:nkn))
	  call MPI_Allreduce(gloc,gglob,2,MPI_REAL,MPI_MIN		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allreduce')
	  gx(1) = gglob(1)
	  gx(3) = gglob(2)
	  gloc(1) = maxval(xgv(1:nkn))
	  gloc(2) = maxval(ygv(1:nkn))
	  call MPI_Allreduce(gloc,gglob,2,MPI_REAL,MPI_MAX		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allreduce')
	  gx(2) = gglob(1)
	  gx(4) = gglob(2)
	end if

	!-----------------------------------------------
	! 1. own offers in slot order, all offers to all processes
	!-----------------------------------------------

	nown = n_park

	allocate(key(max(nown,1)), iord(max(nown,1))			&
     &		, obuf(max(noff*nown,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_resolve: allocation')

	do j = 1, nown
	  key(j) = park_idx(j)
	  iord(j) = j
	end do
	call lgr_mpi_sort_by_key(nown,key,iord)
	do j = 2, nown
	  if( key(j) == key(j-1) ) then
	    write(6,*) 'lgr_mpi_resolve: slot parked twice: ',key(j)
	    call shympi_abort_internal('lgr_mpi_resolve: slot parked twice')
	  end if
	end do

	do jj = 1, nown
	  i = key(jj)
	  ie = lgr_ar(i)%actual%ie
	  if( ie < 1 .or. ie > nel ) then
	    write(6,*) 'lgr_mpi_resolve: rank,i,ie,mark: ',my_id,i,ie	&
     &		,lgr_marked(i)
	    call shympi_abort_internal('lgr_mpi_resolve: old element')
	  end if
	  if( lgr_marked(i) /= 2 .and. lgr_marked(i) /= 3 ) then
	    write(6,*) 'lgr_mpi_resolve: rank,i,mark: ',my_id,i,lgr_marked(i)
	    call shympi_abort_internal('lgr_mpi_resolve: not parked')
	  end if
	  obuf(noff*(jj-1)+1) = dble(lgr_park_xy(3,i))	!new x
	  obuf(noff*(jj-1)+2) = dble(lgr_park_xy(4,i))	!new y
	  obuf(noff*(jj-1)+3) = dble(ip_int_elem(ie))	!old element
	  obuf(noff*(jj-1)+4) = dble(lgr_ar(i)%actual%l)	!layer
	  obuf(noff*(jj-1)+5) = dble(lgr_marked(i)-1)		!phase
	end do

	call MPI_Allgather(nown,1,MPI_INTEGER,ncnt,1,MPI_INTEGER		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allgather')
	idsp(0) = 0
	do r = 1, nproc-1
	  idsp(r) = idsp(r-1) + ncnt(r-1)
	end do
	ntot = idsp(nproc-1) + ncnt(nproc-1)
	ncntd = noff*ncnt
	idspd = noff*idsp

	allocate(abuf(max(noff*ntot,1)), kl(2,max(ntot,1))		&
     &		, klg(2,max(ntot,1)), ians(2,max(ntot,1))			&
     &		, iansg(2,max(ntot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_resolve: allocation')

	call MPI_Allgatherv(obuf,noff*nown,MPI_DOUBLE_PRECISION		&
     &		,abuf,ncntd,idspd,MPI_DOUBLE_PRECISION,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allgatherv')

	!-----------------------------------------------
	! 2. every offered point against the owned elements
	!-----------------------------------------------

	do j = 1, ntot
	  xp = real(abuf(noff*(j-1)+1))
	  yp = real(abuf(noff*(j-1)+2))
	  io = nint(abuf(noff*(j-1)+3))
	  kb = knone
	  ieb = 0
	  nlb = 0
	  if( bown ) then
	    if( xp >= bx(1) .and. xp <= bx(2) ) then
	      if( yp >= bx(3) .and. yp <= bx(4) ) then
	        do ie = 1, nel
	          if( id_elem(1,ie) /= my_id ) cycle
	          if( in_element(ie,xp,yp) ) then
	            k = lgr_mpi_search_key(ip_int_elem(ie),io,nel_global)
	            if( k < kb ) then
	              kb = k
	              ieb = ip_int_elem(ie)
	              nlb = ilhv(ie)
	            end if
	          end if
	        end do
	      end if
	    end if
	  end if
	  kl(1,j) = kb
	  kl(2,j) = my_id
	  ians(1,j) = ieb
	  ians(2,j) = nlb
	end do

	!-----------------------------------------------
	! 3. the smallest key, then its element and layer count
	!-----------------------------------------------

	if( ntot > 0 ) then
	  call MPI_Allreduce(kl,klg,ntot,MPI_2INTEGER,MPI_MINLOC		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allreduce')
	  do j = 1, ntot
	    if( klg(1,j) == knone .or. klg(2,j) /= my_id ) then
	      ians(1,j) = 0
	      ians(2,j) = 0
	    end if
	  end do
	  call MPI_Allreduce(ians,iansg,2*ntot,MPI_INTEGER,MPI_MAX		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_resolve: MPI_Allreduce')
	end if

	!-----------------------------------------------
	! 4. decisions for the own parked particles, in slot order
	!-----------------------------------------------

	if( allocated(pos_idx) ) deallocate(pos_idx,pos_dest,pos_elem)
	allocate(pos_idx(max(nown,1)), pos_dest(max(nown,1))		&
     &		, pos_elem(max(nown,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_resolve: allocation')

	npos = 0
	do jj = 1, nown
	  i = key(jj)
	  iclass = park_class(iord(jj))
	  joff = idsp(my_id) + jj
	  phase = lgr_marked(i) - 1
	  lb = lgr_ar(i)%actual%l
	  lgr_npark_ph(phase) = lgr_npark_ph(phase) + 1
	  lgr_npark_cl(iclass) = lgr_npark_cl(iclass) + 1
	  xp = lgr_park_xy(3,i)
	  yp = lgr_park_xy(4,i)
	  if( xp < gx(1) .or. xp > gx(2) .or. yp < gx(3) .or. yp > gx(4) ) then
	    lgr_nres_outbox = lgr_nres_outbox + 1
	  end if
	  if( klg(1,joff) == knone ) then	!no element contains the point
	    lgr_park_ie(i) = 0
	    lgr_marked(i) = lgr_marked(i) + 2
	    lgr_nres_none = lgr_nres_none + 1
	    if( iclass == 3 ) lgr_nres_hitnone = lgr_nres_hitnone + 1
	    cycle
	  end if
	  iw = iansg(1,joff)
	  if( iw < 1 .or. iw > nel_global ) then
	    write(6,*) 'lgr_mpi_resolve: rank,i,element: ',my_id,i,iw
	    call shympi_abort_internal('lgr_mpi_resolve: element found')
	  end if
	  if( phase == 1 .and. iansg(2,joff) < lb ) then  !lacks the layer
	    lgr_park_ie(i) = -1
	    lgr_marked(i) = lgr_marked(i) + 2
	    lgr_nres_layer = lgr_nres_layer + 1
	    cycle
	  end if
	  iel = lgr_mpi_find_elem(iw)
	  if( iel > 0 ) then			!held here: stays
	    lgr_park_ie(i) = iel
	    lgr_marked(i) = lgr_marked(i) + 2
	    lgr_nres_stay = lgr_nres_stay + 1
	  else					!goes to the process that answered
	    npos = npos + 1
	    pos_idx(npos) = i
	    pos_dest(npos) = klg(2,joff)
	    pos_elem(npos) = iw
	    lgr_nres_sent = lgr_nres_sent + 1
	  end if
	end do

	n_park = 0
	lgr_nres_round = lgr_nres_round + 1

	deallocate(key,iord,obuf,abuf,kl,klg,ians,iansg)

	lgr_tres = lgr_tres + (MPI_Wtime() - t0)

	end subroutine lgr_mpi_resolve

!*******************************************************************

	subroutine lgr_mpi_relocate_step

! at levdbg >= 3, after the hand-over of every particle step (called by
! lagrange, serial too): in a serial run the re-locations of classes 3
! and 4 (lgr_mpi_relocate_check) in this step, what one process of
! several would park, and their largest number in one step so far. On
! several processes lgr_mpi_handover keeps the largest number of
! particles parked in one step itself (all processes, all rounds).

	implicit none

	integer :: n

	if( .not. blgr_dbg .or. bmpi_lagr ) return

	n = lgr_nreloc(3) + lgr_nreloc(4)
	lgr_npark_step_max = max(lgr_npark_step_max,n-lgr_nreloc34_prev)
	lgr_nreloc34_prev = n

	end subroutine lgr_mpi_relocate_step

!*******************************************************************

	subroutine lgr_mpi_relocate_stats

! at levdbg >= 3, once (the first call; every process makes the same
! calls, so all take part in the same reductions): rank 0 writes the
! counts of the element search at the end of the horizontal diffusion
! step and of the Stokes drift step, summed over all processes:
!  " lgr relocation classes: in the old element N1, hit clear of the
!    margin N2, hit within the margin N3, failed search N4, most of
!    classes 3 and 4 in one step M" (on several processes M is the most
!    particles parked in one step, and the line goes on with
!    ", resolution rounds R, resolution time T s, parked outside the
!    mesh box O": T the largest over the processes, O the parked points
!    outside the bounding box of the whole mesh)
!  in a serial run: " lgr relocation self-check: compared N, differing
!    D, clear hits in a second element C, points in two or more elements
!    M, key order walks W, wrong K" (lgr_mpi_relocate_check; D and C
!    must be 0; M says how many of the N tested the order of the key;
!    W, K: lgr_mpi_selftest_key on rank 0, K must be 0)
!  on several processes: " lgr relocation by position: parked N
!    (diffusion Nd, Stokes Ns; hit within the margin Nh, failed search
!    Nf), stayed S, kept for lack of a layer L, went to another process
!    G, nobody answered A, hit within the margin and nobody answered Z,
!    key order walks W, wrong K" (lgr_mpi_resolve; Z must be 0 and
!    S + L + G + A = N; W, K as in the serial line, K must be 0)
! check_lgr_mpi.sh reads the last two lines. A self-check never stops
! the run. Called by lagrange after the step that reaches the end of the
! particle run and at the first call after it.

	use shympi, only : my_id, n_threads

	implicit none

	include 'mpif.h'

	integer, parameter :: nv = 20
	integer :: ival(nv), ivalg(nv), ierr
	double precision :: tmax
	character(len=600) :: line
	character(len=12) :: tbuf
	logical, save :: bdone = .false.

	if( .not. blgr_dbg ) return
	if( bdone ) return
	bdone = .true.

	ival(1:4) = lgr_nreloc(1:4)
	ival(5) = lgr_nchk_comp
	ival(6) = lgr_nchk_diff
	ival(7) = lgr_nchk_clear2
	ival(8:9) = lgr_npark_ph(1:2)
	ival(10:11) = lgr_npark_cl(3:4)
	ival(12) = lgr_nres_stay
	ival(13) = lgr_nres_layer
	ival(14) = lgr_nres_sent
	ival(15) = lgr_nres_none
	ival(16) = lgr_nres_hitnone
	ival(17) = lgr_nres_outbox
	ival(18) = lgr_nchk_multi
	ival(19) = lgr_npark_step_max		!the same on every process
	ival(20) = lgr_nres_round		!the same on every process
	tmax = lgr_tres

	if( n_threads > 1 ) then
	  call MPI_Allreduce(ival,ivalg,18,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_relocate_stats: MPI_Allreduce')
	  ivalg(19:20) = ival(19:20)
	  call MPI_Allreduce(lgr_tres,tmax,1,MPI_DOUBLE_PRECISION,MPI_MAX	&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_relocate_stats: MPI_Allreduce')
	else
	  ivalg = ival
	end if

	if( my_id /= 0 ) return

	line = ' lgr relocation classes: in the old element '//itoa(ivalg(1))	&
     &		//', hit clear of the margin '//itoa(ivalg(2))		&
     &		//', hit within the margin '//itoa(ivalg(3))		&
     &		//', failed search '//itoa(ivalg(4))			&
     &		//', most of classes 3 and 4 in one step '//itoa(ivalg(19))
	if( n_threads > 1 ) then
	  write(tbuf,'(f12.3)') tmax
	  write(6,'(a)') trim(line)//', resolution rounds '//itoa(ivalg(20))	&
     &		//', resolution time '//trim(adjustl(tbuf))			&
     &		//' s, parked outside the mesh box '//itoa(ivalg(17))
	  write(6,'(a)') ' lgr relocation by position: parked '		&
     &		//itoa(ivalg(8)+ivalg(9))					&
     &		//' (diffusion '//itoa(ivalg(8))//', Stokes '//itoa(ivalg(9))	&
     &		//'; hit within the margin '//itoa(ivalg(10))		&
     &		//', failed search '//itoa(ivalg(11))//'), stayed '		&
     &		//itoa(ivalg(12))//', kept for lack of a layer '		&
     &		//itoa(ivalg(13))//', went to another process '		&
     &		//itoa(ivalg(14))//', nobody answered '//itoa(ivalg(15))	&
     &		//', hit within the margin and nobody answered '		&
     &		//itoa(ivalg(16))//', key order walks '//itoa(lgr_nkey_walk)	&
     &		//', wrong '//itoa(lgr_nkey_wrong)
	else
	  write(6,'(a)') trim(line)
	  write(6,'(a)') ' lgr relocation self-check: compared '		&
     &		//itoa(ivalg(5))//', differing '//itoa(ivalg(6))		&
     &		//', clear hits in a second element '//itoa(ivalg(7))		&
     &		//', points in two or more elements '//itoa(ivalg(18))	&
     &		//', key order walks '//itoa(lgr_nkey_walk)			&
     &		//', wrong '//itoa(lgr_nkey_wrong)
	end if
	flush(6)

	contains

	  function itoa(n) result(s)
	  integer, intent(in) :: n
	  character(len=:), allocatable :: s
	  character(len=12) :: buf
	  integer :: ierr
	  write(buf,'(i0)') n
	  !explicit allocation: the build has -fno-realloc-lhs
	  allocate(character(len=len_trim(buf)) :: s, stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_relocate_stats: allocation')
	  s = buf(1:len_trim(buf))
	  end function itoa

	end subroutine lgr_mpi_relocate_stats

!*******************************************************************

	subroutine lgr_mpi_output(iu, dtime)

! particle file on several processes; collective: every process calls it
! at every output time of the particle file (lagrange), also a process
! without a particle. Rank 0 writes at dtime the three blocks of
! lgr_output (active iwhat = 0, inserted -1, exited 1), each a header
! (dtime, n, iwhat) and per particle the three records lgr_output writes
! in a serial run, in the order of the ids: the order of a serial run,
! whose slots hold the particles in the order of their ids (appended,
! never removed). The other processes write nothing; they do not use iu
! (the file is opened by rank 0 only, iu is not connected elsewhere).
!
! What each process contributes (lgr_output_record, lgr_output_fill):
!   active   its particles with actual%ie > 0
!   exited   its particles with actual%ie <= 0 (a particle that left
!            stays on the process it left from, which holds that element)
!   inserted the particles it released since the last output, from its
!            release records (rel_id, rel_body; lgr_mpi_keep_release):
!            x, y from the release coordinates in the release element,
!            hl from that element's layers at dtime, as a serial run does.
!            The particle may be on another process by now, so the type,
!            the sinking and custom(1) (in every custom slot, as serial)
!            of the particle at dtime, which a serial run writes here,
!            are taken on rank 0 from the particle's own active or exited
!            record
! The element written is the global one (ip_int_elem, lgr_output_fill).
! The inserted block comes only from the release records, never from
! the sign of init%ie: a particle is listed once, by the process that
! released it, and the list is cleared at every output.
!
! If no process holds a particle nothing is written (as lgr_output with
! nbdy = 0); the processes decide together from the gathered counts.
!
! The run stops instead of writing a wrong file if
!   - the global number of particles differs from the number of release
!     records taken (lgr_nrel_total): particles were released by a
!     release that does not pass lgr_mpi_assign_ids (continuous release,
!     lgrtrj, lgrini; not supported on several processes), or removed
!   - on rank 0: an id occurs twice among the active and exited records,
!     or an inserted id occurs twice or is in neither block
!
! Memory: rank 0 holds the gathered records of the three blocks at once,
! lgr_orec_base+ncust double precision values per record (88 bytes with
! ncust = 1): at an output right after the release of all n particles of
! a run, 2 n records (2 x 88 bytes x n, 35 MB for n = 200,001), plus its
! own records and two integers per gathered record for the ordering

	use shympi, only : my_id, n_threads

	implicit none

	include 'mpif.h'

	integer, intent(in) :: iu
	double precision, intent(in) :: dtime

	integer, parameter :: nval = 5	!per process: active, exited,
					!inserted, particles, records taken
	integer :: ival(nval), ntot(nval)
	integer :: nrec, ip, k, ka, ke, ierr, nbad, iwhat
	integer :: na, ne, ni		!records of this process
	integer :: nga, nge, ngi	!records of all processes
	integer :: ndup, nboth, nmiss
	integer, allocatable :: iall(:,:)
	integer, allocatable :: keya(:), keye(:), keyi(:)
	integer, allocatable :: idxa(:), idxe(:), idxi(:)
	double precision, allocatable :: rec(:)
	double precision, allocatable :: bufa(:), bufe(:), bufi(:)
	double precision, allocatable :: ga(:), ge(:), gi(:)
	real :: c(ncust)

	nrec = lgr_orec_base + ncust

!	--------------------------------------------
!	counts of all processes
!	--------------------------------------------

	na = 0
	ne = 0
	do ip=1,nbdy
	  if( lgr_ar(ip)%actual%ie > 0 ) then
	    na = na + 1
	  else
	    ne = ne + 1
	  end if
	end do
	ni = n_rel

	ival = (/ na, ne, ni, nbdy, lgr_nrel_total /)
	allocate(iall(nval,n_threads), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_output: allocation')
	call MPI_Allgather(ival,nval,MPI_INTEGER,iall,nval,MPI_INTEGER	&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_output: MPI_Allgather')
	ntot = sum(iall,dim=2)

	if( ntot(4) /= ntot(5) ) then
	  if( my_id == 0 ) then
	    write(6,*) 'lgr_mpi_output: particles ',ntot(4)		&
     &		,', release records taken ',ntot(5)
	    write(6,*) 'particles were released (or removed) by an option'	&
     &		//' that is not supported on several MPI processes'	&
     &		//' (continuous release, lgrtrj, lgrini)'
	    flush(6)
	  end if
	  call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written
	  call shympi_abort_internal('lgr_mpi_output: particles without'	&
     &		//' a release record')
	end if

	if( ntot(4) == 0 ) then		!no particle anywhere: no output
	  n_rel = 0
	  deallocate(iall)
	  return
	end if

!	--------------------------------------------
!	records of this process
!	--------------------------------------------

	allocate(rec(nrec), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_output: allocation')
	allocate(bufa(max(na*nrec,1)), bufe(max(ne*nrec,1))		&
     &		, bufi(max(ni*nrec,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_output: allocation')

	ka = 0
	ke = 0
	do ip=1,nbdy
	  if( lgr_ar(ip)%actual%ie > 0 ) then
	    call lgr_output_record(ip,0,rec)
	    bufa(ka*nrec+1:(ka+1)*nrec) = rec
	    ka = ka + 1
	  else
	    call lgr_output_record(ip,1,rec)
	    bufe(ke*nrec+1:(ke+1)*nrec) = rec
	    ke = ke + 1
	  end if
	end do

	c = 0.		!type, sinking, custom values: set on rank 0
	do k=1,ni
	  call lgr_output_fill(rel_body(k)%ie,rel_body(k)%xi		&
     &		,rel_body(k)%z,rel_body(k)%l,rel_body(k)%time,rel_id(k)	&
     &		,0,0.,c,rec)
	  bufi((k-1)*nrec+1:k*nrec) = rec
	end do

!	--------------------------------------------
!	all records on rank 0
!	--------------------------------------------

	call lgr_mpi_gather_records(na,nrec,bufa,iall(1,:),ntot(1),ga)
	call lgr_mpi_gather_records(ne,nrec,bufe,iall(2,:),ntot(2),ge)
	call lgr_mpi_gather_records(ni,nrec,bufi,iall(3,:),ntot(3),gi)
	n_rel = 0			!written below, on rank 0

!	--------------------------------------------
!	rank 0: order by id, checks, inserted records completed
!	--------------------------------------------

	nga = ntot(1)
	nge = ntot(2)
	ngi = ntot(3)
	nbad = 0
	if( my_id == 0 ) then
	  allocate(keya(max(nga,1)), idxa(max(nga,1)), keye(max(nge,1))	&
     &		, idxe(max(nge,1)), keyi(max(ngi,1)), idxi(max(ngi,1))	&
     &		, stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_output: allocation')
	  call order_by_id(nga,ga,keya,idxa)
	  call order_by_id(nge,ge,keye,idxe)
	  call order_by_id(ngi,gi,keyi,idxi)

	  ndup = count_dup(nga,keya) + count_dup(nge,keye)		&
     &		+ count_dup(ngi,keyi)
	  nboth = 0
	  do k=1,nge
	    if( lgr_mpi_bisect(nga,keya,keye(k)) > 0 ) nboth = nboth + 1
	  end do
	  nmiss = 0
	  do k=1,ngi
	    ip = lgr_mpi_bisect(nga,keya,keyi(k))
	    if( ip > 0 ) then
	      call complete_inserted(idxi(k),ga,idxa(ip))
	    else
	      ip = lgr_mpi_bisect(nge,keye,keyi(k))
	      if( ip > 0 ) then
	        call complete_inserted(idxi(k),ge,idxe(ip))
	      else
	        nmiss = nmiss + 1
	      end if
	    end if
	  end do

	  nbad = ndup + nboth + nmiss
	  if( nbad > 0 ) then
	    write(6,*) 'lgr_mpi_output: ids twice in a block ',ndup	&
     &		,', ids both active and exited ',nboth			&
     &		,', inserted ids in neither block ',nmiss
	    flush(6)
	  end if
	end if

	call MPI_Bcast(nbad,1,MPI_INTEGER,0,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_output: MPI_Bcast')
	if( nbad > 0 ) call shympi_abort_internal('lgr_mpi_output: the'	&
     &		//' particle records of the processes are inconsistent')

!	--------------------------------------------
!	rank 0: the three blocks as lgr_output writes them
!	--------------------------------------------

	if( my_id == 0 ) then
	  iwhat = 0
	  write(iu) dtime,nga,iwhat
	  do k=1,nga
	    rec = ga((idxa(k)-1)*nrec+1:idxa(k)*nrec)
	    call lgr_output_write(iu,rec)
	  end do
	  iwhat = -1
	  write(iu) dtime,ngi,iwhat
	  do k=1,ngi
	    rec = gi((idxi(k)-1)*nrec+1:idxi(k)*nrec)
	    call lgr_output_write(iu,rec)
	  end do
	  iwhat = 1
	  write(iu) dtime,nge,iwhat
	  do k=1,nge
	    rec = ge((idxe(k)-1)*nrec+1:idxe(k)*nrec)
	    call lgr_output_write(iu,rec)
	  end do
	  deallocate(keya,idxa,keye,idxe,keyi,idxi)
	end if

	deallocate(iall,rec,bufa,bufe,bufi,ga,ge,gi)

	contains

!	--------------------------------------------

	  subroutine order_by_id(n,g,key,idx)
	  ! idx(1:n): the records of g in the order of their ids key(1:n)
	  integer, intent(in) :: n
	  double precision, intent(in) :: g(:)
	  integer, intent(out) :: key(:)
	  integer, intent(out) :: idx(:)
	  integer :: j
	  do j=1,n
	    key(j) = nint(g((j-1)*nrec+1))
	    idx(j) = j
	  end do
	  call lgr_mpi_sort_by_key(n,key,idx)
	  end subroutine order_by_id

	  function count_dup(n,key)
	  ! ids that follow an equal id in the ordered key(1:n)
	  integer :: count_dup
	  integer, intent(in) :: n
	  integer, intent(in) :: key(:)
	  integer :: j
	  count_dup = 0
	  do j=2,n
	    if( key(j) == key(j-1) ) count_dup = count_dup + 1
	  end do
	  end function count_dup

	  subroutine complete_inserted(jins,g,jsrc)
	  ! type, sinking and custom(1) in every custom slot of inserted
	  ! record jins of gi from record jsrc of g (the particle's active
	  ! or exited record at this output)
	  integer, intent(in) :: jins
	  double precision, intent(in) :: g(:)
	  integer, intent(in) :: jsrc
	  integer :: oi, os
	  oi = (jins-1)*nrec
	  os = (jsrc-1)*nrec
	  gi(oi+2) = g(os+2)
	  gi(oi+4) = g(os+4)
	  gi(oi+lgr_orec_base+1:oi+nrec) = g(os+lgr_orec_base+1)
	  end subroutine complete_inserted

	end subroutine lgr_mpi_output

!*******************************************************************

	subroutine lgr_mpi_gather_records(n,nrec,buf,counts,nglob,g)

! gathers on rank 0 the records of all processes (collective): this
! process gives buf(1:n*nrec) (n records of nrec values), counts(1:nproc)
! are the numbers of records of all processes (rank r in counts(r+1)),
! nglob their sum. On rank 0, g(1:nglob*nrec) holds the records in rank
! order; g is allocated here, with size 1 on the other processes and for
! no record.

	use shympi, only : my_id, n_threads

	implicit none

	include 'mpif.h'

	integer, intent(in) :: n
	integer, intent(in) :: nrec
	double precision, intent(in) :: buf(:)
	integer, intent(in) :: counts(:)
	integer, intent(in) :: nglob
	double precision, allocatable, intent(out) :: g(:)

	integer :: ir, ierr
	integer, allocatable :: icnt(:), idsp(:)

	allocate(icnt(n_threads), idsp(n_threads), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_records: allocation')
	do ir=1,n_threads
	  icnt(ir) = counts(ir) * nrec
	end do
	idsp(1) = 0
	do ir=2,n_threads
	  idsp(ir) = idsp(ir-1) + icnt(ir-1)
	end do

	if( my_id == 0 ) then
	  allocate(g(max(nglob*nrec,1)), stat=ierr)
	else
	  allocate(g(1), stat=ierr)
	end if
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_records: allocation')

	call MPI_Gatherv(buf,n*nrec,MPI_DOUBLE_PRECISION			&
     &		,g,icnt,idsp,MPI_DOUBLE_PRECISION				&
     &		,0,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_gather_records: MPI_Gatherv')

	deallocate(icnt,idsp)

	end subroutine lgr_mpi_gather_records

!*******************************************************************

	subroutine lgr_mpi_reduce_connect

! sum connectivity matrices across all ranks

	use shympi
	use connectivity

	implicit none

	include 'mpif.h'

	integer :: ierr, n2
	integer :: itmp(nconnect_dim,nconnect_dim)
	real :: rtmp(nconnect_dim,nconnect_dim)

	if( .not. bmpi_lagr ) return

	n2 = nconnect_dim * nconnect_dim

	call MPI_Allreduce(i_connect, itmp, n2,				&
     &		MPI_INTEGER, MPI_SUM, MPI_COMM_WORLD, ierr)
	i_connect = itmp

	call MPI_Allreduce(t_connect, rtmp, n2,				&
     &		MPI_REAL, MPI_SUM, MPI_COMM_WORLD, ierr)
	t_connect = rtmp

	end subroutine lgr_mpi_reduce_connect

!*******************************************************************

	subroutine lgr_mpi_global_count(nloc,nglob)

! the sum of nloc over all processes, returned on every process (drogue:
! the global number of particles for the info file); on several
! processes every process must call it; on one process nglob = nloc

	use shympi, only : shympi_is_parallel

	implicit none

	include 'mpif.h'

	integer, intent(in) :: nloc
	integer, intent(out) :: nglob

	integer :: ierr

	if( .not. shympi_is_parallel() ) then
	  nglob = nloc
	  return
	end if

	call MPI_Allreduce(nloc,nglob,1,MPI_INTEGER,MPI_SUM,		&
     &			MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_global_count: MPI_Allreduce')

	end subroutine lgr_mpi_global_count

!*******************************************************************

	subroutine lgr_mpi_gather_global(n,iglob,vloc,nglob,vglob,what)

! assembles on rank 0 the global array vglob(nglob) from the entries the
! ranks own: on every rank vloc(1:n) with the global numbers iglob(1:n).
! Every global number 1..nglob must come exactly once from all ranks
! together, otherwise the run is aborted (what names the array in the
! message). vglob is defined on rank 0 only (0 on the other ranks).

	use shympi, only : my_id,n_threads,shympi_max,shympi_gather

	implicit none

	integer, intent(in) :: n
	integer, intent(in) :: iglob(n)
	double precision, intent(in) :: vloc(n)
	integer, intent(in) :: nglob
	double precision, intent(out) :: vglob(nglob)
	character(len=*), intent(in) :: what

	integer :: nmax, ia, i, ip, ierr, nbad, nloc
	integer, allocatable :: counts(:), ibuf(:), idom(:,:), nset(:)
	double precision, allocatable :: vbuf(:), vdom(:,:)

	nloc = n
	nmax = max(shympi_max(nloc),1)	!same buffer length on every rank

	allocate(counts(n_threads), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_global: allocation')
	allocate(ibuf(nmax), vbuf(nmax), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_global: allocation')
	allocate(idom(nmax,n_threads), vdom(nmax,n_threads), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_global: allocation')

	ibuf = 0
	vbuf = 0.d0
	ibuf(1:n) = iglob(1:n)
	vbuf(1:n) = vloc(1:n)
	call shympi_gather(nloc,counts)
	call shympi_gather(ibuf,idom)
	call shympi_gather(vbuf,vdom)

	vglob = 0.d0
	if( my_id == 0 ) then
	  allocate(nset(nglob), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_gather_global: allocation')
	  nset = 0
	  nbad = 0
	  do ia=1,n_threads
	    do i=1,counts(ia)
	      ip = idom(i,ia)
	      if( ip < 1 .or. ip > nglob ) then
	        nbad = nbad + 1
	        cycle
	      end if
	      nset(ip) = nset(ip) + 1
	      vglob(ip) = vdom(i,ia)
	    end do
	  end do
	  nbad = nbad + count( nset /= 1 )
	  if( nbad > 0 ) then
	    write(6,*) 'lgr_mpi_gather_global: ',trim(what)		&
     &		,': entries out of range or not exactly once: ',nbad
	    call shympi_abort_internal('lgr_mpi_gather_global: '	&
     &		//trim(what))
	  end if
	  deallocate(nset)
	end if

	deallocate(counts,ibuf,vbuf,idom,vdom)

	end subroutine lgr_mpi_gather_global

!*******************************************************************

	subroutine lgr_mpi_global_area(area)

! total area of the basin, bit for bit as compute_total_area gives it in
! a serial run: the terms ev(10,ie) of the elements this rank is the
! main owner of are gathered to rank 0 and added there in the order of
! the global element numbers, with the kinds of compute_total_area
! (double precision sum, real result 12*sum); the result is broadcast.
! In a serial run it calls compute_total_area.

	use shympi, only : shympi_is_parallel,my_id,id_elem,ip_int_elem	&
     &			,nel_global,shympi_bcast
	use basin, only : nel
	use evgeom, only : ev

	implicit none

	real, intent(out) :: area

	integer :: ie, n, ierr
	integer, allocatable :: iglob(:)
	double precision, allocatable :: vloc(:), vglob(:)
	double precision :: a, tot_area
	real :: rbuf(1)

	if( .not. shympi_is_parallel() ) then
	  call compute_total_area(area)
	  return
	end if

	allocate(iglob(nel), vloc(nel), vglob(nel_global), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_global_area: allocation')

	n = 0
	do ie=1,nel
	  if( id_elem(1,ie) /= my_id ) cycle	!main owner only
	  n = n + 1
	  iglob(n) = ip_int_elem(ie)
	  vloc(n) = ev(10,ie)
	end do

	call lgr_mpi_gather_global(n,iglob,vloc,nel_global,vglob,'area')

	rbuf = 0.
	if( my_id == 0 ) then		!the loop of compute_total_area
	  tot_area = 0.
	  do ie=1,nel_global
	    a = vglob(ie)
	    tot_area = tot_area + a
	  end do
	  rbuf(1) = 12. * tot_area
	end if
	call shympi_bcast(rbuf)
	area = rbuf(1)

	deallocate(iglob,vloc,vglob)

	end subroutine lgr_mpi_global_area

!*******************************************************************

	subroutine lgr_mpi_global_center(x0,y0)

! centre of the basin, bit for bit as basin_center gives it in a serial
! run (xy_center over all nodes): the coordinates of the nodes this rank
! owns are gathered to rank 0, put in the order of the global node
! numbers and passed to xy_center there; the result is broadcast. The
! coordinates travel as double precision (real to double and back is
! exact). In a serial run it calls basin_center.

	use shympi, only : shympi_is_parallel,my_id,id_node,ip_int_node	&
     &			,nkn_global,shympi_bcast
	use basin, only : nkn,xgv,ygv

	implicit none

	real, intent(out) :: x0,y0

	integer :: k, n, ierr
	integer, allocatable :: iglob(:)
	double precision, allocatable :: xloc(:), yloc(:)
	double precision, allocatable :: xglob(:), yglob(:)
	real, allocatable :: xg(:), yg(:)
	real :: rbuf(2)

	if( .not. shympi_is_parallel() ) then
	  call basin_center(x0,y0)
	  return
	end if

	allocate(iglob(nkn), xloc(nkn), yloc(nkn), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_global_center: allocation')
	allocate(xglob(nkn_global), yglob(nkn_global), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_global_center: allocation')

	n = 0
	do k=1,nkn
	  if( id_node(k) /= my_id ) cycle	!own nodes only
	  n = n + 1
	  iglob(n) = ip_int_node(k)
	  xloc(n) = xgv(k)
	  yloc(n) = ygv(k)
	end do

	call lgr_mpi_gather_global(n,iglob,xloc,nkn_global,xglob	&
     &		,'center x')
	call lgr_mpi_gather_global(n,iglob,yloc,nkn_global,yglob	&
     &		,'center y')

	rbuf = 0.
	if( my_id == 0 ) then		!as basin_center
	  allocate(xg(nkn_global), yg(nkn_global), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_global_center: allocation')
	  xg = real(xglob)
	  yg = real(yglob)
	  call xy_center(nkn_global,xg,yg,rbuf(1),rbuf(2))
	  deallocate(xg,yg)
	end if
	call shympi_bcast(rbuf)
	x0 = rbuf(1)
	y0 = rbuf(2)

	deallocate(iglob,xloc,yloc,xglob,yglob)

	end subroutine lgr_mpi_global_center

!*******************************************************************

	subroutine lgr_mpi_assign_ids(nbdy_before)

! gives the particles of one seeding call the ids they have in a serial
! run, and applies the limit nbdymax to the particles of the run. Called
! on every process after each seeding call (lgr_init_all for the whole
! basin, lagbound_seed_particles for one polygon); nbdy_before is the
! number of particles the process held before the call. Collective: a
! process that created no particle in the call takes part as well. In a
! serial run it returns at once.
!
! In a serial run the ids follow the order of creation: in one seeding
! call the elements in increasing number, in an element the order of the
! loops (grid points, then one particle per layer at a point). On several
! processes only the main owner of an element releases in it, so all new
! particles of an element are on one process, in their order of creation
! (slots nbdy_before+1 ... nbdy), and the global element number
! (init%ie_global = ip_int_elem) is the serial element number. The key of
! a new particle is (global release element, position among the new
! particles of that element); the particle that is m-th in the global
! order of the keys gets the id idbdy0 + m, where idbdy0 is the number of
! ids given out before the call. The new particles are counted per global
! element on each process, the counts summed over the processes
! (MPI_Allreduce over nel_global entries: every process needs all the
! offsets, the gather helper lgr_mpi_gather_global delivers to rank 0
! only), and each process takes its offsets from the exclusive prefix sum
! in global element order. Afterwards idbdy = idbdy0 + the global number
! of new particles, on every process.
!
! insert_particle has advanced idbdy by one per particle on this process
! (provisional ids), so idbdy0 = idbdy - (nbdy - nbdy_before). It must be
! the same on every process; if not (ids were given out by a release that
! does not pass here) the run stops.
!
! limit nbdymax (> 0): as in a serial run it limits the particles of the
! run. On several processes insert_particle does not stop; here the run
! stops if the global number of particles (nbdy summed over the
! processes) exceeds nbdymax or a process passed it by itself
! (lgr_nbdymax_passed): rank 0 writes the message of insert_particle once,
! then every process stops (after the seeding call, not at the particle
! that passes the limit).
!
! A release with random depths (ipvert < -1, lgr_random_depth_release)
! draws the depth of each new particle again with the id it has now
! (lgr_release_depth): the depth is a function of the id (#225), and the id
! insert_particle gave is provisional. ipvert < -1 still stops at start-up
! on several processes (lgr_mpi_check_supported), so this is not run today.
!
! At the end the release records of the new particles are kept for the
! inserted block of the particle file (lgr_mpi_keep_release).

	use shympi, only : shympi_is_parallel,my_id,id_elem,nel_global
	use basin, only : nel

	implicit none

	include 'mpif.h'

	integer, intent(in) :: nbdy_before

	integer :: i, ie, ieg, nnew, ntot, nc, ierr
	integer :: idbdy0, idmin, idmax
	integer :: ival(2), ivalg(2)	!particles held, limit passed
	integer, allocatable :: icount(:), ioff(:)
	logical, external :: lgr_random_depth_release

	if( .not. shympi_is_parallel() ) return

	nnew = nbdy - nbdy_before
	if( nnew < 0 ) call shympi_abort_internal			&
     &		('lgr_mpi_assign_ids: fewer particles after the release')
	idbdy0 = idbdy - nnew

!	--------------------------------------------
!	the same ids given out before the call on every process
!	--------------------------------------------

	call MPI_Allreduce(idbdy0,idmin,1,MPI_INTEGER,MPI_MIN		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_assign_ids: MPI_Allreduce')
	call MPI_Allreduce(idbdy0,idmax,1,MPI_INTEGER,MPI_MAX		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_assign_ids: MPI_Allreduce')
	if( idmin /= idmax ) then
	  if( my_id == 0 ) then
	    write(6,*) 'lgr_mpi_assign_ids: the ids given out before the'	&
     &		//' release differ between the processes: ',idmin,idmax
	    write(6,*) 'a release of particles that is not supported on'	&
     &		//' several MPI processes has run'
	    flush(6)
	  end if
	  call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written
	  call shympi_abort_internal('lgr_mpi_assign_ids: ids differ'	&
     &		//' between processes')
	end if

!	--------------------------------------------
!	limit nbdymax on the global number of particles
!	--------------------------------------------

	ival(1) = nbdy
	ival(2) = 0
	if( lgr_nbdymax_passed ) ival(2) = 1
	call MPI_Allreduce(ival,ivalg,2,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_assign_ids: MPI_Allreduce')
	if( nbdymax > 0 .and. ( ivalg(1) > nbdymax .or. ivalg(2) > 0 ) ) then
	  if( my_id == 0 ) then		!the message of insert_particle
	    write(6,*) 'nbdymax = ',nbdymax
	    write(6,*) 'Cannot insert more than nbdymax particles'
	    write(6,*) 'Please change nbdymax in STR file'
	    write(6,*) 'particles needed: at least ',ivalg(1)
	    flush(6)
	  end if
	  call MPI_Barrier(MPI_COMM_WORLD,ierr)	!rank 0 has written
	  call shympi_abort_internal('error stop insert_particle: nbdy')
	end if

!	--------------------------------------------
!	new particles per global element, summed over the processes
!	--------------------------------------------

	allocate(icount(nel_global), ioff(nel_global), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_assign_ids: allocation')

	icount = 0
	do i=nbdy_before+1,nbdy
	  ieg = lgr_ar(i)%init%ie_global
	  ie = -lgr_ar(i)%init%ie
	  if( ieg < 1 .or. ieg > nel_global .or. ie < 1 .or. ie > nel ) then
	    write(6,*) 'lgr_mpi_assign_ids: particle ',i,' release'	&
     &		//' element ',ie,ieg
	    call shympi_abort_internal('lgr_mpi_assign_ids: new'	&
     &		//' particle without a release element')
	  end if
	  if( id_elem(1,ie) /= my_id ) then
	    write(6,*) 'lgr_mpi_assign_ids: particle ',i,' release'	&
     &		//' element ',ieg,' main owner ',id_elem(1,ie)
	    call shympi_abort_internal('lgr_mpi_assign_ids: new'	&
     &		//' particle in an element owned by another process')
	  end if
	  icount(ieg) = icount(ieg) + 1
	end do

	call MPI_Allreduce(icount,ioff,nel_global,MPI_INTEGER,MPI_SUM	&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_assign_ids: MPI_Allreduce')

	ntot = 0			!exclusive prefix sum: ioff(ieg) =
	do ieg=1,nel_global		!new particles in elements before ieg
	  nc = ioff(ieg)
	  ioff(ieg) = ntot
	  ntot = ntot + nc
	end do

!	--------------------------------------------
!	ids in the order of the keys, the global count
!	--------------------------------------------

	do i=nbdy_before+1,nbdy		!in order of creation
	  ieg = lgr_ar(i)%init%ie_global
	  ioff(ieg) = ioff(ieg) + 1
	  lgr_ar(i)%id = idbdy0 + ioff(ieg)
	end do
	idbdy = idbdy0 + ntot

	deallocate(icount,ioff)

	! random depths drawn again with the ids of a serial run (#225), before
	! the release records are kept
	if( lgr_random_depth_release() ) then
	  do i=nbdy_before+1,nbdy
	    call lgr_release_depth(i)
	  end do
	end if

	call lgr_mpi_keep_release(nbdy_before)	!for lgr_mpi_output

	end subroutine lgr_mpi_assign_ids

!*******************************************************************

	subroutine lgr_mpi_keep_release(nbdy_before)

! keeps the release records of the particles in the slots nbdy_before+1
! ... nbdy (just released by this process, their ids final) for the
! inserted block of the next output of the particle file (lgr_mpi_output;
! see rel_id and rel_body at the top of the module): the id and the
! release record init with ie = the local release element (init%ie is
! negative until a serial output writes it; it is not changed here).
! lgr_nrel_total counts the particles; the records are kept only if the
! particle file is written (blgr_file). Several processes only.

	implicit none

	integer, intent(in) :: nbdy_before

	integer :: i, nnew, nsize, ierr
	integer, allocatable :: inew(:)
	type(lagr_body), allocatable :: bnew(:)

	nnew = nbdy - nbdy_before
	if( nnew <= 0 ) return
	lgr_nrel_total = lgr_nrel_total + nnew
	if( .not. blgr_file ) return

	if( .not. allocated(rel_id) ) then
	  allocate(rel_id(max(nnew,1024)), rel_body(max(nnew,1024))	&
     &		, stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_keep_release: allocation')
	end if
	if( n_rel + nnew > size(rel_id) ) then	!larger lists, entries copied
	  nsize = max(2*size(rel_id), n_rel + nnew)
	  allocate(inew(nsize), bnew(nsize), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_keep_release: allocation')
	  inew(1:n_rel) = rel_id(1:n_rel)
	  bnew(1:n_rel) = rel_body(1:n_rel)
	  call move_alloc(inew,rel_id)
	  call move_alloc(bnew,rel_body)
	end if

	do i=nbdy_before+1,nbdy
	  n_rel = n_rel + 1
	  rel_id(n_rel) = lgr_ar(i)%id
	  rel_body(n_rel) = lgr_ar(i)%init
	  rel_body(n_rel)%ie = abs(lgr_ar(i)%init%ie)
	end do

	end subroutine lgr_mpi_keep_release

!*******************************************************************

	subroutine lgr_mpi_debug_dump(dtime,bpart_only,bclose)

! debug dump of particles, side fluxes and node arrays (levdbg >= 3)
!
! NN = rank (my_id). Every file starts with the line "# rank R of N"
! (R = my_id, N = number of processes). At the first call of a run all
! files are replaced, so that none is left from an older run: part, flux
! and node always, flux3 in a 3D run; in a 2D run an old flux3 file is
! deleted. Flux, flux3 and node keep only their header if the run ends
! before 10 h. A rank without particles keeps only the header in part.
!
! bpart_only (optional, default false): true for the call right after a
! release (before any tracking); it writes the particles only, never the
! flux, flux3 and node files
!
! bclose (optional, default false): true for the call at the end of the
! particle run: it closes the part file, and later calls write nothing
!
! lgrdbg.part.NN.txt: at every particle output and right after every
! release, one line per array entry
!	class time id x y z lb ie_global rank ncross
!	key_ie key_xi1 key_xi2 key_l key_z key_time
!   class P: element with only own nodes, M: mixed element (a vertex owned
!   by another rank) this rank is the main owner of, G: mixed element
!   owned elsewhere, D: entry with ie < 0, a particle that has left the
!   basin (x = y = 0, ie_global = -global element; in a serial run a
!   decayed particle shows the same since #226, ie = -abs(ie); an entry
!   with ie = 0 would show ie_global = 0, but neither the tracker nor the
!   hand-over makes one); lb = layer; ncross = lgr_ncross(i)
!   (crossings of the last time step; for a particle handed over in that
!   step the count of the whole step)
!   The last six columns are the particle's key, the same in a serial run
!   and on several processes, all with their full digits: init%ie_global,
!   init%xi(1), init%xi(2), init%l, init%z, init%time (the release
!   element, the first two release coordinates, the release layer, the
!   release depth in the layer and the release time; several particles
!   can start at one position, in different layers). Used by
!   lgr_dbg_compare.py to pair the particles of two runs.
!
! once, at the first output at or after 10 h of the run:
! lgrdbg.flux.NN.txt: one line per element and side ii (opposite vertex ii)
!	ie_global node_global rank main_owner n_ghost_nodes
!	flux3d(1,ii,ie) flux2d(ii,ie)
! lgrdbg.flux3.NN.txt (only if nlv > 1): the same with flux3d of the
!	bottom layer ilhv(ie) in place of flux3d(1,ii,ie)
! lgrdbg.node.NN.txt: one line per local node
!	node_global rank owner wlnv(1,k) mfluxv(1,k) difv(1,k) wxv(k) wyv(k)
!
! the routine only reads model state

	use shympi, only : my_id,id_node,id_elem,ip_int_node,ip_int_elem
	use basin, only : nkn,nel,nen3v
	use levels, only : nlv,ilhv
	use femtime, only : dtanf
	use mod_hydro_vel, only : wlnv
	use mod_bound_dynamic, only : mfluxv
	use mod_diff_visc_fric, only : difv
	use mod_meteo, only : wxv,wyv
	use para, only : getpar

	implicit none

	double precision, intent(in) :: dtime
	logical, intent(in), optional :: bpart_only
	logical, intent(in), optional :: bclose

	double precision, parameter :: dtflux = 36000.d0 !fluxes after 10 h

	integer, save :: icall = 0		!0 first call, 1 on, -1 off
	integer, save :: iupart = 0		!unit of lgrdbg.part.NN.txt
	integer, save :: iuflux = 0		!unit of lgrdbg.flux.NN.txt
	integer, save :: iuflux3 = 0		!unit of lgrdbg.flux3.NN.txt
	integer, save :: iunode = 0		!unit of lgrdbg.node.NN.txt
	logical, save :: bflux = .false.	!flux and node files written

	integer :: i,ie,ii,k,ieg,ng,ierr
	double precision :: x,y,xi(3)
	character(len=1) :: what

	if( icall < 0 ) return

	if( present(bclose) ) then
	  if( bclose ) then			!end of the particle run
	    if( icall == 1 ) close(iupart)
	    icall = -1			!no dump line after the close
	    return
	  end if
	end if

	if( icall == 0 ) then
	  icall = -1
	  if( nint(getpar('levdbg')) < 3 ) return
	  icall = 1
	  call lgr_mpi_debug_open('part',iupart)
	  call lgr_mpi_debug_open('flux',iuflux)
	  call lgr_mpi_debug_open('node',iunode)
	  call lgr_mpi_debug_open('flux3',iuflux3)
	  if( nlv <= 1 ) then			!2D run: no flux3 file
	    close(iuflux3,status='delete')
	    iuflux3 = 0
	  end if
	end if

!	--------------------------------------------
!	particles, every output
!	--------------------------------------------

	do i=1,nbdy
	  ie = lgr_ar(i)%actual%ie
	  if( ie > 0 ) then
	    xi = lgr_ar(i)%actual%xi
	    call xi2xy_ierr(ie,x,y,xi,ierr)
	    if( ierr /= 0 ) then	!a bare stop in xi2xy until #305
	      call xi2xy_write_error(ie,xi)
	      call shympi_abort_internal('error stop lgr_mpi_debug_dump:'	&
     &		//' error of xi2xy')
	    end if
	    ieg = ip_int_elem(ie)
	    ng = lgr_mpi_ghost_nodes(ie)
	    if( ng == 0 ) then
	      what = 'P'
	    else if( id_elem(1,ie) == my_id ) then
	      what = 'M'
	    else
	      what = 'G'
	    end if
	  else
	    x = 0.d0
	    y = 0.d0
	    ieg = 0
	    if( ie < 0 ) ieg = -ip_int_elem(-ie)
	    what = 'D'
	  end if
	  write(iupart,1000) what,dtime,lgr_ar(i)%id,x,y		&
     &		,lgr_ar(i)%actual%z,lgr_ar(i)%actual%l,ieg,my_id	&
     &		,lgr_ncross(i)					&
     &		,lgr_ar(i)%init%ie_global,lgr_ar(i)%init%xi(1)		&
     &		,lgr_ar(i)%init%xi(2),lgr_ar(i)%init%l			&
     &		,lgr_ar(i)%init%z,lgr_ar(i)%init%time
	end do
	flush(iupart)

!	--------------------------------------------
!	fluxes and node arrays, once (files opened at the first call)
!	--------------------------------------------

	if( present(bpart_only) ) then
	  if( bpart_only ) return		!call after a release
	end if
	if( bflux .or. dtime - dtanf < dtflux ) return
	bflux = .true.

	do ie=1,nel
	  ng = lgr_mpi_ghost_nodes(ie)
	  do ii=1,3
	    k = nen3v(ii,ie)
	    write(iuflux,2000) ip_int_elem(ie),ip_int_node(k),my_id	&
     &		,id_elem(1,ie),ng,flux3d(1,ii,ie),flux2d(ii,ie)
	  end do
	end do
	close(iuflux)

	if( nlv > 1 ) then
	  do ie=1,nel
	    ng = lgr_mpi_ghost_nodes(ie)
	    do ii=1,3
	      k = nen3v(ii,ie)
	      write(iuflux3,2000) ip_int_elem(ie),ip_int_node(k),my_id	&
     &		,id_elem(1,ie),ng,flux3d(ilhv(ie),ii,ie),flux2d(ii,ie)
	    end do
	  end do
	  close(iuflux3)
	end if

	do k=1,nkn
	  write(iunode,3000) ip_int_node(k),my_id,id_node(k)		&
     &		,wlnv(1,k),mfluxv(1,k),difv(1,k),wxv(k),wyv(k)
	end do
	close(iunode)

	write(6,*) 'lgr_mpi_debug_dump: flux and node files written ',dtime

 1000	format(a1,f14.1,i11,2es25.16e3,es17.8e2,i6,i11,i6,i6		&
     &		,i11,2es25.16e3,i6,es17.8e2,es25.16e3)
 2000	format(2i11,i6,i6,i3,2es17.8e2)
 3000	format(i11,i6,i6,5es17.8e2)
	end subroutine lgr_mpi_debug_dump

!*******************************************************************

	subroutine lgr_mpi_debug_open(what,iu)

! opens lgrdbg.WHAT.NN.txt fresh (replacing an old file); NN = rank
! and writes the header line "# rank R of N"

	use shympi, only : my_id,n_threads

	implicit none

	character(len=*), intent(in) :: what
	integer, intent(out) :: iu

	integer :: ierr
	character(len=80) :: name

	write(name,'(a,a,a,i0.2,a)') 'lgrdbg.',what,'.',my_id,'.txt'
	open(newunit=iu,file=name,status='replace',form='formatted'	&
     &		,action='write',iostat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('lgr_mpi_debug_open: cannot open '	&
     &		//trim(name))
	end if
	write(iu,'(a,i0,a,i0)') '# rank ',my_id,' of ',n_threads
	flush(iu)

	end subroutine lgr_mpi_debug_open

!*******************************************************************

	function lgr_mpi_ghost_nodes(ie)

! number of vertices of element ie owned by another rank (0 = own element)

	use shympi, only : my_id,id_node
	use basin, only : nen3v

	implicit none

	integer :: lgr_mpi_ghost_nodes
	integer, intent(in) :: ie

	integer :: ii

	lgr_mpi_ghost_nodes = 0
	do ii=1,3
	  if( id_node(nen3v(ii,ie)) /= my_id ) then
	    lgr_mpi_ghost_nodes = lgr_mpi_ghost_nodes + 1
	  end if
	end do

	end function lgr_mpi_ghost_nodes

!*******************************************************************

	end module mod_lagrange_mpi

!*******************************************************************
!*******************************************************************
!*******************************************************************
! the internal-error guards of the tracker (#256), outside the module so
! that every Lagrangian file can call them, also lagrange_connect.f90
! (mod_lagrange_mpi uses its module connectivity)
!*******************************************************************

	subroutine lgr_internal_error(message)

! an internal-error guard of the tracker (a programming error or a
! corrupt state, never the input) has failed. Inside the OpenMP particle
! loop of drogue (lgr_omp_loop) run by more than one thread, the calling
! thread may be a worker, which must not call MPI_ABORT (MPI is
! initialised MPI_THREAD_FUNNELED): the failure and its message are
! recorded (lgr_mpi_list_fail, kind 5, inside the critical section
! lgr_export; lgr_internal_flag = 1) and the routine returns, so that its
! caller leaves the particle with defined values and the tracker stops
! (lgr_internal_failed); the main thread aborts with the message in
! lgr_mpi_list_check after the loop, before any collective call.
! Anywhere else (a loop on one thread, the hand-over, the release) it
! aborts at once through shympi_abort_internal, as the guard did before
! (#256), after writing the events of the tracker recorded in the pass
! (lgr_events, #305: among them the values of the error, for a guard
! with an event kind; until #305 lgr_event wrote them only for such a
! kind, so that a guard with none, "error stop drogue: internal error",
! "lagr_connect_count: (1)" or "lagr_count: (1)", dropped the other
! events of the pass on one thread, which lgr_mpi_list_check writes on
! several). Must not be called inside the critical section lgr_export

	use mod_lagrange, only : lgr_events
	use mod_lagrange_mpi, only : lgr_omp_loop, lgr_internal_flag
	use mod_lagrange_mpi, only : lgr_mpi_list_fail

	implicit none

	character(len=*), intent(in) :: message	!message of the abort

	logical :: openmp_in_parallel

	if( .not. lgr_omp_loop ) then
	  call lgr_events			!the events of the pass (#305)
	  call shympi_abort_internal(message)
	else if( .not. openmp_in_parallel() ) then
	  call lgr_events			!the events of the pass (#305)
	  call shympi_abort_internal(message)
	end if

!$OMP CRITICAL (lgr_export)
	call lgr_mpi_list_fail(5,0,0,0,0,0,message)
!$OMP END CRITICAL (lgr_export)
!$OMP ATOMIC WRITE
	lgr_internal_flag = 1

	end subroutine lgr_internal_error

!*******************************************************************

	function lgr_internal_failed()

! true if an internal-error guard of the tracker was recorded in the
! particle loop on this process (lgr_internal_error, #256): the tracker
! then leaves its particle at once with defined values, and track_single
! skips the remaining particles of the loop. OMP atomic read, called from
! any thread; always false in a run that works

	use mod_lagrange_mpi, only : lgr_internal_flag

	implicit none

	logical :: lgr_internal_failed

	integer :: n

!$OMP ATOMIC READ
	n = lgr_internal_flag

	lgr_internal_failed = ( n /= 0 )

	end function lgr_internal_failed
