#!/bin/bash
#------------------------------------------------------------------------
# MFS bulk heat flux (iheat = 8), issue #319.
#
# Usage:  ./check_iheat8.sh [NP]     (processes of row 2, default 4)
#
# Each row runs a scratch copy of mm_hyd_41.str (run name of its own, made
# by sed in this folder, its outputs removed at the end; the logs go to a
# folder made with mktemp under ${TMPDIR:-/tmp}, removed when every row
# passed, kept and named when one failed): without the tilt lines, six
# hours, with "iheat = 8" added to the iturb line.  The heat forcing is
# INPUT/qflux09.txt (solar radiation, air temperature, relative humidity,
# cloud cover) as for any other iheat.  A run has ended only if its
# launcher exits with 0, its log has "simulation end" and no "STOP" line.
#
#   1. serial: the run ends.  Before #319 meteo_get_heat_extra passed the
#      pressure to rh2dp in Pa (101325), rh2dp wants mbar and stopped the
#      run at the first heat step with the bare stop "error stop wb2rh:
#      pressure" (exit code 0, no "simulation end").
#   2. NP processes: the same run ends on every process.
#
# Needs shyfem and mpirun on PATH (an OpenMPI build) and `make init` done.
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

for t in shyfem mpirun; do
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
sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
    -e "s/^        mm_hyd_41\$/        $TAG/" \
    -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
    -e 's/^\(        iturb = 1      ievap = 1       hmin = 1\.    aapar = 0\.\)$/\1\n        iheat = 8/' \
    mm_hyd_41.str > "$TAG.str"
[ "$(grep -c '^        iheat = 8$' "$TAG.str")" = 1 ] || { echo "IHEAT8 CHECK FAIL: the sed expression set no iheat"; exit 1; }

ended() { [ "$1" = 0 ] && grep -q "simulation end" "$2" && ! grep -q "STOP" "$2"; }

echo "=== 1. serial: mm_hyd_41 with iheat = 8, six hours"
timeout 600 nice -n 10 shyfem "$TAG.str" > "$SCR/1.log" 2>&1; r=$?
if ended "$r" "$SCR/1.log"; then echo "  ended"
else grep "STOP" "$SCR/1.log" | head -3; tail -2 "$SCR/1.log"; fail "row 1: the serial run did not end (exit $r)"; fi

echo "=== 2. $NP processes: the same run"
for f in "$HERE/$TAG".*; do [ "$f" = "$HERE/$TAG.str" ] || rm -f "$f"; done
timeout 600 nice -n 10 mpirun --oversubscribe -np "$NP" shyfem "$TAG.str" > "$SCR/2.log" 2>&1; r=$?
if ended "$r" "$SCR/2.log"; then echo "  ended"
else grep "STOP\|error stop" "$SCR/2.log" | head -3; tail -2 "$SCR/2.log"; fail "row 2: the run did not end on $NP processes (exit $r)"; fi

if [ "$rc" = 0 ]; then
  echo "IHEAT8 CHECK: PASS"
  rm -rf "$SCR"
else
  echo "IHEAT8 CHECK: FAIL (logs in $SCR)"
fi
exit "$rc"
