
!--------------------------------------------------------------------------
!
!    Copyright (C) 1999,2005,2007,2009-2019  Georg Umgiesser
!    Copyright (C) 2017  Christian Ferrarin
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

! assimilation routines
!
! revision log :
!
! 17.10.2025    ggu     new routine scalar_nudging()
! 21.10.2025    ggu     new routine scalar_assimilation()
! 24.10.2025    ggu     first draft of assimilation ready
! 27.10.2025    ggu     pass 3d array, change of names
! 30.10.2025    ggu     bug fixes
! 07.11.2025    ggu     introduced iuse
! 10.11.2025    ggu     general assimilation of scalar variables
! 14.11.2025    ggu     set up debug file
! 13.12.2025    ggu     new routine make_vertical_correlation()
! 22.07.2026    arb     3d application completed: layer/vcorlength
!                       parsed, increment distributed with gaussian
!                       vertical weights (2d path kept verbatim)
! 22.07.2026    arb     ported to razinkele/shyfem: observation-window
!                       check no longer hidden behind the debug flag,
!                       debug file opt-in with newunit, checked opens,
!                       collective-safe aborts, get_bobs local z(3)
!
!****************************************************************

!*******************************************************************
!*******************************************************************
!*******************************************************************

	subroutine scalar_assimilation(idass,zback)

! assimilation of scalar
!
! mode == 0	nudging with tau
! mode == 1	apply zanal directly - at tau intervals

	use basin
	use levels
	use shympi
	use intp_fem_file
	use mod_assimil_admin

	implicit none

	integer idass
	real zback(nlvdi,nkn)

	real, allocatable :: xobs(:), yobs(:)
	real, allocatable :: bobs(:), zobs(:), zaux(:)
	real, save, allocatable :: zanal(:)
	real, save, allocatable :: zback2d(:)
	logical bback
	logical basstime
	integer iu,ierr
	integer, save :: iudbg = 0
	integer nintp,i
	integer mode
	integer nback,ivar,iusec,inofc
	integer, save :: nvar,idobs
	integer, save :: icall = 0
	integer, save :: nobs = 0
	real tau,rtau,dt,tacum
	real alpha,vcorr
	integer lobs,l
	real rwgt(nlvdi)
	real, allocatable :: zincr(:)
	real, parameter :: flag = -999.
	double precision dtime
	character*80 file_coords
	character*80 file_obs
	character*20 aline
	logical, save :: bdebug = .false.
	logical bwrite

	integer ifemop

	if( icall == -1 ) return
	if( idass == 0 ) return

!---------------------------------------------------------------
! check basics and set parameters
!---------------------------------------------------------------

	! 3d: the analysis is computed on the observation layer and its
	! increment applied over the vertical with gaussian weights from
	! make_vertical_correlation (layer 0 or vcorlength 0 -> uniform)

	call get_act_dtime(dtime)

	nintp = 2
	nback = nkn
	bback = .true.

	bwrite = bdebug .and. my_id == 0

!---------------------------------------------------------------
! initialize at first call
!---------------------------------------------------------------

	if( icall == 0 ) then		!global initialization

	  nobs = passim(idass)%nobs
	  if( nobs <= 0 ) icall = -1
	  if( icall == -1 ) return

	  allocate(zanal(nkn),zback2d(nkn),stat=ierr)
	  if( ierr /= 0 ) then
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: allocation')
	  end if

	  if( bdebug .and. my_id == 0 ) then	!only the master writes
	    iudbg = ifemop('assdbg','formatted','unknown')
	    if( iudbg <= 0 ) then
	      call shympi_abort_internal( &
     &		'error stop scalar_assimilation: cannot open debug file')
	    end if
	  end if

	end if

	if( .not. passim(idass)%binit ) then

	  file_obs = passim(idass)%fileobs
	  file_coords = passim(idass)%filecoords

	  nobs = 0
	  open(newunit=iu,file=file_coords,status='old' &
     &		,form='formatted',iostat=ierr)
	  if( ierr /= 0 ) then
	    write(6,*) 'cannot open coordinate file: ',trim(file_coords)
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: opening filecoords')
	  end if
	  allocate(xobs(0),yobs(0))	!not written in counting mode
	  call read_coords(iu,nobs,xobs,yobs)	!only count
	  if( nobs == 0 ) then
	    ! an empty coords file contradicts the nobs of the STR
	    ! section - abort instead of silently disabling (upstream
	    ! set a global icall=-1 here, killing ALL instances)
	    write(6,*) 'no coordinates in file: ',trim(file_coords)
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: empty filecoords')
	  end if
	  deallocate(xobs,yobs)
	  allocate(xobs(nobs),yobs(nobs),stat=ierr)
	  if( ierr /= 0 ) then
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: allocation')
	  end if
	  rewind(iu)
	  call read_coords(iu,nobs,xobs,yobs)	!read coords
	  close(iu)

	  if( nobs /= passim(idass)%nobs ) then
	    write(6,*) 'nobs: ',nobs,passim(idass)%nobs
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: nobs incompatible')
	  end if

	  allocate(passim(idass)%xobs(nobs),passim(idass)%yobs(nobs) &
     &		,passim(idass)%ies(nobs),stat=ierr)
	  if( ierr /= 0 ) then
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: allocation')
	  end if
	  passim(idass)%xobs = xobs
	  passim(idass)%yobs = yobs
	  passim(idass)%ies = -1		!still to be initialized
	  deallocate(xobs,yobs)

	  if( shympi_is_master() ) then
	    write(6,*) 'assimilation observations read: ',nobs
	  end if

	  nvar = nobs
	  call iff_ts_init(dtime,file_obs,nintp,nvar,idobs)
	  passim(idass)%idobs = idobs

	  if( nobs /= nvar ) then	!iff_ts_init returns file columns
	    write(6,*) 'nobs,nvar: ',nobs,nvar
	    write(6,*) 'number of coordinates and observations are different'
	    call shympi_abort_internal( &
     &		'error stop scalar_assimilation: nobs/=nvar')
	  end if

	  if( bwrite ) write(iudbg,*) 'starting optintp: ',nobs

	  passim(idass)%binit = .true.
	end if

	icall = icall + 1

	nobs = passim(idass)%nobs
	if( nobs <= 0 ) return
	ivar = passim(idass)%ivar
	idobs = passim(idass)%idobs

!---------------------------------------------------------------
! see if in observation window
!---------------------------------------------------------------

	! this check must run unconditionally - upstream had it inside
	! the debug branch, so without debug the interpolation below ran
	! outside the observation window
	if( .not. iff_file_has_data(idobs,dtime) ) then
	  if( bwrite ) then
	    call get_timeline(dtime,aline)
	    write(iudbg,*) 'file has no data  ',aline,dtime,ivar
	  end if
	  return
	end if

	if( bwrite ) then
	  call get_timeline(dtime,aline)
	  write(iudbg,*) 'file has data  ',aline,dtime,ivar
	  write(iudbg,*) 'doing optintp',dtime
	end if

!---------------------------------------------------------------
! see if assimilation time step has arrived
!---------------------------------------------------------------

	call get_timestep(dt)
	tau = passim(idass)%tau
	tacum = passim(idass)%tacum
	mode = passim(idass)%mode

	if( mode == 1 ) then
	  tacum = tacum + dt
	  basstime = ( tacum >= tau )	!do assimilation at this time
	  if( basstime ) tacum = tacum - tau
	  if( tau <= 0. ) tacum = 0.	!apply every step - don't accumulate
	  passim(idass)%tacum = tacum
	  if( bwrite ) then
	    write(iudbg,*) 'checking assimilation in time',basstime,tacum
	  end if
	  if( .not. basstime ) return
	end if

	if( bwrite ) write(iudbg,*) 'doing assimilation in time',dtime

!---------------------------------------------------------------
! allocate arrays
!---------------------------------------------------------------

	allocate(xobs(nobs),yobs(nobs))
	allocate(bobs(nobs),zobs(nobs),zaux(nobs))

	xobs = passim(idass)%xobs
	yobs = passim(idass)%yobs

!---------------------------------------------------------------
! interpolate observations in time
!---------------------------------------------------------------

	idobs = passim(idass)%idobs
	call iff_ts_intp(idobs,dtime,zobs)
	where( passim(idass)%iuse == 0 ) zobs = flag

!---------------------------------------------------------------
! compute background values at observation points
!---------------------------------------------------------------

	lobs = max(1,passim(idass)%layer(1))	!0 = column -> use surface
	if( lobs > nlvdi ) then
	  write(6,*) 'layer,nlvdi: ',lobs,nlvdi
	  call shympi_abort_internal( &
     &		'error stop scalar_assimilation: layer > nlvdi')
	end if
	zback2d = zback(lobs,:)
	call get_bobs(nobs,xobs,yobs,zback2d,bobs,passim(idass)%ies)

!---------------------------------------------------------------
! do optimal interpolation
!---------------------------------------------------------------

	!write(6,*) passim(idass)%sigback
	!write(6,*) passim(idass)%sigobs
	call opt_intp(nobs,xobs,yobs,zobs,bobs                          &
     &                  ,nback,bback,xgv,ygv,zback2d			&
     &                  ,passim(idass)%corlength			&
     &                  ,passim(idass)%maxlength			&
     &                  ,passim(idass)%sigback				&
     &                  ,passim(idass)%sigobs				&
     &                  ,zanal)

!---------------------------------------------------------------
! write debug message to file
!---------------------------------------------------------------

!	zobs is observations interpolated at actual time
!	bobs is background at observation points
!	zaux is analysis at obervation points

	if( bdebug ) then
	  call get_bobs(nobs,xobs,yobs,zanal,zaux,passim(idass)%ies)
	  if( my_id == 0 ) then
	    iusec = sum(passim(idass)%iuse)
	    inofc = count(zobs/=flag)
	    write(iudbg,*) 'final optimal interpolation: ',nobs,iusec,inofc,ivar
	    do i=1,nobs
	      if( zobs(i) == flag ) then
		if( bobs(i) /= zaux(i) ) then
		  !analysis moved at a flagged station - legitimate when
		  !it lies within maxlength of an active station
		  write(iudbg,*) 'analysis changed at flagged' &
     &			//' station: ',i,bobs(i),zaux(i)
		end if
		cycle
	      end if
	      write(iudbg,*) i,zobs(i),bobs(i),zaux(i)
	    end do
	  end if
	end if

!---------------------------------------------------------------
! apply the analysis (nudging or direct insertion)
!---------------------------------------------------------------

	if( mode /= 0 .and. mode /= 1 ) then
	  write(6,*) 'error in mode: ',mode
	  call shympi_abort_internal( &
     &		'error stop scalar_assimilation: error in mode')
	end if
	if( mode == 0 .and. tau <= 0. ) then
	  write(6,*) 'for mode==0 tau>0 must be given'
	  call shympi_abort_internal( &
     &		'error stop scalar_assimilation: mode==0 and tau==0')
	end if

	if( nlvdi == 1 ) then

	  ! 2d path - kept verbatim (bit-identical to the original)
	  if( mode == 0 ) then	!nudging
	    if( bwrite ) write(iudbg,*) 'doing nudging'
	    rtau = 1./tau
	    call scalar_nudging_0(dt,zback2d,zanal,rtau)
	  else			!apply directly
	    zback2d = zanal
	  end if
	  zback(1,:) = zback2d

	else

	  ! 3d path: distribute the analysis increment of the
	  ! observation layer over the vertical. weights: 1 at the
	  ! observation layer, gaussian decay with vcorlength [m];
	  ! layer 0 or vcorlength 0 -> uniform over the column.
	  ! mode 0 uses the implicit-nudging factor alpha = r/(1+r),
	  ! algebraically identical to scalar_nudging_0 at the
	  ! observation layer itself
	  vcorr = passim(idass)%vcorlength(1)
	  if( passim(idass)%layer(1) <= 0 .or. vcorr <= 0. ) then
	    rwgt = 1.
	  else
	    call make_vertical_correlation(vcorr,lobs,rwgt)
	  end if

	  alpha = 1.
	  if( mode == 0 ) then
	    if( bwrite ) write(iudbg,*) 'doing nudging (3d)'
	    rtau = dt/tau
	    alpha = rtau/(1.+rtau)
	  end if

	  ! apply per node only over its existing layers - writing
	  ! below the local bottom corrupts inactive layer slots that
	  ! other code may still read
	  allocate(zincr(nkn))
	  zincr = zanal - zback2d
	  do i=1,nkn
	    do l=1,ilhkv(i)
	      if( rwgt(l) <= 0. ) cycle
	      zback(l,i) = zback(l,i) + alpha*rwgt(l)*zincr(i)
	    end do
	  end do
	  deallocate(zincr)

	end if

!---------------------------------------------------------------
! end of routine
!---------------------------------------------------------------

	end

!*******************************************************************

	subroutine scalar_nudging(dt,scal,sobs,rtau)

! does nudging of scalars - implicit - rtau matrix version

	use basin
	use levels

	implicit none

	real, intent(in) :: dt			!time step
	real, intent(inout) :: scal(nlvdi,nkn)	!scalar
	real, intent(in) :: sobs(nlvdi,nkn)	!observation of scalar
	real, intent(in) :: rtau(nlvdi,nkn)	!inverse of time scale tau

	integer k,l,lmax
	real r,rr

	do k=1,nkn
	  lmax = ilhkv(k)
	  do l=1,lmax
	    r = dt * rtau(l,k)
	    rr = 1./(1.+r)
	    scal(l,k) = rr*scal(l,k) + (1.-rr)*sobs(l,k)
	  end do
	end do

	end

!*******************************************************************

	subroutine scalar_nudging_0(dt,scal,sobs,rtau)

! does nudging of scalars - implicit - rtau scalar version

	use basin
	use levels

	implicit none

	real, intent(in) :: dt			!time step
	real, intent(inout) :: scal(nlvdi,nkn)	!scalar
	real, intent(in) :: sobs(nlvdi,nkn)	!observation of scalar
	real, intent(in) :: rtau		!inverse of time scale tau

	integer k,l,lmax
	real r,rr

	r = dt * rtau
	rr = 1./(1.+r)

	do k=1,nkn
	  lmax = ilhkv(k)
	  do l=1,lmax
	    scal(l,k) = rr*scal(l,k) + (1.-rr)*sobs(l,k)
	  end do
	end do

	end

!*******************************************************************

	subroutine read_coords(iu,nobs,xobs,yobs)

	implicit none

	integer iu
	integer nobs
	real xobs(nobs), yobs(nobs)

	integer i,j
	integer ios
	real x,y
	character*80 name

	i = 0
	do
	  read(iu,*,iostat=ios) j,x,y
	  if( ios < 0 ) exit
	  if( ios > 0 ) goto 99
	  i = i + 1
	  if( i /= j ) goto 98
	  if( nobs == 0 ) cycle
	  if( i > nobs) goto 97
	  xobs(i) = x
	  yobs(i) = y
	end do

	nobs = i

	return
   97	continue
	write(6,*) 'i,nobs: ',i,nobs
	call shympi_abort_internal('error stop read_coords: i>nobs')
   98	continue
	write(6,*) 'i,j: ',i,j
	call shympi_abort_internal('error stop read_coords: i/=j')
   99	continue
	inquire(iu,name=name)
	write(6,*) 'reading file ',trim(name)
	write(6,*) 'read error close to line ',i
	call shympi_abort_internal('error stop read_coords: read error')
	end

!*******************************************************************

	subroutine get_bobs(nobs,xobs,yobs,zback,bobs,ies)

! get value of the background grid on observation points

	use basin
	use levels
	use shympi

	implicit none

	integer nobs
	real xobs(nobs)
	real yobs(nobs)
	real zback(nkn)		!2d field (extracted layer)
	real bobs(nobs)
	integer ies(nobs)	!element where obs point is in

	integer i,ie,n,ii,k
	integer, save :: icall = 0
	integer iaux(nobs)
	real zp
	real z(3)	!upstream had z(nobs) - out of bounds for nobs < 3

	if( ies(1) == -1 ) then
	  ies = 0
	  iaux = 0

	  do i=1,nobs
	    call find_element(xobs(i),yobs(i),ie)
	    if( ie <= 0 ) cycle
	    if( ie > nel_unique ) cycle
	    ies(i) = ie
	    iaux(i) = 1
	  end do

	  call shympi_gather_and_sum(iaux)
	  n = sum(iaux)
	  if( any(iaux==0) .or. n /= nobs ) then
	    write(6,*) n,nobs
	    write(6,*) iaux
	    write(6,*) ies
	    if( any(iaux==0) ) then
	      write(6,*) 'observation point outside the grid'
	    else
	      write(6,*) 'observation point found on more than one' &
     &			//' rank (lies on a subdomain boundary) -' &
     &			//' move the point slightly'
	    end if
	    call shympi_abort_internal( &
     &		'error stop get_bobs: bad observation location')
	  end if
	end if

	icall = icall + 1

	bobs = 0.
	do i=1,nobs
	  ie = ies(i)
	  if( ie == 0 ) cycle
	  do ii=1,3
	    k = nen3v(ii,ie)
	    z(ii) = zback(k)
	  end do
	  call femintp(ie,z,xobs(i),yobs(i),zp)
	  bobs(i) = zp
	end do

	call shympi_gather_and_sum(bobs)

	end

!*******************************************************************

        subroutine assimil_ts(tarray,sarray)

	use basin
	use levels
	use shympi
	use mod_assimil_admin

        implicit none

	real tarray(nlvdi,nkn)
	real sarray(nlvdi,nkn)

	integer, save :: icall = 0
	integer, save :: idtemp = 0
	integer, save :: idsalt = 0

	if( icall == -1 ) return

	if( icall == 0 ) then
	  idtemp = get_id_from_var(12)
	  idsalt = get_id_from_var(11)
	end if

	icall = icall + 1
	
	if( idtemp /= 0 ) call scalar_assimilation(idtemp,tarray)
	if( idsalt /= 0 ) call scalar_assimilation(idsalt,sarray)

        end

!*******************************************************************

        subroutine assimil_init_ids(nvar,ivars,ids)

! initializes array ids

	use mod_assimil_admin

	implicit none

	integer, intent(in) 	:: nvar
	integer, intent(in) 	:: ivars(nvar)
	integer, intent(inout) 	:: ids(3,nvar)

	integer id,iv,ivar
	integer idmax

	ids = -1
	idmax = 0
	do iv=1,nvar
	  id = get_id_from_var(ivars(iv))
	  if( id > 0 ) then
	    idmax = idmax + 1
	    ids(1,idmax) = id
	    ids(2,idmax) = iv
	    ids(3,idmax) = ivars(iv)
	  end if
	end do

	end

!*******************************************************************

        subroutine assimil_3dvars(nvar,ivars,array,ids)

! goes through all variables and checks if assimilation has to be carried out
!
! ids on first call must be set to 0

	use basin
	use levels
	use shympi
	use mod_assimil_admin

        implicit none

	integer, intent(in) 	:: nvar
	integer, intent(in) 	:: ivars(nvar)
	real, intent(inout) 	:: array(nlvdi,nkn,nvar)	!analysis written back
	integer, intent(inout) 	:: ids(3,nvar)

	integer i,id,iv,ivar
	integer idmax

	if( ids(1,1) == -1 ) return

	if( ids(1,1) == 0 ) call assimil_init_ids(nvar,ivars,ids)

	do i=1,nvar
	  id = ids(1,i)
	  if( id < 0 ) exit		!no more variables to assimilate
	  iv = ids(2,i)
	  ivar = ids(3,i)
	  write(6,*) 'doing assimilation for ivar = ',ivar
	  call scalar_assimilation(id,array(:,:,iv))
	end do

        end

!*******************************************************************

        subroutine assimil_2dvars(nvar,ivars,array,ids)

! goes through all variables and checks if assimilation has to be carried out
!
! ids on first call must be set to 0

	use basin
	use levels
	use shympi
	use mod_assimil_admin

        implicit none

	integer, intent(in) 	:: nvar
	integer, intent(in) 	:: ivars(nvar)
	real, intent(inout) 	:: array(nkn,nvar)	!analysis written back
	integer, intent(inout) 	:: ids(3,nvar)	!upstream had ids(2,..) - OOB in init

	integer i,id,iv,ivar
	integer idmax

	if( ids(1,1) == -1 ) return

	if( ids(1,1) == 0 ) call assimil_init_ids(nvar,ivars,ids)

	do i=1,nvar
	  id = ids(1,i)
	  if( id < 0 ) exit		!no more variables to assimilate
	  iv = ids(2,i)
	  ivar = ivars(iv)
	  write(6,*) 'doing assimilation for ivar = ',ivar
	  call scalar_assimilation(id,array(:,iv))
	end do

        end

!*******************************************************************

	subroutine make_vertical_correlation(vcorr,layer,r)

	use levels

	implicit none

	real vcorr
	integer layer
	real r(nlvdi)
	
	integer l
	real htop,hbottom,hc0,h
	real hc(nlvdi)
	logical has_sigma_levels

	if( has_sigma_levels() ) then
	  call shympi_abort_internal( &
     &		'error stop make_vertical_correlation: no sigma layers')
	else if( layer > nlvdi ) then
	  write(6,*) 'layer,nlv: ',layer,nlv
	  call shympi_abort_internal( &
     &		'error stop make_vertical_correlation: impossible layer')
	end if

	htop = 0.
	do l=1,nlv
	  hbottom = hlv(l)
	  hc(l) = ( hbottom + htop ) / 2.
	  htop = hbottom
	end do

	if( layer <= 0 ) then
	  r = 1.
	else
	  hc0 = hc(layer)
	  do l=1,nlv
	    h = hc(l)
	    !upstream: whole-array assign AND '/2.*vcorr**2' which
	    !MULTIPLIES by vcorr**2 - larger length gave narrower kernel
	    r(l) = exp( -(h-hc0)**2 / (2.*vcorr**2) )
	  end do
	end if

	end

!*******************************************************************

