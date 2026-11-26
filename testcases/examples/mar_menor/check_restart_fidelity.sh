#!/bin/bash
#------------------------------------------------------------------------
# A run read from a restart file must continue exactly as the run that
# was not interrupted (#303, #304).
#
# On 9187cdf1 (restart format version 19) a restarted run differs from
# the continuous run from its first step on, because state that the next
# step uses is not in the restart record:
#   - evapv, the evaporation of the last heat-flux step, which the next
#     step adds to the water-level equation (evap_init sets it to 0);
#   - iwetv, the wet/dry counter of the elements, which holds re-wetting
#     back (setweg sets it to 0), and the time of setweg's last new step;
#   - tws and dtw, the skin temperature and warm-layer difference of the
#     COARE heat flux (iheat = 6), save variables of qflux3d;
#   - windcd, the drag coefficient COARE sets with itdrag = 4
#     (windcd_init resets it to dragco);
#   - tken, eps, visv and difv of the k-epsilon closure (iturb = 2).
# In mm_hyd_41 the water level differs by 3.9e-6 m at the first output
# after the read, and GOTM grows that to a salinity difference of 4.9 by
# 12:00; wet/dry and COARE cases differ by mm, k-epsilon by 0.4 m.  The
# audit of round 6 measured all this (docs/investigation/2026-11-restart-
# v20/, reportI304.md, reportI304b.md, results_i304b.txt); this check
# runs its cases with its recipes.
#
# Cases.  Each is a continuous run, a write run that ends at the restart
# time and writes its last record (idtrst = -1), and a read run from that
# record (itrst = -1, ityrst = 1) to the end of the continuous run, all on
# the same number of processes (the write run and then the read run, next
# to the continuous run):
#   mm_i0         mm_hyd_41.str without its tilt lines (ztilt, ktilt;
#                 tilting stops on several processes, #216), outputs every
#                 hour (idtout = idtcon = 1h), iturb = 0, ievap = 1;
#                 2009-01-01 00:00-12:00, restart at 06:00, serial
#   mm_i1         the same with GOTM (iturb = 1)
#   mm_h6d4       mm_i0 with the COARE heat flux and its drag (iheat = 6,
#                 itdrag = 4)
#   mm_h6noon     mm_h6d4 from 00:00 to 18:00, restart at 12:00, when the
#                 warm layer dtw is not 0
#   ven_s         ../venice_lagoon/venlag_smoke.str (GOTM, COARE heat flux,
#                 evaporation, wet/dry, itsplt = 2), 2014-08-01 00:00-06:00,
#                 restart at 03:00, serial
#   ven_np2       the same on 2 processes
#   ven_np4       the same on 4 processes
#   ven_keps_s    venlag_smoke.str with k-epsilon (iturb = 2), serial
#   ven_keps_np4  the same on 4 processes
# Required for a case: the three runs end (exit code 0 and "simulation
# end" in the log, timeout 1200 s each); the log of an NP-process run has
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI,
# cannot pass); the read run's log has "A restart has been performed"
# once from every rank and its restart time is the write run's end; and
# every record of the read run's .hydro.shy, .ts.shy and .ext equals the
# continuous run's record at the same time: max|d| = 0, compared with
# shy_maxdiff.py (next to this script).  A record of the read run with no
# record of the continuous run at its time, or one of the continuous run
# from the restart time on with none in the read run, is a difference.
#
# Prints one line per case,
#   case NAME: max|d| zeta X@T, transport X@T, S X@T, T X@T, ext X -> PASS|FAIL
# (X@T: the largest difference of the variable and the hour where it
# occurs, from the start date; ext X: the largest of the .ext file), or
# "case NAME: did not run (reason) -> FAIL", each followed by the summary
# lines of shy_maxdiff.py (for the .shy files with the differences in the
# first hour after the restart and at the end); then the time of each case
# and the total, and "RESTART FIDELITY: PASS" or "RESTART FIDELITY: FAIL",
# and exits 0 or 1.
#
# Usage:  ./check_restart_fidelity.sh [case ...]    (no case: every case)
# Needs shyfem, shypre and python3 with numpy on PATH, and mpirun (an
# OpenMPI build) for the cases on several processes.  Works in a folder
# made with mktemp -d under ${TMPDIR:-/tmp}: the basins are built there
# with shypre from GRID/MM_coarse_smooth.grd and ../venice_lagoon/GRID/
# venlag62.grd, INPUT is linked and the STR files are made there with sed
# from mm_hyd_41.str and venlag_smoke.str, so nothing in the source
# folders changes.  The cases run at the same time (32 processes at the
# start); every mpirun has --bind-to none, so that the runs do not share
# the two cores Open MPI binds a 2-process run to.  Takes about 2 minutes
# on the development machine (the serial venlag cases are the longest).
# The folder is removed when every case passes and kept otherwise (its
# path is printed before the verdict, which is the last line).
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
ALL="mm_i0 mm_i1 mm_h6d4 mm_h6noon ven_s ven_np2 ven_np4 ven_keps_s ven_keps_np4"
CASES="${*:-$ALL}"
needmm=no; needven=no; needmpi=no
for c in $CASES; do
  case " $ALL " in *" $c "*) ;; *) echo "usage: $0 [case ...], cases: $ALL"; exit 2 ;; esac
  case "$c" in mm_*) needmm=yes ;; ven_*) needven=yes ;; esac
  case "$c" in *_np*) needmpi=yes ;; esac
done
tools="shyfem shypre python3"
[ "$needmpi" = yes ] && tools="$tools mpirun"
for t in $tools; do
  command -v "$t" > /dev/null 2>&1 || { echo "RESTART FIDELITY: FAIL ($t is not on PATH)"; exit 1; }
done
python3 -c 'import numpy' 2> /dev/null || { echo "RESTART FIDELITY: FAIL (python3 has no numpy)"; exit 1; }
[ -f "$HERE/shy_maxdiff.py" ] || { echo "RESTART FIDELITY: FAIL (missing $HERE/shy_maxdiff.py)"; exit 1; }
if [ "$needmm" = yes ]; then
  for f in GRID/MM_coarse_smooth.grd mm_hyd_41.str INPUT/level_Mar_Menor.dat INPUT/S_MarMenor.txt \
           INPUT/T_MarMenor.txt INPUT/river.txt INPUT/wind09.txt INPUT/qflux09.txt INPUT/rain09.txt \
           INPUT/gotmturb.nml; do
    [ -f "$HERE/$f" ] || { echo "RESTART FIDELITY: FAIL (missing $HERE/$f)"; exit 1; }
  done
fi
if [ "$needven" = yes ]; then
  VEN="$(cd "$HERE/../venice_lagoon" && pwd)" || { echo "RESTART FIDELITY: FAIL (no ../venice_lagoon)"; exit 1; }
  for f in GRID/venlag62.grd venlag_smoke.str INPUT/gotmturb.nml INPUT/wind_lightBora.dat \
           INPUT/heat_idealSummer.dat; do
    [ -f "$VEN/$f" ] || { echo "RESTART FIDELITY: FAIL (missing $VEN/$f)"; exit 1; }
  done
fi
P="$(mktemp -d "${TMPDIR:-/tmp}/rstfid.XXXXXX")" || exit 1
T0=$(date +%s)
echo "restart fidelity check: $(command -v shyfem), cases: $CASES, in $P  $(date +%H:%M:%S)"

# On an interrupt: stop the cases and their runs.  timeout starts its
# command in a process group of its own, so the interrupt does not reach
# the runs; and a TERM sent to the whole group of this script ends the
# case subshells before the trap runs, which leaves their runs orphaned.
# So the trap stops the case subshells with what they started (killtree)
# and then every run still listed in a run.pid file (the PID of its
# timeout, which passes the TERM on to the run's process group).
PIDS=""
killtree() {  # PID...: the processes and everything they started
  local p c
  for p in "$@"; do
    for c in $(pgrep -P "$p"); do killtree "$c"; done
    kill -TERM "$p" 2> /dev/null
  done
}
stopruns() {
  local f p
  killtree $PIDS
  for f in "$P"/*/[cwr]/run.pid; do
    [ -f "$f" ] || continue
    p="$(cat "$f")"
    [ "$(ps -o comm= -p "$p" 2> /dev/null)" = timeout ] && kill -TERM "$p"
  done
}
trap 'stopruns; echo "  files kept in $P"; echo "RESTART FIDELITY: FAIL (interrupted)"; exit 130' INT TERM

#--- the basins
bas() {  # DIR GRD [shypre option]
  mkdir "$P/$1" && cp "$2" "$P/$1/" || return 1
  ( cd "$P/$1" && shypre ${3:-} "$(basename "$2")" > shypre.log 2>&1 )
}
basok=yes
if [ "$needmm" = yes ]; then bas mmbas "$HERE/GRID/MM_coarse_smooth.grd" & PIDS="$PIDS $!"; fi
if [ "$needven" = yes ]; then bas venbas "$VEN/GRID/venlag62.grd" -silent & PIDS="$PIDS $!"; fi
for p in $PIDS; do wait "$p" || basok=no; done
PIDS=""
if [ "$needmm" = yes ] && [ ! -s "$P/mmbas/MM_coarse_smooth.bas" ]; then basok=no; fi
if [ "$needven" = yes ] && [ ! -s "$P/venbas/venlag62.bas" ]; then basok=no; fi
[ "$basok" = yes ] || { echo "  files kept in $P"; echo "RESTART FIDELITY: FAIL (shypre failed, see mmbas/shypre.log or venbas/shypre.log there)"; exit 1; }

#--- the STR files
# mkmm CASE ITURB TR TE [EXTRA]: c (00:00-TE), w (00:00-TR), r (TR-TE)
# from mm_hyd_41.str; the iturb line becomes "iturb = ITURB  ievap = 1
# hmin = 1.  aapar = 0." (and the line EXTRA)
mkmm() {
  local d="$P/$1" it="$2" tr="$3" te="$4" ex="${5:-}" pl s
  pl="iturb = $it      ievap = 1       hmin = 1.    aapar = 0."
  base() {  # title itend
    sed -e '/^[[:space:]]*ztilt[[:space:]]*=/d' -e '/^[[:space:]]*ktilt[[:space:]]*=/d' \
        -e "s/^        mm_hyd_41\$/        $1/" \
        -e "s/itend = '[^']*'/itend = '2009-01-01::$2:00:00'/" \
        -e "s/idtout = '3h'/idtout = '1h'/" -e "s/idtcon = '3h'/idtcon = '1h'/" \
        -e "s/^        iturb = 1      ievap = 1       hmin = 1\.    aapar = 0\.\$/        $pl${ex:+\\n        $ex}/" \
        "$HERE/mm_hyd_41.str"
  }
  base c "$te" > "$d/c/c.str"
  base w "$tr" | sed -e "s/^        $pl\$/&\n        idtrst = -1/" > "$d/w/w.str"
  base r "$te" | sed -e "s/^        $pl\$/&\n        itrst = -1     ityrst = 1/" \
                     -e "s/^\\\$name\$/\$name\\n        restrt = 'w.rst'/" > "$d/r/r.str"
  for s in c w r; do
    grep -q 'ztilt\|ktilt' "$d/$s/$s.str" && return 1
    [ "$(grep -c "^        $s\$\|idtout = '1h'\|idtcon = '1h'\|^        $pl\$" "$d/$s/$s.str")" = 4 ] || return 1
    if [ -n "$ex" ]; then grep -q "^        $ex\$" "$d/$s/$s.str" || return 1; fi
  done
  grep -q "itend = '2009-01-01::$te:00:00'" "$d/c/c.str" || return 1
  [ "$(grep -c "itend = '2009-01-01::$tr:00:00'\|^        idtrst = -1\$" "$d/w/w.str")" = 2 ] || return 1
  [ "$(grep -c "itend = '2009-01-01::$te:00:00'\|^        itrst = -1     ityrst = 1\$\|^        restrt = 'w.rst'\$" \
       "$d/r/r.str")" = 3 ] || return 1
  RTIME="2009-01-01::$tr:00:00"; H1=$(( 10#$tr + 1 )); H2=$(( 10#$te ))
}
# mkven CASE ITURB: c (00:00-06:00), w (00:00-03:00), r (03:00-06:00)
# from venlag_smoke.str with iturb = ITURB
mkven() {
  local d="$P/$1" it="$2" s tab=$'\t'
  base() {  # title itend (the title lines of venlag_smoke.str begin with a tab)
    sed -e "s/^\tvenlag_smoke\$/\t$1/" -e "s/itend  = '2014-08-01::06:00'/itend  = '2014-08-01::$2'/" \
        -e "s/^        iturb  = 1\$/        iturb  = $it/" "$VEN/venlag_smoke.str"
  }
  base c 06:00 > "$d/c/c.str"
  base w 03:00 | sed -e "s/^        iturb  = $it\$/&\n        idtrst = -1/" > "$d/w/w.str"
  base r 06:00 | sed -e "s/^        iturb  = $it\$/&\n        itrst = -1     ityrst = 1/" \
                     -e "s/^\\\$name\$/\$name\\n        restrt = 'w.rst'/" > "$d/r/r.str"
  for s in c w r; do
    [ "$(grep -c "^$tab$s\$\|^        iturb  = $it\$" "$d/$s/$s.str")" = 2 ] || return 1
  done
  grep -q "itend  = '2014-08-01::06:00'" "$d/c/c.str" || return 1
  [ "$(grep -c "itend  = '2014-08-01::03:00'\|^        idtrst = -1\$" "$d/w/w.str")" = 2 ] || return 1
  [ "$(grep -c "itend  = '2014-08-01::06:00'\|^        itrst = -1     ityrst = 1\$\|^        restrt = 'w.rst'\$" \
       "$d/r/r.str")" = 3 ] || return 1
  RTIME="2014-08-01::03:00:00"; H1=4; H2=6
}

#--- the runs
# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
# run DIR NAME NP: runs DIR/NAME.str; prints why it failed, if it did
run() {
  local d="$1" n="$2" np="$3" r
  if [ "$np" = 1 ]; then
    ( cd "$d" && OMP_NUM_THREADS=1 exec timeout 1200 nice -n 10 shyfem "$n.str" < /dev/null > "$n.log" 2>&1 ) &
  else
    ( cd "$d" && OMP_NUM_THREADS=1 exec timeout 1200 nice -n 10 mpirun --oversubscribe --bind-to none -np "$np" \
        shyfem "$n.str" < /dev/null > "$n.log" 2>&1 ) &
  fi
  echo "$!" > "$d/run.pid"
  wait "$!"
  r=$?
  rm -f "$d/run.pid"
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/$n.log"; then
    echo "$n: exit code $r, $(grep -c 'simulation end' "$d/$n.log") 'simulation end' in $d/$n.log"; return 1
  fi
  if [ "$np" != 1 ] && ! ranks_ok "$d/$n.log" "$np"; then
    echo "$n: not $np MPI processes, $(grep -c 'shympi initialized:' "$d/$n.log") 'shympi initialized:' lines"; return 1
  fi
  return 0
}
# onecase NAME: runs the case, writes NAME.line (the case line) and
# NAME.detail (the summary lines)
onecase() {
  local cs="$1" d="$P/$1" np=1 s t0 why rc pc pw f k line="" ext="" un=0 nr
  t0=$(date +%s)
  case "$cs" in *_np*) np="${cs##*_np}" ;; esac
  mkdir "$d" || return 1
  for s in c w r; do
    mkdir "$d/$s" || return 1
    case "$cs" in
      mm_*)  mkdir "$d/$s/GRID" && cp "$P/mmbas/MM_coarse_smooth.bas" "$d/$s/GRID/" && ln -s "$HERE/INPUT" "$d/$s/INPUT" ;;
      ven_*) mkdir "$d/$s/GRID" && cp "$P/venbas/venlag62.bas" "$d/$s/GRID/" && ln -s "$VEN/INPUT" "$d/$s/INPUT" ;;
    esac || return 1
  done
  RTIME=""; H1=""; H2=""
  case "$cs" in
    mm_i0)        mkmm "$cs" 0 06 12 ;;
    mm_i1)        mkmm "$cs" 1 06 12 ;;
    mm_h6d4)      mkmm "$cs" 0 06 12 "iheat = 6   itdrag = 4" ;;
    mm_h6noon)    mkmm "$cs" 0 12 18 "iheat = 6   itdrag = 4" ;;
    ven_s|ven_np*)           mkven "$cs" 1 ;;
    ven_keps_s|ven_keps_np*) mkven "$cs" 2 ;;
  esac
  if [ $? != 0 ] || [ -z "$RTIME" ]; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # c, and w then r (r starts when w has ended, while c may still run)
  why=""
  run "$d/c" c "$np" > "$d/c.why" & pc=$!
  ( run "$d/w" w "$np" > "$d/w.why" || exit 1
    [ -s "$d/w/w.rst" ] || { echo "w: no restart file $d/w/w.rst" > "$d/w.why"; exit 1; }
    ln -s ../w/w.rst "$d/r/w.rst" || exit 2
    run "$d/r" r "$np" > "$d/r.why" || exit 2 ) & pw=$!
  wait "$pc" || why="$why$(cat "$d/c.why"); "
  wait "$pw"
  case $? in
    0) k="$(grep -c 'A restart has been performed' "$d/r/r.log")"
       [ "$k" = "$np" ] || why="${why}r: 'A restart has been performed' $k times in $d/r/r.log, not $np; "
       k="$(grep -c "used restart time = *$RTIME *\$" "$d/r/r.log")"
       [ "$k" = "$np" ] || why="${why}r: restart time $RTIME $k times in $d/r/r.log, not $np; " ;;
    1) why="$why$(cat "$d/w.why"); " ;;
    *) why="$why$(cat "$d/r.why" 2> /dev/null); " ;;
  esac
  echo "$cs $(( $(date +%s) - t0 )) s" > "$d.time"
  if [ -n "$why" ]; then
    echo "case $cs: did not run (${why%; }) -> FAIL" > "$d.line"; return 1
  fi
  rc=0
  : > "$d.detail"
  for f in hydro.shy ts.shy ext; do
    python3 "$HERE/shy_maxdiff.py" "$d/c/c.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    if [ "$k" != 0 ] && [ "$k" != 1 ]; then
      why="$why$f: $(grep -v '^ \|^SUMMARY' "$d/cmp.$f.txt" | head -1); "
      continue
    fi
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    nr="$(echo "$s" | sed -n 's/.*unmatched \([0-9]*\) .*/\1/p')"
    un=$(( un + ${nr:-0} ))
    # max|d| NAME=X@T ... of the summary line
    if [ "$f" = ext ]; then
      ext="$(echo "${s##*max|d| }" | awk '{ for (i = 1; i <= NF; i++) { split($i, a, /[=@]/); if (a[2] + 0 > m) m = a[2] + 0 } }
        END { printf "%.3e", m }')"
      echo "    $f: ${s#SUMMARY *: }" >> "$d.detail"
    else
      line="$line$(echo "${s##*max|d| }" | awk '{ for (i = 1; i <= NF; i++) { split($i, a, /[=@]/); printf "%s %s@%s, ", a[1], a[2], a[3] } }')"
      # the differences in the first hour after the restart and at the end
      echo "    $f: ${s#SUMMARY *: }; at ${H1}h$(athour "$d/cmp.$f.txt" "$H1"); at ${H2}h$(athour "$d/cmp.$f.txt" "$H2")" \
        >> "$d.detail"
    fi
  done
  if [ -n "$why" ]; then
    echo "case $cs: did not compare (${why%; }) -> FAIL" > "$d.line"; return 1
  fi
  line="case $cs: max|d| ${line}ext $ext"
  [ "$un" = 0 ] || line="$line, $un unmatched records"
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}
# athour CMPFILE H: " NAME X ..." of the lines "t= H.000h NAME max|d|=X"
# of shy_maxdiff.py
athour() {
  awk -v h="$2" '/^  t=/ { s = $0; sub(/^ *t= */, "", s); split(s, f, " "); t = f[1]; sub(/h$/, "", t)
    if (t + 0 == h + 0 && f[3] ~ /^max/) { v = f[3]; sub(/^max\|d\|=/, "", v); printf " %s %s", f[2], v } }' "$1"
}

for cs in $CASES; do
  onecase "$cs" & PIDS="$PIDS $!"
done
wait
PIDS=""

rc=0
for cs in $CASES; do
  if [ -s "$P/$cs.line" ]; then cat "$P/$cs.line"; else echo "case $cs: did not run (no result) -> FAIL"; fi
  [ -s "$P/$cs.detail" ] && cat "$P/$cs.detail"
  grep -q -- '-> PASS$' "$P/$cs.line" 2> /dev/null || rc=1
done
tm=""
for cs in $CASES; do [ -s "$P/$cs.time" ] && tm="$tm$(cat "$P/$cs.time"), "; done
echo "time: ${tm}total $(( $(date +%s) - T0 )) s"
if [ "$rc" = 0 ]; then
  echo "RESTART FIDELITY: PASS"
  rm -rf "$P"
else
  echo "  files kept in $P"
  echo "RESTART FIDELITY: FAIL"
fi
exit "$rc"
