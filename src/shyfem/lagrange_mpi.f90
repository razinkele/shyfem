
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
! lgr_mpi_pack_particle		serialize the whole particle record to a double buffer
! lgr_mpi_unpack_particle	deserialize the whole particle record
! lgr_mpi_remove_particle	remove a particle from the array (last one moves up)
! lgr_mpi_remove_list		remove several particles (highest slot first)
! lgr_mpi_selftest_pack		self-test of record and removal (levdbg >= 3)
! lgr_mpi_find_elem		local element of a global element, 0 if not held
! lgr_mpi_find_node		local node of a global node, 0 if not held
! lgr_mpi_handover		hand-over of the marked particles, in rounds
! lgr_mpi_handover_round	one round of the hand-over
! lgr_mpi_handover_stats	totals of the hand-over (levdbg >= 3)
! lgr_mpi_gather_output		gather particles to rank 0 for output
! lgr_mpi_reduce_connect	reduce connectivity matrices
! lgr_mpi_gather_global		global array on rank 0 from the owned entries
! lgr_mpi_global_area		total basin area as in a serial run
! lgr_mpi_global_center		basin centre as in a serial run
! lgr_mpi_reset_export		reset export buffers
! lgr_mpi_debug_dump		text dump of particles, fluxes, node arrays
! lgr_mpi_debug_open		open one debug dump file
! lgr_mpi_ghost_nodes		number of vertices of an element owned elsewhere
! lgr_mpi_bisect		position of a key in a sorted list

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
	integer, parameter :: lgr_hand_extra = 8
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

	! totals of the hand-over on this process (lgr_mpi_handover_stats)
	integer, save :: lgr_nhand = 0       !particles sent
	integer, save :: lgr_nround_max = 0  !most rounds with a mark in a step
	integer, save :: lgr_nputback = 0    !put back at a cut-off side for
					     !lack of a layer (OMP atomic)

	logical, save :: bmpi_lagr = .false.      !true if MPI active for lagrange

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

	subroutine lgr_mpi_init

! initializes the MPI buffers of the Lagrangian module; needs nbdymax and
! ncust and the allocated particle array (called after the first
! particles are read), runs the self-test of the particle record at
! levdbg >= 3
!
! test hook: if the environment variable LGR_TEST_SMALL_EXPORT is set to 1
! the lists of marks start with 2 entries instead of max(nbdymax,1024),
! so that their growth is exercised by a small run

	use shympi
	use para, only : getpar

	implicit none

	integer :: ierr, ndim, ist
	character(len=16) :: sval

	lgr_pack_size = lgr_pack_base + ncust
	bmpi_lagr = shympi_is_parallel()
	blgr_dbg = nint(getpar('levdbg')) >= 3

	call lgr_mpi_selftest_pack		!only at levdbg >= 3

	if( .not. bmpi_lagr ) return

	ndim = max(nbdymax, 1024)
	call get_environment_variable('LGR_TEST_SMALL_EXPORT',sval,	&
     &			status=ist)
	if( ist == 0 .and. trim(sval) == '1' ) ndim = 2

	allocate(export_dest(ndim), export_idx(ndim), export_elem(ndim)	&
     &		, export_side(ndim), export_nleft(ndim), export_tleft(ndim)	&
     &		, stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_init: allocation')

	n_export = 0
	n_export_grow = 0

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
	call MPI_Allgather(csum,nproc,MPI_INTEGER8,			&
     &			csall,nproc,MPI_INTEGER8,MPI_COMM_WORLD,ierr)

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
	call MPI_Allreduce(nd3,nd3g,1,MPI_INTEGER,MPI_SUM,		&
     &			MPI_COMM_WORLD,ierr)

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
	call MPI_Allreduce(hash,hmax,1,MPI_INTEGER8,MPI_MAX,		&
     &			MPI_COMM_WORLD,ierr)
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
	call MPI_Allreduce(lmin,lming,1,MPI_INTEGER,MPI_MIN		&
     &			,MPI_COMM_WORLD,ierr)
	call MPI_Allreduce(lmax,lmaxg,1,MPI_INTEGER,MPI_MAX		&
     &			,MPI_COMM_WORLD,ierr)
	call MPI_Allreduce(dt,dtmax,1,MPI_DOUBLE_PRECISION,MPI_MAX	&
     &			,MPI_COMM_WORLD,ierr)
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
	if( irmin >= n_threads ) return

	iall = info
	call MPI_Bcast(iall,lgr_side_nfo,MPI_INTEGER,irmin,MPI_COMM_WORLD	&
     &			,ierr)

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

	subroutine lgr_mpi_mark_side(i, ie, iside, t_left, n_left)

! records that particle i stopped on side iside of local element ie, a
! cut-off side, with the time t_left and the crossings n_left still to do;
! it goes to rank -lgr_ieltv(iside,ie) - 1000. Sets lgr_marked(i) (the
! particle's own slot); the shared lists are written inside the critical
! section lgr_export and grow when full. Called by the tracker, inside the
! parallel loop of drogue or outside any parallel region.

	use shympi, only : my_id, n_threads

	implicit none

	integer, intent(in) :: i		!particle (slot)
	integer, intent(in) :: ie		!local element it is leaving
	integer, intent(in) :: iside		!side of ie (1..3)
	real, intent(in) :: t_left		!time still to advect
	integer, intent(in) :: n_left		!crossings still allowed

	integer :: r

	r = -lgr_ieltv(iside,ie) - 1000
	if( r < 0 .or. r >= n_threads .or. r == my_id			&
     &		.or. .not. allocated(export_idx) ) then
	  write(6,*) 'lgr_mpi_mark_side: i,ie,iside,mark: ',i,ie,iside	&
     &		,lgr_ieltv(iside,ie)
	  call shympi_abort_internal('lgr_mpi_mark_side: not a cut-off'	&
     &		//' side of a parallel run')
	end if

	lgr_marked(i) = 1

!$OMP CRITICAL (lgr_export)
	if( n_export + 1 > size(export_idx) ) call lgr_mpi_grow_export
	n_export = n_export + 1
	export_idx(n_export) = i
	export_dest(n_export) = r
	export_elem(n_export) = ie
	export_side(n_export) = iside
	export_nleft(n_export) = n_left
	export_tleft(n_export) = t_left
!$OMP END CRITICAL (lgr_export)

	end subroutine lgr_mpi_mark_side

!*******************************************************************

	subroutine lgr_mpi_grow_export

! doubles the size of the lists of marks (new lists, copy of the n_export
! entries in use, move_alloc); called inside the critical section
! lgr_export of lgr_mpi_mark_side

	use shympi, only : my_id

	implicit none

	integer :: ierr, nnew
	integer, allocatable :: idest(:), iidx(:), ielem(:), iside(:)
	integer, allocatable :: inleft(:)
	real, allocatable :: rtleft(:)

	nnew = 2*max(size(export_idx), 1)

	allocate(idest(nnew), iidx(nnew), ielem(nnew), iside(nnew)	&
     &		, inleft(nnew), rtleft(nnew), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_grow_export: allocation')

	idest(1:n_export) = export_dest(1:n_export)
	iidx(1:n_export) = export_idx(1:n_export)
	ielem(1:n_export) = export_elem(1:n_export)
	iside(1:n_export) = export_side(1:n_export)
	inleft(1:n_export) = export_nleft(1:n_export)
	rtleft(1:n_export) = export_tleft(1:n_export)
	call move_alloc(idest,export_dest)
	call move_alloc(iidx,export_idx)
	call move_alloc(ielem,export_elem)
	call move_alloc(iside,export_side)
	call move_alloc(inleft,export_nleft)
	call move_alloc(rtleft,export_tleft)

	n_export_grow = n_export_grow + 1
	if( blgr_dbg ) write(6,*) 'lgr_mpi_grow_export: rank ',my_id,	&
     &		' new size ',nnew,' growth number ',n_export_grow

	end subroutine lgr_mpi_grow_export

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
! moved into slot i with all its fields (also lgr_ncross and lgr_marked),
! nbdy is reduced by one; the custom values of the vacated last slot are
! freed (insert allocates them again). To remove several particles use
! lgr_mpi_remove_list.

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
	end if

	if( allocated(lgr_ar(nbdy)%custom) ) deallocate(lgr_ar(nbdy)%custom)
	lgr_ncross(nbdy) = 0
	lgr_marked(nbdy) = 0
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
! must sit in its slot with all fields and its lgr_ncross value, nbdy one
! less. Then six particles are put behind the nbdy present, three of them
! are marked (lgr_marked), the last one of the array among them, and
! removed in one go with lgr_mpi_remove_list (list not sorted): exactly
! the three unmarked ones must remain, each once, with all its fields, its
! lgr_ncross value and no mark. Particle array, nbdy and ncust are
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
     &		'remove: lgr_ncross      ',				&
     &		'remove: nbdy            ',				&
     &		'remove list: particles  ',				&
     &		'remove list: ncross,mark',				&
     &		'remove list: nbdy       ' /)

	integer, parameter :: nlist = 6		!particles of the list test
	integer :: ierr, ifield, ifmax, ncust_save, npack_save
	integer :: n0, j, jj, k
	double precision, allocatable :: buf(:)
	type(lagr_entry) :: p, q
	type(lagr_entry) :: psave(nlist), pnew(nlist)
	integer :: isave(nlist), msave(nlist), nfound(nlist)
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
	    call lgr_mpi_selftest_fill(pnew(j),j)
	    lgr_ar(n0+j) = pnew(j)
	    lgr_ncross(n0+j) = 10*j
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
	  else if( lgr_ncross(n0+1) /= 30 ) then
	    ifield = 20
	  end if
	  nbdy = n0
	  do j = 1, 3
	    lgr_ar(n0+j) = psave(j)
	    lgr_ncross(n0+j) = isave(j)
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
	    call lgr_mpi_selftest_fill(pnew(j),j)
	    lgr_ar(n0+j) = pnew(j)
	    lgr_ncross(n0+j) = 10*j
	    lgr_marked(n0+j) = 0
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

! hand-over of the particles marked at a cut-off side in this time step
! (lgr_mpi_mark_side): they finish the step on the process across, with
! the time and the crossings they have left. In rounds
! (lgr_mpi_handover_round); every process takes part in every round, and
! a round is made while the global number of marks is not zero (one
! collective decision per round). A particle that arrives can reach
! another cut-off side in the same step: it is marked again and goes in
! the next round. Every hand-over uses one crossing of the particle's
! budget for the step (100, n_left), so no particle is handed over more
! than 100 times in a step and the rounds end; more rounds than that is
! an internal error (the same on every process).
!
! called after drogue, outside any parallel region, on every process

	use shympi, only : n_threads

	implicit none

	include 'mpif.h'

	double precision, intent(in) :: dtime

	integer, parameter :: nround_cap = 101	!crossing budget, plus one
	integer :: nglob, nround, ierr

	if( n_threads <= 1 ) return

	nround = 0
	do
	  call MPI_Allreduce(n_export,nglob,1,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	  if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover: MPI_Allreduce')
	  if( nglob == 0 ) exit
	  nround = nround + 1
	  if( nround > nround_cap ) call shympi_abort_internal		&
     &		('lgr_mpi_handover: more rounds than crossings allowed')
	  call lgr_mpi_handover_round(dtime)
	end do

	lgr_nround_max = max(lgr_nround_max,nround)

	end subroutine lgr_mpi_handover

!*******************************************************************

	subroutine lgr_mpi_handover_round(dtime)

! one round of the hand-over (lgr_mpi_handover), on every process:
! 1. the marks are sorted by particle slot (the threads fill the list in
!    the order they arrive) and counted per destination; the counts are
!    exchanged (MPI_Alltoall), so both sides know every message length
! 2. each marked particle is packed, per destination in slot order: its
!    record and the hand-over fields (layout at the top of the module):
!    the element it is leaving, the end nodes of the side and its weights
!    there, t_left, n_left, phase; the messages are sent and received,
!    their lengths checked
! 3. the sent particles are removed (lgr_mpi_remove_list), the list of
!    marks is emptied
! 4. the arrivals are appended in a fixed order (by sending process, then
!    in the sender's order). Each is put into the local element across the
!    side, the one that has both end nodes and is not the element left,
!    with the weights at the two end nodes and zero at the third vertex:
!    the values track_xi_next_element copies in a serial run. Then the
!    layer adjustment that track_xi applies after a crossing
!    (track_xi_adjust_layer), which the sender did not run
! 5. each arrival goes on with track_advect, with the time and crossings
!    that travelled (the start-of-step tests of track_single were applied
!    where the step began) and, unless it is marked again, track_finish
!    (phase 0) once. Marks made here go in the next round.
!
! the record travels whole and unchanged: actual%time still holds the
! start of the step, as track_finish needs it

	use shympi
	use basin, only : nen3v

	implicit none

	include 'mpif.h'

	double precision, intent(in) :: dtime

	interface
	  subroutine track_advect(i,t_left,n_left,dtime)
	    implicit none
	    integer, intent(in) :: i
	    real, intent(inout) :: t_left
	    integer, intent(inout) :: n_left
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

	integer :: nproc, lrecp, lrec, nmark, j, jj, i, k, r, ie, iside
	integer :: ia2, ia3, ip, ierr, nreq, nrecv, nget, nstot, nrtot
	integer :: iega, kg1, kg2, kl1, kl2, ieb, nf, phase, lb
	integer :: nsend(0:n_threads-1), nrcv(0:n_threads-1)
	integer :: soff(0:n_threads), roff(0:n_threads)
	integer :: ifill(0:n_threads-1)
	integer :: ireq(2*n_threads)
	integer :: istat(MPI_STATUS_SIZE,2*n_threads)
	integer, allocatable :: key(:), iord(:), islot(:), inleft(:)
	real, allocatable :: rtleft(:)
	double precision, allocatable :: sbuf(:), rbuf(:)
	double precision :: w1, w2, zz
	double precision :: xi(3)

	nproc = n_threads
	lrecp = lgr_pack_base + ncust		!record of a particle
	lrec = lrecp + lgr_hand_extra		!record and hand-over fields
	nmark = n_export

	!-----------------------------------------------
	! 1. marks sorted by slot, counted per destination, counts exchanged
	!-----------------------------------------------

	allocate(key(max(nmark,1)), iord(max(nmark,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: allocation')

	do j = 1, nmark
	  key(j) = export_idx(j)
	  iord(j) = j
	end do
	call lgr_mpi_sort_by_key(nmark,key,iord)
	do j = 2, nmark
	  if( key(j) == key(j-1) ) then
	    write(6,*) 'lgr_mpi_handover_round: slot marked twice: ',key(j)
	    call shympi_abort_internal				&
     &		('lgr_mpi_handover_round: slot marked twice')
	  end if
	end do

	nsend = 0
	do j = 1, nmark
	  r = export_dest(j)
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
	  j = iord(jj)
	  r = export_dest(j)
	  i = export_idx(j)
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
	  ip = lrec*(soff(r) + ifill(r))
	  ifill(r) = ifill(r) + 1
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
	! 3. remove the sent particles, empty the list of marks
	!-----------------------------------------------

	call lgr_mpi_remove_list(nmark,key)	!key: the marked slots
	lgr_nhand = lgr_nhand + nmark
	n_export = 0

	!-----------------------------------------------
	! 4. append the arrivals: by sending process, then the sender's order
	!-----------------------------------------------

	if( nbdy + nrtot > size(lgr_ar) ) then
	  call mod_lagrange_handle_alloc(nbdy+nrtot)
	end if

	allocate(islot(max(nrtot,1)), inleft(max(nrtot,1))		&
     &		, rtleft(max(nrtot,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_handover_round: allocation')

	do j = 1, nrtot
	  ip = lrec*(j-1)
	  nbdy = nbdy + 1
	  i = nbdy
	  call lgr_mpi_unpack_particle(rbuf(ip+1:ip+lrecp),lgr_ar(i))
	  ip = ip + lrecp
	  iega = nint(rbuf(ip+1))
	  kg1 = nint(rbuf(ip+2))
	  kg2 = nint(rbuf(ip+3))
	  w1 = rbuf(ip+4)
	  w2 = rbuf(ip+5)
	  rtleft(j) = real(rbuf(ip+6))
	  inleft(j) = nint(rbuf(ip+7))
	  phase = nint(rbuf(ip+8))
	  if( phase /= 0 ) then
	    write(6,*) 'lgr_mpi_handover_round: phase ',phase
	    call shympi_abort_internal('lgr_mpi_handover_round: phase')
	  end if

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
	  lgr_ncross(i) = 100 - inleft(j)	!crossings so far in the step
	  lgr_marked(i) = 0
	  islot(j) = i
	end do

	!-----------------------------------------------
	! 5. the arrivals go on: advection, then the rest of the step
	!-----------------------------------------------

	do j = 1, nrtot
	  i = islot(j)
	  call track_advect(i,rtleft(j),inleft(j),dtime)
	  if( lgr_marked(i) == 0 ) call track_finish(i,0,dtime)
	end do

	deallocate(key,iord,sbuf,rbuf,islot,inleft,rtleft)

	end subroutine lgr_mpi_handover_round

!*******************************************************************

	subroutine lgr_mpi_handover_stats

! at levdbg >= 3, on several processes, collective: rank 0 writes the
! totals of the hand-over over all processes: particles handed over, the
! most hand-overs of one particle in one time step, and the particles put
! back at a cut-off side for lack of a layer (track_xi_side_test).
! The most hand-overs of one particle in a step is the most rounds of a
! step: in round k the particles sent are those marked in drogue (k = 1)
! or arrivals of round k-1 marked again, so each of them is handed over
! for the k-th time.

	use shympi, only : my_id, n_threads

	implicit none

	include 'mpif.h'

	integer :: ival(2), ivalg(2), nrmax, ierr

	if( .not. blgr_dbg .or. n_threads <= 1 ) return

	ival(1) = lgr_nhand
	ival(2) = lgr_nputback
	call MPI_Allreduce(ival,ivalg,2,MPI_INTEGER,MPI_SUM		&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_stats: MPI_Allreduce')
	call MPI_Allreduce(lgr_nround_max,nrmax,1,MPI_INTEGER,MPI_MAX	&
     &			,MPI_COMM_WORLD,ierr)
	if( ierr /= MPI_SUCCESS ) call shympi_abort_internal		&
     &		('lgr_mpi_handover_stats: MPI_Allreduce')

	if( my_id == 0 ) then
	  write(6,'(a,i0,a,i0,a,i0)') ' lgr hand-over: particles handed'	&
     &		//' over: ',ivalg(1),', most hand-overs of one particle in'	&
     &		//' one step: ',nrmax,', put back at a cut-off side for'	&
     &		//' lack of a layer: ',ivalg(2)
	end if

	end subroutine lgr_mpi_handover_stats

!*******************************************************************

	subroutine lgr_mpi_gather_output(iu, dtime)

! gather all particles to rank 0 for trajectory output

	use shympi

	implicit none

	include 'mpif.h'

	integer, intent(in) :: iu
	double precision, intent(in) :: dtime

	integer :: ierr, i, j, nproc, myrank
	integer :: nbdy_local, nbdy_global, nbdy_save
	integer, allocatable :: all_counts(:), all_data(:), displs(:)
	double precision, allocatable :: local_buf(:), global_buf(:)

	nproc = n_threads
	myrank = my_id

	if( nproc <= 1 ) then
	  call lgr_output(iu, dtime)
	  return
	end if

	nbdy_local = nbdy
	lgr_pack_size = lgr_pack_base + ncust

	allocate(all_counts(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	call MPI_Allgather(nbdy_local, 1, MPI_INTEGER,			&
     &		all_counts, 1, MPI_INTEGER,				&
     &		MPI_COMM_WORLD, ierr)

	nbdy_global = sum(all_counts)

	! Pack local particles
	allocate(local_buf(max(nbdy_local*lgr_pack_size,1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	do i = 1, nbdy_local
	  j = (i - 1) * lgr_pack_size
	  call lgr_mpi_pack_particle(lgr_ar(i),				&
     &		local_buf(j+1:j+lgr_pack_size))
	end do

	! Compute displacements
	allocate(displs(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	allocate(all_data(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	displs(0) = 0
	do i = 0, nproc - 1
	  all_data(i) = all_counts(i) * lgr_pack_size
	end do
	do i = 1, nproc - 1
	  displs(i) = displs(i-1) + all_data(i-1)
	end do

	if( myrank == 0 ) then
	  allocate(global_buf(max(nbdy_global*lgr_pack_size,1)),	&
     &		stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	else
	  allocate(global_buf(1),stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal('lgr_mpi_gather: alloc')
	end if

	call MPI_Gatherv(local_buf, nbdy_local*lgr_pack_size,		&
     &		MPI_DOUBLE_PRECISION,					&
     &		global_buf, all_data, displs,				&
     &		MPI_DOUBLE_PRECISION,					&
     &		0, MPI_COMM_WORLD, ierr)

	! Rank 0: unpack and write
	if( myrank == 0 ) then
	  nbdy_save = nbdy
	  nbdy = nbdy_global
	  call mod_lagrange_handle_alloc(nbdy)
	  do i = 1, nbdy_global
	    j = (i - 1) * lgr_pack_size
	    call lgr_mpi_unpack_particle(global_buf(j+1:j		&
     &			+lgr_pack_size), lgr_ar(i))
	  end do
	  call lgr_output(iu, dtime)
	  nbdy = nbdy_save
	  call mod_lagrange_handle_alloc(nbdy)
	end if

	deallocate(local_buf, global_buf, all_counts, all_data, displs)

	end subroutine lgr_mpi_gather_output

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

	subroutine lgr_mpi_debug_dump(dtime,bpart_only)

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
! lgrdbg.part.NN.txt: at every particle output and right after every
! release, one line per array entry
!	class time id x y z lb ie_global rank ncross
!   class P: element with only own nodes, M: mixed element (a vertex owned
!   by another rank) this rank is the main owner of, G: mixed element
!   owned elsewhere, D: entry with ie <= 0 (x = y = 0, ie_global = 0 for
!   ie = 0, -global element for ie < 0); lb = layer; ncross = lgr_ncross(i)
!   (crossings of the last time step; for a particle handed over in that
!   step the count of the whole step)
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

	double precision, parameter :: dtflux = 36000.d0 !fluxes after 10 h

	integer, save :: icall = 0		!0 first call, 1 on, -1 off
	integer, save :: iupart = 0		!unit of lgrdbg.part.NN.txt
	integer, save :: iuflux = 0		!unit of lgrdbg.flux.NN.txt
	integer, save :: iuflux3 = 0		!unit of lgrdbg.flux3.NN.txt
	integer, save :: iunode = 0		!unit of lgrdbg.node.NN.txt
	logical, save :: bflux = .false.	!flux and node files written

	integer :: i,ie,ii,k,ieg,ng
	double precision :: x,y,xi(3)
	character(len=1) :: what

	if( icall < 0 ) return

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
	    call xi2xy(ie,x,y,xi)
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
     &		,lgr_ncross(i)
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

 1000	format(a1,f14.1,i11,2es25.16e3,es17.8e2,i6,i11,i6,i6)
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
