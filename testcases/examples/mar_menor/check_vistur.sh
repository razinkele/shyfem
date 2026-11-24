#!/bin/bash
#------------------------------------------------------------------------
# vistur and diftur must act on a 3D run without turbulence closure
# (iturb = 0, issue #248).
#
# def_para documents vistur/diftur as the constant vertical turbulent
# viscosity/diffusivity of iturb = 0.  set_eddy (src/shyfem/initialize.f90)
# puts them into visv/difv, but handle_gotm_init (src/shyfem/turbulence.f90),
# called at set-up whatever iturb, replaced them by GOTM's initial 1e-6
# (gotm_internal_init), so a run with vistur = 1.e-2 or diftur = 1.e-3 was
# byte-identical to one without.
#
# Cases, each 6 hours (2009-01-01 00:00 to 06:00), serially, made in a
# scratch folder from mm_hyd_41.str without its tilt lines (ztilt, ktilt:
# 19 levels, the open level boundary with salinity and temperature files,
# the river, heat flux, rain, wind) with iturb = 0:
#   base  as is (vistur = diftur = 0, the defaults)
#   vis   with vistur = 1.e-2
#   dif   with diftur = 1.e-3
#   g0    base with iturb = 1 (GOTM), and g1 that with vistur = 1.e-2 and
#         diftur = 1.e-3: GOTM computes visv/difv itself and never reads
#         vistur/diftur, so g0 and g1 must be byte-identical (a control:
#         the parameters reach the run only through iturb = 0)
# Required: every run ends (exit code 0 and "simulation end" in its log);
# the parameter listing of the log of vis shows vistur = 0.100000E-01 and
# that of dif diftur = 0.100000E-02 (the STR edit took); vis.hydro.shy
# differs from base.hydro.shy (the viscosity acts on the currents);
# dif.ts.shy differs from base.ts.shy (the diffusivity acts on salinity
# and temperature); g0.hydro.shy, g0.ts.shy equal g1.hydro.shy, g1.ts.shy.
# Before #248 vis.hydro.shy and base.hydro.shy were byte-identical, and so
# were dif.ts.shy and base.ts.shy.
#
# Usage:  ./check_vistur.sh
# Needs shyfem first on PATH and `make init` done.  The scratch folder is
# made with mktemp under ${TMPDIR:-/tmp} and removed at the end.
# Prints "VISTUR CHECK: PASS" (exit 0) or "VISTUR CHECK: FAIL" (exit 1).
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "VISTUR CHECK FAIL: $*"; rc=1; }

command -v shyfem > /dev/null 2>&1 || { echo "VISTUR CHECK FAIL: shyfem is not on PATH"; exit 1; }
[ -f "$HERE/GRID/MM_coarse_smooth.bas" ] \
  || { echo "VISTUR CHECK FAIL: GRID/MM_coarse_smooth.bas is missing: run 'make init' in $HERE"; exit 1; }

P="$(mktemp -d "${TMPDIR:-/tmp}/check_vistur.XXXXXX")" || exit 1
cleanup() { rm -rf "$P"; }
trap cleanup EXIT
trap 'exit 130' INT TERM
ln -s "$HERE/GRID" "$P/GRID" && ln -s "$HERE/INPUT" "$P/INPUT" || exit 1

# mk NAME ITURB [PARA-LINE]: NAME.str from mm_hyd_41.str
mk() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
      -e "s/^\([[:space:]]*\)mm_hyd_41[[:space:]]*\$/\1$1/" \
      -e "s/^\([[:space:]]*\)iturb = 1 /\1iturb = $2 /" "$HERE/mm_hyd_41.str" > "$P/$1.str" || return 1
  if [ $# -ge 3 ]; then
    sed -i "0,/^\\\$para[[:space:]]*\$/s//\$para\n        $3/" "$P/$1.str" || return 1
    grep -qF -- "$3" "$P/$1.str" || return 1
  fi
  grep -q "^[[:space:]]*$1[[:space:]]*\$" "$P/$1.str" && grep -q "iturb = $2 " "$P/$1.str" \
    && ! grep -q 'tilt' "$P/$1.str"
}
mk base 0                                     || fail "cannot make base.str"
mk vis 0 "vistur = 1.e-2"                     || fail "cannot make vis.str"
mk dif 0 "diftur = 1.e-3"                     || fail "cannot make dif.str"
mk g0 1                                       || fail "cannot make g0.str"
mk g1 1 "vistur = 1.e-2   diftur = 1.e-3"     || fail "cannot make g1.str"
[ $rc = 0 ] || { echo "VISTUR CHECK: FAIL"; exit 1; }

for c in base vis dif g0 g1; do
  ( cd "$P" && timeout 600 nice -n 10 shyfem "$c.str" < /dev/null > "$c.log" 2>&1 )
  r=$?
  if [ $r != 0 ] || ! grep -q "simulation end" "$P/$c.log"; then
    tail -5 "$P/$c.log"; fail "$c did not end (exit code $r)"
  fi
done
[ $rc = 0 ] || { echo "VISTUR CHECK: FAIL"; exit 1; }

grep -q "vistur *= *0\.100000E-01" "$P/vis.log" || fail "the log of vis does not list vistur = 0.100000E-01"
grep -q "diftur *= *0\.100000E-02" "$P/dif.log" || fail "the log of dif does not list diftur = 0.100000E-02"

# same A B: true if the two files exist and are byte-identical
same() { [ -f "$P/$1" ] && [ -f "$P/$2" ] && cmp -s "$P/$1" "$P/$2"; }
for f in base.hydro.shy base.ts.shy vis.hydro.shy dif.ts.shy; do
  [ -s "$P/$f" ] || fail "no output file $f"
done
if same base.hydro.shy vis.hydro.shy; then
  fail "vistur = 1.e-2 has no effect: vis.hydro.shy is byte-identical to base.hydro.shy"
else
  echo "vistur = 1.e-2 acts: vis.hydro.shy differs from base.hydro.shy ($(cmp "$P/base.hydro.shy" "$P/vis.hydro.shy" 2>&1 | sed 's/.*differ: //'))"
fi
if same base.ts.shy dif.ts.shy; then
  fail "diftur = 1.e-3 has no effect: dif.ts.shy is byte-identical to base.ts.shy"
else
  echo "diftur = 1.e-3 acts: dif.ts.shy differs from base.ts.shy ($(cmp "$P/base.ts.shy" "$P/dif.ts.shy" 2>&1 | sed 's/.*differ: //'))"
fi
for f in hydro.shy ts.shy; do
  same g0.$f g1.$f || fail "iturb = 1: vistur/diftur changed g1.$f (GOTM must not read them)"
done

if [ $rc = 0 ]; then echo "VISTUR CHECK: PASS"; else echo "VISTUR CHECK: FAIL"; fi
exit $rc
