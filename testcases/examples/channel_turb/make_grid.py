#!/usr/bin/env python3
"""Straight flat-bottom channel for the k-eps vs GOTM benchmark.

L x W = 20 km x 1 km, depth 10 m, 250 m triangles. Writes channel.grd and
prints the two open-boundary node lists (left = inflow, right = outflow),
each ordered counter-clockwise along the domain boundary.
"""
L, W, DX, H = 20000.0, 1000.0, 250.0, 10.0
nx, ny = int(L / DX) + 1, int(W / DX) + 1


def nid(i, j):
    return j * nx + i + 1


with open("channel.grd", "w") as f:
    f.write("\n")
    for j in range(ny):
        for i in range(nx):
            f.write(f"1 {nid(i, j)} 0 {i * DX:.1f} {j * DX:.1f} {H}\n")
    f.write("\n")
    e = 0
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)
            e += 1
            f.write(f"2 {e} 0 3 {a} {b} {c} {H}\n")
            e += 1
            f.write(f"2 {e} 0 3 {a} {c} {d} {H}\n")

inflow = [nid(0, j) for j in reversed(range(ny))]      # left edge, top -> bottom
outflow = [nid(nx - 1, j) for j in range(ny)]          # right edge, bottom -> top
mid = [nid(nx // 2, j) for j in range(ny)]
print("inflow ", *inflow)
print("outflow", *outflow)
print("mid-channel nodes", *mid, "| nx", nx, "ny", ny, "nodes", nx * ny, "elements", e)
