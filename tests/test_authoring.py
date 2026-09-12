"""Making a symbol out of a drawing.

There is no separate symbol editor, because a symbol is very nearly a drawing
already: the shapes are the artwork and the ports say where the pins go. What
is worth guarding is the handful of decisions the conversion makes on the
user's behalf, because each one is a place where a reasonable drawing could
become an unusable symbol.

Usage:

    python3 -m unittest tests.test_authoring
"""

import json
import os
import shutil
import tempfile
import unittest

from drawlogic import authoring, render_svg, routing
from drawlogic.doc import new_document
from drawlogic.symbols import Symbol, SymbolError, default_registry


def drawing(shapes=None, ports=None):
  """What someone would have on screen before pressing Save as symbol."""
  doc = new_document("thing", 600, 400)
  doc.shapes.extend(shapes if shapes is not None else [
    {"id": "s1", "kind": "rect", "x": 200, "y": 100, "w": 120, "h": 80,
     "rotate": 0, "style": {"fill": "#ffffff", "stroke": "#16202b"}},
  ])
  doc.cells.extend(ports if ports is not None else [
    {"id": "p1", "type": "port_in", "x": 160, "y": 115, "label": "a"},
    {"id": "p2", "type": "port_out", "x": 340, "y": 135, "label": "y"},
  ])
  doc.normalize()
  return doc


def pins(data):
  return {pin["name"]: (pin["x"], pin["y"], pin["dir"]) for pin in data["pins"]}


class TestTheBody(unittest.TestCase):

  def test_the_shapes_set_the_size_not_the_ports(self):
    # A port sits beside the thing it connects to. Counting it would leave
    # every pin sunk inside the outline rather than on it.
    data = authoring.symbol_from(drawing(), "thing")
    self.assertEqual(data["size"], [120.0, 80.0])

  def test_the_artwork_is_moved_to_the_symbol_s_own_origin(self):
    data = authoring.symbol_from(drawing(), "thing")
    rect = [op for op in data["draw"] if op["op"] == "rect"][0]
    self.assertEqual((rect["x"], rect["y"]), (0.0, 0.0))

  def test_text_rides_along_without_deciding_the_size(self):
    # There is no way to measure a string here, and a caption should not
    # inflate the body it is written on.
    doc = drawing()
    doc.shapes.append({"id": "s2", "kind": "text", "x": 900, "y": 900,
                       "rotate": 0, "text": "note", "style": {}})
    data = authoring.symbol_from(doc, "thing")
    self.assertEqual(data["size"], [120.0, 80.0])
    self.assertIn("text", [op["op"] for op in data["draw"]])

  def test_a_filled_shape_is_the_body_and_an_empty_one_is_a_mark_on_it(self):
    # Parts are painted by role rather than by colour, so a placed cell can be
    # recoloured and the theme can change underneath it.
    doc = drawing(shapes=[
      {"id": "s1", "kind": "rect", "x": 200, "y": 100, "w": 120, "h": 80,
       "rotate": 0, "style": {"fill": "#eeeeee"}},
      {"id": "s2", "kind": "line", "rotate": 0,
       "points": [[210, 110], [310, 170]], "style": {"fill": "none"}},
    ])
    roles = [op["role"] for op in authoring.symbol_from(doc, "thing")["draw"]]
    self.assertEqual(roles, ["body", "decor"])

  def test_text_matching_a_pin_becomes_that_pin_s_label(self):
    # So renaming the pin on a placed cell renames what is drawn on it.
    doc = drawing()
    doc.shapes.append({"id": "s2", "kind": "text", "x": 210, "y": 130,
                       "rotate": 0, "text": "a", "style": {}})
    data = authoring.symbol_from(doc, "thing")
    label = [op for op in data["draw"] if op["op"] == "text"][0]
    self.assertEqual(label.get("pin"), "a")

  def test_an_open_run_of_points_becomes_a_path_not_a_polygon(self):
    doc = drawing(shapes=[
      {"id": "s1", "kind": "rect", "x": 200, "y": 100, "w": 120, "h": 80,
       "rotate": 0, "style": {"fill": "#fff"}},
      {"id": "s2", "kind": "polyline", "rotate": 0,
       "points": [[210, 110], [250, 150], [300, 120]], "style": {}},
    ])
    ops = [op["op"] for op in authoring.symbol_from(doc, "thing")["draw"]]
    self.assertIn("path", ops)
    self.assertNotIn("polygon", ops)


class TestWhereThePinsLand(unittest.TestCase):

  def test_a_port_beside_the_body_lands_on_that_edge(self):
    found = pins(authoring.symbol_from(drawing(), "thing"))
    self.assertEqual(found["a"][0], 0.0)
    self.assertEqual(found["y"][0], 120.0)

  def test_a_port_near_a_corner_still_means_the_side_it_is_outside(self):
    # A port to the left of a tall block is closer to the top of it than to
    # the left side. Picking the nearest edge would put the pin on the top.
    doc = drawing(ports=[
      {"id": "p1", "type": "port_in", "x": 160, "y": 105, "label": "a"},
    ])
    found = pins(authoring.symbol_from(doc, "thing"))
    self.assertEqual(found["a"][0], 0.0, "should be on the west edge")

  def test_a_port_dropped_inside_the_body_goes_to_the_nearest_edge(self):
    doc = drawing(ports=[
      {"id": "p1", "type": "port_in", "x": 210, "y": 105, "label": "a"},
    ])
    found = pins(authoring.symbol_from(doc, "thing"))
    self.assertIn(0.0, found["a"][:2], "a pin must sit on an edge to face out")

  def test_direction_comes_from_the_port_type(self):
    found = pins(authoring.symbol_from(drawing(), "thing"))
    self.assertEqual(found["a"][2], "in")
    self.assertEqual(found["y"][2], "out")

  def test_pins_take_any_bus_width(self):
    # A custom block is a block; the drawing it stands for decides the width.
    data = authoring.symbol_from(drawing(), "thing")
    self.assertTrue(all(pin["width"] == 0 for pin in data["pins"]))


class TestWhenItCannotBeDone(unittest.TestCase):

  def test_a_drawing_with_no_shapes_says_so(self):
    doc = drawing(shapes=[])
    with self.assertRaises(authoring.AuthoringError) as caught:
      authoring.symbol_from(doc, "thing")
    self.assertIn("outline", str(caught.exception))

  def test_a_drawing_with_no_ports_says_so(self):
    doc = drawing(ports=[])
    with self.assertRaises(authoring.AuthoringError) as caught:
      authoring.symbol_from(doc, "thing")
    self.assertIn("port", str(caught.exception))

  def test_a_symbol_needs_an_id(self):
    with self.assertRaises(authoring.AuthoringError):
      authoring.symbol_from(drawing(), "  ")


class TestTheSymbolIsUsable(unittest.TestCase):
  """The whole point: it has to work like every other symbol."""

  def setUp(self):
    self.data = authoring.symbol_from(drawing(), "thing", name="A thing")
    self.registry = default_registry().copy()
    self.registry.add(Symbol("thing", self.data))

  def test_it_loads_as_a_symbol_at_all(self):
    self.assertEqual(self.registry.require("thing").name, "A thing")

  def test_it_is_offered_in_the_palette(self):
    self.assertIn("thing", self.registry.ids())

  def test_it_previews(self):
    self.assertIn("<svg ", render_svg.render_symbol(self.registry.require("thing")))

  def test_a_wire_reaches_its_pins_the_right_way_round(self):
    doc = new_document("use", 700, 300)
    doc.cells.extend([
      {"id": "p", "type": "port_in", "x": 60, "y": 100, "label": "in"},
      {"id": "u1", "type": "thing", "x": 240, "y": 60},
    ])
    doc.nets.append({"id": "n1", "name": None, "width": 1,
                     "from": {"cell": "p", "pin": "p"},
                     "to": [{"cell": "u1", "pin": "a", "waypoints": []}],
                     "style": {}})
    doc.normalize(self.registry)
    [points] = routing.route(doc, doc.nets[0], self.registry)
    self.assertGreaterEqual(len(points), 2)
    # `a` is on the west face, so the wire has to arrive from the west.
    self.assertLess(points[-2][0], points[-1][0])

  def test_it_renders_inside_a_drawing(self):
    doc = new_document("use", 700, 300)
    doc.cells.append({"id": "u1", "type": "thing", "x": 240, "y": 60,
                      "label": "U1"})
    doc.normalize(self.registry)
    svg = render_svg.render(doc, registry=self.registry)
    self.assertIn('data-type="thing"', svg)


class TestTheFileItIsWrittenTo(unittest.TestCase):

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, self.dir)
    self.path = os.path.join(self.dir, "symbols.json")
    self.data = authoring.symbol_from(drawing(), "thing")

  def test_a_new_file_is_created(self):
    authoring.add_to_file(self.path, "thing", self.data)
    with open(self.path) as handle:
      self.assertIn("thing", json.load(handle))

  def test_saving_again_replaces_rather_than_duplicates(self):
    authoring.add_to_file(self.path, "thing", self.data)
    self.data["name"] = "Renamed"
    authoring.add_to_file(self.path, "thing", self.data)
    with open(self.path) as handle:
      library = json.load(handle)
    self.assertEqual(len(library), 1)
    self.assertEqual(library["thing"]["name"], "Renamed")

  def test_other_symbols_in_the_file_are_left_alone(self):
    authoring.add_to_file(self.path, "one", self.data)
    authoring.add_to_file(self.path, "two", self.data)
    with open(self.path) as handle:
      self.assertEqual(sorted(json.load(handle)), ["one", "two"])

  def test_a_symbol_that_will_not_load_is_never_written(self):
    # A file the registry cannot read would take the whole palette down with
    # it, so it is built before it is saved.
    broken = dict(self.data, size=[0, 0])
    with self.assertRaises(SymbolError):
      authoring.add_to_file(self.path, "broken", broken)
    self.assertFalse(os.path.exists(self.path))

  def test_a_folder_s_symbols_are_found_without_being_asked_for(self):
    from drawlogic import sheets

    authoring.add_to_file(self.path, "thing", self.data)
    doc = new_document("use", 400, 300)
    doc.cells.append({"id": "u1", "type": "thing", "x": 100, "y": 100})
    doc.normalize()
    drawing_path = os.path.join(self.dir, "use.dlg")
    doc.save(drawing_path)

    _doc, registry, _issues = sheets.open_document(drawing_path)
    self.assertIsNotNone(registry.get("thing"),
                         "a drawing's folder should carry its own symbols")


if __name__ == "__main__":
  unittest.main()
