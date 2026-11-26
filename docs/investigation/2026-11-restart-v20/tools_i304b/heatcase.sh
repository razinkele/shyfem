#!/bin/bash
# heatcase.sh NAME IHEAT ITDRAG ITURB NP : one mm_hyd_41 fidelity case; also r2 = read with I304_NOEXTRA=1,
# r3 = read with I304_NORESET=1; summary to NAME.sum
set -u
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/i304b.Wtvn
N="$1"; IH="$2"; ID="$3"; IT="$4"; NP="${5:-1}"
D=$S/$N; T=$S/tools
export TMPDIR=$S
$T/mkmm.sh $D "iturb = $IT      ievap = 1       hmin = 1.    aapar = 0." "iheat = $IH   itdrag = $ID" || exit 1
sed -e "s/^        r\$/        r2/" $D/r.str > $D/r2.str
sed -e "s/^        r\$/        r3/" $D/r.str > $D/r3.str
CENV="I304_DUMP=$D/dc I304_TAGS=A I304_DPRE=0 I304_DWIN=0" $T/run3.sh $D $NP > $D/run.txt 2>&1
export PATH=/home/razinka/wt-i304b/bin:/usr/bin:$PATH
cd $D
if [ "$NP" = 1 ]; then
  env OMP_NUM_THREADS=1 I304_NOEXTRA=1 timeout 2400 nice -n 10 shyfem r2.str < /dev/null > r2.log 2>&1; echo "r2 exit $?" >> run.txt
  env OMP_NUM_THREADS=1 I304_NORESET=1 timeout 2400 nice -n 10 shyfem r3.str < /dev/null > r3.log 2>&1; echo "r3 exit $?" >> run.txt
else
  env OMP_NUM_THREADS=1 I304_NOEXTRA=1 timeout 2400 nice -n 10 mpirun --oversubscribe -x I304_NOEXTRA -np $NP shyfem r2.str < /dev/null > r2.log 2>&1; echo "r2 exit $?" >> run.txt
  env OMP_NUM_THREADS=1 I304_NORESET=1 timeout 2400 nice -n 10 mpirun --oversubscribe -x I304_NORESET -np $NP shyfem r3.str < /dev/null > r3.log 2>&1; echo "r3 exit $?" >> run.txt
fi
{
  echo "===== $N: iheat=$IH itdrag=$ID iturb=$IT np=$NP"
  cat run.txt
  grep -h "qflux3d: iheat\|^ *itdrag = \|iheat = " c.log | head -3
  echo "-- r (all carried)"; $T/summ.py $D c r
  echo "-- r2 (extras windcd/tws/dtw NOT restored)"; $T/summ.py $D c r2
  echo "-- r3 (setweg clock NOT reset)"; $T/summ.py $D c r3
} > $S/$N.sum 2>&1
