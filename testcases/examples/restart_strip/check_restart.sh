#!/bin/bash
#------------------------------------------------------------------------
# restart reader gate for a mesh with more nodes than elements
#
# strip.grd is a 2x3-node strip: nkn=6 > nel=4. rst_skip_record (used by
# rstinf and rst2shy) sized its 3d skip buffers (nlv+1)*nel, so the node
# records (saltv/tempv/rhov, wlnv) overran them on such a mesh.
#
#   write : 3d baroclinic run, writes strip_rst.rst (last record)
#   skip  : rstinf + rst2shy read every record through rst_skip_record
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
step rst2shy rst2shy.log rst2shy strip_rst.rst
step warm    warm.log    shyfem strip_warm.str
grep -q "A restart has been performed" warm.log \
  || { echo "FAIL warm: no restart performed"; exit 1; }
echo "PASS: restart written, skipped and re-read on an nkn > nel mesh"
