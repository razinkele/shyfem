#!/usr/bin/env python3
"""
convert_error_stop.py - turn the error stops of free-form Fortran files into
calls of error_stop of mod_error_stop (exit 7, "error stop ROUTINE: TEXT" on
stdout), as done for the tools in #336 and #338.

A  stop 'error stop ...'  ends the program with exit 0 (gfortran), so a
script or the UI cannot tell a failed run from a good one.

Converted automatically (in place, wherever the statement stands: after a
numeric label, after "if(...)", after "then;", "else", before "; end if"):

  stop 'error stop NAME: text'   ->  call error_stop('NAME','text')
  stop 'error stop NAME (n)'     ->  call error_stop('NAME','(n)')
  stop 'error stop: text'        ->  call error_stop('ROUTINE','text')
                                     (ROUTINE = the enclosing routine, only
                                     when the script is certain of it)

Everything else is LISTED, never skipped, with file, line and the reason:
  - an error stop in a form not above (no text, a continued statement, a
    quote that cannot be moved into the call, a routine it is not sure of),
  - any other line that mentions "error stop",
  - every other stop (bare, or with another text): normal end or error?
The exit status is 1 if a line that mentions "error stop" is left (so
"N converted" is never a claim that the file is done), else 0.
--check only scans: nothing is written.

Decisions for the listed sites go in a file given with --decide, one per
line, by the line number of the ORIGINAL file:
    adjgrd.f90:559  insgr|no such node
    shyadj.f90:114  shyadj|no nodes in grid        (also for a bare stop)
The statement "stop" (with its text, if any) of that line becomes
call error_stop('ROUTINE','TEXT').

Every routine that gets a call also gets, after its header and its use
lines, one import line. By default
    use mod_error_stop, only: error_stop
but in a routine, or in a host module or host routine of it, that has
"use shympi" the renamed form is used, and the call uses the new name:
    use mod_error_stop, only: tool_error_stop => error_stop
(shympi has its own generic error_stop, which exits 33; a plain import
there is ambiguous or merges with it).  The report says which form each
routine got.  A module that re-exports shympi cannot be seen by a text
scan: for such files pass --rename, which forces the renamed form
everywhere.  A routine that already imports mod_error_stop keeps its form.

Line endings (LF, CRLF or mixed) are kept.  A call that would pass 132
characters is wrapped with &.  With --makefile FILE a dependency line
OBJ.o: .../lib/mod/mod_error_stop.mod is appended to FILE for every object
that gained the import (make depend does not work on main).
Fixed form (.f) files are refused: the line length is 72 columns there.

Usage:  convert_error_stop.py [--dry-run] [--check] [--rename]
                              [--decide FILE] [--makefile FILE] [--report]
                              FILE.f90 ...
"""
import argparse
import os
import re
import sys

ALIAS = "tool_error_stop"
MAXLEN = 132

CANON = re.compile(r"^\s+(?P<n>\w+):\s+(?P<t>.+?)\s*$")
NUMBERED = re.compile(r"^\s+(?P<n>\w+)\s+(?P<t>\(\d+\))\s*$")
COLON = re.compile(r"^:\s+(?P<t>.+?)\s*$")
# an optional run of kind/type prefixes, then subroutine/function/program
HEADER = re.compile(
    r"^(?:(?:[a-z_]\w*(?:\s*\([^()]*(?:\([^()]*\)[^()]*)*\))?(?:\s*\*\s*\d+)?"
    r"|double\s+precision)\s+)*"
    r"(?P<k>subroutine|function|program)\s+(?P<n>\w+)", re.I)
MODPROC = re.compile(r"^module\s+procedure\s+(?P<n>\w+)", re.I)
END = re.compile(r"^end\s*(?:subroutine|function|program|procedure)\b|^end$", re.I)
USE = re.compile(r"^use(?=[\s,:])\s*(?:,\s*\w+\s*)?(?:::)?\s*(?P<m>\w+)(?=\s*(?:,|&|$))(?P<rest>.*)$", re.I)


def mask(line):
    """the line with string contents blanked (x) and the comment cut off"""
    out = []
    q = None
    for ch in line:
        if q:
            out.append(ch if ch == q else "x")
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            out.append(ch)
        elif ch == "!":
            break
        else:
            out.append(ch)
    return "".join(out)


def literal_at(text, pos):
    """the Fortran string literal starting at text[pos]: (content, end)"""
    q = text[pos]
    i = pos + 1
    buf = []
    while i < len(text):
        if text[i] == q:
            if i + 1 < len(text) and text[i + 1] == q:
                buf.append(q + q)
                i += 2
                continue
            return "".join(buf), i + 1
        buf.append(text[i])
        i += 1
    return None, None


class Scope:
    def __init__(self, kind, name, start):
        self.kind, self.name, self.start = kind, name, start
        self.uses = []          # (line index, module, rest)
        self.contains = False


def structure(masked):
    """per line index: the stack of Scopes (outermost first) in force"""
    stack, per_line = [], []
    idepth = 0
    for i, m in enumerate(masked):
        s = m.strip()
        low = s.lower()
        if re.match(r"^(abstract\s+)?interface\b", low):
            idepth += 1
        elif re.match(r"^end\s*interface\b", low):
            idepth = max(0, idepth - 1)
            per_line.append(list(stack))
            continue
        if idepth:
            per_line.append(list(stack))
            continue
        mm = re.match(r"^module\s+(\w+)\s*$", low)
        if mm and mm.group(1) != "procedure":
            stack.append(Scope("module", mm.group(1), i))
        elif re.match(r"^end\s*module\b", low):
            while stack and stack[-1].kind != "module":
                stack.pop()
            if stack:
                stack.pop()
        else:
            h = HEADER.match(s) if not low.startswith("end") else None
            mp = MODPROC.match(s)
            if h or mp:
                stack.append(Scope("routine", (h or mp).group("n").lower(), i))
            elif low == "contains":
                if stack:
                    stack[-1].contains = True
            elif END.match(low):
                if stack and stack[-1].kind == "routine":
                    stack.pop()
            else:
                u = USE.match(s)
                if u and stack and not stack[-1].contains:
                    rest = u.group("rest")
                    k = i
                    while masked[k].rstrip().endswith("&") and k + 1 < len(masked):
                        rest = rest.rstrip()[:-1] + " " + masked[k + 1].strip().lstrip("&")
                        k += 1
                    stack[-1].uses.append((i, u.group("m").lower(), rest))
        per_line.append(list(stack))
    return per_line


def import_form(stack, force_rename):
    """(alias, use text or None if already imported, why); alias None = the
    existing import is unclear, list the routine"""
    for sc in stack:
        for _, mod, rest in sc.uses:
            if mod != "mod_error_stop":
                continue
            only = re.match(r"^\s*,\s*only\s*:(?P<l>.*)$", rest, re.I)
            if only:
                for item in only.group("l").split(","):
                    item = item.strip()
                    m = re.match(r"^(\w+)\s*=>\s*error_stop$", item, re.I)
                    if m:
                        return m.group(1), None, "already imported as " + m.group(1)
                    if item.lower() == "error_stop":
                        return "error_stop", None, "already imported"
                return None, None, "an existing use mod_error_stop does not import error_stop"
            m = re.search(r"(\w+)\s*=>\s*error_stop", rest, re.I)
            if m:
                return m.group(1), None, "already imported as " + m.group(1)
            if rest.strip() == "":
                return "error_stop", None, "already imported"
            return None, None, "an existing use mod_error_stop is unclear"
    shympi = any(mod == "shympi" for sc in stack for _, mod, _ in sc.uses)
    if shympi or force_rename:
        why = "use shympi in the routine or its host" if shympi else "--rename"
        return ALIAS, "use mod_error_stop, only: %s => error_stop" % ALIAS, why
    return "error_stop", "use mod_error_stop, only: error_stop", "no shympi seen"


def load_decisions(path):
    dec = {}
    if not path:
        return dec
    with open(path) as f:
        for raw in f:
            raw = raw.split("#")[0].strip()
            if not raw:
                continue
            loc, spec = raw.split(None, 1)
            fn, ln = loc.rsplit(":", 1)
            r, t = spec.split("|", 1)
            dec[(os.path.basename(fn), int(ln))] = (r.strip(), t.strip())
    return dec


def convert(path, args, decisions):
    with open(path, newline="") as f:
        raw = f.read()
    lines, crs = [], []
    for r in raw.split("\n"):
        crs.append("\r" if r.endswith("\r") else "")
        lines.append(r[:-1] if r.endswith("\r") else r)
    masked = [mask(l) for l in lines]
    per_line = structure(masked)
    base = os.path.basename(path)
    new = {}                # line index -> list of replacement lines
    after = {}              # line index -> list of lines inserted after it
    done, listed, forms = [], [], {}
    inserted = {}           # scope start -> True
    used = set()

    def say(i, why):
        listed.append((i + 1, lines[i].strip(), why))

    seen = set()

    def say1(i, why):
        if (i, why) not in seen:
            seen.add((i, why))
            say(i, why)

    for i, line in enumerate(lines):
        if line.lstrip().startswith("!"):
            continue
        m = masked[i]
        stops = list(re.finditer(r"\bstop\b", m, re.I))
        if not stops:
            continue
        stack = per_line[i]
        rt = stack[-1] if stack and stack[-1].kind == "routine" else None
        dkey = (base, i + 1)
        edits = []                  # (pos, end, name, text, alias, use, why)
        for n, sm in enumerate(stops):
            pos, j = sm.start(), sm.end()
            while j < len(line) and line[j] in " \t":
                j += 1
            if re.search(r"\berror\s*$", m[:pos], re.I):
                say1(i, "F2008 error stop statement: decide by hand")
                continue
            end, content = sm.end(), None
            if j < len(line) and line[j] in "'\"":
                content, e2 = literal_at(line, j)
                if content is not None:
                    end = e2
            decided = n == 0 and dkey in decisions
            iserr = content is not None and content.lower().startswith("error stop")
            if not decided and not iserr:
                say1(i, "other stop (normal end or error?)")
                continue
            # the whole stop code must be one literal (or none) and then the
            # end of the statement, a ; or a comment
            tailm = m[end:].strip()
            if (content is None and j < len(line) and line[j] not in ";!") or \
               (tailm != "" and not tailm.startswith(";")):
                say1(i, "stop code is not a single literal (continued or concatenated)")
                continue
            if decided:
                name, text = decisions[dkey]
                text = text.replace("'", "''")
                used.add(dkey)
            else:
                rest = content[len("error stop"):]
                c, nm, co = CANON.match(rest), NUMBERED.match(rest), COLON.match(rest)
                if c:
                    name, text = c.group("n"), c.group("t")
                elif nm:
                    name, text = nm.group("n"), nm.group("t")
                elif co and rt:
                    name, text = rt.name, co.group("t")
                elif co:
                    say1(i, "error stop: enclosing routine not certain")
                    continue
                else:
                    say1(i, "error stop in a form the script does not convert")
                    continue
                if line[j] == '"' and ("'" in text or '""' in text):
                    say1(i, "quote in the text of a double-quoted string")
                    continue
            if rt is None:
                say1(i, "no enclosing routine found")
                continue
            alias, use, why_form = import_form(stack, args.rename)
            if alias is None:
                say1(i, why_form)
                continue
            edits.append((pos, end, name, text, alias, use, why_form))
        if not edits:
            continue
        cur = line
        for pos, end, name, text, alias, use, why_form in reversed(edits):
            cur = cur[:pos] + "call %s('%s','%s')" % (alias, name, text) + cur[end:]
        if len(cur) <= MAXLEN:
            new[i] = [cur]
        else:
            pos, end, name, text, alias, use, why_form = edits[0]
            ind = re.match(r"\s*", line).group(0)
            head = line[:pos] + "call %s('%s', &" % (alias, name)
            tail = ind + "\t'%s')" % text + line[end:]
            if len(edits) > 1 or len(head) > MAXLEN or len(tail) > MAXLEN:
                say1(i, "call longer than %d characters" % MAXLEN)
                continue
            new[i] = [head, tail]
        for pos, end, name, text, alias, use, why_form in edits:
            done.append((i + 1, line.strip(), " / ".join(x.strip() for x in new[i])))
            forms[rt.name] = (alias, why_form)
            if use is not None:
                inserted[rt.start] = (rt, use)
    for (fn, ln), _ in decisions.items():
        if fn == base and (fn, ln) not in used:
            listed.append((ln, "", "decision not applied: no stop on this line"))
    # the import lines
    for hs, (sc, use) in inserted.items():
        j = sc.start
        while mask(lines[j]).rstrip().endswith("&"):
            j += 1
        if sc.uses:
            last = max(u[0] for u in sc.uses)
            ind = re.match(r"[ \t]*", lines[last]).group(0) or "\t"
            while mask(lines[last]).rstrip().endswith("&"):     # continued use
                last += 1
        else:
            last = j
            k = j + 1
            while k < len(lines) and (lines[k].strip() == "" or lines[k].lstrip().startswith("!")):
                k += 1
            ind = (re.match(r"[ \t]*", lines[k]).group(0) if k < len(lines) else "") or "\t"
        after.setdefault(last, []).append((ind + use, crs[last]))
    # what is left: a line without a stop that still mentions error stop
    for i, line in enumerate(lines):
        if line.lstrip().startswith("!") or re.search(r"\bstop\b", masked[i], re.I):
            continue
        code = line[:len(masked[i])]
        if re.search(r"error\s+stop", code, re.I):
            say1(i, "mentions error stop, not converted")
    listed.sort()
    out, ocr = [], []
    for i, line in enumerate(lines):
        for s in new.get(i, [line]):
            out.append(s)
            ocr.append(crs[i])
        for s, c in after.get(i, []):
            out.append(s)
            ocr.append(c)
    return out, ocr, done, listed, forms


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="only scan and list, write nothing")
    ap.add_argument("--rename", action="store_true",
                    help="force the renamed import everywhere")
    ap.add_argument("--decide", help="file with decisions for listed sites")
    ap.add_argument("--makefile")
    ap.add_argument("--report", action="store_true",
                    help="print every old -> new line")
    a = ap.parse_args()
    decisions = load_decisions(a.decide)
    ndone = nleft = nerr = 0
    objs = []
    for p in a.files:
        if p.lower().endswith(".f"):
            print("%s: fixed form, not converted" % p)
            nerr += 1
            continue
        out, ocr, done, listed, forms = convert(p, a, decisions)
        left = [x for x in listed if "other stop" not in x[2]]
        ndone += len(done)
        nleft += len(left)
        print("%s: %d converted, %d left for a decision, %d other stops" %
              (p, len(done), len(left), len(listed) - len(left)))
        if a.report:
            for ln, old, newl in done:
                print("   %5d  %s\n         -> %s" % (ln, old, newl))
        for r, (alias, why) in sorted(forms.items()):
            print("   import in %s: %s (%s)" % (r, alias, why))
        for ln, old, why in listed:
            print("   %5d  %s   [%s]" % (ln, old, why))
        if done and not (a.dry_run or a.check):
            with open(p, "w", newline="") as f:
                f.write("\n".join(l + c for l, c in zip(out, ocr)))
            objs.append(p)
        elif done:
            objs.append(p)
    if a.makefile and objs and not (a.dry_run or a.check):
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
    print("total: %d converted, %d left for a decision" % (ndone, nleft))
    return 1 if (nleft or nerr) else 0


if __name__ == "__main__":
    sys.exit(main())
