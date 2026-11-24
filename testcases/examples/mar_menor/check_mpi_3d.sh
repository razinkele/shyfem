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
#   g3d6 g3d with ireib = 6 (czdef is the roughness length of the bottom
#        friction): GOTM's bottom roughness then comes from the nodal
#        average of model_bottom_z0 (src/shyfem/turbulence.f90), which
#        had the same defect (#230); with one czdef everywhere the mean is
#        that value for any weights, so only the rounding can differ
#   g3da g3d6 with a $area section that gives the two area codes of
#        GRID/MM_geo.grd (0: 1,036 elements, 1: 1,509) different
#        roughness lengths (2.5e-3 and 2.5e-2 m): at a node between the
#        two areas the weights decide the mean, so elements counted
#        twice change the roughness itself
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 1200 s each); the log of an NP-process run has the line
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI or a
# binary without MPI, cannot pass); and the files CASE.hydro.shy and, for c41,
# mm_hyd_41.ts.shy and the extra-point file mm_hyd_41.ext of the
# NP-process run are byte-identical to the serial ones; the NP-process
# runs have the ghost check of the output gathers on (SHYFEM_GHOST_CHECK=1,
# #268): their logs must say "ghost check of the output gathers is on"
# and have no line "GHOST CHECK:" (a ghost copy out of step with its
# owner, which the files no longer show since the gathers take the
# owners' values only).  The .ext file
# holds the barotropic nodal velocity of uvtop0 (same file), which had the
# same defect (#230): with uvtopr alone fixed, the 2D velocity at the
# extra point 'inlet' (node 58) was 0.014 m/s off on 4 processes.  The
# .inf file is not compared: with the output files byte-identical, its
# global totals (total_volume and the temp and salt totals, one energy
# line) still differ in the last printed digits on several processes.
# They are diagnostics only: masscont sums over the own nodes
# (nkn_inner) of each process, and info_output('total_volume','sum',...)
# adds the partial totals of the processes, so the additions come in
# another order than in the serial sum.  When a file differs the largest
# difference of every variable is printed (needs shyelab, extelab and
# python3 with netCDF4; without them only the first differing byte).
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
    if txt.count('$name\n') != 1:
        sys.exit('cannot make %s: no single $name section in %s for gotmpa' % (dst, src))
    txt = txt.replace('$name\n', "$name\n        gotmpa = 'INPUT/gotmturb.nml'\n", 1)
if n0 != 1 or '$lagrg' in txt or "itend = '2009-01-02'" not in txt:
    sys.exit('cannot make %s from %s' % (dst, src))
open(dst, 'w').write(txt)
PY
}
mk3d g3d 1 || { echo "MPI 3D CHECK: FAIL (cannot make g3d.str)"; exit 1; }
mk3d k3d 2 || { echo "MPI 3D CHECK: FAIL (cannot make k3d.str)"; exit 1; }
sed -e 's/ireib = 5/ireib = 6/' -e 's/^        g3d$/        g3d6/' "$P/g3d.str" > "$P/g3d6.str"
grep -q 'ireib = 6' "$P/g3d6.str" && grep -q '^        g3d6$' "$P/g3d6.str" \
  || { echo "MPI 3D CHECK: FAIL (cannot make g3d6.str)"; exit 1; }
# the area codes the roughness of g3da relies on
[ "$(awk '$1 == 2 { a[$3] = 1 } END { s = ""; for (k = 0; k < 10; k++) if (k in a) s = s k; print s }' "$HERE/GRID/MM_geo.grd")" = 01 ] \
  || { echo "MPI 3D CHECK: FAIL (GRID/MM_geo.grd does not have the two area codes 0 and 1)"; exit 1; }
{ sed -e 's/^        g3d6$/        g3da/' "$P/g3d6.str"
  printf '\n$area\n        0  2.5e-3\n        1  2.5e-2\n$end\n'; } > "$P/g3da.str"
grep -q '^        g3da$' "$P/g3da.str" && grep -q '^\$area$' "$P/g3da.str" \
  || { echo "MPI 3D CHECK: FAIL (cannot make g3da.str)"; exit 1; }

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
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" && cp "$P/$1.str" "$d/" || return 1
  if [ "$2" = 1 ]; then
    ( cd "$d" && timeout 1200 nice -n 10 shyfem "$1.str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && SHYFEM_GHOST_CHECK=1 timeout 1200 nice -n 10 mpirun --oversubscribe -np "$2" shyfem "$1.str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  # NP > 1: the run must really have NP processes (an mpirun that does
  # not match the binary's MPI, or a binary without MPI, gives NP serial
  # runs that write the serial files: a check that cannot fail)
  if [ "$2" != 1 ] && ! ranks_ok "$d/run.log" "$2"; then
    echo "  the log does not show $2 MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines,"
    echo "  expected one from each rank 0 to $(( $2 - 1 )) with $2 processes ($d/run.log)"
    return 1
  fi
  if [ "$2" != 1 ] && ! grep -q 'ghost check of the output gathers is on' "$d/run.log"; then
    echo "  the log does not say 'ghost check of the output gathers is on' ($d/run.log)"
    return 1
  fi
  return 0
}
ghosts() {  # CASE NP: no ghost copy out of step in the output gathers (#268)
  local log="$P/$1.np$2/run.log" n
  n="$(grep -c '^GHOST CHECK:' "$log")"
  [ "$n" = 0 ] && return 0
  # per array: the number of gathers (records) with ghost copies that differ
  grep '^GHOST CHECK:' "$log" | grep 'ghost copies differ' \
    | sed -E 's/\): [0-9]+ ghost copies differ.*/)/' | sort | uniq -c | sed 's/^/   /' | head -20
  fail "$1 on $2 processes: $n GHOST CHECK lines, ghost copies out of step with their owners ($log)"
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

extdiffs() {  # SERIAL_EXT MPI_EXT: the split series that differ, largest difference
  local a="$1" b="$2" s
  if ! command -v extelab > /dev/null 2>&1; then
    echo "    first difference: $(cmp "$a" "$b" 2>&1 | head -1)"; return
  fi
  # extelab gets a short relative name (it crashed on a long path)
  rm -rf "$P/ext_a" "$P/ext_b"; mkdir "$P/ext_a" "$P/ext_b" || return
  cp "$a" "$P/ext_a/x.ext" && cp "$b" "$P/ext_b/x.ext" || return
  ( cd "$P/ext_a" && extelab -split x.ext > log 2>&1 ) && ( cd "$P/ext_b" && extelab -split x.ext > log 2>&1 ) \
    || { echo "    extelab failed"; return; }
  for s in "$P"/ext_a/*.[23]d.*; do
    case "$(basename "$s")" in all.*) continue ;; esac	# all columns at once
    cmp -s "$s" "$P/ext_b/$(basename "$s")" && continue
    paste "$s" "$P/ext_b/$(basename "$s")" | awk -v n="$(basename "$s")" \
      '!/^#/ { d = $2 - $4; if (d < 0) d = -d; if (d > m) { m = d; t = $1; x = $2; y = $4 } }
       END { printf "    %-12s largest difference %.4g at %s (serial %s, here %s)\n", n, m, t, x, y }'
  done
}

for c in c41 g3d k3d g3d6 g3da; do
  echo "=== $c"
  if ! run "$c" 1; then fail "$c: the serial run did not end"; continue; fi
  if ! run "$c" "$NP"; then fail "$c: the run on $NP processes did not end, or not on $NP processes (above)"; continue; fi
  ghosts "$c" "$NP"
  files="$c.hydro.shy"
  [ "$c" = c41 ] && files="mm_hyd_41.hydro.shy mm_hyd_41.ts.shy mm_hyd_41.ext"
  for f in $files; do
    a="$P/$c.np1/$f"; b="$P/$c.np$NP/$f"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$c: $f missing or empty"; continue; fi
    if cmp -s "$a" "$b"; then
      echo "  $f: byte-identical"
    elif [ "${f##*.}" = ext ]; then
      echo "  $f: DIFFERS"; extdiffs "$a" "$b"; fail "$c: $f differs between serial and $NP processes"
    else
      echo "  $f: DIFFERS"; diffs "$a" "$b"; fail "$c: $f differs between serial and $NP processes"
    fi
  done
done

# the $area section of g3da must have changed the serial run (otherwise
# g3da is g3d6 again and tests nothing more)
a="$P/g3d6.np1/g3d6.hydro.shy"; b="$P/g3da.np1/g3da.hydro.shy"
if [ -s "$a" ] && [ -s "$b" ]; then
  if cmp -s "$a" "$b"; then fail "g3da: the serial run equals g3d6's (the \$area roughness had no effect)"
  else echo "  g3da serial differs from g3d6 serial (the \$area roughness acts)"; fi
fi

if [ "$rc" = 0 ]; then echo "MPI 3D CHECK: PASS"; else echo "MPI 3D CHECK: FAIL"; fi
echo "$P"
exit "$rc"
