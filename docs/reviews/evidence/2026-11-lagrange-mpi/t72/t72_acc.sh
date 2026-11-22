#!/bin/bash
# Task 7.2 C3: the full acceptance run on the clean build of the head of
# lgr/s7-stops (built before this script: make clean + the usual OpenMPI build;
# this script does not build).  Every criterion AC1-AC11 on 2 and 4 processes,
# the cases of spec section 7 that the shipped cases and the driver show, and
# the supporting gates of the stage ends.  One model run at a time.  Based on
# the stage-6 final gates.  Every driver log and every model log of a gate is
# kept in $D (printed first; t72_acc3.sh takes it as its argument); the
# acceptance table is built from these logs (t72_extract.py $D).
#
# usage: t72_acc.sh REF_BIN_DIR FLOORS_RUNS_DIR
#   REF_BIN_DIR      the serial reference build of the guard (wt-lgr-ref3,
#                    commit 0fddec90, when it was run)
#   FLOORS_RUNS_DIR  the particle files of the floor runs, lgr_runs/ of
#                    testcases/examples/mar_menor/measure_lgr_floors.sh (AC8)
# Since the final fix round of the branch the driver passes --min-changed 1
# itself in mode handover on several processes; case C on 2 processes, which
# has no hand-over on the development machine's partition, then needs
# --min-changed 0 (the plain call below is the command as it was run).
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1; T=$W/testcases/examples/mar_menor
REF="${1:?usage: t72_acc.sh REF_BIN_DIR FLOORS_RUNS_DIR}"
FR="${2:?usage: t72_acc.sh REF_BIN_DIR FLOORS_RUNS_DIR}"
D=$(mktemp -d "${TMPDIR:-/tmp}/t72acc.XXXXXX") || exit 1
echo "scratch: $D   head: $(git -C "$W" rev-parse --short HEAD)   $(date '+%F %T %Z')"
cd "$W" || exit 1
[ -z "$(git status --porcelain)" ] || { echo "work tree not clean"; git status --porcelain | head; exit 1; }
echo "=== binary: $(readlink -f bin/shyfem), sha256 $(sha256sum src/shyfem/shyfem | cut -c1-16), libmpi.so.40: $(ldd src/shyfem/shyfem | grep -c 'libmpi.so.40'), built $(stat -c %y src/shyfem/shyfem | cut -c1-19); src changed since the commit before the head: $(git diff --name-only HEAD~1 HEAD -- src | wc -l) files"
export PATH=$W/bin:/usr/bin:$PATH
cd "$T" || exit 1
ls GRID/MM_geo.bas GRID/MM_coarse.bas > /dev/null || exit 1
git diff --quiet HEAD -- GRID/MM_coarse.bas && echo "GRID/MM_coarse.bas: the tracked file" || { echo "GRID/MM_coarse.bas differs from the tracked file"; exit 1; }
cleanstrip() { local f; for f in "$W/testcases/examples/restart_strip/partition.4.elem.grd" "$W/testcases/examples/restart_strip/partition.4.node.grd" "$W/testcases/examples/restart_strip/partition.2.elem.grd" "$W/testcases/examples/restart_strip/partition.2.node.grd"; do [ -f "$f" ] && rm -f "$f"; done; }

echo "=== $(date +%H:%M:%S) tool self-tests: $(bash test_lgr_compare.sh 2>&1 | tail -1) / $(bash test_lgr_dbg_compare.sh 2>&1 | tail -1) / $(python3 lgr_lgmean_compare.py --selftest 2>&1 | tail -1)"
nice -n 19 bash check_lgr_serial.sh "$REF" > "$D/guard.log" 2>&1
echo "=== $(date +%H:%M:%S) AC6/AC7 serial guard vs ref3: $(grep 'SERIAL GUARD' "$D/guard.log" | tail -1); DIFFERS lines: $(grep -c 'DIFFERS' "$D/guard.log")"
nice -n 19 bash check_lgr_serial.sh repro > "$D/repro.log" 2>&1
echo "=== $(date +%H:%M:%S) repro: $(tail -1 "$D/repro.log")"
for np in 2 4; do
  nice -n 19 bash check_mpi.sh $np > "$D/check_mpi.$np.log" 2>&1
  echo "=== $(date +%H:%M:%S) MPI gate (check_mpi.sh $np, with check 5): $(tail -1 "$D/check_mpi.$np.log")"
  cleanstrip
done

gate() {  # CASE NP MODE [options...]: run the driver, keep its log and the model logs
  local c=$1 np=$2 m=$3 tag; shift 3
  tag="$c.$np.$m"; [ -n "${TAGX:-}" ] && tag="$tag.$TAGX"
  rm -f "$T/$c.np$np.log" "$T/$c.serial.log" "$T/$c.np$np.perturb.log"
  timeout 1800 nice -n 19 bash check_lgr_mpi.sh $c $np $m "$@" > "$D/$tag.log" 2>&1; local rc=$?
  [ -f "$T/$c.np$np.log" ] && cp "$T/$c.np$np.log" "$D/$tag.mpi.log"
  [ -f "$T/$c.serial.log" ] && cp "$T/$c.serial.log" "$D/$tag.ser.log"
  [ -f "$T/$c.np$np.perturb.log" ] && cp "$T/$c.np$np.perturb.log" "$D/$tag.mpi2.log"
  if [ -n "${SAVE:-}" ]; then
    [ -f "$T/$c.serial.lgr.shy" ] && cp "$T/$c.serial.lgr.shy" "$D/$tag.serial.lgr.shy"
    [ -f "$T/$c.lgr.shy" ] && cp "$T/$c.lgr.shy" "$D/$tag.mpi.lgr.shy"
  fi
  printf '%-9s %2s %-8s exit %d: %s\n' $c $np $m $rc "$(grep 'LGR GATE' "$D/$tag.log" | tail -1)"
  grep -E 'rule: jump|FAIL' "$D/$tag.log" | grep -v 'LGR GATE' | head -3 | cut -c1-200 | sed 's/^/      /'
}

echo "=== $(date +%H:%M:%S) AC1: flux (A, B, C on 2, 4)"
for c in mm_lgr_a mm_lgr_b mm_lgr_c; do for np in 2 4; do gate $c $np flux; done; done
echo "=== $(date +%H:%M:%S) AC2 ids and AC3 pos (particle file; A, B, C, E, W on 2, 4)"
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr_w; do for np in 2 4; do
  gate $c $np ids
  if [ $c = mm_lgr_a ]; then SAVE=1 gate $c $np pos; else gate $c $np pos; fi
done; done
echo "=== $(date +%H:%M:%S) AC3 positions in the dump against the floors (A, B, C, E, W on 2, 4)"
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr_w; do for np in 2 4; do gate $c $np floor; done; done
echo "=== $(date +%H:%M:%S) AC3 hand-over fidelity and AC11 (A, B, C, W on 2, 4; B on 8 for spec section 7 cases 1 and 8)"
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_w; do gate $c 2 handover; gate $c 4 handover --min-changed 1; done
gate mm_lgr_b 8 handover --min-changed 1
echo "=== $(date +%H:%M:%S) AC4: case D ids (LGR_LEVDBG=3) on 2, 4"
for np in 2 4; do ( export LGR_LEVDBG=3 SAVE=1; gate mm_lgr $np ids ); done
echo "=== $(date +%H:%M:%S) AC5: case D mean and spread per type (not gated)"
python3 "$EV/../ac5_stats.py" S1="$D/mm_lgr.2.ids.serial.lgr.shy" S2="$D/mm_lgr.4.ids.serial.lgr.shy" np2="$D/mm_lgr.2.ids.mpi.lgr.shy" np4="$D/mm_lgr.4.ids.mpi.lgr.shy" > "$D/ac5.log" 2>&1
echo "AC5: exit $?"; cat "$D/ac5.log"
echo "=== $(date +%H:%M:%S) AC8: lgrelab -lgmean, case A, serial against 2 and 4 processes, against the six perturbed serial runs"
for np in 2 4; do
  python3 lgr_lgmean_compare.py "$D/mm_lgr_a.$np.pos.serial.lgr.shy" "$D/mm_lgr_a.$np.pos.mpi.lgr.shy" "$FR/mm_lgr_a.r0.lgr.shy" "$FR"/mm_lgr_a.r[+-]*.lgr.shy > "$D/ac8.$np.log" 2>&1
  echo "AC8 $np processes: exit $?: $(grep -E 'values compared|within' "$D/ac8.$np.log" | tail -2 | tr '\n' ' ') $(tail -1 "$D/ac8.$np.log")"
done
cmp "$D/mm_lgr_a.2.pos.serial.lgr.shy" "$FR/mm_lgr_a.r0.lgr.shy" && echo "AC8: the serial file equals the base run of floors_runs (byte for byte)"
echo "=== $(date +%H:%M:%S) AC10: stops on 2 and 4"
for np in 2 4; do TMPDIR="$D" gate mm_lgr_a $np stops; grep -E '^  [a-z0-9]+: (ok|FAIL);' "$D/mm_lgr_a.$np.stops.log" | cut -c1-200; done
echo "=== $(date +%H:%M:%S) spec section 7, case 5 (ranks without particles) and the release split between processes (W)"
gate mm_lgr_a 4 part --by key --tol 0 --first-only --elem --ranks-empty-ok
python3 "$EV/../release_owners.py" "$T/mm_lgr_a.np4.dbg" 2>&1 | head -5
for np in 2 4; do
  gate mm_lgr_w $np part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids
  python3 "$EV/../release_owners.py" "$T/mm_lgr_w.np$np.dbg" 2>&1 | head -5
done
echo "=== $(date +%H:%M:%S) perturbed twins (A, B, C, E, W on 4)"
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr_w; do gate $c 4 perturb; done

R="$D/runs"; mkdir "$R"
mkrun() {  # CASE NAME LINES... -> folder with links and an STR with the lines after $para
  local c=$1 n=$2 d="$R/$2"; shift 2; mkdir "$d"
  ln -s "$T/GRID" "$d/GRID"; ln -s "$T/INPUT" "$d/INPUT"; ln -s "$T/release_areas.txt" "$d/release_areas.txt"
  awk -v add="$*" '{ print } !done && /^\$para[ \t\r]*$/ { n = split(add, a, ";"); for (i = 1; i <= n; i++) print "        " a[i]; done = 1 }' "$T/$c.str" > "$d/$c.str"
  echo "$d"
}
echo "=== $(date +%H:%M:%S) spec section 7, case 9: OpenMP (A, C, E with nomp = -1, levdbg = 3, 4 processes, OMP_NUM_THREADS=4; two runs and a one-thread run)"
for c in mm_lgr_a mm_lgr_c mm_lgr_e; do
  for v in omp1 omp2; do
    d=$(mkrun $c ${c}_$v "levdbg = 3;nomp = -1")
    ( cd "$d" && OMP_NUM_THREADS=4 nice -n 19 mpirun --oversubscribe -np 4 -x OMP_NUM_THREADS shyfem $c.str > run.log 2>&1 )
  done
  d=$(mkrun $c ${c}_one "levdbg = 3")
  ( cd "$d" && OMP_NUM_THREADS=1 nice -n 19 mpirun --oversubscribe -np 4 -x OMP_NUM_THREADS shyfem $c.str > run.log 2>&1 )
  n=0; s12=0; s1o=0
  for f in "$R/${c}_omp1"/lgrdbg.*.txt; do
    b=$(basename "$f"); n=$((n + 1))
    cmp -s "$f" "$R/${c}_omp2/$b" && s12=$((s12 + 1))
    cmp -s "$f" "$R/${c}_one/$b" && s1o=$((s1o + 1))
  done
  no=$(ls "$R/${c}_one"/lgrdbg.*.txt | wc -l)
  echo "$c: used OMP threads: $(grep -h 'used OMP threads' "$R/${c}_omp1/run.log" | head -1 | tr -s ' '), $(grep -h 'used OMP threads' "$R/${c}_omp2/run.log" | head -1 | tr -s ' '), one-thread run: $(grep -h 'used OMP threads' "$R/${c}_one/run.log" | head -1 | tr -s ' '); ended $(grep -c 'simulation end' "$R/${c}_omp1/run.log") $(grep -c 'simulation end' "$R/${c}_omp2/run.log") $(grep -c 'simulation end' "$R/${c}_one/run.log"); dump files: $n (one-thread $no); run 1 = run 2: $s12; run 1 = one-thread: $s1o; hand-overs: $(grep -h 'lgr hand-over: particles' "$R/${c}_omp1/run.log" | sed 's/.*cut-off side: \([0-9]*\), by position: \([0-9]*\),.*/side \1, position \2/')"
  rm -f "$R/${c}"_*/*.shy
done
echo "=== $(date +%H:%M:%S) consistency check: fault runs (case A, 4 processes, levdbg 2; each must abort with exit 33) and plain runs"
for f in DROP DUP; do
  d=$(mkrun mm_lgr_a fault_$f "levdbg = 2")
  ( cd "$d" && env LGR_TEST_$f=2 nice -n 19 mpirun --oversubscribe -np 4 -x LGR_TEST_$f shyfem mm_lgr_a.str > run.log 2>&1 ); rc=$?
  echo "LGR_TEST_$f=2: exit $rc; ended $(grep -c 'simulation end' "$d/run.log"); messages: $(grep -h 'lgr_mpi_check_consistency:' "$d/run.log" | sed 's/^ *//' | sort -u | cut -c1-110 | head -3 | tr '\n' ';')"
done
for run in "mm_lgr 2" "mm_lgr 4" "mm_lgr_e 4"; do
  set -- $run; d=$(mkrun $1 plain_$1_np$2 "levdbg = 2")
  ( cd "$d" && nice -n 19 mpirun --oversubscribe -np $2 shyfem $1.str > run.log 2>&1 ); rc=$?
  echo "$1 np$2 levdbg 2: exit $rc; ended $(grep -c 'simulation end' "$d/run.log"); check messages $(grep -c 'lgr_mpi_check_consistency' "$d/run.log"); lost-particle lines $(grep -c 'loosing particle' "$d/run.log")"
  rm -f "$d"/*.shy
done
cleanstrip
echo "status after: [$(git -C "$W" status --porcelain | head -5)]"
echo "=== $(date +%H:%M:%S) DONE (logs in $D)"
