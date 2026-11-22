#!/usr/bin/env python3
"""d5_partition.py DESIGN METIS_NODE_GRD BASIN_GRD OUT_GRD

A given 4-domain partition of case B's mesh (testcases/examples/mar_menor,
GRID/MM_coarse.grd) for spec section 7, case 4: a particle leaving through
the open boundary from a mixed element held by a process that is not its
main owner (Task 6.1, ruling D5).  DESIGN is `first` (rejected at start-up,
kept as evidence) or `second` (the one run).

How a run takes it: `shypre -partition OUT_GRD MM_coarse.grd` stores the node
types of OUT_GRD as the partition in MM_coarse.bas; on 4 processes
handle_partition (src/utils/shympi/mpi_basin.f90) then uses it ("partitiones
contained in basin: 4 / using these partitiones...") instead of METIS.  A
serial run ignores it (shympi_setup returns at once).

Start of both designs: the METIS partition the model makes for this mesh on 4
processes, METIS_NODE_GRD = GRID/MM_coarse.4.node.grd (tracked; node type =
rank + 1, the same owners as the 4-process run of case B writes in
partition.4.node.grd).  In the serial run 568 of the 595 particles leave
through the open sides between nodes 163 and 177; METIS puts those nodes and
the interior nodes behind them on rank 2, so every exit element is an inner
element of rank 2.  Main owner of a mixed element (id_elem(1,ie), adjust_indices
in mpi_basin.f90): the rank with two of its three nodes (three ranks: the
owner of the lowest node).  A case-4 element is an element with an open side
whose two end nodes are on rank C = 1 and whose interior node is on rank
R = 2: main owner C, held by R, which carries the particles of the sea part
behind the boundary.

first:  the open-boundary nodes 158..177 go to rank 1 (which holds the
        open-boundary nodes 120..157 next to them).  Every element with an
        open side between two of them becomes a case-4 element.  REJECTED at
        start-up: setnod stops ("error stop setnod: open boundary node",
        external node 158), see below.
second: the same nodes and every interior node next to one of them go to
        rank 1; then the interior nodes of the exit elements are handed back
        to rank 2 one at a time (most serial exits first) and each is kept
        only if the start-up classification below stays as with METIS (the
        same four nodes over the limit, and no boundary node within MARGIN
        degrees of it that is not so with METIS: node 42, 358.38).

The start-up classification (setnod, src/utils/shyutilmpi/topo_update.f90):
on several processes every process adds the angles of all its local elements
at their nodes (winkv), then shympi_exchange_and_sum_2d_nodes adds the values
of the ghost copies to the owner, although the owner already holds every
element around its own node; a node whose sum exceeds winmax = 359.99 is an
inner node, and an open-boundary node classified inner stops the run.  The
replay here computes that sum for every node (full ring + the contributions
of every other holder; angles from the coordinates of BASIN_GRD) and lists
the boundary nodes that pass the limit.  With METIS on 4 processes it lists
the material-boundary nodes 10, 16, 25, 32 (a prediction: no run shows it,
since a material-boundary node classified inner does not stop the run).

OUT_GRD: the nodes of BASIN_GRD (same numbers, order and coordinates) with
node type = rank + 1, and its elements with type 0 (no element partition).
"""
import collections
import math
import sys

C, R = 1, 2                  # rank taking the boundary nodes, rank behind
MOVED = range(158, 178)      # open-boundary nodes 158..177
OPEN = range(85, 178)        # $bound1 of mm_lgr_b.str
WINMAX = 359.99
MARGIN = 5.0                 # degrees below WINMAX for every other node
# interior nodes of the serial exit elements at nodes 163..177, by exits
# (serial dump of case B at 172,800 s: element, exits)
EXIT_INTERIOR = [400, 682, 994, 1008, 700, 416, 1018, 672, 389, 395, 392,
                 394]


def read_grd(path):
    nodes, elems, order = {}, {}, []
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == '1':
            nodes[int(p[1])] = (int(p[2]), p[3], p[4])
            order.append(('n', int(p[1])))
        elif p[0] == '2':
            elems[int(p[1])] = tuple(int(x) for x in p[4:4 + int(p[3])])
            order.append(('e', int(p[1])))
    return nodes, elems, order


class Mesh:
    def __init__(self, bnodes, belems):
        self.xy = {k: (float(x), float(y)) for k, (_, x, y) in bnodes.items()}
        self.elems = belems
        self.ring = collections.defaultdict(list)
        for e, ks in belems.items():
            for k in ks:
                self.ring[k].append(e)
        self.angle = {}
        for e, ks in belems.items():
            for k in ks:
                o = [n for n in ks if n != k]
                x0, y0 = self.xy[k]
                v1 = (self.xy[o[0]][0] - x0, self.xy[o[0]][1] - y0)
                v2 = (self.xy[o[1]][0] - x0, self.xy[o[1]][1] - y0)
                cs = (v1[0] * v2[0] + v1[1] * v2[1]) / \
                    (math.hypot(*v1) * math.hypot(*v2))
                self.angle[(e, k)] = math.degrees(math.acos(max(-1., min(1., cs))))
        self.full = {k: sum(self.angle[(e, k)] for e in self.ring[k])
                     for k in self.xy}

    def replay(self, rank):
        """setnod's sum on several processes for boundary nodes: {node: sum}"""
        out = {}
        for k in self.xy:
            if self.full[k] > WINMAX:
                continue                  # inner node in the serial run too
            tot = self.full[k]
            for r in set(rank.values()):
                if r == rank[k]:
                    continue
                tot += sum(self.angle[(e, k)] for e in self.ring[k]
                           if any(rank[n] == r for n in self.elems[e]))
            out[k] = tot
        return out


def classify(mesh, rank):
    s = mesh.replay(rank)
    bad = sorted(k for k, v in s.items() if v > WINMAX)
    close = sorted(k for k, v in s.items() if WINMAX - MARGIN < v <= WINMAX)
    return bad, close, s


def case4_elements(mesh, rank):
    """elements with an open side between two nodes on C and the third on R"""
    out = []
    for e, ks in mesh.elems.items():
        ob = [k for k in ks if k in OPEN]
        if len(ob) != 2:
            continue
        inner = [k for k in ks if k not in OPEN]
        if len(inner) != 1:
            continue
        if rank[ob[0]] == C and rank[ob[1]] == C and rank[inner[0]] == R:
            out.append(e)
    return sorted(out)


def main():
    if len(sys.argv) != 5 or sys.argv[1] not in ('first', 'second'):
        sys.exit(__doc__)
    design, metis, basin, out = sys.argv[1:5]
    mnodes, _, _ = read_grd(metis)
    bnodes, belems, border = read_grd(basin)
    if set(mnodes) != set(bnodes):
        sys.exit('node numbers of %s and %s differ' % (metis, basin))
    mesh = Mesh(bnodes, belems)
    metis_rank = {k: t - 1 for k, (t, _, _) in mnodes.items()}
    bad0, close0, s0 = classify(mesh, metis_rank)
    print('METIS: boundary nodes over the limit on 4 processes (replay):', bad0)
    print('METIS: boundary nodes within %.0f degrees of the limit: %s'
          % (MARGIN, ['%d:%.2f' % (n, s0[n]) for n in close0]))

    rank = dict(metis_rank)
    for k in MOVED:
        if rank[k] != R:
            sys.exit('node %d is on rank %d in %s, expected %d'
                     % (k, rank[k], metis, R))
        rank[k] = C
    if design == 'second':
        nbr = set()
        for k in MOVED:
            for e in mesh.ring[k]:
                nbr.update(n for n in mesh.elems[e] if n not in OPEN)
        for k in nbr:
            rank[k] = C
        print('second: interior nodes next to 158..177 moved to rank %d: %s'
              % (C, sorted(nbr)))
        bad, close, _ = classify(mesh, rank)
        if bad != bad0 or not set(close) <= set(close0):
            sys.exit('second: start already fails the replay: %s %s' % (bad, close))
        for k in EXIT_INTERIOR:
            if k not in nbr:
                sys.exit('exit interior node %d is not next to 158..177' % k)
            rank[k] = R
            bad, close, s = classify(mesh, rank)
            keep = (bad == bad0 and set(close) <= set(close0))
            print('  hand node %4d back to rank %d: %s (over the limit %s,'
                  ' within %.0f degrees of it %s)'
                  % (k, R, 'kept' if keep else 'undone', bad, MARGIN,
                     ['%d:%.2f' % (n, s[n]) for n in close]))
            if not keep:
                rank[k] = C

    bad, close, s = classify(mesh, rank)
    print('%s: boundary nodes over the limit (replay): %s' % (design, bad))
    print('%s: boundary nodes within %.0f degrees of the limit: %s'
          % (design, MARGIN, ['%d:%.2f' % (n, s[n]) for n in close]))
    worst = max((v for k, v in s.items() if k not in bad), default=0.)
    print('%s: largest sum of a boundary node below the limit: %.2f' % (design, worst))
    c4 = case4_elements(mesh, rank)
    print('%s: case-4 elements (open side on rank %d, interior node on rank %d):'
          ' %d %s' % (design, C, R, len(c4), c4))
    sizes = [sum(1 for r in rank.values() if r == i) for i in range(4)]
    print('%s: nodes per rank: %s' % (design, sizes))
    with open(out, 'w') as fh:
        fh.write('0 partition of MM_coarse for 4 processes (d5_partition.py %s):'
                 ' node type = rank + 1\n\n' % design)
        for what, n in border:
            if what == 'n':
                _, x, y = bnodes[n]
                fh.write('1 %d %d %s %s\n' % (n, rank[n] + 1, x, y))
            else:
                ks = belems[n]
                fh.write('2 %d 0 %d %s\n' % (n, len(ks), ' '.join(map(str, ks))))
    print('written', out)


if __name__ == '__main__':
    main()
