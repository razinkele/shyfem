#!/bin/bash
#------------------------------------------------------------------------
# Position floors of the Lagrangian test cases (the floor table of
# check_lgr_mpi.sh): a serial run against serial runs whose wind drag
# coefficient (dragco) is changed by a relative amount r, for r = +-1e-5,
# +-7e-6, +-4e-6.  The floor of a case is the ENVELOPE of the six
# comparisons (one run is one sample): the largest number of particles
# beyond the tight limit at the last output, and the largest distance at
# any output.  The comparison is the one the MPI gates use
# (lgr_dbg_compare.py part on the debug dump, limit 1e-5 degrees, case B
# 2 m).
#
# Usage:  ./measure_lgr_floors.sh BIN_DIR [COMMIT] [BY] [JOBS] [CASES]
#
#   BIN_DIR  folder with the shyfem and shypre binaries to measure (the
#            serial reference build whose floors are wanted)
#   COMMIT   commit of this repository whose tracked inputs are used
#            (default HEAD)
#   BY       key (default; needs the key columns of the dump) or id
#   JOBS     runs at a time (default 3); every run is niced
#   CASES    default "mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e" (mm_lgr_w too)
#
# The inputs are the tracked files of COMMIT (git archive of GRID, INPUT,
# release_areas.txt, lgr_dbg_compare.py and the STR files), so
# GRID/MM_coarse.bas is the tracked file and never one that `make init`
# rewrote; GRID/MM_geo.bas, which is not tracked, is built in the scratch
# folder with BIN_DIR/shypre -noopti MM_geo.grd (the same bytes as the file
# `make init` users build by hand).  Every run gets "levdbg = 3" after the
# $para line (the debug dump the comparison reads).
#
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp} and touches
# nothing in the work tree.  The folder is kept (its path is the last line
# of the output): CASE.TAG/ is one run (TAG r0 for the base run, r+1e-5 and
# so on), CASE.cmp.TAG.txt one comparison, and lgr_runs/CASE.TAG.lgr.shy
# and .str the particle file and STR file of every run.  The base file and
# the six perturbed files of mm_lgr_a are the envelope of AC8 (acceptance
# file): python3 lgr_lgmean_compare.py SERIAL MPI \
#     DIR/lgr_runs/mm_lgr_a.r0.lgr.shy DIR/lgr_runs/mm_lgr_a.r[+-]*.lgr.shy
#
# The floors of the table were measured with this script (then kept outside
# the repository) on the serial reference build of commit 0fddec90; they
# were measured again on 2026-11-24 for the rebuilt basin (#251) with the
# build of 37f08788 (release 8.6.0) on the inputs of commit 5ebf495b
# (floors_basin251.log), and case C once more on 2026-11-24 for #248
# with the build of #248 on the inputs of commit 7564a360
# (floors_vistur248.log); the logs are in
# docs/reviews/evidence/2026-11-lagrange-mpi/.
# Exit code 0 when every run ended and every comparison gave a result
# (FLOORS: complete), 1 otherwise.
#------------------------------------------------------------------------
set -u
BIN="${1:?usage: $0 BIN_DIR [COMMIT] [BY] [JOBS] [CASES]}"
COMMIT="${2:-HEAD}"; BY="${3:-key}"; JOBS="${4:-3}"
CASES="${5:-mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e}"
RELS="+1e-5 -1e-5 +7e-6 -7e-6 +4e-6 -4e-6"

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
SRC="$(git -C "$HERE" rev-parse --show-toplevel)" || { echo "FLOORS: not inside a git checkout"; exit 1; }
MM="${HERE#"$SRC"/}"		# testcases/examples/mar_menor
BIN="$(cd "$BIN" && pwd)" || { echo "FLOORS: no folder $1"; exit 1; }
[ -x "$BIN/shyfem" ] || { echo "FLOORS: no shyfem in $BIN"; exit 1; }
[ -x "$BIN/shypre" ] || { echo "FLOORS: no shypre in $BIN"; exit 1; }
W="$(mktemp -d "${TMPDIR:-/tmp}/lgrfloors.XXXXXX")" || { echo "FLOORS: mktemp failed"; exit 1; }
echo "$(date '+%Y-%m-%d %H:%M:%S')  floors: binary $BIN, inputs of $(git -C "$SRC" rev-parse --short "$COMMIT"), by $BY, in $W"

# tracked inputs of the commit; the geographic basin is built here
STRS=""; for c in $CASES; do STRS="$STRS $MM/$c.str"; done
git -C "$SRC" archive "$COMMIT" "$MM/GRID" "$MM/INPUT" "$MM/release_areas.txt" \
    "$MM/lgr_dbg_compare.py" $STRS | tar -x -C "$W" --strip-components=3 \
  || { echo "FLOORS: git archive failed"; exit 1; }
( cd "$W/GRID" && "$BIN/shypre" -noopti MM_geo.grd > shypre_geo.log 2>&1 ) \
  && [ -f "$W/GRID/MM_geo.bas" ] || { echo "FLOORS: shypre failed on MM_geo.grd (log $W/GRID/shypre_geo.log)"; exit 1; }

# one folder per run: CASE.TAG with links to the inputs and its own STR
make_run() {  # CASE TAG REL
  local c="$1" tag="$2" rel="$3" d="$W/$1.$2"
  mkdir "$d" || return 1
  ln -s ../GRID "$d/GRID"; ln -s ../INPUT "$d/INPUT"
  ln -s ../release_areas.txt "$d/release_areas.txt"
  python3 - "$W/$c.str" "$d/$c.str" "$rel" <<'PY'
import re, sys
src, dst, rel = sys.argv[1], sys.argv[2], float(sys.argv[3])
out, done_dbg, ndrag = [], False, 0
for line in open(src):
    m = re.search(r'(dragco\s*=\s*)([0-9.eEdD+-]+)', line)
    if m and not line.lstrip().startswith('#'):
        base = float(m.group(2).lower().replace('d', 'e'))
        line = line[:m.start(2)] + ('%.12e' % (base * (1.0 + rel))) + line[m.end(2):]
        ndrag += 1
    out.append(line)
    if not done_dbg and re.match(r'^\$para\s*$', line):
        out.append('        levdbg = 3\n'); done_dbg = True
if ndrag != 1 or not done_dbg:
    sys.exit('STR %s: dragco lines %d, $para found %s' % (src, ndrag, done_dbg))
open(dst, 'w').writelines(out)
PY
}

LIST="$W/runs.txt"; : > "$LIST"
for c in $CASES; do
  make_run "$c" r0 0 || { echo "FLOORS: cannot set up $c"; exit 1; }
  echo "$c r0" >> "$LIST"
  for r in $RELS; do
    make_run "$c" "r$r" "$r" || { echo "FLOORS: cannot set up $c $r"; exit 1; }
    echo "$c r$r" >> "$LIST"
  done
done

run_one() {  # CASE TAG
  local d="$W/$1.$2"
  ( cd "$d" && PATH="$BIN:/usr/bin:$PATH" nice -n 19 shyfem "$1.str" > run.log 2>&1 )
  if grep -q "simulation end" "$d/run.log"; then echo "  $1.$2: ended"
  else echo "  $1.$2: DID NOT END: $(tail -2 "$d/run.log" | tr '\n' ' ' | cut -c1-200)"; fi
}
export -f run_one; export W BIN
xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1"' < "$LIST"

# the particle and STR files of every run, side by side (AC8's envelope)
mkdir "$W/lgr_runs" || exit 1
while read -r c tag; do
  cp "$W/$c.$tag/$c.str" "$W/lgr_runs/$c.$tag.str"
  [ -f "$W/$c.$tag/$c.lgr.shy" ] && cp "$W/$c.$tag/$c.lgr.shy" "$W/lgr_runs/$c.$tag.lgr.shy"
done < "$LIST"

bad=0
echo
printf '%-9s %-6s %8s %8s %12s %10s\n' case rel pairs beyond_last largest at_time
for c in $CASES; do
  if [ "$c" = mm_lgr_b ]; then TOL=2; else TOL=1e-5; fi
  envn=0; envd=0
  for r in $RELS; do
    out="$W/$c.cmp.r$r.txt"
    python3 "$W/lgr_dbg_compare.py" part "$W/$c.r0" "$W/$c.r$r" --by "$BY" --tol "$TOL" > "$out" 2>&1
    # the per-output lines start with the time; column 10 is the number beyond the limit
    last="$(grep -E '^ +[0-9]+\.[0-9] +[0-9]+ +[0-9]+ ' "$out" | tail -1)"
    n="$(echo "$last" | awk '{print $10}')"; np="$(echo "$last" | awk '{print $2}')"
    big="$(grep 'largest distance' "$out" | awk '{print $3}')"
    at="$(grep 'largest distance' "$out" | awk '{print $6}')"
    printf '%-9s %-6s %8s %8s %12s %10s\n' "$c" "$r" "${np:-?}" "${n:-?}" "${big:-?}" "${at:-?}"
    if [ -z "$n" ] || [ -z "$big" ]; then
      echo "  FLOORS: no result for $c $r: $(head -1 "$out" | cut -c1-160)"; bad=1
    fi
    envn="$(python3 -c "print(max(int('$envn'), int('${n:-0}')))")"
    envd="$(python3 -c "print('%.4e' % max(float('$envd'), float('${big:-0}')))")"
  done
  printf '%-9s %-6s %8s %8s %12s   <- floor (envelope of %d runs, limit %s)\n' "$c" ENV "" "$envn" "$envd" "$(echo $RELS | wc -w)" "$TOL"
done
for d in "$W"/*.r*/; do
  grep -q "simulation end" "$d/run.log" 2>/dev/null || bad=1
done
if [ "$bad" = 0 ]; then echo "FLOORS: complete"; else echo "FLOORS: INCOMPLETE (see the lines above)"; fi
echo
echo "$(date '+%Y-%m-%d %H:%M:%S')  comparisons and logs in:"
echo "$W"
exit "$bad"
