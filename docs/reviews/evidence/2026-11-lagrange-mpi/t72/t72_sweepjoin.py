#!/usr/bin/env python3
"""Task 7.2 C4: the sweep of 2026-11-21 (mpisweep.log, eutrosweep.log) against
the rerun (results.tsv, infcmp.tsv of t72_sweep.sh): one Markdown row per case
and build, then and now, serial and 4 processes, with a verdict.
usage: t72_sweepjoin.py MPISWEEP_LOG EUTROSWEEP_LOG RESULTS_TSV INFCMP_TSV SWEEP_DIR
For a run of the rerun that stopped, the detail is the line of its output that
says "is not supported with MPI" or "too many MPI processes" when there is
one (the first matching line of a 4-process log depends on the order in which
the processes write).
"""
import os
import re
import sys

FINE = {'ENDED', 'STEPPING'}
RANK = {'ENDED': 0, 'STEPPING': 0, 'STOP': 1, 'OTHER': 1, 'SILENT': 2, 'CRASH': 3}


def parse_log(path, build, folder=None):
    out = {}
    pat = re.compile(r'^  (\S+) (ser|mpi): (\S+) rc=(\S+) steps=(\d+)\s*(?:\| (.*))?$')
    for line in open(path):
        m = pat.match(line.rstrip('\n'))
        if not m:
            continue
        case = m.group(1) if folder is None else '%s/%s' % (folder, m.group(1))
        out[(build, case, m.group(2))] = (m.group(3), m.group(4), int(m.group(5)), (m.group(6) or '').strip())
    return out


def norm(det):
    """a message without the process number of an MPI abort"""
    return re.sub(r'invoked on rank \d+', 'invoked on rank N', det)


def short(c):
    if c is None:
        return '–'
    cls, rc, steps, det = c
    s = cls
    if cls == 'STEPPING':
        s += ' (%d steps)' % steps
    if cls not in FINE:
        s += ' rc %s' % rc
        if det:
            s += ': ' + det.replace('|', '/')[:70]
    return s


def main():
    then = parse_log(sys.argv[1], 'default')
    then.update(parse_log(sys.argv[2], 'eutro', 'weutro_box'))
    now = {}
    for line in open(sys.argv[3]):
        p = line.rstrip('\n').split('\t')
        if p[0] == 'build':
            continue
        b, d, s, v, cls, rc, steps, det = (p + [''] * 8)[:8]
        det = det.strip()
        if cls == 'STOP' and os.path.exists(os.path.join(sys.argv[5], v, d, s + '.out')):
            out = os.path.join(sys.argv[5], v, d, s + '.out')
            for key in ('is not supported with MPI', 'too many MPI processes'):
                hits = [ln.strip() for ln in open(out, errors='replace') if key in ln]
                if hits:
                    det = hits[0] if len(hits) == 1 else '%s (x%d)' % (hits[0], len(hits))
                    break
        now[(b, '%s/%s' % (d, s), v)] = (cls, rc, int(steps or 0), det)
    inf = {}
    for line in open(sys.argv[4]):
        p = line.rstrip('\n').split('\t')
        if p[0] == 'label':
            continue
        m = re.match(r'\[(\w+)\] (\S+)', p[0])
        if m:
            inf[(m.group(1), m.group(2))] = '%s (%s)' % (p[6].split()[0], p[4])
    cases = sorted({(b, c) for b, c, _ in list(now) + list(then)}, key=lambda x: (x[0] != 'default', x[1]))
    print('| Build | Case | Serial then | Serial now | 4 processes then | 4 processes now | Energy lines now | Verdict |')
    print('|---|---|---|---|---|---|---|---|')
    worse = []
    for b, c in cases:
        row = []
        verdict = []
        for v in ('ser', 'mpi'):
            t, n = then.get((b, c, v)), now.get((b, c, v))
            row += [short(t), short(n)]
            if t is None:
                verdict.append('%s: new case' % v)
            elif n is None:
                verdict.append('%s: NOT RUN' % v)
                worse.append((b, c, v))
            elif RANK[n[0]] > RANK[t[0]]:
                verdict.append('%s: WORSE' % v)
                worse.append((b, c, v))
            elif RANK[n[0]] < RANK[t[0]]:
                verdict.append('%s: better' % v)
            elif t[0] not in FINE and norm(t[3]) != norm(n[3]):
                verdict.append('%s: other message' % v)
        print('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
            b, c, row[0], row[1], row[2], row[3], inf.get((b, c), '–'), '; '.join(verdict) or 'same'))
    n_then = len({c for b, c, v in then if b == 'default'})
    n_now = len({c for b, c, v in now if b == 'default'})
    print()
    print('cases: then %d (default build), now %d; EUTRO build then %d, now %d; worse: %d %s'
          % (n_then, n_now, len({c for b, c, v in then if b == 'eutro'}),
             len({c for b, c, v in now if b == 'eutro'}), len(worse), worse))


if __name__ == '__main__':
    main()
