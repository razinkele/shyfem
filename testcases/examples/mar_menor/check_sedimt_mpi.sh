#!/bin/bash
#------------------------------------------------------------------------
# The older sediment routine sedimt of src/shyfem/custom_admin.f90
# (icust = 82) on several processes against the serial run (issue #274).
#
# sedimt called getinfo on every process, summed over nkn (ghost nodes
# included) and had no reduction, so on several processes every process
# wrote its own per-domain totals into the .inf file, over each other.
# It now sums the nodes each process owns, reduces them to the global
# node order and the master writes one line (the pattern of #220).
#
# Case: the Mar Menor STR file mm_rst_ssedi_write.str with issedi = 0,
# icust = 82 and an output line (idtcon = '1h', itmcon = start of the run):
# two days from rest.  sedimt sets the concentration to 0 at its first
# call and the lagoon has no boundary, so a river (kbound 218, ibtyp 3,
# 50 m**3/s, as in mm_hyd_22.str) with the concentration 1 is added: the
# concentration it brings is what sinks (the case checks the routine, not
# the physics).  Run serially and
# on each NP of NPS (default 2 4) with the METIS partition the model makes.
# Required: every run ends (exit code 0, "simulation end", timeout 600 s);
# the log of an NP-process run has "shympi initialized: ID NP" once from
# each rank; the NP-process runs have the ghost check on
# (SHYFEM_GHOST_CHECK=1, #268) and no line "GHOST CHECK:"; the files
# .hydro.shy, .conz.shy and the sedimt output file (the file of the
# routine's three records) are byte-identical to the serial ones; the
# sedimt: lines of the .inf file are the serial ones, as text (same
# number, each identical, none from another process); the serial lines
# are not zero (otherwise nothing is tested).
#
# Usage:  ./check_sedimt_mpi.sh [NP ...]
# Needs shyfem, shypre and mpirun on PATH (an OpenMPI build).  Works in a
# folder made with mktemp -d under ${TMPDIR:-/tmp}; nothing in this folder
# changes.  The folder is kept (its path is the last line).  Prints
# "SEDIMT MPI CHECK: PASS" or "SEDIMT MPI CHECK: FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
NPS="${*:-2 4}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
for np in $NPS; do
  case "$np" in ''|*[!0-9]*|0|1) echo "usage: $0 [NP ...] (each NP at least 2)"; exit 2 ;; esac
done
for t in shyfem shypre mpirun; do
  command -v "$t" > /dev/null 2>&1 || { echo "SEDIMT MPI CHECK: FAIL ($t is not on PATH)"; exit 1; }
done
for f in GRID/MM_coarse.grd mm_rst_ssedi_write.str; do
  [ -f "$HERE/$f" ] || { echo "SEDIMT MPI CHECK: FAIL (missing $HERE/$f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/sedimt.XXXXXX")" || exit 1
echo "sedimt mpi check: $(command -v shyfem), serial vs $NPS processes, in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "SEDIMT MPI CHECK FAIL: $*"; rc=1; }

mkdir "$P/GRID" && cp "$HERE/GRID/MM_coarse.grd" "$P/GRID/" || exit 1
( cd "$P/GRID" && shypre MM_coarse.grd > shypre.log 2>&1 ) \
  || { echo "SEDIMT MPI CHECK: FAIL (shypre failed, log $P/GRID/shypre.log)"; exit 1; }

sed -e "s/^\([[:space:]]*\)issedi = 1[[:space:]]*$/\1icust = 82\n\1idtout = '1h'\n\1idtcon = '1h'\n\1itmcon = 0/" \
    -e 's/mm_rst_ssedi_write/sedimt/' \
    "$HERE/mm_rst_ssedi_write.str" > "$P/sedimt.str"
cat >> "$P/sedimt.str" <<'EOF2'

$bound2    ----LosAlcazares--
        kbound =  218
        ibtyp = 3
        boundn = 'INPUT/river.txt'
        conzn = 'INPUT/riverc.txt'
        intpol = 2
        zfact = 50
$end
EOF2
mkdir "$P/INPUT" && cp "$HERE/INPUT/river.txt" "$P/INPUT/" \
  && sed 's/ 1\.000 */ 1.000/' "$HERE/INPUT/river.txt" > "$P/INPUT/riverc.txt" || exit 1
grep -q '^[[:space:]]*icust = 82$' "$P/sedimt.str" || { echo "SEDIMT MPI CHECK: FAIL (cannot make the STR file)"; exit 1; }

ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # NP (NP 1: a plain run without mpirun)
  local d="$P/np$1" r
  mkdir "$d" && ln -s ../GRID "$d/GRID" && ln -s ../INPUT "$d/INPUT" && cp "$P/sedimt.str" "$d/" || return 1
  if [ "$1" = 1 ]; then
    ( cd "$d" && timeout 600 nice -n 10 shyfem sedimt.str < /dev/null > run.log 2>&1 )
  else
    ( cd "$d" && SHYFEM_GHOST_CHECK=1 timeout 600 nice -n 10 mpirun --oversubscribe -np "$1" shyfem sedimt.str < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" != 0 ] || ! grep -q "simulation end" "$d/run.log"; then
    tail -3 "$d/run.log"; echo "  exit code $r"; return 1
  fi
  if [ "$1" != 1 ] && ! ranks_ok "$d/run.log" "$1"; then
    echo "  the log does not show $1 MPI processes ($d/run.log)"; return 1
  fi
  if [ "$1" != 1 ] && ! grep -q 'ghost check of the output gathers is on' "$d/run.log"; then
    echo "  the log does not say 'ghost check of the output gathers is on' ($d/run.log)"; return 1
  fi
  return 0
}

if ! run 1; then fail "the serial run did not end (above)"; echo "$P"; exit 1; fi
grep ' sedimt: ' "$P/np1/sedimt.inf" > "$P/np1/sedimt.txt" 2> /dev/null
if [ ! -s "$P/np1/sedimt.txt" ]; then
  fail "no sedimt: line in the serial info file ($P/np1/sedimt.inf)"
elif ! awk '{ if ($3 + 0 != 0) m = 1; if ($4 + 0 != 0) s = 1 } END { exit !(m && s) }' "$P/np1/sedimt.txt"; then
  fail "the serial sedimt: suspended mass (column 3) or bed sediment (column 4) is zero in every line (nothing is tested)"
else
  echo "  serial: $(wc -l < "$P/np1/sedimt.txt") sedimt: lines, last: $(tail -1 "$P/np1/sedimt.txt")"
fi
files="$(cd "$P/np1" && ls sedimt*.shy)"
for np in $NPS; do
  if ! run "$np"; then fail "the run on $np processes did not end, or not on $np processes (above)"; continue; fi
  n="$(grep -c '^GHOST CHECK:' "$P/np$np/run.log")"
  if [ "$n" = 0 ]; then echo "  np $np  GHOST CHECK lines: 0"
  else fail "np $np: $n GHOST CHECK lines ($P/np$np/run.log)"; fi
  grep ' sedimt: ' "$P/np$np/sedimt.inf" > "$P/np$np/sedimt.txt" 2> /dev/null
  if cmp -s "$P/np1/sedimt.txt" "$P/np$np/sedimt.txt"; then
    echo "  np $np  sedimt: lines of the info file: identical ($(wc -l < "$P/np1/sedimt.txt") lines)"
  else
    echo "  np $np  sedimt: lines of the info file: DIFFER (serial $(wc -l < "$P/np1/sedimt.txt") lines, here $(wc -l < "$P/np$np/sedimt.txt"))"
    diff "$P/np1/sedimt.txt" "$P/np$np/sedimt.txt" | head -4 | sed 's/^/    /'
    fail "the sedimt: lines of the info file differ between serial and $np processes"
  fi
  for f in $files; do
    if [ ! -s "$P/np1/$f" ] || [ ! -s "$P/np$np/$f" ]; then fail "$f missing or empty"; continue; fi
    if cmp -s "$P/np1/$f" "$P/np$np/$f"; then echo "  np $np  $f: byte-identical"
    else echo "  np $np  $f: DIFFERS ($(cmp "$P/np1/$f" "$P/np$np/$f" 2>&1 | head -1))"; fail "$f differs between serial and $np processes"; fi
  done
done

if [ "$rc" = 0 ]; then echo "SEDIMT MPI CHECK: PASS"; else echo "SEDIMT MPI CHECK: FAIL"; fi
echo "$P"
exit "$rc"
