#!/bin/bash
#------------------------------------------------------------------------
# Output gathers on several processes: the files get the owner's value of
# every node and the main process's value of every element, and the ghost
# check reports a ghost copy out of step with its owner (issue #268).
#
# On a node partition a process holds its own nodes and ghost copies of
# nodes of its neighbours, and an element can be held by up to three
# processes (its main process is id_elem(1,ie)).  shympi_l2g_array
# (src/utils/shympi/mpi_node.f90) gathers the local arrays into the
# global array of every output and restart file.  Before #268 it copied
# every local value, ghosts included, in process order, so the copy of
# the highest process won: a module that left a ghost out of step
# (simple sediment, #262) showed the ghost's value in the files.  Now it
# copies the owners' values only.  With SHYFEM_GHOST_CHECK set, the
# master compares every ghost copy with the owner's value before the
# files get it and reports each array that differs, on lines like
#   GHOST CHECK: shy file NAME var IVAR (node, real): node 9 (internal 9)
#     value 1/1: process 0 has X, owner process 2 has Y
# (elements: "main process"; restart arrays: "restart file NAME array N";
# then the count), and the run goes on.  The test hook
# SHYFEM_GHOST_DESYNC makes the master add 1 to every ghost copy it has
# gathered (the model state is not touched): a module that leaves every
# ghost out of step, at every gather.
#
# Cases, on NP processes (default 4) with the METIS partition the model
# makes, each one run twice with SHYFEM_GHOST_CHECK=1:
#   s2d  mm_rst_ssedi_write.str with an hourly output line (as in
#        check_ssedi_mpi.sh): 2D, files .hydro.shy, .conz.shy, .ssed.shy,
#        .csed.shy and the restart file (node and element arrays; integer
#        and real; one and three values per item); its .fvl.shy holds a
#        header only (no record, so no data gather), and is compared too
#   g3d  the g3d case of check_mpi_3d.sh (mm_lgr.str without its
#        particles, the 19 levels of mm_hyd_41.str, GOTM) for 6 hours,
#        with an hourly output and a restart file at the end: 3D real
#        arrays and the double-precision GOTM arrays of the restart file
# Runs:
#   clean   no "GHOST CHECK:" line: the ghosts of a correct run are in
#           step with their owners
#   desync  SHYFEM_GHOST_DESYNC=1 as well: "GHOST CHECK:" lines in the
#           format above for every output file with records (the shy
#           files above and the restart file), node and element lines,
#           and every file of the run byte-identical to the clean run's
#           (no ghost copy reaches a file); in g3d also a 3D line (19 or
#           20 values per node) and a double-precision line
# Required also: every run ends (exit code 0 and "simulation end" in its
# log, timeout 600 s each), its log has "shympi initialized: ID NP" once
# from each rank 0 to NP-1 (NP serial runs, from an mpirun that does not
# match the binary's MPI or a binary without MPI, cannot pass), and it
# acknowledges the switches it was given ("ghost check of the output
# gathers is on", "test hook SHYFEM_GHOST_DESYNC").
#
# Usage:  ./check_ghost_gather_mpi.sh [NP]
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build).
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp} (the basins
# are built there from GRID/MM_coarse.grd and GRID/MM_geo.grd, the
# geographic basin of mm_lgr.str; INPUT is linked, the STR files are
# made there from this folder's), so nothing in this folder changes.
# The folder is kept (its path is the last line).  Prints "GHOST GATHER
# CHECK: PASS" or "GHOST GATHER CHECK: FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
case "$NP" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP] (NP at least 2)"; exit 2 ;; esac
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "GHOST GATHER CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse.grd GRID/MM_geo.grd mm_rst_ssedi_write.str mm_lgr.str mm_hyd_41.str INPUT/gotmturb.nml; do
  [ -f "$HERE/$f" ] || { echo "GHOST GATHER CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/ghostgather.XXXXXX")" || exit 1
echo "ghost gather check: $(command -v shyfem), $NP processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "GHOST GATHER CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse.grd" "$HERE/GRID/MM_geo.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse.grd > shypre1.log 2>&1 && shypre -noopti MM_geo.grd > shypre2.log 2>&1 ) \
  || { echo "GHOST GATHER CHECK: FAIL (shypre failed, logs in $P/GRID)"; exit 1; }

#--- the STR files
sed "/^[[:space:]]*issedi = 1[[:space:]]*$/a\\        idtout = '1h'\\n        idtcon = '1h'" \
  "$HERE/mm_rst_ssedi_write.str" > "$P/s2d.str"
[ "$(grep -c "^        idt\(out\|con\) = '1h'$" "$P/s2d.str")" = 2 ] \
  || { echo "GHOST GATHER CHECK: FAIL (cannot add the output line to s2d.str)"; exit 1; }
python3 - "$HERE/mm_lgr.str" "$HERE/mm_hyd_41.str" "$P/g3d.str" <<'PY' || { echo "GHOST GATHER CHECK: FAIL (cannot make g3d.str)"; exit 1; }
import re
import sys
src, l41, dst = sys.argv[1:4]
levels = re.search(r'(\$levels.*?\$end\n)', open(l41).read(), re.S).group(1)
out, skip, intitle, nt = [], False, False, 0
for ln in open(src).read().splitlines(True):
    s = ln.strip()
    if s.startswith('$lagrg'):          # no particles
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
            ln = '        g3d\n'          # the run name
        if s.startswith('$end'):
            intitle = False
    out.append(re.sub(r"itend = '[^']*'", "itend = '2009-01-01::06:00:00'", ln))
txt = ''.join(out)
if txt.count('$para\n') != 1 or txt.count('$name\n') != 1 or '$lagrg' in txt \
        or "itend = '2009-01-01::06:00:00'" not in txt:
    sys.exit('cannot make %s from %s' % (dst, src))
txt = re.sub(r'^\s*(idtout|idtrst|itmrst)\s*=.*\n', '', txt, flags=re.M)
txt = txt.replace('$para\n', "$para\n        iturb = 1\n        idtout = '1h'\n"
                  "        idtrst = -1\n        itmrst = -1\n", 1)
txt = re.sub(r'(\$para.*?\$end\n)', lambda m: m.group(1) + '\n' + levels, txt, count=1, flags=re.S)
txt = txt.replace('$name\n', "$name\n        gotmpa = 'INPUT/gotmturb.nml'\n", 1)
open(dst, 'w').write(txt)
PY

#--- runs
# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_init, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # CASE MODE (clean | desync)
  local d="$P/$1.$2" r hook=""
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" && cp "$P/$1.str" "$d/" || return 1
  [ "$2" = desync ] && hook=1
  ( cd "$d" && SHYFEM_GHOST_CHECK=1 SHYFEM_GHOST_DESYNC="$hook" timeout 600 nice -n 10 \
      mpirun --oversubscribe -np "$NP" shyfem "$1.str" < /dev/null > run.log 2>&1 )
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  if ! ranks_ok "$d/run.log" "$NP"; then
    echo "  the log does not show $NP MPI processes: $(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines ($d/run.log)"
    return 1
  fi
  if ! grep -q 'ghost check of the output gathers is on' "$d/run.log"; then
    echo "  the log does not say 'ghost check of the output gathers is on': this shyfem has no ghost check ($d/run.log)"
    return 1
  fi
  if [ "$2" = desync ] && ! grep -q 'test hook SHYFEM_GHOST_DESYNC' "$d/run.log"; then
    echo "  the log does not acknowledge the test hook SHYFEM_GHOST_DESYNC ($d/run.log)"
    return 1
  fi
  return 0
}

for c in s2d g3d; do
  echo "=== $c on $NP processes"
  if [ "$c" = s2d ]; then
    named="$(for e in hydro.shy conz.shy ssed.shy csed.shy rst; do printf ' mm_rst_ssedi_write.%s' "$e"; done)"
  else
    named=" g3d.hydro.shy g3d.rst"
  fi
  for m in clean desync; do
    if ! run "$c" "$m"; then fail "$c $m: the run did not end, or not as required (above)"; continue 2; fi
  done
  dc="$P/$c.clean"; dd="$P/$c.desync"
  # clean: silent
  n="$(grep -c '^GHOST CHECK:' "$dc/run.log")"
  if [ "$n" = 0 ]; then
    echo "  clean: no GHOST CHECK line"
  else
    grep '^GHOST CHECK:' "$dc/run.log" | head -5
    fail "$c clean: $n GHOST CHECK lines in a run whose ghosts should be in step ($dc/run.log)"
  fi
  # files: the output of the clean run, byte-identical in the desync run
  files="$(cd "$dc" && ls *.shy *.rst 2> /dev/null)"
  if ! echo "$files" | grep -q '\.rst$' || [ "$(echo "$files" | grep -c '\.shy$')" -lt 1 ]; then
    fail "$c: the clean run wrote no restart file or no shy file ($dc)"
  fi
  for f in $files; do
    if [ ! -s "$dd/$f" ]; then
      fail "$c desync: $f missing or empty"
    elif cmp -s "$dc/$f" "$dd/$f"; then
      echo "  desync: $f byte-identical to the clean run's"
    else
      echo "  desync: $f DIFFERS from the clean run's: $(cmp "$dc/$f" "$dd/$f" 2>&1 | head -1)"
      fail "$c desync: a ghost copy reached $f"
    fi
  done
  # desync: every line in the format, every file named, node and element lines
  python3 - "$dd/run.log" "$c" $named <<'PY' || fail "$c desync: the GHOST CHECK lines are missing or not as required (above)"
import re
import sys
log, case, files = sys.argv[1], sys.argv[2], sys.argv[3:]
item = re.compile(r'^GHOST CHECK: (.+) \((node|element), (integer|real|double)\): (node|element) (\d+) '
                  r'\(internal (\d+)\) value (\d+)/(\d+): process (\d+) has (\S+), (owner|main) process (\d+) has (\S+)$')
summ = re.compile(r'^GHOST CHECK: (.+) \((node|element), (integer|real|double)\): (\d+) ghost copies differ '
                  r'from the (owner|main) process \((\d+) values per (node|element), first (\d+) shown\)$')
lines = [ln.rstrip('\n') for ln in open(log) if ln.startswith('GHOST CHECK:')]
ok, labels, kinds, nvals = True, set(), set(), set()
for ln in lines:
    m, s = item.match(ln), summ.match(ln)
    if m:
        lab, kind, typ, kind2, ext, inter, l, nov, pg, gv, who, po, ov = m.groups()
        if kind != kind2 or (who == 'owner') != (kind == 'node') or pg == po or gv == ov \
                or not 1 <= int(l) <= int(nov):
            print('  not as required: ' + ln)
            ok = False
        labels.add(lab); kinds.add((kind, typ)); nvals.add(int(nov))
    elif s:
        labels.add(s.group(1))
    else:
        print('  not in the format: ' + ln)
        ok = False
print('  desync: %d GHOST CHECK lines, %d arrays named, kinds %s, values per item %s'
      % (len(lines), len(labels), ', '.join('%s %s' % k for k in sorted(kinds)), sorted(nvals)))
for f in files:
    want = ('shy file %s var ' % f) if f.endswith('.shy') else ('restart file %s' % f)
    if not any(lab.startswith(want) for lab in labels):
        print('  no GHOST CHECK line names %s (expected a label starting "%s")' % (f, want))
        ok = False
if not {'node', 'element'} <= {k for k, _ in kinds}:
    print('  missing node or element lines: %s' % sorted(kinds))
    ok = False
if case == 'g3d':
    if max(nvals or {0}) < 19:
        print('  no 3D line (values per item %s)' % sorted(nvals))
        ok = False
    if not any(t == 'double' for _, t in kinds):
        print('  no double-precision line (the GOTM arrays of the restart file)')
        ok = False
sys.exit(0 if ok else 1)
PY
done

if [ "$rc" = 0 ]; then echo "GHOST GATHER CHECK: PASS"; else echo "GHOST GATHER CHECK: FAIL"; fi
echo "$P"
exit "$rc"
