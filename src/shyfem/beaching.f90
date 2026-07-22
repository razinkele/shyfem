
!--------------------------------------------------------------------------
!
!    Copyright (C) 2025-2026  Georg Umgiesser
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

! routines for simulating beaching of tracers
!
! ported from the shyfemcm community model (pnrr branch,
! commits d1283711..928c676f, 11/2025-05/2026, ggu) with these
! adaptations: activation and preset selection through the new STR
! parameter |ibeach| (upstream sniffed the basin from nkn_global and
! was enabled by editing a source default), collective-safe aborts,
! checked allocations, master-rank printing
!
! beaching: nodes on material (closed) boundaries lose a fraction of
! surface-layer tracer per time step into a per-node beach store
! burial:   nodes lose a fraction of bottom-layer tracer per time step
! into a per-node burial store
! rates are looked up per element area code from presets; both stores
! are written with the conz output frequency (itmcon/idtcon) and reset
! after each write, so records are accumulations over the output window
!
! note: beach_value/burry_value are not part of the restart file - a
! restart in the middle of an output window loses that window's partial
! accumulation (conzv itself is restart-safe)
!
! revision log :
!
! 12.11.2025    ggu     created from scratch
! 13.11.2025    ggu     added burrying
! 06.02.2026    ggu     routine made more general (rates for single area codes)
! 05.05.2026    ggu     more documentation, bug fix for iconz == 1
! 22.07.2026    arb     ported to razinkele/shyfem; ibeach STR parameter
!
!**************************************************************

!==============================================================
	module mod_beaching
!==============================================================

	implicit none

	logical, save :: bbeach = .false.
	logical, save :: bbeach_debug = .false.
	integer, save :: iudbg = 0

	integer, save, allocatable :: beach_node(:)
	integer, save, allocatable :: burry_node(:)
	integer, save, allocatable :: node_area_code(:)
	real, save, allocatable :: beach_value(:,:)
	real, save, allocatable :: burry_value(:,:)
	real, save, allocatable :: beach_rates(:)
	real, save, allocatable :: burry_rates(:)
	double precision, save :: da_beach(5)
	character*80, save :: what_beach = 'none'

!==============================================================
	end module mod_beaching
!==============================================================

!**************************************************************

	subroutine beaching_init

! initialization of the beaching algorithm

	use basin
	use mod_beaching
	use shympi
	use mod_geom
	use mod_conz
	use para

	implicit none

	integer ibeach
	integer nvar,ivar,id,ierr
	logical b2d
	double precision dtime
	character*10 type

	logical has_output_d

	real, allocatable :: value(:)

!-----------------------------------------------------------------
! read STR parameter and select rate preset
!-----------------------------------------------------------------

	ibeach = nint(getpar('ibeach'))
	if( ibeach == 0 ) return

	if( ibeach == 1 ) then
	  what_beach = 'curonian'
	else if( ibeach == 2 ) then
	  what_beach = 'danube'
	else
	  write(6,*) 'beaching algorithm: unknown ibeach = ',ibeach
	  write(6,*) 'valid values: 0 (off), 1 (curonian), 2 (danube)'
	  call shympi_abort_internal('error stop beaching_init: ibeach')
	end if

	bbeach = .true.

!-----------------------------------------------------------------
! initialize beach/burry values, rates, and node_area_code
!-----------------------------------------------------------------

	nvar = iconz
	b2d = .true.

	if( nvar <= 1 ) then
	  write(6,*) 'cannot run beaching algorithm for iconz <= 1'
	  write(6,*) 'please set iconz at least to 2'
	  call shympi_abort_internal('error stop beaching_init: iconz <= 1')
	end if

	if( shympi_is_master() ) then
	  write(6,*) 'setting up beaching algorithm for ',trim(what_beach)
	  write(6,*) 'running for nvar = ',nvar
	end if

	! debug file only on the master rank; bbeach_debug stays the
	! all-ranks gate so collective reductions in beaching_run are
	! entered by every rank
	if( bbeach_debug .and. shympi_is_master() ) then
	  open(newunit=iudbg,file='beaching_debug.dat',status='replace' &
     &		,iostat=ierr)
	  if( ierr /= 0 ) iudbg = 0
	end if

	allocate(node_area_code(nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_init: allocation')
	end if
	allocate(beach_value(nkn,nvar),burry_value(nkn,nvar),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_init: allocation')
	end if
	beach_value = 0
	burry_value = 0

	call shympi_barrier
	call beaching_rate_setup
	call shympi_barrier
	call beaching_node_setup
	call shympi_barrier

	if( .not. bbeach ) then
	  if( shympi_is_master() ) then
	    write(6,*) 'no beaching requested or all rates are zero'
	  end if
	  return	!don't create empty output files
	end if

!-----------------------------------------------------------------
! initialize output files
!-----------------------------------------------------------------

	call init_output_d('itmcon','idtcon',da_beach)
	if( has_output_d(da_beach) ) then
	  call shyfem_init_scalar_file('beach',nvar,b2d,id)
	  da_beach(4) = id
	  call shyfem_init_scalar_file('burry',nvar,b2d,id)
	  da_beach(5) = id
	end if

!-----------------------------------------------------------------
! debug output: show beaching nodes
!-----------------------------------------------------------------

	if( .not. bbeach_debug ) return

	allocate(value(nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_init: allocation')
	end if
	type = 'beachi'
	dtime = 0.
	value = beach_node	!transfer integer to real

	nvar = 1
	ivar = 75		!general index

	call shyfem_init_scalar_file(type,nvar,b2d,id)
	call shy_write_scalar2d(id,type,dtime,nvar,ivar,value)
	call shy_close_output_file(id)

!-----------------------------------------------------------------
! end of routine
!-----------------------------------------------------------------

	end

!**************************************************************

	subroutine beaching_run

! this computes beaching and burrying during the simulation

	use basin
	use levels
	use mod_beaching
	use mod_conz
	use shympi

	implicit none

	logical bwrite
	integer k,ivar,id,iv,nvar,lmax,ia,ierr
	real cb,db,c1
	real cu,du,cl
	real beach_rate,burry_rate
	double precision dtime
	double precision cbsum,cusum
	real, allocatable :: cmax1(:),bmax(:),umax(:)
	character*20 aline

	logical next_output_d

	if( .not. bbeach ) return

	bwrite = iudbg > 0	!iudbg is only ever opened on the master

!-----------------------------------------------------------------
! loop over nodes and compute beach_value and burry_value
!-----------------------------------------------------------------

	nvar = iconz
	cbsum = 0.
	cusum = 0.

	do k=1,nkn
	  lmax = ilhkv(k)
	  ia = node_area_code(k)
	  beach_rate = beach_rates(ia)
	  burry_rate = burry_rates(ia)
	  do iv=1,nvar
	    if( beach_node(k) > 0 ) then
	      c1 = conzv(1,k,iv)
	      cb = beach_value(k,iv)
	      db = beach_rate * c1
	      c1 = c1 - db
	      cb = cb + db
	      conzv(1,k,iv) = c1
	      beach_value(k,iv) = cb
	      cbsum = cbsum + cb
	    end if
	    if( burry_node(k) > 0 ) then
	      cl = conzv(lmax,k,iv)
	      cu = burry_value(k,iv)
	      du = burry_rate * cl
	      cl = cl - du
	      cu = cu + du
	      conzv(lmax,k,iv) = cl
	      burry_value(k,iv) = cu
	      cusum = cusum + cu
	    end if
	  end do
	end do

!-----------------------------------------------------------------
! debug output
!-----------------------------------------------------------------

	! the reductions are collectives - EVERY rank must enter this
	! block (gate on bbeach_debug), only the master rank writes
	if( bbeach_debug ) then
	  allocate(cmax1(nvar),bmax(nvar),umax(nvar),stat=ierr)
	  if( ierr /= 0 ) then
	    call shympi_abort_internal('error stop beaching_run: allocation')
	  end if
	  do iv=1,nvar
	    cmax1(iv) = maxval(conzv(1,:,iv))
	    bmax(iv) = maxval(beach_value(:,iv))
	    umax(iv) = maxval(burry_value(:,iv))
	    cmax1(iv) = shympi_max(cmax1(iv))
	    bmax(iv) = shympi_max(bmax(iv))
	    umax(iv) = shympi_max(umax(iv))
	  end do
	  if( bwrite ) then
	    call get_act_dtime(dtime)
	    call get_act_timeline(aline)
	    write(iudbg,*) 'bsum: ',aline,cbsum,cusum
	    do iv=1,nvar
	      write(iudbg,*) iv,bmax(iv),umax(iv),cmax1(iv)
	    end do
	    flush(iudbg)
	  end if
	end if

!-----------------------------------------------------------------
! output to file
!-----------------------------------------------------------------

	if( next_output_d(da_beach) ) then
	  call get_act_dtime(dtime)
	  id = nint(da_beach(4))
	  do iv=1,nvar
	    ivar = 300 + iv
	    call shy_write_scalar_record2d(id,dtime,ivar,beach_value(:,iv))
	  end do
	  id = nint(da_beach(5))
	  do iv=1,nvar
	    ivar = 300 + iv
	    call shy_write_scalar_record2d(id,dtime,ivar,burry_value(:,iv))
	  end do
	  beach_value = 0
	  burry_value = 0
	end if

!-----------------------------------------------------------------
! end of routine
!-----------------------------------------------------------------

	end

!**************************************************************
!**************************************************************
!**************************************************************

	subroutine beaching_node_setup

	use basin
	use mod_beaching
	use mod_geom
	use shympi

	implicit none

	integer ie,ia,ii,k,ierr
	integer ibeach,iburry
	integer iamax,ian,iantot
	integer, allocatable :: ianode(:)

	logical is_open_boundary_node

	if( shympi_is_master() ) then
	  write(6,*) 'setting up beaching nodes for ',trim(what_beach)
	end if

!----------------------------------------------
! create nodal code from area code
!----------------------------------------------

	iamax = -1
	node_area_code = -1

	do ie=1,nel
	  ia = iarv(ie)
	  iamax = max(iamax,ia)
	  do ii=1,3
	    k = nen3v(ii,ie)
	    node_area_code(k) = max(node_area_code(k),ia)
	  end do
	end do
	iamax = shympi_max(iamax)

	do k=1,nkn
	  if( node_area_code(k) < 0 ) then
	    write(6,*) 'node without local element: k = ',k
	    call shympi_abort_internal('error stop beaching_node_setup:' &
     &				//' node without area code')
	  end if
	end do

	allocate(ianode(0:iamax),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_node_setup:' &
     &				//' allocation')
	end if
	ianode = 0
	do k=1,nkn_unique
	  ia = node_area_code(k)
	  ianode(ia) = ianode(ia) + 1
	end do

	if( shympi_is_master() ) then
	  write(6,*) 'statistics for node area code: '
	  write(6,*) '  area code       nodes'
	end if

	iantot = 0
	do ia=0,iamax
	  ian = shympi_sum(ianode(ia))
	  iantot = iantot + ian
	  if( shympi_is_master() ) then
	    write(6,*) ia,ian
	  end if
	end do
	if( iantot /= nkn_global ) then
	  write(6,*) 'total: ',iantot,nkn_global
	  call shympi_abort_internal('error stop beaching_node_setup:' &
     &				//' iantot/=nkn')
	end if

	call shympi_exchange_2d_node(node_area_code)

!----------------------------------------------
! set flag on node if beaching/burrying is possible
!----------------------------------------------

	allocate(beach_node(nkn),burry_node(nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_node_setup:' &
     &				//' allocation')
	end if

	beach_node = 0
	burry_node = 0

	do k=1,nkn
	  ia = node_area_code(k)
	  if( burry_rates(ia) > 0. ) burry_node(k) = 1
	  if( is_material_boundary_node(k) ) then
	    if( .not. is_open_boundary_node(k) ) then
	      if( beach_rates(ia) > 0. ) beach_node(k) = 1
	    end if
	  end if
	end do

	call shympi_exchange_2d_node(beach_node)
	call shympi_exchange_2d_node(burry_node)

	! count over unique nodes only - ghost nodes would be counted
	! once per rank that sees them, inflating the MPI statistic
	ibeach = count( beach_node(1:nkn_unique) == 1 )
	iburry = count( burry_node(1:nkn_unique) == 1 )

	ibeach = shympi_sum(ibeach)
	iburry = shympi_sum(iburry)

	if( shympi_is_master() ) then
	  write(6,*) 'beach and burry nodes: ',ibeach,iburry
	end if

!----------------------------------------------
! end of the routine
!----------------------------------------------

	end

!**************************************************************
!**************************************************************
!**************************************************************

	subroutine beaching_rate_setup

! sets up and checks beaching and burrying rates

	use basin
	use mod_beaching
	use shympi

	implicit none

	integer iamax,ie,ia,ierr
	real total_rate,max_rate

!----------------------------------------------
! sets up beach/burry rates
!----------------------------------------------

	if( shympi_is_master() ) then
	  write(6,*) 'setting up beaching rates for ',trim(what_beach)
	end if

	iamax = 0
	do ie=1,nel
	  ia = iarv(ie)
	  if( ia > iamax ) iamax = ia
	end do
	iamax = shympi_max(iamax)

	allocate(beach_rates(0:iamax),burry_rates(0:iamax),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('error stop beaching_rate_setup:' &
     &				//' allocation')
	end if

	beach_rates = 0
	burry_rates = 0

	if( what_beach == 'curonian' ) then
	  call beaching_rate_setup_curonian(iamax)
	else if( what_beach == 'danube' ) then
	  call beaching_rate_setup_danube(iamax)
	else
	  bbeach = .false.
	end if

	if( .not. bbeach ) return

!----------------------------------------------
! check and write out final rates for beach/burry
!----------------------------------------------

	if( shympi_is_master() ) then
	  write(6,*) 'final rates for beaching:'
	  write(6,*) '  area code   beach rate       burry rate' &
     &				//'       total rate'
	end if

	max_rate = 0.
	do ia=0,iamax
	  total_rate = beach_rates(ia) + burry_rates(ia)
	  max_rate = max(max_rate,total_rate)
	  if( shympi_is_master() ) then
	    write(6,*) ia,beach_rates(ia),burry_rates(ia),total_rate
	  end if
	  if( total_rate > 1. ) then
	    write(6,*) 'sum of beach_rate + burry_rate > 1 for ia = ',ia
	    call shympi_abort_internal('error stop beaching_rate_setup:' &
     &				//' rate too high')
	  end if
	end do

	if( max_rate == 0 ) bbeach = .false.	!no beach/burry needed

!----------------------------------------------
! end of the routine
!----------------------------------------------

	end

!**************************************************************

	subroutine beaching_rate_setup_danube(iamax)

! rate preset for the danube delta (ibeach = 2)

	use mod_beaching

	implicit none

	integer, intent(in) :: iamax

	! 0: razelm-sinoe lagoon
	! 1: black sea
	! 2: danube
	! 3: inter-connection danube - lagoon

	if( iamax >= 0 ) then
	  beach_rates(0) = 0.3
	  burry_rates(0) = 0.1
	end if
	if( iamax >= 1 ) then
	  beach_rates(1) = 0.3
	  burry_rates(1) = 0.1
	end if

	end

!**************************************************************

	subroutine beaching_rate_setup_curonian(iamax)

! rate preset for the curonian lagoon (ibeach = 1)

	use mod_beaching

	implicit none

	integer, intent(in) :: iamax

	! 0: baltic sea
	! 1: nemunas delta
	! 2: curonian lagoon
	! 3: reed belt

	if( iamax >= 2 ) then
	  beach_rates(2) = 0.2
	  burry_rates(2) = 0.1
	end if
	if( iamax >= 3 ) then
	  beach_rates(3) = 0.4
	  burry_rates(3) = 0.2
	end if

	end

!**************************************************************
