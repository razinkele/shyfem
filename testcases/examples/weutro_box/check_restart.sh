#!/bin/bash
#------------------------------------------------------------------------
# weutro/EUTRO restart round-trip gate — Phase 2 C4 of
# docs/plans/2026-06-03-weutro-eco-fixes-plan.md
#
# Proves the ecological state survives a restart:
#   full   : run 0 -> 2 days continuously                  (reference)
#   part1  : run 0 -> 1 day, write a restart (idtrst=-1)
#   part2  : run 1 -> 2 days, read part1's restart (itrst=-1)
# The final bio state of part2 must equal that of full (within TOL).
# Before C4 the eco restart was a no-op (bio cold-started to einit at the
# restart boundary), so part2 diverged -> this gate failed.
#
# Requires an ECOLOGICAL=EUTRO build + shyfem/shyelab on PATH.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
export PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH
TOL=1e-4

run() { timeout 300 shyfem "$1" > "${1%.str}.run.log" 2>&1 || { echo "FAIL: $1 did not complete"; exit 1; }; }
final_rec() {  # last time-record, layer1, vars 701-709 -> "varid value"
  shyelab -write "$1" 2>/dev/null | grep "l,ivar,min,aver,max" \
    | awk '$3==1 && $4>=701 && $4<=709 {print $4, $6}' | tail -9
}

run eco_2d.str            # full reference (0->2d)
run eco_rst_part1.str     # 0->1d, writes eco_rst_part1.rst
run eco_rst_part2.str     # 1->2d, reads the restart

echo "=== restart round-trip: full vs part2 final state ==="
rc=0
join <(final_rec eco_2d.eutro.shy) <(final_rec eco_rst_part2.eutro.shy) \
  | awk -v tol="$TOL" '
    { d=$2-$3; ad=(d<0?-d:d);
      bad=(ad>tol)?"  <-- MISMATCH":"";
      if(ad>tol) fail=1;
      printf "var %d  full=%-13s restart=%-13s  |diff|=%g%s\n",$1,$2,$3,ad,bad }
    END{ exit fail }' || rc=1

echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "RESTART GATE: PASS"; else echo "RESTART GATE: FAIL"; fi
exit $rc
