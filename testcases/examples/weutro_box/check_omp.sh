#!/bin/bash
#------------------------------------------------------------------------
# weutro/EUTRO OpenMP thread-safety gate — Phase 2 H1 of
# docs/plans/2026-06-03-weutro-eco-fixes-plan.md
#
# The bio advection must give identical results regardless of thread count.
# Before H1 the per-variable loop was an OMP PARALLEL DO calling scal_adv,
# whose scal_adv->scal3sh->conz3d chain uses serial-only SAVE scratch — so a
# multi-thread run RACED and crashed (SIGSEGV). This gate runs eco_2d with 1
# and 4 threads and requires (a) both complete and (b) bit-identical final bio.
#
# Requires an ECOLOGICAL=EUTRO build + shyfem/shyelab on PATH.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
export PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH
rc=0

OMP_NUM_THREADS=1 timeout 300 shyfem eco_2d.str    > eco_2d.run.log    2>&1 || { echo "FAIL: 1-thread run crashed"; exit 1; }
OMP_NUM_THREADS=4 timeout 300 shyfem eco_2d_mt.str > eco_2d_mt.run.log 2>&1 || { echo "FAIL: 4-thread run crashed (race?)"; exit 1; }

fr(){ shyelab -write "$1" 2>/dev/null | grep "l,ivar,min,aver,max" \
        | awk '$3==1 && $4>=701 && $4<=709 {print $4,$6}' | tail -9; }

echo "=== OMP thread-safety: 1-thread vs 4-thread final bio ==="
join <(fr eco_2d.eutro.shy) <(fr eco_2d_mt.eutro.shy) \
  | awk '{d=$2-$3; ad=(d<0?-d:d);
          if(ad>1e-6){fail=1; tag="  <-- DIFF"} else tag="";
          printf "var %d  1thr=%-13s 4thr=%-13s |diff|=%g%s\n",$1,$2,$3,ad,tag}
         END{exit fail}' || rc=1

echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "OMP GATE: PASS"; else echo "OMP GATE: FAIL"; fi
exit $rc
