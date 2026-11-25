#!/bin/bash
#------------------------------------------------------------------------
# The vertical random walk of ilagr = 3 keeps particles that are evenly
# spread over the depth evenly spread (issue #284): a well-mixed state
# must stay well mixed.  Five modes:
#
#   const      (the default, #284) a diffusivity constant over the depth,
#              in still water
#   linear     (#286) a linear profile of the diffusivity, in the forced
#              mm_hyd_41 with the particles not advected
#   parabolic  (#286) a parabolic profile, the same case
#   gotm       (#286) GOTM's diffusivity, the same case
#   thin       (#287) the walk spreads the particles at its diffusivity in
#              layers 0.5 m thick (constant diffusivity, still water)
#
#========================= mode const (the default) =====================
# Case: mm_hyd_41 (19 levels, 1 m down to 10 m, then 12, 15, 20, 30, ...
# 80 m: the layers thicken downward) without its tilt lines, for one day,
# in still water: no wind, heat flux or rain, no evaporation, the open
# level boundary and the river closed (ibtyp = 0), ibarcl = 0; no
# turbulence closure (iturb = 0) with diftur = 1.e-2, so the walk's
# diffusivity (diftur + 1e-6/3, lag_vdiff_ele) is the same at every
# interface for the whole run (#248).  The $lagrg section releases at
# the start nbdy = 2000 particles over the basin, each as ipvert = 20
# particles at the depths (i - 0.5)/20 of its column (39960 particles in
# 1792 elements, so the release is exactly uniform in relative depth),
# ilagr = 3, rwhpar = 0 (no horizontal walk), output every hour.  Two
# runs, lgrseed = 1 and 2 (fixed, so the verdict is the same in every
# run), serially.
#
# Required, for each run:
#   - the run ends (exit code 0 and "simulation end" in its log); its log
#     lists diftur = 0.100000E-01, and its line "lgr vertical diffusion:
#     random walk time step [s] min 300.000 mean 300.000, ... below the
#     model step 0" shows a diffusivity constant over the depth in every
#     element and step (K'' = 0 and K' = 0: neither step rule of
#     lag_vdiff_ele limits the step, and the walk takes the model step in
#     one call of lgr_diff_vert, spec test 1 of #286);
#   - the water is still: every particle keeps the position and element
#     of its release at every output (so its column depth is that of the
#     release: twice the mean depth of the particles released in the
#     element; every depth read lies in 0 ... that column depth);
#   - the release histogram (20 bins of relative depth, depth / column
#     depth) is exactly uniform (chi-square 0), and no particle is lost:
#     every output holds all released particles as active ones;
#   - the walk ran: the mean |dz| of the particles over the first hour
#     (from the release, 300 s before 00:00, to the output at 01:00, T =
#     3900 s), and over every later hour (T = 3600 s), is at least 0.15
#     sqrt(2 K T).  A walk that never moves keeps the uniform release
#     and passes the chi-square test, so this test is what makes that one
#     meaningful; and the two lines of the walk's particle steps (#261)
#     show calls >= particle steps >= 39960 x 288 and no step stopped at
#     the cap or ended by two calls in a row that used no time;
#   - well mixed: the mean chi-square of the 20-bin histogram of the
#     active particles over the hourly outputs 12:00 ... 24:00 is at most
#     31 (19 degrees of freedom: 19 +- 6 per output if well mixed).
#
# Since #286 a call of lgr_diff_vert makes one displacement across the
# layer interfaces, reflected at the surface and at the bed: here, at a
# constant K, the walk takes the model step in one call (calls = particle
# steps = 39960 x 289 = 11548440, at most 1 call and 1 draw in a step).
# Measured (mean chi-square 12:00 ... 24:00 for lgrseed 1, 2, 3; mean
# |dz| over the first hour / sqrt(2 K T), seed 1):
#                                       seed 1  seed 2  seed 3   |dz|
#   the walk of #286 (one call a step)    19.9    19.5    20.7  0.409
#   before #286, the walk that stopped at every interface:
#   origin/main 668acb4d                 331.4   313.1   371.4  0.315
#   thickness of the layer entered only   53.5    56.0    42.5  0.311
#   time tv**2/dt of a stopped call only 605.7   563.0          0.328
#   both (the fix of #284)                20.4    18.6    17.7  0.324
#   a walk that never moves                0.0     0.0          0.000
# (the walk of #286: the upper / lower 15 % of the column at 1.004 /
# 0.993 of uniform for seed 1; |dz| 0.406 and 0.411 for seeds 2 and 3;
# the run takes about 25 s.)  The limit 31 lies 10.3 above the highest
# value of the walk of #286, 10.6 above that of the fix of #284 and 11.5
# below the lowest of the thickness alone; the floor 0.15 is about half
# of what the walks that move give.  The walk of #286 gives 0.41, what a
# gaussian walk with the diffusivity K, reflected at the surface and
# bottom, gives; the walk before spread the particles more slowly than
# that, before and after #284 (the variance of the hourly displacement of
# particles far from the surface and bottom about 0.75 of 2 K T, issue
# #287; mode thin).
# Before #284 (origin/main 668acb4d) the particles drifted to the bottom
# (11 % too few in the upper 15 % of the column, 10 % too many in the
# lower 15 %).  Of the two defects of the walk then, the first drove them
# down: after a particle crossed an interface it went on with the
# thickness of the layer it left (with only the second fixed the upper /
# lower 15 % are at 0.842 / 1.130 of uniform).  The second, a call that
# stopped at an interface counted the time tv in which it had diffused
# for tv**2/dt, alone drove them up (with only the first fixed: 1.045 /
# 0.979), so it partly masked the first.  Both went with the stops (#286).
#
#================= modes linear, parabolic and gotm (#286) ================
# Case: the forced mm_hyd_41 as it is (GOTM, iturb = 1; wind, heat flux,
# rain and evaporation; the open level boundary and the river as in the
# STR) without its tilt lines, for one day, with the hydro output every
# hour (idtout = '1h': lgr_vprof.read_geom takes the geometry from its
# header) and the $lagrg section of mode const (39960 particles uniform
# in relative depth at the release, ilagr = 3, rwhpar = 0, output every
# hour).  This is the case the measurements of #286 ran (lgr_wm.str in
# docs/investigation/2026-11-lgr-walk-redesign/str; it differs only in
# the run name, the lgrseed line and idtout = '3h').  Three runs, lgrseed
# = 1, 2 and 3, in parallel (at most 7200 s each).  The particles are not
# advected (test hook LGR_TEST_NOADV=1, read once at the start by
# lgr_mpi_init): only the vertical walk moves them, in a column whose
# depth follows the water level.  The diffusivity of the walk at the
# interfaces of every element, with s = depth of the interface / column
# depth, is
#   linear     test hook LGR_TEST_KPROF=1: K = 1e-3 + 2e-2 s [m**2/s]
#   parabolic  test hook LGR_TEST_KPROF=2: K = 1e-3 + 8e-2 s (1 - s)
#   gotm       GOTM's (LGR_TEST_KPROF unset)
# Where K changes over the depth, a random walk keeps a well-mixed state
# well mixed only if it takes the gradient of K into account correctly
# (Visser 1997); the walk before #286 did not.  These profiles are the
# ones the measurements of #286 used.
#
# Required, for each run:
#   - the run ends (exit code 0 and "simulation end" in its log);
#   - the hooks took: the log holds the master's line " test hook
#     LGR_TEST_NOADV: particles are not advected" and, in modes linear
#     and parabolic, " test hook LGR_TEST_KPROF: the vertical diffusivity
#     of the particles is profile N" with N = 1 or 2 (in mode gotm no such
#     line).  A binary without the hooks would measure another case and
#     could pass.  And no particle is advected: every active particle
#     keeps the position and element of its release at every output;
#   - 39960 particles released, all of them active (none exited) at
#     every output;
#   - well mixed: the mean over the 13 hourly outputs 12:00 ... 24:00 of
#     the chi-square of the 20-bin histogram of the relative depth of all
#     active particles (unweighted) is below 31, the limit of mode const.
#     The relative depth (lgr_vprof.rel_depths) is the depth over the
#     column depth in the particle's column at the output time; the
#     particle file holds no water level, so it is recovered from the
#     particle records.
# Printed for each run, not gated: the walk's lines of the log
# (lgr_vdiff_stats: the random walk time step, the step rule's gradient
# term, the particle steps and calls of lgr_diff_vert, the cap); the top
# 5 % ratio (the share of the particles in the upper 5 % of the column
# over 5 %), mean over 12:00 ... 24:00; and in mode gotm the mean
# chi-square of the particles in one-layer columns, with their number (a
# one-layer column must stay well mixed too; no measured spread exists to
# set a limit from).
#
# Measured (mean chi-square 12:00 ... 24:00 for lgrseed 1, 2, 3; top 5 %
# ratio of seed 1):
#                                        seed 1  seed 2  seed 3  top 5 %
#   the walk of #286, linear               25.4    22.0    21.7   1.019
#                     parabolic            20.3    20.5    18.6   1.007
#                     gotm                 18.8    22.0    19.6   1.036
#   the walk before (#284), linear       3196.7  3206.9  3383.4   0.437
#                           parabolic     147.2   124.6   128.1   0.844
#                           gotm           17.6    20.8    19.0   0.981
# The walk of #286 made 112.6 calls per particle step in mode linear
# (most 1501 in a step; the gradient term of the step set it in 735504
# element steps, its floor 0.2 s in 23575), 426.5 in parabolic (700536,
# 65889) and 162.8 in gotm (528351, 35052), and no step reached the cap;
# the walk before 2.55 in linear and 76.8 in parabolic (34103497 with
# these hooks).  The measurements of #286, an in-model histogram of the
# same relative depths on a debug build of 97a7ad46, gave with the walk
# before linear 3198 and parabolic 148 (seed 1), gotm 17.6 and 20.8
# (seeds 1, 2), and with the prototype of the walk of #286 (B07: f =
# 0.07, floors 2 s and 0.2 s) linear 25.3, 21.8, 21.6, parabolic 20.4,
# 20.6, 18.6 and gotm 18.7, 21.9, 19.5 (top 5 % 1.036, 1.052, 1.034):
# the walk of #286 reproduces each seed within 0.2.  Its top 5 % for
# seeds 1, 2, 3: linear 1.019, 1.023, 1.034, parabolic 1.007, 1.008,
# 1.006, gotm 1.036, 1.052, 1.034.  With GOTM's K that is a small surface
# excess the walk before did not have (0.98) and whose cause is not known
# (spec of #286, section 6); it is printed and not gated.
# Mode gotm passes with the walk before too: it guards against a
# regression and does not show the fix.  Its one-layer columns (1400
# particles) gave 18.0, 20.8 and 19.5 with the walk of #286, 53.3, 54.0
# and 57.4 with the walk before (which put a particle that reached the
# edge of a one-layer column at a random depth in it).
#
#=========================== mode thin (#287) ============================
# Case: still water as in mode const (iturb = 0, diftur = 1.e-2), but with
# uniform levels 0.5 m apart, in the STR down to 75 m (0.5 1 1.5 ... 75,
# 150 levels; the deepest point is 74.62 m).  The model adds the 0.12 m
# below 74.5 m in the deepest elements to the layer above (a last layer
# thinner than hlvmin = 0.25 of its regular thickness, set_last_layer),
# so the run has 149 levels, 0.5 ... 74.5 m.  One run, lgrseed = 1 (at
# most 3600 s), no test hook.  At constant K the walk must spread the
# particles at K whatever the thickness of the layers (#287: it did not).
#
# Required:
#   - the run ends; its log lists diftur = 0.100000E-01; the hydro header
#     holds the 149 levels 0.5, 1, ... 74.5 m;
#   - still water and no particle lost, as in mode const (every particle
#     keeps the position and element of its release; every output holds
#     all released particles as active ones);
#   - K_eff/K within 0.1 of 1.  K_eff (the method of the measurements of
#     #287) is the mean over the 23 pairs of consecutive hourly outputs of
#     sum(dz**2) / n / (2 dt), dt = 3600 s, over the n particles that lie
#     at least 3 sigma = 3 sqrt(2 K dt) (25.5 m) below the surface and
#     above the bed at the start of the hour; dz is their change of depth
#     over the hour, and the column depth is that of mode const (twice
#     the mean depth of the particles released in the element).
# Printed, not gated: the walk's lines of the log, as in the modes above.
#
# Measured (K_eff/K, lgrseed 1): the walk of #286 1.016 +- 0.026
# (standard error of the mean of the 23 hourly values, 0.782 ... 1.337;
# about 201 particles per hour far enough from the surface and the bed;
# one call per particle step: at a constant K the walk takes the model
# step); the walk before (#284; 34103497 with the hooks of the other
# modes) 0.142 +- 0.003 (0.113 ... 0.172; about 199 particles per hour).
# The measurements of #287 gave 0.142 for main and 1.02 +- 0.02 for the
# prototype of the walk of #286 (NOSTOP).
#
# Usage:  ./check_lgr_wellmixed.sh [const | linear | parabolic | gotm | thin]
# Needs shyfem and python3 on PATH (python3 with numpy for every mode but
# const) and `make init` done.  The scratch folder is made with mktemp
# under ${TMPDIR:-/tmp}; it is removed at the end when the check passes
# and kept (its path is printed) when it fails.
# Takes about half a minute and 200 MB of scratch space in mode const;
# with the walk of #286 (wall clock, the runs of a mode in parallel,
# measured with all modes running at once on 28 cores) about 5 minutes in
# mode linear, 7 in gotm, 15 in parabolic and under a minute in thin, and
# up to 250 MB of scratch space.  A run of the modes linear, parabolic and
# gotm stops after 7200 s (the walk can make several hundred calls per
# particle step there), of mode thin after 3600 s.
# Prints "WELLMIXED: PASS" (exit 0) or "WELLMIXED: FAIL" (exit 1) in mode
# const, and in the others the same with the mode's name after WELLMIXED,
# e.g. "WELLMIXED linear: PASS" or "WELLMIXED linear: FAIL".
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "  FAIL: $*"; rc=1; }
CHI2MAX=31
DZFLOOR=0.15
SEEDS="1 2"
SEEDS_FORCED="1 2 3"	# modes linear, parabolic and gotm
KEFFTOL=0.1		# mode thin: |K_eff/K - 1| at most

MODE="${1:-const}"
case "$MODE" in
  const|linear|parabolic|gotm|thin) ;;
  *) echo "usage: $0 [const | linear | parabolic | gotm | thin]"; exit 2 ;;
esac
LABEL="WELLMIXED"
[ "$MODE" = const ] || LABEL="WELLMIXED $MODE"

command -v shyfem > /dev/null 2>&1 || { echo "$LABEL: FAIL (shyfem is not on PATH)"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "$LABEL: FAIL (python3 is not on PATH)"; exit 1; }
if [ "$MODE" != const ]; then
  python3 -c 'import numpy' > /dev/null 2>&1 || { echo "$LABEL: FAIL (python3 cannot import numpy)"; exit 1; }
fi
[ -f "$HERE/GRID/MM_coarse_smooth.bas" ] \
  || { echo "$LABEL: FAIL (GRID/MM_coarse_smooth.bas is missing: run 'make init' in $HERE)"; exit 1; }

P="$(mktemp -d "${TMPDIR:-/tmp}/check_wellmixed.XXXXXX")" || exit 1
finish() {
  if [ "$rc" = 0 ]; then
    rm -rf "$P"
    echo "$LABEL: PASS"
  else
    echo "  logs kept in $P"
    echo "$LABEL: FAIL"
  fi
  exit "$rc"
}
ln -s "$HERE/GRID" "$P/GRID" && ln -s "$HERE/INPUT" "$P/INPUT" || { fail "cannot link GRID and INPUT"; finish; }

# mk NAME SEED: NAME.str from mm_hyd_41.str (still water, iturb = 0,
# diftur = 1.e-2, one day) with the $lagrg section
mk() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e 's/^\([[:space:]]*\)ibarcl = 3/\1ibarcl = 0/' \
      -e 's/^\([[:space:]]*\)iturb = 1      ievap = 1 /\1iturb = 0      ievap = 0 /' \
      -e 's/^\([[:space:]]*\)iturb = 0 .*/&\n\1diftur = 1.e-2   vistur = 1.e-3/' \
      -e 's/^\([[:space:]]*\)ibtyp = [13][[:space:]]*$/\1ibtyp = 0/' \
      -e '/^[[:space:]]*wind[[:space:]]*=/d' -e '/^[[:space:]]*qflux[[:space:]]*=/d' \
      -e '/^[[:space:]]*rain[[:space:]]*=/d' "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 50000\n        nbdy = 2000  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = 20\n        lgrseed = %s\n$end\n' \
    "'1h'" "$2" >> "$P/$1.str" || return 1
  # every edit took
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" || return 1
  for o in 'ibarcl = 0' 'iturb = 0      ievap = 0' 'diftur = 1.e-2' "lgrseed = $2"; do
    grep -qF -- "$o" "$P/$1.str" || return 1
  done
  [ "$(grep -c 'ibtyp = 0' "$P/$1.str")" = 2 ] || return 1
  ! grep -q 'tilt\|wind\|qflux\|rain\|ibtyp = [13]' "$P/$1.str"
}

#================= modes linear, parabolic and gotm (#286) ================
# mkf NAME SEED: NAME.str from mm_hyd_41.str (forced as it is, without
# its tilt lines, one day, hydro output every hour) with the $lagrg
# section of mode const
mkf() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e "s/idtout = '[^']*'/idtout = '1h'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 50000\n        nbdy = 2000  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = 20\n        lgrseed = %s\n$end\n' \
    "'1h'" "$2" >> "$P/$1.str" || return 1
  # every edit took, and the forcing is kept
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" || return 1
  for o in "itend = '2009-01-02'" "idtout = '1h'" "lgrseed = $2" 'ibarcl = 3' \
           'iturb = 1      ievap = 1 ' "wind='INPUT/wind09.txt'" "qflux='INPUT/qflux09.txt'" \
           "rain='INPUT/rain09.txt'" "gotmpa = 'INPUT/gotmturb.nml'"; do
    grep -qF -- "$o" "$P/$1.str" || return 1
  done
  [ "$(grep -c 'ibtyp = [13]' "$P/$1.str")" = 2 ] || return 1
  ! grep -q 'tilt' "$P/$1.str"
}

if [ "$MODE" = linear ] || [ "$MODE" = parabolic ] || [ "$MODE" = gotm ]; then
  KPROF=0
  [ "$MODE" = linear ] && KPROF=1
  [ "$MODE" = parabolic ] && KPROF=2
  for s in $SEEDS_FORCED; do
    mkf f_s$s $s || { fail "cannot make f_s$s.str"; finish; }
  done
  # the hooks are set (or unset) explicitly: a hook inherited from the
  # caller's environment would measure another case
  for s in $SEEDS_FORCED; do
    if [ "$KPROF" = 0 ]; then
      ( cd "$P" && timeout 7200 nice -n 10 env -u LGR_TEST_KPROF LGR_TEST_NOADV=1 \
          shyfem f_s$s.str < /dev/null > f_s$s.log 2>&1; echo $? > f_s$s.rc ) &
    else
      ( cd "$P" && timeout 7200 nice -n 10 env LGR_TEST_NOADV=1 LGR_TEST_KPROF=$KPROF \
          shyfem f_s$s.str < /dev/null > f_s$s.log 2>&1; echo $? > f_s$s.rc ) &
    fi
  done
  wait
  for s in $SEEDS_FORCED; do
    c=f_s$s; log="$P/$c.log"
    echo "=== $c: forced mm_hyd_41, particles not advected, diffusivity $MODE, ilagr = 3, lgrseed = $s, one day"
    if [ "$(cat "$P/$c.rc" 2> /dev/null)" != 0 ] || ! grep -q "simulation end" "$log"; then
      tail -5 "$log" | sed 's/^/    /'; fail "$c did not end (exit code $(cat "$P/$c.rc" 2> /dev/null))"; continue
    fi
    # the hooks took (lgr_mpi_init writes these lines)
    grep -qxF ' test hook LGR_TEST_NOADV: particles are not advected' "$log" \
      || fail "$c: the log does not acknowledge the test hook LGR_TEST_NOADV (a binary without the hooks?)"
    if [ "$KPROF" = 0 ]; then
      if grep -q 'test hook LGR_TEST_KPROF' "$log"; then
        fail "$c: the log acknowledges the test hook LGR_TEST_KPROF: the diffusivity is not GOTM's"
      fi
    else
      grep -qxF " test hook LGR_TEST_KPROF: the vertical diffusivity of the particles is profile $KPROF" "$log" \
        || fail "$c: the log does not acknowledge the test hook LGR_TEST_KPROF with profile $KPROF (a binary without the hooks?)"
    fi
    # the walk's lines (lgr_vdiff_stats: step, step rule, calls), not gated
    grep 'lgr vertical diffusion' "$log" | sed 's/^/  /'
    PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$P/$c.hydro.shy" "$CHI2MAX" "$MODE" <<'EOF' || fail "$c: see above"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
import lgr_vprof as lv

path, gpath, chi2max, mode = sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
NPART = 39960
ok = True
geom = lv.read_geom(gpath)
ilhv = geom["ilhv"]
_, times = lc.read_file(path)
rel = {}		# release records (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1])
print("  released %d particles, %d outputs (%.0f ... %.0f s)"
      % (len(rel), len(times), times[0][0], times[-1][0]))
if len(rel) != NPART:
    print("  FAIL: %d particles released, expected %d" % (len(rel), NPART))
    ok = False
nlost = nmove = 0
for t, b, _ in times:
    if len(b[0]) != len(rel) or b[1]:
        nlost += 1
    for pid, p in b[0].items():
        r = rel.get(pid)
        if r is None or (p["x"], p["y"], p["ie"]) != (r["x"], r["y"], r["ie"]):
            nmove += 1
print("  outputs that do not hold all %d particles as active ones: %d;"
      " active records that left their release position or element: %d"
      % (len(rel), nlost, nmove))
if nlost:
    print("  FAIL: particles lost or exited (the chi-square would leave them out)")
    ok = False
if nmove:
    print("  FAIL: particles were advected (LGR_TEST_NOADV did not take)")
    ok = False

late = []
nout = 0
for (t, b, _), rows in zip(times, lv.rel_depths(times, geom)):
    s = [x[1] for x in rows]
    nout += sum(1 for v in s if v < -1.e-5 or v > 1.0 + 1.e-5)
    if 43200.0 <= t <= 86400.0:
        one = [x[1] for x in rows if ilhv[b[0][x[0]]["ie"] - 1] == 1]
        late.append((t, lv.chi2(s), lv.bin_ratio(s, None, 0, 1), lv.chi2(one), len(one)))
print("  relative depths outside 0 ... 1 (all outputs, not gated): %d" % nout)
if len(late) != 13:
    print("  FAIL: %d outputs in 12:00 ... 24:00, expected 13" % len(late))
    ok = False
else:
    m = sum(x[1] for x in late) / len(late)
    top = sum(x[2] for x in late) / len(late)
    print("  well mixed: mean chi-square over 12:00 ... 24:00 %.1f (limit: below %.0f;"
          " per output %.1f ... %.1f); top 5 %% of the column %.3f of uniform"
          % (m, chi2max, min(x[1] for x in late), max(x[1] for x in late), top))
    if mode == "gotm":
        print("  one-layer columns (not gated): mean chi-square over 12:00 ... 24:00 %.1f,"
              " %d particles" % (sum(x[3] for x in late) / len(late), late[-1][4]))
    if not m < chi2max:
        print("  FAIL: not well mixed")
        ok = False
sys.exit(0 if ok else 1)
EOF
  done
  finish
fi

#=========================== mode thin (#287) ============================
if [ "$MODE" = thin ]; then
  c=thin_s1; log="$P/$c.log"
  mk $c 1 || { fail "cannot make $c.str"; finish; }
  # the levels of mm_hyd_41 replaced by 0.5 1 1.5 ... 75 (the first level
  # at or below the deepest point, 74.62 m), ten to a line
  awk '
    /^[[:space:]]*1 2 3 4 5 6 7 8 9 10 12 15 20 30 40 50 60 70 80[[:space:]]*$/ {
      line = "       "; n = 0
      for( i = 1; ; i++ ) {
        v = i * 0.5; line = line " " sprintf("%g", v); n++
        if( v >= 74.62 ) { print line; break }
        if( n == 10 ) { print line; line = "       "; n = 0 }
      }
      nrep++; next
    }
    { print }
    END { if( nrep != 1 ) exit 1 }' "$P/$c.str" > "$P/$c.tmp" && mv "$P/$c.tmp" "$P/$c.str" \
    || { fail "cannot set the levels of $c.str"; finish; }
  nlev="$(awk '/^\$levels/ { f = 1; next } /^\$end/ { f = 0 } f { n += NF } END { print n + 0 }' "$P/$c.str")"
  [ "$nlev" = 150 ] || { fail "$c.str has $nlev levels, expected 150"; finish; }
  grep -qx '        70.5 71 71.5 72 72.5 73 73.5 74 74.5 75' "$P/$c.str" \
    || { fail "$c.str: the levels do not end at 75 m"; finish; }
  if awk '/^\$levels/ { f = 1; next } /^\$end/ { f = 0 } f && length > 79 { b = 1 } END { exit !b }' "$P/$c.str"; then
    fail "$c.str: a line of levels is longer than 79 characters"; finish
  fi
  ( cd "$P" && timeout 3600 nice -n 10 env -u LGR_TEST_KPROF -u LGR_TEST_NOADV \
      shyfem $c.str < /dev/null > $c.log 2>&1; echo $? > $c.rc )
  echo "=== $c: mm_hyd_41 in still water, levels 0.5 m apart, iturb = 0, diftur = 1.e-2, ilagr = 3, lgrseed = 1, one day"
  if [ "$(cat "$P/$c.rc" 2> /dev/null)" != 0 ] || ! grep -q "simulation end" "$log"; then
    tail -5 "$log" | sed 's/^/    /'; fail "$c did not end (exit code $(cat "$P/$c.rc" 2> /dev/null))"; finish
  fi
  grep -q "diftur *= *0\.100000E-01" "$log" || fail "$c: the log does not list diftur = 0.100000E-01"
  if grep -q 'test hook LGR_TEST_\(KPROF\|NOADV\)' "$log"; then
    fail "$c: the log acknowledges a test hook LGR_TEST_KPROF or LGR_TEST_NOADV"
  fi
  # the walk's lines (lgr_vdiff_stats: step, step rule, calls), not gated
  grep 'lgr vertical diffusion' "$log" | sed 's/^/  /'
  PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$P/$c.hydro.shy" "$KEFFTOL" <<'EOF' || fail "$c: see above"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
import lgr_vprof as lv

path, gpath, tol = sys.argv[2], sys.argv[3], float(sys.argv[4])
K = 1.e-2		# diftur
ok = True
hlv = [float(v) for v in lv.read_geom(gpath)["hlv"]]
bad = [k for k in range(len(hlv)) if abs(hlv[k] - 0.5 * (k + 1)) > 1.e-4]
print("  levels in the hydro header: %d, %.2f ... %.2f m" % (len(hlv), hlv[0], hlv[-1]))
if len(hlv) != 149 or bad:
    print("  FAIL: not the 149 levels 0.5, 1, ... 74.5 m")
    ok = False
_, times = lc.read_file(path)
rel = {}		# release records (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1])
# column depth of an element: 2 x the mean depth of the particles
# released in it (depths (i - 0.5)/20 of the column)
acc = {}
for p in rel.values():
    a = acc.setdefault(p["ie"], [0.0, 0])
    a[0] += p["hl"]
    a[1] += 1
ht = dict((ie, 2.0 * a[0] / a[1]) for ie, a in acc.items())
print("  released %d particles in %d elements (column depth %.2f ... %.2f m), %d outputs"
      % (len(rel), len(ht), min(ht.values()), max(ht.values()), len(times)))
if len(rel) < 39000:
    print("  FAIL: fewer than 39000 particles released")
    ok = False
nmove = nout = nlost = 0
for t, b, _ in times:
    if len(b[0]) != len(rel) or b[1]:
        nlost += 1
    for pid, p in b[0].items():
        r = rel[pid]
        if (p["x"], p["y"], p["ie"]) != (r["x"], r["y"], r["ie"]):
            nmove += 1
        q = p["hl"] / ht[p["ie"]]
        if q < -1.e-5 or q > 1.0 + 1.e-5:
            nout += 1
print("  still water: records that left their release position or element %d;"
      " depths outside their column %d; outputs that do not hold all particles"
      " as active ones %d" % (nmove, nout, nlost))
if nmove or nout or nlost:
    print("  FAIL: the water is not still or particles were lost")
    ok = False

# K_eff: hourly mean-square displacement of the particles far from the
# surface and the bed (at least 3 sigma at the start of the hour)
ks = []
prev = None
for t, b, _ in times:
    if prev is not None and b[0]:
        dt = t - prev[0]
        sig = math.sqrt(2.0 * K * dt)
        sq = 0.0
        n = 0
        for pid, p in b[0].items():
            q = prev[1].get(pid)
            if q is None:
                continue
            h = ht[p["ie"]]
            if q["hl"] < 3.0 * sig or h - q["hl"] < 3.0 * sig:
                continue
            d = p["hl"] - q["hl"]
            sq += d * d
            n += 1
        ks.append((dt, n, sq / n / (2.0 * dt) / K if n > 1 else float("nan")))
    prev = (t, b[0])
nbad = sum(1 for dt, n, _ in ks if dt != 3600.0 or n < 2)
if len(ks) != 23 or nbad:
    print("  FAIL: %d pairs of hourly outputs (expected 23), %d of them not 3600 s apart"
          " or with fewer than 2 particles far from the surface and the bed" % (len(ks), nbad))
    ok = False
else:
    v = [k for _, _, k in ks]
    m = sum(v) / len(v)
    se = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1) / len(v))
    print("  K_eff/K %.3f +- %.3f (SE) over %d hourly pairs (hourly %.3f ... %.3f), %.0f"
          " particles per hour at least 3 sigma = %.2f m from the surface and the bed"
          " (limit: within %.2f of 1)"
          % (m, se, len(v), min(v), max(v), sum(n for _, n, _ in ks) / float(len(ks)),
             3.0 * math.sqrt(2.0 * K * 3600.0), tol))
    if not abs(m - 1.0) <= tol:
        print("  FAIL: the walk does not spread the particles at its diffusivity")
        ok = False
sys.exit(0 if ok else 1)
EOF
  finish
fi

for s in $SEEDS; do
  mk wm_s$s $s || { fail "cannot make wm_s$s.str"; finish; }
done
for s in $SEEDS; do
  ( cd "$P" && timeout 1800 nice -n 10 env -u LGR_TEST_KPROF -u LGR_TEST_NOADV \
      shyfem wm_s$s.str < /dev/null > wm_s$s.log 2>&1; echo $? > wm_s$s.rc ) &
done
wait
for s in $SEEDS; do
  c=wm_s$s; log="$P/$c.log"
  echo "=== $c: mm_hyd_41 in still water, iturb = 0, diftur = 1.e-2, ilagr = 3, lgrseed = $s, one day"
  if [ "$(cat "$P/$c.rc" 2> /dev/null)" != 0 ] || ! grep -q "simulation end" "$log"; then
    tail -5 "$log" | sed 's/^/    /'; fail "$c did not end (exit code $(cat "$P/$c.rc" 2> /dev/null))"; continue
  fi
  grep -q "diftur *= *0\.100000E-01" "$log" || fail "$c: the log does not list diftur = 0.100000E-01"
  line="$(grep -m1 'lgr vertical diffusion: random walk time step' "$log")"
  echo "  ${line:-no line 'lgr vertical diffusion: random walk time step' in the log}"
  echo "$line" | grep -Eq 'min 300\.0* mean 300\.0*,.* below the model step 0( |$)' \
    || fail "$c: the diffusivity is not constant over the depth (random walk time step below 300 s)"
  # the walk's particle steps (#261): it ran in every step, to the end
  l1="$(grep 'lgr vertical diffusion: particle steps:' "$log")"
  l2="$(grep 'lgr vertical diffusion: steps stopped at the cap of' "$log")"
  echo "  ${l1:-no line 'lgr vertical diffusion: particle steps:' in the log}"
  echo "  ${l2:-no line 'lgr vertical diffusion: steps stopped at the cap of' in the log}"
  nst="$(printf '%s' "$l1" | sed -n 's/.*particle steps: *\([0-9][0-9]*\),.*/\1/p')"
  ncl="$(printf '%s' "$l1" | sed -n 's/.*, calls: *\([0-9][0-9]*\),.*/\1/p')"
  ncap="$(printf '%s' "$l2" | sed -n 's/.*steps stopped at the cap of [0-9]* calls: *\([0-9][0-9]*\),.*/\1/p')"
  nend="$(printf '%s' "$l2" | sed -n 's/.*steps ended by 2 calls in a row that used no time: *\([0-9][0-9]*\),.*/\1/p')"
  if [ -z "$nst" ] || [ -z "$ncl" ] || [ "$nst" -lt $((39960 * 288)) ] || [ "$ncl" -lt "$nst" ]; then
    fail "$c: particle steps ${nst:-not reported} and calls ${ncl:-not reported}, expected calls >= particle steps >= 39960 x 288"
  fi
  [ "${ncap:-x}" = 0 ] || fail "$c: particle steps stopped at the cap ${ncap:-not reported}, expected 0"
  [ "${nend:-x}" = 0 ] || fail "$c: particle steps ended by two calls in a row that used no time ${nend:-not reported}, expected 0"
  PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$CHI2MAX" "$DZFLOOR" <<'EOF' || fail "$c: see above"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc

path, chi2max, dzfloor = sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
K = 1.e-2		# diftur
NB = 20
ok = True
_, times = lc.read_file(path)
rel = {}		# release records (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1])
# column depth of an element: 2 x the mean depth of the particles
# released in it (depths (i - 0.5)/20 of the column)
acc = {}
for p in rel.values():
    a = acc.setdefault(p["ie"], [0.0, 0])
    a[0] += p["hl"]
    a[1] += 1
ht = dict((ie, 2.0 * a[0] / a[1]) for ie, a in acc.items())
print("  released %d particles in %d elements (column depth %.2f ... %.2f m), %d outputs"
      % (len(rel), len(ht), min(ht.values()), max(ht.values()), len(times)))
if len(rel) < 39000:
    print("  FAIL: fewer than 39000 particles released")
    ok = False

nmove = nout = 0
def hist(parts):
    global nout
    h = [0] * NB
    for p in parts.values():
        r = p["hl"] / ht[p["ie"]]
        if r < -1.e-5 or r > 1.0 + 1.e-5:
            nout += 1
        h[min(max(int(r * NB), 0), NB - 1)] += 1
    return h
def chi2(h):
    e = sum(h) / float(NB)
    return sum((x - e) ** 2 / e for x in h) if e > 0 else 0.0

c0 = chi2(hist(rel))
late = []
nlost = 0
for t, b, _ in times:
    if len(b[0]) != len(rel) or b[1]:
        nlost += 1
    for pid, p in b[0].items():
        r = rel[pid]
        if (p["x"], p["y"], p["ie"]) != (r["x"], r["y"], r["ie"]):
            nmove += 1
    h = hist(b[0])		# every output: depths inside their column
    if 43200.0 <= t <= 86400.0:
        late.append((t, chi2(h), h))
print("  still water: records that left their release position or element %d;"
      " depths outside their column %d" % (nmove, nout))
if nmove or nout:
    print("  FAIL: the water is not still (the column depth of the release does not apply)")
    ok = False
print("  outputs that do not hold all %d particles as active ones: %d" % (len(rel), nlost))
if nlost:
    print("  FAIL: particles lost (the chi-square would leave them out)")
    ok = False
print("  release: chi-square %.3f" % c0)
if c0 != 0.0:
    print("  FAIL: the release is not exactly uniform over the depth")
    ok = False

# the walk ran: mean |dz| over the first output
t1, b1 = next((t, b[0]) for t, b, _ in times if b[0])
T = t1 - min(p["tt"] for p in rel.values())
dz = sum(abs(p["hl"] - rel[pid]["hl"]) for pid, p in b1.items()) / len(b1)
s = math.sqrt(2.0 * K * T)
print("  the walk ran: mean |dz| over the first %.0f s %.4f m = %.3f sqrt(2 K T) (floor %.2f)"
      % (T, dz, dz / s, dzfloor))
if not dz >= dzfloor * s:
    print("  FAIL: the particles did not move (a walk that never moves keeps the uniform release)")
    ok = False
# and over every later hour
rmin = None
prev = None
for t, b, _ in times:
    if prev is not None and b[0]:
        dt = t - prev[0]
        n = 0
        acc = 0.0
        for pid, p in b[0].items():
            q = prev[1].get(pid)
            if q is not None:
                acc += abs(p["hl"] - q["hl"])
                n += 1
        r = (acc / n if n else 0.0) / math.sqrt(2.0 * K * dt)
        if rmin is None or r < rmin[0]:
            rmin = (r, prev[0], t)
    prev = (t, b[0])
if rmin is None:
    print("  FAIL: no two outputs to compare")
    ok = False
else:
    print("  and over every later hour: smallest mean |dz| %.3f sqrt(2 K T) (%.0f ... %.0f s)"
          % rmin)
    if not rmin[0] >= dzfloor:
        print("  FAIL: the particles stopped moving")
        ok = False

# well mixed: mean chi-square over 12:00 ... 24:00
if len(late) != 13:
    print("  FAIL: %d outputs in 12:00 ... 24:00, expected 13" % len(late))
    ok = False
else:
    m = sum(c for _, c, _ in late) / len(late)
    top = sum(sum(h[0:3]) / (3.0 * sum(h) / NB) for _, _, h in late) / len(late)
    bot = sum(sum(h[17:20]) / (3.0 * sum(h) / NB) for _, _, h in late) / len(late)
    print("  well mixed: mean chi-square over 12:00 ... 24:00 %.1f (limit %.0f); density of the"
          " upper / lower 15 %% of the column %.3f / %.3f of uniform" % (m, chi2max, top, bot))
    if not m <= chi2max:
        print("  FAIL: not well mixed")
        ok = False
sys.exit(0 if ok else 1)
EOF
done
finish
