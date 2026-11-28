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
BIN="${SHYFEM_BIN:-$HERE/../../../bin}"   # SHYFEM_BIN=<bin dir> to use another build
export PATH="$BIN:/usr/bin:$PATH"

# clean_case NAME...: delete every output of these cases before the run, so the
# gate cannot pass on a file an earlier run (another build) left behind. Inputs
# (STR, GRID/, INPUT/) are never touched. need FILE...: the run must have written them.
clean_case() { local n; for n in "$@"; do
  rm -f "$n".{eutro,hydro,fvl,lcz,merc}.shy "$n".{inf,run.log,rst,ext,flx}; done; }
need() { local f; for f in "$@"; do [ -s "$f" ] || {
  echo "FAIL: $f was not written by this run (no stale output is accepted; is the ecology module linked?)"; exit 1; }; done; }

clean_case eco_3d_settle
timeout 400 shyfem eco_3d_settle.str > eco_3d_settle.run.log 2>&1 \
  || { echo "FAIL: eco_3d_settle did not complete"; exit 1; }

need eco_3d_settle.eutro.shy

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
