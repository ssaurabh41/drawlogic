import unittest

from drawlogic.symbols import Symbol, SymbolError, default_registry


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


if __name__ == "__main__":
  unittest.main()
