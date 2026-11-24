#!/bin/bash
#------------------------------------------------------------------------
# `make init` keeps the tracked basin GRID/MM_coarse.bas (#251).
#
# Usage:  ./check_make_init.sh
#
# GRID/MM_coarse.bas is a tracked file: the Mar Menor cases read it, and the
# particle floors are measured on it.  A `make init` that ran shypre on
# MM_coarse.grd rewrote it whenever shypre wrote other bytes: after 9abe01a4
# (exact decimal parsing in istod) 46 element depths came out one unit in
# the last place lower, so every tree was left with a modified tracked file
# and its results depended on whether it had run `make init`.  The tracked
# file has since been rebuilt with that shypre (2026-11-24), so check 5
# below (the real shypre) passes today even for a `make init` that rebuilds
# the file; checks 1 and 4 (the stand-in shypre) still catch that.
#
# Checked in scratch copies of this folder's Makefile and GRID/ (and of
# ../mar_menor_lagrange, whose GRID is a link to this folder's), with a
# stand-in shypre first on PATH that logs its arguments and writes a dummy
# basin:
#   1. make init with the tracked basin present: shypre is not run on
#      MM_coarse.grd, GRID/MM_coarse.bas is byte for byte the tracked one,
#      and GRID/MM_coarse_smooth.bas is built;
#   2. make init with GRID/MM_coarse.bas missing: it is built;
#   3. make cleanbas: GRID/MM_coarse_smooth.bas is removed and the tracked
#      basin is kept;
#   4. make init and make cleanbas in ../mar_menor_lagrange: the tracked
#      basin (reached through its GRID link) is kept;
# and with the real shypre (the first shypre on PATH; SKIPPED when there is
# none):
#   5. make init in a scratch copy leaves GRID/MM_coarse.bas byte for byte
#      the tracked one and builds GRID/MM_coarse_smooth.bas.
# "The tracked one" is the blob of HEAD when this folder is in a git work
# tree, else the file in GRID/.  In a git work tree it also checks
#   0. GRID/MM_coarse.bas of this folder is the blob of HEAD (it is not in
#      a tree where an older `make init` rewrote it; restore it with
#      git show HEAD:./GRID/MM_coarse.bas > GRID/MM_coarse.bas).
# Nothing in this folder is written; the scratch folder is made with mktemp
# under ${TMPDIR:-/tmp} and removed at the end.  Needs make.
# Exit code 0 (MAKE INIT CHECK: PASS) or 1 (MAKE INIT CHECK: FAIL).
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
PARENT="$(dirname "$HERE")"
LGRDIR="mar_menor_lagrange"
BAS="GRID/MM_coarse.bas"
rc=0
nskip=0
fail() { echo "  FAIL: $*"; rc=1; }
ok() { echo "  ok: $*"; }

command -v make > /dev/null 2>&1 || { echo "MAKE INIT CHECK: FAIL (make is not on PATH)"; exit 1; }
for f in Makefile GRID/MM_coarse.grd GRID/MM_coarse_smooth.grd "$BAS"; do
  [ -f "$HERE/$f" ] || { echo "MAKE INIT CHECK: FAIL ($f is missing in $HERE)"; exit 1; }
done
REALSHYPRE="$(command -v shypre 2> /dev/null || true)"

SCR=""
cleanup() {
  if [ -n "$SCR" ] && [ -d "$SCR" ]; then rm -rf "$SCR"; fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM
SCR="$(mktemp -d "${TMPDIR:-/tmp}/make_init.XXXXXX")" || { echo "MAKE INIT CHECK: FAIL (mktemp failed)"; exit 1; }

#--- the tracked basin -----------------------------------------------------
TRACKED="$SCR/tracked.bas"
if git -C "$HERE" rev-parse --is-inside-work-tree > /dev/null 2>&1 \
   && git -C "$HERE" cat-file -e "HEAD:./$BAS" 2> /dev/null; then
  git -C "$HERE" show "HEAD:./$BAS" > "$TRACKED" || { echo "MAKE INIT CHECK: FAIL (git show HEAD:./$BAS failed)"; exit 1; }
  echo "=== 0. $BAS of this folder is the blob of HEAD"
  if cmp -s "$TRACKED" "$HERE/$BAS"; then
    ok "identical"
  else
    fail "$BAS differs from HEAD (rewritten by an older 'make init'?): restore it with: git show HEAD:./$BAS > $BAS"
  fi
else
  echo "=== 0. not a git work tree: the tracked basin is $BAS as it is"
  cp "$HERE/$BAS" "$TRACKED" || { echo "MAKE INIT CHECK: FAIL (cannot copy $BAS)"; exit 1; }
fi

# mkcopy DIR: DIR/mar_menor with this folder's Makefile, the two grids and
# the tracked basin (the folder name is the BASE_DIR of ../mar_menor_lagrange)
mkcopy() {
  mkdir -p "$1/mar_menor/GRID" || return 1
  cp "$HERE/Makefile" "$1/mar_menor/" || return 1
  cp "$HERE/GRID/MM_coarse.grd" "$HERE/GRID/MM_coarse_smooth.grd" "$1/mar_menor/GRID/" || return 1
  cp "$TRACKED" "$1/mar_menor/$BAS"
}

# the stand-in shypre: logs its arguments, writes a dummy basin per grid
FAKE="$SCR/fakebin"
mkdir "$FAKE" || exit 1
cat > "$FAKE/shypre" <<'EOF'
#!/bin/bash
echo "shypre $*" >> "$SHYPRE_LOG"
for a in "$@"; do
  case "$a" in
    -*) ;;
    *.grd) printf 'stand-in basin of %s\n' "$a" > "${a%.grd}.bas" ;;
  esac
done
EOF
chmod +x "$FAKE/shypre" || exit 1
export SHYPRE_LOG

# fakemake LOG DIR TARGET: make TARGET in DIR with the stand-in shypre
fakemake() {
  SHYPRE_LOG="$1"; : > "$SHYPRE_LOG"
  ( cd "$2" && PATH="$FAKE:$PATH" make "$3" ) > "$1.make" 2>&1
}

#--- 1. tracked basin present ----------------------------------------------
echo "=== 1. make init with the tracked basin present (stand-in shypre)"
D="$SCR/t1"
if ! mkcopy "$D"; then
  fail "cannot make the scratch copy"
elif ! fakemake "$SCR/t1.log" "$D/mar_menor" init; then
  tail -5 "$SCR/t1.log.make"; fail "make init failed"
else
  if grep -q "MM_coarse\.grd" "$SCR/t1.log"; then fail "shypre was run on MM_coarse.grd ($(grep "MM_coarse\.grd" "$SCR/t1.log"))"
  else ok "shypre not run on MM_coarse.grd"; fi
  if cmp -s "$TRACKED" "$D/mar_menor/$BAS"; then ok "$BAS is the tracked one"
  else fail "$BAS is not the tracked one after make init"; fi
  if grep -q "MM_coarse_smooth\.grd" "$SCR/t1.log" && [ -f "$D/mar_menor/GRID/MM_coarse_smooth.bas" ]; then
    ok "GRID/MM_coarse_smooth.bas built"
  else fail "GRID/MM_coarse_smooth.bas not built"; fi
fi

#--- 2. basin missing ------------------------------------------------------
echo "=== 2. make init with $BAS missing (stand-in shypre)"
D="$SCR/t2"
if ! mkcopy "$D"; then
  fail "cannot make the scratch copy"
else
  rm -f "$D/mar_menor/$BAS"
  if ! fakemake "$SCR/t2.log" "$D/mar_menor" init; then
    tail -5 "$SCR/t2.log.make"; fail "make init failed"
  elif grep -q "MM_coarse\.grd" "$SCR/t2.log" && [ -f "$D/mar_menor/$BAS" ]; then
    ok "$BAS built"
  else
    fail "$BAS not built when it is missing"
  fi
fi

#--- 3. make cleanbas ------------------------------------------------------
echo "=== 3. make cleanbas"
D="$SCR/t3"
if ! mkcopy "$D"; then
  fail "cannot make the scratch copy"
else
  printf 'generated\n' > "$D/mar_menor/GRID/MM_coarse_smooth.bas"
  if ! fakemake "$SCR/t3.log" "$D/mar_menor" cleanbas; then
    tail -5 "$SCR/t3.log.make"; fail "make cleanbas failed"
  else
    if [ -f "$D/mar_menor/GRID/MM_coarse_smooth.bas" ]; then fail "GRID/MM_coarse_smooth.bas not removed"
    else ok "GRID/MM_coarse_smooth.bas removed"; fi
    if cmp -s "$TRACKED" "$D/mar_menor/$BAS"; then ok "$BAS kept"
    else fail "$BAS removed or changed by make cleanbas"; fi
  fi
fi

#--- 4. ../mar_menor_lagrange ----------------------------------------------
echo "=== 4. make init and make cleanbas in ../$LGRDIR (GRID links to this folder's)"
D="$SCR/t4"
if [ ! -f "$PARENT/$LGRDIR/Makefile" ]; then
  echo "  SKIPPED: $PARENT/$LGRDIR/Makefile does not exist"; nskip=$((nskip + 1))
elif ! mkcopy "$D" || ! mkdir "$D/$LGRDIR" || ! cp "$PARENT/$LGRDIR/Makefile" "$D/$LGRDIR/"; then
  fail "cannot make the scratch copies"
elif ! fakemake "$SCR/t4.log" "$D/$LGRDIR" init; then
  tail -5 "$SCR/t4.log.make"; fail "make init failed in $LGRDIR"
else
  if grep -q "MM_coarse\.grd" "$SCR/t4.log"; then fail "shypre was run on MM_coarse.grd ($(grep "MM_coarse\.grd" "$SCR/t4.log"))"
  else ok "shypre not run on MM_coarse.grd"; fi
  if cmp -s "$TRACKED" "$D/mar_menor/$BAS"; then ok "$BAS is the tracked one after make init"
  else fail "$BAS is not the tracked one after make init in $LGRDIR"; fi
  if ! fakemake "$SCR/t4c.log" "$D/$LGRDIR" cleanbas; then
    tail -5 "$SCR/t4c.log.make"; fail "make cleanbas failed in $LGRDIR"
  elif cmp -s "$TRACKED" "$D/mar_menor/$BAS"; then ok "$BAS kept by make cleanbas"
  else fail "$BAS removed or changed by make cleanbas in $LGRDIR"; fi
fi

#--- 5. real shypre --------------------------------------------------------
echo "=== 5. make init with the real shypre"
D="$SCR/t5"
if [ -z "$REALSHYPRE" ]; then
  echo "  SKIPPED: no shypre on PATH"; nskip=$((nskip + 1))
elif ! mkcopy "$D"; then
  fail "cannot make the scratch copy"
elif ! ( cd "$D/mar_menor" && make init ) > "$SCR/t5.make" 2>&1; then
  tail -5 "$SCR/t5.make"; fail "make init failed ($REALSHYPRE)"
else
  if cmp "$TRACKED" "$D/mar_menor/$BAS" > "$SCR/t5.cmp" 2>&1; then ok "$BAS is the tracked one ($REALSHYPRE)"
  else fail "$BAS rewritten by make init: $(cat "$SCR/t5.cmp")"; fi
  if [ -f "$D/mar_menor/GRID/MM_coarse_smooth.bas" ]; then ok "GRID/MM_coarse_smooth.bas built"
  else fail "GRID/MM_coarse_smooth.bas not built"; fi
fi

if [ "$rc" != 0 ]; then
  echo "MAKE INIT CHECK: FAIL"
elif [ "$nskip" -gt 0 ]; then
  echo "MAKE INIT CHECK: PASS ($nskip check(s) skipped)"
else
  echo "MAKE INIT CHECK: PASS"
fi
exit "$rc"
