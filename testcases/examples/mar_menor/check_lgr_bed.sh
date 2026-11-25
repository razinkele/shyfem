#!/bin/bash
#------------------------------------------------------------------------
# The vertical velocity of ilagr = 3 particles in the bottom layer (#299).
# In the bottom layer of a column of more than one layer the flow's
# vertical velocity is linear in the relative depth z of the layer, from
# the element mean of the interface velocity at the layer top (wt) to 0
# at the bed, and the settling velocity sv of the particle is not
# tapered: w(z) = wt (1 - z) - sv (track_xi, lgr_bed_move, lgr_bed_exit;
# check_lgr_fixes.sh bed-w tests the two routines on their own).  Before,
# the whole bottom layer had the layer mean of w, which does not vanish
# at the bed: an upward mean lifted the particles off the bed and a
# downward one held them there, and the bottom of the column was left
# with about half its share of particles.  Two parts:
#
#========================== part 1: the bottom (#299) ======================
# Case: the closed forced mm_hyd_41: both boundaries closed (ibtyp = 0),
# its tilt lines removed, one day, with GOTM (iturb = 1), wind, heat flux,
# rain and evaporation and the baroclinic terms as in the STR, and the
# $lagrg section of check_lgr_wellmixed.sh: nbdy = 2000 particles
# released at the start over the basin, each as ipvert = 20 particles at
# the depths (i - 0.5)/20 of its column (39960 particles), ilagr = 3,
# rwhpar = 0, output every hour.  This is the case of the measurements of
# #299 (gc_s1.str in docs/investigation/2026-11-lgr-walk-redesign/str;
# the STR made here differs from it only in the run name and the lgrseed
# line).  Two runs, lgrseed = 1 and 2, in parallel (at most 7200 s each).
#
# Required, for each run:
#   - the run ends (exit code 0 and "simulation end" in its log);
#   - 39960 particles released;
#   - the bottom 5 % of the column holds at least 0.80 of its uniform
#     share of the particles at 24:00: bin_ratio(..., 19, 20) of the
#     relative depths of lgr_vprof.rel_depths (the depth of the particle
#     over the depth of its column at the output time) with the weight
#     'rel' (the depth of the release column, the volume the particle
#     stands for), the measure of the measurements of #299 (anaA).
# Printed, not gated: the bottom 15 % at 24:00, and the chi-square of the
# 20-bin histogram with the same weight at 24:00 and its mean over the
# hourly outputs 12:00 ... 24:00.
#
#========================= part 2: settling (#299) =========================
# The bed velocity must not taper the settling velocity: settling is the
# motion of the particle relative to the water, and the bed condition
# belongs to the water.  A tapered form, (wt - sv)(1 - z), makes a
# settling particle in still water approach the bed exponentially and
# never reach it by settling.  The stock settling velocities (ised = 1:
# three classes at 3e-6, 1e-5 and 3e-5 m/s, lagrange_sedim.f90) are too
# slow for "the particles reach the bed" to beat the spread of the walk
# within hours, so this part measures the drift of the settling
# particles instead.
# Case: mm_hyd_41 in still water, as check_lgr_wellmixed.sh const (no
# tilt, wind, heat flux or rain, no evaporation, both boundaries closed,
# ibarcl = 0, iturb = 0), but with diftur = 0. (vistur = 1.e-3): the walk
# sees only its floor K = 1e-6/3 m**2/s at every interface (lag_vdiff_ele:
# (difmol + 3 diftur)/3), and with ised = 1 in $lagrg (each particle gets
# a sediment class, its type, and its settling velocity, s in the particle
# file); the $lagrg section of part 1 otherwise (39960 particles, uniform
# in relative depth), lgrseed = 1, for five hours, output every hour.
# In still water the bottom stress is 0, so lgr_sediment deposits only a
# particle at exactly z = 1 in the bottom layer, and erodes none.
# The particles judged: those of the fastest class (type 3, 3e-5 m/s; the
# type, not the single-precision s, picks it) that start in the bottom
# layer of a column of at least two layers, at a distance d_b = (1 - z0)
# hd above the bed of at least s t + 4 sigma (hd the thickness of the
# bottom layer, hev - hlv(lmax-1) from the hydro header; sigma = sqrt(2 K
# t), the spread of the walk), so that neither the walk nor settling
# brings them to the bed.  t = the output time at 05:00 less the release
# time of the particle, tt of its release record: the release lies 300 s
# before 00:00, so t = 18300 s (asserted).
#
# Required:
#   - the run ends; the water is still (every active particle at 05:00
#     at the position and in the element of its release);
#   - the check can tell the forms apart: at least 300 particles judged
#     (the noise of a particle's drift is about sigma/(s t) = 0.2 of it, so
#     300 give a standard error near 1.2 %), and the drift the tapered form
#     would give, R_tap = sum d_b (1 - exp(-s t/hd)) / sum s t, at most
#     0.85.  Too few particles or too large an R_tap fail the check;
#   - every judged particle is in the water at 05:00 (in its element, a
#     layer >= 1: none deposited);
#   - R = sum (depth at 05:00 - depth at the release) / sum s t, the mean
#     drift over the settling distance, within 0.95 ... 1.05 (untapered
#     settling gives 1).
#
# Measured (2026-11-25), part 1: the bottom 5 % and 15 % at 24:00, the
# chi-square (release-column weight) mean over 12:00 ... 24:00 and at
# 24:00, lgrseed 1 / 2:
#                                bottom 5 %     bottom 15 %   chi-square    at 24:00
#   origin/main 576abae5       0.487 / 0.495  0.754 / 0.754  221.1 / 213.0  450 / 425
#   the walk of #286 and the
#   bed velocity of #299       0.881 / 0.885  0.912 / 0.912   54.5 /  59.1  156 / 155
# The measurements of #299 (anaA, on the particle files of the same case)
# gave 0.49 / 0.49, 221.1 / 213.0 and 450 / 425 for main's walk, and 0.88
# / 0.89, 54.5 / 59.1 and 156 / 155 for the prototype of the walk of #286
# with the prototype of the bed velocity (which tapered sv; sv = 0 here,
# where the two forms are the same): the check reproduces both.  The
# same build without the re-read of w and hd after the layer switch at
# the start of track_xi gives 0.881 / 0.885, 54.5 / 59.1 and 156.1 /
# 154.6.  The chi-square left (55 ... 59; 19 +- 6 if well mixed) is the
# other residuals of #299, not the subject of this check.
# Part 2: 2350 particles of class 3 start in the bottom layer of a column
# of at least two layers, 1067 of them judged; R_tap = 0.586:
#   origin/main 576abae5 (the layer mean, sv not tapered)    R = 0.999
#   the bed velocity of #299 (sv not tapered)                 R = 0.988
#   the bed velocity tapering sv, (wt - sv)(1 - z), put in
#   for the test                                              R = 0.575 (FAIL)
# A run of part 1 takes about 4 minutes (main's about 5, measured with
# the other runs of the check beside it), the run of part 2 a few seconds.
#
# Usage:  ./check_lgr_bed.sh [both | 1 | 2]
# (both, the default: the two parts; 1 or 2: that part only.)  Needs
# shyfem and python3 with numpy on PATH, and `make init` done.  The scratch
# folder is made with mktemp under ${TMPDIR:-/tmp}; it is removed at the
# end when the check passes and kept (its path is printed) when it fails.
# All runs of the check run in parallel.
# Prints "BED: PASS" (exit 0) or "BED: FAIL" (exit 1), with one part
# "BED part 1: PASS" and so on.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "  FAIL: $*"; rc=1; }
BOT5MIN=0.80		# part 1: bottom 5 % at 24:00, at least
SEEDS="1 2"		# part 1
NMIN=300		# part 2: judged particles, at least
RTAPMAX=0.85		# part 2: the tapered expectation, at most
RLO=0.95		# part 2: R within RLO ... RHI
RHI=1.05

PART="${1:-both}"
case "$PART" in
  both|1|2) ;;
  *) echo "usage: $0 [both | 1 | 2]"; exit 2 ;;
esac
LABEL="BED"
[ "$PART" = both ] || LABEL="BED part $PART"

command -v shyfem > /dev/null 2>&1 || { echo "$LABEL: FAIL (shyfem is not on PATH)"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "$LABEL: FAIL (python3 is not on PATH)"; exit 1; }
python3 -c 'import numpy' > /dev/null 2>&1 || { echo "$LABEL: FAIL (python3 cannot import numpy)"; exit 1; }
[ -f "$HERE/GRID/MM_coarse_smooth.bas" ] \
  || { echo "$LABEL: FAIL (GRID/MM_coarse_smooth.bas is missing: run 'make init' in $HERE)"; exit 1; }

P="$(mktemp -d "${TMPDIR:-/tmp}/check_bed.XXXXXX")" || exit 1
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

LAGRG='\n$lagrg\n        ilagr = 3   nbdymax = 50000\n        nbdy = 2000  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = 20\n        lgrseed = %s\n$end\n'

# mkc NAME SEED (part 1): NAME.str from mm_hyd_41.str (forced, both
# boundaries closed, no tilt lines, one day) with the $lagrg section
mkc() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-02'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e 's/^\([[:space:]]*\)ibtyp = [13][[:space:]]*$/\1ibtyp = 0/' "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  printf "$LAGRG" "'1h'" "$2" >> "$P/$1.str" || return 1
  # every edit took, and the forcing is kept
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" || return 1
  for o in "itend = '2009-01-02'" "lgrseed = $2" 'ibarcl = 3' 'iturb = 1      ievap = 1 ' \
           "wind='INPUT/wind09.txt'" "qflux='INPUT/qflux09.txt'" "rain='INPUT/rain09.txt'" \
           "gotmpa = 'INPUT/gotmturb.nml'" 'ipvert = 20'; do
    grep -qF -- "$o" "$P/$1.str" || return 1
  done
  [ "$(grep -c 'ibtyp = 0' "$P/$1.str")" = 2 ] || return 1
  ! grep -q 'tilt\|ibtyp = [13]' "$P/$1.str"
}

# mks NAME SEED (part 2): NAME.str from mm_hyd_41.str (still water,
# iturb = 0, diftur = 0., five hours) with the $lagrg section and ised = 1
mks() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::05:00:00'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e 's/^\([[:space:]]*\)ibarcl = 3/\1ibarcl = 0/' \
      -e 's/^\([[:space:]]*\)iturb = 1      ievap = 1 /\1iturb = 0      ievap = 0 /' \
      -e 's/^\([[:space:]]*\)iturb = 0 .*/&\n\1diftur = 0.   vistur = 1.e-3/' \
      -e 's/^\([[:space:]]*\)ibtyp = [13][[:space:]]*$/\1ibtyp = 0/' \
      -e '/^[[:space:]]*wind[[:space:]]*=/d' -e '/^[[:space:]]*qflux[[:space:]]*=/d' \
      -e '/^[[:space:]]*rain[[:space:]]*=/d' "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  printf "$LAGRG" "'1h'" "$2" | sed 's/^\([[:space:]]*\)lgrseed = .*/&\n\1ised = 1/' >> "$P/$1.str" || return 1
  # every edit took
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" || return 1
  for o in "itend = '2009-01-01::05:00:00'" 'ibarcl = 0' 'iturb = 0      ievap = 0' \
           'diftur = 0.   vistur = 1.e-3' "lgrseed = $2" 'ised = 1' 'ipvert = 20'; do
    grep -qF -- "$o" "$P/$1.str" || return 1
  done
  [ "$(grep -c 'ibtyp = 0' "$P/$1.str")" = 2 ] || return 1
  ! grep -q 'tilt\|wind\|qflux\|rain\|ibtyp = [13]' "$P/$1.str"
}

# the runs of the check, all in parallel; the hooks of
# check_lgr_wellmixed.sh are unset (a hook inherited from the caller's
# environment would measure another case)
RUNS=""
if [ "$PART" != 2 ]; then
  for s in $SEEDS; do
    mkc bc_s$s $s || { fail "cannot make bc_s$s.str"; finish; }
    RUNS="$RUNS bc_s$s:7200"
  done
fi
if [ "$PART" != 1 ]; then
  mks bs_s1 1 || { fail "cannot make bs_s1.str"; finish; }
  RUNS="$RUNS bs_s1:1800"
fi
for r in $RUNS; do
  c="${r%%:*}"; tmax="${r##*:}"
  ( cd "$P" && timeout "$tmax" nice -n 10 env -u LGR_TEST_KPROF -u LGR_TEST_NOADV \
      shyfem $c.str < /dev/null > $c.log 2>&1; echo $? > $c.rc ) &
done
wait

# ended C: the run C ended (exit code 0 and "simulation end" in its log)
ended() {
  if [ "$(cat "$P/$1.rc" 2> /dev/null)" != 0 ] || ! grep -q "simulation end" "$P/$1.log"; then
    tail -5 "$P/$1.log" | sed 's/^/    /'
    fail "$1 did not end (exit code $(cat "$P/$1.rc" 2> /dev/null))"
    return 1
  fi
}

#========================== part 1: the bottom (#299) ======================
if [ "$PART" != 2 ]; then
  for s in $SEEDS; do
    c=bc_s$s
    echo "=== $c: the closed forced mm_hyd_41 (both ibtyp = 0, GOTM, wind), ilagr = 3, lgrseed = $s, one day"
    ended $c || continue
    PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$P/$c.hydro.shy" "$BOT5MIN" <<'EOF' || fail "$c: see above"
import sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
import lgr_vprof as lv

path, gpath, bmin = sys.argv[2], sys.argv[3], float(sys.argv[4])
NPART = 39960
ok = True
geom = lv.read_geom(gpath)
_, times = lc.read_file(path)
rel = {}		# release records (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1])
print("  released %d particles, %d outputs (%.0f ... %.0f s); at the last output %d active,"
      " %d exited" % (len(rel), len(times), times[0][0], times[-1][0], len(times[-1][1][0]),
                      len(times[-1][1][1])))
if len(rel) != NPART:
    print("  FAIL: %d particles released, expected %d" % (len(rel), NPART))
    ok = False
late = []
end = None
for (t, b, _), rows in zip(times, lv.rel_depths(times, geom)):
    s = [x[1] for x in rows]
    w = [x[2] for x in rows]
    if 43200.0 <= t <= 86400.0:
        late.append(lv.chi2(s, w))
    if t == 86400.0:
        end = (lv.bin_ratio(s, w, 19, 20), lv.bin_ratio(s, w, 17, 20), lv.chi2(s, w))
if end is None or len(late) != 13:
    print("  FAIL: no output at 24:00, or %d outputs in 12:00 ... 24:00 (expected 13)" % len(late))
    ok = False
else:
    print("  bottom 5 %% of the column at 24:00: %.3f of uniform (limit: at least %.2f);"
          " bottom 15 %% %.3f" % (end[0], bmin, end[1]))
    print("  chi-square (release-column weight) at 24:00 %.1f, mean over 12:00 ... 24:00 %.1f"
          % (end[2], sum(late) / len(late)))
    if not end[0] >= bmin:
        print("  FAIL: the bottom of the column is depleted of particles")
        ok = False
sys.exit(0 if ok else 1)
EOF
  done
fi

#========================= part 2: settling (#299) =========================
if [ "$PART" != 1 ]; then
  c=bs_s1
  echo "=== $c: mm_hyd_41 in still water, iturb = 0, diftur = 0., ised = 1, ilagr = 3, lgrseed = 1, five hours"
  if ended $c; then
    PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$P/$c.hydro.shy" "$NMIN" "$RTAPMAX" "$RLO" "$RHI" <<'EOF' || fail "$c: see above"
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
import lgr_vprof as lv

path, gpath = sys.argv[2], sys.argv[3]
nmin, rtapmax, rlo, rhi = int(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]), float(sys.argv[7])
KF = 1.e-6 / 3.0	# the floor of the walk's diffusivity (diftur = 0)
CLASS = 3		# the fastest sediment class (3e-5 m/s)
T5 = 18000.0		# the output at 05:00
TEXP = 18300.0		# its time since the release (300 s before 00:00)
ok = True
geom = lv.read_geom(gpath)
hlv = [float(v) for v in geom["hlv"]]
hev = [float(v) for v in geom["hev"]]
ilhv = [int(v) for v in geom["ilhv"]]
_, times = lc.read_file(path)
rel = {}		# release records (inserted blocks)
for t, b, _ in times:
    rel.update(b[-1])
b5 = next((b for t, b, _ in times if t == T5), None)
if b5 is None:
    print("  FAIL: no output at 05:00 (%d outputs, %.0f ... %.0f s)"
          % (len(times), times[0][0], times[-1][0]))
    sys.exit(1)
act = b5[0]
ncls = {}
for r in rel.values():
    ncls[r["type"]] = ncls.get(r["type"], 0) + 1
print("  released %d particles (per sediment class: %s); at 05:00 %d active, %d exited,"
      " %d of the active deposited (layer -1)"
      % (len(rel), ", ".join("%d: %d" % kv for kv in sorted(ncls.items())), len(act),
         len(b5[1]), sum(1 for p in act.values() if p["lb"] < 1)))
nmove = sum(1 for pid, p in act.items()
            if (p["x"], p["y"], p["ie"]) != (rel[pid]["x"], rel[pid]["y"], rel[pid]["ie"]))
if nmove:
    print("  FAIL: %d active particles left their release position or element"
          " (the water is not still)" % nmove)
    ok = False

num = den = tap = 0.0
n = nbot = nbad = 0
tset = set()
svals = set()
for pid, r in rel.items():
    if r["type"] != CLASS:
        continue
    ie = r["ie"]
    lmax = ilhv[ie - 1]
    if lmax < 2 or r["lb"] != lmax:
        continue
    nbot += 1
    hd = hev[ie - 1] - hlv[lmax - 2]	# the bottom layer (zeta = 0)
    t = T5 - r["tt"]
    tset.add(t)
    svals.add(r["s"])
    st = r["s"] * t
    db = (1.0 - r["z"]) * hd
    if db < st + 4.0 * math.sqrt(2.0 * KF * t):
        continue
    p = act.get(pid)
    if p is None or p["lb"] < 1 or p["ie"] != ie:
        nbad += 1
        continue
    n += 1
    num += p["hl"] - r["hl"]
    den += st
    tap += db * (1.0 - math.exp(-st / hd))
sig = math.sqrt(2.0 * KF * TEXP)
print("  class %d: %d particles start in the bottom layer of a column of at least two layers;"
      " judged (at least s t + 4 sigma = %.3f m above the bed): %d (at least %d)"
      % (CLASS, nbot, 3.e-5 * TEXP + 4.0 * sig, n, nmin))
print("  settling velocity s %s m/s, t %s s, sigma = sqrt(2 K t) %.3f m"
      % (" ".join("%.4e" % v for v in sorted(svals)), " ".join("%.0f" % v for v in sorted(tset)), sig))
if tset != {TEXP}:
    print("  FAIL: the time since the release is not %.0f s" % TEXP)
    ok = False
if nbad:
    print("  FAIL: %d judged particles not in the water at 05:00 (missing, another element,"
          " or deposited)" % nbad)
    ok = False
if n < nmin or den <= 0.0:
    print("  FAIL: too few particles judged: the check cannot tell the forms apart")
    sys.exit(1)
R = num / den
Rtap = tap / den
print("  the tapered form would give R_tap = %.3f (at most %.2f)" % (Rtap, rtapmax))
print("  drift over the settling distance R = %.3f (required %.2f ... %.2f)" % (R, rlo, rhi))
if not Rtap <= rtapmax:
    print("  FAIL: R_tap too close to 1: the check cannot tell the forms apart")
    ok = False
elif not rlo <= R <= rhi:
    print("  FAIL: the particles do not settle at their settling velocity in the bottom layer")
    ok = False
sys.exit(0 if ok else 1)
EOF
  fi
fi
finish
