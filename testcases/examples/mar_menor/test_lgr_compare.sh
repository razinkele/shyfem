#!/bin/bash
# Self-test for lgr_compare.py: builds small synthetic .lgr.shy files in a
# temporary directory and checks exit codes and key output lines.
# Prints "LGR COMPARE TEST: PASS" or "FAIL"; exits 0 or 1.

set -u
here="$(cd "$(dirname "$0")" && pwd)" || exit 1
tool="$here/lgr_compare.py"
tmp="$(mktemp -d)" || exit 1
[ -n "$tmp" ] && [ -d "$tmp" ] || exit 1
trap '[ -n "$tmp" ] && { rm -rf "$tmp/lg"; rm -f "$tmp"/*.lgr.shy "$tmp"/out.txt "$tmp"/gen.py; rmdir "$tmp"; }' EXIT
fail=0

cat > "$tmp/gen.py" <<'PY'
import struct, sys
d = sys.argv[1]
NCUST = 2

def rec(payload):
    n = struct.pack('<i', len(payload))
    return n + payload + n

def header(decoy, real=False):
    # arbitrary fake model header; the tool must not depend on its content
    # (real: the first three records of a model header, for --dims)
    if real:
        out = rec(struct.pack('<ii', 1617, 15)) + rec(struct.pack('<i', 3))
        out += rec(struct.pack('<5i', 1402, 2545, 1, 19, 1))
    else:
        out = rec(b'FAKEHDR1' * 3) + rec(struct.pack('<8i', *range(8)))
    if decoy:
        # a 4-byte record followed by a 16-byte record with iwhat = 0,
        # but no consistent block behind it
        out += rec(struct.pack('<i', 99))
        out += rec(struct.pack('<dii', 0.0, 1, 0))
        out += rec(b'junk')
    out += rec(struct.pack('<i', NCUST))
    return out

CUR_TT = {}   # tt shift per id at the output being built (build's tt_shift)

def particle(pid, x, y, z=-1.5, lb=1, ie=3, typ=1, hl=0.25):
    r1 = struct.pack('<iidfi', pid, typ, 100.0 + pid + CUR_TT.get(pid, 0.0), 0.5, ie)
    r2 = struct.pack('<fffif', x, y, z, lb, hl)
    r3 = struct.pack('<%df' % NCUST, *([0.5 * pid] * NCUST))
    return rec(r1) + rec(r2) + rec(r3)

def block(dtime, iwhat, parts):
    return rec(struct.pack('<dii', dtime, len(parts), iwhat)) + b''.join(
        particle(*p) for p in parts)

def build(path, shift_id=None, drop_id=None, reverse=False, decoy=False,
          nan_id=None, type_id=None, times=(0.0, 3600.0), moves=None,
          real=False, tt_shift=None, ins_mod=None, ins_ie=3, exit_ie=4,
          exit_id=9):
    # moves: {dtime: {id: (dx, ie, hl)}} shifts x of an active particle by
    # dx at that output and writes its element ie and its depth hl
    # tt_shift: {dtime: {id: dt}} adds dt to the time tt of that particle
    # (active and exited blocks)
    # ins_mod: {dtime: {id: (dx, ie, hl, dtt)}} changes an inserted particle:
    # x by dx, its element, its depth hl, its time tt by dtt
    # ins_ie, exit_ie: the element of every inserted / the exited particle
    # exit_id: the id of the exited particle (ids 1..9 without it are active)
    global CUR_TT
    out = header(decoy, real)
    for dtime in times:
        CUR_TT = (tt_shift or {}).get(dtime, {})
        active = [(i, 0.1 * i, 0.2 * i) for i in range(1, 10) if i != exit_id]
        inserted = [(i, 0.1 * i, 0.2 * i, -1.5, 1, ins_ie) for i in (1, 2, 3)]
        exited = [(9, 0.9, 1.8, -1.5, 1, exit_ie)] if exit_id == 9 else \
            [(exit_id, 0.1 * exit_id, 0.2 * exit_id, -1.5, 1, exit_ie)]
        im = (ins_mod or {}).get(dtime, {})
        inserted = [(i, x + im[i][0], y, -1.5, 1, im[i][1], 1, im[i][2])
                    if i in im else (i, x, y, z, lb, ie)
                    for i, x, y, z, lb, ie in inserted]
        ins_tt = {i: im[i][3] for i in im}
        if moves is not None:
            mv = moves.get(dtime, {})
            active = [(i, x + mv[i][0], y, -1.5, 1, mv[i][1], 1, mv[i][2])
                      if i in mv else (i, x, y) for i, x, y in active]
        active = [(i, x + 2e-5 if i == shift_id else x, y) + tuple(rest)
                  for i, x, y, *rest in active]
        if nan_id is not None:
            active = [(i, float('nan') if i == nan_id else x, y) for i, x, y in active]
        if type_id is not None:
            active = [(i, x, y, -1.5, 1, 3, 2 if i == type_id else 1) for i, x, y in active]
        if drop_id is not None:
            active = [p for p in active if p[0] != drop_id]
        if reverse:
            active.reverse()
            inserted.reverse()
        out += block(dtime, 0, active)
        CUR_TT = ins_tt
        out += block(dtime, -1, inserted)
        CUR_TT = (tt_shift or {}).get(dtime, {})
        out += block(dtime, 1, exited)
    with open(path, 'wb') as f:
        f.write(out)

build(d + '/t1.lgr.shy')
build(d + '/t2_shifted.lgr.shy', shift_id=5)
build(d + '/t3_missing_id.lgr.shy', drop_id=7)
build(d + '/t4_reordered.lgr.shy', reverse=True)
build(d + '/t5_decoy.lgr.shy', decoy=True)
build(d + '/t6_one_time.lgr.shy', times=(0.0,))
build(d + '/t7_nan.lgr.shy', nan_id=4)
build(d + '/t8_type.lgr.shy', type_id=6)
# floors: at the last output ids 2 and 5 move 3e-5 in their element, id 7
# moves 5e-5 into element 4 with another depth; at the first output id 4
# moves 8e-5 (the largest distance at any output)
build(d + '/t10_floor.lgr.shy', moves={0.0: {4: (8e-5, 3, 0.25)},
      3600.0: {2: (3e-5, 3, 0.25), 5: (3e-5, 3, 0.25), 7: (5e-5, 4, 0.75)}})
# id 2 keeps its element at the last output but its depth hl differs
build(d + '/t11_hl.lgr.shy', moves={3600.0: {2: (3e-5, 3, 0.75)}})
build(d + '/t12_header.lgr.shy', real=True)
# tt: id 5 at the first output; ids 5, 6 (active) and 9 (exited) at the last
build(d + '/t13_tt.lgr.shy', tt_shift={0.0: {5: 300.0}, 3600.0: {5: 300.0, 6: 300.0, 9: 300.0}})
# an active particle at distance 0 whose element differs (id 5, first output)
build(d + '/t14_ie0.lgr.shy', moves={0.0: {5: (0.0, 7, 0.25)}})
# local element numbers beyond the basin in the inserted / the exited block
build(d + '/t15_ins_ie.lgr.shy', ins_ie=9)
build(d + '/t16_exit_ie.lgr.shy', exit_ie=9)
# inserted block: only tt differs (id 2), only hl differs by less than
# --tol-hl (id 3), only x differs by 3e-5 (id 1), only the element (id 2)
build(d + '/t17_ins_tt.lgr.shy', ins_mod={0.0: {2: (0.0, 3, 0.25, 300.0)}})
build(d + '/t18_ins_hl.lgr.shy', ins_mod={3600.0: {3: (0.0, 3, 0.25005, 0.0)}})
build(d + '/t21_ins_hl_big.lgr.shy', ins_mod={3600.0: {3: (0.0, 3, 0.2503, 0.0)}})
build(d + '/t19_ins_x.lgr.shy', ins_mod={3600.0: {1: (3e-5, 3, 0.25, 0.0)}})
build(d + '/t20_ins_ie.lgr.shy', ins_mod={3600.0: {2: (0.0, 5, 0.25, 0.0)}})
# two output times whose three blocks hold no particle: nothing to compare
# (a file without any output time is a read error: find_particle_start)
out = header(False)
for dtime in (0.0, 3600.0):
    for iwhat in (0, -1, 1):
        out += block(dtime, iwhat, [])
with open(d + '/t22_empty.lgr.shy', 'wb') as f:
    f.write(out)
with open(d + '/t1.lgr.shy', 'rb') as f:
    whole = f.read()
with open(d + '/t9_truncated.lgr.shy', 'wb') as f:
    f.write(whole[:-10])
# id 8 has exited and id 9 is active (t1: the other way round): the counts
# per block and the set of all ids are those of t1
build(d + '/t23_block_swap.lgr.shy', exit_id=8)
# t=3600.0 written twice: first with id 5 moved (t2_shifted's output), then
# t1's own output; t1 and t2_shifted share the header and the block sizes
with open(d + '/t2_shifted.lgr.shy', 'rb') as f:
    shifted = f.read()
hsize = len(header(False))
osize = (len(whole) - hsize) // 2
with open(d + '/t24_time_twice.lgr.shy', 'wb') as f:
    f.write(whole[:hsize + osize] + shifted[hsize + osize:] + whole[hsize + osize:])
PY
python3 "$tmp/gen.py" "$tmp" || { echo "LGR COMPARE TEST: FAIL (generator)"; exit 1; }

# check DESCRIPTION EXPECTED_EXIT [GREP_REGEX] -- command...
check() {
    local desc="$1" want="$2" rx="$3"; shift 3
    python3 "$tool" "$@" > "$tmp/out.txt" 2>&1
    local got=$?
    if [ "$got" -ne "$want" ]; then
        echo "FAIL: $desc: exit $got, expected $want"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    if [ -n "$rx" ] && ! grep -Ezq -- "$rx" "$tmp/out.txt"; then
        echo "FAIL: $desc: output lacks /$rx/"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    echo "ok: $desc"
}

t="$tmp"
check "identical files, pos" 0 "t=0.0 active +nA=8 nB=8 .*max.dx.=0.0000e\+00" "$t/t1.lgr.shy" "$t/t1.lgr.shy" --mode pos --tol 1e-5
check "shifted id 5 is reported with its difference" 1 "id 5.*(1\.99|2\.00)[0-9]*e-05" \
    "$t/t1.lgr.shy" "$t/t2_shifted.lgr.shy" --mode pos --tol 1e-5
check "missing id 7, ids mode" 1 "only in A: 7" \
    "$t/t1.lgr.shy" "$t/t3_missing_id.lgr.shy" --mode ids
check "reordered particles match by id, tol 0" 0 "" \
    "$t/t1.lgr.shy" "$t/t4_reordered.lgr.shy" --mode pos --tol 0
check "NaN position in one file" 1 "id 4 differs" \
    "$t/t1.lgr.shy" "$t/t7_nan.lgr.shy" --mode pos --tol 1e-5
check "type differs for one particle" 1 "id 6 differs \(type 1/2\)" \
    "$t/t1.lgr.shy" "$t/t8_type.lgr.shy" --mode pos --tol 0
check "output time present in one file only" 1 "t=3600.0 only in A" \
    "$t/t1.lgr.shy" "$t/t6_one_time.lgr.shy" --mode ids
check "truncated file is a read error" 2 "" "$t/t9_truncated.lgr.shy" "$t/t1.lgr.shy" --mode ids
check "no particle at any output, ids mode: nothing compared" 1 "nothing compared: 2 output times in both files, no particle in them.*LGR COMPARE: FAIL" \
    "$t/t22_empty.lgr.shy" "$t/t22_empty.lgr.shy" --mode ids --same-counts
check "no particle at any output, pos mode: nothing compared" 1 "nothing compared: 2 output times in both files, no particle in them.*LGR COMPARE: FAIL" \
    "$t/t22_empty.lgr.shy" "$t/t22_empty.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 0 --max-largest 0
check "particles in one file only: compared, and they differ" 1 "only in A: 1,2,3,4,5,6,7,8" \
    "$t/t1.lgr.shy" "$t/t22_empty.lgr.shy" --mode ids
check "summary of one file" 0 "output times: 2.*first output t=0.0: active=8 inserted=3 exited=1; active ids 1..8.*last output t=3600.0: active=8 inserted=3 exited=1" \
    "$t/t1.lgr.shy" --summary
check "decoy 4-byte record in the header" 0 "nA=8 nB=8" \
    "$t/t1.lgr.shy" "$t/t5_decoy.lgr.shy" --mode pos --tol 0

# floors of --mode pos (--max-beyond-last, --max-largest)
check "moved particles fail without the floor options" 1 "id 2 differs \(position\)" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5
check "moved particles within both floors" 0 "floor: particles beyond --tol 1e-05 at the last output both files share \(t=3600.0\): 3 <= 3: ok.*floor: largest distance at any output \(t=0.0\): [78][.0-9]*e-05 <= 9e-05: ok" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 3 --max-largest 9e-5
check "hl of a pair in another element is not gated under the floors" 0 "t=3600.0 active .*beyond tol 3, hl not gated \(ie differs\) 1" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 3 --max-largest 9e-5
check "count floor exceeded" 1 "at the last output both files share \(t=3600.0\): 3 > 2: FAIL" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 2 --max-largest 9e-5
check "distance floor exceeded" 1 "largest distance at any output \(t=0.0\): [78][.0-9]*e-05 > 7e-05: FAIL" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 3 --max-largest 7e-5
check "distance floor alone" 0 "largest distance at any output" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-largest 9e-5
check "hl differs in the same element under the floors" 1 "id 2 differs \(hl 0.25/0.75\)" \
    "$t/t1.lgr.shy" "$t/t11_hl.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1
check "NaN position fails under the floors" 1 "id 4 differs \(position NaN\)" \
    "$t/t1.lgr.shy" "$t/t7_nan.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 100 --max-largest 1
check "missing id fails under the floors" 1 "only in A: 7" \
    "$t/t1.lgr.shy" "$t/t3_missing_id.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 100 --max-largest 1
check "floor options need --mode pos" 2 "" \
    "$t/t1.lgr.shy" "$t/t1.lgr.shy" --mode ids --max-largest 1

# --max-tt-differ: particles whose time tt differs, against a floor
check "tt differs, exact by default" 1 "id 5 differs \(tt 105.0/405.0\)" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 0
check "tt differs within the floor, counted per output" 0 "t=0.0 active .*, tt differs 1.*t=3600.0 active .*, tt differs 2.*t=3600.0 exited .*, tt differs 1.*tt: particles whose tt differs \(any output, any block\): 3 <= 3: ok" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 0 --max-tt-differ 3
check "tt floor exceeded" 1 "tt: particles whose tt differs \(any output, any block\): 3 > 2: FAIL" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 0 --max-tt-differ 2
check "tt floor together with the position floors" 0 "3 <= 3: ok" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 0 --max-largest 0 --max-tt-differ 3
check "tt floor needs --mode pos" 2 "" \
    "$t/t1.lgr.shy" "$t/t1.lgr.shy" --mode ids --max-tt-differ 1

# a differing tt within the floor is listed with its particle
check "tt within the floor: the particle line is printed" 0 "id 5: tt 105.0/405.0" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 0 --max-tt-differ 3
check "tt within the floor and the position floors: line printed" 0 "id 6: tt 106.0/406.0" \
    "$t/t1.lgr.shy" "$t/t13_tt.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 0 --max-largest 0 --max-tt-differ 3

# global elements: a pair at distance 0 with another element fails
check "distance 0, another element, no floors" 1 "id 5 differs \(ie 3/7\).*ie differs at distance 0 .*: 1" \
    "$t/t1.lgr.shy" "$t/t14_ie0.lgr.shy" --mode pos --tol 1e-5
check "distance 0, another element, under the floors" 1 "id 5 differs \(ie 3/7\)" \
    "$t/t1.lgr.shy" "$t/t14_ie0.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 3
check "distance 0, another element: the total is printed" 1 "ie: pairs at distance 0 with another ie \(any output, any block\): 1: FAIL" \
    "$t/t1.lgr.shy" "$t/t14_ie0.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1
check "no such pair: the total is 0" 0 "ie: pairs at distance 0 with another ie \(any output, any block\): 0: ok" \
    "$t/t1.lgr.shy" "$t/t10_floor.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 3 --max-largest 9e-5
check "local element numbers in the inserted block" 1 "B inserted id 1: ie=9 outside 1..6" \
    "$t/t1.lgr.shy" "$t/t15_ins_ie.lgr.shy" --mode ids --nel 6
check "local element numbers in the exited block" 1 "B exited id 9: ie=9 outside 1..6" \
    "$t/t1.lgr.shy" "$t/t16_exit_ie.lgr.shy" --mode ids --nel 6
check "element numbers in range in every block" 0 "" \
    "$t/t1.lgr.shy" "$t/t1.lgr.shy" --mode ids --nel 6 --nlv 3

# the inserted block holds fixed release data: exact, whatever the floors say
check "inserted block: only tt differs, tt floor 5" 1 "id 2 differs \(.*tt 102.0/402.0" \
    "$t/t1.lgr.shy" "$t/t17_ins_tt.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block: only hl differs, above --tol-hl" 1 "id 3 differs \(hl 0.25/0.250[23][0-9]*" \
    "$t/t1.lgr.shy" "$t/t21_ins_hl_big.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block: only hl differs, below --tol-hl" 0 "inserted block: pairs that differ \(any output\): 0: ok" \
    "$t/t1.lgr.shy" "$t/t18_ins_hl.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block: only x differs, within the floors" 1 "id 1 differs \(position\)" \
    "$t/t1.lgr.shy" "$t/t19_ins_x.lgr.shy" --mode pos --tol 1e-4 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block: only the element differs" 1 "id 2 differs \(ie 3/5\)" \
    "$t/t1.lgr.shy" "$t/t20_ins_ie.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block: the total is printed" 1 "inserted block: pairs that differ \(any output\): 1: FAIL" \
    "$t/t1.lgr.shy" "$t/t17_ins_tt.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5
check "inserted block identical: the total is 0" 0 "inserted block: pairs that differ \(any output\): 0: ok" \
    "$t/t1.lgr.shy" "$t/t4_reordered.lgr.shy" --mode pos --tol 1e-5 --max-beyond-last 10 --max-largest 1 --max-tt-differ 5

# ids mode compares the ids of each block, not only all ids and the counts
check "ids mode: an active and an exited particle swap blocks" 1 "t=0.0 active +nA=8 nB=8 only in A: 8 only in B: 9.*t=0.0 exited +nA=1 nB=1 only in A: 9 only in B: 8.*LGR COMPARE: FAIL" \
    "$t/t1.lgr.shy" "$t/t23_block_swap.lgr.shy" --mode ids --same-counts --nel 6 --nlv 3
check "ids mode: the same ids in every block" 0 "t=3600.0 exited +nA=1 nB=1.*LGR COMPARE: PASS" \
    "$t/t1.lgr.shy" "$t/t4_reordered.lgr.shy" --mode ids --same-counts --nel 6 --nlv 3

# an output time written twice in one file is a read error (the format
# writes each output time once), whichever copy would match
check "an output time twice in file A, pos mode" 2 "t24_time_twice.lgr.shy: output time 3600.0 is written twice \(outputs 2 and 3\)" \
    "$t/t24_time_twice.lgr.shy" "$t/t1.lgr.shy" --mode pos --tol 1e-5
check "an output time twice in file B, ids mode" 2 "output time 3600.0 is written twice" \
    "$t/t1.lgr.shy" "$t/t24_time_twice.lgr.shy" --mode ids --same-counts
check "an output time twice, summary" 2 "output time 3600.0 is written twice" \
    "$t/t24_time_twice.lgr.shy" --summary

# --dims: nel and nlv of the model header
check "dims of a model header" 0 "nkn 1402 nel 2545 nlv 19" "$t/t12_header.lgr.shy" --dims
check "dims of a file without a model header" 2 "" "$t/t1.lgr.shy" --dims

# lgr_lgmean_compare.py: runs are folders holding lgrelab.out and the
# lagrange_mean_traj.T files (a file is run through lgrelab, not available here)
lgtool="$here/lgr_lgmean_compare.py"
lgcheck() {
    local desc="$1" want="$2" rx="$3"; shift 3
    python3 "$lgtool" "$@" > "$tmp/out.txt" 2>&1
    local got=$?
    if [ "$got" -ne "$want" ]; then
        echo "FAIL: $desc: exit $got, expected $want"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    if [ -n "$rx" ] && ! grep -Ezq -- "$rx" "$tmp/out.txt"; then
        echo "FAIL: $desc: output lacks /$rx/"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    if grep -q Traceback "$tmp/out.txt"; then
        echo "FAIL: $desc: traceback in the output"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    echo "ok: $desc"
}
# mklg NAME X [TABLE_SUFFIX]: a run with one type file; X is the x column
mklg() {
    local d="$tmp/lg/$1"
    mkdir -p "$d"
    printf '    1  2009-01-01::01:00:00       145       145         0         0         1%s\n' "${3:-}" > "$d/lgrelab.out"
    if [ "$2" != none ]; then
        printf '2009-01-01::01:00:00 %s    37.68299     2.766     0.045     0.000     0.000\n' "$2" > "$d/lagrange_mean_traj.1"
    fi
}
# mklg_wide NAME V: as mklg, with a second output whose row has one more
# column than the first, V its value (every run alike, so the runs agree on
# the shape)
mklg_wide() {
    mklg "$1" -0.77963
    printf '2009-01-01::02:00:00 -0.77963    37.68299     2.766     0.045     0.000     0.000 %s\n' "$2" >> "$tmp/lg/$1/lagrange_mean_traj.1"
}
mkdir -p "$tmp/lg" || exit 1
for n in serial mpi base p1 p2 p3 p4 p5 p6; do mklg "$n" -0.77963; done
for n in serial base p1 p2 p3 p4 p5 p6; do mklg_wide "w_$n" 0.000; done
mklg_wide w_mpi nan
mklg nofiles none
mklg nan nan
mklg inf inf
mklg other_table -0.77963 "0"
g="$tmp/lg"
lgcheck "lgmean: six perturbed runs, as told by default" 0 "LGMEAN COMPARE: PASS" \
    "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/p6"
lgcheck "lgmean: five perturbed runs when six are required" 1 "5 perturbed runs.* 6 .*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5"
lgcheck "lgmean: seven perturbed runs when six are required" 1 "7 perturbed runs.* 6 .*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/p6" "$g/p6"
lgcheck "lgmean: --perturbed 2 takes two runs" 0 "LGMEAN COMPARE: PASS" \
    --perturbed 2 "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2"
lgcheck "lgmean: --perturbed 2 with three runs" 1 "3 perturbed runs.* 2 .*LGMEAN COMPARE: FAIL" \
    --perturbed 2 "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2" "$g/p3"
lgcheck "lgmean: no trajectory files at all" 1 "no lagrange_mean_traj.*LGMEAN COMPARE: FAIL" \
    "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles" "$g/nofiles"
lgcheck "lgmean: a NaN value is a clean failure" 1 "non-finite.*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/nan" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/p6"
lgcheck "lgmean: a NaN in a perturbed run is a clean failure" 1 "non-finite.*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/mpi" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/nan"
lgcheck "lgmean: an infinite value is a clean failure" 1 "non-finite.*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/inf" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/p6"
lgcheck "lgmean: an unequal particle table" 1 "particle table differs.*LGMEAN COMPARE: FAIL" \
    "$g/serial" "$g/other_table" "$g/base" "$g/p1" "$g/p2" "$g/p3" "$g/p4" "$g/p5" "$g/p6"
lgcheck "lgmean: a row with another number of columns is an input error" 2 "lagrange_mean_traj.1: line 2 has 8 columns, line 1 has 7" \
    "$g/w_serial" "$g/w_mpi" "$g/w_base" "$g/w_p1" "$g/w_p2" "$g/w_p3" "$g/w_p4" "$g/w_p5" "$g/w_p6"
python3 "$lgtool" --selftest > "$tmp/out.txt" 2>&1
if [ $? -eq 0 ] && grep -q "LGMEAN SELFTEST: PASS" "$tmp/out.txt"; then
    echo "ok: lgmean selftest"
else
    echo "FAIL: lgmean selftest"; sed 's/^/    /' "$tmp/out.txt"; fail=1
fi

if [ "$fail" -eq 0 ]; then echo "LGR COMPARE TEST: PASS"; exit 0; fi
echo "LGR COMPARE TEST: FAIL"; exit 1
