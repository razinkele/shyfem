#!/bin/bash
# mkcase.sh DIR ITURB : makes the continuous (c41), write (w41) and read (r41) STR of the
# #304 fidelity comparison from mm_hyd_41.str (serial, tilt kept), idtout = 1h
set -eu
D="$1"; IT="$2"
HERE=/home/razinka/wt-i304/testcases/examples/mar_menor
mkdir -p "$D/GRID"
cp $HERE/GRID/MM_coarse_smooth.grd "$D/GRID/"
( cd "$D/GRID" && shypre MM_coarse_smooth.grd > shypre.log 2>&1 )
ln -sfn $HERE/INPUT "$D/INPUT"
base() {  # title itend extra-para
  sed -e "s/^        mm_hyd_41\$/        $1/" \
      -e "s/itend = '[^']*'/itend = '$2'/" \
      -e "s/idtout = '3h'/idtout = '1h'/" \
      -e "s/^        iturb = 1 /        iturb = $IT /" \
      $HERE/mm_hyd_41.str
}
base c41 '2009-01-01::12:00:00' > "$D/c41.str"
base w41 '2009-01-01::06:00:00' | sed -e "s/^        iturb = $IT /        idtrst = -1\n        iturb = $IT /" > "$D/w41.str"
base r41 '2009-01-01::12:00:00' | sed -e "s/^        iturb = $IT /        itrst = -1     ityrst = 1\n        iturb = $IT /" \
      -e "s/^\\\$name\$/\$name\\n        restrt = 'w41.rst'/" > "$D/r41.str"
grep -n "itend\|idtout\|iturb\|idtrst\|itrst\|restrt\|^        [cwr]41" "$D"/c41.str "$D"/w41.str "$D"/r41.str
