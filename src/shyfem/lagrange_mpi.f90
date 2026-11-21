
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
! lgr_mpi_flux_sum_3d		sum of partial side fluxes flux3d across ranks
! lgr_mpi_flux_sum_2d		sum of partial side fluxes flux2d across ranks
! lgr_mpi_flux_sum		common part of the two flux sums
! lgr_mpi_mark_export		mark particle for export to remote rank
! lgr_mpi_pack_particle		serialize particle to double buffer
! lgr_mpi_unpack_particle	deserialize particle from double buffer
! lgr_mpi_exchange		exchange particles between MPI ranks
! lgr_mpi_global_to_local_elem	convert global element to local
! lgr_mpi_gather_output		gather particles to rank 0 for output
! lgr_mpi_reduce_connect	reduce connectivity matrices
! lgr_mpi_reset_export		reset export buffers
! lgr_mpi_debug_dump		text dump of particles, fluxes, node arrays
! lgr_mpi_debug_open		open one debug dump file
! lgr_mpi_ghost_nodes		number of vertices of an element owned elsewhere

	module mod_lagrange_mpi

	use mod_lagrange

	implicit none

	integer, parameter :: lgr_pack_base = 13  !base fields per particle
	integer, save :: lgr_pack_size = 0        !total fields (base + ncust)

	integer, save :: n_export = 0
	integer, save, allocatable :: export_dest(:)    !dest rank per export
	integer, save, allocatable :: export_idx(:)     !particle index per export

	logical, save :: bmpi_lagr = .false.      !true if MPI active for lagrange

	! lists of local elements shared with other ranks (lgr_mpi_topology_init):
	! shared with rank r: lgr_share_elem(lgr_share_ptr(r)+1:lgr_share_ptr(r+1)),
	! sorted by ip_int_elem; lgr_nshare(r) = length of that stretch
	integer, save, allocatable :: lgr_nshare(:)       !(0:nproc-1)
	integer, save, allocatable :: lgr_share_ptr(:)     !(0:nproc)
	integer, save, allocatable :: lgr_share_elem(:)    !local element numbers

	contains

!*******************************************************************

	subroutine lgr_mpi_init

	use shympi

	implicit none

	integer :: ierr, ndim

	lgr_pack_size = lgr_pack_base + ncust
	bmpi_lagr = shympi_is_parallel()

	if( .not. bmpi_lagr ) return

	ndim = max(nbdymax, 1024)
	allocate(export_dest(ndim), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_init: allocation')
	allocate(export_idx(ndim), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_init: allocation')

	n_export = 0

	end subroutine lgr_mpi_init

!*******************************************************************

	subroutine lgr_mpi_topology_init

! builds, for every other rank r, the list of local elements shared with r
! (r is among id_elem(1:id_elem(0,ie),ie)), sorted by ip_int_elem
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

	subroutine lgr_mpi_mark_export(i, dest_rank)

! mark particle i for export to dest_rank

	implicit none

	integer, intent(in) :: i, dest_rank

!$OMP CRITICAL (lgr_export)
	n_export = n_export + 1
	if( n_export > size(export_idx) ) then
	  call shympi_abort_internal('lgr_mpi_mark_export: overflow')
	end if
	export_idx(n_export) = i
	export_dest(n_export) = dest_rank
!$OMP END CRITICAL (lgr_export)

	end subroutine lgr_mpi_mark_export

!*******************************************************************

	subroutine lgr_mpi_pack_particle(p, buf)

! serialize one particle into double precision buffer

	implicit none

	type(lagr_entry), intent(in) :: p
	double precision, intent(out) :: buf(lgr_pack_size)

	integer :: j

	buf(1)  = p%actual%xi(1)
	buf(2)  = p%actual%xi(2)
	buf(3)  = p%actual%xi(3)
	buf(4)  = p%actual%time
	buf(5)  = dble(p%actual%z)
	buf(6)  = dble(p%actual%ie_global)
	buf(7)  = dble(p%actual%l)
	buf(8)  = dble(p%id)
	buf(9)  = dble(p%type)
	buf(10) = p%sinking
	buf(11) = dble(p%bitmap_in)
	buf(12) = dble(p%bitmap_out)
	buf(13) = dble(ncust)

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

! deserialize particle from double precision buffer

	implicit none

	double precision, intent(in) :: buf(lgr_pack_size)
	type(lagr_entry), intent(out) :: p

	integer :: j, nc, ierr

	p%actual%xi(1) = buf(1)
	p%actual%xi(2) = buf(2)
	p%actual%xi(3) = buf(3)
	p%actual%time  = buf(4)
	p%actual%z     = real(buf(5))
	p%actual%ie_global = nint(buf(6))
	p%actual%l     = nint(buf(7))
	p%id           = nint(buf(8))
	p%type         = nint(buf(9))
	p%sinking      = buf(10)
	p%bitmap_in    = nint(buf(11))
	p%bitmap_out   = nint(buf(12))
	nc             = nint(buf(13))

	if( .not. allocated(p%custom) ) then
	  allocate(p%custom(nc), stat=ierr)
	  if (ierr /= 0) call shympi_abort_internal			&
     &		('lgr_mpi_unpack: allocation')
	end if
	do j = 1, nc
	  p%custom(j) = real(buf(lgr_pack_base + j))
	end do

	p%actual%ie = 0		!resolved by caller
	p%init = p%actual

	end subroutine lgr_mpi_unpack_particle

!*******************************************************************

	subroutine lgr_mpi_exchange

! exchange particles between MPI ranks after advection
!
! 1. count exports per destination rank
! 2. exchange counts (MPI_Alltoall)
! 3. pack outgoing particles
! 4. exchange particle data (MPI_Alltoallv)
! 5. unpack received particles, resolve local element IDs
! 6. remove exported particles from local array

	use shympi
	use basin, only : nel

	implicit none

	include 'mpif.h'

	integer :: i, j, ip, ierr, irank
	integer :: n_recv_total
	integer :: nproc, myrank
	integer :: ie_global, ie_local

	integer, allocatable :: send_counts(:), recv_counts(:)
	integer, allocatable :: send_displs(:), recv_displs(:)
	integer, allocatable :: send_data_counts(:), recv_data_counts(:)
	double precision, allocatable :: send_buf(:), recv_buf(:)

	nproc = n_threads
	myrank = my_id

	if( nproc <= 1 ) return

	allocate(send_counts(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(recv_counts(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(send_displs(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(recv_displs(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(send_data_counts(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(recv_data_counts(0:nproc-1), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')

	!-----------------------------------------------
	! 1. Count exports per destination rank
	!-----------------------------------------------

	send_counts = 0
	do i = 1, n_export
	  irank = export_dest(i)
	  if( irank >= 0 .and. irank < nproc ) then
	    send_counts(irank) = send_counts(irank) + 1
	  end if
	end do

	!-----------------------------------------------
	! 2. Exchange particle counts
	!-----------------------------------------------

	call MPI_Alltoall(send_counts, 1, MPI_INTEGER,			&
     &		recv_counts, 1, MPI_INTEGER,				&
     &		MPI_COMM_WORLD, ierr)

	!-----------------------------------------------
	! 3. Compute displacements and pack
	!-----------------------------------------------

	send_displs(0) = 0
	recv_displs(0) = 0
	do i = 1, nproc - 1
	  send_displs(i) = send_displs(i-1)				&
     &		+ send_counts(i-1) * lgr_pack_size
	  recv_displs(i) = recv_displs(i-1)				&
     &		+ recv_counts(i-1) * lgr_pack_size
	end do

	do i = 0, nproc - 1
	  send_data_counts(i) = send_counts(i) * lgr_pack_size
	  recv_data_counts(i) = recv_counts(i) * lgr_pack_size
	end do

	allocate(send_buf(max(sum(send_data_counts),1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')
	allocate(recv_buf(max(sum(recv_data_counts),1)), stat=ierr)
	if (ierr /= 0) call shympi_abort_internal('lgr_mpi_exchange: alloc')

	! Pack sorted by destination rank (recount)
	send_counts = 0
	do i = 1, n_export
	  irank = export_dest(i)
	  if( irank < 0 .or. irank >= nproc ) cycle
	  ip = export_idx(i)
	  j = send_displs(irank) + send_counts(irank) * lgr_pack_size
	  call lgr_mpi_pack_particle(lgr_ar(ip),			&
     &		send_buf(j+1:j+lgr_pack_size))
	  send_counts(irank) = send_counts(irank) + 1
	end do

	!-----------------------------------------------
	! 4. Exchange particle data
	!-----------------------------------------------

	call MPI_Alltoallv(send_buf, send_data_counts, send_displs,	&
     &		MPI_DOUBLE_PRECISION,					&
     &		recv_buf, recv_data_counts, recv_displs,		&
     &		MPI_DOUBLE_PRECISION,					&
     &		MPI_COMM_WORLD, ierr)

	!-----------------------------------------------
	! 5. Unpack received particles
	!-----------------------------------------------

	n_recv_total = sum(recv_counts)

	do i = 1, n_recv_total
	  j = (i - 1) * lgr_pack_size
	  nbdy = nbdy + 1
	  call mod_lagrange_handle_alloc(nbdy)
	  call lgr_mpi_unpack_particle(recv_buf(j+1:j+lgr_pack_size),	&
     &		lgr_ar(nbdy))
	  ie_global = lgr_ar(nbdy)%actual%ie_global
	  call lgr_mpi_global_to_local_elem(ie_global, ie_local)
	  lgr_ar(nbdy)%actual%ie = ie_local
	  lgr_ncross(nbdy) = -1		!unknown: the count is not sent yet
	end do

	!-----------------------------------------------
	! 6. Mark exported particles as transferred
	!-----------------------------------------------

	do i = 1, n_export
	  ip = export_idx(i)
	  lgr_ar(ip)%actual%ie = 0	!mark as dead/transferred
	end do

	n_export = 0

	deallocate(send_counts, recv_counts)
	deallocate(send_displs, recv_displs)
	deallocate(send_data_counts, recv_data_counts)
	deallocate(send_buf, recv_buf)

	end subroutine lgr_mpi_exchange

!*******************************************************************

	subroutine lgr_mpi_global_to_local_elem(ie_global, ie_local)

! convert global element ID to local element ID on this rank

	use shympi
	use basin, only : nel

	implicit none

	integer, intent(in) :: ie_global
	integer, intent(out) :: ie_local

	integer :: ie

	ie_local = 0
	do ie = 1, nel
	  if( ip_int_elem(ie) == ie_global ) then
	    ie_local = ie
	    return
	  end if
	end do

	write(6,*) 'warning: lgr_mpi elem not found: ',ie_global
	ie_local = -1

	end subroutine lgr_mpi_global_to_local_elem

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

	subroutine lgr_mpi_check_ghost(i, ie)

! check if particle i is in a ghost element and mark for export

	use shympi

	implicit none

	integer, intent(in) :: i, ie
	integer :: owner_rank

	if( .not. bmpi_lagr ) return

	owner_rank = id_elem(1,ie)
	if( owner_rank /= my_id ) then
	  call lgr_mpi_mark_export(i, owner_rank)
	end if

	end subroutine lgr_mpi_check_ghost

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

	subroutine lgr_mpi_debug_dump(dtime)

! debug dump of particles, side fluxes and node arrays (levdbg >= 3)
!
! NN = rank (my_id). Every file starts with the line "# rank R of N"
! (R = my_id, N = number of processes). At the first call of a run all
! files are replaced, so that none is left from an older run: part, flux
! and node always, flux3 in a 3D run; in a 2D run an old flux3 file is
! deleted. Flux, flux3 and node keep only their header if the run ends
! before 10 h.
!
! lgrdbg.part.NN.txt: at every particle output, one line per array entry
!	class time id x y z lb ie_global rank ncross
!   class P: element with only own nodes, M: mixed element (a vertex owned
!   by another rank) this rank is the main owner of, G: mixed element
!   owned elsewhere, D: entry with ie <= 0 (x = y = 0, ie_global = 0 for
!   ie = 0, -global element for ie < 0); lb = layer; ncross = lgr_ncross(i)
!   (-1 = unknown, for a particle received from another rank in the
!   last time step)
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
