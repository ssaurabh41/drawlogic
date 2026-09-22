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

import io
import unittest

from drawlogic import drc, render_svg, routing, theme
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


def hand_shorted_nets():
  """in2 to U1.a and in1 to U1.b, with waypoints that put both down x=120."""
  return [
    {"id": "n1", "name": "s1", "from": {"cell": "in2", "pin": "p"},
     "to": [{"cell": "U1", "pin": "a", "waypoints": [[120, 205], [120, 110]]}]},
    {"id": "n2", "name": "s2", "from": {"cell": "in1", "pin": "p"},
     "to": [{"cell": "U1", "pin": "b", "waypoints": [[120, 105], [120, 130]]}]},
  ]


def _through(a, b, box):
  """True if the straight run a-b passes through the inside of a box."""
  x0, y0, x1, y1 = box
  lo_x, hi_x = sorted((a[0], b[0]))
  lo_y, hi_y = sorted((a[1], b[1]))
  return (max(x0, lo_x) < min(x1, hi_x) or x0 < lo_x < x1) and \
         (max(y0, lo_y) < min(y1, hi_y) or y0 < lo_y < y1)


def rules_in(violations):
  return set(v.rule for v in violations)


def only(violations, rule):
  return [v for v in violations if v.rule == rule]


class TestShorts(unittest.TestCase):
  """Two nets drawn as one. The faults that make a drawing lie."""

  def test_a_short_drawn_by_hand_is_reported(self):
    """Waypoints are honoured as drawn, so two wires put on one line by hand
    stay there -- and nothing in the file says these nets are connected while
    the picture says they are."""
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 200), gate("U1", 160, 100)],
      hand_shorted_nets())

    shorts = only(drc.check(doc), "wire-short")
    self.assertTrue(shorts, "two nets drawn on one line went unreported")
    self.assertEqual(shorts[0].level, "error")
    self.assertIn("n1", shorts[0].where)
    self.assertIn("n2", shorts[0].where)

  def test_the_same_two_nets_left_to_the_router_are_clean(self):
    """Without this the test above proves only that the checker says "short"
    a lot. The same two nets, with no waypoints, are routed apart."""
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 200), gate("U1", 160, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])

    self.assertEqual(only(drc.check(doc), "wire-short"), [])

  def test_two_nets_into_one_gate_must_not_merge(self):
    """The reported case: in1 to B and in2 to A, squeezed two columns from
    the gate. Both wires cross over on a row of their own, and their legs
    down to it used to share the stub column beside the gate -- drawn as one
    wire. A leg that would lie on another net now moves outward instead, and
    not through the cells at either end of its own net."""
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 160), gate("U1", 105, 100)],
      [wire("n1", "in2", "p", "U1", "a", "s1"),
       wire("n2", "in1", "p", "U1", "b", "s2")])

    self.assertEqual([v for v in drc.check(doc) if v.level == "error"], [])
    # The ports, which a moved leg used to run straight through. The gate is
    # left out: the ports sit so close that their own stubs reach into it,
    # which is this fixture's squeeze rather than anything a leg did.
    bodies = routing.body_boxes(doc, exclude={"U1"})
    for _net, branches in routing.route_all(doc):
      for points in branches:
        for a, b in zip(points[1:-2], points[2:-1]):
          for box in bodies:
            self.assertFalse(_through(a, b, box),
                             "a wire runs through a cell: %r-%r" % (a, b))

  def test_the_same_two_nets_with_room_are_clean(self):
    """The same drawing, given room: the wires cross and bridge, not merge."""
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


class TestParallelRuns(unittest.TestCase):
  """Two different nets running alongside each other.

  This rule had no test at all. Replacing `_check_wire_spacing` with a no-op
  left all 34 DRC tests green, so the whole rule -- the one the manual leads
  with -- could have been deleted without the suite noticing. The shorts
  tested elsewhere come from `_check_wire_contact`, a different checker that
  happens to catch the same drawings, which is what made the hole invisible.

  Coordinate endpoints rather than pins, so the distance under test is the one
  written here and not whatever the router decided.
  """

  def runs(self, gap):
    doc = new_document("parallel", 700, 400)
    doc.nets.extend([
      {"id": "n1", "name": "aa",
       "from": {"x": 100, "y": 200}, "to": [{"x": 600, "y": 200}]},
      {"id": "n2", "name": "bb",
       "from": {"x": 100, "y": 200 + gap}, "to": [{"x": 600, "y": 200 + gap}]},
    ])
    doc.normalize()
    return list(drc.check(doc))

  def test_two_nets_closer_than_the_gap_are_reported(self):
    found = only(self.runs(drc.WIRE_GAP - 3), "wire-spacing")
    self.assertTrue(found, "two nets 3 short of WIRE_GAP went unreported")
    self.assertEqual(found[0].level, "warning")
    self.assertIsNotNone(found[0].at, "nothing to walk to in the editor")

  def test_two_nets_a_clear_gap_apart_are_left_alone(self):
    """The negative control: without it the rule could fire on everything and
    still look like it worked."""
    self.assertEqual(only(self.runs(drc.WIRE_GAP * 2), "wire-spacing"), [])

  def test_lying_on_top_of_each_other_is_a_short_not_a_crowd(self):
    """Same measurement, different distance -- and a different severity, so
    the two ends of the rule are pinned separately."""
    found = only(self.runs(0), "wire-short")
    self.assertTrue(found)
    self.assertEqual(found[0].level, "error")
    self.assertEqual(only(self.runs(0), "wire-spacing"), [],
                     "a short should not also be reported as a crowd")

  def test_wires_that_only_cross_are_not_running_together(self):
    """Perpendicular wires share one point, not a run. Reporting those would
    make the rule fire on every ordinary drawing."""
    doc = new_document("crossing", 700, 400)
    doc.nets.extend([
      {"id": "h", "name": "aa",
       "from": {"x": 100, "y": 200}, "to": [{"x": 600, "y": 200}]},
      {"id": "v", "name": "bb",
       "from": {"x": 300, "y": 80}, "to": [{"x": 300, "y": 340}]},
    ])
    doc.normalize()
    self.assertEqual(only(drc.check(doc), "wire-spacing"), [])


class TestEveryCheckerIsReachable(unittest.TestCase):
  """Each checker `check()` runs must be the only reason some test passes.

  REVIEW.md claimed removing any one of them turned this file red. Eight did;
  `_check_wire_spacing` did not, because nothing here exercised it. The claim
  was checked by hand once and then drifted, so it is asserted here instead --
  the same mutation, run in a loop.
  """

  def checkers(self):
    import inspect
    import re
    source = inspect.getsource(drc.check)
    return re.findall(r"^\s+(_check_\w+)\(scene, report\)", source, re.M)

  def test_there_are_no_checkers_nothing_depends_on(self):
    names = self.checkers()
    self.assertGreaterEqual(len(names), 9, names)

    # Everything in this file except this test, which would recurse.
    cases = ["%s.%s" % (__name__, name) for name in sorted(globals())
             if name.startswith("Test") and name != type(self).__name__]

    unnoticed = []
    for name in names:
      original = getattr(drc, name)
      setattr(drc, name, lambda *args, **kwargs: None)
      try:
        # Rebuilt each time: a suite empties itself as it runs, so reusing one
        # would silently test nothing after the first pass.
        suite = unittest.defaultTestLoader.loadTestsFromNames(cases)
        result = unittest.TextTestRunner(
          stream=io.StringIO(), verbosity=0).run(suite)
        if result.wasSuccessful():
          unnoticed.append(name)
      finally:
        setattr(drc, name, original)

    self.assertEqual(
      unnoticed, [],
      "these checks could be deleted and this file would stay green: %s"
      % ", ".join(unnoticed))


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

  def test_close_crossings_still_get_two_separate_bridges(self):
    """Never merged into one. Two crossings are two crossings, and the
    drawing should say so."""
    import re
    svg = render_svg.render(self.crossed(310, 330))
    path = [p for p in re.findall(r'<path class="dl-net"[^>]*d="([^"]+)"', svg)
            if p.count("A") == 2][0]
    self.assertEqual(path.count("A"), 2, "the two bridges were merged")

  def test_a_crowded_bridge_narrows_to_leave_wire_showing(self):
    """A bridge cannot be moved -- it is drawn where the wires actually cross
    -- but how wide it is can be. Two crossings 20 apart would leave only 10
    units between two full-width bulges; narrowing them leaves the 12 the
    rule asks for."""
    import re
    svg = render_svg.render(self.crossed(310, 330))
    radii = [float(m) for m in re.findall(r"A([\d.]+) [\d.]+", svg)]
    self.assertTrue(radii)
    self.assertLess(max(radii), theme.HOP_RADIUS,
                    "a crowded bridge should be narrower than a lone one")
    flat = 330 - max(radii) - (310 + max(radii))
    self.assertGreaterEqual(round(flat, 3), drc.HOP_FLAT)

  def test_a_lone_bridge_keeps_its_full_width(self):
    """The negative control: narrowing must only happen where it is needed."""
    import re
    svg = render_svg.render(self.crossed(200, 460))
    radii = [float(m) for m in re.findall(r"A([\d.]+) [\d.]+", svg)]
    self.assertTrue(radii)
    self.assertEqual(max(radii), theme.HOP_RADIUS)

  def test_crossings_too_close_even_for_a_narrowed_bridge_are_reported(self):
    """Below HOP_GAP the renderer has run out of room: both bridges are at
    their smallest and there is still too little wire between them. That is
    what the rule is left to catch, and why it is not vacuous."""
    self.assertTrue(only(drc.check(self.crossed(310, 322)), "hop-spacing"))

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
    # The hand-drawn short, squeezed against the gate so warnings come too.
    doc = build(
      [port("in1", 60, 100), port("in2", 60, 200), gate("U1", 125, 100)],
      hand_shorted_nets())
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


class TestRouterUnderPressure(unittest.TestCase):
  """What the router does when it runs out of room.

  Measured with the DRCs rather than by naming coordinates: the claim is about
  the drawing being readable, not about any particular set of corridors.
  """

  def crossover(self, count, gate_x=220):
    """Every port crossing to the block at the opposite end.

    This is the shape that fills a corridor band: every vertical run overlaps
    every other one, so no two of them may share a corridor.
    """
    doc = new_document("crossover", 1000, 900)
    for index in range(count):
      doc.cells.append({"id": "in%d" % index, "type": "port_in", "x": 60,
                        "y": 100 + 60 * index, "label": "in%d" % index})
      doc.cells.append({"id": "U%d" % index, "type": "buf", "x": gate_x,
                        "y": 100 + 60 * (count - 1 - index)})
      doc.nets.append({"id": "n%d" % index, "name": "s%d" % index,
                       "from": {"cell": "in%d" % index, "pin": "p"},
                       "to": [{"cell": "U%d" % index, "pin": "a"}]})
    return doc

  def test_a_full_band_crowds_wires_rather_than_merging_them(self):
    """Eight wires through a band with room for five.

    The router used to fall straight back to the corridor it wanted once no
    well-separated one was left, which put wire after wire on the same line:
    six pairs of unrelated nets drawn as one. Crowded is a judgement about
    spacing; merged is the drawing claiming a connection nobody made, and the
    two are not the same failure.
    """
    for count in (4, 6, 8):
      with self.subTest(wires=count):
        found = drc.check(self.crossover(count))
        self.assertEqual(
          [str(v) for v in found if v.rule == "wire-short"], [],
          "%d wires through one band were drawn on top of each other" % count)

  def test_a_blocked_row_makes_the_wire_go_round_not_through(self):
    """A wire from a port to a block four columns away, with blocks standing
    on both pins' rows.

    No choice of crossover column helps, because those rows are the pins' own
    -- so the router used to draw the wire straight through the blocks, which
    reads as connecting to every one of them.
    """
    doc = build(
      [port("a", 60, 100), gate("U1", 200, 100, "xor2", "U1"),
       gate("U2", 340, 100, "buf", "U2"), gate("U3", 470, 100, "nand2", "U3"),
       gate("U4", 610, 100, "and2", "U4")],
      [wire("n", "a", "p", "U4", "b", "w")], width=900, height=500)

    crossed = [v for v in drc.check(doc) if v.rule == "wire-over-cell"]
    self.assertEqual([str(v) for v in crossed], [],
                     "the wire was drawn through the blocks in its way")

  def test_a_wire_keeps_off_an_instance_name(self):
    """A name is worse to cross than a body: a body can still be read around
    the wire, a word cannot. So the room a name takes is part of what the
    router steers round, not only something the DRCs complain about after."""
    doc = build(
      [port("a", 60, 120), gate("U1", 260, 140, "xor2", "U1"),
       gate("U2", 560, 140, "and2", "U2")],
      [wire("n", "a", "p", "U2", "b", "w")], width=900, height=500)

    self.assertEqual([str(v) for v in drc.check(doc)
                      if v.rule == "text-to-wire"], [],
                     "the wire was drawn through an instance name")

  def test_wires_still_spread_out_when_there_is_room(self):
    """The last resort must stay a last resort.

    With space to spare the corridors should be properly apart, not merely
    not-touching -- otherwise the new pass has quietly become the only one.
    Measured on the corridors themselves, since the runs into the pins sit at
    whatever the pins are and the router has no say in those.
    """
    doc = self.crossover(4, gate_x=520)
    corridors = sorted({round(point[0], 3)
                        for _net, branches in routing.route_all(doc)
                        for points in branches for point in points
                        if 80 < point[0] < 520})
    self.assertTrue(len(corridors) >= 2, "expected a corridor per wire")
    for first, second in zip(corridors, corridors[1:]):
      self.assertGreaterEqual(
        second - first, drc.WIRE_GAP,
        "corridors %g and %g are closer than two wires may sit with room "
        "to spare" % (first, second))


class TestOddDocuments(unittest.TestCase):
  """The checker runs on whatever the editor sends, not on tidy input.

  A properties panel does not type-check what was typed and a .dlg is a JSON
  file anyone may have edited, so a label can arrive as a number. The checker
  measuring how wide that text is called len() on an int and brought the whole
  Check down -- reported as an AttributeError from cell_label_box.
  """

  def labelled(self, label):
    doc = new_document("odd", 500, 350)
    doc.cells.append({"id": "U1", "type": "and2", "x": 80, "y": 80,
                      "label": label})
    doc.normalize()
    return doc

  def test_a_label_that_is_not_text_does_not_stop_the_check(self):
    for label in (123, 4.5, True, {"a": 1}, ["x"], None):
      with self.subTest(label=label):
        drc.check(self.labelled(label))

  def test_a_number_typed_as_a_name_is_kept_as_text(self):
    """Coerced rather than refused: `1` typed into the Name box is a name the
    user meant, and a drawing that will not open is the worse answer."""
    self.assertEqual(self.labelled(123).cells[0]["label"], "123")

  def test_something_with_no_sensible_text_is_dropped(self):
    self.assertIsNone(self.labelled({"a": 1}).cells[0].get("label"))

  def test_shape_text_gets_the_same_treatment(self):
    doc = new_document("odd", 500, 350)
    doc.shapes.append({"id": "s1", "kind": "text", "x": 20, "y": 20,
                       "text": 42})
    doc.normalize()
    self.assertEqual(doc.shapes[0]["text"], "42")
    drc.check(doc)


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


class TestLegsGetOutOfEachOthersWay(unittest.TestCase):
  """A corridor is only as good as the legs that lead into it.

  `clear_at` has always asked whether all three legs of a Z route miss the
  cells. `free_at` asked only whether the corridor missed other wires, so the
  router would happily choose a column with nothing in it and lay the leg
  leading into it straight along another net's leg. That overlap is a
  `wire-short`: two unrelated nets drawn as one wire.

  It accounted for 31 of the 46 DRC errors auto layout left on the benchmark
  corpus, and for eight of the nine on its densest drawing.
  """

  def three_rows(self):
    """A leaves row 0 and arrives at row 1; B leaves row 1 and arrives at 2.

    At row 1 one net arrives and another departs, so their legs share that
    height and B's corridor has to sit left of A's. One constraint, pointing
    one way: there is an answer, and the router has only to find it.
    """
    doc = new_document("legs", 900, 500)
    for index in range(3):
      doc.cells.append({"id": "s%d" % index, "type": "port_in",
                        "x": 100, "y": 120 + index * 70, "label": "i%d" % index})
      doc.cells.append({"id": "d%d" % index, "type": "port_out",
                        "x": 520, "y": 120 + index * 70, "label": "o%d" % index})
    doc.nets.append({"id": "a", "name": "a", "from": {"cell": "s0", "pin": "p"},
                     "to": [{"cell": "d1", "pin": "p"}]})
    doc.nets.append({"id": "b", "name": "b", "from": {"cell": "s1", "pin": "p"},
                     "to": [{"cell": "d2", "pin": "p"}]})
    doc.normalize()
    return doc

  def test_two_nets_sharing_a_row_are_not_drawn_as_one(self):
    self.assertEqual(only(drc.check(self.three_rows()), "wire-short"), [],
                     "a leg was laid along another net's leg")

  def test_the_drawing_is_clean_altogether(self):
    """Not just free of shorts: the fix must not trade one error for another."""
    errors = [v for v in drc.check(self.three_rows()) if v.level == "error"]
    self.assertEqual([str(e) for e in errors], [])

  def test_the_corridors_end_up_in_the_order_the_rows_demand(self):
    """Stated as the constraint rather than as a coordinate, so the test says
    why the answer is right instead of only what it was on the day."""
    doc = self.three_rows()
    corridors = {}
    for net, branches in routing.route_all(doc, default_registry()):
      for points in branches:
        verticals = [p[0] for p, q in zip(points, points[1:])
                     if abs(p[0] - q[0]) < 1e-6]
        if verticals:
          corridors[net["id"]] = verticals[0]
    self.assertIn("a", corridors)
    self.assertIn("b", corridors)
    self.assertLess(corridors["b"], corridors["a"],
                    "b leaves row 1 and a arrives at it, so b must pass first")

  def test_a_clear_drawing_still_spreads_its_wires_out(self):
    """The guard on the guard. Demanding full separation of the legs made the
    search refuse well-spaced corridors over what is only a warning and settle
    for a cramped one, so the legs are asked the weaker question: not on top
    of each other, rather than far enough apart to read as separate."""
    doc = self.three_rows()
    corridors = sorted(
      p[0] for _net, branches in routing.route_all(doc, default_registry())
      for points in branches
      for p, q in zip(points, points[1:]) if abs(p[0] - q[0]) < 1e-6)
    for one, two in zip(corridors, corridors[1:]):
      self.assertGreaterEqual(
        abs(two - one), drc.WIRE_GAP,
        "corridors %g and %g are closer than two wires need, with room to "
        "spare" % (one, two))



if __name__ == "__main__":
  unittest.main()
