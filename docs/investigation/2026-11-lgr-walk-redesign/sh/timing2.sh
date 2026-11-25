#!/bin/bash
# timing2.sh: the fixed part (all but the walk) on both timing cases: N2 at
# constant K (LGR_DBG_KCONST=0.01, 1 walk call per particle step), 3 rounds,
# sequential, nothing else of mine running
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk2.VMQJdX
N2="LGR_DBG_NOSTOP=1 LGR_DBG_MODE=2 LGR_DBG_VCAP=1000000 LGR_DBG_KCONST=0.01"
for i in 1 2 3; do
  $S/run.sh tr_K_$i $S/str/lgr_ilagr3.str 0 $N2 >> $S/res/timing_r.txt 2>&1
  $S/run.sh th_K_$i $S/str/lgr_wm.str 0 LGR_DBG_NOADV=1 $N2 >> $S/res/timing_h.txt 2>&1
done
echo timing2 done >> $S/res/timing_h.txt
