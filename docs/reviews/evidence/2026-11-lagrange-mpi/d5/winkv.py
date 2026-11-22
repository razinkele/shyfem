#!/usr/bin/env python3
"""Replay setnod's winkv on several processes for a node partition: owner's full
ring sum plus the ghost contributions every other holder adds in phase 1 of
shympi_exchange_and_sum_2d_nodes.  Prints boundary nodes whose value reaches
winmax = 359.99 (classified inner), for a partition grd (node type = rank+1)."""
import sys, math, collections
grd, part = sys.argv[1:3]
nodes, elems = {}, {}
for l in open(grd):
    p = l.split()
    if p and p[0] == '1': nodes[int(p[1])] = (float(p[3]), float(p[4]))
    elif p and p[0] == '2': elems[int(p[1])] = tuple(int(x) for x in p[4:7])
rank = {}
for l in open(part):
    p = l.split()
    if p and p[0] == '1': rank[int(p[1])] = int(p[2]) - 1
def ang(e, k):
    a, b, c = elems[e]
    o = [n for n in (a, b, c) if n != k]
    x0, y0 = nodes[k]; x1, y1 = nodes[o[0]]; x2, y2 = nodes[o[1]]
    v1 = (x1-x0, y1-y0); v2 = (x2-x0, y2-y0)
    cs = (v1[0]*v2[0]+v1[1]*v2[1]) / math.hypot(*v1) / math.hypot(*v2)
    return math.degrees(math.acos(max(-1, min(1, cs))))
ring = collections.defaultdict(list)
for e, ks in elems.items():
    for k in ks: ring[k].append(e)
nbad = 0; nbnd = 0
for k in sorted(nodes):
    full = sum(ang(e, k) for e in ring[k])
    if full > 359.99: continue          # inner node serially
    nbnd += 1
    holders = collections.defaultdict(float)
    for e in ring[k]:
        for r in set(rank[n] for n in elems[e]):
            if r != rank[k]: holders[r] += ang(e, k)
    tot = full + sum(holders.values())
    if tot > 359.99:
        nbad += 1
        print('node %d owner %d full %.2f with ghost sums %.2f (others %s)'
              % (k, rank[k], full, tot, dict((r, round(v, 1)) for r, v in holders.items())))
print('boundary nodes', nbnd, 'classified inner on several processes', nbad)
