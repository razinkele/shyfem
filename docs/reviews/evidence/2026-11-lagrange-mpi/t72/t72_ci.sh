#!/bin/bash
# Task 7.2 C1/C2: check_mpi.sh in a tracked-files-only export of the work
# tree's HEAD, as the Fortran CI's mpi-build job runs it.
#   t72_ci.sh build   : export, CI's own build command, CI's steps (make init,
#                       bash check_mpi.sh 4), every output line time-stamped
#   t72_ci.sh BINDIR  : export of testcases/examples only, BINDIR first on
#                       PATH (no build), make init, bash check_mpi.sh 4
# If the work tree's check_mpi.sh differs from HEAD's, the work tree's copy
# is put into the export (said so in the log).
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1
MODE="${1:?usage: t72_ci.sh build|BINDIR}"
R=$(mktemp -d "${TMPDIR:-/tmp}/t72ci.XXXXXX") || exit 1
ts() { while IFS= read -r l; do printf '%s %s\n' "$(date +%T)" "$l"; done; }
echo "$(date '+%F %T %Z') export of $(git -C $W rev-parse --short HEAD) in $R, mode $MODE"
if [ "$MODE" = build ]; then
  git -C $W archive HEAD | tar -x -C "$R" || exit 1
else
  git -C $W archive HEAD testcases/examples | tar -x -C "$R" || exit 1
fi
if ! git -C $W diff --quiet HEAD -- testcases/examples/mar_menor/check_mpi.sh; then
  cp $W/testcases/examples/mar_menor/check_mpi.sh "$R/testcases/examples/mar_menor/" || exit 1
  echo "check_mpi.sh: the work tree's (uncommitted) copy"
fi
ls "$R/testcases/examples/mar_menor/GRID/" | tr '\n' ' '; echo
if [ "$MODE" = build ]; then
  cd "$R" || exit 1
  # CI (fortran-ci.yml, job mpi-build): make clean && make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr
  t0=$(date +%s)
  PATH=/usr/bin:$PATH nice -n 10 make clean > build-ci.log 2>&1
  PATH=/usr/bin:$PATH nice -n 10 make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr >> build-ci.log 2>&1
  brc=$?
  echo "$(date +%T) CI build rc=$brc in $(( $(date +%s) - t0 )) s; libmpi.so.40: $(ldd src/shyfem/shyfem | grep -c libmpi.so.40); bin/shyfem -> $(readlink -f bin/shyfem); netcdf linked: $(ldd src/shyfem/shyfem | grep -c netcdf)"
  [ "$brc" = 0 ] || exit 1
  BIN="$R/bin"
  export PATH="/usr/bin:$BIN:$PATH"	# the order of the CI step
else
  BIN="$MODE"
  export PATH="$BIN:/usr/bin:$PATH"
fi
echo "shyfem: $(readlink -f "$(command -v shyfem)"), shypre: $(readlink -f "$(command -v shypre)"), mpirun: $(command -v mpirun), python3: $(command -v python3)"
cd "$R/testcases/examples/mar_menor" || exit 1
make init > init.log 2>&1 || { tail -5 init.log; echo "make init failed"; exit 1; }
echo "$(date +%T) make init done; GRID/MM_geo.bas present before the gate: $([ -f GRID/MM_geo.bas ] && echo yes || echo no)"
t0=$(date +%s)
bash check_mpi.sh 4 2>&1 | ts
grc=${PIPESTATUS[0]}
echo "$(date +%T) check_mpi.sh 4: exit $grc, $(( $(date +%s) - t0 )) s"
echo "files made in GRID by the gate: $(cd GRID && ls | tr '\n' ' ')"
echo "$(date '+%F %T %Z') done ($R)"
