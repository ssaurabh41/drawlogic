"""Design rule checks: does the drawing say what the file says?

Every check here is built the same way -- a small drawing made to break one
rule, and the assertion that the rule finds it. The other half matters just as
much and is easy to leave out: a drawing that does *not* break the rule must
come back clean, because a check that fires on everything tells you nothing.

The headline case is `test_two_nets_into_one_gate_must_not_merge`. It is the
one a real user reported: two separate signals into the two inputs of one
gate, drawn as a single line with a junction dot on it, so the drawing claims
a connection the file has never heard of.

Usage:

    python3 -m unittest tests.test_drc
"""

import unittest

from drawlogic import drc
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry

from tests import open_example


def build(cells, nets, width=600, height=420, title="drc"):
  """A drawing from plain lists, so each test reads as the picture it makes."""
  doc = new_document(title, width, height)
  doc.cells.extend(cells)
  doc.nets.extend(nets)
  return doc


def port(cell_id, x, y, label=None, kind="port_in"):
  return {"id": cell_id, "type": kind, "x": x, "y": y,
          "label": label if label is not None else cell_id}


def gate(cell_id, x, y, kind="and2", label=None):
  spec = {"id": cell_id, "type": kind, "x": x, "y": y}
  if label is not None:
    spec["label"] = label
  return spec


def wire(net_id, source, source_pin, target, target_pin, name=None):
  net = {"id": net_id, "from": {"cell": source, "pin": source_pin},
         "to": [{"cell": target, "pin": target_pin}]}
  if name:
    net["name"] = name
  return net


def rules_in(violations):
  return set(v.rule for v in violations)


def only(violations, rule):
  return [v for v in violations if v.rule == rule]


class TestShorts(unittest.TestCase):
  """Two nets drawn as one. The faults that make a drawing lie."""

  def test_two_nets_into_one_gate_must_not_merge(self):
    """The reported case: in1 to B and in2 to A, drawn as one wire.

    The ports sit two columns from the gate with no room between them for two
    corridors, so both wires take the same one. Nothing in the file says these
    nets are connected; the picture says they are.
    """
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 105, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])

    shorts = only(drc.check(doc), "wire-short")
    self.assertTrue(shorts, "two nets drawn on one line went unreported")
    self.assertEqual(shorts[0].level, "error")
    self.assertIn("n1", shorts[0].where)
    self.assertIn("n2", shorts[0].where)

  def test_the_same_two_nets_with_room_are_clean(self):
    """The same drawing, given room: the wires cross and bridge, not merge.

    Without this the test above proves only that the checker says "short" a
    lot. The difference between the two is the gap between the columns.
    """
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 260, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])

    self.assertEqual(only(drc.check(doc), "wire-short"), [])

  def test_two_nets_off_one_pin_are_a_rail_not_a_short(self):
    """One pin driving two loads is one signal, so the overlap is the point.

    This is the exemption that stops the check from firing on every fan-out,
    and it is the one most likely to be broken by tightening the rule.
    """
    doc = build(
      [port("a", 60, 200), gate("U1", 300, 100), gate("U2", 300, 260)],
      [wire("n1", "a", "p", "U1", "a"), wire("n2", "a", "p", "U2", "a")])

    self.assertEqual(only(drc.check(doc), "wire-short"), [])


  def test_a_wire_end_dropped_on_another_wire_is_an_error(self):
    """The other way a drawing invents a connection: a wire end left on a
    wire. Three ends at a point get a junction dot, and a junction dot means
    connected -- so this is the most convincing lie a drawing can tell, since
    a dot is exactly what a real connection looks like.
    """
    doc = build(
      [port("a", 40, 100), port("y", 500, 360, kind="port_out"),
       port("b", 40, 250)],
      [], width=600, height=460)
    doc.nets.extend([
      {"id": "h", "name": "h", "from": {"cell": "a", "pin": "p"},
       "to": [{"cell": "y", "pin": "p",
               "waypoints": [[300, 105], [300, 365]]}]},
      # Dragged out from a port and let go on top of the other wire.
      {"id": "t", "name": "t", "from": {"cell": "b", "pin": "p"},
       "to": [{"x": 300, "y": 255}]},
    ])

    found = only(drc.check(doc), "wire-short")
    self.assertTrue(found, "a wire ending on another net went unreported")
    self.assertIn("ends on the middle of", found[0].message)

  def test_a_crossing_with_no_bridge_is_an_error(self):
    """The renderer skips a bridge whose crossing lands on a wire corner --
    including a third net's corner, which has nothing to do with either wire.
    That leaves two nets meeting at a bare point, which is what a connection
    looks like.

    A third net can only have a corner on a crossing by running along both
    wires to get there, so this drawing is a mess in several other ways too.
    The rule earns its place by naming the pair that now reads as joined,
    which none of the other complaints does.
    """
    doc = build(
      [port("a", 40, 200), port("y", 600, 200, kind="port_out"),
       port("b", 280, 40), port("c", 280, 420, kind="port_out"),
       port("d", 40, 340), port("e", 600, 60, kind="port_out")],
      [wire("h", "a", "p", "y", "p", "h")], width=700, height=500)
    doc.nets.extend([
      {"id": "v", "name": "v", "from": {"cell": "b", "pin": "p"},
       "to": [{"cell": "c", "pin": "p",
               "waypoints": [[300, 45], [300, 425]]}]},
      {"id": "k", "name": "k", "from": {"cell": "d", "pin": "p"},
       "to": [{"cell": "e", "pin": "p",
               "waypoints": [[300, 345], [300, 205], [600, 205], [600, 65]]}]},
    ])

    found = only(drc.check(doc), "wire-crossing")
    self.assertTrue(found, "an unbridged crossing went unreported")
    self.assertEqual(found[0].level, "error")
    self.assertIn("h", found[0].where)
    self.assertIn("v", found[0].where)


class TestWiresAndCells(unittest.TestCase):
  """Wires against the blocks they pass."""

  def test_a_wire_dragged_across_a_body_is_an_error(self):
    """A wire over a gate reads either as stopping there or as passing
    behind it, and the file does not say which.

    Dragged there on purpose, with waypoints, because the router will not do
    this by itself -- which is the point: this rule is for hand-drawn sheets,
    where a dragged wire segment is exactly how a wire ends up behind a gate.
    """
    net = wire("n1", "a", "p", "y", "p")
    net["to"][0]["waypoints"] = [[280, 125], [280, 305]]
    doc = build(
      [port("a", 60, 120, kind="port_in"), port("y", 520, 300, kind="port_out"),
       gate("U1", 250, 180, label="U1")],
      [net])

    crossed = only(drc.check(doc), "wire-over-cell")
    self.assertTrue(crossed, "a wire drawn across a gate went unreported")
    self.assertEqual(crossed[0].level, "error")
    self.assertIn("U1", crossed[0].where)

  def test_the_same_wire_left_to_the_router_is_clean(self):
    """Without the waypoints the router goes round, and nothing is reported.

    So the rule above is measuring the wire, not merely the presence of a
    gate somewhere near it.
    """
    doc = build(
      [port("a", 60, 120, kind="port_in"), port("y", 520, 300, kind="port_out"),
       gate("U1", 250, 180, label="U1")],
      [wire("n1", "a", "p", "y", "p")])
    self.assertEqual(rules_in(drc.check(doc)) & {"wire-over-cell",
                                                 "wire-to-cell"}, set())


class TestWireShape(unittest.TestCase):
  """Jogs too short to read as deliberate."""

  def test_a_few_units_of_step_is_reported(self):
    """Two ports five apart make the wire step five units halfway along. It
    does not read as going round something; it reads as having missed."""
    doc = build([port("a", 40, 200), port("y", 600, 205, kind="port_out")],
                [wire("n", "a", "p", "y", "p")], width=700, height=420)
    found = only(drc.check(doc), "wire-jog")
    self.assertTrue(found, "a five-unit jog went unreported")

  def test_two_ports_in_line_need_no_jog(self):
    doc = build([port("a", 40, 200), port("y", 600, 200, kind="port_out")],
                [wire("n", "a", "p", "y", "p")], width=700, height=420)
    self.assertEqual(only(drc.check(doc), "wire-jog"), [])


class TestSpacing(unittest.TestCase):
  """The distances that decide whether two things read as two."""

  def test_cells_closer_than_the_floor_are_reported(self):
    doc = build([gate("U1", 200, 200), gate("U2", 200, 250)], [])
    found = only(drc.check(doc), "cell-spacing")
    self.assertTrue(found)
    self.assertEqual(found[0].level, "warning")

  def test_cells_a_gap_apart_are_clean(self):
    doc = build([gate("U1", 200, 100), gate("U2", 200, 300)], [])
    self.assertEqual(only(drc.check(doc), "cell-spacing"), [])

  def test_ports_are_held_to_their_own_rule(self):
    """A port is smaller than a gate, so it gets a rule of its own rather
    than the one written for parts with bodies."""
    doc = build([port("a", 100, 200), port("b", 100, 215)], [])
    self.assertTrue(only(drc.check(doc), "port-spacing"))
    self.assertEqual(only(drc.check(doc), "cell-spacing"), [],
                     "two ports were measured by the rule for gates")

  def test_a_port_pressed_against_a_gate_is_reported(self):
    doc = build([port("a", 200, 205), gate("U1", 235, 190)], [])
    self.assertTrue(only(drc.check(doc), "port-to-cell"))


class TestText(unittest.TestCase):
  """Names against wires, bodies and other names."""

  def test_an_instance_name_under_a_neighbour_is_reported(self):
    """Stacked cells put each name against the body above it, so the name
    reads as belonging to the wrong cell."""
    doc = build([gate("U1", 200, 200, label="U1"),
                 gate("U2", 200, 250, label="U2")], [])
    self.assertTrue(only(drc.check(doc), "text-to-cell"))

  def test_names_far_apart_are_clean(self):
    doc = build([gate("U1", 100, 100, label="U1"),
                 gate("U2", 400, 320, label="U2")], [])
    self.assertEqual(rules_in(drc.check(doc)) & {"text-to-cell",
                                                 "text-to-text"}, set())


class TestHops(unittest.TestCase):
  """The little bridges that say a crossing is not a connection.

  A bridge only reads as "not connected" when there is flat wire either side
  of it, so these rules are about what surrounds a bridge rather than about
  the bridge itself.
  """

  def crossed(self, first, second):
    """One wire crossed by two others, pinned to the given x positions."""
    doc = build(
      [port("a", 40, 240), port("y", 620, 240, kind="port_out"),
       port("b", 180, 60), port("c", 180, 420, kind="port_out"),
       port("d", 440, 60), port("e", 440, 420, kind="port_out")],
      [wire("h", "a", "p", "y", "p")], width=700, height=500)
    for net_id, source, target, x in (("v1", "b", "c", first),
                                      ("v2", "d", "e", second)):
      doc.nets.append({
        "id": net_id, "from": {"cell": source, "pin": "p"},
        "to": [{"cell": target, "pin": "p",
                "waypoints": [[x, 120], [x, 400]]}]})
    return doc

  def test_two_bridges_on_top_of_each_other_are_reported(self):
    found = only(drc.check(self.crossed(310, 322)), "hop-spacing")
    self.assertTrue(found, "two bridges 12 apart merge and went unreported")

  def test_two_bridges_with_wire_between_them_are_clean(self):
    self.assertEqual(only(drc.check(self.crossed(280, 380)), "hop-spacing"), [])

  def test_a_bridge_on_a_corner_is_reported(self):
    """A bridge over a corner deforms it, and a deformed corner is how a
    junction is drawn -- so the reader loses the connection as well."""
    doc = build(
      [port("a", 40, 200), port("y", 520, 200, kind="port_out"),
       port("b", 210, 60), port("c", 300, 360, kind="port_out")],
      [wire("h", "a", "p", "y", "p"),
       wire("v", "b", "p", "c", "p")], width=600, height=440)
    # The bent wire turns 10 from where it crosses the straight one.
    doc.nets[1]["to"][0]["waypoints"] = [[215, 195], [215, 215], [300, 215]]
    self.assertTrue(only(drc.check(doc), "hop-to-corner"))


class TestSheet(unittest.TestCase):
  """Drawing against the edge of the paper."""

  def test_a_cell_off_the_sheet_is_an_error(self):
    """The exporter crops to the sheet, so this part is not in the file
    anyone else opens."""
    doc = build([gate("U1", 580, 200)], [], width=600, height=420)
    found = only(drc.check(doc), "off-sheet")
    self.assertTrue(found)
    self.assertEqual(found[0].level, "error")

  def test_a_cell_just_inside_the_edge_is_a_warning(self):
    doc = build([gate("U1", 10, 200)], [], width=600, height=420)
    self.assertTrue(only(drc.check(doc), "sheet-edge"))
    self.assertEqual(only(drc.check(doc), "off-sheet"), [])


class TestViolations(unittest.TestCase):
  """What a violation carries, since the editor and the CLI both read it."""

  def test_a_violation_reads_like_a_validate_issue(self):
    """doc.Issue and Violation are printed by the same loop in cli.py, so
    they have to carry the same three fields."""
    doc = build([gate("U1", 200, 200), gate("U2", 200, 250)], [])
    found = drc.check(doc)[0]
    for field in ("level", "where", "message"):
      self.assertTrue(getattr(found, field), "%s is empty" % field)
    self.assertIn(found.level, ("error", "warning"))

  def test_every_violation_says_where_to_look(self):
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 105, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])
    for violation in drc.check(doc):
      self.assertIsNotNone(violation.at,
                           "%s gives the reader nowhere to look" % violation.rule)
      self.assertEqual(len(violation.at), 2)

  def test_a_violation_survives_the_trip_to_the_browser(self):
    doc = build([gate("U1", 200, 200), gate("U2", 200, 250)], [])
    data = drc.check(doc)[0].as_data()
    self.assertEqual(set(data), {"rule", "level", "where", "message", "at"})
    self.assertIsInstance(data["at"], list)

  def test_errors_are_listed_before_warnings(self):
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 105, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])
    levels = [v.level for v in drc.check(doc)]
    self.assertIn("error", levels)
    self.assertEqual(levels, sorted(levels, key=lambda l: l != "error"),
                     "warnings were mixed in among the errors")

  def test_one_pair_is_reported_once(self):
    """A crowded wire is one problem to fix, not one per segment."""
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 105, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])
    pairs = [v.where for v in drc.check(doc) if v.rule == "wire-short"]
    self.assertEqual(len(pairs), len(set(pairs)))


class TestExamples(unittest.TestCase):
  """The drawings shipped with the project are the drawings people copy."""

  EXAMPLES = ("alu_slice", "cdc_fifo", "dff_slice", "fifo_top", "mac_pipe",
              "soc_top", "spi_master")

  def test_no_example_has_a_drc_error(self):
    """Warnings are judgements about spacing and some are worth living with.
    An error is the drawing saying something untrue, and an example that does
    that teaches it to everyone who opens it.
    """
    for name in self.EXAMPLES:
      with self.subTest(example=name):
        doc, registry, _ = open_example("examples/%s.dlg" % name)
        errors = [v for v in drc.check(doc, registry) if v.level == "error"]
        self.assertEqual(
          [str(e) for e in errors], [],
          "%s has DRC errors; fix the drawing, not the rule" % name)


if __name__ == "__main__":
  unittest.main()
