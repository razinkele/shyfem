#!/bin/bash
#------------------------------------------------------------------------
# The partition files of a multi-process run are the same at every run
# (issue #279).
#
# At the start of a run on several processes the model partitions the
# basin with METIS and writes partition.N.node.grd, partition.N.elem.grd
# (and partition.N.txt).  Nothing reads the files, but they were not
# reproducible: every process wrote the same file at once, and the
# element partition of the master was not the one of the other processes
# (check_partition works on the basin of the master and leaves the
# element areas there different), so the file held whatever the last
# writer left.  With mm_hyd_00 on 4 processes 10 runs gave 4 different
# partition.4.elem.grd (md5), the node partition used by the model was
# always the same.
#
# The test runs the case K times (default 12) in fresh folders, with
# the run cut to one hour, and requires that the md5 sum of every
# partition.* file is the same in all runs, that the files exist, and
# that the element partition is the one of METIS (balanced: each domain
# holds between 90 and 110 percent of nel/NP elements as owner).
#
# Choice of K: before the fix 18 runs gave the file contents with the
# relative frequencies 0.56, 0.33, 0.06, 0.06, so the chance that K runs
# of the unfixed model all give the same file is about 0.56^K; for K = 12
# that is about 1e-3 (K = 10: 3e-3).  A fixed model passes every time.
#
# Usage:  ./check_partition_file.sh [K [NP]]
# Needs shyfem and mpirun on PATH (an OpenMPI build); `make init` first.
# The runs are made in a folder from mktemp -d under ${TMPDIR:-/tmp},
# INPUT and GRID are linked, nothing in this folder changes.  The folder
# is removed on success and kept on failure.
# PASS line: "PARTITION FILE: PASS"
#------------------------------------------------------------------------

K=${1:-12}
NP=${2:-4}
HERE=$(cd "$(dirname "$0")" && pwd)
STR=mm_hyd_00.str
ELEM_TOL_LOW=90
ELEM_TOL_HIGH=110

if [ ! -f "$HERE/GRID/MM_coarse.bas" ]; then
  echo "PARTITION FILE: FAIL (run make init first: GRID/MM_coarse.bas)"
  exit 1
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/partition_file.XXXXXX") || exit 1
fail=0

for i in $(seq 1 "$K"); do
  d=$WORK/run$i
  mkdir "$d"
  ln -s "$HERE/INPUT" "$d/INPUT"
  ln -s "$HERE/GRID" "$d/GRID"
  # one hour of 300 s steps: the partition is written before the first step
  sed -e "s/itend *= *'2009-01-05'/itend = '2009-01-01::01:00:00'/" \
      "$HERE/$STR" > "$d/$STR"
  if ! grep -q "2009-01-01::01:00:00" "$d/$STR"; then
    echo "PARTITION FILE: FAIL (cannot shorten the run: itend not found)"
    exit 1
  fi
  ( cd "$d" && timeout 300 mpirun --oversubscribe -np "$NP" shyfem "$STR" \
      > run.log 2>&1 )
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "run $i: exit code $rc (see $d/run.log)"
    fail=1
  fi
done

nfiles=0
for f in "partition.$NP.node.grd" "partition.$NP.elem.grd" "partition.$NP.txt"; do
  n=$(for i in $(seq 1 "$K"); do
        [ -f "$WORK/run$i/$f" ] && md5sum < "$WORK/run$i/$f"
      done | sort | uniq -c | wc -l)
  have=$(for i in $(seq 1 "$K"); do [ -f "$WORK/run$i/$f" ] && echo x; done | wc -l)
  echo "$f: present in $have of $K runs, $n distinct md5"
  if [ "$have" -ne "$K" ]; then
    fail=1
  fi
  if [ "$n" -ne 1 ]; then
    fail=1
  fi
  nfiles=$((nfiles+1))
done

# the element partition is the one of METIS: ownership counts per domain
# (area is the third column of an element line, type 2), nel read from the
# same file
f=$WORK/run1/partition.$NP.elem.grd
if [ -f "$f" ]; then
  awk -v np="$NP" -v lo="$ELEM_TOL_LOW" -v hi="$ELEM_TOL_HIGH" '
    $1 == 2 { nel++; cnt[$3]++ }
    END {
      bad = 0
      for (a = 1; a <= np; a++) {
        pct = 100.0 * cnt[a] / (nel / np)
        printf "  domain %d: %d elements (%.1f percent of nel/NP)\n", a, cnt[a], pct
        if (pct < lo || pct > hi) bad = 1
      }
      exit bad
    }' "$f" || { echo "element partition is not balanced"; fail=1; }
fi

if [ $fail -eq 0 ]; then
  echo "PARTITION FILE: PASS ($K runs, NP=$NP)"
  rm -rf "$WORK"
  exit 0
fi
echo "PARTITION FILE: FAIL (runs kept in $WORK)"
exit 1
