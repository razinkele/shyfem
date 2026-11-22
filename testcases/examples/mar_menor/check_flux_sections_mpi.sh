#!/bin/bash
#------------------------------------------------------------------------
# Flux sections on several processes: the flux file of a run on NP
# processes must be byte-identical to the serial one (#238).
#
# Usage:  ./check_flux_sections_mpi.sh [NP ...]     (default: 2 4 8)
#
# What it checks: a flux section sums, at each of its nodes, transports
# taken around the ring of elements of that node (flx3d, flux_with_bounds
# and mkweig in discharge_flux.f90); the result depends on the element the
# ring starts at.  On several processes the ring of an interior node used
# to start at its element of smallest local number, which near the border
# of a domain is not the one a serial run starts at (set_geom_rings_mpi in
# lnkmpi.f90 now starts every closed ring at the smallest global element).
# The sections below are the 129 nodes whose ring that routine turns on 2,
# 4 or 8 processes of case B (GRID/MM_coarse, the METIS partition of the
# development machine), each paired with the neighbour its ring now starts
# at (two adjacent nodes, one section each).  Before the fix the flux files
# differ (ca7ce42c: 240, 632 and 1,524 bytes on 2, 4 and 8 processes,
# section fluxes one single-precision step apart); after it they are
# byte-identical.
#
# How: a scratch copy of mm_lgr_b.str in this folder, run name
# mm_flxsec_PID (outputs carry that name), without its $lagrg section, with
# idtflx = 300 (one flux record per time step) and the sections, run
# serially and on each NP, each under "timeout 600" (a run that times out
# fails).  Each run must exit with 0 and log "simulation end"; a run on NP
# processes must also show its NP ranks: the line "shympi initialized: ID
# NP" once from each rank 0 to NP-1, as in check_lgr_mpi.sh (an mpirun of
# another MPI, or a launcher that starts shyfem once, runs serial copies
# that write the serial flux file and would pass the comparison).  The
# serial log must report the 129 sections ("nsect,kfluxm" line of prflxa)
# and the serial flux file must hold 576 data records (two days at 300 s;
# a data record is a record as long as the last one), so that a run that
# wrote a header and no time series cannot pass; each NP flux file must
# hold as many records as the serial one, and is then compared with cmp.
# The scratch STR and the outputs are removed at the end; the logs too
# when everything passed (otherwise their names are printed).
#
# Limit: the node list is tied to that partition.  On a partition where
# none of these nodes lies next to a domain border the check passes
# without exercising a turned ring (it cannot fail there); the section
# flux of a node off the border is the same before and after the fix.
#
# Needs shyfem, mpirun (an OpenMPI build), timeout and python3 on PATH and
# `make init`.  test_lgr_drivers.sh runs this driver with fake programs
# (exit codes, time-outs, missing ranks, short flux files).
# Exit code 0 (FLUX SECTIONS: PASS) or 1 (FLUX SECTIONS: FAIL).
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
rc=0
fail() { echo "FLUX SECTIONS FAIL: $*"; rc=1; }

NPS="$*"
[ -n "$NPS" ] || NPS="2 4 8"
for np in $NPS; do
  case "$np" in ''|*[!0-9]*) echo "NP must be a number: '$np'"; exit 2 ;; esac
  [ "$np" -ge 2 ] || { echo "NP must be at least 2: '$np'"; exit 2; }
done

command -v shyfem > /dev/null 2>&1 || { echo "FLUX SECTIONS FAIL: shyfem is not on PATH"; exit 1; }
command -v mpirun > /dev/null 2>&1 || { echo "FLUX SECTIONS FAIL: mpirun is not on PATH"; exit 1; }
command -v timeout > /dev/null 2>&1 || { echo "FLUX SECTIONS FAIL: timeout is not on PATH"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "FLUX SECTIONS FAIL: python3 is not on PATH"; exit 1; }
[ -f GRID/MM_coarse.bas ] || { echo "FLUX SECTIONS FAIL: GRID/MM_coarse.bas is missing: run 'make init'"; exit 1; }

RUN="mm_flxsec_$$"
NSECT=129
NDATA=576		# data records: (itend - itanf) / idtflx = 172800 / 300
cleanup() {
  local f
  for f in "$HERE/$RUN".*; do
    case "$f" in *.log) ;; *) [ -e "$f" ] && rm -f "$f" ;; esac
  done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

#--- scratch STR -----------------------------------------------------------
[ "$(grep -c '^[[:space:]]*mm_lgr_b[[:space:]]*$' mm_lgr_b.str)" = 1 ] || { echo "FLUX SECTIONS FAIL: cannot find the run name line of mm_lgr_b.str"; exit 1; }
grep -q '^\$para[[:space:]]*$' mm_lgr_b.str || { echo "FLUX SECTIONS FAIL: mm_lgr_b.str has no line with only \$para"; exit 1; }
awk -v run="$RUN" '
  /^\$lagrg/ { skip = 1 }
  skip { if ($0 ~ /^\$end/) skip = 0; next }
  /^[ \t]*mm_lgr_b[ \t]*$/ { print "        " run; next }
  { print }
  !done && /^\$para[ \t\r]*$/ { print "        idtflx = 300"; done = 1 }
' mm_lgr_b.str > "$RUN.str" || { echo "FLUX SECTIONS FAIL: cannot write $RUN.str"; exit 1; }
cat >> "$RUN.str" <<'EOF'

$flux
        295 1157 'r295'
        300 1213 'r300'
        304 388 'r304'
        316 580 'r316'
        351 923 'r351'
        378 772 'r378'
        388 49 'r388'
        406 1010 'r406'
        408 420 'r408'
        420 421 'r420'
        421 408 'r421'
        442 249 'r442'
        450 489 'r450'
        480 49 'r480'
        481 778 'r481'
        489 800 'r489'
        514 1104 'r514'
        515 846 'r515'
        534 579 'r534'
        539 1005 'r539'
        559 236 'r559'
        562 16 'r562'
        572 767 'r572'
        573 876 'r573'
        579 917 'r579'
        580 579 'r580'
        602 1167 'r602'
        603 1167 'r603'
        609 943 'r609'
        610 611 'r610'
        611 1114 'r611'
        629 1295 'r629'
        637 863 'r637'
        644 655 'r644'
        655 656 'r655'
        656 644 'r656'
        659 1215 'r659'
        691 1332 'r691'
        695 696 'r695'
        696 411 'r696'
        704 411 'r704'
        722 753 'r722'
        734 367 'r734'
        740 959 'r740'
        767 511 'r767'
        771 1010 'r771'
        772 419 'r772'
        778 779 'r778'
        779 481 'r779'
        800 450 'r800'
        846 1182 'r846'
        859 107 'r859'
        863 372 'r863'
        876 1204 'r876'
        883 884 'r883'
        884 239 'r884'
        902 411 'r902'
        905 236 'r905'
        906 976 'r906'
        908 602 'r908'
        917 580 'r917'
        923 602 'r923'
        936 1156 'r936'
        943 119 'r943'
        948 1203 'r948'
        950 1157 'r950'
        952 1085 'r952'
        976 624 'r976'
        980 1249 'r980'
        981 629 'r981'
        982 618 'r982'
        1005 1276 'r1005'
        1010 1212 'r1010'
        1011 1015 'r1011'
        1015 978 'r1015'
        1020 1393 'r1020'
        1027 300 'r1027'
        1034 1314 'r1034'
        1058 1174 'r1058'
        1062 722 'r1062'
        1081 514 'r1081'
        1085 612 'r1085'
        1087 1106 'r1087'
        1104 1081 'r1104'
        1114 610 'r1114'
        1115 275 'r1115'
        1136 789 'r1136'
        1140 351 'r1140'
        1157 619 'r1157'
        1167 908 'r1167'
        1182 336 'r1182'
        1183 1106 'r1183'
        1185 980 'r1185'
        1200 1338 'r1200'
        1202 1020 'r1202'
        1203 933 'r1203'
        1204 573 'r1204'
        1210 1388 'r1210'
        1211 1293 'r1211'
        1212 406 'r1212'
        1213 1027 'r1213'
        1215 410 'r1215'
        1216 1267 'r1216'
        1222 1052 'r1222'
        1234 336 'r1234'
        1240 292 'r1240'
        1244 481 'r1244'
        1267 1295 'r1267'
        1273 683 'r1273'
        1276 539 'r1276'
        1295 981 'r1295'
        1304 1372 'r1304'
        1306 1057 'r1306'
        1314 1345 'r1314'
        1319 1176 'r1319'
        1324 439 'r1324'
        1332 1210 'r1332'
        1338 868 'r1338'
        1340 783 'r1340'
        1345 1034 'r1345'
        1357 1319 'r1357'
        1359 790 'r1359'
        1366 1393 'r1366'
        1372 1394 'r1372'
        1381 784 'r1381'
        1388 1332 'r1388'
        1389 783 'r1389'
        1393 1202 'r1393'
        1394 1304 'r1394'
$end
EOF
n="$(sed -n '/^\$flux/,/^\$end/p' "$RUN.str" | grep -c "'r[0-9]*'")"
[ "$n" = "$NSECT" ] || { echo "FLUX SECTIONS FAIL: $n sections in $RUN.str, expected $NSECT"; exit 1; }

#--- runs ------------------------------------------------------------------
# run_ok LOG EXITCODE: exit 0 and "simulation end" in the log
run_ok() {
  [ "$2" = 0 ] && grep -q "simulation end" "$1"
}
# ranks_ok LOG NPROC: each of the NPROC ranks printed once "shympi
# initialized: ID NPROC" (the same test as in check_lgr_mpi.sh)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
ranks_msg() { echo "$(basename "$1"): the log does not show $2 MPI processes ($(grep -c 'shympi initialized:' "$1") 'shympi initialized:' lines, expected one from each rank 0 to $(( $2 - 1 )))"; }
# flx_records FILE: "TOTAL DATA", the number of Fortran records of FILE and
# of those as long as its last record; "bad" if FILE is not a sequence of
# records
flx_records() {
  python3 - "$1" <<'PY'
import struct, sys
try:
    b = open(sys.argv[1], 'rb').read()
    lens, i = [], 0
    while i < len(b):
        n = struct.unpack('<i', b[i:i+4])[0]
        if n < 0 or i + 8 + n > len(b) or b[i+4+n:i+8+n] != b[i:i+4]:
            raise ValueError
        lens.append(n)
        i += 8 + n
    print(len(lens), sum(1 for n in lens if lens and n == lens[-1]))
except Exception:
    print("bad")
PY
}

echo "=== serial"
rm -f "$RUN.flx"
timeout 600 nice -n 19 shyfem "$RUN.str" > "$RUN.serial.log" 2>&1
src=$?
if [ "$src" = 124 ]; then
  fail "serial run timed out after 600 s"; echo "FLUX SECTIONS: FAIL"; exit 1
fi
if ! run_ok "$RUN.serial.log" "$src"; then
  tail -5 "$RUN.serial.log"; fail "serial run did not end (exit code $src)"
  echo "FLUX SECTIONS: FAIL"; exit 1
fi
line="$(grep 'nsect,kfluxm' "$RUN.serial.log" | head -1)"
ns="$(echo "$line" | awk '{print $2}')"
echo "  serial log: $(echo "$line" | sed 's/^ *//')"
[ "$ns" = "$NSECT" ] || fail "serial run reports '$ns' sections, expected $NSECT"
[ -s "$RUN.flx" ] || { fail "serial run wrote no $RUN.flx"; echo "FLUX SECTIONS: FAIL"; exit 1; }
recs="$(flx_records "$RUN.flx")"
ndata="$(echo "$recs" | awk '{print $2}')"
echo "  serial flux file: $(wc -c < "$RUN.flx") bytes, records (all, data): $recs"
if [ "$ndata" != "$NDATA" ]; then
  fail "serial flux file has '$ndata' data records, expected $NDATA"; echo "FLUX SECTIONS: FAIL"; exit 1
fi
mv "$RUN.flx" "$RUN.serial.flxsave"

for np in $NPS; do
  echo "=== $np processes"
  rm -f "$RUN.flx"
  timeout 600 nice -n 19 mpirun --oversubscribe -np "$np" shyfem "$RUN.str" > "$RUN.np$np.log" 2>&1
  mrc=$?
  if [ "$mrc" = 124 ]; then fail "run on $np processes timed out after 600 s"; continue; fi
  if ! run_ok "$RUN.np$np.log" "$mrc"; then
    tail -5 "$RUN.np$np.log"; fail "run on $np processes did not end (exit code $mrc)"; continue
  fi
  if ! ranks_ok "$RUN.np$np.log" "$np"; then fail "$(ranks_msg "$RUN.np$np.log" "$np")"; continue; fi
  if [ ! -s "$RUN.flx" ]; then fail "run on $np processes wrote no $RUN.flx"; continue; fi
  nrecs="$(flx_records "$RUN.flx")"
  if [ "$nrecs" != "$recs" ]; then
    fail "flux file on $np processes has records (all, data) '$nrecs', the serial one $recs"; continue
  fi
  if cmp -s "$RUN.serial.flxsave" "$RUN.flx"; then
    echo "  $np ranks reported; flux file identical to the serial one ($(wc -c < "$RUN.flx") bytes, $nrecs records)"
  else
    nb="$(cmp -l "$RUN.serial.flxsave" "$RUN.flx" 2> /dev/null | wc -l)"
    fail "flux file on $np processes differs from the serial one ($nb bytes, first at $(cmp "$RUN.serial.flxsave" "$RUN.flx" 2>&1 | sed 's/.*differ: //'))"
  fi
done

if [ "$rc" = 0 ]; then
  rm -f "$HERE/$RUN".*.log
  echo "FLUX SECTIONS: PASS"
else
  echo "logs kept: $(ls "$HERE/$RUN".*.log | tr '\n' ' ')"
  echo "FLUX SECTIONS: FAIL"
fi
exit "$rc"

