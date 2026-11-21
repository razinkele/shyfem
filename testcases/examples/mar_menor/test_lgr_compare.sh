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

def header(decoy):
    # arbitrary fake model header; the tool must not depend on its content
    out = rec(b'FAKEHDR1' * 3) + rec(struct.pack('<8i', *range(8)))
    if decoy:
        # a 4-byte record followed by a 16-byte record with iwhat = 0,
        # but no consistent block behind it
        out += rec(struct.pack('<i', 99))
        out += rec(struct.pack('<dii', 0.0, 1, 0))
        out += rec(b'junk')
    out += rec(struct.pack('<i', NCUST))
    return out

def particle(pid, x, y, z=-1.5, lb=1, ie=3, typ=1):
    r1 = struct.pack('<iidfi', pid, typ, 100.0 + pid, 0.5, ie)
    r2 = struct.pack('<fffif', x, y, z, lb, 0.25)
    r3 = struct.pack('<%df' % NCUST, *([0.5 * pid] * NCUST))
    return rec(r1) + rec(r2) + rec(r3)

def block(dtime, iwhat, parts):
    return rec(struct.pack('<dii', dtime, len(parts), iwhat)) + b''.join(
        particle(*p) for p in parts)

def build(path, shift_id=None, drop_id=None, reverse=False, decoy=False,
          nan_id=None, type_id=None, times=(0.0, 3600.0)):
    out = header(decoy)
    for dtime in times:
        active = [(i, 0.1 * i, 0.2 * i) for i in range(1, 9)]
        inserted = [(i, 0.1 * i, 0.2 * i, -1.5, 1, 3) for i in (1, 2, 3)]
        exited = [(9, 0.9, 1.8, -1.5, 1, 4)]
        active = [(i, x + 2e-5 if i == shift_id else x, y) for i, x, y in active]
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

if [ "$fail" -eq 0 ]; then echo "LGR COMPARE TEST: PASS"; exit 0; fi
echo "LGR COMPARE TEST: FAIL"; exit 1
