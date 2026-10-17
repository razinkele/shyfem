#!/usr/bin/env python3
"""Write the benchmark STRs and GOTM namelists.

Runs (each at 20 and 40 uniform layers):
  keps     SHYFEM's own k-epsilon (iturb=2)
  gotm_gen GOTM as shipped in venice_lagoon/mar_menor: second-order CCH02
           stability functions + generic length scale (GLS "gen")
  gotm_ke1 GOTM standard k-epsilon: first-order, constant cmu (cm0=0.5477),
           dissipation equation, ce1/ce2/sig_k/sig_e = 1.44/1.92/1.0/1.3
  gotm_ke2 GOTM k-epsilon (dissipation equation) with the CCH02 second-order
           stability functions
"""
import re
from pathlib import Path

SHIPPED = Path("../venice_lagoon/INPUT/gotmturb.nml").read_text()
INFLOW = "325 244 163 82 1"
OUTFLOW = "81 162 243 324 405"


def nml(**kv):
    text = SHIPPED
    for key, val in kv.items():
        text, n = re.subn(rf"(^\s*{key}\s*=\s*)[^\s!]+", rf"\g<1>{val}", text, count=1, flags=re.M)
        assert n == 1, key
    return text


NMLS = {
    "gotm_gen": nml(),
    "gotm_ke1": nml(turb_method=2, len_scale_method=8, stab_method=1),
    "gotm_ke2": nml(turb_method=3, len_scale_method=8),
}
for name, text in NMLS.items():
    Path(f"INPUT/{name}.nml").write_text(text)

STR = """
 Neutral steady open-channel benchmark for the turbulence closures
 ({run}, {nl} layers). Flat 10 m channel, 0.1 m level drop over 20 km,
 roughness length z0 = 5 mm, no wind, no Coriolis, no stratification.

$title
	channel_turb
	{run}_{nl}
	channel
$end

&para
	date = '2026-01-01'  time = 0
	itanf = '2026-01-01'  itend = '2026-01-03'
	idt = '1m'  itsplt = 2  coumax = 0.9  idtmin = 0.1

	itmout = '2026-01-02::12:00'  idtout = '1h'
	itmdbg = '2026-01-02::22:00'  idtdbg = '1h'

	ibarcl = 0  icor = 0
	ireib = 6  czdef = 0.005
	iturb = {iturb}
	ilin = 0  itlin = 0  ihwadv = 1
	ampar = 0.6  azpar = 0.6  atpar = 1.0  adpar = 1.0  aapar = 0.
&end

$levels
	{levels}
$end

$bound1
	kbound = {inflow}
	ibtyp = 1  ampli = 0.  zref = 0.1
$end

$bound2
	kbound = {outflow}
	ibtyp = 1  ampli = 0.  zref = 0.
$end

$name
{gotmpa}
$end
"""
for nl in (20, 40):
    dz = 10.0 / nl
    vals = [f"{dz * (i + 1):g}" for i in range(nl)]
    # STR lines are capped at 80 characters: 10 levels per line
    levels = "\n\t".join(" ".join(vals[i:i + 10]) for i in range(0, nl, 10))
    for run, iturb in (("keps", 2), ("gotm_gen", 1), ("gotm_ke1", 1), ("gotm_ke2", 1)):
        gotmpa = f"\tgotmpa = 'INPUT/{run}.nml'" if iturb == 1 else ""
        Path(f"{run}_{nl}.str").write_text(
            STR.format(run=run, nl=nl, iturb=iturb, levels=levels,
                       inflow=INFLOW, outflow=OUTFLOW, gotmpa=gotmpa)
        )
print(sorted(p.name for p in Path(".").glob("*.str")))
