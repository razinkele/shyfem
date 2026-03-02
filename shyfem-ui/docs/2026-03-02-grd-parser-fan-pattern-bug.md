# GrdParser Fan-Pattern Bug — Findings & Fix

**Date:** 2026-03-02
**Commit:** `2c2e8a7`
**Files:** `shyfem_ui/services/parser_grd.py`, `tests/test_parser_grd.py`

## Symptom

Mesh visualization in the deck.gl map displayed a fan-shaped pattern radiating from a single point, overlaying the real mesh. Affected both Mar Menor and Curonian Lagoon grids.

## Root Cause

The Python `.grd` parser misinterpreted the SHYFEM element format.

### Correct format (confirmed from Fortran source `src/utils/generic/grd.f90:886`)

```
2 <id> <type> <nvert> <node1> <node2> ... [depth]
```

- `nvert` at position 4 (1-indexed) is the **vertex count** (3 for triangles, 4 for quads)
- Node IDs follow after `nvert`
- Optional depth value comes after the last node

Example from `MM_coarse.grd`:
```
2 1 1 3 334 828 335 7.442161
       ^               ^
       nvert=3          depth
```

### What the parser did wrong

The parser read `parts[3:]` as **all node IDs**, treating `nvert` as a node ID:

```python
# BUG: nvert (always 3 for triangles) becomes node ID 3
node_ids = []
for p in parts[3:]:
    node_ids.append(int(p))
```

Result: every triangle element got 4 nodes `[3, 334, 828, 335]` instead of `[334, 828, 335]`. Since node 3 appeared in every element, all triangles shared that vertex — creating the fan pattern.

The depth value `7.442161` was silently dropped because `int("7.442161")` raises `ValueError`.

### Same bug in line records

Line (boundary) records use the identical format:

```
3 <id> <type> <nvert> <node1> <node2> ...
```

The line parser also read `parts[3:]` as nodes, misinterpreting `nvert`.

## Fix

### 1. Element parser — read nvert, then nodes

```python
nvert = int(parts[3])
node_ids = [int(parts[4 + i]) for i in range(nvert)]
# Optional depth after the last node
depth_idx = 4 + nvert
if depth_idx < len(parts):
    depth = float(parts[depth_idx])
```

### 2. Line parser — read nvert, support multi-line continuation

Line records in real SHYFEM grids can have hundreds of nodes spanning multiple file lines:

```
3 16 2 13
 553 554 555 556 557 558 559 560 561 562
 563 564 553
```

The fix tracks a `pending_line` state. Continuation lines (where `parts[0] > 3`) append node IDs to the pending record until `nvert` nodes are collected.

### 3. Generate method — write nvert and depth

```python
# Before (wrong): "2 1 1 334 828 335"
# After (correct): "2 1 1 3 334 828 335 7.442161"
f"2 {elem.id} {elem.elem_type} {len(elem.nodes)} {nodes_str}{depth_str}"
```

### 4. Element dataclass — added depth field

```python
@dataclass
class Element:
    id: int
    elem_type: int
    nodes: list[int] = field(default_factory=list)
    depth: float | None = None  # NEW
```

## Verification

- Mar Menor grid: 1402 nodes, 2545 triangles, max 3 nodes per element, 0 warnings
- Parse → generate → reparse roundtrip preserves all data including depth
- 44 parser tests pass (14 new)

## How the bug was found

1. User reported "mesh visualised like a fan originated in one point"
2. Investigation checked whether it was a mesh generation or display bug
3. Compared the Fortran parser (`grd.f90:886`: `nvert=nint(f(4))`) with the Python parser
4. Confirmed `nvert` field was missing from the Python parser logic

## Key reference

The authoritative format definition is in `src/utils/generic/grd.f90`:

| Record | Format | Fortran reference |
|--------|--------|-------------------|
| Node | `1 id type x y [depth]` | line ~860 |
| Element | `2 id type nvert n1 n2 ... [depth]` | line ~886 |
| Line | `3 id type nvert n1 n2 ...` | line ~976 |
| Comment | `0 text...` | — |

`nvert` is always at field position 4 (1-indexed). For elements it is typically 3 (triangle) or 4 (quad). For lines it can be any positive integer, with nodes potentially spanning continuation lines.
