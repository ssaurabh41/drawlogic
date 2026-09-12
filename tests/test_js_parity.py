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
import shutil
import subprocess
import tempfile
import unittest

from drawlogic import render_svg, routing, theme

from tests import ROOT, open_example

NODE = shutil.which("node")
DUMP = os.path.join(ROOT, "tests", "js", "route_dump.mjs")
EXAMPLES = os.path.join(ROOT, "examples")


def _round(value, places=3):
  return round(float(value), places)


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
    for payload in (registry.as_data(), _theme_payload()):
      handle, name = tempfile.mkstemp(suffix=".json")
      with os.fdopen(handle, "w") as out:
        json.dump(payload, out)
      handles.append(name)
    return json.loads(subprocess.check_output(
      [NODE, DUMP, handles[0], path, handles[1]], cwd=ROOT))
  finally:
    for name in handles:
      os.unlink(name)


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
        self.assertTrue(any(points for _, points in routes),
                        "%s routed to nothing, so this proves nothing" % name)

        expected = [[net["id"], [[_round(x), _round(y)] for x, y in points]]
                    for net, points in routes]
        actual = [[net_id, [[_round(x), _round(y)] for x, y in points]]
                  for net_id, points in browser["routes"]]
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
           for net_id, (spot, anchor) in expected.items()},
          "%s: net names land in different places" % name)

  def test_every_example_puts_its_arrows_in_the_same_place(self):
    for name, path in self.examples():
      with self.subTest(example=name):
        doc, registry, _ = open_example(path)
        browser = _browser_result(path, registry)
        routes = routing.route_all(doc, registry)

        expected = {
          net["id"]: [[_round(tip[0]), _round(tip[1])]
                      for tip, _ in render_svg._arrow_spots(
                        points, theme.ARROW_SIZE)]
          for net, points in routes if len(points) >= 2}
        actual = {net_id: [[_round(tip[0]), _round(tip[1])]
                           for tip, _ in spots]
                  for net_id, spots in browser["arrows"] if spots}
        self.assertEqual(actual, expected,
                         "%s: direction arrows land in different places" % name)


if __name__ == "__main__":
  unittest.main()
