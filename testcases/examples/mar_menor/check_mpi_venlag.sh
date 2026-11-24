#!/bin/bash
#------------------------------------------------------------------------
# venlag_assim (Venice lagoon, 3D, one $assimil section) serial against NP
# processes, byte for byte (issue #263).
#
# On 4 processes venlag_assim differed from the serial run in its last
# hour (salinity 2.0e-4, temperature 9.4e-5, current 6.3e-6 m/s, water
# level 2.1e-7 m) although venlag_smoke, the same STR without $assimil,
# was byte-identical.  The cause was not the assimilation: the scalar
# transport (conz3d_omp, src/shyfem/concentration_omp.f90) adds the
# contributions of the elements around a node in double precision, colour
# by colour (the independent element subsets of src/shyfem/subset.f90),
# and each process coloured its own part of the mesh, so the elements of
# a node came in another order than in the serial run.  The sums then
# differ in the last bits at every step; the cast to single precision
# hides that nearly always, but at 05:03:44 the salinity of node 1396
# (14.5 km from the observation) rounded to the next value, and the
# difference spread from there.  Any 3D or 2D run with scalar transport
# can meet such a rounding by chance; venlag_assim does in its 6 hours.
# The assimilation only changes the state enough for it to happen there.
#
# The case: testcases/examples/venice_lagoon/venlag_assim.str as it is
# (2014-08-01 00:00 to 06:00, 17 levels, GOTM, heat flux, evaporation,
# three tidal inlets, one temperature station nudged in at layer 1),
# run serially and on NP processes (default 4) with the METIS partition
# the model makes.  About 75 s serially and 21 s on 4 processes on the
# development machine.
# Required: both runs end (exit code 0 and "simulation end" in the log,
# timeout 1200 s each); the serial log reports the observation read
# ("assimilation observations read:"), so that the $assimil section is
# active; the log of the NP-process run has the line "shympi initialized:
# ID NP" once from each rank 0 to NP-1 (so that NP serial runs, from an
# mpirun that does not match the binary's MPI or a binary without MPI,
# cannot pass); and venlag_assim.hydro.shy, venlag_assim.ts.shy and the
# extra-point file venlag_assim.ext of the NP-process run are
# byte-identical to the serial ones.  When a .shy file differs the largest
# difference of every variable is printed (needs shyelab and python3 with
# netCDF4; without them only the first differing byte).
#
# Usage:  ./check_mpi_venlag.sh [NP]
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build).
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp} (the basin is
# built there from ../venice_lagoon/GRID/venlag62.grd, INPUT and the
# observation files are copied), so nothing in the source folders
# changes.  The folder is kept (its path is the last line).  Prints
# "MPI VENLAG CHECK: PASS" or "MPI VENLAG CHECK: FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
VEN="$(cd "$HERE/../venice_lagoon" && pwd)" || { echo "MPI VENLAG CHECK: FAIL (no ../venice_lagoon)"; exit 1; }
case "$NP" in ''|*[!0-9]*) echo "usage: $0 [NP]"; exit 2 ;; esac
[ "$NP" -ge 2 ] || { echo "usage: $0 [NP] with NP >= 2"; exit 2; }
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "MPI VENLAG CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
CASE=venlag_assim
for f in GRID/venlag62.grd $CASE.str venlag_assim_coords.dat venlag_assim_obs.dat \
         INPUT/gotmturb.nml INPUT/wind_lightBora.dat INPUT/heat_idealSummer.dat; do
  [ -f "$VEN/$f" ] || { echo "MPI VENLAG CHECK: FAIL (missing $VEN/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/mpivenlag.XXXXXX")" || exit 1
echo "mpi venlag check: $(command -v shyfem), $CASE serial vs $NP processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "MPI VENLAG CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" "$P/INPUT" && cp "$VEN/GRID/venlag62.grd" "$P/GRID/" \
  && cp "$VEN"/INPUT/gotmturb.nml "$VEN"/INPUT/wind_lightBora.dat "$VEN"/INPUT/heat_idealSummer.dat "$P/INPUT/" \
  || exit 1
( cd "$P/GRID" && shypre -silent venlag62.grd > shypre.log 2>&1 ) \
  || { echo "MPI VENLAG CHECK: FAIL (shypre failed, log in $P/GRID)"; exit 1; }

# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # NP (1: a plain run without mpirun)
  local d="$P/np$1" r t0
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s ../INPUT "$d/INPUT" \
    && cp "$VEN/$CASE.str" "$VEN/venlag_assim_coords.dat" "$VEN/venlag_assim_obs.dat" "$d/" || return 1
  t0=$(date +%s)
  if [ "$1" = 1 ]; then
    ( cd "$d" && timeout 1200 nice -n 10 shyfem "$CASE.str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && timeout 1200 nice -n 10 mpirun --oversubscribe -np "$1" shyfem "$CASE.str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  echo "  np $1: $(( $(date +%s) - t0 )) s"
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  if ! grep -q "assimilation observations read:" "$d/run.log"; then
    echo "  the log does not report the assimilation observations ($d/run.log)"; return 1
  fi
  # NP > 1: the run must really have NP processes (an mpirun that does
  # not match the binary's MPI, or a binary without MPI, gives NP serial
  # runs that write the serial files: a check that cannot fail)
  if [ "$1" != 1 ] && ! ranks_ok "$d/run.log" "$1"; then
    echo "  the log does not show $1 MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines,"
    echo "  expected one from each rank 0 to $(( $1 - 1 )) with $1 processes ($d/run.log)"
    return 1
  fi
  return 0
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
    first = next((t + 1 for t in range(len(per)) if per[t] > 0), None)
    print('    %-12s largest difference %.3e, at the last output %.3e, first differing output %s of %d'
          % (v, max(per), per[-1], 'none' if first is None else first, len(per)))
PY
}

if ! run 1; then
  fail "the serial run did not end, or its assimilation is not active (above)"
elif ! run "$NP"; then
  fail "the run on $NP processes did not end, or not on $NP processes (above)"
else
  for f in $CASE.hydro.shy $CASE.ts.shy $CASE.ext; do
    a="$P/np1/$f"; b="$P/np$NP/$f"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$f missing or empty"; continue; fi
    if cmp -s "$a" "$b"; then
      echo "  $f: byte-identical"
    elif [ "${f##*.}" = shy ]; then
      echo "  $f: DIFFERS"; diffs "$a" "$b"; fail "$f differs between serial and $NP processes"
    else
      echo "  $f: DIFFERS, first difference: $(cmp "$a" "$b" 2>&1 | head -1)"
      fail "$f differs between serial and $NP processes"
    fi
  done
fi

if [ "$rc" = 0 ]; then echo "MPI VENLAG CHECK: PASS"; else echo "MPI VENLAG CHECK: FAIL"; fi
echo "$P"
exit "$rc"
