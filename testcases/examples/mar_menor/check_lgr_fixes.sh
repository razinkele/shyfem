#!/bin/bash
#------------------------------------------------------------------------
# Checks of the fixes of the Lagrangian module that followed #217 (the
# module on several MPI processes).  Each mode runs the model in a scratch
# copy of this folder (made with mktemp under ${TMPDIR:-/tmp}, removed at
# the end when the mode passes, kept with its path printed when it fails)
# with the shyfem first on PATH, and prints "<MODE>: PASS" or "FAIL".
#
# Usage:  ./check_lgr_fixes.sh MODE
#
#   stk-omp   (#243) the Stokes drift case mm_lgr_e with 4 OpenMP threads
#             (nomp = 4 in $para) and with 1 (nomp = 1), serially and on 4
#             MPI processes: the four runs must end, the 4-thread logs must
#             have the line "used OMP threads: 4" (the build compiles the
#             OpenMP directives: -fopenmp is always in FFLAGS), and the
#             particle file of 4 threads must be byte-identical (cmp) to
#             that of 1 thread, serially and on 4 processes.  This check
#             cannot fail on the data race it guards against (lag_stk set
#             a saved flag on its first call inside the parallel loop):
#             every thread wrote the same value, so no run shows it; it
#             shows that the change of the initialisation (once, before the
#             loop) leaves the result of 1 and 4 threads unchanged.
#   nbdymax   (#269) a release larger than nbdymax stops the run with exit
#             code 33 and a message naming nbdymax and the particles needed,
#             not with the exit code 0 of a bare stop: mm_lgr_a (150
#             particles) with nbdymax = 100, serially and on 4 processes
#             (there lgr_mpi_assign_ids decides on the global count); and
#             a particle file of 150 particles read by lgrini with
#             nbdymax = 100 (lgr_input_shell, serial only).
#   decay     (#226) mm_lgr_a serially, once as it is and once with
#             "ldecay = 86400." in $lagrg (decay of particles with an
#             e-folding time of one day, #246: of the 145 particles 2 are
#             left after the four days of the run; before #246 all of them
#             had decayed within five hours): the decay run must end (before #226 it stopped
#             with SIGSEGV at the first output after a decay: the exited
#             record read the coordinates of element 0).  Then
#             lgr_compare.py's reader checks the two particle files: the
#             decayed particles (exited in the decay run, not exited in the
#             plain run at the same output) are at least one; every exited
#             record of the decay run has an element in 1..nel and a
#             position inside a triangle of GRID/MM_geo.grd (inside the
#             basin), and a decayed particle stays in the exited block of
#             every later output with the same element and position (its
#             last position); every
#             active particle of the decay run has the same record as in
#             the plain run (decay changes no other particle).
#   decay-rate (#246) the survival of decay is exp(-t/ldecay) whatever the
#             time step: mm_lgr_a for six hours with about 5000 particles
#             (nbdy = 5000, nbdymax = 20000) and "ldecay = 21600." (six
#             hours), serially, once with idt = 300 s and once with idt =
#             60 s.  The release must hold at least 4000 particles.  At
#             every output (hourly, t = ldecay/2 and t = ldecay among them)
#             the number of active particles n of each run must be within 4
#             standard deviations of its expectation E = sum of
#             exp(-age/ldecay) over the released particles (age = output
#             time - release time of the particle, the time of its record
#             in the inserted block; variance sum of p (1 - p)); and the two
#             runs must agree: the difference of their survival fractions,
#             each less its expected fraction E/N (which takes the release
#             time, one time step before the first call, into account), must
#             be within 4 standard deviations of that difference, taken as
#             for independent runs.  The two runs are not fully independent:
#             the step key of a draw is the absolute time of the step, so at
#             the times both runs have a step (every 300 s) a particle draws
#             the same number in both (tested against 1 - exp(-300/ldecay)
#             and 1 - exp(-60/ldecay)); this correlation makes the true
#             spread of the difference smaller than the bound assumes, so
#             the comparison is looser than 4 standard deviations.  mm_lgr_a
#             has no open boundary, so a particle leaves the active block
#             only by decaying.  The seed is fixed, so the numbers are the
#             same in every run (with the seeds 2 to 7, idt = 300 s, the
#             count after six hours was within 1.5 standard deviations of
#             its expectation, of either sign).  Before #246 every step
#             tested the survival of the whole age, exp(-age/ldecay), with a
#             new draw (survival about exp(-t**2/(2 ldecay dt))): with idt =
#             300 s 1469 of the 4952 particles were active after one hour
#             (4134 expected) and none after three hours (2962 expected),
#             with idt = 60 s 33 after one hour (4180 expected).
#             Part 2, restart: mm_lgr (random walk rwhpar = 0.5) with
#             "ldecay = 3600." for six hours, particle output every 300 s,
#             serially: the run that went on, the same run to 01:00 with a
#             restart file (idtrst = -1), and a run from 01:00 with that
#             restart file and its particle file (lgrini, itlgin = 01:00,
#             nbdy = 0).  At least one particle must decay in the first step
#             after the restart in the run that went on, and at every output
#             of the restarted run the active particles must be those of the
#             run that went on, each record equal (the exited block is not
#             compared: lgrini reads only the active particles).  The
#             particle file resets a particle's age (init%time is the
#             restart time), but the restarted run's first call of lagrange
#             is at the restart time itself (age 0: no draw, and the record
#             already holds that step's decay), and from the next step on
#             every particle draws over a full step with the keys of the
#             run that went on (measured: 56 active at 01:00, 51 at 01:05,
#             the same 51 in the restarted run, 60 outputs equal).
#   outside   (#247) a release point that lies in no element releases
#             nothing: mm_lgr_a (2D) and mm_lgr_c (3D, with ipvert = -3:
#             three random depths per particle) for six hours, serially,
#             with no area release (idtl = -1) and a trajectory release
#             (lgrtrj, nbdy = 5 particles per point): at 01:00 a point east
#             of the basin, outside the mesh, at 02:00 the centroid of
#             element 1000.  Each run must end; its log must have the line
#             "particles not released, point outside the mesh: N at time:
#             2009-01-01::01:00:00" (N = 5, in 3D 15), and "new particles
#             released: 0" at 01:00 and N at 02:00; in its particle file no
#             output before 02:00 holds a particle, every output from 02:00
#             holds exactly the ids 1 ... N (the skipped particles took no
#             id), the release element of each is 1000, and every record of
#             every block has an element in 1..nel and a layer in 1..nlv.
#             Before #247 the point outside gave particles with element 0,
#             and both runs stopped at the first output after 01:00 in
#             xi_abc (xi2xy of element 0, the exited block of lgr_output):
#             mm_lgr_a with SIGSEGV, mm_lgr_c with SIGFPE.
#   segments  (#252) find_elems_to_segment (src/utils/shyutil/lnku.f90),
#             the elements on the two sides of a segment k1-k2, used by the
#             continuous release along a boundary (lgrpps: create_parts,
#             get_bflux_ppv) and by shyplot's vertical sections.  1. its
#             self-test at levdbg = 3 (lgr_selftest_segments, called by
#             lgr_mpi_init: check_elems_to_segment compares its result for
#             every side of every element, in both directions, with the
#             elements of the two nodes found from nen3v alone, not from the
#             lists it reads): mm_lgr_a for one hour, serially and on 4
#             processes, every rank must write "lgr self-test
#             find_elems_to_segment: rank R segments S wrong 0" once, and
#             the serial run must check S = 6 x nel segments.  2. mm_lgr_a
#             for six hours with no area release (idtl = -1) and a
#             continuous release (lgrpps = 0.01) along the open boundary
#             nodes 85 ... 99 of mm_hyd_12a, serially: the run must end,
#             release at least 100 particles, and each particle's release
#             record (inserted block) must lie on one of those boundary
#             segments (within 2e-5 degrees, the single precision of the
#             positions) and name as its element the element of that
#             segment (the one element that has both nodes, found by a
#             search of GRID/MM_geo.grd).  Only the part 85 ... 99 of the
#             boundary list of mm_hyd_12a is used: the list skips the
#             boundary nodes 13 (between 99 and 100) and 14 (between 162 and
#             163), so its segments 99-100 and 162-163 are sides inside the
#             mesh: create_parts stopped there with "error stop
#             create_parts: error in boundary" before and after #252, until
#             #254, which skips them with a warning (mode bnd-release
#             releases along the whole list).
#             Before #252 find_elems_to_segment read the element list of k2
#             with the position of k2 in the list of k1: the self-test (with
#             the three reads of the fix put back) gave 15266 wrong of 15270
#             segments, and the binary of the commit before released 77 of
#             219 particles in an element that does not hold their segment.
#   ilagr3    (#231) the 3D case mm_hyd_41 without its tilt lines (ktilt,
#             ztilt), for one day, with a $lagrg section that sets ilagr = 3
#             (vertical advection and diffusion), nbdymax = 20000, nbdy =
#             300, idtl = 0, idtlgr = '1h', rwhpar = 0, ipvert = -1 (the
#             reproducer of #231), serially: the run must end (before #231 it
#             stopped with SIGFPE in its first particle step, in intp_neville
#             called by diff_get_vert for a particle in an element with one
#             layer, and with only that corrected, in diff_get_vert at the
#             square root of a negative diffusivity extrapolated in the
#             bottom layer of an element with two layers); its log line "lgr
#             vertical diffusion: negative diffusivities set to 0: N" must
#             have N = 0 (with the bottom interface in the interpolation no
#             diffusivity is negative; a fix that only set the negative
#             values to 0 gave about 1.07 million in one day); and its
#             particle file must hold only finite values,
#             active particles with an element in 1..nel, a layer in 1..nlv
#             and a depth z in the layer within 0..1 (the line of the random
#             walk time step of the run, #257, is printed for information:
#             with the walk of #286 min 0.2 s (the floor of its gradient
#             term), mean 14.1 s, 168.7 sub-steps per 300 s step and 726266
#             of 735505 element steps below the model step; with the
#             curvature rule alone, min 2 s, mean 33.5 s, 41.7 sub-steps;
#             before #257 mean 24.9 s, 98.4 sub-steps).  The cap of the
#             calls of lgr_diff_vert in a particle step (#261, #286): the
#             log must hold no line "warning particle dif" (written from
#             inside the OpenMP particle loop for every step that reached
#             the cap until #261), and each of the two lines of the
#             particle steps once, "lgr vertical diffusion: particle steps:
#             ..., most calls in a step: M, ..." with 100 < M <= 1501 and
#             "... steps stopped at the cap of 10000 calls: N, ...; steps
#             ended by 2 calls in a row that used no time: E, ..." with N =
#             0 and E = 0.  The walk of #286 (lgr_diff_vert) makes ceiling(
#             T/dtvd) calls in a step of T s, one displacement each and none
#             ended at an interface, so the calls are not capped by the
#             layers any more: measured 119714348 calls in 772898 particle
#             steps, 154.9 per step (the reproducer of #286 gave 154.8),
#             most 1501 in a step, N = 0 at T = 300 s and E = 0.  The bound
#             1501 is ceiling(300/0.2) = 1500 for the floor of the gradient
#             term, 0.2 s, plus one call for the single-precision rounding of
#             the time left; M must exceed 100, the cap before #261.  The
#             walk before #286 ended a call at each layer interface: M
#             10000 (the cap), N = 1 of 777212 particle steps, 142 s not
#             diffused.  Before #261 the log has 59859 lines "warning
#             particle dif" and neither line; with the cap put back to 100
#             (lgr_nvdiff_max) and the old walk M = 100 and N = 59618; with
#             the cap at 100 and the walk of #286 (a throwaway build, same
#             case) the run ends, with no line "warning particle dif" or
#             any other line from the loop: M = 100, N = 154604 of 769401
#             particle steps, 26.7 million s not diffused, E = 0.  A second
#             run, 12 hours with the end of the
#             particle run itlend = 06:02:30 (between two time steps), must
#             write the line of the negative diffusivities and the two lines
#             of the particle steps exactly once each.
#   vdiff-events (#288) nothing is written from inside the OpenMP particle
#             loop for a vertical walk of diff_body that ended with time
#             left: the particle out of the domain ("loosing particle dif"
#             until #288) or the cause unknown ("unknown error dif"), one
#             line per particle step written by the worker threads until
#             #288.  No run reaches these branches (the walk of #286 makes
#             one displacement per call and no call ends where the particle
#             reaches a layer interface, the surface or the bed, so the walk
#             ends only with no time left, at the cap or by two calls in a
#             row that used no time, and lgr_diff_vert never sets lb < 1), so
#             the mode uses the test hook LGR_TEST_VDIFF_END=10 (read once
#             at start-up, lgr_mpi_init): the walk of a particle whose id is
#             a multiple of 10 ends at once, in every step, with its whole
#             time left; one whose id is also a multiple of 20 leaves the
#             domain there.  Case: mm_hyd_41 in still water (as in
#             check_lgr_wellmixed.sh: no tilt, wind, heat flux or rain,
#             boundaries closed, iturb = 0, diftur = 1.e-2) for two hours,
#             ilagr = 3, nbdy = 300 released at the start (idtl = 0), rwhpar
#             = 0 (no particle moves horizontally), ipvert = -1, output every
#             hour, nomp = -1 in $para, serially, once with OMP_NUM_THREADS
#             = 1 and once with 4.  Each run must end, report its threads
#             ("used OMP threads: N") and acknowledge the hook.  From its
#             particle file the check takes the released ids R and expects
#             L = the ids of R that are multiples of 20 (lost in the first
#             step) and U = the odd multiples of 10 (walk ended in every
#             step); from the .inf file the particle steps P (the lines
#             "lagrange_nbdy:" with particles).  The log must hold no line
#             "loosing particle dif" or "unknown error dif"; one line "lgr
#             vertical diffusion: lost with time left: |L| in the step to
#             ..., |L| in the run ...; first: id min(L), ..." and P lines
#             "lgr vertical diffusion: walk ended with time left, cause
#             unknown: |U| in the step to ..., k|U| in the run ...; first: id
#             min(U), ..." (k = 1 ... P); the particle file must end with
#             exactly L exited and every other id of R active.  The two
#             runs must write the same summary lines and byte-identical
#             particle files (cmp).  With the hook alone (the code before
#             #288) the runs write |L| lines "loosing particle dif" and P|U|
#             lines "unknown error dif" from inside the loop, and no
#             summary line.
#   adv-events (#294) nothing is written from inside the OpenMP particle
#             loop for an advection that ended with time left or for a flux
#             over a wall side: until #294 track_body_xi wrote a line
#             "loosing particle adv" (and "warning particle adv", "unknown
#             error adv") for each such particle step and track_xi_get_flux
#             a line "material boundary:" for each such call, from the
#             worker threads; now they are counted and written once per
#             pass, "lgr advection: lost with time left: N in the step to
#             TIME, M in the run (P events per 100 of the I particles
#             released); first: id, element, crossings left, time left [s]"
#             and "lgr advection: flux over a wall side set to 0: N ...;
#             first: id, element, layer, side, flux" (the part in the run
#             read "P % of the I particles released" until #305; the line
#             must have the new form).  Case
#             mm_lgr_b as it is (two days, ilagr = 1, about 1000 particles
#             released at the start, rwhpar = 0, an open boundary: a
#             particle leaves the domain only by advection, at the open
#             boundary), with nomp = -1 in $para: serially with
#             OMP_NUM_THREADS = 1 and with 4, and with nomp = 2 on 4 MPI
#             processes.  Each run must end and report its threads.  No
#             log may hold one of the six old per-particle lines (also "vel
#             < 0" and "warning: wrong layer").  In each run every kind of
#             summary line ("lgr advection: ...") has at most one line per
#             pass (per process on several processes, each with its rank),
#             and its "in the run" count is the sum of its counts so far.
#             Serially the particle file is the oracle of the lost
#             particles: at each output the lost particles counted in the
#             steps up to its time ("in the run") are exactly the exited
#             particles of that output (only advection takes a particle out
#             here), the first id of a step is one of the particles that
#             exited by the next output and not by the one before, its
#             element is negative and it had time and crossings left; the
#             flux lines must exist.  The runs on 1 and 4 threads must write
#             the same summary lines and byte-identical particle files
#             (cmp); on 4 processes the counts of each kind and step summed
#             over the ranks must equal the serial ones.  Before #294 the
#             serial run writes 595 lines "loosing particle adv" and 121
#             "material boundary:", and no summary line; with #294 the
#             summary lines count 595 lost particles and 121 fluxes in the
#             run.
#   vdiff-dt  (#257) the time step of the vertical random walk follows the
#             curvature of the diffusivity.  Visser (1997) requires the
#             step to be much smaller than min 1/|K''| over the water
#             column; lag_vdiff_ele takes 1/100 of that, dtvd = 1/(100
#             max|K''|) (at least 2 s), with K'' the second derivative of
#             the diffusivity K over the layer interfaces of the element
#             (lgr_vdiff_curvature).  1. lgr_vdiff_curvature, cut out of
#             src/shyfem/lagrange_dif.f90 and compiled on its own with a
#             small test program (gfortran, -ffpe-trap=zero,invalid,
#             overflow): on six unequal layers (1, 2, 4, 0.5, 3, 1.5 m) a
#             quadratic K must give K'' = 2c at every interface (within
#             1e-3 relative; the bottom one extrapolated), a linear K 0
#             (within 1e-7) and a constant K exactly 0; two layers give the
#             value of interface 1 at the bottom too; a layer of zero
#             thickness must set bzero (then lag_vdiff_ele takes the
#             smallest step) without a division by zero.  A second
#             difference with one spacing, (K(l+1) - 2 K(l) + K(l-1))/hl(l)
#             **2 (the sign fixed, the spacing not), fails the quadratic and
#             the linear profile on unequal layers, and so does the formula
#             before #257.  Likewise lgr_vdiff_gradstep (#286), the gradient
#             term dt <= 0.07 Kmin/K'**2 per layer (K' = slope of K in the
#             layer): linear K 17.5 s, constant K untouched, a K jump in one
#             layer, a layer of zero thickness skipped, one layer 280 s.
#             2. The 3D case mm_hyd_41
#             as in mode ilagr3 (no tilt, one day, ilagr = 3, nbdy = 300,
#             rwhpar = 0, ipvert = -1) with iturb = 0 and diftur = 1.e-3
#             (and vistur = 1.e-3), serially: without turbulence closure
#             the diffusivity is diftur at every interface for the whole
#             run, so the walk's K (diftur + 1e-6/3, lag_vdiff_ele) is the
#             same everywhere, K'' = 0, and the random walk must take the
#             model time step: the log line "lgr vertical diffusion:
#             random walk time step [s] min 300.000 mean 300.000, ...
#             below the model step 0" (written once at the end,
#             lgr_vdiff_stats; until #261 the line went on with "over 100
#             sub-steps 0", which the check accepts).  Before #248 the run had
#             diftur only in the particle step made at set-up: then
#             handle_gotm_init, called whatever iturb, replaced it by
#             GOTM's initial 1e-6, so the mode tested a constant K of
#             1e-6 + 1e-6/3 instead of 1e-3 + 1e-6/3.  Before #257 the
#             "second derivative" was (K(l+1) + 2 K(l) + K(l-1))/hl(l)**2,
#             about 4 K/h**2, so the step was h**2/(400 K) also for a
#             constant K: with the old formula put back into the fixed code
#             (whose statistics line it keeps) the run gives min 2 s, mean
#             16.6 s, 119.8 sub-steps per step and 700536 of 735505 element
#             steps below the model step, all of them over 100 sub-steps
#             (measured 2026-11-24 with #248; before #248, with K = 1e-6 +
#             1e-6/3: min 2 s and 2424 element steps below the model step,
#             all over 100 sub-steps, elements with a very thin layer,
#             where h**2/(400 K) is that small).  The code before #257 has
#             neither the routine nor the line, so this mode cannot be red
#             on it; its red evidence is the old formula put back.
#   walk-fold (#286, #287) the reflection and the layer search of the
#             vertical random walk of ilagr = 3 (lgr_diff_vert: one
#             displacement per call, across the layer interfaces, reflected
#             at the surface and at the bed).  lgr_walk_locate (the layer
#             lb and the relative depth z of a depth d in 0 ... H) and
#             lgr_walk_fold (d of any value folded into 0 ... H, H the
#             column depth, modulo 2 H, then located), cut out of
#             src/shyfem/lagrange_dif.f90 and compiled together on their
#             own with a small test program (gfortran, -ffpe-trap=zero,
#             invalid,overflow).  Layers (1, 2, 0, 3) m (the interfaces 0,
#             1, 3, 3, 6, H = 6): d = 2.5 gives lb = 2, z = 0.75; d = -0.5
#             (above the surface) the depth 0.5, lb = 1, z = 0.5; d = 6.5
#             (below the bed) 5.5, lb = 4, z = 2.5/3; d = 13 (13 mod 12) 1,
#             lb = 1, z = 1; d = 3 (the interface above the layer of zero
#             thickness) lb = 2, z = 1, never lb = 3; d = 0 lb = 1, z = 0;
#             d = 6 lb = 4, z = 1; every layer of zero thickness (H = 0) lb
#             = lmax, z = 0.5 with no division; layers (1, 2, 3, 0), a
#             bottom layer of zero thickness: lgr_walk_locate at d = 6
#             gives lb = 3, z = 1, so the diffusivity interpolated there,
#             K(lb-1) + z (K(lb) - K(lb-1)) as in lgr_diff_vert, is K(3),
#             with no division by the zero thickness (where the
#             interpolation of the walk before, exxpp, divides 0/0).  And
#             for 2001 depths from -3 H to 3 H on layers (1, 2, 0, 3): a
#             layer of non-zero thickness, z in 0 ... 1, and the depth of
#             (lb, z) equal to the folded d.  These layers and interfaces
#             are exact in single precision, so z never leaves 0 ... 1
#             there even without the clamp of lgr_walk_locate; diff_body
#             builds the interfaces as a single-precision running sum, where
#             hle(l) - hle(l-1) can exceed hl(l).  So the interfaces of
#             layers (0.1, 0.2, 0.3, 0.4) and of 0.1 + 0.01 l (l = 1 ...
#             50) are built that way and each is located: lb = l and z in 0
#             ... 1 at every one (without the clamp z exceeds 1 by a
#             rounding at 1 and 22 of them, 1 + 3.7e-8 and 1 + 8.0e-7; a
#             real z of 1.000001 makes track_xi stop the run); the program
#             also requires that the unclamped value exceeds 1 at one
#             interface at least, or the case no longer tests the clamp.
#             Before #286 neither routine exists (the walk stopped at
#             every interface).
#   bed-w     (#299) the vertical velocity of an ilagr = 3 particle in the
#             bottom layer of a column of more than one layer (track_xi):
#             the flow's w is linear in the relative depth z of the layer,
#             from wt (the element mean of the interface velocity at the
#             layer top) to 0 at the bed, and the settling velocity sv is
#             not tapered: w(z) = wt (1 - z) - sv (w > 0 upward, z = 0 at
#             the layer top, 1 at the bed).  lgr_bed_move (the relative
#             depth after a time t) and lgr_bed_exit (the time to reach the
#             layer top or the bed, huge(1.d0) if neither is ever reached),
#             cut out of src/shyfem/lagrange_vertical.f90 and compiled
#             together on their own with a small test program (gfortran,
#             -fcheck=bounds, -ffpe-trap=zero,invalid,overflow), against an
#             RK4 integration of du/dt = (wt u - sv)/hd (u = 1 - z, 10**5
#             steps) to 1e-7 absolute, hd = 2 m: sv = 0, wt = -1e-4, z0 =
#             0.3 after 3600 s (the measured tapered case: the bed is never
#             reached); wt = 0, sv = 1e-3 (linear: the bed at hd (1 - z0)/sv
#             exactly); wt = 2e-4, sv = 1e-4 (equilibrium at u = 0.5: from
#             z0 = 0.6 the bed, from z0 = 0.4 the top); wt = -2e-4, sv =
#             1e-4 (the bed from any z0: 0, 0.3, 0.9); wt = 1e-18, sv = 3e-5
#             (a round-off wt: the linear answer); a rising particle (sv <
#             0) that reaches the top and one that approaches a stable
#             equilibrium.  At each exit time the RK4 solution is at the top
#             or the bed (1e-7) and lgr_bed_move gives z = 0 or 1 (1e-9);
#             halfway the two agree (1e-7).  The edge returns: on the bed
#             with sv = 0, and at the equilibrium u = sv/wt, never (huge;
#             there lgr_bed_move keeps z exactly); on the bed with sv > 0
#             (wt 2e-4, 0, -2e-4) 0 and the bed; at the top moving up 0 and
#             the top.  A layer of zero thickness (hd = 0): no motion (z
#             kept exactly, huge), with no division.  Before #299 neither
#             routine exists (the bottom layer had the layer mean of w).
#   grow-fail (#242) on 4 MPI processes with 4 OpenMP threads each (nomp =
#             4), with LGR_TEST_SMALL_EXPORT=1 (the lists of marks and of
#             parked particles start with 2 entries, so they grow in the
#             first steps) and the hook LGR_TEST_GROW_FAIL (the first
#             enlargement of that list on every process takes the path of a
#             failed allocate): mm_lgr_a with =export (the list of marks at
#             sides; it parks nothing) and the Stokes drift case mm_lgr_e
#             with =park (its list of marks never passes 2 entries on 4
#             processes, its parkings do).  Each run has a
#             timeout of 300 s and must stop with exit code 33 (the code
#             shympi_abort_internal gives MPI_ABORT; Open MPI's mpirun
#             returns it), with the message "lgr_mpi_grow_export:
#             allocation" (or _park) and the line of the check made by the
#             main thread after the particle loop ("lgr_mpi_list_check:"),
#             with "used OMP threads: 4" in the log and no SIGSEGV, SIGFPE
#             or "Fortran runtime" line.  Before #242 the grow routine
#             called the abort itself, from whichever OpenMP thread held
#             the critical section (MPI is initialised
#             MPI_THREAD_FUNNELED): no such check line.
#   int-fail  (#256) the internal-error guards of the tracker reached
#             inside the OpenMP particle loop of drogue: mm_lgr_a on 4 MPI
#             processes with the hook LGR_TEST_INTERNAL_FAIL=1 (the first
#             particle that a thread other than 0 takes on each process
#             gets a negative travel time, so that the guard of
#             track_single, "error stop drogue: internal error", fires once
#             per process), with 4 OpenMP threads (nomp = 4) and with 1
#             (nomp = 1).  Each run has a timeout of 300 s and must stop
#             with exit code 33 and the guard's message, with no SIGSEGV,
#             SIGFPE or "Fortran runtime" line and no "simulation end".
#             The 4-thread run must report 4 threads, the hook must fire on
#             a thread other than 0 (line "lgr_mpi_test_internal: ...
#             OpenMP thread N") and the run must stop through the check
#             the main thread makes after the loop (line
#             "lgr_mpi_list_check: ... an internal error found in the
#             particle loop").  Before #256 the guard called the abort
#             itself, from the worker thread (MPI_THREAD_FUNNELED): no such
#             check line.  The 1-thread run must stop in the guard itself,
#             as before #256 (no check line: a loop on one thread runs on
#             the main thread).
#   events    (#305) every kind of event of the tracker (lgr_event, the 27
#             kinds of lgr_event_desc; 26, the node sink, since #310, and
#             27, the vertex hold, since #316, see mode node-sink-run) and
#             the three ways the run stops
#             after an internal error, which no normal run reaches, with
#             the test hook LGR_TEST_EVENT=K (read once at start-up,
#             lgr_mpi_init: the particle in slot 1 records an event of kind
#             K with fixed values in the first pass, the integer values 1,
#             2, ..., the real values 0.5, 1.5, ..., for kind 18 the text
#             LGR_TEST_EVENT, and for a kind that stops the run calls
#             lgr_internal_error, "error stop lgr_mpi_test_event: kind K";
#             for kind 23 the error 1 of xy2xi_ierr in diff_body is forced
#             instead, "error stop diff_body: error of xy2xi").  Case
#             mm_lgr_a for 30 minutes, for each K = 1 ... 27 with nomp = 1
#             and nomp = 4 serially and with nomp = 1 on 4 MPI processes
#             (timeout 120 s each).  Each run must acknowledge the hook and
#             write the line of kind K as lgr_event_desc documents it (the
#             expected head, text, names, the values with three decimals or
#             in full precision, written out in this script, not taken from
#             the code): for the kinds that do not stop the run (1, 2, 5 to
#             10, 26, 27) "1 in the step to T, 1 in the run (P % of the I
#             particles released)" for 1 and 2 (the lines of #288) and "(P
#             events per 100 of the I particles released)" for the others
#             (an event count, which can pass 100 per 100 particles; #305),
#             with T the time of the release, I the particles released and
#             P = 100/I; such a run must end, the line of 4 threads must be
#             the line of 1 thread, and on 4 processes every process with
#             particles writes it once, with its rank.  For the kinds that
#             stop the run (3, 4, 11 to 25) each run must stop with exit
#             code 33 and the message, with no "simulation end": on 1 thread
#             at once, with the line written before the message and no line
#             "lgr_mpi_list_check:"; on 4 threads through the check of the
#             main thread after the particle loop ("lgr_mpi_list_check: ...
#             an internal error found in the particle loop by OpenMP thread
#             N"); on 4 processes with the line naming the rank, and Open
#             MPI's line "MPI_ABORT was invoked on rank R" (required: the
#             build is Open MPI) with R among the ranks of the lines.  No
#             run may write a SIGSEGV, SIGFPE or
#             "Fortran runtime" line or an event line of another kind.
#             Then, on 1 thread, LGR_TEST_EVENT=8 with LGR_TEST_INTERNAL_FAIL
#             =1 (a non-stop event and, in the same pass, the guard "error
#             stop drogue: internal error", which has no event kind): the
#             line of kind 8 must be written before the stop (until #305
#             the abort at once of lgr_internal_error dropped the events of
#             the pass, written only for a kind that stops the run).  And
#             the source: no call of the routines of the old name xi2xy,
#             xy2xi, xi_dist, xit_start_end (a bare stop, exit code 0, on
#             an error) in the Fortran files under src (.f, .F, .f90, .F90;
#             src/tools excepted: the tools run on one process; until #305
#             the release, the particle output, the larvae, the debug dump
#             and the TVD set-up called them, all but the larvae also on
#             several processes; they now call the _ierr form and stop
#             through shympi_abort_internal, exit code 33; no run reaches
#             these errors), except exactly one known call inside the
#             OpenMP tasks of conz3d_omp: a debug line of tvd_get_upwind_c
#             under bdebug = .false. (since #317 the upwind value itself
#             calls femintp_xi_ierr, records an error and stops after the
#             OpenMP tasks, so femintp_xi has no call of the model left); it
#             must be found once, by file, routine and line.  The code before #305 does not know
#             the hook; the code before #310 has no kind 26 (LGR_TEST_EVENT
#             =26 is out of range there: no hook, no line), the code before
#             #316 no kind 27.
#   node-sink (#310) the classifier of a node sink, track_xi_node_sink (a
#             particle that used up its 100 element crossings with time left
#             converging onto a node of the mesh: the flux reconstruction of
#             a layer makes it spiral into an interior node where the layer
#             flow converges, the time to each side shrinking
#             geometrically), cut out of src/shyfem/lagrange_vertical.f90
#             and compiled on its own with a small test program (gfortran,
#             -fcheck=bounds, -ffpe-trap=zero,invalid,overflow).  With d the
#             sum of the two smallest internal coordinates (the distance
#             from the nearest vertex), at the start of the step and at the
#             end of the crossings, a sink is d_end < 1e-3 and d_end <=
#             d_start, or d_end < 1e-15.  The cases, the numbers of the
#             investigation of #310: a sink (3.5e-3 to 2.7e-14, the trace of
#             part 1 of check_lgr_bed.sh), a weak sink (4e-4 to 1.2e-6, about
#             x0.75 per turn: two coordinates below 1e-6, the rule of the
#             first prototype, misses it), a sink entered from far in the
#             step (0.6 to 1e-10), a sink reached exactly (5e-4 to 5e-4),
#             the floating-point floor (1e-16 to 5e-16), true; a source
#             (the restart point of the Venice particle of #310 and #315,
#             (0, 0.99999999999999289, 7.105e-15), to 2.9e-14 and to 2.5e-5),
#             above the floor (1e-16 to 2e-15), far from a vertex (d 0.5,
#             and 1.5e-3 although converging), near a side but not a vertex
#             (one coordinate 1e-12, d 0.4), false; each with the node at
#             each of the three vertices at the start and at the end (9
#             orders).  Before #310 the routine does not exist.
#   node-sink-run [REF_BIN_DIR] (#310) a node sink is its own event kind:
#             the closed forced mm_hyd_41 of check_lgr_bed.sh part 1 (no
#             tilt, one day, both ibtyp = 0) with ilagr = 1, rwhpar = 0 and
#             100 particles released at 16:30 in a 400 m square around the
#             interior node 702 (lgrlin, node702.txt written here), where
#             the layer-1 flow converges (the "nt1" case of the
#             investigation; 13 s serially): serially with 1 OpenMP thread
#             and with 4 (nomp = 4), and on 4 MPI processes.  Each run must
#             end and write no line "lgr advection: element crossings used
#             up with time left" and at least one line "lgr advection:
#             stopped at a node the layer flow converges on (node sink) with
#             time left: N in the step to T, M in the run (P events per 100
#             of the I particles released); first: id, element, layer L,
#             time left [s] S" with L >= 1 and S > 0, M the sum of the N so
#             far; the 4-thread run the same lines and a byte-identical
#             particle file (cmp) as 1 thread; on 4 processes the N of each
#             step summed over the ranks must be the serial N.  With
#             REF_BIN_DIR (a build of the code before the change, e.g.
#             origin/main) the same case runs serially and on 4 processes
#             with REF_BIN_DIR/shyfem: its lines "element crossings used up
#             with time left" (at least one) must be the node-sink lines of
#             this binary step by step (N, M, and the first id, element and
#             time left), on 4 processes per rank, and the particle
#             files, the .hydro.shy and the .inf files must be byte-identical
#             (cmp), serially and on 4 processes: the change is a log text
#             only.  Measured (2026-11-26): origin/main 9187cdf1 writes 32
#             lines "element crossings used up", 546 in the run (on 4
#             processes all on rank 3); with #310 32 node-sink lines, 546
#             in the run, and none of the other.  Without REF_BIN_DIR the
#             comparison is skipped (said in the PASS line).  The code
#             before #310 fails this mode on its lines "element crossings
#             used up".  Since #316 each run must also write lines "lgr
#             advection: all the time left spent moving off a vertex (vertex
#             hold): N in the step to T, M in the run (P events per 100 of
#             the I particles released); first: id, element, layer L, node
#             K, time spent [s] S" with L >= 1, K = 702 (the external number
#             of the node) and S > 0, M the sum of the N so far, and exactly
#             HOLD_EXPECT = 1599 events in the run: measured 2026-11-27, the
#             th = 0 path of track_xi moved a particle off a vertex and spent
#             all its time left 1599 times, in 80 passes, always at node
#             702, each pass as often as the investigation's counter of
#             these calls (#316; 1582 of them are steps that start and end
#             at the node, 17 the step that brings a particle onto it); the
#             4-thread lines must be the 1-thread lines, and on 4 processes
#             the N of each step summed over the ranks the serial N.
#             REF_BIN_DIR may also be a build with #310 (the live reference
#             build, for example): then its node-sink lines must be this
#             binary's, step by step, and the files compared byte-identical
#             (the vertex hold is a log line only); a build with #316 must
#             also write this binary's vertex-hold lines, step by step (N,
#             M, and the first id, element, layer, node and time spent), and
#             a build without #316 none.  The code before #316 fails this
#             mode: no vertex-hold line.
#   cross-budget (#315) a step that used up its base budget of crossings
#             (100) with time left and is not a node sink goes on with 1500
#             extra crossings, so a particle that circles a node outward
#             and that the re-snap of x, y puts back on the node every step
#             leaves it.  ../venice_lagoon/venlag_smoke.str (the 3D
#             Venice lagoon, basin venlag62 made here with shypre) until
#             03:32 with 50 surface particles (ilagr = 1, lgrseed = 1)
#             released at 03:00 in a 20 m square around node 392, where
#             particle 1356 of the full release was held: serially and on 4
#             processes.  The node is a sink for the particles from about
#             03:07 (kind 26) and then turns into a source; 8 of them sit
#             exactly on it.  Required (measured 2026-11-28): CB_CROSS = 24
#             events "element crossings used up with time left" in the run
#             (8 particles in each of the 3 steps to 03:26:01, 03:26:38 and
#             03:27:15, each line with crossings left 0 and time left > 0, no
#             line after 03:27:15), CB_SINK = 136 node-sink events and
#             CB_HOLD = 91 vertex-hold events (#316), both as before #315,
#             and no particle exactly on node 392 (the float32 of its
#             coordinates in venlag62.grd) at the last output (12720 s); on
#             4 processes the particle file byte-identical to the serial one
#             and the N of each step of the three kinds summed over the
#             ranks the serial N.  The code before #315 fails it: 101
#             events of the first kind (the 8 particles in every step from
#             03:26:01 on) and the 8 particles still on the node at 12720 s
#             (ids 9 10 17 20 25 30 47 53).  The numbers are exact: a change
#             of the flow or of the tracker needs them measured again.
#   small-export (#242) mm_lgr_a (its list of marks grows) and mm_lgr_e
#             (its list of parked particles grows) on 4 MPI processes with
#             LGR_TEST_SMALL_EXPORT=1 (both lists start with 2 entries and
#             grow inside the OpenMP particle loop), at levdbg = 2 (the
#             consistency check of every step is on): with 4 threads and
#             with 1 thread, and with 1 thread without the hook.  The three
#             runs must end, the consistency check must write nothing, the
#             4-thread log must report 4 threads, and the particle file of
#             4 threads must be byte-identical (cmp) to both 1-thread files.
#             A fourth run, 4 threads at levdbg = 3, prints a line per
#             growth with the OpenMP thread that made it: at least one
#             growth must be counted (its particle file is not compared).
#             This is not a red test of #242 (the growth itself was right
#             before); it checks that the growth inside the loop, which had
#             only run on one thread, gives the 1-thread result on 4.
#   seed      (#225) every random draw of a particle comes from its own
#             stream (seed lgrseed, particle id, time step, kind of draw),
#             so a run is repeatable on any number of threads and
#             processes.  Particle files compared byte for byte (cmp):
#             1. mm_lgr (random walk rwhpar = 0.5) serially: the plain run,
#                a run with "lgrseed = 1" (the default, set explicitly) and
#                a run with 4 OpenMP threads (nomp = 4; its log must report
#                4 threads) must be identical; a run with "lgrseed = 2"
#                must differ from the plain run (the seed reaches the
#                draws) and have the same ids and counts per block
#                (lgr_compare.py --mode ids --same-counts);
#             2. mm_lgr on 4 MPI processes with 4 threads and with 1
#                thread: identical;
#             3. the draws that run only serially: mm_lgr_c (3D, ilagr = 2)
#                with ipvert = -3 (random depth at release), rwhpar = 0.5,
#                lbeach = 0.5 (beaching), ldecay = 86400. (decay), ilarv =
#                1 (larvae), ised = 1 (sediment class and deposition) and a
#                point release at the river node 218 (lgrpps = 0.002: the
#                element at the node, the number of particles and their
#                times): two runs with 1 thread and one with 4 threads
#                identical, a run with lgrseed = 2 different;
#             4. the vertical diffusion: mm_hyd_41 without its tilt lines,
#                one day, with ilagr = 3, rwhpar = 0.5, ipvert = -3 (as in
#                mode ilagr3 otherwise): 1 thread and 4 threads identical;
#             5. a particle restart: mm_lgr run to 2009-01-03 with a restart
#                file (idtrst = -1), then from 2009-01-03 with that restart
#                file (itrst = -1) and its particle file (lgrini, itlgin =
#                '2009-01-03', nbdy = 0): at every output of the restarted
#                run each record (active and exited, every field) must equal
#                the record of the same particle in the plain run of part 1
#                at that output (the time step key of the draws is the
#                absolute time of the step, so the restarted run draws what
#                the run that went on drew);
#             6. a particle restart followed by releases: mm_lgr with a
#                release every day from 2009-01-01 12:00 (idtl = '1d',
#                itranf), run to the end; the same run to 2009-01-03 with a
#                restart file; and a run from 2009-01-03 with that restart
#                file and particle file (lgrini, itlgin) and the releases
#                from 2009-01-03 12:00 (nbdy = 150): the restarted run must
#                release after the restart, no id may repeat in an output of
#                its particle file (in a block, or active and exited), and
#                each record must equal that of the run that went on, at
#                every output (the inserted block of its first output, which
#                lists the particles read from the file, excepted).  Before
#                the fix of the ids (#225, review) lgr_input_shell left the
#                counter of ids at 0: the release after the restart gave the
#                ids 1 ... 145 again, so two particles drew the same numbers
#                (the binary of 7e7b1e55: 37 of 48 outputs with repeated ids,
#                7290 records differ).
#             Before #225 the draws came from random_number, seeded
#             differently in every run and per thread, and from ggrand, a
#             single saved stream: the binary of the commit before fails
#             the first comparison of each part (and does not know
#             lgrseed).  The continuous release along an open boundary
#             (create_parts) is not run here: until #254 it stopped along
#             the whole open boundary of mm_hyd_12a with "error stop
#             create_parts: error in boundary" (also before #225, and after
#             #252: the boundary list skips two boundary nodes); mode
#             segments releases along a part of it, mode bnd-release along
#             all of it.
#   sedbeach  (#225, review) the sediment step and beached particles:
#             mm_lgr_a (2D: every element has one layer, so a particle is
#             always in its bottom layer) with rwhpar = 0.5, ised = 1 (every
#             particle gets a sediment class as its type and a settling
#             velocity) and lbeach = 1 (a particle on a material side
#             beaches: lag_beach negates its type), serially.  The run must
#             end with no "Fortran runtime" or signal line; the particle
#             file must hold beached particles (negative type), each of
#             which reached lgr_sediment with that negative type (in the
#             domain, in its bottom layer, settling velocity above 0); and
#             each beached particle must keep its record (position, layer,
#             z) at every output after it beached.  Before the fix
#             lgr_sediment used the negative type as the sediment class:
#             with -fcheck=bounds (COMPILER_PROFILE=CHECK) the run stopped
#             in its first quarter of an hour with "Index '-3' of dimension
#             1 of array 'tcd' below lower bound of 1"; the normal build
#             read a value outside the array (no visible effect in this
#             case, where the beached particles have z = 0.5).
#   bnd-release (#254) the continuous release along an open boundary
#             (lgrpps on a level boundary, create_parts), serially, on the
#             geographic basin GRID/MM_geo (made with -noopti: its element
#             numbers are those of MM_geo.grd): mm_lgr_a for two hours with
#             no other release (nbdy = 0) and the sea boundary of the Mar
#             Menor cases (kbound 85 ... 177 of mm_lgr_b, ibtyp = 1) with
#             lgrpps = 0.2.  That list leaves out the boundary nodes 13 and
#             14: of its 92 pairs of consecutive nodes 90 are sides of the
#             basin boundary and 99-100 and 162-163 inner sides (the check
#             counts them from MM_geo.grd).  The run must end, its log must
#             warn about exactly those two pairs, and every particle of the
#             inserted blocks of the particle file must start inside its
#             element (barycentric weights >= -5e-3), on a side of that
#             element (one weight within 5e-3 of 0) that is one of the 90
#             sides of the list; each of the 90 sides must get a particle.
#             The same for a release per volume of inflow, lgrpps =
#             -0.00001 (get_bflux_ppv; only the sides with an inflow get
#             particles, so it needs at least one particle, not one per
#             side).
#             A second run with kbound = 98 100 99 101 (no two consecutive
#             nodes are the ends of a side of the basin boundary, while each
#             node has a neighbour on the basin boundary in the list, as the
#             open boundary of the hydrodynamics needs) must stop with
#             "error stop lgr_release_line: no boundary side to release on",
#             a non-zero exit code and no "simulation end".  Before #254
#             the runs stopped with a bare stop, exit code 0 ("STOP error
#             stop create_parts: error in boundary", for lgrpps < 0 "STOP
#             error stop get_bflux_ppv: nodes not at boundary"; the release
#             runs "did not end", the last gave exit code 0; measured
#             before #252 was merged here); and before #252
#             find_elems_to_segment gave every segment of this list the
#             element of the next one, so the particles released before that
#             stop started in an element that does not hold their point.
#
# A run has ended only if its launcher exits with 0 and its log has
# "simulation end".  Needs shyfem, mpirun (Open MPI) and python3 on PATH,
# and `make init` plus (cd GRID && shypre -noopti MM_geo.grd) done here;
# modes vdiff-dt, walk-fold, bed-w and node-sink also gfortran on PATH and
# the source tree three levels up (../../../src/shyfem/lagrange_dif.f90,
# for bed-w and node-sink lagrange_vertical.f90, as in a checkout); mode
# events that source tree too (all of ../../../src); mode cross-budget
# ../venice_lagoon (GRID/venlag62.grd, INPUT, venlag_smoke.str) and shypre
# on PATH.  Mode node-sink-run takes an optional second argument,
# REF_BIN_DIR.
# Exit code 0 on PASS, 1 on FAIL, 2 on a usage error.
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
MODE="${1:-}"
NP=4
rc=0

usage() { echo "usage: $0 stk-omp | decay | decay-rate | outside | segments | ilagr3 | vdiff-events | adv-events | vdiff-dt | walk-fold | bed-w | node-sink | node-sink-run [REF_BIN_DIR] | cross-budget | grow-fail | int-fail | events | small-export | seed | sedbeach | bnd-release | nbdymax"; exit 2; }
fail() { echo "  FAIL: $*"; rc=1; }

case "$MODE" in
  stk-omp|decay|decay-rate|outside|segments|ilagr3|vdiff-events|adv-events|vdiff-dt|walk-fold|bed-w|node-sink|node-sink-run|cross-budget|grow-fail|int-fail|events|small-export|seed|sedbeach|bnd-release|nbdymax) ;;
  *) usage ;;
esac
# the reference binary of node-sink-run (optional; no other mode reads one)
REF=""
if [ "$MODE" = node-sink-run ] && [ $# -gt 1 ]; then
  [ $# = 2 ] || usage
  [ -x "$2/shyfem" ] || { echo "$MODE: FAIL (no executable shyfem in the reference directory '$2')"; exit 1; }
  REF="$(cd "$2" && pwd)" || exit 1
fi

for t in shyfem mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "$MODE: FAIL ($t is not on PATH)"; exit 1; }
done
for b in GRID/MM_geo.bas GRID/MM_coarse.bas GRID/MM_coarse_smooth.bas; do
  [ -f "$HERE/$b" ] || { echo "$MODE: FAIL ($b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE)"; exit 1; }
done

# a GRID/MM_geo.bas that is not what today's shypre writes is replaced, with a
# line saying so (#280); before the copy of this folder below
"$HERE/check_geo_bas.sh" "$HERE" "$MODE" || exit 1

SCR="$(mktemp -d "${TMPDIR:-/tmp}/lgr_fixes.XXXXXX")" || { echo "$MODE: FAIL (mktemp)"; exit 1; }
cp -r "$HERE" "$SCR/mm" || { echo "$MODE: FAIL (cannot copy the test folder)"; exit 1; }
W="$SCR/mm"
rm -f "$W"/*.shy "$W"/*.inf "$W"/*.ext "$W"/*.log

finish() {
  if [ "$rc" = 0 ]; then
    rm -rf "$SCR"
    echo "$MODE: PASS"
  else
    echo "  logs kept in $SCR"
    echo "$MODE: FAIL"
  fi
  exit "$rc"
}

# with_line SRC DST SECTION LINE: copy of SRC.str with LINE right after
# its $SECTION line and the run name (second line of $title) set to DST
with_line() {
  awk -v line="$4" -v name="$2" -v sect="$3" '
    /^\$title/ { t = 1; nt = 0 }
    t && !/^\$/ { nt++; if( nt == 2 ) { print "        " name; next } }
    /^\$end/ { t = 0 }
    { print }
    !done && $0 ~ "^\\$" sect "[ \t\r]*$" { print "        " line; done = 1 }
  ' "$W/$1.str" > "$W/$2.str"
}
with_para() { with_line "$1" "$2" para "$3"; }

# run NAME LOG LAUNCHER...: run NAME.str in the scratch folder; true if
# the launcher exited with 0 and the log has "simulation end"
run() {
  local name="$1" log="$2" lrc; shift 2
  ( cd "$W" && nice -n 10 "$@" "$name.str" > "$log" 2>&1 )
  lrc=$?
  if [ "$lrc" != 0 ]; then
    echo "  $name: the launcher exited with code $lrc ($W/$log)"
    tail -5 "$W/$log" | sed 's/^/    /'
    return 1
  fi
  grep -q "simulation end" "$W/$log" || { echo "  $name: no 'simulation end' in $W/$log"; return 1; }
}

# threads LOG N: the log reports N OpenMP threads
threads() {
  local line
  line="$(grep -m1 'used OMP threads' "$W/$1")"
  echo "  $1: ${line:-no 'used OMP threads' line}"
  echo "$line" | grep -q "used OMP threads: *$2\$" || fail "$1 does not report $2 OpenMP threads"
}

#=============================== stk-omp (#243) ============================
if [ "$MODE" = stk-omp ]; then
  for n in 1 4; do
    with_para mm_lgr_e stk_t$n "nomp = $n"
  done
  for n in 1 4; do
    echo "=== mm_lgr_e, $n OpenMP thread(s): serial and on $NP processes"
    run stk_t$n stk_t$n.serial.log shyfem || fail "serial run with $n thread(s) did not end"
    mv "$W/stk_t$n.lgr.shy" "$W/stk_t$n.serial.lgr.shy" 2> /dev/null
    run stk_t$n stk_t$n.np$NP.log mpirun --oversubscribe -np $NP shyfem || fail "run on $NP processes with $n thread(s) did not end"
    mv "$W/stk_t$n.lgr.shy" "$W/stk_t$n.np$NP.lgr.shy" 2> /dev/null
  done
  threads stk_t4.serial.log 4
  threads stk_t4.np$NP.log 4
  threads stk_t1.serial.log 1
  for v in serial np$NP; do
    a="$W/stk_t1.$v.lgr.shy"; b="$W/stk_t4.$v.lgr.shy"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$v: particle file missing"
    elif cmp -s "$a" "$b"; then echo "  $v: particle file of 4 threads identical to 1 thread ($(stat -c %s "$a") bytes)"
    else fail "$v: particle file of 4 threads differs from 1 thread"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
    fi
  done
  finish
fi

#=============================== decay (#226) ==============================
if [ "$MODE" = decay ]; then
  with_para mm_lgr_a dec_plain "levdbg = 0"
  with_line mm_lgr_a dec_on lagrg "ldecay = 86400."
  grep -q "ldecay = 86400." "$W/dec_on.str" || fail "no ldecay line in dec_on.str"
  echo "=== mm_lgr_a serially, without and with ldecay = 86400."
  run dec_plain dec_plain.log shyfem || fail "plain run did not end"
  run dec_on dec_on.log shyfem || fail "decay run did not end"
  if [ "$rc" = 0 ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/dec_plain.lgr.shy" "$W/dec_on.lgr.shy" "$W/GRID/MM_geo.grd" <<'EOF' || fail "particle file check"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

plain_path, dec_path, grd = sys.argv[2:5]
nodes, elems = {}, []
with open(grd) as fh:
    for line in fh:
        f = line.split()
        if not f:
            continue
        if f[0] == "1":
            nodes[int(f[1])] = (float(f[3]), float(f[4]))
        elif f[0] == "2":
            elems.append(tuple(int(v) for v in f[4:7]))
tri = [(nodes[a], nodes[b], nodes[c]) for a, b, c in elems]

def inside(x, y, eps=1e-6):
    """True if (x, y) lies in a triangle of the mesh (barycentric, eps)."""
    for (x1, y1), (x2, y2), (x3, y3) in tri:
        if x < min(x1, x2, x3) - eps or x > max(x1, x2, x3) + eps:
            continue
        if y < min(y1, y2, y3) - eps or y > max(y1, y2, y3) + eps:
            continue
        d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if d == 0.0:
            continue
        l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
        l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
        if min(l1, l2, 1.0 - l1 - l2) >= -1e-4:
            return True
    return False

nel = len(elems)
_, tp = lc.read_file(plain_path)
_, td = lc.read_file(dec_path)
ok = True
mp = {t: b for t, b, _ in tp}
first_pos = {}
ndec_last = 0
nbad_act = 0
for t, b, _ in td:
    if t not in mp:
        print("  output t=%r of the decay run not in the plain run" % t)
        ok = False
        continue
    ext_p = set(mp[t][1])
    lost = sorted(set(first_pos) - set(b[1]))
    if lost:				# a decayed particle stays in the exited block
        print("  t=%r decayed ids missing from the exited block: %s" % (t, lc.fmt_ids(lost)))
        ok = False
    for pid, p in b[1].items():
        if not 1 <= p["ie"] <= nel:
            print("  t=%r exited id %d: element %d outside 1..%d" % (t, pid, p["ie"], nel))
            ok = False
        if not (math.isfinite(p["x"]) and math.isfinite(p["y"])) or not inside(p["x"], p["y"]):
            print("  t=%r exited id %d: position %r %r not inside the basin" % (t, pid, p["x"], p["y"]))
            ok = False
        if pid in ext_p:
            continue			# left the basin in the plain run too
        if pid in first_pos:
            if first_pos[pid] != (p["x"], p["y"], p["ie"]):
                print("  t=%r decayed id %d moved: %r -> %r" % (t, pid, first_pos[pid], (p["x"], p["y"], p["ie"])))
                ok = False
        else:
            first_pos[pid] = (p["x"], p["y"], p["ie"])
    for pid, p in b[0].items():
        q = mp[t][0].get(pid)
        if q != p:
            nbad_act += 1
    last = t, b
t, b = last
ndec_last = len(set(b[1]) - set(mp[t][1]))
print("  output times %d; at the last one (t=%r): active %d and exited %d in the decay run, active %d and exited %d in the plain run, decayed %d"
      % (len(td), t, len(b[0]), len(b[1]), len(mp[t][0]), len(mp[t][1]), ndec_last))
print("  decayed particles seen %d, every one at a fixed position inside the basin: %s"
      % (len(first_pos), "yes" if ok else "NO"))
for pid in sorted(first_pos)[:1]:
    print("  example: id %d, exited record ie %d x %r y %r (inside: %s; the point 0,0: %s)"
          % (pid, first_pos[pid][2], first_pos[pid][0], first_pos[pid][1],
             inside(first_pos[pid][0], first_pos[pid][1]), inside(0.0, 0.0)))
if ndec_last < 1:
    print("  no decayed particle in the last output")
    ok = False
if nbad_act:
    print("  active records that differ from the plain run: %d" % nbad_act)
    ok = False
else:
    print("  active records of the decay run identical to the plain run")
sys.exit(0 if ok else 1)
EOF
  fi
  finish
fi

#=============================== decay-rate (#246) =========================
if [ "$MODE" = decay-rate ]; then
  for dt in 300 60; do
    sed -e "s/^\(\s*\)mm_lgr_a\s*$/\1dr_$dt/" \
        -e "s/itend = '2009-01-05'/itend = '2009-01-01::06:00:00'/" \
        -e "s/idt = '300s'/idt = '${dt}s'/" \
        -e 's/^\(\s*\)nbdymax = 5000\s*$/\1nbdymax = 20000/' \
        -e 's/^\(\s*\)nbdy = 150\s*$/\1nbdy = 5000\n\1ldecay = 21600./' "$W/mm_lgr_a.str" > "$W/dr_$dt.str"
    for o in "dr_$dt" "itend = '2009-01-01::06:00:00'" "idt = '${dt}s'" 'nbdymax = 20000' 'nbdy = 5000' 'ldecay = 21600.'; do
      grep -qF -- "$o" "$W/dr_$dt.str" || fail "no '$o' in dr_$dt.str"
    done
  done
  for dt in 300 60; do
    echo "=== mm_lgr_a serially, six hours, about 5000 particles, ldecay = 21600., idt = $dt s"
    run dr_$dt dr_$dt.log shyfem || fail "the run with idt = $dt s did not end"
    nrel="$(sed -n 's/.*new particles released: *\([0-9][0-9]*\).*/\1/p' "$W/dr_$dt.log" | head -1)"
    echo "  particles released: ${nrel:-none}"
    [ "${nrel:-0}" -ge 4000 ] || fail "idt = $dt s: ${nrel:-no} particles released, expected at least 4000"
  done
  if [ "$rc" = 0 ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/dr_300.lgr.shy" "$W/dr_60.lgr.shy" <<'EOF' || fail "survival check"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

LDECAY = 21600.0
NSIG = 4.0

def survival(path):
    """Per output time: (t, active, released, expected E, variance V)."""
    _, times = lc.read_file(path)
    rel = {}				# id -> release time (inserted block)
    out = []
    for t, b, _ in times:
        for pid, p in b[-1].items():
            rel[pid] = p["tt"]
        if set(b[0]) - set(rel):
            raise SystemExit("  %s t=%r: an active particle without a release record" % (path, t))
        ps = [math.exp(-(t - tr) / LDECAY) for tr in rel.values()]
        out.append((t, len(b[0]), len(rel), sum(ps), sum(p * (1.0 - p) for p in ps)))
    return out

ok = True
runs = {dt: survival(path) for dt, path in ((300, sys.argv[2]), (60, sys.argv[3]))}
for dt, rows in runs.items():
    print("  idt = %d s: output time, active / released, expected, (active - expected) in standard deviations" % dt)
    for t, n, nrel, e, v in rows:
        z = (n - e) / math.sqrt(v) if v > 0 else float("inf")
        bad = not abs(z) <= NSIG
        ok = ok and not bad
        print("    t = %4.1f h  %5d / %d  expected %8.1f  (%+.2f)%s" % (t / 3600.0, n, nrel, e, z, "  BEYOND 4" if bad else ""))
by_t = {dt: {r[0]: r for r in rows} for dt, rows in runs.items()}
common = sorted(set(by_t[300]) & set(by_t[60]))
if len(common) < 6:
    print("  the two runs share %d output times, expected 6" % len(common))
    ok = False
print("  idt = 300 s against 60 s: survival fraction less its expectation, difference in standard deviations")
for t in common:
    _, n1, r1, e1, v1 = by_t[300][t]
    _, n2, r2, e2, v2 = by_t[60][t]
    d = (n1 - e1) / r1 - (n2 - e2) / r2
    sd = math.sqrt(v1 / r1 ** 2 + v2 / r2 ** 2)
    z = d / sd if sd > 0 else float("inf")
    bad = not abs(z) <= NSIG
    ok = ok and not bad
    print("    t = %4.1f h  fractions %.4f / %.4f  (%+.2f)%s" % (t / 3600.0, n1 / r1, n2 / r2, z, "  BEYOND 4" if bad else ""))
sys.exit(0 if ok else 1)
EOF
  fi

  # 2. a run restarted from its particle file decays as the run that went
  #    on: mm_lgr (random walk), ldecay = 3600., six hours, output every
  #    300 s; the run that went on, the same run to 01:00 with a restart
  #    file, and a run from 01:00 with that restart file and particle file
  setname_dr() {
    awk -v name="$2" '
      /^\$title/ { t = 1; nt = 0 }
      t && !/^\$/ { nt++; if( nt == 2 ) { print "        " name; next } }
      /^\$end/ { t = 0 }
      { print }
    ' "$W/$1.str" > "$W/$2.str"
  }
  sed -e 's/^\(\s*\)rwhpar = .*/&\n\1ldecay = 3600./' -e "s/itend = '2009-01-05'/itend = '2009-01-01::06:00:00'/" \
      -e "s/idtlgr = '1h'/idtlgr = '300s'/" "$W/mm_lgr.str" > "$W/drr_base.str"
  setname_dr drr_base drr_a
  sed -e "s/itend = '2009-01-01::06:00:00'/itend = '2009-01-01::01:00:00'/" \
      -e 's/^\$para[ \t]*$/$para\n        idtrst = -1\n        itmrst = -1/' "$W/drr_a.str" > "$W/drr_w1.str"
  setname_dr drr_w1 drr_w
  sed -e "s/itanf = '2009-01-01'/itanf = '2009-01-01::01:00:00'/" \
      -e 's/^\$para[ \t]*$/$para\n        itrst = -1\n        ityrst = 1/' \
      -e "s/^\\([ \t]*\\)nbdy = 150[ \t]*$/\\1nbdy = 0\n\\1lgrini = 'drr_w.lgr.shy'\n\\1itlgin = '2009-01-01::01:00:00'/" \
      -e "s/^\\\$name[ \t]*$/\$name\n        restrt = 'drr_w.rst'/" "$W/drr_a.str" > "$W/drr_r1.str"
  setname_dr drr_r1 drr_r
  for o in 'ldecay = 3600.' "idtlgr = '300s'" "itend = '2009-01-01::06:00:00'"; do
    grep -qF -- "$o" "$W/drr_a.str" || fail "no '$o' in drr_a.str"
  done
  for o in "itend = '2009-01-01::01:00:00'" 'idtrst = -1'; do
    grep -qF -- "$o" "$W/drr_w.str" || fail "no '$o' in drr_w.str"
  done
  for o in "itanf = '2009-01-01::01:00:00'" 'itrst = -1' 'nbdy = 0' "lgrini = 'drr_w.lgr.shy'" "itlgin = '2009-01-01::01:00:00'" "restrt = 'drr_w.rst'"; do
    grep -qF -- "$o" "$W/drr_r.str" || fail "no '$o' in drr_r.str"
  done
  echo "=== mm_lgr, ldecay = 3600., restarted at 01:00 from its particle and restart files"
  for r in drr_a drr_w drr_r; do run $r $r.log shyfem || fail "$r: the run did not end"; done
  grep -q 'initializing lagrangian from file' "$W/drr_r.log" || fail "the restarted run did not read the particle file"
  grep -q 'A restart has been performed' "$W/drr_r.log" || fail "the restarted run did not read the restart file"
  if [ -s "$W/drr_a.lgr.shy" ] && [ -s "$W/drr_r.lgr.shy" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/drr_a.lgr.shy" "$W/drr_r.lgr.shy" <<'EOF' || fail "the restarted run decays otherwise than the run that went on"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

def load(path):
    _, times = lc.read_file(path)
    return {t: b for t, b, _ in times}

full, rest = load(sys.argv[2]), load(sys.argv[3])
ok = True
t0, t1 = 3600.0, 3900.0			# the restart and the first step after it
if t0 not in full or t1 not in full:
    print("  the run that went on has no output at %r or %r" % (t0, t1))
    sys.exit(1)
n0, n1 = len(full[t0][0]), len(full[t1][0])
print("  the run that went on: active %d at the restart (01:00), %d one step later" % (n0, n1))
if n1 >= n0:
    print("  no particle decayed in the first step after the restart: the check would not see a missing draw")
    ok = False
nout = nrec = ndiff = 0
for t in sorted(rest):
    nout += 1
    a, b = full.get(t), rest[t]
    if a is None:
        print("  output t=%r of the restarted run not in the run that went on" % t)
        ok = False
        continue
    if set(a[0]) != set(b[0]):
        ndiff += 1
        if ndiff <= 3:
            print("  t=%r: active ids differ (only in the run that went on %s, only in the restarted run %s)"
                  % (t, lc.fmt_ids(set(a[0]) - set(b[0])), lc.fmt_ids(set(b[0]) - set(a[0]))))
    for pid in set(a[0]) & set(b[0]):
        nrec += 1
        if a[0][pid] != b[0][pid]:
            ndiff += 1
print("  restarted run: %d outputs, %d active records compared with the run that went on, %d differences"
      % (nout, nrec, ndiff))
sys.exit(0 if ok and ndiff == 0 and nrec > 0 else 1)
EOF
  else
    fail "particle file missing (drr_a or drr_r)"
  fi
  finish
fi

#=============================== outside (#247) ============================
if [ "$MODE" = outside ]; then
  # trajectory file: 01:00 a point east of the basin (in no element of
  # MM_geo, whose longitudes end at -0.6187), 02:00 the centroid of element
  # 1000 (inside)
  printf '2009-01-01::01:00:00 -0.50 37.75\n2009-01-01::02:00:00 -0.7127473 37.7160403\n' > "$W/traj_outside.txt"
  for c in a c; do
    sed -e "s/^\(\s*\)mm_lgr_$c\s*$/\1out_$c/" \
        -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
        -e 's/^\(\s*\)idtl = 0\s*$/\1idtl = -1/' \
        -e 's/^\(\s*\)nbdy = 150\s*$/\1nbdy = 5/' \
        -e 's/^\(\s*\)ipvert = -1\s*$/\1ipvert = -3/' \
        -e "s/^\(\s*\)lgrlin = .*/\1lgrtrj = 'traj_outside.txt'/" "$W/mm_lgr_$c.str" > "$W/out_$c.str"
    for o in "out_$c" "itend = '2009-01-01::06:00:00'" 'idtl = -1' 'nbdy = 5' "lgrtrj = 'traj_outside.txt'"; do
      grep -qF -- "$o" "$W/out_$c.str" || fail "no '$o' in out_$c.str"
    done
    grep -q 'lgrlin' "$W/out_$c.str" && fail "lgrlin left in out_$c.str"
  done
  grep -qF 'ipvert = -3' "$W/out_c.str" || fail "no 'ipvert = -3' in out_c.str"
  # case, particles per point (nbdy = 5 calls, 3 random depths each in 3D)
  for cn in "a 5" "c 15"; do
    set -- $cn; c=$1; np=$2
    echo "=== mm_lgr_$c serially (6 h, nbdy = 5$( [ $c = c ] && echo ', 3D, ipvert = -3')) with lgrtrj: a point outside the mesh at 01:00, one inside at 02:00"
    run out_$c out_$c.log shyfem || { fail "out_$c: the run did not end"; continue; }
    l1="$(grep -m1 'particles not released, point outside the mesh' "$W/out_$c.log")"
    echo "  ${l1:-no line 'particles not released, point outside the mesh' in the log}"
    echo "$l1" | grep -q "mesh: *$np at time: 2009-01-01::01:00:00" || fail "out_$c: no count $np of particles not released at 01:00"
    l2="$(grep 'new particles released' "$W/out_$c.log" | tr -s ' ' | sed 's/^ //')"
    echo "$l2" | sed 's/^/  /'
    echo "$l2" | grep -q "released: 0 at time: 2009-01-01::01:00:00" || fail "out_$c: not 0 particles released at 01:00"
    echo "$l2" | grep -q "released: $np at time: 2009-01-01::02:00:00" || fail "out_$c: not $np particles released at 02:00"
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/out_$c.lgr.shy" "$np" <<'EOF' || fail "out_$c: particle file check"
import struct, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

path, np = sys.argv[2], int(sys.argv[3])
with open(path, "rb") as fh:
    head = fh.read(4096)
pos = 0
recs = []
for _ in range(3):			# model header: (idshy, nvers), (ftype),
    (n,) = struct.unpack_from("<i", head, pos)	# (nkn, nel, npr, nlv, nvar)
    recs.append((pos + 4, n))
    pos += 8 + n
nkn, nel, _npr, nlv, _nvar = struct.unpack_from("<5i", head, recs[2][0])
_, times = lc.read_file(path)
ok = True
nrec = 0
want = set(range(1, np + 1))
for t, b, _ in times:
    ids = set()
    for w in lc.IWHAT_ORDER:
        for pid, p in b[w].items():
            nrec += 1
            ids.add(pid)
            if not 1 <= p["ie"] <= nel or not 1 <= p["lb"] <= nlv:
                print("  t=%r %s id %d: element %d, layer %d outside 1..%d, 1..%d"
                      % (t, lc.BLOCK_NAME[w], pid, p["ie"], p["lb"], nel, nlv))
                ok = False
    if t < 7200.0 and ids:
        print("  t=%r (before the release inside, at 02:00): particles %s" % (t, lc.fmt_ids(ids)))
        ok = False
    if t >= 7200.0 and ids != want:
        print("  t=%r: ids %s, expected 1..%d" % (t, lc.fmt_ids(ids), np))
        ok = False
    for pid, p in b[-1].items():
        if p["ie"] != 1000:
            print("  t=%r inserted id %d: release element %d, expected 1000" % (t, pid, p["ie"]))
            ok = False
print("  output times %d (nel %d, nlv %d), records %d: ids 1..%d from 02:00 on, every element in 1..nel: %s"
      % (len(times), nel, nlv, nrec, np, "yes" if ok else "NO"))
sys.exit(0 if ok and nrec > 0 else 1)
EOF
  done
  finish
fi

#=============================== segments (#252) ===========================
if [ "$MODE" = segments ]; then
  # 1. the self-test of find_elems_to_segment at levdbg = 3 (one hour of
  #    mm_lgr_a), serially and on NP processes
  sed -e 's/^\(\s*\)mm_lgr_a\s*$/\1sg_dbg/' -e 's/^\$para\s*$/$para\n        levdbg = 3/' \
      -e "s/itend = '2009-01-05'/itend = '2009-01-01::01:00:00'/" "$W/mm_lgr_a.str" > "$W/sg_dbg.str"
  for o in sg_dbg 'levdbg = 3' "itend = '2009-01-01::01:00:00'"; do
    grep -qF -- "$o" "$W/sg_dbg.str" || fail "no '$o' in sg_dbg.str"
  done
  nel="$(awk '$1 == 2' "$W/GRID/MM_geo.grd" | wc -l)"
  for np in 1 $NP; do
    echo "=== mm_lgr_a, one hour, levdbg = 3, on $np process(es): self-test of find_elems_to_segment"
    if [ $np = 1 ]; then run sg_dbg sg_dbg.np1.log shyfem || fail "the serial run did not end"
    else run sg_dbg sg_dbg.np$np.log mpirun --oversubscribe -np $np shyfem || fail "the run on $np processes did not end"
    fi
    log="$W/sg_dbg.np$np.log"
    grep 'lgr self-test find_elems_to_segment' "$log" | sort | sed 's/^ */  /'
    for ((r = 0; r < np; r++)); do
      line="$(grep "lgr self-test find_elems_to_segment: rank $r segments" "$log")"
      [ -n "$line" ] || { fail "$np process(es): no self-test line of rank $r"; continue; }
      [ "$(echo "$line" | wc -l)" = 1 ] || fail "$np process(es): rank $r wrote the self-test line more than once"
      echo "$line" | grep -q ' wrong 0$' || fail "$np process(es): rank $r: wrong segments"
    done
    if [ $np = 1 ]; then
      grep -q "rank 0 segments $((6 * nel)) wrong" "$log" || fail "serial: not 6 x nel = $((6 * nel)) segments checked"
    fi
  done

  # 2. a continuous release (lgrpps) along the open boundary nodes 85 ... 99
  #    of mm_hyd_12a (the part of its list whose segments are all boundary
  #    sides), six hours, serially
  sed -e 's/^\(\s*\)mm_lgr_a\s*$/\1sg_line/' -e "s/itend = '2009-01-05'/itend = '2009-01-01::06:00:00'/" \
      -e 's/^\(\s*\)idtl = 0\s*$/\1idtl = -1/' "$W/mm_lgr_a.str" > "$W/sg_line.str"
  printf '\n$bound1\n        kbound = 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99\n        ibtyp = 1\n        boundn = %s\n        lgrpps = 0.01\n$end\n' \
    "'INPUT/level_Mar_Menor.dat'" >> "$W/sg_line.str"
  for o in sg_line "itend = '2009-01-01::06:00:00'" 'idtl = -1' 'lgrpps = 0.01'; do
    grep -qF -- "$o" "$W/sg_line.str" || fail "no '$o' in sg_line.str"
  done
  echo "=== mm_lgr_a, six hours, continuous release (lgrpps = 0.01) along the boundary nodes 85 ... 99, serially"
  if run sg_line sg_line.log shyfem; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/sg_line.lgr.shy" "$W/GRID/MM_geo.grd" <<'EOF' || fail "release elements"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

path, grd = sys.argv[2], sys.argv[3]
kb = list(range(85, 100))
nodes, el = {}, {}
with open(grd) as fh:
    for line in fh:
        f = line.split()
        if f and f[0] == "1":
            nodes[int(f[1])] = (float(f[3]), float(f[4]))
        elif f and f[0] == "2":
            el[int(f[1])] = [int(v) for v in f[4:7]]
segs = list(zip(kb[:-1], kb[1:]))
# the element of each segment, by search of the element list: exactly one
# (a boundary side)
segel = {}
for a, c in segs:
    es = [e for e, ns in el.items() if a in ns and c in ns]
    if len(es) != 1:
        print("  segment %d-%d: elements %r, not a boundary side" % (a, c, es))
        sys.exit(1)
    segel[(a, c)] = es[0]
_, times = lc.read_file(path)
n = nbad = 0
for t, b, _ in times:
    for pid, p in b[-1].items():	# release records (inserted block)
        n += 1
        x, y, ie = p["x"], p["y"], p["ie"]
        best = None			# the segment the point lies on
        for a, c in segs:
            (x1, y1), (x2, y2) = nodes[a], nodes[c]
            dx, dy = x2 - x1, y2 - y1
            l2 = dx * dx + dy * dy
            s = ((x - x1) * dx + (y - y1) * dy) / l2
            d = abs((x - x1) * dy - (y - y1) * dx) / math.sqrt(l2)
            if -1e-4 <= s <= 1.0 + 1e-4 and (best is None or d < best[0]):
                best = (d, a, c)
        # positions are single precision degrees: 2e-5 is about 2 m
        if best is None or best[0] > 2e-5:
            nbad += 1
            if nbad <= 5:
                print("  t=%r id %d: release point %r %r on no segment" % (t, pid, x, y))
        elif ie != segel[(best[1], best[2])]:
            nbad += 1
            if nbad <= 5:
                print("  t=%r id %d: released in element %d, its segment %d-%d has element %d"
                      % (t, pid, ie, best[1], best[2], segel[(best[1], best[2])]))
print("  particles released %d, not in the element of their boundary segment %d" % (n, nbad))
sys.exit(0 if n >= 100 and nbad == 0 else 1)
EOF
  else
    fail "the line release did not end"
  fi
  finish
fi

#=============================== ilagr3 (#231) =============================
if [ "$MODE" = ilagr3 ]; then
  sed -e '/^\s*ztilt\s*=/d' -e '/^\s*ktilt\s*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e 's/^\(\s*\)mm_hyd_41\s*$/\1lgr_ilagr3/' "$W/mm_hyd_41.str" > "$W/lgr_ilagr3.str"
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 20000\n        nbdy = 300  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = -1\n$end\n' "'1h'" >> "$W/lgr_ilagr3.str"
  grep -q "lgr_ilagr3" "$W/lgr_ilagr3.str" || fail "run name not set in lgr_ilagr3.str"
  grep -q "tilt" "$W/lgr_ilagr3.str" && fail "tilt lines left in lgr_ilagr3.str"
  echo "=== mm_hyd_41 (no tilt, one day) with ilagr = 3, serially"
  run lgr_ilagr3 lgr_ilagr3.log shyfem || fail "the ilagr = 3 run did not end"
  line="$(grep -m1 'lgr vertical diffusion: negative diffusivities set to 0:' "$W/lgr_ilagr3.log")"
  echo "  ${line:-no line 'lgr vertical diffusion: negative diffusivities set to 0:' in the log}"
  nneg="$(echo "$line" | sed -n 's/.*set to 0: *\([0-9][0-9]*\).*/\1/p')"
  [ "${nneg:-x}" = 0 ] || fail "negative interpolated diffusivities: ${nneg:-not reported}, expected 0"
  line="$(grep -m1 'lgr vertical diffusion: random walk time step' "$W/lgr_ilagr3.log")"
  [ -n "$line" ] && echo "  $line"	# information only (#257)
  # the cap of the calls of a particle step (#261)
  nwarn="$(grep -c 'warning particle dif' "$W/lgr_ilagr3.log")"
  echo "  lines 'warning particle dif' (written in the particle loop until #261): $nwarn"
  [ "$nwarn" = 0 ] || fail "$nwarn lines 'warning particle dif' in the log, expected none"
  l1="$(grep 'lgr vertical diffusion: particle steps:' "$W/lgr_ilagr3.log")"
  l2="$(grep 'lgr vertical diffusion: steps stopped at the cap of' "$W/lgr_ilagr3.log")"
  echo "  ${l1:-no line 'lgr vertical diffusion: particle steps:' in the log}"
  echo "  ${l2:-no line 'lgr vertical diffusion: steps stopped at the cap of' in the log}"
  [ "$(printf '%s' "$l1" | grep -c .)" = 1 ] || fail "the line of the particle steps is not written once"
  [ "$(printf '%s' "$l2" | grep -c .)" = 1 ] || fail "the line of the steps stopped at the cap is not written once"
  mcall="$(printf '%s' "$l1" | sed -n 's/.*most calls in a step: *\([0-9][0-9]*\).*/\1/p')"
  ncap="$(printf '%s' "$l2" | sed -n 's/.*steps stopped at the cap of [0-9]* calls: *\([0-9][0-9]*\),.*/\1/p')"
  nend="$(printf '%s' "$l2" | sed -n 's/.*steps ended by 2 calls in a row that used no time: *\([0-9][0-9]*\),.*/\1/p')"
  if [ -z "$mcall" ] || [ "$mcall" -le 100 ] || [ "$mcall" -gt 1501 ]; then
    fail "most calls of lgr_diff_vert in a particle step ${mcall:-not reported}, expected more than 100 (the cap before #261) and at most 1501 (ceiling(300/0.2) + 1; measured 1501)"
  fi
  [ "${ncap:-x}" = 0 ] || fail "particle steps stopped at the cap ${ncap:-not reported}, expected 0 (T = 300 s needs at most 1501 calls; measured 0)"
  [ "${nend:-x}" = 0 ] || fail "particle steps ended by two calls in a row that used no time ${nend:-not reported}, expected 0"
  if [ "$rc" = 0 ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/lgr_ilagr3.lgr.shy" <<'EOF' || fail "particle file check"
import math, struct, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

path = sys.argv[2]
with open(path, "rb") as fh:
    head = fh.read(4096)
recs = []				# model header: (idshy, nvers), (ftype),
pos = 0					# (nkn, nel, npr, nlv, nvar)
for _ in range(3):
    (n,) = struct.unpack_from("<i", head, pos)
    recs.append((pos + 4, n))
    pos += 8 + n
if [r[1] for r in recs] != [8, 4, 20]:
    print("  no model header in %s" % path)
    sys.exit(1)
nkn, nel, _npr, nlv, _nvar = struct.unpack_from("<5i", head, recs[2][0])
_, times = lc.read_file(path)
ok = True
nact = 0
for t, b, _ in times:
    for w in lc.IWHAT_ORDER:
        for pid, p in b[w].items():
            vals = [p["x"], p["y"], p["z"], p["hl"], p["tt"], p["s"]] + list(p["c"])
            if not all(math.isfinite(v) for v in vals):
                print("  t=%r %s id %d: a value is not finite: %r" % (t, lc.BLOCK_NAME[w], pid, p))
                ok = False
    for pid, p in b[0].items():
        nact += 1
        if not 1 <= p["ie"] <= nel or not 1 <= p["lb"] <= nlv or not 0.0 <= p["z"] <= 1.0:
            print("  t=%r active id %d: ie %d lb %d z %r outside 1..%d, 1..%d, 0..1"
                  % (t, pid, p["ie"], p["lb"], p["z"], nel, nlv))
            ok = False
t, b, _ = times[-1]
print("  output times %d (nel %d, nlv %d); last t=%r: active %d, exited %d; active records checked %d: %s"
      % (len(times), nel, nlv, t, len(b[0]), len(b[1]), nact, "ok" if ok else "FAIL"))
if not times or nact == 0:
    ok = False
sys.exit(0 if ok else 1)
EOF
  fi
  # the end of the particle run between two calls of lagrange: the line of
  # the negative diffusivities must still be written (once)
  sed -e "s/itend = '[^']*'/itend = '2009-01-01::12:00:00'/" \
      -e 's/^\(\s*\)lgr_ilagr3\s*$/\1lgr_ilagr3_end/' \
      -e "s/^\(\s*\)ilagr = 3 .*/&\n        itlend = '2009-01-01::06:02:30'/" \
      "$W/lgr_ilagr3.str" > "$W/lgr_ilagr3_end.str"
  grep -q "itlend = '2009-01-01::06:02:30'" "$W/lgr_ilagr3_end.str" || fail "no itlend line in lgr_ilagr3_end.str"
  echo "=== the same, 12 hours, with itlend = 06:02:30 (between two time steps of 300 s)"
  run lgr_ilagr3_end lgr_ilagr3_end.log shyfem || fail "the ilagr = 3 run with itlend did not end"
  n="$(grep -c 'lgr vertical diffusion: negative diffusivities set to 0:' "$W/lgr_ilagr3_end.log")"
  line="$(grep -m1 'lgr vertical diffusion: negative diffusivities set to 0:' "$W/lgr_ilagr3_end.log")"
  echo "  ${line:-no line 'lgr vertical diffusion: negative diffusivities set to 0:' in the log} ($n line(s))"
  [ "$n" = 1 ] || fail "the line of the negative diffusivities is written $n times with itlend between two steps, expected once"
  for t in 'particle steps:' 'steps stopped at the cap of'; do
    n="$(grep -c "lgr vertical diffusion: $t" "$W/lgr_ilagr3_end.log")"
    echo "  lines 'lgr vertical diffusion: $t': $n"
    [ "$n" = 1 ] || fail "the line 'lgr vertical diffusion: $t' is written $n times with itlend between two steps, expected once"
  done
  finish
fi

#=============================== vdiff-events (#288) =======================
if [ "$MODE" = vdiff-events ]; then
  HOOK=10
  # mm_hyd_41 in still water (the edits of check_lgr_wellmixed.sh), two
  # hours, with the $lagrg section and nomp = -1 (threads from
  # OMP_NUM_THREADS)
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::02:00:00'/" \
      -e 's/^\([[:space:]]*\)mm_hyd_41[[:space:]]*$/\1vdev/' \
      -e 's/^\([[:space:]]*\)ibarcl = 3/\1ibarcl = 0/' \
      -e 's/^\([[:space:]]*\)iturb = 1      ievap = 1 /\1iturb = 0      ievap = 0 /' \
      -e 's/^\([[:space:]]*\)iturb = 0 .*/&\n\1diftur = 1.e-2   vistur = 1.e-3/' \
      -e 's/^\([[:space:]]*\)ibtyp = [13][[:space:]]*$/\1ibtyp = 0/' \
      -e '/^[[:space:]]*wind[[:space:]]*=/d' -e '/^[[:space:]]*qflux[[:space:]]*=/d' \
      -e '/^[[:space:]]*rain[[:space:]]*=/d' "$W/mm_hyd_41.str" > "$W/vdev0.str"
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 20000\n        nbdy = 300  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = -1\n$end\n' "'1h'" >> "$W/vdev0.str"
  for t in 1 4; do
    with_para vdev0 vdev_t$t "nomp = -1"
  done
  for o in "itend = '2009-01-01::02:00:00'" 'ibarcl = 0' 'iturb = 0      ievap = 0' 'diftur = 1.e-2' 'nomp = -1' 'ilagr = 3'; do
    grep -qF -- "$o" "$W/vdev_t4.str" || fail "vdev_t4.str: no '$o'"
  done
  [ "$(grep -c 'ibtyp = 0' "$W/vdev_t4.str")" = 2 ] || fail "vdev_t4.str: the boundaries are not closed"
  grep -q 'tilt\|wind\|qflux\|rain\|ibtyp = [13]' "$W/vdev_t4.str" && fail "vdev_t4.str: forcing or tilt lines left"
  grep -q "^[[:space:]]*vdev_t4[[:space:]]*\$" "$W/vdev_t4.str" || fail "vdev_t4.str: run name not set"
  [ "$rc" = 0 ] || finish
  for t in 1 4; do
    echo "=== mm_hyd_41 in still water, two hours, ilagr = 3, LGR_TEST_VDIFF_END=$HOOK, OMP_NUM_THREADS=$t, serially"
    run vdev_t$t vdev_t$t.log env LGR_TEST_VDIFF_END=$HOOK OMP_NUM_THREADS=$t shyfem \
      || fail "the run with $t thread(s) did not end"
    threads vdev_t$t.log $t
    grep -q "test hook LGR_TEST_VDIFF_END: .* multiple of $HOOK " "$W/vdev_t$t.log" \
      || fail "$t thread(s): the log does not acknowledge the test hook LGR_TEST_VDIFF_END"
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" vdev_t$t "$HOOK" <<'EOF' || fail "$t thread(s): see above"
import os, re, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

w, name, hook = sys.argv[1], sys.argv[2], int(sys.argv[3])
ok = True
_, times = lc.read_file(os.path.join(w, name + ".lgr.shy"))
rel = set()				# released ids (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1].keys())
lost = sorted(i for i in rel if i % (2 * hook) == 0)
unkn = sorted(i for i in rel if i % hook == 0 and i % (2 * hook) != 0)
t, b, _ = times[-1]
act, ext = set(b[0].keys()), set(b[1].keys())
print("  released %d particles; expected: lost %d (first id %s), walks ended in every step %d (first id %s)"
      % (len(rel), len(lost), lost[0] if lost else "-", len(unkn), unkn[0] if unkn else "-"))
print("  last output t=%r: active %d, exited %d" % (t, len(act), len(ext)))
if not lost or not unkn:
    print("  FAIL: the release gives no particle to the hook")
    ok = False
if ext != set(lost) or act != rel - set(lost):
    print("  FAIL: the exited particles are not exactly the ids that are multiples of %d" % (2 * hook))
    ok = False
# particle steps: the lines lagrange_nbdy of the .inf file with particles
npass = 0
with open(os.path.join(w, name + ".inf")) as fh:
    for line in fh:
        f = line.split()
        if len(f) == 2 and f[0] == "lagrange_nbdy:" and int(f[1]) > 0:
            npass += 1
print("  particle steps (lines lagrange_nbdy: in %s.inf): %d" % (name, npass))
if npass < 2:
    print("  FAIL: fewer than 2 particle steps")
    ok = False
with open(os.path.join(w, name + ".log"), errors="replace") as fh:
    log = fh.read().split("\n")
nper = [sum(1 for l in log if s in l) for s in ("loosing particle dif", "unknown error dif")]
print("  lines written from inside the particle loop: 'loosing particle dif' %d, 'unknown error dif' %d"
      % tuple(nper))
if sum(nper) > 0:
    print("  FAIL: %d lines written from inside the particle loop, one per particle step"
          " (the summary lines expected instead)" % sum(nper))
    ok = False
pat = r"(\d+) in the step to (\S+), (\d+) in the run \(.*\); first: id (\d+),"
kinds = (("lost with time left", lost, 1),
         ("walk ended with time left, cause unknown", unkn, npass))
for text, ids, nexp in kinds:
    lines = [l for l in log if "lgr vertical diffusion: " + text + ":" in l]
    print("  summary lines 'lgr vertical diffusion: %s:': %d (expected %d)" % (text, len(lines), nexp))
    for l in lines[:2] + (["    ..."] if len(lines) > 3 else []) + lines[2:][-1:]:
        print("    " + l.strip())
    if len(lines) != nexp:
        print("  FAIL: %d summary lines, expected %d" % (len(lines), nexp))
        ok = False
        continue
    for k, l in enumerate(lines, 1):
        m = re.search("lgr vertical diffusion: " + re.escape(text) + ": " + pat, l)
        if not m:
            print("  FAIL: cannot read the line %r" % l.strip())
            ok = False
            continue
        n, ntot, first = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if n != len(ids) or ntot != k * len(ids) or first != ids[0]:
            print("  FAIL: step %d: %d in the step, %d in the run, first id %d;"
                  " expected %d, %d, %d" % (k, n, ntot, first, len(ids), k * len(ids), ids[0]))
            ok = False
sys.exit(0 if ok else 1)
EOF
  done
  # the same summary lines and the same particle file on 1 and 4 threads
  for t in 1 4; do
    grep 'lgr vertical diffusion: lost with time left:\|lgr vertical diffusion: walk ended with time left' \
      "$W/vdev_t$t.log" > "$W/vdev_t$t.summary"
  done
  if [ ! -s "$W/vdev_t1.summary" ]; then
    fail "no summary lines to compare"
  elif cmp -s "$W/vdev_t1.summary" "$W/vdev_t4.summary"; then
    echo "  summary lines of 4 threads identical to 1 thread ($(wc -l < "$W/vdev_t1.summary") lines)"
  else
    fail "the summary lines of 4 threads differ from 1 thread"; diff "$W/vdev_t1.summary" "$W/vdev_t4.summary" | head -4 | sed 's/^/    /'
  fi
  a="$W/vdev_t1.lgr.shy"; b="$W/vdev_t4.lgr.shy"
  if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "particle file missing"
  elif cmp -s "$a" "$b"; then echo "  particle file of 4 threads identical to 1 thread ($(stat -c %s "$a") bytes)"
  else fail "the particle file of 4 threads differs from 1 thread"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
  fi
  finish
fi

#=============================== adv-events (#294) =========================
if [ "$MODE" = adv-events ]; then
  # mm_lgr_b as it is, with the threads from OMP_NUM_THREADS (serial runs)
  # or two threads per process (nomp = 2, the run on NP processes)
  with_para mm_lgr_b advb "nomp = -1"
  with_para mm_lgr_b advb_mpi "nomp = 2"
  for f in advb advb_mpi; do
    grep -q "^[[:space:]]*$f[[:space:]]*\$" "$W/$f.str" || fail "$f.str: run name not set"
    grep -q "ilagr = 1" "$W/$f.str" || fail "$f.str: no 'ilagr = 1'"
  done
  [ "$rc" = 0 ] || finish
  for t in 1 4; do
    echo "=== mm_lgr_b, OMP_NUM_THREADS=$t, serially"
    run advb advb_t$t.log env OMP_NUM_THREADS=$t shyfem || fail "the run with $t thread(s) did not end"
    mv "$W/advb.lgr.shy" "$W/advb_t$t.lgr.shy" 2> /dev/null
    threads advb_t$t.log $t
  done
  echo "=== mm_lgr_b, 2 OpenMP threads, on $NP processes"
  run advb_mpi advb_np$NP.log mpirun --oversubscribe -np $NP shyfem || fail "the run on $NP processes did not end"
  threads advb_np$NP.log 2
  STR_ITANF="$(sed -n "s/.*itanf = '\([^']*\)'.*/\1/p" "$W/advb.str" | head -1)"
  PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$STR_ITANF" "$NP" <<'EOF' || fail "see above"
import datetime, os, re, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

w, itanf, np_ = sys.argv[1], sys.argv[2], int(sys.argv[3])
t0 = datetime.datetime.strptime(itanf[:10], "%Y-%m-%d")
ok = True
def bad(msg):
    global ok
    print("  FAIL: " + msg)
    ok = False

OLD = ("loosing particle adv", "warning particle adv", "unknown error adv",
       "material boundary:", "vel < 0", "warning: wrong layer")
LOST, WALL = "lost with time left", "flux over a wall side set to 0"
pat = re.compile(r"^ lgr advection:(?: rank (\d+):)? (.+?): (\d+) in the step to (\S+?)"
                 r"(?:, (\d+) in the run \([\d.]+ events per 100 of the \d+ particles released\))?; first: (.*)$")

def read_log(name):
    """the summary lines of a log: {(rank, kind): [(step, n, ntot, first)]}"""
    with open(os.path.join(w, name), errors="replace") as fh:
        log = fh.read().split("\n")
    nold = [sum(1 for l in log if s in l) for s in OLD]
    print("  %s: lines written from inside the particle loop: %s" % (name,
          ", ".join("'%s' %d" % (s, n) for s, n in zip(OLD, nold))))
    if sum(nold) > 0:
        bad("%s: %d lines written from inside the particle loop, one per particle step"
            " (the summary lines expected instead)" % (name, sum(nold)))
    ev, lines = {}, [l for l in log if l.startswith(" lgr advection:")]
    for l in lines:
        m = pat.match(l)
        if not m:
            bad("%s: cannot read the line %r" % (name, l))
            continue
        rank = int(m.group(1)) if m.group(1) is not None else -1
        step = datetime.datetime.strptime(m.group(4), "%Y-%m-%d::%H:%M:%S")
        first = dict((f.rsplit(" ", 1)[0].strip(), f.rsplit(" ", 1)[1]) for f in m.group(6).split(", "))
        ntot = int(m.group(5)) if m.group(5) is not None else None
        ev.setdefault((rank, m.group(2)), []).append(((step - t0).total_seconds(), int(m.group(3)), ntot, first))
    for (rank, kind), es in sorted(ev.items()):
        steps = [e[0] for e in es]
        tot = 0
        for s, n, ntot, _ in es:
            tot += n
            if ntot != tot:
                bad("%s rank %d '%s': step %r: %r in the run, expected %d" % (name, rank, kind, s, ntot, tot))
                break
        if steps != sorted(set(steps)):
            bad("%s rank %d '%s': more than one line in a pass" % (name, rank, kind))
        print("    %s%s: %d lines (passes), %d events in the run"
              % (name, "" if rank < 0 else " rank %d" % rank, len(es), tot) + " '%s'" % kind)
    return ev, lines

ev1, lines1 = read_log("advb_t1.log")
ev4, lines4 = read_log("advb_t4.log")
evm, _ = read_log("advb_np%d.log" % np_)

# serial: the particle file is the oracle of the lost particles
_, times = lc.read_file(os.path.join(w, "advb_t1.lgr.shy"))
lost = ev1.get((-1, LOST), [])
wall = ev1.get((-1, WALL), [])
if not lost:
    bad("no summary line '%s'" % LOST)
if not wall:
    bad("no summary line '%s'" % WALL)
if any(r >= 0 for r, _ in ev1):
    bad("a serial line has a rank")
nout = 0
for t, b, _ in times:
    ext = set(b[1].keys())
    upto = [e for e in lost if e[0] <= t]
    nrun = upto[-1][2] if upto else 0
    if nrun != len(ext):
        nout += 1
        if nout <= 3:
            bad("output t=%r: %d lost in the run, %d exited particles in the particle file" % (t, nrun, len(ext)))
if nout > 3:
    bad("... and %d more outputs (of %d) where the two differ" % (nout - 3, len(times)))
# the first of each step: exited by the next output, not by the one before
outs = [(t, set(b[1].keys())) for t, b, _ in times]
nchk = 0
for s, n, ntot, first in lost:
    after = [e for t, e in outs if t >= s]
    before = [e for t, e in outs if t < s]
    i = int(first["id"])
    if not after or i not in after[0] or (before and i in before[-1]):
        bad("step %r: first id %d did not exit between the outputs around the step" % (s, i))
    if int(first["element"]) >= 0 or not 0 < int(first["crossings left"]) <= 100 \
            or not float(first["time left [s]"]) > 0:
        bad("step %r: first %r: not out of the domain with time and crossings left" % (s, first))
    nchk += 1
if lost:
    t, b, _ = times[-1]
    print("  serial: %d lost in the run (%d steps checked), %d exited at the last output t=%r;"
          " %d fluxes over a wall side in the run" % (lost[-1][2], nchk, len(b[1]), t,
          wall[-1][2] if wall else 0))
    print("    " + [l for l in lines1 if LOST in l][0].strip())
    if wall:
        print("    " + [l for l in lines1 if WALL in l][0].strip())

# 1 and 4 threads: the same summary lines
if not lines1:
    bad("no summary lines to compare")
elif lines1 != lines4:
    bad("the summary lines of 4 threads differ from 1 thread")
else:
    print("  summary lines of 4 threads identical to 1 thread (%d lines)" % len(lines1))

# several processes: each line with its rank; per kind and step the sum
# over the ranks equals the serial count
if any(r < 0 for r, _ in evm):
    bad("a line of the run on %d processes has no rank" % np_)
ser = dict(((k, s), n) for (r, k), es in ev1.items() for s, n, _, _ in es)
par = {}
for (r, k), es in evm.items():
    for s, n, _, _ in es:
        par[(k, s)] = par.get((k, s), 0) + n
if not ser:
    bad("no serial counts to compare with the run on %d processes" % np_)
elif ser != par:
    diff = sorted(set(ser) ^ set(par)) + sorted(x for x in set(ser) & set(par) if ser[x] != par[x])
    bad("the counts summed over the %d ranks differ from the serial ones (%d steps, first %r)"
        % (np_, len(diff), diff[:1]))
else:
    print("  %d processes: the counts of %d kind(s) and steps summed over %d rank(s) equal the serial ones"
          % (np_, len(set(k for k, _ in ser)), len(set(r for r, _ in evm))))
sys.exit(0 if ok else 1)
EOF
  a="$W/advb_t1.lgr.shy"; b="$W/advb_t4.lgr.shy"
  if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "particle file missing"
  elif cmp -s "$a" "$b"; then echo "  particle file of 4 threads identical to 1 thread ($(stat -c %s "$a") bytes)"
  else fail "the particle file of 4 threads differs from 1 thread"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
  fi
  finish
fi

#=============================== vdiff-dt (#257) ===========================
if [ "$MODE" = vdiff-dt ]; then
  # 1. lgr_vdiff_curvature compiled on its own (no model run)
  echo "=== lgr_vdiff_curvature on its own: quadratic, linear and constant K on unequal layers, a layer of zero thickness"
  SRCF="$HERE/../../../src/shyfem/lagrange_dif.f90"
  if ! command -v gfortran > /dev/null 2>&1; then
    fail "gfortran is not on PATH"
  elif [ ! -f "$SRCF" ]; then
    fail "no $SRCF"
  else
    awk '/^[ \t]*subroutine lgr_vdiff_curvature/,/^[ \t]*end subroutine lgr_vdiff_curvature/' "$SRCF" > "$W/vcurv.f90"
    grep -q 'end subroutine lgr_vdiff_curvature' "$W/vcurv.f90" || fail "lgr_vdiff_curvature not found in $SRCF"
    cat > "$W/vcurv_test.f90" <<'EOF'
	program vcurv_test
! K = a + b z + c z**2 at the interfaces z of unequal layers: K'' must be
! 2c at every interface (the bottom one extrapolated), 0 for a linear and
! for a constant K; a layer of zero thickness sets bzero (no division)
	implicit none
	integer, parameter :: n = 6
	real, parameter :: a = 1.e-3, b = 2.e-4, c = 5.e-5
	real :: hl(n), z(0:n), wd(0:n)
	double precision :: d2(n)
	logical :: bz
	integer :: l, nfail, icase
	character(len=40) :: aname
	nfail = 0
	hl = (/ 1., 2., 4., 0.5, 3., 1.5 /)
	z(0) = 0.
	do l = 1,n
	  z(l) = z(l-1) + hl(l)
	end do
	do icase = 1,3
	  if( icase == 1 ) then
	    wd = a + b*z + c*z*z
	    aname = 'quadratic K, expected 2c = 1e-4'
	  else if( icase == 2 ) then
	    wd = a + b*z
	    aname = 'linear K, expected 0'
	  else
	    wd = a
	    aname = 'constant K, expected 0'
	  end if
	  call lgr_vdiff_curvature(n,hl,wd,d2,bz)
	  write(6,'(2x,a,a,6es11.3)') trim(aname),':',d2
	  do l = 1,n
	    if( icase == 1 ) then
	      if( abs(d2(l)-2.d0*c) > 1.d-3*2.d0*c ) nfail = nfail + 1
	    else if( icase == 2 ) then
	      if( abs(d2(l)) > 1.d-3*2.d0*c ) nfail = nfail + 1
	    else
	      if( d2(l) /= 0.d0 ) nfail = nfail + 1
	    end if
	  end do
	  if( bz ) nfail = nfail + 1
	end do
	! two layers: the interface 1, and the bottom one takes its value
	wd(0:2) = a + b*z(0:2) + c*z(0:2)**2
	call lgr_vdiff_curvature(2,hl(1:2),wd(0:2),d2(1:2),bz)
	write(6,'(2x,a,2es11.3)') 'two layers, quadratic K:',d2(1:2)
	if( abs(d2(1)-2.d0*c) > 1.d-3*2.d0*c .or. d2(2) /= d2(1) ) nfail = nfail + 1
	if( bz ) nfail = nfail + 1
	! a layer of zero thickness
	hl(3) = 0.
	call lgr_vdiff_curvature(n,hl,wd,d2,bz)
	write(6,'(2x,a,l2)') 'a layer of zero thickness: bzero',bz
	if( .not. bz ) nfail = nfail + 1
	if( any(d2 /= 0.d0) ) nfail = nfail + 1
	write(6,'(2x,a,i0)') 'failed checks: ',nfail
	if( nfail > 0 ) stop 1
	end program vcurv_test
EOF
    if ( cd "$W" && gfortran -ffpe-trap=zero,invalid,overflow -o vcurv_test vcurv_test.f90 vcurv.f90 > vcurv_build.log 2>&1 ); then
      ( cd "$W" && ./vcurv_test ) || fail "lgr_vdiff_curvature: wrong second derivatives"
    else
      fail "the test of lgr_vdiff_curvature does not compile"; sed 's/^/    /' "$W/vcurv_build.log" | head -5
    fi

    # the gradient term of the step (#286), cut out and compiled the same way
    echo "=== lgr_vdiff_gradstep on its own: linear K, constant K, a jump of K, a layer of zero thickness, one layer"
    awk '/^[ \t]*subroutine lgr_vdiff_gradstep/,/^[ \t]*end subroutine lgr_vdiff_gradstep/' "$SRCF" > "$W/vgrad.f90"
    if ! grep -q 'end subroutine lgr_vdiff_gradstep' "$W/vgrad.f90"; then
      fail "lgr_vdiff_gradstep not found in $SRCF"
    else
    cat > "$W/vgrad_test.f90" <<'EOF'
	program vgrad_test
! dtg = min over the layers of facg Kmin/K'**2, K' = (K(l)-K(l-1))/hl(l)
	implicit none
	real, parameter :: facg = 0.07
	real :: hl(6), z(0:6), wd(0:6), dtg, want
	integer :: l, nfail
	nfail = 0
	hl = (/ 1., 2., 4., 0.5, 3., 1.5 /)
	z(0) = 0.
	do l = 1,6
	  z(l) = z(l-1) + hl(l)
	end do
	! linear K: K' = 2e-3 everywhere, Kmin = 1e-3 at the top layer
	wd = 1.e-3 + 2.e-3*z
	dtg = 300.
	call lgr_vdiff_gradstep(6,hl,wd,facg,dtg)
	want = 17.5
	write(6,'(2x,a,2es13.5)') 'linear K, dtg and expected:',dtg,want
	if( abs(dtg-want) > 1.e-5*want ) nfail = nfail + 1
	! constant K: no gradient, the step is untouched
	wd = 1.e-3
	dtg = 300.
	call lgr_vdiff_gradstep(6,hl,wd,facg,dtg)
	write(6,'(2x,a,es13.5)') 'constant K, dtg:',dtg
	if( dtg /= 300. ) nfail = nfail + 1
	! a jump of K confined to layer 3
	wd = 1.e-3
	wd(3:6) = 5.e-2
	dtg = 300.
	call lgr_vdiff_gradstep(6,hl,wd,facg,dtg)
	want = real(0.07d0*1.d-3/((4.9d-2/4.d0)**2))
	write(6,'(2x,a,2es13.5)') 'a K jump in layer 3, dtg and expected:',dtg,want
	if( abs(dtg-want) > 1.e-5*want ) nfail = nfail + 1
	! a layer of zero thickness: layers (1, 2, 0, 3), no division by zero
	hl(1:4) = (/ 1., 2., 0., 3. /)
	z(0:4) = (/ 0., 1., 3., 3., 6. /)
	wd(0:4) = 1.e-3 + 2.e-3*z(0:4)
	dtg = 300.
	call lgr_vdiff_gradstep(4,hl(1:4),wd(0:4),facg,dtg)
	want = 17.5
	write(6,'(2x,a,2es13.5)') 'a layer of zero thickness, dtg and expected:',dtg,want
	if( abs(dtg-want) > 1.e-5*want ) nfail = nfail + 1
	! one layer
	wd(0:1) = (/ 1.e-3, 2.e-3 /)
	hl(1) = 2.
	dtg = 300.
	call lgr_vdiff_gradstep(1,hl(1:1),wd(0:1),facg,dtg)
	want = 280.
	write(6,'(2x,a,2es13.5)') 'lmax = 1, dtg and expected:',dtg,want
	if( abs(dtg-want) > 1.e-5*want ) nfail = nfail + 1
	write(6,'(2x,a,i0)') 'failed checks: ',nfail
	if( nfail > 0 ) stop 1
	end program vgrad_test
EOF
    if ( cd "$W" && gfortran -ffpe-trap=zero,invalid,overflow -o vgrad_test vgrad_test.f90 vgrad.f90 > vgrad_build.log 2>&1 ); then
      ( cd "$W" && ./vgrad_test ) || fail "lgr_vdiff_gradstep: wrong step"
    else
      fail "the test of lgr_vdiff_gradstep does not compile"; sed 's/^/    /' "$W/vgrad_build.log" | head -5
    fi
    fi
  fi

  # 2. a model run with the same diffusivity at every interface
  sed -e '/^\s*ztilt\s*=/d' -e '/^\s*ktilt\s*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e 's/^\(\s*\)mm_hyd_41\s*$/\1vdt_const/' \
      -e 's/^\(\s*\)iturb = 1 /\1iturb = 0 /' \
      -e 's/^\(\s*\)iturb = 0 .*/&\n\1diftur = 1.e-3   vistur = 1.e-3/' "$W/mm_hyd_41.str" > "$W/vdt_const.str"
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 20000\n        nbdy = 300  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = -1\n$end\n' "'1h'" >> "$W/vdt_const.str"
  for o in vdt_const 'iturb = 0' 'diftur = 1.e-3' 'ilagr = 3'; do
    grep -qF -- "$o" "$W/vdt_const.str" || fail "no '$o' in vdt_const.str"
  done
  grep -q "tilt" "$W/vdt_const.str" && fail "tilt lines left in vdt_const.str"
  echo "=== mm_hyd_41 (no tilt, one day, iturb = 0, diftur = 1.e-3 at every interface) with ilagr = 3, serially: K'' = 0 and K' = 0, so neither step rule (curvature, gradient) limits the step and the model step is taken"
  if run vdt_const vdt_const.log shyfem; then
    line="$(grep -m1 'lgr vertical diffusion: random walk time step' "$W/vdt_const.log")"
    echo "  ${line:-no line 'lgr vertical diffusion: random walk time step' in the log}"
    echo "$line" | grep -q 'min 300\.000* mean 300\.000*,' || fail "the random walk time step is not the model time step (300 s) everywhere"
    echo "$line" | grep -Eq ' below the model step 0( over 100 sub-steps 0)?$' || fail "element steps with a random walk time step below the model step"
    line="$(grep -m1 'lgr vertical diffusion step rule' "$W/vdt_const.log")"
    echo "  ${line:-no line 'lgr vertical diffusion step rule' in the log}"
    echo "$line" | grep -q 'gradient term set the step in 0 element steps, its floor 0.2 s in 0$' || fail "the gradient term set the step at a constant K"
  else
    fail "the run did not end"
  fi
  finish
fi

#=============================== walk-fold (#286, #287) ====================
if [ "$MODE" = walk-fold ]; then
  echo "=== lgr_walk_locate and lgr_walk_fold on their own: layers (1, 2, 0, 3) and (1, 2, 3, 0), every layer of zero thickness, depths from -3 H to 3 H"
  SRCF="$HERE/../../../src/shyfem/lagrange_dif.f90"
  if ! command -v gfortran > /dev/null 2>&1; then
    fail "gfortran is not on PATH"
  elif [ ! -f "$SRCF" ]; then
    fail "no $SRCF"
  else
    awk '/^[ \t]*subroutine lgr_walk_locate[(]/,/^[ \t]*end subroutine lgr_walk_locate[ \t]*$/' "$SRCF" > "$W/walk.f90"
    awk '/^[ \t]*subroutine lgr_walk_fold[(]/,/^[ \t]*end subroutine lgr_walk_fold[ \t]*$/' "$SRCF" >> "$W/walk.f90"
    nfound=0
    for r in lgr_walk_locate lgr_walk_fold; do
      if grep -q "end subroutine $r" "$W/walk.f90"; then
        nfound=$((nfound + 1))
      else
        fail "$r not found in $SRCF"
      fi
    done
    if [ "$nfound" = 2 ]; then
    cat > "$W/walk_test.f90" <<'EOF'
	program walk_test
! lgr_walk_fold (a depth d of any value folded into 0 ... H, then located)
! and lgr_walk_locate (the layer lb and relative depth z of a depth in 0
! ... H): the first layer of non-zero thickness whose bottom is at or
! below d, z = (d - top)/thickness, 0.5 if every layer has zero thickness
	implicit none
	real :: hl(4), hle(0:4), wd(0:4)
	real :: hs(50), he(0:50)
	double precision :: d, z, dd, zd, ak, zmax
	integer :: lb, nfail, i, nbad, icase, n, l, nraw
	nfail = 0
	! layers (1, 2, 0, 3) m: interfaces 0, 1, 3, 3, 6, H = 6
	hl = (/ 1., 2., 0., 3. /)
	hle = (/ 0., 1., 3., 3., 6. /)
	call cfold(2.5d0,2,0.75d0,'d = 2.5')
	call cfold(-0.5d0,1,0.5d0,'d = -0.5 (above the surface: 0.5)')
	call cfold(6.5d0,4,2.5d0/3.d0,'d = 6.5 (below the bed: 5.5)')
	call cfold(13.d0,1,1.d0,'d = 13 (13 mod 12 = 1)')
	call cfold(3.d0,2,1.d0,'d = 3 (above the zero layer)')
	call cfold(0.d0,1,0.d0,'d = 0 (the surface)')
	call cfold(6.d0,4,1.d0,'d = 6 (the bed)')
	call cloc(2.5d0,2,0.75d0,'locate d = 2.5')
	call cloc(3.d0,2,1.d0,'locate d = 3 (above the zero layer)')
	call cloc(0.d0,1,0.d0,'locate d = 0 (the surface)')
	call cloc(6.d0,4,1.d0,'locate d = 6 (the bed)')
	! the sweep: a layer of non-zero thickness, z in 0 ... 1, and the
	! depth of (lb, z) equal to the folded d
	nbad = 0
	do i = 0,2000
	  d = -18.d0 + 36.d0*i/2000.d0
	  call lgr_walk_fold(4,hl,hle,d,lb,z)
	  dd = modulo(d,12.d0)
	  if( dd > 6.d0 ) dd = 12.d0 - dd
	  if( lb < 1 .or. lb > 4 ) then
	    nbad = nbad + 1
	  else if( hl(lb) <= 0. ) then
	    nbad = nbad + 1
	  else if( z < 0.d0 .or. z > 1.d0 ) then
	    nbad = nbad + 1
	  else
	    zd = hle(lb-1) + z*hl(lb)
	    if( abs(zd-dd) > 1.d-9 ) nbad = nbad + 1
	  end if
	end do
	write(6,'(2x,a,i0)') 'sweep of 2001 depths from -18 to 18 m, wrong: ',nbad
	if( nbad > 0 ) nfail = nfail + 1
	! every layer of zero thickness, H = 0: lb = lmax, z = 0.5, no
	! division (the build traps zero, invalid)
	hl = 0.
	hle = 0.
	call cfold(0.7d0,4,0.5d0,'H = 0, d = 0.7')
	call cloc(0.d0,4,0.5d0,'H = 0, locate d = 0')
	! a bottom layer of zero thickness, layers (1, 2, 3, 0): interfaces 0,
	! 1, 3, 6, 6; d = 6 lies in layer 3 at z = 1, so the diffusivity
	! interpolated there as in lgr_diff_vert is K(3)
	hl = (/ 1., 2., 3., 0. /)
	hle = (/ 0., 1., 3., 6., 6. /)
	call cloc(6.d0,3,1.d0,'zero bottom layer, locate d = 6')
	call cfold(6.d0,3,1.d0,'zero bottom layer, d = 6')
	wd = (/ 1.e-3, 2.e-3, 5.e-3, 7.e-3, 9.e-3 /)
	call lgr_walk_locate(4,hl,hle,6.d0,lb,z)
	if( lb >= 1 .and. lb <= 4 ) then
	  ak = wd(lb-1) + z*(wd(lb)-wd(lb-1))
	  write(6,'(2x,a,es14.6,a,es14.6)') 'zero bottom layer, K at d = 6:'	&
     &		,ak,', expected K(3) =',dble(wd(3))
	  if( abs(ak-wd(3)) > 1.d-6*wd(3) ) nfail = nfail + 1
	end if
	! the interfaces as diff_body builds them, a single-precision running
	! sum: hle(l) - hle(l-1) can exceed hl(l), so at an interface, d =
	! hle(l), (d - hle(l-1))/hl(l) can exceed 1 by a rounding. The clamp
	! of lgr_walk_locate must keep z in 0 ... 1 (a real z of 1.000001 makes
	! track_xi stop the run) and lb must be l. nraw counts the interfaces
	! where the unclamped value exceeds 1: at least one, or the case no
	! longer tests the clamp
	do icase = 1,2
	  if( icase == 1 ) then
	    n = 4
	    hs(1:4) = (/ 0.1, 0.2, 0.3, 0.4 /)
	  else
	    n = 50
	    do l = 1,n
	      hs(l) = 0.1 + 0.01*l
	    end do
	  end if
	  he(0) = 0.
	  do l = 1,n
	    he(l) = he(l-1) + hs(l)
	  end do
	  nraw = 0
	  nbad = 0
	  zmax = 0.d0
	  do l = 0,n
	    if( l > 0 ) then
	      if( (dble(he(l))-he(l-1))/hs(l) > 1.d0 ) nraw = nraw + 1
	    end if
	    call lgr_walk_locate(n,hs(1:n),he(0:n),dble(he(l)),lb,z)
	    zmax = max(zmax,z)
	    if( z < 0.d0 .or. z > 1.d0 ) nbad = nbad + 1
	    if( lb /= max(l,1) ) nbad = nbad + 1
	  end do
	  write(6,'(2x,a,i0,a,i0,a,i0,a,es10.3)')				&
     &		'single-precision running sum of ',n			&
     &		,' layers, at every interface: unclamped value > 1 at ',nraw	&
     &		,', z outside 0 ... 1 or wrong layer at ',nbad		&
     &		,', max z - 1 ',zmax-1.d0
	  if( nbad > 0 ) nfail = nfail + 1
	  if( nraw == 0 ) nfail = nfail + 1
	end do
	write(6,'(2x,a,i0)') 'failed checks: ',nfail
	if( nfail > 0 ) stop 1
	contains
	subroutine cfold(dv,lbw,zw,text)
	double precision, intent(in) :: dv,zw
	integer, intent(in) :: lbw
	character(len=*), intent(in) :: text
	integer :: l
	double precision :: zz
	call lgr_walk_fold(4,hl,hle,dv,l,zz)
	call report(text,l,zz,lbw,zw)
	end subroutine cfold
	subroutine cloc(dv,lbw,zw,text)
	double precision, intent(in) :: dv,zw
	integer, intent(in) :: lbw
	character(len=*), intent(in) :: text
	integer :: l
	double precision :: zz
	call lgr_walk_locate(4,hl,hle,dv,l,zz)
	call report(text,l,zz,lbw,zw)
	end subroutine cloc
	subroutine report(text,l,zz,lbw,zw)
	character(len=*), intent(in) :: text
	integer, intent(in) :: l,lbw
	double precision, intent(in) :: zz,zw
	write(6,'(2x,a,a,i0,a,f10.6,a,i0,a,f10.6,a)') text,': lb ',l,' z '	&
     &		,zz,' (expected ',lbw,', ',zw,')'
	if( l /= lbw .or. abs(zz-zw) > 1.d-12 ) nfail = nfail + 1
	end subroutine report
	end program walk_test
EOF
    if ( cd "$W" && gfortran -fcheck=bounds -ffpe-trap=zero,invalid,overflow -o walk_test walk_test.f90 walk.f90 > walk_build.log 2>&1 ); then
      ( cd "$W" && ./walk_test ) || fail "lgr_walk_locate, lgr_walk_fold: wrong layer or relative depth"
    else
      fail "the test of lgr_walk_locate and lgr_walk_fold does not compile"; sed 's/^/    /' "$W/walk_build.log" | head -5
    fi
    fi
  fi
  finish
fi

#=============================== bed-w (#299) ==============================
if [ "$MODE" = bed-w ]; then
  echo "=== lgr_bed_move and lgr_bed_exit on their own: w(z) = wt (1 - z) - sv in the bottom layer, against RK4"
  SRCF="$HERE/../../../src/shyfem/lagrange_vertical.f90"
  if ! command -v gfortran > /dev/null 2>&1; then
    fail "gfortran is not on PATH"
  elif [ ! -f "$SRCF" ]; then
    fail "no $SRCF"
  else
    awk '/^[ \t]*subroutine lgr_bed_move[(]/,/^[ \t]*end subroutine lgr_bed_move[ \t]*$/' "$SRCF" > "$W/bed.f90"
    awk '/^[ \t]*subroutine lgr_bed_exit[(]/,/^[ \t]*end subroutine lgr_bed_exit[ \t]*$/' "$SRCF" >> "$W/bed.f90"
    nfound=0
    for r in lgr_bed_move lgr_bed_exit; do
      if grep -q "end subroutine $r" "$W/bed.f90"; then
        nfound=$((nfound + 1))
      else
        fail "$r not found in $SRCF"
      fi
    done
    if [ "$nfound" = 2 ]; then
    cat > "$W/bed_test.f90" <<'EOF'
	program bed_test
! lgr_bed_move and lgr_bed_exit (w(z) = wt (1 - z) - sv in the bottom
! layer, z = 0 at its top, 1 at the bed) against an RK4 integration of
! du/dt = (wt u - sv)/hd, u = 1 - z, with 10**5 steps
	implicit none
	double precision, parameter :: big = huge(1.d0)
	double precision :: z1, te, tw
	logical :: bup
	integer :: nfail
	nfail = 0
	! the measured tapered case: sv = 0, the bed is never reached
	call cmove(-1.d-4,0.d0,2.d0,0.3d0,3600.d0				&
     &		,'sv = 0, wt = -1e-4, z0 = 0.3, t = 3600 s')
	call cnever(-1.d-4,0.d0,2.d0,0.3d0,'sv = 0, wt = -1e-4, z0 = 0.3')
	! wt = 0: linear, the bed at hd (1 - z0)/sv exactly
	call cexit(0.d0,1.d-3,2.d0,0.3d0,.false.,'wt = 0, sv = 1e-3, z0 = 0.3')
	call lgr_bed_exit(0.d0,1.d-3,2.d0,0.3d0,te,bup)
	tw = 2.d0*(1.d0-0.3d0)/1.d-3
	write(6,'(2x,a,es23.15,a,es23.15)') 'wt = 0: texit',te		&
     &		,', hd (1 - z0)/sv',tw
	if( abs(te-tw) > 1.d-12*tw ) nfail = nfail + 1
	! equilibrium at u = sv/wt = 0.5: below it the bed, above it the top
	call cexit(2.d-4,1.d-4,2.d0,0.6d0,.false.				&
     &		,'wt = 2e-4, sv = 1e-4, z0 = 0.6 (below the equilibrium)')
	call cexit(2.d-4,1.d-4,2.d0,0.4d0,.true.				&
     &		,'wt = 2e-4, sv = 1e-4, z0 = 0.4 (above the equilibrium)')
	! wt < 0, sv > 0: the bed in finite time from any z0
	call cexit(-2.d-4,1.d-4,2.d0,0.d0,.false.,'wt = -2e-4, sv = 1e-4, z0 = 0')
	call cexit(-2.d-4,1.d-4,2.d0,0.3d0,.false.,'wt = -2e-4, sv = 1e-4, z0 = 0.3')
	call cexit(-2.d-4,1.d-4,2.d0,0.9d0,.false.,'wt = -2e-4, sv = 1e-4, z0 = 0.9')
	! a round-off wt: the linear answer (no division by wt)
	call cexit(1.d-18,3.d-5,2.d0,0.3d0,.false.,'wt = 1e-18, sv = 3e-5, z0 = 0.3')
	call lgr_bed_exit(1.d-18,3.d-5,2.d0,0.3d0,te,bup)
	tw = 2.d0*(1.d0-0.3d0)/3.d-5
	write(6,'(2x,a,es23.15,a,es23.15)') 'wt = 1e-18: texit',te	&
     &		,', linear',tw
	if( abs(te-tw) > 1.d-9*tw ) nfail = nfail + 1
	! a rising particle (sv < 0): the top; and one that approaches the
	! stable equilibrium u = sv/wt = 0.5 from below, never the top
	call cexit(-1.d-4,-3.d-4,2.d0,0.5d0,.true.,'wt = -1e-4, sv = -3e-4, z0 = 0.5')
	call cnever(-2.d-4,-1.d-4,2.d0,0.8d0,'wt = -2e-4, sv = -1e-4, z0 = 0.8')
	! the edge returns
	call cnever(2.d-4,0.d0,2.d0,1.d0,'on the bed, sv = 0, wt = 2e-4')
	call cnever(2.d-4,1.d-4,2.d0,0.5d0,'at the equilibrium u = sv/wt = 0.5')
	call lgr_bed_move(2.d-4,1.d-4,2.d0,0.5d0,3600.d0,z1)
	write(6,'(2x,a,f20.17)') 'at the equilibrium, z after 3600 s:',z1
	if( z1 /= 0.5d0 ) nfail = nfail + 1
	call lgr_bed_move(2.d-4,0.d0,2.d0,1.d0,3600.d0,z1)
	write(6,'(2x,a,f20.17)') 'on the bed, sv = 0, z after 3600 s:',z1
	if( z1 /= 1.d0 ) nfail = nfail + 1
	call czero(2.d-4,1.d-4,2.d0,1.d0,.false.,'on the bed, sv = 1e-4, wt = 2e-4')
	call czero(0.d0,1.d-4,2.d0,1.d0,.false.,'on the bed, sv = 1e-4, wt = 0')
	call czero(-2.d-4,1.d-4,2.d0,1.d0,.false.,'on the bed, sv = 1e-4, wt = -2e-4')
	call czero(2.d-4,1.d-4,2.d0,0.d0,.true.,'at the top, wt = 2e-4, sv = 1e-4')
	! a layer of zero thickness: no motion, no division
	call lgr_bed_move(-1.d-4,1.d-4,0.d0,0.3d0,3600.d0,z1)
	call lgr_bed_exit(-1.d-4,1.d-4,0.d0,0.3d0,te,bup)
	write(6,'(2x,a,f20.17,a,l2)') 'hd = 0: z after 3600 s',z1		&
     &		,', texit huge',te == big
	if( z1 /= 0.3d0 ) nfail = nfail + 1
	if( te /= big ) nfail = nfail + 1
	write(6,'(2x,a,i0)') 'failed checks: ',nfail
	if( nfail > 0 ) stop 1
	contains
	double precision function rk4(wt,sv,hd,u0,t)
	double precision, intent(in) :: wt,sv,hd,u0,t
	integer, parameter :: n = 100000
	integer :: i
	double precision :: h,u,k1,k2,k3,k4
	h = t/n
	u = u0
	do i = 1,n
	  k1 = (wt*u-sv)/hd
	  k2 = (wt*(u+0.5d0*h*k1)-sv)/hd
	  k3 = (wt*(u+0.5d0*h*k2)-sv)/hd
	  k4 = (wt*(u+h*k3)-sv)/hd
	  u = u + h*(k1+2.d0*k2+2.d0*k3+k4)/6.d0
	end do
	rk4 = u
	end function rk4
	subroutine cmove(wt,sv,hd,z0,t,text)
	! lgr_bed_move against RK4 after the time t
	double precision, intent(in) :: wt,sv,hd,z0,t
	character(len=*), intent(in) :: text
	double precision :: z,zr
	call lgr_bed_move(wt,sv,hd,z0,t,z)
	zr = 1.d0 - rk4(wt,sv,hd,1.d0-z0,t)
	write(6,'(2x,a,a,f12.9,a,f12.9,a,es9.2)') text,': z ',z,', RK4 ',zr	&
     &		,', diff ',abs(z-zr)
	if( .not. abs(z-zr) <= 1.d-7 ) nfail = nfail + 1
	end subroutine cmove
	subroutine cexit(wt,sv,hd,z0,bupw,text)
	! a finite exit time to the top (bupw) or the bed: RK4 is there at
	! that time, so is lgr_bed_move; halfway they agree
	double precision, intent(in) :: wt,sv,hd,z0
	logical, intent(in) :: bupw
	character(len=*), intent(in) :: text
	double precision :: t,z,zr,zw
	logical :: bu
	call lgr_bed_exit(wt,sv,hd,z0,t,bu)
	zw = 1.d0
	if( bupw ) zw = 0.d0
	if( t == big .or. .not. t > 0.d0 .or. (bu .neqv. bupw) ) then
	  write(6,'(2x,a,a,es12.4,a,l2,a,l2)') text,': texit',t,', top',bu	&
     &		,', expected a finite time, top',bupw
	  nfail = nfail + 1
	  return
	end if
	call lgr_bed_move(wt,sv,hd,z0,t,z)
	zr = 1.d0 - rk4(wt,sv,hd,1.d0-z0,t)
	write(6,'(2x,a,a,f12.3,a,l2,a,f12.9,a,f12.9,a,f4.1)') text		&
     &		,': texit',t,', top',bu,', z then ',z,', RK4 ',zr,', expected',zw
	if( .not. abs(z-zw) <= 1.d-9 ) nfail = nfail + 1
	if( .not. abs(zr-zw) <= 1.d-7 ) nfail = nfail + 1
	call cmove(wt,sv,hd,z0,0.5d0*t,'  halfway')
	end subroutine cexit
	subroutine cnever(wt,sv,hd,z0,text)
	! never at the top or the bed: huge; after 3600 s lgr_bed_move as RK4
	double precision, intent(in) :: wt,sv,hd,z0
	character(len=*), intent(in) :: text
	double precision :: t
	logical :: bu
	call lgr_bed_exit(wt,sv,hd,z0,t,bu)
	write(6,'(2x,a,a,l2)') text,': texit huge',t == big
	if( t /= big ) nfail = nfail + 1
	call cmove(wt,sv,hd,z0,3600.d0,'  after 3600 s')
	end subroutine cnever
	subroutine czero(wt,sv,hd,z0,bupw,text)
	! on a boundary, moving out: 0, to the top (bupw) or the bed
	double precision, intent(in) :: wt,sv,hd,z0
	logical, intent(in) :: bupw
	character(len=*), intent(in) :: text
	double precision :: t
	logical :: bu
	call lgr_bed_exit(wt,sv,hd,z0,t,bu)
	write(6,'(2x,a,a,es10.3,a,l2,a,l2,a)') text,': texit',t,', top',bu	&
     &		,' (expected 0,',bupw,')'
	if( t /= 0.d0 .or. (bu .neqv. bupw) ) nfail = nfail + 1
	end subroutine czero
	end program bed_test
EOF
    if ( cd "$W" && gfortran -fcheck=bounds -ffpe-trap=zero,invalid,overflow -o bed_test bed_test.f90 bed.f90 > bed_build.log 2>&1 ); then
      ( cd "$W" && ./bed_test ) || fail "lgr_bed_move, lgr_bed_exit: wrong relative depth or exit time"
    else
      fail "the test of lgr_bed_move and lgr_bed_exit does not compile"; sed 's/^/    /' "$W/bed_build.log" | head -5
    fi
    fi
  fi
  finish
fi

#=============================== node-sink (#310) ==========================
if [ "$MODE" = node-sink ]; then
  echo "=== track_xi_node_sink on its own: a sink is d_end < 1e-3 and d_end <= d_start, or d_end < 1e-15"
  SRCF="$HERE/../../../src/shyfem/lagrange_vertical.f90"
  if ! command -v gfortran > /dev/null 2>&1; then
    fail "gfortran is not on PATH"
  elif [ ! -f "$SRCF" ]; then
    fail "no $SRCF"
  else
    awk '/^[ \t]*logical function track_xi_node_sink[(]/,/^[ \t]*end function track_xi_node_sink[ \t]*$/' "$SRCF" > "$W/sink.f90"
    if ! grep -q "end function track_xi_node_sink" "$W/sink.f90"; then
      fail "track_xi_node_sink not found in $SRCF"
    else
    cat > "$W/sink_test.f90" <<'EOF'
	program sink_test
! track_xi_node_sink (#310): d = the sum of the two smallest internal
! coordinates (the distance from the nearest vertex) at the start of the
! step (xis) and at the end of the crossings (xie); a sink is d_end <
! 1e-3 and d_end <= d_start, or d_end < 1e-15. Each case with the node at
! each of the three vertices at the start and at the end (9 orders)
	implicit none
	integer :: nfail,ncase
	nfail = 0
	ncase = 0
	! a sink: the trace of part 1 of check_lgr_bed.sh (id 17673)
	call c((/1.d0-3.5d-3,2.0d-3,1.5d-3/),(/1.d0-2.7d-14,1.5d-14,1.2d-14/)	&
     &		,.true.,'sink, 3.5e-3 to 2.7e-14')
	! a weak sink (about x0.75 per turn, still 1.2e-6 away after 100
	! crossings: two coordinates below 1e-6, the first prototype, miss it)
	call c((/1.d0-4.d-4,2.5d-4,1.5d-4/),(/1.d0-1.2d-6,1.1d-6,0.1d-6/)	&
     &		,.true.,'weak sink, 4e-4 to 1.2e-6')
	! a sink entered from far in the step
	call c((/0.3d0,0.3d0,0.4d0/),(/1.d0-1.d-10,0.6d-10,0.4d-10/)		&
     &		,.true.,'sink from far, 0.6 to 1e-10')
	! no larger than at the start: a sink
	call c((/1.d0-5.d-4,3.d-4,2.d-4/),(/1.d0-5.d-4,2.d-4,3.d-4/)		&
     &		,.true.,'sink reached exactly, 5e-4 to 5e-4')
	! the floating-point floor, where the spiral stops shrinking
	call c((/0.d0,1.d0-1.d-16,1.d-16/),(/0.d0,1.d0-5.d-16,5.d-16/)	&
     &		,.true.,'the floor, 1e-16 to 5e-16')
	! sources: the restart point of the Venice particle (vl1, id 1356),
	! which spirals out
	call c((/0.d0,0.99999999999999289d0,7.105d-15/)			&
     &		,(/1.d0-2.9d-14,2.0d-14,0.9d-14/)				&
     &		,.false.,'source, 7.105e-15 to 2.9e-14')
	call c((/0.d0,0.99999999999999289d0,7.105d-15/)			&
     &		,(/1.d0-2.5d-5,1.5d-5,1.0d-5/)				&
     &		,.false.,'source, 7.105e-15 to 2.5e-5')
	call c((/0.d0,1.d0-1.d-16,1.d-16/),(/0.d0,1.d0-2.d-15,2.d-15/)	&
     &		,.false.,'above the floor, 1e-16 to 2e-15')
	! far from a vertex, also when converging
	call c((/0.4d0,0.3d0,0.3d0/),(/0.2d0,0.3d0,0.5d0/)			&
     &		,.false.,'far, 0.6 to 0.5')
	call c((/0.3d0,0.4d0,0.3d0/),(/1.d0-1.5d-3,1.d-3,0.5d-3/)		&
     &		,.false.,'far, 0.6 to 1.5e-3')
	! near a side, not a vertex: one coordinate small
	call c((/0.3d0,0.3d0,0.4d0/),(/1.d-12,0.4d0,0.6d0-1.d-12/)		&
     &		,.false.,'near a side, 0.6 to 0.4')
	write(6,'(2x,a,i0,a,i0)') 'cases ',ncase,', failed checks: ',nfail
	if( nfail > 0 ) stop 1
	contains
	subroutine c(xis,xie,bwant,text)
	! the 9 orders of the coordinates of xis and xie
	double precision, intent(in) :: xis(3),xie(3)
	logical, intent(in) :: bwant
	character(len=*), intent(in) :: text
	logical, external :: track_xi_node_sink
	double precision :: as(3),ae(3),ds,de
	integer :: is,ie,nbad
	! d at the start and at the end, shown (the sum of the two smallest)
	ds = min(xis(1)+xis(2),xis(2)+xis(3),xis(1)+xis(3))
	de = min(xie(1)+xie(2),xie(2)+xie(3),xie(1)+xie(3))
	nbad = 0
	do is = 0,2
	  as = cshift(xis,is)
	  do ie = 0,2
	    ae = cshift(xie,ie)
	    if( track_xi_node_sink(as,ae) .neqv. bwant ) nbad = nbad + 1
	  end do
	end do
	ncase = ncase + 1
	nfail = nfail + nbad
	write(6,'(2x,a,a,es9.2,a,es9.2,a,l2,a,l2,a,i0,a)') text		&
     &		,': d',ds,' to',de,', sink',bwant .neqv. nbad > 0		&
     &		,' (expected',bwant,'; ',9-nbad,' of 9 orders)'
	end subroutine c
	end program sink_test
EOF
    if ( cd "$W" && gfortran -fcheck=bounds -ffpe-trap=zero,invalid,overflow -o sink_test sink_test.f90 sink.f90 > sink_build.log 2>&1 ); then
      ( cd "$W" && ./sink_test ) || fail "track_xi_node_sink: a sink or a source told wrongly"
    else
      fail "the test of track_xi_node_sink does not compile"; sed 's/^/    /' "$W/sink_build.log" | head -5
    fi
    fi
  fi
  finish
fi

#=============================== node-sink-run (#310) ======================
if [ "$MODE" = node-sink-run ]; then
  # the closed forced mm_hyd_41 of check_lgr_bed.sh part 1 with 100
  # surface particles released at 16:30 around node 702
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1ns_t1/" \
      -e 's/^\([[:space:]]*\)ibtyp = [13][[:space:]]*$/\1ibtyp = 0/' "$W/mm_hyd_41.str" > "$W/ns_t1.str"
  printf '\n$lagrg\n        ilagr = 1   nbdymax = 5000\n        nbdy = 100  idtl = 0  idtlgr = %s\n        itlanf = %s\n        lgrlin = %s\n        rwhpar = 0  ipvert = 5\n        lgrseed = 1\n$end\n' \
      "'1h'" "'2009-01-01::16:30:00'" "'node702.txt'" >> "$W/ns_t1.str"
  printf '695355.0 4185998.0 1\n695755.0 4185998.0 0\n695755.0 4186398.0 0\n695355.0 4186398.0 0\n695355.0 4185998.0 0\n' > "$W/node702.txt"
  with_para ns_t1 ns_t4 "nomp = 4"
  sed "s/^\([[:space:]]*\)ns_t1[[:space:]]*\$/\1ns_np/" "$W/ns_t1.str" > "$W/ns_np.str"
  grep -q "^[[:space:]]*ns_np[[:space:]]*\$" "$W/ns_np.str" || fail "ns_np.str: run name not set"
  for o in "itend = '2009-01-02'" 'ilagr = 1' "itlanf = '2009-01-01::16:30:00'" "lgrlin = 'node702.txt'" \
           'rwhpar = 0' "wind='INPUT/wind09.txt'" "gotmpa = 'INPUT/gotmturb.nml'"; do
    grep -qF -- "$o" "$W/ns_t1.str" || fail "no '$o' in ns_t1.str"
  done
  [ "$(grep -c 'ibtyp = 0' "$W/ns_t1.str")" = 2 ] || fail "ns_t1.str: the boundaries are not both closed (ibtyp = 0)"
  grep -q 'tilt' "$W/ns_t1.str" && fail "tilt lines left in ns_t1.str"
  grep -q "^[[:space:]]*ns_t1[[:space:]]*\$" "$W/ns_t1.str" || fail "ns_t1.str: run name not set"
  grep -q "nomp = 4" "$W/ns_t4.str" || fail "ns_t4.str: no 'nomp = 4'"
  [ "$rc" = 0 ] || finish
  echo "=== the closed forced mm_hyd_41, ilagr = 1, 100 particles around node 702 at 16:30: 1 and 4 threads serially, on $NP processes"
  run ns_t1 ns_t1.log shyfem || fail "ns_t1: the run did not end"
  run ns_t4 ns_t4.log shyfem || fail "ns_t4: the run did not end"
  run ns_np ns_np.log mpirun --oversubscribe -np $NP shyfem || fail "ns_np: the run did not end"
  threads ns_t1.log 1
  threads ns_t4.log 4
  tags="ns_t1 ns_t4 ns_np"
  if [ -n "$REF" ]; then
    # the same STR files, in a folder of their own (ref)
    mkdir "$W/ref" && ln -s "$W/GRID" "$W/ref/GRID" && ln -s "$W/INPUT" "$W/ref/INPUT" \
      && cp "$W/ns_t1.str" "$W/ns_np.str" "$W/node702.txt" "$W/ref/" || { fail "cannot make the folder of the reference runs"; finish; }
    echo "=== the same with the reference binary $REF/shyfem: serially and on $NP processes (in $W/ref)"
    W0="$W"; W="$W0/ref"
    run ns_t1 ns_t1.log "$REF/shyfem" || fail "ref/ns_t1: the run did not end"
    run ns_np ns_np.log mpirun --oversubscribe -np $NP "$REF/shyfem" || fail "ref/ns_np: the run did not end"
    W="$W0"
    tags="$tags ref/ns_t1 ref/ns_np"
    for v in t1 np; do
      for f in lgr.shy hydro.shy inf; do
        a="$W/ref/ns_$v.$f"; b="$W/ns_$v.$f"
        if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$v: .$f missing"
        elif cmp -s "$a" "$b"; then echo "  $v: .$f identical to the reference binary's ($(stat -c %s "$b") bytes)"
        else fail "$v: .$f differs from the reference binary's"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
        fi
      done
    done
  else
    echo "  (no REF_BIN_DIR: the comparison with a reference binary is skipped)"
  fi
  a="$W/ns_t1.lgr.shy"; b="$W/ns_t4.lgr.shy"
  if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "particle file of 1 or 4 threads missing"
  elif cmp -s "$a" "$b"; then echo "  particle file of 4 threads identical to 1 thread ($(stat -c %s "$a") bytes)"
  else fail "particle file of 4 threads differs from 1 thread"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
  fi
  [ "$rc" = 0 ] || finish
  PYTHONDONTWRITEBYTECODE=1 python3 - "$W" $tags <<'EOF' || fail "see above"
import os, re, sys

w, tags = sys.argv[1], sys.argv[2:]
ok = True
def bad(msg):
    global ok
    print("  FAIL: " + msg)
    ok = False

CROSS = "element crossings used up with time left"
SINK = "stopped at a node the layer flow converges on (node sink) with time left"
HOLD = "all the time left spent moving off a vertex (vertex hold)"	# #316
HOLD_EXPECT = 1599	# events in the run, measured (see the head of this script)
HOLD_NODE = "702"
HEAD = r"^ lgr advection:(?: rank (?P<rank>\d+):)? "
TAIL = (r": (?P<n>\d+) in the step to (?P<t>\S+?), (?P<ntot>\d+) in the run \([\d.]+ events per 100"
        r" of the \d+ particles released\); first: id (?P<id>\d+), element (?P<el>-?\d+), %s (?P<v3>-?\d+),"
        r" time left \[s\] (?P<tl>\S+)$")
RX = {CROSS: re.compile(HEAD + re.escape(CROSS) + TAIL % "crossings left"),
      SINK: re.compile(HEAD + re.escape(SINK) + TAIL % "layer"),
      HOLD: re.compile(HEAD + re.escape(HOLD)
                       + r": (?P<n>\d+) in the step to (?P<t>\S+?), (?P<ntot>\d+) in the run \([\d.]+ events per"
                       r" 100 of the \d+ particles released\); first: id (?P<id>\d+), element (?P<el>-?\d+),"
                       r" layer (?P<v3>-?\d+), node (?P<node>\d+), time spent \[s\] (?P<tl>\S+)$")}

def lines(tag, text):
    """the lines of the kind text in TAG.log: (rank, time) -> match"""
    with open(os.path.join(w, tag + ".log"), errors="replace") as fh:
        log = fh.read().split("\n")
    out, nbad = {}, 0
    for l in log:
        if text not in l:
            continue
        m = RX[text].match(l)
        if not m:
            nbad += 1
            if nbad <= 2:
                bad("%s: a line of '%s' not as documented: %r" % (tag, text, l))
            continue
        key = (m.group("rank"), m.group("t"))
        if key in out:
            bad("%s: two lines of '%s' for rank %s in the step to %s" % (tag, text, key[0], key[1]))
        out[key] = m
    # the count in the run is the sum of the counts so far, per rank
    tot = {}
    for (r, t), m in out.items():		# in the order of the log
        tot[r] = tot.get(r, 0) + int(m.group("n"))
        if int(m.group("ntot")) != tot[r]:
            bad("%s: '%s' rank %s at %s: %s in the run, the counts so far sum to %d"
                % (tag, text, r, t, m.group("ntot"), tot[r]))
    return out

def per_step(d):
    """events of each step summed over the ranks"""
    s = {}
    for (_, t), m in d.items():
        s[t] = s.get(t, 0) + int(m.group("n"))
    return s

L = {tag: (lines(tag, CROSS), lines(tag, SINK)) for tag in tags}
H = {tag: lines(tag, HOLD) for tag in tags}		# #316
for tag in tags:
    c, s = L[tag]
    print("  %s: lines '%s' %d (%d in the run), node-sink lines %d (%d in the run), vertex-hold lines %d (%d in"
          " the run)" % (tag, CROSS, len(c), sum(per_step(c).values()), len(s), sum(per_step(s).values()),
                         len(H[tag]), sum(per_step(H[tag]).values())))
# the vertex hold (#316): every run, its count, its values; 4 threads and 4
# processes as 1 thread
for tag in ("ns_t1", "ns_t4", "ns_np"):
    h = H[tag]
    nh = sum(per_step(h).values())
    if nh != HOLD_EXPECT:
        bad("%s: %d vertex-hold events in the run ('%s'), expected %d" % (tag, nh, HOLD, HOLD_EXPECT))
    for (r, t), m in h.items():
        if int(m.group("v3")) < 1 or not float(m.group("tl")) > 0.0 or int(m.group("id")) < 1 \
                or int(m.group("el")) < 1 or m.group("node") != HOLD_NODE:
            bad("%s: vertex-hold line at %s: id %s, element %s, layer %s, node %s, time spent %s; expected id,"
                " element and layer >= 1, node %s and time spent > 0" % (tag, t, m.group("id"), m.group("el"),
                m.group("v3"), m.group("node"), m.group("tl"), HOLD_NODE))
        if tag != "ns_np" and r is not None:
            bad("%s: a serial vertex-hold line with rank %s" % (tag, r))
if [m.group(0) for m in H["ns_t4"].values()] != [m.group(0) for m in H["ns_t1"].values()]:
    bad("the vertex-hold lines of 4 threads differ from those of 1 thread")
if per_step(H["ns_np"]) != per_step(H["ns_t1"]):
    bad("ns_np: the vertex-hold events of a step summed over the ranks differ from the serial ones")
for tag in ("ns_t1", "ns_t4", "ns_np"):
    c, s = L[tag]
    if c:
        bad("%s: %d lines '%s', expected none (the particles of this case converge onto node 702)" % (tag, len(c), CROSS))
    if not s:
        bad("%s: no node-sink line" % tag)
    for (r, t), m in s.items():
        if int(m.group("v3")) < 1 or not float(m.group("tl")) > 0.0 or int(m.group("id")) < 1 or int(m.group("el")) < 1:
            bad("%s: node-sink line at %s: id %s, element %s, layer %s, time left %s; expected id, element and"
                " layer >= 1 and time left > 0" % (tag, t, m.group("id"), m.group("el"), m.group("v3"), m.group("tl")))
        if tag != "ns_np" and r is not None:
            bad("%s: a serial line with rank %s" % (tag, r))
s1 = L["ns_t1"][1]
if [m.group(0) for m in L["ns_t4"][1].values()] != [m.group(0) for m in s1.values()]:
    bad("the node-sink lines of 4 threads differ from those of 1 thread")
if per_step(L["ns_np"][1]) != per_step(s1):
    bad("ns_np: the node-sink events of a step summed over the ranks differ from the serial ones")
if "ref/ns_t1" in L:
    for mine, ref in (("ns_t1", "ref/ns_t1"), ("ns_np", "ref/ns_np")):
        rc_, rs = L[ref]
        if rs and not rc_:
            # a reference with #310: the node-sink lines are this binary's,
            # step by step; its vertex-hold lines (a build with #316) too,
            # and none in a build without #316 (#316)
            hr, hm = H[ref], H[mine]
            if hr:
                hkeys = ("n", "ntot", "id", "el", "v3", "node", "tl")
                if sorted(hm) != sorted(hr) or any([hm[k].group(g) for g in hkeys] != [hr[k].group(g) for g in hkeys]
                                                   for k in hr):
                    bad("%s: the vertex-hold lines differ from those of the reference %s (a build with #316)"
                        % (mine, ref))
                else:
                    print("  %s: the vertex-hold lines are those of the reference (a build with #316), step by step"
                          " (%d lines)" % (mine, len(hm)))
            else:
                print("  %s: the reference writes no vertex-hold line (a build without #316)" % ref)
            ms = L[mine][1]
            keys = ("n", "ntot", "id", "el", "v3", "tl")
            if sorted(ms) != sorted(rs) or any([ms[k].group(g) for g in keys] != [rs[k].group(g) for g in keys]
                                               for k in rs):
                bad("%s: the node-sink lines differ from those of the reference %s" % (mine, ref))
            else:
                print("  %s: the node-sink lines are those of the reference (a build with #310), step by step"
                      " (%d lines)" % (mine, len(ms)))
            continue
        if not rc_:
            bad("%s: no line '%s': the case no longer reaches the trap" % (ref, CROSS))
        if rs:
            bad("%s: node-sink lines in the reference run (a binary with #310?)" % ref)
        ms = L[mine][1]
        if sorted(ms) != sorted(rc_):
            bad("%s: node-sink lines at (rank, step) %s, the reference's '%s' at %s"
                % (mine, sorted(ms)[:4], CROSS, sorted(rc_)[:4]))
            continue
        nd = 0
        for k in rc_:
            a, b = rc_[k], ms[k]
            if [a.group(g) for g in ("n", "ntot", "id", "el", "tl")] != [b.group(g) for g in ("n", "ntot", "id", "el", "tl")]:
                nd += 1
                if nd <= 2:
                    bad("%s at %s: %r, the reference: %r" % (mine, k, b.group(0), a.group(0)))
        if nd == 0:
            print("  %s: the node-sink lines are the reference's lines '%s', step by step (%d lines)"
                  % (mine, CROSS, len(ms)))
sys.exit(0 if ok else 1)
EOF
  [ "$rc" = 0 ] && [ -z "$REF" ] && echo "  (PASS without the comparison with a reference binary: give REF_BIN_DIR for it)"
  finish
fi

#=============================== cross-budget (#315) =======================
if [ "$MODE" = cross-budget ]; then
  # venlag_smoke until 03:32, 50 surface particles released at 03:00 around
  # node 392 (Venice lagoon)
  VEN="$HERE/../venice_lagoon"
  for f in GRID/venlag62.grd INPUT venlag_smoke.str; do
    [ -e "$VEN/$f" ] || { fail "$VEN/$f is missing"; finish; }
  done
  command -v shypre > /dev/null 2>&1 || { fail "shypre is not on PATH"; finish; }
  V="$SCR/ven"
  mkdir -p "$V/GRID" && cp "$VEN/GRID/venlag62.grd" "$V/GRID/" && ln -s "$VEN/INPUT" "$V/INPUT" \
    || { fail "cannot make the folder of the Venice runs"; finish; }
  ( cd "$V/GRID" && shypre venlag62.grd > shypre.log 2>&1 ) && [ -s "$V/GRID/venlag62.bas" ] \
    || { fail "shypre venlag62.grd failed ($V/GRID/shypre.log)"; finish; }
  sed -e "s/itend  = '2014-08-01::06:00'/itend  = '2014-08-01::03:32'/" \
      -e "s/^\([[:space:]]*\)venlag_smoke[[:space:]]*\$/\1cb_t1/" "$VEN/venlag_smoke.str" > "$V/cb_t1.str"
  printf '\n$lagrg\n        ilagr = 1   nbdymax = 1000\n        nbdy = 50  idtl = 0  idtlgr = 60\n        itlanf = %s\n        lgrlin = %s\n        rwhpar = 0\n        lgrseed = 1\n$end\n' \
      "'2014-08-01::03:00:00'" "'node392.txt'" >> "$V/cb_t1.str"
  printf '26698.2 11387.6 1\n26718.2 11387.6 0\n26718.2 11407.6 0\n26698.2 11407.6 0\n26698.2 11387.6 0\n' > "$V/node392.txt"
  sed "s/^\([[:space:]]*\)cb_t1[[:space:]]*\$/\1cb_np/" "$V/cb_t1.str" > "$V/cb_np.str"
  for o in "itend  = '2014-08-01::03:32'" 'ilagr = 1' "itlanf = '2014-08-01::03:00:00'" "lgrlin = 'node392.txt'"; do
    grep -qF -- "$o" "$V/cb_t1.str" || fail "no '$o' in cb_t1.str"
  done
  grep -q "^[[:space:]]*cb_t1[[:space:]]*\$" "$V/cb_t1.str" || fail "cb_t1.str: run name not set"
  grep -q "^[[:space:]]*cb_np[[:space:]]*\$" "$V/cb_np.str" || fail "cb_np.str: run name not set"
  [ "$rc" = 0 ] || finish
  echo "=== venlag_smoke until 03:32, 50 particles released at 03:00 around node 392: serially and on $NP processes"
  W0="$W"; W="$V"
  run cb_t1 cb_t1.log shyfem || fail "cb_t1: the run did not end"
  run cb_np cb_np.log mpirun --oversubscribe -np $NP shyfem || fail "cb_np: the run did not end"
  W="$W0"
  a="$V/cb_t1.lgr.shy"; b="$V/cb_np.lgr.shy"
  if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "particle file serially or on $NP processes missing"
  elif cmp -s "$a" "$b"; then echo "  particle file on $NP processes identical to the serial one ($(stat -c %s "$a") bytes)"
  else fail "particle file on $NP processes differs from the serial one"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
  fi
  [ "$rc" = 0 ] || finish
  PYTHONDONTWRITEBYTECODE=1 python3 - "$V" "$W" <<'EOF' || fail "see above"
import os, re, struct, sys

v, w = sys.argv[1], sys.argv[2]
sys.path.insert(0, w)
import lgr_compare as lc

ok = True
def bad(msg):
    global ok
    print("  FAIL: " + msg)
    ok = False

CB_CROSS, CB_SINK, CB_HOLD, CB_NODE = 24, 136, 91, 392	# measured 2026-11-28
CB_LASTSTEP = "2014-08-01::03:27:15"
CROSS = "element crossings used up with time left"
SINK = "stopped at a node the layer flow converges on (node sink) with time left"
HOLD = "all the time left spent moving off a vertex (vertex hold)"
HEAD = r"^ lgr advection:(?: rank (?P<rank>\d+):)? "
STEP = r": (?P<n>\d+) in the step to (?P<t>\S+?), (?P<ntot>\d+) in the run "
RXC = re.compile(HEAD + re.escape(CROSS) + STEP + r"\([\d.]+ events per 100 of the \d+ particles"
                 r" released\); first: id (?P<id>\d+), element (?P<el>-?\d+), crossings left (?P<nl>-?\d+),"
                 r" time left \[s\] (?P<tl>\S+)$")

def kind(tag, text, rx=None):
    """(rank, step) -> match of the lines of kind text in TAG.log"""
    out = {}
    with open(os.path.join(v, tag + ".log"), errors="replace") as fh:
        for l in fh:
            if text not in l:
                continue
            m = (rx or re.compile(HEAD + re.escape(text) + STEP)).match(l)
            if not m:
                bad("%s: a line of '%s' not as documented: %r" % (tag, text, l.rstrip()))
                continue
            out[(m.group("rank"), m.group("t"))] = m
    return out

def per_step(d):
    s = {}
    for (_, t), m in d.items():
        s[t] = s.get(t, 0) + int(m.group("n"))
    return s

res = {}
for tag in ("cb_t1", "cb_np"):
    c, s_, h = kind(tag, CROSS, RXC), kind(tag, SINK), kind(tag, HOLD)
    res[tag] = (c, s_, h)
    nc, ns, nh = (sum(per_step(d).values()) for d in (c, s_, h))
    print("  %s: '%s' %d (%d lines), node sink %d, vertex hold %d" % (tag, CROSS, nc, len(c), ns, nh))
    if nc != CB_CROSS:
        bad("%s: %d events '%s' in the run, expected %d (the code before #315: 101)" % (tag, nc, CROSS, CB_CROSS))
    if ns != CB_SINK:
        bad("%s: %d node-sink events, expected %d (as before #315)" % (tag, ns, CB_SINK))
    if nh != CB_HOLD:
        bad("%s: %d vertex-hold events, expected %d (as before #315)" % (tag, nh, CB_HOLD))
    for (r, t), m in c.items():
        if int(m.group("nl")) != 0 or not float(m.group("tl")) > 0.0 or int(m.group("id")) < 1:
            bad("%s: line '%s' at %s: crossings left %s, time left %s, id %s" % (tag, CROSS, t, m.group("nl"),
                m.group("tl"), m.group("id")))
        if t > CB_LASTSTEP:
            bad("%s: a line '%s' in the step to %s, after %s: a particle still used up its crossings"
                % (tag, CROSS, t, CB_LASTSTEP))
        if tag == "cb_t1" and r is not None:
            bad("%s: a serial line with rank %s" % (tag, r))
for i in range(3):
    if per_step(res["cb_np"][i]) != per_step(res["cb_t1"][i]):
        bad("cb_np: the events '%s' of a step summed over the ranks differ from the serial ones"
            % (CROSS, SINK, HOLD)[i])

# no particle exactly on node 392 at the last output
xn = yn = None
with open(os.path.join(v, "GRID", "venlag62.grd")) as fh:
    for l in fh:
        p = l.split()
        if len(p) >= 5 and p[0] == "1" and p[1] == str(CB_NODE):
            xn, yn = float(p[3]), float(p[4])
            break
if xn is None:
    bad("node %d not found in venlag62.grd" % CB_NODE)
else:
    f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
    _, recs = lc.read_file(os.path.join(v, "cb_t1.lgr.shy"))
    t_last, blocks, _ = recs[-1]
    on = sorted(k for k, q in blocks[0].items() if f32(q["x"]) == f32(xn) and f32(q["y"]) == f32(yn))
    print("  cb_t1: last output %s, %d particles in it, on node %d: %d %s" % (t_last, len(blocks[0]),
          CB_NODE, len(on), on))
    if on:
        bad("cb_t1: %d particles exactly on node %d at the last output (the code before #315: 8)" % (len(on), CB_NODE))
sys.exit(0 if ok else 1)
EOF
  finish
fi

#=============================== grow-fail (#242) ==========================
if [ "$MODE" = grow-fail ]; then
  for L in export park; do
    c=mm_lgr_a
    [ "$L" = park ] && c=mm_lgr_e
    with_para $c gf_$L "nomp = 4"
    echo "=== $c on $NP processes x 4 threads, LGR_TEST_SMALL_EXPORT=1 LGR_TEST_GROW_FAIL=$L"
    t0=$(date +%s)
    ( cd "$W" && LGR_TEST_SMALL_EXPORT=1 LGR_TEST_GROW_FAIL=$L timeout 300 nice -n 10 \
        mpirun --oversubscribe -np $NP -x LGR_TEST_SMALL_EXPORT -x LGR_TEST_GROW_FAIL \
        shyfem gf_$L.str > gf_$L.log 2>&1 )
    lrc=$?
    log="$W/gf_$L.log"
    echo "  exit code $lrc after $(( $(date +%s) - t0 )) s"
    [ "$lrc" = 33 ] || fail "$L: exit code $lrc, expected 33"
    threads gf_$L.log 4
    grep -q "lgr_mpi_grow_$L: allocation" "$log" || fail "$L: no 'lgr_mpi_grow_$L: allocation' in the log"
    if grep -q "lgr_mpi_list_check:" "$log"; then
      grep "lgr_mpi_list_check:" "$log" | sort -u | head -4 | sed 's/^/  /'
    else
      fail "$L: no line of the check after the particle loop (lgr_mpi_list_check:)"
    fi
    grep -m3 "lgr_mpi_grow_$L: allocation\|REDTMP" "$log" | sed 's/^/  /'
    if grep -q "SIGSEGV\|SIGFPE\|Fortran runtime" "$log"; then
      fail "$L: crash line in the log"; grep -m3 "SIGSEGV\|SIGFPE\|Fortran runtime" "$log" | sed 's/^/    /'
    fi
    grep -q "simulation end" "$log" && fail "$L: the run ended instead of stopping"
  done
  finish
fi

#=============================== int-fail (#256) ===========================
if [ "$MODE" = int-fail ]; then
  for n in 4 1; do
    with_para mm_lgr_a if_t$n "nomp = $n"
    echo "=== mm_lgr_a on $NP processes x $n thread(s), LGR_TEST_INTERNAL_FAIL=1"
    t0=$(date +%s)
    ( cd "$W" && LGR_TEST_INTERNAL_FAIL=1 timeout 300 nice -n 10 \
        mpirun --oversubscribe -np $NP -x LGR_TEST_INTERNAL_FAIL \
        shyfem if_t$n.str > if_t$n.log 2>&1 )
    lrc=$?
    log="$W/if_t$n.log"
    echo "  exit code $lrc after $(( $(date +%s) - t0 )) s"
    [ "$lrc" = 33 ] || fail "$n thread(s): exit code $lrc, expected 33"
    threads if_t$n.log $n
    grep -m2 "lgr_mpi_test_internal:" "$log" | sed 's/^/  /'
    grep -q "lgr_mpi_test_internal:" "$log" || fail "$n thread(s): the hook did not fire"
    grep -q "error stop drogue: internal error" "$log" \
      || fail "$n thread(s): no 'error stop drogue: internal error' in the log"
    if [ "$n" = 4 ]; then
      grep -q "lgr_mpi_test_internal:.*OpenMP thread 0$" "$log" \
        && fail "4 threads: the hook fired on thread 0"
      if grep -q "lgr_mpi_list_check:.*internal error found in the particle loop" "$log"; then
        grep "lgr_mpi_list_check:" "$log" | sort -u | head -4 | sed 's/^/  /'
      else
        fail "4 threads: no line of the check after the particle loop (lgr_mpi_list_check:)"
      fi
    else
      grep -q "lgr_mpi_list_check:" "$log" \
        && fail "1 thread: a check line, expected the abort in the guard itself"
    fi
    grep -m2 "error stop drogue: internal error" "$log" | sed 's/^/  /'
    if grep -q "SIGSEGV\|SIGFPE\|Fortran runtime" "$log"; then
      fail "$n thread(s): crash line in the log"; grep -m3 "SIGSEGV\|SIGFPE\|Fortran runtime" "$log" | sed 's/^/    /'
    fi
    grep -q "simulation end" "$log" && fail "$n thread(s): the run ended instead of stopping"
  done
  finish
fi

#=============================== events (#305) =============================
if [ "$MODE" = events ]; then
  SRC="$HERE/../../../src"
  [ -d "$SRC/shyfem" ] && [ -d "$SRC/utils" ] || { echo "$MODE: FAIL (no source tree at $SRC)"; exit 1; }
  # mm_lgr_a for 30 minutes (the hook fires in the first pass), 1 and 4
  # OpenMP threads
  sed -e "s/itend = '[^']*'/itend = '2009-01-01::00:30:00'/" "$W/mm_lgr_a.str" > "$W/ev0.str"
  with_para ev0 ev_t1 "nomp = 1"
  with_para ev0 ev_t4 "nomp = 4"
  for f in ev_t1 ev_t4; do
    grep -q "itend = '2009-01-01::00:30:00'" "$W/$f.str" || fail "$f.str: no itend = '2009-01-01::00:30:00'"
    grep -q "^[[:space:]]*$f[[:space:]]*\$" "$W/$f.str" || fail "$f.str: run name not set"
  done
  grep -q "nomp = 1" "$W/ev_t1.str" || fail "ev_t1.str: no 'nomp = 1'"
  grep -q "nomp = 4" "$W/ev_t4.str" || fail "ev_t4.str: no 'nomp = 4'"
  [ "$rc" = 0 ] || finish
  # evrun TAG STR LAUNCHER...: STR.str in the scratch folder with a timeout
  # of 120 s, log TAG.log, exit code in TAG.rc
  evrun() {
    local tag="$1" str="$2"; shift 2
    ( cd "$W" && timeout 120 nice -n 10 "$@" "$str.str" > "$tag.log" 2>&1 )
    echo $? > "$W/$tag.rc"
  }
  t0=$(date +%s)
  echo "=== mm_lgr_a, 30 minutes, LGR_TEST_EVENT=K for K = 1 ... 27: 1 and 4 threads serially, 1 thread on $NP processes"
  for k in $(seq 1 27); do
    evrun ev_k${k}_t1 ev_t1 env LGR_TEST_EVENT=$k shyfem
    evrun ev_k${k}_t4 ev_t4 env LGR_TEST_EVENT=$k shyfem
    evrun ev_k${k}_np ev_t1 env LGR_TEST_EVENT=$k mpirun --oversubscribe -np $NP -x LGR_TEST_EVENT shyfem
  done
  echo "=== the same, 1 thread, LGR_TEST_EVENT=8 and LGR_TEST_INTERNAL_FAIL=1 (an event and a guard with no kind in the same pass)"
  evrun ev_if ev_t1 env LGR_TEST_EVENT=8 LGR_TEST_INTERNAL_FAIL=1 shyfem
  echo "  82 runs in $(( $(date +%s) - t0 )) s"
  PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$NP" <<'EOF' || fail "see above"
import os, re, sys

w, np_ = sys.argv[1], int(sys.argv[2])
ok = True
def bad(msg):
    global ok
    print("  FAIL: " + msg)
    ok = False

# the line of each kind as lgr_event_desc documents it (written out here,
# not taken from the code): head, text, the part "in the run" (None: the
# kind stops the run; "%": the lines of #288; "per100": an event count),
# the names of the values, how many are integers, reals with 3 decimals
CVD, CADV = "lgr vertical diffusion", "lgr advection"
TL = ["id", "element", "calls left", "time left [s]"]
TA = ["id", "element", "crossings left", "time left [s]"]
LAY = ["id", "element", "layer", "of"]
DEP = LAY + ["tv", "t", "dz", "w", "hd", "z"]
NXT = ["id", "element", "in", "it", "ia1", "ieb", "ieltv 1", "ieltv 2", "ieltv 3"]
XI = ["xi 1", "xi 2", "xi 3"]
KIND = {
    1: (CVD, "lost with time left", "%", TL, 3, True),
    2: (CVD, "walk ended with time left, cause unknown", "%", TL, 3, True),
    3: (CVD, "depth outside 0..1 after a call of lgr_diff_vert", None, DEP, 4, False),
    4: (CVD, "no such layer in lgr_diff_vert", None, LAY, 4, False),
    5: (CADV, "element crossings used up with time left", "per100", TA, 3, True),
    6: (CADV, "lost with time left", "per100", TA, 3, True),
    7: (CADV, "advection ended with time left, cause unknown", "per100", TA, 3, True),
    8: (CADV, "flux over a wall side set to 0", "per100", ["id", "element", "layer", "side", "flux"], 4, False),
    9: (CADV, "negative velocity in track_xi", "per100", LAY + ["vel", "flux 1", "flux 2", "flux 3"], 4, False),
    10: (CADV, "layer below the bottom of the element entered, put in its bottom layer", "per100", LAY, 4, False),
    11: ("lgr layers", "incompatible layers in lagr_layer_thickness", None, ["element", "nlev", "lmax", "lmax_act"], 4, False),
    12: (CADV, "internal error (3) of track_xi", None, ["id", "element", "s", "t", "th", "ds", "sorig"], 2, False),
    13: (CADV, "depth outside 0..1 in track_xi", None, DEP, 4, False),
    14: (CADV, "erroneous xi in track_xi_next_element", None, NXT[:4] + XI, 4, False),
    15: (CADV, "erroneous xi sanity in track_xi_next_element", None, NXT[:5] + XI, 5, False),
    16: (CADV, "erroneous ieltv in track_xi_next_element", None, NXT + XI, 9, False),
    17: (CADV, "no such layer in track_xi_get_vertical", None, LAY, 4, False),
    18: (CADV, "wrong xi in track_xi_check", None, ["id"] + XI, 1, False),
    19: ("lgr connectivity", "time is nan in lagr_connect_count", None, ["id", "slot", "element", "time"], 3, False),
    20: ("lgr connectivity", "particle not coming from a source in lagr_connect_count", None,
         ["id", "slot", "element of origin", "external element", "station"], 5, False),
    21: ("lgr element search", "no old element in lgr_mpi_locate", None, ["slot", "phase", "element"], 3, False),
    22: (CADV, "determinant too small in xi2xy", None, ["id", "element"] + XI, 2, False),
    23: (CADV, "xy2xi failed (error -1: element out of range, 1 or 3: xi cannot be adjusted)", None,
         ["id", "element", "error", "x", "y"], 3, False),
    24: (CADV, "internal error of xit_start_end in track_xi", None, ["id", "element", "iflux", "error", "alpha"] + XI, 4, False),
    25: (CADV, "error of xi_dist in track_xi (1: a point not on a side, 2: impossible)", None,
         ["id", "element", "error", "xis 1", "xis 2", "xis 3", "xie 1", "xie 2", "xie 3"], 3, False),
    26: (CADV, "stopped at a node the layer flow converges on (node sink) with time left", "per100",
         ["id", "element", "layer", "time left [s]"], 3, True),
    27: (CADV, "all the time left spent moving off a vertex (vertex hold)", "per100",
         ["id", "element", "layer", "node", "time spent [s]"], 4, True),
}
SITE = {18: "LGR_TEST_EVENT"}
ANYEV = re.compile(r"^ lgr (vertical diffusion|advection|layers|connectivity|element search):")
CRASH = ("SIGSEGV", "SIGFPE", "Fortran runtime")
CHECK = "lgr_mpi_list_check:"
INLOOP = re.compile(r"lgr_mpi_list_check: rank \d+ \(drogue, after the particle loop\): an internal error"
                    r" found in the particle loop by OpenMP thread (\d+)")

def line_re(k):
    head, text, lab, names, _, _ = KIND[k]
    r = "^ " + re.escape(head) + r":(?: rank (?P<rank>\d+):)? " + re.escape(text)
    if k in SITE:
        r += re.escape(" (%s)" % SITE[k])
    r += r": (?P<n>\d+) in the step to (?P<t>\S+?)"
    if lab is not None:
        what = "%" if lab == "%" else "events per 100"
        r += r", (?P<ntot>\d+) in the run \((?P<p>[\d.]+) " + re.escape(what) \
             + r" of the (?P<nrel>\d+) particles released\)"
    r += "; first:"
    for j, nm in enumerate(names):
        r += ("" if j == 0 or nm == "of" else ",") + " " + re.escape(nm) + r" (?P<v%d>[^,\s]+)" % j
    return re.compile(r + "$")

def message(k):
    return "error stop diff_body: error of xy2xi" if k == 23 else "error stop lgr_mpi_test_event: kind %d" % k

def values_ok(k, m, tag):
    _, _, _, names, ni, bfix = KIND[k]
    vals = [m.group("v%d" % j) for j in range(len(names))]
    if k == 23:		# the values of diff_body's own site, the error forced to 1
        try:
            good = int(vals[0]) >= 1 and int(vals[1]) >= 1 and vals[2] == "1"
            float(vals[3]), float(vals[4])
        except ValueError:
            good = False
        if not good:
            bad("%s: values %r, expected id and element >= 1, error 1, x and y" % (tag, vals))
        return
    for j, v in enumerate(vals):
        if j < ni:
            good = v == str(j + 1)
        elif bfix:
            good = v == "%.3f" % (j - ni + 0.5)
        else:
            try:
                good = float(v) == j - ni + 0.5
            except ValueError:
                good = False
        if not good:
            bad("%s: value %d (%s) is %r, expected the fixed value of the hook" % (tag, j + 1, names[j], v))

def read(tag):
    with open(os.path.join(w, tag + ".log"), errors="replace") as fh:
        log = fh.read().split("\n")
    with open(os.path.join(w, tag + ".rc")) as fh:
        rc = int(fh.read().strip() or "-1")
    return log, rc

# the release of the serial run: time and particles (the first pass)
log, _ = read("ev_k8_t1")
rel = [re.search(r"new particles released: *(\d+) at time: (\S+)", l) for l in log]
rel = [m for m in rel if m]
if not rel:
    print("  FAIL: no release line in ev_k8_t1.log")
    sys.exit(1)
NREL, TREL = int(rel[0].group(1)), rel[0].group(2)
print("  serial release: %d particles at %s (the first pass)" % (NREL, TREL))

def common(k, tag, log, rc, nthreads):
    """checks of every run; returns its matches of the line of kind k"""
    if not any(("test hook LGR_TEST_EVENT: an event of kind %d " % k) in l for l in log):
        bad("%s: the log does not acknowledge the test hook LGR_TEST_EVENT=%d" % (tag, k))
    if nthreads is not None:
        th = [re.search(r"used OMP threads: *(\d+)", l) for l in log]
        th = [int(m.group(1)) for m in th if m]
        if th[:1] != [nthreads]:
            bad("%s: used OMP threads %r, expected %d" % (tag, th[:1], nthreads))
    for s in CRASH:
        if any(s in l for l in log):
            bad("%s: a '%s' line" % (tag, s))
    rx = line_re(k)
    hits = []
    for i, l in enumerate(log):
        if not ANYEV.match(l):
            continue
        m = rx.match(l)
        if not m:
            bad("%s: an event line not of kind %d as documented: %r" % (tag, k, l))
            continue
        hits.append((i, m))
        if m.group("n") != "1" or m.group("t") != TREL:
            bad("%s: %s in the step to %s, expected 1 in the step to %s" % (tag, m.group("n"), m.group("t"), TREL))
        if KIND[k][2] is not None:
            p = "%.2f" % (100.0 / NREL)
            if m.group("ntot") != "1" or m.group("nrel") != str(NREL) or m.group("p") != p:
                bad("%s: in the run %s (%s of %s), expected 1 (%s of %d)"
                    % (tag, m.group("ntot"), m.group("p"), m.group("nrel"), p, NREL))
        values_ok(k, m, tag)
    return hits

for k in range(1, 28):
    brun = KIND[k][2] is not None
    res = {}
    for flow, nth in (("t1", 1), ("t4", 4), ("np", None)):
        tag = "ev_k%d_%s" % (k, flow)
        log, rc = read(tag)
        hits = common(k, tag, log, rc, nth)
        ranks = [m.group("rank") for _, m in hits]
        res[flow] = (log, rc, hits, ranks)
        end = any("simulation end" in l for l in log)
        msg = [i for i, l in enumerate(log) if message(k) in l]
        if brun:
            if rc != 0 or not end:
                bad("%s: exit code %d, 'simulation end' %s; expected the run to end" % (tag, rc, end))
            if msg:
                bad("%s: the message '%s' in a run that goes on" % (tag, message(k)))
        else:
            if rc != 33 or end:
                bad("%s: exit code %d, 'simulation end' %s; expected exit code 33 and no end" % (tag, rc, end))
            if not msg:
                bad("%s: no message '%s'" % (tag, message(k)))
        if flow != "np":
            if len(hits) != 1 or ranks != [None]:
                bad("%s: %d lines of kind %d (ranks %r), expected one without a rank" % (tag, len(hits), k, ranks))
        else:
            rk = [int(r) for r in ranks if r is not None]
            if not hits or len(rk) != len(hits) or len(set(rk)) != len(rk) or not all(0 <= r < np_ for r in rk):
                bad("%s: lines of kind %d with the ranks %r, expected one or more, each with a distinct rank"
                    " in 0..%d" % (tag, k, ranks, np_ - 1))
            if brun:		# every process with particles writes its line
                nwith = sum(1 for l in log if re.search(r"new particles released: *[1-9]\d* at time: " + re.escape(TREL), l))
                if len(hits) != nwith:
                    bad("%s: %d lines of kind %d, expected one per process with particles (%d)" % (tag, len(hits), k, nwith))
            else:
                # Open MPI (the build requires it) names the rank that aborted
                ab = [re.search(r"MPI_ABORT was invoked on rank (\d+)", l) for l in log]
                ab = [int(m.group(1)) for m in ab if m]
                if not ab:
                    bad("%s: no line 'MPI_ABORT was invoked on rank R' (Open MPI) for a kind that stops the run" % tag)
                elif ab[0] not in rk:
                    bad("%s: MPI_ABORT on rank %d, not one of the ranks of the lines %r" % (tag, ab[0], rk))
        if not brun and flow == "t1":
            if hits and msg and hits[0][0] > msg[0]:
                bad("%s: the line of kind %d after the message" % (tag, k))
            if any(CHECK in l for l in log):
                bad("%s: a line '%s', expected the abort at once on one thread" % (tag, CHECK))
        if not brun and flow == "t4":
            if not any(INLOOP.search(l) for l in log):
                bad("%s: no line of the check after the particle loop (%s ... OpenMP thread N)" % (tag, CHECK))
    l1 = [res["t1"][0][i] for i, _ in res["t1"][2]]
    l4 = [res["t4"][0][i] for i, _ in res["t4"][2]]
    if l1 != l4:
        bad("kind %d: the line of 4 threads differs from that of 1 thread" % k)
    shown = l1[0].strip() if l1 else "(no line)"
    print("  kind %2d %s: %s; %d process(es) with a line, ranks %s"
          % (k, "goes on" if brun else "stops  ", shown[:150] + (" ..." if len(shown) > 150 else ""),
             len(res["np"][2]), ",".join(r or "-" for r in res["np"][3])))
    if not brun:
        ck = [INLOOP.search(l) for l in res["t4"][0]]
        ck = [m.group(0) for m in ck if m]
        print("          4 threads: %s" % (ck[0] if ck else "(no line of the check)"))

# a non-stop event and a guard with no kind in the same pass, 1 thread
log, rc = read("ev_if")
hits = common(8, "ev_if", log, rc, 1)
msg = [i for i, l in enumerate(log) if "error stop drogue: internal error" in l]
fired = any("lgr_mpi_test_internal: travel time set negative by OpenMP thread 0" in l for l in log)
print("  LGR_TEST_EVENT=8 + LGR_TEST_INTERNAL_FAIL=1, 1 thread: exit code %d, the hook of the guard %s,"
      " lines of kind 8: %d, message: %s" % (rc, "fired" if fired else "did not fire", len(hits),
      log[msg[0]].strip() if msg else "none"))
if rc != 33 or not msg or not fired or any("simulation end" in l for l in log):
    bad("ev_if: expected exit code 33 with 'error stop drogue: internal error' after the hook of the guard fired")
if len(hits) != 1:
    bad("ev_if: %d lines of kind 8, expected the event of the pass written before the stop" % len(hits))
elif msg and hits[0][0] > msg[0]:
    bad("ev_if: the line of kind 8 after the message")
if any(CHECK in l for l in log):
    bad("ev_if: a line '%s', expected the abort at once on one thread" % CHECK)
sys.exit(0 if ok else 1)
EOF
  # the routines of the old name stop with a bare stop (exit code 0): none
  # may be called in the model (every Fortran file under src, src/tools
  # excepted: the tools run on one process), where they run on several
  # processes; kept is exactly one known call inside the OpenMP tasks of
  # conz3d_omp, a debug line of tvd_get_upwind_c under bdebug = .false.,
  # where an abort through MPI_ABORT may not come from a worker either
  # (since #317 the upwind value calls femintp_xi_ierr, records an error
  # and stops after the OpenMP tasks; femintp_xi has no model call left)
  PYTHONDONTWRITEBYTECODE=1 python3 - "$SRC" <<'EOF' || fail "calls of xi2xy, xy2xi, xi_dist or xit_start_end (bare stop) in the model, see above"
import os, re, sys
src = sys.argv[1]
# the calls kept: (file under src, routine, the stripped line), each once
KEEP = [("shyfem/tvd_admin.f90", "tvd_get_upwind_c", "call xy2xi(ienew,xd,yd,xi)")]
EXT = (".f", ".F", ".f90", ".F90")
unit = re.compile(r"^\s*(?:[a-z ()*0-9,=]*\s)?(?:subroutine|function)\s+(\w+)", re.I)
call = re.compile(r"^[^!]*\bcall\s+(xi2xy|xy2xi|xi_dist|xit_start_end)\s*\(", re.I)
bad, kept, seen = [], [], dict((k, 0) for k in KEEP)
files = []
for top, dirs, names in os.walk(src):
    dirs.sort()
    if os.path.relpath(top, src).split(os.sep)[0] == "tools":
        dirs[:] = []
        continue
    files += [os.path.join(top, f) for f in sorted(names) if f.endswith(EXT)]
for path in files:
    rel = os.path.relpath(path, src).replace(os.sep, "/")
    fixed = path.endswith((".f", ".F"))	# fixed form: a comment in column 1
    name = None
    with open(path, errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if fixed and line[:1] in "cC*!":
                continue
            m = unit.match(line)
            if m and not line.lstrip().lower().startswith("end"):
                name = m.group(1).lower()
            if call.match(line):
                key = (rel, name, line.strip())
                what = "    src/%s:%d (%s): %s" % (rel, n, name, line.strip())
                if key in seen and seen[key] == 0:
                    seen[key] = 1
                    kept.append(what)
                else:
                    bad.append(what)
print("  Fortran files scanned under src (src/tools excepted): %d; calls kept inside the OpenMP tasks"
      " of conz3d_omp: %d (expected %d)" % (len(files), len(kept), len(KEEP)))
for l in kept:
    print(l)
ok = True
for k, v in seen.items():
    if v != 1:
        print("  FAIL: the kept call src/%s (%s) %r is not found: update the list" % k)
        ok = False
if len(kept) != len(KEEP):
    ok = False
if bad:
    print("  FAIL: calls of the old name (bare stop) on the paths of the model:")
    for l in bad:
        print(l)
    ok = False
if not ok:
    sys.exit(1)
print("  no other call of xi2xy, xy2xi, xi_dist or xit_start_end (bare stop) in the model")
EOF
  finish
fi

#=============================== nbdymax (#269) ============================
if [ "$MODE" = nbdymax ]; then
  sed 's/^\([ \t]*nbdymax[ \t]*=[ \t]*\)5000/\1100/' "$W/mm_lgr_a.str" > "$W/nbm.str"
  grep -q "nbdymax *= *100" "$W/nbm.str" || fail "nbdymax = 100 not set in nbm.str"
  for np in 1 $NP; do
    if [ "$np" = 1 ]; then launcher="shyfem"; else launcher="mpirun --oversubscribe -np $np shyfem"; fi
    echo "=== mm_lgr_a with nbdymax = 100 (150 particles) on $np process(es)"
    ( cd "$W" && timeout 300 nice -n 10 $launcher nbm.str > nbm_$np.log 2>&1 )
    lrc=$?
    echo "  exit code $lrc"
    [ "$lrc" = 33 ] || fail "$np process(es): exit code $lrc, expected 33"
    grep -m4 "Cannot insert more than nbdymax\|particles needed\|error stop insert_particle" "$W/nbm_$np.log" | sed 's/^/  /'
    grep -q "Cannot insert more than nbdymax particles" "$W/nbm_$np.log" || fail "$np process(es): no 'Cannot insert more than nbdymax particles'"
    grep -q "particles needed: at least" "$W/nbm_$np.log" || fail "$np process(es): no 'particles needed: at least' line"
    grep -q "error stop insert_particle: nbdy" "$W/nbm_$np.log" || fail "$np process(es): no 'error stop insert_particle: nbdy' abort message"
    grep -q "simulation end" "$W/nbm_$np.log" && fail "$np process(es): the run ended instead of stopping"
  done
  # a particle file with more particles than nbdymax (lgr_input_shell,
  # serial only: lgrini stops at start-up on several processes)
  echo "=== a particle file of 150 particles read with nbdymax = 100"
  with_para mm_lgr_a nbm_w "itend = '2009-01-01::02:00:00'"
  run nbm_w nbm_w.log shyfem || fail "the run that makes the particle file did not end"
  sed -e 's/^\([ \t]*\)nbdymax[ \t]*=[ \t]*5000/\1nbdymax = 100/' \
      -e 's/^\([ \t]*\)nbdy[ \t]*=[ \t]*150[ \t]*$/\1nbdy = 0\n\1lgrini = '"'nbm_w.lgr.shy'"'\n\1itlgin = '"'2009-01-01::01:00:00'"'/' \
      "$W/mm_lgr_a.str" > "$W/nbm_r.str"
  for o in "nbdymax = 100" "nbdy = 0" "lgrini = 'nbm_w.lgr.shy'"; do
    grep -qF -- "$o" "$W/nbm_r.str" || fail "no '$o' in nbm_r.str"
  done
  ( cd "$W" && timeout 300 nice -n 10 shyfem nbm_r.str > nbm_r.log 2>&1 )
  lrc=$?
  echo "  exit code $lrc"
  [ "$lrc" = 33 ] || fail "particle file: exit code $lrc, expected 33"
  grep -q "initializing lagrangian from file" "$W/nbm_r.log" || fail "particle file: the run did not read the particle file"
  grep -m4 "Cannot insert more than nbdymax\|particles needed\|error stop lgr_input_shell" "$W/nbm_r.log" | sed 's/^/  /'
  grep -q "Cannot insert more than nbdymax particles" "$W/nbm_r.log" || fail "particle file: no 'Cannot insert more than nbdymax particles'"
  grep -q "particles needed: at least" "$W/nbm_r.log" || fail "particle file: no 'particles needed: at least' line"
  grep -q "error stop lgr_input_shell: nbdy" "$W/nbm_r.log" || fail "particle file: no 'error stop lgr_input_shell: nbdy' abort message"
  grep -q "simulation end" "$W/nbm_r.log" && fail "particle file: the run ended instead of stopping"
  finish
fi

#=============================== small-export (#242) =======================
if [ "$MODE" = small-export ]; then
  for c in mm_lgr_a mm_lgr_e; do
    # se_${c}_t4 (4 threads, hook), _t1 (1 thread, hook), _t1n (1 thread,
    # no hook), _t4d (4 threads, hook, levdbg = 3)
    with_para $c se_${c}_t4x "nomp = 4"; with_line se_${c}_t4x se_${c}_t4 para "levdbg = 2"
    with_para $c se_${c}_t1x "nomp = 1"; with_line se_${c}_t1x se_${c}_t1 para "levdbg = 2"
    with_line se_${c}_t1x se_${c}_t1n para "levdbg = 2"
    with_line se_${c}_t4x se_${c}_t4d para "levdbg = 3"
    echo "=== $c on $NP processes, LGR_TEST_SMALL_EXPORT=1, levdbg = 2: 4 threads, 1 thread; 1 thread without the hook"
    for v in t4 t1 t1n t4d; do		# the levdbg line of each run
      want=2; [ $v = t4d ] && want=3
      if grep -q "^ *levdbg = $want\s*$" "$W/se_${c}_$v.str"; then echo "  se_${c}_$v.str: levdbg = $want"
      else fail "$c $v: no 'levdbg = $want' line in se_${c}_$v.str"
      fi
    done
    for v in t4 t1 t4d; do
      run se_${c}_$v se_${c}_$v.log env LGR_TEST_SMALL_EXPORT=1 \
        mpirun --oversubscribe -np $NP -x LGR_TEST_SMALL_EXPORT shyfem || fail "$c $v: the run did not end"
    done
    run se_${c}_t1n se_${c}_t1n.log mpirun --oversubscribe -np $NP shyfem || fail "$c t1n: the run did not end"
    threads se_${c}_t4.log 4
    threads se_${c}_t1.log 1
    for v in t4 t1 t1n t4d; do
      n="$(grep -c 'lgr_mpi_check_consistency' "$W/se_${c}_$v.log")"
      if [ "$n" -gt 0 ]; then fail "$c $v: consistency check wrote $n lines"
      else echo "  se_${c}_$v.log: consistency check silent"
      fi
    done
    for v in t1 t1n; do
      a="$W/se_${c}_t4.lgr.shy"; b="$W/se_${c}_$v.lgr.shy"
      if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$c: particle file missing (t4 or $v)"
      elif cmp -s "$a" "$b"; then echo "  $c: particle file of 4 threads (hook) identical to $v ($(stat -c %s "$a") bytes)"
      else fail "$c: particle file of 4 threads (hook) differs from $v"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
      fi
    done
    ng="$(grep -c 'lgr_mpi_grow_\(export\|park\): rank' "$W/se_${c}_t4d.log")"
    nw="$(grep 'lgr_mpi_grow_\(export\|park\): rank' "$W/se_${c}_t4d.log" | grep -vc 'OpenMP thread *0$')"
    echo "  $c, 4 threads at levdbg = 3: $ng growths of the lists, $nw of them made by an OpenMP thread other than 0"
    grep 'lgr_mpi_grow_\(export\|park\): rank' "$W/se_${c}_t4d.log" | head -3 | sed 's/^/   /'
    [ "$ng" -gt 0 ] || fail "$c: no growth of the lists at levdbg = 3"
  done
  finish
fi

#=============================== seed (#225) ===============================
if [ "$MODE" = seed ]; then
  # same NAME A B: cmp of NAME.A.lgr.shy and NAME.B.lgr.shy must be equal
  same() {
    local a="$W/$1.$2.lgr.shy" b="$W/$1.$3.lgr.shy"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$1: particle file missing ($2 or $3)"
    elif cmp -s "$a" "$b"; then echo "  $1: $2 and $3 identical ($(stat -c %s "$a") bytes)"
    else fail "$1: $2 and $3 differ"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
    fi
  }
  # differ NAME A B: the two particle files must differ
  differ() {
    local a="$W/$1.$2.lgr.shy" b="$W/$1.$3.lgr.shy"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$1: particle file missing ($2 or $3)"
    elif cmp -s "$a" "$b"; then fail "$1: $2 and $3 are identical (the seed does not reach the draws)"
    else echo "  $1: $2 and $3 differ, as they must"
    fi
  }
  # srun NAME VARIANT LAUNCHER...: run the STR file NAME_VARIANT.str, keep
  # its particle file as NAME.VARIANT.lgr.shy
  srun() {
    local name="$1" v="$2"; shift 2
    run "${name}_$v" "${name}_$v.log" "$@" || fail "$name $v: the run did not end"
    mv "$W/${name}_$v.lgr.shy" "$W/$name.$v.lgr.shy" 2> /dev/null
  }
  # setname SRC DST: copy of SRC.str with the run name DST (second line of
  # $title), nothing else changed
  setname() {
    awk -v name="$2" '
      /^\$title/ { t = 1; nt = 0 }
      t && !/^\$/ { nt++; if( nt == 2 ) { print "        " name; next } }
      /^\$end/ { t = 0 }
      { print }
    ' "$W/$1.str" > "$W/$2.str"
  }

  echo "=== 1. mm_lgr serially: plain, lgrseed = 1, 4 threads, lgrseed = 2"
  setname mm_lgr d_t1
  with_line mm_lgr d_s1 lagrg "lgrseed = 1"
  with_para mm_lgr d_t4 "nomp = 4"
  with_line mm_lgr d_s2 lagrg "lgrseed = 2"
  grep -q '^ *lgrseed = 1$' "$W/d_s1.str" && grep -q '^ *lgrseed = 2$' "$W/d_s2.str" \
    || fail "no lgrseed line in d_s1.str or d_s2.str"
  for v in t1 s1 t4 s2; do srun d $v shyfem; done
  threads d_t4.log 4
  threads d_t1.log 1
  same d t1 s1
  same d t1 t4
  differ d t1 s2
  if [ -s "$W/d.t1.lgr.shy" ] && [ -s "$W/d.s2.lgr.shy" ]; then
    python3 "$W/lgr_compare.py" "$W/d.t1.lgr.shy" "$W/d.s2.lgr.shy" --mode ids --same-counts \
      > "$W/d_ids.txt" 2>&1 || { fail "d: lgrseed = 2 changes the ids or counts per block"; tail -5 "$W/d_ids.txt"; }
    [ "$rc" = 0 ] && echo "  d: lgrseed = 2 has the ids and counts per block of the plain run"
  fi

  echo "=== 2. mm_lgr on $NP processes: 4 threads and 1 thread"
  with_para mm_lgr p_t4 "nomp = 4"
  with_para mm_lgr p_t1 "nomp = 1"
  srun p t4 mpirun --oversubscribe -np $NP shyfem
  srun p t1 mpirun --oversubscribe -np $NP shyfem
  threads p_t4.log 4
  same p t1 t4

  echo "=== 3. mm_lgr_c with the serial-only draws: twice 1 thread, 4 threads, lgrseed = 2"
  sed -e 's/^\([ \t]*\)ipvert = -1[ \t]*$/\1ipvert = -3\n\1lbeach = 0.5\n\1ldecay = 86400.\n\1ilarv = 1\n\1ised = 1/' \
      -e 's/^\([ \t]*\)rwhpar = 0[ \t]*$/\1rwhpar = 0.5/' "$W/mm_lgr_c.str" > "$W/c_base.str"
  printf '\n$bound1\n        kbound = 218\n        ibtyp = 3\n        boundn = %s\n        lgrpps = 0.002\n$end\n' \
    "'INPUT/river.txt'" >> "$W/c_base.str"
  for o in 'ipvert = -3' 'lbeach = 0.5' 'ldecay = 86400.' 'ilarv = 1' 'ised = 1' 'rwhpar = 0.5' 'lgrpps = 0.002'; do
    grep -q "^ *$o\$" "$W/c_base.str" || fail "no line '$o' in c_base.str"
  done
  setname c_base c_r1
  setname c_base c_r2
  with_para c_base c_t4 "nomp = 4"
  with_line c_base c_s2 lagrg "lgrseed = 2"
  for v in r1 r2 t4 s2; do srun c $v shyfem; done
  threads c_t4.log 4
  same c r1 r2
  same c r1 t4
  differ c r1 s2

  echo "=== 4. vertical diffusion (ilagr = 3): 1 thread and 4 threads"
  sed -e '/^\s*ztilt\s*=/d' -e '/^\s*ktilt\s*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" "$W/mm_hyd_41.str" > "$W/v_base.str"
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 20000\n        nbdy = 300  idtl = 0  idtlgr = %s\n        rwhpar = 0.5  ipvert = -3\n$end\n' \
    "'1h'" >> "$W/v_base.str"
  grep -q "tilt" "$W/v_base.str" && fail "tilt lines left in v_base.str"
  setname v_base v_t1
  with_para v_base v_t4 "nomp = 4"
  for v in t1 t4; do srun v $v shyfem; done
  threads v_t4.log 4
  same v t1 t4

  echo "=== 5. mm_lgr restarted on 2009-01-03 from its particle and restart files"
  setname mm_lgr r_w0
  sed -e "s/itend = '2009-01-05'/itend = '2009-01-03'/" \
      -e 's/^\$para[ \t]*$/$para\n        idtrst = -1\n        itmrst = -1/' "$W/r_w0.str" > "$W/r_w1.str"
  setname r_w1 r_wr
  sed -e "s/itanf = '2009-01-01'/itanf = '2009-01-03'/" \
      -e 's/^\$para[ \t]*$/$para\n        itrst = -1\n        ityrst = 1/' \
      -e "s/^\\([ \t]*\\)nbdy = 150[ \t]*$/\\1nbdy = 0\n\\1lgrini = 'r_wr.lgr.shy'\n\\1itlgin = '2009-01-03'/" \
      -e "s/^\\\$name[ \t]*$/\$name\n        restrt = 'r_wr.rst'/" "$W/r_w0.str" > "$W/r_r1.str"
  setname r_r1 r_rr
  for o in "itend = '2009-01-03'" 'idtrst = -1'; do
    grep -qF -- "$o" "$W/r_wr.str" || fail "no '$o' in r_wr.str"
  done
  for o in "itanf = '2009-01-03'" 'itrst = -1' 'nbdy = 0' "lgrini = 'r_wr.lgr.shy'" "itlgin = '2009-01-03'" "restrt = 'r_wr.rst'"; do
    grep -qF -- "$o" "$W/r_rr.str" || fail "no '$o' in r_rr.str"
  done
  run r_wr r_wr.log shyfem || fail "the run to 2009-01-03 did not end"
  run r_rr r_rr.log shyfem || fail "the restarted run did not end"
  grep -q 'initializing lagrangian from file' "$W/r_rr.log" || fail "the restarted run did not read the particle file"
  grep -q 'A restart has been performed' "$W/r_rr.log" || fail "the restarted run did not read the restart file"
  if [ -s "$W/r_rr.lgr.shy" ] && [ -s "$W/d.t1.lgr.shy" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/d.t1.lgr.shy" "$W/r_rr.lgr.shy" <<'EOP' || fail "the restarted run differs from the run that went on"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

def load(path):
    _, times = lc.read_file(path)
    return {t: b for t, b, _ in times}

full, rest = load(sys.argv[2]), load(sys.argv[3])
nrec = ndiff = 0
for t in sorted(rest):
    if t not in full:
        print("  output t=%r of the restarted run not in the plain run" % t)
        ndiff += 1
        continue
    for w in (0, 1):			# active and exited records
        a, b = full[t][w], rest[t][w]
        if set(a) != set(b):
            print("  t=%r block %d: ids differ" % (t, w))
            ndiff += 1
        for pid in set(a) & set(b):
            nrec += 1
            if a[pid] != b[pid]:
                ndiff += 1
                if ndiff <= 5:
                    print("  t=%r id %d: %r / %r" % (t, pid, a[pid], b[pid]))
print("  restarted run: %d outputs, %d records compared with the plain run, %d differ"
      % (len(rest), nrec, ndiff))
sys.exit(0 if ndiff == 0 and nrec > 0 else 1)
EOP
  else
    fail "particle file missing (d.t1 or r_rr)"
  fi

  echo "=== 6. mm_lgr with daily releases, restarted on 2009-01-03, releases after the restart"
  sed -e "s/^\\([ \t]*\\)idtl = 0[ \t]*$/\\1idtl = '1d'\n\\1itranf = '2009-01-01::12:00:00'/" \
      "$W/mm_lgr.str" > "$W/q_base.str"
  setname q_base q_a
  sed -e "s/itend = '2009-01-05'/itend = '2009-01-03'/" \
      -e 's/^\$para[ \t]*$/$para\n        idtrst = -1\n        itmrst = -1/' "$W/q_base.str" > "$W/q_w1.str"
  setname q_w1 q_w
  sed -e "s/itanf = '2009-01-01'/itanf = '2009-01-03'/" \
      -e 's/^\$para[ \t]*$/$para\n        itrst = -1\n        ityrst = 1/' \
      -e "s/itranf = '2009-01-01::12:00:00'/itranf = '2009-01-03::12:00:00'/" \
      -e "s/^\\([ \t]*\\)nbdy = 150[ \t]*$/&\n\\1lgrini = 'q_w.lgr.shy'\n\\1itlgin = '2009-01-03'/" \
      -e "s/^\\\$name[ \t]*$/\$name\n        restrt = 'q_w.rst'/" "$W/q_base.str" > "$W/q_r1.str"
  setname q_r1 q_r
  for o in "idtl = '1d'" "itranf = '2009-01-01::12:00:00'"; do
    grep -qF -- "$o" "$W/q_a.str" || fail "no '$o' in q_a.str"
  done
  for o in "itend = '2009-01-03'" 'idtrst = -1'; do
    grep -qF -- "$o" "$W/q_w.str" || fail "no '$o' in q_w.str"
  done
  for o in "itanf = '2009-01-03'" 'itrst = -1' 'nbdy = 150' "lgrini = 'q_w.lgr.shy'" "itlgin = '2009-01-03'" "itranf = '2009-01-03::12:00:00'" "restrt = 'q_w.rst'"; do
    grep -qF -- "$o" "$W/q_r.str" || fail "no '$o' in q_r.str"
  done
  for r in q_a q_w q_r; do run $r $r.log shyfem || fail "$r: the run did not end"; done
  grep -q 'A restart has been performed' "$W/q_r.log" || fail "the restarted run did not read the restart file"
  if grep -q 'new particles released: .* at time: 2009-01-03::12:00:00' "$W/q_r.log"; then
    echo "  q_r: $(grep -m1 'largest id in the file' "$W/q_r.log" | sed 's/^ *//')"
    echo "  q_r: $(grep -m1 'new particles released' "$W/q_r.log" | sed 's/^ *//')"
  else
    fail "the restarted run released no particles on 2009-01-03 12:00"
  fi
  if [ -s "$W/q_a.lgr.shy" ] && [ -s "$W/q_r.lgr.shy" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/q_a.lgr.shy" "$W/q_r.lgr.shy" <<'EOP' || fail "repeated ids or records that differ from the run that went on"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

def load(path):
    _, times = lc.read_file(path)
    return times

full = {t: b for t, b, _ in load(sys.argv[2])}
rest = load(sys.argv[3])
nrep = nrec = ndiff = 0
for k, (t, b, dups) in enumerate(rest):
    if dups or set(b[0]) & set(b[1]):
        nrep += 1
        if nrep <= 3:
            print("  t=%r: repeated ids %r, active and exited %r"
                  % (t, dups[:5], sorted(set(b[0]) & set(b[1]))[:5]))
    if t not in full:
        print("  output t=%r of the restarted run not in the run that went on" % t)
        ndiff += 1
        continue
    for w in lc.IWHAT_ORDER:
        if w == -1 and k == 0:
            continue		# lists the particles read from the file
        a, r = full[t][w], b[w]
        if set(a) != set(r):
            ndiff += 1
            if ndiff <= 5:
                print("  t=%r %s: ids differ" % (t, lc.BLOCK_NAME[w]))
        for pid in set(a) & set(r):
            nrec += 1
            if a[pid] != r[pid]:
                ndiff += 1
                if ndiff <= 5:
                    print("  t=%r %s id %d differs" % (t, lc.BLOCK_NAME[w], pid))
print("  restarted run: %d outputs, %d with a repeated id; %d records compared"
      " with the run that went on, %d differ" % (len(rest), nrep, nrec, ndiff))
sys.exit(0 if nrep == 0 and ndiff == 0 and nrec > 0 else 1)
EOP
  else
    fail "particle file missing (q_a or q_r)"
  fi
  finish
fi

#=============================== sedbeach (#225, review) ===================
if [ "$MODE" = sedbeach ]; then
  sed -e 's/^\([ \t]*\)rwhpar = 0[ \t]*$/\1rwhpar = 0.5\n\1ised = 1\n\1lbeach = 1/' \
      "$W/mm_lgr_a.str" > "$W/sb_base.str"
  for o in 'rwhpar = 0.5' 'ised = 1' 'lbeach = 1'; do
    grep -q "^ *$o\$" "$W/sb_base.str" || fail "no line '$o' in sb_base.str"
  done
  with_para sb_base sb "levdbg = 0"
  echo "=== mm_lgr_a (2D) with ised = 1 and lbeach = 1, serially"
  run sb sb.log shyfem || fail "the run did not end"
  if grep -q 'Fortran runtime\|Program received signal\|SIGSEGV\|SIGFPE' "$W/sb.log"; then
    fail "run-time error or signal in the log"
    grep -m3 -A1 'At line\|Fortran runtime\|Program received signal' "$W/sb.log" | sed 's/^/    /'
  fi
  if [ "$rc" = 0 ] && [ -s "$W/sb.lgr.shy" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/sb.lgr.shy" <<'EOP' || fail "particle file check"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

_, times = lc.read_file(sys.argv[2])
first = {}
nrec = nmoved = nsink0 = 0
for t, b, _ in times:
    for pid, p in b[0].items():		# active particles
        if p["type"] >= 0:
            continue
        nrec += 1
        if p["s"] == 0.0:
            nsink0 += 1
        rec = (p["x"], p["y"], p["z"], p["lb"], p["ie"])
        if pid in first and first[pid] != rec:
            nmoved += 1
            if nmoved <= 3:
                print("  t=%r id %d: beached record changed %r -> %r" % (t, pid, first[pid], rec))
        first.setdefault(pid, rec)
print("  beached particles %d (records %d, with settling velocity 0: %d),"
      " records changed after beaching %d" % (len(first), nrec, nsink0, nmoved))
ok = len(first) > 0 and nmoved == 0 and nsink0 == 0
sys.exit(0 if ok else 1)
EOP
  elif [ "$rc" = 0 ]; then
    fail "no particle file"
  fi
  finish
fi

#=============================== bnd-release (#254) ========================
if [ "$MODE" = bnd-release ]; then
  KB="$(awk '/^\$bound1/{b=1; next} b && /kbound/{k=1} b && /ibtyp/{exit} b && k {sub(/kbound *=/,""); printf "%s ", $0}' "$W/mm_lgr_b.str")"
  echo "  kbound of mm_lgr_b: $(echo $KB | wc -w) nodes ($(echo $KB | cut -d' ' -f1) ... $(echo $KB | awk '{print $NF}'))"
  # bnd_all: that list; bnd_two: four of its nodes in an order in which no
  # two consecutive nodes are the ends of a side of the basin boundary
  # (98-100, 100-99 inner side, 99-101), while every node still has a
  # neighbour on the basin boundary in the list (the open boundary of the
  # hydrodynamics, bndo, needs that)
  # bnd_ppv: that list with lgrpps = -0.00001 (particles per cubic metre of
  # the inflow over each side: get_bflux_ppv)
  for c in all ppv two; do
    k="$KB"
    [ "$c" = two ] && k="98 100 99 101"
    pps=0.2
    [ "$c" = ppv ] && pps=-0.00001
    sed -e "s/itend = '[^']*'/itend = '2009-01-01::02'/" -e 's/^\(\s*nbdy\s*=\s*\)150/\10/' \
        -e '/lgrlin/d' -e "s/^\(\s*\)mm_lgr_a\s*$/\1bnd_$c/" "$W/mm_lgr_a.str" > "$W/bnd_$c.str"
    # kbound in lines of 10 nodes (an STR line has at most 80 characters)
    printf '\n$bound1\n        kbound = %s\n        ibtyp = 1\n        boundn = %s\n        lgrpps = %s\n$end\n' \
      "$(echo $k | xargs -n 10 | sed '2,$s/^/                 /')" "'INPUT/level_Mar_Menor.dat'" "$pps" >> "$W/bnd_$c.str"
    grep -q "bnd_$c" "$W/bnd_$c.str" || fail "run name not set in bnd_$c.str"
    grep -q "nbdy *= *0" "$W/bnd_$c.str" || fail "nbdy = 0 not set in bnd_$c.str"
  done

  for c in all ppv; do
  echo "=== mm_lgr_a for two hours, release along the Mar Menor sea boundary ($(grep -o 'lgrpps = .*' "$W/bnd_$c.str")), serially"
  bend=1
  run bnd_$c bnd_$c.log shyfem || { fail "$c: the boundary release run did not end"; bend=0; }
  grep "warning lagrange: boundary" "$W/bnd_$c.log" | sed 's/^/  /'
  nw="$(grep -c "warning lagrange: boundary 1 with lgrpps" "$W/bnd_$c.log")"
  [ "$nw" = 2 ] || fail "$c: warnings of skipped pairs: $nw, expected 2"
  for p in "99 and 100" "162 and 163"; do
    grep -q "warning lagrange: boundary 1 with lgrpps: nodes $p of kbound" "$W/bnd_$c.log" \
      || fail "$c: no warning for the pair $p"
  done
  if [ "$bend" = 0 ]; then
    echo "  particle file not checked (the run did not end)"
  elif [ -s "$W/bnd_$c.lgr.shy" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$W" "$W/bnd_$c.lgr.shy" "$W/GRID/MM_geo.grd" $c $KB <<'EOP' || fail "$c: start elements of the released particles"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

path, grd, case = sys.argv[2:5]
kb = [int(v) for v in sys.argv[5:]]
nodes, elems = {}, {}
with open(grd) as fh:
    for line in fh:
        f = line.split()
        if not f:
            continue
        if f[0] == "1":
            nodes[int(f[1])] = (float(f[3]), float(f[4]))
        elif f[0] == "2":
            elems[int(f[1])] = tuple(int(v) for v in f[4:7])
owner = {}
for ie, nn in elems.items():
    for a in range(3):
        owner.setdefault(frozenset((nn[a], nn[(a + 1) % 3])), []).append(ie)
pairs = list(zip(kb[:-1], kb[1:]))
sides = {frozenset(p) for p in pairs if len(owner.get(frozenset(p), [])) == 1}
inner = [p for p in pairs if len(owner.get(frozenset(p), [])) != 1]
print("  pairs of kbound %d: sides of the basin boundary %d, other pairs %s" % (len(pairs), len(sides), inner))
ok = len(sides) == 90 and inner == [(99, 100), (162, 163)]
if not ok:
    print("  the list is not the one this check expects")

TOL = 5e-3
def weights(ie, x, y):
    (x1, y1), (x2, y2), (x3, y3) = (nodes[k] for k in elems[ie])
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
    l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
    return (l1, l2, 1.0 - l1 - l2)

_, times = lc.read_file(path)
seen, nins, nbad = {}, 0, 0
per_side = dict.fromkeys(sides, 0)
for t, b, _ in times:
    for pid, p in b[-1].items():		# inserted block: release records
        nins += 1
        ie, x, y = p["ie"], p["x"], p["y"]
        why = None
        if ie not in elems:
            why = "element %d not in 1..%d" % (ie, len(elems))
        else:
            w = weights(ie, x, y)
            j = min(range(3), key=lambda a: abs(w[a]))
            nn = elems[ie]
            side = frozenset((nn[(j + 1) % 3], nn[(j + 2) % 3]))
            if min(w) < -TOL:
                why = "point outside its element %d (weights %s)" % (ie, w)
            elif abs(w[j]) > TOL:
                why = "point not on a side of its element %d (weights %s)" % (ie, w)
            elif side not in per_side:
                why = "on side %s of element %d, not a side of the list" % (sorted(side), ie)
            else:
                per_side[side] += 1
        if why:
            nbad += 1
            if nbad <= 5:
                print("  t=%r id %d: %s" % (t, pid, why))
nempty = sorted(sorted(s) for s, n in per_side.items() if n == 0)
print("  released particles %d, on a side of the list in its element: %d, wrong: %d"
      % (nins, nins - nbad, nbad))
print("  sides of the list with no particle: %d %s" % (len(nempty), nempty[:5]))
# every side gets particles by length (lgrpps > 0); per volume (case ppv)
# only the sides with an inflow do
if nins == 0 or nbad or (nempty and case != "ppv"):
    ok = False
sys.exit(0 if ok else 1)
EOP
  else
    fail "$c: no particle file"
  fi
  done

  echo "=== the same with kbound = 98 100 99 101 (no side of the basin boundary: nothing to release on)"
  ( cd "$W" && timeout 300 nice -n 10 shyfem bnd_two.str > bnd_two.log 2>&1 )
  lrc=$?
  echo "  exit code $lrc"
  [ "$lrc" != 0 ] || fail "kbound = 98 100 99 101: exit code 0, expected non-zero"
  grep -m3 "warning lagrange: boundary 1" "$W/bnd_two.log" | sed 's/^/  /'
  grep -m2 "has lgrpps but no\|error stop lgr_release_line\|STOP" "$W/bnd_two.log" | sed 's/^/  /'
  grep -q "error stop lgr_release_line: no boundary side to release on" "$W/bnd_two.log" \
    || fail "kbound = 98 100 99 101: no 'error stop lgr_release_line: no boundary side to release on'"
  grep -q "simulation end" "$W/bnd_two.log" && fail "kbound = 98 100 99 101: the run ended instead of stopping"
  finish
fi
