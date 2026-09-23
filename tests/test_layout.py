"""Laying a drawing out from what it is wired to.

The thing worth guarding is not any particular arrangement -- there are many
good ones -- but the properties that make an arrangement usable: signal flows
left to right, nothing lands on top of anything else, the same input always
gives the same answer, and running it on its own output changes nothing.

That last one matters more than it sounds. A layout that keeps shuffling means
the user can never tell whether the button did anything.

Usage:

    python3 -m unittest tests.test_layout
"""

import copy
import random
import unittest

from drawlogic import drc, layout, routing
from drawlogic.doc import Document, loads_of, new_document
from drawlogic.symbols import default_registry

from tests import ROOT, open_example

import os


def chain(length=4):
  """A port driving a row of inverters into an output port."""
  doc = new_document("chain", 900, 400)
  doc.cells.append({"id": "pin", "type": "port_in", "x": 40, "y": 40,
                    "label": "a"})
  for index in range(length):
    doc.cells.append({"id": "u%d" % index, "type": "inv",
                      "x": 200 + index * 10, "y": 200 - index * 30})
  doc.cells.append({"id": "pout", "type": "port_out", "x": 60, "y": 300,
                    "label": "y"})

  links = [("pin", "p", "u0", "a")]
  for index in range(length - 1):
    links.append(("u%d" % index, "y", "u%d" % (index + 1), "a"))
  links.append(("u%d" % (length - 1), "y", "pout", "p"))
  for index, (source, source_pin, target, target_pin) in enumerate(links, 1):
    doc.nets.append({"id": "n%d" % index, "name": None,
                     "from": {"cell": source, "pin": source_pin},
                     "to": {"cell": target, "pin": target_pin},
                     "waypoints": [], "style": {}})
  doc.normalize()
  return doc


def scramble(doc, seed=1):
  random.seed(seed)
  for cell in doc.cells:
    cell["x"] = random.randrange(20, 1400, 10)
    cell["y"] = random.randrange(20, 800, 10)
  return doc


def boxes(doc, registry):
  return [layout._box(registry, doc, cell) for cell in doc.cells]


def overlapping(doc, registry):
  found = []
  placed = list(zip(doc.cells, boxes(doc, registry)))
  for index, (cell, box) in enumerate(placed):
    for other_cell, other in placed[index + 1:]:
      if not (box[0] + box[2] <= other[0] or other[0] + other[2] <= box[0]
              or box[1] + box[3] <= other[1] or other[1] + other[3] <= box[1]):
        found.append((cell["id"], other_cell["id"]))
  return found


def _straight(routes):
  """How many branches run dead straight, and how many there are."""
  branches = [points for _, all_of_them in routes for points in all_of_them]
  return sum(1 for points in branches if len(points) == 2), len(branches)


def positions(doc):
  return [(c["id"], round(c["x"], 3), round(c["y"], 3)) for c in doc.cells]


class TestFlow(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_a_chain_comes_out_in_order_left_to_right(self):
    doc = scramble(chain())
    layout.arrange(doc, self.registry)
    order = sorted(doc.cells, key=lambda c: c["x"])
    self.assertEqual([c["id"] for c in order],
                     ["pin", "u0", "u1", "u2", "u3", "pout"])

  def test_a_driver_always_sits_left_of_what_it_drives(self):
    doc = scramble(chain(6))
    layout.arrange(doc, self.registry)
    by_id = {c["id"]: c for c in doc.cells}
    for net in doc.nets:
      source = by_id[net["from"]["cell"]]
      for load in loads_of(net):
        target = by_id[load["cell"]]
        self.assertLess(source["x"], target["x"],
                        "%s should sit left of %s"
                        % (source["id"], target["id"]))

  def test_output_ports_line_up_on_the_right_edge(self):
    doc = new_document("fan", 900, 400)
    doc.cells.append({"id": "pin", "type": "port_in", "x": 40, "y": 40})
    doc.cells.append({"id": "u1", "type": "inv", "x": 200, "y": 40})
    doc.cells.append({"id": "u2", "type": "buf", "x": 400, "y": 200})
    for index, (a, ap, b, bp) in enumerate(
        [("pin", "p", "u1", "a"), ("u1", "y", "u2", "a"),
         ("u1", "y", "o1", "p"), ("u2", "y", "o2", "p")], 1):
      doc.nets.append({"id": "n%d" % index, "name": None,
                       "from": {"cell": a, "pin": ap},
                       "to": {"cell": b, "pin": bp},
                       "waypoints": [], "style": {}})
    for name, y in (("o1", 40), ("o2", 200)):
      doc.cells.append({"id": name, "type": "port_out", "x": 600, "y": y})
    doc.normalize()

    layout.arrange(doc, self.registry)
    by_id = {c["id"]: c for c in doc.cells}
    # o1 is driven one step earlier than o2, but both are outputs and both
    # belong on the edge, or the sheet ends in a staircase.
    self.assertEqual(by_id["o1"]["x"], by_id["o2"]["x"])


class TestItStaysPut(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_the_same_drawing_always_lays_out_the_same_way(self):
    first = scramble(chain(5), seed=3)
    second = copy.deepcopy(first)
    layout.arrange(first, self.registry)
    layout.arrange(second, self.registry)
    self.assertEqual(positions(first), positions(second))

  def test_laying_out_a_laid_out_drawing_changes_nothing(self):
    # Otherwise there is no way to tell whether the button did anything.
    doc = scramble(chain(5), seed=4)
    layout.arrange(doc, self.registry)
    once = positions(doc)
    layout.arrange(doc, self.registry)
    self.assertEqual(positions(doc), once)

  def test_every_example_settles_after_one_pass(self):
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        layout.arrange(doc, registry)
        once = positions(doc)
        layout.arrange(doc, registry)
        self.assertEqual(positions(doc), once)


class TestNothingLandsOnAnythingElse(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_no_two_cells_overlap(self):
    doc = scramble(chain(7), seed=5)
    layout.arrange(doc, self.registry)
    self.assertEqual(overlapping(doc, self.registry), [])

  def test_no_two_cells_overlap_in_any_example(self):
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        layout.arrange(doc, registry)
        self.assertEqual(overlapping(doc, registry), [])

  def test_the_sheet_grows_to_hold_the_result(self):
    doc = scramble(chain(8), seed=6)
    layout.arrange(doc, self.registry)
    for cell, box in zip(doc.cells, boxes(doc, self.registry)):
      self.assertLessEqual(box[0] + box[2], doc.canvas["width"], cell["id"])
      self.assertLessEqual(box[1] + box[3], doc.canvas["height"], cell["id"])


class TestWhatItTidiesAway(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_waypoints_are_dropped(self):
    # A waypoint is a coordinate on the old sheet. Left in place it names
    # somewhere with nothing at it, and the wire dutifully goes there.
    doc = chain(3)
    loads_of(doc.nets[0])[0]["waypoints"] = [[700, 700]]
    layout.arrange(doc, self.registry)
    for net in doc.nets:
      for load in loads_of(net):
        self.assertEqual(load["waypoints"], [])

  def test_cells_are_turned_to_face_forward(self):
    doc = chain(3)
    doc.cells[1]["mirror"] = True
    doc.cells[2]["rotate"] = 90
    layout.arrange(doc, self.registry)
    self.assertEqual([c.get("mirror") for c in doc.cells], [False] * len(doc.cells))
    self.assertEqual([c.get("rotate") for c in doc.cells], [0] * len(doc.cells))


class TestAwkwardDrawings(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_a_feedback_loop_is_reported_rather_than_followed(self):
    doc = chain(3)
    doc.nets.append({"id": "loop", "name": None,
                     "from": {"cell": "u2", "pin": "y"},
                     "to": {"cell": "u0", "pin": "a"},
                     "waypoints": [], "style": {}})
    doc.normalize()
    result = layout.arrange(doc, self.registry)
    self.assertEqual(result.feedback, 1)
    self.assertIn("feedback", str(result))

  def test_two_cells_wired_to_each_other_do_not_hang_it(self):
    doc = new_document("pair", 600, 300)
    doc.cells.append({"id": "a", "type": "inv", "x": 100, "y": 100})
    doc.cells.append({"id": "b", "type": "inv", "x": 300, "y": 100})
    doc.nets.append({"id": "n1", "name": None, "from": {"cell": "a", "pin": "y"},
                     "to": {"cell": "b", "pin": "a"}, "waypoints": [], "style": {}})
    doc.nets.append({"id": "n2", "name": None, "from": {"cell": "b", "pin": "y"},
                     "to": {"cell": "a", "pin": "a"}, "waypoints": [], "style": {}})
    doc.normalize()
    result = layout.arrange(doc, self.registry)
    self.assertEqual(result.feedback, 1)

  def test_a_drawing_with_no_wires_still_lays_out(self):
    doc = new_document("loose", 600, 300)
    for index in range(4):
      doc.cells.append({"id": "u%d" % index, "type": "inv", "x": 40, "y": 40})
    doc.normalize()
    layout.arrange(doc, self.registry)
    self.assertEqual(overlapping(doc, self.registry), [])

  def test_an_empty_drawing_is_not_an_error(self):
    doc = new_document("empty", 400, 300)
    doc.normalize()
    result = layout.arrange(doc, self.registry)
    self.assertEqual(result.cells, 0)


class TestItActuallyHelps(unittest.TestCase):
  """The point of all this: wires that run straight."""

  def test_a_scrambled_drawing_comes_back_with_straight_wires(self):
    for name in ("cdc_fifo", "mac_pipe", "spi_master"):
      with self.subTest(example=name):
        doc, registry, _ = open_example(
          os.path.join(ROOT, "examples", name + ".dlg"))
        scramble(doc, seed=9)
        straight_before, total = _straight(routing.route_all(doc, registry))
        layout.arrange(doc, registry)
        straight_after, total = _straight(routing.route_all(doc, registry))

        self.assertGreater(straight_after, straight_before,
                           "%s: laying out should straighten wires" % name)
        self.assertGreater(straight_after, total * 0.2,
                           "%s: only %d of %d branches run straight"
                           % (name, straight_after, total))


class TestOrderingChoice(unittest.TestCase):
  """Following a wire through the columns it skips, and picking a winner."""

  def test_a_wire_that_skips_a_column_gets_stand_ins(self):
    ranks = {"a": 0, "b": 3}
    linked, extra = layout._span_chain([("a", "b", None, None)], ranks)
    self.assertEqual(sorted(extra.values()), [1, 2],
                     "a wire spanning three columns needs a stand-in in each "
                     "column it passes through")
    self.assertEqual(len(linked), 3, "the chain should be a -> s1 -> s2 -> b")

  def test_a_wire_to_the_next_column_gets_none(self):
    linked, extra = layout._span_chain([("a", "b", None, None)], {"a": 0, "b": 1})
    self.assertEqual(extra, {}, "the sweep already sees an adjacent column")
    self.assertEqual(linked, [("a", "b")])

  def test_crossings_are_counted(self):
    # One horizontal and one vertical run of different nets, meeting in the
    # middle: exactly one crossing. Same net, or parallel runs: none.
    crossing = [("n1", (0, 10), (20, 10)), ("n2", (10, 0), (10, 20))]
    self.assertEqual(layout._crossings(crossing), 1)
    same_net = [("n1", (0, 10), (20, 10)), ("n1", (10, 0), (10, 20))]
    self.assertEqual(layout._crossings(same_net), 0)
    parallel = [("n1", (0, 10), (20, 10)), ("n2", (0, 30), (20, 30))]
    self.assertEqual(layout._crossings(parallel), 0)

  def test_it_keeps_the_better_of_the_two_orderings(self):
    """Whichever way it goes, it is never worse than both tried alone.

    Stand-ins help some drawings and hurt others, which is why the layout
    tries both. The guarantee worth testing is that the result is at least as
    good as the better one, not that either particular one wins.
    """
    for name in ("alu_slice", "cdc_fifo", "mac_pipe"):
      with self.subTest(example=name):
        path = os.path.join(ROOT, "examples", name + ".dlg")
        scores = []
        for spans in (True, False):
          doc, registry, _ = open_example(path)
          cells = [c for c in doc.cells if registry.for_cell(c) is not None]
          layout._face_forward(cells)
          layout._forget_waypoints(doc)
          edges, _feedback = layout._edges(doc, registry, cells)
          ranks = layout._ranks(doc, registry, cells, edges)
          order = layout._order(cells, edges, ranks, spans=spans)
          layout._place(doc, registry, cells, edges, ranks, order,
                        layout.GAP_X, layout.GAP_Y)
          layout._normalise(doc, registry, cells, layout.MARGIN)
          scores.append(layout._score(doc, registry))

        doc, registry, _ = open_example(path)
        layout.arrange(doc, registry)
        chosen = layout._score(doc, registry)
        self.assertLessEqual(
          chosen, min(scores) + 1e-6,
          "%s: arrange scored %.0f, but one of the orderings scored %.0f"
          % (name, chosen, min(scores)))


class TestStackingKeepsTheColumnOrder(unittest.TestCase):
  """_stack used to re-sort a column by the heights its cells wanted, which
  made every order the same answer: the crossing cuts in _order and every swap
  _refine measured were thrown away, and a loose cell always went last."""

  def stack(self, column, desired):
    by_id = {c: {"id": c, "y": 0.0} for c in "abc"}
    boxes = {c: (0.0, 0.0, 40.0, 40.0) for c in "abc"}
    layout._stack(by_id, boxes, column, desired, 20.0)
    return by_id

  def test_a_cell_listed_first_stays_on_top(self):
    placed = self.stack(["b", "a"], {"a": 0.0, "b": 100.0})
    self.assertLess(placed["b"]["y"], placed["a"]["y"])

  def test_a_loose_cell_keeps_its_slot(self):
    placed = self.stack(["a", "c", "b"], {"a": 0.0, "b": 300.0})
    self.assertLess(placed["a"]["y"], placed["c"]["y"])
    self.assertLess(placed["c"]["y"], placed["b"]["y"])

  def test_a_cell_with_room_still_goes_where_its_wire_wants(self):
    placed = self.stack(["a", "b"], {"a": 0.0, "b": 300.0})
    self.assertEqual(placed["b"]["y"], 300.0)

  def test_ports_stack_as_close_as_the_drcs_allow(self):
    """Reported: auto-layout spread a column of ports a cell gap apart --
    82 units -- where the same ports drawn by hand sat about 33 apart."""
    by_id = {c: {"id": c, "y": 0.0, "label": c} for c in "abc"}
    boxes = {c: (0.0, 0.0, 20.0, 10.0) for c in "abc"}
    layout._stack(by_id, boxes, ["a", "b", "c"], {}, 52.0,
                  ports=frozenset("ab"))
    self.assertEqual(by_id["b"]["y"] - by_id["a"]["y"],
                     10.0 + drc.PORT_GAP + drc.TEXT_TO_CELL)
    self.assertEqual(by_id["c"]["y"] - by_id["b"]["y"],
                     10.0 + 52.0 + drc.LABEL_HEADROOM,
                     "a cell under a port still keeps the full cell gap")


class TestAutoLayoutLeavesNoErrors(unittest.TestCase):
  """Every DRC error auto-layout has produced so far was the router drawing
  two nets as one; this holds the examples to none."""

  def test_no_example_comes_out_of_layout_with_an_error(self):
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        layout.arrange(doc, registry)
        errors = [str(v) for v in drc.check(doc, registry)
                  if v.level == "error"]
        self.assertEqual(errors, [])


class TestRefinement(unittest.TestCase):
  """Swapping neighbours in a column and measuring the result.

  Ordering by median neighbour position answers "which cell is roughly where".
  It does not answer "is this the best arrangement", and a user reported
  exactly the gap: columns that look tidy with wires running much further than
  they need to.
  """

  def crossbar(self, width=4):
    """Two columns wired straight across, then scrambled within a column.

    Every wire wants its two ends level. The median pass has nothing to pull
    them into line with, because every cell in a column has exactly one
    neighbour and they all disagree -- so only trying a swap fixes it.
    """
    doc = new_document("crossbar", 900, 700)
    for index in range(width):
      doc.cells.append({"id": "a%d" % index, "type": "buf",
                        "x": 100, "y": 60 + index * 90})
      doc.cells.append({"id": "b%d" % index, "type": "buf",
                        "x": 500, "y": 60 + index * 90})
      doc.nets.append({"id": "n%d" % index,
                       "from": {"cell": "a%d" % index, "pin": "y"},
                       "to": [{"cell": "b%d" % index, "pin": "a"}]})
    return doc

  def test_refining_never_makes_a_drawing_worse(self):
    """The one thing the pass must guarantee: it keeps a swap only when the
    measurement says so, so its answer is never worse than what it was given.
    """
    for width in (3, 4, 5):
      with self.subTest(width=width):
        doc = self.crossbar(width)
        registry = default_registry()
        layout.arrange(doc, registry)
        after = layout._score(doc, registry)

        # The same drawing, laid out with the refinement switched off.
        plain = self.crossbar(width)
        sweeps = layout.REFINE_SWEEPS
        try:
          layout.REFINE_SWEEPS = 0
          layout.arrange(plain, registry)
          before = layout._score(plain, registry)
        finally:
          layout.REFINE_SWEEPS = sweeps

        self.assertLessEqual(after, before + 1e-6,
                             "refining made the drawing score worse")

  def test_it_earns_its_place_on_a_real_drawing(self):
    """The pass has to actually find something, or it is cost with no gain.

    Asked of the shipped examples rather than a made-up drawing, because the
    constructions where the median ordering is obviously wrong are exactly the
    ones it already gets right: every cell has one neighbour and the median is
    the answer. Where swapping pays is a drawing messy enough to have no
    obvious answer, which is what the examples are.

    Over the whole set rather than one file, so improving a single drawing
    cannot break this -- but the pass going quiet everywhere does.
    """
    improved = []
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      scores = {}
      for sweeps in (0, layout.REFINE_SWEEPS):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        was = layout.REFINE_SWEEPS
        try:
          layout.REFINE_SWEEPS = sweeps
          layout.arrange(doc, registry)
          scores[sweeps] = layout._score(doc, registry)
        finally:
          layout.REFINE_SWEEPS = was
      if scores[layout.REFINE_SWEEPS] < scores[0] - 1.0:
        improved.append(name)
    self.assertTrue(improved,
                    "refining improved none of the examples, so it is only "
                    "costing time")

  def test_it_is_still_the_same_answer_every_time(self):
    """A layout that shuffles means nobody can tell whether the button did
    anything. Trying swaps must not make the result depend on luck."""
    registry = default_registry()
    runs = []
    for _ in range(3):
      doc = self.crossbar(4)
      layout.arrange(doc, registry)
      runs.append([(c["id"], c["x"], c["y"]) for c in doc.cells])
    self.assertEqual(runs[0], runs[1])
    self.assertEqual(runs[1], runs[2])

  def test_refining_stops_when_it_finds_nothing(self):
    """The sweep count is a ceiling, not a target -- otherwise raising it for
    quality would cost time on every drawing that settled in one pass."""
    doc = self.crossbar(3)
    registry = default_registry()
    calls = []
    real = layout._score

    def counted(*args, **kwargs):
      calls.append(1)
      return real(*args, **kwargs)

    layout._score = counted
    try:
      layout.arrange(doc, registry)
    finally:
      layout._score = real
    # Two candidate orderings, plus the refinement. Far fewer than the cap
    # would allow if every sweep always ran.
    ceiling = 2 + layout.REFINE_SWEEPS * (len(doc.cells) + 2) + 4
    self.assertLess(len(calls), ceiling, "the sweeps did not stop early")


class TestPortsFollowTheirWire(unittest.TestCase):
  """A cell with nothing arriving is placed by what leaves it.

  Reported as: a port placed neatly against its neighbours to save room, with
  a long bent wire to the gate it feeds. The placement pass puts each cell
  where its *incoming* wire wants it, which says nothing at all about an input
  port -- so a port kept whatever height the ordering pass happened to give
  it.
  """

  def fan(self, count=3):
    """One port per gate, with the gates spread far apart vertically."""
    doc = new_document("fan", 900, 800)
    for index in range(count):
      doc.cells.append({"id": "p%d" % index, "type": "port_in",
                        "x": 60, "y": 60 + index * 30, "label": "p%d" % index})
      doc.cells.append({"id": "u%d" % index, "type": "and2",
                        "x": 400, "y": 60 + index * 190})
      doc.nets.append({"id": "n%d" % index,
                       "from": {"cell": "p%d" % index, "pin": "p"},
                       "to": [{"cell": "u%d" % index, "pin": "a"}]})
    return doc

  def pin_y(self, doc, registry, cell_id, pin):
    cell = doc.cell(cell_id)
    return registry.for_cell(cell).pin_position(cell, pin, doc.symbol_scale)[1]

  def test_a_port_lands_level_with_the_pin_it_feeds(self):
    doc = self.fan()
    registry = default_registry()
    layout.arrange(doc, registry)
    for index in range(3):
      with self.subTest(port=index):
        self.assertAlmostEqual(
          self.pin_y(doc, registry, "p%d" % index, "p"),
          self.pin_y(doc, registry, "u%d" % index, "a"),
          places=3, msg="the wire out of this port is not straight")

  def test_ports_are_still_pushed_apart(self):
    """Following a wire must not let two ports land on top of each other --
    which is exactly what happened the first time this was tried, because the
    boxes it measured were from before the cells moved.
    """
    doc = self.fan()
    registry = default_registry()
    layout.arrange(doc, registry)
    overlaps = [v for v in drc.check(doc, registry) if v.rule == "cell-overlap"]
    self.assertEqual([str(v) for v in overlaps], [])

  def test_settling_is_a_choice_the_drawing_makes(self):
    """It is not always right, so it is not always done.

    Straightening the wire out of every port is worth a great deal on a flat
    drawing of gates and close to nothing on a sheet of hierarchy blocks,
    where dragging a port to line up with one pin of a twelve-pin block
    spreads its whole column out. So it is one of the arrangements laid out
    and measured rather than something applied unconditionally -- and the
    proof that it is a real choice is that the examples do not all make it the
    same way.
    """
    chosen = set()
    real = layout._place

    def watched(*args, **kwargs):
      if len(args) > 8:
        chosen.add(args[8])
      else:
        chosen.add(kwargs.get("settle", True))
      return real(*args, **kwargs)

    layout._place = watched
    try:
      for name in ("alu_slice.dlg", "soc_top.dlg"):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        layout.arrange(doc, registry)
    finally:
      layout._place = real
    self.assertEqual(chosen, {True, False},
                     "both settings have to be tried for it to be a choice")

  def test_settling_straightens_a_port_that_would_otherwise_bend(self):
    """The case it exists for, asked directly."""
    doc = self.fan()
    registry = default_registry()
    layout.arrange(doc, registry)
    bends = 0
    for index in range(3):
      if abs(self.pin_y(doc, registry, "p%d" % index, "p")
             - self.pin_y(doc, registry, "u%d" % index, "a")) > 1e-3:
        bends += 1
    self.assertEqual(bends, 0, "%d of 3 port wires still bend" % bends)


class TestWhatTheScoreCountsFor(unittest.TestCase):
  """The score is what decides between two arrangements, so what it counts
  for is the whole of the layout's taste. These are judgements, not
  measurements -- the point of testing them is that each one has an effect at
  all, not that the number is right."""

  def two_cells(self, gap):
    doc = new_document("spread", 1400, 900)
    doc.cells.extend([
      {"id": "u1", "type": "buf", "x": 100, "y": 100},
      {"id": "u2", "type": "buf", "x": 100 + gap, "y": 100},
    ])
    doc.nets.append({"id": "n", "from": {"cell": "u1", "pin": "y"},
                     "to": [{"cell": "u2", "pin": "a"}]})
    return doc

  def test_a_tighter_drawing_scores_better(self):
    registry = default_registry()
    self.assertLess(layout._score(self.two_cells(200), registry),
                    layout._score(self.two_cells(600), registry))

  def test_spread_counts_for_something_beyond_the_wire_it_adds(self):
    """Otherwise SPREAD_COST is a constant nothing reads, which is the shape
    of bug this project has had before."""
    registry = default_registry()
    tight, wide = self.two_cells(200), self.two_cells(600)
    difference = layout._score(wide, registry) - layout._score(tight, registry)

    was = layout.SPREAD_COST
    try:
      layout.SPREAD_COST = 0.0
      without = layout._score(wide, registry) - layout._score(tight, registry)
    finally:
      layout.SPREAD_COST = was
    self.assertGreater(difference, without)

  def test_a_drc_error_outweighs_a_handful_of_crossings(self):
    """The score used to measure crossings, length and spread and nothing
    else, so it shipped arrangements holding wire-shorts quite happily: two
    nets lying on top of each other cross nothing, add no length, and take no
    room. An error is the drawing saying something untrue, so it has to cost
    more than the legibility it could buy by lying.
    """
    self.assertGreater(layout.ERROR_COST, layout.CROSSING_COST * 3)

  def test_the_score_counts_what_the_checker_finds(self):
    """Otherwise ERROR_COST is a constant nothing reads."""
    registry = default_registry()
    doc = self.two_cells(200)
    was = layout.ERROR_COST
    seen = []
    real = drc.check
    try:
      def counted(*args, **kwargs):
        found = real(*args, **kwargs)
        seen.append(len(found))
        return found
      drc.check = counted
      layout._score(doc, registry)
    finally:
      drc.check = real
      layout.ERROR_COST = was
    self.assertTrue(seen, "_score never asked the checker anything")

  def test_a_crossing_costs_more_than_the_wire_it_saves(self):
    """The whole reason crossings are priced at all: a drawing should accept
    a longer wire to lose one."""
    self.assertGreater(layout.CROSSING_COST, drc.CELL_GAP_X)


class TestCellMinGap(unittest.TestCase):
  """drc.CELL_MIN_GAP is documented as a real floor, so it has to be one."""

  def test_a_larger_minimum_widens_the_actual_gap(self):
    doc = new_document("gap")
    doc.cells.extend([
      {"id": "a", "type": "and2", "x": 0, "y": 0},
      {"id": "b", "type": "and2", "x": 0, "y": 0},
    ])
    doc.normalize()

    old = drc.CELL_MIN_GAP
    try:
      drc.CELL_MIN_GAP = 200.0
      layout.arrange(doc)
      gap = doc.cells[1]["y"] - doc.cells[0]["y"] - 40  # and2 is 40 tall
      self.assertGreaterEqual(
        gap, 200.0,
        "CELL_MIN_GAP is documented as the least space allowed between any "
        "two cells; raising it must widen the gap layout actually leaves")
    finally:
      drc.CELL_MIN_GAP = old


class TestTransposeCutsCrossings(unittest.TestCase):
  """The adjacent-swap pass that follows median ordering.

  Median ordering places a cell at the middle of its neighbours, which is a
  good guess and not an answer: it can leave two cells the wrong way round
  when swapping them would plainly cross fewer wires. This is the cheap
  correction, counted from the order alone rather than by routing anything.

  It matters beyond tidiness. Where one net leaves a row and another arrives
  at the same row, their horizontal legs sit at the same height, and keeping
  them apart needs the leaving net's corridor to the left of the arriving
  one's -- which the mirror-image pair demands in reverse. A fully crossed
  pair has no valid assignment at all and the router resolves it by drawing
  one wire on another, which is a `wire-short`. Every crossing removed here
  is one of those removed downstream.
  """

  def test_it_undoes_a_swap_that_plainly_crosses(self):
    """Two cells in the wrong order, each wired straight across: the only
    thing to decide is whether to swap them back."""
    order = [["a", "b"], ["x", "y"]]
    left = {"a": [], "b": [], "x": ["b"], "y": ["a"]}
    right = {"a": ["y"], "b": ["x"], "x": [], "y": []}
    layout._transpose(order, left, right)
    self.assertEqual(order[0], ["b", "a"],
                     "the crossing pair was left crossed")

  def test_it_leaves_an_order_that_is_already_right(self):
    """The negative control: a pass that always swaps would satisfy the test
    above and be worthless."""
    order = [["a", "b"], ["x", "y"]]
    left = {"a": [], "b": [], "x": ["a"], "y": ["b"]}
    right = {"a": ["x"], "b": ["y"], "x": [], "y": []}
    layout._transpose(order, left, right)
    self.assertEqual(order[0], ["a", "b"])

  def test_pair_crossings_counts_what_it_says(self):
    position = {"p": 0, "q": 1}
    side = {"top": ["q"], "bottom": ["p"]}
    self.assertEqual(layout._pair_crossings("top", "bottom", side, position), 1)
    self.assertEqual(layout._pair_crossings("bottom", "top", side, position), 0)

  def test_it_never_makes_a_real_drawing_worse(self):
    """Measured over the shipped examples rather than argued: the whole point
    of counting crossings combinatorially is that it is cheap enough to check
    every adjacent pair, so it should never come out behind."""
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        doc, registry, _ = open_example(os.path.join(ROOT, "examples", name))
        layout.arrange(doc, registry)
        first = _crossings_of(doc, registry)
        layout.arrange(doc, registry)
        self.assertEqual(_crossings_of(doc, registry), first,
                         "a second pass changed the crossing count")


def _crossings_of(doc, registry):
  return layout._crossings(
    list(routing.segments_of(routing.route_all(doc, registry))))



if __name__ == "__main__":
  unittest.main()


class TestWhichWayTheSignalRuns(unittest.TestCase):
  """Direction comes from the pins, not from the order the wire was drawn.

  A net records which pin was clicked first, and half the time that is the
  load: clicking the flip-flop's D and then the gate that feeds it is a
  perfectly ordinary way to draw a wire, and it is the same circuit either
  way. Every drawing in examples/ and benchmarks/ was wired driver-first by
  the same hand, so not one of them can tell whether this works -- which is
  why it needs a fixture of its own.
  """

  def wired(self, backwards=False, tie_resets=False):
    """A port into an AND, into a flop, out to a port.

    `backwards` draws the AND-to-flop wire from the flop's D back to the
    gate's Y, which is the same circuit stated the other way round.
    `tie_resets` adds a wire between two reset pins, which drives nothing.
    """
    doc = new_document("flow", 900, 400)
    doc.cells.append({"id": "pin", "type": "port_in", "x": 40, "y": 40,
                      "label": "a"})
    doc.cells.append({"id": "g", "type": "and2", "x": 200, "y": 200})
    doc.cells.append({"id": "ff", "type": "dffr", "x": 300, "y": 100})
    doc.cells.append({"id": "ff2", "type": "dffr", "x": 300, "y": 260})
    doc.cells.append({"id": "pout", "type": "port_out", "x": 60, "y": 300,
                      "label": "y"})
    links = [("pin", "p", "g", "a"),
             ("ff", "d", "g", "y") if backwards else ("g", "y", "ff", "d"),
             ("ff", "q", "pout", "p")]
    if tie_resets:
      links.append(("ff", "rn", "ff2", "rn"))
    for index, (source, source_pin, target, target_pin) in enumerate(links, 1):
      doc.nets.append({"id": "n%d" % index, "name": None,
                       "from": {"cell": source, "pin": source_pin},
                       "to": {"cell": target, "pin": target_pin},
                       "waypoints": [], "style": {}})
    doc.normalize()
    return doc

  def ranks_of(self, doc):
    registry = default_registry()
    cells = [c for c in doc.cells if registry.for_cell(c) is not None]
    edges, _feedback = layout._edges(doc, registry, cells)
    return layout._ranks(doc, registry, cells, edges)

  def test_a_wire_drawn_backwards_ranks_the_same_way(self):
    """The gate stays left of the flop it feeds, whichever end was clicked."""
    forward = self.ranks_of(self.wired(backwards=False))
    reversed_ = self.ranks_of(self.wired(backwards=True))
    self.assertEqual(
      forward, reversed_,
      "drawing the wire from the flop back to the gate moved things: "
      "%s against %s" % (reversed_, forward))
    self.assertLess(forward["g"], forward["ff"],
                    "the gate should sit left of the flop it drives")

  def test_a_wire_between_two_inputs_orders_nothing(self):
    """Two reset pins tied together says nothing about which comes first.

    It is a drawing with no driver -- `validate` says so -- and obeying it as
    though it were one would push a flop into a column of its own for a wire
    that carries nothing.
    """
    without = self.ranks_of(self.wired())
    with_tie = self.ranks_of(self.wired(tie_resets=True))
    self.assertEqual(
      with_tie["ff2"], without["ff2"],
      "tying two reset pins together moved a flop: %d against %d"
      % (with_tie["ff2"], without["ff2"]))
    self.assertEqual(with_tie, without,
                     "a wire with no driver changed the columns")

  def test_an_undeclared_pin_is_read_from_the_side_it_leaves(self):
    """`inout` -- which is what a pin that never said anything gets.

    Right of centre drives, anything else takes, so mirroring a port turns it
    round. That is what lets an inout port be an input on the left of the
    sheet and an output on the right.
    """
    doc = new_document("io", 400, 200)
    cell = {"id": "p", "type": "port_inout", "x": 100, "y": 100, "label": "b"}
    doc.cells.append(cell)
    doc.normalize()
    registry = default_registry()
    symbol = registry.for_cell(cell)
    self.assertEqual(symbol.pin("p")["dir"], "inout",
                     "this test is pointless unless the pin is undeclared")

    self.assertEqual(layout._flow(doc, registry, cell, "p"), "in",
                     "a connector on the left should read as taking")
    cell["mirror"] = True
    self.assertEqual(layout._flow(doc, registry, cell, "p"), "out",
                     "mirrored, the same connector faces right and drives")

  def test_an_inout_port_lands_on_the_side_it_faces(self):
    """An inout port is an input or an output by which way its connector faces.

    Nothing in the type name says which, so the column it belongs in has to
    come from the same place the direction does. Facing left it takes, and
    belongs on the right edge with the other output ports; mirrored it drives,
    and belongs in the first column with the inputs.
    """
    def ranks_with(mirror):
      doc = new_document("io", 900, 400)
      doc.cells.append({"id": "pin", "type": "port_in", "x": 40, "y": 40,
                        "label": "a"})
      doc.cells.append({"id": "u", "type": "inv", "x": 200, "y": 200})
      doc.cells.append({"id": "io", "type": "port_inout", "x": 400, "y": 200,
                        "mirror": mirror, "label": "b"})
      # A longer branch beside it, so the sheet is wider than the port's own
      # chain. Without that the port's natural column is already the last one
      # and the test cannot tell whether anything put it there.
      for index in range(3):
        doc.cells.append({"id": "v%d" % index, "type": "inv",
                          "x": 200 + index * 80, "y": 320})
      links = [("pin", "p", "u", "a"), ("u", "y", "io", "p"),
               ("pin", "p", "v0", "a"), ("v0", "y", "v1", "a"),
               ("v1", "y", "v2", "a")]
      for index, (source, source_pin, target, target_pin) in enumerate(links, 1):
        doc.nets.append({"id": "n%d" % index, "name": None,
                         "from": {"cell": source, "pin": source_pin},
                         "to": {"cell": target, "pin": target_pin},
                         "waypoints": [], "style": {}})
      doc.normalize()
      return self.ranks_of(doc)

    facing_left = ranks_with(False)
    self.assertEqual(
      facing_left["io"], max(facing_left.values()),
      "a left-facing inout port takes, so it belongs on the right edge")

    facing_right = ranks_with(True)
    self.assertEqual(
      facing_right["io"], 0,
      "a mirrored inout port drives, so it belongs in the first column")


class TestForkingIsChosenByMeasuring(unittest.TestCase):
  """Whether wires fork late is decided by routing the drawing, not assumed.

  A wire with several loads can give each one its own way across the sheet, or
  run as one trunk that divides near the pins it serves. The second is shorter
  on most drawings and puts the junction dot beside the load rather than the
  driver -- but not on all of them, because a branch that leaves late takes a
  line of its own and every wire routed after it has to dodge that line
  instead. Assuming either way made some drawing worse, so the layout routes
  the finished arrangement both ways and keeps the better.
  """

  def test_the_choice_never_makes_a_drawing_worse(self):
    """Whatever it picks is at least as good as either answer alone."""
    for name in ("alu_slice", "cdc_fifo", "spi_master", "mac_pipe",
                 "dff_slice"):
      with self.subTest(example=name):
        path = os.path.join(ROOT, "examples", name + ".dlg")
        doc, registry, _ = open_example(path)
        layout.arrange(doc, registry)
        chosen = layout._score(doc, registry)

        both = []
        for late in (False, True):
          if late:
            doc.canvas["forkLate"] = True
          else:
            doc.canvas.pop("forkLate", None)
          both.append(layout._score(doc, registry))
        self.assertLessEqual(
          chosen, min(both) + 1e-6,
          "%s: kept a %.0f when %.0f was available" % (name, chosen, min(both)))

  def test_it_leaves_the_flag_off_when_it_buys_nothing(self):
    """An unchanged drawing is written exactly as it was before this existed."""
    doc, registry, _ = open_example(os.path.join(ROOT, "examples",
                                                 "spi_master.dlg"))
    layout.arrange(doc, registry)
    self.assertNotIn(
      "forkLate", doc.canvas,
      "spi_master measures worse forking late, so the flag should be absent "
      "rather than written as false")

  def test_laying_out_twice_gives_the_same_answer(self):
    """The search has to start from a known state, whatever the file carried.

    Left as the file happened to have it, the second layout searched
    differently from the first and settled somewhere else -- which is the one
    thing a layout button must never do.
    """
    for name in ("alu_slice", "soc_top"):
      with self.subTest(example=name):
        path = os.path.join(ROOT, "examples", name + ".dlg")
        doc, registry, _ = open_example(path)
        layout.arrange(doc, registry)
        once = doc.dumps()
        layout.arrange(doc, registry)
        self.assertEqual(doc.dumps(), once,
                         "%s moved when laid out a second time" % name)


class TestTheLayoutSettlesOnTheGrid(unittest.TestCase):
  """A laid-out drawing lands on the step its pins use, where that is safe.

  Placing works in real numbers, so cells came to rest on values like 113.48.
  Nothing downstream minded, but the next person to drag something did: a drag
  snaps to the grid, and a grid the drawing is no longer on lines nothing up.
  """

  STEP = drc.PIN_GRID

  def laid_out(self, name):
    doc, registry, _ = open_example(
      os.path.join(ROOT, "examples", name + ".dlg"))
    layout.arrange(doc, registry)
    return doc, registry

  def on_grid(self, doc):
    return all(abs(value / self.STEP - round(value / self.STEP)) < 1e-9
               for cell in doc.cells for value in (cell["x"], cell["y"]))

  def test_a_drawing_whose_pins_suit_it_comes_back_on_the_grid(self):
    for name in ("alu_slice", "dff_slice", "mac_pipe"):
      with self.subTest(example=name):
        doc, registry = self.laid_out(name)
        self.assertTrue(
          layout._offsets_on_grid(doc, registry, self.STEP),
          "%s was picked because its pin offsets are whole steps" % name)
        self.assertTrue(self.on_grid(doc),
                        "%s came back off the grid" % name)

  def test_a_drawing_whose_pins_do_not_is_left_alone(self):
    """spi_master uses block8, whose pins sit at 26, 58, 102 and 134.

    Rounding there moves the two ends of a wire by different amounts, which
    bends wires that were straight -- four of nineteen down to one, measured.
    So it is not done at all rather than done and then regretted.
    """
    doc, registry = self.laid_out("spi_master")
    self.assertFalse(
      layout._offsets_on_grid(doc, registry, self.STEP),
      "spi_master's offsets are whole steps now, so this test has lost its "
      "subject -- pick another drawing or drop it")
    self.assertFalse(self.on_grid(doc),
                     "spi_master was rounded despite its offsets")

  def test_settling_never_costs_an_error_or_a_warning(self):
    """The grid is worth a little wire, and nothing at all beyond that."""
    for name in ("alu_slice", "cdc_fifo", "mac_pipe", "dff_slice"):
      with self.subTest(example=name):
        doc, registry = self.laid_out(name)
        after = layout._violation_count(doc, registry)
        for cell in doc.cells:
          cell["x"] = cell["x"] + 0.37
          cell["y"] = cell["y"] + 0.37
        off_grid = layout._violation_count(doc, registry)
        self.assertLessEqual(
          after, off_grid,
          "%s reads worse on the grid (%s) than off it (%s)"
          % (name, after, off_grid))
