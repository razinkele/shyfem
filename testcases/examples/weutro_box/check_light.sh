#!/bin/bash
#------------------------------------------------------------------------
# weutro/EUTRO vertical-light gate — Phase 3 C1/C2 of
# docs/plans/2026-06-03-weutro-eco-fixes-plan.md
#
# With surface light over a deep stratified column, phytoplankton growth must
# decrease with depth (light attenuates). Before C1/C2 every layer received
# full surface irradiance, so PHYT was bit-identical at all depths -> this gate
# fails. After the fix the surface layer must exceed the deepest layer by a
# clear margin.
#
# Requires ECOLOGICAL=EUTRO build + shyfem/shyelab on PATH + 'make init'.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
export PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH
MARGIN=1e-4    # required (PHYT_surface - PHYT_deep)

timeout 400 shyfem eco_3d_light.str > eco_3d_light.run.log 2>&1 \
  || { echo "FAIL: eco_3d_light did not complete"; exit 1; }

# final-record PHYT (var 704) aver at surface (layer 1) and deepest layer
prof() { shyelab -write eco_3d_light.eutro.shy 2>/dev/null \
  | grep "l,ivar,min,aver,max" | awk '$4==704{print $3,$6}'; }
# take the last full set of layers (final record): collect, then surface/deep
read NL < <(prof | awk '{print $1}' | sort -n | tail -1)   # number of layers
surf=$(prof | awk -v n="$NL" '$1==1{v=$2} END{print v}')
deep=$(prof | awk -v n="$NL" -v nl="$NL" '$1==nl{v=$2} END{print v}')

echo "=== vertical light response (final PHYT) ==="
echo "  surface (layer 1)   PHYT = $surf"
echo "  deepest (layer $NL) PHYT = $deep"
awk -v s="$surf" -v d="$deep" -v m="$MARGIN" 'BEGIN{
  diff=s-d;
  printf "  surface-deep = %g (need > %g)\n", diff, m;
  if(diff>m){print "LIGHT GATE: PASS"; exit 0}
  else {print "LIGHT GATE: FAIL (no vertical light gradient -- C1/C2 unfixed)"; exit 1}
}'
