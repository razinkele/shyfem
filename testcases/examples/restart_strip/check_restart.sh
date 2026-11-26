#!/bin/bash
#------------------------------------------------------------------------
# restart reader gate for a mesh with more nodes than elements
#
# strip.grd is a 2x3-node strip: nkn=6 > nel=4. rst_skip_record (used by
# rstinf and rst2shy) sized its 3d skip buffers (nlv+1)*nel, so the node
# records (saltv/tempv/rhov, wlnv) overran them on such a mesh.
#
#   write : 3d baroclinic run, writes strip_rst.rst (last record)
#   skip  : rstinf reads every record through rst_skip_record
#   conv  : rst2shy (restart + basin file) converts the restart file to
#           .hydro.shy and .ts.shy. rst2shy exits non-zero on an error
#           (#327; it exited 0 before). The gate removes any old
#           strip_rst.*.shy first (the write run makes strip_rst.hydro.shy
#           under the same name), then requires both files to exist and be
#           non-empty, no "error stop" in the log, and the same number of
#           records read as rstinf
#   err   : rst2shy given only the restart file (no basin file) must exit
#           7 with "rst_init: missing files" (it exited 0 before #327)
#   warm  : a second run restarts from the file
#
# The overrun only faults reliably in a bounds-checked build:
#   PATH=/usr/bin:$PATH make fem BOUNDS=true
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
BIN="$(cd "$HERE/../../.." && pwd)/bin"
export PATH=$BIN:/usr/bin:$PATH

step() {  # name, log, command...
  local name=$1 log=$2; shift 2
  if timeout 300 "$@" > "$log" 2>&1 && ! grep -q "Fortran runtime error" "$log"; then
    echo "ok   $name"
  else
    echo "FAIL $name (see $log)"; grep -m1 "Fortran runtime error" "$log"; exit 1
  fi
}

step shypre  shypre.log  shypre strip.grd
step write   write.log   shyfem strip_rst.str
step rstinf  rstinf.log  rstinf strip_rst.rst
rm -f strip_rst.hydro.shy strip_rst.ts.shy
step rst2shy rst2shy.log rst2shy strip_rst.rst strip.bas
nrec() { sed -n 's/.*Number of records read: *\([0-9][0-9]*\).*/\1/p' "$1" | tail -1; }
! grep -qi "error stop" rst2shy.log \
  || { echo "FAIL rst2shy: $(grep -i -m1 'error stop' rst2shy.log)"; exit 1; }
for f in strip_rst.hydro.shy strip_rst.ts.shy; do
  [ -s "$f" ] || { echo "FAIL rst2shy: $f missing or empty (see rst2shy.log)"; exit 1; }
done
n_inf=$(nrec rstinf.log); n_shy=$(nrec rst2shy.log)
{ [ -n "$n_shy" ] && [ "$n_shy" -ge 1 ] && [ "$n_shy" = "$n_inf" ]; } \
  || { echo "FAIL rst2shy: records read ${n_shy:-none}, rstinf read ${n_inf:-none}"; exit 1; }
echo "ok   rst2shy converted $n_shy record(s) to .hydro.shy and .ts.shy"
rm -f rst2shy_err.log
timeout 300 rst2shy strip_rst.rst > rst2shy_err.log 2>&1; rc=$?
{ [ "$rc" -eq 7 ] && grep -q "rst_init: missing files" rst2shy_err.log; } \
  || { echo "FAIL rst2shy without a basin file: exit $rc (want 7 + rst_init: missing files)"; exit 1; }
echo "ok   rst2shy without a basin file exits $rc"
step warm    warm.log    shyfem strip_warm.str
grep -q "A restart has been performed" warm.log \
  || { echo "FAIL warm: no restart performed"; exit 1; }
echo "PASS: restart written, skipped, converted and re-read on an nkn > nel mesh"
