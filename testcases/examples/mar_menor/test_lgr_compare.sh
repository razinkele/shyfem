#!/bin/bash
# Self-test for lgr_compare.py: builds small synthetic .lgr.shy files in a
# temporary directory and checks exit codes and key output lines.
# Prints "LGR COMPARE TEST: PASS" or "FAIL"; exits 0 or 1.

set -u
here="$(cd "$(dirname "$0")" && pwd)" || exit 1
tool="$here/lgr_compare.py"
tmp="$(mktemp -d)" || exit 1
[ -n "$tmp" ] && [ -d "$tmp" ] || exit 1
trap '[ -n "$tmp" ] && { rm -f "$tmp"/*.lgr.shy "$tmp"/out.txt "$tmp"/gen.py; rmdir "$tmp"; }' EXIT
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
          real=False, tt_shift=None):
    # moves: {dtime: {id: (dx, ie, hl)}} shifts x of an active particle by
    # dx at that output and writes its element ie and its depth hl
    # tt_shift: {dtime: {id: dt}} adds dt to the time tt of that particle
    global CUR_TT
    out = header(decoy, real)
    for dtime in times:
        CUR_TT = (tt_shift or {}).get(dtime, {})
        active = [(i, 0.1 * i, 0.2 * i) for i in range(1, 9)]
        inserted = [(i, 0.1 * i, 0.2 * i, -1.5, 1, 3) for i in (1, 2, 3)]
        exited = [(9, 0.9, 1.8, -1.5, 1, 4)]
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
        out += block(dtime, -1, inserted)
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
with open(d + '/t1.lgr.shy', 'rb') as f:
    whole = f.read()
with open(d + '/t9_truncated.lgr.shy', 'wb') as f:
    f.write(whole[:-10])
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

# --dims: nel and nlv of the model header
check "dims of a model header" 0 "nkn 1402 nel 2545 nlv 19" "$t/t12_header.lgr.shy" --dims
check "dims of a file without a model header" 2 "" "$t/t1.lgr.shy" --dims

if [ "$fail" -eq 0 ]; then echo "LGR COMPARE TEST: PASS"; exit 0; fi
echo "LGR COMPARE TEST: FAIL"; exit 1
