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
# with about half its share of particles.  Three parts:
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
#   - the basin is closed: no particle in the exited block of any output,
#     and no log line of particles "lost with time left" (lgr_event,
#     track_body_xi);
#   - the bottom 5 % of the column holds at least 0.80 of its uniform
#     share of the particles at 24:00: bin_ratio(..., 19, 20) of the
#     relative depths of lgr_vprof.rel_depths (the depth of the particle
#     over the depth of its column at the output time) with the weight
#     'rel' (the depth of the release column, the volume the particle
#     stands for), the measure of the measurements of #299 (anaA).
# Printed, not gated: the bottom 15 % at 24:00, and the chi-square of the
# 20-bin histogram with the same weight at 24:00 and its mean over the
# hourly outputs 12:00 ... 24:00; and the log lines of particles with
# their "element crossings used up with time left" (100 calls of track_xi
# in a step; the particle stays in the basin): lgrseed = 1 has one, at
# 22:55 in element 1149, of a particle in layer 1 at 22:00 and 23:00 (in
# element 10, a column of one layer), with the walk of #286 and the bed
# velocity of #299 (main has none here, but writes two at elements 1148
# and 1149 in part 3; the cause is not known).
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
#     at the position and in the element of its release); the basin is
#     closed (no exited particle at any output, no log line of particles
#     "lost with time left" or with their "element crossings used up with
#     time left": in still water no particle moves horizontally);
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
#==================== part 3: fast settling at the walls (#299) ============
# A particle whose time to leave its layer is 0 (on the bed with sv > 0,
# at the top of the bottom layer where the bed velocity points up but the
# layer mean did not switch it, or after a switch into a layer whose w
# points back) must not move vertically in that step of track_xi, as a
# particle on the bed did not before (the rule bbott).  A zero time there
# made the material-boundary rule of track_xi give the horizontal step a
# time of 0 too, and a particle on a wall side was moved through the wall,
# out of the closed basin.  The stock settling velocities rarely put a
# particle in such a state at a wall; settling 30 times faster does.  The
# particle file of the model (lgrini) carries each particle's settling
# velocity, so no hook is needed.
# Case: a run as part 1 (lgrseed = 1) to 01:00 writes the particle file;
# the settling velocity of every particle record in it is set to 1e-3
# m/s (Python, the record layout of lgr_compare.py); then the closed forced
# case of part 1 for one day (at most 7200 s) with no release (nbdy = 0)
# reads its 39960 particles at 01:00 (lgrini, itlgin = 01:00), without
# ised (no deposition, so the particles settle onto the bed and stay
# there).
# Required:
#   - the run ends; it read the 39960 particles ("particles read:"), and
#     every particle of its first output settles at 1e-3 m/s (s);
#   - the basin is closed: every output holds the 39960 particles as active
#     ones, none exited, and the log has no line of particles "lost with
#     time left".
# Printed, not gated: the log lines of particles with their "element
# crossings used up with time left" (main writes two in this case: a
# particle that stays in the basin) and the particles in the bottom layer
# of their column at 24:00.
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
# Part 3: exited particles at most / log lines "lost with time left" /
# "element crossings used up with time left" / particles in the bottom
# layer of their column at 24:00:
#   origin/main 576abae5 (the layer mean; bbott)        0 / 0 /  2 / 37294
#   39b8247d (the bed velocity, a zero time to leave
#   the layer kept as 0)                                6 / 6 / 43 / 36992 (FAIL)
#   the bed velocity, a zero time = no vertical motion  0 / 0 /  4 / 36993
# 39b8247d lost its particles through walls (elements 659, 254, ...; the
# first at 06:45); it gives part 1 particle files byte-identical to the
# fixed build (sv = 0 there).
# A run of part 1 takes about 4 minutes (main's about 5, measured with
# the other runs of the check beside it), the run of part 2 a few seconds,
# part 3 about as long as part 1.
#
# Usage:  ./check_lgr_bed.sh [all | 1 | 2 | 3]
# (all, the default: the three parts; 1, 2 or 3: that part only.)  Needs
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
SFAST=1.e-3		# part 3: the settling velocity set in the particle file [m/s]
NPART=39960		# part 3: particles in the particle file

PART="${1:-all}"
case "$PART" in
  all|1|2|3) ;;
  *) echo "usage: $0 [all | 1 | 2 | 3]"; exit 2 ;;
esac
LABEL="BED"
[ "$PART" = all ] || LABEL="BED part $PART"
# want N: part N is run
want() { [ "$PART" = all ] || [ "$PART" = "$1" ]; }

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

# mkp NAME (part 3): NAME.str as part 1's (lgrseed = 1), to 01:00: the
# run that writes the particle file
mkp() {
  mkc "$1" 1 || return 1
  sed -i "s/itend = '2009-01-02'/itend = '2009-01-01::01:00:00'/" "$P/$1.str" || return 1
  grep -qF "itend = '2009-01-01::01:00:00'" "$P/$1.str"
}

# mkx NAME FILE (part 3): NAME.str as part 1's (one day, lgrseed = 1) with
# no release (nbdy = 0) and the particles of the particle file FILE at
# 01:00 (lgrini, itlgin)
mkx() {
  mkc "$1" 1 || return 1
  sed -i -e 's/^\([[:space:]]*\)nbdy = 2000  idtl = 0 /\1nbdy = 0  idtl = 0 /' \
         -e "s/^\([[:space:]]*\)lgrseed = 1\$/&\n\1lgrini = '$2'\n\1itlgin = '2009-01-01::01:00:00'/" \
         "$P/$1.str" || return 1
  for o in 'nbdy = 0  idtl = 0' "lgrini = '$2'" "itlgin = '2009-01-01::01:00:00'"; do
    grep -qF -- "$o" "$P/$1.str" || return 1
  done
  ! grep -q 'ised' "$P/$1.str"
}

# the runs of the check, all in parallel; the hooks of
# check_lgr_wellmixed.sh are unset (a hook inherited from the caller's
# environment would measure another case)
RUNS=""
if want 1; then
  for s in $SEEDS; do
    mkc bc_s$s $s || { fail "cannot make bc_s$s.str"; finish; }
    RUNS="$RUNS bc_s$s:7200"
  done
fi
if want 2; then
  mks bs_s1 1 || { fail "cannot make bs_s1.str"; finish; }
  RUNS="$RUNS bs_s1:1800"
fi
if want 3; then
  # the particle file: a run to 01:00, then every particle record's
  # settling velocity set to SFAST (s, the fourth field of the first
  # record of a particle: id i4, type i4, tt f8, s f4, ie i4)
  mkp bf_rel || { fail "cannot make bf_rel.str"; finish; }
  ( cd "$P" && timeout 1800 nice -n 10 env -u LGR_TEST_KPROF -u LGR_TEST_NOADV \
      shyfem bf_rel.str < /dev/null > bf_rel.log 2>&1 ) && grep -q "simulation end" "$P/bf_rel.log" \
    || { tail -5 "$P/bf_rel.log" | sed 's/^/    /'; fail "bf_rel (the run that writes the particle file of part 3) did not end"; finish; }
  PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/bf_rel.lgr.shy" "$P/bf_fast.lgr.shy" "$SFAST" <<'EOF' \
    || { fail "cannot write the particle file of part 3"; finish; }
import struct, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
src, dst, sv = sys.argv[2], sys.argv[3], float(sys.argv[4])
data = bytearray(open(src, "rb").read())
recs = lc.split_records(bytes(data))
i, ncust = lc.find_particle_start(bytes(data), recs)
off = struct.calcsize("<iid")		# s in (id, type, tt, s, ie)
n = 0
while i < len(recs):
    dtime, npart, _ = lc.HEAD.unpack_from(data, recs[i][0])
    i += 1
    for _ in range(npart):
        struct.pack_into("<f", data, recs[i][0] + off, sv)
        n += 1
        i += 3
open(dst, "wb").write(bytes(data))
_, times = lc.read_file(dst)		# read back: the format holds
print("  particle file of part 3: %d records, settling velocity set to %g m/s;"
      " record times %s s" % (n, sv, " ".join("%.0f" % t for t, _, _ in times)))
EOF
  mkx bf_s1 bf_fast.lgr.shy || { fail "cannot make bf_s1.str"; finish; }
  RUNS="$RUNS bf_s1:7200"
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

# loglines C GATE KIND: the log lines of C with the text KIND (lines of
# lgr_event, track_body_xi): their number and the first two printed; with
# GATE = 1 any such line fails the check (the basins here are closed)
LOST='lost with time left'
XUSED='element crossings used up with time left'
loglines() {
  local n
  n="$(grep -c -- "$3" "$P/$1.log")"
  [ "$n" = 0 ] || grep -m2 -- "$3" "$P/$1.log" | sed 's/^/    /'
  if [ "$2" = 1 ]; then
    echo "  log lines of particles '$3': $n"
    [ "$n" = 0 ] || fail "$1: log lines of particles '$3' in a closed basin"
  else
    echo "  log lines of particles '$3' (not gated): $n"
  fi
}

#========================== part 1: the bottom (#299) ======================
if want 1; then
  for s in $SEEDS; do
    c=bc_s$s
    echo "=== $c: the closed forced mm_hyd_41 (both ibtyp = 0, GOTM, wind), ilagr = 3, lgrseed = $s, one day"
    ended $c || continue
    loglines $c 1 "$LOST"
    loglines $c 0 "$XUSED"
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
nex = max(len(b[1]) for t, b, _ in times)
if nex:
    print("  FAIL: up to %d particles exited the closed basin" % nex)
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
if want 2; then
  c=bs_s1
  echo "=== $c: mm_hyd_41 in still water, iturb = 0, diftur = 0., ised = 1, ilagr = 3, lgrseed = 1, five hours"
  if ended $c; then
    loglines $c 1 "$LOST"
    loglines $c 1 "$XUSED"
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
nex = max(len(b[1]) for t, b, _ in times)
if nex:
    print("  FAIL: up to %d particles exited the closed basin" % nex)
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

#==================== part 3: fast settling at the walls (#299) ============
if want 3; then
  c=bf_s1
  echo "=== $c: the closed forced case of part 1, the $NPART particles of a particle file settling at $SFAST m/s, ilagr = 3, one day"
  if ended $c; then
    grep -Eq "particles read: +$NPART( |\$)" "$P/$c.log" \
      || fail "$c: the log does not show the $NPART particles read from the particle file"
    loglines $c 1 "$LOST"
    loglines $c 0 "$XUSED"
    PYTHONDONTWRITEBYTECODE=1 python3 - "$HERE" "$P/$c.lgr.shy" "$P/$c.hydro.shy" "$SFAST" "$NPART" <<'EOF' || fail "$c: see above"
import struct, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
import lgr_vprof as lv

path, gpath = sys.argv[2], sys.argv[3]
sfast = struct.unpack("<f", struct.pack("<f", float(sys.argv[4])))[0]	# as stored
npart = int(sys.argv[5])
ok = True
ilhv = [int(v) for v in lv.read_geom(gpath)["ilhv"]]
_, times = lc.read_file(path)
act0 = times[0][1][0]
nfast = sum(1 for p in act0.values() if p["s"] == sfast)
print("  %d outputs (%.0f ... %.0f s); first output: %d active particles, %d of them settling"
      " at %g m/s" % (len(times), times[0][0], times[-1][0], len(act0), nfast, sfast))
if nfast != npart:
    print("  FAIL: not the %d particles of the particle file, each settling at %g m/s"
          % (npart, sfast))
    ok = False
nact = min(len(b[0]) for t, b, _ in times)
nex = max(len(b[1]) for t, b, _ in times)
print("  active particles at every output at least %d; exited at most %d" % (nact, nex))
if nact != npart or nex:
    print("  FAIL: particles left the closed basin")
    ok = False
act = times[-1][1][0]
nbl = sum(1 for p in act.values() if p["lb"] == ilhv[p["ie"] - 1])
print("  at %.0f s %d of the %d active particles in the bottom layer of their column (not gated)"
      % (times[-1][0], nbl, len(act)))
sys.exit(0 if ok else 1)
EOF
  fi
fi
finish
