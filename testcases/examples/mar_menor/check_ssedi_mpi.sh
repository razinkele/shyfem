#!/bin/bash
#------------------------------------------------------------------------
# Simple sediment (issedi = 1) on several processes against the serial
# run, byte for byte (issue #262).
#
# On several processes the sediment fields differed from the serial run
# on the nodes along the edges of the domains (bed sediment of the
# restart file up to 13 %, suspended sediment 8.7e-4 of 0.93), while
# the hydrodynamics and the inner nodes were bit-identical.  The cause:
# compute_bottom_flux (src/shyfem/simple_sedi.f90) averages the flux of
# the elements around every node and had no exchange, so a ghost node
# kept the mean of the elements its process holds; the node loop of
# simple_sedi then computed the bed sediment and the bottom concentration
# of the ghost from that flux, and the gather of the output and restart
# files (shympi_l2g_array) takes the ghost copies too, so a ghost copy
# overwrote the owner's value in the files.  The owner itself also added
# its ring in the local order, not the serial one (last bits).
#
# Cases, run serially and on each NP of NPS (default 2 4) with the METIS
# partition the model makes, from the Mar Menor STR files with an output
# line added (idtout = '1h', idtcon = '1h'):
#   write  mm_rst_ssedi_write.str: two days from rest with a uniform
#          initial concentration, restart file at the end (its last
#          record is the bed sediment, conza, written by
#          write_restart_ssedi)
#   read   mm_rst_ssedi_read.str: two more days from the last record of
#          the SERIAL write run's restart file (every run reads the same
#          file, so a difference here comes from the reading or the run
#          on NP processes, not from the restart file)
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 600 s each); the log of an NP-process run has the line
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI or a
# binary without MPI, cannot pass); the read runs say "A restart has been
# performed"; the files .hydro.shy, .conz.shy, .ssed.shy (bed sediment:
# mass, mass per area, height) and .csed.shy (sediment concentration) of
# both cases and the restart file of the write case are byte-identical
# to the serial ones; the last record of the restart file is the bed
# sediment of every node (1402 reals) and is compared on its own as well;
# the serial bed sediment is not zero everywhere (otherwise the
# comparison tests nothing); and no run leaves a file named fort.* in its
# folder (the module wrote the debug file fort.778 from every process
# at every step, issue #264).  When a file differs the largest difference
# of every variable and the number of nodes that differ are printed
# (needs shyelab and python3 with netCDF4; without them only the first
# differing byte).  The sedimt: lines of the .inf file (the totals of
# suspended and bed sediment) are compared as text with the serial ones
# (#220): same number of lines, every line identical (they were written
# by every process, over each other, with the totals of the process's
# own nodes).
#
# Usage:  ./check_ssedi_mpi.sh [NP ...]
# Needs shyfem, shypre, mpirun and python3 (with numpy) on PATH (an
# OpenMPI build).  Works in a folder made with mktemp -d under
# ${TMPDIR:-/tmp} (GRID/MM_coarse.grd is copied there and its basin is
# built there with shypre, the STR files are made there from this
# folder's), so nothing in this folder changes.  The folder is kept (its
# path is the last line).  Prints "SSEDI MPI CHECK: PASS" or "SSEDI MPI
# CHECK: FAIL" and exits 0 or 1.  Takes about 17 s for 2 and 4.
#------------------------------------------------------------------------
set -u
NPS="${*:-2 4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
for np in $NPS; do
  case "$np" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP ...] (each NP at least 2)"; exit 2 ;; esac
done
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "SSEDI MPI CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
python3 -c 'import numpy' 2> /dev/null || { echo "SSEDI MPI CHECK: FAIL (python3 has no numpy)"; exit 1; }
for f in GRID/MM_coarse.grd mm_rst_ssedi_write.str mm_rst_ssedi_read.str; do
  [ -f "$HERE/$f" ] || { echo "SSEDI MPI CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/ssedi.XXXXXX")" || exit 1
echo "ssedi mpi check: $(command -v shyfem), serial vs $NPS processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "SSEDI MPI CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse.grd > shypre.log 2>&1 ) \
  || { echo "SSEDI MPI CHECK: FAIL (shypre failed, log $P/GRID/shypre.log)"; exit 1; }
NKN="$(awk '$1 == 1 { n++ } END { print n + 0 }' "$HERE/GRID/MM_coarse.grd")"

#--- the STR files: the shipped ones with an output line
for c in write read; do
  sed "/^[[:space:]]*issedi = 1[[:space:]]*$/a\\        idtout = '1h'\\n        idtcon = '1h'" \
    "$HERE/mm_rst_ssedi_$c.str" > "$P/$c.str"
  [ "$(grep -c "^        idt\(out\|con\) = '1h'$" "$P/$c.str")" = 2 ] \
    || { echo "SSEDI MPI CHECK: FAIL (cannot add the output line to $c.str)"; exit 1; }
done

#--- runs and comparison
# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # CASE NP (NP 1: a plain run without mpirun)
  local d="$P/$1.np$2" r
  mkdir "$d" && ln -s ../GRID "$d/GRID" && cp "$P/$1.str" "$d/" || return 1
  if [ "$1" = read ]; then
    cp "$P/write.np1/mm_rst_ssedi_write.rst" "$d/" || return 1
  fi
  if [ "$2" = 1 ]; then
    ( cd "$d" && timeout 600 nice -n 10 shyfem "$1.str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && timeout 600 nice -n 10 mpirun --oversubscribe -np "$2" shyfem "$1.str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  if [ "$1" = read ] && ! grep -q "A restart has been performed" "$d/run.log"; then
    echo "  the log does not say 'A restart has been performed' ($d/run.log)"; return 1
  fi
  if [ "$2" != 1 ] && ! ranks_ok "$d/run.log" "$2"; then
    echo "  the log does not show $2 MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines,"
    echo "  expected one from each rank 0 to $(( $2 - 1 )) with $2 processes ($d/run.log)"
    return 1
  fi
  return 0
}
noside() {  # CASE NP: no fort.* debug file in the run folder (#264)
  local side
  side="$(cd "$P/$1.np$2" && ls -d fort.* 2> /dev/null)"
  [ -z "$side" ] && return 0
  fail "$1 on $2 process(es) left the side files $(echo $side)"
}
diffs() {  # SERIAL_SHY MPI_SHY: largest difference and nodes that differ, per variable
  local a="$1" b="$2" na nb
  if ! command -v shyelab > /dev/null 2>&1 || ! python3 -c 'import netCDF4' 2> /dev/null; then
    echo "    first difference: $(cmp "$a" "$b" 2>&1 | head -1)"; return
  fi
  na="${a%.shy}.nc"; nb="${b%.shy}.nc"
  ( cd "$(dirname "$a")" && shyelab -outformat nc "$(basename "$a")" > /dev/null 2>&1 && mv out.nc "$na" ) || { echo "    shyelab failed on $a"; return; }
  ( cd "$(dirname "$b")" && shyelab -outformat nc "$(basename "$b")" > /dev/null 2>&1 && mv out.nc "$nb" ) || { echo "    shyelab failed on $b"; return; }
  python3 - "$na" "$nb" <<'PY'
import sys
import numpy as np
import netCDF4
a, b = netCDF4.Dataset(sys.argv[1]), netCDF4.Dataset(sys.argv[2])
skip = {'Mesh2', 'Mesh2_face_nodes', 'Mesh2_node_x', 'Mesh2_node_y', 'level', 'total_depth', 'time'}
for v in a.variables:
    if v in skip or v not in b.variables:
        continue
    x = np.ma.filled(np.ma.asarray(a.variables[v][:], dtype=float), 0.)
    y = np.ma.filled(np.ma.asarray(b.variables[v][:], dtype=float), 0.)
    if x.shape != y.shape:
        print('    %-20s shapes differ %s %s' % (v, x.shape, y.shape))
        continue
    d = np.abs(x - y).reshape(x.shape[0], x.shape[1], -1).max(axis=2)  # time, node
    print('    %-20s largest difference %.3e (largest serial value %.3g); nodes that differ: first output %d, last %d, any %d of %d'
          % (v, d.max(), np.abs(x).max(), (d[0] > 0).sum(), (d[-1] > 0).sum(), (d.max(axis=0) > 0).sum(), d.shape[1]))
PY
}
sedrec() {  # SERIAL_RST MPI_RST: the last record (bed sediment) of both restart files
  python3 - "$1" "$2" "$NKN" <<'PY'
import struct
import sys
import numpy as np
nkn = int(sys.argv[3])
def last(path):
    b = open(path, 'rb').read()
    n = struct.unpack('<i', b[-4:])[0]
    if n != 4 * nkn or len(b) < n + 8 or struct.unpack('<i', b[-8 - n:-4 - n])[0] != n:
        sys.exit('    %s: the last record is not %d reals (bed sediment); length %d' % (path, nkn, n))
    return np.frombuffer(b[-4 - n:-4], dtype='<f4').astype(float)
x, y = last(sys.argv[1]), last(sys.argv[2])
d = np.abs(x - y)
print('    bed sediment record (conza, %d nodes): %d nodes differ, largest difference %.3e (largest serial value %.3g)'
      % (nkn, (d > 0).sum(), d.max(), np.abs(x).max()))
if d.max() > 0:
    i = int(d.argmax())
    print('    worst node (internal) %d: serial %.6g, here %.6g' % (i + 1, x[i], y[i]))
sys.exit(1 if d.max() > 0 else 0)
PY
}

for c in write read; do
  echo "=== $c"
  if ! run "$c" 1; then
    fail "$c: the serial run did not end (above)"
    [ "$c" = write ] && break
    continue
  fi
  noside "$c" 1
  files="mm_rst_ssedi_$c.hydro.shy mm_rst_ssedi_$c.conz.shy mm_rst_ssedi_$c.ssed.shy mm_rst_ssedi_$c.csed.shy"
  if [ "$c" = write ]; then
    files="$files mm_rst_ssedi_write.rst"
    # the serial restart file must end with a bed sediment that is not zero
    python3 - "$P/write.np1/mm_rst_ssedi_write.rst" "$NKN" <<'PY' || fail "write: the serial restart file has no usable bed sediment record"
import struct
import sys
import numpy as np
b, nkn = open(sys.argv[1], 'rb').read(), int(sys.argv[2])
n = struct.unpack('<i', b[-4:])[0]
if n != 4 * nkn:
    sys.exit('  last record of %s: length %d, not %d reals' % (sys.argv[1], n, nkn))
a = np.frombuffer(b[-4 - n:-4], dtype='<f4')
print('  serial bed sediment record: %d nodes, %d above zero, largest %.4g' % (nkn, (a > 0).sum(), a.max()))
sys.exit(0 if a.max() > 0 else 1)
PY
  fi
  for np in $NPS; do
    if ! run "$c" "$np"; then fail "$c: the run on $np processes did not end, or not on $np processes (above)"; continue; fi
    noside "$c" "$np"
    # the sedimt: lines of the info file, once and as in the serial run (#220)
    ia="$P/$c.np1/mm_rst_ssedi_$c.inf"; ib="$P/$c.np$np/mm_rst_ssedi_$c.inf"
    grep ' sedimt: ' "$ia" > "$P/$c.np1/sedimt.txt" 2> /dev/null
    grep ' sedimt: ' "$ib" > "$P/$c.np$np/sedimt.txt" 2> /dev/null
    if [ ! -s "$P/$c.np1/sedimt.txt" ]; then
      fail "$c: no sedimt: line in the serial info file"
    elif cmp -s "$P/$c.np1/sedimt.txt" "$P/$c.np$np/sedimt.txt"; then
      echo "  np $np  sedimt: lines of the info file: identical ($(wc -l < "$P/$c.np1/sedimt.txt") lines)"
    else
      echo "  np $np  sedimt: lines of the info file: DIFFER (serial $(wc -l < "$P/$c.np1/sedimt.txt") lines, here $(wc -l < "$P/$c.np$np/sedimt.txt"))"
      diff "$P/$c.np1/sedimt.txt" "$P/$c.np$np/sedimt.txt" | head -4 | sed 's/^/    /'
      fail "$c: the sedimt: lines of the info file differ between serial and $np processes"
    fi
    for f in $files; do
      a="$P/$c.np1/$f"; b="$P/$c.np$np/$f"
      if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$c: $f missing or empty"; continue; fi
      if cmp -s "$a" "$b"; then
        echo "  np $np  $f: byte-identical"
      else
        echo "  np $np  $f: DIFFERS"
        fail "$c: $f differs between serial and $np processes"
        if [ "${f##*.}" = rst ]; then
          echo "    first difference: $(cmp "$a" "$b" 2>&1 | head -1)"
        else
          diffs "$a" "$b"
        fi
      fi
      if [ "${f##*.}" = rst ]; then
        if sedrec "$a" "$b" > "$P/$c.np$np/sedrec.txt"; then
          echo "  np $np  restart bed sediment record: identical"
        else
          cat "$P/$c.np$np/sedrec.txt"
          fail "$c: the bed sediment record of the restart file differs between serial and $np processes"
        fi
      fi
    done
  done
done

if [ "$rc" = 0 ]; then echo "SSEDI MPI CHECK: PASS"; else echo "SSEDI MPI CHECK: FAIL"; fi
echo "$P"
exit "$rc"
