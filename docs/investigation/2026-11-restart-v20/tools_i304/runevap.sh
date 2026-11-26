#!/bin/bash
# runevap.sh DIR : as rundump.sh, and evapv carried from w41 to r41 by the I304 side file
set -u
D="$1"; BIN="${2:-/home/razinka/wt-i304/bin}"
export PATH=$BIN:/usr/bin:$PATH
cd "$D" || exit 1
( I304_DUMP=$D/dc timeout 1200 nice -n 10 shyfem c41.str < /dev/null > c41.log 2>&1; echo "c41 exit $?" > c41.rc ) &
( I304_EVAPW=$D/evap.bin timeout 1200 nice -n 10 shyfem w41.str < /dev/null > w41.log 2>&1; echo "w41 exit $?" > w41.rc ) &
wait
cat c41.rc w41.rc
I304_EVAPR=$D/evap.bin I304_DUMP=$D/dr timeout 1200 nice -n 10 shyfem r41.str < /dev/null > r41.log 2>&1; echo "r41 exit $?"
grep -c "simulation end" c41.log w41.log r41.log
grep -h "I304:" w41.log r41.log
