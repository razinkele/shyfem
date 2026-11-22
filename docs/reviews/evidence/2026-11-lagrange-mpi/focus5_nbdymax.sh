#!/bin/bash
# focus5_nbdymax.sh [NP] [TIMEOUT] : Review Focus 5 of the plan (the global
# particle limit nbdymax), reproducible from a checkout.
#
# Case B (mm_lgr_b: one whole-basin release of 1,003 particles at the start,
# nbdy = 1000) with nbdymax = 500 and with nbdymax = 200 in place of 20000,
# each run on NP processes (default 4) and serially, with the build of this
# checkout (bin/ of the repository first on PATH), in a scratch copy of the
# test folder (git archive of HEAD into a folder made with mktemp -d under
# ${TMPDIR:-/tmp}; GRID/MM_coarse.bas is the tracked file).  Every run has a
# timeout of TIMEOUT seconds (default 300; exit code 124 means it hung).
#
# On several processes insert_particle does not stop by itself; it records
# that its process passed the limit, and lgr_mpi_assign_ids sums the counts
# and the records of all processes after the release and stops every
# process with the serial message (rank 0 writes it).  With the METIS
# partition of the development machine the release block of case B on 4
# processes holds 251, 252, 246, 254 particles (./check_lgr_mpi.sh mm_lgr_b 4
# part, then release_owners.py mm_lgr_b.np4.dbg): with 500 no process passes
# the limit by itself and only the global sum (1,003) does; with 200 every
# process passes it by itself.
#
# Per run: the exit code, how often "Cannot insert more than nbdymax
# particles" appears (must be once), whether the run ended (it must not),
# whether it hung (it must not), and SIGFPE/SIGSEGV/"Fortran runtime" lines
# (must be none).  On NP processes the exit code must also be non-zero (a
# serial STOP exits with 0).  Prints "FOCUS 5: PASS" or "FAIL" and exits 0
# or 1; the scratch folder is removed after a PASS and kept (path printed)
# after a FAIL.
set -u
NP="${1:-4}"; TO="${2:-300}"
EV="$(cd "$(dirname "$0")" && pwd)" || exit 1
W="$(git -C "$EV" rev-parse --show-toplevel)" || { echo "not inside a git checkout"; exit 1; }
export PATH=$W/bin:/usr/bin:$PATH
R=$(mktemp -d "${TMPDIR:-/tmp}/focus5.XXXXXX") || exit 1
echo "$(date '+%F %T %Z') focus 5: commit $(git -C "$W" rev-parse --short HEAD), binary $(readlink -f "$(command -v shyfem)"), $NP processes, in $R"
git -C "$W" archive HEAD testcases/examples/mar_menor | tar -x -C "$R" --strip-components=2 || exit 1
cd "$R/mar_menor" || exit 1
rc=0
for lim in 500 200; do
  s="mm_lgr_b_nbdymax$lim"
  sed "s/^\([ \t]*\)nbdymax = 20000[ \t]*$/\1nbdymax = $lim/" mm_lgr_b.str > "$s.str"
  if cmp -s mm_lgr_b.str "$s.str"; then echo "nbdymax $lim: the sed expression changed nothing"; rc=1; continue; fi
  for mode in np serial; do
    if [ "$mode" = np ]; then
      timeout "$TO" nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$s.str" > "$s.np$NP.log" 2>&1; x=$?; log="$s.np$NP.log"; lab="$NP processes"
    else
      timeout "$TO" nice -n 19 shyfem "$s.str" > "$s.serial.log" 2>&1; x=$?; log="$s.serial.log"; lab="serial"
    fi
    nmsg=$(grep -c 'Cannot insert more than nbdymax particles' "$log")
    nend=$(grep -c 'simulation end' "$log")
    nsig=$(grep -c 'SIGFPE\|SIGSEGV\|Fortran runtime' "$log")
    nabort=$(grep -c 'error stop insert_particle: nbdy' "$log")
    ok=1
    [ "$nmsg" = 1 ] || ok=0
    [ "$nend" = 0 ] || ok=0
    [ "$nsig" = 0 ] || ok=0
    [ "$x" != 124 ] || ok=0
    if [ "$mode" = np ] && [ "$x" = 0 ]; then ok=0; fi
    [ "$ok" = 1 ] || rc=1
    echo "nbdymax = $lim, $lab: $([ "$ok" = 1 ] && echo ok || echo FAIL); exit $x$([ "$x" = 124 ] && echo ' (timeout: hung)'), message x$nmsg, 'error stop insert_particle: nbdy' x$nabort, ended $nend, signals $nsig"
    rm -f mm_lgr_b.*.shy mm_lgr_b.inf
  done
done
if [ "$rc" = 0 ]; then
  cd / && rm -rf "$R"
  echo "FOCUS 5: PASS"
else
  echo "logs kept in $R/mar_menor"
  echo "FOCUS 5: FAIL"
fi
exit "$rc"
