"""Wire routing and SVG rendering."""

import re
import unittest

from drawlogic import render_svg, routing, theme
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry
from tests import EXAMPLE


def _doc_with_pair(gap=300):
  doc = new_document()
  doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
  doc.cells.append({"id": "u2", "type": "inv", "x": gap, "y": 0})
  doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                   "to": {"cell": "u2", "pin": "a"}})
  doc.normalize()
  return doc


def _viewbox(svg):
  match = re.search(r'viewBox="([^"]+)"', svg)
  return [float(v) for v in match.group(1).split()]


def _size(svg):
  width = float(re.search(r'\bwidth="([\d.]+)"', svg).group(1))
  height = float(re.search(r'\bheight="([\d.]+)"', svg).group(1))
  return width, height


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


class TestRender(unittest.TestCase):

  def setUp(self):
    self.doc = Document.load(EXAMPLE)

  def test_renders_well_formed_svg(self):
    svg = render_svg.render(self.doc)
    self.assertTrue(svg.startswith('<?xml version="1.0"'))
    self.assertIn("<svg ", svg)
    self.assertTrue(svg.rstrip().endswith("</svg>"))
    self.assertEqual(svg.count("<svg "), 1)

  def test_every_cell_and_net_reaches_the_output(self):
    svg = render_svg.render(self.doc)
    for cell in self.doc.cells:
      self.assertIn('data-id="%s"' % cell["id"], svg)
    for net in self.doc.nets:
      self.assertIn('data-id="%s"' % net["id"], svg)

  def test_zoom_scales_the_size_but_not_the_geometry(self):
    plain = render_svg.render(self.doc, zoom=1.0)
    doubled = render_svg.render(self.doc, zoom=2.0)

    self.assertEqual(_viewbox(plain), _viewbox(doubled))
    pw, ph = _size(plain)
    dw, dh = _size(doubled)
    self.assertAlmostEqual(dw, pw * 2, places=3)
    self.assertAlmostEqual(dh, ph * 2, places=3)

  def test_width_overrides_zoom_and_keeps_the_aspect_ratio(self):
    svg = render_svg.render(self.doc, zoom=5.0, width=800)
    width, height = _size(svg)
    view = _viewbox(svg)
    self.assertAlmostEqual(width, 800)
    # Output dimensions are written to two decimals, so compare at that.
    self.assertAlmostEqual(height, 800 * view[3] / view[2], places=1)

  def test_full_canvas_is_the_default_and_crop_trims_to_content(self):
    full = _viewbox(render_svg.render(self.doc))
    cropped = _viewbox(render_svg.render(self.doc, crop=True))
    self.assertEqual(full[2], self.doc.canvas["width"])
    self.assertEqual(full[3], self.doc.canvas["height"])
    self.assertLess(cropped[2], full[2])

  def test_grid_is_left_out_unless_asked_for(self):
    self.assertNotIn("dl-grid", render_svg.render(self.doc))
    self.assertIn("dl-grid", render_svg.render(self.doc, show_grid=True))

  def test_transparent_background_omits_the_paper(self):
    opaque = render_svg.render(self.doc)
    clear = render_svg.render(self.doc, background="none")
    self.assertIn('fill="#ffffff"', opaque)
    self.assertLess(clear.count('fill="#ffffff"'), opaque.count('fill="#ffffff"'))

  def test_title_is_drawn_and_can_be_suppressed(self):
    self.assertIn("dff_slice", render_svg.render(self.doc))
    without = render_svg.render(self.doc, title=False)
    self.assertEqual(without.count("dff_slice"), 1)  # only the <title> element

  def test_font_scale_grows_every_label(self):
    small = render_svg.render(self.doc)
    self.doc.canvas["font"]["scale"] = 2.0
    large = render_svg.render(self.doc)
    self.assertNotEqual(small, large)
    self.assertIn('font-size="22"', large)

  def test_bus_is_drawn_like_any_other_wire(self):
    svg = render_svg.render(self.doc)
    bus = re.search(r'data-id="n8"[^>]*stroke-width="([\d.]+)"', svg)
    single = re.search(r'data-id="n1"[^>]*stroke-width="([\d.]+)"', svg)
    self.assertEqual(float(bus.group(1)), float(single.group(1)))

  def test_symbol_scale_grows_cells_about_their_own_centre(self):
    before = self.doc.content_bbox()
    self.doc.canvas["symbolScale"] = 2.0
    after = self.doc.content_bbox()
    # Cells get bigger, so the drawing spreads, but stays centred where it was.
    self.assertGreater(after[2], before[2])
    self.assertAlmostEqual(before[0] + before[2] / 2.0,
                           after[0] + after[2] / 2.0, delta=12)


class TestDirectionArrows(unittest.TestCase):

  def setUp(self):
    self.doc = Document.load(EXAMPLE)

  def _arrows(self, svg):
    return svg.count("<polygon")

  def test_every_wire_gets_at_least_one_arrow_by_default(self):
    svg = render_svg.render(self.doc)
    self.assertGreaterEqual(self._arrows(svg), len(self.doc.nets))

  def test_a_short_wire_gets_exactly_one(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 140, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    doc.normalize()
    self.assertEqual(self._arrows(render_svg.render(doc)), 1)

  def test_a_long_wire_gets_more_so_direction_reads_along_it(self):
    # One arrow near the receiving end says nothing about a run that is
    # mostly somewhere else.
    doc = new_document(width=2000)
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 1600, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    doc.normalize()
    self.assertGreater(self._arrows(render_svg.render(doc)), 1)

  def test_arrows_can_be_switched_off_per_render(self):
    self.assertEqual(self._arrows(render_svg.render(self.doc, arrows=False)), 0)

  def test_arrows_can_be_switched_off_in_the_document(self):
    self.doc.canvas["arrows"] = False
    self.assertEqual(self._arrows(render_svg.render(self.doc)), 0)

  def test_a_single_net_can_opt_out(self):
    before = self._arrows(render_svg.render(self.doc))
    own = len(render_svg._arrow_spots(
      routing.route(self.doc, self.doc.nets[0]), theme.ARROW_SIZE))
    self.doc.nets[0]["style"] = {"arrow": False}
    after = self._arrows(render_svg.render(self.doc))
    self.assertEqual(after, before - own)

  def test_arrow_points_from_driver_to_load(self):
    # n5 runs left to right from FF1.q to the q port, so the arrow's tip must
    # sit to the right of its base.
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 300, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    doc.normalize()
    svg = render_svg.render(doc)
    points = re.search(r'<polygon points="([^"]+)"', svg).group(1)
    xs = [float(p.split(",")[0]) for p in points.split()]
    self.assertGreater(xs[0], xs[1])


class TestEscaping(unittest.TestCase):

  def test_markup_in_labels_cannot_break_the_file(self):
    doc = new_document('<script>alert("x")</script>')
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0,
                      "label": 'A & B <tag>'})
    doc.normalize()
    svg = render_svg.render(doc)
    self.assertNotIn("<script>", svg)
    self.assertIn("&amp;", svg)
    self.assertIn("&lt;tag&gt;", svg)


class TestStrokeWeight(unittest.TestCase):

  def test_enlarging_a_gate_keeps_its_line_weight(self):
    # An SVG transform would scale stroke width along with the shape, which
    # makes a big gate look bold. The renderer divides it back out.
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0,
                      "w": 240, "h": 160})
    doc.normalize()
    svg = render_svg.render(doc)
    width = float(re.search(r'<path [^>]*stroke-width="([\d.]+)"', svg).group(1))
    self.assertAlmostEqual(width * 4, 1.6, places=2)


class TestPinLabels(unittest.TestCase):
  """Naming a pin on one instance, without touching the symbol."""

  def cell(self, cell_type, **extra):
    doc = new_document()
    cell = {"id": "u1", "type": cell_type, "x": 100, "y": 100}
    cell.update(extra)
    doc.cells.append(cell)
    doc.normalize()
    return doc

  def test_a_name_replaces_the_symbols_own_label(self):
    doc = self.cell("dff", pins={"ck": "wclk"})
    svg = render_svg.render(doc)
    self.assertIn(">wclk<", svg)
    self.assertNotIn(">CK<", svg)
    # The other two are untouched.
    self.assertIn(">D<", svg)
    self.assertIn(">Q<", svg)

  def test_an_empty_name_hides_the_symbols_label(self):
    doc = self.cell("dff", pins={"ck": ""})
    svg = render_svg.render(doc)
    self.assertNotIn(">CK<", svg)

  def test_a_block_with_no_labels_of_its_own_gets_one(self):
    doc = self.cell("block", pins={"in1": "wptr"})
    svg = render_svg.render(doc)
    self.assertIn(">wptr<", svg)

  def test_the_label_lands_inside_the_body_on_the_pins_own_face(self):
    doc = self.cell("block", pins={"in1": "L", "out1": "R"})
    svg = render_svg.render(doc)
    left = re.search(r'<text x="([\d.]+)"[^>]*text-anchor="(\w+)"[^>]*>L<', svg)
    right = re.search(r'<text x="([\d.]+)"[^>]*text-anchor="(\w+)"[^>]*>R<', svg)
    self.assertIsNotNone(left)
    self.assertIsNotNone(right)
    # in1 sits on the west face at x=100, out1 on the east face at x=240.
    self.assertGreater(float(left.group(1)), 100)
    self.assertLess(float(right.group(1)), 240)
    self.assertEqual(left.group(2), "start")
    self.assertEqual(right.group(2), "end")

  def test_a_mirrored_cell_flips_the_anchor(self):
    doc = self.cell("block", pins={"in1": "L"}, mirror=True)
    svg = render_svg.render(doc)
    anchor = re.search(r'<text [^>]*text-anchor="(\w+)"[^>]*>L<', svg)
    self.assertEqual(anchor.group(1), "end")

  def test_naming_a_pin_that_does_not_exist_is_an_error(self):
    doc = self.cell("block", pins={"nope": "x"})
    errors = [i for i in doc.validate() if i.level == "error"]
    self.assertTrue(any("nope" in str(i) for i in errors))

  def test_every_labelled_symbol_ties_its_labels_to_real_pins(self):
    # The override only works because each pin_label draw op says which pin it
    # belongs to. A new symbol that forgets the link would silently ignore the
    # cell's name.
    registry = default_registry()
    for symbol_id in registry.ids():
      symbol = registry.require(symbol_id)
      names = {pin["name"] for pin in symbol.pins}
      for op in symbol.draw:
        if op.get("role") != "pin_label":
          continue
        with self.subTest(symbol=symbol_id, text=op.get("text")):
          self.assertIn(op.get("pin"), names,
                        "pin_label %r is not tied to a pin" % op.get("text"))


class TestSymbolPreview(unittest.TestCase):

  def test_previews_a_single_symbol(self):
    symbol = default_registry().require("mux2")
    svg = render_svg.render_symbol(symbol)
    self.assertIn("<svg ", svg)
    self.assertIn("2:1 multiplexer", svg)


if __name__ == "__main__":
  unittest.main()
