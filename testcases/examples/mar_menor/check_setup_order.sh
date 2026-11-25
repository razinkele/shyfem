#!/bin/bash
#------------------------------------------------------------------------
# Set-up order of the vertical mixing (issue #283).
#
# 1. The particle step made at set-up must see the closure's visv/difv
#    (part (1)).  The set-up call of lagrange (one particle step:
#    lag_vdiff_ele and drogue) ran before handle_gotm_init, so with a
#    closure (iturb > 0) that step read set_eddy's vistur/diftur, which the
#    closure never reads.  Cases (mm_hyd_41 without its tilt lines,
#    iturb = 1 (GOTM), one hour, the $lagrg section of check_lgr_fixes.sh
#    ilagr3: ilagr = 3, 300 particles; particle, hydro and T/S output every
#    hour):
#      p0  as is
#      p1  with vistur = 1.e-2 and diftur = 1.e-3
#    Required: p0.lgr.shy, p0.hydro.shy, p0.ts.shy byte-identical to those
#    of p1 (GOTM never reads vistur/diftur, so they must not reach the
#    particles either).  Before the fix p0.lgr.shy and p1.lgr.shy differ
#    (the first particle step walks with diftur = 1e-3 in p1, 0 in p0)
#    while the hydro and ts files are identical.  The two runs use one
#    binary, so this holds for any walk.
# 2. Step 1 of a k-epsilon or Munk-Anderson run starts from the closure's
#    own vertical mixing (part (2)).
#
# The closure first steps in turb_closure, after hydro and run_scalar of
# the first time step, so step 1 uses the visv/difv set at set-up by
# handle_gotm_init (src/shyfem/turbulence.f90).  Before the fix that was
# GOTM's initial 1e-6 for k-epsilon (iturb = 2) and Munk-Anderson
# (iturb = 3) too, so Munk-Anderson ignored vistur/diftur in step 1.
# Started at rest, k-epsilon's initial state is visv = 1.3e-6,
# difv = 1.1e-9 everywhere (keps_init) and Munk-Anderson gives
# vistur/diftur everywhere (no shear and no stratification: Ri = 0), so
# the first step of these runs must equal the first step of a run
# without closure (iturb = 0) with those constants.  Cases (mm_hyd_41
# without its tilt lines, one step of 300 s, hydro and T/S output after
# it):
#   k0  iturb = 0, vistur = 1.3e-6, diftur = 1.1e-9
#   k2  iturb = 2 with vistur = 0, diftur = 0 (k-epsilon does not read
#       them; set_eddy puts them into visv/difv, so a handle_gotm_init that
#       kept set_eddy's values for k-epsilon would give k2 a step 1 with no
#       turbulent mixing and fail, as it would with values other than
#       k-epsilon's own constants)
#   m0  iturb = 0, vistur = 1.e-2, diftur = 1.e-3
#   m3  iturb = 3 with the same lines
# Required: every run ends; the logs of k2 and m3 say that their closure
# started; k2.hydro.shy, k2.ts.shy byte-identical to those of k0, and
# m3.hydro.shy, m3.ts.shy to those of m0.  Before the fix they differ.
#
# Limit: at rest Munk-Anderson gives vistur/diftur (Ri = 0), the values
# set_eddy already put in, so this check cannot tell "Munk-Anderson
# evaluated at set-up" from "set_eddy's values kept" for iturb = 3.  The
# only assertion in the repository that Munk-Anderson is evaluated at
# set-up is the n2max line count of check_rst3d_ma_mpi.sh (one line more
# than the time steps, the first on a stratified restart state).
#
# Usage:  ./check_setup_order.sh
# Needs shyfem first on PATH and `make init` done.  The scratch folder is
# made with mktemp under ${TMPDIR:-/tmp}, removed at the end when the check
# passes, kept (its path printed) when it fails.
# Prints "SETUP ORDER: PASS" (exit 0) or "SETUP ORDER: FAIL" (exit 1),
# with a line per part.  Takes a few seconds.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "SETUP ORDER FAIL: $*"; rc=1; }

command -v shyfem > /dev/null 2>&1 || { echo "SETUP ORDER FAIL: shyfem is not on PATH"; exit 1; }
[ -f "$HERE/GRID/MM_coarse_smooth.bas" ] \
  || { echo "SETUP ORDER FAIL: GRID/MM_coarse_smooth.bas is missing: run 'make init' in $HERE"; exit 1; }

P="$(mktemp -d "${TMPDIR:-/tmp}/check_setup_order.XXXXXX")" || exit 1
cleanup() { if [ "$rc" = 0 ]; then rm -rf "$P"; else echo "  files kept in $P"; fi; }
trap cleanup EXIT
trap 'exit 130' INT TERM
ln -s "$HERE/GRID" "$P/GRID" && ln -s "$HERE/INPUT" "$P/INPUT" || exit 1

# mk NAME ITURB ITEND IDTOUT PARA-LINE: NAME.str from mm_hyd_41.str without
# its tilt lines, ending at ITEND, the hydro and T/S output (idtout, idtcon)
# every IDTOUT, PARA-LINE as the first line of $para (empty: none)
mk() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '$3'/" \
      -e "s/idtout = '[^']*'/idtout = '$4'/" -e "s/idtcon = '[^']*'/idtcon = '$4'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e "s/^\([[:space:]]*\)iturb = 1 /\1iturb = $2 /" "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  if [ -n "$5" ]; then
    sed -i "0,/^\\\$para[[:space:]]*\$/s//\$para\n        $5/" "$P/$1.str" || return 1
    grep -qF -- "$5" "$P/$1.str" || return 1
  fi
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" && grep -q "iturb = $2 " "$P/$1.str" \
    && grep -q "idt = '300s'" "$P/$1.str" && grep -q "itend = '$3'" "$P/$1.str" \
    && grep -q "idtout = '$4'" "$P/$1.str" && grep -q "idtcon = '$4'" "$P/$1.str" \
    && ! grep -q 'tilt' "$P/$1.str"
}
# lgr NAME: append the $lagrg section of check_lgr_fixes.sh ilagr3
lgr() {
  printf '\n$lagrg\n        ilagr = 3   nbdymax = 20000\n        nbdy = 300  idtl = 0  idtlgr = %s\n        rwhpar = 0  ipvert = -1\n$end\n' "'1h'" >> "$P/$1.str"
}
H1=2009-01-01::01:00:00
S1=2009-01-01::00:05:00
mk p0 1 $H1 1h "" && lgr p0                                      || fail "cannot make p0.str"
mk p1 1 $H1 1h "vistur = 1.e-2   diftur = 1.e-3" && lgr p1       || fail "cannot make p1.str"
mk k0 0 $S1 300s "vistur = 1.3e-6   diftur = 1.1e-9"   || fail "cannot make k0.str"
mk k2 2 $S1 300s "vistur = 0.   diftur = 0."           || fail "cannot make k2.str"
mk m0 0 $S1 300s "vistur = 1.e-2   diftur = 1.e-3"     || fail "cannot make m0.str"
mk m3 3 $S1 300s "vistur = 1.e-2   diftur = 1.e-3"     || fail "cannot make m3.str"
[ $rc = 0 ] || { echo "SETUP ORDER: FAIL"; exit 1; }

for c in p0 p1 k0 k2 m0 m3; do
  ( cd "$P" && timeout 600 nice -n 10 shyfem "$c.str" < /dev/null > "$c.log" 2>&1 )
  r=$?
  if [ $r != 0 ] || ! grep -q "simulation end" "$P/$c.log"; then
    tail -5 "$P/$c.log"; fail "$c did not end (exit code $r)"
  fi
done
[ $rc = 0 ] || { echo "SETUP ORDER: FAIL"; exit 1; }

grep -q "diftur *= *0\.100000E-02" "$P/p1.log" || fail "the log of p1 does not list diftur = 0.100000E-02"

# the closures ran (turb_closure, munk_anderson_shell) and m3 read its lines
grep -q "starting turbulence model: iturb = *2" "$P/k2.log" || fail "the log of k2 does not show k-epsilon (iturb = 2)"
grep -q "starting turbulence model: iturb = *3" "$P/m3.log" || fail "the log of m3 does not show Munk-Anderson (iturb = 3)"
grep -q "starting Munk Anderson turbulence model" "$P/m3.log" || fail "the log of m3 does not show the Munk-Anderson start"
grep -q "vistur *= *0\.100000E-01" "$P/m3.log" || fail "the log of m3 does not list vistur = 0.100000E-01"
grep -q "diftur *= *0\.100000E-02" "$P/m3.log" || fail "the log of m3 does not list diftur = 0.100000E-02"

# same A B: true if the two files exist, are not empty and are byte-identical
same() { [ -s "$P/$1" ] && [ -s "$P/$2" ] && cmp -s "$P/$1" "$P/$2"; }
# part LABEL A B EXT...: A.EXT and B.EXT byte-identical for every EXT
part() {
  local label="$1" a="$2" b="$3" e bad=""; shift 3
  for e in "$@"; do
    same "$a.$e" "$b.$e" || bad="$bad $b.$e"
  done
  if [ -z "$bad" ]; then
    echo "$label: PASS"
  else
    fail "$label: differs from $a:$bad"
  fi
}
part "1 particle step at set-up (iturb = 1, vistur/diftur set)" p0 p1 lgr.shy hydro.shy ts.shy
part "2 step 1 of k-epsilon (iturb = 2) = iturb = 0 with its initial state" k0 k2 hydro.shy ts.shy
part "2 step 1 of Munk-Anderson (iturb = 3) = iturb = 0 with vistur/diftur" m0 m3 hydro.shy ts.shy

if [ $rc = 0 ]; then echo "SETUP ORDER: PASS"; else echo "SETUP ORDER: FAIL"; fi
exit $rc
