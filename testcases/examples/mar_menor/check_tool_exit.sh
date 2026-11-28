#!/bin/bash
#------------------------------------------------------------------------
# Tool exit status gate (#336): the SHYFEM tools that shyfem-ui runs
# (shypre, shybas, shyparts, shyelab, shyplot, shyadj, lgrelab) exit 7 on
# a missing or wrong input file.
#
# Before #336 every one of these rows ended on an error message with exit
# status 0 (a bare stop, "STOP error stop ..." on stderr, or in shyelab a
# written line and a normal end), so a script or the UI could not tell a
# failed run from a good one. They now end through error_stop of
# mod_error_stop: exit 7 and "error stop ROUTINE: TEXT" on stdout.
#
# It works in a mktemp -d folder with the binaries found on PATH (it does
# not put this tree's bin first: with another build first on PATH it
# checks that build) and asserts:
#   1. error rows, exit 7 and the message on stdout:
#        shypre    missing.grd, wrong.grd       (grd.f90)
#        shybas    missing.bas, wrong.bas       (shybas.f)
#        shyparts  missing.grd, wrong.grd       (no -np: shyparts.f90)
#        shyparts  -np 2 missing.grd, -np 2 wrong.grd (grd.f90, shyparts)
#        shyelab   missing.shy, wrong.shy       (shyelab.f90)
#        shyplot   missing.shy, wrong.shy       (plotutil.f90)
#        shyadj    missing.grd, wrong.grd       (grd.f90)
#        shyadj    square.grd, zero.grd         (adjgrd.f90, adjvar.f90, #338)
#        lgrelab   missing.lgr, wrong.lgr       (shy_util2.f)
#        extelab   missing.ext                  (extelab1.f90, #355)
#        flxelab   missing.flx                  (flxelab1.f90, #355)
#      a wrong file is "junk line" / "1 2 3"; and the two clo.f90 messages:
#        shyelab -  and  shyelab - FILE   (no option name after "-")
#        shyplot -tmin <1100 characters> FILE (value too long for option)
#        shyelab   option and output errors     (shyelab_*.f90, elabutil.f90, ... #338)
#        shyfem    ibio = 1 and imerc = 1 on a build without that module: exit 33
#                  (#338; a probe run that reaches the end of the simulation means the
#                  build links the module: skipped; any other probe result fails)
#   2. exit 0 for -h (with "Usage: TOOL") and for no argument (the usage,
#      #332 kept it at 0) of each of the seven tools
#   3. exit 0, and no "error stop" in the output, for a good run of each:
#        shypre -noopti MM_geo.grd, shybas MM_coarse.bas,
#        shyparts -np 2 MM_coarse.grd, shyadj MM_coarse.grd,
#        shyelab mm_lgr.hydro.shy, shyplot -varid 1 mm_lgr.hydro.shy,
#        lgrelab -lgmean mm_lgr.lgr.shy
#      (the .shy files come from mm_lgr.str run for 6 hours with shyfem)
#      and the same three tools on a path of over 80 characters (#343:
#      shy_util2.f cut the file name at 80, and the tools stopped with
#      "file not existing" for a file that exists): shyelab, shyplot -varid 1
#      and lgrelab -lgmean on the .shy files in a folder nested 5 deep, with
#      100 characters of folder names added to the mktemp -d path
#      and shyelab -split on an .ext and a .flx file, on a short and on that
#      long path (#355: extelab1.f90 and flxelab1.f90 kept the name in
#      character*80, ifileo failed and the first read segfaulted on unit -1
#      at over 80 characters; the files come from a 6 hour run of mm_ef.str,
#      written by this script: 4 extra nodes and one flux section)
#
# Needs shyfem, extelab, flxelab and the seven tools on PATH. Leaves nothing in this folder.
# Usage:  ./check_tool_exit.sh
#         PATH=<other bin>:$PATH ./check_tool_exit.sh   (checks that build)
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="shypre shybas shyparts shyelab shyplot shyadj lgrelab"
verdict() { echo "=================================================================="
  if [ "$1" -eq 0 ]; then echo "TOOL EXIT: PASS"; else echo "TOOL EXIT: FAIL"; fi; }

for t in shyfem extelab flxelab $TOOLS; do
  command -v "$t" > /dev/null || { echo "FAIL: $t not on PATH"; verdict 1; exit 1; }
done
echo "binaries: $(dirname "$(command -v shypre)")"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/check_tool_exit.XXXXXX")" || exit 1
# the unwritable-folder rows run with a-w on a folder: restore u+w before rm
trap 'chmod -R u+w "$TMP" 2> /dev/null; rm -rf "$TMP"' EXIT
cd "$TMP" || exit 1
rc=0
n=0
nfail=0

# row WANT PATTERN CMD...: CMD exits WANT; PATTERN ("" for none) is a fixed
# string that its stdout must contain. A good row (WANT 0) must also print
# no "error stop" on stdout or stderr.
row() {
  local want=$1 pat=$2; shift 2
  n=$((n + 1))
  timeout 300 "$@" > "$TMP/out.$n" 2> "$TMP/err.$n"
  local st=$? why=""
  [ "$st" -eq "$want" ] || why="exit $st, want $want"
  if [ -z "$why" ] && [ -n "$pat" ] && ! grep -qF -- "$pat" "$TMP/out.$n"; then
    why="no \"$pat\" on stdout"
  fi
  if [ -z "$why" ] && [ "$want" -eq 0 ] && grep -qi "error stop" "$TMP/out.$n" "$TMP/err.$n"; then
    why="\"$(grep -hi -m1 "error stop" "$TMP/out.$n" "$TMP/err.$n" | sed 's/^ *//')\""
  fi
  local cmd="$*"
  [ "${#cmd}" -gt 60 ] && cmd="${cmd:0:57}..."
  if [ -z "$why" ]; then
    printf 'ok   %-60s exit %s\n' "$cmd" "$st"
  else
    printf 'FAIL %-60s %s\n' "$cmd" "$why"
    local f last
    for f in out err; do
      last=$(grep -v '^ *$' "$TMP/$f.$n" | tail -1 | sed 's/^ *//; s/ *$//' | cut -c1-100)
      [ -n "$last" ] && echo "       last line on std$f: $last"
    done
    rc=1; nfail=$((nfail + 1))
  fi
}

#------------------------------------------------------------------------
# inputs
#------------------------------------------------------------------------

mkdir GRID INPUT good || exit 1
cp "$HERE/GRID/MM_coarse.grd" "$HERE/GRID/MM_coarse.bas" "$HERE/GRID/MM_geo.grd" GRID/ \
  && cp "$HERE/INPUT/wind_scir.txt" INPUT/ \
  && cp "$HERE/release_areas.txt" "$HERE/mm_lgr.str" . \
  || { echo "FAIL: cannot copy the inputs"; verdict 1; exit 1; }
for e in grd bas shy lgr; do printf 'junk line\n1 2 3\n' > "wrong.$e"; done
rm -f missing.grd missing.bas missing.shy missing.lgr
# two grids shyadj cannot adjust (#338): a square of two triangles (too few
# nodes, the grades do not add up: "element layout") and MM_coarse.grd with
# node 3 of element 100 moved onto node 1 of it (an element of zero area)
printf '1 1 0 0.0 0.0\n1 2 0 1000.0 0.0\n1 3 0 1000.0 1000.0\n1 4 0 0.0 1000.0\n2 1 0 3 1 2 3 5.0\n2 2 0 3 1 3 4 5.0\n' > square.grd
awk 'NR == FNR { if ($1 == 1) { x[$2] = $4; y[$2] = $5 }
                 if ($1 == 2 && $2 == 100) { a = $5; c = $7 }; next }
     $1 == 1 && $2 == c { print $1, $2, $3, x[a], y[a]; next }
     { print }' "$HERE/GRID/MM_coarse.grd" "$HERE/GRID/MM_coarse.grd" > zero.grd

echo "=== good runs (exit 0)"
cd GRID || exit 1
row 0 "" shypre -noopti MM_geo.grd
cd .. || exit 1
[ -s GRID/MM_geo.bas ] || { echo "FAIL: shypre made no GRID/MM_geo.bas"; rc=1; nfail=$((nfail + 1)); }
sed -i "s/itend = '2009-01-05'/itend = '2009-01-01::06:00:00'/" mm_lgr.str
grep -q "itend = '2009-01-01::06:00:00'" mm_lgr.str \
  || { echo "FAIL: cannot shorten mm_lgr.str"; verdict 1; exit 1; }
timeout 600 shyfem mm_lgr.str > shyfem.log 2>&1 \
  || { echo "FAIL: shyfem mm_lgr.str did not complete"; tail -3 shyfem.log; verdict 1; exit 1; }
for f in mm_lgr.hydro.shy mm_lgr.lgr.shy; do
  [ -s "$f" ] || { echo "FAIL: shyfem made no $f"; verdict 1; exit 1; }
done
# a second short run for the .ext and .flx files (no lagrangian part): four
# extra nodes, and one flux section of two adjacent nodes (two vertices of
# element 1 of GRID/MM_coarse.grd)
cat > mm_ef.str <<'EOF_STR' || { echo "FAIL: cannot write mm_ef.str"; verdict 1; exit 1; }
$title
        2D sim for Mar Menor - ext and flx for the tool gate
        mm_ef
        GRID/MM_coarse
$end

$para
        itanf = '2009-01-01'    itend = '2009-01-01::06:00:00'
        idt = '300s'
        idtext = '300s'
        idtflx = '300s'

        date = 20090101

        ilin = 1
$end

$extra
        128     'sea boundary'
        58      'inlet'
        868     'center of lagoon'
        441     'border of lagoon'
$end

$flux
        334 828 'r1'
$end
EOF_STR
timeout 600 shyfem mm_ef.str > shyfem_ef.log 2>&1 \
  || { echo "FAIL: shyfem mm_ef.str did not complete"; tail -3 shyfem_ef.log; verdict 1; exit 1; }
for f in mm_ef.ext mm_ef.flx; do
  [ -s "$f" ] || { echo "FAIL: shyfem made no $f"; verdict 1; exit 1; }
done
cd good || exit 1
row 0 "" shybas ../GRID/MM_coarse.bas
row 0 "domain successfully partitioned" shyparts -np 2 ../GRID/MM_coarse.grd
row 0 "Successful completion" shyadj ../GRID/MM_coarse.grd
row 0 "time records read" shyelab ../mm_lgr.hydro.shy
row 0 "total number of plots" shyplot -varid 1 ../mm_lgr.hydro.shy
row 0 "time records read" lgrelab -lgmean ../mm_lgr.lgr.shy
row 0 "time records elaborated" shyelab -split ../mm_ef.ext
row 0 "time records elaborated" shyelab -split ../mm_ef.flx

# the same runs on a path over 80 characters, whatever the length of TMPDIR
LONGDIR="$TMP"
for i in 1 2 3 4 5; do LONGDIR="$LONGDIR/long_path_segment_$i"; done
mkdir -p "$LONGDIR" && ln -s "$TMP/mm_lgr.hydro.shy" "$TMP/mm_lgr.lgr.shy" \
  "$TMP/mm_ef.ext" "$TMP/mm_ef.flx" "$LONGDIR/" \
  || { echo "FAIL: cannot make the long path"; verdict 1; exit 1; }
[ "${#LONGDIR}" -gt 80 ] || { echo "FAIL: long path is not over 80 characters"; verdict 1; exit 1; }
row 0 "time records read" shyelab "$LONGDIR/mm_lgr.hydro.shy"
row 0 "total number of plots" shyplot -varid 1 "$LONGDIR/mm_lgr.hydro.shy"
row 0 "time records read" lgrelab -lgmean "$LONGDIR/mm_lgr.lgr.shy"
row 0 "time records elaborated" shyelab -split "$LONGDIR/mm_ef.ext"
row 0 "time records elaborated" shyelab -split "$LONGDIR/mm_ef.flx"
cd .. || exit 1

echo "=== help and usage (exit 0)"
for t in $TOOLS; do
  row 0 "Usage: $t" "$t" -h
  row 0 "Usage: $t" "$t"
done

echo "=== missing or wrong input file (exit 7, message on stdout)"
row 7 "error stop grd_internal_init: cannot open file"           shypre missing.grd
row 7 "error stop grd_read: error reading grd file"              shypre wrong.grd
row 7 "error stop read_command_line_file: no such file"          shybas missing.bas
row 7 "error stop read_command_line_file: unknown format"        shybas wrong.bas
row 7 "error stop shyparts_init: no np given"                    shyparts missing.grd
row 7 "error stop shyparts_init: no np given"                    shyparts wrong.grd
row 7 "error stop grd_internal_init: cannot open file"           shyparts -np 2 missing.grd
row 7 "error stop read_given_file: format not recognized"        shyparts -np 2 wrong.grd
row 7 "error stop shyelab: file does not exist"                  shyelab missing.shy
row 7 "error stop shyelab: unknown file type"                    shyelab wrong.shy
row 7 "error stop classify_files: file not existing: missing.shy" shyplot missing.shy
row 7 "error stop classify_files: cannot determine file type"    shyplot wrong.shy
row 7 "error stop grd_internal_init: cannot open file"           shyadj missing.grd
row 7 "error stop grd_read: error reading grd file"              shyadj wrong.grd
row 7 "error stop statgrd: element layout"                       shyadj square.grd
row 7 "error stop checkarea: non-positive area"                      shyadj zero.grd
row 7 "error stop shyelab: file not existing"                    lgrelab missing.lgr
row 7 "error stop shyelab: not a valid shy file"                 lgrelab wrong.lgr
row 7 "error stop extelab: cannot open file"                     extelab missing.ext
row 7 "error stop flxelab: cannot open file"                     flxelab missing.flx

echo "=== shyelab option and output errors (exit 7, message on stdout; #338)"
H=mm_lgr.hydro.shy
printf '' > nodes_empty.txt
printf 'abc\n' > nodes_junk.txt
printf '99999\n' > nodes_none.txt
row 7 "error stop shyelab_init_output: outformat not recognized" shyelab -outformat foo $H
row 7 "error stop convert_to_internal_nodes: no such node"    shyelab -node 99999 $H
row 7 "error stop get_node_list: read error"                 shyelab -node abc $H
row 7 "error stop get_node_file: cannot open file"           shyelab -nodes missing.txt $H
row 7 "error stop get_node_file: no data"                    shyelab -nodes nodes_empty.txt $H
row 7 "error stop get_node_file: read error"                 shyelab -nodes nodes_junk.txt $H
row 7 "error stop convert_to_internal_nodes: no such node"    shyelab -nodes nodes_none.txt $H
row 7 "error stop get_closest_node: need 2 values"           shyelab -coord 1 $H
row 7 "error stop get_closest_node: internal error (1)"      shyelab -coord a,b $H
row 7 "error stop parse_extract_range: error in parsing"     shyelab -extract abc $H
row 7 "error stop initialize_extract: error in record list"  shyelab -extract 0 $H
row 7 "error stop shy_proj: unknown projection"              shyelab -proj foo $H
row 7 "error stop shy_proj: no parameters"                   shyelab -proj GB $H
row 7 "error stop elabtime_set_minmax: cannot parse"         shyelab -tmin garbage $H
row 7 "error stop shyelab: need 2 files"                     shyelab -diff $H
row 7 "error stop handle_smooth_option: cannot parse"        shyelab -smooth abc $H
row 7 "error stop elabutil_set_averaging: incompatible options" shyelab -aver -sum $H
row 7 "error stop shyelab1: vorticity output format"         shyelab -vorticity -out -outformat gis $H
row 7 "error stop fem_regular_parse: string"                 shyelab -lgdens -reg abc mm_lgr.lgr.shy
row 7 "error stop shyelab_init_output: regular output"       shyelab -reg 100 -resample 1 $H
row 7 "error stop handle_area: area file"                    shyelab -areas GRID/MM_coarse.grd $H
# output into a folder that cannot be written (not as root: root can write there)
mkdir ro && ln -s ../$H ro/h.shy && chmod a-w ro
if touch ro/probe 2> /dev/null; then
  rm -f ro/probe
  echo "skip shyelab rows for an unwritable folder (the folder is writable, root?)"
else
  cd ro || exit 1
  row 7 "error stop shy_split_internal: cannot open file"      shyelab -split h.shy
  row 7 "error stop shyelab_init_output: opening file"         shyelab -out h.shy
  row 7 "error stop gis_write_connect: cannot open file"       shyelab -out -outformat gis h.shy
  cd .. || exit 1
fi
chmod u+w ro

echo "=== extelab, flxelab, lgrelab and tselab input and option errors (exit 7, message on stdout; #338)"
: > empty.ext
: > empty.flx
printf 'junk\n' > wrong.ext
head -c 300 mm_ef.ext > trunc.ext
head -c 300 mm_ef.flx > trunc.flx
printf '2009-01-01::00:00:00 1.0\n2009-01-01::01:00:00 2.0\n' > good.ts
printf 'junk line\n1 2 3\n' > wrong.ts
for h in 0 1 2 3 4 5; do printf '2009-01-01::0%s:00:00 %s.0\n' $h $h; done > late_bad.ts
printf '2009-01-01::07:00:00 abc\n' >> late_bad.ts
row 0 "" tselab good.ts
row 7 "error stop extelab: not a valid ext file"           extelab empty.ext
row 7 "error stop extelab: not a valid ext file"           extelab wrong.ext
row 7 "error stop extelab: empty header"                  extelab trunc.ext
row 7 "error stop flxelab: not a valid flx file"          flxelab empty.flx
row 7 "error stop flxelab: not a valid flx file"          flxelab wrong.ext
row 7 "error stop flxelab: error in header"               flxelab trunc.flx
row 7 "error stop lgrelab: -lg2d output"                  lgrelab -lg2d mm_lgr.lgr.shy
row 7 "error stop tselab: not a valid time series file"   tselab missing.ts
row 7 "error stop tselab: not a valid time series file"   tselab wrong.ts
row 7 "error stop tsinf: error reading record"            tselab late_bad.ts

echo "=== option errors of clo.f90 (exit 7, message on stdout)"
long=$(printf '%01100d' 0)
row 7 'error stop clo_parse_options: no option name after "-"'   shyelab -
row 7 'error stop clo_parse_options: no option name after "-"'   shyelab - mm_lgr.hydro.shy
row 7 "error stop clo_parse_options: value too long for option: tmin" \
  shyplot -tmin "$long" mm_lgr.hydro.shy

# a model run that asks for an ecology module the build does not link (#338,
# ecological_dummy.f90, mercury_dummy.f90) must stop with exit 33 (shympi_abort_internal),
# not 0: ibio = 1 and imerc = 1 in an otherwise good STR. A probe run decides:
# its output has the "not linked" message -> the row is checked; it ran to the end
# (exit 0 and "cpu time (total)" in the log) -> the build links the module, skip;
# anything else (killed, crashed, the message reworded) -> FAIL, never a skip.
echo "=== ecology module not linked (exit 33, message on stdout)"
eco_row() {   # PARAM LINKED-MSG MESSAGE
  local par=$1 notlinked=$2 msg=$3 st
  sed "0,/^\$para/s//\$para\n        $par = 1/" mm_lgr.str > mm_eco.str
  grep -q "^        $par = 1" mm_eco.str || { echo "FAIL: cannot set $par in mm_eco.str"; rc=1; nfail=$((nfail + 1)); return; }
  timeout 300 shyfem mm_eco.str > eco_probe.out 2>&1
  st=$?
  if grep -qF -- "$notlinked" eco_probe.out; then
    row 33 "$msg" shyfem mm_eco.str
  elif [ "$st" -eq 0 ] && grep -qF "cpu time (total)" eco_probe.out; then
    echo "skip $par = 1 row (this build links the module: probe exit 0, ran to the end)"
  else
    echo "FAIL $par = 1 probe: exit $st, no \"$notlinked\" and no end of simulation"
    echo "       last line: $(grep -v '^ *$' eco_probe.out | tail -1 | sed 's/^ *//' | cut -c1-100)"
    rc=1; nfail=$((nfail + 1))
  fi
}
eco_row ibio "No ecological module has been linked" "error stop ecological_module: ibio"
eco_row imerc "you will have to set MERCURY = true" "error stop mercury_init: mercury module is not linked"

echo "$n rows, $nfail failed"
verdict $rc
exit $rc
