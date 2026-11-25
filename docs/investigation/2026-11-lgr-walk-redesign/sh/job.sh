#!/bin/bash
# job.sh NAME STRFILE VARIANT KEEPMODE [ENV=VAL ...]
#   VARIANT: S (HDFIX TFIX, Milstein, cap 10000), N2 (NOSTOP Visser),
#            P7 (no variant env: the caller gives all)
#   KEEPMODE: chi2 (vprof only, files deleted) | keep (particle file kept)
#            | anaA (anaA.py + splitA.py on the particle file, then deleted)
S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk2.VMQJdX
TC=/home/razinka/wt-mwalk2/testcases/examples/mar_menor
n="$1"; strf="$2"; v="$3"; km="$4"; shift 4
case "$v" in
  S)  venv="LGR_DBG_HDFIX=1 LGR_DBG_TFIX=1 LGR_DBG_VCAP=10000" ;;
  N2) venv="LGR_DBG_NOSTOP=1 LGR_DBG_MODE=2 LGR_DBG_VCAP=1000000" ;;
  P7) venv="" ;;
  *) echo "unknown variant $v"; exit 2 ;;
esac
keep=0; [ "$km" != chi2 ] && keep=1
vp="LGR_DBG_VPROF=1"; [ "$km" = anaA ] && vp=""
$S/run.sh "$n" "$strf" $keep $venv $vp "$@"
rc=$?
d=$S/runs/$n; str=$(basename "$strf" .str)
if [ "$km" = anaA ]; then
  python3 -I $S/py299/anaA.py $TC "$d/$n.lgr.shy" "$d/$str.hydro.shy" $S/res/$n.json > $S/res/$n.anaA.txt 2>&1 || echo "$n anaA failed"
  python3 -I $S/py299/splitA.py $TC "$d/$n.lgr.shy" "$d/$str.hydro.shy" > $S/res/split_$n.txt 2>&1 || echo "$n splitA failed"
  rm -f "$d"/*.shy "$d"/*.ext "$d"/*.inf
fi
exit $rc
