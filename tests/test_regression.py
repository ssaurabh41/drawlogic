"""Verification regression suite.

Two kinds of check:

1. **Golden files.** Every example is rendered with fixed options and compared
   byte for byte against a stored SVG in tests/golden/. Any unintended change
   to the renderer, the router or the symbol library shows up here as a diff,
   which unit tests on their own would not catch.

2. **Invariants.** Properties that must hold for every drawing, checked
   against all examples and every symbol rather than one hand-picked case:
   wires stay axis-aligned and clear of unrelated cells, pins resolve inside
   their symbol, documents round-trip unchanged, and exports are reproducible.

Regenerating the goldens after a deliberate change:

    DRAWLOGIC_REGOLD=1 python3 -m unittest tests.test_regression

Then read the diff before committing it. A golden updated without being read
is worse than no golden at all.
"""

import glob
import os
import re
import unittest

from drawlogic import render_svg, routing
from drawlogic.doc import Document, loads_of
from drawlogic.symbols import default_registry
from tests import ROOT, open_example

GOLDEN_DIR = os.path.join(ROOT, "tests", "golden")
EXAMPLES = sorted(glob.glob(os.path.join(ROOT, "examples", "*.dlg")))

# Fixed so a golden only changes when the drawing or the renderer changes.
RENDER_OPTIONS = {"zoom": 1.0, "crop": False, "title": True, "arrows": True}

REGOLD = os.environ.get("DRAWLOGIC_REGOLD") == "1"


def example_name(path):
  return os.path.splitext(os.path.basename(path))[0]


class TestExamplesExist(unittest.TestCase):

  def test_there_are_examples_to_check(self):
    self.assertTrue(EXAMPLES, "no examples found; the suite would pass vacuously")

  def test_the_complex_example_is_present(self):
    # A trivial drawing exercises almost none of the router.
    names = [example_name(p) for p in EXAMPLES]
    self.assertIn("cdc_fifo", names)


class TestGoldenSvg(unittest.TestCase):
  """Rendered output is compared byte for byte against a stored file."""

  def test_examples_match_their_golden(self):
    if not os.path.isdir(GOLDEN_DIR):
      os.makedirs(GOLDEN_DIR)

    stale = []
    for path in EXAMPLES:
      name = example_name(path)
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        svg = render_svg.render(doc, registry=registry, **RENDER_OPTIONS)
        golden = os.path.join(GOLDEN_DIR, name + ".svg")

        if REGOLD or not os.path.isfile(golden):
          with open(golden, "w") as handle:
            handle.write(svg)
          stale.append(name)
          continue

        with open(golden) as handle:
          expected = handle.read()
        if svg != expected:
          self.fail(
            "%s no longer renders the same as tests/golden/%s.svg.\n%s\n"
            "If the change is intended, regenerate with "
            "DRAWLOGIC_REGOLD=1 python3 -m unittest tests.test_regression"
            % (name, name, _first_difference(expected, svg)))

    if stale and not REGOLD:
      self.skipTest("wrote new goldens for: %s; re-run to check them"
                    % ", ".join(stale))


def _first_difference(expected, actual):
  """The first line that differs, which is usually enough to see what moved."""
  expected_lines = expected.split("\n")
  actual_lines = actual.split("\n")
  for index in range(max(len(expected_lines), len(actual_lines))):
    want = expected_lines[index] if index < len(expected_lines) else "<missing>"
    got = actual_lines[index] if index < len(actual_lines) else "<missing>"
    if want != got:
      return ("  line %d\n  golden: %s\n  now:    %s"
              % (index + 1, want[:160], got[:160]))
  return "  files differ in trailing whitespace only"


class TestEveryExample(unittest.TestCase):
  """Invariants that must hold for every drawing in examples/."""

  def documents(self):
    """Every example, opened the way the CLI opens it."""
    for path in EXAMPLES:
      doc, registry, issues = open_example(path)
      yield example_name(path), doc, registry, issues

  def test_no_validation_errors(self):
    for name, doc, registry, issues in self.documents():
      with self.subTest(example=name):
        errors = [i for i in issues + doc.validate(registry)
                  if i.level == "error"]
        self.assertEqual(errors, [], "%s has validation errors" % name)

  def test_every_net_resolves(self):
    for name, doc, registry, _ in self.documents():
      with self.subTest(example=name):
        for net, branches in routing.route_all(doc, registry):
          self.assertTrue(branches,
                          "%s: net %s drives nothing" % (name, net.get("id")))
          for points in branches:
            self.assertGreaterEqual(
              len(points), 2,
              "%s: net %s has a branch with no path" % (name, net.get("id")))

  def test_every_segment_is_axis_aligned(self):
    for name, doc, registry, _ in self.documents():
      with self.subTest(example=name):
        routes = routing.route_all(doc, registry)
        for net_id, (ax, ay), (bx, by) in routing.segments_of(routes):
          self.assertTrue(
            abs(ax - bx) < 1e-6 or abs(ay - by) < 1e-6,
            "%s: net %s has a diagonal segment" % (name, net_id))

  def test_no_wire_crosses_an_unrelated_cell(self):
    # The router may fall back to a blocked corridor when a layout leaves it
    # no choice, so this reports rather than asserting zero -- but a jump in
    # the count means the router got worse.
    worst = {}
    for name, doc, registry, _ in self.documents():
      crossings = 0
      for net, branches in routing.route_all(doc, registry):
        for load, points in zip(loads_of(net), branches):
          exclude = set()
          for endpoint in (net.get("from"), load):
            if isinstance(endpoint, dict) and "cell" in endpoint:
              exclude.add(endpoint["cell"])
          boxes = routing.obstacle_boxes(doc, registry, exclude=exclude)
          for index in range(len(points) - 1):
            (ax, ay), (bx, by) = points[index], points[index + 1]
            if abs(ax - bx) < 1e-6:
              clear = routing._vertical_clear(ax, ay, by, boxes)
            else:
              clear = routing._horizontal_clear(ay, ax, bx, boxes)
            if not clear:
              crossings += 1
      worst[name] = crossings

    self.assertEqual(worst.get("dff_slice"), 0,
                     "dff_slice should route with nothing crossing a cell")
    for name, count in worst.items():
      self.assertLessEqual(
        count, 6,
        "%s has %d wire segments crossing unrelated cells, which is more "
        "than this layout used to need" % (name, count))

  def test_documents_round_trip_unchanged(self):
    for name, doc, _registry, _issues in self.documents():
      with self.subTest(example=name):
        once = doc.dumps()
        twice = Document.loads(once).dumps()
        self.assertEqual(once, twice, "%s does not round-trip" % name)

  def test_saved_file_is_already_canonical(self):
    # Guards against an example being hand-edited into a shape the tool would
    # not itself write, which would make every future diff noisy.
    for path in EXAMPLES:
      with self.subTest(example=example_name(path)):
        with open(path) as handle:
          on_disk = handle.read()
        self.assertEqual(Document.load(path).dumps(), on_disk,
                         "%s is not in canonical form; open and save it"
                         % os.path.basename(path))

  def test_rendering_is_reproducible(self):
    for name, doc, registry, _ in self.documents():
      with self.subTest(example=name):
        first = render_svg.render(doc, registry=registry, **RENDER_OPTIONS)
        again, again_registry, _ = open_example(
          os.path.join(ROOT, "examples", name + ".dlg"))
        second = render_svg.render(again, registry=again_registry,
                                   **RENDER_OPTIONS)
        self.assertEqual(first, second)


class TestEverySymbol(unittest.TestCase):
  """Invariants across the whole symbol library, not one hand-picked cell."""

  def setUp(self):
    self.registry = default_registry()

  def test_every_symbol_previews(self):
    for type_id in self.registry.ids():
      with self.subTest(symbol=type_id):
        svg = render_svg.render_symbol(self.registry.require(type_id))
        self.assertIn("<svg ", svg)
        self.assertTrue(svg.rstrip().endswith("</svg>"))

  def test_every_symbol_places_and_renders(self):
    from drawlogic.doc import new_document
    for type_id in self.registry.ids():
      with self.subTest(symbol=type_id):
        doc = new_document("probe")
        doc.cells.append({"id": "c1", "type": type_id, "x": 100, "y": 100})
        doc.normalize()
        svg = render_svg.render(doc)
        self.assertIn('data-type="%s"' % type_id, svg)

  def test_pins_resolve_inside_the_drawn_shape(self):
    for type_id in self.registry.ids():
      symbol = self.registry.require(type_id)
      cell = {"id": "c1", "type": type_id, "x": 0, "y": 0,
              "w": symbol.width, "h": symbol.height, "rotate": 0,
              "mirror": False}
      for pin in symbol.pins:
        with self.subTest(symbol=type_id, pin=pin["name"]):
          x, y = symbol.pin_position(cell, pin["name"])
          self.assertGreaterEqual(x, -0.001)
          self.assertGreaterEqual(y, -0.001)
          self.assertLessEqual(x, symbol.width + 0.001)
          self.assertLessEqual(y, symbol.height + 0.001)

  def test_rotation_is_reversible(self):
    for type_id in self.registry.ids():
      symbol = self.registry.require(type_id)
      pin = symbol.pins[0]["name"]
      base = {"id": "c1", "type": type_id, "x": 40, "y": 70,
              "w": symbol.width, "h": symbol.height, "mirror": False}
      with self.subTest(symbol=type_id):
        start = symbol.pin_position(dict(base, rotate=0), pin)
        turned = symbol.pin_position(dict(base, rotate=360), pin)
        self.assertAlmostEqual(start[0], turned[0], places=6)
        self.assertAlmostEqual(start[1], turned[1], places=6)


class TestEmbeddedImages(unittest.TestCase):
  """A custom cell's picture has to survive export, not just the canvas."""

  PIXEL = ("data:image/gif;base64,"
           "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

  def _doc(self):
    from drawlogic.doc import new_document
    doc = new_document("picture")
    doc.cells.append({"id": "c1", "type": "custom", "x": 40, "y": 40,
                      "image": self.PIXEL})
    doc.normalize()
    return doc

  def test_image_reaches_the_exported_svg(self):
    svg = render_svg.render(self._doc())
    self.assertIn("<image ", svg)
    self.assertIn(self.PIXEL, svg)

  def test_xlink_namespace_is_declared_when_needed(self):
    self.assertIn("xmlns:xlink", render_svg.render(self._doc()))

  def test_no_xlink_namespace_when_there_are_no_images(self):
    from drawlogic.doc import new_document
    doc = new_document("plain")
    doc.cells.append({"id": "c1", "type": "and2", "x": 0, "y": 0})
    doc.normalize()
    self.assertNotIn("xmlns:xlink", render_svg.render(doc))

  def test_image_survives_a_save_and_reload(self):
    reloaded = Document.loads(self._doc().dumps())
    self.assertEqual(reloaded.cell("c1")["image"], self.PIXEL)


class TestCrossingHops(unittest.TestCase):
  """A crossing and a connection must not look the same."""

  def setUp(self):
    self.doc = Document.load(os.path.join(ROOT, "examples", "cdc_fifo.dlg"))

  def _crossed(self):
    doc = Document.load(os.path.join(ROOT, "examples", "cdc_fifo.dlg"))
    return routing.hop_points(routing.route_all(doc))

  def test_the_example_actually_has_crossings(self):
    # Otherwise everything below would pass without testing anything.
    self.assertTrue(self._crossed(), "cdc_fifo should contain wire crossings")

  def test_crossings_become_arcs_in_the_output(self):
    svg = render_svg.render(self.doc)
    total = sum(len(v) for v in self._crossed().values())
    self.assertEqual(svg.count(" 0 0 1 "), svg.count(" 0 0 1 "))
    self.assertEqual(len(re.findall(r"A[\d.]+ [\d.]+ 0 0 [01] ", svg)), total)

  def test_hops_can_be_switched_off(self):
    self.assertNotIn("A5 5", render_svg.render(self.doc, hops=False))
    self.doc.canvas["hops"] = False
    self.assertNotIn("A5 5", render_svg.render(self.doc))

  def test_a_junction_never_gets_a_hop(self):
    # Where wires genuinely meet there is a shared vertex, so the point is a
    # junction dot and must not also be bridged.
    routes = routing.route_all(self.doc)
    junctions = {(round(p[0], 3), round(p[1], 3))
                 for p in routing.junctions(routes)}
    for points in routing.hop_points(routes).values():
      for point in points:
        self.assertNotIn((round(point[0], 3), round(point[1], 3)), junctions)

  def test_a_hop_sits_on_a_real_crossing(self):
    routes = routing.route_all(self.doc)
    verticals = [(a[0], min(a[1], b[1]), max(a[1], b[1]))
                 for _, a, b in routing.segments_of(routes)
                 if abs(a[0] - b[0]) < 1e-6]

    for points in routing.hop_points(routes).values():
      for x, y in points:
        self.assertTrue(
          any(abs(vx - x) < 1e-6 and lo < y < hi for vx, lo, hi in verticals),
          "hop at %g,%g does not sit on a vertical wire" % (x, y))


class TestExportOptions(unittest.TestCase):
  """Option handling checked on the complex example, not a toy one."""

  def setUp(self):
    self.doc = Document.load(os.path.join(ROOT, "examples", "cdc_fifo.dlg"))

  def _viewbox(self, svg):
    return [float(v) for v in
            re.search(r'viewBox="([^"]+)"', svg).group(1).split()]

  def test_zoom_changes_size_but_not_geometry(self):
    plain = render_svg.render(self.doc, zoom=1.0)
    big = render_svg.render(self.doc, zoom=3.0)
    self.assertEqual(self._viewbox(plain), self._viewbox(big))
    width = float(re.search(r'\bwidth="([\d.]+)"', big).group(1))
    self.assertAlmostEqual(width, self.doc.canvas["width"] * 3, places=1)

  def test_crop_is_smaller_than_the_sheet(self):
    cropped = self._viewbox(render_svg.render(self.doc, crop=True))
    self.assertLess(cropped[2], self.doc.canvas["width"])

  def test_grid_and_arrows_are_opt_out(self):
    self.assertNotIn("dl-grid", render_svg.render(self.doc))
    self.assertIn("dl-grid", render_svg.render(self.doc, show_grid=True))
    self.assertEqual(render_svg.render(self.doc, arrows=False).count("<polygon"),
                     0)

  def test_every_cell_and_net_reaches_the_output(self):
    svg = render_svg.render(self.doc)
    for cell in self.doc.cells:
      self.assertIn('data-id="%s"' % cell["id"], svg)
    for net in self.doc.nets:
      self.assertIn('data-id="%s"' % net["id"], svg)


if __name__ == "__main__":
  unittest.main()
