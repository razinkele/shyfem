
!--------------------------------------------------------------------------
!
!    Copyright (C) 2023  Georg Umgiesser
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

! proof of concept
!
! revision log :
!
! 03.03.2023    ggu     created

!--------------------------------------------------------------------------

	program ncgrid

	implicit none

	integer nx,ny,iu
	integer ix,iy
	integer n,nl
	integer ierr
	double precision x,y
	double precision, allocatable :: lon(:,:),lat(:,:)
	integer, allocatable :: node(:,:)

	open(newunit=iu,file='xdata.txt',status='old',form='formatted' &
     &			,iostat=ierr)
	if( ierr /= 0 ) then
	  write(6,*) 'error opening file: xdata.txt'
	  stop 'error stop ncgrid: cannot open xdata.txt'
	end if
	read(iu,*) nx,ny
	allocate(lon(nx,ny),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	read(iu,*) lon
	close(iu)

	open(newunit=iu,file='ydata.txt',status='old',form='formatted' &
     &			,iostat=ierr)
	if( ierr /= 0 ) then
	  write(6,*) 'error opening file: ydata.txt'
	  stop 'error stop ncgrid: cannot open ydata.txt'
	end if
	read(iu,*) nx,ny
	allocate(lat(nx,ny),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	read(iu,*) lat
	close(iu)

	write(6,*) 'finished reading...'

	allocate(node(nx,ny),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

	open(newunit=iu,file='ncgrid.grd',status='unknown',form='formatted' &
     &			,iostat=ierr)
	if( ierr /= 0 ) then
	  write(6,*) 'error opening file: ncgrid.grd'
	  stop 'error stop ncgrid: cannot open ncgrid.grd'
	end if

! write nodes

	n = 0
	do iy=1,ny
	  do ix=1,nx
	    n = n + 1
	    node(ix,iy) = n
	    x = lon(ix,iy)
	    y = lat(ix,iy)
	    write(iu,1000) 1,n,0,x,y
	  end do
	end do

! write lines

	nl = 0
	do iy=1,ny
	  nl = nl + 1
	  write(iu,2000) 3,nl,0,nx
	  write(iu,3000) node(:,iy)
	end do

	do ix=1,nx
	  nl = nl + 1
	  write(iu,2000) 3,nl,0,ny
	  write(iu,3000) node(ix,:)
	end do

! finished

	close(iu)
	write(6,*) 'data writte: ',n

	stop
 1000	format(i1,i10,i3,2f16.8)
 2000	format(i1,i10,i3,i5)
 3000	format(10i7)
	end

