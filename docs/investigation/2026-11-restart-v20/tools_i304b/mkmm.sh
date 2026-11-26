#!/bin/bash
# mkmm.sh DIR "PARA LINE" ["EXTRA LINE"] : continuous c (0-12 h), write w (0-6 h, idtrst=-1), read r (6-12 h,
# itrst=-1) from mm_hyd_41.str, issue variant (no tilt, idtout = idtcon = 1h); the iturb line is
# replaced by "PARA LINES" (e.g. "iturb = 0 ievap = 1 hmin = 1. aapar = 0. iheat = 6")
set -eu
D="$1"; PL="$2"; EX="${3:-}"
HERE=/home/razinka/wt-i304b/testcases/examples/mar_menor
mkdir -p "$D/GRID"
cp $HERE/GRID/MM_coarse_smooth.grd "$D/GRID/"
( cd "$D/GRID" && PATH=/home/razinka/wt-i304b/bin:/usr/bin:$PATH shypre MM_coarse_smooth.grd > shypre.log 2>&1 )
mkdir -p "$D/INPUT"; cp $HERE/INPUT/* "$D/INPUT/"
base() {  # title itend
  sed -e "s/^        mm_hyd_41\$/        $1/" \
      -e "s/itend = '[^']*'/itend = '$2'/" \
      -e "s/idtout = '3h'/idtout = '1h'/" \
      -e "s/idtcon = '3h'/idtcon = '1h'/" \
      -e "/ztilt = /d" -e "/ktilt = /d" \
      -e "s/^        iturb = .*\$/        $PL${EX:+\\n        $EX}/" \
      $HERE/mm_hyd_41.str
}
TR="${TR:-06}"; TE="${TE:-12}"
base c "2009-01-01::$TE:00:00" > "$D/c.str"
base w "2009-01-01::$TR:00:00" | sed -e "s/^\(        $PL\)\$/\1\n        idtrst = -1/" > "$D/w.str"
base r "2009-01-01::$TE:00:00" | sed -e "s/^\(        $PL\)\$/\1\n        itrst = -1     ityrst = 1/" \
      -e "s/^\\\$name\$/\$name\\n        restrt = 'w.rst'/" > "$D/r.str"
grep -c "idtrst = -1" "$D/w.str" > /dev/null && grep -c "restrt = 'w.rst'" "$D/r.str" > /dev/null
