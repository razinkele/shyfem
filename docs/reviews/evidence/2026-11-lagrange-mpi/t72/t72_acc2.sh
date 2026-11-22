#!/bin/bash
# Task 7.2 C3, second part: spec section 7 cases 7, 4 and 6, each in a scratch
# copy of the test folder (git archive of HEAD; GRID/MM_geo.bas, not tracked,
# built there with shypre), with the build of this checkout (bin/) on PATH.
#  case 7: case A with a release file of two squares (t72_c7find.py), each
#          centred exactly on the midpoint of a side between elements of two
#          main owners (one side for 2 processes, one for 4); the polygon's
#          grid point (0, 0) is its centre, so a serial run inserts that point
#          in both elements.  Release gate with ids and whole-run ids on 2, 4;
#          t72_c7check.py on the release block of the dumps.
#  case 4: ../d5/run_d5.sh HEAD (case B with a partition written into the
#          basin)
#  case 6: the dense copy of case B (../case6, 200,001 particles) on 8
#          processes, driver mode part --by key (levdbg 3), then the hand-over
#          check on the same dumps; the class floor of that copy is 4
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1; T=$W/testcases/examples/mar_menor
C7=$EV		# release_case7.txt (made by t72_c7find.py)
D=$(mktemp -d "${TMPDIR:-/tmp}/t72acc2.XXXXXX") || exit 1
echo "scratch: $D   head: $(git -C "$W" rev-parse --short HEAD)   binary sha256 $(sha256sum $W/src/shyfem/shyfem | cut -c1-16)   $(date '+%F %T %Z')"
export PATH=$W/bin:/usr/bin:$PATH
copy() {  # NAME -> path of a fresh copy of the test folder
  local r="$D/$1"; mkdir "$r"
  git -C "$W" archive HEAD testcases/examples/mar_menor | tar -x -C "$r" --strip-components=3 || return 1
  ( cd "$r/GRID" && shypre -noopti MM_geo.grd > shypre_geo.log 2>&1 ) || return 1
  echo "$r"
}
drv() {  # DIR CASE NP MODE [options]: one driver call in DIR, one line
  local dir=$1 c=$2 np=$3 m=$4; shift 4
  ( cd "$dir" && timeout 7200 nice -n 19 bash check_lgr_mpi.sh $c $np $m "$@" > "drv.$c.$np.$m.log" 2>&1 ); local rc=$?
  cp "$dir/$c.np$np.log" "$dir/model.$c.$np.$m.mpi.log" 2>/dev/null; cp "$dir/$c.serial.log" "$dir/model.$c.$np.$m.ser.log" 2>/dev/null
  printf '%-9s %2s %-8s exit %d: %s\n' $c $np $m $rc "$(grep 'LGR GATE' "$dir/drv.$c.$np.$m.log" | tail -1)"
}

echo "=== $(date +%H:%M:%S) spec section 7, case 7: a release point on a side between elements of two processes"
r=$(copy case7) || exit 1
cp "$C7/release_case7.txt" "$r/release_case7.txt"
sed -i "s|lgrlin = 'release_areas.txt'|lgrlin = 'release_case7.txt'|" "$r/mm_lgr_a.str"
grep -q "lgrlin = 'release_case7.txt'" "$r/mm_lgr_a.str" || { echo "sed did not apply"; exit 1; }
cat "$r/release_case7.txt"
PTS="-0.685530782 37.6688919 -0.640307009 37.7183838"
for np in 2 4; do
  drv "$r" mm_lgr_a $np part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids
  grep -E 'lgr_init_line|lagr_init_all:|particles inserted' "$r/model.mm_lgr_a.$np.part.ser.log" | head -4 | tr -s ' ' | sed 's/^/    serial: /'
  python3 "$EV/t72_c7check.py" "$r/mm_lgr_a.serial.dbg" "$r/mm_lgr_a.np$np.dbg" $PTS | sed 's/^/    /'
  drv "$r" mm_lgr_a $np ids
  grep -E 'output times|first output|last output' "$r/drv.mm_lgr_a.$np.ids.log" | head -6 | sed 's/^/    /'
done
rm -rf "$r"/*.dbg "$r"/*.shy

echo "=== $(date +%H:%M:%S) spec section 7, case 4: ../d5/run_d5.sh HEAD"
bash "$EV/../d5/run_d5.sh" HEAD > "$D/d5.log" 2>&1; echo "run_d5.sh exit $?"; cat "$D/d5.log"

echo "=== $(date +%H:%M:%S) spec section 7, case 6: the dense copy of case B on 8 processes"
r=$(copy case6) || exit 1
cp "$EV/../case6/mm_lgr_b_dense200k.str" "$r/mm_lgr_b.str"
drv "$r" mm_lgr_b 8 part --by key
sed -n '/=== 3/,$p' "$r/drv.mm_lgr_b.8.part.log" | grep -vE '^ *$' | head -40 | cut -c1-200
grep -E 'lgr hand-over|lgr dry|lgr left|lgr relocation by|consistency' "$r/model.mm_lgr_b.8.part.mpi.log" | sed 's/^ *//' | cut -c1-260
echo "consistency check lines in the MPI log: $(grep -c 'lgr_mpi_check_consistency' "$r/model.mm_lgr_b.8.part.mpi.log")"
( cd "$r" && python3 lgr_dbg_compare.py part mm_lgr_b.serial.dbg mm_lgr_b.np8.dbg --tol 2 --by key --handover --step 0.25 --min-changed 1 > handover.log 2>&1 ); echo "hand-over check on the dense dumps: exit $?"
grep -E 'rule:|changed|PASS|FAIL' "$r/handover.log" | tail -6 | cut -c1-250
du -sh "$r"
rm -rf "$r"/*.dbg "$r"/*.shy
echo "=== $(date +%H:%M:%S) DONE (logs in $D)"
