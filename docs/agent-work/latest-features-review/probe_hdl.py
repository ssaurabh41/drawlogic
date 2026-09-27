"""Independent probes of `drawlogic import` (hdl.py) at baseline 0f53171.

Each test asserts the behaviour the module's own docstring promises. A
failure here is a finding, not a broken test: nothing in this file is part
of the shipped suite.

Run (from this directory):

    python -m unittest discover -s . -p "probe_*.py" -v
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

from drawlogic import drc, hdl, sheets
from drawlogic.symbols import default_registry

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def read(name):
  with open(os.path.join(FIXTURES, name)) as handle:
    return handle.read()


class TestBehaviourIsWarnedNotRefused(unittest.TestCase):
  """See hdl.py's docstring: "always/initial blocks ... reported as a warning
  rather than refused"."""

  def imported(self, name):
    return hdl.import_verilog(read(name), default_registry())

  def test_a_case_statement_is_a_warning(self):
    try:
      _top, _drawings, warnings = self.imported("always_case.v")
    except hdl.HdlError as exc:
      self.fail("refused the file instead of warning: %s" % exc)
    self.assertTrue(any("behavioural" in w for w in warnings),
                    "no warning mentioned the always block: %r" % warnings)

  def test_an_if_else_is_a_warning(self):
    try:
      _top, _drawings, warnings = self.imported("always_else.v")
    except hdl.HdlError as exc:
      self.fail("refused the file instead of warning: %s" % exc)
    self.assertTrue(any("behavioural" in w for w in warnings),
                    "no warning mentioned the always block: %r" % warnings)

  def test_an_expression_in_a_declaration_is_a_warning(self):
    _top, _drawings, warnings = self.imported("wire_assign.v")
    self.assertTrue(any("x" in w for w in warnings),
                    "wire x = a & b; was dropped without a word: %r" % warnings)


class TestTheDrawingSaysWhatTheVerilogSays(unittest.TestCase):
  """The positive control: what is understood has to come out valid."""

  def test_a_flat_netlist_round_trips_clean(self):
    text = ("module add1 (input a, input b, output s, output c);\n"
            "  wire n;\n"
            "  xor g1 (s, a, b);\n"
            "  and g2 (n, a, b);\n"
            "  buf g3 (c, n);\n"
            "endmodule\n")
    top, drawings, warnings = hdl.import_verilog(text, default_registry())
    self.assertEqual(top, "add1")
    self.assertEqual(warnings, [])
    registry = default_registry()
    errors = [i for i in drawings["add1"].validate(registry)
              if i.level == "error"]
    errors += [v for v in drc.check(drawings["add1"], registry)
               if v.level == "error"]
    self.assertEqual([str(e) for e in errors], [])


if __name__ == "__main__":
  unittest.main()
