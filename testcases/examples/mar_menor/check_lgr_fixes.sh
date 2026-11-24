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
#             mesh, and create_parts stops there with "error stop
#             create_parts: error in boundary", before and after #252.
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
#             min 2 s, mean 33.5 s, 41.7 sub-steps per 300 s step, 66071 of
#             735505 element steps over 100 sub-steps; before #257 mean
#             24.9 s, 98.4 sub-steps, 396008 over 100).  A second run, 12
#             hours with the end of the particle run itlend = 06:02:30
#             (between two time steps), must write that line exactly once.
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
#             before #257.  2. The 3D case mm_hyd_41
#             as in mode ilagr3 (no tilt, one day, ilagr = 3, nbdy = 300,
#             rwhpar = 0, ipvert = -1) with iturb = 0 and diftur = 1.e-3,
#             serially: the diffusivity is then the same at every
#             interface (today GOTM's initial 1e-6 m2/s: handle_gotm_init,
#             called at set-up whatever iturb, overwrites the diftur that
#             set_eddy put in), so K'' = 0 and the random walk must take
#             the model time step: the log line "lgr vertical diffusion:
#             random walk time step [s] min 300.000 mean 300.000, ...
#             below the model step 0 over 100 sub-steps 0" (written once
#             at the end, lgr_vdiff_stats).  Before #257 the "second
#             derivative" was (K(l+1) + 2 K(l) + K(l-1))/hl(l)**2, about
#             4 K/h**2, so the step was h**2/(400 K) also for a constant K:
#             with the old formula (put back into the fixed code, whose
#             statistics line it keeps) min 2 s and 2424 element steps
#             below the model step, all of them over 100 sub-steps (dtvd
#             under 3 s: elements with a very thin layer, where h**2/(400 K)
#             is that small).  The code before #257 has neither the
#             routine nor the line, so this mode cannot be red on it; its
#             red evidence is the old formula put back.
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
#             (create_parts) is not run: along the whole open boundary of
#             mm_hyd_12a it stops with "error stop create_parts: error in
#             boundary" (also before #225, and after #252: the boundary list
#             skips two boundary nodes, see mode segments, which releases
#             along a part of it).
#
# A run has ended only if its launcher exits with 0 and its log has
# "simulation end".  Needs shyfem, mpirun (Open MPI) and python3 on PATH,
# and `make init` plus (cd GRID && shypre -noopti MM_geo.grd) done here.
# Exit code 0 on PASS, 1 on FAIL, 2 on a usage error.
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
MODE="${1:-}"
NP=4
rc=0

usage() { echo "usage: $0 stk-omp | decay | decay-rate | outside | segments | ilagr3 | vdiff-dt | grow-fail | small-export | seed"; exit 2; }
fail() { echo "  FAIL: $*"; rc=1; }

case "$MODE" in
  stk-omp|decay|decay-rate|outside|segments|ilagr3|vdiff-dt|grow-fail|small-export|seed) ;;
  *) usage ;;
esac

for t in shyfem mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "$MODE: FAIL ($t is not on PATH)"; exit 1; }
done
for b in GRID/MM_geo.bas GRID/MM_coarse.bas GRID/MM_coarse_smooth.bas; do
  [ -f "$HERE/$b" ] || { echo "$MODE: FAIL ($b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE)"; exit 1; }
done

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
  echo "=== mm_hyd_41 (no tilt, one day, iturb = 0: the same diffusivity at every interface) with ilagr = 3, serially"
  if run vdt_const vdt_const.log shyfem; then
    line="$(grep -m1 'lgr vertical diffusion: random walk time step' "$W/vdt_const.log")"
    echo "  ${line:-no line 'lgr vertical diffusion: random walk time step' in the log}"
    echo "$line" | grep -q 'min 300\.000* mean 300\.000*,' || fail "the random walk time step is not the model time step (300 s) everywhere"
    echo "$line" | grep -q ' below the model step 0 over 100 sub-steps 0$' || fail "element steps with a random walk time step below the model step"
  else
    fail "the run did not end"
  fi
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
