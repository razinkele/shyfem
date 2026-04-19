#!/usr/bin/env python3
"""Subroutine-scoped `implicit none` compliance check for SHYFEM.

Exits 0 if every subroutine in the watched directories either declares
`implicit none` itself or is contained in a module that does.  Exits 1
with a list of offenders otherwise.

Honors Fortran's module-level implicit-none inheritance (contained
procedures inherit the statement from the enclosing module).

Usage:
    check_implicit_none.py [--max-violations N] DIR [DIR ...]
"""
import argparse
import os
import re
import sys


def scan_file(path):
    """Yield (line_no, subroutine_name) for each non-compliant sub."""
    try:
        src = open(path, errors="ignore").read()
    except OSError:
        return
    lines = src.split("\n")
    low = [ln.lower() for ln in lines]
    stack = []   # module-level implicit-none flags
    i = 0
    while i < len(lines):
        lw = low[i].strip()
        if re.match(r"(recursive\s+)?module\s+(?!procedure\b)\w+", lw):
            imp = False
            j = i + 1
            while j < len(lines):
                hl = low[j].strip()
                if re.match(r"contains\s*$", hl):
                    break
                if re.match(r"((recursive|pure|elemental|\w+)\s+)*(subroutine|function)\s+\w+", hl):
                    break
                if re.match(r"end\s+module", hl):
                    break
                if re.match(r"implicit\s+none", hl):
                    imp = True
                    break
                j += 1
            stack.append(imp)
            i += 1
            continue
        if re.match(r"end\s+module", lw):
            if stack:
                stack.pop()
            i += 1
            continue
        m = re.match(r"((recursive|pure|elemental)\s+)*subroutine\s+(\w+)", lw)
        if m:
            name = m.group(3)
            depth = 1
            k = i + 1
            body = []
            while k < len(lines) and depth > 0:
                bl = low[k].strip()
                if re.match(r"((recursive|pure|elemental)\s+)*subroutine\s+\w+", bl):
                    depth += 1
                elif re.match(r"end\s+subroutine\b", bl) or bl == "end":
                    depth -= 1
                    if depth == 0:
                        break
                if depth > 0:
                    body.append(low[k])
                k += 1
            body_text = "\n".join(body)
            has_in = bool(re.search(r"^\s*implicit\s+none", body_text, re.M))
            inherits = any(stack)
            if not has_in and not inherits:
                yield (i + 1, name)
            i = k + 1
            continue
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument(
        "--max-violations", type=int, default=0,
        help="Exit non-zero if offender count exceeds this threshold",
    )
    ap.add_argument(
        "--exclude", action="append", default=[],
        help="Directory substring to skip (repeatable)",
    )
    args = ap.parse_args()

    violations = []
    for root_dir in args.dirs:
        for root, _, files in os.walk(root_dir):
            if any(x in root for x in args.exclude):
                continue
            for f in files:
                if not (f.endswith(".f90") or f.endswith(".f")):
                    continue
                p = os.path.join(root, f)
                for lineno, name in scan_file(p):
                    violations.append((p, lineno, name))

    for p, lineno, name in violations:
        print(f"{p}:{lineno}: subroutine {name} missing implicit none", file=sys.stderr)

    total = len(violations)
    print(f"Total offenders: {total} (threshold: {args.max_violations})")
    if total > args.max_violations:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
