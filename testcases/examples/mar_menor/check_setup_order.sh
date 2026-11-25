#!/bin/bash
#------------------------------------------------------------------------
# Step 1 of a k-epsilon or Munk-Anderson run starts from the closure's
# own vertical mixing (issue #283, part (2)).
#
# The closure first runs in turb_closure, after hydro and run_scalar of
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
#   k2  iturb = 2 with the same lines (k-epsilon does not read them)
#   m0  iturb = 0, vistur = 1.e-2, diftur = 1.e-3
#   m3  iturb = 3 with the same lines
# Required: every run ends; the logs of k2 and m3 say that their closure
# started; k2.hydro.shy, k2.ts.shy byte-identical to those of k0, and
# m3.hydro.shy, m3.ts.shy to those of m0.  Before the fix they differ.
#
# Not checked here: part (1) of #283, the particle step made at set-up
# (ilagr = 3), which still sees set_eddy's diftur whatever iturb.  It is
# open and goes with the change of the vertical walk (#286/#287).
#
# Usage:  ./check_setup_order.sh
# Needs shyfem first on PATH and `make init` done.  The scratch folder is
# made with mktemp under ${TMPDIR:-/tmp}, removed at the end when the check
# passes, kept (its path printed) when it fails.
# Prints "SETUP ORDER: PASS" (exit 0) or "SETUP ORDER: FAIL" (exit 1),
# with a line per closure.  Takes a few seconds.
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

# mk NAME ITURB PARA-LINE: NAME.str from mm_hyd_41.str without its tilt
# lines, one step of 300 s, the hydro and T/S output (idtout, idtcon)
# after it, PARA-LINE as the first line of $para
mk() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::00:05:00'/" \
      -e "s/idtout = '[^']*'/idtout = '300s'/" -e "s/idtcon = '[^']*'/idtcon = '300s'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e "s/^\([[:space:]]*\)iturb = 1 /\1iturb = $2 /" "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  sed -i "0,/^\\\$para[[:space:]]*\$/s//\$para\n        $3/" "$P/$1.str" || return 1
  grep -qF -- "$3" "$P/$1.str" \
    && grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" && grep -q "iturb = $2 " "$P/$1.str" \
    && grep -q "idt = '300s'" "$P/$1.str" && grep -q "itend = '2009-01-01::00:05:00'" "$P/$1.str" \
    && grep -q "idtout = '300s'" "$P/$1.str" && grep -q "idtcon = '300s'" "$P/$1.str" \
    && ! grep -q 'tilt' "$P/$1.str"
}
mk k0 0 "vistur = 1.3e-6   diftur = 1.1e-9"   || fail "cannot make k0.str"
mk k2 2 "vistur = 1.3e-6   diftur = 1.1e-9"   || fail "cannot make k2.str"
mk m0 0 "vistur = 1.e-2   diftur = 1.e-3"     || fail "cannot make m0.str"
mk m3 3 "vistur = 1.e-2   diftur = 1.e-3"     || fail "cannot make m3.str"
[ $rc = 0 ] || { echo "SETUP ORDER: FAIL"; exit 1; }

for c in k0 k2 m0 m3; do
  ( cd "$P" && timeout 600 nice -n 10 shyfem "$c.str" < /dev/null > "$c.log" 2>&1 )
  r=$?
  if [ $r != 0 ] || ! grep -q "simulation end" "$P/$c.log"; then
    tail -5 "$P/$c.log"; fail "$c did not end (exit code $r)"
  fi
done
[ $rc = 0 ] || { echo "SETUP ORDER: FAIL"; exit 1; }

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
part "step 1 of k-epsilon (iturb = 2) = iturb = 0 with its initial state" k0 k2 hydro.shy ts.shy
part "step 1 of Munk-Anderson (iturb = 3) = iturb = 0 with vistur/diftur" m0 m3 hydro.shy ts.shy

if [ $rc = 0 ]; then echo "SETUP ORDER: PASS"; else echo "SETUP ORDER: FAIL"; fi
exit $rc
