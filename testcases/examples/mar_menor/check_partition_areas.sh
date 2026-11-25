#!/bin/bash
#------------------------------------------------------------------------
# check_partition leaves the element areas of the master as they were
# (issue #290).
#
# At the start of a run on several processes the model partitions the
# basin with METIS (handle_partition, src/utils/shympi/mpi_basin.f90) and
# checks the partition with check_partition.  That works on the basin of
# the master alone: for every domain it replaces the basin by the domain
# (make_new_basin) and then puts the old one back (restore_old_basin).
# make_new_basin overwrote the element areas iarv and the node areas
# iarnv of the master, and restore_old_basin gave back neither: the node
# areas were repaired at the end of check_connections, the element areas
# not, so after check_partition the master held other element areas than
# the other processes (505 of the 2545 elements of MM_coarse on 4
# processes).  Nothing read them since #279, but the partitioner's element
# partition (epart = iarv) was wrong on the master.
#
# The test hook SHYFEM_PARTITION_CHECK makes every process print, right
# after check_partition,
#   PARTITION CHECK: process ID elements changed N of NEL
# with N the number of elements whose area check_partition changed.  Each
# of the NP processes must print one line, with N = 0.  A shyfem without
# the hook prints no line and fails the test too.
#
# Usage:  ./check_partition_areas.sh [NP]      (default 4, at least 2)
# Needs shyfem and mpirun on PATH (an OpenMPI build); `make init` first.
# Works in a folder from mktemp -d under ${TMPDIR:-/tmp} (INPUT and GRID
# linked, the run cut to 10 minutes: the partition comes before the first
# step); nothing in this folder changes.  The folder is removed on success
# and kept on failure.  PASS line: "PARTITION AREAS: PASS"
#------------------------------------------------------------------------
NP="${1:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
case "$NP" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP] (NP at least 2)"; exit 2 ;; esac
for t in shyfem mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "PARTITION AREAS: FAIL ($t is not on PATH)"; exit 1; }
done
if [ ! -f "$HERE/GRID/MM_coarse.bas" ]; then
  echo "PARTITION AREAS: FAIL (run make init first: GRID/MM_coarse.bas)"
  exit 1
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/partition_areas.XXXXXX")" || exit 1
ln -s "$HERE/INPUT" "$WORK/INPUT" && ln -s "$HERE/GRID" "$WORK/GRID" || { rm -rf "$WORK"; exit 1; }
sed -e "s/itend *= *'2009-01-05'/itend = '2009-01-01::00:10:00'/" "$HERE/mm_hyd_00.str" > "$WORK/t.str"
grep -q "itend = '2009-01-01::00:10:00'" "$WORK/t.str" \
  || { echo "PARTITION AREAS: FAIL (cannot shorten the run)"; rm -rf "$WORK"; exit 1; }
( cd "$WORK" && SHYFEM_PARTITION_CHECK=1 timeout 300 nice -n 10 \
    mpirun --oversubscribe -np "$NP" shyfem t.str < /dev/null > run.log 2>&1 )
r=$?
fail=0
if [ "$r" != 0 ] || ! grep -q "simulation end" "$WORK/run.log"; then
  tail -3 "$WORK/run.log"; echo "  exit code $r"; fail=1
fi
grep 'PARTITION CHECK:' "$WORK/run.log"
n="$(grep -c 'PARTITION CHECK:' "$WORK/run.log")"
if [ "$n" != "$NP" ]; then
  echo "  $n PARTITION CHECK lines, $NP expected (one per process)"; fail=1
fi
ok="$(grep 'PARTITION CHECK:' "$WORK/run.log" | awk '$7 == 0' | awk '{print $4}' | sort -un | tr '\n' ' ')"
want="$(seq 0 $((NP-1)) | tr '\n' ' ')"
if [ "$ok" != "$want" ]; then
  echo "  processes with no element changed: [${ok}] expected [${want}]"; fail=1
fi
if [ "$fail" = 0 ]; then
  echo "PARTITION AREAS: PASS"
  rm -rf "$WORK"
else
  echo "PARTITION AREAS: FAIL (kept in $WORK)"
  exit 1
fi
