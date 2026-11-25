#!/bin/bash
#------------------------------------------------------------------------
# Wetting and drying, serial against 2 and 4 processes, byte for byte
# (issue #295).
#
# The dry-element counter iwetv (src/shyfem/geom_dynamic.f90) is started
# for the elements that are dry at the beginning by setweg(-1) in
# shyfem_init (src/shyfem/shyfem_subs.f90).  That call was made only in a
# serial run (if( .not. bmpi ) ... !shympi - FIXME, from 2017, never
# revisited): on several processes the first setweg(0) counted as a new
# time and the counter of such an element began at -1 instead of +1.  The
# element then passed the re-wetting gate (-iwetv > 5 in setweg) one step
# earlier than in the serial run, and the two runs went apart: with
# mm_hyd_12b (Mar Menor, zconst = -0.3, 10 dry elements at the start) at
# the sixth step, 00:30, with 15 dry elements serially and 12 on several
# processes.  setweg(-1) is now called on every process.
#
# The case: testcases/examples/mar_menor/mm_hyd_12b.str as it is, except
# that the tilt lines (ztilt, ktilt) are removed (a tilt stops a run on
# several processes, issue #216) and that it ends after one day
# (2009-01-02), run serially and on 2 and 4 processes with the METIS
# partition the model makes, about 2 s each on the development machine.
# Required: every run ends (exit code 0 and "simulation end" in the log,
# timeout 600 s each); the serial run has dry elements at its first step
# (the 4th number of the first "wet_and_dry:" line of the .inf file; a run
# without them could pass without testing anything); the log of the NP-process
# runs has the line "shympi initialized: ID NP" once from each rank 0 to
# NP-1; and every .shy file and the extra-point
# file .ext of the runs on 2 and 4 processes are byte-identical to
# the serial ones.  On a difference the first differing "wet_and_dry:" line
# of the .inf files is printed.
#
# Usage:  ./check_wetdry_mpi.sh
# Needs shyfem, shypre and mpirun on PATH (an OpenMPI build).  Works in a
# folder made with mktemp -d under ${TMPDIR:-/tmp} (the basin is built
# there from GRID/MM_coarse.grd), so nothing in the source folders
# changes.  The folder is kept (its path is the last line).  Prints
# "WETDRY MPI CHECK: PASS" or "WETDRY MPI CHECK: FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
for t in shyfem shypre mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "WETDRY MPI CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse.grd mm_hyd_12b.str INPUT/level_Mar_Menor.dat INPUT/wind_scir.txt; do
  [ -f "$HERE/$f" ] || { echo "WETDRY MPI CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/wetdry.XXXXXX")" || exit 1
echo "wetdry mpi check: $(command -v shyfem), serial vs 2 and 4 processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "WETDRY MPI CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre -silent MM_coarse.grd > shypre.log 2>&1 ) \
  || { echo "WETDRY MPI CHECK: FAIL (shypre failed, log in $P/GRID)"; exit 1; }

sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
    -e "s/itend = '[^']*'/itend = '2009-01-02'/" "$HERE/mm_hyd_12b.str" > "$P/wd.str"
if grep -q 'ktilt\|ztilt' "$P/wd.str" || ! grep -q "itend = '2009-01-02'" "$P/wd.str" \
   || ! grep -q 'zconst = -0.30' "$P/wd.str"; then
  echo "WETDRY MPI CHECK: FAIL (cannot make wd.str from mm_hyd_12b.str)"; exit 1
fi

ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # NP (1: a plain run without mpirun)
  local d="$P/np$1" r
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" && cp "$P/wd.str" "$d/" || return 1
  if [ "$1" = 1 ]; then
    ( cd "$d" && timeout 600 nice -n 10 shyfem wd.str < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && timeout 600 nice -n 10 mpirun --oversubscribe -np "$1" shyfem wd.str < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  # NP > 1: the run must really have NP processes (an mpirun that does
  # not match the binary's MPI gives NP serial runs: a check that cannot fail)
  if [ "$1" != 1 ] && ! ranks_ok "$d/run.log" "$1"; then
    echo "  the log does not show $1 MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines ($d/run.log)"
    return 1
  fi
  return 0
}

if ! run 1; then
  fail "the serial run did not end (above)"
else
  INF="$(ls "$P"/np1/*.inf 2> /dev/null | head -1)"
  if [ -z "$INF" ]; then
    fail "the serial run wrote no .inf file"
  else
    DRY0="$(grep 'wet_and_dry:' "$INF" | head -1 | awk '{print $4}')"
    DRY0="${DRY0%.}"
    echo "  serial run: $DRY0 dry elements at the first step"
    case "$DRY0" in ''|*[!0-9]*) fail "cannot read the dry elements of the first step from $INF"; DRY0=0 ;; esac
    [ "$DRY0" -gt 0 ] || fail "the serial run has no dry elements at the start: the check would test nothing"
  fi
fi
if [ "$rc" = 0 ]; then
  for np in 2 4; do
    if ! run "$np"; then fail "the run on $np processes did not end, or not on $np processes (above)"; continue; fi
    for a in "$P"/np1/*.shy "$P"/np1/*.ext; do
      f="$(basename "$a")"; b="$P/np$np/$f"
      if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$f missing or empty (serial or $np processes)"; continue; fi
      if cmp -s "$a" "$b"; then
        echo "  np $np: $f byte-identical"
      else
        echo "  np $np: $f DIFFERS, first difference: $(cmp "$a" "$b" 2>&1 | head -1)"
        fail "$f differs between serial and $np processes"
      fi
    done
    if [ "$rc" != 0 ]; then
      d="$(diff <(grep 'wet_and_dry:' "$INF") <(grep 'wet_and_dry:' "$P/np$np/$(basename "$INF")") | head -4)"
      [ -n "$d" ] && { echo "  first differing wet_and_dry lines (< serial, > $np processes):"; echo "$d" | sed 's/^/    /'; }
    fi
  done
fi

if [ "$rc" = 0 ]; then echo "WETDRY MPI CHECK: PASS"; else echo "WETDRY MPI CHECK: FAIL"; fi
echo "$P"
exit "$rc"
