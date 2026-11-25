#!/bin/bash
#------------------------------------------------------------------------
# Test of check_geo_bas.sh (issue #280): a GRID/MM_geo.bas that is not what
# today's shypre writes is found, and the gates that read it call the check.
#
# Usage:  ./test_geo_bas.sh
#
# Needs shypre on PATH (a build of this tree) and python3.  Works in a
# folder made with mktemp under ${TMPDIR:-/tmp}, removed at the end, and
# touches nothing in this folder (the basin is built from a copy of
# GRID/MM_geo.grd).
#
#   1. every gate that reads GRID/MM_geo.bas of this folder calls
#      check_geo_bas.sh (check_mpi.sh, check_lgr_serial.sh,
#      check_lgr_mpi.sh, check_lgr_fixes.sh, check_itlin.sh).
#   2. a fresh basin: the check prints nothing, exit 0, the file is the
#      same bytes.
#   3. a stale basin made from the fresh one by moving one element depth
#      by one unit in the last place (the kind of difference the parser of
#      before 9abe01a4 made, in 112 elements): with --check-only exit 1,
#      the line with "stale" and the advice "rebuild GRID/MM_geo.bas (cd
#      GRID && shypre -noopti MM_geo.grd)", the file untouched; without it
#      exactly one line with "stale", exit 0, the file now the fresh bytes,
#      and a second run prints nothing.
#   4. if the file of the live tree (the one built on 2026-06-12, which the
#      shypre before 9abe01a4 wrote) is found, row 3 again with it; set
#      MM_GEO_STALE_FILE to name another file, or to "none" to skip.
#   5. a missing basin: exit 1 and the advice; with --build-missing one line
#      with "missing", exit 0, the fresh bytes.
#   6. no shypre on PATH: exit 1 and "shypre is not on PATH".
#
# Exit code 0 (GEO BAS TEST: PASS) or 1 (GEO BAS TEST: FAIL).
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
rc=0
fail() { echo "  FAIL: $*"; rc=1; }
ADVICE="rebuild GRID/MM_geo.bas (cd GRID && shypre -noopti MM_geo.grd)"

command -v shypre  > /dev/null 2>&1 || { echo "GEO BAS TEST: FAIL (shypre is not on PATH)"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "GEO BAS TEST: FAIL (python3 is not on PATH)"; exit 1; }
[ -x "$HERE/check_geo_bas.sh" ] || { echo "GEO BAS TEST: FAIL (no executable check_geo_bas.sh in $HERE)"; exit 1; }
[ -f "$HERE/GRID/MM_geo.grd" ] || { echo "GEO BAS TEST: FAIL (no GRID/MM_geo.grd in $HERE)"; exit 1; }

T="$(mktemp -d "${TMPDIR:-/tmp}/test_geo_bas.XXXXXX")" || { echo "GEO BAS TEST: FAIL (mktemp)"; exit 1; }
trap 'rm -rf "$T"' EXIT
trap 'rm -rf "$T"; exit 130' INT TERM

echo "=== 1. the gates call check_geo_bas.sh"
for f in check_mpi.sh check_lgr_serial.sh check_lgr_mpi.sh check_lgr_fixes.sh check_itlin.sh; do
  if grep -v '^[[:space:]]*#' "$HERE/$f" | grep -q 'check_geo_bas\.sh'; then
    echo "  $f: calls it"
  else
    fail "$f does not call check_geo_bas.sh (a stale GRID/MM_geo.bas would be used without a word)"
  fi
done

# a work folder with the basin made by shypre
mkdir "$T/fresh" "$T/fresh/GRID" || exit 1
cp "$HERE/GRID/MM_geo.grd" "$T/fresh/GRID/" || exit 1
( cd "$T/fresh/GRID" && shypre -noopti MM_geo.grd > shypre.log 2>&1 ) && [ -s "$T/fresh/GRID/MM_geo.bas" ] \
  || { tail -3 "$T/fresh/GRID/shypre.log"; echo "GEO BAS TEST: FAIL (shypre failed)"; exit 1; }
cp "$T/fresh/GRID/MM_geo.bas" "$T/fresh.bas"

# a folder with the grid and the given basin (or none)
mkwork() {  # NAME [BASIN]
  mkdir "$T/$1" "$T/$1/GRID" || return 1
  cp "$HERE/GRID/MM_geo.grd" "$T/$1/GRID/" || return 1
  if [ $# -ge 2 ]; then cp "$2" "$T/$1/GRID/MM_geo.bas" || return 1; fi
}

# the stale file: one element depth (record 11) one ulp away
python3 -I - "$T/fresh.bas" "$T/stale_synth.bas" <<'EOF' || { echo "GEO BAS TEST: FAIL (cannot make the stale file)"; exit 1; }
import struct, sys
d = bytearray(open(sys.argv[1], 'rb').read())
i = 0; k = 0
while i < len(d):
    n = struct.unpack_from('<i', d, i)[0]
    if k == 11:
        off = i + 4 + 4 * 100
        v = struct.unpack_from('<i', d, off)[0]
        struct.pack_into('<i', d, off, v + 1)
        break
    i += 8 + n; k += 1
else:
    sys.exit('no record 11')
open(sys.argv[2], 'wb').write(d)
EOF
cmp -s "$T/fresh.bas" "$T/stale_synth.bas" && { echo "GEO BAS TEST: FAIL (the stale file equals the fresh one)"; exit 1; }

echo "=== 2. fresh basin: silent"
r0=$rc
mkwork w2 "$T/fresh.bas" || exit 1
out="$("$HERE/check_geo_bas.sh" "$T/w2" "T" 2>&1)"; r=$?
[ "$r" = 0 ] || fail "fresh: exit $r: $out"
[ -z "$out" ] || fail "fresh: printed: $out"
cmp -s "$T/w2/GRID/MM_geo.bas" "$T/fresh.bas" || fail "fresh: the file changed"
[ "$rc" = "$r0" ] && echo "  silent, exit 0, file untouched"

# row 3 / 4: a stale basin
stale_rows() {  # TAG STALEFILE
  local tag="$1" st="$2" out r n
  mkwork "s_$tag" "$st" || exit 1
  out="$("$HERE/check_geo_bas.sh" --check-only "$T/s_$tag" "T" 2>&1)"; r=$?
  [ "$r" = 1 ] || fail "$tag: --check-only: exit $r, not 1: $out"
  case "$out" in *stale*) ;; *) fail "$tag: --check-only: no 'stale' in: $out" ;; esac
  case "$out" in *"$ADVICE"*) ;; *) fail "$tag: --check-only: no advice in: $out" ;; esac
  cmp -s "$T/s_$tag/GRID/MM_geo.bas" "$st" || fail "$tag: --check-only changed the file"
  out="$("$HERE/check_geo_bas.sh" "$T/s_$tag" "T" 2>&1)"; r=$?
  n="$(printf '%s\n' "$out" | wc -l)"
  [ "$r" = 0 ] || fail "$tag: replace: exit $r: $out"
  [ -n "$out" ] && [ "$n" = 1 ] || fail "$tag: replace: $n lines, not 1: $out"
  case "$out" in *stale*replaced*) ;; *) fail "$tag: replace: no 'stale ... replaced' in: $out" ;; esac
  cmp -s "$T/s_$tag/GRID/MM_geo.bas" "$T/fresh.bas" || fail "$tag: replace: the file is not the fresh one"
  out="$("$HERE/check_geo_bas.sh" "$T/s_$tag" "T" 2>&1)"; r=$?
  { [ "$r" = 0 ] && [ -z "$out" ]; } || fail "$tag: second run: exit $r, printed: $out"
}
echo "=== 3. stale basin (one depth one ulp off)"
r0=$rc
stale_rows synth "$T/stale_synth.bas"
[ "$rc" = "$r0" ] && echo "  found, advice given, replaced with one line, then silent"

echo "=== 4. the file of the live tree, if there"
r0=$rc
LIVE="${MM_GEO_STALE_FILE-/home/razinka/shyfem/testcases/examples/mar_menor/GRID/MM_geo.bas}"
if [ "$LIVE" = none ] || [ ! -f "$LIVE" ]; then
  echo "  none (MM_GEO_STALE_FILE='$LIVE'): skipped"
elif cmp -s "$LIVE" "$T/fresh.bas"; then
  echo "  $LIVE is fresh: nothing to test"
else
  stale_rows live "$LIVE"
  [ "$rc" = "$r0" ] && echo "  $LIVE: found, advice given, replaced (in a copy), then silent"
fi

echo "=== 5. missing basin"
r0=$rc
mkwork w5 || exit 1
out="$("$HERE/check_geo_bas.sh" "$T/w5" "T" 2>&1)"; r=$?
[ "$r" = 1 ] || fail "missing: exit $r, not 1: $out"
case "$out" in *"$ADVICE"*) ;; *) fail "missing: no advice in: $out" ;; esac
[ ! -e "$T/w5/GRID/MM_geo.bas" ] || fail "missing: the file was made without --build-missing"
out="$("$HERE/check_geo_bas.sh" --build-missing "$T/w5" "T" 2>&1)"; r=$?
[ "$r" = 0 ] || fail "missing, --build-missing: exit $r: $out"
case "$out" in *missing*) ;; *) fail "missing, --build-missing: no 'missing' in: $out" ;; esac
[ "$(printf '%s\n' "$out" | wc -l)" = 1 ] || fail "missing, --build-missing: not one line: $out"
cmp -s "$T/w5/GRID/MM_geo.bas" "$T/fresh.bas" || fail "missing, --build-missing: not the fresh file"
[ "$rc" = "$r0" ] && echo "  exit 1 with the advice; --build-missing builds it with one line"

echo "=== 6. no shypre on PATH"
r0=$rc
mkwork w6 "$T/fresh.bas" || exit 1
out="$(PATH=/usr/bin:/bin "$HERE/check_geo_bas.sh" "$T/w6" "T" 2>&1)"; r=$?
if [ "$(PATH=/usr/bin:/bin command -v shypre)" ]; then
  echo "  shypre is in /usr/bin or /bin: skipped"
else
  [ "$r" = 1 ] || fail "no shypre: exit $r, not 1: $out"
  case "$out" in *"shypre is not on PATH"*) ;; *) fail "no shypre: message: $out" ;; esac
  [ "$rc" = "$r0" ] && echo "  exit 1, 'shypre is not on PATH'"
fi

if [ "$rc" = 0 ]; then echo "GEO BAS TEST: PASS"; else echo "GEO BAS TEST: FAIL"; fi
exit "$rc"
