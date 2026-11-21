#!/bin/bash
#------------------------------------------------------------------------
# Serial guard and reproducibility check of the Lagrangian test cases.
#
# Usage:  ./check_lgr_serial.sh REF_BIN_DIR    guard against a reference build
#         ./check_lgr_serial.sh repro          the current binary against itself
#
# Guard (SERIAL GUARD: PASS|FAIL): for the cases mm_lgr_a, _b, _c, _e the
# files CASE.lgr.shy, CASE.hydro.shy and CASE.inf of
#   - the current binary (shyfem first on PATH, run in this folder),
#   - the current binary under "mpirun -np 1" (scratch copy), and
#   - the reference binary REF_BIN_DIR/shyfem (scratch copy)
# are compared byte by byte with cmp.  For mm_lgr (random walk on) and
# ../mar_menor_lagrange/mm_lgr_01 only CASE.hydro.shy and CASE.inf are
# compared.  mm_lgr_01 needs its own setup (make links, run in the scratch
# copy); if it cannot be set up or run the check is reported as SKIPPED and
# the final line reads "SERIAL GUARD: PASS (1 check skipped)".
#
# repro (REPRO: PASS|FAIL): the cases a, b, c, e are run twice with the
# current binary and the two CASE.lgr.shy files are compared with cmp.
#
# The scratch copies are made with mktemp under ${TMPDIR:-/tmp} and removed
# at the end.  Needs shyfem, mpirun (OpenMPI) and python3 on PATH, and
# `make init` plus (cd GRID && shypre -noopti MM_geo.grd) done.
# Exit code 0 on PASS, 1 on FAIL.
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
PARENT="$(dirname "$HERE")"
FOLDER="$(basename "$HERE")"
LGRDIR="mar_menor_lagrange"
rc=0
nskip=0
LABEL="SERIAL GUARD"

if [ $# -ne 1 ]; then
  echo "usage: $0 REF_BIN_DIR | repro"
  exit 2
fi
ARG="$1"
[ "$ARG" = repro ] && LABEL="REPRO"
fail() { echo "$LABEL FAIL: $*"; rc=1; }

#--- preconditions -------------------------------------------------------
command -v shyfem  > /dev/null 2>&1 || { echo "$LABEL FAIL: shyfem is not on PATH"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "$LABEL FAIL: python3 is not on PATH"; exit 1; }
for b in GRID/MM_geo.bas GRID/MM_coarse.bas; do
  if [ ! -f "$HERE/$b" ]; then
    echo "$LABEL FAIL: $b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE"
    exit 1
  fi
done
if [ "$ARG" != repro ]; then
  command -v mpirun > /dev/null 2>&1 || { echo "$LABEL FAIL: mpirun is not on PATH"; exit 1; }
  REF="$ARG"
  if [ ! -d "$REF" ] || [ ! -x "$REF/shyfem" ]; then
    echo "$LABEL FAIL: no executable shyfem in reference directory '$REF'"
    exit 1
  fi
  REF="$(cd "$REF" && pwd)"
  if [ "$REF/shyfem" -ef "$(command -v shyfem)" ]; then
    echo "note: the reference binary is the same file as the current one"
  fi
fi

SCR=""
cleanup() {
  if [ -n "$SCR" ] && [ -d "$SCR" ]; then rm -rf "$SCR"; fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# run_in DIR CASE LOG LAUNCHER...   run CASE.str in DIR, true if it ended
run_in() {
  local dir="$1" case="$2" log="$3"; shift 3
  ( cd "$dir" && nice -n 19 "$@" "$case.str" > "$log" 2>&1 )
  grep -q "simulation end" "$dir/$log"
}

ALLCASES="mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e"

#=============================== repro =====================================
if [ "$ARG" = repro ]; then
  SCR="$(mktemp -d "${TMPDIR:-/tmp}/lgr_repro.XXXXXX")" || { echo "REPRO FAIL: mktemp failed"; exit 1; }
  for c in $ALLCASES; do
    echo "=== $c: two runs with the current binary"
    rm -f "$HERE/$c.lgr.shy"
    if ! run_in "$HERE" "$c" "$c.log" shyfem; then
      tail -5 "$HERE/$c.log"; fail "$c: first run did not end"; continue
    fi
    cp "$HERE/$c.lgr.shy" "$SCR/$c.run1.lgr.shy" || { fail "$c: no particle file"; continue; }
    rm -f "$HERE/$c.lgr.shy"
    if ! run_in "$HERE" "$c" "$c.log" shyfem; then
      tail -5 "$HERE/$c.log"; fail "$c: second run did not end"; continue
    fi
    if cmp -s "$SCR/$c.run1.lgr.shy" "$HERE/$c.lgr.shy"; then
      echo "  $c.lgr.shy: identical"
    else
      echo "  $c.lgr.shy: DIFFERS between two runs of one binary"
      fail "$c: not reproducible"
    fi
  done
  if [ "$rc" = 0 ]; then echo "REPRO: PASS"; else echo "REPRO: FAIL"; fi
  exit "$rc"
fi

#=============================== guard =====================================
SCR="$(mktemp -d "${TMPDIR:-/tmp}/lgr_guard.XXXXXX")" || { echo "SERIAL GUARD FAIL: mktemp failed"; exit 1; }
# one copy of this folder (and of the Lagrangian example) per run variant
for v in np1 ref cur; do
  mkdir "$SCR/$v" || { echo "SERIAL GUARD FAIL: cannot make $SCR/$v"; exit 1; }
  cp -r "$HERE" "$SCR/$v/$FOLDER" || { echo "SERIAL GUARD FAIL: cannot copy the test folder"; exit 1; }
  # outputs of earlier runs in the copy are removed (the basins are in GRID/)
  rm -f "$SCR/$v/$FOLDER"/*.shy "$SCR/$v/$FOLDER"/*.inf "$SCR/$v/$FOLDER"/*.ext
done

# check_files LABEL FILE... : cmp file of the current run against the two others
check_files() {
  local c="$1" f other name; shift
  for ext in "$@"; do
    f="$HERE/$c.$ext"
    if [ ! -f "$f" ]; then echo "  $c.$ext: MISSING in the current run"; fail "$c.$ext missing"; continue; fi
    for other in np1 ref; do
      name="$SCR/$other/$FOLDER/$c.$ext"
      if [ ! -f "$name" ]; then echo "  $c.$ext vs $other: MISSING"; fail "$c.$ext missing in $other run"
      elif cmp -s "$f" "$name"; then echo "  $c.$ext vs $other: identical"
      else echo "  $c.$ext vs $other: DIFFERS"; fail "$c.$ext differs from the $other run"
      fi
    done
  done
}

# run_three CASE: current binary, mpirun -np 1, reference binary
run_three() {
  local c="$1" ok=1
  rm -f "$HERE/$c.lgr.shy" "$HERE/$c.hydro.shy" "$HERE/$c.inf"
  if ! run_in "$HERE" "$c" "$c.log" shyfem; then
    tail -5 "$HERE/$c.log"; fail "$c: current serial run did not end"; ok=0
  fi
  if ! run_in "$SCR/np1/$FOLDER" "$c" "$c.np1.log" mpirun --oversubscribe -np 1 shyfem; then
    tail -5 "$SCR/np1/$FOLDER/$c.np1.log"; fail "$c: mpirun -np 1 run did not end"; ok=0
  fi
  if ! PATH="$REF:/usr/bin:$PATH" run_in "$SCR/ref/$FOLDER" "$c" "$c.ref.log" shyfem; then
    tail -5 "$SCR/ref/$FOLDER/$c.ref.log"; fail "$c: reference run did not end"; ok=0
  fi
  return $((1 - ok))
}

n=0
for c in $ALLCASES mm_lgr; do
  n=$((n + 1))
  if [ "$c" = mm_lgr ]; then
    echo "=== $n. mm_lgr (random walk on): hydro.shy and inf only"
    exts="hydro.shy inf"
  else
    echo "=== $n. $c: lgr.shy, hydro.shy and inf"
    exts="lgr.shy hydro.shy inf"
  fi
  if run_three "$c"; then check_files "$c" $exts; fi
done

#--- ../mar_menor_lagrange/mm_lgr_01 (own setup, scratch copies only) -----------
n=$((n + 1))
echo "=== $n. $LGRDIR/mm_lgr_01: hydro.shy and inf only"
skip_reason=""
for v in np1 ref cur; do
  [ -z "$skip_reason" ] || break
  if [ ! -d "$PARENT/$LGRDIR" ]; then skip_reason="$PARENT/$LGRDIR does not exist"; break; fi
  cp -r "$PARENT/$LGRDIR" "$SCR/$v/$LGRDIR" || { skip_reason="cannot copy $LGRDIR"; break; }
  if ! ( cd "$SCR/$v/$LGRDIR" && make links > make_links.log 2>&1 ); then
    skip_reason="'make links' failed in $LGRDIR"; break
  fi
  [ -f "$SCR/$v/$LGRDIR/GRID/MM_coarse_smooth.bas" ] || skip_reason="GRID/MM_coarse_smooth.bas missing for $LGRDIR (run 'make init' in $FOLDER, then 'shypre' of MM_coarse_smooth.grd)"
done
if [ -z "$skip_reason" ]; then
  c=mm_lgr_01
  lok=1
  run_in "$SCR/cur/$LGRDIR" "$c" "$c.log" shyfem || { lok=0; skip_reason="current serial run did not end: $(tail -1 "$SCR/cur/$LGRDIR/$c.log")"; }
  if [ "$lok" = 1 ]; then
    run_in "$SCR/np1/$LGRDIR" "$c" "$c.np1.log" mpirun --oversubscribe -np 1 shyfem || { lok=0; skip_reason="mpirun -np 1 run did not end: $(tail -1 "$SCR/np1/$LGRDIR/$c.np1.log")"; }
  fi
  if [ "$lok" = 1 ]; then
    PATH="$REF:/usr/bin:$PATH" run_in "$SCR/ref/$LGRDIR" "$c" "$c.ref.log" shyfem || { lok=0; skip_reason="reference run did not end: $(tail -1 "$SCR/ref/$LGRDIR/$c.ref.log")"; }
  fi
  if [ "$lok" = 1 ]; then
    for ext in hydro.shy inf; do
      for other in np1 ref; do
        a="$SCR/cur/$LGRDIR/$c.$ext"; b="$SCR/$other/$LGRDIR/$c.$ext"
        if [ ! -f "$a" ] || [ ! -f "$b" ]; then echo "  $c.$ext vs $other: MISSING"; fail "$c.$ext missing"
        elif cmp -s "$a" "$b"; then echo "  $c.$ext vs $other: identical"
        else echo "  $c.$ext vs $other: DIFFERS"; fail "$c.$ext differs from the $other run"
        fi
      done
    done
  fi
fi
if [ -n "$skip_reason" ]; then
  echo "  mm_lgr_01: SKIPPED: $skip_reason"
  nskip=$((nskip + 1))
fi

if [ "$rc" != 0 ]; then
  echo "SERIAL GUARD: FAIL"
elif [ "$nskip" -gt 0 ]; then
  echo "SERIAL GUARD: PASS ($nskip check skipped)"
else
  echo "SERIAL GUARD: PASS"
fi
exit "$rc"
