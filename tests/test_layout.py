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

from drawlogic import layout, routing
from drawlogic.doc import Document, new_document
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
      target = by_id[net["to"]["cell"]]
      self.assertLess(source["x"], target["x"],
                      "%s should sit left of %s" % (source["id"], target["id"]))

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
    doc.nets[0]["waypoints"] = [[700, 700]]
    layout.arrange(doc, self.registry)
    self.assertEqual([n["waypoints"] for n in doc.nets], [[]] * len(doc.nets))

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
        before = routing.route_all(doc, registry)
        straight_before = sum(1 for _, p in before if len(p) == 2)

        layout.arrange(doc, registry)
        after = routing.route_all(doc, registry)
        straight_after = sum(1 for _, p in after if len(p) == 2)

        self.assertGreater(straight_after, straight_before,
                           "%s: laying out should straighten wires" % name)
        self.assertGreater(straight_after, len(after) * 0.2,
                           "%s: only %d of %d wires run straight"
                           % (name, straight_after, len(after)))


if __name__ == "__main__":
  unittest.main()
