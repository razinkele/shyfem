#!/bin/bash
# runcase.sh DIR [BIN] : runs c41 and w41 (in parallel), then r41 reading w41.rst, serially
set -u
D="$1"; BIN="${2:-/home/razinka/wt-i304/bin}"
export PATH=$BIN:/usr/bin:$PATH
cd "$D" || exit 1
( timeout 1200 nice -n 10 shyfem c41.str < /dev/null > c41.log 2>&1; echo "c41 exit $?" > c41.rc ) &
( timeout 1200 nice -n 10 shyfem w41.str < /dev/null > w41.log 2>&1; echo "w41 exit $?" > w41.rc ) &
wait
cat c41.rc w41.rc
timeout 1200 nice -n 10 shyfem r41.str < /dev/null > r41.log 2>&1; echo "r41 exit $?"
grep -c "simulation end" c41.log w41.log r41.log
