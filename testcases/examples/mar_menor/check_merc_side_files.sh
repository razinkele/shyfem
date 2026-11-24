#!/bin/bash
#------------------------------------------------------------------------
# The mercury module writes no debug side files (issue #264).
#
# The mercury routines wrote debug files under fixed unit numbers from
# every process: header lines to fort.250 to fort.282 and fort.350 to
# fort.382 (mercury.f90), and per-station lines for a hard-coded list of
# nodes of the Venice lagoon, given by external number, to fort.247 and
# fort.250 to fort.282 (merc_water4sed.f90), fort.450 to fort.482
# (merc_sed.f90) and fort.664, fort.665, fort.997 to fort.999
# (merc_sed4sed.f90).  On several processes every process that held such
# a node wrote the same file, so lines were lost or interleaved; nothing
# read the files, and they were removed.  In the Mar Menor mesh a
# mercury run left 73 such files (nodes 1331, 1372, 1375 and 1378 exist
# there).  The simple sediment module's fort.778 is checked by
# check_ssedi_mpi.sh.
#
# Cases: the three mercury cases of ../weutro_box (merc_2d.str, two days;
# merc_rst_part1.str, one day writing a restart file; merc_rst_part2.str,
# the next day from it), run serially and on NP processes (default 4)
# with the METIS partition the model makes.
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 600 s each); mercury really ran (its .merc.shy file is not
# empty: a binary built without MERCURY=true stops at start-up, which
# fails here); the log of an NP-process run has the line "shympi
# initialized: ID NP" once from each rank 0 to NP-1; and no file named
# fort.* is left in the run folders.
#
# Usage:  ./check_merc_side_files.sh [NP]
# Needs a binary built with MERCURY=true: shyfem, shypre and mpirun on
# PATH (an OpenMPI build).  Works in a folder made with mktemp -d under
# ${TMPDIR:-/tmp} (GRID/MM_coarse.grd of ../weutro_box is copied there
# and its basin is built there with shypre), so nothing in the test
# folders changes.  The folder is kept (its path is the last line).
# Prints "MERC SIDE FILES CHECK: PASS" or "MERC SIDE FILES CHECK: FAIL"
# and exits 0 or 1.  Takes about 20 s.
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
WB="$(cd "$HERE/../weutro_box" 2> /dev/null && pwd)" || { echo "MERC SIDE FILES CHECK: FAIL (no folder $HERE/../weutro_box)"; exit 1; }
case "$NP" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP] (NP at least 2)"; exit 2 ;; esac
for t in shyfem shypre mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "MERC SIDE FILES CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
CASES="merc_2d merc_rst_part1 merc_rst_part2"
for f in GRID/MM_coarse.grd merc_2d.str merc_rst_part1.str merc_rst_part2.str; do
  [ -f "$WB/$f" ] || { echo "MERC SIDE FILES CHECK: FAIL (missing $WB/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/mercside.XXXXXX")" || exit 1
echo "merc side files check: $(command -v shyfem), serial and $NP processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "MERC SIDE FILES CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$WB/GRID/MM_coarse.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse.grd > shypre.log 2>&1 ) \
  || { echo "MERC SIDE FILES CHECK: FAIL (shypre failed, log $P/GRID/shypre.log)"; exit 1; }

# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}

for n in 1 "$NP"; do
  d="$P/np$n"
  mkdir "$d" && ln -s ../GRID "$d/GRID" || exit 1
  for c in $CASES; do cp "$WB/$c.str" "$d/" || exit 1; done
  echo "=== $n process(es)"
  for c in $CASES; do
    if [ "$n" = 1 ]; then
      ( cd "$d" && timeout 600 nice -n 10 shyfem "$c.str" < /dev/null > "$c.log" 2>&1 )
    else
      ( cd "$d" && timeout 600 nice -n 10 mpirun --oversubscribe -np "$n" shyfem "$c.str" < /dev/null > "$c.log" 2>&1 )
    fi
    r=$?
    if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/$c.log"; then
      tail -3 "$d/$c.log"
      fail "$c on $n process(es) did not end (exit code $r; a binary without MERCURY=true stops at start-up)"
      continue
    fi
    if [ ! -s "$d/$c.merc.shy" ]; then fail "$c on $n process(es): no mercury output $c.merc.shy"; continue; fi
    if [ "$n" != 1 ] && ! ranks_ok "$d/$c.log" "$n"; then
      fail "$c: the log does not show $n MPI processes ($d/$c.log)"; continue
    fi
    echo "  $c: ran"
  done
  side="$(cd "$d" && ls -d fort.* 2> /dev/null)"
  if [ -n "$side" ]; then
    fail "$(echo "$side" | wc -l) side files fort.* left on $n process(es): $(echo $side | cut -c1-200)"
  else
    echo "  no fort.* file"
  fi
done

if [ "$rc" = 0 ]; then echo "MERC SIDE FILES CHECK: PASS"; else echo "MERC SIDE FILES CHECK: FAIL"; fi
echo "$P"
exit "$rc"
