#!/bin/bash
#------------------------------------------------------------------------
# Self-test of the random numbers of the Lagrangian module (#225): the
# counter-based generator of src/shyfem/lagrange_random.f90 (module
# mod_lagrange_random, Threefry-4x32-20 keyed on seed, particle id, time
# step and draw index), compiled on its own with a small test program.
#
# Usage:  ./check_lgr_random.sh [NDRAW]      (NDRAW default 1000000)
#
# Checks (the first three are lgr_random_selftest of the module; its
# header gives the details and the limits):
#   1. the nine Threefry-4x32 test vectors of Random123 (13, 20 and 72
#      rounds; tests/kat_vectors of github.com/DEShawResearch/random123):
#      the output words exactly;
#   2. the conversions at the extreme words 0 and 2**32-1: the double and
#      the single precision value strictly inside (0,1);
#   3. five frozen values of lgr_rand_u and lgr_rand_r, exactly;
#   4. NDRAW draws along each key the model varies (ids, steps, draw
#      counts, seeds), as double and as single precision values: mean,
#      variance, lag-1 correlation and the chi-square of 100 bins, and the
#      correlation of the x and y draws of the random walk; limits five
#      standard deviations of each statistic for independent uniform
#      values (|mean-1/2| < 5 sqrt(1/(12 N)), |var-1/12| < 5 sqrt(1/(180
#      N)), |corr| < 5/sqrt(N), |chi-square-99| < 5 sqrt(198));
#   5. no "runtime error" from the undefined-behaviour sanitizer
#      (gfortran -fsanitize=undefined reports a signed integer overflow,
#      which the generator must never make), no run-time check message;
#   6. an independent Python implementation of Threefry-4x32-20 and of the
#      packing of the keys (below) gives bit for bit the values the
#      Fortran prints for 300 keys (negative and extreme values among
#      them), for lgr_random after lgr_random_set_seed/lgr_random_set_step
#      (the step key is the time in ms) and for the release stream
#      lgr_random_release (counted from 0 in each step).
#
# This test cannot be red on the commit before #225: the module does not
# exist there (the compile step fails).  Instead it was run on mutated
# copies of the module (2026-11-22), and each one failed: a rotation
# constant changed (10 -> 11: test vectors, frozen values), the step, the
# id or the draw index left out of the keys (frozen values, and the
# statistic of that key: variance 0, correlation 1), the high word of the
# step left out (frozen values, Python cross-check), the single precision
# value built from 24 bits instead of 23 (extremes: 1-2**-24 became 2),
# the release stream not counted, the step key in seconds instead of ms
# (Python cross-check).
#
# Needs gfortran and python3.  Works in a folder made with mktemp under
# ${TMPDIR:-/tmp}, removed at the end.  Prints "LGR RANDOM: PASS" or
# "LGR RANDOM: FAIL"; exit code 0 or 1.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
SRC="$HERE/../../../src/shyfem/lagrange_random.f90"
NDRAW="${1:-1000000}"
rc=0
fail() { echo "LGR RANDOM FAIL: $*"; rc=1; }

case "$NDRAW" in ''|*[!0-9]*) echo "usage: $0 [NDRAW]"; exit 2 ;; esac
for t in gfortran python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "LGR RANDOM: FAIL ($t is not on PATH)"; exit 1; }
done
[ -f "$SRC" ] || { echo "LGR RANDOM: FAIL (no $SRC)"; exit 1; }

W="$(mktemp -d "${TMPDIR:-/tmp}/lgr_random.XXXXXX")" || { echo "LGR RANDOM: FAIL (mktemp)"; exit 1; }
trap 'rm -rf "$W"' EXIT

cat > "$W/main.f90" <<'EOF'
program lgr_random_test

! runs lgr_random_selftest, then prints keys and the bits of the values for
! the Python cross-check of check_lgr_random.sh

use mod_lagrange_random
implicit none

integer :: nfail, ndraw, i, n, iseed, id, idraw, isite
integer(kind=8) :: istep, h
double precision :: u, atime
real :: r
character(len=32) :: arg

call get_command_argument(1, arg)
read(arg, *) ndraw
call lgr_random_selftest(ndraw, nfail)
write(6, '(a,i0)') 'SELFTEST nfail ', nfail

h = 20261122_8
do i = 1, 300
  call next(h); iseed = int(h) - 1073741824
  call next(h); id = int(h)
  call next(h); istep = (h - 1073741824_8) * 2147483_8
  call next(h); idraw = int(h)
  if( i == 1 ) then
    iseed = -2147483647 - 1; id = -1; istep = -huge(istep) - 1; idraw = -1
  else if( i == 2 ) then
    iseed = huge(iseed); id = huge(id); istep = huge(istep); idraw = huge(idraw)
  else if( i == 3 ) then
    iseed = 0; id = 0; istep = 0; idraw = 0
  end if
  u = lgr_rand_u(iseed, id, istep, idraw)
  r = lgr_rand_r(iseed, id, istep, idraw)
  write(6, '(a,i12,i12,i21,i12,1x,z16.16,1x,z8.8)') 'KEY', iseed, id, &
       istep, idraw, transfer(u, 0_8), transfer(r, 0)
end do

do i = 1, 20
  call next(h); iseed = int(h) - 1073741824
  call next(h); atime = 6.3e10_8 + dble(h) * 0.25d0 + 0.1d0
  call next(h); id = int(h)
  call next(h); isite = 1 + mod(int(h), 11)
  call next(h); n = mod(int(h), 1000)
  call lgr_random_set_seed(iseed)
  call lgr_random_set_step(atime)
  r = lgr_random(id, isite, n)
  write(6, '(a,i12,1x,z16.16,i12,i4,i6,1x,z8.8)') 'MOD', iseed, &
       transfer(atime, 0_8), id, isite, n, transfer(r, 0)
  do n = 0, 2
    r = lgr_random_release()
    write(6, '(a,i12,1x,z16.16,i4,1x,z8.8)') 'REL', iseed, &
         transfer(atime, 0_8), n, transfer(r, 0)
  end do
end do

contains

subroutine next(hh)
! Park-Miller step modulo 2**31-1 (products below 2**47)
integer(kind=8), intent(inout) :: hh
hh = modulo(48271_8 * hh, 2147483647_8)
end subroutine next

end program lgr_random_test
EOF

echo "=== compile $SRC with the test program (gfortran -fsanitize=undefined)"
FLAGS="-O2 -fcheck=all -ffpe-trap=invalid,zero,overflow -fsanitize=undefined"
if ! ( cd "$W" && gfortran $FLAGS -Wno-tabs "$SRC" main.f90 -o lgr_random_test > compile.log 2>&1 ); then
  tail -20 "$W/compile.log"
  echo "LGR RANDOM: FAIL (compile)"; exit 1
fi

echo "=== self-test with $NDRAW draws per statistic"
( cd "$W" && ./lgr_random_test "$NDRAW" > run.log 2>&1 )
trc=$?
grep 'lgr random:' "$W/run.log"
[ "$trc" = 0 ] || { tail -5 "$W/run.log"; fail "the test program exited with code $trc"; }
if grep -q 'runtime error\|Fortran runtime\|Program received signal' "$W/run.log"; then
  grep -m5 'runtime error\|Fortran runtime\|Program received signal' "$W/run.log" | sed 's/^/    /'
  fail "sanitizer or run-time check message (a signed overflow or an array bound)"
fi
nf="$(sed -n 's/^SELFTEST nfail \([0-9][0-9]*\)$/\1/p' "$W/run.log")"
if [ -z "$nf" ]; then fail "no result line of the self-test"
elif [ "$nf" != 0 ]; then fail "$nf checks of the self-test failed"
else echo "  self-test: every check ok"; fi

echo "=== independent Python implementation against the Fortran values"
python3 - "$W/run.log" <<'EOF' || fail "the Python cross-check found differences"
import struct, sys

M = 0xFFFFFFFF
ROT = [(10, 26), (11, 21), (13, 27), (23, 5), (6, 20), (17, 11), (25, 10), (18, 20)]

def rotl(x, r):
    return ((x << r) | (x >> (32 - r))) & M

def threefry(ctr, key, nr=20):
    ks = list(key) + [0x1BD11BDA ^ key[0] ^ key[1] ^ key[2] ^ key[3]]
    x = [(c + k) & M for c, k in zip(ctr, key)]
    for r in range(nr):
        a, b = ROT[r % 8]
        if r % 2 == 0:
            x[0] = (x[0] + x[1]) & M; x[1] = rotl(x[1], a) ^ x[0]
            x[2] = (x[2] + x[3]) & M; x[3] = rotl(x[3], b) ^ x[2]
        else:
            x[0] = (x[0] + x[3]) & M; x[3] = rotl(x[3], a) ^ x[0]
            x[2] = (x[2] + x[1]) & M; x[1] = rotl(x[1], b) ^ x[2]
        if r % 4 == 3:
            s = (r + 1) // 4
            for i in range(4):
                x[i] = (x[i] + ks[(s + i) % 5]) & M
            x[3] = (x[3] + s) & M
    return x

def words(seed, pid, step, idraw):
    st = step & 0xFFFFFFFFFFFFFFFF
    return threefry([st & M, st >> 32, idraw & M, 0], [seed & M, pid & M, 0, 0])

def ubits(w):
    k = (w[0] << 20) | (w[1] >> 12)
    return struct.unpack('<Q', struct.pack('<d', (2 * k + 1) / 2.0**53))[0]

def rbits(w):
    return struct.unpack('<I', struct.pack('<f', (2 * (w[0] >> 9) + 1) / 2.0**24))[0]

def index(site, n):
    return site * 2**24 + n % 2**24

def step_of(hexbits):
    atime = struct.unpack('<d', struct.pack('<Q', int(hexbits, 16)))[0]
    return int(atime * 1000.0 + 0.5)   # nint, positive times

nkey = nmod = nrel = bad = 0
for line in open(sys.argv[1]):
    f = line.split()
    if not f:
        continue
    if f[0] == 'KEY':
        seed, pid, step, idraw = map(int, f[1:5])
        w = words(seed, pid, step, idraw)
        ok = ubits(w) == int(f[5], 16) and rbits(w) == int(f[6], 16)
        nkey += 1
    elif f[0] == 'MOD':
        seed, pid, site, n = int(f[1]), int(f[3]), int(f[4]), int(f[5])
        w = words(seed, pid, step_of(f[2]), index(site, n))
        ok = rbits(w) == int(f[6], 16)
        nmod += 1
    elif f[0] == 'REL':
        seed, n = int(f[1]), int(f[3])
        w = words(seed, 0, step_of(f[2]), index(11, n))
        ok = rbits(w) == int(f[4], 16)
        nrel += 1
    else:
        continue
    if not ok:
        bad += 1
        if bad <= 5:
            print('  differs:', line.rstrip())
print('  keys %d (lgr_rand_u and lgr_rand_r), lgr_random %d, lgr_random_release %d: %d differ'
      % (nkey, nmod, nrel, bad))
sys.exit(0 if bad == 0 and nkey == 300 and nmod == 20 and nrel == 60 else 1)
EOF

if [ "$rc" = 0 ]; then echo "LGR RANDOM: PASS"; else echo "LGR RANDOM: FAIL"; fi
exit "$rc"
