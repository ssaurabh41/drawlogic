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
from unittest import mock

from drawlogic import drc, hdl, sheets, yosys
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

  def test_assign_joins_two_names_and_logic_becomes_gates(self):
    _, drawings, warnings = hdl.import_verilog(
      "module m (input a, output y, output z);\n"
      "  assign y = a;\n"
      "  assign z = a & y;\n"
      "  always @(a) begin end\n"
      "endmodule\n", synth="builtin")
    net = nets_by_name(drawings["m"])
    self.assertEqual(sorted(net), ["a", "z"])
    self.assertEqual(ends(net["a"]), [("g1", "a"), ("g1", "b"), ("p_a", "p"),
                                      ("p_y", "p")])
    self.assertEqual(ends(net["z"]), [("g1", "y"), ("p_z", "p")])
    self.assertIn("m line 4: a sensitivity list that is neither @(*) nor all "
                  "edges", " ".join(warnings))

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



# ---- behaviour -------------------------------------------------------------

SHIFT_REGISTER = """\
module shift_register_4bit (
    input  wire       clk,
    input  wire       reset,
    input  wire       serial_in,
    output reg  [3:0] q
);

always @(posedge clk or posedge reset) begin
    if (reset)
        q <= 4'b0000;
    else
        q <= {q[2:0], serial_in};
end

endmodule
"""

GATE_LOGIC = {
  "inv": lambda p: 1 - p["a"], "buf": lambda p: p["a"],
  "and2": lambda p: p["a"] & p["b"], "or2": lambda p: p["a"] | p["b"],
  "xor2": lambda p: p["a"] ^ p["b"], "nand2": lambda p: 1 - (p["a"] & p["b"]),
  "nor2": lambda p: 1 - (p["a"] | p["b"]), "xnor2": lambda p: 1 - (p["a"] ^ p["b"]),
  "mux2": lambda p: p["d1"] if p["s"] else p["d0"],
  "tie0": lambda p: 0, "tie1": lambda p: 1,
}


def simulate(doc, inputs):
  """What the drawn one-bit gates compute, net by net, for `inputs`
  ({port label: 0 or 1}). Flip-flop outputs can be given as inputs too."""
  cells = {cell["id"]: cell for cell in doc.cells}
  pin_net = {}
  for net in doc.nets:
    for end in [net["from"]] + net["to"]:
      pin_net[(end["cell"], end["pin"])] = net["id"]
  value = {}
  for cell in doc.cells:
    if cell["type"] == "port_in" and cell["label"] in inputs:
      value[pin_net[(cell["id"], "p")]] = inputs[cell["label"]]
  for (cell_id, pin), net in pin_net.items():
    if cells[cell_id]["type"] in ("dff", "dffr") and pin == "q":
      name = next(n["name"] for n in doc.nets if n["id"] == net)
      if name in inputs:
        value[net] = inputs[name]
  for _ in range(len(doc.cells)):
    for cell in doc.cells:
      logic = GATE_LOGIC.get(cell["type"])
      out = pin_net.get((cell["id"], "y"))
      if logic is None or out is None or out in value:
        continue
      pins = {}
      for pin in ("a", "b", "s", "d0", "d1"):
        net = pin_net.get((cell["id"], pin))
        if net is not None:
          if net not in value:
            break
          pins[pin] = value[net]
      else:
        value[out] = logic(pins)
  names = {net["id"]: net["name"] for net in doc.nets}
  return {names[net]: bit for net, bit in value.items()}


def output(doc, inputs, label):
  port = next(c for c in doc.cells if c.get("label") == label)
  net = next(n for n in doc.nets if any(t["cell"] == port["id"] for t in n["to"]))
  return simulate(doc, inputs).get(net["name"])


class TestBehaviour(unittest.TestCase):
  """rtl.py: the RTL people write, drawn without Yosys."""

  def draw(self, text):
    top, drawings, warnings = hdl.import_verilog(text, synth="builtin")
    return drawings[top], warnings

  def test_a_shift_register_is_a_chain_of_flip_flops(self):
    doc, warnings = self.draw(SHIFT_REGISTER)
    self.assertEqual(warnings, [])
    flops = {c["id"]: c for c in doc.cells if c["type"] == "dffr"}
    self.assertEqual(sorted(flops), ["q_0_reg", "q_1_reg", "q_2_reg", "q_3_reg"])
    source = {}
    for net in doc.nets:
      for end in net["to"]:
        source[(end["cell"], end["pin"])] = net["name"]
    self.assertEqual([source[("q_%d_reg" % i, "d")] for i in range(4)],
                     ["serial_in", "q[0]", "q[1]", "q[2]"])
    # posedge reset is active high; dffr's rn is active low: one inverter.
    self.assertEqual(set(source[("q_%d_reg" % i, "rn")] for i in range(4)),
                     {"reset_n"})
    self.assertEqual(set(source[("q_%d_reg" % i, "ck")] for i in range(4)),
                     {"clk"})
    # The bits meet the bus in one column, not one column per flip-flop.
    joins = [c["x"] for c in doc.cells if c["type"] == "bus_join"]
    self.assertEqual((len(joins), len(set(joins))), (4, 1), joins)
    registry = default_registry()
    self.assertEqual([str(i) for i in list(doc.validate(registry))
                      + list(drc.check(doc, registry)) if i.level == "error"], [])

  def test_logic_computes_what_the_verilog_says(self):
    doc, warnings = self.draw(
      "module m (input a, b, c, s, output y, z, w);\n"
      "  assign y = s ? a : (b & ~c);\n"
      "  assign z = !(a || b) ^ c;\n"
      "  assign w = {a, b} == 2'b10;\n"
      "endmodule\n")
    self.assertEqual(warnings, [])
    for bits in range(16):
      a, b, c, s = (bits >> 3) & 1, (bits >> 2) & 1, (bits >> 1) & 1, bits & 1
      inputs = {"a": a, "b": b, "c": c, "s": s}
      self.assertEqual(output(doc, inputs, "y"), a if s else (b & (1 - c)), inputs)
      self.assertEqual(output(doc, inputs, "z"), (1 - (a | b)) ^ c, inputs)
      self.assertEqual(output(doc, inputs, "w"), int(a == 1 and b == 0), inputs)

  def test_if_and_case_become_the_next_state_logic(self):
    doc, warnings = self.draw(
      "module fsm (input clk, rst_n, go, en, d, output reg state, output reg r);\n"
      "  localparam IDLE = 1'b0, RUN = 1'b1;\n"
      "  always @(posedge clk or negedge rst_n)\n"
      "    if (!rst_n) state <= IDLE;\n"
      "    else case (state)\n"
      "      IDLE: if (go) state <= RUN;\n"
      "      default: if (!go) state <= IDLE;\n"
      "    endcase\n"
      "  always @(posedge clk) if (en) r <= d;\n"
      "endmodule\n")
    self.assertEqual(warnings, [])
    types = {c["id"]: c["type"] for c in doc.cells}
    self.assertEqual((types["state_reg"], types["r_reg"]), ("dffr", "dff"))
    d_of = {}
    for net in doc.nets:
      for end in net["to"]:
        d_of[(end["cell"], end["pin"])] = net["name"]
    # negedge rst_n is already active low: straight onto rn.
    self.assertEqual(d_of[("state_reg", "rn")], "rst_n")
    for state in (0, 1):
      for go in (0, 1):
        got = simulate(doc, {"state": state, "go": go})[d_of[("state_reg", "d")]]
        self.assertEqual(got, go, (state, go))   # this machine follows go
    for r in (0, 1):
      for en in (0, 1):
        for d in (0, 1):
          got = simulate(doc, {"r": r, "en": en, "d": d})[d_of[("r_reg", "d")]]
          self.assertEqual(got, d if en else r, (r, en, d))

  def test_what_has_no_drawing_is_reported_with_its_line(self):
    _, warnings = self.draw(
      "module m (input clk, en, a, output reg [3:0] n, output reg l);\n"
      "  always @(posedge clk) n <= n + 1;\n"
      "  always @(*) if (en) l = a;\n"
      "endmodule\n")
    text = " ".join(warnings)
    self.assertIn("line 2: the operator +", text)
    self.assertIn("m line 3: l keeps its value on some path, which is a latch",
                  text)

  def test_directives_and_an_else_on_its_own_line_are_read(self):
    doc, _ = self.draw("`timescale 1ns/1ps\n" + SHIFT_REGISTER)
    self.assertEqual(len([c for c in doc.cells if c["type"] == "dffr"]), 4)


FEEDBACK = {
  "accumulate": """\
module acc (input clk, input rst_n, input en, input [1:0] d, output reg [1:0] s);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= 2'd0;
    else if (en) s <= s ^ d;
endmodule
""",
  "state machine": """\
module fsm (input clk, input rst_n, input a, input b, output reg [1:0] st,
            output busy);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= 2'd0;
    else case (st)
      2'd0: if (a) st <= 2'd1;
      2'd1: if (b) st <= 2'd2; else st <= 2'd0;
      2'd2: st <= 2'd3;
      default: st <= 2'd0;
    endcase
  assign busy = st[0] | st[1];
endmodule
""",
  "mixed": """\
module mix (input clk, rst_n, en, sel, input [1:0] a, b, input go,
            output [1:0] y, output reg [1:0] r, output reg busy);
  reg state;
  assign y = sel ? a : b;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) r <= 2'b00;
    else if (en) r <= a ^ b;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) state <= 1'b0;
    else case (state)
      1'b0: if (go) state <= 1'b1;
      1'b1: if (!go) state <= 1'b0;
    endcase
  always @(*) begin
    busy = 1'b0;
    if (state) busy = 1'b1;
  end
endmodule
""",
}


class TestFeedbackIsDrawnCleanly(unittest.TestCase):
  """Registers whose next state depends on themselves: every one is a wire
  looping back from a gate to the flip-flop feeding it. These drew with
  wire shorts and wires across cells until the router learned to go round
  a loop rather than straight back through it."""

  def test_each_design_passes_the_drcs(self):
    registry = default_registry()
    for name, text in sorted(FEEDBACK.items()):
      with self.subTest(design=name):
        top, drawings, _warnings = hdl.import_verilog(text, synth="builtin")
        doc = drawings[top]
        errors = [str(v) for v in drc.check(doc, registry)
                  if v.level == "error"]
        self.assertEqual(errors, [])


@unittest.skipUnless(yosys.available(), "yosys is not installed")
class TestYosys(unittest.TestCase):

  def test_behaviour_goes_through_yosys_when_it_is_there(self):
    top, drawings, warnings = hdl.import_verilog(SHIFT_REGISTER)
    self.assertTrue(warnings[0].startswith("note: synthesised with Yosys"), warnings)
    doc = drawings[top]
    self.assertEqual(len([c for c in doc.cells if c["type"] == "dffr"]), 4)
    registry = default_registry()
    self.assertEqual([str(i) for i in doc.validate(registry)
                      if i.level == "error"], [])

  def test_yosys_draws_arithmetic_the_built_in_reader_cannot(self):
    top, drawings, warnings = hdl.import_verilog(
      "module c (input clk, output reg [1:0] n);\n"
      "  always @(posedge clk) n <= n + 1;\nendmodule\n", synth="yosys")
    doc = drawings[top]
    self.assertEqual(len([c for c in doc.cells if c["type"] == "dff"]), 2)
    self.assertEqual(len(warnings), 1, warnings)

  def test_a_port_wired_straight_through_keeps_its_own_name(self):
    _, drawings, _ = hdl.import_verilog(
      "module m (input a, output y, input [1:0] v, output [1:0] w);\n"
      "  assign y = a;\n  assign w = v;\n"
      "  always @(*) begin end\nendmodule\n", synth="yosys")
    doc = drawings["m"]
    self.assertEqual(sorted(c["label"] for c in doc.cells),
                     ["a", "v[1:0]", "w[1:0]", "y"])
    self.assertEqual(sorted(ends(n) for n in doc.nets),
                     [[("p_a", "p"), ("p_y", "p")], [("p_v", "p"), ("p_w", "p")]])

  def test_a_netlist_is_not_resynthesised(self):
    _, drawings, warnings = hdl.import_verilog(FULL_ADDER)
    self.assertEqual(warnings, [])
    self.assertIn("x1", [c["id"] for c in drawings["full_adder"].cells])


class TestChoosingASynthesiser(unittest.TestCase):

  def test_insisting_on_yosys_without_it_is_an_error(self):
    with mock.patch.object(yosys, "available", return_value=None):
      with self.assertRaises(hdl.HdlError) as caught:
        hdl.import_verilog(SHIFT_REGISTER, synth="yosys")
    self.assertIn("yosys is not installed", str(caught.exception))

  def test_without_yosys_behaviour_is_drawn_by_rtl(self):
    with mock.patch.object(yosys, "available", return_value=None):
      _, drawings, warnings = hdl.import_verilog(SHIFT_REGISTER)
    self.assertEqual(warnings, [])

  def test_a_yosys_failure_falls_back_and_says_so(self):
    with mock.patch.object(yosys, "available", return_value="/bin/yosys"), \
         mock.patch.object(yosys, "synthesize",
                           side_effect=yosys.YosysError("boom")):
      _, drawings, warnings = hdl.import_verilog(SHIFT_REGISTER)
    self.assertIn("Yosys could not synthesise this (boom)", warnings[0])
    doc = drawings["shift_register_4bit"]
    self.assertEqual(len([c for c in doc.cells if c["type"] == "dffr"]), 4)


# ---- what the first review of the importer reported ------------------------

# The Verilog of the first review's fixtures
# (`docs/agent-work/latest-features-review/fixtures/`), written out here so
# these tests stand on their own. The first two were refused outright at
# 0f53171 -- `python -m drawlogic import` failed with
# `line 5: cannot read 'else q <= d'` -- though both are ordinary sequential
# Verilog; the third imported quietly with its expression thrown away.
ALWAYS_ELSE = """\
module seq2 (input clk, input rst, input d, output reg q);
  always @(posedge clk)
    if (rst) q <= 1'b0;
    else q <= d;
endmodule
"""

ALWAYS_CASE = """\
module seq (input clk, input [1:0] sel, output reg q);
  always @(posedge clk) begin
    case (sel)
      2'd0: q <= 1'b0;
      default: q <= 1'b1;
    endcase
  end
endmodule
"""

DECLARED_EXPRESSION = """\
module cont (input a, input b, output y);
  wire x = a & b;
  buf g (y, x);
endmodule
"""

ASSIGNED_EXPRESSION = """\
module cont (input a, input b, output x);
  assign x = a & b;
endmodule
"""


class TestWhatTheFirstReviewReported(unittest.TestCase):
  """The importer defects recorded in the first review, checked against the
  drawing the importer makes now rather than against the warning it used to
  raise. The warning-shaped probes that used to reproduce them are kept in
  that review's directory as history; they fail here, and rightly so."""

  def draw(self, text):
    top, drawings, warnings = hdl.import_verilog(text, synth="builtin")
    return drawings[top], warnings

  def driver_of(self, doc, cell_id, pin):
    """(source endpoint, net name) of whatever drives `cell_id`.`pin`."""
    for net in doc.nets:
      for end in net["to"]:
        if end["cell"] == cell_id and end["pin"] == pin:
          return net["from"], net["name"]
    return None, None

  def test_an_if_else_without_begin_end_computes_the_next_state(self):
    doc, warnings = self.draw(ALWAYS_ELSE)
    self.assertEqual(warnings, [])
    types = {cell["id"]: cell["type"] for cell in doc.cells}
    self.assertEqual(types.get("q_reg"), "dff")
    _source, next_state = self.driver_of(doc, "q_reg", "d")
    self.assertTrue(next_state, "the flip-flop's D pin is driven by nothing")
    for rst in (0, 1):
      for d in (0, 1):
        self.assertEqual(simulate(doc, {"rst": rst, "d": d})[next_state],
                         0 if rst else d, (rst, d))

  def test_a_case_statement_is_drawn_and_the_drawing_validates(self):
    doc, warnings = self.draw(ALWAYS_CASE)
    self.assertEqual(warnings, [])
    types = {cell["id"]: cell["type"] for cell in doc.cells}
    self.assertEqual(types.get("q_reg"), "dff")
    source, _net = self.driver_of(doc, "q_reg", "d")
    # The next state is the `case`, not the clock or the selector itself.
    self.assertNotIn(source["cell"], ("p_clk", "p_sel"), source)
    registry = default_registry()
    errors = [str(i) for i in list(doc.validate(registry))
              + list(drc.check(doc, registry)) if i.level == "error"]
    self.assertEqual(errors, [])

  def test_an_expression_in_a_declaration_reaches_the_drawing(self):
    """`wire x = a & b;` carries a driver. It used to be read as a plain
    declaration: the `&` was thrown away without a word and `x` was left
    with nothing driving it."""
    doc, warnings = self.draw(DECLARED_EXPRESSION)
    self.assertEqual(warnings, [])
    self.assertIn("and2", [cell["type"] for cell in doc.cells],
                  "the `&` was dropped: %r"
                  % sorted((c["id"], c["type"]) for c in doc.cells))
    for a in (0, 1):
      for b in (0, 1):
        self.assertEqual(simulate(doc, {"a": a, "b": b})["y"], a & b, (a, b))

  def test_a_starting_value_on_a_reg_is_reported_not_drawn(self):
    doc, warnings = self.draw("module m (input a, output y);\n"
                              "  reg r = 1'b0;\n"
                              "  assign y = a;\n"
                              "endmodule\n")
    self.assertIn("the starting value of r is not drawn", " ".join(warnings))

  def test_the_same_logic_as_a_bare_assign_is_drawn(self):
    """The positive control for the probe above: `assign x = a & b;` does
    become a gate, so the missing one there is the declaration form being
    misread, not logic the reader cannot draw."""
    doc, warnings = self.draw(ASSIGNED_EXPRESSION)
    self.assertEqual(warnings, [])
    self.assertIn("and2", [cell["type"] for cell in doc.cells])
    self.assertIn("x", [net["name"] for net in doc.nets])

  def test_a_statement_after_a_behavioural_block_is_still_an_error(self):
    """Reading behaviour must not quieten the reader: a module-level
    statement it cannot read is still an error naming its line."""
    text = ("module m (input clk, output reg y);\n"
            "  always @(posedge clk) y <= 1'b1;\n"
            "  oops nonsense;\n"
            "endmodule\n")
    with self.assertRaises(hdl.HdlError) as caught:
      self.draw(text)
    self.assertIn("line 3: cannot read 'oops nonsense'", str(caught.exception))

  def test_an_initial_block_is_reported_and_left_out(self):
    doc, warnings = self.draw("module m (input a, output y);\n"
                              "  assign y = a;\n"
                              "  initial $display(\"hi\");\n"
                              "endmodule\n")
    self.assertIn("m line 3: an initial block only sets up a simulation",
                  " ".join(warnings))
    self.assertEqual([c for c in doc.cells if c["type"] == "dff"], [])


if __name__ == "__main__":
  unittest.main()
