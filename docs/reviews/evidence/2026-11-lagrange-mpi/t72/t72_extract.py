#!/usr/bin/env python3
"""Task 7.2 C3: the values of the acceptance table from the logs of
t72_acc.sh (directory given).  Prints one block per criterion."""
import glob
import os
import re
import sys

D = sys.argv[1]
CASES = ['mm_lgr_a', 'mm_lgr_b', 'mm_lgr_c', 'mm_lgr_e', 'mm_lgr_w']
SHORT = {'mm_lgr_a': 'A', 'mm_lgr_b': 'B', 'mm_lgr_c': 'C', 'mm_lgr_e': 'E', 'mm_lgr_w': 'W', 'mm_lgr': 'D'}


def read(name):
    p = os.path.join(D, name)
    return open(p, errors='replace').read() if os.path.exists(p) else ''


def verdict(txt):
    m = re.findall(r'LGR GATE: (PASS|FAIL)', txt)
    return m[-1] if m else 'MISSING'


print('== AC1 flux: case np verdict | rows off (all arrays) | largest worst/scale per class (all-own, main owner, elsewhere)')
for c in ['mm_lgr_a', 'mm_lgr_b', 'mm_lgr_c']:
    for np_ in (2, 4):
        t = read('%s.%d.flux.log' % (c, np_))
        off, worst = 0, {}
        for m in re.finditer(r'^  (all-own nodes|mixed, main owner|mixed, owned elsewhere)\s+(\d+)\s+(\d+)\s+(\S+)', t, re.M):
            off += int(m.group(3))
            worst[m.group(1)] = max(worst.get(m.group(1), 0.0), float(m.group(4)))
        cov = re.findall(r'coverage: (.*)', t)
        print('%s %d %s | off %d | %s | %s' % (SHORT[c], np_, verdict(t), off,
              ', '.join('%.1e' % worst.get(k, -1) for k in ('all-own nodes', 'mixed, main owner', 'mixed, owned elsewhere')),
              cov[0][:120] if cov else 'no coverage line'))
        mt = read('%s.%d.flux.mpi.log' % (c, np_))
        for line in re.findall(r'lgr topology: elements shared.*', mt):
            print('    ' + ' '.join(line.split()))

print('== AC2 ids / AC3 pos (particle file)')
for c in CASES:
    for np_ in (2, 4):
        ti, tp = read('%s.%d.ids.log' % (c, np_)), read('%s.%d.pos.log' % (c, np_))
        fl = re.findall(r'^floor: .*?: (\S+) <= (\S+): (\w+)', tp, re.M)
        tt = re.findall(r'^tt: .*?: (\d+) <= (\d+): (\w+)', tp, re.M)
        ins = re.findall(r'^inserted block: .*?: (\d+): (\w+)', tp, re.M)
        iez = re.findall(r'^ie: .*?: (\d+): (\w+)', tp, re.M)
        last = re.findall(r'last output t=(\S+): active=(\d+) inserted=(\d+) exited=(\d+)', ti)
        print('%s %d ids %s pos %s | beyond %s | largest %s | tt %s | inserted-block diffs %s | ie diffs at 0 %s | last output (serial, MPI) %s'
              % (SHORT[c], np_, verdict(ti), verdict(tp),
                 '/'.join(fl[0][:2]) if fl else '?', '/'.join(fl[1][:2]) if len(fl) > 1 else '?',
                 '/'.join(tt[0][:2]) if tt else '?', ins[0][0] if ins else '?', iez[0][0] if iez else '?', last))

print('== AC3 floor (dump)')
for c in CASES:
    for np_ in (2, 4):
        t = read('%s.%d.floor.log' % (c, np_))
        fl = re.findall(r'^  floor: .*?: (\S+) <= (\S+): (\w+)', t, re.M)
        tot = re.findall(r'totals over (\d+) outputs: unmatched (\d+), nan (\d+).*?layer differs (\d+), z differs (\d+)', t)
        print('%s %d %s | beyond %s | largest %s | totals %s' % (SHORT[c], np_, verdict(t),
              '/'.join(fl[0][:2]) if fl else '?', '/'.join(fl[1][:2]) if len(fl) > 1 else '?', tot))

print('== AC3 hand-over fidelity, AC11, spec 7 statistics')
for c in ['mm_lgr_a', 'mm_lgr_b', 'mm_lgr_c', 'mm_lgr_w']:
    for np_ in (2, 4, 8):
        t = read('%s.%d.handover.log' % (c, np_))
        if not t:
            continue
        rule = re.findall(r'rule: (.*)', t)
        grp = re.findall(r'^  (changed process|stayed)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)', t, re.M)
        reloc = re.findall(r'lgr relocation by position: parked (\d+).*?went to another process (\d+), nobody answered (\d+), hit within the margin and nobody answered (\d+)', t)
        print('%s %d %s | groups %s' % (SHORT[c], np_, verdict(t), grp))
        print('    rule: %s' % (rule[0][:230] if rule else '?'))
        print('    relocation (parked, went to another process, nobody answered, margin-unanswered): %s' % reloc)
        mt = read('%s.%d.handover.mpi.log' % (c, np_))
        for pat in (r'lgr hand-over: .*', r'lgr dry elements: .*', r'lgr left the basin: .*', r'lgr side table: \d+ cut-off.*',
                    r'lgr side table: added.*', r'lgr side table: layers.*', r'lgr topology: elements shared.*'):
            for line in re.findall(pat, mt):
                print('    ' + ' '.join(line.split())[:260])
        cons = re.findall(r'consistency check \(levdbg = \d\) silent', t)
        print('    consistency check silent lines: %d' % len(cons))

print('== AC4 case D')
for np_ in (2, 4):
    t = read('mm_lgr.%d.ids.log' % np_)
    reloc = re.findall(r'lgr relocation by position: parked (\d+).*?stayed (\d+), kept for lack of a layer (\d+), went to another process (\d+), nobody answered (\d+), hit within the margin and nobody answered (\d+)', t)
    selfc = re.findall(r'lgr relocation self-check: compared (\d+), differing (\d+)', t)
    print('D %d %s | relocation %s | serial self-check %s | silent %d | %s' % (np_, verdict(t), reloc, selfc,
          len(re.findall(r'silent', t)), re.findall(r'last output t=\S+: active=\d+ inserted=\d+ exited=\d+', t)))
    mt = read('mm_lgr.%d.ids.mpi.log' % np_)
    for line in re.findall(r'lgr hand-over: particles.*', mt):
        print('    ' + ' '.join(line.split())[:200])

print('== perturb')
for c in CASES:
    t = read('%s.4.perturb.log' % c)
    n = re.findall(r'(\d+) dump files compared, (\d+) differing', t)
    print('%s 4 %s %s' % (SHORT[c], verdict(t), n))

print('== release gates (part --first-only)')
for f in sorted(glob.glob(os.path.join(D, '*.part.log'))):
    print(os.path.basename(f), verdict(open(f).read()))
