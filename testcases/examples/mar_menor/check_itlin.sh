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
#      ends; the largest water level and speed of its hydro file are
#      printed (there is no reference for itlin = 1 results: the numbers are
#      plausibility only).  Before #227: the same crash; with the
#      allocation alone it stopped at once in lagr_layer_thickness (the
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
#      shympi_abort_internal since #227).  This row reads the text, not a
#      run: no run checked for #227 reaches those lines (no tracer of the
#      2D runs changed layer; a 3D run with itlin = 1, mm_hyd_43 with
#      "itlin = 1", blows up within three time steps, before any tracer
#      changes layer).
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
MSG="option itlin = 1 (semi-Lagrangian advection of momentum) is not supported with MPI"
ADV="run on one process, or set itlin = 0"
ITL='s/^\([ \t]*\)ilin = [01][ \t]*$/\1ilin = 0  itlin = 1/'

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
    mkdir -p "$SCR/split" && cp "$R2.hydro.shy" "$SCR/split/h.shy"
    ( cd "$SCR/split" && shyelab -split h.shy > split.log 2>&1 )
    z=$(cd "$SCR/split" && shyelab -write zeta.shy 2>/dev/null | awk '/l,ivar/{a=($5<0?-$5:$5); b=($7<0?-$7:$7); if(a>m)m=a; if(b>m)m=b} END{printf "%.3g", m}')
    s=$(cd "$SCR/split" && shyelab -write speed.shy 2>/dev/null | awk '/l,ivar/{if($7>m)m=$7} END{printf "%.3g", m}')
    echo "  ended; largest |water level| $z m, largest speed $s m/s (plausibility only)"
  else tail -3 "$SCR/2.log"; grep -m1 -A3 '^#3 ' "$SCR/2.log"; fail "row 2: the serial run did not end (exit $r)"; fi
fi

echo "=== 3. $NP processes: mm_hyd_01 with ilin = 0, itlin = 1 must stop at start-up"
if [ -f "$R1.str" ]; then
  for f in "$R1".*; do [ "$f" = "$R1.str" ] || rm -f "$f"; done
  timeout 600 nice -n 10 mpirun --oversubscribe -np "$NP" shyfem "$R1.str" > "$SCR/3.log" 2>&1; r=$?
  n1=$(grep -c "$MSG" "$SCR/3.log"); n2=$(grep -c "$ADV" "$SCR/3.log")
  nbad=$(grep -c 'SIGFPE\|SIGSEGV\|Fortran runtime' "$SCR/3.log")
  ok=1
  [ "$r" = 33 ] || { ok=0; echo "  exit code $r (expected 33)"; }
  [ "$n1" = 1 ] || { ok=0; echo "  message seen $n1 times (expected once)"; }
  [ "$n2" = 1 ] || { ok=0; echo "  advice seen $n2 times (expected once)"; }
  [ "$nbad" = 0 ] || { ok=0; echo "  $nbad SIGFPE/SIGSEGV/Fortran runtime lines"; }
  if [ "$ok" = 1 ]; then echo "  stopped as expected: exit $r, message x$n1, advice x$n2"
  else tail -3 "$SCR/3.log"; fail "row 3: no clean start-up stop on $NP processes"; fi
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
if [ ! -f "$SRC" ]; then fail "row 5: $SRC not found"
else
  # code part of each line (text after ! removed, a blank put in front),
  # then a stop statement: the word stop followed by a quoted text or by
  # the end of the line
  pat="[^_a-z0-9]stop[[:space:]]*('|\$)"
  nstop=$(sed -e 's/!.*//' -e 's/^/ /' "$SRC" | grep -ciE "$pat")
  if [ "$nstop" = 0 ]; then echo "  none"
  else sed -e 's/!.*//' -e 's/^/ /' "$SRC" | grep -niE "$pat" | head -10; fail "row 5: $nstop bare stop statements"; fi
fi

if [ "$rc" = 0 ]; then rm -rf "$SCR"; echo "ITLIN CHECK: PASS"
else echo "logs kept in $SCR"; echo "ITLIN CHECK: FAIL"; fi
exit "$rc"
