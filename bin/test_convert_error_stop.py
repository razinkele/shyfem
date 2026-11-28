#!/usr/bin/env python3
"""Synthetic tests of convert_error_stop.py: every form it must convert, and
every form it must list (never skip).  Run:  python3 bin/test_convert_error_stop.py"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "convert_error_stop.py")

PLAIN = """\
module m1
	implicit none
contains
	subroutine a1(x)
	implicit none
	integer x
	if(x>1) then; stop 'error stop a1: then'; end if
   99	stop 'error stop g: label'
	if(x>5) stop 'error stop a1: it''s'
	if(x>6) stop "error stop a1: dq"
	stop 'error stop a1 (3)'
	stop 'error stop: colon form'
	stop 'error stop nocolon'
	stop
	stop 'a1: done'
	end subroutine
	real(8) function f1(x)
	integer x
	stop 'error stop: in f1'
	end function
	integer*4 function f2(x)
	integer x
	stop 'error stop: in f2'
	end function
	type(t) function f3(x)
	integer x
	stop 'error stop: in f3'
	end function
	double precision function f4(x)
	integer x
	stop 'error stop: in f4'
	end function
	subroutine withif()
	interface
	  subroutine ifs(y)
	  integer y
	  end subroutine
	end interface
	stop 'error stop: after interface'
	end subroutine
	module procedure mp
	stop 'error stop: in mp'
	end procedure
	subroutine host
	implicit none
	call inner
	stop 'error stop: host after inner'
	contains
	subroutine inner
	stop 'error stop: in inner'
	end subroutine
	end subroutine
	stop 'error stop: module level lost'
end module
"""

SHYMPI = """\
module m2
	use shympi
contains
	subroutine b1
	implicit none
	stop 'error stop b1: module uses shympi'
	end subroutine
end module
subroutine b2
	use shympi
	implicit none
	stop 'error stop b2: routine uses shympi'
end
subroutine b3
	implicit none
	stop 'error stop b3: plain'
end
"""

LONG = ("""\
subroutine c1
	implicit none
	if( ierr /= 0 ) stop 'error stop c1: %s'
end
""" % ("long text " * 11))


TRICKY = """\
module kk
	implicit none
	integer a1, b1
end module
subroutine s1
	implicit none
	integer used
	used = 0
	stop 'error stop s1: used'
end
subroutine s2
	use kk
	implicit none
	integer user, usevar
	user = 3
	usevar = 4
	stop 'error stop s2: user'
end
subroutine s3
	use kk, only: a1, &
	   b1
	implicit none
	stop 'error stop s3: continued use'
end
subroutine s4
	use kk, only: a1, & ! comment
	   b1
	implicit none
	stop 'error stop s4: continued use with comment'
end
subroutine s5
	implicit none
	error stop 'error stop s5: f2008'
end
"""

STUB = """\
module mod_error_stop
	implicit none
	interface error_stop
	  module procedure es2
	end interface
contains
	subroutine success
	end subroutine
	subroutine es2(r,t)
	character*(*) r, t
	end subroutine
end module
"""


ROUND3 = """\
subroutine r1(bad)
	use mod_error_stop, only: error_stop
	implicit none
	logical bad
	if (bad) then; stop 'error stop r1: a'; else; stop 'error stop r1: b'; end if
	if (bad) STOP
	if (bad) STOP 'ERROR STOP r1: upper'
end
subroutine r2
	use mod_error_stop, only: &
	   es => error_stop
	implicit none
	stop 'error stop r2: alias'
end
subroutine r3
	implicit none
	stop 'error stop r3: a' // &
	   'b'
end
subroutine r4
	use mod_error_stop, only: success
	implicit none
	stop 'error stop r4: x'
end
subroutine r5(bad)
	implicit none
	logical bad
	if (bad) STOP 'Error Stop r5: mixed' ; stop 'error stop r5: two'
end
SUBROUTINE r6
	USE Mod_Error_Stop, ONLY: error_stop
	IMPLICIT NONE
	STOP 'error stop r6: caps'
END SUBROUTINE
"""


def run(*args, cwd):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=cwd,
                       capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p.returncode, p.stdout + p.stderr


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)

    def w(self, name, text, newline=""):
        p = os.path.join(self.d.name, name)
        with open(p, "w", newline="") as f:
            f.write(text)
        return p

    def r(self, name):
        with open(os.path.join(self.d.name, name), newline="") as f:
            return f.read()

    def test_forms_and_leftovers(self):
        p = self.w("t.f90", PLAIN)
        rc, out = run("--report", p, cwd=self.d.name)
        print("---- forms: exit %d\n%s" % (rc, out))
        src = self.r("t.f90")
        self.assertEqual(rc, 1)                       # sites are left
        for want in [
            "call error_stop('a1','then')",
            "call error_stop('g','label')",
            "call error_stop('a1','it''s')",
            "call error_stop('a1','dq')",
            "call error_stop('a1','(3)')",
            "call error_stop('a1','colon form')",
            "call error_stop('f1','in f1')",
            "call error_stop('f2','in f2')",
            "call error_stop('f3','in f3')",
            "call error_stop('f4','in f4')",
            "call error_stop('withif','after interface')",
            "call error_stop('mp','in mp')",
            "call error_stop('inner','in inner')",
            "call error_stop('host','host after inner')",
        ]:
            self.assertIn(want, src)
        self.assertIn("99\tcall error_stop('g','label')", src)     # label kept
        # listed, not skipped
        self.assertIn("[error stop in a form the script does not convert]", out)   # nocolon
        self.assertIn("[error stop: enclosing routine not certain]", out)         # module level
        self.assertIn("[other stop (normal end or error?)]", out)                 # bare, 'a1: done'
        self.assertNotIn("stop 'error stop g", src)
        self.assertEqual(src.count("stop 'error stop"), 2)    # nocolon + module level
        # no import inside the interface body, one per routine with a call
        iface = src.split("interface")[1]
        self.assertNotIn("mod_error_stop", iface.split("end interface")[0])
        self.assertEqual(src.count("use mod_error_stop, only: error_stop"), 9)

    def test_shympi_visibility(self):
        p = self.w("s.f90", SHYMPI)
        rc, out = run(p, cwd=self.d.name)
        print("---- shympi: exit %d\n%s" % (rc, out))
        src = self.r("s.f90")
        self.assertEqual(rc, 0)
        self.assertIn("call tool_error_stop('b1','module uses shympi')", src)
        self.assertIn("call tool_error_stop('b2','routine uses shympi')", src)
        self.assertIn("call error_stop('b3','plain')", src)
        self.assertEqual(src.count("only: tool_error_stop => error_stop"), 2)
        self.assertIn("b3: error_stop", out)
        self.assertIn("use shympi in the routine or its host", out)

    def test_rename_override(self):
        p = self.w("r.f90", "subroutine r1\n\timplicit none\n\tstop 'error stop r1: x'\nend\n")
        rc, out = run("--rename", p, cwd=self.d.name)
        self.assertEqual(rc, 0)
        self.assertIn("call tool_error_stop('r1','x')", self.r("r.f90"))

    def test_crlf_kept(self):
        p = self.w("c.f90", PLAIN.replace("\n", "\r\n"))
        run(p, cwd=self.d.name)
        src = self.r("c.f90")
        self.assertEqual(src.count("\n"), src.count("\r\n"))      # every line still CRLF
        self.assertIn("call error_stop('a1','then')", src)
        self.assertIn("\tuse mod_error_stop, only: error_stop\r\n", src)

    def test_mixed_endings(self):
        p = self.w("x.f90", "subroutine x1\r\n\timplicit none\n\tstop 'error stop x1: a'\r\nend\n")
        run(p, cwd=self.d.name)
        self.assertEqual(self.r("x.f90").replace("\r\n", "").count("\r"), 0)
        self.assertIn("call error_stop('x1','a')\r\n", self.r("x.f90"))

    def test_long_call_wrapped(self):
        p = self.w("l.f90", LONG)
        rc, out = run(p, cwd=self.d.name)
        print("---- long: exit %d\n%s" % (rc, out))
        src = self.r("l.f90")
        self.assertEqual(rc, 0)
        self.assertTrue(all(len(l) <= 132 for l in src.split("\n")))
        self.assertIn("call error_stop('c1', &", src)

    def test_check_mode_writes_nothing_and_exits_1(self):
        p = self.w("k.f90", PLAIN)
        rc, out = run("--check", p, cwd=self.d.name)
        self.assertEqual(rc, 1)
        self.assertEqual(self.r("k.f90"), PLAIN)

    def test_decide_file(self):
        p = self.w("d.f90", "subroutine d1\n\timplicit none\n\tstop 'error stop d1'\n\tstop\nend\n")
        dec = self.w("dec.txt", "d.f90:3 d1|some text\nd.f90:4 d1|bare\n")
        rc, out = run("--decide", dec, p, cwd=self.d.name)
        src = self.r("d.f90")
        self.assertEqual(rc, 0)
        self.assertIn("call error_stop('d1','some text')", src)
        self.assertIn("call error_stop('d1','bare')", src)

    def test_tricky_use_lines_parse(self):
        p = self.w("u.f90", TRICKY)
        rc, out = run(p, cwd=self.d.name)
        print("---- tricky: exit %d\n%s" % (rc, out))
        src = self.r("u.f90")
        self.assertEqual(rc, 1)                    # s5 is listed
        self.assertNotIn("error call", src)
        self.assertIn("error stop 'error stop s5: f2008'", src)
        self.assertIn("[F2008 error stop statement: decide by hand]", out)
        lines = src.split("\n")
        def at(sub):
            return [i for i, l in enumerate(lines) if sub in l][0]
        # the import comes before any executable or declaration line
        self.assertLess(at("only: error_stop"), at("used = 0"))
        s2 = src.split("subroutine s2")[1].split("end\n")[0]
        self.assertLess(s2.index("mod_error_stop"), s2.index("implicit none"))
        # a continued use statement is not cut in two
        for name in ("s3", "s4"):
            body = src.split("subroutine " + name)[1].split("end\n")[0]
            i = body.index("only: a1,")
            self.assertTrue(body[i:].split("\n")[1].strip().startswith("b1"))
        # and the whole file parses against a stub of the module
        self.w("mod_error_stop.f90", STUB)
        gf = subprocess.run(["gfortran", "-fsyntax-only", "mod_error_stop.f90"],
                            cwd=self.d.name, capture_output=True, text=True)
        self.assertEqual(gf.returncode, 0, gf.stderr)
        # s5 (still the f2008 statement) is removed for the syntax check
        ok = src.replace("\terror stop 'error stop s5: f2008'\n", "")
        self.w("u2.f90", ok)
        gf = subprocess.run(["gfortran", "-fsyntax-only", "u2.f90"],
                            cwd=self.d.name, capture_output=True, text=True)
        print("---- gfortran -fsyntax-only u2.f90: exit %d %s" % (gf.returncode, gf.stderr))
        self.assertEqual(gf.returncode, 0, gf.stderr)

    def test_round3_review_findings(self):
        p = self.w("v.f90", ROUND3)
        rc, out = run(p, cwd=self.d.name)
        print("---- round 3: exit %d\n%s" % (rc, out))
        src = self.r("v.f90")
        self.assertEqual(rc, 1)
        # every stop of a line is converted (r1 a and b, r5 both)
        self.assertIn("then; call error_stop('r1','a'); else; call error_stop('r1','b'); end if", src)
        self.assertIn("call error_stop('r5','mixed') ; call error_stop('r5','two')", src)
        # upper case keywords: the stop with its text is converted, the bare
        # STOP is listed, and the existing upper-case import is recognised
        self.assertIn("call error_stop('r1','upper')", src)
        self.assertRegex(out, r"if \(bad\) STOP +\[other stop")
        self.assertIn("call error_stop('r6','caps')", src)
        self.assertEqual(src.upper().count("USE MOD_ERROR_STOP"), 5)   # r1 r2 r4 r6 had one, r5 got one
        # the alias of a continued existing import is used
        self.assertIn("call es('r2','alias')", src)
        # a stop code that is not one literal is listed, not half converted
        self.assertIn("stop 'error stop r3: a' // &", src)
        self.assertIn("[stop code is not a single literal", out)
        # an existing import that does not import error_stop is listed
        self.assertIn("stop 'error stop r4: x'", src)
        self.assertIn("[an existing use mod_error_stop does not import error_stop]", out)
        # the converted file parses against the stub
        self.w("mod_error_stop.f90", STUB)
        gf = subprocess.run(["gfortran", "-fsyntax-only", "mod_error_stop.f90"],
                            cwd=self.d.name, capture_output=True, text=True)
        self.assertEqual(gf.returncode, 0, gf.stderr)
        gf = subprocess.run(["gfortran", "-fsyntax-only", "v.f90"],
                            cwd=self.d.name, capture_output=True, text=True)
        print("---- gfortran -fsyntax-only v.f90: exit %d %s" % (gf.returncode, gf.stderr))
        self.assertEqual(gf.returncode, 0, gf.stderr)

    def test_decision_text_with_apostrophe(self):
        p = self.w("q.f90", "subroutine q1\n\timplicit none\n\tstop 'error stop q1'\nend\n")
        dec = self.w("dq.txt", "q.f90:3 q1|can't read grid\n")
        rc, out = run("--decide", dec, p, cwd=self.d.name)
        self.assertEqual(rc, 0)
        self.assertIn("call error_stop('q1','can''t read grid')", self.r("q.f90"))

    def test_leading_space_literal(self):
        p = self.w("ls.f90", "subroutine ls1\n\timplicit none\n\tstop ' error stop ls1: lead'\n\tstop ' error stop ls1 (2)'\nend\n")
        rc, out = run(p, cwd=self.d.name)
        src = self.r("ls.f90")
        self.assertEqual(rc, 0)
        self.assertIn("call error_stop('ls1','lead')", src)
        self.assertIn("call error_stop('ls1','(2)')", src)

    def test_decided_continued_stop(self):
        text = ("subroutine dc1(b)\n\timplicit none\n\tlogical b\n\tif( b ) then\n"
                "\t  stop 'error stop dc1: ' // &\n     &\t\t\t'second part'\n\tend if\n"
                "\tif( b ) then\n\t  stop 'error stop dc1: ' // &\n\t    'a ' // &\n\t    'b'\n\tend if\nend\n")
        p = self.w("dc.f90", text)
        # without a decision both are listed, nothing is half converted
        rc, out = run("--check", p, cwd=self.d.name)
        self.assertEqual(rc, 1)
        self.assertEqual(out.count("[stop code is not a single literal"), 2)
        dec = self.w("ddc.txt", "dc.f90:5 dc1|first\ndc.f90:9 dc1|second\n")
        rc, out = run("--decide", dec, p, cwd=self.d.name)
        src = self.r("dc.f90")
        print("---- decided continued: exit %d\n%s\n%s" % (rc, out, src))
        self.assertEqual(rc, 0)
        self.assertIn("call error_stop('dc1','first')", src)
        self.assertIn("call error_stop('dc1','second')", src)
        self.assertNotIn("second part", src)
        self.assertNotIn("&", src)
        self.w("mod_error_stop.f90", STUB)
        for f in ("mod_error_stop.f90", "dc.f90"):
            gf = subprocess.run(["gfortran", "-fsyntax-only", f], cwd=self.d.name,
                                capture_output=True, text=True)
            self.assertEqual(gf.returncode, 0, gf.stderr)

    def test_fixed_form_refused(self):
        p = self.w("f.f", "      stop 'error stop x: y'\n")
        rc, out = run(p, cwd=self.d.name)
        self.assertEqual(rc, 1)
        self.assertEqual(self.r("f.f"), "      stop 'error stop x: y'\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
