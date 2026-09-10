import unittest

from drawlogic import routing
from drawlogic.doc import Document, new_document
from tests import EXAMPLE


def _doc_with_pair(gap=300):
  doc = new_document()
  doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
  doc.cells.append({"id": "u2", "type": "inv", "x": gap, "y": 0})
  doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                   "to": {"cell": "u2", "pin": "a"}})
  doc.normalize()
  return doc


class TestRouting(unittest.TestCase):

  def test_aligned_pins_route_straight(self):
    doc = _doc_with_pair()
    # and2.y sits at y=20; inv.a sits at y=20 as well.
    points = routing.route(doc, doc.nets[0])
    self.assertEqual(len(points), 2)
    self.assertAlmostEqual(points[0][1], points[1][1])

  def test_offset_pins_route_with_two_corners(self):
    doc = _doc_with_pair()
    doc.cell("u2")["y"] = 120
    points = routing.route(doc, doc.nets[0])
    self.assertEqual(len(points), 4)
    self.assertAlmostEqual(points[0][1], points[1][1])
    self.assertAlmostEqual(points[1][0], points[2][0])
    self.assertAlmostEqual(points[2][1], points[3][1])

  def test_every_segment_is_axis_aligned(self):
    doc = Document.load(EXAMPLE)
    for net, points in routing.route_all(doc):
      for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        self.assertTrue(abs(ax - bx) < 1e-6 or abs(ay - by) < 1e-6,
                        "net %s has a diagonal segment" % net.get("id"))

  def test_moving_a_gate_carries_its_wire(self):
    # This is the whole point of storing pin references instead of
    # coordinates, so it gets an explicit test.
    doc = _doc_with_pair()
    before = routing.route(doc, doc.nets[0])
    doc.cell("u1")["x"] += 40
    doc.cell("u1")["y"] += 25
    after = routing.route(doc, doc.nets[0])

    self.assertAlmostEqual(after[0][0], before[0][0] + 40)
    self.assertAlmostEqual(after[0][1], before[0][1] + 25)
    self.assertAlmostEqual(after[-1][0], before[-1][0])
    self.assertAlmostEqual(after[-1][1], before[-1][1])

  def test_backward_target_does_not_route_through_the_cell(self):
    doc = _doc_with_pair()
    doc.cell("u2")["x"] = -200
    doc.cell("u2")["y"] = 150
    points = routing.route(doc, doc.nets[0])
    start = points[0]
    # The wire must leave the driving pin heading east before turning back.
    self.assertGreater(points[1][0], start[0])

  def test_no_segment_crosses_an_unrelated_cell(self):
    # Every leg has to clear other cells, not just the corridor. A corridor
    # that dodges a gate is useless if the leg into it still cuts through one.
    doc = Document.load(EXAMPLE)
    for net, points in routing.route_all(doc):
      exclude = set()
      for side in ("from", "to"):
        endpoint = net.get(side) or {}
        if "cell" in endpoint:
          exclude.add(endpoint["cell"])
      boxes = routing.obstacle_boxes(doc, exclude=exclude)
      for index in range(len(points) - 1):
        (ax, ay), (bx, by) = points[index], points[index + 1]
        if abs(ax - bx) < 1e-6:
          clear = routing._vertical_clear(ax, ay, by, boxes)
        else:
          clear = routing._horizontal_clear(ay, ax, bx, boxes)
        self.assertTrue(clear, "net %s cuts through a cell" % net.get("id"))

  def test_unresolvable_net_routes_to_nothing(self):
    doc = _doc_with_pair()
    doc.nets[0]["to"] = {"cell": "ghost", "pin": "a"}
    self.assertEqual(routing.route(doc, doc.nets[0]), [])

  def test_free_endpoint_is_honoured(self):
    doc = _doc_with_pair()
    doc.nets[0]["to"] = {"x": 400, "y": 200}
    points = routing.route(doc, doc.nets[0])
    self.assertAlmostEqual(points[-1][0], 400)
    self.assertAlmostEqual(points[-1][1], 200)


class TestJunctions(unittest.TestCase):

  def test_branch_gets_a_dot(self):
    doc = Document.load(EXAMPLE)
    routes = routing.route_all(doc)
    found = routing.junctions(routes)
    self.assertTrue(found, "the branch off FF1.q should produce a junction dot")

  def test_a_plain_corner_is_not_a_junction(self):
    doc = _doc_with_pair()
    doc.cell("u2")["y"] = 120
    routes = routing.route_all(doc)
    self.assertEqual(routing.junctions(routes), [])

  def test_crossing_wires_are_not_joined(self):
    # Two nets that cross without sharing a vertex must stay unconnected;
    # a crossing and a connection must never look the same.
    doc = new_document()
    doc.cells.append({"id": "a1", "type": "port_in", "x": 0, "y": 100})
    doc.cells.append({"id": "a2", "type": "port_out", "x": 400, "y": 100})
    doc.cells.append({"id": "b1", "type": "port_in", "x": 200, "y": 0,
                      "rotate": 90})
    doc.cells.append({"id": "b2", "type": "port_out", "x": 200, "y": 300,
                      "rotate": 90})
    doc.nets.append({"id": "n1", "from": {"cell": "a1", "pin": "p"},
                     "to": {"cell": "a2", "pin": "p"}})
    doc.nets.append({"id": "n2", "from": {"cell": "b1", "pin": "p"},
                     "to": {"cell": "b2", "pin": "p"}})
    doc.normalize()
    self.assertEqual(routing.junctions(routing.route_all(doc)), [])


class TestBusWidth(unittest.TestCase):

  def test_bus_is_drawn_like_any_other_wire(self):
    # Width is carried by the name, not by line weight.
    self.assertEqual(routing.stroke_width({"width": 8}),
                     routing.stroke_width({"width": 1}))


if __name__ == "__main__":
  unittest.main()
