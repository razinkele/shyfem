#!/bin/bash
# mkven.sh DIR TRST [SED-EXPR] : venlag_smoke continuous c (0-6 h), write w (0-TRST, idtrst=-1),
# read r (TRST-6 h, itrst=-1); TRST like 03:00; SED-EXPR is applied to all three STR
set -eu
D="$1"; TR="$2"; SX="${3:-}"
VEN=/home/razinka/wt-i304b/testcases/examples/venice_lagoon
mkdir -p "$D/GRID" "$D/INPUT"
cp $VEN/GRID/venlag62.grd "$D/GRID/"
cp $VEN/INPUT/gotmturb.nml $VEN/INPUT/wind_lightBora.dat $VEN/INPUT/heat_idealSummer.dat "$D/INPUT/"
[ -f "$D/GRID/venlag62.bas" ] || ( cd "$D/GRID" && PATH=/home/razinka/wt-i304b/bin:/usr/bin:$PATH shypre -silent venlag62.grd > shypre.log 2>&1 )
base() { # title itend
  sed -e "s/^\tvenlag_smoke\$/\t$1/" -e "s/itend  = '2014-08-01::06:00'/itend  = '$2'/" ${SX:+-e "$SX"} $VEN/venlag_smoke.str
}
base c '2014-08-01::06:00' > "$D/c.str"
base w "2014-08-01::$TR" | sed -e "s/^        iturb  = \(.*\)\$/        iturb  = \1\n        idtrst = -1/" > "$D/w.str"
base r '2014-08-01::06:00' | sed -e "s/^        iturb  = \(.*\)\$/        iturb  = \1\n        itrst = -1     ityrst = 1/" \
     -e "s/^\\\$name\$/\$name\\n        restrt = 'w.rst'/" > "$D/r.str"
grep -q "idtrst = -1" "$D/w.str"; grep -q "restrt = 'w.rst'" "$D/r.str"; grep -q "itend  = '2014-08-01::$TR'" "$D/w.str"
