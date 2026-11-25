#!/bin/bash
#------------------------------------------------------------------------
# NetCDF conversion gate (#222): `shyelab -outformat nc` must turn the EUTRO
# and the mercury output into a valid NetCDF file.
#
# Before the fix the ids 741/742 (ulva) and 251..299 (mercury) had no name,
# NetCDF refused the empty name and shyelab left a 32 byte zero out.nc
# behind (and exited 0).
#
# For eco_2d.eutro.shy and merc_2d.merc.shy it asserts:
#   1. shyelab -outformat nc exits 0 and out.nc passes `ncdump -h`
#   2. every variable of the .shy file is in out.nc under its expected,
#      non-empty name, and out.nc has no other data variable
#   3. at the last time record min and max of every variable equal what
#      `shyelab -write` prints (relative 2e-5: -write prints 6 digits)
#
# Requires an ECOLOGICAL=EUTRO MERCURY=true NETCDF=true build and `make init`.
# Usage:  ./check_nc.sh        (SHYFEM_BIN=<bin dir> to use another build)
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
BIN="${SHYFEM_BIN:-$HERE/../../../bin}"
export PATH="$BIN:/usr/bin:$PATH"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/check_nc.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
rc=0

command -v ncdump >/dev/null || { echo "FAIL: ncdump not found"; exit 1; }

run(){ timeout 600 shyfem "$1" > "$TMP/${1%.str}.run.log" 2>&1 \
        || { echo "FAIL: $1 did not complete"; exit 1; }; }

# ivar -> expected nc name, per file
declare -A EUTRO=( [701]=weutro_pelagic_1 [702]=weutro_pelagic_2
  [703]=weutro_pelagic_3 [704]=weutro_pelagic_4 [705]=weutro_pelagic_5
  [706]=weutro_pelagic_6 [707]=weutro_pelagic_7 [708]=weutro_pelagic_8
  [709]=weutro_pelagic_9 [741]=ulva_biomass [742]=ulva_nitrogen_quota )
declare -A MERC=( [251]=hg0_water [252]=hg2_water [253]=mehg_water
  [271]=hg2_sediment [272]=mehg_sediment [281]=silt_water [282]=pom_water
  [291]=silt_sediment [292]=pom_sediment [297]=sea_bed_depth_change
  [298]=active_layer_thickness [299]=mercury_bottom_stress )

# last-time "min max" of ivar at level 1, from shyelab -write; empty if none
shy_minmax(){ shyelab -write "$1" 2>/dev/null | grep "l,ivar,min,aver,max" \
    | awk -v v="$2" '$3==1 && $4==v {m=$5; x=$7; f=1} END{if(f) print m, x}'; }

# last-time "min max" of the nc variable, from ncdump. Every token keeps its
# position (ncdump prints a fill value as _); the last nkn tokens must all be
# numbers, otherwise "nan nan".
nc_minmax(){ ncdump -v "$2" "$1" | awk -v nkn="$3" -v nm="$2" '
    /^data:/{d=1; next}
    d && $1==nm {next}
    d {gsub(/[;,}]/," "); for(i=1;i<=NF;i++) a[n++]=$i}
    END{ if(n<nkn){print "nan nan"; exit}
         for(i=n-nkn;i<n;i++){
           if(a[i] !~ /^[-+]?[0-9]*[.]?[0-9]+([eE][-+]?[0-9]+)?$/){print "nan nan"; exit}
           v=a[i]+0; if(i==n-nkn||v<m)m=v; if(i==n-nkn||v>x)x=v }
         printf "%.8g %.8g\n",m,x }'; }

check_file(){
  local shyf="$1" arrname="$2"
  local -n map="$arrname"
  echo "=================================================================="
  echo "FILE: $shyf"
  echo "=================================================================="
  rm -f out.nc
  shyelab -outformat nc "$shyf" > "$TMP/nc.log" 2>&1
  local st=$?
  if [ $st -ne 0 ]; then
    echo "FAIL: shyelab -outformat nc exit status $st"; tail -5 "$TMP/nc.log"
    rc=1; ls -l out.nc 2>/dev/null; rm -f out.nc; return
  fi
  if ! ncdump -h out.nc > "$TMP/hdr.txt" 2> "$TMP/hdr.err"; then
    echo "FAIL: out.nc is not a valid netcdf file ($(stat -c %s out.nc 2>/dev/null) bytes)"
    cat "$TMP/hdr.err"; tail -4 "$TMP/nc.log"; rc=1; rm -f out.nc; return
  fi
  echo "  out.nc is valid ($(stat -c %s out.nc) bytes)"
  local nkn
  nkn=$(awk '/nMesh2_node =/{print $3; exit}' "$TMP/hdr.txt")
  # data variables: those with a time dimension
  local nvarnc nvarmap=${#map[@]}
  nvarnc=$(grep -cE '^\s+(float|double) [^ ]+\(time,' "$TMP/hdr.txt")
  if [ "$nvarnc" -ne "$nvarmap" ]; then
    echo "FAIL: $nvarnc data variables in out.nc, expected $nvarmap"; rc=1
  fi
  local ids
  if ! shyelab -write "$shyf" > "$TMP/write.txt" 2>/dev/null; then
    echo "FAIL: shyelab -write $shyf failed"; rc=1; rm -f out.nc; return
  fi
  ids=$(grep "l,ivar,min,aver,max" "$TMP/write.txt" \
        | awk '{print $4}' | sort -un | tr '\n' ' ')
  if [ -z "$ids" ]; then
    echo "FAIL: shyelab -write $shyf lists no variable"; rc=1; rm -f out.nc; return
  fi
  local want
  want=$(printf '%s\n' "${!map[@]}" | sort -n | tr '\n' ' ')
  if [ "$ids" != "$want" ]; then
    echo "FAIL: ids in $shyf are [$ids], expected [$want]"; rc=1
  fi
  local id name mm_shy mm_nc
  for id in $ids; do
    name="${map[$id]:-}"
    if [ -z "$name" ]; then echo "FAIL: id $id has no expected name"; rc=1; continue; fi
    if ! grep -qE "^\s+(float|double) $name\(time," "$TMP/hdr.txt"; then
      echo "FAIL: id $id: variable $name missing in out.nc"; rc=1; continue
    fi
    mm_shy=$(shy_minmax "$shyf" "$id"); mm_nc=$(nc_minmax out.nc "$name" "$nkn")
    if [ -z "$mm_shy" ]; then
      echo "FAIL: id $id: no record in shyelab -write"; rc=1; continue
    fi
    if awk -v a="$mm_shy" -v b="$mm_nc" 'BEGIN{
         split(a,s," "); split(b,c," ");
         for(i=1;i<=2;i++){ d=s[i]-c[i]; if(d<0)d=-d; r=(s[i]<0?-s[i]:s[i]);
           if(r<1e-30) r=1; if(d/r>2e-5 || c[i]=="nan") exit 1 }
         exit 0 }'; then
      echo "  ok   $id $name  min/max $mm_nc"
    else
      echo "FAIL: id $id $name: shyelab -write [$mm_shy] vs nc [$mm_nc]"; rc=1
    fi
  done
  rm -f out.nc
}

run eco_2d.str
run merc_2d.str
check_file eco_2d.eutro.shy EUTRO
check_file merc_2d.merc.shy MERC

echo "=================================================================="
if [ "$rc" -eq 0 ]; then echo "NC GATE: PASS"; else echo "NC GATE: FAIL"; fi
exit $rc
