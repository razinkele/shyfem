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
# and fourteen cases of another kind, each with its own write runs
# (serial):
#   old_v19       (a merge-time check, needs REF_BIN_DIR, see below) a
#                 version 19 file (venlag_smoke, as ven_s), written by the
#                 reference binary REF_BIN_DIR/shyfem (a build of the last
#                 main commit before version 20) and read by this binary
#                 (r) and by the reference binary (m): r must read it as
#                 main did, so r's .hydro.shy, .ts.shy and .ext must be the
#                 same bytes as m's (cmp) and equal from the first record r
#                 must write (the comparator exits 0, #330: cmp alone would
#                 pass two files that both lack it; a canary drops it from
#                 copies of both, which must be rejected); r's log must
#                 show "nvers = 19" and "setweg clock not reset" (only a
#                 version 20 record restores iwetv, so only then is
#                 setweg's clock reset); without REF_BIN_DIR the case is
#                 skipped
#   drag0_reads_cd4  the version 20 file of mm_h6d4's write run (windcd
#                 set by COARE, itdrag = 4) read with itdrag = 0, as written
#                 (r) and with its windcd record set to the STR's dragco
#                 (p): with itdrag = 0 windcd is the user's dragco and must
#                 not come from the file, so both logs must say "windcd not
#                 applied (file itdrag = 4, run itdrag = 0)" and r must equal
#                 p (max|d| = 0; compared even if a log line is missing);
#                 the patch walks the record markers and checks the sizes
#                 of the hydro block's records, and fails if the file's
#                 windcd is dragco everywhere (then r and p could not differ)
#   drag4_reads_cd0  the reverse: mm_h6d4's write run with itdrag = 0 (its
#                 windcd is its dragco, 2.5e-3) read with itdrag = 4 and
#                 dragco = 2.0e-3 (the heat flux runs), as written (r) and
#                 with its windcd record set to 2.0e-3 (p): windcd is applied
#                 only when the writer's itdrag (a record of its own) equals
#                 the reader's, so the reader keeps its own dragco until
#                 COARE sets windcd (at the first step meteo_force uses it
#                 before qflux3d, and on the nodes that stay dry); both
#                 logs must say "windcd not applied (file itdrag = 0, run
#                 itdrag = 4)" and r must equal p
#   drag4_noheat_reads_cd4  (#323) mm_h6d4's write run with ibarcl = 0, so
#                 that its qflux3d never runs (itdrag = 4 kept): its heat
#                 flag is 0 and its windcd is its dragco, 2.5e-3; read with
#                 itdrag = 4, the heat flux running and dragco = 2.0e-3, as
#                 written (r) and with its windcd record set to 2.0e-3 (p):
#                 with itdrag = 4 windcd is applied only if the file's heat
#                 flag is set, so both logs must say "windcd not applied
#                 (itdrag = 4, file heat flag not set)" and r must equal p;
#                 the patch's line must show heat flag 0 and itdrag 4 (the
#                 two drag cases above check theirs: heat flag 1, their
#                 writer's itdrag); and a third read (n) of the same file
#                 without heat flux (ibarcl = 0, itdrag = 4 kept) must log
#                 "windcd not applied (itdrag = 4, no heat flux, file heat
#                 flag not set)" (#330)
#   flgrst_no_hydro  mm_h6d4's write run read with flgrst = 110 (depth and
#                 T/S, no hydro): the read must end, its log must show id 1
#                 not wanted and ids 2 and 3 wanted, the seven version 20
#                 records skipped (all seven named), and "setweg clock not
#                 reset" with the cold start's clock (not the restart
#                 time); and T and S in its .ext at the restart time must
#                 equal the write run's, so the records after the skipped
#                 ones were read right: the comparator on the T and S
#                 records of both .ext files, to the restart time, must
#                 exit 0 (#330; not on the whole files: the read run's
#                 records after the restart time have none in the write
#                 run's, and zeta differs, hydro is not read), and a
#                 canary, the read run's .ext without its records at the
#                 restart time, must be rejected
#   evap_reads_noheat  the version 20 file of mm_h6d4's write run (evapv of
#                 the heat flux, windcd set by COARE) read with ibarcl = 0,
#                 so that qflux3d does not run (ievap = 1, iheat = 6,
#                 itdrag = 4 kept), as written (r) and with its evapv record
#                 set to 0 and its windcd record to dragco (p), the values a
#                 cold start keeps for the whole run: r must not apply the
#                 file's evapv and windcd, so r must equal p (max|d| = 0;
#                 compared even if a log line is missing) and both logs must
#                 say "evapv not applied" and "windcd not applied (itdrag =
#                 4, no heat flux)" (that text: an i0 format, #330)
#   keps_to_gotm  the version 20 file of ven_keps_s's write run (k-epsilon,
#                 iturb = 2: its turbulence block, id 8, holds tken, eps,
#                 visv and difv, and no GOTM arrays) read with GOTM (iturb =
#                 1), as written (r) and with flgrst = 1111111 (o: ids 1 to
#                 7, so id 8 is not wanted, and GOTM starts from its own
#                 initial state whatever the file holds): the k-epsilon
#                 arrays must not be applied, and GOTM must start from its
#                 own initial state, not from arrays the file does not hold.
#                 r and o must end; r's restart table must show id 8
#                 wanted and available (else the case would test nothing)
#                 and o's id 8 not wanted; both logs must say "k-epsilon
#                 state not applied" and "handle_gotm_init: GOTM arrays
#                 initialised"; r's .hydro.shy, .ts.shy and .ext must hold
#                 no NaN or infinity; and r must equal o (max|d| = 0;
#                 compared even if a log line is missing)
#   offline_ts_noheat  the version 20 file of mm_h6d4's write run read with
#                 T/S from an offline file (idtoff = -2, offlin = 'f.off';
#                 f.off written by a run f, 00:00-14:00, idtoff = 3600), so
#                 that barocl returns before qflux3d at every step (ievap =
#                 1, iheat = 6, itdrag = 4 kept), as written (r) and with its
#                 evapv record set to 0 and its windcd record to dragco (p):
#                 r must not apply the file's evapv and windcd, so r must
#                 equal p (max|d| = 0 in .hydro.shy and .ext, and the
#                 .ts.shy files, which hold no data record then, the same
#                 bytes; compared even if a log line is missing); both logs
#                 must say "T/S from the offline file (idtoff = -2)",
#                 "evapv not applied", "windcd not applied (itdrag = 4, no
#                 heat flux)" and "tws, dtw not applied (no heat flux)" (the
#                 outputs cannot show tws and dtw: qflux3d never runs), must
#                 show that the offline file was read, and must not have
#                 qflux3d's start-up line (it never runs); the run uses
#                 idtoff = -2 only, idtoff = -3 and <= -4 (also T/S from the
#                 file) are covered by reading the code (offline_reads_ts)
#   offline_ts_noheat_str  (#323) the same with idtoff given as a time span
#                 string, idtoff = '-2s', which handle_offline decodes
#                 (convert_time_d) to -2, T/S from the file, as the restart
#                 reader must too (offline_reads_ts), with the same checks
#   clock_itrst_after_start  (#323, the setweg clock of R5) mm_i0's write
#                 run (record at 06:00) read with an explicit itrst =
#                 06:00 by a run that starts one step before it (itanf =
#                 05:55, idt = 300 s, to 07:00) and writes its last record
#                 (idtrst = -1, at 07:00): setweg counts a new step when the
#                 time differs from its clock, and each step calls it first
#                 in set_dry, at the time before the step (05:55 for the
#                 first), then at the step's time; the restart sets the
#                 clock to the start of the run, 05:55 (dtanf), so the
#                 first step counts once, as in the continuous run.  The
#                 record's time, 06:00, as clock would make set_dry count a
#                 new step at 05:55 and the step another at 06:00: every
#                 element wet all the run would count one step too many
#                 (measured with that mutation: 14 instead of 13; the first
#                 step is not missed, as one might expect, since set_dry
#                 runs before it).  So iwetv in the read run's record at
#                 07:00 minus iwetv in the file read must be at most 13,
#                 the steps from 05:55 to 07:00, and 13 for some element;
#                 and the log must say "setweg clock reset to the start of
#                 the run" with 21300 s.  Any start other than the
#                 record's time shows the clock so (an explicit itrst; the
#                 case takes one step before the record); with itrst = -1
#                 the start is set to the record's time (dtanf is that
#                 time), and the two clocks are the same.  No result file
#                 shows it here: iwetv decides only the re-wetting of an
#                 element dry for some steps (and the simple sediments),
#                 and no element is dry in this run; the restart record
#                 written by the read run shows it.  What it pins is dtanf
#                 against the record's time, not the reset line itself:
#                 with an explicit itrst the cold start's clock is already
#                 the STR's itanf (setup_time runs before setweg(0)), which
#                 equals dtanf, so the case passes also without the reset
#                 (measured).  The reset matters with itrst = -1, where the
#                 start moves to the record's time after setweg(0) while
#                 the cold clock stays at the STR's itanf (when that
#                 differs): clock_itrst_last pins it.  The log must also
#                 say "windcd not applied (itdrag = 0 here and in the
#                 file; windcd is restored only with itdrag = 3 or 4)"
#                 once, and not the old "(file itdrag = 0, run itdrag =
#                 0)", which read like a mismatch (#330)
#   clock_itrst_last  (#330, the setweg clock reset itself) mm_i0's write
#                 run (record at 06:00) read with mm_i0's read STR, itrst
#                 = -1 and itanf = 00:00, to 07:00, writing its last record
#                 (idtrst = -1, at 07:00): setweg(0) sets the clock to the
#                 STR's itanf, 00:00, at the set-up, and the restart then
#                 moves the start to the record's time, 06:00 (dtanf); the
#                 reset (dtime_setweg_old = dtanf) sets the clock to 06:00,
#                 so the first set_dry, at 06:00, counts no new step.
#                 Without it set_dry counts one at 06:00 and the step
#                 another at 06:05: iwetv in the read run's record at 07:00
#                 minus iwetv in the file read must be at most 12, the
#                 steps from 06:00 to 07:00, and 12 for some element
#                 (measured with the reset line taken out: 13, and the
#                 clock 0); the log must say "setweg clock reset to the
#                 start of the run" with 21600 s and the record's time,
#                 21600 s; and the windcd line of clock_itrst_after_start.
#                 As there, no result file shows it (only an element that
#                 re-wets in the read window would), the restart record
#                 written by the read run does
#   idtoff_unparsed  (#330) mm_h6d4's write run read with idtoff = 'xyz',
#                 a string convert_time_d cannot parse (the restart reader
#                 decodes idtoff with it, offline_reads_ts, as hydro is
#                 wanted and the heat flux runs, before handle_offline
#                 does), serially (r) and on 2 processes (p): each must
#                 stop with exit code 33 (shympi_abort_internal; before, a
#                 bare stop ended each process with exit 0, and mpirun
#                 exited 1), print "error stop convert_time_d: cannot parse
#                 idtoff" (once serially, at least once on 2 processes, as
#                 MPI_ABORT may stop the other process before it prints)
#                 and not end the simulation; p's log must show both ranks
#   tools         rstinf and rst2shy (this build's, on PATH) on version 20
#                 files; three write runs of this binary, serial, with a
#                 record every 3 h (m20: mm_h6d4's write run, 03:00 and
#                 06:00) or every hour (k20: ven_keps_s's, with k-epsilon;
#                 g20: ven_s's, with GOTM; 01:00 to 03:00).  On each file:
#                 rstinf lists version 20, the number of records, the
#                 version 20 records of the hydro block, the writer's itdrag
#                 (m 4, k and g 0), the heat flag (1: qflux3d ran) and
#                 whether the turbulence block holds the k-epsilon state;
#                 rstinf of the file and of a copy finds no difference in
#                 any record; rstinf of the file and of the file with some
#                 version 20 records of its first record changed (m: evapv,
#                 windcd, tws, dtw; k: evapv, tken, difv; g: tws) names
#                 exactly those records; rst2shy converts every record, and
#                 each record it writes is the write run's own output record
#                 at the same time (.hydro.shy, and .ts.shy but rho, which
#                 the model does not write), byte for byte; and it writes
#                 every record of the write run's output at each restart
#                 record's time (m: 3 h and 6 h, k and g: 1, 2 and 3 h, from
#                 idtrst and the end of the write run), so a converted
#                 record that is missing fails too (#323); a canary drops
#                 the converted records of the last restart time from a
#                 copy, which must fail
#   tools_v19     (a merge-time check, needs REF_BIN_DIR, see below)
#                 rstinf and rst2shy on version 19 files as REF_BIN_DIR's:
#                 the same three write runs by REF_BIN_DIR (m19, k19, g19);
#                 rstinf (list, and file against copy) and rst2shy print
#                 what REF_BIN_DIR's print (but the commit line of the
#                 banner), and rst2shy's .shy files are the same bytes as
#                 REF_BIN_DIR's; without REF_BIN_DIR the case is skipped
# and a case kept out of the default list, a canary for the comparator:
#   mm_e0         mm_i0 with ievap = 0: no evaporation, no wet/dry, no
#                 closure, so it passes also with main before version 20
# Required for a case: the three runs end (exit code 0 and "simulation
# end" in the log, timeout 1200 s each); the log of an NP-process run has
# "shympi initialized: ID NP" once from each rank 0 to NP-1 (so that NP
# serial runs, from an mpirun that does not match the binary's MPI,
# cannot pass); the read run's log has "A restart has been performed"
# once from every rank and its restart time is the write run's end; and
# every record of the read run's .hydro.shy, .ts.shy and .ext equals the
# continuous run's record at the same time: max|d| = 0, compared with
# shy_maxdiff.py (next to this script).  A record of the read run with no
# record of the continuous run at its time or before the first record the
# read run must write, or one of the continuous run from that first record
# on with none in the read run, is a difference (#323).  That first record
# comes from the case's settings, never from the read run's file (firsth):
# the read run starts at the restart time TR (itrst = -1 sets itanf to
# it), and by the rule of adjust_itmidt_d (src/shyfem/outputd.f90) a .shy
# file writes its first record one output step after the start when the
# STR sets no itmout (.hydro.shy) or itmcon (.ts.shy), as mm_hyd_41.str
# (7h for a restart at 6h), and at the start if the STR sets it to its
# start date, as venlag_smoke.str (3h); the .ext writes at the start
# (extra.f90 calls assure_initial_output_d).  Each comparison of two read
# runs (the cases of another kind) uses the same first records.  A canary
# of each case of the first list drops the first expected record of each
# file from a copy of the read run's file, which the comparator must
# reject.  With it, a self-check of the comparator's two guards of --first
# (#330), on inputs made from each file of the case: the read run's file
# with the continuous run's records at its last output time before the
# first expected record added, which the comparator must reject with exit
# 1 ("before the first record B must have"), and the continuous run's
# file without its records at the first expected record, which it must
# reject with exit 2 ("has no record at"); so that a guard taken out of
# shy_maxdiff.py fails here.
#
# Prints one line per case,
#   case NAME: max|d| zeta X@T, transport X@T, S X@T, T X@T, ext X -> PASS|FAIL
# (X@T: the largest difference of the variable and the hour where it
# occurs, from the start date; ext X: the largest of the .ext file), or
# "case NAME: did not run (reason) -> FAIL", each followed by the summary
# lines of shy_maxdiff.py (for the .shy files with the differences in the
# first hour after the restart and at the end); then the time of each case
# and the total, and "RESTART FIDELITY: PASS" (with "(N cases skipped:
# they need REF_BIN_DIR)" when old_v19 or tools_v19 is skipped) or
# "RESTART FIDELITY: FAIL", and exits 0 or 1.  A skipped case prints
# "case NAME: skipped (needs REF_BIN_DIR: ...) -> SKIPPED" and does not
# fail the run.
#
# Usage:  [REF_BIN_DIR=DIR] ./check_restart_fidelity.sh [case ...]
#         (no case: every case but mm_e0)
# REF_BIN_DIR, for the merge-time checks old_v19 and tools_v19: the bin
# folder of a build of the last main commit before version 20, that is
# 9187cdf1 or, once version 20 is merged, the first parent of its merge
# commit (git rev-parse MERGE^1).  Not origin/main after the merge, which
# writes version 20 too, and not v8.6.0: #248 and #283 changed the results
# of iturb = 0 3D runs and of iturb = 2 runs after it.  Build it in a
# throwaway work tree, from the repository:
#   git worktree add --detach /tmp/ref19 9187cdf1
#   (cd /tmp/ref19 && PATH=/usr/bin:$PATH make fem NETCDF=true NETCDFDIR=/usr NETCDFFDIR=/usr/local)
#   REF_BIN_DIR=/tmp/ref19/bin ./check_restart_fidelity.sh
#   git worktree remove --force /tmp/ref19
# Without REF_BIN_DIR the two cases are skipped; with a REF_BIN_DIR that
# lacks shyfem (or, for tools_v19, rstinf or rst2shy) they fail.  The
# other cases need this build alone.
# Needs shyfem, shypre and python3 with numpy on PATH, rstinf and rst2shy
# for the cases tools and tools_v19, and mpirun (an OpenMPI build) for the
# cases on several processes (*_np*, idtoff_unparsed).  Works in a folder
# made with mktemp -d under ${TMPDIR:-/tmp}: the basins are built there
# with shypre from GRID/MM_coarse_smooth.grd and ../venice_lagoon/GRID/
# venlag62.grd, INPUT is linked and the STR files are made there with sed
# from mm_hyd_41.str and venlag_smoke.str, so nothing in the source
# folders changes (python3 -B: the import of shy_maxdiff writes no
# __pycache__ next to it, #323).  The cases run at the same time (52
# processes at the start with REF_BIN_DIR, 48 without); every mpirun has
# --bind-to none, so that the runs do not share the two cores Open MPI
# binds a 2-process run to.  Takes about 2 minutes on the development
# machine (the serial venlag cases are the longest).
# The folder is removed when every case passes and kept otherwise (its
# path is printed before the verdict, which is the last line).
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
ALL="mm_i0 mm_i1 mm_h6d4 mm_h6noon ven_s ven_np2 ven_np4 ven_keps_s ven_keps_np4"
ALL="$ALL old_v19 drag0_reads_cd4 drag4_reads_cd0 drag4_noheat_reads_cd4 flgrst_no_hydro evap_reads_noheat"
ALL="$ALL keps_to_gotm offline_ts_noheat offline_ts_noheat_str clock_itrst_after_start clock_itrst_last"
ALL="$ALL idtoff_unparsed tools tools_v19"
OPT="mm_e0"     # cases kept out of the default list
CASES="${*:-$ALL}"
needmm=no; needven=no; needmpi=no; needtools=no
for c in $CASES; do
  case " $ALL $OPT " in *" $c "*) ;; *) echo "usage: [REF_BIN_DIR=DIR] $0 [case ...], cases: $ALL (and $OPT)"; exit 2 ;; esac
  case "$c" in
    mm_*|drag*_reads_*|flgrst_no_hydro|evap_reads_noheat|offline_ts_noheat*|clock_itrst_*|idtoff_unparsed) needmm=yes ;;
    ven_*|old_v19|keps_to_gotm) needven=yes ;;
    tools|tools_v19) needmm=yes; needven=yes; needtools=yes ;;
  esac
  case "$c" in *_np*|idtoff_unparsed) needmpi=yes ;; esac
done
tools="shyfem shypre python3"
[ "$needmpi" = yes ] && tools="$tools mpirun"
[ "$needtools" = yes ] && tools="$tools rstinf rst2shy"
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
  for f in "$P"/*/*/run.pid; do
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
  TRH=$(( 10#$tr ))
  FHYD="$(firsth "$d/r/r.str" itmout idtout)" && FTS="$(firsth "$d/r/r.str" itmcon idtcon)" \
    && FEXT="$(firsth "$d/r/r.str" itmext idtext ext)" || return 1
  RTIME="2009-01-01::$tr:00:00"; H1=$(( 10#$tr + 1 )); H2=$(( 10#$te ))
}
# firsth STR ITM IDT [ext]: the hour, from the start date, of the first
# record that the read run of the STR file STR, from the restart time TRH
# (hours from the start date), writes into the file whose output start
# and step the STR sets with ITM and IDT (itmout idtout: .hydro.shy,
# itmcon idtcon: .ts.shy, itmext idtext: .ext, with "ext"), by the rule of
# adjust_itmidt_d (src/shyfem/outputd.f90): the read run starts at TRH
# (itrst = -1 sets itanf to it); a .shy file writes its first record one
# step IDT after the start if the STR does not set ITM, and at the start
# if it sets ITM to its own start date (itanf); the .ext writes at the
# start in both cases (assure_initial_output_d, extra.f90).  Prints
# nothing and fails for any other ITM, or a .shy IDT not in whole hours.
# Never from the read run's file: that is what the comparator checks.
firsth() {
  local str="$1" itm="$2" idt="$3" ext="${4:-}" vm va vd
  vm="$(sed -n "s/^.*[[:space:]]$itm[[:space:]]*=[[:space:]]*'\([^']*\)'.*\$/\1/p" "$str")"
  va="$(sed -n "s/^.*[[:space:]]itanf[[:space:]]*=[[:space:]]*'\([^']*\)'.*\$/\1/p" "$str")"
  vd="$(sed -n "s/^.*[[:space:]]$idt[[:space:]]*=[[:space:]]*'\([0-9]*\)h'.*\$/\1/p" "$str")"
  [ "$(echo "$va" | wc -w)" = 1 ] || return 1
  if [ -n "$vm" ]; then
    [ "$vm" = "$va" ] || return 1
  elif grep -q "[[:space:]]$itm[[:space:]]*=" "$str"; then
    return 1
  elif [ -z "$ext" ]; then
    [ "$(echo "$vd" | wc -w)" = 1 ] || return 1
    echo $(( TRH + vd )); return 0
  fi
  echo "$TRH"
}
# firstof F: the first record (firsth) of the file kind F (hydro.shy,
# ts.shy or ext) of the case mkmm or mkven made
firstof() {
  case "$1" in hydro.shy) echo "$FHYD" ;; ts.shy) echo "$FTS" ;; ext) echo "$FEXT" ;; esac
}
# evap0 CASE: the STR files mkmm made, with ievap = 0
evap0() {
  local s
  for s in c w r; do
    sed -i 's/^\(        iturb = [0-9]      ievap = \)1 /\10 /' "$P/$1/$s/$s.str" || return 1
    grep -q '^        iturb = [0-9]      ievap = 0 ' "$P/$1/$s/$s.str" || return 1
  done
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
  TRH=3
  FHYD="$(firsth "$d/r/r.str" itmout idtout)" && FTS="$(firsth "$d/r/r.str" itmcon idtcon)" \
    && FEXT="$(firsth "$d/r/r.str" itmext idtext ext)" || return 1
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
# runx DIR NAME NP [BIN]: runs DIR/NAME.str with BIN (default: shyfem on
# PATH) on NP processes, its output in DIR/NAME.log; returns its exit code
runx() {
  local d="$1" n="$2" np="$3" bin="${4:-shyfem}" r
  if [ "$np" = 1 ]; then
    ( cd "$d" && OMP_NUM_THREADS=1 exec timeout 1200 nice -n 10 "$bin" "$n.str" < /dev/null > "$n.log" 2>&1 ) &
  else
    ( cd "$d" && OMP_NUM_THREADS=1 exec timeout 1200 nice -n 10 mpirun --oversubscribe --bind-to none -np "$np" \
        "$bin" "$n.str" < /dev/null > "$n.log" 2>&1 ) &
  fi
  echo "$!" > "$d/run.pid"
  wait "$!"
  r=$?
  rm -f "$d/run.pid"
  return "$r"
}
# run DIR NAME NP [BIN]: runx, which must end the run (exit code 0,
# "simulation end", and NP processes); prints why it failed, if it did
run() {
  local d="$1" n="$2" np="$3" r
  runx "$@"
  r=$?
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
  local cs="$1" d="$P/$1" np=1 s t0 why rc pc pw f k line="" ext="" un=0 nr fh can="" grd=""
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
    mm_e0)        mkmm "$cs" 0 06 12 && evap0 "$cs" ;;
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
    fh="$(firstof "$f")"
    python3 -B "$HERE/shy_maxdiff.py" --first "$fh" "$d/c/c.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    if [ "$k" != 0 ] && [ "$k" != 1 ]; then
      why="$why$f: $(grep -v '^ \|^SUMMARY' "$d/cmp.$f.txt" | head -1); "
      continue
    fi
    # the canary: r's file without its first expected record must fail;
    # and the comparator's two guards of --first, on inputs made from c's
    # and r's files
    can="$can$(canary "$d/c/c.$f" "$d/r/r.$f" "$d/drop.$f" "$fh")"
    grd="$grd$(guards "$d/c/c.$f" "$d/r/r.$f" "$d" "$f" "$fh")"
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
  if [ -n "$can" ]; then line="$line; canary: ${can%; }"; rc=1; fi
  if [ -n "$grd" ]; then line="$line; guards of --first: ${grd%; }"; rc=1; fi
  echo "    first records required: hydro.shy ${FHYD}h, ts.shy ${FTS}h, ext ${FEXT}h; canary (each without it):" \
       "$(if [ -z "$can" ]; then echo rejected; else echo FAILED; fi); guards of --first (a record of r before it," \
       "c without it): $(if [ -z "$grd" ]; then echo rejected; else echo FAILED; fi)" >> "$d.detail"
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}
# shyfix MODE SRC DST H [ARG ...]: DST is the .shy or .ext file SRC with
# other data records, H in hours from the file's start date (the hours of
# shy_maxdiff.py); prints what it did:
#   drop   SRC without its records at H, or at its last time if H is
#          "last"; fails if there is none
#   keep   only SRC's records at H or before whose variable (ivar) is one
#          of ARG...; none kept is no error (the comparator rejects a file
#          without data records)
#   graft  SRC with the records of the file ARG (of the same kind, A of a
#          comparison) at ARG's last time before H added before its own;
#          fails if ARG has none
shyfix() {
  python3 -B - "$HERE" "$@" << 'EOF'
import struct, sys
sys.path.insert(0, sys.argv[1])
import shy_maxdiff
mode, src, dst, h, args = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6:]
def parts(path):    # kind, header records, t0, data records (each a list of its records)
    recs = shy_maxdiff.records(path)
    kind = shy_maxdiff.kind_of(recs, path)
    if kind == 'shy':
        i0 = [k for k, r in enumerate(recs) if len(r) == 0][1] + 1   # header: to its second empty record
        t0, step = 0., 2                                               # data: (time, ivar, n, m, lmax), values
    else:
        i0 = 7                                                          # header: 7 records, atime0 the third
        t0, step = struct.unpack('<d', recs[2])[0], 1                  # data: (atime, ivar, ...) values
    return kind, recs[:i0], t0, [recs[i:i + step] for i in range(i0, len(recs), step)]
def tim(d):         # the time of a data record (the first 8 bytes)
    return struct.unpack_from('<d', d[0])[0]
def ivar(d):        # its variable (the integer after the time)
    return struct.unpack_from('<i', d[0], 8)[0]
kind, head, t0, data = parts(src)
ts = [tim(d) for d in data]
t = max(ts) if h == 'last' and ts else t0 + 3600. * float(h if h != 'last' else 0)
if mode == 'drop':
    keep = [d for d in data if abs(tim(d) - t) >= 0.5]
    n = len(data) - len(keep)
    if n == 0:
        sys.exit(f"no data record at {h}h in {src}")
    msg = f"{n} records at {(t - t0) / 3600.:g}h dropped"
elif mode == 'keep' and h != 'last' and args:
    iv = {int(a) for a in args}
    keep = [d for d in data if tim(d) < t + 0.5 and ivar(d) in iv]
    msg = f"{len(keep)} records of variables {' '.join(args)} at {h}h or before kept"
elif mode == 'graft' and h != 'last' and len(args) == 1:
    ko, _, _, other = parts(args[0])
    if ko != kind:
        sys.exit(f"{args[0]} is a .{ko} file, {src} a .{kind} file")
    before = [tim(d) for d in other if tim(d) < t - 0.5]
    if not before:
        sys.exit(f"{args[0]} has no data record before {h}h")
    tg = max(before)
    add = [d for d in other if abs(tim(d) - tg) < 0.5]
    keep = add + data
    msg = f"{len(add)} records of {args[0]} at {(tg - t0) / 3600.:g}h added"
else:
    sys.exit(f"shyfix: bad arguments {' '.join(sys.argv[2:])}")
with open(dst, 'wb') as fp:
    for r in head + [r for d in keep for r in d]:
        fp.write(struct.pack('<i', len(r)) + r + struct.pack('<i', len(r)))
print(msg)
EOF
}
# shydrop SRC DST H: shyfix drop (SRC without its records at H, or at its
# last time if H is "last")
shydrop() {
  shyfix drop "$@"
}
# canary A B DROP H: B (a read run's file, which passed against A) without
# its records at H, the first record it must have, is DROP; the comparator
# must reject it (exit 1, A's records at H not in DROP); prints "B: reason; "
# if not
canary() {
  local k w
  w="$(shydrop "$2" "$3" "$4" 2>&1)" || { echo -n "${2##*/}: cannot drop its records at ${4}h ($w); "; return; }
  python3 -B "$HERE/shy_maxdiff.py" --first "$4" "$1" "$3" > "$3.txt" 2>&1
  k=$?
  if [ "$k" != 1 ] || ! grep -q "^  t= *$4\.000h .* of A: no record in B at this time\$" "$3.txt"; then
    echo -n "${2##*/} without its records at ${4}h not rejected (exit $k, see $3.txt); "
  fi
}
# guards A B DIR F H: the two guards of the comparator's --first, on
# inputs made from A and B (a case's files of kind F, which passed, H the
# first record B must have): B with A's records at A's last time before H
# added (DIR/g1.F) must be rejected with exit 1 and "of B: before the
# first record B must have (Hh)", and A without its records at H
# (DIR/g2.F) with exit 2 and "has no record at Hh (--first)"; prints
# "F: reason; " for each that is not
guards() {
  local a="$1" b="$2" dd="$3" f="$4" h="$5" k w
  if ! w="$(shyfix graft "$b" "$dd/g1.$f" "$h" "$a" 2>&1)"; then
    echo -n "$f: cannot add A's records before ${h}h to B ($w); "
  else
    python3 -B "$HERE/shy_maxdiff.py" --first "$h" "$a" "$dd/g1.$f" > "$dd/g1.$f.txt" 2>&1
    k=$?
    if [ "$k" != 1 ] || ! grep -q "of B: before the first record B must have (${h}h)\$" "$dd/g1.$f.txt"; then
      echo -n "$f: B with A's records before ${h}h not rejected (exit $k, see $dd/g1.$f.txt); "
    fi
  fi
  if ! w="$(shydrop "$a" "$dd/g2.$f" "$h" 2>&1)"; then
    echo -n "$f: cannot drop A's records at ${h}h ($w); "
  else
    python3 -B "$HERE/shy_maxdiff.py" --first "$h" "$dd/g2.$f" "$b" > "$dd/g2.$f.txt" 2>&1
    k=$?
    if [ "$k" != 2 ] || ! grep -q "has no record at ${h}h (--first)\$" "$dd/g2.$f.txt"; then
      echo -n "$f: --first ${h}h with no record in A not rejected (exit $k, see $dd/g2.$f.txt); "
    fi
  fi
}
# athour CMPFILE H: " NAME X ..." of the lines "t= H.000h NAME max|d|=X"
# of shy_maxdiff.py
athour() {
  awk -v h="$2" '/^  t=/ { s = $0; sub(/^ *t= */, "", s); split(s, f, " "); t = f[1]; sub(/h$/, "", t)
    if (t + 0 == h + 0 && f[3] ~ /^max/) { v = f[3]; sub(/^max\|d\|=/, "", v); printf " %s %s", f[2], v } }' "$1"
}

#--- the cases of another kind (old_v19, drag0_reads_cd4, drag4_reads_cd0, drag4_noheat_reads_cd4,
#    flgrst_no_hydro, evap_reads_noheat, keps_to_gotm, offline_ts_noheat, offline_ts_noheat_str,
#    clock_itrst_after_start, clock_itrst_last, idtoff_unparsed; tools and tools_v19 below)
# rundir DIR mm|ven: a run folder with its own copy of the basin and INPUT
rundir() {
  mkdir "$1" && mkdir "$1/GRID" || return 1
  case "$2" in
    mm)  cp "$P/mmbas/MM_coarse_smooth.bas" "$1/GRID/" && ln -s "$HERE/INPUT" "$1/INPUT" ;;
    ven) cp "$P/venbas/venlag62.bas" "$1/GRID/" && ln -s "$VEN/INPUT" "$1/INPUT" ;;
  esac
}
# readok LOG: a serial read run's log shows the restart once, at RTIME;
# prints why not
readok() {
  local k
  k="$(grep -c 'A restart has been performed' "$1")"
  [ "$k" = 1 ] || { echo "'A restart has been performed' $k times in $1, not 1"; return 1; }
  k="$(grep -c "used restart time = *$RTIME *\$" "$1")"
  [ "$k" = 1 ] || { echo "restart time $RTIME $k times in $1, not 1"; return 1; }
  return 0
}
# donecase CASE T0 WHY: writes CASE.time; with WHY, the "did not run" line
donecase() {
  echo "$1 $(( $(date +%s) - $2 )) s" > "$P/$1.time"
  [ -z "$3" ] && return 0
  echo "case $1: did not run (${3%; }) -> FAIL" > "$P/$1.line"
  return 1
}

# same19 A B H OUT: the files A (m's) and B (r's) of old_v19 are the same:
# the comparator, with B's first record H, exits 0 (its output in OUT),
# and cmp finds the same bytes; prints "same bytes" or why not, and fails
# unless both hold (cmp alone would pass two files that both lack their
# first record, #330)
same19() {
  local k bad=""
  python3 -B "$HERE/shy_maxdiff.py" --first "$3" "$1" "$2" > "$4" 2>&1
  k=$?
  [ "$k" = 0 ] || bad="comparator exit $k, "
  cmp -s "$1" "$2" || bad="${bad}DIFFERS (cmp), "
  if [ -n "$bad" ]; then echo -n "${bad%, }"; return 1; fi
  echo -n "same bytes"
}

# case_old_v19: a version 19 file read as main reads it
case_old_v19() {
  local cs=old_v19 d="$P/old_v19" s t0 why="" f k w rc=0 ref pr pm line="" fh can=""
  t0=$(date +%s)
  ref="${REF_BIN_DIR:-}/shyfem"
  if [ -z "${REF_BIN_DIR:-}" ]; then
    echo "case $cs: skipped (needs REF_BIN_DIR: a build of the last main commit before version 20) -> SKIPPED" > "$d.line"
    return 0
  fi
  if [ ! -x "$ref" ]; then
    echo "case $cs: did not run (REF_BIN_DIR='${REF_BIN_DIR:-}' has no shyfem; it must be the bin folder of a build" \
         "of the last main commit before version 20) -> FAIL" > "$d.line"
    return 1
  fi
  mkdir "$d" || return 1
  for s in c w r m; do rundir "$d/$s" ven || return 1; done
  RTIME=""
  if ! mkven "$cs" 1 || [ -z "$RTIME" ] || ! cp "$d/r/r.str" "$d/m/r.str"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # w: REF_BIN_DIR writes the version 19 file; r (this binary) and m
  # (REF_BIN_DIR) read it
  if ! run "$d/w" w 1 "$ref" > "$d/w.why"; then
    why="REF_BIN_DIR $(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  else
    ln -s ../w/w.rst "$d/r/w.rst" && ln -s ../w/w.rst "$d/m/w.rst" || return 1
    run "$d/r" r 1 > "$d/r.why" & pr=$!
    run "$d/m" r 1 "$ref" > "$d/m.why" & pm=$!
    if wait "$pr"; then
      w="$(readok "$d/r/r.log")" || why="${why}r: $w; "
      k="$(grep -c 'nvers = *19 *$' "$d/r/r.log")"
      [ "$k" = 1 ] || why="${why}r: 'nvers = 19' $k times in $d/r/r.log, not 1 (REF_BIN_DIR must write version 19); "
      k="$(grep -c 'setweg clock not reset' "$d/r/r.log")"
      [ "$k" = 1 ] || why="${why}r: 'setweg clock not reset' $k times in $d/r/r.log, not 1; "
    else
      why="$why$(cat "$d/r.why"); "
    fi
    if wait "$pm"; then
      w="$(readok "$d/m/r.log")" || why="${why}m: $w; "
    else
      why="${why}REF_BIN_DIR $(cat "$d/m.why"); "
    fi
  fi
  donecase "$cs" "$t0" "$why" || return 1
  : > "$d.detail"
  for f in hydro.shy ts.shy ext; do
    fh="$(firstof "$f")"
    w="$(same19 "$d/m/r.$f" "$d/r/r.$f" "$fh" "$d/cmp.$f.txt")" || rc=1
    line="${line}$f $w, "
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    [ -n "$s" ] || s="$(head -1 "$d/cmp.$f.txt")"
    echo "    $f (m against r): ${s#SUMMARY *: }" >> "$d.detail"
    # the canary: both files without their first expected record are the
    # same bytes, so only the comparator (exit 2: A has no record at fh)
    # can reject them
    if ! shydrop "$d/m/r.$f" "$d/dropm.$f" "$fh" > /dev/null 2>&1 \
       || ! shydrop "$d/r/r.$f" "$d/dropr.$f" "$fh" > /dev/null 2>&1; then
      can="$can$f: cannot drop its records at ${fh}h; "
    elif w="$(same19 "$d/dropm.$f" "$d/dropr.$f" "$fh" "$d/drop.$f.txt")"; then
      can="$can$f of m and r without their records at ${fh}h passed ($w); "
    else
      case "$w" in
        *"comparator exit 2"*) ;;
        *) can="$can$f of m and r without their records at ${fh}h not rejected by the comparator ($w); " ;;
      esac
    fi
  done
  echo "    first records required: hydro.shy ${FHYD}h, ts.shy ${FTS}h, ext ${FEXT}h; canary (m and r without it):" \
       "$(if [ -z "$can" ]; then echo rejected; else echo FAILED; fi)" >> "$d.detail"
  line="case $cs: REF_BIN_DIR's version 19 file read by this binary and by REF_BIN_DIR: ${line%, }"
  if [ -n "$can" ]; then line="$line; canary: ${can%; }"; rc=1; fi
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}

# rstpatch SRC DST NAME=VALUE ...: DST is the version 20 restart file SRC
# with every value of the record NAME of its first time record set to
# VALUE (as a 4-byte real); NAME is evapv, windcd, tws or dtw (hydro
# block) or tken, eps, visv or difv (turbulence block of a k-epsilon
# file); walks the record markers and checks the sizes of the records of
# the hydro block (and, for a turbulence record, of the records up to it),
# so that a change of the layout fails here; fails if a record already
# holds VALUE everywhere (then the read of SRC and of DST could not differ)
rstpatch() {
  python3 -B - "$@" << 'EOF'
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
HYDRO = ('evapv', 'windcd', 'tws', 'dtw')
KEPS = ('tken', 'eps', 'visv', 'difv')
sets = []                       # (record name, value) to set
for arg in sys.argv[3:]:
    nm, _, val = arg.partition('=')
    if nm not in HYDRO + KEPS or not val:
        sys.exit(f"bad argument {arg}: NAME=VALUE, NAME one of {' '.join(HYDRO + KEPS)}")
    sets.append((nm, float(val)))
if not sets:
    sys.exit("nothing to set")
data = bytearray(open(src, 'rb').read())
recs = []                       # (offset of the data, length) of each record
pos = 0
while pos < len(data):
    if pos + 4 > len(data):
        sys.exit(f"truncated record marker at byte {pos}")
    n = struct.unpack_from('<i', data, pos)[0]
    end = pos + 4 + n
    if n < 0 or end + 4 > len(data) or struct.unpack_from('<i', data, end)[0] != n:
        sys.exit(f"bad record at byte {pos} (length {n})")
    recs.append((pos + 4, n))
    pos = end + 4
def ints(i):
    o, n = recs[i]
    return struct.unpack_from(f'<{n // 4}i', data, o)
# header: idfile nvers nrec; date time; atime; nkn nel nlv
if len(recs) < 4 or recs[0][1] != 12 or recs[3][1] != 12:
    sys.exit("not a restart file (records 1 and 4 are not 3 integers)")
nvers = ints(0)[1]
if nvers != 20:
    sys.exit(f"the file is version {nvers}, not 20")
nkn, nel, nlv = ints(3)
i = 4 + (3 if nlv > 1 else 0)   # hlv, ilhv, ilhkv
names = ['iwegv', 'znv', 'zenv', 'utlnv', 'vtlnv', 'iwetv', 'evapv', 'itdrag', 'windcd',
         'heat flag', 'tws', 'dtw', 'hm3v']
sizes = [nel, nkn, 3 * nel, nlv * nel, nlv * nel, nel, nkn, 1, nkn, 1, nkn, nkn, 3 * nel]
if len(recs) < i + len(names):
    sys.exit(f"the file has {len(recs)} records, too few for the hydro block")
for k, (nm, sz) in enumerate(zip(names, sizes)):
    if recs[i + k][1] != 4 * sz:
        sys.exit(f"record {nm} has {recs[i + k][1]} bytes, not {4 * sz}")
where = {nm: i + k for k, nm in enumerate(names)}       # record index of each name
if any(nm in KEPS for nm, _ in sets):
    # after hm3v: ibarcl [saltv tempv rhov] iturb [tken eps visv difv]
    def need(j, nm, sz):
        if len(recs) <= j or recs[j][1] != 4 * sz:
            sys.exit(f"record {nm} is missing or has not {4 * sz} bytes")
    j = i + len(names)
    need(j, 'ibarcl', 1)
    ibarcl = ints(j)[0]
    j += 1
    if ibarcl > 0:
        for nm in ('saltv', 'tempv', 'rhov'):
            need(j, nm, nlv * nkn)
            j += 1
    need(j, 'iturb', 1)
    iturb = ints(j)[0]
    if iturb != 2:
        sys.exit(f"the file's iturb is {iturb}, not 2: no k-epsilon records")
    for k, nm in enumerate(KEPS):
        need(j + 1 + k, nm, (nlv + 1) * nkn)
        where[nm] = j + 1 + k
for nm, val in sets:
    o, nb = recs[where[nm]]
    n = nb // 4
    x = struct.unpack_from(f'<{n}f', data, o)
    v = struct.unpack('<f', struct.pack('<f', val))[0]
    ndiff = sum(1 for y in x if y != v)
    print(f"{nm} of the file: {n} values from {min(x):.6g} to {max(x):.6g}, {ndiff} differ from "
          f"{v:.6g}; heat flag {ints(i + names.index('heat flag'))[0]}, "
          f"itdrag {ints(i + names.index('itdrag'))[0]}")
    if ndiff == 0:
        sys.exit(f"the file's {nm} is {v:.6g} everywhere: r and p could not differ")
    struct.pack_into(f'<{n}f', data, o, *([v] * n))
with open(dst, 'wb') as fp:
    fp.write(data)
EOF
}
# dlog LOG NAME PATTERN: the checks of a read log of drag0_reads_cd4,
# drag4_reads_cd0 or drag4_noheat_reads_cd4 (PATTERN: the windcd line, a
# fixed string); prints "NAME: reason; " for each one that fails
dlog() {
  local w k
  w="$(readok "$1")" || echo -n "$2: $w; "
  k="$(grep -c -F -- "$3" "$1")"
  [ "$k" = 1 ] || echo -n "$2: '$3' $k times in $1, not 1; "
}
# case_drag CASE WITD RITD RDC WHEAT: a file written with itdrag = WITD
# (mm_h6d4's write run with that itdrag; with WHEAT 0 also with ibarcl =
# 0, so that its qflux3d never runs and its heat flag is 0) read with
# itdrag = RITD (and dragco = RDC, if not empty) and the heat flux
# running: the reader keeps its own dragco, not the file's windcd, so the
# read r must equal the read p of the same file with windcd set to the
# reader's dragco (compared even if a log line is missing); both logs say
# "windcd not applied (file itdrag = WITD, run itdrag = RITD)", or, with
# WITD = RITD = 4, "windcd not applied (itdrag = 4, file heat flag not
# set)"; and the patch's line shows the file's heat flag WHEAT and itdrag
# WITD (else the case would not test what it says).  With WITD = RITD = 4
# a third read n of w's file without heat flux (r's STR with ibarcl = 0)
# must log "windcd not applied (itdrag = 4, no heat flux, file heat flag
# not set)" (#330)
case_drag() {
  local cs="$1" witd="$2" ritd="$3" rdc="$4" wh="$5" d="$P/$1" s t0 why="" lw="" f k rc=0 pr pp pn line="" cmpl="" dc="" pat
  local patn="" rs="r p"
  if [ "$witd" = "$ritd" ]; then
    pat="windcd not applied (itdrag = $ritd, file heat flag not set)"
    patn="windcd not applied (itdrag = $ritd, no heat flux, file heat flag not set)"
    rs="r p n"
  else
    pat="windcd not applied (file itdrag = $witd, run itdrag = $ritd)"
  fi
  t0=$(date +%s)
  mkdir "$d" || return 1
  for s in c w $rs; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 "iheat = 6   itdrag = $witd" && [ -n "$RTIME" ]; then
    sed -i "s/^        iheat = 6   itdrag = $witd\$/        iheat = 6   itdrag = $ritd/" "$d/r/r.str"
    [ -n "$rdc" ] && sed -i "s/dragco = [^ ]*/dragco = $rdc/" "$d/r/r.str"
    [ "$wh" = 0 ] && sed -i 's/^        ibarcl = 3$/        ibarcl = 0/' "$d/w/w.str"
    dc="$(sed -n 's/.*dragco = \([^ ]*\).*/\1/p' "$d/r/r.str")"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c "^        iheat = 6   itdrag = $ritd\$" "$d/r/r.str")" != 1 ] \
     || [ "$(echo "$dc" | wc -w)" != 1 ] || { [ -n "$rdc" ] && [ "$dc" != "$rdc" ]; } \
     || [ "$(grep -c '^        ibarcl = 3$' "$d/r/r.str")" != 1 ] \
     || { [ "$wh" = 0 ] && [ "$(grep -c '^        ibarcl = 0$' "$d/w/w.str")" != 1 ]; } \
     || ! cp "$d/r/r.str" "$d/p/r.str"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  if [ -n "$patn" ]; then
    sed 's/^        ibarcl = 3$/        ibarcl = 0/' "$d/r/r.str" > "$d/n/r.str"
    if [ "$(grep -c '^        ibarcl = 0$' "$d/n/r.str")" != 1 ]; then
      echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
    fi
  fi
  # w writes with itdrag = WITD; r reads w.rst, p the same file with windcd
  # set to the reader's dragco, both with itdrag = RITD (and n reads w.rst
  # without heat flux)
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  elif ! rstpatch "$d/w/w.rst" "$d/p/w.rst" "windcd=$dc" > "$d/patch.txt" 2>&1; then
    why="cannot set the windcd record of $d/w/w.rst: $(tail -1 "$d/patch.txt"); "
  else
    k="$(grep -c "; heat flag $wh, itdrag $witd\$" "$d/patch.txt")"
    [ "$k" = 1 ] || lw="the file of w has not heat flag $wh and itdrag $witd ($d/patch.txt); "
    ln -s ../w/w.rst "$d/r/w.rst" || return 1
    run "$d/r" r 1 > "$d/r.why" & pr=$!
    run "$d/p" r 1 > "$d/p.why" & pp=$!
    if [ -n "$patn" ]; then
      ln -s ../w/w.rst "$d/n/w.rst" || return 1
      run "$d/n" r 1 > "$d/n.why" & pn=$!
    fi
    if wait "$pr"; then lw="$lw$(dlog "$d/r/r.log" r "$pat")"; else why="${why}r: $(cat "$d/r.why"); "; fi
    if wait "$pp"; then lw="$lw$(dlog "$d/p/r.log" p "$pat")"; else why="${why}p: $(cat "$d/p.why"); "; fi
    if [ -n "$patn" ]; then
      if wait "$pn"; then lw="$lw$(dlog "$d/n/r.log" n "$patn")"; else why="${why}n: $(cat "$d/n.why"); "; fi
    fi
  fi
  donecase "$cs" "$t0" "$why" || return 1
  echo "    $(head -1 "$d/patch.txt")" > "$d.detail"
  for f in hydro.shy ts.shy ext; do
    python3 -B "$HERE/shy_maxdiff.py" --first "$(firstof "$f")" "$d/p/r.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    [ -n "$s" ] || s="$(head -1 "$d/cmp.$f.txt")"
    echo "    $f (p against r): ${s#SUMMARY *: }" >> "$d.detail"
    case "$k" in 0) cmpl="${cmpl}$f equal, " ;; 1) cmpl="${cmpl}$f DIFFERS, " ;; *) cmpl="${cmpl}$f not compared, " ;; esac
  done
  line="case $cs: itdrag = $ritd read (dragco $dc) of a file written with itdrag = $witd"
  [ "$wh" = 0 ] && line="$line without qflux3d (ibarcl = 0)"
  line="$line, against the same file with windcd = $dc: ${cmpl%, }"
  [ -n "$patn" ] && line="$line; n, the read without heat flux (ibarcl = 0), log checked"
  if [ -n "$lw" ]; then line="$line; log: ${lw%; }"; rc=1; fi
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}

# e0log LOG NAME: the log checks of evap_reads_noheat; prints "NAME:
# reason; " for each one that fails
e0log() {
  local k
  k="$(grep -c 'evapv not applied' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'evapv not applied' $k times in $1, not 1; "
  k="$(grep -c -F 'windcd not applied (itdrag = 4, no heat flux)' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'windcd not applied (itdrag = 4, no heat flux)' $k times in $1, not 1; "
}
# case_evap: a read whose qflux3d does not run (ibarcl = 0) keeps the
# cold evapv (0) and windcd (dragco), not the file's values
case_evap() {
  local cs=evap_reads_noheat d="$P/evap_reads_noheat" s t0 why="" lw="" w f k rc=0 pr pp line="" cmpl="" dc=""
  t0=$(date +%s)
  mkdir "$d" || return 1
  for s in c w r p; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 "iheat = 6   itdrag = 4" && [ -n "$RTIME" ]; then
    sed -i 's/^        ibarcl = 3$/        ibarcl = 0/' "$d/r/r.str"
    dc="$(sed -n 's/.*dragco = \([^ ]*\).*/\1/p' "$d/r/r.str")"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c '^        ibarcl = 0$' "$d/r/r.str")" != 1 ] \
     || [ "$(echo "$dc" | wc -w)" != 1 ] || ! cp "$d/r/r.str" "$d/p/r.str"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # w writes with the heat flux (evapv, COARE's windcd); r reads w.rst, p
  # the same file with evapv = 0 and windcd = dragco, both with ibarcl = 0
  # (ievap = 1, iheat = 6, itdrag = 4 as in w)
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  elif ! rstpatch "$d/w/w.rst" "$d/p/w.rst" evapv=0 "windcd=$dc" > "$d/patch.txt" 2>&1; then
    why="cannot set the evapv and windcd records of $d/w/w.rst: $(tail -1 "$d/patch.txt"); "
  else
    ln -s ../w/w.rst "$d/r/w.rst" || return 1
    run "$d/r" r 1 > "$d/r.why" & pr=$!
    run "$d/p" r 1 > "$d/p.why" & pp=$!
    for s in r p; do
      if [ "$s" = r ]; then wait "$pr"; k=$?; else wait "$pp"; k=$?; fi
      if [ "$k" = 0 ]; then
        w="$(readok "$d/$s/r.log")" || why="$why$s: $w; "
        lw="$lw$(e0log "$d/$s/r.log" "$s")"
      else
        why="$why$s: $(cat "$d/$s.why"); "
      fi
    done
  fi
  donecase "$cs" "$t0" "$why" || return 1
  sed 's/^/    /' "$d/patch.txt" > "$d.detail"
  # compared even when a log line is missing, so that a wrong apply shows
  # as a difference; the .ts.shy only if a run wrote one
  for f in hydro.shy ts.shy ext; do
    [ -e "$d/p/r.$f" ] || [ -e "$d/r/r.$f" ] || continue
    python3 -B "$HERE/shy_maxdiff.py" --first "$(firstof "$f")" "$d/p/r.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    [ -n "$s" ] || s="$(head -1 "$d/cmp.$f.txt")"
    echo "    $f (p against r): ${s#SUMMARY *: }" >> "$d.detail"
    case "$k" in 0) cmpl="${cmpl}$f equal, " ;; 1) cmpl="${cmpl}$f DIFFERS, " ;; *) cmpl="${cmpl}$f not compared, " ;; esac
  done
  line="case $cs: ibarcl = 0 read (no qflux3d) of a file with evapv and COARE's windcd, against the same file"
  line="$line with evapv = 0 and windcd = dragco $dc: ${cmpl%, }"
  if [ -n "$lw" ]; then line="$line; log: ${lw%; }"; rc=1; fi
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}

# offlog LOG NAME: the log checks of offline_ts_noheat and
# offline_ts_noheat_str; prints "NAME: reason; " for each one that fails
offlog() {
  local k
  k="$(grep -c 'T/S from the offline file (idtoff = *-2 *)' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'T/S from the offline file (idtoff = -2)' $k times in $1, not 1; "
  k="$(grep -c 'reading offline from file' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'reading offline from file' $k times in $1, not 1; "
  k="$(grep -c 'qflux3d: iheat' "$1")"
  [ "$k" = 0 ] || echo -n "$2: qflux3d started ('qflux3d: iheat' $k times in $1); "
  k="$(grep -c 'tws, dtw not applied (no heat flux)' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'tws, dtw not applied (no heat flux)' $k times in $1, not 1; "
  e0log "$1" "$2"
}
# case_offline CASE IDTOFF: a read whose T/S comes from an offline file
# (idtoff = IDTOFF: -2, or the time span string '-2s', which handle_offline
# decodes to -2) never runs qflux3d (barocl returns before it), so it
# keeps the cold evapv (0) and windcd (dragco), not the file's values
case_offline() {
  local cs="$1" idt="$2" d="$P/$1" s t0 why="" lw="" w f k rc=0 pf pw pr pp line="" cmpl="" dc=""
  t0=$(date +%s)
  mkdir "$d" "$d/c" || return 1
  for s in w r p f; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 "iheat = 6   itdrag = 4" && [ -n "$RTIME" ]; then
    # f: c with a record of the offline file every hour, to 14:00 (the
    # cubic interpolation of the read run needs records after 12:00)
    sed -e "s/^        c\$/        f/" -e "s/itend = '2009-01-01::12:00:00'/itend = '2009-01-01::14:00:00'/" \
        -e "s/^        iheat = 6   itdrag = 4\$/&\n        idtoff = 3600/" "$d/c/c.str" > "$d/f/f.str"
    sed -i -e "s/^        itrst = -1     ityrst = 1\$/&\n        idtoff = $idt/" \
           -e "s/^\\\$name\$/\$name\\n        offlin = 'f.off'/" "$d/r/r.str"
    dc="$(sed -n 's/.*dragco = \([^ ]*\).*/\1/p' "$d/r/r.str")"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c "^        f\$\|itend = '2009-01-01::14:00:00'\|^        idtoff = 3600\$" "$d/f/f.str")" != 3 ] \
     || [ "$(grep -c -e "^        idtoff = $idt\$" -e "^        offlin = 'f.off'\$" "$d/r/r.str")" != 2 ] \
     || [ "$(echo "$dc" | wc -w)" != 1 ] || ! cp "$d/r/r.str" "$d/p/r.str"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # f writes f.off and w the restart file (with the heat flux: evapv,
  # COARE's windcd); r reads w.rst, p the same file with evapv = 0 and
  # windcd = dragco, both with T/S from f.off (ievap = 1, iheat = 6,
  # itdrag = 4 as in w)
  run "$d/f" f 1 > "$d/f.why" & pf=$!
  run "$d/w" w 1 > "$d/w.why" & pw=$!
  wait "$pf" || why="$(cat "$d/f.why"); "
  wait "$pw" || why="$why$(cat "$d/w.why"); "
  if [ -n "$why" ]; then
    :
  elif [ ! -s "$d/f/f.off" ]; then
    why="f: no offline file $d/f/f.off; "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  elif ! rstpatch "$d/w/w.rst" "$d/p/w.rst" evapv=0 "windcd=$dc" > "$d/patch.txt" 2>&1; then
    why="cannot set the evapv and windcd records of $d/w/w.rst: $(tail -1 "$d/patch.txt"); "
  else
    ln -s ../w/w.rst "$d/r/w.rst" && ln -s ../f/f.off "$d/r/f.off" && ln -s ../f/f.off "$d/p/f.off" || return 1
    run "$d/r" r 1 > "$d/r.why" & pr=$!
    run "$d/p" r 1 > "$d/p.why" & pp=$!
    for s in r p; do
      if [ "$s" = r ]; then wait "$pr"; k=$?; else wait "$pp"; k=$?; fi
      if [ "$k" = 0 ]; then
        w="$(readok "$d/$s/r.log")" || why="$why$s: $w; "
        lw="$lw$(offlog "$d/$s/r.log" "$s")"
      else
        why="$why$s: $(cat "$d/$s.why"); "
      fi
    done
  fi
  donecase "$cs" "$t0" "$why" || return 1
  sed 's/^/    /' "$d/patch.txt" > "$d.detail"
  # compared even when a log line is missing, so that a wrong apply shows
  # as a difference; the .ts.shy files hold no data record (barocl, which
  # writes them, returns at once when T/S comes from the offline file), so
  # they are compared with cmp, and T and S with the .ext
  if cmp -s "$d/p/r.ts.shy" "$d/r/r.ts.shy"; then
    cmpl="ts.shy same bytes, "
  else
    cmpl="ts.shy DIFFERS, "; rc=1
  fi
  for f in hydro.shy ext; do
    python3 -B "$HERE/shy_maxdiff.py" --first "$(firstof "$f")" "$d/p/r.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    [ -n "$s" ] || s="$(head -1 "$d/cmp.$f.txt")"
    echo "    $f (p against r): ${s#SUMMARY *: }" >> "$d.detail"
    case "$k" in 0) cmpl="${cmpl}$f equal, " ;; 1) cmpl="${cmpl}$f DIFFERS, " ;; *) cmpl="${cmpl}$f not compared, " ;; esac
  done
  line="case $cs: idtoff = $idt read (T/S from an offline file, no qflux3d) of a file with evapv and COARE's windcd,"
  line="$line against the same file with evapv = 0 and windcd = dragco $dc: ${cmpl%, }"
  if [ -n "$lw" ]; then line="$line; log: ${lw%; }"; rc=1; fi
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}

# tsrst W R H PFX: the T and S records (ivar 12 and 11) of the .ext files
# W (the write run's, to the restart time) and R (the read run's), to H
# hours (copies PFX.w.ext and PFX.r.ext), compared from H (output in
# PFX.txt): R must have W's T and S records at H, equal, and none before
# (the comparator exits 0; zeta and the velocities are not compared, as
# hydro is not read, nor R's records after H, which W does not have);
# prints the comparator's exit code and summary, or why it could not
# compare, and fails unless it exits 0
tsrst() {
  local k w
  w="$(shyfix keep "$1" "$4.w.ext" "$3" 11 12 2>&1)" || { echo -n "$w"; return 1; }
  w="$(shyfix keep "$2" "$4.r.ext" "$3" 11 12 2>&1)" || { echo -n "$w"; return 1; }
  python3 -B "$HERE/shy_maxdiff.py" --first "$3" "$4.w.ext" "$4.r.ext" > "$4.txt" 2>&1
  k=$?
  w="$(grep '^SUMMARY' "$4.txt")"
  [ -n "$w" ] || w="$(head -1 "$4.txt")"
  echo -n "comparator exit $k: ${w#SUMMARY *: }"
  [ "$k" = 0 ]
}
# case_flgrst: a read without hydro skips the version 20 records and
# keeps the setweg clock
case_flgrst() {
  local cs=flgrst_no_hydro d="$P/flgrst_no_hydro" s t0 why="" k w v ts trs cn
  t0=$(date +%s)
  mkdir "$d" || return 1
  for s in c w r; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 "iheat = 6   itdrag = 4" && [ -n "$RTIME" ]; then
    sed -i 's/^        itrst = -1     ityrst = 1$/&\n        flgrst = 110/' "$d/r/r.str"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c '^        flgrst = 110$' "$d/r/r.str")" != 1 ]; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  trs=$(( (H1 - 1) * 3600 ))    # the restart time in seconds from the start
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  else
    ln -s ../w/w.rst "$d/r/w.rst" || return 1
    run "$d/r" r 1 > "$d/r.why" || why="$(cat "$d/r.why"); "
  fi
  donecase "$cs" "$t0" "$why" || return 1
  w="$(readok "$d/r/r.log")" || why="$why$w; "
  # the table of rst_perform_restart: id bwant bavail buse description
  k="$(awk '($1 == 1 && $2 == "F" && $5 == "hydrodynamics") || ($1 == 2 && $2 == "T" && $3 == "T" && $5 == "depth") ||
            ($1 == 3 && $2 == "T" && $3 == "T" && $5 == "T/S/rho") { n++ } END { print n + 0 }' "$d/r/r.log")"
  [ "$k" = 3 ] || why="${why}the restart table of $d/r/r.log does not show hydro not wanted, depth and T/S wanted; "
  k="$(grep -c 'iwetv, evapv, itdrag, windcd, heat flag, tws, dtw skipped (hydro not wanted)' "$d/r/r.log")"
  [ "$k" = 1 ] || why="${why}'... skipped (hydro not wanted)' $k times in $d/r/r.log, not 1; "
  k="$(grep -c 'setweg clock reset to' "$d/r/r.log")"
  [ "$k" = 0 ] || why="${why}'setweg clock reset to' $k times in $d/r/r.log; "
  v="$(awk '/setweg clock not reset/ { print $NF }' "$d/r/r.log")"
  if [ "$(echo "$v" | wc -w)" != 1 ]; then
    why="${why}'setweg clock not reset' $(echo "$v" | wc -w) times in $d/r/r.log, not 1; "
  elif awk -v v="$v" -v t="$trs" 'BEGIN { exit !(v + 0 == t + 0) }'; then
    why="${why}the setweg clock $v is the restart time; "
  fi
  # T and S at the restart time (FEXT, the first record of r.ext): the
  # comparator on the T and S records of w.ext and r.ext to that time must
  # exit 0; the canary: r.ext without its records at that time must fail
  ts="$(tsrst "$d/w/w.ext" "$d/r/r.ext" "$FEXT" "$d/ts")" \
    || why="${why}T and S of r.ext at the restart time are not w.ext's ($ts); "
  cn=FAILED
  if ! w="$(shydrop "$d/r/r.ext" "$d/drop.ext" "$FEXT" 2>&1)"; then
    why="${why}canary: cannot drop the records at ${FEXT}h of r.ext ($w); "
  elif w="$(tsrst "$d/w/w.ext" "$d/drop.ext" "$FEXT" "$d/tsdrop")"; then
    why="${why}canary: r.ext without its records at ${FEXT}h passed ($w); "
  else
    cn=rejected
  fi
  echo "    setweg clock not reset: ${v:-none}; T and S of r.ext against w.ext to ${FEXT}h: $ts;" \
       "canary (r.ext without its records at ${FEXT}h): $cn" > "$d.detail"
  if [ -n "$why" ]; then
    echo "case $cs: ${why%; } -> FAIL" > "$d.line"; return 1
  fi
  echo "case $cs: flgrst = 110 read ended, hydro not wanted, version 20 records skipped, setweg clock" \
       "not reset, T and S at the restart time are the write run's -> PASS" > "$d.line"
  return 0
}

# rstiwetv A B N: iwetv (the elements' wet/dry counter) of the first record
# of the version 20 restart file B minus that of A, N the steps of the run
# from A's record to B's: prints the largest difference, how many elements
# have it, and how many are dry (iwegv > 0) in A and in B; fails unless the
# largest difference is N
rstiwetv() {
  python3 -B - "$@" << 'EOF'
import struct, sys
def wetdry(path):
    data = open(path, 'rb').read()
    recs, pos = [], 0               # (offset of the data, length) of each record
    while pos < len(data):
        n = struct.unpack_from('<i', data, pos)[0]
        end = pos + 4 + n
        if n < 0 or end + 4 > len(data) or struct.unpack_from('<i', data, end)[0] != n:
            sys.exit(f"{path}: bad record at byte {pos}")
        recs.append((pos + 4, n))
        pos = end + 4
    def ints(i):
        return struct.unpack_from(f'<{recs[i][1] // 4}i', data, recs[i][0])
    if len(recs) < 10 or recs[0][1] != 12 or ints(0)[1] != 20:
        sys.exit(f"{path}: not a version 20 restart file")
    nkn, nel, nlv = ints(3)
    i = 4 + (3 if nlv > 1 else 0)   # hlv, ilhv, ilhkv; then iwegv znv zenv utlnv vtlnv iwetv
    if recs[i][1] != 4 * nel or recs[i + 5][1] != 4 * nel:
        sys.exit(f"{path}: iwegv or iwetv has not {nel} values")
    return ints(i), ints(i + 5)
(ga, wa), (gb, wb) = wetdry(sys.argv[1]), wetdry(sys.argv[2])
n = int(sys.argv[3])
d = [y - x for x, y in zip(wa, wb)]
mx = max(d)
print(f"iwetv grew by at most {mx} ({d.count(mx)} of {len(d)} elements) in a run of {n} steps; "
      f"dry elements: {sum(1 for v in ga if v > 0)} in the file read, {sum(1 for v in gb if v > 0)} at the end")
sys.exit(0 if mx == n else 1)
EOF
}
# case_clock CASE: setweg's clock at a restart, from mm_i0's write run
# (record at 06:00) read to 07:00 by a run that writes its own record
# there (idtrst = -1; idt = 300 s); the read must count each step once in
# setweg's iwetv, so iwetv must grow by the steps of the run:
#   clock_itrst_after_start  an explicit itrst = 06:00 one step after the
#     start (itanf = 05:55): the restart sets the clock to the start of
#     the run (dtanf, R5), the time of the first set_dry, not to the time
#     of the record read (with which set_dry would count one step more)
#   clock_itrst_last  itrst = -1 with the STR's itanf, 00:00: setweg(0)
#     sets the clock to 00:00 at the set-up, then the restart moves the
#     start to the record's time, 06:00 (dtanf), and must reset the clock
#     to it (dtime_setweg_old = dtanf; without it set_dry would count one
#     step more at 06:00), #330
# Both logs must also show the windcd line of the same itdrag, 0, in the
# file and the run, and not the old line that read like a mismatch (#330)
case_clock() {
  local cs="$1" d="$P/$1" s t0 why="" w k v ns ita itr clk
  if [ "$cs" = clock_itrst_after_start ]; then
    ita="2009-01-01::05:55:00"; itr="'2009-01-01::06:00:00'"; clk=21300     # starts at 05:55
  else
    ita="2009-01-01"; itr=-1; clk=21600     # starts at the record's time, 06:00
  fi
  ns=$(( (7 * 3600 - clk) / 300 ))     # the steps from the start of the run to 07:00
  t0=$(date +%s)
  mkdir "$d" "$d/c" || return 1
  for s in w r; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 && [ -n "$RTIME" ]; then
    sed -i -e "s/itanf = '2009-01-01'    itend = '2009-01-01::12:00:00'/itanf = '$ita'    itend = '2009-01-01::07:00:00'/" \
           -e "s/^        itrst = -1     ityrst = 1\$/        itrst = $itr     ityrst = 1\n        idtrst = -1/" "$d/r/r.str"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c -e "itanf = '$ita'    itend = '2009-01-01::07:00:00'" \
       -e "^        itrst = $itr     ityrst = 1\$" -e '^        idtrst = -1$' -e "^        idt = '300s'" \
       "$d/r/r.str")" != 4 ]; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # w writes the record at 06:00; r reads it (from 05:55, or from 06:00
  # with itrst = -1) and writes its own at 07:00
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  else
    ln -s ../w/w.rst "$d/r/w.rst" || return 1
    if ! run "$d/r" r 1 > "$d/r.why"; then
      why="$(cat "$d/r.why"); "
    elif [ ! -s "$d/r/r.rst" ]; then
      why="r: no restart file $d/r/r.rst; "
    fi
  fi
  donecase "$cs" "$t0" "$why" || return 1
  w="$(readok "$d/r/r.log")" || why="$why$w; "
  # " setweg clock reset to the start of the run: CLOCK (time of the record
  # read: TIME )": CLOCK is field 10, TIME field 16
  v="$(awk '/setweg clock reset to the start of the run:/ { print $10 }' "$d/r/r.log")"
  k="$(awk '/setweg clock reset to the start of the run:/ { print $16 }' "$d/r/r.log")"
  if [ "$(echo "$v" | wc -w)" != 1 ]; then
    why="${why}'setweg clock reset to the start of the run' $(echo "$v" | wc -w) times in $d/r/r.log, not 1; "
  elif ! awk -v v="$v" -v c="$clk" 'BEGIN { exit !(v + 0 == c + 0) }'; then
    why="${why}the setweg clock is $v, not $clk (the start of the run); "
  elif ! awk -v v="$k" 'BEGIN { exit !(v + 0 == 21600) }'; then
    why="${why}the time of the record read is $k, not 21600 (06:00); "
  fi
  w="windcd not applied (itdrag = 0 here and in the file; windcd is restored only with itdrag = 3 or 4)"
  k="$(grep -c -F -- "$w" "$d/r/r.log")"
  [ "$k" = 1 ] || why="${why}'$w' $k times in $d/r/r.log, not 1; "
  w="windcd not applied (file itdrag = 0, run itdrag = 0)"
  k="$(grep -c -F -- "$w" "$d/r/r.log")"
  [ "$k" = 0 ] || why="${why}the old line '$w' $k times in $d/r/r.log; "
  w="$(rstiwetv "$d/w/w.rst" "$d/r/r.rst" "$ns" 2>&1)" || why="${why}r.rst against w.rst: $w; "
  echo "    setweg clock: ${v:-none}; $w" > "$d.detail"
  if [ -n "$why" ]; then
    echo "case $cs: ${why%; } -> FAIL" > "$d.line"; return 1
  fi
  if [ "$cs" = clock_itrst_after_start ]; then
    echo "case $cs: itrst = 06:00 read from 05:55 counts each step once (the setweg clock is the start" \
         "of the run): iwetv of its record at 07:00 is the file's plus $ns steps -> PASS" > "$d.line"
  else
    echo "case $cs: itrst = -1 read (itanf 00:00 in the STR, the run starts at the record's time, 06:00)" \
         "counts each step once (the setweg clock is reset to 06:00): iwetv of its record at 07:00 is the" \
         "file's plus $ns steps -> PASS" > "$d.line"
  fi
  return 0
}

# case_idtoff: a read with an idtoff string that convert_time_d cannot
# parse (idtoff = 'xyz') stops every process with exit code 33 and the
# message, serially (r) and on 2 processes (p) (#330)
case_idtoff() {
  local cs=idtoff_unparsed d="$P/idtoff_unparsed" s t0 why="" bad="" det="" k n np pr pp
  local msg="error stop convert_time_d: cannot parse idtoff"
  t0=$(date +%s)
  mkdir "$d" "$d/c" || return 1
  for s in w r p; do rundir "$d/$s" mm || return 1; done
  RTIME=""
  if mkmm "$cs" 0 06 12 "iheat = 6   itdrag = 4" && [ -n "$RTIME" ]; then
    sed -i "s/^        itrst = -1     ityrst = 1\$/&\n        idtoff = 'xyz'/" "$d/r/r.str"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c "^        idtoff = 'xyz'\$" "$d/r/r.str")" != 1 ] || ! cp "$d/r/r.str" "$d/p/r.str"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # w writes the record (with the heat flux, so that the restart reader
  # decodes idtoff, offline_reads_ts); r and p read it with idtoff = 'xyz'
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  else
    ln -s ../w/w.rst "$d/r/w.rst" && ln -s ../w/w.rst "$d/p/w.rst" || return 1
    runx "$d/r" r 1 & pr=$!
    runx "$d/p" r 2 & pp=$!
    for s in r p; do
      if [ "$s" = r ]; then wait "$pr"; k=$?; np=1; else wait "$pp"; k=$?; np=2; fi
      n="$(grep -c -F -- "$msg" "$d/$s/r.log")"
      det="$det$s ($np process(es)): exit code $k, '$msg' $n times; "
      [ "$k" = 33 ] || bad="$bad$s: exit code $k, not 33; "
      if [ "$np" = 1 ]; then
        [ "$n" = 1 ] || bad="$bad$s: '$msg' $n times in $d/$s/r.log, not 1; "
      else
        # MPI_ABORT may stop the other process before it prints
        [ "$n" -ge 1 ] || bad="$bad$s: '$msg' not in $d/$s/r.log; "
        ranks_ok "$d/$s/r.log" "$np" \
          || bad="$bad$s: not $np MPI processes, $(grep -c 'shympi initialized:' "$d/$s/r.log") 'shympi initialized:' lines; "
      fi
      n="$(grep -c 'simulation end' "$d/$s/r.log")"
      [ "$n" = 0 ] || bad="$bad$s: 'simulation end' $n times in $d/$s/r.log; "
    done
  fi
  donecase "$cs" "$t0" "$why" || return 1
  echo "    ${det%; }" > "$d.detail"
  if [ -n "$bad" ]; then
    echo "case $cs: ${bad%; } -> FAIL" > "$d.line"; return 1
  fi
  echo "case $cs: idtoff = 'xyz' read stops with exit code 33 and '$msg', serially and on 2 processes -> PASS" \
    > "$d.line"
  return 0
}

# nonfinite FILE...: the number of values that are NaN or infinite in the
# data records of the .shy and .ext files (read as shy_maxdiff.py reads
# them, which counts NaN in both files as equal); prints a message
# instead of a number if a file cannot be read
nonfinite() {
  python3 -B - "$HERE" "$@" << 'EOF'
import sys
import numpy as np
sys.path.insert(0, sys.argv[1])
import shy_maxdiff
n = 0
for p in sys.argv[2:]:
    try:
        _, _, _, recs = shy_maxdiff.load(p)
    except Exception as e:      # OSError, FormatError, struct.error
        sys.exit(f"cannot read {p}: {e}")
    for v in recs.values():
        n += int(np.count_nonzero(~np.isfinite(np.frombuffer(v, '<f4'))))
print(n)
EOF
}
# k2glog LOG NAME WANT: the log checks of keps_to_gotm (WANT: T or F, id 8
# wanted in the restart table); prints "NAME: reason; " for each one that
# fails
k2glog() {
  local w k
  w="$(readok "$1")" || echo -n "$2: $w; "
  k="$(grep -c 'k-epsilon state not applied' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'k-epsilon state not applied' $k times in $1, not 1; "
  k="$(grep -c 'handle_gotm_init: GOTM arrays initialised' "$1")"
  [ "$k" = 1 ] || echo -n "$2: 'handle_gotm_init: GOTM arrays initialised' $k times in $1, not 1; "
  # the table of rst_perform_restart: id bwant bavail buse description
  k="$(awk -v w="$3" '$1 == 8 && $2 == w && $3 == "T" && $5 == "gotm" { n++ } END { print n + 0 }' "$1")"
  [ "$k" = 1 ] || echo -n "$2: the restart table of $1 does not show id 8 available with wanted = $3; "
}
# case_keps_to_gotm: a k-epsilon file read by a GOTM run starts GOTM from
# its own initial state
case_keps_to_gotm() {
  local cs=keps_to_gotm d="$P/keps_to_gotm" s t0 why="" lw="" w f k rc=0 pr po cmpl="" nf line
  t0=$(date +%s)
  mkdir "$d" "$d/c" || return 1
  for s in w r o; do rundir "$d/$s" ven || return 1; done
  RTIME=""
  if mkven "$cs" 2 && [ -n "$RTIME" ]; then
    sed -i 's/^        iturb  = 2$/        iturb  = 1/' "$d/r/r.str"
    sed -e 's/^        itrst = -1     ityrst = 1$/&\n        flgrst = 1111111/' "$d/r/r.str" > "$d/o/r.str"
  fi
  if [ -z "$RTIME" ] || [ "$(grep -c '^        iturb  = 1$' "$d/r/r.str")" != 1 ] \
     || [ "$(grep -c '^        iturb  = 1$\|^        flgrst = 1111111$' "$d/o/r.str")" != 2 ]; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*/*.str) -> FAIL" > "$d.line"; return 1
  fi
  # w writes with k-epsilon; r and o read w.rst with GOTM, o without id 8
  if ! run "$d/w" w 1 > "$d/w.why"; then
    why="$(cat "$d/w.why"); "
  elif [ ! -s "$d/w/w.rst" ]; then
    why="w: no restart file $d/w/w.rst; "
  else
    ln -s ../w/w.rst "$d/r/w.rst" && ln -s ../w/w.rst "$d/o/w.rst" || return 1
    run "$d/r" r 1 > "$d/r.why" & pr=$!
    run "$d/o" r 1 > "$d/o.why" & po=$!
    if wait "$pr"; then lw="$lw$(k2glog "$d/r/r.log" r T)"; else why="${why}r: $(cat "$d/r.why"); "; fi
    if wait "$po"; then lw="$lw$(k2glog "$d/o/r.log" o F)"; else why="${why}o: $(cat "$d/o.why"); "; fi
  fi
  donecase "$cs" "$t0" "$why" || return 1
  : > "$d.detail"
  # compared even when a log line is missing, so that GOTM started from
  # other arrays shows as a difference
  for f in hydro.shy ts.shy ext; do
    python3 -B "$HERE/shy_maxdiff.py" --first "$(firstof "$f")" "$d/o/r.$f" "$d/r/r.$f" > "$d/cmp.$f.txt" 2>&1
    k=$?
    [ "$k" = 0 ] || rc=1
    s="$(grep '^SUMMARY' "$d/cmp.$f.txt")"
    [ -n "$s" ] || s="$(head -1 "$d/cmp.$f.txt")"
    echo "    $f (o against r): ${s#SUMMARY *: }" >> "$d.detail"
    case "$k" in 0) cmpl="${cmpl}$f equal, " ;; 1) cmpl="${cmpl}$f DIFFERS, " ;; *) cmpl="${cmpl}$f not compared, " ;; esac
  done
  nf="$(nonfinite "$d/r/r.hydro.shy" "$d/r/r.ts.shy" "$d/r/r.ext" 2>&1)"
  case "$nf" in
    0) ;;
    ''|*[!0-9]*) lw="${lw}r: NaN/infinity not counted (${nf:-no output}); " ;;
    *) lw="${lw}r: $nf values are NaN or infinite; " ;;
  esac
  line="case $cs: iturb = 1 read of a k-epsilon file, against the same read without id 8 (flgrst = 1111111):"
  line="$line ${cmpl%, }; NaN/infinity in r: ${nf:-?}"
  if [ -n "$lw" ]; then line="$line; log: ${lw%; }"; rc=1; fi
  if [ "$rc" = 0 ]; then echo "$line -> PASS" > "$d.line"; else echo "$line -> FAIL" > "$d.line"; fi
  return "$rc"
}

#--- the case tools (rstinf, rst2shy)
# tooldo DIR OUT TOOL ARG...: runs TOOL ARG... in DIR (timeout 300 s),
# its output to DIR/OUT; the tools' exit status is not used here (rstinf's
# diff mode exits 0 also when it finds differences; errors exit non-zero,
# #327), the output is checked
tooldo() {
  local dd="$1" out="$2"
  shift 2
  ( cd "$dd" && exec timeout 300 nice -n 10 "$@" < /dev/null > "$out" 2>&1 )
  return 0
}
# nocommit FILE: FILE without the commit line of the banner
nocommit() {
  grep -v '^ *commit *: ' "$1"
}
# tcount FILE PATTERN WANT LABEL: prints "LABEL: ...; " unless PATTERN
# (grep, basic) matches WANT lines of FILE
tcount() {
  local k
  k="$(grep -c -- "$2" "$1")"
  [ "$k" = "$3" ] || echo -n "$4: '$2' $k times in $1, not $3; "
}
# tinfo FILE NVERS NREC LABEL: rstinf's listing FILE shows version NVERS
# (in its two header lines) and NREC records
tinfo() {
  local v
  v="$(awk '/^version nrec/ { getline; printf "%s ", $1 }' "$1")"
  [ "$v" = "$2 $2 " ] || echo -n "$4: version '${v% }' in $1, not $2 twice; "
  tcount "$1" "Number of records read: *$3\$" 1 "$4"
}
# t2shy DIR BIN BAS: rst2shy of BIN (this build's on PATH or REF_BIN_DIR's)
# on DIR/w.rst (as x.rst) in a new folder DIR/t (this build) or DIR/tm
# (REF_BIN_DIR)
t2shy() {
  local dd="$1/t"
  [ "$2" = rst2shy ] || dd="$1/tm"
  mkdir "$dd" && ln -s ../w.rst "$dd/x.rst" || return 1
  tooldo "$dd" rst2shy.txt "$2" x.rst "../GRID/$3"
}
# tshy DIR1 DIR2 LABEL: the .shy files rst2shy wrote in DIR1 and DIR2 are
# the same files with the same bytes (x.hydro.shy and x.ts.shy at least)
tshy() {
  local f n=0
  for f in hydro ts; do
    [ -s "$1/x.$f.shy" ] || echo -n "$3: no x.$f.shy in $1; "
  done
  [ "$(cd "$1" && ls x.*.shy 2> /dev/null)" = "$(cd "$2" && ls x.*.shy 2> /dev/null)" ] \
    || echo -n "$3: rst2shy wrote other files in $1 than in $2; "
  for f in "$1"/x.*.shy; do
    [ -e "$f" ] || continue
    cmp -s "$f" "$2/${f##*/}" || echo -n "$3: ${f##*/} differs (cmp $f $2/${f##*/}); "
    n=$(( n + 1 ))
  done
  echo "$n" > "$1/nshy.txt"
}
# shyat MODEL CONV H...: rst2shy's file CONV holds every record that the
# model's file MODEL holds at the times H (hours from MODEL's start date:
# the times of the restart records rst2shy converted), and no record at
# another time (#323: a converted record that is missing fails); and every
# record of CONV whose variable MODEL also holds is MODEL's record at the
# same absolute time, byte for byte (the variables MODEL does not hold
# may only be rho, 13, which the model does not write); prints "N records
# equal" or the reasons, exit 1 on a difference
shyat() {
  python3 -B - "$HERE" "$@" << 'PY'
import datetime, sys
sys.path.insert(0, sys.argv[1])
import shy_maxdiff
def start(st):
    d, t = st
    return datetime.datetime(d // 10000, d // 100 % 100, d % 100, t // 10000, t // 100 % 100, t % 100)
try:
    _, sa, _, ka = shy_maxdiff.load(sys.argv[2])
    _, sb, _, kb = shy_maxdiff.load(sys.argv[3])
    hs = [float(h) for h in sys.argv[4:]]
except Exception as e:      # OSError, FormatError, struct.error, ValueError
    print(f"cannot read: {e}")
    sys.exit(1)
off = (start(sb) - start(sa)).total_seconds()
va = {k[1] for k in ka}
neq, bad, other = 0, [], set()
if not hs:
    bad.append("no restart record time given")
for h in hs:                    # the model's records at each restart record's time
    km = [k for k in ka if abs(k[0] - 3600. * h) < 0.5]
    if not km:
        bad.append(f"the model's file has no record at {h:g}h")
    for (t, ivar, size, j) in km:
        if (t - off, ivar, size, j) not in kb:
            bad.append(f"no converted record #{j} of variable {ivar} at {h:g}h")
for (t, ivar, size, j), v in kb.items():
    if not any(abs(t + off - 3600. * h) < 0.5 for h in hs):
        bad.append(f"a converted record of variable {ivar} at {(t + off) / 3600.:g}h, not a restart record's time")
    if ivar not in va:
        other.add(ivar)
        continue
    w = ka.get((t + off, ivar, size, j))
    if w is None:
        bad.append(f"no record of variable {ivar} at {t + off:g} s in the model's file")
    elif w != v:
        bad.append(f"variable {ivar} at {t + off:g} s differs")
    else:
        neq += 1
if other - {13}:
    bad.append(f"variables {sorted(other - {13})} not in the model's file")
if neq == 0:
    bad.append("no record compared")
if bad:
    print("; ".join(bad[:3]))
    sys.exit(1)
print(f"{neq} records equal, none missing at " + ", ".join(f"{h:g}h" for h in hs)
      + (" (rho not in the model's file)" if other else ""))
PY
}
# tcheck STR: the hours of the restart records of the write run STR of
# tools (from its start at 0 h: every idtrst, whole hours, to its end)
tcheck() {
  local st te h out=""
  st="$(sed -n "s/^        idtrst = '\([0-9]*\)h'\$/\1/p" "$1")"
  te="$(sed -n "s/^.*[[:space:]]itend[[:space:]]*=[[:space:]]*'[^:']*::\([0-9][0-9]\):.*\$/\1/p" "$1")"
  [ "$(echo "$st" | wc -w)" = 1 ] && [ "$(echo "$te" | wc -w)" = 1 ] && [ "$st" -gt 0 ] || return 1
  for (( h = st; h <= 10#$te; h += st )); do out="$out $h"; done
  echo $out
}
# tstr D: the STR files of the write runs of tools and tools_v19 in D
# (D/m.str: mm_h6d4's write run with a record every 3 h; D/k.str and
# D/g.str: ven_keps_s's and ven_s's with a record every hour); mkmm and
# mkven make them in D/{m,k,g}/{c,w,r}
tstr() {
  local d="$1" s rel="${1#$P/}"
  for s in m k g; do mkdir "$d/$s" "$d/$s/c" "$d/$s/w" "$d/$s/r" || return 1; done
  RTIME=""
  mkmm "$rel/m" 0 06 12 "iheat = 6   itdrag = 4" && mkven "$rel/k" 2 && mkven "$rel/g" 1 && [ -n "$RTIME" ] || return 1
  sed -e "s/^        idtrst = -1\$/        idtrst = '3h'/" "$d/m/w/w.str" > "$d/m.str"
  sed -e "s/^        idtrst = -1\$/        idtrst = '1h'/" "$d/k/w/w.str" > "$d/k.str"
  sed -e "s/^        idtrst = -1\$/        idtrst = '1h'/" "$d/g/w/w.str" > "$d/g.str"
  [ "$(grep -c "^        idtrst = '3h'\$" "$d/m.str")" = 1 ] || return 1
  [ "$(cat "$d/k.str" "$d/g.str" | grep -c "^        idtrst = '1h'\$")" = 2 ] || return 1
}
# twrite D BIN X...: the write runs D/X (X = m.., k.. or g..: the STR file
# D/${X%??}.str) with BIN, at the same time; prints why one failed
twrite() {
  local d="$1" bin="$2" x i=0
  local -a pl=()
  shift 2
  for x in "$@"; do
    case "$x" in m*) rundir "$d/$x" mm ;; *) rundir "$d/$x" ven ;; esac || { echo "$x: no run folder; "; return 1; }
    cp "$d/${x%??}.str" "$d/$x/w.str" || return 1
    run "$d/$x" w 1 "$bin" > "$d/$x.why" & pl+=($!)
  done
  for x in "$@"; do
    if ! wait "${pl[$i]}"; then
      echo -n "$x: $(cat "$d/$x.why"); "
    elif [ ! -s "$d/$x/w.rst" ]; then
      echo -n "$x: no restart file $d/$x/w.rst; "
    fi
    i=$(( i + 1 ))
  done
}
# case_tools: rstinf and rst2shy on version 20 files (this build alone)
case_tools() {
  local cs=tools d="$P/tools" s x t0 why="" bad="" k bas nrec pargs nm np itd w cps
  t0=$(date +%s)
  mkdir "$d" || return 1
  if ! tstr "$d"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*.str) -> FAIL" > "$d.line"; return 1
  fi
  why="$(twrite "$d" shyfem m20 k20 g20)"
  donecase "$cs" "$t0" "$why" || return 1
  : > "$d.detail"
  # x NREC (records), writer's iturb, writer's itdrag, the records changed
  # in the first record of the patched copy
  for x in m k g; do
    case "$x" in
      m) nrec=2; bas=MM_coarse_smooth.bas; k=0; itd=4; pargs="evapv=99 windcd=99 tws=99 dtw=99" ;;
      k) nrec=3; bas=venlag62.bas;         k=2; itd=0; pargs="evapv=99 tken=99 difv=99" ;;
      g) nrec=3; bas=venlag62.bas;         k=1; itd=0; pargs="tws=99" ;;
    esac
    s="$d/${x}20"
    tooldo "$s" info.txt rstinf w.rst
    bad="$bad$(tinfo "$s/info.txt" 20 "$nrec" "${x}20 rstinf")"
    bad="$bad$(tcount "$s/info.txt" '^   hydro block, after vtlnv: iwetv, evapv, itdrag, windcd, heat flag, tws, dtw$' 1 "${x}20 rstinf")"
    bad="$bad$(tcount "$s/info.txt" "^   itdrag of the writer: $itd " 1 "${x}20 rstinf")"
    bad="$bad$(tcount "$s/info.txt" '^   heat flag: 1 ' 1 "${x}20 rstinf")"
    if [ "$k" = 2 ]; then
      bad="$bad$(tcount "$s/info.txt" '^   turbulence block, after iturb = 2: tken, eps, visv, difv (k-epsilon)$' 1 "${x}20 rstinf")"
    else
      bad="$bad$(tcount "$s/info.txt" "^   turbulence block, after iturb = $k: no k-epsilon state\$" 1 "${x}20 rstinf")"
    fi
    cp "$s/w.rst" "$s/w2.rst" || return 1
    tooldo "$s" same.txt rstinf w.rst w2.rst
    bad="$bad$(tcount "$s/same.txt" 'Differences found: *0$' 1 "${x}20 rstinf diff")"
    bad="$bad$(tcount "$s/same.txt" "Number of records read: *$nrec\$" 1 "${x}20 rstinf diff")"
    bad="$bad$(tcount "$s/same.txt" 'records are different' 0 "${x}20 rstinf diff")"
    if rstpatch "$s/w.rst" "$s/wp.rst" $pargs > "$s/patch.txt" 2>&1; then
      tooldo "$s" patched.txt rstinf w.rst wp.rst
      np=0
      for nm in $pargs; do
        nm="${nm%=*}"
        bad="$bad$(tcount "$s/patched.txt" "records are different: $nm  *[0-9]" 1 "${x}20 rstinf diff patched")"
        np=$(( np + 1 ))
      done
      bad="$bad$(tcount "$s/patched.txt" 'records are different' "$np" "${x}20 rstinf diff patched")"
      bad="$bad$(tcount "$s/patched.txt" "Differences found: *$np\$" 1 "${x}20 rstinf diff patched")"
      bad="$bad$(tcount "$s/patched.txt" "Number of records read: *$nrec\$" 1 "${x}20 rstinf diff patched")"
    else
      bad="$bad${x}20: cannot change $pargs of $s/w.rst: $(tail -1 "$s/patch.txt"); "
    fi
    # rst2shy: every record, each the model's own output record at its time,
    # and none missing at the times of the restart records (cps, from the
    # STR); the canary: a copy without the last time's records must fail
    t2shy "$s" rst2shy "$bas" || return 1
    bad="$bad$(tcount "$s/t/rst2shy.txt" "Number of records read: *$nrec\$" 1 "${x}20 rst2shy")"
    cps="$(tcheck "$d/$x.str")"
    [ "$(echo "$cps" | wc -w)" = "$nrec" ] || bad="$bad${x}20: restart record times '$cps' from $d/$x.str, not $nrec; "
    for nm in hydro ts; do
      if w="$(shyat "$s/w.$nm.shy" "$s/t/x.$nm.shy" $cps 2>&1)"; then
        echo "    ${x}20 rst2shy x.$nm.shy against the write run's w.$nm.shy: $w" >> "$d.detail"
      else
        bad="$bad${x}20 rst2shy: x.$nm.shy against the write run's w.$nm.shy: $w; "
      fi
      # (rst2shy's file starts at its first record: its last time is the
      # last restart record's, ${cps##* } h from the model's start)
      if ! w="$(shydrop "$s/t/x.$nm.shy" "$s/t/drop.$nm.shy" last 2>&1)"; then
        bad="$bad${x}20 canary: cannot drop the records of the last time of x.$nm.shy ($w); "
      elif w="$(shyat "$s/w.$nm.shy" "$s/t/drop.$nm.shy" $cps 2>&1)" \
           || [ "$(echo "$w" | grep -c "no converted record #0 of variable [0-9]* at ${cps##* }h")" = 0 ]; then
        bad="$bad${x}20 canary: x.$nm.shy without its records at ${cps##* }h not rejected ($w); "
      fi
    done
    echo "    $x: version 20 file of $nrec records; rstinf diff of the patched copy: $(grep -c 'records are different' \
      "$s/patched.txt" 2> /dev/null) records differ" >> "$d.detail"
  done
  if [ -n "$bad" ]; then
    echo "case $cs: ${bad%; } -> FAIL" > "$d.line"; return 1
  fi
  echo "case $cs: rstinf (list, diff, diff of a patched copy) and rst2shy read the version 20 files (mm COARE," \
       "venlag k-epsilon, venlag GOTM); rst2shy's records are the write run's own output records, none missing" \
       "(canary rejected) -> PASS" > "$d.line"
  return 0
}
# case_tools_v19: rstinf and rst2shy on version 19 files, as REF_BIN_DIR's
# (a merge-time check: skipped without REF_BIN_DIR)
case_tools_v19() {
  local cs=tools_v19 d="$P/tools_v19" ref="${REF_BIN_DIR:-}" s x t0 why="" bad="" bas nrec
  t0=$(date +%s)
  if [ -z "$ref" ]; then
    echo "case $cs: skipped (needs REF_BIN_DIR: a build of the last main commit before version 20) -> SKIPPED" > "$d.line"
    return 0
  fi
  if [ ! -x "$ref/shyfem" ] || [ ! -x "$ref/rstinf" ] || [ ! -x "$ref/rst2shy" ]; then
    echo "case $cs: did not run (REF_BIN_DIR='$ref' has no shyfem, rstinf and rst2shy) -> FAIL" > "$d.line"
    return 1
  fi
  mkdir "$d" || return 1
  if ! tstr "$d"; then
    echo "case $cs: did not run (cannot make its STR files, see $d/*.str) -> FAIL" > "$d.line"; return 1
  fi
  why="$(twrite "$d" "$ref/shyfem" m19 k19 g19)"
  donecase "$cs" "$t0" "$why" || return 1
  : > "$d.detail"
  for x in m k g; do
    case "$x" in
      m) nrec=2; bas=MM_coarse_smooth.bas ;;
      *) nrec=3; bas=venlag62.bas ;;
    esac
    s="$d/${x}19"
    tooldo "$s" info.txt rstinf w.rst
    tooldo "$s" info_m.txt "$ref/rstinf" w.rst
    bad="$bad$(tinfo "$s/info_m.txt" 19 "$nrec" "${x}19 rstinf of REF_BIN_DIR")"
    [ "$(nocommit "$s/info.txt")" = "$(nocommit "$s/info_m.txt")" ] \
      || bad="$bad${x}19: rstinf prints other lines than REF_BIN_DIR's (diff $s/info.txt $s/info_m.txt); "
    cp "$s/w.rst" "$s/w2.rst" || return 1
    tooldo "$s" same.txt rstinf w.rst w2.rst
    tooldo "$s" same_m.txt "$ref/rstinf" w.rst w2.rst
    bad="$bad$(tcount "$s/same_m.txt" 'Differences found: *0$' 1 "${x}19 rstinf diff of REF_BIN_DIR")"
    bad="$bad$(tcount "$s/same_m.txt" "Number of records read: *$nrec\$" 1 "${x}19 rstinf diff of REF_BIN_DIR")"
    [ "$(nocommit "$s/same.txt")" = "$(nocommit "$s/same_m.txt")" ] \
      || bad="$bad${x}19: rstinf diff prints other lines than REF_BIN_DIR's (diff $s/same.txt $s/same_m.txt); "
    t2shy "$s" rst2shy "$bas" && t2shy "$s" "$ref/rst2shy" "$bas" || return 1
    bad="$bad$(tcount "$s/tm/rst2shy.txt" "Number of records read: *$nrec\$" 1 "${x}19 rst2shy of REF_BIN_DIR")"
    [ "$(nocommit "$s/t/rst2shy.txt")" = "$(nocommit "$s/tm/rst2shy.txt")" ] \
      || bad="$bad${x}19: rst2shy prints other lines than REF_BIN_DIR's (diff $s/t/rst2shy.txt $s/tm/rst2shy.txt); "
    bad="$bad$(tshy "$s/t" "$s/tm" "${x}19 rst2shy")"
    echo "    $x: version 19 file of $nrec records; rst2shy: $(cat "$s/t/nshy.txt" 2> /dev/null) .shy files" >> "$d.detail"
  done
  if [ -n "$bad" ]; then
    echo "case $cs: ${bad%; } -> FAIL" > "$d.line"; return 1
  fi
  echo "case $cs: rstinf (list, diff) and rst2shy work on the version 19 files (mm COARE, venlag k-epsilon," \
       "venlag GOTM) as REF_BIN_DIR's -> PASS" > "$d.line"
  return 0
}

for cs in $CASES; do
  case "$cs" in
    old_v19)         case_old_v19 ;;
    drag0_reads_cd4) case_drag drag0_reads_cd4 4 0 "" 1 ;;
    drag4_reads_cd0) case_drag drag4_reads_cd0 0 4 2.0e-3 1 ;;
    drag4_noheat_reads_cd4) case_drag drag4_noheat_reads_cd4 4 4 2.0e-3 0 ;;
    flgrst_no_hydro) case_flgrst ;;
    evap_reads_noheat) case_evap ;;
    keps_to_gotm)    case_keps_to_gotm ;;
    offline_ts_noheat) case_offline offline_ts_noheat -2 ;;
    offline_ts_noheat_str) case_offline offline_ts_noheat_str "'-2s'" ;;
    clock_itrst_*)   case_clock "$cs" ;;
    idtoff_unparsed) case_idtoff ;;
    tools)           case_tools ;;
    tools_v19)       case_tools_v19 ;;
    *)               onecase "$cs" ;;
  esac & PIDS="$PIDS $!"
done
wait
PIDS=""

rc=0; nskip=0
for cs in $CASES; do
  if [ -s "$P/$cs.line" ]; then cat "$P/$cs.line"; else echo "case $cs: did not run (no result) -> FAIL"; fi
  [ -s "$P/$cs.detail" ] && cat "$P/$cs.detail"
  if grep -q -- '-> SKIPPED$' "$P/$cs.line" 2> /dev/null; then
    nskip=$(( nskip + 1 ))
  elif ! grep -q -- '-> PASS$' "$P/$cs.line" 2> /dev/null; then
    rc=1
  fi
done
tm=""
for cs in $CASES; do [ -s "$P/$cs.time" ] && tm="$tm$(cat "$P/$cs.time"), "; done
echo "time: ${tm}total $(( $(date +%s) - T0 )) s"
if [ "$rc" = 0 ]; then
  if [ "$nskip" = 0 ]; then
    echo "RESTART FIDELITY: PASS"
  else
    echo "RESTART FIDELITY: PASS ($nskip cases skipped: they need REF_BIN_DIR)"
  fi
  rm -rf "$P"
else
  echo "  files kept in $P"
  echo "RESTART FIDELITY: FAIL"
fi
exit "$rc"
