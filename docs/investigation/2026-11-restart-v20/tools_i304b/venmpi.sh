#!/bin/bash
# venmpi.sh NP : venlag_smoke fidelity on NP processes (restart 03:00) + controls
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/i304b.Wtvn
NP=$1; D=$S/ven$NP
export TMPDIR=$S
$S/tools/mkven.sh $D 03:00 || exit 1
$S/tools/run3.sh $D $NP > $D/run.txt 2>&1
{ echo "===== venlag np=$NP"; cat $D/run.txt; $S/tools/summ.py $D c r 4 6
  $S/tools/rr.sh $D $NP rnoreset 4 6 I304_NORESET=1
  $S/tools/rr.sh $D $NP rmain 4 6 I304_SKIP=iwetv,evapv,windcd,tws,dtw I304_NORESET=1
  $S/tools/rr.sh $D $NP rnoiwetv 4 6 I304_SKIP=iwetv
} > $S/ven$NP.sum 2>&1
