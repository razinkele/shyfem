#!/bin/bash
# rr.sh DIR NP NAME T1 T2 [VAR=VAL ...] : one more read run NAME (copy of r.str) with the given
# environment; prints the comparison with c at hours T1 T2
set -u
D="$1"; NP="$2"; N="$3"; T1="$4"; T2="$5"; shift 5
T=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/i304b.Wtvn/tools
export PATH=/home/razinka/wt-i304b/bin:/usr/bin:$PATH
cd "$D" || exit 1
sed -e "s/^\(\s*\)r\$/\1$N/" r.str > $N.str
grep -q "^\s*$N\$" $N.str || { echo "title not replaced"; exit 1; }
XS=""; for a in "$@"; do XS="$XS -x ${a%%=*}"; done
if [ "$NP" = 1 ]; then
  env OMP_NUM_THREADS=1 "$@" timeout 2400 nice -n 10 shyfem $N.str < /dev/null > $N.log 2>&1; rc=$?
else
  env OMP_NUM_THREADS=1 "$@" timeout 2400 nice -n 10 mpirun --oversubscribe $XS -np $NP shyfem $N.str < /dev/null > $N.log 2>&1; rc=$?
fi
echo "-- $N ($*): exit $rc, simulation end $(grep -c 'simulation end' $N.log), $(grep -h 'I304: v20' $N.log | sort -u | sed 's/^ *//')$(grep -h 'I304: setweg' $N.log | sort -u | sed 's/^ */; /')"
$T/summ.py $D c $N $T1 $T2
