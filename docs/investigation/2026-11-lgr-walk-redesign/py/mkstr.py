# mkstr.py SRC.str OUTDIR NAME KIND SEED [LEVELS]
# writes OUTDIR/NAME.str from mm_hyd_41.str (one day, tilt lines removed)
# KIND: go   forced, boundaries as in mm_hyd_41 (open level boundary, river), GOTM
#       gc   forced, both boundaries closed (ibtyp = 0), GOTM (iturb = 1)
#       kc   forced, both boundaries closed, iturb = 0, diftur = 1.e-2, vistur = 1.e-3
#       kc3/kc4  the same with diftur = 1.e-3 / 1.e-4
#       s2/s3/s4 still water as check_lgr_wellmixed.sh, iturb = 0, diftur = 1.e-2 / 1.e-3 / 1.e-4
# SEED: lgrseed (0 = no lgrseed line, the default 1)
# LEVELS: def (mm_hyd_41) or a uniform spacing in m (0.5, 1, 2) down to >= 74.62 m
import re, sys
src, outdir, name, kind, seed = sys.argv[1:6]
seed = int(seed)
lev = sys.argv[6] if len(sys.argv) > 6 else "def"
txt = open(src).read()
def sub(pat, rep, n_expected, flags=re.M):
    global txt
    txt, n = re.subn(pat, rep, txt, flags=flags)
    if n != n_expected:
        sys.exit("edit %r: %d matches, expected %d" % (pat, n, n_expected))
sub(r"^[ \t]*ztilt[ \t]*=.*\n", "", 1)
sub(r"^[ \t]*ktilt[ \t]*=.*\n", "", 1)
sub(r"itend = '[^']*'", "itend = '2009-01-02'", 1)
sub(r"^([ \t]*)mm_hyd_41[ \t]*$", r"\g<1>" + name, 1)
if kind in ("gc", "kc", "kc3", "kc4", "s2", "s3", "s4"):
    sub(r"^([ \t]*)ibtyp = [13][ \t]*$", r"\1ibtyp = 0", 2)
if kind in ("kc", "kc3", "kc4"):
    kk = {"kc": "1.e-2", "kc3": "1.e-3", "kc4": "1.e-4"}[kind]
    sub(r"^([ \t]*)iturb = 1      ievap = 1 (.*)$", r"\1iturb = 0      ievap = 1 \2\n\1diftur = %s   vistur = 1.e-3" % kk, 1)
if kind in ("s2", "s3", "s4"):
    k = {"s2": "1.e-2", "s3": "1.e-3", "s4": "1.e-4"}[kind]
    sub(r"^([ \t]*)ibarcl = 3", r"\1ibarcl = 0", 1)
    sub(r"^([ \t]*)iturb = 1      ievap = 1 (.*)$", r"\1iturb = 0      ievap = 0 \2\n\1diftur = %s   vistur = 1.e-3" % k, 1)
    sub(r"^[ \t]*wind[ \t]*=.*\n", "", 1)
    sub(r"^[ \t]*qflux[ \t]*=.*\n", "", 1)
    sub(r"^[ \t]*rain[ \t]*=.*\n", "", 1)
if lev != "def":
    dz = float(lev)
    vals = []
    i = 1
    while True:
        v = i * dz
        vals.append(("%g" % v))
        if v >= 74.62:
            break
        i += 1
    lines = []
    for j in range(0, len(vals), 10):
        lines.append("        " + " ".join(vals[j:j + 10]))
    sub(r"^[ \t]*1 2 3 4 5 6 7 8 9 10 12 15 20 30 40 50 60 70 80[ \t]*$", "\n".join(lines), 1)
    for l in lines:
        assert len(l) < 80
lag = "\n$lagrg\n        ilagr = 3   nbdymax = 50000\n        nbdy = 2000  idtl = 0  idtlgr = '1h'\n        rwhpar = 0  ipvert = 20\n"
if seed > 0:
    lag += "        lgrseed = %d\n" % seed
lag += "$end\n"
txt += lag
open("%s/%s.str" % (outdir, name), "w").write(txt)
