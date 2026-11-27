#!/bin/bash
#------------------------------------------------------------------------
# Error of the TVD upwind value (itvd = 2) inside the OpenMP tasks of
# conz3d_omp, issue #317.
#
# Usage:  ./check_tvd_omp.sh [NP]     (processes of the MPI rows, default 4)
#
# tvd_get_upwind_c runs in the tasks of conz3d_omp (itvd = 2), where a
# worker thread may neither write nor abort.  It used to call femintp_xi,
# whose xy2xi ends a wrong coordinate with a bare stop (exit code 0), and
# had a second bare stop (lremote).  Now it records the error
# (mod_tvd: tvd_error_record) and the main thread checks the record after
# the parallel region (tvd_check_error): one message, exit code 33
# (shympi_abort_internal).  No error can be reached with real data, so
# the rows use the test hook TVD_TEST_ERROR=K (read once by tvd_init, on
# the master process only): K = 1 forces the xy2xi error, K = 2 the
# lremote error, in the first upwind value of the run.  The case is
# mm_hyd_42 (2D, salinity and temperature, so that the upwind values are
# not uniform) without its tilt lines (tilting is serial only), with
# "itvd = 2".  Every row runs a scratch copy with a run name of its own
# (removed with its outputs at the end; the logs go to a folder made with
# mktemp under ${TMPDIR:-/tmp}, removed when every row passed, kept and
# printed when one failed).  A run has ended only if its launcher exits
# with 0 and its log has "simulation end".
#
#   1. serial, 1 thread, no hook: the run ends (3 hours), and the hook
#      line is not in the log (the guard: the hook is inert).
#   2. serial, 1 thread (nomp default 0), TVD_TEST_ERROR=1: exit code 33
#      and exactly one line "error stop tvd_get_upwind_c", no
#      "simulation end", no signal or runtime-error line.  Before #317
#      the hook does not exist and the run ends with exit code 0 (the
#      path it stands for, a wrong xi, was a bare stop with exit code 0).
#   3. serial, nomp = -1 and OMP_NUM_THREADS = 4 (the log must say "used
#      OMP threads: 4": nomp defaults to 0, which forces one thread),
#      TVD_TEST_ERROR=1: the same as row 2.
#   4. NP processes, TVD_TEST_ERROR=1 (master only): the same as row 2
#      (the abort is MPI_ABORT, exit code 33 of Open MPI's mpirun), and
#      the log shows NP processes.
#   5. serial, 1 thread, TVD_TEST_ERROR=2 (the lremote check): the same
#      as row 2.
#   6. serial, nomp = -1, OMP_NUM_THREADS = 4, T/S and two tracers (iconz =
#      2: three transports run as concurrent sibling tasks, which share the
#      error record), TVD_TEST_ERROR=3 (every call that reaches the check
#      fails): exactly one error line and exit 33.  Before the fix of the
#      review of #317 each transport that saw the error wrote a line and
#      aborted from its own task (more than one line).
#   7. source: tvd_get_upwind_c in src/shyfem/tvd_admin.f90 has no stop
#      statement and calls femintp_xi_ierr, not femintp_xi (reads the
#      text, not a run).
#
# Needs shyfem and mpirun on PATH (an OpenMPI build) and `make init` done.
# Exit code 0 (TVD OMP CHECK: PASS) or 1 (TVD OMP CHECK: FAIL).
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
case "$NP" in ''|*[!0-9]*) echo "usage: $0 [NP]  (NP > 1)"; exit 2 ;; esac
[ "$NP" -gt 1 ] || { echo "usage: $0 [NP]  (NP > 1)"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
SRC="$HERE/../../../src/shyfem/tvd_admin.f90"
rc=0
fail() { echo "TVD OMP CHECK FAIL: $*"; rc=1; }

for t in shyfem mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "TVD OMP CHECK FAIL: $t is not on PATH"; exit 1; }
done
[ -f GRID/MM_coarse_smooth.grd ] || { echo "TVD OMP CHECK FAIL: GRID/MM_coarse_smooth.grd is missing"; exit 1; }

SCR="$(mktemp -d "${TMPDIR:-/tmp}/tvdomp.XXXXXX")" || exit 1
TAG="tvo$$"
cleanup() {
  local f
  for f in "$HERE/${TAG}"_*; do [ -e "$f" ] && rm -f "$f"; done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# mkstr NAME [nomp] : scratch copy of mm_hyd_42.str with run name NAME, no
# tilt lines, itvd = 2, three hours; "nomp" adds nomp = -1, "conz" adds two
# tracers (iconz = 2, as mm_hyd_conz.str)
mkstr() {
  local name="$1" extra="" a
  shift
  for a in "$@"; do
    [ "$a" = nomp ] && extra="${extra}\\1nomp = -1\\n"
    [ "$a" = conz ] && extra="${extra}\\1iconz = 2\\n\\1conref = 1.\\n\\1idecay = 1\\n\\1taupar = 0.5 1.\\n"
  done
  [ "$(grep -c "^[[:space:]]*mm_hyd_42[[:space:]]*$" mm_hyd_42.str)" = 1 ] \
    || { fail "cannot find the run name line of mm_hyd_42.str"; return 1; }
  sed -e "s/^\([ \t]*\)mm_hyd_42[ \t]*\$/\1$name/" \
      -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/^\([ \t]*\)ilin = 1/\1itvd = 2\n${extra}\1ilin = 1/" \
      -e "s/itend = '[^']*'/itend = '2009-01-01::03:00:00'/" mm_hyd_42.str > "$name.str"
  grep -q "itvd = 2" "$name.str" && ! grep -q "tilt" "$name.str" \
    || { fail "the sed expressions made no itvd = 2 case without tilt for $name"; return 1; }
}
ended() { [ "$1" = 0 ] && grep -q "simulation end" "$2"; }

# stopcheck ROW LOG EXIT CODE : exit code 33, one error line (with "code
# CODE "), no end, no signal
stopcheck() {
  local row="$1" log="$2" r="$3" code="$4" n1 nbad nend nhook ok=1
  n1=$(grep -c "error stop tvd_get_upwind_c: code $code " "$log")
  [ "$(grep -c "error stop tvd_get_upwind_c" "$log")" = "$n1" ] || n1="$n1 (and other error lines)"
  nend=$(grep -c "simulation end" "$log")
  nhook=$(grep -c "test hook TVD_TEST_ERROR" "$log")
  nbad=$(grep -c 'SIGFPE\|SIGSEGV\|Fortran runtime' "$log")
  [ "$r" = 33 ] || { ok=0; echo "  exit code $r (expected 33)"; }
  [ "$n1" = 1 ] || { ok=0; echo "  error line seen $n1 times (expected once)"; }
  [ "$nend" = 0 ] || { ok=0; echo "  the run ended ('simulation end' seen)"; }
  [ "$nhook" = 1 ] || { ok=0; echo "  hook line seen $nhook times (expected once)"; }
  [ "$nbad" = 0 ] || { ok=0; echo "  $nbad SIGFPE/SIGSEGV/Fortran runtime lines"; }
  if [ "$ok" = 1 ]; then echo "  stopped as expected: exit $r, error line x$n1: $(grep -m1 'error stop tvd_get_upwind_c' "$log" | sed 's/^ *//' | cut -c1-60)..."
  else tail -3 "$log"; fail "row $row: no single clean stop with exit code 33"; fi
}

echo "=== 1. serial, 1 thread, no hook: the itvd = 2 case ends"
R1="${TAG}_off"
if mkstr "$R1"; then
  TVD_TEST_ERROR= OMP_NUM_THREADS=1 timeout 900 nice -n 10 shyfem "$R1.str" > "$SCR/1.log" 2>&1; r=$?
  if ! ended "$r" "$SCR/1.log"; then tail -3 "$SCR/1.log"; fail "row 1: the run did not end (exit $r)"
  elif grep -q "test hook TVD_TEST_ERROR" "$SCR/1.log"; then fail "row 1: the hook line is in the log without the hook"
  elif ! grep -q "tvd type: *2" "$SCR/1.log"; then fail "row 1: the log shows no itvd = 2 (tvd type: 2)"
  else echo "  ended, no hook line, itvd = 2"; fi
fi

echo "=== 2. serial, 1 thread, TVD_TEST_ERROR=1 (xy2xi): one message, exit 33"
R2="${TAG}_t1"
if mkstr "$R2"; then
  TVD_TEST_ERROR=1 OMP_NUM_THREADS=1 timeout 900 nice -n 10 shyfem "$R2.str" > "$SCR/2.log" 2>&1; r=$?
  stopcheck 2 "$SCR/2.log" "$r" 1
fi

echo "=== 3. serial, 4 threads (nomp = -1), TVD_TEST_ERROR=1: one message, exit 33"
R3="${TAG}_t4"
if mkstr "$R3" nomp; then
  TVD_TEST_ERROR=1 OMP_NUM_THREADS=4 timeout 900 nice -n 10 shyfem "$R3.str" > "$SCR/3.log" 2>&1; r=$?
  if ! grep -q "for simulation used OMP threads: *4\$" "$SCR/3.log"; then
    grep "used OMP threads" "$SCR/3.log"; fail "row 3: the log does not say 'used OMP threads: 4' (nomp = -1, OMP_NUM_THREADS = 4)"
  else
    echo "  $(grep 'for simulation used OMP threads' "$SCR/3.log" | sed 's/^ *//;s/  */ /g')"
    stopcheck 3 "$SCR/3.log" "$r" 1
  fi
fi

echo "=== 4. $NP processes, TVD_TEST_ERROR=1: one message, exit 33"
R4="${TAG}_np"
if mkstr "$R4"; then
  TVD_TEST_ERROR=1 OMP_NUM_THREADS=1 timeout 900 nice -n 10 mpirun --oversubscribe -np "$NP" -x TVD_TEST_ERROR -x OMP_NUM_THREADS shyfem "$R4.str" > "$SCR/4.log" 2>&1; r=$?
  nr=$(grep -c 'shympi initialized:' "$SCR/4.log")
  if [ "$nr" != "$NP" ]; then fail "row 4: the log shows $nr 'shympi initialized:' lines, expected $NP"
  else stopcheck 4 "$SCR/4.log" "$r" 1; fi
fi

echo "=== 5. serial, 1 thread, TVD_TEST_ERROR=2 (lremote): one message, exit 33"
R5="${TAG}_lr"
if mkstr "$R5"; then
  TVD_TEST_ERROR=2 OMP_NUM_THREADS=1 timeout 900 nice -n 10 shyfem "$R5.str" > "$SCR/5.log" 2>&1; r=$?
  stopcheck 5 "$SCR/5.log" "$r" 4
fi

echo "=== 6. serial, 4 threads, T/S and two tracers, TVD_TEST_ERROR=3 (every call fails): ONE message, exit 33"
R7="${TAG}_cc"
if mkstr "$R7" nomp conz; then
  grep -q "iconz = 2" "$R7.str" || fail "row 6: no tracers in $R7.str"
  TVD_TEST_ERROR=3 OMP_NUM_THREADS=4 timeout 900 nice -n 10 shyfem "$R7.str" > "$SCR/7.log" 2>&1; r=$?
  if ! grep -q "for simulation used OMP threads: *4\$" "$SCR/7.log"; then
    grep "used OMP threads" "$SCR/7.log"; fail "row 6: the log does not say 'used OMP threads: 4'"
  else
    stopcheck 6 "$SCR/7.log" "$r" 1
  fi
fi

echo "=== 7. source: no stop in tvd_get_upwind_c, femintp_xi_ierr called"
if [ ! -f "$SRC" ]; then fail "row 7: $SRC not found"
else
  # comment lines are left out of the stop count; a 'stop', an 'error stop' text
  # and the stop' forms all count
  body=$(awk 'tolower($0) ~ /^[ \t]*subroutine[ \t]+tvd_get_upwind_c[ \t]*\(/ {f=1} f {print} f && tolower($0) ~ /^[ \t]*end[ \t]*$/ {exit}' "$SRC")
  nsub=$(printf '%s\n' "$body" | grep -ciE '^[[:space:]]*subroutine[[:space:]]+tvd_get_upwind_c[[:space:]]*\(')
  nstop=$(printf '%s\n' "$body" | grep -v '^[[:space:]]*!' | grep -ciE '(^|[^a-z_])stop([^a-z_]|$)|error[[:space:]]+stop')
  nxi=$(printf '%s\n' "$body" | grep -ciE 'call[[:space:]]+femintp_xi_ierr[[:space:]]*\(')
  nold=$(printf '%s\n' "$body" | grep -ciE '^[[:space:]]*call[[:space:]]+femintp_xi[[:space:]]*\(')
  nrec=$(printf '%s\n' "$body" | grep -ciE 'call[[:space:]]+tvd_error_record[[:space:]]*\(')
  if [ "$nsub" != 1 ]; then
    fail "row 7: could not read tvd_get_upwind_c from $SRC (subroutine lines $nsub)"
  elif [ "$nstop" != 0 ] || [ "$nxi" != 1 ] || [ "$nold" != 0 ] || [ "$nrec" != 2 ]; then
    fail "row 7: tvd_get_upwind_c has $nstop stop statements (expected 0), $nxi calls of femintp_xi_ierr (expected 1), $nold calls of femintp_xi (expected 0), $nrec calls of tvd_error_record (expected 2)"
  else echo "  no stop statement, one call of femintp_xi_ierr"; fi
fi

if [ "$rc" = 0 ]; then
  rm -rf "$SCR"
  echo "TVD OMP CHECK: PASS"
else
  echo "logs kept in $SCR"
  echo "TVD OMP CHECK: FAIL"
fi
exit "$rc"
