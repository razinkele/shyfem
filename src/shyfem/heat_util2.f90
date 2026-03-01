
!--------------------------------------------------------------------------
!
!    Copyright (C) 2010,2019  Georg Umgiesser
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
! 23.03.2010	ggu	changed v6.1.1
! 16.02.2019	ggu	changed VERS_7_5_60
! 21.05.2019	ggu	changed VERS_7_5_62

!*******************************************************************

	subroutine satur(t,p,ew,rw,qw)

! computes saturation values for water vapor
!
! e/p = r / ( eps + r )	=>  r = eps / ( p/e - 1 )
! r   = q / ( 1 - q )	=>  q = r / ( r + 1 )

	implicit none

	real, intent(in) :: t		!temperature [C]
	real, intent(in) :: p		!pressure [mb]
	real, intent(out) :: ew		!saturation vapor pressure [mb]
	real, intent(out) :: rw		!saturation mixing ratio [0-1]
	real, intent(out) :: qw		!saturation specific humidity [0-1]

	real eps				!molecular weight ratio
	parameter(eps=0.62197)
	real fice
!	parameter (fice=0.00422)		!over ice
	parameter (fice=0.0)
	real fsalt
!	parameter (fsalt=0.98)			!over salt
	parameter (fsalt=1.0)

	real aux,fw

	aux = (0.7859+0.03477*t)/(1.+0.00412*t)
	aux = aux + fice * t
	fw = 1. + 1.e-6 * p * (4.5+0.0006*t*t)

	ew = fsalt * fw * 10.**aux

	rw = eps / ( p/ew - 1. )
	qw = rw / ( rw + 1. )

	end

!*******************************************************************

	subroutine vapor(t,p,u,e,r,q)

! computes values for water vapor given relative humidity
!
! e/p = r / ( eps + r )	=>  r = eps / ( p/e - 1 )
! r   = q / ( 1 - q )	=>  q = r / ( r + 1 )
! u = r / rw

	implicit none

	real, intent(in) :: t		!temperature [C]
	real, intent(in) :: p		!pressure [mb]
	real, intent(in) :: u		!relative humidity [%] ([0-100])
	real, intent(out) :: e		!vapor pressure [mb]
	real, intent(out) :: r		!mixing ratio [0-1]
	real, intent(out) :: q		!specific humidity [0-1]

	real eps				!molecular weight ratio
	parameter(eps=0.62197)

	real ew,rw,qw

	call satur(t,p,ew,rw,qw)	!compute saturation values

	r = 0.01 * u * rw
	q = r / ( r + 1. )
	e = p * r / ( eps + r )

	end

!*******************************************************************

	subroutine smithb(w,cd)

	implicit none

	real, intent(in) :: w		!wind speed [m/s]
	real, intent(out) :: cd		!drag coefficient [-]

	if( w .le. 6. ) then
	  cd = 1.1e-3
	else
	  cd = 0.61e-3 + 0.063e-3 * w
	end if

	end

!*******************************************************************

	subroutine charnock(w,cd)

	use mod_physical_constants, only : g => grav_sp, &
     &			k => vonkarman_sp

	implicit none

	real, intent(in) :: w		!wind speed [m/s]
	real, intent(out) :: cd		!drag coefficient [-]

	real rho	!density of air [kg/m**3]
	real z		!anemometer height [m]
	real a		!Charnock constant [-]

	parameter(rho=1.25,z=10.,a=0.0185)

	real cdold,aux,tau

	cd = 1.5e-3
	cdold = 0.
	
	do while( abs(cd-cdold) .gt. 1.e-5 )
	  cdold = cd
	  tau = cd * rho * w * w
	  aux = rho * g * z / ( a * tau )
	  cd = ( k / log(aux) )**2
	end do

	end

!*******************************************************************

	subroutine chartest

	implicit none

	integer :: i
	real :: w,cd1,cd2

	do i=1,20
	  w = i
	  call charnock(w,cd1)
	  call smithb(w,cd2)
	  write(6,*) w,cd1,cd2
	end do

	end

!*******************************************************************
!*******************************************************************
!*******************************************************************

!	call chartest
!	end

!*******************************************************************

