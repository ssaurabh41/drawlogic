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
from tests.test_hdl import FEEDBACK, feedback_drawing

NODE = shutil.which("node")
DUMP = os.path.join(ROOT, "tests", "js", "route_dump.mjs")
EXAMPLES = os.path.join(ROOT, "examples")


def _round(value, places=3):
  return round(float(value), places)


def _rounded(branches):
  return [[[_round(x), _round(y)] for x, y in points] for points in branches]


def _browser_result(path, registry):
  """Route and lay out a drawing in node, using what Python resolved for it.

  Handing node drawlogic/symbols.json instead would leave a referenced drawing
  with no symbol, so every net would route to nothing -- and match a Python
  side that had not resolved either. Two empty answers agree.
  """
  handles = []
  try:
    for payload in (registry.as_data(), theme.as_data(), drc.as_data()):
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
    for payload in (registry.as_data(), doc.ordered(), theme.as_data(),
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


def _arrow_modes_drawing():
  """One wire in every arrow mode, plus one left to decide for itself on an
  inout pin -- the cases no example has, so nothing else here reaches them.
  """
  doc = new_document("arrow modes", 900, 600)
  doc.canvas["grid"]["style"] = "blank"
  doc.cells.extend([
    {"id": "io", "type": "iocell", "x": 400, "y": 420},
    {"id": "pad", "type": "port_inout", "x": 60, "y": 455},
  ])
  for index, mode in enumerate(("forward", "backward", "both", "none")):
    y = 80 + index * 80
    doc.nets.append({"id": "m%d" % index, "style": {"arrow": mode},
                     "from": {"x": 60, "y": y},
                     "to": [{"x": 700, "y": y}, {"x": 500, "y": y + 40}]})
  doc.nets.append({"id": "pad_net", "from": {"cell": "pad", "pin": "p"},
                   "to": [{"cell": "io", "pin": "pad"}]})
  doc.normalize()
  return doc


@unittest.skipUnless(NODE, "node is not installed")
class TestArrowModesAgree(unittest.TestCase):
  """Every arrow mode draws the same heads in the editor and the file."""

  def setUp(self):
    self.registry = default_registry()

  def test_every_mode_draws_the_same_arrows_in_both(self):
    doc = _arrow_modes_drawing()
    browser = _browser_render(doc, self.registry)
    exported = _exported_arrows(render_svg.render(doc, registry=self.registry))
    self.assertEqual(browser["arrows"], exported)

  def test_the_modes_really_differ(self):
    """Otherwise the comparison above could pass with every mode ignored."""
    counts = []
    for mode in ("forward", "backward", "both", "none"):
      one = _arrow_modes_drawing()
      one.data["nets"] = [n for n in one.nets if n["id"] == "m0"]
      one.nets[0]["style"]["arrow"] = mode
      counts.append(len(_exported_arrows(
        render_svg.render(one, registry=self.registry))))
    forward, backward, both, none = counts
    self.assertGreater(forward, 0)
    self.assertGreater(backward, 0)
    self.assertGreater(both, max(forward, backward))
    self.assertEqual(none, 0)


def _top_pinned_drawing():
  """Cells with a pin on top, whose names move beside them, and wires that
  have to keep off those names -- one coming in to the top pin itself."""
  doc = new_document("names beside", 900, 500)
  doc.canvas["grid"]["style"] = "blank"
  doc.cells.extend([
    {"id": "en", "type": "port_in", "x": 60, "y": 60, "label": "en"},
    {"id": "d", "type": "port_in", "x": 60, "y": 215, "label": "d"},
    {"id": "t1", "type": "tbuf", "x": 300, "y": 190, "label": "T1"},
    {"id": "io", "type": "iocell", "x": 560, "y": 160, "label": "IO_PAD_7"},
    {"id": "q", "type": "port_out", "x": 820, "y": 215, "label": "q"},
  ])
  doc.nets.extend([
    {"id": "n1", "from": {"cell": "en", "pin": "p"},
     "to": [{"cell": "t1", "pin": "en"}, {"cell": "io", "pin": "oe"}]},
    {"id": "n2", "from": {"cell": "d", "pin": "p"}, "to": [{"cell": "t1", "pin": "a"}]},
    {"id": "n3", "from": {"cell": "t1", "pin": "y"}, "to": [{"cell": "io", "pin": "pad"}]},
    {"id": "n4", "from": {"cell": "io", "pin": "y"}, "to": [{"cell": "q", "pin": "p"}]},
  ])
  doc.normalize()
  return doc


def _exported_cell_names(svg):
  start = svg.index('<g class="dl-cells">')
  found = re.findall(
    r'<text x="([^"]+)" y="([^"]+)" text-anchor="([^"]+)"[^>]*font-weight="600"[^>]*>([^<]*)<',
    svg[start:])
  return sorted([text, x, y, anchor] for x, y, anchor, text in found)


def _exported_wires(svg):
  return sorted([i, d] for i, d in re.findall(
    r'<path class="dl-net" data-id="([^"]+)" d="([^"]+)"', svg))


@unittest.skipUnless(NODE, "node is not installed")
class TestNamesBesideCellsAgree(unittest.TestCase):
  """A name moved off a top pin goes to the same place in both renderers,
  and both route the same wires around it."""

  def setUp(self):
    self.registry = default_registry()

  def test_both_put_the_names_in_the_same_place(self):
    doc = _top_pinned_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    self.assertEqual(browser["cellNames"], _exported_cell_names(exported))
    anchors = {name: anchor for name, _x, _y, anchor in browser["cellNames"]}
    self.assertEqual(anchors["T1"], "end", "the fixture's name did not move")

  def test_both_route_the_same_wires_round_them(self):
    doc = _top_pinned_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    self.assertEqual(browser["wires"], _exported_wires(exported))


def _block_diagram_drawing():
  """Text inside cells -- fitted, cut short, rotated -- and replicated cells."""
  doc = new_document("blocks", 900, 500)
  doc.canvas["grid"]["style"] = "blank"
  doc.cells.extend([
    {"id": "cpu", "type": "block", "x": 80, "y": 80, "label": "u_cpu",
     "text": ["CPU cluster", "Cortex-A55", "4 cores, 1.8 GHz", "1 MB L2", "ACE"],
     "copies": 4},
    {"id": "ddr", "type": "block", "x": 380, "y": 80, "textFit": False,
     "text": ["DDR ctrl", "LPDDR4x, 2 ch x 16b wide", "a", "b", "c", "d"]},
    {"id": "dma", "type": "block6", "x": 600, "y": 260, "rotate": 90,
     "text": ["DMA", "8 channels"], "copies": 2},
    {"id": "g", "type": "and2", "x": 300, "y": 330, "text": ["en"]},
    # Replicated cells that are not plain blocks: each copies its own body,
    # and the tie cell, having none, falls back to a rectangle.
    {"id": "g2", "type": "and2", "x": 120, "y": 380, "copies": 2},
    {"id": "ff", "type": "dff", "x": 220, "y": 380, "copies": 3,
     "mirror": True},
    {"id": "io", "type": "iocell", "x": 420, "y": 300, "copies": 2},
    {"id": "t0", "type": "tie0", "x": 120, "y": 460, "copies": 2},
  ])
  doc.nets.append({"id": "n1", "from": {"cell": "cpu", "pin": "out1"},
                   "to": [{"cell": "ddr", "pin": "in1"}]})
  doc.normalize()
  return doc


def _exported_inside(svg):
  start = svg.index('<g class="dl-cells">')
  found = re.findall(r'<text x="([^"]+)" y="([^"]+)" font-family="[^"]+" '
                     r'font-size="[^"]+" fill="[^"]+">([^<]*)<', svg[start:])
  return sorted([text, x, y] for x, y, text in found)


def _exported_stacks(svg):
  return sorted([c, x, y, w, h] for c, x, y, w, h in re.findall(
    r'<rect class="(dl-stack|dl-copies)" x="([^"]+)" y="([^"]+)" '
    r'width="([^"]+)" height="([^"]+)"', svg))


def _exported_stack_bodies(svg):
  return sorted([transform, re.findall(r"<(\w+) ", inner)]
                for transform, inner in re.findall(
                  r'<g class="dl-stack" transform="([^"]+)">(.*?)</g>', svg,
                  re.S))


def _arrowhead_drawing():
  """Every head kind and size, at both ends, on lines going every way."""
  doc = new_document("heads", 700, 500)
  doc.canvas["grid"]["style"] = "blank"
  kinds = [k for k in theme.LINE_HEADS if k != "none"]
  for index, kind in enumerate(kinds):
    for turn, (dx, dy) in enumerate([(160, 0), (0, 120), (-90, 70)]):
      x, y = 60 + index * 110, 60 + turn * 140
      doc.shapes.append({
        "id": "s%d_%d" % (index, turn), "kind": "line",
        "points": [[x, y], [x + dx, y + dy]],
        "style": {"headEnd": kind, "headEndSize": "sml"[turn],
                  "headStart": kinds[(index + 1) % len(kinds)],
                  "strokeWidth": 1 + turn}})
  doc.shapes.append({"id": "pl", "kind": "polyline",
                     "points": [[40, 470], [200, 470], [200, 400]],
                     "style": {"headStart": "triangle", "headEnd": "open"}})
  doc.normalize()
  return doc


def _exported_heads(svg):
  heads = []
  for tag, attrs in re.findall(r'<(\w+) class="dl-head" ([^>]*)/>', svg):
    get = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs)).get
    heads.append([tag, get("points"), get("cx"), get("cy"), get("rx"),
                  get("ry"), get("transform")])
  return sorted(heads)


def _exported_shape_lines(svg):
  return sorted(re.findall(r'<polyline points="([^"]+)"', svg))


def _rotated_drawing():
  """Symbols with their own pin names, at every angle, mirrored and not."""
  doc = new_document("turned", 900, 500)
  doc.canvas["grid"]["style"] = "blank"
  for row, type_id in enumerate(("dff", "mux2", "iocell")):
    for col, (rotate, mirror) in enumerate([(0, False), (90, False),
                                            (180, False), (270, False),
                                            (90, True), (270, True)]):
      doc.cells.append({"id": "%s_%d" % (type_id, col), "type": type_id,
                        "x": 40 + col * 140, "y": 40 + row * 150,
                        "rotate": rotate, "mirror": mirror})
  doc.normalize()
  return doc


def _exported_pin_labels(svg):
  found = re.findall(
    r'<text x="([^"]+)" y="([^"]+)" text-anchor="([^"]+)" font-family="[^"]+" '
    r'font-size="[^"]+" fill="%s">([^<]*)<' % re.escape(theme.COLORS["pin_label"]),
    svg)
  return sorted([text, x, y, anchor] for x, y, anchor, text in found)


@unittest.skipUnless(NODE, "node is not installed")
class TestPinLabelsAgree(unittest.TestCase):
  """Pin names land in the same place in the editor and the file, at any angle."""

  def test_turned_and_flipped_cells_name_their_pins_alike(self):
    registry = default_registry()
    doc = _rotated_drawing()
    browser = _browser_render(doc, registry)
    exported = _exported_pin_labels(render_svg.render(doc, registry=registry))
    self.assertGreater(len(exported), 40, "the fixture names too few pins")
    self.assertEqual(browser["pinLabels"], exported)


class TestTheGridDefaultsAgree(unittest.TestCase):
  """A new drawing snaps to the pin grid, in the file and in the editor alike.

  The step a drag snaps to is the drawing's grid. On the pin grid, a cell
  dragged anywhere keeps every pin where a wire can meet it; on a coarser
  one only some positions do. doc.py's default is what a file without a grid
  of its own gets, and model.js holds two more -- a new drawing's, and the
  fallback for one with no size -- that have to say the same.
  """

  def test_the_file_default_is_the_pin_grid(self):
    from drawlogic import doc as doc_module
    self.assertEqual(doc_module.DEFAULT_CANVAS["grid"]["size"], drc.PIN_GRID)

  def test_the_editor_says_the_same(self):
    from drawlogic import doc as doc_module
    want = doc_module.DEFAULT_CANVAS["grid"]["size"]
    with open(os.path.join(ROOT, "drawlogic", "web", "js", "model.js")) as f:
      source = f.read()
    fallback = re.search(r"\(doc\.canvas\.grid \|\| \{\}\)\.size\) \|\| (\d+)",
                         source)
    fresh = re.search(r'grid: \{ style: "blank", size: (\d+) \}', source)
    self.assertIsNotNone(fallback, "gridStep's fallback is gone from model.js")
    self.assertIsNotNone(fresh, "a new drawing's grid is gone from model.js")
    self.assertEqual(float(fallback.group(1)), want)
    self.assertEqual(float(fresh.group(1)), want)


class TestThePanelOffersEveryHead(unittest.TestCase):
  """The properties panel lists the heads itself; a head added to the theme
  and forgotten there could be drawn but never chosen."""

  def test_the_list_matches_the_theme(self):
    with open(os.path.join(ROOT, "drawlogic", "web", "js", "panels.js")) as f:
      source = f.read()
    found = re.search(r"export const HEAD_KINDS = \[([^\]]*)\]", source)
    self.assertIsNotNone(found, "HEAD_KINDS is gone from panels.js")
    self.assertEqual(re.findall(r'"([^"]+)"', found.group(1)),
                     list(theme.LINE_HEADS))


@unittest.skipUnless(NODE, "node is not installed")
class TestArrowheadsAgree(unittest.TestCase):
  """Drawn lines with arrowheads look the same in the editor and the file."""

  def setUp(self):
    self.registry = default_registry()

  def test_the_same_heads_in_the_same_places(self):
    doc = _arrowhead_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    # Five kinds, three lines each, a head at both ends; and the polyline's two.
    self.assertEqual(len(browser["heads"]), 5 * 3 * 2 + 2)
    self.assertEqual(browser["heads"], _exported_heads(exported))

  def test_both_trim_the_line_to_meet_its_heads(self):
    doc = _arrowhead_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    self.assertEqual(len(browser["shapeLines"]), 5 * 3 + 1)
    self.assertEqual(browser["shapeLines"], _exported_shape_lines(exported))


@unittest.skipUnless(NODE, "node is not installed")
class TestCellTextAgrees(unittest.TestCase):
  """Text inside cells and replicated cells draw the same in both renderers."""

  def setUp(self):
    self.registry = default_registry()

  def test_the_same_lines_in_the_same_places(self):
    doc = _block_diagram_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    self.assertTrue(browser["inside"], "the fixture draws no text inside")
    self.assertEqual(browser["inside"], _exported_inside(exported))
    self.assertTrue(any(text.endswith("\u2026") for text, _x, _y in browser["inside"]),
                    "the fixture cuts nothing short, so clipping is untested")

  def test_the_same_stacks_and_badges(self):
    doc = _block_diagram_drawing()
    browser = _browser_render(doc, self.registry)
    exported = render_svg.render(doc, registry=self.registry)
    # The tie cell has no body to copy and falls back to a rectangle; each of
    # the six replicated cells has a badge.
    self.assertEqual(len(browser["stacks"]), 7)
    self.assertEqual(browser["stacks"], _exported_stacks(exported))
    # The two blocks, the gate, the flip-flop and the IO cell copy their own
    # bodies.
    self.assertEqual(len(browser["stackBodies"]), 5)
    self.assertEqual(browser["stackBodies"], _exported_stack_bodies(exported))

  def test_both_fit_the_box_the_same_way(self):
    """The editor grows a box as text is typed; doc.py does it on load. The
    two have to land on the same size or a saved file reopens different."""
    import json as _json
    doc = _block_diagram_drawing()
    for cell in doc.cells:
      cell["w"], cell["h"] = self.registry.for_cell(cell).width, \
        self.registry.for_cell(cell).height
    script = (
      "import * as g from './drawlogic/web/js/geometry.js';"
      "import { readFileSync } from 'node:fs';"
      "g.setLibrary(JSON.parse(readFileSync(process.argv[1], 'utf8')));"
      "const doc = JSON.parse(readFileSync(process.argv[2], 'utf8'));"
      "for (const c of doc.cells) g.fitCellText(g.forCell(c), c, 1, 1);"
      "console.log(JSON.stringify(doc.cells.map((c) => [c.id, c.w, c.h])));")
    handles = []
    try:
      for payload in (self.registry.as_data(), doc.ordered()):
        handle, name = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w") as out:
          _json.dump(payload, out)
        handles.append(name)
      browser = _json.loads(subprocess.check_output(
        [NODE, "--input-type=module", "-e", script] + handles, cwd=ROOT))
    finally:
      for name in handles:
        os.unlink(name)
    for cell in doc.cells:
      render_svg.fit_cell_text(self.registry.for_cell(cell), cell, 1, 1)
    self.assertEqual(browser, [[c["id"], c["w"], c["h"]] for c in doc.cells])


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

  def test_the_bridge_really_does_move_an_arrow(self):
    """Otherwise the test above passes on a drawing where nothing is at stake
    -- two renderers agreeing that there was nothing to move.

    It used to demand that an arrow be *dropped*. An arrow now slides along
    its wire first and is only given up when the whole run is spoken for, so
    the bridge usually costs a position rather than an arrow. Either way the
    marks have to come out somewhere other than where they would have with
    the bridges ignored, which is the thing worth proving.
    """
    doc = _crossing_drawing()
    routes = routing.route_all(doc, self.registry)
    hop_map = routing.hop_points(routes)
    self.assertTrue([s for spots in hop_map.values() for s in spots],
                    "the fixture has no bridge, so it tests nothing")
    kept = _exported_arrows(render_svg.render(doc, registry=self.registry))
    # The same drawing with nothing to bridge over, so nothing for an arrow
    # to keep clear of. Asked through render rather than of the placer, so
    # what is compared is what the file actually carries.
    without = _exported_arrows(
      render_svg.render(doc, registry=self.registry, hops=False))
    self.assertTrue(without, "the fixture draws no arrows at all")
    self.assertNotEqual(
      kept, without,
      "the bridges changed nothing about where the arrows went, so both "
      "renderers could ignore hops and still agree")

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

  def test_a_wire_past_a_wrapped_name_routes_the_same_in_both(self):
    """routing.js kept room above a cell for one line of its name, routing.py
    for as many as the name wraps to -- and no example has a name long enough
    to wrap, so the parity check above could not see it. This wire runs level
    with the second line of such a name."""
    doc = new_document("wrapped", 700, 400)
    doc.cells.append({"id": "g", "type": "and2", "x": 300, "y": 200,
                      "label": "a_very_long_instance_name_that_wraps"})
    doc.nets.append({"id": "n", "from": {"x": 50, "y": 165},
                     "to": [{"x": 650, "y": 165}]})
    doc.normalize()
    registry = default_registry()
    routes = routing.route_all(doc, registry)
    self.assertGreater(len(routes[0][1][0]), 2,
                       "the wire went straight, so the name is not in its way "
                       "and this proves nothing")
    with tempfile.TemporaryDirectory() as folder:
      path = os.path.join(folder, "wrapped.dlg")
      doc.save(path)
      browser = _browser_result(path, registry)
    self.assertEqual([[i, _rounded(b)] for i, b in browser["routes"]],
                     [["n", _rounded(routes[0][1])]])

  def test_feedback_loops_route_the_same_in_both(self):
    """No example loops a register back on itself, so none takes the ways
    round a loop -- two bends, three bends, off the row entirely -- that
    imported RTL relies on. These do."""
    registry = default_registry()
    for name in sorted(FEEDBACK):
      with self.subTest(design=name):
        doc = feedback_drawing(name)
        routes = routing.route_all(doc, registry)
        with tempfile.TemporaryDirectory() as folder:
          path = os.path.join(folder, "loop.dlg")
          doc.save(path)
          browser = _browser_result(path, registry)
        self.assertEqual(
          [[i, _rounded(b)] for i, b in browser["routes"]],
          [[net["id"], _rounded(b)] for net, b in routes])

  def test_a_crossover_kept_clear_of_a_pin_row_routes_the_same_in_both(self):
    """No example crosses over a couple of units off a pin's row; the fixture
    does, so it is what holds both routers to stepping a readable distance
    away."""
    path = os.path.join(ROOT, "tests", "fixtures", "crowded_port.dlg")
    doc, registry, _ = open_example(path)
    browser = _browser_result(path, registry)
    self.assertEqual(
      [[i, _rounded(b)] for i, b in browser["routes"]],
      [[net["id"], _rounded(b)] for net, b in routing.route_all(doc, registry)])

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
