#!/bin/bash
#------------------------------------------------------------------------
# Lagrangian MPI gate: one test case run serially and on NP processes, the
# results compared with the matching tool.
#
# Usage:  ./check_lgr_mpi.sh CASE NP MODE [EXTRA ARGS FOR THE TOOL ...]
#
#   CASE  mm_lgr_a | mm_lgr_b | mm_lgr_c | mm_lgr_e | mm_lgr_w | mm_lgr
#         (a, b, c, e, w are accepted as short names; mm_lgr_w is case A
#         with one release polygon around the whole basin)
#   NP    number of MPI processes of the second run
#   MODE  flux   debug dump of the element fluxes, serial vs MPI
#         part   debug dump of the particles (per output time), serial vs
#                MPI, paired by key (by position for a dump without keys)
#         handover  debug dump of the particles (as part), then the hand-over
#                fidelity check of lgr_dbg_compare.py: --by key --handover,
#                the particles that changed process against those that did
#                not (--step 6e-8, case B 0.25: one single-precision step);
#                for NP > 1 the driver passes --min-changed 1 (a check in
#                which no particle changes process fails instead of passing
#                silently); a --min-changed among the caller's arguments
#                replaces it
#         pos    final particle file: positions against the case's floors
#                (the table below, as floor), layers, types, times
#         ids    final particle file: the ids of each block, the counts per
#                block (--same-counts), valid cells (--nel, --nlv of the
#                basin)
#         perturb  two MPI runs (no serial run) with the debug dump, one
#                plain and one with MALLOC_PERTURB_=85; every dump file of
#                the two runs must be byte-identical (dependence of the
#                result on memory that malloc hands out)
#         floor  debug dump of the particles (as part), compared by key with
#                the case's --tol and its position floors (the table below):
#                --max-beyond-last and --max-largest of lgr_dbg_compare.py
#         stops  (case mm_lgr_a only) the options that are not supported on
#                several processes: for each of the twelve rows (ilagr3,
#                lbeach, artype, ldecay, lgrini, ised, ilarv, icnn, lgrpps,
#                lgrtrj, rwhpar = -1 in place of the case's rwhpar = 0,
#                ipvert = -2) a scratch copy of the STR file with that
#                option set (made by
#                sed, in this folder, with a run name of its own, removed at
#                the end; lgrini and lgrtrj name a file that does not exist,
#                the MPI run must stop before it is opened) is run on NP
#                processes (NP > 1) and serially, each with a timeout of
#                600 s.  NP processes: exit code 33 exactly (the code
#                shympi_abort_internal passes to MPI_ABORT; the project
#                requires Open MPI, whose mpirun returns it; any other
#                code, the timeout's 124 included, fails the row), the line
#                "Lagrangian option NAME is not supported with MPI" and the
#                line "run on one process, or remove NAME" once each, no
#                SIGFPE, SIGSEGV or "Fortran runtime" line, no particle
#                file.  Serial: the MPI message
#                must never appear; the outcome (ended, or its own failure,
#                with its exit code) is printed per row; a serial run that
#                times out fails the row (its outcome is unknown).  Needs no
#                serial reference run.  The logs go to a
#                folder made with mktemp under ${TMPDIR:-/tmp}: removed at
#                the end when every row passed, kept (its path is printed)
#                when a row failed.
#
# Every model run the driver launches (the serial run, the MPI run, both
# MPI runs of perturb) has ended only if its launcher exits with 0 and its
# log has "simulation end"; otherwise the gate fails.  Mode stops expects
# a non-zero exit instead (see there).
# The serial outputs are renamed to CASE.serial.* (lgr.shy, hydro.shy, inf,
# log); the MPI log is CASE.npN.log.  For flux and part the run uses a
# temporary copy of the STR file with "levdbg = 3" right after the $para
# line (the run name inside the file is unchanged, so the output names are
# the same); the debug files of each run end up in CASE.serial.dbg/ and
# CASE.npN.dbg/, both made fresh by every call.
#
# LGR_LEVDBG (environment variable, modes pos and ids only; unset by
# default, and then nothing changes): 2 or 3 runs both runs at that levdbg
# through the same temporary STR copy.  At 2 the built-in consistency check
# (lgr_mpi_check_consistency) is active on several processes; at 3 also the
# debug dump (kept in CASE.serial.dbg/ and CASE.npN.dbg/), the side
# self-test and the re-location self-checks below, which are then required
# as in the dump modes (the MPI log's "lgr relocation by position" line is
# printed).  Example: LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr 4 ids
# Consistency check: whenever the driver sets levdbg (the dump modes, or
# LGR_LEVDBG), the log of a run on several processes must hold no line of
# lgr_mpi_check_consistency: it writes only when a check fails (and then
# aborts the run).
#
# Note: flux uses the relative default limit of lgr_dbg_compare.py (1e-5) for
# every case; the per-case --tol below applies to pos and part only.
# Limits: the geographic cases use --tol 1e-5, the Cartesian case mm_lgr_b
# --tol 2 (for pos and part).  The flux comparison is relative and keeps
# the default of lgr_dbg_compare.py.  Part pairs the particles by their key
# (--by key) when both dumps carry the six key columns, as every dump since
# stage 3 does, and by position (--by nearest) for an older dump without
# them (nearest pairs by position, which can pair a particle with another
# one's partner, and above FULL_EDGES pairs of a time block it is only an
# approximation of its own rule: see lgr_dbg_compare.py).  Arguments after
# MODE come last on the tool command line and so replace the defaults, for
# example
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
# compared only for pairs in the same element) and the case's tt floor
# (--max-tt-differ: particles whose time tt differs).  The ids per block,
# the output times, layers, z, types, sinking and custom values gate
# exactly as without floors.
# ids: lgr_compare.py --mode ids --same-counts --nel N --nlv L, with N and L
# from the model header of the serial particle file (lgr_compare.py --dims:
# the basin's element count and the number of layers).  For NP > 1 it also
# runs lgr_inf_compare.py on the two info files: as many energy lines (same
# times) and the same lagrange_nbdy value (the global particle count) at
# every step; for mm_lgr (random walk, closed basin) the count must also be
# 145 at every step.
#
# handover: the particles of the two runs are paired by their key (the last
# six columns of the dump); the statistic and the rule (a jump test against
# the noise of the particles that stayed, and a Poisson count test) are
# described in the docstring of lgr_dbg_compare.py.  The distances above the
# limit of the part mode are printed, not gated.  Arguments after MODE come
# last, so --step, --jump-factor, --jump-floor, --quantile and --min-changed
# can be given or replaced.  For NP > 1 the default is --min-changed 1 (at
# least one pair of the "changed process" group).  Where a partition makes
# no particle change process the default fails (case C on 2 processes with
# the METIS partition of the development machine: no hand-over at all);
# --min-changed 0 among the caller's arguments replaces it.
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
  echo "usage: [LGR_LEVDBG=2|3] $0 CASE NP MODE [tool args ...]   (CASE: mm_lgr_a|b|c|e|w|mm_lgr, MODE: flux|part|handover|floor|pos|ids|perturb|stops)"
  exit 2
}

[ $# -ge 3 ] || usage
CASE="$1"; NP="$2"; MODE="$3"; shift 3
case "$CASE" in
  a|b|c|e|w) CASE="mm_lgr_$CASE" ;;
  mm_lgr_a|mm_lgr_b|mm_lgr_c|mm_lgr_e|mm_lgr_w|mm_lgr) ;;
  *) echo "unknown case '$CASE'"; usage ;;
esac
case "$NP" in ''|*[!0-9]*) echo "NP must be a number"; usage ;; esac
[ "$NP" -ge 1 ] || usage
case "$MODE" in flux|part|handover|floor|pos|ids|perturb|stops) ;; *) echo "unknown mode '$MODE'"; usage ;; esac
LEVDBG_ENV="${LGR_LEVDBG:-}"
if [ -n "$LEVDBG_ENV" ]; then
  case "$MODE" in pos|ids) ;; *) echo "LGR_LEVDBG applies to the modes pos and ids only"; usage ;; esac
  case "$LEVDBG_ENV" in 2|3) ;; *) echo "LGR_LEVDBG must be 2 or 3"; usage ;; esac
fi
if [ "$CASE" = mm_lgr_b ]; then TOL=2; STEP=0.25; else TOL=1e-5; STEP=6e-8; fi

# Position floors (mode floor): particles beyond --tol at the last output and
# the largest distance at any output, each the envelope of six serial runs
# whose wind drag is changed by up to a relative 1e-5 (degrees for A, C, E,
# metres for B), measured with measure_lgr_floors.sh (this folder).  Source:
# docs/reviews/2026-11-lagrange-mpi-acceptance.md, section "Task 3.7", table
# "Position floors on the new reference" (measured on the reference build
# wt-lgr-ref3, commit 0fddec90; its log is floors_ref3.log in
# docs/reviews/evidence/2026-11-lagrange-mpi/).  The distances are the
# measured envelopes rounded UP, never below the measurement: A 2.9734e-3 ->
# 2.98e-3, B 181.75 -> 182, C 7.1106e-3 -> 7.12e-3, E 4.2915e-3 -> 4.3e-3
# (until Task 5.1 A and C were rounded down, 2.97e-3 and 7.1e-3, so that
# perturbed serial runs exceeded them).  Never change a value to make a run
# pass.  Mode pos uses the same floors on the particle file, and FLOOR_T,
# the tt floor: the most particles whose time tt differs from the base run
# in one of the six perturbed runs, measured on their particle files (the
# files measure_lgr_floors.sh writes into lgr_runs/ of its scratch folder;
# lgr_compare.py --mode pos):
# A 0, B 2 (particles that leave the basin one time step apart), C 0, E 0.
# mm_lgr_w (Task 6.1, measured the same way on wt-lgr-ref3 with the inputs
# of commit 6b514083, log floors_w.log in the same evidence folder):
# 37 / 4.3113e-3 -> 4.32e-3 / tt 1
# (particle 46 comes to rest in the dry element 870 in every run, at a time
# tt between 327,900 and 329,100 s that differs by a few steps).
# mm_lgr (#225, PROPOSED 2026-11-22, awaiting the owner's approval: the
# random walk, rwhpar = 0.5, repeatable since its draws come from
# per-particle streams; measured the same way with the build of #225, bin
# of wt-lgr on the inputs of commit b0cd1972, by key; log floors_mm_lgr.log
# in the same evidence folder):
# 82 / 1.4268e-1 -> 1.43e-1 / tt 0
# (observed in the run with -1e-5: particle 40 is in another element than
# in the base run from t = 162,000 s, stays in element 401 from t = 262,800
# to 288,000 s while the base run's particle moves on, and is 0.143 degrees
# away at t = 338,400 s; the envelope is of the size of the basin. Measured
# against serial on 2, 4 and 8 processes: 0, 2 and 11 particles beyond
# 1e-5 at the last output, largest distance 0, 1.4e-4 and 2.1e-2 degrees.
# The binary of b0cd1972, whose walk is not seeded, fails it on 4: 145
# particles, 0.211 degrees.)
case "$CASE" in
  mm_lgr_a) FLOOR_N=78; FLOOR_D=2.98e-3; FLOOR_T=0 ;;
  mm_lgr_b) FLOOR_N=48; FLOOR_D=182; FLOOR_T=2 ;;
  mm_lgr_c) FLOOR_N=19; FLOOR_D=7.12e-3; FLOOR_T=0 ;;
  mm_lgr_e) FLOOR_N=33; FLOOR_D=4.3e-3; FLOOR_T=0 ;;
  mm_lgr_w) FLOOR_N=37; FLOOR_D=4.32e-3; FLOOR_T=1 ;;
  mm_lgr)   FLOOR_N=82; FLOOR_D=1.43e-1; FLOOR_T=0 ;;	# PROPOSED (#225)
  *) FLOOR_N=""; FLOOR_D=""; FLOOR_T="" ;;
esac
if [ "$MODE" = floor ] && [ -z "$FLOOR_N" ]; then
  echo "no position floor for $CASE"; usage
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
  # scratch STR and outputs of mode stops (names carry this process id)
  for f in "$HERE"/stops_*_$$.*; do
    [ -e "$f" ] && rm -f "$f"
  done
  rm -f "$HERE/no_such_file_stops.lgr" "$HERE/no_such_file_stops.trj"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

STR="$CASE.str"
DUMP=0		# 1: the runs write the debug dump (levdbg = 3), kept and checked
LEVDBG=""	# levdbg the driver sets in the temporary STR ("": none)
if [ "$MODE" = flux ] || [ "$MODE" = part ] || [ "$MODE" = handover ] || [ "$MODE" = floor ] || [ "$MODE" = perturb ]; then
  DUMP=1; LEVDBG=3
elif [ -n "$LEVDBG_ENV" ]; then
  LEVDBG="$LEVDBG_ENV"
  [ "$LEVDBG" = 3 ] && DUMP=1
fi
if [ -n "$LEVDBG" ]; then
  if grep -q '^[[:space:]]*levdbg' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str already sets levdbg; refusing to add a second one"
    exit 1
  fi
  if ! grep -q '^\$para[[:space:]]*$' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str has no line with only \$para"
    exit 1
  fi
  TMPSTR="$HERE/$CASE.lgrdbg.$$.str"
  awk -v lv="$LEVDBG" '{ print } !done && /^\$para[ \t\r]*$/ { print "        levdbg = " lv; done = 1 }' \
      "$HERE/$CASE.str" > "$TMPSTR" || { echo "LGR GATE FAIL: cannot write $TMPSTR"; exit 1; }
  STR="$(basename "$TMPSTR")"
  [ -n "$LEVDBG_ENV" ] && echo "  LGR_LEVDBG=$LEVDBG_ENV: both runs at levdbg = $LEVDBG"
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

# dump_has_keys DIR: true if DIR has particle dumps and every particle line
# of them has the 16 columns of a dump with the key (10 without it)
dump_has_keys() {
  local f n=0
  for f in "$1"/lgrdbg.part.*.txt; do [ -e "$f" ] && n=$((n + 1)); done
  [ "$n" -gt 0 ] || return 1
  awk '!/^#/ && NF && NF != 16 { bad = 1; exit } END { exit bad }' "$1"/lgrdbg.part.*.txt
}

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

# consistency_check LOG NPROC: with levdbg set by the driver, a run on several
# processes has the consistency check active, and the check writes a line
# only when it fails (see header); no such line is allowed
consistency_check() {
  local log="$1" np="$2" n
  [ -n "$LEVDBG" ] && [ "$np" -gt 1 ] || return 0
  n="$(grep -c 'lgr_mpi_check_consistency' "$log")"
  if [ "$n" -gt 0 ]; then
    fail "consistency check wrote $n lines in $log"
    grep 'lgr_mpi_check_consistency' "$log" | sort -u | head -5 | sed 's/^/    /'
  else
    echo "  $(basename "$log"): consistency check (levdbg = $LEVDBG) silent"
  fi
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
  consistency_check "$HERE/$CASE.np$NP.log" "$NP"

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
  consistency_check "$HERE/$CASE.np$NP.perturb.log" "$NP"

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

#--- stops mode: options that stop on several processes ---------------------
if [ "$MODE" = stops ]; then
  [ "$CASE" = mm_lgr_a ] || { echo "mode stops needs the case mm_lgr_a"; usage; }
  [ "$NP" -gt 1 ] || { echo "mode stops needs NP > 1"; usage; }
  [ -z "$LEVDBG_ENV" ] || { echo "LGR_LEVDBG does not apply to mode stops"; usage; }
  # one row: NAME, then the sed expression that sets it ("%" is no part of
  # any text below); lines are added after "ilagr = 1" of the $lagrg section
  ADD='s/^\([ \t]*\)ilagr = 1[ \t]*$/&\n\1'
  STOPS_NAMES="ilagr3 lbeach artype ldecay lgrini ised ilarv icnn lgrpps lgrtrj rwhpar ipvert"
  stops_expr() {
    case "$1" in
      ilagr3) echo 's/^\([ \t]*\)ilagr = 1[ \t]*$/\1ilagr = 3/' ;;
      # the case sets rwhpar = 0 further down in $lagrg: replace that line
      # (a line added after ilagr = 1 would be overridden by it)
      rwhpar) echo 's/^\([ \t]*\)rwhpar = 0[ \t]*$/\1rwhpar = -1/' ;;
      ipvert) echo "${ADD}ipvert = -2/" ;;
      lbeach) echo "${ADD}lbeach = 0.5/" ;;
      artype) echo "${ADD}artype = 1/" ;;
      ldecay) echo "${ADD}ldecay = 3600/" ;;
      lgrini) echo "${ADD}lgrini = 'no_such_file_stops.lgr'/" ;;
      ised)   echo "${ADD}ised = 1/" ;;
      ilarv)  echo "${ADD}ilarv = 1/" ;;
      lgrtrj) echo "${ADD}lgrtrj = 'no_such_file_stops.trj'/" ;;
      icnn)   echo '$a\\n$connec\n        icnn = 1\n$end' ;;
      lgrpps) echo '$a\\n$bound1\n        kbound = 218\n        ibtyp = 3\n        boundn = '"'INPUT/river.txt'"'\n        lgrpps = 1\n$end' ;;
    esac
  }
  # the text of the message names the option as written in the STR file
  stops_label() {
    case "$1" in
      ilagr3) echo "ilagr = 3" ;;
      icnn)   echo "icnn" ;;
      rwhpar) echo "rwhpar < 0" ;;
      ipvert) echo "ipvert < -1" ;;
      *)      echo "$1" ;;
    esac
  }
  SCR="$(mktemp -d "${TMPDIR:-/tmp}/lgrstops.XXXXXX")" || exit 1
  [ "$(grep -c "^[[:space:]]*$CASE[[:space:]]*$" "$HERE/$CASE.str")" = 1 ] || { echo "LGR GATE FAIL: cannot find the run name line of $CASE.str"; exit 1; }
  echo "=== stops: $CASE, $NP processes and serial (logs in $SCR)"
  for opt in $STOPS_NAMES; do
    RUN="stops_${opt}_$$"
    lab="$(stops_label "$opt")"
    expr="$(stops_expr "$opt")"
    sed -e "s/^\([ \t]*\)$CASE[ \t]*\$/\1$RUN/" -e "$expr" "$HERE/$CASE.str" > "$HERE/$RUN.str" \
      || { fail "cannot write $RUN.str"; continue; }
    if sed -e "$expr" "$HERE/$CASE.str" | cmp -s - "$HERE/$CASE.str"; then fail "$opt: the sed expression changed nothing"; fi
    row_ok=1
    # --- NP processes
    timeout 600 nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$RUN.str" > "$SCR/$opt.np$NP.log" 2>&1
    mrc=$?
    n1="$(grep -c "Lagrangian option $lab is not supported with MPI" "$SCR/$opt.np$NP.log")"
    n2="$(grep -c "run on one process, or remove $lab" "$SCR/$opt.np$NP.log")"
    nbadsig="$(grep -c 'SIGFPE\|SIGSEGV\|Fortran runtime' "$SCR/$opt.np$NP.log")"
    nfile=0; [ -e "$HERE/$RUN.lgr.shy" ] && nfile=1
    if [ "$mrc" = 124 ]; then row_ok=0; echo "  $opt: $NP processes: timed out after 600 s (exit 124; the run must stop promptly with exit 33)"
    elif [ "$mrc" != 33 ]; then row_ok=0; echo "  $opt: $NP processes: exit code $mrc (expected 33, the abort code of shympi_abort_internal)"; fi
    [ "$n1" = 1 ] || { row_ok=0; echo "  $opt: $NP processes: message seen $n1 times (expected once)"; }
    [ "$n2" = 1 ] || { row_ok=0; echo "  $opt: $NP processes: 'run on one process' line seen $n2 times (expected once)"; }
    [ "$nbadsig" = 0 ] || { row_ok=0; echo "  $opt: $NP processes: $nbadsig SIGFPE/SIGSEGV/Fortran runtime lines"; }
    [ "$nfile" = 0 ] || { row_ok=0; echo "  $opt: $NP processes: particle file written"; }
    for f in "$HERE/$RUN".*; do [ "$f" = "$HERE/$RUN.str" ] || rm -f "$f"; done
    # --- serial
    timeout 600 nice -n 19 shyfem "$RUN.str" > "$SCR/$opt.serial.log" 2>&1
    src=$?
    if grep -q 'is not supported with MPI' "$SCR/$opt.serial.log"; then
      row_ok=0; echo "  $opt: serial: the MPI message appears"
    fi
    if [ "$src" = 124 ]; then
      row_ok=0; sout="timed out after 600 s (exit 124)"
      echo "  $opt: serial: timed out after 600 s (exit 124): its outcome is unknown"
    elif grep -q 'simulation end' "$SCR/$opt.serial.log"; then sout="ended (exit $src)"
    elif grep -q 'Program received signal' "$SCR/$opt.serial.log"; then
      sout="own failure (exit $src): $(grep -m1 'Program received signal' "$SCR/$opt.serial.log" | cut -c1-60)"
    else sout="own failure (exit $src): $(grep -v '^[[:space:]]*$' "$SCR/$opt.serial.log" | tail -1 | cut -c1-70)"; fi
    rm -f "$HERE/no_such_file_stops.lgr" "$HERE/no_such_file_stops.trj"	# a serial run may create it
    for f in "$HERE/$RUN".*; do [ -e "$f" ] && rm -f "$f"; done
    if [ "$row_ok" = 1 ]; then st=ok; else st=FAIL; rc=1; fi
    echo "  $opt: $st; $NP processes exit $mrc, message x$n1, advice x$n2, signals $nbadsig, particle file $nfile; serial: $sout"
  done
  if [ "$rc" = 0 ]; then
    rm -rf "$SCR"
    echo "LGR GATE: PASS"
  else
    echo "logs of the failed rows kept in $SCR"
    echo "LGR GATE: FAIL"
  fi
  exit "$rc"
fi

#--- 1. serial run -----------------------------------------------------------
echo "=== 1. $CASE serial (mode $MODE)"
clean_outputs
nice -n 19 shyfem "$STR" > "$HERE/$CASE.serial.log" 2>&1
ser_rc=$?
if [ "$ser_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.serial.log"; then
  tail -5 "$HERE/$CASE.serial.log"
  fail "$CASE did not end serially (exit code $ser_rc)"
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
  grep 'lgr_mpi_check_consistency' "$HERE/$CASE.np$NP.log" | sort -u | head -5 | sed 's/^/    /'
  fail "$CASE did not end on $NP processes (exit code $mpi_rc)"
  echo "LGR GATE: FAIL"; exit 1
fi
collect_dbg "$CASE.np$NP.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
echo "  MPI run ended"
if [ "$DUMP" = 1 ]; then
  selftest_check "$HERE/$CASE.np$NP.log" "$NP"
  relocation_check "$HERE/$CASE.np$NP.log" "$NP"
fi
consistency_check "$HERE/$CASE.np$NP.log" "$NP"

#--- 3. comparison ---------------------------------------------------------------
echo "=== 3. compare ($MODE)"
case "$MODE" in
  flux)
    python3 "$HERE/lgr_dbg_compare.py" flux "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" "$@"
    crc=$?
    ;;
  part)
    # by key when both dumps carry the six key columns (every dump since
    # stage 3), by position (--by nearest) for an older dump
    BY=nearest
    if dump_has_keys "$HERE/$CASE.serial.dbg" && dump_has_keys "$HERE/$CASE.np$NP.dbg"; then BY=key; fi
    echo "  part: pairs --by $BY (a --by among the caller's arguments replaces it)"
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by "$BY" "$@"
    crc=$?
    ;;
  handover)
    # on several processes at least one pair must change process (the
    # caller's --min-changed comes later on the command line and wins)
    MINCH=""
    if [ "$NP" -gt 1 ]; then
      MINCH="--min-changed 1"
      case " $* " in
        *" --min-changed "*|*" --min-changed="*)
          echo "  hand-over check: the caller's --min-changed replaces the default 1" ;;
        *) echo "  hand-over check: --min-changed 1 (default for $NP processes)" ;;
      esac
    fi
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by key --handover --step "$STEP" $MINCH "$@"
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
        echo "  floors of $CASE: beyond $TOL at the last output $FLOOR_N, largest distance at any output $FLOOR_D, particles with another tt $FLOOR_T"
        python3 "$HERE/lgr_compare.py" "$A" "$B" --mode pos --tol "$TOL" \
            --max-beyond-last "$FLOOR_N" --max-largest "$FLOOR_D" \
            --max-tt-differ "$FLOOR_T" "$@"
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

# ids: also the info file (only rank 0 writes it, the global particle count)
if [ "$MODE" = ids ] && [ "$NP" -gt 1 ]; then
  INFARGS=""
  [ "$CASE" = mm_lgr ] && INFARGS="--nbdy 145"
  if [ -f "$HERE/$CASE.serial.inf" ] && [ -f "$HERE/$CASE.inf" ]; then
    python3 "$HERE/lgr_inf_compare.py" "$HERE/$CASE.serial.inf" "$HERE/$CASE.inf" $INFARGS \
      || fail "the info file of $NP processes differs from the serial one (lgr_inf_compare.py)"
  else
    fail "missing info file: serial $([ -f "$HERE/$CASE.serial.inf" ] && echo yes || echo NO), MPI $([ -f "$HERE/$CASE.inf" ] && echo yes || echo NO)"
  fi
fi

if [ "$rc" = 0 ]; then echo "LGR GATE: PASS"; else echo "LGR GATE: FAIL"; fi
exit "$rc"
