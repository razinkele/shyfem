#!/bin/bash
#------------------------------------------------------------------------
# Semi-Lagrangian advection of momentum (itlin = 1), issue #227.
#
# Usage:  ./check_itlin.sh [NP]     (processes of the MPI rows, default 4)
#
# Every row runs a scratch copy of a shipped STR file with a run name of
# its own (made by sed in this folder, removed with its outputs at the end;
# the logs go to a folder made with mktemp under ${TMPDIR:-/tmp}, removed
# when every row passed, kept and printed when one failed).  A run has
# ended only if its launcher exits with 0 and its log has "simulation end".
#
#   1. serial, mm_hyd_01 with "ilin = 0  itlin = 1" (closed basin at rest):
#      the run ends.  Before #227 it died at its first time step with a
#      segmentation fault in rprs: the side lengths, fluxes and positions
#      the back-tracking uses were allocated only in a particle run.
#   2. serial, mm_hyd_22a (tide at the open boundary, river, wind, Coriolis,
#      variable time step), one day, with "ilin = 0  itlin = 1": the run
#      ends, and the largest |water level| and speed of its hydro file stay
#      below 1 m and 5 m/s.  The values come from shyelab -split and
#      -write; each command must succeed and give at least one record with
#      numeric values, or the row fails (an empty or unreadable hydro file
#      cannot pass as 0).  There is no reference for itlin = 1 results:
#      the bounds only catch a return to garbage (measured: 0.18 m and
#      0.51 m/s; the same case with ilin = 1, without its tilt, 0.16 m and
#      1.0 m/s in 4 days; runs gone wrong reached 1.97 m and 9.9 m/s, the
#      shipped case with itlin = 0, and 18 m and 62 m/s, mm_hyd_02 with
#      itlin = 1 at a fixed 300 s step).  Before #227: the same crash; with
#      the allocation alone it stopped at once in lagr_layer_thickness (the
#      tracker's element number turned negative in the side tests made for
#      the vertical weights).
#   3. NP processes, the run of row 1: stops at start-up with exit code 33
#      (the code shympi_abort_internal passes to MPI_ABORT; the project
#      requires Open MPI, whose mpirun returns it), the line "option
#      itlin = 1 (semi-Lagrangian advection of momentum) is not supported
#      with MPI" and the line "run on one process, or set itlin = 0" once
#      each, no SIGFPE, SIGSEGV or "Fortran runtime" line.  (The
#      back-tracking stops at the edge of a process's domain: measured
#      before the stop was added, on 2 and 4 processes the water level of
#      mm_hyd_22a without its boundary tilt, which stops on several
#      processes, differed from the serial run by 0.05 m with itlin = 1,
#      against 3e-6 m for the same case with ilin = 1.)
#   4. NP processes, mm_hyd_01 as shipped (ilin = 1) with "itlin = 1"
#      added: the run ends and the message of row 3 does not appear
#      (itlin is not used when ilin = 1).  A guard row: it passes before
#      #227 too, and fails if the stop of row 3 catches a run it must not.
#   5. source: src/shyfem/lagrange_track.f90 has no bare stop statement
#      (the eight in the layer change of track_orig and track_line are
#      shympi_abort_internal since #227; the file must define track_orig
#      and track_line once each).  This row reads the text, not a
#      run: no run checked for #227 reaches those lines (no tracer of the
#      2D runs changed layer, and a 3D run stops at start-up, row 8).
#   6. serial, mm_hyd_01 with "ilin = 0  itlin = 2" (no such option):
#      stops with exit code 33 and "error stop set_explicit: no such
#      option".  Before #227 a bare stop ended the run with exit code 0.
#   7. serial, mm_hyd_01 on the geographic basin GRID/MM_geo with
#      "ilin = 0  itlin = 1": stops at start-up with exit code 33, the line
#      "option itlin = 1 (semi-Lagrangian advection of momentum) is not
#      supported on a geographic (lat/lon) grid" and "use a Cartesian grid,
#      or set itlin = 0" once each, no signal line (the back-tracking
#      compares metres with degrees; before, mm_lgr_a, on the same basin,
#      died with SIGFPE in dirz, and with that division avoided it ran to
#      the end with 708,358 loop-limit messages).  The basin is made first
#      when it is missing (shypre -noopti MM_geo.grd, as check_mpi.sh does).
#   8. serial, mm_hyd_43 (3D) with "ilin = 0  itlin = 1": stops at start-up
#      with exit code 33, "... is not supported in 3D (more than one
#      layer)" and "run in 2D, or set itlin = 0" once each, no signal line
#      (before, it blew up within three time steps with a bare stop in the
#      layer thickness).
#
# Needs shyfem, shyelab and mpirun on PATH (an OpenMPI build) and
# `make init` done.  Exit code 0 (ITLIN CHECK: PASS) or 1 (ITLIN CHECK:
# FAIL).
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
case "$NP" in ''|*[!0-9]*) echo "usage: $0 [NP]  (NP > 1)"; exit 2 ;; esac
[ "$NP" -gt 1 ] || { echo "usage: $0 [NP]  (NP > 1)"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
SRC="$HERE/../../../src/shyfem/lagrange_track.f90"
rc=0
fail() { echo "ITLIN CHECK FAIL: $*"; rc=1; }

for t in shyfem shyelab mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "ITLIN CHECK FAIL: $t is not on PATH"; exit 1; }
done
[ -f GRID/MM_coarse.bas ] || { echo "ITLIN CHECK FAIL: GRID/MM_coarse.bas is missing: run 'make init'"; exit 1; }

SCR="$(mktemp -d "${TMPDIR:-/tmp}/itlin.XXXXXX")" || exit 1
TAG="itl$$"
cleanup() {
  local f
  for f in "$HERE/${TAG}"_*; do [ -e "$f" ] && rm -f "$f"; done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# mkstr SRC NAME SED... : scratch copy of SRC.str with run name NAME
mkstr() {
  local src="$1" name="$2"; shift 2
  [ "$(grep -c "^[[:space:]]*$src[[:space:]]*$" "$src.str")" = 1 ] \
    || { fail "cannot find the run name line of $src.str"; return 1; }
  sed -e "s/^\([ \t]*\)$src[ \t]*\$/\1$name/" "$@" "$src.str" > "$name.str"
}
ended() { [ "$1" = 0 ] && grep -q "simulation end" "$2"; }
ADV="run on one process, or set itlin = 0"
ITL='s/^\([ \t]*\)ilin = [01][ \t]*$/\1ilin = 0  itlin = 1/'

# stopcheck ROW LOG EXIT TEXT ADVICE : a start-up stop with exit code 33,
# the message and the advice once each, no signal or runtime-error line
stopcheck() {
  local row="$1" log="$2" r="$3" text="$4" adv="$5" n1 n2 nbad ok=1
  n1=$(grep -c "option itlin = 1 (semi-Lagrangian advection of momentum) is not supported $text" "$log")
  n2=$(grep -c "$adv" "$log")
  nbad=$(grep -c 'SIGFPE\|SIGSEGV\|Fortran runtime' "$log")
  [ "$r" = 33 ] || { ok=0; echo "  exit code $r (expected 33)"; }
  [ "$n1" = 1 ] || { ok=0; echo "  message seen $n1 times (expected once)"; }
  [ "$n2" = 1 ] || { ok=0; echo "  advice seen $n2 times (expected once)"; }
  [ "$nbad" = 0 ] || { ok=0; echo "  $nbad SIGFPE/SIGSEGV/Fortran runtime lines"; }
  if [ "$ok" = 1 ]; then echo "  stopped as expected: exit $r, message x$n1, advice x$n2"
  else tail -3 "$log"; fail "row $row: no clean start-up stop"; fi
}

# recmax FILE MODE : the largest value over the record lines
# ("l,ivar,min,aver,max") that "shyelab -write FILE" prints in $SCR/split;
# MODE abs: largest |min| or |max|, MODE max: largest max.  Prints the value
# and returns 0 only if shyelab exits with 0 and at least one record line
# was read whose min and max are numbers; otherwise prints nothing and
# returns 1 (a missing, empty or unreadable file, or a NaN, can then not
# pass as 0; a real 0 still passes).  The output of shyelab is kept in
# $SCR/split/write_FILE.log.
recmax() {
  local f="$1" mode="$2"
  ( cd "$SCR/split" && shyelab -write "$f" > "write_$f.log" 2>&1 ) || return 1
  awk -v mode="$mode" '
    BEGIN { num = "^[-+]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][-+]?[0-9]+)?$" }
    /l,ivar,min,aver,max/ {
      if( $5 !~ num || $7 !~ num ) { bad = 1; next }
      a = ($5 < 0 ? -$5 : $5); b = ($7 < 0 ? -$7 : $7)
      v = (mode == "abs" ? (a > b ? a : b) : $7 + 0)
      if( n == 0 || v > m ) m = v
      n++
    }
    END { if( n == 0 || bad ) exit 1; printf "%.3g", m }' "$SCR/split/write_$f.log"
}

echo "=== 1. serial: mm_hyd_01 with ilin = 0, itlin = 1"
R1="${TAG}_hyd01"
if mkstr mm_hyd_01 "$R1" -e "$ITL"; then
  grep -q "itlin = 1" "$R1.str" || fail "row 1: the sed expression set no itlin"
  timeout 600 nice -n 10 shyfem "$R1.str" > "$SCR/1.log" 2>&1; r=$?
  if ended "$r" "$SCR/1.log"; then echo "  ended"
  else tail -3 "$SCR/1.log"; grep -m1 -A3 '^#3 ' "$SCR/1.log"; fail "row 1: the serial run did not end (exit $r)"; fi
fi

echo "=== 2. serial: mm_hyd_22a (one day) with ilin = 0, itlin = 1"
R2="${TAG}_hyd22a"
if mkstr mm_hyd_22a "$R2" -e "$ITL" -e "s/itend = '[^']*'/itend = '2009-01-02'/"; then
  grep -q "itlin = 1" "$R2.str" || fail "row 2: the sed expression set no itlin"
  timeout 900 nice -n 10 shyfem "$R2.str" > "$SCR/2.log" 2>&1; r=$?
  if ended "$r" "$SCR/2.log"; then
    mkdir -p "$SCR/split"
    if ! cp "$R2.hydro.shy" "$SCR/split/h.shy"; then
      fail "row 2: cannot copy $R2.hydro.shy"
    elif ! ( cd "$SCR/split" && shyelab -split h.shy > split.log 2>&1 ); then
      tail -3 "$SCR/split/split.log"; fail "row 2: shyelab -split failed"
    elif ! z=$(recmax zeta.shy abs); then
      fail "row 2: no usable water level record (none, or a value that is not a number) from shyelab -split/-write of $R2.hydro.shy (logs in $SCR/split)"
    elif ! s=$(recmax speed.shy max); then
      fail "row 2: no usable speed record (none, or a value that is not a number) from shyelab -split/-write of $R2.hydro.shy (logs in $SCR/split)"
    elif awk -v z="$z" -v s="$s" 'BEGIN{exit !(z+0 < 1 && s+0 < 5)}'; then
      echo "  ended; largest |water level| $z m, largest speed $s m/s (bounds 1 m, 5 m/s; plausibility only)"
    else fail "row 2: largest |water level| $z m, largest speed $s m/s (bounds 1 m, 5 m/s)"; fi
  else tail -3 "$SCR/2.log"; grep -m1 -A3 '^#3 ' "$SCR/2.log"; fail "row 2: the serial run did not end (exit $r)"; fi
fi

echo "=== 3. $NP processes: mm_hyd_01 with ilin = 0, itlin = 1 must stop at start-up"
if [ -f "$R1.str" ]; then
  for f in "$R1".*; do [ "$f" = "$R1.str" ] || rm -f "$f"; done
  timeout 600 nice -n 10 mpirun --oversubscribe -np "$NP" shyfem "$R1.str" > "$SCR/3.log" 2>&1; r=$?
  stopcheck 3 "$SCR/3.log" "$r" "with MPI" "$ADV"
fi

echo "=== 4. $NP processes: mm_hyd_01 (ilin = 1) with itlin = 1 must run"
R4="${TAG}_hyd01lin"
if mkstr mm_hyd_01 "$R4" -e 's/^\([ \t]*\)ilin = 1[ \t]*$/\1ilin = 1  itlin = 1/'; then
  grep -q "ilin = 1  itlin = 1" "$R4.str" || fail "row 4: the sed expression set no itlin"
  timeout 600 nice -n 10 mpirun --oversubscribe -np "$NP" shyfem "$R4.str" > "$SCR/4.log" 2>&1; r=$?
  if grep -q "is not supported with MPI" "$SCR/4.log"; then fail "row 4: the MPI message appears with ilin = 1"
  elif ended "$r" "$SCR/4.log"; then echo "  ended, no message"
  else tail -3 "$SCR/4.log"; fail "row 4: the run did not end on $NP processes (exit $r)"; fi
fi

echo "=== 5. source: no bare stop in lagrange_track.f90"
nsub=$(grep -ciE "^[[:space:]]*subroutine (track_orig|track_line)[[:space:]]*\(" "$SRC" 2>/dev/null)
if [ ! -f "$SRC" ]; then fail "row 5: $SRC not found"
elif [ "$nsub" != 2 ]; then
  # the text read must be the tracker: an unreadable or wrong file would
  # otherwise count no stop statement and pass
  fail "row 5: $SRC does not hold track_orig and track_line once each (found ${nsub:-none})"
else
  # code part of each line (text after ! removed, a blank put in front),
  # then a stop statement: the word stop followed by a quoted text or by
  # the end of the line
  pat="[^_a-z0-9]stop[[:space:]]*('|\$)"
  nstop=$(sed -e 's/!.*//' -e 's/^/ /' "$SRC" | grep -ciE "$pat")
  if [ "$nstop" = 0 ]; then echo "  none"
  else sed -e 's/!.*//' -e 's/^/ /' "$SRC" | grep -niE "$pat" | head -10; fail "row 5: $nstop bare stop statements"; fi
fi

echo "=== 6. serial: mm_hyd_01 with ilin = 0, itlin = 2 (no such option) must stop"
R6="${TAG}_hyd01opt"
if mkstr mm_hyd_01 "$R6" -e 's/^\([ \t]*\)ilin = 1[ \t]*$/\1ilin = 0  itlin = 2/'; then
  grep -q "itlin = 2" "$R6.str" || fail "row 6: the sed expression set no itlin"
  timeout 600 nice -n 10 shyfem "$R6.str" > "$SCR/6.log" 2>&1; r=$?
  n1=$(grep -c "error stop set_explicit: no such option" "$SCR/6.log")
  if [ "$r" = 33 ] && [ "$n1" -ge 1 ]; then echo "  stopped as expected: exit $r"
  else tail -3 "$SCR/6.log"; fail "row 6: exit $r, message seen $n1 times (expected exit 33 and the message)"; fi
fi

echo "=== 7. serial: mm_hyd_01 on the geographic basin with ilin = 0, itlin = 1 must stop"
R7="${TAG}_hyd01geo"
# built when missing; a stale one is replaced, with a line saying so (#280)
if ! ./check_geo_bas.sh --build-missing . "ITLIN CHECK"; then
  fail "row 7: GRID/MM_geo.bas is not usable (check_geo_bas.sh)"
elif mkstr mm_hyd_01 "$R7" -e "$ITL" -e 's|^\([ \t]*\)GRID/MM_coarse[ \t]*$|\1GRID/MM_geo|'; then
  grep -q "itlin = 1" "$R7.str" || fail "row 7: the sed expression set no itlin"
  grep -q "GRID/MM_geo" "$R7.str" || fail "row 7: the sed expression set no geographic basin"
  timeout 600 nice -n 10 shyfem "$R7.str" > "$SCR/7.log" 2>&1; r=$?
  stopcheck 7 "$SCR/7.log" "$r" "on a geographic (lat/lon) grid" "use a Cartesian grid, or set itlin = 0"
fi

echo "=== 8. serial: mm_hyd_43 (3D) with ilin = 0, itlin = 1 must stop"
R8="${TAG}_hyd43"
if mkstr mm_hyd_43 "$R8" -e "$ITL"; then
  grep -q "itlin = 1" "$R8.str" || fail "row 8: the sed expression set no itlin"
  timeout 600 nice -n 10 shyfem "$R8.str" > "$SCR/8.log" 2>&1; r=$?
  stopcheck 8 "$SCR/8.log" "$r" "in 3D (more than one layer)" "run in 2D, or set itlin = 0"
fi

if [ "$rc" = 0 ]; then rm -rf "$SCR"; echo "ITLIN CHECK: PASS"
else echo "logs kept in $SCR"; echo "ITLIN CHECK: FAIL"; fi
exit "$rc"
