#!/bin/bash
#------------------------------------------------------------------------
# NetCDF conversion gate for several tracers (#292): `shyelab -outformat nc`
# of a .conz.shy file with iconz = 2 (ids 301 and 302).
#
# Before the fix both ids were called `concentration`, the second define
# failed with "NetCDF: String match to name in use" and shyelab exited 1
# (or, before #222, left a 32 byte zero out.nc).
#
# It runs mm_hyd_conz.str with iconz = 2 for 6 h and asserts:
#   1. shyelab -outformat nc exits 0 and out.nc passes `ncdump -h`
#   2. out.nc has exactly the data variables concentration_1 and
#      concentration_2 (the name carries the id: 301 -> 1, 302 -> 2)
#   3. at the last record min and max of each equal `shyelab -write`
#      (relative 2e-5: -write prints 6 digits)
#   4. a file with ONE tracer (shyelab -split) still gives `concentration`
#      (unchanged name, the results viewer of shyfem-ui looks for it)
#
# Requires a NETCDF=true build and the mar_menor basin (make init).
# Usage:  ./check_nc_tracers.sh      (SHYFEM_BIN=<bin dir> for another build)
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="${SHYFEM_BIN:-$HERE/../../../bin}"
export PATH="$BIN:/usr/bin:$PATH"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/check_nc_tracers.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
rc=0

command -v ncdump >/dev/null || { echo "FAIL: ncdump not found"; exit 1; }
[ -f "$HERE/GRID/MM_coarse.bas" ] || { echo "FAIL: GRID/MM_coarse.bas missing (make init)"; exit 1; }

mkdir "$TMP/run" && cd "$TMP/run" || exit 1
cp -r "$HERE/GRID" "$HERE/INPUT" . && cp "$HERE/mm_hyd_conz.str" .
sed -i -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
       -e "s/iconz = 2/iconz = 2\n\t idtcon = 3600\n\t itmcon = 0/" mm_hyd_conz.str
grep -q "iconz = 2" mm_hyd_conz.str || { echo "FAIL: mm_hyd_conz.str has no iconz = 2"; exit 1; }
timeout 900 shyfem mm_hyd_conz.str > run.log 2>&1 || { echo "FAIL: shyfem did not complete"; tail -5 run.log; exit 1; }
[ -f mm_hyd_conz.conz.shy ] || { echo "FAIL: no mm_hyd_conz.conz.shy"; exit 1; }

shy_minmax(){ shyelab -write "$1" 2>/dev/null | grep "l,ivar,min,aver,max" \
    | awk -v v="$2" '$3==1 && $4==v {m=$5; x=$7; f=1} END{if(f) print m, x}'; }
nc_minmax(){ ncdump -v "$2" "$1" | awk -v nkn="$3" -v nm="$2" '
    /^data:/{d=1; next}
    d && $1==nm {next}
    d {gsub(/[;,}]/," "); for(i=1;i<=NF;i++) a[n++]=$i}
    END{ if(n<nkn){print "nan nan"; exit}
         for(i=n-nkn;i<n;i++){
           if(a[i] !~ /^[-+]?[0-9]*[.]?[0-9]+([eE][-+]?[0-9]+)?$/){print "nan nan"; exit}
           v=a[i]+0; if(i==n-nkn||v<m)m=v; if(i==n-nkn||v>x)x=v }
         printf "%.8g %.8g\n",m,x }'; }

echo "=== two tracers: mm_hyd_conz.conz.shy (ids 301 302)"
rm -f out.nc
shyelab -outformat nc mm_hyd_conz.conz.shy > nc.log 2>&1
st=$?
if [ $st -ne 0 ]; then
  echo "FAIL: shyelab -outformat nc exit status $st"; tail -4 nc.log; rc=1
elif ! ncdump -h out.nc > hdr.txt 2> hdr.err; then
  echo "FAIL: out.nc is not a valid netcdf file"; cat hdr.err; rc=1
else
  nkn=$(awk '/nMesh2_node =/{print $3; exit}' hdr.txt)
  vars=$(grep -E '^\s+(float|double) [^ ]+\(time,' hdr.txt | sed -E 's/^\s+(float|double) ([^(]+)\(.*/\2/' | sort | tr '\n' ' ')
  if [ "$vars" != "concentration_1 concentration_2 " ]; then
    echo "FAIL: data variables [$vars], expected [concentration_1 concentration_2 ]"; rc=1
  fi
  for pair in "301 concentration_1" "302 concentration_2"; do
    set -- $pair
    mm_shy=$(shy_minmax mm_hyd_conz.conz.shy "$1"); mm_nc=$(nc_minmax out.nc "$2" "$nkn")
    if [ -z "$mm_shy" ]; then echo "FAIL: id $1: no record in shyelab -write"; rc=1; continue; fi
    if awk -v a="$mm_shy" -v b="$mm_nc" 'BEGIN{ split(a,s," "); split(b,c," ");
         for(i=1;i<=2;i++){ d=s[i]-c[i]; if(d<0)d=-d; r=(s[i]<0?-s[i]:s[i]);
           if(r<1e-30) r=1; if(d/r>2e-5 || c[i]=="nan") exit 1 } exit 0 }'; then
      echo "  ok   $1 $2  min/max $mm_nc"
    else
      echo "FAIL: id $1 $2: shyelab -write [$mm_shy] vs nc [$mm_nc]"; rc=1
    fi
  done
fi
rm -f out.nc

echo "=== one tracer: shyelab -split gives one file per tracer"
mkdir split && cp mm_hyd_conz.conz.shy split/ && cd split || exit 1
shyelab -split mm_hyd_conz.conz.shy > /dev/null 2>&1
if [ ! -f conc_001.shy ]; then
  echo "FAIL: shyelab -split made no conc_001.shy"; rc=1
else
  shyelab -outformat nc conc_001.shy > nc1.log 2>&1
  if [ $? -ne 0 ] || ! ncdump -h out.nc > hdr1.txt 2>&1; then
    echo "FAIL: single tracer file did not convert"; tail -3 nc1.log; rc=1
  else
    vars=$(grep -E '^\s+(float|double) [^ ]+\(time,' hdr1.txt | sed -E 's/^\s+(float|double) ([^(]+)\(.*/\2/' | tr '\n' ' ')
    if [ "$vars" = "concentration " ]; then echo "  ok   one tracer keeps the name: $vars"
    else echo "FAIL: one tracer gave [$vars], expected [concentration ]"; rc=1; fi
  fi
fi

echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "NC TRACER GATE: PASS"; else echo "NC TRACER GATE: FAIL"; fi
exit $rc
