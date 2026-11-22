#!/bin/bash
# Task 7.2 C3, third part.
#  case 7, second try: squares that hold every vertex of both elements of each
#  side (t72_c7find.py, release file release_case7b.txt); same sides, same
#  midpoints.  (The first try's check reported one copy per point; the cause
#  was the checker, which matched the dump's x, y exactly although they come
#  back from xi: see t72_c7run.sh.  The squares were made larger before that
#  was found; it is not known that the first squares missed an element.)
#  AC5: a third serial run of case D (S3), for the spread of three serial runs.
# usage: t72_acc3.sh T72ACC_DIR   (the folder t72_acc.sh printed first: the
# particle files of its case D runs)
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1; T=$W/testcases/examples/mar_menor
C7=$EV		# release_case7b.txt (made by t72_c7find.py)
A="${1:?usage: t72_acc3.sh T72ACC_DIR}"
D=$(mktemp -d "${TMPDIR:-/tmp}/t72acc3.XXXXXX") || exit 1
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
}
echo "=== $(date +%H:%M:%S) spec section 7, case 7 (squares holding both elements of each side)"
r=$(copy case7b) || exit 1
cp "$C7/release_case7b.txt" "$r/release_case7.txt"
sed -i "s|lgrlin = 'release_areas.txt'|lgrlin = 'release_case7.txt'|" "$r/mm_lgr_a.str"
grep -q "lgrlin = 'release_case7.txt'" "$r/mm_lgr_a.str" || { echo "sed did not apply"; exit 1; }
cat "$r/release_case7.txt"
PTS="-0.685530782 37.6688919 -0.640307009 37.7183838"
for np in 2 4; do
  drv "$r" mm_lgr_a $np part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids
  grep -E 'lgr_init_line|particles inserted|elements fully in line|elements to be checked' "$r/model.mm_lgr_a.$np.part.ser.log" | tr -s ' ' | sed 's/^/    serial: /'
  python3 "$EV/t72_c7check.py" "$r/mm_lgr_a.serial.dbg" "$r/mm_lgr_a.np$np.dbg" $PTS | sed 's/^/    /'
  drv "$r" mm_lgr_a $np ids
  grep -E 'output times|first output|last output' "$r/drv.mm_lgr_a.$np.ids.log" | head -6 | sed 's/^/    /'
done
rm -rf "$r"/*.dbg "$r"/*.shy

echo "=== $(date +%H:%M:%S) AC5: a third serial run of case D"
r=$(copy s3) || exit 1
( cd "$r" && nice -n 19 shyfem mm_lgr.str > s3.log 2>&1 ); echo "S3 serial run: exit $?, ended $(grep -c 'simulation end' "$r/s3.log")"
python3 "$EV/../ac5_stats.py" S1="$A/mm_lgr.2.ids.serial.lgr.shy" S2="$A/mm_lgr.4.ids.serial.lgr.shy" np2="$A/mm_lgr.2.ids.mpi.lgr.shy" np4="$A/mm_lgr.4.ids.mpi.lgr.shy" S3="$r/mm_lgr.lgr.shy" > "$D/ac5_s3.log" 2>&1
echo "ac5_stats exit $?"; cat "$D/ac5_s3.log"
cp "$r/mm_lgr.lgr.shy" "$D/mm_lgr.S3.lgr.shy"; rm -f "$r"/*.shy
echo "=== $(date +%H:%M:%S) DONE (logs in $D)"
