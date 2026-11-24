
!--------------------------------------------------------------------------
!
!    Copyright (C) 2015,2019  Georg Umgiesser
!    Copyright (C) 2015  Erik Pascolo
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

! routines to create subsets for OMP
!
! contents :
!
! revision log :
!
! 01.09.2015	erp	code written from scratch
! 18.09.2015	ggu	code integrated
! 29.09.2015	ggu	new routine which is much faster
! 30.09.2015	ggu	new routine domain_clusterization_dummy()
! 05.10.2015	ggu	equilibrate subset filling
! 12.10.2015	ggu	changed VERS_7_3_3
! 16.11.2015	ggu	changed VERS_7_3_14
! 16.02.2019	ggu	changed VERS_7_5_60
! 13.03.2019	ggu	changed VERS_7_5_61
! 24.11.2026	arb	colors made on the global mesh: every process has
!			the element colors of a serial run (#263)
! 24.11.2026	arb	subset_order_dump: debug dump of the element order
!			at the own nodes (SHYFEM_SUBSET_DUMP, #263)
!
!***********************************************************
!***********************************************************
!***********************************************************

!==================================================================
        module mod_subset
!==================================================================

        implicit none

        integer, save :: subset_num		!total number of subsets
        integer, save :: max_sharing_node  

        integer,save,allocatable,dimension(:)   :: subset_el !elems in subset
        integer,save,allocatable,dimension(:,:) :: indipendent_subset !elems
        integer,save,allocatable,dimension(:,:) :: nodes_map
        integer,save,allocatable,dimension(:,:) :: nodes_counter

!==================================================================
        contains
!==================================================================

      subroutine domain_clusterization

      use basin

      !call domain_clusterization_eric
      call domain_clusterization_ggu
      !call domain_clusterization_dummy

      call subset_order_dump	!only with SHYFEM_SUBSET_DUMP set

      end subroutine domain_clusterization

!***********************************************************

      subroutine domain_clusterization_eric

!$	use omp_lib
	use basin

      implicit none

      integer :: ie,ik,i,j,k,n,m,a,b,c
      integer :: row_cluster
      integer :: numsubset,start,subset_lenght
      integer :: sum_subset_lenght
      integer :: max_subset_lenght
      integer :: max_l,min_l
      integer :: ierr
      logical :: not_contained,stop_criterion
      integer,allocatable,dimension(:) :: subset
      integer, dimension(2) :: temp
      double precision :: timer
      
      !----------------------------------------------
      !! CREATE NODE COUNTER  
      !----------------------------------------------
      
      print *,"  ----------- STARTING DOMAIN CLUSTERING -----------"

      allocate(nodes_counter(2,nkn),stat=ierr)
      if( ierr /= 0 ) stop 'error stop: allocation failed'
            
      nodes_counter = 0
     
      do ie=1,nel
         nodes_counter(1,nen3v(1,ie)) = nen3v(1,ie)
	 nodes_counter(2,nen3v(1,ie)) = nodes_counter(2,nen3v(1,ie))+1
	 nodes_counter(1,nen3v(2,ie)) = nen3v(2,ie)
	 nodes_counter(2,nen3v(2,ie)) = nodes_counter(2,nen3v(2,ie))+1
	 nodes_counter(1,nen3v(3,ie)) = nen3v(3,ie)
	 nodes_counter(2,nen3v(3,ie)) = nodes_counter(2,nen3v(3,ie))+1
      enddo
      
      max_sharing_node = MAXVAL(nodes_counter(2,:))
      
      !! sort nodes_counter in descending order

      DO j = 1,nkn-1
	DO k = j+1,nkn
	  IF(nodes_counter(2,j) .lt. nodes_counter(2,k)) THEN
	  temp = nodes_counter(:,k)
	  nodes_counter(:,k) =nodes_counter(:,j)
	  nodes_counter(:,j) = temp
	  ENDIF
	END DO 
      END DO 

      !----------------------------------------------
      !! END CREATE NODE COUNTER
      !----------------------------------------------
      
      !----------------------------------------------
      !! CREATE ELEMENTS MAPS
      !----------------------------------------------
      
      allocate(nodes_map(0:max_sharing_node,nkn),stat=ierr)
      if( ierr /= 0 ) stop 'error stop: allocation failed'
      nodes_map = 0
      
      do i=1,nkn
	n = 1
	nodes_map(0,i) = i
	do j=1,nel
	  
	  if(nen3v(1,j) .eq. i .OR. nen3v(2,j) .eq. i .OR. nen3v(3,j) .eq. i) then
	    nodes_map(n,i) = j
	    n = n+1
	  endif
	  
	end do
      end do
      
      !----------------------------------------------
      !! END CREATE ELEMENTS MAPS
      !----------------------------------------------
      
      print *,"  ----------- DOMAIN CLUSTERING INFORMATION -----------"
      print *,"  NUM NODES = ",nkn," NUM ELEMENTS = ",nel
      print *,"  MAX LINK = ",max_sharing_node
      
      !----------------------------------------------
      !! GREEDY LOOP
      !----------------------------------------------
      
      allocate(subset(nel),stat=ierr)
      if( ierr /= 0 ) stop 'error stop: allocation failed'
      
!$    timer = omp_get_wtime()
      
      subset = 0
      numsubset = 1
      max_subset_lenght = 0
      sum_subset_lenght = 0
      start = 1
      stop_criterion = .true.
      
      do while(stop_criterion)  
            
      call greedy_subset(start,numsubset,subset_lenght,subset,    &
      &                       nel,max_l,min_l)
      
      print *,"  SUBSET = ",numsubset," LENGTH = ",subset_lenght
      
      max_subset_lenght = MAX(max_subset_lenght,subset_lenght)
      sum_subset_lenght = sum_subset_lenght + subset_lenght
      
      stop_criterion = .false.
      
     	do a=1,nel
	  IF(subset(a) == 0) then
	      start = a
	      stop_criterion = .true.
	      numsubset = numsubset + 1
	      exit
	  endif
        end do 
            
      end do
      
      !----------------------------------------------
      !! END GREEDY LOOP
      !----------------------------------------------
     
!$     timer = omp_get_wtime() - timer
      
      !----------------------------------------------
      !! CREATE INDIPENDENT SUBSET MATRIX
      !----------------------------------------------

      subset_num = numsubset
      allocate(indipendent_subset(max_subset_lenght,subset_num),stat=ierr)
      if( ierr /= 0 ) stop 'error stop: allocation failed'
      allocate(subset_el(subset_num),stat=ierr)
      if( ierr /= 0 ) stop 'error stop: allocation failed'
      indipendent_subset = 0
  
     !! fill subset matrix loop     
      do i=1,subset_num
	  n = 1
	  do j = 1,nel
	      if(subset(j) == i) then
		indipendent_subset(n,i) = j
		n = n+1
	      endif
	    enddo
	    subset_el(i) = n-1
      enddo
      
      print *,"  NUM ITERATION GREEDY ALGO = ",numsubset
      print *,"  SUM SUBSET LENGTH = ",sum_subset_lenght
      print *,"  MAX LENGTH SUBSET = ",max_subset_lenght
      print *,"  TIME GREEDY = ",timer
      
      !----------------------------------------------
      ! controll if subset is indipendent
      !----------------------------------------------

      call check_subset(subset,max_subset_lenght,nel)
      
      print *,"  -----------------------------------------------------"
      
      deallocate(subset)
     
      end subroutine domain_clusterization_eric

!***********************************************************
      
      subroutine greedy_subset(start,numsubset,subset_lenght,subset     &
      &                           ,nel,max_l,min_l)
      
      implicit none
      
      integer,intent(in) :: nel,start,numsubset
      integer,intent(out) :: subset_lenght,max_l,min_l
      integer :: i,j,k,jend,jel,check_indipendency_global
      integer :: check_indipendency_local
      integer,dimension(:),intent(inout) :: subset

      max_l = 0
      min_l = 1000
      subset(start) = numsubset
      subset_lenght = 1
      check_indipendency_global = 0
      
      do i = 1,nel 
	
	! check if the element is just added
	if( subset(i) == 0 ) then
	
	 check_indipendency_global = 0
	  
	   ! loop on just assigned element
!$OMP PARALLEL DO PRIVATE(j) &
!$OMP& FIRSTPRIVATE(numsubset,i) DEFAULT(NONE) &
!$OMP& SHARED(subset,nel) SCHEDULE(GUIDED) &
!$OMP& REDUCTION(+:check_indipendency_global)
	   do j=1,nel
	   
            ! check all elements that have the same numsubset 
	      if(subset(j) == numsubset)then
	    
		! check indipendency with other subset element
		if(indipendent_element(i,j) .eqv. .false.) then
		  check_indipendency_global=check_indipendency_global+1
		endif
	      
	      endif
	   
	  enddo
!$OMP END PARALLEL DO

	  ! if all elements in subset is indipendent add el i
	  if(check_indipendency_global == 0) then
	    subset(i) = numsubset
	    subset_lenght = subset_lenght + 1
	   
	  endif
	  
	endif
            
      enddo
      
      end subroutine greedy_subset

!***********************************************************

      logical function indipendent_element(i,j)
      
	use basin, only : nen3v

      implicit none
      
      integer,intent(in) :: i,j
      integer :: a,b,c
      !logical :: indipendent_element
      
      indipendent_element = .true.
      	   
 	      do b = 1,3
 	       do c = 1,3
		if(nen3v(b,i) .eq. nen3v(c,j)) then
 		indipendent_element = .false.
 		endif
 	      enddo
 	    enddo
      
      end function indipendent_element
      
!***********************************************************

      subroutine check_subset(elem,max_subset_el,nel)
      
      implicit none
      integer, intent(in) :: nel,max_subset_el
      integer,intent(inout),dimension(:) :: elem
      integer :: ie,ik,i,j,k,n,m
      
      do i=1,nel
	 IF(elem(i) .eq. 0) then
	 print *,"ERROR ",i," is not set"
	 endif
      enddo
      
      do i=1,subset_num

	do j=1,subset_el(i)
	  
	  ie = indipendent_subset(j,i)
	  
	  do k=1,subset_el(i)
	  
	  if( k .ne. j ) then
	    
	    ik = indipendent_subset(k,i)
 	    if (indipendent_element(ie,ik) .neqv. .true.) then
	       print *,"  ERROR SUBSET NOT INDEPENDENT",i,ie,ik
	       stop 'error stop subset: subsets not independent'
	    endif
	    
	   endif
	  
	  enddo
	  
	enddo
      enddo

      print *,"  ALL SUBSETS ARE INDIPENDENT"
      
      end subroutine check_subset

!***********************************************************
!***********************************************************
!***********************************************************

	subroutine domain_clusterization_ggu

! colors the elements (no two elements of one color share a node) and
! fills the subsets with the local elements of every color
!
! The colors are made on the global mesh (nen3v_global) and every local
! element takes the color of its global element (ip_int_elem), so that
! each process has the colors of a serial run (#263). conz3d_omp (and
! hydro_zeta, with every solver but PETSc) adds the contributions of the
! elements around a node subset after subset, and an element of a subset
! gives a node at most one contribution, so the colors alone decide the
! order of the additions at a node. With colors
! made on the local domain of each process a node got them in another
! order than in a serial run: the double precision sums differed in the
! last bits and the scalars, cast to single precision, now and then
! rounded to the next value. In a serial run the global mesh is the local
! mesh (ip_int_elem(ie) = ie) and the colors are the same as before.

	use basin
	use shympi, only : nkn_global,nel_global,nen3v_global	&
     &			,ip_int_node,ip_int_elem

	implicit none

        !integer, save :: subset_num		!total number of subsets
        !integer,save,allocatable,dimension(:)   :: subset_el !elems in subset
        !integer,save,allocatable,dimension(:,:) :: indipendent_subset !elems

	integer ie,ii,k,ieg
	integer ncol,nmax,ncolor,naver
	integer ic,n,ntot
	integer ierr
	integer nkg,neg			!nodes and elements of the global mesh
	integer, allocatable :: colork(:)	!colors on global node (bits)
	integer, allocatable :: color(:)	!color of global element
	integer, allocatable :: colorl(:)	!color of local element
	integer, allocatable :: mark(:)		!last color on local node

	nkg = nkn_global
	neg = nel_global

	if( size(nen3v_global,1) /= 3 .or. size(nen3v_global,2) /= neg ) then
	  write(6,*) 'nen3v_global: ',shape(nen3v_global),' nel_global: ',neg
	  call shympi_abort_internal( &
     &		'domain_clusterization_ggu: nen3v_global is not global')
	end if

	allocate(colork(nkg),color(neg),colorl(nel),mark(nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal( &
     &		'domain_clusterization_ggu: allocation failed')
	end if

	nmax = 0
	color = 0
	colork = 0

        print *,"  ----------- STARTING DOMAIN CLUSTERING -----------"

!	-------------------------------------------
!	check that every local element is its global element
!	-------------------------------------------

	do ie=1,nel
	  ieg = ip_int_elem(ie)
	  if( ieg < 1 .or. ieg > neg ) then
	    write(6,*) 'local element, global element: ',ie,ieg,neg
	    call shympi_abort_internal( &
     &		'domain_clusterization_ggu: global element out of range')
	  end if
	  do ii=1,3
	    if( ip_int_node(nen3v(ii,ie)) /= nen3v_global(ii,ieg) ) then
	      write(6,*) 'local element, global element: ',ie,ieg
	      write(6,*) 'local nodes as global: ',ip_int_node(nen3v(:,ie))
	      write(6,*) 'global nodes: ',nen3v_global(:,ieg)
	      call shympi_abort_internal( &
     &		'domain_clusterization_ggu: local and global element differ')
	    end if
	  end do
	end do

!	-------------------------------------------
!	color the elements of the global mesh
!	-------------------------------------------

	call compute_color(ncolor,nmax)
	naver = nint(neg/float(ncolor))
	write(6,*) 'ncolor=',ncolor,' average=',naver,' nmax=',nmax

!	-------------------------------------------
!	set parameters and allocate arrays
!	-------------------------------------------

	subset_num = ncolor
	allocate(subset_el(subset_num),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal( &
     &		'domain_clusterization_ggu: allocation failed')
	end if
	subset_el = 0

	call compute_subset_filling(nmax)	!sets subset_el (global)

!	-------------------------------------------
!	adjust colors
!	-------------------------------------------

	call adjust_color

!	-------------------------------------------
!	check colors
!	-------------------------------------------

	call check_color

!	-------------------------------------------
!	local elements take the color of their global element
!	-------------------------------------------

	do ie=1,nel
	  colorl(ie) = color(ip_int_elem(ie))
	end do

!	-------------------------------------------
!	transfer complete information to arrays
!	-------------------------------------------

	nmax = 0
	subset_el = 0
	do ie=1,nel
	  ic = colorl(ie)
	  subset_el(ic) = subset_el(ic) + 1
	  nmax = max(nmax,subset_el(ic))
	end do

	allocate(indipendent_subset(nmax,subset_num),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal( &
     &		'domain_clusterization_ggu: allocation failed')
	end if
	subset_el = 0
	indipendent_subset = 0

	do ie=1,nel
	  ic = colorl(ie)
	  n = subset_el(ic) + 1
	  if( n > nmax ) then
	    write(6,*) 'n,nmax: ',n,nmax
	    call shympi_abort_internal( &
     &		'domain_clusterization_ggu: intern (1)')
	  end if
	  indipendent_subset(n,ic) = ie
	  subset_el(ic) = n
	end do

!	-------------------------------------------
!	check that the local subsets are independent
!	-------------------------------------------

	mark = 0
	do ic=1,subset_num
	  do n=1,subset_el(ic)
	    ie = indipendent_subset(n,ic)
	    do ii=1,3
	      k = nen3v(ii,ie)
	      if( mark(k) == ic ) then
	        write(6,*) 'subset, element, node: ',ic,ie,k
	        call shympi_abort_internal( &
     &		  'domain_clusterization_ggu: local subset not independent')
	      end if
	      mark(k) = ic
	    end do
	  end do
	end do

!	-------------------------------------------
!	write to terminal
!	-------------------------------------------

        print *,"  ---------- DOMAIN CLUSTERING INFORMATION ----------"
        print *,"  NUM NODES = ",nkn," NUM ELEMENTS = ",nel
        print *,"  NUMBER OF SUBSETS = ",subset_num
        ntot = 0
        do ic=1,subset_num
  	  n = subset_el(ic)
	  ntot = ntot + n
          print *,"  SUBSET = ",ic," LENGTH = ",n
        end do
        print *,"  SUM SUBSET LENGTH = ",ntot

	if( ntot /= nel ) then
	  write(6,*) 'ntot,nel: ',ntot,nel
	  write(6,*) 'error in total length of subsets'
	  call shympi_abort_internal( &
     &		'domain_clusterization_ggu: internal error (1)')
	end if

!	-------------------------------------------
!	end of routine
!	-------------------------------------------

	deallocate(colork,color,colorl,mark)

	contains

!***********************

	subroutine compute_ic_minmax(icmin,icmax)

	integer icmin,icmax

	integer ic,n
	integer ncmin,ncmax

	ncmin = neg
	ncmax = 0
	icmin = 0
	icmax = 0

	do ic=1,subset_num
	  n = subset_el(ic)
	  if( n > ncmax ) then
	    ncmax = n
	    icmax = ic
	  end if
	  if( n < ncmin ) then
	    ncmin = n
	    icmin = ic
	  end if
	end do

	end subroutine compute_ic_minmax

!***********************

	subroutine compute_subset_filling(nmax)

	integer nmax

	integer ie,ic,n

	nmax = 0
	subset_el = 0

	do ie=1,neg
	  ic = color(ie)
	  n = subset_el(ic) + 1
	  nmax = max(nmax,n)
	  subset_el(ic) = n
	end do

	end subroutine compute_subset_filling

!***********************

	subroutine adjust_color

	logical bdebug
	integer ic
	integer icmin,icmax,ncolor
	integer ncmin,ncmax
	integer naver,nemax
	integer ie_start

	bdebug = .false.
	ie_start = 0
	ncolor = subset_num
	naver = nint(neg/float(ncolor))
	icmax = 1
	icmin = ncolor

	write(6,'(20i6)') (subset_el(ic),ic=1,ncolor)

	do

	  call compute_ic_minmax(icmin,icmax)
	  ncmin = subset_el(icmin)
	  ncmax = subset_el(icmax)
	  nemax = min(ncmax-naver,naver-ncmin)
	  if( bdebug ) write(6,*) 'exchanging colors: ',icmin,icmax
	  if( bdebug ) write(6,*) 'aver and max changes: ',naver,nemax

	  call apply_one_color(icmax,icmin,ie_start,nemax,ncol)

	  call compute_subset_filling(nmax)	!sets subset_el

	  write(6,'(20i6)') (subset_el(ic),ic=1,ncolor)
	  if( bdebug ) write(6,*) 'changes done and max: ',ncol,nmax

	  if( ncol == 0 ) exit

	end do

	write(6,*) 'difference in filling: ',ncmin,ncmax,ncmax-ncmin
	end subroutine adjust_color

!***********************

	subroutine compute_color(ncolor,nmax)

	integer ncolor,nmax

	integer ncol,ic_new,ic_old
	integer ie_start,nemax

	nmax = 0
	ic_new = 0
	ic_old = 0
	ie_start = 0
	nemax = neg

	color = 0
	colork = 0

	do
	  ic_new = ic_new + 1
	  if( ic_new > 31 ) then
	    call shympi_abort_internal('compute_color: no more bytes')
	  end if
	  call apply_one_color(ic_old,ic_new,ie_start,nemax,ncol)
	  nmax = max(nmax,ncol)
	  if( ncol == 0 ) exit		!everything colored
	end do

	ncolor = ic_new - 1

	end subroutine compute_color

!***********************

	subroutine apply_one_color(ic_old,ic_new,ie_start,nemax,ncol)

	integer ic_old,ic_new	!colors to use
	integer ie_start	!starting point for ie
	integer nemax		!at most color this number of elements
	integer ncol		!how many elements colored

	integer n,ie,iestride

	ncol = 0
	n = 0
	ie = ie_start
	iestride = 1

	do
	  n = n + 1
	  if( n > neg ) exit
	  if( ncol >= nemax ) exit
	  ie = ie + iestride
	  if( ie > neg ) ie = mod(ie,neg)
	  if( may_color(ie,ic_old,ic_new) ) then
	    ncol = ncol + 1
	    call color_elem(ie,ic_new)
	  end if
	end do
	
	ie_start = ie

	end subroutine apply_one_color

!***********************

	function may_color(ie,ic_from,ic_to)

	logical may_color
	integer ic_from,ic_to

	integer ie,ires
	integer ii,k

	may_color = .false.

	if( color(ie) /= ic_from ) return
	do ii=1,3
	  k = nen3v_global(ii,ie)
	  ires = ibits(colork(k),ic_to,1)
	  !if( colork(k) /= 0 ) return
	  if( ires /= 0 ) return
	end do

	may_color = .true.

	end function may_color

!***********************

	subroutine color_elem(ie,ic_new)

	integer ie,ic_new

	integer ii,k,ic_old
	integer col

	ic_old = color(ie)
	color(ie) = ic_new
	do ii=1,3
	  k = nen3v_global(ii,ie)
	  col = colork(k)
	  col = ibclr(col,ic_old)
	  col = ibset(col,ic_new)
	  colork(k) = col
	end do

	end subroutine color_elem

!***********************

	subroutine check_color

	integer ie,ii,k
	integer ic,col,ires
	logical berror

	berror = .false.

	do ie=1,neg
	  ic = color(ie)
	  do ii=1,3
	    k = nen3v_global(ii,ie)
	    col = colork(k)
	    ires = ibits(col,ic,1)
	    if( ires == 0 ) then
	      write(6,*) 'no such color: ',ie,ii,k,ic
	      berror = .true.
	    end if
	    col = ibclr(col,ic)
	    colork(k) = col
	  end do
	end do

	do k=1,nkg
	  if( colork(k) /= 0 ) then
	    write(6,*) 'still color on node: ',k,colork(k)
	    berror = .true.
	  end if
	end do

	if( berror ) then
	  call shympi_abort_internal('check_color: internal error (1)')
	else
	  write(6,*) 'check_color passed...'
	end if

	end subroutine check_color

!***********************

	end subroutine domain_clusterization_ggu

!***********************************************************

	subroutine domain_clusterization_dummy

	use basin

	implicit none

	integer nmax,ie,ic
	integer ntot,n
	integer ierr

!	-------------------------------------------
!	set parameters and allocate arrays
!	-------------------------------------------

	nmax = nel
	subset_num = 1
	allocate(subset_el(subset_num),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(indipendent_subset(nmax,subset_num),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	subset_el = 0
	indipendent_subset = 0

!	-------------------------------------------
!	transfer information to arrays
!	-------------------------------------------

	ic = 1
	do ie=1,nel
	  indipendent_subset(ie,ic) = ie
	end do
	subset_el(ic) = nel

!	-------------------------------------------
!	write to terminal
!	-------------------------------------------

        print *,"  ---------- DOMAIN CLUSTERING INFORMATION ----------"
        print *,"  NUM NODES = ",nkn," NUM ELEMENTS = ",nel
        print *,"  NUMBER OF SUBSETS = ",subset_num
        ntot = 0
        do ic=1,subset_num
  	  n = subset_el(ic)
	  ntot = ntot + n
          print *,"  SUBSET = ",ic," LENGTH = ",n
        end do
        print *,"  SUM SUBSET LENGTH = ",ntot

!	-------------------------------------------
!	end of routine
!	-------------------------------------------

	end subroutine domain_clusterization_dummy

!***********************************************************

	subroutine subset_order_dump

! debug dump of the order in which the subset loops (conz3d_omp, and
! hydro_zeta with every solver but PETSc) reach the elements around each
! own node, read by the test
! testcases/examples/mar_menor/check_subset_order_mpi.sh (#263). Active
! only when the environment variable SHYFEM_SUBSET_DUMP holds a file
! prefix: then every process writes PREFIX.RANK.txt (RANK = my_id, 0 on
! one process), one line per own node (the nodes whose sums those loops
! use): the external node number, the number of its elements and, in the
! order the loops reach them, the external number and the subset (color)
! of each element. Written once, at start-up.

	use basin
	use shympi

	implicit none

	integer :: ic,j,ie,ii,k,i,n,ntot,nemax
	integer :: ist,ios,iu,ierr
	integer, allocatable :: nek(:)		!elements found per node
	integer, allocatable :: iek(:,:)	!elements in loop order
	integer, allocatable :: icek(:,:)	!their subset
	character(len=256) :: prefix
	character(len=16) :: crank
	integer ipext,ieext

	call get_environment_variable('SHYFEM_SUBSET_DUMP',prefix,status=ist)
	if( ist /= 0 ) return
	if( len_trim(prefix) == 0 ) return

	ntot = nkn
	if( shympi_partition_on_nodes() ) ntot = nkn_unique

	allocate(nek(nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('subset_order_dump: allocation failed')
	end if
	nek = 0
	do ie=1,nel
	  do ii=1,3
	    k = nen3v(ii,ie)
	    nek(k) = nek(k) + 1
	  end do
	end do
	nemax = maxval(nek)

	allocate(iek(nemax,nkn),icek(nemax,nkn),stat=ierr)
	if( ierr /= 0 ) then
	  call shympi_abort_internal('subset_order_dump: allocation failed')
	end if
	nek = 0
	do ic=1,subset_num
	  do j=1,subset_el(ic)
	    ie = indipendent_subset(j,ic)
	    do ii=1,3
	      k = nen3v(ii,ie)
	      n = nek(k) + 1
	      nek(k) = n
	      iek(n,k) = ie
	      icek(n,k) = ic
	    end do
	  end do
	end do

	write(crank,'(i0)') my_id
	open(newunit=iu,file=trim(prefix)//'.'//trim(crank)//'.txt'	&
     &		,status='replace',action='write',iostat=ios)
	if( ios /= 0 ) then
	  call shympi_abort_internal				&
     &		('subset_order_dump: cannot open the file of SHYFEM_SUBSET_DUMP')
	end if
	do k=1,ntot
	  write(iu,'(i9,i4,*(i10,i4))') ipext(k),nek(k)			&
     &		,(ieext(iek(i,k)),icek(i,k),i=1,nek(k))
	end do
	close(iu)

	deallocate(nek,iek,icek)

	end subroutine subset_order_dump

!==================================================================
        end module mod_subset
!==================================================================


