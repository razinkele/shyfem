#!/bin/bash
# timing.sh: sequential user-CPU timings, nothing else of mine running.
# Part 1, reproducer (check_lgr_fixes.sh ilagr3 case, GOTM with advection,
# 2914 particles): S, S capped at 5 s and 2 s, N2, and the N2 settings A1,
# B07, A3, 3 rounds (per-call fits: N2 line from N2/A1/B07/A3, S line from
# S/S_dt5/S_dt2). Part 2, particle-heavy (GOTM without advection, 39,960
# particles, seed 1): S, N2, B07, 3 rounds. Each line: user time and the
# load at start and end (runs above load 8 are discarded in the analysis).
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk2.VMQJdX
R=$S/str/lgr_ilagr3.str
G=$S/str/lgr_wm.str
N2="LGR_DBG_NOSTOP=1 LGR_DBG_MODE=2 LGR_DBG_VCAP=1000000"
SS="LGR_DBG_HDFIX=1 LGR_DBG_TFIX=1 LGR_DBG_VCAP=10000"
declare -A E
E[S]="$SS"
E[Sdt5]="$SS LGR_DBG_DTMAX=5"
E[Sdt2]="$SS LGR_DBG_DTMAX=2"
E[N2]="$N2"
E[A1]="$N2 LGR_DBG_DTCRIT=1 LGR_DBG_FACV=0.05 LGR_DBG_DTMIN=2 LGR_DBG_DTMING=0.5"
E[B07]="$N2 LGR_DBG_DTCRIT=1 LGR_DBG_FACV=0.07 LGR_DBG_DTMIN=2 LGR_DBG_DTMING=0.2"
E[A3]="$N2 LGR_DBG_DTCRIT=1 LGR_DBG_FACV=0.05 LGR_DBG_DTMIN=2 LGR_DBG_DTMING=0.2"
for i in 1 2 3; do
  for v in S Sdt5 Sdt2 N2 A1 B07 A3; do
    $S/run.sh tr_${v}_$i $R 0 ${E[$v]} >> $S/res/timing_r.txt 2>&1
  done
done
echo timing part 1 done >> $S/res/timing_r.txt
for i in 1 2 3; do
  for v in S N2 B07; do
    $S/run.sh th_${v}_$i $G 0 LGR_DBG_NOADV=1 ${E[$v]} >> $S/res/timing_h.txt 2>&1
  done
done
echo timing part 2 done >> $S/res/timing_h.txt
