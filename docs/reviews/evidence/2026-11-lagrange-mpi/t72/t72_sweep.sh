#!/bin/bash
# Task 7.2 C4: the 4-process sweep of 2026-11-21 (memory note
# project_mpi_sweep_2026-11-21, recipe of mpisweep.sh / eutrosweep.sh), rerun on
# the head of lgr/s7-stops.  Differences from the recipe, and why:
#  - binary: the clean build of this checkout (bin/; not a main worktree);
#    the EUTRO + mercury build in a `git archive HEAD` export (not a worktree
#    of the live tree)
#  - test folders: `git archive HEAD testcases/examples` (tracked files only;
#    the work tree holds outputs of earlier runs)
#  - init adds the geographic basin of the particle cases (shypre -noopti
#    MM_geo.grd), which make init does not build
#  - the serial and the 4-process run of a case run one after the other (the
#    machine rule: at most two model runs at a time; C3 runs beside this)
#  - mm_lgr and the particle cases added since (mm_lgr_a/b/c/e/w) get the
#    600 s timeout of the restart writers, so that load cannot turn an end
#    into "still stepping"
#  - every case that ends in both modes: the .inf energy lines serial vs 4
#    processes (infcmp.py of the 2026-11-21 result comparison)
# Results: $C/results.tsv, $C/infcmp.tsv (C printed at the start)
set -u
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1	# t72/ of the evidence folder
W="$(git -C "$EV" rev-parse --show-toplevel)" || exit 1
T_WRITER=600
T_RUN=75
T_LONG=600
T_ECO=1800
C=$(mktemp -d "${TMPDIR:-/tmp}/t72sweep.XXXXXX") || exit 1
fail() { echo "SWEEP FAIL: $*"; exit 1; }
step() { echo "=== $(date +%H:%M:%S) $*"; }

step "binary and exports in $C (head $(git -C $W rev-parse --short HEAD))"
[ "$(readlink -f $W/bin/shyfem)" = "$W/src/shyfem/shyfem" ] || fail "bin/shyfem is not the work tree binary"
ldd $W/src/shyfem/shyfem | grep -q 'libmpi.so.40' || fail "not OpenMPI"
SHA0=$(sha256sum $W/src/shyfem/shyfem | cut -c1-16)
echo "default binary: $W/src/shyfem/shyfem sha256 $SHA0"

# EUTRO + mercury build in the background (export of HEAD)
E="$C/eutro-src"; mkdir "$E"
git -C $W archive HEAD | tar -x -C "$E" || fail "export for the EUTRO build"
( cd "$E" && PATH=/usr/bin:$PATH nice -n 10 make fem ECOLOGICAL=EUTRO MERCURY=true NETCDF=true NETCDFDIR=/usr NETCDFFDIR=/usr/local > "$C/eutro_build.log" 2>&1; echo "rc=$?" >> "$C/eutro_build.log" ) &
EB=$!

for v in ser mpi; do
  mkdir -p "$C/$v"
  git -C $W archive HEAD testcases/examples | tar -x -C "$C/$v" --strip-components=2 || fail "export $v"
done

export PATH="$W/bin:/usr/bin:$PATH"
step "init (default build's tools)"
for v in ser mpi; do
  ( cd "$C/$v/mar_menor" && make init > init.log 2>&1 && cd GRID && shypre -noopti MM_geo.grd > shypre_geo.log 2>&1 ) || echo "  $v mar_menor init failed"
  ( cd "$C/$v/mar_menor_lagrange" && (make init > init.log 2>&1 || true) )
  ( cd "$C/$v/venice_lagoon" && shypre -silent GRID/venlag62.grd > init.log 2>&1 ) || echo "  $v venice init failed"
  ( cd "$C/$v/restart_strip" && shypre -silent strip.grd > init.log 2>&1 ) || echo "  $v strip init failed"
  ( cd "$C/$v/weutro_box" && make init BIN="$W/bin" > init.log 2>&1 ) || echo "  $v weutro init failed"
  ( cd "$C/$v/channel_turb" && python3 make_grid.py > init.log 2>&1 && python3 make_cases.py >> init.log 2>&1 && shypre -silent channel.grd >> init.log 2>&1 ) || echo "  $v channel init failed"
done

printf 'build\tfolder\tstr\tvariant\tclass\trc\tsteps\tdetail\n' > "$C/results.tsv"
printf 'label\tvar\tnrec\tmax_serial\tmax_diff\tworst_rec\tverdict\n' > "$C/infcmp.tsv"

classify() { # build dir str variant rc
  local b=$1 d=$2 s=$3 v=$4 rc=$5 O="$C/$4/$2/$3.out" steps end cls det
  steps=$(grep -cE '^ [0-9]{4}-[0-9]{2}-[0-9]{2}::[0-9:]+ +[-0-9.]+ +[0-9.]+ +[1-9][0-9]* +/ +[0-9]+ +[0-9.]+ %' "$O" 2>/dev/null)
  end=$(grep -c 'simulation end' "$O" 2>/dev/null)
  det=$(grep -m1 -iE 'error stop|Program received signal|Segmentation|SIGFPE|not supported|not ready|killed|MPI_ABORT' "$O" 2>/dev/null | tr -s ' \t' ' ' | cut -c1-110)
  if [ "$end" -gt 0 ] && [ "$rc" = 0 ]; then cls=ENDED
  elif [ "$rc" = 124 ] && [ "$steps" -gt 0 ]; then cls=STEPPING
  elif [ "$rc" = 124 ]; then cls=SILENT
  elif grep -qiE 'Program received signal|Segmentation|SIGFPE|SIGSEGV|signal 8|signal 11' "$O" 2>/dev/null; then cls=CRASH
  elif grep -qi 'error stop' "$O" 2>/dev/null; then cls=STOP
  else cls=OTHER; det="${det:-$(tail -1 "$O" 2>/dev/null | tr -s ' \t' ' ' | cut -c1-110)}"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$b" "$d" "$s" "$v" "$cls" "$rc" "$steps" "$det" >> "$C/results.tsv"
  echo "  [$b] $d/$s $v: $cls rc=$rc steps=$steps ${det:+| $det}"
}

runpair() { # build dir str timeout
  local b=$1 d=$2 s=$3 t=$4 rs rp
  ( cd "$C/ser/$d" && nice -n 19 timeout "$t" shyfem "$s.str" > "$s.out" 2>&1 ); rs=$?
  ( cd "$C/mpi/$d" && nice -n 19 timeout "$t" mpirun --oversubscribe -np 4 shyfem "$s.str" > "$s.out" 2>&1 ); rp=$?
  classify "$b" "$d" "$s" ser $rs
  classify "$b" "$d" "$s" mpi $rp
  if grep -q 'simulation end' "$C/ser/$d/$s.out" && grep -q 'simulation end' "$C/mpi/$d/$s.out" \
     && [ -s "$C/ser/$d/$s.inf" ] && [ -s "$C/mpi/$d/$s.inf" ]; then
    python3 "$EV/infcmp.py" "[$b] $d/$s" "$C/ser/$d/$s.inf" "$C/mpi/$d/$s.inf" >> "$C/infcmp.tsv" 2>> "$C/infcmp.err"
  fi
}

WRITERS="mar_menor:mm_rst_write mar_menor:mm_rst_cycle_write mar_menor:mm_rst_periodic mar_menor:mm_rst_repeat mar_menor:mm_rst_ssedi_write mar_menor:mm_rst_keps_write weutro_box:eco_rst_part1 weutro_box:merc_rst_part1 restart_strip:strip_rst"
LONG="mar_menor:mm_lgr mar_menor:mm_lgr_a mar_menor:mm_lgr_b mar_menor:mm_lgr_c mar_menor:mm_lgr_e mar_menor:mm_lgr_w"

step "default build: restart writers (timeout $T_WRITER s)"
for w in $WRITERS; do runpair default "${w%%:*}" "${w##*:}" $T_WRITER; done

step "default build: all other runs (timeout $T_RUN s; particle cases $T_LONG s)"
for f in $(git -C $W ls-files 'testcases/examples/*/*.str' | grep -v '/apn' | sed 's|testcases/examples/||'); do
  d=${f%%/*}; s=$(basename "$f" .str)
  case " $WRITERS " in *" $d:$s "*) continue;; esac
  t=$T_RUN; case " $LONG " in *" $d:$s "*) t=$T_LONG;; esac
  runpair default "$d" "$s" $t
done
[ "$(sha256sum $W/src/shyfem/shyfem | cut -c1-16)" = "$SHA0" ] || echo "WARNING: the default binary changed during the sweep"

step "EUTRO + mercury build (waiting for it)"
wait $EB
tail -1 "$C/eutro_build.log"
grep -q '^rc=0' "$C/eutro_build.log" || fail "EUTRO build"
ldd "$E/src/shyfem/shyfem" | grep -q 'libmpi.so.40' || fail "EUTRO build not OpenMPI"
[ "$(readlink -f "$E/bin/shyfem")" = "$E/src/shyfem/shyfem" ] || fail "EUTRO bin/shyfem not its own binary"
export PATH="$E/bin:/usr/bin:$W/bin:$PATH"
echo "EUTRO binary: $(readlink -f "$(command -v shyfem)")"

step "prove the EUTRO build: the folder's serial check scripts (PATH pointed at this build)"
mkdir -p "$C/chk"; git -C $W archive HEAD testcases/examples/weutro_box | tar -x -C "$C/chk" --strip-components=2
( cd "$C/chk/weutro_box" && make init BIN="$E/bin" > init.log 2>&1 && sed -i -E "s|^(export PATH=)[^:]*/bin:|\1$E/bin:|; s|^(BIN *= *).*|\1$E/bin|" check_*.sh Makefile )
for c in check_eco.sh check_mercury.sh check_restart.sh; do
  ( cd "$C/chk/weutro_box" && nice -n 19 timeout $T_ECO bash ./$c > "$c.log" 2>&1 ); rc=$?
  echo "  $c rc=$rc: $(grep -E 'GATE|PASS|FAIL' "$C/chk/weutro_box/$c.log" | tail -2 | tr '\n' ' ' | cut -c1-150)"
done

step "EUTRO build: the 10 weutro_box cases (part 1 before part 2), serial and 4 processes"
for v in ser mpi; do rm -rf "$C/$v/weutro_box"; git -C $W archive HEAD testcases/examples/weutro_box | tar -x -C "$C/$v" --strip-components=2; ( cd "$C/$v/weutro_box" && make init BIN="$E/bin" > init.log 2>&1 ) || echo "  $v weutro init failed"; done
for s in eco_2d eco_2d_mt eco_3d eco_3d_light eco_3d_settle eco_rst_part1 eco_rst_part2 merc_2d merc_rst_part1 merc_rst_part2; do
  runpair eutro weutro_box "$s" $T_ECO
done
step "SWEEP DONE ($C)"
