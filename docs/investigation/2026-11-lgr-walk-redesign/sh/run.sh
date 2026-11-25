#!/bin/bash
# run.sh NAME STRFILE KEEP [ENV=VAL ...]: runs STRFILE in $S/runs/NAME with the
# frozen debug binary $S/bin/shyfem (serial, 1 thread, nice 10). KEEP=0 deletes
# every .shy/.ext/.inf after the run (chi2 from the vprof lines of the log);
# KEEP=1 keeps the particle and hydro files for an analysis that deletes them.
# RUNBIN=dir overrides the binary folder (e.g. the frozen mwalk binary).
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk2.VMQJdX
TC=/home/razinka/wt-mwalk2/testcases/examples/mar_menor
n="$1"; strf="$2"; keep="$3"; shift 3
d="$S/runs/$n"; str=$(basename "$strf" .str)
rm -rf "$d"; mkdir -p "$d" || exit 1
cd "$d" || exit 1
ln -s "$TC/GRID" GRID && ln -s "$TC/INPUT" INPUT || exit 1
cp "$strf" "$str.str" || exit 1
echo "$*" > "$n.env"
export TMPDIR="$S" OMP_NUM_THREADS=1
l0=$(cut -d' ' -f1 /proc/loadavg)
/usr/bin/time -f "wall %e s user %U s maxrss %M kB" -o "$n.time" \
  env "$@" PATH="${RUNBIN:-$S/bin}:/usr/bin:$PATH" nice -n 10 shyfem "$str.str" < /dev/null > "$n.log" 2>&1
rc=$?
[ -f lgr_vdbg.txt ] && mv lgr_vdbg.txt "$n.vdbg.txt"
[ -f "$str.lgr.shy" ] && mv "$str.lgr.shy" "$n.lgr.shy"
if [ "$keep" = 0 ]; then rm -f ./*.shy ./*.ext ./*.inf; fi
echo "$n rc=$rc end=$(grep -c 'simulation end' "$n.log") $(tail -1 "$n.time") load $l0 $(cut -d' ' -f1 /proc/loadavg)"
exit $rc
