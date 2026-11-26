#!/usr/bin/env python3
"""summ.py DIR NAME_C NAME_R [times...] : max|d| per ivar at the given hours between
NAME_C.{hydro,ts}.shy and NAME_R.{hydro,ts}.shy, and the number of records that differ."""
import sys, subprocess, re, os
D, C, R = sys.argv[1:4]
times = [float(t) for t in sys.argv[4:]] or [7.0, 12.0]
here = os.path.dirname(os.path.abspath(__file__))
for kind in ('hydro', 'ts'):
    a = f"{D}/{C}.{kind}.shy"; b = f"{D}/{R}.{kind}.shy"
    if not (os.path.exists(a) and os.path.exists(b)):
        print(f"  {kind}: missing"); continue
    out = subprocess.run([sys.executable, f"{here}/shycmp.py", a, b], capture_output=True, text=True).stdout
    nrec = ndiff = 0; worst = {}; allmax = {}
    for line in out.splitlines():
        m = re.match(r"t=\s*([\d.]+)h ivar=\s*(\d+) .*max\|d\|=(\S+)", line)
        if not m: continue
        t, iv, d = float(m.group(1)), int(m.group(2)), float(m.group(3))
        nrec += 1; ndiff += d > 0
        allmax[iv] = max(allmax.get(iv, 0.), d)
        for tt in times:
            if abs(t - tt) < 1e-6:
                worst[(tt, iv)] = max(worst.get((tt, iv), 0.), d)
    s = "  ".join(f"{tt:g}h iv{iv}={worst[(tt,iv)]:.3e}" for (tt, iv) in sorted(worst))
    print(f"  {kind}: {ndiff}/{nrec} records differ; max over run " + " ".join(f"iv{k}={v:.3e}" for k, v in sorted(allmax.items())) + f"\n     {s}")
