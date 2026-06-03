#!/bin/bash
#------------------------------------------------------------------------
# weutro/EUTRO eco testcase gate — Phase 0.4 of
# docs/plans/2026-06-03-weutro-eco-fixes-plan.md
#
# Runs the 2D and 3D eco cases and asserts:
#   1. the run completes (shyfem exit 0)
#   2. no NaN/Inf/'***' in the .inf log
#   3. every pelagic state variable (701..709) stays >= -TOL  (positivity)
#   4. dissolved oxygen (706) stays within a physical range [0, 25] mg/L
# Prints a baseline min/aver/max summary per variable.
#
# Requires shyfem + shyelab on PATH and an ECOLOGICAL=EUTRO build.
#   make fem ECOLOGICAL=EUTRO   (from repo root)
# Usage:  ./check_eco.sh
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH
TOL=1e-6          # allowed slack below zero (pre-fix; should tighten after Phase 1)
DO_MAX=25.0
rc=0

run_case() {
  local str="$1" tag="$2"
  echo "=================================================================="
  echo "CASE: $tag  ($str)"
  echo "=================================================================="
  if ! timeout 600 shyfem "$str" > "${tag}.run.log" 2>&1; then
    echo "FAIL[$tag]: shyfem did not complete (see ${tag}.run.log)"; rc=1; return
  fi
  local inf="${str%.str}.inf"
  if grep -qiE "nan|infinity|\*\*\*\*" "$inf" 2>/dev/null; then
    echo "FAIL[$tag]: NaN/Inf/**** found in $inf"; rc=1
  fi
  local shy="${str%.str}.eutro.shy"
  if [ ! -f "$shy" ]; then echo "FAIL[$tag]: no bio output $shy"; rc=1; return; fi

  shyelab -write "$shy" 2>/dev/null | grep "l,ivar,min,aver,max" \
    | awk -v tol="$TOL" -v domax="$DO_MAX" -v tag="$tag" '
      { l=$3; ivar=$4; mn=$5+0; av=$6+0; mx=$7+0;
        if (mn ~ /[Nn][Aa][Nn]/ || mx ~ /[Nn][Aa][Nn]/) {print "FAIL["tag"]: NaN var "ivar" layer "l; bad=1}
        if (ivar>=701 && ivar<=709 && mn < -tol) {printf "FAIL[%s]: negative var %d layer %d min=%g\n",tag,ivar,l,mn; bad=1}
        if (ivar==706 && (mx > domax)) {printf "FAIL[%s]: DO out of range var706 layer %d max=%g\n",tag,l,mx; bad=1}
      }
      END{ if(bad) exit 1 }' || rc=1

  echo "--- baseline final-record summary (layer 1) ---"
  shyelab -write "$shy" 2>/dev/null | grep "l,ivar,min,aver,max" \
    | awk '$3==1 && $4>=701 && $4<=709 {printf "  var %d  min=%-12s aver=%-12s max=%-12s\n",$4,$5,$6,$7}' \
    | tail -9
  echo "PASS-checks[$tag] complete"
}

run_case eco_2d.str 2D
run_case eco_3d.str 3D

echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "ECO GATE: PASS"; else echo "ECO GATE: FAIL"; fi
exit $rc
