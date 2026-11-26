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
#   diff  : rstinf of two files exits 0 when no record differs and 1 when
#           one does (#332; it exited 0 in both cases): the file against
#           a copy, and against a copy whose first level depth (hlv(1) =
#           2.0, at byte 76: the first value of the record after the 4
#           header records) has its low-order byte changed. rstinf with
#           an unknown option exits 7 (#332; it exited 0), with -h and
#           --help 0 and the help (--help was an unknown option)
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
off=76
{ [ "$(od -An -tu4 -j72 -N4 strip_rst.rst | tr -d ' ')" = 12 ] \
  && [ "$(od -An -tx1 -j$off -N4 strip_rst.rst | tr -d ' ')" = 00000040 ]; } \
  || { echo "FAIL rstinf diff: strip_rst.rst has no hlv(1) = 2.0 at byte $off"; exit 1; }
rm -f strip_same.rst strip_diff.rst rstinf_same.log rstinf_diff.log
cp strip_rst.rst strip_same.rst && cp strip_rst.rst strip_diff.rst \
  && printf '\001' | dd of=strip_diff.rst bs=1 seek=$off count=1 conv=notrunc 2> /dev/null \
  || { echo "FAIL rstinf diff: cannot make the copies"; exit 1; }
timeout 300 rstinf strip_rst.rst strip_same.rst > rstinf_same.log 2>&1; rc=$?
{ [ "$rc" -eq 0 ] && grep -q 'Differences found: *0$' rstinf_same.log; } \
  || { echo "FAIL rstinf diff of a copy: exit $rc (want 0 + Differences found: 0)"; exit 1; }
timeout 300 rstinf strip_rst.rst strip_diff.rst > rstinf_diff.log 2>&1; rc=$?
{ [ "$rc" -eq 1 ] && grep -q 'records are different: hlv ' rstinf_diff.log \
  && grep -q 'Differences found: *1$' rstinf_diff.log; } \
  || { echo "FAIL rstinf diff of a changed copy: exit $rc (want 1 + hlv differs, Differences found: 1)"; exit 1; }
echo "ok   rstinf diff exits 0 for a copy, $rc for a copy with one byte changed"
rm -f rstinf_bogus.log rstinf_help.log
timeout 300 rstinf --bogus strip_rst.rst > rstinf_bogus.log 2>&1; rc=$?
{ [ "$rc" -eq 7 ] && grep -q -- 'no such option: -bogus' rstinf_bogus.log; } \
  || { echo "FAIL rstinf --bogus: exit $rc (want 7 + no such option: -bogus)"; exit 1; }
for h in -h --help; do
  timeout 300 rstinf $h > rstinf_help.log 2>&1; rc_h=$?
  { [ "$rc_h" -eq 0 ] && grep -q 'Usage: rstinf' rstinf_help.log \
    && ! grep -q 'no such option' rstinf_help.log; } \
    || { echo "FAIL rstinf $h: exit $rc_h (want 0 + Usage: rstinf, no 'no such option')"; exit 1; }
done
echo "ok   rstinf --bogus exits $rc, rstinf -h and --help exit $rc_h"
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
