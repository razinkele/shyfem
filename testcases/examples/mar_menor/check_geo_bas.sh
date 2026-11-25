#!/bin/bash
#------------------------------------------------------------------------
# GRID/MM_geo.bas is the one that today's shypre writes (issue #280).
#
# Usage:  ./check_geo_bas.sh [--check-only] [--build-missing] [DIR [LABEL]]
#
#   DIR    the mar_menor folder (default: the folder of this script)
#   LABEL  the prefix of the message, e.g. "LGR GATE" (default "GEO BAS")
#
# The geographic basin GRID/MM_geo.bas is not tracked (it is in .gitignore)
# and not made by `make init`: users build it by hand with
#   (cd GRID && shypre -noopti MM_geo.grd)
# so a tree keeps whatever file it was given.  The decimal parsing of
# 9abe01a4 (2026-10-16, "parse decimal digits exactly") changed what shypre
# writes: a file built before it differs in the depth of 112 of the 2,545
# elements (336 values, at most 1.9e-6 m, one unit in the last place of a
# single precision number; nothing else: the nodes and the coordinates are
# the same bytes).  The file of the live tree (2026-06-12) is byte-identical
# to what the shypre before 9abe01a4 writes.  Every case that reads it
# (mm_lgr, mm_lgr_a, c, e, w) then gives other bytes, at
# round-off size: measured on one binary, hydro |d| up to 2.6e-5 (transport)
# and 1.4e-6 m (level), 3 to 24 particles of 80 to 648 beyond 1e-5 degrees at
# the end, the largest distance at any output 2.3e-4 to 2.1e-2 degrees (the
# last one is mm_lgr, the random walk; see the CHANGELOG line of #280).
#
# This script builds the basin with the shypre on PATH into a folder of its
# own (made with mktemp under ${TMPDIR:-/tmp}, removed at the end) and
# compares it with GRID/MM_geo.bas:
#   - the same bytes: nothing is printed (exit 0), so that a fresh tree
#     keeps the output of its gates as it was;
#   - other bytes: the file is replaced with the fresh one and ONE line says
#     so (exit 0).  With --check-only the file is not touched: one line
#     "... rebuild GRID/MM_geo.bas (cd GRID && shypre -noopti MM_geo.grd)"
#     and exit 1;
#   - missing: exit 1 with that line, or, with --build-missing, built (one
#     line, exit 0).
# Exit 2: usage; exit 1 also when shypre cannot be run or fails.
#
# The gates call it before they read the basin (check_mpi.sh,
# check_lgr_serial.sh, check_lgr_mpi.sh, check_lgr_fixes.sh,
# check_itlin.sh); test_geo_bas.sh tests it.  The scripts that already
# build the basin in a folder of their own (check_mpi_3d.sh,
# check_ghost_gather_mpi.sh, check_lgr_bounds.sh, measure_lgr_floors.sh)
# need no check.
#------------------------------------------------------------------------
set -u
CHECK_ONLY=0; BUILD_MISSING=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check-only)    CHECK_ONLY=1; shift ;;
    --build-missing) BUILD_MISSING=1; shift ;;
    --*) echo "usage: $0 [--check-only] [--build-missing] [DIR [LABEL]]"; exit 2 ;;
    *) break ;;
  esac
done
[ $# -le 2 ] || { echo "usage: $0 [--check-only] [--build-missing] [DIR [LABEL]]"; exit 2; }
DIR="${1:-$(dirname "$0")}"
LABEL="${2:-GEO BAS}"
DIR="$(cd "$DIR" 2>/dev/null && pwd)" || { echo "$LABEL FAIL: no folder $1"; exit 1; }
HINT="rebuild GRID/MM_geo.bas (cd GRID && shypre -noopti MM_geo.grd)"
GRD="$DIR/GRID/MM_geo.grd"
BAS="$DIR/GRID/MM_geo.bas"
[ -f "$GRD" ] || { echo "$LABEL FAIL: $GRD not found"; exit 1; }
command -v shypre > /dev/null 2>&1 || { echo "$LABEL FAIL: shypre is not on PATH"; exit 1; }

T="$(mktemp -d "${TMPDIR:-/tmp}/geo_bas.XXXXXX")" || { echo "$LABEL FAIL: mktemp failed"; exit 1; }
trap 'rm -rf "$T"' EXIT
trap 'rm -rf "$T"; exit 130' INT TERM
cp "$GRD" "$T/MM_geo.grd" || { echo "$LABEL FAIL: cannot copy $GRD"; exit 1; }
if ! ( cd "$T" && nice -n 19 shypre -noopti MM_geo.grd > shypre.log 2>&1 ) || [ ! -s "$T/MM_geo.bas" ]; then
  tail -3 "$T/shypre.log" 2> /dev/null
  echo "$LABEL FAIL: shypre -noopti failed on $GRD"
  exit 1
fi

if [ ! -f "$BAS" ]; then
  if [ "$BUILD_MISSING" = 1 ]; then
    cp "$T/MM_geo.bas" "$BAS.new.$$" && mv "$BAS.new.$$" "$BAS" \
      || { rm -f "$BAS.new.$$"; echo "$LABEL FAIL: cannot write $BAS"; exit 1; }
    echo "$LABEL NOTE: GRID/MM_geo.bas was missing: built with shypre -noopti"
    exit 0
  fi
  echo "$LABEL FAIL: GRID/MM_geo.bas is missing: $HINT"
  exit 1
fi

if cmp -s "$T/MM_geo.bas" "$BAS"; then
  exit 0
fi
nbytes="$(cmp -l "$T/MM_geo.bas" "$BAS" 2> /dev/null | wc -l)"
SHYPRE="$(command -v shypre)"
WHY="differs from what $SHYPRE writes in $nbytes bytes (likely built before 9abe01a4, the old parser's depths; or $SHYPRE is an older build)"
if [ -L "$BAS" ]; then
  echo "$LABEL FAIL: GRID/MM_geo.bas is a symlink to a stale file ($WHY), not replaced: $HINT"
  exit 1
fi
if [ "$CHECK_ONLY" = 1 ]; then
  echo "$LABEL FAIL: GRID/MM_geo.bas is stale ($WHY): $HINT"
  exit 1
fi
cp "$T/MM_geo.bas" "$BAS.new.$$" && mv "$BAS.new.$$" "$BAS" \
  || { rm -f "$BAS.new.$$"; echo "$LABEL FAIL: GRID/MM_geo.bas is stale and cannot be replaced: $HINT"; exit 1; }
echo "$LABEL NOTE: GRID/MM_geo.bas was stale ($WHY): replaced with what $SHYPRE writes; results of runs made with the old file differ at round-off"
exit 0
