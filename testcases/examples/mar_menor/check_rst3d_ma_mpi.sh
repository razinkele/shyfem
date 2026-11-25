#!/bin/bash
#------------------------------------------------------------------------
# A 3D Munk-Anderson restart read on several processes, with the closure
# evaluated at set-up on the restart state (issue #283, part (2)).
#
# Since #283 handle_gotm_init (src/shyfem/turbulence.f90) calls
# munk_anderson_shell at set-up when iturb = 3, so that step 1 uses the
# closure's mixing and not GOTM's 1e-6.  After a restart the closure is
# then evaluated on the state read from the restart file, on every node
# of every process (ghost nodes included, from their own copies of the
# velocities and densities), with one collective reduction (the n2max
# line of the info file).  This check runs that path on several
# processes and requires the same results as serially.
#
# Case, from mm_hyd_41.str without its tilt lines (ztilt, ktilt; tilting
# stops on several processes, #216): Munk-Anderson (iturb = 3) with
# vistur = 1.e-2, diftur = 1.e-3 (with the defaults 0/0 Munk-Anderson
# gives no mixing and nothing would be tested), the 19 levels of
# mm_hyd_41.str (on 4 processes the process in the lagoon has 7),
# temperature and salinity, the open level boundary with salinity and
# temperature files, the river, heat flux, rain and wind:
#   write  2009-01-01 00:00 to 06:00 from rest, serially, restart file
#          at the end (idtrst = -1): six hours of forced, stratified flow
#   read   from the last record of that file to 12:00, serially and on
#          each NP of the arguments (default 4)
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 600 s each); the log of an NP-process run has the line
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI or a
# binary without MPI, cannot pass) and "A restart has been performed"
# from every rank; the NP-process runs have the ghost check of the
# output gathers on (SHYFEM_GHOST_CHECK=1, #268) and no line
# "GHOST CHECK:"; in every NP-process read a process has fewer levels
# than the basin; the info file of the serial read has one n2max line
# more than the read has time steps (the closure was evaluated at
# set-up as well as at every step) and the first of them, at set-up, has
# n2max > 0 (the restart state is stratified, so the closure does not
# return the constants vistur/diftur there: otherwise the case would
# not test the evaluation on the restart state); and the files
# .hydro.shy, .ts.shy, .fvl.shy and .ext of every NP-process read are
# byte-identical to those of the serial read.
# Before #283 the closure was not evaluated at set-up, so the n2max
# requirement fails there (the reads themselves end and agree).
#
# Usage:  ./check_rst3d_ma_mpi.sh [NP ...]
# Needs shyfem, shypre and mpirun on PATH (an OpenMPI build).  Works in a
# folder made with mktemp -d under ${TMPDIR:-/tmp} (GRID/MM_coarse_smooth.grd
# is copied there and its basin is built there with shypre, INPUT is
# linked, the STR files are made there from this folder's), so nothing in
# this folder changes.  The folder is kept (its path is the last line).
# Prints "RST3D MA MPI CHECK: PASS" or "RST3D MA MPI CHECK: FAIL" and
# exits 0 or 1.  Takes about 1 minute for 4.
#------------------------------------------------------------------------
set -u
NPS="${*:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
for np in $NPS; do
  case "$np" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP ...] (each NP at least 2)"; exit 2 ;; esac
done
for t in shyfem shypre mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "RST3D MA MPI CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse_smooth.grd mm_hyd_41.str; do
  [ -f "$HERE/$f" ] || { echo "RST3D MA MPI CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/rst3d_ma.XXXXXX")" || exit 1
echo "rst3d ma mpi check: $(command -v shyfem), serial vs $NPS processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "RST3D MA MPI CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse_smooth.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse_smooth.grd > shypre.log 2>&1 ) \
  || { echo "RST3D MA MPI CHECK: FAIL (shypre failed, log $P/GRID/shypre.log)"; exit 1; }

#--- the STR files
L19='1 2 3 4 5 6 7 8 9 10 12 15 20 30 40 50 60 70 80'
grep -q "^        $L19\$" "$HERE/mm_hyd_41.str" \
  || { echo "RST3D MA MPI CHECK: FAIL (mm_hyd_41.str does not have the levels $L19)"; exit 1; }
grep -q "^        idt = '300s'" "$HERE/mm_hyd_41.str" \
  || { echo "RST3D MA MPI CHECK: FAIL (mm_hyd_41.str does not have idt = '300s')"; exit 1; }
sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
    -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
    -e 's/^        mm_hyd_41$/        wma/' \
    -e 's/^        iturb = 1 /        idtrst = -1\n        vistur = 1.e-2   diftur = 1.e-3\n        iturb = 3 /' \
    "$HERE/mm_hyd_41.str" > "$P/w_ma.str"
sed -e 's/^        wma$/        rma/' \
    -e "s/itend = '[^']*'/itend = '2009-01-01::12:00:00'/" \
    -e 's/^        idtrst = -1$/        itrst = -1     ityrst = 1/' \
    -e "s/^\\\$name\$/\$name\\n        restrt = 'wma.rst'/" \
    "$P/w_ma.str" > "$P/r_ma.str"
grep -q 'ktilt\|ztilt' "$P/w_ma.str" && { echo "RST3D MA MPI CHECK: FAIL (tilt lines left in w_ma.str)"; exit 1; }
[ "$(grep -c "^        wma$\|^        idtrst = -1$\|itend = '2009-01-01::06:00:00'\|^        vistur = 1.e-2   diftur = 1.e-3$\|^        iturb = 3 \|^        $L19\$" "$P/w_ma.str")" = 6 ] \
  || { echo "RST3D MA MPI CHECK: FAIL (cannot make w_ma.str)"; exit 1; }
[ "$(grep -c "^        rma$\|^        itrst = -1     ityrst = 1$\|itend = '2009-01-01::12:00:00'\|^        restrt = 'wma.rst'$\|^        iturb = 3 " "$P/r_ma.str")" = 5 ] \
  || { echo "RST3D MA MPI CHECK: FAIL (cannot make r_ma.str)"; exit 1; }
NSTEP=72	# 06:00 to 12:00 in steps of 300 s

#--- runs and comparison
# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
# levels LOG: the levels of the processes, sorted (init_vertical,
# src/shyfem/initialize.f90: "init_vertical: nlvdi = N  nlv = N")
levels() {
  awk '/init_vertical: nlvdi =/ { print $NF }' "$1" | sort -n | tr '\n' ' ' | sed 's/ $//'
}
run() {  # DIR STR NP [RST]  (NP 1: a plain run without mpirun)
  local d="$1" str="$2" np="$3" rst="${4:-}" r n
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" && cp "$P/$str" "$d/" || return 1
  if [ -n "$rst" ]; then cp "$rst" "$d/wma.rst" || return 1; fi
  if [ "$np" = 1 ]; then
    ( cd "$d" && timeout 600 nice -n 10 shyfem "$str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && SHYFEM_GHOST_CHECK=1 timeout 600 nice -n 10 mpirun --oversubscribe -np "$np" shyfem "$str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    grep -E 'restart: |error reading|error stop' "$d/run.log" | sort | uniq -c | head -8
    echo "  exit code $r ($d/run.log)"; return 1
  fi
  if [ -n "$rst" ]; then
    n="$(grep -c 'A restart has been performed' "$d/run.log")"
    [ "$n" = "$np" ] || { echo "  'A restart has been performed' $n times in the log, not $np ($d/run.log)"; return 1; }
  fi
  if [ "$np" != 1 ] && ! ranks_ok "$d/run.log" "$np"; then
    echo "  the log does not show $np MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines,"
    echo "  expected one from each rank 0 to $(( np - 1 )) with $np processes ($d/run.log)"
    return 1
  fi
  if [ "$np" != 1 ] && ! grep -q 'ghost check of the output gathers is on' "$d/run.log"; then
    echo "  the log does not say 'ghost check of the output gathers is on' ($d/run.log)"
    return 1
  fi
  return 0
}

if ! run "$P/w.np1" w_ma.str 1; then
  fail "the serial write run did not end (above)"
  echo "RST3D MA MPI CHECK: FAIL"; echo "$P"; exit 1
fi
grep -q 'starting Munk Anderson turbulence model' "$P/w.np1/run.log" \
  || fail "the log of the write run does not show Munk-Anderson"
[ -s "$P/w.np1/wma.rst" ] || { fail "the write run left no restart file wma.rst"; echo "RST3D MA MPI CHECK: FAIL"; echo "$P"; exit 1; }

ref="$P/r.np1"
if ! run "$ref" r_ma.str 1 "$P/w.np1/wma.rst"; then
  fail "the serial read did not end (above)"
  echo "RST3D MA MPI CHECK: FAIL"; echo "$P"; exit 1
fi
# the closure at set-up, on the restart state: the n2max lines of the
# info file (setm2n2, one per evaluation of the closure)
inf="$ref/rma.inf"
if [ ! -s "$inf" ]; then
  fail "the serial read wrote no info file rma.inf"
else
  nn="$(grep -c '^ *n2max:' "$inf")"
  n2first="$(awk '/^ *n2max:/ { print $2; exit }' "$inf")"
  echo "  serial read: $nn n2max lines for $NSTEP time steps; value of the first n2max line ${n2first:-none} (the set-up evaluation only if there are $(( NSTEP + 1 )) lines)"
  [ "$nn" = $(( NSTEP + 1 )) ] \
    || fail "the info file of the serial read has $nn n2max lines, not $(( NSTEP + 1 )) ($NSTEP steps and the set-up): the closure was not evaluated at set-up"
  awk -v v="${n2first:-0}" 'BEGIN { exit !(v + 0 > 0) }' \
    || fail "the first n2max line of the serial read is ${n2first:-missing}, not > 0: no stratification at the restart, nothing is tested"
fi

for np in $NPS; do
  d="$P/r.np$np"
  what="the restart file read on $np processes"
  run "$d" r_ma.str "$np" "$P/w.np1/wma.rst"
  ok=$?
  if [ -f "$d/run.log" ]; then
    lv="$(levels "$d/run.log")"
    read -r nl lmin lmax <<< "$(echo "$lv" | awk '{ print NF, $1, $NF }')"
    echo "  read np $np  levels of the processes: $lv"
    if [ "$nl" != "$np" ]; then
      fail "$what: $nl init_vertical lines in the log, not $np"
    elif [ "$lmin" = "$lmax" ]; then
      fail "$what: every process has the $lmax levels of the basin (levels $lv): nothing is tested"
    fi
  fi
  if [ "$ok" != 0 ]; then
    fail "$what: the run did not end, or not on $np processes (above)"
    continue
  fi
  n="$(grep -c '^GHOST CHECK:' "$d/run.log")"
  [ "$n" = 0 ] || fail "$what: $n GHOST CHECK lines, ghost copies out of step with their owners ($d/run.log)"
  for f in rma.hydro.shy rma.ts.shy rma.fvl.shy rma.ext; do
    if [ ! -s "$ref/$f" ] || [ ! -s "$d/$f" ]; then fail "$what: $f missing or empty"; continue; fi
    if cmp -s "$ref/$f" "$d/$f"; then
      echo "  read np $np  $f: byte-identical to the serial read"
    else
      echo "  read np $np  $f: DIFFERS ($(cmp "$ref/$f" "$d/$f" 2>&1 | head -1))"
      fail "$what: $f differs from the serial read"
    fi
  done
done

if [ "$rc" = 0 ]; then echo "RST3D MA MPI CHECK: PASS"; else echo "RST3D MA MPI CHECK: FAIL"; fi
echo "$P"
exit "$rc"
