"""Structural Verilog in, drawings out.

What matters is that the drawings say what the Verilog says: the same cells,
wired the same way, a child module drawn as a block that opens onto its own
drawing -- and that what cannot be drawn is said out loud rather than dropped.

Usage:

    python3 -m unittest tests.test_hdl
"""

import os
import shutil
import tempfile
import unittest

from drawlogic import drc, hdl, sheets
from drawlogic.symbols import default_registry

import tests  # noqa: F401  (puts the repo on sys.path)


FULL_ADDER = """\
// a full adder from gate primitives
module full_adder (input a, input b, input cin, output sum, output cout);
  wire s1, c1, c2;
  xor x1 (s1, a, b);
  xor x2 (sum, s1, cin);
  and a1 (c1, a, b);
  and a2 (c2, s1, cin);
  or  o1 (cout, c1, c2);
endmodule
"""

# `stage` is used twice; vendor_pll is defined nowhere; the header of `top`
# is the older style, with the directions in the body.
HIERARCHY = """\
module top(clk, d, q);
  input clk;
  input [3:0] d;
  output [3:0] q;
  wire [3:0] mid;
  wire lock;
  stage s0 (.clk(clk), .d(d), .q(mid));
  stage s1 (.clk(clk), .d(mid), .q(q));
  vendor_pll pll (.ref(clk), .locked(lock));
endmodule

module stage (input clk, input [3:0] d, output [3:0] q);
  dff r (.d(d[0]), .ck(clk), .q(q[0]));
endmodule
"""


def nets_by_name(doc):
  return {net["name"]: net for net in doc.nets}


def ends(net):
  found = [(net["from"]["cell"], net["from"]["pin"])]
  found += [(load["cell"], load["pin"]) for load in net["to"]]
  return sorted(found)


class TestGates(unittest.TestCase):

  def setUp(self):
    self.top, self.drawings, self.warnings = hdl.import_verilog(FULL_ADDER)
    self.doc = self.drawings["full_adder"]

  def test_every_gate_and_port_becomes_a_cell(self):
    types = {cell["id"]: cell["type"] for cell in self.doc.cells}
    self.assertEqual(self.top, "full_adder")
    self.assertEqual(types, {
      "x1": "xor2", "x2": "xor2", "a1": "and2", "a2": "and2", "o1": "or2",
      "p_a": "port_in", "p_b": "port_in", "p_cin": "port_in",
      "p_sum": "port_out", "p_cout": "port_out"})
    self.assertEqual(self.warnings, [])

  def test_a_primitive_is_driven_from_its_first_terminal(self):
    nets = nets_by_name(self.doc)
    self.assertEqual(nets["s1"]["from"], {"cell": "x1", "pin": "y"})
    self.assertEqual(ends(nets["s1"]), [("a2", "a"), ("x1", "y"), ("x2", "a")])
    self.assertEqual(nets["a"]["from"], {"cell": "p_a", "pin": "p"})
    self.assertEqual(ends(nets["cout"]), [("o1", "y"), ("p_cout", "p")])

  def test_the_drawing_is_valid_and_laid_out(self):
    registry = default_registry()
    problems = [issue for issue in list(self.doc.validate(registry))
                + list(drc.check(self.doc, registry)) if issue.level == "error"]
    self.assertEqual([str(issue) for issue in problems], [])
    # Laid out: inputs left of the gates, outputs right of them.
    x = {cell["id"]: cell["x"] for cell in self.doc.cells}
    self.assertLess(x["p_a"], x["x1"])
    self.assertLess(x["o1"], x["p_cout"])


class TestHierarchy(unittest.TestCase):

  def setUp(self):
    self.top, self.drawings, self.warnings = hdl.import_verilog(HIERARCHY)
    self.folder = tempfile.mkdtemp()
    for name, doc in self.drawings.items():
      doc.save(os.path.join(self.folder, name + ".dlg"))

  def tearDown(self):
    shutil.rmtree(self.folder)

  def test_each_module_is_a_drawing_and_the_top_is_found(self):
    self.assertEqual(self.top, "top")
    self.assertEqual(sorted(self.drawings), ["stage", "top", "vendor_pll"])

  def test_every_drawing_opens_with_its_blocks_resolved(self):
    for name in self.drawings:
      doc, registry, issues = sheets.open_document(
        os.path.join(self.folder, name + ".dlg"))
      problems = [issue for issue in list(issues) + list(doc.validate(registry))
                  if issue.level == "error"]
      self.assertEqual([str(issue) for issue in problems], [], name)

  def test_a_child_is_a_block_wired_by_its_port_labels(self):
    top = self.drawings["top"]
    refs = {cell["id"]: cell.get("ref") for cell in top.cells
            if cell["type"] == "sheet"}
    self.assertEqual(refs, {"s0": "stage.dlg", "s1": "stage.dlg",
                            "pll": "vendor_pll.dlg"})
    mid = nets_by_name(top)["mid[3:0]"]
    self.assertEqual(mid["width"], 4)
    self.assertEqual(ends(mid), [("s0", "q[3:0]"), ("s1", "d[3:0]")])
    self.assertEqual(mid["from"], {"cell": "s0", "pin": "q[3:0]"})

  def test_the_older_header_takes_directions_and_widths_from_the_body(self):
    ports = {cell["id"]: (cell["type"], cell["label"])
             for cell in self.drawings["top"].cells
             if cell["type"].startswith("port")}
    self.assertEqual(ports, {"p_clk": ("port_in", "clk"),
                             "p_d": ("port_in", "d[3:0]"),
                             "p_q": ("port_out", "q[3:0]")})

  def test_an_unknown_module_gets_a_drawing_of_the_ports_it_is_used_by(self):
    stub = self.drawings["vendor_pll"]
    self.assertEqual(sorted((cell["type"], cell["label"]) for cell in stub.cells),
                     [("port_inout", "locked"), ("port_inout", "ref")])
    self.assertIn("vendor_pll is not defined", " ".join(self.warnings))

  def test_one_bit_of_a_vector_goes_through_a_ripper_facing_the_signal(self):
    stage = self.drawings["stage"]
    types = {cell["id"]: cell["type"] for cell in stage.cells}
    self.assertEqual(types["rip_d_0"], "ripper")    # taken off d
    self.assertEqual(types["join_q_0"], "bus_join")  # put on q
    nets = nets_by_name(stage)
    self.assertEqual((nets["d[0]"]["width"], nets["d[3:0]"]["width"]), (1, 4))
    self.assertEqual(ends(nets["d[0]"]), [("r", "d"), ("rip_d_0", "bit")])
    self.assertEqual(nets["d[0]"]["from"], {"cell": "rip_d_0", "pin": "bit"})
    self.assertEqual(nets["q[0]"]["from"], {"cell": "r", "pin": "q"})
    self.assertEqual(nets["q[3:0]"]["from"], {"cell": "join_q_0", "pin": "bus"})
    self.assertEqual([w for w in self.warnings if "stage" in w], [])
    # The joiner faces forward: the flip-flop, then it, then the port.
    x = {cell["id"]: cell["x"] for cell in stage.cells}
    self.assertLess(x["r"], x["join_q_0"])
    self.assertLess(x["join_q_0"], x["p_q"])


class TestWhatCannotBeDrawn(unittest.TestCase):

  def test_a_slice_connects_the_whole_vector_and_says_so(self):
    _, drawings, warnings = hdl.import_verilog(
      "module m (input [3:0] a, output y);\n"
      "  and g (y, a[1:0], a[3]);\n"
      "endmodule\n")
    self.assertIn("m line 2: part of a is connected", " ".join(warnings))

  def test_assign_joins_two_names_and_anything_else_is_reported(self):
    _, drawings, warnings = hdl.import_verilog(
      "module m (input a, output y, output z);\n"
      "  assign y = a;\n"
      "  assign z = a & y;\n"
      "  always @(a) begin end\n"
      "endmodule\n")
    net = nets_by_name(drawings["m"])
    self.assertEqual(sorted(net), ["a"])
    self.assertEqual(ends(net["a"]), [("p_a", "p"), ("p_y", "p")])
    text = " ".join(warnings)
    self.assertIn("m line 3: only `assign a = b;` can be drawn", text)
    self.assertIn("m line 4: behavioural code is not drawn", text)

  def test_a_gate_with_no_symbol_is_drawn_as_a_block(self):
    top, drawings, warnings = hdl.import_verilog(
      "module m (input a, b, c, d, output y);\n"
      "  and g (y, a, b, c, d);\n"
      "endmodule\n")
    self.assertEqual(sorted(drawings), ["and4", "m"])
    self.assertEqual(drawings["m"].cell("g")["ref"], "and4.dlg")
    self.assertIn("and with 4 inputs has no symbol", " ".join(warnings))


class TestErrorsAndChoices(unittest.TestCase):

  def assertRefused(self, text, message):
    with self.assertRaises(hdl.HdlError) as caught:
      hdl.import_verilog(text)
    self.assertIn(message, str(caught.exception))

  def test_an_error_names_its_line(self):
    self.assertRefused("module m (input a);\n\n  this is not verilog;\n"
                       "endmodule\n", "line 3: cannot read")
    self.assertRefused("module m (input a);\n", "line 1: module m has no endmodule")
    self.assertRefused("// nothing here\n", "no module found")

  def test_a_module_that_contains_itself_is_refused(self):
    self.assertRefused("module a (input x);\n  b u (.x(x));\nendmodule\n"
                       "module b (input x);\n  a u (.x(x));\nendmodule\n",
                       "instantiates itself")

  def test_the_top_is_the_module_nothing_uses_unless_one_is_named(self):
    text = "module leaf (input x);\nendmodule\n" \
           "module root (input x);\n  leaf u (.x(x));\nendmodule\n"
    self.assertEqual(hdl.import_verilog(text)[0], "root")
    self.assertEqual(hdl.import_verilog(text, top="leaf")[0], "leaf")
    with self.assertRaises(hdl.HdlError):
      hdl.import_verilog(text, top="nowhere")


if __name__ == "__main__":
  unittest.main()
