#!/bin/bash
#------------------------------------------------------------------------
# Tests of the exit-status handling of the gate drivers check_lgr_serial.sh,
# check_lgr_mpi.sh and check_lgr_bounds.sh.  A gate must never print PASS
# for a run that failed to launch, timed out or exited with an error code,
# also when the run's log has "simulation end".
#
# Usage:  ./test_lgr_drivers.sh [SRC_DIR]
#   SRC_DIR  the folder that holds the drivers and the tools under test
#            (default: this folder; an export of an older commit shows which
#            tests its drivers fail)
#
# No model runs: fake shyfem, mpirun, timeout and shypre (written into a
# folder made with mktemp under ${TMPDIR:-/tmp}, removed at the end) stand
# in for the real ones, and every driver runs in a fresh copy of its own
# (the drivers cd to their own folder and remove outputs there).  The fake
# shyfem copies a small synthetic particle file to NAME.lgr.shy, writes
# NAME.hydro.shy and NAME.inf, prints "simulation end" and exits with
# FAKE_RC; the fake mpirun runs its program once with FAKE_RC set to
# FAKE_MPI_RC; the fake timeout runs its command and then returns 124 (the
# exit code of GNU timeout at its limit) when FAKE_TIMEOUT names the kind
# of run (mpi, serial or all).  check_lgr_bounds.sh is run in a throwaway git
# repository whose Makefile target fem "builds" by copying the fakes (the
# build log carries the -fcheck=bounds flag).  Each driver also gets a run in
# which everything succeeds, which must PASS (so that a FAIL elsewhere is not
# a broken fixture).  A few seconds in all.
# Prints one line per test and "LGR DRIVER TEST: PASS" or "FAIL"; exits 0 or 1.
#------------------------------------------------------------------------
set -u
here="$(cd "$(dirname "$0")" && pwd)" || exit 1
src="$(cd "${1:-$here}" && pwd)" || { echo "LGR DRIVER TEST: FAIL (no folder ${1:-})"; exit 1; }
tmp="$(mktemp -d "${TMPDIR:-/tmp}/lgrdrv.XXXXXX")" || exit 1
[ -n "$tmp" ] && [ -d "$tmp" ] || exit 1
trap 'rm -rf "$tmp"' EXIT
fail=0
export TMPDIR="$tmp"		# the drivers' own scratch folders go in here

#--- fakes -------------------------------------------------------------------
mkdir "$tmp/fake" || exit 1
cat > "$tmp/fake/shyfem" <<'EOF'
#!/bin/bash
# fake shyfem STR (see test_lgr_drivers.sh)
name="$(basename "${1%.str}")"; name="${name%%.lgrdbg.*}"
if [ "${FAKE_UNDER_MPI:-0}" = 1 ] && [ "${FAKE_STOPS:-0}" = 1 ]; then
  opt="${name#stops_}"; opt="${opt%_*}"
  case "$opt" in
    ilagr3) lab="ilagr = 3" ;; rwhpar) lab="rwhpar < 0" ;;
    ipvert) lab="ipvert < -1" ;; *) lab="$opt" ;;
  esac
  echo " Lagrangian option $lab is not supported with MPI"
  echo " run on one process, or remove $lab"
  exit "${FAKE_RC:-0}"
fi
cp "$FAKE_LGR" "$name.lgr.shy" || exit 99
echo "fake hydro" > "$name.hydro.shy"
echo "fake inf" > "$name.inf"
if [ "${FAKE_RUNTIME:-0}" = 1 ]; then
  echo "At line 1 of file fake.f90"
  echo "Fortran runtime error: Index '0' of dimension 1 of array 'x' below lower bound of 1"
  exit 2
fi
[ "${FAKE_END:-1}" = 1 ] && echo "      simulation end"
exit "${FAKE_RC:-0}"
EOF
cat > "$tmp/fake/mpirun" <<'EOF'
#!/bin/bash
# fake mpirun [options] PROG ARGS: PROG ARGS once, FAKE_RC = FAKE_MPI_RC
while [ $# -gt 0 ]; do
  case "$1" in
    -np|-n|-x) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
export FAKE_UNDER_MPI=1 FAKE_RC="${FAKE_MPI_RC:-0}"
exec "$@"
EOF
cat > "$tmp/fake/timeout" <<'EOF'
#!/bin/bash
# fake timeout DURATION CMD...: CMD without a limit, then 124 if FAKE_TIMEOUT
# is all, or mpi and CMD runs mpirun, or serial and it does not
shift
"$@"; rc=$?
case " $* " in *" mpirun "*) kind=mpi ;; *) kind=serial ;; esac
case "${FAKE_TIMEOUT:-}" in all|"$kind") exit 124 ;; esac
exit "$rc"
EOF
printf '#!/bin/bash\nexit 0\n' > "$tmp/fake/shypre"
chmod +x "$tmp/fake"/* || exit 1
mkdir "$tmp/ref" && ln -s "$tmp/fake/shyfem" "$tmp/ref/shyfem" || exit 1
export PATH="$tmp/fake:$PATH"

# the synthetic particle file: a header record, ncust = 1, two output
# times with two active particles each (the format of lgr_compare.py)
python3 - "$tmp/fixture.lgr.shy" <<'PY' || { echo "LGR DRIVER TEST: FAIL (fixture)"; exit 1; }
import struct, sys
def rec(p):
    n = struct.pack('<i', len(p))
    return n + p + n
out = rec(b'FAKEHDR1' * 3) + rec(struct.pack('<i', 1))
for dtime in (0.0, 3600.0):
    parts = [(1, 0.1, 0.2), (2, 0.3, 0.4)]
    out += rec(struct.pack('<dii', dtime, len(parts), 0))
    for pid, x, y in parts:
        out += rec(struct.pack('<iidfi', pid, 1, 100.0, 0.5, 3))
        out += rec(struct.pack('<fffif', x, y, -1.5, 1, 0.25))
        out += rec(struct.pack('<f', 0.5))
    out += rec(struct.pack('<dii', dtime, 0, -1)) + rec(struct.pack('<dii', dtime, 0, 1))
with open(sys.argv[1], 'wb') as f:
    f.write(out)
PY
export FAKE_LGR="$tmp/fixture.lgr.shy"

#--- helpers -------------------------------------------------------------------
# expect DESC WANT_EXIT REGEX CMD...: CMD must exit with WANT_EXIT and its
# output (read as one string: .* spans lines) must match the extended
# regular expression REGEX
expect() {
  local desc="$1" want="$2" rx="$3" got; shift 3
  "$@" > "$tmp/out.txt" 2>&1
  got=$?
  if [ "$got" -ne "$want" ]; then
    echo "FAIL: $desc: exit $got, expected $want"; tail -12 "$tmp/out.txt" | sed 's/^/    /'; fail=1; return
  fi
  if [ -n "$rx" ] && ! grep -Ezq -- "$rx" "$tmp/out.txt"; then
    echo "FAIL: $desc: output lacks /$rx/"; tail -12 "$tmp/out.txt" | sed 's/^/    /'; fail=1; return
  fi
  echo "ok: $desc"
}

# newdir NAME: a fresh folder $tmp/NAME/mar_menor with the drivers, the
# tools, the STR file of case A, stub STR files and stub basins
newdir() {
  local d="$tmp/$1/mar_menor" c
  mkdir -p "$d/GRID" || return 1
  cp "$src/check_lgr_serial.sh" "$src/check_lgr_mpi.sh" "$src/lgr_compare.py" \
     "$src/lgr_inf_compare.py" "$src/lgr_dbg_compare.py" "$src/mm_lgr_a.str" "$d/" || return 1
  : > "$d/GRID/MM_geo.bas"; : > "$d/GRID/MM_coarse.bas"
  for c in mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr_w mm_lgr; do printf '$para\n$end\n' > "$d/$c.str"; done
  echo "$d"
}

#--- check_lgr_serial.sh -----------------------------------------------------------
d=$(newdir s1) || exit 1
expect "serial repro: every run succeeds" 0 "REPRO: PASS" \
  bash "$d/check_lgr_serial.sh" repro
d=$(newdir s2) || exit 1
expect "serial repro: shyfem exits 1 after 'simulation end'" 1 "REPRO: FAIL" \
  env FAKE_RC=1 bash "$d/check_lgr_serial.sh" repro
d=$(newdir s3) || exit 1
expect "serial guard: every run succeeds" 0 "SERIAL GUARD: PASS \(1 check skipped\)" \
  bash "$d/check_lgr_serial.sh" "$tmp/ref"
d=$(newdir s4) || exit 1
expect "serial guard: shyfem exits 1 after 'simulation end'" 1 "current serial run did not end.*SERIAL GUARD: FAIL" \
  env FAKE_RC=1 bash "$d/check_lgr_serial.sh" "$tmp/ref"
d=$(newdir s5) || exit 1
expect "serial guard: mpirun -np 1 exits 1 after 'simulation end'" 1 "mpirun -np 1 run did not end.*SERIAL GUARD: FAIL" \
  env FAKE_MPI_RC=1 bash "$d/check_lgr_serial.sh" "$tmp/ref"

#--- check_lgr_mpi.sh ----------------------------------------------------------------
d=$(newdir m1) || exit 1
expect "mpi pos: every run succeeds" 0 "LGR GATE: PASS" \
  bash "$d/check_lgr_mpi.sh" mm_lgr_a 1 pos
d=$(newdir m2) || exit 1
expect "mpi pos: the serial reference exits 1 after 'simulation end'" 1 "did not end serially \(exit code 1\).*LGR GATE: FAIL" \
  env FAKE_RC=1 bash "$d/check_lgr_mpi.sh" mm_lgr_a 1 pos
d=$(newdir m3) || exit 1
expect "mpi pos: the MPI run exits 1 after 'simulation end'" 1 "LGR GATE: FAIL" \
  env FAKE_MPI_RC=1 bash "$d/check_lgr_mpi.sh" mm_lgr_a 1 pos
# the stop on several processes is shympi_abort_internal's MPI_ABORT with
# code 33, which Open MPI's mpirun returns: only 33 passes
d=$(newdir m4) || exit 1
expect "mpi stops: every row stops as expected (exit 33)" 0 "LGR GATE: PASS" \
  env FAKE_STOPS=1 FAKE_MPI_RC=33 bash "$d/check_lgr_mpi.sh" mm_lgr_a 2 stops
d=$(newdir m5) || exit 1
expect "mpi stops: the MPI runs time out after printing both lines" 1 "timed out after 600 s.*LGR GATE: FAIL" \
  env FAKE_STOPS=1 FAKE_MPI_RC=33 FAKE_TIMEOUT=mpi bash "$d/check_lgr_mpi.sh" mm_lgr_a 2 stops
d=$(newdir m6) || exit 1
expect "mpi stops: the serial runs time out" 1 "serial: timed out after 600 s.*LGR GATE: FAIL" \
  env FAKE_STOPS=1 FAKE_MPI_RC=33 FAKE_TIMEOUT=serial bash "$d/check_lgr_mpi.sh" mm_lgr_a 2 stops
d=$(newdir m7) || exit 1
expect "mpi stops: both lines printed, then exit 1 instead of 33" 1 "exit code 1 \(expected 33.*LGR GATE: FAIL" \
  env FAKE_STOPS=1 FAKE_MPI_RC=1 bash "$d/check_lgr_mpi.sh" mm_lgr_a 2 stops

#--- check_lgr_bounds.sh in a throwaway repository --------------------------------
repo="$tmp/repo"
mm="$repo/testcases/examples/mar_menor"
mkdir -p "$mm/GRID" "$repo/fakes" || exit 1
cp "$src/check_lgr_bounds.sh" "$mm/" || exit 1
cp "$tmp/fake/shyfem" "$tmp/fake/mpirun" "$tmp/fake/timeout" "$tmp/fake/shypre" "$repo/fakes/" || exit 1
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr; do printf '$para\n$end\n' > "$mm/$c.str"; done
: > "$mm/GRID/MM_geo.grd"
printf 'fem:\n\t@echo "gfortran $(FGNU_BOUNDS) -c fake.f90"\n\tmkdir -p src/shyfem bin\n\tcp fakes/shyfem src/shyfem/shyfem\n\tln -sf ../src/shyfem/shyfem bin/shyfem\n\tcp fakes/mpirun fakes/timeout fakes/shypre bin/\n' > "$repo/Makefile"
( cd "$repo" && git init -q && git add -A && \
  git -c user.name=test -c user.email=test@example.invalid commit -q -m fixture ) \
  || { echo "LGR DRIVER TEST: FAIL (fixture repository)"; exit 1; }
expect "bounds: every run ends" 0 "BOUNDS GATE: PASS" \
  bash "$mm/check_lgr_bounds.sh"
expect "bounds: a runtime message is a finding" 1 "RUNTIME MESSAGE.*BOUNDS GATE: FAIL" \
  env FAKE_RUNTIME=1 bash "$mm/check_lgr_bounds.sh"
expect "bounds: runs that exit 1 without 'simulation end'" 1 "did not end \(exit code 1\).*BOUNDS GATE: FAIL \([0-9]+ runs did not end" \
  env FAKE_END=0 FAKE_RC=1 FAKE_MPI_RC=1 bash "$mm/check_lgr_bounds.sh"
expect "bounds: runs that exit 1 after 'simulation end'" 1 "exited with code 1.*BOUNDS GATE: FAIL \([0-9]+ runs did not end" \
  env FAKE_RC=1 FAKE_MPI_RC=1 bash "$mm/check_lgr_bounds.sh"
expect "bounds: runs that time out after 'simulation end'" 1 "TIMED OUT.*BOUNDS GATE: FAIL \([0-9]+ runs did not end" \
  env FAKE_TIMEOUT=all bash "$mm/check_lgr_bounds.sh"

if [ "$fail" -eq 0 ]; then echo "LGR DRIVER TEST: PASS"; exit 0; fi
echo "LGR DRIVER TEST: FAIL"; exit 1
