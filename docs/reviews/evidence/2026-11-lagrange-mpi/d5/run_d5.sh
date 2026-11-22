#!/bin/bash
# run_d5.sh [COMMIT] : spec section 7, case 4 (Task 6.1, ruling D5) from scratch
#
# Case B on 4 processes with the given partition of d5_partition.py
# (design "second"), in a fresh scratch copy of the test folder at COMMIT
# (default HEAD of this repository), with the binary of this checkout on
# PATH (bin/ of the repository first; build it first).  Steps:
#   1. git archive of testcases/examples/mar_menor at COMMIT into a folder
#      made with mktemp -d under ${TMPDIR:-/tmp}; GRID/MM_geo.bas (not
#      tracked) is built there with shypre -noopti MM_geo.grd
#   2. d5_partition.py second GRID/MM_coarse.4.node.grd GRID/MM_coarse.grd
#      GRID/part_second.grd   (node type = rank + 1)
#   3. (cd GRID && shypre -partition part_second.grd MM_coarse.grd): the
#      partition goes into GRID/MM_coarse.bas of the copy only
#   4. LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr_b 4 ids  (must PASS; the MPI log
#      must say "using these partitiones" and hold the line "lgr left the
#      basin: particles 595, from an element whose main owner is another
#      process: M" with M > 0)
#   5. d5_count.py on the 4-process dump (must give the same M)
# The copy is kept (its path is printed); nothing in the work tree is touched.
# part_first.grd and part_second.grd are the two partition files as made on
# 2026-11-22 (step 2 writes part_second.grd again; the first design stops
# the hydrodynamics at start-up, issue #238, see setnod_first.txt).
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1
W="$(git -C "$EV" rev-parse --show-toplevel)" || { echo "not inside a git checkout"; exit 1; }
COMMIT="${1:-HEAD}"
export PATH=$W/bin:/usr/bin:$PATH
R=$(mktemp -d "${TMPDIR:-/tmp}/d5run.XXXXXX") || exit 1
echo "$(date '+%F %T %Z') d5: commit $(git -C "$W" rev-parse --short "$COMMIT"), binary $(readlink -f "$(command -v shyfem)"), in $R"
git -C "$W" archive "$COMMIT" testcases/examples/mar_menor | tar -x -C "$R" --strip-components=2 || exit 1
D=$R/mar_menor
cd "$D/GRID" || exit 1
shypre -noopti MM_geo.grd > shypre_geo.log 2>&1 || { echo "shypre failed on MM_geo.grd"; exit 1; }
python3 "$EV/d5_partition.py" second MM_coarse.4.node.grd MM_coarse.grd part_second.grd | tail -4 || exit 1
shypre -partition part_second.grd MM_coarse.grd > shypre_second.log 2>&1 || { echo "shypre failed"; exit 1; }
grep -q 'reading partitioning file part_second.grd' shypre_second.log || { echo "shypre did not read the partition"; exit 1; }
cd "$D" || exit 1
LGR_LEVDBG=3 nice -n 19 bash check_lgr_mpi.sh mm_lgr_b 4 ids > d5_ids.log 2>&1; rc=$?
echo "ids: exit $rc: $(grep 'LGR GATE' d5_ids.log | tail -1)"
echo "partition: $(grep -E 'partitiones contained in basin|using these partitiones|we will do partitioning' mm_lgr_b.np4.log | tr -s ' ' | tr '\n' ';')"
grep 'lgr left the basin' mm_lgr_b.np4.log
python3 "$EV/d5_count.py" mm_lgr_b.np4.dbg | head -1
echo "$(date '+%F %T %Z') d5 done ($R)"
exit $rc
