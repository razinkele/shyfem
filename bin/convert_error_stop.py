#!/usr/bin/env python3
"""
convert_error_stop.py - turn the error stops of Fortran 90 files into calls
of error_stop of mod_error_stop (exit 7, "error stop ROUTINE: TEXT" on
stdout), as done for the tools in #336 and #338.

A bare  stop 'error stop ...'  ends the program with exit 0 (gfortran), so
a script or the UI cannot tell a failed run from a good one.

Forms it converts (the forms are listed by --report, nothing else is touched):

  stop 'error stop NAME: text'   ->  call error_stop('NAME','text')
  stop 'error stop NAME (n)'     ->  call error_stop('NAME','(n)')
  stop 'error stop: text'        ->  call error_stop('ROUTINE','text')
                                     (ROUTINE = the enclosing routine)

Forms it leaves for a decision by hand (it lists them with file and line):

  stop 'error stop NAME'         (no text)
  stop 'error stop ...' with anything else, a continued line, a stop with
  a text that does not start with "error stop", and a bare  stop

Every routine that gets a call also gets, after its header and any use
lines, the line  use mod_error_stop, only: error_stop  (or, with
--rename NAME, only: NAME => error_stop; use it where shympi is visible,
its own generic error_stop exits 33).  With --makefile FILE a dependency
line  OBJ.o: .../lib/mod/mod_error_stop.mod  is appended to FILE for every
object that gained the use (make depend does not work on main).

Usage:  convert_error_stop.py [--dry-run] [--rename NAME] [--makefile FILE]
                              [--report] FILE.f90 ...
Fixed form (.f) files are refused: the line length is 72 columns there.
"""
import argparse
import os
import re
import sys

STOP = re.compile(
    r"""^(?P<pre>\s*(?:if\s*\(.*\)\s*)?)stop\s+(?P<q>['"])error stop(?P<rest>[^'"]*)(?P=q)\s*(?P<post>!.*)?$""",
    re.I)
CANON = re.compile(r"^\s+(?P<n>\w+):\s+(?P<t>.+?)\s*$")
NUMBERED = re.compile(r"^\s+(?P<n>\w+)\s+(?P<t>\(\d+\))\s*$")
COLON = re.compile(r"^:\s+(?P<t>.+?)\s*$")
HEADER = re.compile(
    r"^\s*(?:(?:integer|real|double precision|logical|character\S*|"
    r"recursive|pure|elemental)\s+)*(?:subroutine|function|program)\s+(?P<n>\w+)",
    re.I)
USE = re.compile(r"^\s*use\s+(\w+)", re.I)
BARE = re.compile(r"^\s*(?:if\s*\(.*\)\s*)?stop\s*(?:!.*)?$", re.I)


def convert(path, rename):
    with open(path, newline="") as f:
        lines = f.read().split("\n")
    out = list(lines)
    cur = None            # (header line index, name)
    needs = {}            # header line index -> routine name
    done, manual = [], []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("!"):
            continue
        h = HEADER.match(line)
        if h and not re.match(r"^\s*end\b", line, re.I):
            cur = (i, h.group("n").lower())
            continue
        m = STOP.match(line)
        if not m:
            if BARE.match(line):
                manual.append((i + 1, line.strip(), "bare stop"))
            continue
        rest = m.group("rest")
        c = CANON.match(rest)
        nm = NUMBERED.match(rest)
        co = COLON.match(rest)
        if c:
            name, text = c.group("n"), c.group("t")
        elif nm:
            name, text = nm.group("n"), nm.group("t")
        elif co and cur:
            name, text = cur[1], co.group("t")
        else:
            manual.append((i + 1, line.strip(), "needs a decision"))
            continue
        if cur is None or "'" in text or '"' in text:
            manual.append((i + 1, line.strip(), "needs a decision"))
            continue
        new = "%scall %s('%s','%s')" % (m.group("pre"), rename or "error_stop",
                                         name, text)
        if m.group("post"):
            new += " " + m.group("post")
        out[i] = new
        needs[cur[0]] = cur[1]
        done.append((i + 1, line.strip(), new.strip()))
    # insert the use lines, last header first so that the indices stay valid
    use = ("use mod_error_stop, only: %s => error_stop" % rename) if rename \
        else "use mod_error_stop, only: error_stop"
    for hi in sorted(needs, reverse=True):
        j = hi
        while out[j].rstrip().endswith("&"):      # continued header
            j += 1
        k = j + 1
        last = j
        while k < len(out):
            s = out[k].strip()
            if s == "" or s.startswith("!"):
                k += 1
            elif USE.match(out[k]):
                if "mod_error_stop" in out[k]:
                    last = None
                    break
                last = k
                k += 1
            else:
                break
        if last is None:
            continue
        ind = re.match(r"\s*", out[k] if k < len(out) else "\t").group(0) or "\t"
        out.insert(last + 1, ind + use)
    return out, done, manual, bool(needs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rename")
    ap.add_argument("--makefile")
    ap.add_argument("--report", action="store_true",
                    help="print every old -> new line")
    a = ap.parse_args()
    ndone = nman = 0
    objs = []
    for p in a.files:
        if p.lower().endswith(".f"):
            print("%s: fixed form, not converted" % p)
            continue
        out, done, manual, touched = convert(p, a.rename)
        ndone += len(done)
        nman += len(manual)
        print("%s: %d converted, %d for a decision" % (p, len(done), len(manual)))
        if a.report:
            for ln, old, new in done:
                print("   %5d  %s\n         -> %s" % (ln, old, new))
        for ln, old, why in manual:
            print("   %5d  %s   [%s]" % (ln, old, why))
        if done and not a.dry_run:
            with open(p, "w", newline="") as f:
                f.write("\n".join(out))
        if touched:
            objs.append(p)
    if a.makefile and objs and not a.dry_run:
        d = os.path.dirname(os.path.abspath(a.files[0]))
        root = d
        while root != "/" and not os.path.exists(os.path.join(root, "Rules.make")):
            root = os.path.dirname(root)
        rel = os.path.relpath(os.path.join(root, "lib", "mod"), d)
        with open(a.makefile, newline="") as f:
            txt = f.read()
        if not txt.endswith("\n"):
            txt += "\n"
        for p in objs:
            o = os.path.splitext(os.path.basename(p))[0] + ".o"
            line = "%s: %s/mod_error_stop.mod\n" % (o, rel)
            if line not in txt:
                txt += line
        with open(a.makefile, "w", newline="") as f:
            f.write(txt)
    print("total: %d converted, %d left for a decision" % (ndone, nman))
    return 0


if __name__ == "__main__":
    sys.exit(main())
