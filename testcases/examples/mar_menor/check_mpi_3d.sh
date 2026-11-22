#!/bin/bash
#------------------------------------------------------------------------
# 3D runs with a turbulence scheme: serial against NP processes, byte for
# byte (issue #230).
#
# On several processes a 3D run with GOTM (iturb = 1) or k-epsilon
# (iturb = 2) differed from the serial run (closed basin: 1.1e-2 m/s in
# the current on 4 processes; with the open boundary of mm_hyd_41: 4.8 psu
# of salinity at the first output), while iturb = 0 did not.  The cause:
# uvtopr (src/shyfem/transforms.f90) averages the element velocities of
# every node into uprv/vprv, which give the turbulence schemes their shear,
# and on a node partition it added the partial sums of the processes that
# hold a node as a ghost to the owner's sums, which already hold every
# element around the node, so shared elements counted twice.
#
# Cases, each one day (2009-01-01 to 2009-01-02), run serially and on NP
# processes (default 4) with the METIS partition the model makes:
#   c41  mm_hyd_41.str without its tilt lines (ztilt, ktilt): 19 levels,
#        GOTM, the open level boundary with salinity and temperature
#        files, the river, heat flux, rain and wind
#   g3d  mm_lgr.str without its particle section ($lagrg), with the
#        19 levels of mm_hyd_41.str, GOTM (iturb = 1, gotmturb.nml of
#        mm_hyd_41.str): a closed 3D basin, wind only
#   k3d  the same with k-epsilon (iturb = 2)
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 1200 s each), and the files CASE.hydro.shy and, for c41,
# mm_hyd_41.ts.shy of the NP-process run are byte-identical to the serial
# ones.  When a file differs the largest difference of every variable is
# printed (needs shyelab on PATH and python3 with netCDF4; without them
# only the first differing byte).
#
# Usage:  ./check_mpi_3d.sh [NP]
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build).
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp} (the basins
# are built there from GRID/MM_coarse_smooth.grd and GRID/MM_geo.grd,
# INPUT is linked, the STR files are made there from this folder's), so
# nothing in this folder changes.  The folder is kept (its path is the
# last line).  Prints "MPI 3D CHECK: PASS" or "MPI 3D CHECK: FAIL" and
# exits 0 or 1.
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
case "$NP" in ''|*[!0-9]*) echo "usage: $0 [NP]"; exit 2 ;; esac
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "MPI 3D CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse_smooth.grd GRID/MM_geo.grd mm_hyd_41.str mm_lgr.str INPUT/gotmturb.nml; do
  [ -f "$HERE/$f" ] || { echo "MPI 3D CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/mpi3d.XXXXXX")" || exit 1
echo "mpi 3d check: $(command -v shyfem), serial vs $NP processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "MPI 3D CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse_smooth.grd" "$HERE/GRID/MM_geo.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse_smooth.grd > shypre1.log 2>&1 && shypre -noopti MM_geo.grd > shypre2.log 2>&1 ) \
  || { echo "MPI 3D CHECK: FAIL (shypre failed, logs in $P/GRID)"; exit 1; }

#--- the STR files
sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
    -e "s/itend = '[^']*'/itend = '2009-01-02'/" "$HERE/mm_hyd_41.str" > "$P/c41.str"
grep -q 'ktilt\|ztilt' "$P/c41.str" && { echo "MPI 3D CHECK: FAIL (tilt lines left in c41.str)"; exit 1; }
mk3d() {  # NAME ITURB
  python3 - "$HERE/mm_lgr.str" "$HERE/mm_hyd_41.str" "$P/$1.str" "$1" "$2" <<'PY' || return 1
import re
import sys
src, l41, dst, name, iturb = sys.argv[1:6]
levels = re.search(r'(\$levels.*?\$end\n)', open(l41).read(), re.S).group(1)
out, skip, intitle, nt = [], False, False, 0
for ln in open(src).read().splitlines(True):
    s = ln.strip()
    if s.startswith('$lagrg'):
        skip = True
        continue
    if skip:
        skip = not s.startswith('$end')
        continue
    if s.startswith('$title'):
        intitle, nt = True, 0
    elif intitle:
        nt += 1
        if nt == 2:
            ln = '        %s\n' % name          # the run name
        if s.startswith('$end'):
            intitle = False
    out.append(re.sub(r"itend = '[^']*'", "itend = '2009-01-02'", ln))
txt = ''.join(out)
n0 = txt.count('$para\n')
txt = txt.replace('$para\n', '$para\n        iturb = %s\n' % iturb, 1)
txt = re.sub(r'(\$para.*?\$end\n)', lambda m: m.group(1) + '\n' + levels, txt, count=1, flags=re.S)
if iturb == '1':
    txt = txt.replace('$name\n', "$name\n        gotmpa = 'INPUT/gotmturb.nml'\n", 1)
if n0 != 1 or '$lagrg' in txt or "itend = '2009-01-02'" not in txt:
    sys.exit('cannot make %s from %s' % (dst, src))
open(dst, 'w').write(txt)
PY
}
mk3d g3d 1 || { echo "MPI 3D CHECK: FAIL (cannot make g3d.str)"; exit 1; }
mk3d k3d 2 || { echo "MPI 3D CHECK: FAIL (cannot make k3d.str)"; exit 1; }

#--- runs and comparison
run() {  # CASE NP (NP 1: a plain run without mpirun)
  local d="$P/$1.np$2" r
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" && cp "$P/$1.str" "$d/" || return 1
  if [ "$2" = 1 ]; then
    ( cd "$d" && timeout 1200 nice -n 10 shyfem "$1.str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && timeout 1200 nice -n 10 mpirun --oversubscribe -np "$2" shyfem "$1.str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" = 0 ] && grep -q "simulation end" "$d/run.log"; then return 0; fi
  tail -3 "$d/run.log"; echo "  exit code $r"; return 1
}
diffs() {  # SERIAL_SHY MPI_SHY: largest difference per variable
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
    x = np.ma.masked_invalid(np.ma.asarray(a.variables[v][:], dtype=float))
    y = np.ma.masked_invalid(np.ma.asarray(b.variables[v][:], dtype=float))
    if x.shape != y.shape:
        print('    %-12s shapes differ %s %s' % (v, x.shape, y.shape))
        continue
    d = np.abs(x - y)
    per = [float(d[t].max()) if d[t].count() else 0.0 for t in range(d.shape[0])]
    cnt = [int((d[t] > 0.1).sum()) for t in range(d.shape[0])]
    print('    %-12s largest difference: first output %.3e, last %.3e, any %.3e; values off by > 0.1: first %d, last %d (of %d); largest serial value %.3g'
          % (v, per[0], per[-1], max(per), cnt[0], cnt[-1], d[0].count(), float(np.abs(x).max())))
PY
}

for c in c41 g3d k3d; do
  echo "=== $c"
  if ! run "$c" 1; then fail "$c: the serial run did not end"; continue; fi
  if ! run "$c" "$NP"; then fail "$c: the run on $NP processes did not end"; continue; fi
  files="$c.hydro.shy"
  [ "$c" = c41 ] && files="mm_hyd_41.hydro.shy mm_hyd_41.ts.shy"
  for f in $files; do
    a="$P/$c.np1/$f"; b="$P/$c.np$NP/$f"
    if [ ! -f "$a" ] || [ ! -f "$b" ]; then fail "$c: $f missing"; continue; fi
    if cmp -s "$a" "$b"; then
      echo "  $f: byte-identical"
    else
      echo "  $f: DIFFERS"; diffs "$a" "$b"; fail "$c: $f differs between serial and $NP processes"
    fi
  done
done

if [ "$rc" = 0 ]; then echo "MPI 3D CHECK: PASS"; else echo "MPI 3D CHECK: FAIL"; fi
echo "$P"
exit "$rc"
