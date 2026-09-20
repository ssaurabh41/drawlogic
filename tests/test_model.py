"""Document format, symbol library and bus naming."""

import json
import re
import unittest

from drawlogic import doc as docmod
from drawlogic.doc import Document, DocumentError, new_document
from drawlogic.symbols import Symbol, SymbolError, default_registry
from tests import EXAMPLE


class TestRoundTrip(unittest.TestCase):

  def test_new_document_round_trips(self):
    doc = new_document("alu_ctrl")
    doc.cells.append({"id": "u1", "type": "and2", "x": 10, "y": 20})
    doc.normalize()

    reloaded = Document.loads(doc.dumps())
    self.assertEqual(reloaded.title, "alu_ctrl")
    self.assertEqual(len(reloaded.cells), 1)
    self.assertEqual(reloaded.cell("u1")["type"], "and2")

  def test_missing_size_is_filled_from_the_symbol(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.normalize()
    self.assertEqual(doc.cell("u1")["w"], 60)
    self.assertEqual(doc.cell("u1")["h"], 40)

  def test_key_order_is_stable_so_diffs_stay_readable(self):
    doc = new_document()
    doc.cells.append({"style": {}, "type": "inv", "y": 5, "x": 1, "id": "u9"})
    doc.normalize()
    emitted = json.loads(doc.dumps())
    self.assertEqual(list(emitted.keys())[:4], ["format", "version", "title", "canvas"])
    self.assertEqual(list(emitted["cells"][0].keys())[:4], ["id", "type", "x", "y"])

  def test_dumps_is_idempotent(self):
    doc = Document.load(EXAMPLE)
    once = doc.dumps()
    twice = Document.loads(once).dumps()
    self.assertEqual(once, twice)

  def test_rejects_foreign_files(self):
    with self.assertRaises(DocumentError):
      Document.loads('{"format": "something-else", "version": 1}')
    with self.assertRaises(DocumentError):
      Document.loads("not json at all")
    with self.assertRaises(DocumentError):
      Document.loads('{"format": "drawlogic", "version": 99}')


class TestValidate(unittest.TestCase):

  def _errors(self, doc):
    return [i for i in doc.validate() if i.level == "error"]

  def test_example_has_no_errors(self):
    self.assertEqual(self._errors(Document.load(EXAMPLE)), [])

  def test_unknown_cell_type_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "flux_capacitor", "x": 0, "y": 0,
                      "w": 10, "h": 10})
    self.assertTrue(any("unknown cell type" in i.message for i in self._errors(doc)))

  def test_net_to_a_pin_that_does_not_exist_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "zzz"}})
    doc.normalize()
    self.assertTrue(any("no such pin" in i.message for i in self._errors(doc)))

  def test_net_to_a_missing_cell_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "ghost", "pin": "a"}})
    doc.normalize()
    self.assertTrue(any("missing cell" in i.message for i in self._errors(doc)))

  def test_duplicate_ids_are_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u1", "type": "inv", "x": 100, "y": 0})
    doc.normalize()
    self.assertTrue(any("duplicate id" in i.message for i in self._errors(doc)))

  def test_bus_name_must_match_declared_width(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]", "width": 4,
                     "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    self.assertTrue(any("implies width" in i.message for i in self._errors(doc)))

  def test_a_bus_on_a_single_bit_pin_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]",
                     "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    doc.normalize()
    self.assertTrue(any("8-bit net" in i.message for i in self._errors(doc)))

  def test_a_bus_on_a_width_zero_pin_is_allowed(self):
    # Width 0 declares a pin that takes a bus of any width, which is what a
    # generic block port and a bus ripper use.
    doc = new_document()
    doc.cells.append({"id": "pd", "type": "port_in", "x": 0, "y": 0})
    doc.cells.append({"id": "b1", "type": "block", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]",
                     "from": {"cell": "pd", "pin": "p"},
                     "to": {"cell": "b1", "pin": "in1"}})
    doc.normalize()
    self.assertEqual(self._errors(doc), [])

  def test_unconnected_pin_is_only_a_warning(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.normalize()
    issues = doc.validate()
    self.assertEqual([i for i in issues if i.level == "error"], [])
    self.assertTrue(any("unconnected" in i.message for i in issues))

  def test_group_member_must_exist(self):
    doc = new_document()
    doc.groups.append({"id": "g1", "members": ["nope"]})
    self.assertTrue(any("does not exist" in i.message for i in self._errors(doc)))


class TestBusNames(unittest.TestCase):

  def test_width_from_name(self):
    self.assertEqual(docmod.net_name_width("d[7:0]"), 8)
    self.assertEqual(docmod.net_name_width("d[3]"), 1)
    self.assertEqual(docmod.net_name_width("clk"), 1)
    self.assertEqual(docmod.net_name_width("addr[31:16]"), 16)

  def test_is_bus(self):
    self.assertTrue(docmod.is_bus_name("d[7:0]"))
    self.assertFalse(docmod.is_bus_name("d[0]"))
    self.assertFalse(docmod.is_bus_name("reset_n"))

  def test_expansion_is_msb_first(self):
    self.assertEqual(docmod.bus_bits("d[3:0]"), ["d[3]", "d[2]", "d[1]", "d[0]"])
    self.assertEqual(docmod.bus_bits("d[0:2]"), ["d[0]", "d[1]", "d[2]"])

  def test_illegal_names_are_rejected(self):
    self.assertIsNone(docmod.parse_net_name("9lives"))
    self.assertIsNone(docmod.parse_net_name("a b"))
    self.assertIsNone(docmod.parse_net_name(""))


class TestRegistry(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def test_builtin_symbols_load(self):
    for expected in ("inv", "and2", "nand2", "or2", "xor2", "dff", "mux2",
                     "nmos", "pmos", "block", "port_in", "port_out"):
      self.assertIn(expected, self.registry, "missing built-in symbol %s" % expected)

  def test_pins_sit_inside_the_symbol_box(self):
    for type_id in self.registry.ids():
      symbol = self.registry.require(type_id)
      for pin in symbol.pins:
        self.assertGreaterEqual(pin["x"], 0, "%s.%s" % (type_id, pin["name"]))
        self.assertGreaterEqual(pin["y"], 0, "%s.%s" % (type_id, pin["name"]))
        self.assertLessEqual(pin["x"], symbol.width, "%s.%s" % (type_id, pin["name"]))
        self.assertLessEqual(pin["y"], symbol.height, "%s.%s" % (type_id, pin["name"]))

  def test_every_symbol_has_at_least_one_pin(self):
    for type_id in self.registry.ids():
      self.assertTrue(self.registry.require(type_id).pins,
                      "%s has no pins, so nothing can connect to it" % type_id)

  def test_rejects_bad_definitions(self):
    with self.assertRaises(SymbolError):
      Symbol("broken", {"size": [0, 10]})
    with self.assertRaises(SymbolError):
      Symbol("broken", {"size": [10, 10], "pins": [{"name": "a"}, {"name": "a"}]})
    with self.assertRaises(SymbolError):
      Symbol("broken", {"size": [10, 10], "draw": [{"op": "spiral"}]})


class TestPlacement(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()
    self.and2 = self.registry.require("and2")

  def _cell(self, **overrides):
    cell = {"id": "u1", "type": "and2", "x": 0, "y": 0, "w": 60, "h": 40,
            "rotate": 0, "mirror": False}
    cell.update(overrides)
    return cell

  def test_pin_at_natural_size_is_the_local_position(self):
    x, y = self.and2.pin_position(self._cell(), "y")
    self.assertAlmostEqual(x, 60)
    self.assertAlmostEqual(y, 20)

  def test_translation_moves_pins(self):
    x, y = self.and2.pin_position(self._cell(x=100, y=200), "y")
    self.assertAlmostEqual(x, 160)
    self.assertAlmostEqual(y, 220)

  def test_resize_scales_pins(self):
    x, y = self.and2.pin_position(self._cell(w=120, h=80), "y")
    self.assertAlmostEqual(x, 120)
    self.assertAlmostEqual(y, 40)

  def test_rotation_keeps_the_centre_fixed(self):
    # Rotating 90 degrees clockwise sends the east output pin to the south.
    x, y = self.and2.pin_position(self._cell(rotate=90), "y")
    self.assertAlmostEqual(x, 30)
    self.assertAlmostEqual(y, 50)

  def test_mirror_flips_left_to_right(self):
    x, y = self.and2.pin_position(self._cell(mirror=True), "y")
    self.assertAlmostEqual(x, 0)
    self.assertAlmostEqual(y, 20)

  def test_unknown_pin_returns_none(self):
    self.assertIsNone(self.and2.pin_position(self._cell(), "nope"))


class TestGroupValidation(unittest.TestCase):
  """Shapes group exactly as cells do, so validate has to accept them."""

  def _grouped(self, members, cells=(), shapes=()):
    doc = new_document("grouped")
    doc.cells.extend(cells)
    doc.shapes.extend(shapes)
    doc.groups.append({"id": "g1", "members": list(members)})
    doc.normalize()
    return [i for i in doc.validate() if i.level == "error"]

  def test_a_group_of_shapes_is_valid(self):
    errors = self._grouped(
      ["s1", "s2"],
      shapes=[{"id": "s1", "kind": "rect", "x": 0, "y": 0, "w": 40, "h": 40},
              {"id": "s2", "kind": "rect", "x": 60, "y": 0, "w": 40, "h": 40}])
    self.assertEqual(errors, [],
                     "the editor groups shapes like cells, so a file it "
                     "wrote must validate: %s" % [i.message for i in errors])

  def test_a_group_mixing_a_cell_and_a_shape_is_valid(self):
    errors = self._grouped(
      ["u1", "s1"],
      cells=[{"id": "u1", "type": "inv", "x": 0, "y": 0}],
      shapes=[{"id": "s1", "kind": "rect", "x": 0, "y": 0, "w": 40, "h": 40}])
    self.assertEqual(errors, [], [i.message for i in errors])

  def test_a_member_that_really_is_missing_is_still_reported(self):
    errors = self._grouped(
      ["s1", "ghost"],
      shapes=[{"id": "s1", "kind": "rect", "x": 0, "y": 0, "w": 40, "h": 40}])
    self.assertEqual(len(errors), 1, "widening the check must not blind it")
    self.assertIn("ghost", errors[0].message)


class TestMalformedContainers(unittest.TestCase):
  """A key that is present but holds the wrong type must be refused here.

  setdefault only fills an absent key, so these used to pass normalize()
  untouched and fail much later -- as a traceback from the command line, and
  as a dropped connection over HTTP.
  """

  def test_a_wrong_typed_section_is_named(self):
    for data, expected in (
        ({"canvas": None}, "canvas must be an object"),
        ({"canvas": []}, "canvas must be an object"),
        ({"canvas": {"grid": 3}}, "canvas.grid must be an object"),
        ({"canvas": {"font": "big"}}, "canvas.font must be an object"),
        ({"cells": "nope"}, "cells must be a list"),
        ({"nets": {}}, "nets must be a list"),
        ({"shapes": 7}, "shapes must be a list"),
        ({"groups": "g"}, "groups must be a list"),
        ({"cells": [1]}, "cells[0] must be an object")):
      with self.subTest(data=data):
        payload = {"format": "drawlogic", "version": 2}
        payload.update(data)
        with self.assertRaises(DocumentError) as caught:
          Document.from_data(payload)
        self.assertIn(expected, str(caught.exception))

  def test_a_document_that_is_not_an_object_is_refused(self):
    for bad in ([], "text", 3, None):
      with self.subTest(data=bad):
        with self.assertRaises(DocumentError):
          Document.from_data(bad)


if __name__ == "__main__":
  unittest.main()


class TestEveryPinSitsOnTheGrid(unittest.TestCase):
  """Pins land on multiples of five, so a dragged wire can reach them.

  A cell is dropped on the drawing's grid and a pin sits at a fixed offset
  inside its symbol, so the pin's place on the sheet is the sum of the two. If
  that offset is not a multiple of the step a wire is dragged on, no amount of
  careful dragging will ever line the wire up with the pin -- it will always
  stop a unit or two short, and the near-miss is drawn as a kink.

  Most of the library already obeyed this. block6 and block8 did not, with
  pins at 24, 26, 58, 96, 102 and 134.
  """

  STEP = 5

  # block6 and block8 sit at 24, 26, 58, 96, 102 and 134, and are left there.
  # Moving them to multiples of five is a one-line change to symbols.json and
  # it makes the drawings worse: cdc_fifo and spi_master were drawn against
  # these offsets, so every cell wired to one of those blocks lines up with it
  # exactly, and shifting a pin by a unit or two turns a straight wire into a
  # 1.2-unit jog. cdc_fifo went from two warnings to six when it was tried.
  #
  # Nor would it be enough on its own: cdc_fifo stretches its blocks by 1.25,
  # and a stretch multiplies the offset, so no fixed grid in symbol space
  # survives it. 24 happens to scale to 30 and 25 to 31.25, which is how the
  # old numbers turned out to be the better ones for that drawing.
  GRANDFATHERED = ("block6", "block8")

  def test_no_new_symbol_has_a_pin_off_the_grid(self):
    registry = default_registry()
    stray = []
    for symbol_id in registry.ids():
      if symbol_id in self.GRANDFATHERED:
        continue
      symbol = registry.get(symbol_id)
      for pin in symbol.pins:
        if pin["x"] % self.STEP or pin["y"] % self.STEP:
          stray.append("%s.%s at (%g, %g)"
                       % (symbol_id, pin["name"], pin["x"], pin["y"]))
    self.assertEqual(stray, [],
                     "pins off the %d grid: %s" % (self.STEP, "; ".join(stray)))

  def test_the_grandfathered_two_are_still_the_only_ones(self):
    """So the exemption shrinks when one of them is fixed, rather than hiding
    the next symbol that drifts off the grid."""
    registry = default_registry()
    off = [symbol_id for symbol_id in registry.ids()
           for pin in registry.get(symbol_id).pins
           if pin["x"] % self.STEP or pin["y"] % self.STEP]
    self.assertEqual(sorted(set(off)), sorted(self.GRANDFATHERED))

  def test_a_placed_pin_lands_on_the_grid_too(self):
    """The offset is only half of it; the cell has to be on the grid as well."""
    registry = default_registry()
    doc = new_document("grid", 400, 300)
    doc.cells.append({"id": "u", "type": "dffr", "x": 100, "y": 60})
    doc.normalize()
    cell = doc.cells[0]
    symbol = registry.for_cell(cell)
    for pin in symbol.pins:
      spot = symbol.pin_position(cell, pin["name"], doc.symbol_scale)
      self.assertEqual(
        (spot[0] % self.STEP, spot[1] % self.STEP), (0, 0),
        "pin %s of a cell on the grid landed at %s" % (pin["name"], spot))
