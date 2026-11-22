#!/bin/bash
# Task 7.2 C3: spec section 7, case 7, the run of record.  Squares that hold
# every vertex of both elements of each side (t72_c7find.py, release file
# release_case7b.txt).  t72_c7check.py matches the point within 1e-5 degrees:
# the dump's x, y come back from xi, so the two copies of a point differ in
# the last bits, and the exact match of the two earlier checks (t72_acc2.sh,
# t72_acc3.sh) found only one of them.
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1; T=$W/testcases/examples/mar_menor
C7=$EV		# release_case7b.txt (made by t72_c7find.py)
D=$(mktemp -d "${TMPDIR:-/tmp}/t72c7run.XXXXXX") || exit 1
echo "scratch: $D   head: $(git -C "$W" rev-parse --short HEAD)   binary sha256 $(sha256sum $W/src/shyfem/shyfem | cut -c1-16)   $(date '+%F %T %Z')"
export PATH=$W/bin:/usr/bin:$PATH
copy() {
  local r="$D/$1"; mkdir "$r"
  git -C "$W" archive HEAD testcases/examples/mar_menor | tar -x -C "$r" --strip-components=3 || return 1
  ( cd "$r/GRID" && shypre -noopti MM_geo.grd > shypre_geo.log 2>&1 ) || return 1
  echo "$r"
}
drv() {
  local dir=$1 c=$2 np=$3 m=$4; shift 4
  ( cd "$dir" && timeout 3600 nice -n 19 bash check_lgr_mpi.sh $c $np $m "$@" > "drv.$c.$np.$m.log" 2>&1 ); local rc=$?
  cp "$dir/$c.np$np.log" "$dir/model.$c.$np.$m.mpi.log" 2>/dev/null; cp "$dir/$c.serial.log" "$dir/model.$c.$np.$m.ser.log" 2>/dev/null
  printf '%-9s %2s %-8s exit %d: %s\n' $c $np $m $rc "$(grep 'LGR GATE' "$dir/drv.$c.$np.$m.log" | tail -1)"
  return $rc
}
nbad=0		# driver calls and checks that failed (the script's exit status)
echo "=== $(date +%H:%M:%S) spec section 7, case 7 (squares holding both elements of each side)"
r=$(copy case7b) || exit 1
cp "$C7/release_case7b.txt" "$r/release_case7.txt"
sed -i "s|lgrlin = 'release_areas.txt'|lgrlin = 'release_case7.txt'|" "$r/mm_lgr_a.str"
grep -q "lgrlin = 'release_case7.txt'" "$r/mm_lgr_a.str" || { echo "sed did not apply"; exit 1; }
cat "$r/release_case7.txt"
PTS="-0.685530782 37.6688919 -0.640307009 37.7183838"
for np in 2 4; do
  drv "$r" mm_lgr_a $np part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids || nbad=$((nbad + 1))
  grep -E 'lgr_init_line|particles inserted|elements fully in line|elements to be checked' "$r/model.mm_lgr_a.$np.part.ser.log" | tr -s ' ' | sed 's/^/    serial: /'
  python3 "$EV/t72_c7check.py" "$r/mm_lgr_a.serial.dbg" "$r/mm_lgr_a.np$np.dbg" $PTS | sed 's/^/    /'
  [ "${PIPESTATUS[0]}" = 0 ] || { nbad=$((nbad + 1)); echo "    t72_c7check.py failed ($np processes)"; }
  drv "$r" mm_lgr_a $np ids || nbad=$((nbad + 1))
  grep -E 'output times|first output|last output' "$r/drv.mm_lgr_a.$np.ids.log" | head -6 | sed 's/^/    /'
done
rm -rf "$r"/*.dbg "$r"/*.shy

echo "=== $(date +%H:%M:%S) DONE (logs in $D); failed driver calls and checks: $nbad"
[ "$nbad" = 0 ] || exit 1
