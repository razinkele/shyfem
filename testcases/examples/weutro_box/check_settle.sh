#!/bin/bash
#------------------------------------------------------------------------
# weutro/EUTRO phytoplankton-settling gate (TR-05).
# eco_3d_settle has no light (PHYT stays ~uniform with depth without settling)
# and wsphyt>0, so phytoplankton must settle DOWNWARD: a deep layer's PHYT must
# clearly exceed the surface layer's. Before TR-05 wsink was hardcoded 0 and
# this redistribution could not occur.
#
# Requires ECOLOGICAL=EUTRO build + shyfem/shyelab on PATH + `make init`.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
export PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH

timeout 400 shyfem eco_3d_settle.str > eco_3d_settle.run.log 2>&1 \
  || { echo "FAIL: eco_3d_settle did not complete"; exit 1; }

phy() { shyelab -write eco_3d_settle.eutro.shy 2>/dev/null \
  | grep "l,ivar,min,aver,max" | awk -v L="$1" '$3==L && $4==704{v=$6} END{print v}'; }
NL=$(shyelab -write eco_3d_settle.eutro.shy 2>/dev/null \
  | grep "l,ivar,min,aver,max" | awk '$4==704{print $3}' | sort -n | tail -1)

surf=$(phy 1)
deep=$(phy "$NL")
echo "=== settling (final PHYT) ==="
echo "  surface (layer 1)   PHYT = $surf"
echo "  deep    (layer $NL) PHYT = $deep"
awk -v s="$surf" -v d="$deep" 'BEGIN{
  if(s=="" || d==""){print "FAIL: missing PHYT records"; exit 1}
  printf "  deep-surface = %g (settling must drive deep > surface)\n", d-s;
  if(d > s*2){print "SETTLE GATE: PASS"; exit 0}
  else {print "SETTLE GATE: FAIL (no downward redistribution)"; exit 1}
}'
