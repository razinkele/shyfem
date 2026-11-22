#!/bin/bash
# g5floors.sh SRC_FOLDER CASE BIN_DIR
# Floors of a copy of a test case, the way of
# testcases/examples/mar_menor/measure_lgr_floors.sh but on the particle
# file: the base serial run against six serial runs with dragco changed by
# a relative +-1e-5, +-7e-6, +-4e-6 (binary BIN_DIR/shyfem), then
# lgr_compare.py --mode pos with huge floors to read the beyond count at the
# last output and the largest distance, and the count of other failing pairs.
# SRC_FOLDER is a copy of the test folder whose CASE.str is the copy to
# measure (for this folder: the test folder with mm_lgr_b.str replaced by
# the one here, GRID/MM_coarse.bas the tracked file); the runs are made in a
# folder from mktemp -d under ${TMPDIR:-/tmp}, printed first and last.
set -u
SRC="${1:?SRC_FOLDER}"; CASE="${2:?CASE}"; BIN="${3:?BIN_DIR}"
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1
REPO="$(git -C "$EV" rev-parse --show-toplevel)" || { echo "not inside a git checkout"; exit 1; }
W="$(mktemp -d "${TMPDIR:-/tmp}/g5floors.XXXXXX")" || exit 1
echo "$(date '+%Y-%m-%d %H:%M:%S') g5floors: $SRC/$CASE.str, binary $BIN, in $W"
cp -r "$SRC/GRID" "$SRC/INPUT" "$W/" || exit 1
[ -f "$SRC/release_areas.txt" ] && cp "$SRC/release_areas.txt" "$W/"
RELS="0 +1e-5 -1e-5 +7e-6 -7e-6 +4e-6 -4e-6"
for r in $RELS; do
  d="$W/r$r"; mkdir "$d"
  ln -s ../GRID "$d/GRID"; ln -s ../INPUT "$d/INPUT"
  [ -f "$W/release_areas.txt" ] && ln -s ../release_areas.txt "$d/release_areas.txt"
  python3 - "$SRC/$CASE.str" "$d/$CASE.str" "$r" <<'PY' || exit 1
import re, sys
src, dst, rel = sys.argv[1], sys.argv[2], float(sys.argv[3])
out, n = [], 0
for line in open(src):
    m = re.search(r'(dragco\s*=\s*)([0-9.eEdD+-]+)', line)
    if m and not line.lstrip().startswith('#'):
        base = float(m.group(2).lower().replace('d', 'e'))
        if rel != 0.0:
            line = line[:m.start(2)] + ('%.12e' % (base * (1.0 + rel))) + line[m.end(2):]
        n += 1
    out.append(line)
if n != 1:
    sys.exit('dragco lines: %d' % n)
open(dst, 'w').writelines(out)
PY
done
run_one() {
  ( cd "$W/r$1" && PATH="$BIN:/usr/bin:$PATH" nice -n 19 shyfem "$CASE.str" > run.log 2>&1 )
  grep -q "simulation end" "$W/r$1/run.log" && echo "  r$1: ended" || echo "  r$1: FAILED"
}
set -- $RELS
while [ $# -gt 0 ]; do
  run_one "$1" & p1=$!
  if [ $# -gt 1 ]; then run_one "$2" & p2=$!; wait $p2; shift; fi
  wait $p1; shift
done
T="$REPO/testcases/examples/mar_menor/lgr_compare.py"
case "$CASE" in mm_lgr_b) TOL=2 ;; *) TOL=1e-5 ;; esac
for r in +1e-5 -1e-5 +7e-6 -7e-6 +4e-6 -4e-6; do
  out="$(python3 "$T" "$W/r0/$CASE.lgr.shy" "$W/r$r/$CASE.lgr.shy" --mode pos --tol $TOL \
      --max-beyond-last 100000000 --max-largest 1e30)"
  bl=$(echo "$out" | sed -n 's/.*both files share (t=[0-9.]*): \([0-9]*\) .*/\1/p')
  lg=$(echo "$out" | sed -n 's/.*largest distance at any output\( (t=[0-9.]*)\)*: \([0-9.e+-]*\) .*/\2/p')
  np=$(echo "$out" | grep -c '^    id ')
  ids=$(echo "$out" | grep '^    id ' | awk '{print $2}' | sort -u | wc -l)
  kinds=$(echo "$out" | grep '^    id ' | sed 's/.*differs (\([a-z]*\).*/\1/' | sort | uniq -c | tr -s ' ' | tr '\n' ',')
  cnt=$(echo "$out" | grep -c 'only in A: [0-9]')
  echo "r$r: beyond_last $bl largest $lg; other failing pair lines $np (ids $ids; kinds $kinds) block-membership differences $cnt"
done
echo "$W"
