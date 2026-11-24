#!/bin/bash
#------------------------------------------------------------------------
# The vertical random walk of ilagr = 3 keeps particles that are evenly
# spread over the depth evenly spread (issue #284): a well-mixed state
# must stay well mixed.
#
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
#     element and step (K'' = 0, the random walk takes the model step);
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
# Measured (mean chi-square 12:00 ... 24:00 for lgrseed 1, 2, 3; mean
# |dz| over the first hour / sqrt(2 K T)):
#                                       seed 1  seed 2  seed 3   |dz|
#   origin/main 668acb4d                 331.4   313.1   371.4  0.315
#   thickness of the layer entered only   53.5    56.0    42.5  0.311
#   time tv**2/dt of a stopped call only 605.7   563.0          0.328
#   both (the fix of #284)                20.4    18.6    17.7  0.324
#   a walk that never moves                0.0     0.0          0.000
# The limit 31 lies 10.6 above the highest value of the fix and 11.5
# below the lowest of the thickness alone; the floor 0.15 is about half
# of what the walks that move give.  (A gaussian walk with the
# diffusivity K, reflected at the surface and bottom, would give 0.41:
# here the walk spreads the particles more slowly than that, before and
# after #284; the variance of the hourly displacement of particles far
# from the surface and bottom is about 0.75 of 2 K T, issue #287.)
# On origin/main the particles drift to the bottom (11 % too few in the
# upper 15 % of the column, 10 % too many in the lower 15 %).  Of the two
# defects of lgr_diff_vert, the first drove them down: after a particle
# crossed an interface it went on with the thickness of the layer it left
# (with only the second fixed the upper / lower 15 % are at 0.842 /
# 1.130 of uniform).  The second, a call that stopped at an interface
# counted the time tv in which it had diffused for tv**2/dt, alone drove
# them up (with only the first fixed: 1.045 / 0.979), so it partly masked
# the first.
#
# Usage:  ./check_lgr_wellmixed.sh
# Needs shyfem and python3 on PATH and `make init` done.  The scratch
# folder is made with mktemp under ${TMPDIR:-/tmp}; it is removed at the
# end when the check passes and kept (its path is printed) when it fails.
# Takes about a minute and 200 MB of scratch space.
# Prints "WELLMIXED: PASS" (exit 0) or "WELLMIXED: FAIL" (exit 1).
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "  FAIL: $*"; rc=1; }
CHI2MAX=31
DZFLOOR=0.15
SEEDS="1 2"

command -v shyfem > /dev/null 2>&1 || { echo "WELLMIXED: FAIL (shyfem is not on PATH)"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "WELLMIXED: FAIL (python3 is not on PATH)"; exit 1; }
[ -f "$HERE/GRID/MM_coarse_smooth.bas" ] \
  || { echo "WELLMIXED: FAIL (GRID/MM_coarse_smooth.bas is missing: run 'make init' in $HERE)"; exit 1; }

P="$(mktemp -d "${TMPDIR:-/tmp}/check_wellmixed.XXXXXX")" || exit 1
finish() {
  if [ "$rc" = 0 ]; then
    rm -rf "$P"
    echo "WELLMIXED: PASS"
  else
    echo "  logs kept in $P"
    echo "WELLMIXED: FAIL"
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

for s in $SEEDS; do
  mk wm_s$s $s || { fail "cannot make wm_s$s.str"; finish; }
done
for s in $SEEDS; do
  ( cd "$P" && timeout 1800 nice -n 10 shyfem wm_s$s.str < /dev/null > wm_s$s.log 2>&1; echo $? > wm_s$s.rc ) &
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
