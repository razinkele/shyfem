! test_projection_midpoint.f90
!
! Regression driver for the projection reference-point fix in
!   src/utils/shyutilmpi/coordinates.f90  (subroutine proj_geo2cart,
!   lines ~191-193): the CPP projection reference point must be the
!   MIDPOINT  0.5*(max+min)  of the lat/lon extent, NOT the half-range
!   0.5*(max-min).  With the half-range value the whole basin is shifted
!   by tens/thousands of km and the x-scaling cos(phi) is wrong.
!
! mar_menor is cartesian (isphe=0) and therefore never exercises
! proj_geo2cart.  This standalone driver drives the very same projection
! library (init_coords + convert_coords, CPP / iproj=3) with a small
! spherical (isphe=1) lat/lon patch and asserts:
!
!   (A) the midpoint reference maps the central node onto (0,0);
!   (B) the resulting cartesian spans are physically sane (km-scale and
!       consistent with the CPP metric 60*1852 m/deg, cos(phi) in x);
!   (C) the buggy half-range reference does NOT map the midpoint to the
!       origin -> locks in the semantics of the fix.
!
! Build + run:
!   cd testcases/projection_midpoint && make check
! or directly:
!   gfortran ../../src/utils/generic/projection.f90 \
!            test_projection_midpoint.f90 -o test_projection_midpoint
!   ./test_projection_midpoint      (exit code 0 = all passed, 1 = failure)
!
	program test_projection_midpoint

	implicit none

	integer, parameter :: n = 5
	real :: xg(n), yg(n)			!lon/lat (geographic)
	real :: xc(n), yc(n)			!x/y (cartesian, meters)
	double precision :: c_param(9)
	real :: xmin,xmax,ymin,ymax
	real :: midlon,midlat
	real :: halflon,halflat
	double precision :: yfact,xfact,rad
	double precision :: dxspan,dyspan,dxexp,dyexp
	double precision :: dorig
	integer :: nfail

	rad = atan(1.d0) / 45.d0		!pi/180
	nfail = 0

!------------------------------------------------------------------
! small lagoon-scale lat/lon box - 4 corners (mar-menor-like location,
! but any lat/lon works); node 5 will sit at the geometric midpoint
!------------------------------------------------------------------
	xg(1) = -0.85 ; yg(1) = 37.60		!SW
	xg(2) = -0.70 ; yg(2) = 37.60		!SE
	xg(3) = -0.85 ; yg(3) = 37.80		!NW
	xg(4) = -0.70 ; yg(4) = 37.80		!NE

	xmin = min(xg(1),xg(2),xg(3),xg(4))
	xmax = max(xg(1),xg(2),xg(3),xg(4))
	ymin = min(yg(1),yg(2),yg(3),yg(4))
	ymax = max(yg(1),yg(2),yg(3),yg(4))

	midlon  = 0.5*(xmax+xmin)		!MIDPOINT (the fix)
	midlat  = 0.5*(ymax+ymin)
	halflon = 0.5*(xmax-xmin)		!half-range (the bug)
	halflat = 0.5*(ymax-ymin)

	xg(5) = midlon ; yg(5) = midlat		!central node = midpoint

	write(6,*) 'lon min/max/mid  : ',xmin,xmax,midlon
	write(6,*) 'lat min/max/mid  : ',ymin,ymax,midlat

!==================================================================
! (A)+(B) MIDPOINT reference - mirrors proj_geo2cart c_phi/c_lon0/c_lat0
!==================================================================
	c_param    = 0.d0
	c_param(1) = midlat			!central latitude (phi)
	c_param(2) = midlon			!longitude of origin
	c_param(3) = midlat			!latitude of origin

	call init_coords(3,c_param)		!3 = CPP (equidist. cylindrical)
	call convert_coords(-1,n,xc,yc,xg,yg)	!-1 = geo -> cartesian

	write(6,*) 'midpoint node -> x,y [m] = ',xc(5),yc(5)

! (A) central node must map onto the cartesian origin
	if( abs(xc(5)) > 1.d-3 .or. abs(yc(5)) > 1.d-3 ) then
	  write(6,*) 'FAIL (A): midpoint node not at origin'
	  nfail = nfail + 1
	else
	  write(6,*) 'PASS (A): midpoint node at cartesian origin'
	end if

! (B) cartesian spans must match the physical CPP scaling (km-scale)
	yfact  = 60.d0 * 1852.d0		!m per degree latitude
	xfact  = yfact * cos(dble(midlat)*rad)	!m per degree longitude
	dyexp  = dble(ymax-ymin) * yfact	!expected N-S span [m]
	dxexp  = dble(xmax-xmin) * xfact	!expected E-W span [m]
	dyspan = dble(yc(3)) - dble(yc(1))	!NW - SW  (latitude offset)
	dxspan = dble(xc(2)) - dble(xc(1))	!SE - SW  (longitude offset)

	write(6,*) 'N-S span computed/expected [m]: ',dyspan,dyexp
	write(6,*) 'E-W span computed/expected [m]: ',dxspan,dxexp

	if( abs(dyspan-dyexp) > 1.d-3*dyexp .or. &
     &	    abs(dxspan-dxexp) > 1.d-3*dxexp ) then
	  write(6,*) 'FAIL (B): cartesian spans do not match CPP metric'
	  nfail = nfail + 1
	else if( dyspan < 1.d3 .or. dyspan > 1.d5 ) then
	  write(6,*) 'FAIL (B): N-S span out of km-scale range'
	  nfail = nfail + 1
	else
	  write(6,*) 'PASS (B): cartesian spans physically sane (km-scale)'
	end if

!==================================================================
! (C) HALF-RANGE reference (the pre-fix BUG) must NOT map the midpoint
!     onto the origin -> proves the midpoint reference is required
!==================================================================
	c_param    = 0.d0
	c_param(1) = halflat
	c_param(2) = halflon
	c_param(3) = halflat

	call init_coords(3,c_param)
	call convert_coords(-1,n,xc,yc,xg,yg)

	dorig = sqrt(dble(xc(5))**2 + dble(yc(5))**2)
	write(6,*) 'half-range: midpoint node -> x,y [m] = ',xc(5),yc(5)
	write(6,*) 'half-range: distance from origin [m] = ',dorig

	if( dorig < 1.d5 ) then
	  write(6,*) 'FAIL (C): half-range ref wrongly near origin'
	  nfail = nfail + 1
	else
	  write(6,*) 'PASS (C): half-range ref far from origin (the bug)'
	end if

!==================================================================
	if( nfail == 0 ) then
	  write(6,*) 'ALL PROJECTION MIDPOINT TESTS PASSED'
	else
	  write(6,*) 'PROJECTION MIDPOINT TESTS FAILED: ',nfail
	  call exit(1)
	end if

	end program test_projection_midpoint
