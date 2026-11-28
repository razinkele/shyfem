#!/bin/bash
#------------------------------------------------------------------------
# MFS bulk heat flux (iheat = 8), issues #319 and #364.
#
# Usage:  ./check_iheat8.sh [NP]     (processes of row 2, default 4)
#
# Each row runs a scratch copy of mm_hyd_41.str (run name of its own, made
# by sed in this folder, its outputs removed at the end; the logs go to a
# folder made with mktemp under ${TMPDIR:-/tmp}, removed when every row
# passed, kept and named when one failed): without the tilt lines, with
# "iheat = 8" added to the iturb line, and the heat fluxes written every
# time step to the meteo file (imetout = 10000, idtmet = '300s').  The heat
# forcing is INPUT/qflux09.txt (solar radiation, air temperature, relative
# humidity, cloud cover) as for any other iheat.  A run has ended only if
# its launcher exits with 0, its log has "simulation end" and no "STOP"
# line.
#
#   1. serial, six hours: the run ends, and at node 868 the first record
#      of the meteo file (2009-01-01::00:05:00, the first time step) has
#      the sensible and latent heat flux of the MFS formulae with the
#      10 m wind speed: qsens -3.258 and qlat 4.258 W/m**2, within
#      0.01 W/m**2 (read with shyelab -node 868, three decimals; the wind
#      relative to the current would give -3.237 and 4.231, the AREG
#      formulae -3.848 and 5.871).  Before #319
#      meteo_get_heat_extra passed the pressure to rh2dp in Pa (101325),
#      rh2dp wants mbar and stopped the run at the first heat step with
#      the bare stop "error stop wb2rh: pressure" (exit code 0, no
#      "simulation end").  Before #364 mfs_qfluxes used the speed of the
#      surface current (about 0.01 m/s here) as the transfer speed, so
#      qsens and qlat were exactly 0 whenever the air was warmer than the
#      water, as at this step (air 10.2 C, water 9.0 C, wind 3.2 m/s).
#   2. NP processes: the same run ends on every process, with the same
#      fluxes at node 868.
#   3. serial, 2009-01-02 06:00 to 10:00: the wind file has a calm record
#      (0 m/s) at 09:00, which a time step meets exactly; the run ends.
#      The transfer speed has a floor (0.01 m/s); without it the bulk
#      formulae divide by zero (S = dT/U**2) and the build of the gates
#      (-ffpe-trap=zero,invalid,overflow) stops with a floating-point
#      exception.
#
# Needs shyfem, shyelab and mpirun on PATH (an OpenMPI build) and
# `make init` done.
# Exit code 0 (IHEAT8 CHECK: PASS) or 1 (IHEAT8 CHECK: FAIL).
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
case "$NP" in ''|*[!0-9]*) echo "usage: $0 [NP]  (NP > 1)"; exit 2 ;; esac
[ "$NP" -gt 1 ] || { echo "usage: $0 [NP]  (NP > 1)"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
rc=0
fail() { echo "IHEAT8 CHECK FAIL: $*"; rc=1; }

NODE=868			# external node ("center of lagoon" in $extra)
QSENS_REF=-3.258		# W/m**2, first time step, MFS with the 10 m wind
QLAT_REF=4.258
TOL=0.01

for t in shyfem shyelab mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "IHEAT8 CHECK FAIL: $t is not on PATH"; exit 1; }
done
[ -f GRID/MM_coarse_smooth.bas ] || { echo "IHEAT8 CHECK FAIL: GRID/MM_coarse_smooth.bas is missing: run 'make init'"; exit 1; }

SCR="$(mktemp -d "${TMPDIR:-/tmp}/iheat8.XXXXXX")" || exit 1
TAG="ih8$$"
cleanup() {
  local f
  for f in "$HERE/${TAG}"*; do [ -e "$f" ] && rm -f "$f"; done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

[ "$(grep -c '^        mm_hyd_41$' mm_hyd_41.str)" = 1 ] \
  || { echo "IHEAT8 CHECK FAIL: cannot find the run name line of mm_hyd_41.str"; exit 1; }
# make_str NAME ITANF ITEND: the scratch copy NAME.str of mm_hyd_41.str
make_str() {
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/^        mm_hyd_41\$/        $1/" \
      -e "s/itanf = '[^']*'/itanf = '$2'/" \
      -e "s/itend = '[^']*'/itend = '$3'/" \
      -e "s/^\(        iturb = 1      ievap = 1       hmin = 1\.    aapar = 0\.\)\$/\1\n        iheat = 8      imetout = 10000      idtmet = '300s'/" \
      mm_hyd_41.str > "$1.str"
  [ "$(grep -c "^        iheat = 8      imetout = 10000      idtmet = '300s'\$" "$1.str")" = 1 ] \
    || { echo "IHEAT8 CHECK FAIL: the sed expression set no iheat in $1.str"; exit 1; }
}
make_str "$TAG" 2009-01-01 2009-01-01::06:00:00
make_str "${TAG}c" 2009-01-02::06:00:00 2009-01-02::10:00:00

ended() { [ "$1" = 0 ] && grep -q "simulation end" "$2" && ! grep -q "STOP" "$2"; }

# fluxes ROW: qsens and qlat of node NODE at the first record of
# $TAG.meteo.shy against the references
fluxes() {
  local d="$SCR/nodes$1" qs ql
  mkdir "$d" || { fail "row $1: cannot make $d"; return; }
  ( cd "$d" && shyelab -node "$NODE" "$HERE/$TAG.meteo.shy" > shyelab.log 2>&1 ) \
    || { tail -3 "$d/shyelab.log"; fail "row $1: shyelab -node $NODE failed on $TAG.meteo.shy"; return; }
  qs=$(awk '$1 == "2009-01-01::00:05:00" { print $2; exit }' "$d/qsens.2d.1" 2> /dev/null)
  ql=$(awk '$1 == "2009-01-01::00:05:00" { print $2; exit }' "$d/qlat.2d.1" 2> /dev/null)
  if [ -z "$qs" ] || [ -z "$ql" ]; then
    fail "row $1: no record 2009-01-01::00:05:00 of qsens/qlat at node $NODE"; return
  fi
  echo "  node $NODE, first step: qsens $qs, qlat $ql W/m**2 (expected $QSENS_REF, $QLAT_REF +- $TOL)"
  awk -v a="$qs" -v b="$QSENS_REF" -v c="$ql" -v d="$QLAT_REF" -v t="$TOL" \
      'BEGIN { exit !( (a-b <= t && b-a <= t) && (c-d <= t && d-c <= t) ) }' \
    || fail "row $1: qsens/qlat at node $NODE are $qs/$ql, not $QSENS_REF/$QLAT_REF within $TOL (the transfer speed is not the 10 m wind?)"
}

echo "=== 1. serial: mm_hyd_41 with iheat = 8, six hours"
timeout 600 nice -n 10 shyfem "$TAG.str" > "$SCR/1.log" 2>&1; r=$?
if ended "$r" "$SCR/1.log"; then echo "  ended"; fluxes 1
else grep "STOP" "$SCR/1.log" | head -3; tail -2 "$SCR/1.log"; fail "row 1: the serial run did not end (exit $r)"; fi

echo "=== 2. $NP processes: the same run"
for f in "$HERE/$TAG".*; do [ "$f" = "$HERE/$TAG.str" ] || rm -f "$f"; done
timeout 600 nice -n 10 mpirun --oversubscribe -np "$NP" shyfem "$TAG.str" > "$SCR/2.log" 2>&1; r=$?
if ended "$r" "$SCR/2.log"; then echo "  ended"; fluxes 2
else grep "STOP\|error stop" "$SCR/2.log" | head -3; tail -2 "$SCR/2.log"; fail "row 2: the run did not end on $NP processes (exit $r)"; fi

echo "=== 3. serial: 2009-01-02 06:00 to 10:00, through the calm wind record of 09:00"
timeout 600 nice -n 10 shyfem "${TAG}c.str" > "$SCR/3.log" 2>&1; r=$?
if ended "$r" "$SCR/3.log"; then echo "  ended"
else grep "STOP\|Floating-point\|SIGFPE" "$SCR/3.log" | head -3; tail -2 "$SCR/3.log"; fail "row 3: the run through a calm record did not end (exit $r)"; fi

if [ "$rc" = 0 ]; then
  echo "IHEAT8 CHECK: PASS"
  rm -rf "$SCR"
else
  echo "IHEAT8 CHECK: FAIL (logs in $SCR)"
fi
exit "$rc"
