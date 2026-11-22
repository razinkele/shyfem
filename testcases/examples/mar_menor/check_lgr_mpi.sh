#!/bin/bash
#------------------------------------------------------------------------
# Lagrangian MPI gate: one test case run serially and on NP processes, the
# results compared with the matching tool.
#
# Usage:  ./check_lgr_mpi.sh CASE NP MODE [EXTRA ARGS FOR THE TOOL ...]
#
#   CASE  mm_lgr_a | mm_lgr_b | mm_lgr_c | mm_lgr_e | mm_lgr
#         (a, b, c, e are accepted as short names)
#   NP    number of MPI processes of the second run
#   MODE  flux   debug dump of the element fluxes, serial vs MPI
#         part   debug dump of the particles (per output time), serial vs MPI
#         handover  debug dump of the particles (as part), then the hand-over
#                fidelity check of lgr_dbg_compare.py: --by key --handover,
#                the particles that changed process against those that did
#                not (--step 6e-8, case B 0.25: one single-precision step)
#         pos    final particle file: positions against the case's floors
#                (the table below, as floor), layers, types, times
#         ids    final particle file: the ids, the counts per block
#                (--same-counts), valid cells (--nel, --nlv of the basin)
#         perturb  two MPI runs (no serial run) with the debug dump, one
#                plain and one with MALLOC_PERTURB_=85; every dump file of
#                the two runs must be byte-identical (dependence of the
#                result on memory that malloc hands out)
#         floor  debug dump of the particles (as part), compared by key with
#                the case's --tol and its position floors (the table below):
#                --max-beyond-last and --max-largest of lgr_dbg_compare.py
#                (not for mm_lgr: its random walk is never seeded, #225)
#
# The serial outputs are renamed to CASE.serial.* (lgr.shy, hydro.shy, inf,
# log); the MPI log is CASE.npN.log.  For flux and part the run uses a
# temporary copy of the STR file with "levdbg = 3" right after the $para
# line (the run name inside the file is unchanged, so the output names are
# the same); the debug files of each run end up in CASE.serial.dbg/ and
# CASE.npN.dbg/, both made fresh by every call.
#
# Note: flux uses the relative default limit of lgr_dbg_compare.py (1e-5) for
# every case; the per-case --tol below applies to pos and part only.
# Limits: the geographic cases use --tol 1e-5, the Cartesian case mm_lgr_b
# --tol 2 (for pos and part).  The flux comparison is relative and keeps
# the default of lgr_dbg_compare.py.  Part uses --by nearest (pairs by
# position; since Task 4.2 the ids equal those of the serial run, so --by id
# or --by key can be given).  Arguments after MODE come last on the tool
# command line and so replace the defaults, for example
#   ./check_lgr_mpi.sh mm_lgr_a 4 part --by id --tol 1e-3
#
# floor: the positions are held against floors measured on the serial
# reference instead of the limit pair by pair: the run fails if more pairs
# are beyond --tol at the last output than the floor's count, or if the
# largest distance at any output is above the floor's distance.  Arguments
# after MODE come last, so a floor can be replaced for a trial run.
#
# pos: lgr_compare.py --mode pos with the case's --tol and the same floors
# (--max-beyond-last, --max-largest: particles of any block beyond --tol at
# the last output, largest distance of any pair at any output; hl is then
# compared only for pairs in the same element).  The ids per block, the
# output times, layers, z, types, times, sinking and custom values gate
# exactly as without floors.  mm_lgr has no floors: --tol pair by pair.
# ids: lgr_compare.py --mode ids --same-counts --nel N --nlv L, with N and L
# from the model header of the serial particle file (lgr_compare.py --dims:
# the basin's element count and the number of layers).
#
# handover: the particles of the two runs are paired by their key (the last
# six columns of the dump); the statistic and the rule (a jump test against
# the noise of the particles that stayed, and a Poisson count test) are
# described in the docstring of lgr_dbg_compare.py.  The distances above the
# limit of the part mode are printed, not gated.  Arguments after MODE come
# last, so --step, --jump-factor, --jump-floor, --quantile and --min-changed
# can be given or replaced.
#
# Side self-test: every mode that runs at levdbg = 3 (flux, part, handover,
# floor, perturb) requires of each log (serial and MPI; both MPI logs in perturb)
# the summary line "lgr side fallback self-test: ok" and no line with
# "lgr side fallback self-test: FAILED"; for mm_lgr_b the open-side count
# of checks run (the "open N/M" field of the summary) must be above 0, and
# for an MPI run on more than one process the cut-off count likewise.
#
# Re-location self-checks (Task 3.5): every mode that runs at levdbg = 3 also
# requires, of a run on one process (the serial run, and the second run if NP
# is 1), the line "lgr relocation self-check: compared N, differing D, clear
# hits in a second element C, points in two or more elements M, key order
# walks W, wrong K" with D = 0 and C = 0 (the search key against
# find_elem_from_old, and the premise of the margin); of a run on several
# processes (the MPI run, both runs in perturb), the line "lgr relocation by
# position: parked N (...), stayed S, kept for lack of a layer L, went to
# another process G, nobody answered A, hit within the margin and nobody
# answered Z, key order walks W, wrong K" with Z = 0 and S + L + G + A = N.
# In both lines W must be above 0 and K = 0 (the key against the walk of
# find_elem_from_old, lgr_mpi_selftest_key).  A missing line fails too.
#
# perturb: the dumps of the second run go to CASE.npN.perturb.dbg/ and its log
# is CASE.npN.perturb.log.  A PASS is weak evidence: the perturbation only
# shows a dependence on memory that malloc hands out, and case A on 4
# processes passed with the defect of issue #234 present.  The variable is
# passed with mpirun -x; the mode fails if a launched process does not see it.
#
# Needs shyfem, mpirun and python3 on PATH (an OpenMPI build of shyfem), and
# `make init` done together with
#   (cd GRID && shypre -noopti MM_geo.grd)
# Exit code 0 (LGR GATE: PASS) or 1 (LGR GATE: FAIL).
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
rc=0
fail() { echo "LGR GATE FAIL: $*"; rc=1; }
usage() {
  echo "usage: $0 CASE NP MODE [tool args ...]   (CASE: mm_lgr_a|b|c|e|mm_lgr, MODE: flux|part|handover|floor|pos|ids|perturb)"
  exit 2
}

[ $# -ge 3 ] || usage
CASE="$1"; NP="$2"; MODE="$3"; shift 3
case "$CASE" in
  a|b|c|e) CASE="mm_lgr_$CASE" ;;
  mm_lgr_a|mm_lgr_b|mm_lgr_c|mm_lgr_e|mm_lgr) ;;
  *) echo "unknown case '$CASE'"; usage ;;
esac
case "$NP" in ''|*[!0-9]*) echo "NP must be a number"; usage ;; esac
[ "$NP" -ge 1 ] || usage
case "$MODE" in flux|part|handover|floor|pos|ids|perturb) ;; *) echo "unknown mode '$MODE'"; usage ;; esac
if [ "$CASE" = mm_lgr_b ]; then TOL=2; STEP=0.25; else TOL=1e-5; STEP=6e-8; fi

# Position floors (mode floor): particles beyond --tol at the last output and
# the largest distance at any output, each the envelope of six serial runs
# whose wind drag is changed by up to a relative 1e-5 (degrees for A, C, E,
# metres for B).  Source: docs/reviews/2026-11-lagrange-mpi-acceptance.md,
# section "Task 3.7", table "Position floors on the new reference" (measured
# on /home/razinka/wt-lgr-ref3, commit 0fddec90).  Never change a value to
# make a run pass.  Mode pos uses the same floors on the particle file.
case "$CASE" in
  mm_lgr_a) FLOOR_N=78; FLOOR_D=2.97e-3 ;;
  mm_lgr_b) FLOOR_N=48; FLOOR_D=182 ;;
  mm_lgr_c) FLOOR_N=19; FLOOR_D=7.1e-3 ;;
  mm_lgr_e) FLOOR_N=33; FLOOR_D=4.3e-3 ;;
  *) FLOOR_N=""; FLOOR_D="" ;;
esac
if [ "$MODE" = floor ] && [ -z "$FLOOR_N" ]; then
  echo "no position floor for $CASE (its random walk is never seeded, #225)"; usage
fi

#--- preconditions -------------------------------------------------------
command -v shyfem  > /dev/null 2>&1 || { echo "LGR GATE FAIL: shyfem is not on PATH"; exit 1; }
command -v mpirun  > /dev/null 2>&1 || { echo "LGR GATE FAIL: mpirun is not on PATH"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "LGR GATE FAIL: python3 is not on PATH"; exit 1; }
for b in GRID/MM_geo.bas GRID/MM_coarse.bas; do
  if [ ! -f "$HERE/$b" ]; then
    echo "LGR GATE FAIL: $b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE"
    exit 1
  fi
done
[ -f "$HERE/$CASE.str" ] || { echo "LGR GATE FAIL: $CASE.str not found in $HERE"; exit 1; }

TMPSTR=""
cleanup() {
  local f
  if [ -n "$TMPSTR" ] && [ -f "$TMPSTR" ]; then rm -f "$TMPSTR"; fi
  # debug files of a failed or aborted run (collect_dbg moves those of a good run)
  for f in "$HERE"/lgrdbg.*.txt; do
    [ -e "$f" ] && rm -f "$f"
  done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

STR="$CASE.str"
DUMP=0
if [ "$MODE" = flux ] || [ "$MODE" = part ] || [ "$MODE" = handover ] || [ "$MODE" = floor ] || [ "$MODE" = perturb ]; then
  DUMP=1
  if grep -q '^[[:space:]]*levdbg' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str already sets levdbg; refusing to add a second one"
    exit 1
  fi
  if ! grep -q '^\$para[[:space:]]*$' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str has no line with only \$para"
    exit 1
  fi
  TMPSTR="$HERE/$CASE.lgrdbg.$$.str"
  awk '{ print } !done && /^\$para[ \t\r]*$/ { print "        levdbg = 3"; done = 1 }' \
      "$HERE/$CASE.str" > "$TMPSTR" || { echo "LGR GATE FAIL: cannot write $TMPSTR"; exit 1; }
  STR="$(basename "$TMPSTR")"
fi

#--- helpers ---------------------------------------------------------------
# remove the model outputs and debug files of earlier runs (explicit names)
clean_outputs() {
  local ext f
  for ext in lgr.shy hydro.shy inf; do
    rm -f "$HERE/$CASE.$ext" "$HERE/$CASE.serial.$ext"
  done
  if [ "$DUMP" = 1 ]; then
    for f in "$HERE"/lgrdbg.*.txt; do
      [ -e "$f" ] && rm -f "$f"
    done
  fi
}

# before the MPI run: only the model's own outputs (the CASE.serial.* files stay)
clean_outputs_mpi() {
  local ext f
  for ext in lgr.shy hydro.shy inf; do rm -f "$HERE/$CASE.$ext"; done
  if [ "$DUMP" = 1 ]; then
    for f in "$HERE"/lgrdbg.*.txt; do
      [ -e "$f" ] && rm -f "$f"
    done
  fi
}

# keep the run's debug files in a fresh folder of its own
collect_dbg() {
  local dir="$HERE/$1" f n=0
  [ "$DUMP" = 1 ] || return 0
  if [ -d "$dir" ]; then rm -rf "$dir"; fi
  mkdir "$dir" || { fail "cannot create $dir"; return 1; }
  for f in "$HERE"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    mv "$f" "$dir/" && n=$((n + 1))
  done
  echo "  $n debug files moved to $1/"
  [ "$n" -gt 0 ] || { fail "run left no lgrdbg.*.txt files"; return 1; }
  return 0
}

summary() { python3 "$HERE/lgr_compare.py" "$1" --summary 2>&1 | sed 's/^/    /'; }

# selftest_check LOG NPROC: the side self-test of a levdbg = 3 run (see header)
selftest_check() {
  local log="$1" np="$2" line n
  if grep -q 'lgr side fallback self-test: FAILED' "$log"; then
    fail "side self-test FAILED in $log"
    grep 'lgr side fallback self-test: FAILED' "$log" | head -5 | sed 's/^/    /'
    return
  fi
  line="$(grep 'lgr side fallback self-test: ok' "$log" | tail -1)"
  if [ -z "$line" ]; then
    fail "no line 'lgr side fallback self-test: ok' in $log"; return
  fi
  echo "  $(basename "$log"):$(echo "$line" | sed 's/^ *//')"
  if [ "$CASE" = mm_lgr_b ]; then
    n="$(echo "$line" | sed -n 's/.* open \([0-9][0-9]*\)\/[0-9][0-9]*.*/\1/p')"
    if [ -z "$n" ]; then fail "no open-side count of checks run in the self-test line of $log"
    elif [ "$n" -eq 0 ]; then fail "open-side count of checks run is 0 in $log"; fi
  fi
  if [ "$np" -gt 1 ]; then
    n="$(echo "$line" | sed -n 's/.* cut-off \([0-9][0-9]*\)\/[0-9][0-9]*.*/\1/p')"
    if [ -z "$n" ]; then fail "no cut-off count of checks run in the self-test line of $log"
    elif [ "$n" -eq 0 ]; then fail "cut-off count of checks run is 0 in $log"; fi
  fi
}

# relocation_check LOG NPROC: the re-location self-checks of a levdbg = 3 run
# (see header)
relocation_check() {
  local log="$1" np="$2" line n d c s l g a z
  line="$(grep 'lgr relocation classes:' "$log" | tail -1)"
  [ -n "$line" ] && echo "  $(basename "$log"):$(echo "$line" | sed 's/^ *//')"
  if [ "$np" -le 1 ]; then
    line="$(grep 'lgr relocation self-check:' "$log" | tail -1)"
    if [ -z "$line" ]; then
      fail "no line 'lgr relocation self-check' in $log"; return
    fi
    echo "  $(basename "$log"):$(echo "$line" | sed 's/^ *//')"
    n="$(echo "$line" | sed -n 's/.*compared \([0-9][0-9]*\),.*/\1/p')"
    d="$(echo "$line" | sed -n 's/.*differing \([0-9][0-9]*\),.*/\1/p')"
    c="$(echo "$line" | sed -n 's/.*clear hits in a second element \([0-9][0-9]*\).*/\1/p')"
    if [ -z "$n" ] || [ -z "$d" ] || [ -z "$c" ]; then
      fail "cannot read the relocation self-check line of $log"; return
    fi
    [ "$d" -eq 0 ] || fail "relocation self-check: $d of $n searches differ from the search key in $log"
    [ "$c" -eq 0 ] || fail "relocation self-check: $c clear hits lie in a second element in $log"
    key_check "$line" "$log"
  else
    line="$(grep 'lgr relocation by position:' "$log" | tail -1)"
    if [ -z "$line" ]; then
      fail "no line 'lgr relocation by position' in $log"; return
    fi
    echo "  $(basename "$log"):$(echo "$line" | sed 's/^ *//')"
    n="$(echo "$line" | sed -n 's/.*position: parked \([0-9][0-9]*\) .*/\1/p')"
    s="$(echo "$line" | sed -n 's/.*, stayed \([0-9][0-9]*\),.*/\1/p')"
    l="$(echo "$line" | sed -n 's/.*kept for lack of a layer \([0-9][0-9]*\),.*/\1/p')"
    g="$(echo "$line" | sed -n 's/.*went to another process \([0-9][0-9]*\),.*/\1/p')"
    a="$(echo "$line" | sed -n 's/.*, nobody answered \([0-9][0-9]*\),.*/\1/p')"
    z="$(echo "$line" | sed -n 's/.*hit within the margin and nobody answered \([0-9][0-9]*\).*/\1/p')"
    if [ -z "$n" ] || [ -z "$s" ] || [ -z "$l" ] || [ -z "$g" ] || [ -z "$a" ] || [ -z "$z" ]; then
      fail "cannot read the relocation by position line of $log"; return
    fi
    [ "$z" -eq 0 ] || fail "relocation by position: $z particles parked with a local hit and no owner answered in $log"
    [ $((s + l + g + a)) -eq "$n" ] || fail "relocation by position: outcomes $s + $l + $g + $a do not add up to the $n parked in $log"
    key_check "$line" "$log"
  fi
}

# key_check LINE LOG: the "key order walks W, wrong K" part of a line
key_check() {
  local w k
  w="$(echo "$1" | sed -n 's/.*key order walks \([0-9][0-9]*\), wrong [0-9][0-9]*.*/\1/p')"
  k="$(echo "$1" | sed -n 's/.*key order walks [0-9][0-9]*, wrong \([0-9][0-9]*\).*/\1/p')"
  if [ -z "$w" ] || [ -z "$k" ]; then fail "no key order count in the relocation line of $2"; return; fi
  [ "$w" -gt 0 ] || fail "key order self-test ran no walk in $2"
  [ "$k" -eq 0 ] || fail "key order self-test: $k of $w walks wrong in $2"
}

#--- perturb mode: two MPI runs, plain and with MALLOC_PERTURB_=85 -------------
if [ "$MODE" = perturb ]; then
  nlost() { grep -c 'loosing particle adv' "$1"; }
  PERTURB_VALUE=85
  # value of MALLOC_PERTURB_ a process launched by mpirun sees, in brackets;
  # stderr is kept out of the value; $1 = plain | perturbed
  probe() {
    if [ "$1" = plain ]; then
      env -u MALLOC_PERTURB_ nice -n 19 mpirun --oversubscribe -np 1 sh -c 'echo "[${MALLOC_PERTURB_-}]"' 2> /dev/null
    else
      MALLOC_PERTURB_=$PERTURB_VALUE nice -n 19 mpirun --oversubscribe -np 1 -x MALLOC_PERTURB_ sh -c 'echo "[${MALLOC_PERTURB_-}]"' 2> /dev/null
    fi
  }
  echo "=== 1. $CASE on $NP processes, plain"
  seen="$(probe plain)"; probe_rc=$?
  echo "  MALLOC_PERTURB_ seen by a launched process (plain run): $seen"
  if [ "$probe_rc" != 0 ] || [ "$seen" != "[]" ]; then
    fail "the plain run would not be unperturbed (probe exit code $probe_rc, seen '$seen', expected '[]')"
    echo "LGR GATE: FAIL"; exit 1
  fi
  clean_outputs_mpi
  env -u MALLOC_PERTURB_ nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$STR" > "$HERE/$CASE.np$NP.log" 2>&1
  mpi_rc=$?
  if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.log"; then
    tail -5 "$HERE/$CASE.np$NP.log"
    fail "$CASE did not end on $NP processes (exit code $mpi_rc)"
    echo "LGR GATE: FAIL"; exit 1
  fi
  collect_dbg "$CASE.np$NP.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
  echo "  plain run ended"
  selftest_check "$HERE/$CASE.np$NP.log" "$NP"
  relocation_check "$HERE/$CASE.np$NP.log" "$NP"

  echo "=== 2. $CASE on $NP processes, MALLOC_PERTURB_=85"
  seen="$(probe perturbed)"; probe_rc=$?
  echo "  MALLOC_PERTURB_ seen by a launched process (perturbed run): $seen"
  if [ "$probe_rc" != 0 ] || [ "$seen" != "[$PERTURB_VALUE]" ]; then
    fail "MALLOC_PERTURB_ does not reach the processes started by mpirun (probe exit code $probe_rc, seen '$seen', expected '[$PERTURB_VALUE]')"
    echo "LGR GATE: FAIL"; exit 1
  fi
  clean_outputs_mpi
  MALLOC_PERTURB_=$PERTURB_VALUE nice -n 19 mpirun --oversubscribe -np "$NP" -x MALLOC_PERTURB_ shyfem "$STR" \
      > "$HERE/$CASE.np$NP.perturb.log" 2>&1
  mpi_rc=$?
  if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.perturb.log"; then
    tail -5 "$HERE/$CASE.np$NP.perturb.log"
    fail "$CASE did not end on $NP processes with MALLOC_PERTURB_ (exit code $mpi_rc)"
    echo "LGR GATE: FAIL"; exit 1
  fi
  collect_dbg "$CASE.np$NP.perturb.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
  echo "  perturbed run ended"
  selftest_check "$HERE/$CASE.np$NP.perturb.log" "$NP"
  relocation_check "$HERE/$CASE.np$NP.perturb.log" "$NP"

  echo "=== 3. compare the dump files byte for byte"
  D1="$HERE/$CASE.np$NP.dbg"; D2="$HERE/$CASE.np$NP.perturb.dbg"
  nfiles=0; ndiff=0
  for f in "$D1"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    nfiles=$((nfiles + 1)); b="$(basename "$f")"
    if [ ! -f "$D2/$b" ]; then echo "  missing in the perturbed run: $b"; ndiff=$((ndiff + 1))
    elif ! cmp -s "$f" "$D2/$b"; then echo "  differs: $b"; ndiff=$((ndiff + 1)); fi
  done
  for f in "$D2"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"
    if [ ! -f "$D1/$b" ]; then echo "  missing in the plain run: $b"; ndiff=$((ndiff + 1)); fi
  done
  echo "  $nfiles dump files compared, $ndiff differing or missing"
  echo "  'loosing particle adv' lines: plain $(nlost "$HERE/$CASE.np$NP.log"), perturbed $(nlost "$HERE/$CASE.np$NP.perturb.log")"
  [ "$nfiles" -gt 0 ] || fail "no dump file exists"
  [ "$ndiff" = 0 ] || fail "the dump files of the plain and the perturbed run differ"
  if [ "$rc" = 0 ]; then echo "LGR GATE: PASS"; else echo "LGR GATE: FAIL"; fi
  exit "$rc"
fi

#--- 1. serial run -----------------------------------------------------------
echo "=== 1. $CASE serial (mode $MODE)"
clean_outputs
nice -n 19 shyfem "$STR" > "$HERE/$CASE.serial.log" 2>&1
if ! grep -q "simulation end" "$HERE/$CASE.serial.log"; then
  tail -5 "$HERE/$CASE.serial.log"
  echo "LGR GATE: FAIL"; exit 1
fi
for ext in lgr.shy hydro.shy inf; do
  if [ -f "$HERE/$CASE.$ext" ]; then mv -f "$HERE/$CASE.$ext" "$HERE/$CASE.serial.$ext"
  elif [ "$ext" = lgr.shy ] && { [ "$MODE" = pos ] || [ "$MODE" = ids ]; }; then
    fail "serial run wrote no $CASE.lgr.shy"; echo "LGR GATE: FAIL"; exit 1
  else echo "  note: serial run wrote no $CASE.$ext"; fi
done
collect_dbg "$CASE.serial.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
echo "  serial run ended"
if [ "$DUMP" = 1 ]; then
  selftest_check "$HERE/$CASE.serial.log" 1
  relocation_check "$HERE/$CASE.serial.log" 1
fi

#--- 2. MPI run ------------------------------------------------------------------
echo "=== 2. $CASE on $NP processes"
clean_outputs_mpi
nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$STR" > "$HERE/$CASE.np$NP.log" 2>&1
mpi_rc=$?
if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.log"; then
  tail -5 "$HERE/$CASE.np$NP.log"
  fail "$CASE did not end on $NP processes (exit code $mpi_rc)"
  echo "LGR GATE: FAIL"; exit 1
fi
collect_dbg "$CASE.np$NP.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
echo "  MPI run ended"
if [ "$DUMP" = 1 ]; then
  selftest_check "$HERE/$CASE.np$NP.log" "$NP"
  relocation_check "$HERE/$CASE.np$NP.log" "$NP"
fi

#--- 3. comparison ---------------------------------------------------------------
echo "=== 3. compare ($MODE)"
case "$MODE" in
  flux)
    python3 "$HERE/lgr_dbg_compare.py" flux "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" "$@"
    crc=$?
    ;;
  part)
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by nearest "$@"
    crc=$?
    ;;
  handover)
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by key --handover --step "$STEP" "$@"
    crc=$?
    ;;
  floor)
    echo "  floors of $CASE: beyond $TOL at the last output $FLOOR_N, largest distance at any output $FLOOR_D"
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by key --max-beyond-last "$FLOOR_N" --max-largest "$FLOOR_D" "$@"
    crc=$?
    ;;
  pos|ids)
    A="$HERE/$CASE.serial.lgr.shy"; B="$HERE/$CASE.lgr.shy"
    if [ ! -f "$A" ] || [ ! -f "$B" ]; then
      echo "  missing particle file: serial $([ -f "$A" ] && echo yes || echo NO), MPI $([ -f "$B" ] && echo yes || echo NO)"
      crc=2
    else
      echo "  serial file:"; summary "$A"
      echo "  MPI file:";    summary "$B"
      if [ "$MODE" = pos ] && [ -n "$FLOOR_N" ]; then
        echo "  floors of $CASE: beyond $TOL at the last output $FLOOR_N, largest distance at any output $FLOOR_D"
        python3 "$HERE/lgr_compare.py" "$A" "$B" --mode pos --tol "$TOL" \
            --max-beyond-last "$FLOOR_N" --max-largest "$FLOOR_D" "$@"
        crc=$?
      elif [ "$MODE" = pos ]; then
        python3 "$HERE/lgr_compare.py" "$A" "$B" --mode pos --tol "$TOL" "$@"
        crc=$?
      else
        dims="$(python3 "$HERE/lgr_compare.py" "$A" --dims)"
        NEL="$(echo "$dims" | sed -n 's/.* nel \([0-9][0-9]*\) .*/\1/p')"
        NLV="$(echo "$dims" | sed -n 's/.* nlv \([0-9][0-9]*\)$/\1/p')"
        if [ -z "$NEL" ] || [ -z "$NLV" ]; then
          echo "  cannot read nel and nlv from the model header of $A: '$dims'"
          crc=2
        else
          echo "  basin of the serial file: $dims"
          python3 "$HERE/lgr_compare.py" "$A" "$B" --mode ids --same-counts \
              --nel "$NEL" --nlv "$NLV" "$@"
          crc=$?
        fi
      fi
    fi
    ;;
esac
case "$crc" in
  0) echo "  comparison: identical within the limits" ;;
  1) fail "$MODE comparison found differences (tool exit code 1)" ;;
  *) fail "$MODE comparison could not be made (tool exit code $crc: unreadable or incomplete input, for example an MPI particle file without output times)" ;;
esac

if [ "$rc" = 0 ]; then echo "LGR GATE: PASS"; else echo "LGR GATE: FAIL"; fi
exit "$rc"
