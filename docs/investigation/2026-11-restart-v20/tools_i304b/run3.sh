#!/bin/bash
# run3.sh DIR NP [c|w|r env assignments via CENV/WENV/RENV] : c and w in parallel, then r.
# NP = 1 runs without mpirun.
set -u
D="$1"; NP="$2"
BIN=/home/razinka/wt-i304b/bin
export PATH=$BIN:/usr/bin:$PATH
cd "$D" || exit 1
runit() { # name envs
  local n="$1"; shift
  if [ "$NP" = 1 ]; then
    env "$@" timeout 2400 nice -n 10 shyfem $n.str < /dev/null > $n.log 2>&1
  else
    env "$@" timeout 2400 nice -n 10 mpirun --oversubscribe -np $NP shyfem $n.str < /dev/null > $n.log 2>&1
  fi
  echo "$n exit $?" > $n.rc
}
( runit c OMP_NUM_THREADS=1 ${CENV:-} ) &
( runit w OMP_NUM_THREADS=1 ${WENV:-} ) &
wait
runit r OMP_NUM_THREADS=1 ${RENV:-}
cat c.rc w.rc r.rc | tr '\n' ' '; echo
grep -c "simulation end" c.log w.log r.log | tr '\n' ' '; echo
grep -h "I304:" r.log | sort | uniq -c
