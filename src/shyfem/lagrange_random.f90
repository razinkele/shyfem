
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

! random numbers of the Lagrangian particle module (#225)
!
! Every random draw of the particle module is a pure function of
!
!   (seed, particle id, time step, draw index)
!
! computed by a counter-based generator, so a draw does not depend on the
! order in which particles, OpenMP threads or MPI processes make their
! draws: a run gives the same particle file on any number of threads and
! (with the ids of #217) of processes, and two runs of the same case are
! identical.
!
! generator: Threefry-4x32 with 20 rounds, from
!   J. K. Salmon, M. A. Moraes, R. O. Dror, D. E. Shaw, "Parallel random
!   numbers: as easy as 1, 2, 3", Proceedings of the 2011 International
!   Conference for High Performance Computing, Networking, Storage and
!   Analysis (SC11), doi:10.1145/2063384.2063405,
! as in the reference implementation Random123 (D. E. Shaw Research,
! include/Random123/threefry.h: the rotation constants R_32x4, the key
! parity 0x1BD11BDA and the key schedule). Threefry uses only additions
! modulo 2**32, rotations and exclusive ors of 32-bit words. Here each word
! is held in an integer(kind=8) in 0 .. 2**32-1: a sum of two words is
! below 2**33 and is masked to 32 bits, a word shifted left by at most 31
! bits stays below 2**63, so no signed integer overflows and no result
! depends on how the compiler treats one. The output words of the test
! vectors of Random123 (tests/kat_vectors) are checked by the self-test.
!
! packing of the keys (32-bit words, two's complement for negative values):
!   key     (seed, id, 0, 0)
!   counter (step low 32 bits, step high 32 bits, draw index, 0)
! The first output word, then the high 20 bits of the second, give a 52-bit
! integer k; the double is (2k+1)/2**53, in the open interval (0,1): never
! 0 or 1 (2**-53 and 1-2**-53 at the extremes). The single precision value
! the model uses (lgr_rand_r) is built from the high 23 bits k' of the
! first word as (2k'+1)/2**24, exactly representable in single precision,
! so it too lies in (0,1) (2**-24 and 1-2**-24 at the extremes): a double
! just below 1 converted to single would round to 1.0.
!
! the keys in the model (lgr_random):
!   seed   the parameter lgrseed of $lagrg (lgr_random_set_seed)
!   id     the particle id (equal in serial and multi-process runs, #217)
!   step   the absolute time of the time step in milliseconds
!          (lgr_random_set_step, once per call of lagrange): the same on
!          every process, and in a run restarted from a particle file
!          (lgrini, itlgin) the same step has the same time, so a particle
!          draws what it drew in the run that went on. Two steps less than
!          1 ms apart would share the key.
!   draw   lgr_rnd_index(site,n) = site*2**24 + n: each kind of draw has its
!          own site (lgr_rnd_hdiff ...), and n numbers the draws of one site
!          for one particle in one step. A particle makes the draws of a site
!          at most once per step, wherever it is (advection draws nothing;
!          a particle handed over at a cut-off side makes its diffusion and
!          beaching draws on the process where its advection ends; a parked
!          particle resumes after its draws), so nothing about the draws has
!          to travel with a particle that changes process. Only the vertical
!          diffusion draws a varying number of values, all inside one call
!          of diff_body (it counts them in a local variable).
! Draws of a release that belong to no particle (continuous release: the
! offset along a boundary, the number of particles of a point, the element
! at a node) come from lgr_random_release: id 0, site lgr_rnd_release, n
! counted from 0 in each step, in the order of the serial release code
! (outside any parallel region; that release stops on several processes).
!
! contents :
!
! lgr_rand_u		double in (0,1) of (seed, id, step, draw index)
! lgr_rand_r		single precision value in (0,1) of the same keys
! lgr_rnd_index		draw index of a site and a count
! lgr_random		single precision draw of a particle in this step
! lgr_random_dp		the same draw in double precision
! lgr_random_release	next draw of the release stream of this step
! lgr_random_set_seed	sets the seed (lgrseed)
! lgr_random_set_step	sets the step key from the absolute time
! lgr_threefry4x32	the Threefry-4x32 block function
! lgr_rnd_words		the two output words of the keys
! lgr_rnd_bits_u	double of two output words
! lgr_rnd_bits_r	single precision value of one output word
! lgr_random_selftest	test vectors, frozen values and statistics

	module mod_lagrange_random

	implicit none

	private

	! sites of the draws (the draw index is site*2**24 + n)
	integer, parameter, public :: lgr_rnd_hdiff = 1    !horizontal random walk: n 0 x, 1 y
	integer, parameter, public :: lgr_rnd_vdiff = 2    !vertical diffusion (n counted)
	integer, parameter, public :: lgr_rnd_beach = 3    !beaching
	integer, parameter, public :: lgr_rnd_relz = 4     !random depth at release
	integer, parameter, public :: lgr_rnd_sedclass = 5 !sediment class at release
	integer, parameter, public :: lgr_rnd_sedim = 6    !deposition and erosion
	integer, parameter, public :: lgr_rnd_decay = 7    !decay
	integer, parameter, public :: lgr_rnd_larva = 8    !larvae
	integer, parameter, public :: lgr_rnd_relpos = 9   !place on a boundary segment
	integer, parameter, public :: lgr_rnd_reltime = 10 !time of release in the step
	integer, parameter, public :: lgr_rnd_release = 11 !release stream (id 0)

	integer, parameter, public :: lgr_rnd_seed_default = 1 !default of lgrseed

	! seed and step key: read anywhere, written only by
	! lgr_random_set_seed and lgr_random_set_step (protected)
	integer, save, public, protected :: lgr_rnd_seed = lgr_rnd_seed_default
	integer(kind=8), save, public, protected :: lgr_rnd_step = 0  !step key [ms]
	integer, save :: lgr_rnd_nrel = 0                  !release draws in step

	integer(kind=8), parameter :: mask32 = 4294967295_8   !2**32-1
	integer(kind=8), parameter :: parity = 466688986_8    !0x1BD11BDA
	integer, parameter :: nsite = 16777216                !2**24
	! rotation constants R_32x4_r_0, R_32x4_r_1 of Random123, r = 0 ... 7
	integer, parameter :: rot(0:1,0:7) = reshape(			&
     &		(/ 10,26, 11,21, 13,27, 23,5, 6,20, 17,11, 25,10, 18,20 /)	&
     &		,(/2,8/))

	public :: lgr_rand_u, lgr_rand_r, lgr_rnd_index
	public :: lgr_random, lgr_random_dp, lgr_random_release
	public :: lgr_random_set_seed, lgr_random_set_step
	public :: lgr_threefry4x32, lgr_rnd_words
	public :: lgr_rnd_bits_u, lgr_rnd_bits_r
	public :: lgr_random_selftest

	contains

!*******************************************************************

	pure function add32(a,b)

! sum of two 32-bit words modulo 2**32

	implicit none

	integer(kind=8) :: add32
	integer(kind=8), intent(in) :: a,b

	add32 = iand(a+b,mask32)

	end function add32

!*******************************************************************

	pure function rotl32(a,r)

! 32-bit word a rotated left by r bits (1 <= r <= 31)

	implicit none

	integer(kind=8) :: rotl32
	integer(kind=8), intent(in) :: a
	integer, intent(in) :: r

	rotl32 = iand(ior(ishft(a,r),ishft(a,r-32)),mask32)

	end function rotl32

!*******************************************************************

	pure subroutine lgr_threefry4x32(nrounds,ctr,key,x)

! the Threefry-4x32 block function with nrounds rounds (20 in the model;
! 13 and 72 only for the test vectors): output words x of the counter ctr
! and the key key, all 32-bit words in 0 .. 2**32-1

	implicit none

	integer, intent(in) :: nrounds
	integer(kind=8), intent(in) :: ctr(0:3)
	integer(kind=8), intent(in) :: key(0:3)
	integer(kind=8), intent(out) :: x(0:3)

	integer(kind=8) :: ks(0:4)
	integer :: i,r,s,ir

	ks(4) = parity
	do i=0,3
	  ks(i) = key(i)
	  ks(4) = ieor(ks(4),key(i))
	  x(i) = add32(ctr(i),key(i))
	end do

	do r=0,nrounds-1
	  ir = mod(r,8)
	  if( mod(r,2) == 0 ) then
	    x(0) = add32(x(0),x(1))
	    x(1) = ieor(rotl32(x(1),rot(0,ir)),x(0))
	    x(2) = add32(x(2),x(3))
	    x(3) = ieor(rotl32(x(3),rot(1,ir)),x(2))
	  else
	    x(0) = add32(x(0),x(3))
	    x(3) = ieor(rotl32(x(3),rot(0,ir)),x(0))
	    x(2) = add32(x(2),x(1))
	    x(1) = ieor(rotl32(x(1),rot(1,ir)),x(2))
	  end if
	  if( mod(r,4) == 3 ) then		!key injection s
	    s = (r+1)/4
	    do i=0,3
	      x(i) = add32(x(i),ks(mod(s+i,5)))
	    end do
	    x(3) = add32(x(3),int(s,8))
	  end if
	end do

	end subroutine lgr_threefry4x32

!*******************************************************************

	pure subroutine lgr_rnd_words(iseed,id,istep,idraw,w0,w1)

! the first two output words of Threefry-4x32-20 for the keys (see the
! header for the packing)

	implicit none

	integer, intent(in) :: iseed		!seed
	integer, intent(in) :: id		!particle id
	integer(kind=8), intent(in) :: istep	!step key
	integer, intent(in) :: idraw		!draw index
	integer(kind=8), intent(out) :: w0,w1

	integer(kind=8) :: ctr(0:3),key(0:3),x(0:3)

	key(0) = iand(int(iseed,8),mask32)
	key(1) = iand(int(id,8),mask32)
	key(2) = 0
	key(3) = 0
	ctr(0) = iand(istep,mask32)
	ctr(1) = iand(ishft(istep,-32),mask32)
	ctr(2) = iand(int(idraw,8),mask32)
	ctr(3) = 0

	call lgr_threefry4x32(20,ctr,key,x)
	w0 = x(0)
	w1 = x(1)

	end subroutine lgr_rnd_words

!*******************************************************************

	pure function lgr_rnd_bits_u(w0,w1)

! double (2k+1)/2**53 in (0,1), k = the 32 bits of w0 and the high 20 bits
! of w1 (k < 2**52, so 2k+1 < 2**53 is exact in double precision)

	implicit none

	double precision :: lgr_rnd_bits_u
	integer(kind=8), intent(in) :: w0,w1

	integer(kind=8) :: k

	k = ior(ishft(iand(w0,mask32),20),ishft(iand(w1,mask32),-12))
	lgr_rnd_bits_u = dble(2*k+1) * 2.d0**(-53)

	end function lgr_rnd_bits_u

!*******************************************************************

	pure function lgr_rnd_bits_r(w0)

! single precision (2k+1)/2**24 in (0,1), k = the high 23 bits of w0
! (2k+1 < 2**24 has at most 24 significant bits: exact in single
! precision, so the largest value is 1-2**-24, never 1)

	implicit none

	real :: lgr_rnd_bits_r
	integer(kind=8), intent(in) :: w0

	integer(kind=8) :: k

	k = ishft(iand(w0,mask32),-9)
	lgr_rnd_bits_r = real( dble(2*k+1) * 2.d0**(-24) )

	end function lgr_rnd_bits_r

!*******************************************************************

	pure function lgr_rand_u(iseed,id,istep,idraw)

! double in the open interval (0,1) of (seed, id, step, draw index)

	implicit none

	double precision :: lgr_rand_u
	integer, intent(in) :: iseed,id,idraw
	integer(kind=8), intent(in) :: istep

	integer(kind=8) :: w0,w1

	call lgr_rnd_words(iseed,id,istep,idraw,w0,w1)
	lgr_rand_u = lgr_rnd_bits_u(w0,w1)

	end function lgr_rand_u

!*******************************************************************

	pure function lgr_rand_r(iseed,id,istep,idraw)

! single precision value in the open interval (0,1) of (seed, id, step,
! draw index): the high 23 bits of the first word of lgr_rand_u

	implicit none

	real :: lgr_rand_r
	integer, intent(in) :: iseed,id,idraw
	integer(kind=8), intent(in) :: istep

	integer(kind=8) :: w0,w1

	call lgr_rnd_words(iseed,id,istep,idraw,w0,w1)
	lgr_rand_r = lgr_rnd_bits_r(w0)

	end function lgr_rand_r

!*******************************************************************

	pure function lgr_rnd_index(isite,n)

! draw index of the n-th draw (from 0) of site isite (1 ... 127): n is
! taken modulo 2**24

	implicit none

	integer :: lgr_rnd_index
	integer, intent(in) :: isite,n

	lgr_rnd_index = isite*nsite + modulo(n,nsite)

	end function lgr_rnd_index

!*******************************************************************

	pure function lgr_random(id,isite,n)

! single precision draw in (0,1) of particle id in the current step: the
! n-th draw (from 0) of site isite; reads only the seed and the step key,
! which are set outside the parallel regions, so it can be called from
! the OpenMP particle loop

	implicit none

	real :: lgr_random
	integer, intent(in) :: id,isite,n

	lgr_random = lgr_rand_r(lgr_rnd_seed,id,lgr_rnd_step		&
     &				,lgr_rnd_index(isite,n))

	end function lgr_random

!*******************************************************************

	pure function lgr_random_dp(id,isite,n)

! double precision draw in (0,1) of particle id in the current step: the
! value of the same keys as lgr_random (which keeps the high 23 bits of
! its first word), with 52 bits, for a test against a small probability
! (decay: the probability of a step can be far below 2**-23, #246);
! reads only the seed and the step key, as lgr_random

	implicit none

	double precision :: lgr_random_dp
	integer, intent(in) :: id,isite,n

	lgr_random_dp = lgr_rand_u(lgr_rnd_seed,id,lgr_rnd_step		&
     &				,lgr_rnd_index(isite,n))

	end function lgr_random_dp

!*******************************************************************

	function lgr_random_release()

! next draw of the release stream of the current step (id 0, site
! lgr_rnd_release, counted from 0 in each step): for the draws of a release
! that belong to no particle. Serial code only (it counts in a saved
! variable): never call it inside a parallel region

	implicit none

	real :: lgr_random_release

	lgr_random_release = lgr_rand_r(lgr_rnd_seed,0,lgr_rnd_step	&
     &			,lgr_rnd_index(lgr_rnd_release,lgr_rnd_nrel))
	lgr_rnd_nrel = lgr_rnd_nrel + 1

	end function lgr_random_release

!*******************************************************************

	subroutine lgr_random_set_seed(iseed)

! sets the seed of every draw (the parameter lgrseed)

	implicit none

	integer, intent(in) :: iseed

	lgr_rnd_seed = iseed

	end subroutine lgr_random_set_seed

!*******************************************************************

	subroutine lgr_random_set_step(atime)

! sets the step key of the draws from the absolute time atime [s] of the
! time step (milliseconds, rounded) and starts the release stream of the
! step at 0; called once per time step by lagrange, outside any parallel
! region, before the release of particles

	implicit none

	double precision, intent(in) :: atime

	lgr_rnd_step = nint(atime*1000.d0,kind=8)
	lgr_rnd_nrel = 0

	end subroutine lgr_random_set_step

!*******************************************************************

	subroutine lgr_random_selftest(ndraw,nfail)

! self-test of the generator; writes one line per check to unit 6 and
! returns the number of failed checks in nfail
!
!  1. the nine test vectors of Threefry-4x32 in Random123's
!     tests/kat_vectors (13, 20 and 72 rounds): the output words exactly
!  2. the conversions at the extreme words 0 and 2**32-1: the double and
!     the single precision value lie strictly inside (0,1)
!  3. five frozen values of lgr_rand_u and lgr_rand_r (computed with an
!     independent Python implementation of Threefry-4x32-20 and of the
!     packing of the keys, see check_lgr_random.sh): exactly
!  4. statistics of ndraw draws (10**6 in check_lgr_random.sh) along each
!     key the model varies, with the seed 1 and the step key 1230768300000
!     unless varied:
!       ids    id = 1 ... ndraw, draw index of site hdiff, n = 0
!       steps  id 1, step key + 300000*j (steps of 300 s), j = 1 ... ndraw
!       draws  id 1, site vdiff, n = 0 ... ndraw-1
!       seeds  seed = 1 ... ndraw, id 1, site hdiff, n = 0
!     each for the double and for the single precision value: mean,
!     variance, lag-1 correlation of consecutive draws and the chi-square
!     of 100 equal bins, and the correlation of the x and y draws of the
!     random walk (site hdiff, n = 0 and 1) over the ids. Limits: five
!     standard deviations of the statistic for independent uniform
!     values, sqrt(1/(12 N)) for the mean, sqrt(1/(180 N)) for the
!     variance (1/12), 1/sqrt(N) for a correlation, sqrt(2*99) around
!     the mean 99 for the chi-square (99 degrees of freedom)

	implicit none

	integer, intent(in) :: ndraw
	integer, intent(out) :: nfail

	integer, parameter :: nkat = 9
	integer :: kat_nr(nkat)
	integer(kind=8) :: kat(12,nkat)
	integer(kind=8) :: x(0:3),w0,w1,kexp
	integer :: i,j,iaxis,iprec
	integer, parameter :: nfroz = 5
	integer :: fseed(nfroz),fid(nfroz),fdraw(nfroz)
	integer(kind=8) :: fstep(nfroz),fku(nfroz)
	integer :: fkr(nfroz)
	double precision :: u,ue
	real :: r,re
	double precision, allocatable :: v(:),vy(:)
	double precision :: dn,dlim_m,dlim_v,dlim_c,dlim_x
	double precision :: amean,avar,acor,achi,xcor
	integer :: ierr
	logical :: bok
	character(len=6) :: aname(4)
	character(len=6) :: aprec(2)
	integer(kind=8), parameter :: step0 = 1230768300000_8

	! Random123 tests/kat_vectors, threefry4x32: counter(4) key(4) out(4)
	kat_nr = (/ 13,13,13, 20,20,20, 72,72,72 /)
	kat(:,1) = (/ int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'531c7e4f',8),int(z'39491ee5',8),int(z'2c855a92',8),int(z'3d6abf9a',8) /)
	kat(:,2) = (/ int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'c4189358',8),int(z'1c9cc83a',8),int(z'd5881c67',8),int(z'6a0a89e0',8) /)
	kat(:,3) = (/ int(z'243f6a88',8),int(z'85a308d3',8),int(z'13198a2e',8),int(z'03707344',8) &
     &		,int(z'a4093822',8),int(z'299f31d0',8),int(z'082efa98',8),int(z'ec4e6c89',8) &
     &		,int(z'4aa71d8f',8),int(z'734738c2',8),int(z'431fc6a8',8),int(z'ae6debf1',8) /)
	kat(:,4) = (/ int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'9c6ca96a',8),int(z'e17eae66',8),int(z'fc10ecd4',8),int(z'5256a7d8',8) /)
	kat(:,5) = (/ int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'2a881696',8),int(z'57012287',8),int(z'f6c7446e',8),int(z'a16a6732',8) /)
	kat(:,6) = (/ int(z'243f6a88',8),int(z'85a308d3',8),int(z'13198a2e',8),int(z'03707344',8) &
     &		,int(z'a4093822',8),int(z'299f31d0',8),int(z'082efa98',8),int(z'ec4e6c89',8) &
     &		,int(z'59cd1dbb',8),int(z'b8879579',8),int(z'86b5d00c',8),int(z'ac8b6d84',8) /)
	kat(:,7) = (/ int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'00000000',8),int(z'00000000',8),int(z'00000000',8),int(z'00000000',8) &
     &		,int(z'93171da6',8),int(z'9220326d',8),int(z'b392b7b1',8),int(z'ff58a002',8) /)
	kat(:,8) = (/ int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8),int(z'ffffffff',8) &
     &		,int(z'60743f3d',8),int(z'9961e684',8),int(z'aab21c34',8),int(z'8c65fb7d',8) /)
	kat(:,9) = (/ int(z'243f6a88',8),int(z'85a308d3',8),int(z'13198a2e',8),int(z'03707344',8) &
     &		,int(z'a4093822',8),int(z'299f31d0',8),int(z'082efa98',8),int(z'ec4e6c89',8) &
     &		,int(z'09930adf',8),int(z'7f27bd55',8),int(z'9ed68ce1',8),int(z'97f803f6',8) /)

	! frozen values: keys, k of the double (2k+1)/2**53, k of the single
	! precision value (2k+1)/2**24
	fseed = (/ 1, 1, -7, -2147483647, 20261122 /)
	fid   = (/ 1, 145, 2147483647, 0, 77 /)
	fstep = (/ 0_8, 1230768300000_8, -5_8, 9223372036854775807_8, 86400000_8 /)
	fdraw = (/ 0, 16777217, 201326591, 2147483647, 33554435 /)
	fku   = (/ 3310991834185722_8, 3106466644174647_8, 3639256216283686_8 &
     &		, 3324860012906451_8, 2772253900661015_8 /)
	fkr   = (/ 6167202, 5786245, 6778642, 6193034, 5163725 /)

	nfail = 0

	!---------------------------------------------------------
	! 1. test vectors
	!---------------------------------------------------------

	do i=1,nkat
	  call lgr_threefry4x32(kat_nr(i),kat(1:4,i),kat(5:8,i),x)
	  bok = all( x(0:3) == kat(9:12,i) )
	  if( .not. bok ) nfail = nfail + 1
	  write(6,'(a,i2,a,i3,a,4(1x,z8.8),a)') ' lgr random: test vector ',i	&
     &		,' (',kat_nr(i),' rounds):',x(0:3),trim(okfail(bok))
	end do

	!---------------------------------------------------------
	! 2. extreme words
	!---------------------------------------------------------

	u = lgr_rnd_bits_u(0_8,0_8)
	ue = lgr_rnd_bits_u(mask32,mask32)
	r = lgr_rnd_bits_r(0_8)
	re = lgr_rnd_bits_r(mask32)
	bok = u > 0.d0 .and. ue < 1.d0 .and. r > 0. .and. re < 1.
	bok = bok .and. u == 2.d0**(-53) .and. ue == 1.d0-2.d0**(-53)
	bok = bok .and. r == 2.**(-24) .and. re == 1.-2.**(-24)
	if( .not. bok ) nfail = nfail + 1
	write(6,'(a,2es24.16,2es16.8,a)') ' lgr random: extremes',u,ue,r,re	&
     &		,trim(okfail(bok))

	!---------------------------------------------------------
	! 3. frozen values
	!---------------------------------------------------------

	do i=1,nfroz
	  u = lgr_rand_u(fseed(i),fid(i),fstep(i),fdraw(i))
	  r = lgr_rand_r(fseed(i),fid(i),fstep(i),fdraw(i))
	  call lgr_rnd_words(fseed(i),fid(i),fstep(i),fdraw(i),w0,w1)
	  kexp = fku(i)
	  bok = u == dble(2*kexp+1)*2.d0**(-53)
	  bok = bok .and. r == real(dble(2*fkr(i)+1)*2.d0**(-24))
	  if( .not. bok ) nfail = nfail + 1
	  write(6,'(a,i2,a,es24.16,es16.8,a)') ' lgr random: frozen value ',i	&
     &		,':',u,r,trim(okfail(bok))
	end do

	!---------------------------------------------------------
	! 4. statistics
	!---------------------------------------------------------

	if( ndraw < 1000 ) then
	  write(6,*) 'lgr random: statistics need at least 1000 draws'
	  nfail = nfail + 1
	  return
	end if

	allocate(v(ndraw),vy(ndraw),stat=ierr)
	if( ierr /= 0 ) then
	  write(6,*) 'lgr random: allocation of the statistics failed'
	  nfail = nfail + 1
	  return
	end if

	dn = dble(ndraw)
	dlim_m = 5.d0*sqrt(1.d0/(12.d0*dn))
	dlim_v = 5.d0*sqrt(1.d0/(180.d0*dn))
	dlim_c = 5.d0/sqrt(dn)
	dlim_x = 5.d0*sqrt(2.d0*99.d0)
	write(6,'(a,i0,a,es10.3,a,es10.3,a,es10.3,a,f6.2,a,f6.2)')		&
     &		' lgr random: statistics of ',ndraw,' draws, limits |mean-1/2| <'&
     &		,dlim_m,', |var-1/12| <',dlim_v,', |corr| <',dlim_c		&
     &		,', chi-square ',99.d0-dlim_x,' ...',99.d0+dlim_x

	aname = (/ 'ids   ','steps ','draws ','seeds ' /)
	aprec = (/ 'double','single' /)

	do iaxis=1,4
	  do iprec=1,2
	    do j=1,ndraw
	      select case( iaxis )
	      case( 1 )
	        call lgr_rnd_words(1,j,step0,lgr_rnd_index(lgr_rnd_hdiff,0),w0,w1)
	      case( 2 )
	        call lgr_rnd_words(1,1,step0+300000_8*j			&
     &				,lgr_rnd_index(lgr_rnd_hdiff,0),w0,w1)
	      case( 3 )
	        call lgr_rnd_words(1,1,step0,lgr_rnd_index(lgr_rnd_vdiff,j-1)	&
     &				,w0,w1)
	      case default
	        call lgr_rnd_words(j,1,step0,lgr_rnd_index(lgr_rnd_hdiff,0),w0,w1)
	      end select
	      if( iprec == 1 ) then
	        v(j) = lgr_rnd_bits_u(w0,w1)
	      else
	        v(j) = lgr_rnd_bits_r(w0)
	      end if
	    end do
	    call stats(ndraw,v,amean,avar,acor,achi)
	    bok = abs(amean-0.5d0) < dlim_m .and. abs(avar-1.d0/12.d0) < dlim_v
	    bok = bok .and. abs(acor) < dlim_c .and. abs(achi-99.d0) < dlim_x
	    bok = bok .and. minval(v) > 0.d0 .and. maxval(v) < 1.d0
	    if( .not. bok ) nfail = nfail + 1
	    write(6,'(a,a6,1x,a6,a,f9.6,a,f9.6,a,f9.6,a,f8.2,a)')		&
     &		' lgr random: ',aname(iaxis),aprec(iprec),': mean',amean	&
     &		,' var',avar,' lag-1 corr',acor,' chi-square',achi,trim(okfail(bok))
	  end do
	end do

	! the x and y draws of the random walk over the ids
	do j=1,ndraw
	  v(j) = lgr_rand_r(1,j,step0,lgr_rnd_index(lgr_rnd_hdiff,0))
	  vy(j) = lgr_rand_r(1,j,step0,lgr_rnd_index(lgr_rnd_hdiff,1))
	end do
	xcor = correlation(ndraw,v,vy)
	bok = abs(xcor) < dlim_c
	if( .not. bok ) nfail = nfail + 1
	write(6,'(a,f9.6,a)') ' lgr random: x against y of the random walk:'	&
     &		//' corr',xcor,trim(okfail(bok))

	deallocate(v,vy)

	contains

	  function okfail(bb)
	  logical, intent(in) :: bb
	  character(len=7) :: okfail
	  if( bb ) then
	    okfail = '  ok'
	  else
	    okfail = '  FAIL'
	  end if
	  end function okfail

	  subroutine stats(n,a,am,av,ac,ax)
	  integer, intent(in) :: n
	  double precision, intent(in) :: a(n)
	  double precision, intent(out) :: am,av,ac,ax
	  integer :: k,ib
	  integer :: ic(0:99)
	  double precision :: s2,s1,e
	  am = sum(a)/n
	  s2 = sum((a-am)**2)
	  av = s2/n
	  s1 = 0.d0
	  do k=1,n-1
	    s1 = s1 + (a(k)-am)*(a(k+1)-am)
	  end do
	  if( s2 > 0.d0 ) then
	    ac = s1/s2
	  else			!all values equal: taken as fully correlated
	    ac = 1.d0
	  end if
	  ic = 0
	  do k=1,n
	    ib = min(99,int(a(k)*100.d0))
	    ic(ib) = ic(ib) + 1
	  end do
	  e = dble(n)/100.d0
	  ax = sum((dble(ic)-e)**2)/e
	  end subroutine stats

	  function correlation(n,a,b)
	  integer, intent(in) :: n
	  double precision, intent(in) :: a(n),b(n)
	  double precision :: correlation
	  double precision :: ma,mb,d
	  ma = sum(a)/n
	  mb = sum(b)/n
	  d = sqrt(sum((a-ma)**2)*sum((b-mb)**2))
	  if( d > 0.d0 ) then
	    correlation = sum((a-ma)*(b-mb)) / d
	  else			!a constant series: taken as fully correlated
	    correlation = 1.d0
	  end if
	  end function correlation

	end subroutine lgr_random_selftest

!*******************************************************************

	end module mod_lagrange_random

!*******************************************************************
