"""Hierarchy: a cell that stands for another drawing.

The property that matters is that a block's pins are never written down. They
are read off the child's ports every time the parent is opened, so the two
cannot quietly disagree -- rename a port and the parent's pin is renamed with
it, breaking any wire that still uses the old name rather than silently
pointing somewhere else.

Usage:

    python3 -m unittest tests.test_sheets
"""

import os
import shutil
import tempfile
import unittest

from drawlogic import render_svg, routing, sheets
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry

from tests import ROOT


def write(directory, name, cells, nets=()):
  doc = new_document(os.path.splitext(name)[0], 600, 400)
  doc.cells.extend(cells)
  doc.nets.extend(nets)
  doc.normalize()
  path = os.path.join(directory, name)
  doc.save(path)
  return path


def port(cell_id, kind, label, y):
  return {"id": cell_id, "type": kind, "x": 40, "y": y, "label": label}


class SheetCase(unittest.TestCase):

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.addCleanup(shutil.rmtree, self.dir)

  def child(self, name="child.dlg", labels=(("a", "port_in", 100),
                                            ("y", "port_out", 200))):
    cells = [port("p%d" % i, kind, label, y)
             for i, (label, kind, y) in enumerate(labels)]
    return write(self.dir, name, cells)

  def parent(self, ref="child.dlg", nets=(), name="top.dlg"):
    block = {"id": "u1", "type": "sheet", "ref": ref, "x": 200, "y": 100,
             "label": "U1"}
    return write(self.dir, name, [block], nets)


class TestPorts(SheetCase):

  def test_a_ports_label_is_its_name(self):
    doc = Document.load(self.child())
    self.assertEqual([p["name"] for p in sheets.ports(doc)], ["a", "y"])

  def test_direction_comes_from_the_port_type(self):
    doc = Document.load(self.child())
    self.assertEqual([p["dir"] for p in sheets.ports(doc)], ["in", "out"])

  def test_ports_are_ordered_down_the_sheet(self):
    doc = Document.load(self.child(labels=(
      ("last", "port_in", 300), ("first", "port_in", 50),
      ("middle", "port_in", 175))))
    self.assertEqual([p["name"] for p in sheets.ports(doc)],
                     ["first", "middle", "last"])

  def test_an_unlabelled_port_falls_back_to_its_id(self):
    path = write(self.dir, "child.dlg",
                 [{"id": "p_lonely", "type": "port_in", "x": 40, "y": 100}])
    self.assertEqual([p["name"] for p in sheets.ports(Document.load(path))],
                     ["p_lonely"])

  def test_two_ports_of_one_name_are_reported(self):
    path = self.child(labels=(("same", "port_in", 100),
                              ("same", "port_in", 200)))
    warnings = [i for i in Document.load(path).validate()
                if i.level == "warning" and "named" in i.message]
    self.assertEqual(len(warnings), 1)
    self.assertIn("'same'", warnings[0].message)


class TestTheDerivedBlock(SheetCase):

  def open_parent(self, **kwargs):
    self.child(**kwargs.pop("child", {}))
    return sheets.open_document(self.parent(**kwargs))

  def test_the_blocks_pins_are_the_childs_ports(self):
    doc, registry, issues = self.open_parent()
    self.assertEqual(issues, [])
    symbol = registry.for_cell(doc.cell("u1"))
    self.assertEqual([p["name"] for p in symbol.pins], ["a", "y"])

  def test_inputs_sit_on_the_left_and_outputs_on_the_right(self):
    doc, registry, _ = self.open_parent()
    symbol = registry.for_cell(doc.cell("u1"))
    pins = {p["name"]: p for p in symbol.pins}
    self.assertEqual(pins["a"]["x"], 0)
    self.assertEqual(pins["y"]["x"], symbol.width)

  def test_renaming_a_port_renames_the_pin(self):
    # The whole point: nothing about the parent has to be edited, and a wire
    # left on the old name fails loudly instead of pointing at nothing.
    self.child()
    path = self.parent(nets=[{"id": "n1", "name": None,
                              "from": {"cell": "u1", "pin": "y"},
                              "to": {"cell": "u1", "pin": "a"},
                              "waypoints": [], "style": {}}])
    doc, registry, _ = sheets.open_document(path)
    self.assertEqual([i for i in doc.validate(registry) if i.level == "error"], [])

    self.child(labels=(("a", "port_in", 100), ("q", "port_out", 200)))
    doc, registry, _ = sheets.open_document(path)
    symbol = registry.for_cell(doc.cell("u1"))
    self.assertIn("q", [p["name"] for p in symbol.pins])
    errors = [i for i in doc.validate(registry) if i.level == "error"]
    self.assertTrue(any("'y'" in i.message for i in errors),
                    "a wire left on the old pin name should be an error")

  def test_a_sheet_block_is_not_offered_in_the_palette(self):
    _doc, registry, _ = self.open_parent()
    self.assertNotIn("sheet:child.dlg", registry.ids())
    self.assertIn("sheet:child.dlg", registry.ids(listed_only=False))

  def test_the_pins_have_names_drawn_on_them(self):
    doc, registry, _ = self.open_parent()
    svg = render_svg.render(doc, registry=registry)
    self.assertIn(">a<", svg)
    self.assertIn(">y<", svg)

  def test_wires_reach_the_derived_pins(self):
    self.child()
    path = self.parent(nets=[{"id": "n1", "name": None,
                              "from": {"cell": "u1", "pin": "y"},
                              "to": {"cell": "u1", "pin": "a"},
                              "waypoints": [], "style": {}}])
    doc, registry, _ = sheets.open_document(path)
    points = routing.route(doc, doc.nets[0], registry)
    self.assertGreaterEqual(len(points), 2)


class TestWhenItGoesWrong(SheetCase):

  def test_a_missing_drawing_is_an_error(self):
    doc, registry, issues = sheets.open_document(self.parent(ref="nope.dlg"))
    self.assertTrue(any("no such drawing" in i.message for i in issues))
    self.assertEqual([i.level for i in issues], ["error"])

  def test_and_is_still_drawn_so_it_can_be_selected_and_fixed(self):
    doc, registry, _ = sheets.open_document(self.parent(ref="nope.dlg"))
    self.assertIsNotNone(registry.for_cell(doc.cell("u1")))
    self.assertIn("not found", render_svg.render(doc, registry=registry))

  def test_a_loop_is_caught_rather_than_followed(self):
    # a.dlg instantiates b.dlg, which instantiates a.dlg again.
    write(self.dir, "b.dlg", [{"id": "u_a", "type": "sheet", "ref": "a.dlg",
                               "x": 100, "y": 100, "label": "U_A"}])
    path = write(self.dir, "a.dlg", [{"id": "u_b", "type": "sheet",
                                      "ref": "b.dlg", "x": 100, "y": 100,
                                      "label": "U_B"}])
    _doc, _registry, issues = sheets.open_document(path)
    self.assertTrue(any("refers back" in i.message for i in issues),
                    [str(i) for i in issues])

  def test_an_unresolved_reference_reads_as_a_validation_error(self):
    self.child()
    doc = Document.load(self.parent())
    errors = [i for i in doc.validate() if i.level == "error"]
    self.assertTrue(any("has not been resolved" in i.message for i in errors))


class TestOneDrawingCannotAffectAnother(SheetCase):

  def test_resolving_leaves_the_shared_library_alone(self):
    self.child()
    sheets.open_document(self.parent())
    self.assertIsNone(default_registry().get("sheet:child.dlg"))

  def test_the_same_ref_in_two_folders_means_two_different_drawings(self):
    # Both parents say `ref: "child.dlg"`, but from different folders, so the
    # text names different files. Sharing one registry would draw one of them
    # with the other's pins.
    here = os.path.join(self.dir, "here")
    there = os.path.join(self.dir, "there")
    for directory, labels in ((here, (("a", "port_in", 100),)),
                              (there, (("zzz", "port_in", 100),))):
      os.makedirs(directory)
      write(directory, "child.dlg",
            [port("p0", kind, label, y) for label, kind, y in labels])
      write(directory, "top.dlg",
            [{"id": "u1", "type": "sheet", "ref": "child.dlg",
              "x": 200, "y": 100, "label": "U1"}])

    names = []
    for directory in (here, there):
      doc, registry, _ = sheets.open_document(os.path.join(directory, "top.dlg"))
      names.append([p["name"] for p in registry.for_cell(doc.cell("u1")).pins])
    self.assertEqual(names, [["a"], ["zzz"]])


class TestTheShippedExample(unittest.TestCase):

  def test_the_top_sheet_resolves_and_routes_straight(self):
    doc, registry, issues = sheets.open_document(
      os.path.join(ROOT, "examples", "fifo_top.dlg"))
    self.assertEqual(issues, [])
    self.assertEqual([i for i in doc.validate(registry) if i.level == "error"], [])

    routes = routing.route_all(doc, registry)
    self.assertTrue(routes)
    bent = [net.get("id") for net, points in routes if len(points) > 2]
    self.assertEqual(bent, [], "every wire on the top sheet should run straight")

  def test_the_hierarchy_is_reported(self):
    doc = Document.load(os.path.join(ROOT, "examples", "fifo_top.dlg"))
    rows = sheets.tree(doc)
    self.assertEqual([(depth, ref) for depth, ref, _ in rows],
                     [(0, "cdc_fifo.dlg")])
    self.assertIsNotNone(rows[0][2])


if __name__ == "__main__":
  unittest.main()
