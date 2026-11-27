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

    def test_fixed_form_refused(self):
        p = self.w("f.f", "      stop 'error stop x: y'\n")
        rc, out = run(p, cwd=self.d.name)
        self.assertEqual(rc, 1)
        self.assertEqual(self.r("f.f"), "      stop 'error stop x: y'\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
