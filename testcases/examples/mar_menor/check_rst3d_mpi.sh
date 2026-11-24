#!/bin/bash
#------------------------------------------------------------------------
# A 3D restart file read on several processes, when a process has fewer
# vertical levels than the whole basin (issue #278).
#
# A restart record holds the layer depths of the whole basin (nlv_global
# values) and a full column of every node and element, written serially
# or gathered on several processes.  The reader compared the size of the
# layer depths with the levels of its own process (rst_get_vertical in
# src/shyfem/restart.f90), so on several processes every process whose
# domain has fewer levels than the basin stopped with "restart: vertical
# structure array size mismatch" (Mar Menor with the 19 levels of
# mm_hyd_41: 18 and 19 levels on 2 processes, 7, 15, 16 and 19 on 4).
# Behind it, rst_read_vertical decided on the levels of its own process
# whether the file holds the vertical structure, while the writer decides
# on those of the whole basin: a process with one level of its own in a
# 3D basin skipped three records that are in the file.  The 3D fields
# themselves were already read as full columns of which each process
# keeps its own levels.
#
# Cases, from mm_hyd_41.str without its tilt lines (ztilt, ktilt; tilting
# stops on several processes, #216): GOTM (iturb = 1), temperature and
# salinity, the open level boundary with salinity and temperature files,
# the river, heat flux, rain and wind; the restart holds the hydrodynamics,
# T/S/rho, the five GOTM arrays and the vertical velocity:
#   l19  the 19 levels of mm_hyd_41.str (a process in the lagoon has 7)
#   l10  the levels 8 10 15 20 30 40 50 60 70 80: the lagoon is less
#        than 8 m deep, so on 4 processes the process in the lagoon has
#        one level (the second defect above)
# For each: write = 2009-01-01 00:00 to 06:00 from rest, restart file at
# the end (idtrst = -1); read = from the last record of that file to
# 12:00.  The write run is made serially and on the largest NP of NPS;
# the serial file is read serially and on each NP of NPS (default 2 4),
# the file written on the largest NP serially and on each NP, all with the
# METIS partition the model makes.
# Required: every run ends (exit code 0 and "simulation end" in its log,
# timeout 600 s each); the log of an NP-process run has the line
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI or a
# binary without MPI, cannot pass) and "A restart has been performed"
# from every rank of a read run; the NP-process runs have the ghost check
# of the output gathers on (SHYFEM_GHOST_CHECK=1, #268) and no line
# "GHOST CHECK:"; in every NP-process read run a process has fewer levels
# than the basin (the levels of the processes, from the lines
# "init_vertical: ... nlv =", are printed), and in one of the l10 read
# runs a process has one level (otherwise the case tests nothing); and
# the files .hydro.shy, .ts.shy, .fvl.shy and .ext of every read run are
# byte-identical to those of the serial read of the serial file.  A
# restart file written on several processes differs from the serial one,
# but only below the bottom of a node (#268), which no reader uses: its
# reads must give the same files.
#
# Usage:  ./check_rst3d_mpi.sh [NP ...]
# Needs shyfem, shypre and mpirun on PATH (an OpenMPI build).  Works in a
# folder made with mktemp -d under ${TMPDIR:-/tmp} (GRID/MM_coarse_smooth.grd
# is copied there and its basin is built there with shypre, INPUT is
# linked, the STR files are made there from this folder's), so nothing in
# this folder changes.  The folder is kept (its path is the last line).
# Prints "RST3D MPI CHECK: PASS" or "RST3D MPI CHECK: FAIL" and exits 0
# or 1.  Takes about 1 minute for 2 and 4.
#------------------------------------------------------------------------
set -u
NPS="${*:-2 4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
NPMAX=0
for np in $NPS; do
  case "$np" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP ...] (each NP at least 2)"; exit 2 ;; esac
  [ "$np" -gt "$NPMAX" ] && NPMAX=$np
done
for t in shyfem shypre mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "RST3D MPI CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse_smooth.grd mm_hyd_41.str INPUT/gotmturb.nml; do
  [ -f "$HERE/$f" ] || { echo "RST3D MPI CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/rst3d.XXXXXX")" || exit 1
echo "rst3d mpi check: $(command -v shyfem), serial vs $NPS processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "RST3D MPI CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse_smooth.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse_smooth.grd > shypre.log 2>&1 ) \
  || { echo "RST3D MPI CHECK: FAIL (shypre failed, log $P/GRID/shypre.log)"; exit 1; }

#--- the STR files
L19='1 2 3 4 5 6 7 8 9 10 12 15 20 30 40 50 60 70 80'
L10='8 10 15 20 30 40 50 60 70 80'
grep -q "^        $L19\$" "$HERE/mm_hyd_41.str" \
  || { echo "RST3D MPI CHECK: FAIL (mm_hyd_41.str does not have the levels $L19)"; exit 1; }
for cs in l19 l10; do
  if [ "$cs" = l19 ]; then lev="$L19"; else lev="$L10"; fi
  sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::06:00:00'/" \
      -e 's/^        mm_hyd_41$/        w41/' \
      -e 's/^        iturb = 1 /        idtrst = -1\n        iturb = 1 /' \
      -e "s/^        $L19\$/        $lev/" \
      "$HERE/mm_hyd_41.str" > "$P/w_$cs.str"
  sed -e 's/^        w41$/        r41/' \
      -e "s/itend = '[^']*'/itend = '2009-01-01::12:00:00'/" \
      -e 's/^        idtrst = -1$/        itrst = -1     ityrst = 1/' \
      -e "s/^\\\$name\$/\$name\\n        restrt = 'w41.rst'/" \
      "$P/w_$cs.str" > "$P/r_$cs.str"
  grep -q 'ktilt\|ztilt' "$P/w_$cs.str" && { echo "RST3D MPI CHECK: FAIL (tilt lines left in w_$cs.str)"; exit 1; }
  [ "$(grep -c "^        w41$\|^        idtrst = -1$\|itend = '2009-01-01::06:00:00'\|^        $lev\$" "$P/w_$cs.str")" = 4 ] \
    || { echo "RST3D MPI CHECK: FAIL (cannot make w_$cs.str)"; exit 1; }
  [ "$(grep -c "^        r41$\|^        itrst = -1     ityrst = 1$\|itend = '2009-01-01::12:00:00'\|^        restrt = 'w41.rst'$" "$P/r_$cs.str")" = 4 ] \
    || { echo "RST3D MPI CHECK: FAIL (cannot make r_$cs.str)"; exit 1; }
done

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
  if [ -n "$rst" ]; then cp "$rst" "$d/w41.rst" || return 1; fi
  if [ "$np" = 1 ]; then
    ( cd "$d" && timeout 600 nice -n 10 shyfem "$str" < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && SHYFEM_GHOST_CHECK=1 timeout 600 nice -n 10 mpirun --oversubscribe -np "$np" shyfem "$str" < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    grep -E 'restart: |error reading|^ *nlv: ' "$d/run.log" | sort | uniq -c | head -8
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
ghosts() {  # DIR LABEL: no ghost copy out of step in the output gathers (#268)
  local n
  n="$(grep -c '^GHOST CHECK:' "$1/run.log")"
  [ "$n" = 0 ] || fail "$2: $n GHOST CHECK lines, ghost copies out of step with their owners ($1/run.log)"
}

for cs in l19 l10; do
  echo "=== $cs"
  one=no
  # the restart files: serial and on NPMAX processes
  if ! run "$P/$cs.w.np1" "w_$cs.str" 1; then fail "$cs: the serial write run did not end (above)"; continue; fi
  wsrc="1"
  if run "$P/$cs.w.np$NPMAX" "w_$cs.str" "$NPMAX"; then
    ghosts "$P/$cs.w.np$NPMAX" "$cs write on $NPMAX processes"
    wsrc="1 $NPMAX"
    if cmp -s "$P/$cs.w.np1/w41.rst" "$P/$cs.w.np$NPMAX/w41.rst"; then
      echo "  restart file written on $NPMAX processes: byte-identical to the serial one"
    else
      echo "  restart file written on $NPMAX processes: differs from the serial one (below the bottom, #268)"
    fi
  else
    fail "$cs: the write run on $NPMAX processes did not end, or not on $NPMAX processes (above)"
  fi
  ref="$P/$cs.r1.np1"
  for src in $wsrc; do
    for np in 1 $NPS; do
      d="$P/$cs.r$src.np$np"
      what="$cs: the restart file written on $src process(es) read on $np process(es)"
      run "$d" "r_$cs.str" "$np" "$P/$cs.w.np$src/w41.rst"
      ok=$?
      if [ "$np" != 1 ] && [ -f "$d/run.log" ]; then
        # the levels are set up before the restart is read: printed also
        # when the read stops
        lv="$(levels "$d/run.log")"
        read -r nl lmin lmax <<< "$(echo "$lv" | awk '{ print NF, $1, $NF }')"
        echo "  file np $src  read np $np  levels of the processes: $lv"
        if [ "$nl" != "$np" ]; then
          fail "$what: $nl init_vertical lines in the log, not $np"
        elif [ "$lmin" = "$lmax" ]; then
          fail "$what: every process has the $lmax levels of the basin (levels $lv): nothing is tested"
        fi
        [ "$lmin" = 1 ] && one=yes
      fi
      if [ "$ok" != 0 ]; then
        fail "$what: the run did not end, or not on $np processes (above)"
        [ "$d" = "$ref" ] && break 2
        continue
      fi
      [ "$np" != 1 ] && ghosts "$d" "$what"
      [ "$d" = "$ref" ] && continue
      for f in r41.hydro.shy r41.ts.shy r41.fvl.shy r41.ext; do
        if [ ! -s "$ref/$f" ] || [ ! -s "$d/$f" ]; then fail "$what: $f missing or empty"; continue; fi
        if cmp -s "$ref/$f" "$d/$f"; then
          echo "  file np $src  read np $np  $f: byte-identical"
        else
          echo "  file np $src  read np $np  $f: DIFFERS ($(cmp "$ref/$f" "$d/$f" 2>&1 | head -1))"
          fail "$what: $f differs from the serial read of the serial file"
        fi
      done
    done
  done
  if [ "$cs" = l10 ] && [ "$one" != yes ]; then
    fail "l10: no read run had a process with one level (run with 4 among the NP), so that read is not tested"
  fi
done

if [ "$rc" = 0 ]; then echo "RST3D MPI CHECK: PASS"; else echo "RST3D MPI CHECK: FAIL"; fi
echo "$P"
exit "$rc"
