
!--------------------------------------------------------------------------
!
!    Copyright (C) 2009-2012,2014-2019  Georg Umgiesser
!    Copyright (C) 2015,2018  Christian Ferrarin
!    Copyright (C) 2015  Michol Ghezzo
!    Copyright (C) 2016  Francesca De Pascalis
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

! handles insertion and output of particles
!
! revision log :
!
! 05.02.2009	ggu	copied from lagrange_cont.f and integrated from others
! 23.03.2010	ggu	changed v6.1.1
! 16.12.2011	ggu	initialization with body id
! 23.01.2012	ggu	new call to insert_particle, new id_body
! 01.10.2012	ggu	output concentrations only for one station
! 08.10.2012	ggu	changed VERS_6_1_58
! 28.03.2014	ggu	bug fix for insert with ie=0, area in concentrations
! 23.04.2014	ggu	new 3d insertion, new version of lgr file, new copy
! 05.05.2014	ggu	changed VERS_6_1_74
! 19.12.2014	ggu	changed VERS_7_0_10
! 23.12.2014	ggu	changed VERS_7_0_11
! 19.01.2015	ggu	changed VERS_7_1_3
! 01.04.2015	ggu	changed VERS_7_1_7
! 23.04.2015	ggu	changed VERS_7_1_8
! 06.05.2015	ccf	write relative total depth and type to output
! 07.05.2015	ccf	assign settling velocity to particles
! 21.05.2015	ggu	changed VERS_7_1_11
! 17.07.2015	ggu	changed VERS_7_1_52
! 17.07.2015	ggu	changed VERS_7_1_80
! 20.07.2015	ggu	changed VERS_7_1_81
! 24.07.2015	ggu	changed VERS_7_1_82
! 07.10.2015	mcg	seed 3d between surface and l_bot 
! 16.11.2015	ggu	changed VERS_7_3_14
! 15.02.2016	ggu&fdp	new release type ipvert=-1
! 22.02.2016	ggu	changed VERS_7_5_4
! 31.03.2017	ggu	changed VERS_7_5_24
! 09.05.2017	ggu	changed VERS_7_5_26
! 27.11.2017	ggu	inserted code to start from lgr files
! 05.12.2017	ggu	changed VERS_7_5_39
! 20.07.2018	ccf	new output file format
! 25.10.2018	ggu	changed VERS_7_5_51
! 16.02.2019	ggu	changed VERS_7_5_60
! 13.03.2019	ggu	changed VERS_7_5_61
!
!*******************************************************************

	subroutine insert_particle(ie,ity,lb,rtime,x,y,z)

! inserts particle at position x,y
!
! this is the ultimate routine that is called for insertion
!
! tin is insert time - compute with rtime
! z = 0.5 (corresponding to larva in water)
!
! on several MPI processes the id given here (idbdy counted on this
! process) is provisional: lgr_mpi_assign_ids, called after the seeding
! call, gives the id of a serial run; and the limit nbdymax does not stop
! here, it is only recorded (lgr_nbdymax_passed): lgr_mpi_assign_ids
! stops the run on the global number of particles
!
! a release point that lies in no element (ie = 0 and find_element finds
! none) gives no particle (#247): it takes no slot and no id, and is only
! counted in nlgr_outside (the release reports it). Before, the particle
! was inserted with ie = 0 and the output read the geometry of element 0
! (SIGSEGV in mm_lgr_a with a trajectory point outside the basin). On
! several processes no caller passes ie = 0 (lgrtrj stops at start-up,
! the polygon and basin releases pass an element the process owns), so
! the ids stay those of a serial run

	use mod_lagrange
	use mod_lagrange_mpi, only : lgr_nbdymax_passed
        use basin, only : neldi,iarv
	use shympi, only : ip_int_elem,shympi_is_parallel
	use femtime

	implicit none

	integer ie	!element of particle - if unknown use 0
	integer ity	!particle type
	integer lb	!layer [1-lmax]
	integer nc	!number of custom properties
	real rtime	!fraction of time step to be inserted (0 for all) [0-1]
	real x,y	!coordinates of particle to be inserted
	real z		!vertical (relative) coordinate [0-1]

	integer pt	!particle type
	real pc		!custom property
	double precision ps		!settling velocity of particle [m/s]
	logical bdebug
	logical lmytype			!use element type for particle type

! rtime is the relative time position when the particle is inserted
! 0 inserts at the beginning of the time step - advection for full time step
! 1 inserts at end of time step - no advection for this time step needed

	integer ip
	integer ierr
	double precision xx,yy,xi(3)

	bdebug = .false.
	lmytype = .false.

	if( ie .eq. 0 ) then
	  call find_element(x,y,ie)
	end if
	if( ie <= 0 ) then		!in no element: not inserted (#247)
	  nlgr_outside = nlgr_outside + 1
	  return
	end if

	nbdy = nbdy + 1
	idbdy = idbdy + 1

	if( nbdymax > 0 .and. nbdy .gt. nbdymax				&
     &			.and. shympi_is_parallel() ) then
	  lgr_nbdymax_passed = .true.	!decided by lgr_mpi_assign_ids
	else if( nbdymax > 0 .and. nbdy .gt. nbdymax ) then
	  write(6,*) 'nbdymax = ',nbdymax
	  write(6,*) 'Cannot insert more than nbdymax particles'
	  write(6,*) 'Please change nbdymax in STR file'
	  stop 'error stop insert_particle: nbdy'
	end if
	call mod_lagrange_handle_alloc(nbdy)

        lgr_ar(nbdy)%init%time = t_act - dt_act*(1.-rtime)
        lgr_ar(nbdy)%actual%time = lgr_ar(nbdy)%init%time

	!call lagr_connect_get_station(ie,ip,z)	!connectivity (z is color)

        lgr_ar(nbdy)%init%ie   = -ie
        lgr_ar(nbdy)%init%l    = lb
        lgr_ar(nbdy)%init%z    = z
        lgr_ar(nbdy)%actual%ie = ie
        lgr_ar(nbdy)%actual%l  = lb
        lgr_ar(nbdy)%actual%z  = z
	if( ie > 0 ) then
	  lgr_ar(nbdy)%actual%ie_global = ip_int_elem(ie)
	  lgr_ar(nbdy)%init%ie_global = ip_int_elem(ie)
	end if

	xi = 1./3.
	if( ie > 0 ) then
	  call xi_init_particle(ie,x,y,xi)
	  lgr_ar(nbdy)%init%xi(:) = xi
	  lgr_ar(nbdy)%actual%xi(:) = xi
	end if
	call track_xi_check('insert particle',idbdy,xi)
	if( bdebug ) then
	  write(6,*) 'debug insert particle: ',nbdy
	  write(6,*) ie,idbdy
	  write(6,*) x,y,z
	  write(6,*) ity,lb,rtime
	  write(6,*) lgr_ar(nbdy)%init%xi
	end if
	lgr_ar(nbdy)%id = idbdy

	call lagr_connect_bitmap_init(nbdy)

	pt = ity 	!by default use boundary number
	if( lmytype ) then
	  pt = iarv(ie) !use type of element ie
	end if 

	! the sediment class is drawn with the particle's id (#225); on several
	! processes this id is provisional, but ised stops there at start-up
	call lgr_set_properties(idbdy,bsedim,blarvae,boilsim,pt,ps,pc,nc)
        allocate( lgr_ar(nbdy)%custom(nc),stat=ierr )
        if( ierr /= 0 ) call shympi_abort_internal(			&
     &		'error stop: allocation failed')
	ncust = nc

	lgr_ar(nbdy)%type = pt
	lgr_ar(nbdy)%sinking = ps
	lgr_ar(nbdy)%custom(1)  = pc

! ..............

	end

!*******************************************************************

	subroutine xi_init_particle(ie,x,y,xi)

	implicit none

	integer ie
	real x,y
	double precision xi(3)

	double precision xx,yy

	if( ie < 1 ) then
	  write(6,*) 'ie = ',ie
	  call shympi_abort_internal('error stop xi_init_particle: ie <= 0')
	end if

	xx = x
	yy = y
	call xy2xi(ie,xx,yy,xi)
	call xi_move_inside(ie,xi)

	end

!*******************************************************************

	subroutine xi_move_inside(ie,xi)

! moves particle a small distance inside the element
! this is done to not fall onto the side or vertex

	implicit none

	integer ie
	double precision xi(3)

	integer is,it,i,in
	double precision dist,disttot
	double precision, parameter :: eps = 1.e-5

	is = 0
	in = 0
	do i=1,3
	  if( xi(i) == 0. ) then
	    is = is + i
	    in = in + 1
	  end if
	end do

	if( in == 0 ) return

	if( in == 1 ) then		!particle on side
	  disttot = 0.
	  do i=1,3
	    if( i /= is ) then
	      dist = eps*xi(i)
	      xi(i) =  xi(i) - dist
	      disttot = disttot + dist
	    end if
	  end do
	  xi(is) = xi(is) + disttot
	else if( in == 2 ) then		!particle on vertex
	  is = 6 - is
	  xi(is) = 1. - 2.*eps
	  do i=1,3
	    if( i /= is ) xi(i) = xi(i) + eps
	  end do
	else
	  call shympi_abort_internal(					&
     &		'error stop xi_move_inside: internal error')
	end if

	end

!*******************************************************************

	subroutine insert_particle_3d(ie,ity,rtime,x,y)

	use mod_lagrange
	use levels

	implicit none

	integer ::  ie	!element of particle - if unknown use 0
	integer :: ity	!type of particle to be inserted
	real :: rtime	!fraction of time step to be inserted (0 for all) [0-1]
	real :: x,y	!coordinates of particle to be inserted

! n = abs(itype)
! itype == 0	release one particle in surface layer
! itype > 0	release n particles regularly
! itype < 0	release n particles randomly
! itype == -1	release particles in every layer
!
! the random depth of a particle (itype < -1) is its own draw (#225),
! keyed on the id it receives: lgr_release_depth, right after its
! insertion (a serial run gives the final id there) and again in
! lgr_mpi_assign_ids once the ids of a serial run are given
!
! a point that lies in no element (ie = 0 and find_element finds none)
! releases nothing (#247): the particles it would have released are
! counted in nlgr_outside (one, n = abs(itype), or for itype = -1 one per
! layer lintop ... linbot of the deepest column, nlv) and the routine
! returns before it reads the layers of an element

	logical b2d,bdebug
	integer n,lmax,l,i
	real h,dh,hact
	integer itype	!type of vertical distribution
	integer lb	!layer [1-lmax]
	integer linf	!bottom layer [1-lmax]
	integer lsrf	!surface layer [1-lmax]
	real z		!vertical (relative) coordinate [0-1]
	real hl(nlv)
	real htot,htotz

	bdebug = .false.

	if( ie == 0 ) call find_element(x,y,ie)
	if( ie <= 0 ) then		!in no element: nothing released (#247)
	  n = 1
	  if( .not. ( blgrsurf .or. nlv <= 1 .or. ipvert == 0 ) ) then
	    if( ipvert == -1 ) then
	      linf = linbot
	      if( linf > nlv .or. linf == 0 ) linf = nlv
	      lsrf = max(1,lintop)
	      n = max(0,linf-lsrf+1)
	    else
	      n = abs(ipvert)
	    end if
	  end if
	  nlgr_outside = nlgr_outside + n
	  return
	end if

	lmax = ilhv(ie)
	linf = linbot	 
	lsrf = lintop	 
	itype = ipvert
	b2d = nlv <= 1

	if( itype /= 0 ) then
	  if( linf .gt. lmax ) then 
	    linf = lmax 
	  else if ( linf .eq. 0 ) then 
	    linf = lmax 
	  end if	
	  if( lsrf .lt. 1 ) then 
	    lsrf = 1 
	  else if ( lsrf .eq. 0 ) then 
	    lsrf = 1 
	  end if	
	end if

	!-------------------------------------------------
	! handle 2d or surface situation
	!-------------------------------------------------

	if( blgrsurf .or. b2d .or. itype == 0 ) then
	  lb = 1
	  z = 0.5
	  call insert_particle(ie,ity,lb,rtime,x,y,z)
	  return
	end if

	if( itype == -1 ) then	! realease one particle in every layer
	  do l=lsrf,linf
	    z = 0.5
	    call insert_particle(ie,ity,l,rtime,x,y,z)
	  end do
	  return
	end if

	!-------------------------------------------------
	! handle 3d situation
	!-------------------------------------------------

	n = abs(itype)
	call lagr_layer_thickness(ie,lmax,hl,htot,htotz)
	h = 0.

	do l=1,linf 
	  h = h + hl(l)
	end do
	dh = h / n
	hact = -dh/2.

	if( bdebug ) write(6,*) '3d release for lagrange ',n,x,y

	do i=1,n
	  if( itype > 0 ) then
	    hact = hact + dh		!regular subdivision
	    call find_vertical_position(lmax,hl,hact,lb,z)
	    call insert_particle(ie,ity,lb,rtime,x,y,z)
	    if( bdebug ) write(6,*) '   ',i,hact,lb,z
	  else				!random depth, drawn with the id
	    lb = 1
	    z = 0.5
	    call insert_particle(ie,ity,lb,rtime,x,y,z)
	    call lgr_release_depth(nbdy)
	    if( bdebug ) write(6,*) '   ',i,lgr_ar(nbdy)%actual%l	&
     &				,lgr_ar(nbdy)%actual%z
	  end if
	end do
	
	!-------------------------------------------------
	! end of routine
	!-------------------------------------------------

	end

!*******************************************************************

	function lgr_random_depth_release()

! true if insert_particle_3d draws a random depth for each particle it
! releases: ipvert < -1 in a basin with more than one layer and ilagr /= 1
! (its branches: surface layer for ilagr = 1, a 2D basin or ipvert = 0;
! every layer for ipvert = -1; regular depths for ipvert > 0)

	use mod_lagrange
	use levels, only : nlv

	implicit none

	logical lgr_random_depth_release

	lgr_random_depth_release = ipvert < -1 .and. .not. blgrsurf		&
     &				.and. nlv > 1

	end

!*******************************************************************

	subroutine lgr_release_depth(ip)

! random depth of particle ip at its release (ipvert < -1, see
! insert_particle_3d): the depth below the surface is r*h, h the depth of
! its element of release down to the bottom of layer linbot (as
! insert_particle_3d computes it) and r the particle's draw (#225),
! lgr_random keyed on its id, the time step and the site lgr_rnd_relz.
! Sets the layer and the position in the layer of init and actual.
!
! called by insert_particle_3d right after the insertion (in a serial run
! the id is final there) and, on several processes, by lgr_mpi_assign_ids
! for each new particle once it has the id of a serial run (the id given
! by insert_particle is provisional there): the depth is a function of the
! id, so the second call gives the serial depth. Called in the time step
! of the release, outside any parallel region: the element's layers are
! those of the insertion. (On several processes ipvert < -1 still stops at
! start-up, lgr_mpi_check_supported, so that call is not run today.)

	use mod_lagrange
	use levels
	use mod_lagrange_random, only : lgr_random, lgr_rnd_relz

	implicit none

	integer, intent(in) :: ip	!slot of the particle

	integer ie,lmax,linf,l,lb
	real h,hact,r,z
	real hl(nlv)
	real htot,htotz

	ie = -lgr_ar(ip)%init%ie	!element of release (positive)
	if( ie <= 0 ) return

	lmax = ilhv(ie)
	linf = linbot
	if( linf .gt. lmax ) then
	  linf = lmax
	else if ( linf .eq. 0 ) then
	  linf = lmax
	end if

	call lagr_layer_thickness(ie,lmax,hl,htot,htotz)
	h = 0.
	do l=1,linf
	  h = h + hl(l)
	end do

	r = lgr_random(lgr_ar(ip)%id,lgr_rnd_relz,0)
	hact = r*h
	call find_vertical_position(lmax,hl,hact,lb,z)

	lgr_ar(ip)%init%l = lb
	lgr_ar(ip)%init%z = z
	lgr_ar(ip)%actual%l = lb
	lgr_ar(ip)%actual%z = z

	end

!*******************************************************************

	subroutine insert_particle_surface(ie,ity,rtime,x,y)

	implicit none

	integer ie	!element of particle - if unknown use 0
	integer ity	!type of particle to be inserted
	real rtime	!fraction of time step to be inserted (0 for all) [0-1]
	real x,y	!coordinates of particle to be inserted

	integer lb	!layer [1-lmax]
	real z		!vertical (relative) coordinate [0-1]

	lb = 1
	z = 0.5

	call insert_particle(ie,ity,lb,rtime,x,y,z)

	end

!*******************************************************************

	subroutine find_vertical_position(lmax,hl,hact,lb,z)

! finds vertical position for depth hact

	implicit none

	integer lmax		!total number of layers
	real hl(lmax)		!layer thickness
	real hact		!vertical depth of particle
	integer lb		!layer [1-lmax] (return)
	real z			!position in layer [0-1] (return, 1 bottom)

	integer l
	real hbot,htop

	hbot = 0.
	htop = 0.

	do l=1,lmax
	  hbot = hbot + hl(l)
	  if( hbot >= hact ) exit
	  htop = hbot
	end do
	if( l > lmax ) then
	  write(6,*) 'lmax,hbot,hact: ',lmax,hbot,hact
	  write(6,*) hl
	  call shympi_abort_internal(					&
     &		'error stop find_vertical_position: hact > hbot')
	end if

	lb = l
	z = (hact-htop)/(hbot-htop) 	!relative position

	!write(6,*) 'lb,z,hl: ',lb,z,hl

	end

!*******************************************************************

	subroutine copy_particle(ifrom,ito)

! copies particle from ifrom to ito

	use mod_lagrange

	implicit none

	integer ifrom,ito

	if( ifrom .eq. ito ) return

        lgr_ar(ito) = lgr_ar(ifrom)
	lgr_ncross(ito) = lgr_ncross(ifrom)	!moves with its particle
	lgr_marked(ito) = lgr_marked(ifrom)	!moves with its particle
	lgr_park_xy(:,ito) = lgr_park_xy(:,ifrom)	!moves with its particle
	lgr_park_ie(ito) = lgr_park_ie(ifrom)	!moves with its particle

	return

        lgr_ar(ito)%init%ie      = lgr_ar(ifrom)%init%ie
        lgr_ar(ito)%init%z       = lgr_ar(ifrom)%init%z
        lgr_ar(ito)%init%l       = lgr_ar(ifrom)%init%l 
        lgr_ar(ito)%init%xi(:)   = lgr_ar(ifrom)%init%xi(:)
        lgr_ar(ito)%init%time    = lgr_ar(ifrom)%init%time

        lgr_ar(ito)%actual%ie    = lgr_ar(ifrom)%actual%ie
        lgr_ar(ito)%actual%z     = lgr_ar(ifrom)%actual%z
        lgr_ar(ito)%actual%l     = lgr_ar(ifrom)%actual%l 
        lgr_ar(ito)%actual%xi(:) = lgr_ar(ifrom)%actual%xi(:)
        lgr_ar(ito)%actual%time  = lgr_ar(ifrom)%actual%time

	lgr_ar(ito)%id           = lgr_ar(ifrom)%id
	lgr_ar(ito)%type         = lgr_ar(ifrom)%type
	lgr_ar(ito)%sinking      = lgr_ar(ifrom)%sinking
	lgr_ar(ito)%custom(:)    = lgr_ar(ifrom)%custom(:)

	call lagr_connect_bitmap_copy(ifrom,ito)

	end

!*******************************************************************

	subroutine delete_particle(ip)

! deletes particle ip: it keeps its last element with a negative sign,
! as a particle that left the basin (#226: with ie = 0 the output read the
! coordinates of element 0); compress_particles treats ie <= 0 as free

	use mod_lagrange

	implicit none

	integer ip

	if( lgr_ar(ip)%actual%ie .gt. 0 ) then
	  lgr_ar(ip)%actual%ie = -lgr_ar(ip)%actual%ie
	end if

	end

!*******************************************************************

	subroutine ntot_particles(ntot)

! returns total number of particles

	use mod_lagrange

	implicit none

	integer ntot

	ntot = nbdy

	end

!*******************************************************************
!*******************************************************************
!*******************************************************************

	subroutine lgr_insert_particle_to_be_deleted(i,id,z,ie,lb,ty,c,tin)

	use mod_lagrange

	implicit none

	integer ie,i,id,lb,ty
	real z,c,tin

        lgr_ar(nbdy)%init%ie     = -ie
        lgr_ar(nbdy)%init%l      = lb
        lgr_ar(nbdy)%init%z      = z
        lgr_ar(nbdy)%init%time   = tin

        lgr_ar(nbdy)%actual%ie   = ie
        lgr_ar(nbdy)%actual%l    = lb
        lgr_ar(nbdy)%actual%z    = z
        lgr_ar(nbdy)%actual%time = tin

        lgr_ar(nbdy)%type = ty
        lgr_ar(nbdy)%sinking = 0.
        lgr_ar(nbdy)%custom(1) = c

	end

!*******************************************************************
! TO BE DONE
	subroutine lgr_input_shell

! initial distribution of particles from a particle file (lgrini): the
! active particles of the record at time itlgin, with their ids
!
! the counter of the ids given out (idbdy) is moved past every id of the
! file up to that record, of all three blocks (active, inserted, exited:
! a particle that left the basin had an id too), so that a release after
! the restart gives the ids the run that went on gives. Before, idbdy
! stayed 0 and the next release gave the ids 1, 2, ... again, and since the
! random draws of a particle are keyed on its id (#225) two particles with
! one id would draw the same numbers. Serial only (lgrini stops on several
! processes, lgr_mpi_check_supported).

	use mod_lagrange
	use shympi, only : ip_int_elem
        use shyfile

	implicit none

        !active particles
        integer, allocatable            :: ida(:)
        integer, allocatable            :: tya(:)
        double precision, allocatable   :: tta(:)
        real, allocatable               :: sa(:)
        integer, allocatable            :: iea(:)
        real, allocatable               :: xa(:),ya(:),za(:)
        integer, allocatable            :: lba(:)
        real, allocatable               :: hla(:)
        real, allocatable               :: ca(:,:)

	integer				:: i,ic
	integer				:: n_act,ntot,n_aux
	integer				:: id
	integer				:: iu
        integer                         :: iwhat
        integer                         :: ierr
	integer				:: idmax	!largest id of the file
	integer				:: iwhat2
	double precision 		:: xi(3)
	double precision 		:: dtime,ditime,ditime2
	double precision 		:: dtlgin
        character*20                    :: aline
	character*256 			:: ifile

        INTERFACE
        subroutine lgr_alloc(nn,nc &
     &          ,id,ty,tt,s,ie,x,y,z,lb,hl,c)
        integer nn,nc
        integer, allocatable            :: id(:)
        integer, allocatable            :: ty(:)
        double precision, allocatable   :: tt(:)
        real, allocatable               :: s(:)
        integer, allocatable            :: ie(:)
        real, allocatable               :: x(:),y(:),z(:)
        integer, allocatable            :: lb(:)
        real, allocatable               :: hl(:)
        real, allocatable               :: c(:,:)
        end subroutine
        END INTERFACE

        !--------------------------------------------------------------
        ! open input file
        !--------------------------------------------------------------

	call getfnm('lgrini',ifile)
	if( ifile == ' ' ) return
        call convert_date_d('itlgin',dtlgin)   !start of lagrangian sim
        call get_timeline(dtlgin,aline)

        id = shy_init(ifile)
        call shy_read_header(id,ierr)
        call shy_get_iunit(id,iu)
        read(iu) ncust

        !--------------------------------------------------------------
        ! loop over records
        !--------------------------------------------------------------
        idmax = 0
        do
          !----------------------------------------------------------------
          ! read lgr data block --> active particles (use only these particles)
          !----------------------------------------------------------------
          call lgr_peek_block_header(iu,ditime,n_act,iwhat,ierr)
          if( ierr > 0 ) write(6,*) 'error in reading file : ',ierr
          if( ierr /= 0 ) exit
          call lgr_alloc(n_act,ncust &
     &          ,ida,tya,tta,sa,iea,xa,ya,za,lba,hla,ca)
          call lgr_get_block(iu,n_act,ncust, &
     &                  ida,tya,tta,sa,iea,xa,ya,za,lba,hla,ca)
          do i=1,n_act
            idmax = max(idmax,ida(i))
          end do
          if( ditime == dtlgin ) then
            ! the inserted and exited blocks of this record (ids too)
            do ic=1,2
              call lgr_peek_block_header(iu,ditime2,n_aux,iwhat2,ierr)
              if( ierr /= 0 ) exit
              if( ditime2 /= dtlgin .or. iwhat2 == 0 ) exit !next record
              call lgr_block_max_id(iu,idmax)
            end do
            exit
          end if
          !----------------------------------------------------------------
          ! data block --> inserted particles (only their ids)
          !----------------------------------------------------------------
          call lgr_peek_block_header(iu,ditime,n_aux,iwhat,ierr)
          if( ierr /= 0 ) exit
          call lgr_block_max_id(iu,idmax)
          !----------------------------------------------------------------
          ! data block --> exited particles (only their ids)
          !----------------------------------------------------------------
          call lgr_peek_block_header(iu,ditime,n_aux,iwhat,ierr)
          if( ierr /= 0 ) exit
          call lgr_block_max_id(iu,idmax)
        end do

        if( ditime /= dtlgin ) then
	  write(6,*) 'cannot find time record: ',dtlgin
	  stop 'error stop lgr_input_shell: no such time record'
        end if

	idbdy = max(idbdy,idmax)	!ids of new particles follow the file's

        call get_act_dtime(dtime)

	write(6,*) 'initializing lagrangian from file: '
	write(6,*) 'file = ',trim(ifile)
	write(6,*) 'time = ',aline

	ntot = nbdy + n_act
	if( nbdymax > 0 .and. ntot > nbdymax ) then
	  write(6,*) 'nbdymax = ',nbdymax
	  write(6,*) 'Cannot insert more than nbdymax particles'
	  write(6,*) 'Please change nbdymax in STR file'
	  stop 'error stop lgr_input_shell: nbdy'
	end if
	call mod_lagrange_handle_alloc(ntot)

	do i=1,n_act
          nbdy = nbdy + 1
          lgr_ar(nbdy)%init%ie     = -iea(i)
          lgr_ar(nbdy)%init%l      = lba(i)
          lgr_ar(nbdy)%init%z      = za(i)
          lgr_ar(nbdy)%init%time   = dtime
          lgr_ar(nbdy)%actual%ie   = iea(i)
          lgr_ar(nbdy)%actual%l    = lba(i)
          lgr_ar(nbdy)%actual%z    = za(i)
          lgr_ar(nbdy)%actual%time = dtime
	  if( iea(i) > 0 ) then
	    lgr_ar(nbdy)%actual%ie_global = ip_int_elem(iea(i))
	    lgr_ar(nbdy)%init%ie_global = ip_int_elem(iea(i))
	  end if
          lgr_ar(nbdy)%id          = ida(i)
          lgr_ar(nbdy)%type        = tya(i)
          lgr_ar(nbdy)%sinking     = sa(i)

          allocate( lgr_ar(nbdy)%custom(ncust),stat=ierr )
          if( ierr /= 0 ) stop 'error stop: allocation failed'
          do ic = 1,ncust
            lgr_ar(nbdy)%custom(ic)= ca(i,ic)
          end do

          call xi_init_particle(iea(i),xa(i),ya(i),xi)
          lgr_ar(nbdy)%init%xi(:) = xi(:)
          lgr_ar(nbdy)%actual%xi(:) = xi(:)
	  call track_xi_check('insert particle',id,xi)

	  call lagr_connect_bitmap_init(nbdy)

	end do

        call shy_close(id)

	write(6,*) 'finished initializing lagrangian from file'
	write(6,*) 'particles read: ',n_act,'  largest id in the file: '	&
     &			,idmax

	end

!*******************************************************************

	subroutine lgr_block_max_id(iu,idmax)

! reads the next data block of a particle file (its header and the three
! records of each particle) and raises idmax to the largest id in it; only
! the id is taken from each particle (the rest of a record is skipped)

	implicit none

	integer, intent(in) :: iu		!unit of the particle file
	integer, intent(inout) :: idmax		!largest id so far

	double precision atime
	integer nn,iwhat,i,idp,ios

	read(iu,iostat=ios) atime,nn,iwhat
	if( ios /= 0 ) then
	  write(6,*) 'lgr_block_max_id: iostat ',ios
	  call shympi_abort_internal('error stop lgr_block_max_id:'	&
     &		//' cannot read a block header of the particle file')
	end if

	do i=1,nn
	  read(iu,iostat=ios) idp		!first value: the id
	  if( ios == 0 ) read(iu,iostat=ios)	!coordinates
	  if( ios == 0 ) read(iu,iostat=ios)	!custom values
	  if( ios /= 0 ) then
	    write(6,*) 'lgr_block_max_id: particle ',i,' of ',nn		&
     &			,', iostat ',ios
	    call shympi_abort_internal('error stop lgr_block_max_id:'	&
     &		//' cannot read a particle of the particle file')
	  end if
	  idmax = max(idmax,idp)
	end do

	end

!*******************************************************************

        subroutine lgr_write_header(iu,nlv,ncust)

        implicit none

	integer, intent(in) 		:: iu
	integer, intent(in) 		:: nlv
	integer, intent(in) 		:: ncust

        integer, parameter      	:: nvers = 6
        integer, parameter      	:: mtype = 367265


        write(iu) mtype,nvers
        write(iu) nlv,ncust                   !from version 5 on

        write(6,*) 'lgr file initialized...'

	end subroutine lgr_write_header

!*******************************************************************

	subroutine lgr_output(iu,dtime)

! outputs particles to file
!
! if body has exited the element its number is negativ (last element);
! a particle that left the basin, decayed (lagrange_decay) or was deleted
! (delete_particle) keeps it, and is written in the exited block at its
! last position at every output (ie = 0 is only a particle inserted
! where find_element found no element)

! mcg : 15/10/2015 write in v.5  hl = effective absolute depth 
! mcg : need to add more start info: level depth custom 
! mcg : suggests to write for each release a small file_ini.lgr
! ccf : new output format

! the three records of a particle are prepared by lgr_output_record and
! written by lgr_output_write (lgr_mpi_output writes the same records on
! several processes)

	use mod_lagrange

	implicit none

	integer, intent(in) 		:: iu
	double precision, intent(in)	:: dtime

	integer 		:: i,ip,ie
	integer 		:: iwhat
	integer			:: n_new  	!particles inserted
	integer			:: n_act   	!particles inside the domain
	integer			:: n_ext     	!particles exited the domain
	double precision, allocatable	:: rec(:)
	integer, allocatable	:: list_new(:)
	integer, allocatable	:: list_ins(:)
	integer, allocatable	:: list_ext(:)
	integer			:: ierr

!----------------------------------------------------------------
! count inserted, active and exited particles
!----------------------------------------------------------------

        if (nbdy == 0 ) return

	allocate(rec(lgr_orec_base+ncust),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(list_new(nbdy),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(list_ins(nbdy),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(list_ext(nbdy),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'

	n_new = 0
	n_act = 0
	n_ext = 0
	do i=1,nbdy
	  ie = lgr_ar(i)%init%ie
	  if( ie < 0 ) then
	    n_new = n_new + 1
	    list_new(n_new) = i
	  end if
	  ie = lgr_ar(i)%actual%ie
	  if( ie > 0 ) then
	    n_act = n_act + 1
	    list_ins(n_act) = i
	  end if
	  if( ie <= 0 ) then
	    n_ext = n_ext + 1
	    list_ext(n_ext) = i
	  end if
	end do

!----------------------------------------------------------------
! write to file - active particles, iwhat = 0
!----------------------------------------------------------------
	
	iwhat = 0
	write(iu) dtime,n_act,iwhat

	do i=1,n_act
	  call lgr_output_record(list_ins(i),0,rec)
	  call lgr_output_write(iu,rec)
	end do

!----------------------------------------------------------------
! write to file - inserted particles, iwhat = -1
!----------------------------------------------------------------

	iwhat = -1
	write(iu) dtime,n_new,iwhat

	do i=1,n_new
	  ip  = list_new(i)
	  ie  = lgr_ar(ip)%init%ie
	  call lgr_output_record(ip,-1,rec)
	  call lgr_output_write(iu,rec)

	  lgr_ar(ip)%init%ie = -ie
	   !should we deleted the init information after writing it?
	end do

!----------------------------------------------------------------
! write to file - exited particles, iwhat = 1
! particles are then deleted by routine compress_particles
! bcompress must be set to true
!----------------------------------------------------------------

	iwhat = 1
	write(iu) dtime,n_ext,iwhat

	do i=1,n_ext
	  call lgr_output_record(list_ext(i),1,rec)
	  call lgr_output_write(iu,rec)

	  !particles are deletedexit particles information after writing it
	end do

!----------------------------------------------------------------
! end of routine
!----------------------------------------------------------------

	end

!*******************************************************************

	subroutine lgr_output_record(ip,which,rec)

! fills the output record rec (layout: lgr_orec_base in mod_lagrange) of
! array entry ip as lgr_output writes it:
!   which = 0   active: the actual position, element actual%ie > 0, all
!               custom values
!   which = -1  inserted: the release record init, element abs(init%ie)
!   which = 1   exited: the actual position, element abs(actual%ie) (the
!               element the particle left, or the last element of a
!               decayed or deleted particle, #226; 0 only for a particle
!               inserted where find_element found no element)
! type and sinking are the particle's own (of the moment). As in the
! serial code since the new output format, an inserted or an exited
! record holds custom(1) in every custom slot (only the active record has
! all custom values); this is reproduced here, not corrected

	use mod_lagrange

	implicit none

	integer, intent(in) :: ip
	integer, intent(in) :: which
	double precision, intent(out) :: rec(lgr_orec_base+ncust)

	type(lagr_body) :: b
	real :: c(ncust)

	select case( which )
	case( 0 )
	  b = lgr_ar(ip)%actual
	  c = lgr_ar(ip)%custom(1:ncust)
	case( -1 )
	  b = lgr_ar(ip)%init
	  c = lgr_ar(ip)%custom(1)
	case( 1 )
	  b = lgr_ar(ip)%actual
	  c = lgr_ar(ip)%custom(1)
	case default
	  write(6,*) 'lgr_output_record: which = ',which
	  call shympi_abort_internal('lgr_output_record: which')
	end select

	call lgr_output_fill(b%ie,b%xi,b%z,b%l,b%time,lgr_ar(ip)%id	&
     &		,lgr_ar(ip)%type,real(lgr_ar(ip)%sinking),c,rec)

	end subroutine lgr_output_record

!*******************************************************************

	subroutine lgr_output_fill(ie,xi,z,lb,tt,id,ty,s,c,rec)

! fills an output record (layout: lgr_orec_base in mod_lagrange) from the
! values of a particle: ie its local element (negative for the element a
! particle left, the last element of a decayed or deleted particle and a
! release record not yet written; 0 only for a particle inserted where
! find_element found no element, which xi2xy cannot place: not changed
! here, see #226), xi its coordinates in that element, and z, lb, tt,
! id, ty, s, c(1:ncust) as they are written. x, y and hl are computed here
! (xi2xy, and lgr_compute_depths with the layer thickness of the moment)
! as lgr_output always did; the element written is the global number
! ip_int_elem(abs(ie)) (the local number in a serial run), 0 for ie = 0

	use mod_lagrange
	use shympi, only : ip_int_elem

	implicit none

	integer, intent(in) :: ie
	double precision, intent(in) :: xi(3)
	real, intent(in) :: z
	integer, intent(in) :: lb
	double precision, intent(in) :: tt
	integer, intent(in) :: id
	integer, intent(in) :: ty
	real, intent(in) :: s
	real, intent(in) :: c(ncust)
	double precision, intent(out) :: rec(lgr_orec_base+ncust)

	integer :: ieg,ii
	real :: x,y,hl,ht,hr
	double precision :: xx,yy

	call xi2xy(abs(ie),xx,yy,xi)
	x = xx
	y = yy
	call lgr_compute_depths(ie,lb,z,hl,ht,hr)
	ieg = 0
	if( ie /= 0 ) ieg = ip_int_elem(abs(ie))

	rec(1) = dble(id)
	rec(2) = dble(ty)
	rec(3) = tt
	rec(4) = dble(s)
	rec(5) = dble(ieg)
	rec(6) = dble(x)
	rec(7) = dble(y)
	rec(8) = dble(z)
	rec(9) = dble(lb)
	rec(10) = dble(hl)
	do ii=1,ncust
	  rec(lgr_orec_base+ii) = dble(c(ii))
	end do

	end subroutine lgr_output_fill

!*******************************************************************

	subroutine lgr_output_write(iu,rec)

! writes an output record (lgr_output_fill) as the three Fortran records
! of a particle in the lgr file, with the types lgr_output always wrote:
! (id, type, time, sinking, element), (x, y, z, layer, hl), (custom values)

	use mod_lagrange

	implicit none

	integer, intent(in) :: iu
	double precision, intent(in) :: rec(lgr_orec_base+ncust)

	integer :: id,ty,ie,lb,ii
	double precision :: tt
	real :: s,x,y,z,hl
	real :: c(ncust)

	id = nint(rec(1))
	ty = nint(rec(2))
	tt = rec(3)
	s  = real(rec(4))
	ie = nint(rec(5))
	x  = real(rec(6))
	y  = real(rec(7))
	z  = real(rec(8))
	lb = nint(rec(9))
	hl = real(rec(10))
	do ii=1,ncust
	  c(ii) = real(rec(lgr_orec_base+ii))
	end do

	write(iu) id,ty,tt,s,ie
	write(iu) x,y,z,lb,hl
	write(iu) (c(ii), ii=1,ncust)

	end subroutine lgr_output_write

!*******************************************************************

	subroutine lgr_compute_depths(ie,lb,z,hl,ht,hr)

	use mod_layer_thickness
	use levels

	implicit none

	integer ie
	integer lb
	real z
	real hl,ht,hr

	integer ieh,l

	hl = 0. !absolute depth in water column
	ht = 0. !absolute depth to bottom of water column
	hr = 0. !relative depth in water column 

	ieh = abs(ie)
	if( ieh == 0 ) return

	do l = 1,lb-1
	  hl = hl + hdenv(l,ieh)
	  ht = ht + hdenv(l,ieh)
	end do

	hl = hl + z*hdenv(lb,ieh)

	do l = lb,ilhv(ieh)
	  ht = ht + hdenv(l,ieh)
	end do

	hr = hl / ht

	end

!*******************************************************************
!*******************************************************************
!*******************************************************************

	subroutine print_elements(text)

! writes element numbers of particles to terminal

	use mod_lagrange

	implicit none

	character*(*) text

	integer i,ii

	write(6,*) text
	write(6,*) 'particles: ',nbdy
	do i=1,nbdy,10
	  write(6,*) (lgr_ar(ii)%actual%ie,ii=i,min(i+9,nbdy))
	end do

	end

!*******************************************************************
	
	subroutine compress_particles

! deletes particles not in system and compresses array

	use mod_lagrange
	use femtime

	implicit none

	integer ifree,icopy,i
	integer nbefore

	logical is_free,is_particle
	is_free(i) = lgr_ar(i)%actual%ie .le. 0
	is_particle(i) = lgr_ar(i)%actual%ie .gt. 0

	ifree = 0
	icopy = nbdy+1
	nbefore = nbdy

	do while( ifree .lt. icopy )

	  do i=ifree+1,icopy-1
	    if( is_free(i) ) exit
	  end do
	  ifree = i
	  if( ifree .eq. icopy ) exit

	  do i=icopy-1,ifree+1,-1
	    if( is_particle(i) ) exit
	  end do
	  icopy = i
	  if( ifree .eq. icopy ) exit

	  call copy_particle(icopy,ifree)
	  call delete_particle(icopy)

	end do

	nbdy = ifree - 1

!--------------------------------------------------------------
! check particle structure
!--------------------------------------------------------------

	!write(lunit,*) 'compress_particles: ',it,nbefore,nbdy,nbefore-nbdy

	do i=1,nbdy
	  if( is_free(i) ) then
	    write(6,*) 'particle i = ',i,' is deleted'
	    stop 'error stop compress_particles: structure'
	  end if
	end do

	do i=nbdy+1,nbefore
	  if( is_particle(i) ) then
	    write(6,*) 'particle i = ',i,' is not deleted'
	    stop 'error stop compress_particles: structure'
	  end if
	end do

	call mod_lagrange_handle_alloc(nbdy)

	end

!*******************************************************************

	subroutine test_compress

! tests compress routine

	implicit none

	integer nadd,nloop,i,ndel
	integer iloop,ntot,ip,ie
	real ggrand

	nadd = 3
	nloop = 20
	ie = 0

	do iloop=1,nloop

	do i=1,nadd
	  ie = ie + 1
	  call insert_particle_surface(ie,0,0.,1.,1.)
	end do

	call ntot_particles(ntot)

	ndel = nint(ggrand(99)*ntot)

	do i=1,ndel
	  ip = nint(ggrand(99)*ntot)
	  call delete_particle(ip)
	end do

	call print_elements('before compress')
	call compress_particles
	call print_elements('after compress')

	end do

	end

!*******************************************************************
!	call test_compress
!	end
!*******************************************************************

