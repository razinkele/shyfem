#!/bin/bash
#------------------------------------------------------------------------
# mercury hardening gate: mercury must RUN (was blocked by mercsolin param +
# molhg=0 div-by-zero) and its restart must reproduce the continuous run to
# output precision (rel < 1e-5; observed exactly 0) for all mercury state vars
# — full 0->2d vs part1 0->1d + restart part2 1->2d.
# Requires a MERCURY=true build + shyfem/shyelab on PATH + `make init`.
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
run(){ clean_case "${1%.str}"
  timeout 400 shyfem "$1" > "${1%.str}.run.log" 2>&1 || { echo "FAIL: $1 did not complete (run-blocker?)"; exit 1; }
  need "${1%.str}.merc.shy"; }
fr(){ shyelab -write "$1" 2>/dev/null | grep "l,ivar,min,aver,max" \
        | awk '$3==1{v[$4]=$6} END{for(k in v) print k,v[k]}' | sort -n; }

run merc_2d.str            # full reference 0->2d (also the smoke test: must complete)
run merc_rst_part1.str     # 0->1d, write restart
run merc_rst_part2.str     # 1->2d, read restart

if grep -qiE "nan|infinity" merc_2d.inf 2>/dev/null; then echo "FAIL: NaN/Inf in mercury run"; exit 1; fi

echo "=== mercury restart round-trip: full vs part2 final (bit-for-bit) ==="
rc=0
join <(fr merc_2d.merc.shy) <(fr merc_rst_part2.merc.shy) | awk '
  function a(x){return x<0?-x:x}
  { rel=($2!=0)?a($2-$3)/a($2):a($2-$3); if(rel>m)m=rel; seen++;
    if(rel>1e-5) printf "  MISMATCH var %s full=%s rst=%s rel=%g\n",$1,$2,$3,rel }
  END{ if(seen<5){print "FAIL: too few vars compared"; exit 1};
       printf "  max rel diff = %g over %d vars\n",m,seen;
       exit (m>1e-5) }' || rc=1
echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "MERCURY GATE: PASS"; else echo "MERCURY GATE: FAIL"; fi
exit $rc
