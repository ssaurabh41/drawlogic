"""The browser router must agree with the Python one, net for net.

drawlogic/web/js/routing.js is a hand-written port of drawlogic/routing.py.
Nothing else in the suite looks at the JavaScript at all, so the two can drift
apart silently -- and a drawing that exports correctly but comes out wrong on
the canvas (or the reverse) is the worst kind of bug to chase.

Node is not a dependency of drawlogic, so these tests skip themselves when it
is not installed. Run them with:

    python3 -m unittest tests.test_js_parity
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from drawlogic import drc, layout, render_svg, routing, theme
from drawlogic.doc import new_document
from drawlogic.symbols import default_registry

from tests import ROOT, open_example

NODE = shutil.which("node")
DUMP = os.path.join(ROOT, "tests", "js", "route_dump.mjs")
EXAMPLES = os.path.join(ROOT, "examples")


def _round(value, places=3):
  return round(float(value), places)


def _rounded(branches):
  return [[[_round(x), _round(y)] for x, y in points] for points in branches]


def _theme_payload():
  """The same theme the server hands the browser."""
  return {
    "colors": theme.COLORS, "widths": theme.WIDTHS,
    "fontSizes": theme.FONT_SIZES, "roleStyles": theme.ROLE_STYLES,
    "fontSans": theme.FONT_SANS, "fontMono": theme.FONT_MONO,
    "junctionRadius": theme.JUNCTION_RADIUS, "arrowSize": theme.ARROW_SIZE,
    "arrowSpacing": theme.ARROW_SPACING, "hopRadius": theme.HOP_RADIUS,
    "pinLabelInset": theme.PIN_LABEL_INSET,
  }


def _browser_result(path, registry):
  """Route and lay out a drawing in node, using what Python resolved for it.

  Handing node drawlogic/symbols.json instead would leave a referenced drawing
  with no symbol, so every net would route to nothing -- and match a Python
  side that had not resolved either. Two empty answers agree.
  """
  handles = []
  try:
    for payload in (registry.as_data(), _theme_payload(), drc.as_data()):
      handle, name = tempfile.mkstemp(suffix=".json")
      with os.fdopen(handle, "w") as out:
        json.dump(payload, out)
      handles.append(name)
    return json.loads(subprocess.check_output(
      [NODE, DUMP, handles[0], path, handles[1], handles[2]], cwd=ROOT))
  finally:
    for name in handles:
      os.unlink(name)


DRC_DUMP = os.path.join(ROOT, "tests", "js", "drc_dump.mjs")
RENDER_DUMP = os.path.join(ROOT, "tests", "js", "render_dump.mjs")


def _browser_render(doc, registry):
  """What the browser renderer actually draws, from render.render() itself."""
  handles = []
  try:
    for payload in (registry.as_data(), doc.ordered(), _theme_payload(),
                    drc.as_data()):
      handle, name = tempfile.mkstemp(suffix=".json")
      with os.fdopen(handle, "w") as out:
        json.dump(payload, out)
      handles.append(name)
    return json.loads(subprocess.check_output(
      [NODE, RENDER_DUMP] + handles, cwd=ROOT))
  finally:
    for name in handles:
      os.unlink(name)


def _exported_arrows(svg):
  """The arrow polygons in the exported file's net layer.

  Scoped to `dl-nets` because symbol artwork can be a polygon too, and both
  renderers put arrows in that group and nothing else polygonal.
  """
  start = svg.index('<g class="dl-nets">')
  end = svg.index("</g>", svg.index('<g class="dl-cells">'))
  return sorted(re.findall(r'<polygon points="([^"]+)"', svg[start:end]))


def _crossing_drawing():
  """One wire crossing another, which is drawn as a bridge.

  The smallest drawing that tells the two renderers apart: an arrow lands
  where the bridge is, so whether it is dropped depends on the thing that
  drifted.
  """
  doc = new_document("crossing", 650, 250)
  doc.canvas["grid"]["style"] = "blank"
  doc.nets.extend([
    {"id": "h", "from": {"x": 50, "y": 100}, "to": [{"x": 550, "y": 100}]},
    {"id": "v", "from": {"x": 290, "y": 50}, "to": [{"x": 290, "y": 180}]},
  ])
  doc.normalize()
  return doc


@unittest.skipUnless(NODE, "node is not installed")
class TestDrcDefaults(unittest.TestCase):
  """The limits routing.js falls back to must be the limits Python holds.

  The editor sets them from /api/drc, so a stale default never shows up
  there. It shows up as the canvas routing a drawing one way and the exporter
  routing it another, which is exactly the drift this suite exists to catch.
  """

  def test_js_defaults_match_drc_py(self):
    actual = json.loads(subprocess.check_output([NODE, DRC_DUMP], cwd=ROOT))
    expected = drc.as_data()
    for key in actual:
      self.assertIn(key, expected, "routing.js has a limit Python does not")
      self.assertAlmostEqual(
        float(actual[key]), float(expected[key]), places=6,
        msg="routing.js default for %r is stale: %r, drc.py says %r"
            % (key, actual[key], expected[key]))


@unittest.skipUnless(NODE, "node is not installed")
class TestWhatEachRendererActuallyDraws(unittest.TestCase):
  """The two renderers compared through their own drawing code.

  Every other test here compares helpers: both sides are asked the same
  question with inputs the test supplies. That caught a lot, and it could not
  catch this. The arrow comparison built its own exclusion set, left the
  crossing bridges out of it, and so did `render.js` -- so the helpers agreed,
  all six tests passed, and the editor drew an arrow on a bridge that the
  exported file did not have. Agreement between two helpers is not agreement
  between two renderers, and only one of them is what anybody sees.

  So this calls `render.render()` and `render_svg.render()` and compares the
  marks that come out.
  """

  def setUp(self):
    self.registry = default_registry()

  def test_a_crossing_gets_the_same_arrows_in_both(self):
    doc = _crossing_drawing()
    browser = _browser_render(doc, self.registry)
    exported = _exported_arrows(render_svg.render(doc, registry=self.registry))
    self.assertEqual(
      browser["arrows"], exported,
      "the editor and the exported file disagree about arrows at a crossing")

  def test_the_bridge_really_does_remove_an_arrow(self):
    """Otherwise the test above passes on a drawing where nothing is at stake
    -- two renderers agreeing that there is nothing to drop."""
    doc = _crossing_drawing()
    routes = routing.route_all(doc, self.registry)
    hop_map = routing.hop_points(routes)
    self.assertTrue([s for spots in hop_map.values() for s in spots],
                    "the fixture has no bridge, so it tests nothing")
    kept = len(_exported_arrows(
      render_svg.render(doc, registry=self.registry)))
    without = sum(
      len(list(render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                       junctions=routing.junctions(routes))))
      for _net, branches in routes for points in branches if len(points) >= 2)
    self.assertLess(kept, without,
                    "no arrow was dropped for the bridge, so both renderers "
                    "could ignore hops and still agree")

  def test_every_example_draws_the_same_arrows_in_both(self):
    for name in sorted(os.listdir(EXAMPLES)):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        doc, registry, _ = open_example(os.path.join(EXAMPLES, name))
        browser = _browser_render(doc, registry)
        exported = _exported_arrows(render_svg.render(doc, registry=registry))
        self.assertEqual(browser["arrows"], exported,
                         "%s draws differently in the editor" % name)


@unittest.skipUnless(NODE, "node is not installed")
class TestRouterParity(unittest.TestCase):

  def examples(self):
    for name in sorted(os.listdir(EXAMPLES)):
      if name.endswith(".dlg"):
        yield name, os.path.join(EXAMPLES, name)

  def test_every_example_routes_the_same_in_both(self):
    for name, path in self.examples():
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        browser = _browser_result(path, registry)
        routes = routing.route_all(doc, registry)
        self.assertTrue(any(branches for _, branches in routes),
                        "%s routed to nothing, so this proves nothing" % name)

        expected = [[net["id"], _rounded(branches)] for net, branches in routes]
        actual = [[net_id, _rounded(branches)]
                  for net_id, branches in browser["routes"]]
        self.assertEqual(actual, expected,
                         "%s: routing.js and routing.py disagree" % name)

  def test_every_example_dots_and_bridges_the_same(self):
    for name, path in self.examples():
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        browser = _browser_result(path, registry)
        routes = routing.route_all(doc, registry)

        expected_dots = sorted([_round(x), _round(y)]
                               for x, y in routing.junctions(routes))
        actual_dots = sorted([_round(x), _round(y)]
                             for x, y in browser["junctions"])
        self.assertEqual(actual_dots, expected_dots,
                         "%s: junction dots differ" % name)

        expected_hops = {
          net_id: sorted([_round(x), _round(y)] for x, y in spots)
          for net_id, spots in routing.hop_points(routes).items()}
        actual_hops = {
          net_id: sorted([_round(x), _round(y)] for x, y in spots)
          for net_id, spots in browser["hops"]}
        self.assertEqual(actual_hops, expected_hops,
                         "%s: crossing bridges differ" % name)


  def test_every_example_puts_its_names_in_the_same_place(self):
    for name, path in self.examples():
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        browser = _browser_result(path, registry)
        routes = routing.route_all(doc, registry)
        canvas = doc.canvas
        expected = render_svg._label_spots(
          routes, render_svg._cell_boxes(doc, registry),
          (canvas.get("width"), canvas.get("height")), doc.font_scale)

        actual = {net_id: ([_round(spot[0][0]), _round(spot[0][1])], spot[1])
                  for net_id, spot in browser["labels"]}
        self.assertEqual(
          actual,
          {net_id: ([_round(spot[0]), _round(spot[1])], anchor)
           for net_id, (spot, anchor, _box, _score) in expected.items()},
          "%s: net names land in different places" % name)

  def test_every_example_puts_its_arrows_in_the_same_place(self):
    for name, path in self.examples():
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        browser = _browser_result(path, registry)
        routes = routing.route_all(doc, registry)

        # Tip and direction both. Comparing tips alone left the direction
        # vector unowned: reversing every arrow in the browser renderer, so
        # that each one points back down its own wire without moving, kept
        # the whole suite green.
        expected = {
          net["id"]: [[[_round(tip[0]), _round(tip[1]),
                        _round(way[0]), _round(way[1])]
                       for tip, way in render_svg._arrow_spots(
                         points, theme.ARROW_SIZE,
                         junctions=render_svg.arrow_marks(
                           routing.junctions(routes),
                           routing.hop_points(routes)))]
                      for points in branches if len(points) >= 2]
          for net, branches in routes if branches}
        actual = {net_id: [[[_round(tip[0]), _round(tip[1]),
                             _round(way[0]), _round(way[1])]
                            for tip, way in spots]
                           for spots in per_branch]
                  for net_id, per_branch in browser["arrows"] if per_branch}
        self.assertEqual(actual, expected,
                         "%s: direction arrows differ in place or direction"
                         % name)

  def test_an_arrow_points_the_way_the_signal_travels(self):
    """Agreement is not correctness: both sides could be reversed together.

    So this one is anchored to the drawing rather than to the other
    implementation -- a wire running left to right carries an arrow pointing
    right, whatever either renderer says.
    """
    doc = new_document("direction")
    # The driver on the left and the load on the right, which is both a
    # left-to-right wire and a circuit that makes sense. It used to be the
    # other way round -- an output port wired into an input port -- which
    # drew a left-to-right arrow only because nothing yet read the pins.
    doc.cells.extend([{"id": "a", "type": "port_in", "x": 10, "y": 100},
                      {"id": "b", "type": "port_out", "x": 400, "y": 100}])
    doc.nets.append({"id": "n1", "name": "sig", "width": 1,
                     "from": {"cell": "a", "pin": "p"},
                     "to": [{"cell": "b", "pin": "p", "waypoints": []}]})
    doc.normalize()

    routes = routing.route_all(doc)
    spots = [spot
             for _net, branches in routes
             for points in branches if len(points) >= 2
             for spot in render_svg._arrow_spots(points, theme.ARROW_SIZE)]
    self.assertTrue(spots, "a wire this long should carry an arrow")
    for tip, way in spots:
      self.assertGreater(
        way[0], 0,
        "the signal runs left to right, so its arrow must point right, "
        "not back at the pin that drives it (tip=%s, direction=%s)"
        % (tip, way))


if __name__ == "__main__":
  unittest.main()


class TestForkingLateAgreesInBothRenderers(unittest.TestCase):
  """A drawing whose wires fork late routes the same in node as in Python.

  Nothing in examples/ carries the flag, because it is written by the layout
  and those files are stored as drawn. So the router parity suite above would
  go on passing with this half-built: both sides would fork early, agree
  perfectly, and prove nothing about the half that does the work. A drawing
  that asks for it is the only thing that tests it.
  """

  def laid_out_with_forking(self, name):
    """An example, laid out, with the wires told to fork late."""
    doc, registry, _ = open_example(os.path.join(EXAMPLES, name))
    layout.arrange(doc, registry)
    doc.canvas["forkLate"] = True
    return doc, registry

  def test_both_routers_agree_when_wires_fork_late(self):
    for name in ("alu_slice.dlg", "cdc_fifo.dlg", "spi_master.dlg"):
      with self.subTest(example=name):
        doc, registry = self.laid_out_with_forking(name)
        handle, path = tempfile.mkstemp(suffix=".dlg")
        os.close(handle)
        try:
          doc.save(path)
          browser = _browser_result(path, registry)
          routes = routing.route_all(doc, registry)
          self.assertTrue(any(branches for _, branches in routes),
                          "%s routed to nothing, so this proves nothing" % name)
          expected = [[net["id"], _rounded(branches)]
                      for net, branches in routes]
          actual = [[net_id, _rounded(branches)]
                    for net_id, branches in browser["routes"]]
          self.assertEqual(
            actual, expected,
            "%s with forkLate: routing.js and routing.py disagree" % name)
        finally:
          os.unlink(path)

  def test_the_flag_actually_changes_what_is_drawn(self):
    """Otherwise the agreement above is between two idle code paths."""
    doc, registry = self.laid_out_with_forking("alu_slice.dlg")
    late = _rounded([b for _net, branches in routing.route_all(doc, registry)
                     for b in branches])
    doc.canvas.pop("forkLate", None)
    early = _rounded([b for _net, branches in routing.route_all(doc, registry)
                      for b in branches])
    self.assertNotEqual(early, late,
                        "forkLate changed nothing, so the parity above is "
                        "comparing two wires that fork early")
