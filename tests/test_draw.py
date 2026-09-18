"""Wire routing and SVG rendering."""

import os
import re
import unittest

from drawlogic import drc, geometry, render_svg, routing, theme
from drawlogic.doc import Document, loads_of, new_document
from drawlogic.symbols import default_registry
from tests import EXAMPLE, ROOT, open_example


def _flat(routes):
  """(net, points) for every branch, for tests that look at one wire at a time."""
  return [(net, points) for net, branches in routes for points in branches]


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
    [points] = routing.route(doc, doc.nets[0])
    self.assertEqual(len(points), 2)
    self.assertAlmostEqual(points[0][1], points[1][1])

  def test_offset_pins_route_with_two_corners(self):
    doc = _doc_with_pair()
    doc.cell("u2")["y"] = 120
    [points] = routing.route(doc, doc.nets[0])
    self.assertEqual(len(points), 4)
    self.assertAlmostEqual(points[0][1], points[1][1])
    self.assertAlmostEqual(points[1][0], points[2][0])
    self.assertAlmostEqual(points[2][1], points[3][1])

  def test_every_segment_is_axis_aligned(self):
    doc = Document.load(EXAMPLE)
    for net, points in _flat(routing.route_all(doc)):
      for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        self.assertTrue(abs(ax - bx) < 1e-6 or abs(ay - by) < 1e-6,
                        "net %s has a diagonal segment" % net.get("id"))

  def test_moving_a_gate_carries_its_wire(self):
    # This is the whole point of storing pin references instead of
    # coordinates, so it gets an explicit test.
    doc = _doc_with_pair()
    [before] = routing.route(doc, doc.nets[0])
    doc.cell("u1")["x"] += 40
    doc.cell("u1")["y"] += 25
    [after] = routing.route(doc, doc.nets[0])

    self.assertAlmostEqual(after[0][0], before[0][0] + 40)
    self.assertAlmostEqual(after[0][1], before[0][1] + 25)
    self.assertAlmostEqual(after[-1][0], before[-1][0])
    self.assertAlmostEqual(after[-1][1], before[-1][1])

  def test_backward_target_does_not_route_through_the_cell(self):
    doc = _doc_with_pair()
    doc.cell("u2")["x"] = -200
    doc.cell("u2")["y"] = 150
    [points] = routing.route(doc, doc.nets[0])
    start = points[0]
    # The wire must leave the driving pin heading east before turning back.
    self.assertGreater(points[1][0], start[0])

  def test_no_segment_crosses_an_unrelated_cell(self):
    # Every leg has to clear other cells, not just the corridor. A corridor
    # that dodges a gate is useless if the leg into it still cuts through one.
    doc = Document.load(EXAMPLE)
    doc.normalize()
    for net, branches in routing.route_all(doc):
      for load, points in zip(loads_of(net), branches):
        exclude = set()
        for endpoint in (net.get("from"), load):
          if isinstance(endpoint, dict) and "cell" in endpoint:
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
    [points] = routing.route(doc, doc.nets[0])
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


def build(cells, nets, width=600, height=420, title="draw"):
  doc = new_document(title, width, height)
  doc.cells.extend(cells)
  doc.nets.extend(nets)
  return doc


def port(cell_id, x, y, label=None, kind="port_in"):
  return {"id": cell_id, "type": kind, "x": x, "y": y,
          "label": label if label is not None else cell_id}


def wire(net_id, source, source_pin, target, target_pin, name=None):
  net = {"id": net_id, "from": {"cell": source, "pin": source_pin},
         "to": [{"cell": target, "pin": target_pin}]}
  if name:
    net["name"] = name
  return net


class TestJunctionsAreNeverHidden(unittest.TestCase):
  """A junction dot is the only mark saying two wires are connected.

  Losing one is not a cosmetic problem: the drawing stops claiming a
  connection that the file still has. Both ways of losing one were reported by
  a user as "the dot disappears when it is close to a cell, or close to an
  arrow".
  """

  def fanout(self, load_x=200, dy=40):
    """A driver fanning out to two loads, so the split lands near its body.

    The defaults are a case where an arrow would otherwise be drawn on the
    junction dot, which is what makes the arrow rule testable at all -- with
    the loads further away the two never collide and the rule does nothing.
    """
    doc = new_document("dot", 700, 420)
    doc.cells.extend([
      {"id": "a", "type": "port_in", "x": 40, "y": 200, "label": "a"},
      {"id": "U1", "type": "and2", "x": 120, "y": 180, "label": "U1"},
      {"id": "U2", "type": "buf", "x": load_x, "y": 200 - dy, "label": "U2"},
      {"id": "U3", "type": "buf", "x": load_x, "y": 200 + dy, "label": "U3"},
    ])
    doc.nets.extend([
      {"id": "n0", "from": {"cell": "a", "pin": "p"},
       "to": [{"cell": "U1", "pin": "a"}]},
      {"id": "n1", "name": "q", "from": {"cell": "U1", "pin": "y"},
       "to": [{"cell": "U2", "pin": "a"}, {"cell": "U3", "pin": "a"}]},
    ])
    return doc

  def test_dots_are_drawn_after_the_cells(self):
    """Cells used to be drawn after the nets, so a dot beside a gate was
    painted over by it."""
    svg = render_svg.render(self.fanout())
    self.assertIn('class="dl-junctions"', svg)
    self.assertLess(svg.index('class="dl-cells"'),
                    svg.index('class="dl-junctions"'),
                    "cells are drawn over the junction dots")

  def test_a_dot_survives_a_split_beside_a_body(self):
    doc = self.fanout()
    routes = routing.route_all(doc, default_registry())
    self.assertTrue(routing.junctions(routes), "expected a junction to test")
    svg = render_svg.render(doc)
    self.assertIn("<circle", svg.split('class="dl-junctions"')[1])

  def test_an_arrow_gives_way_to_a_dot(self):
    """Both are small solid marks in the same ink, so one on the other reads
    as a single fatter arrow and the connection is lost."""
    doc = self.fanout()
    routes = routing.route_all(doc, default_registry())
    dots = routing.junctions(routes)
    self.assertTrue(dots)

    for _net, branches in routes:
      for points in branches:
        if len(points) < 2:
          continue
        for tip, _way in render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                                 junctions=dots):
          for dot in dots:
            self.assertFalse(
              abs(tip[0] - dot[0]) < drc.ARROW_TO_JUNCTION
              and abs(tip[1] - dot[1]) < drc.ARROW_TO_JUNCTION,
              "an arrow at %r sits on the junction at %r" % (tip, dot))

  def test_an_arrow_gives_way_to_a_crossing_bridge_too(self):
    """A bridge is the same problem as a dot in the other direction: the arrow
    sits in the bulge, and the reader cannot see whether the wire hopped or
    stopped. Reported as arrows overlapping hops.
    """
    doc = build(
      [port("a", 40, 200), port("y", 620, 200, kind="port_out"),
       port("b", 300, 40), port("c", 300, 420, kind="port_out")],
      [wire("h", "a", "p", "y", "p", "h"),
       wire("v", "b", "p", "c", "p", "v")], width=700, height=500)

    routes = routing.route_all(doc, default_registry())
    hops = [spot for spots in routing.hop_points(routes).values()
            for spot in spots]
    self.assertTrue(hops, "expected a crossing bridge to test")
    marks = list(routing.junctions(routes)) + hops

    for _net, branches in routes:
      for points in branches:
        if len(points) < 2:
          continue
        for tip, _way in render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                                 junctions=marks):
          for hop in hops:
            self.assertFalse(
              abs(tip[0] - hop[0]) < drc.ARROW_TO_MARK
              and abs(tip[1] - hop[1]) < drc.ARROW_TO_MARK,
              "an arrow at %r sits on the bridge at %r" % (tip, hop))

  def test_no_drawn_arrow_sits_on_a_bridge_in_any_example(self):
    """The rule above is only worth anything if render() passes the bridges
    in -- which it did not at first, so every drawn arrow ignored them.

    Asked of the shipped drawings rather than a made-up one, because a
    collision needs a long wire crossing several others at the right spacing.
    soc_top had an arrow drawn exactly on a bridge, which is what was
    reported; a constructed two-wire case never gets near one.
    """
    import re
    for name in ("soc_top", "spi_master", "cdc_fifo", "alu_slice"):
      with self.subTest(example=name):
        doc, registry, _ = open_example(
          os.path.join(ROOT, "examples", name + ".dlg"))
        routes = routing.route_all(doc, registry)
        hops = [spot for spots in routing.hop_points(routes).values()
                for spot in spots]
        svg = render_svg.render(doc, registry)
        tips = [(float(m.group(1)), float(m.group(2)))
                for m in re.finditer(r'<polygon points="([-\d.]+),([-\d.]+)',
                                     svg)]
        self.assertTrue(tips, "no arrows were drawn at all")
        for tip in tips:
          for hop in hops:
            self.assertFalse(
              abs(tip[0] - hop[0]) < drc.ARROW_TO_MARK
              and abs(tip[1] - hop[1]) < drc.ARROW_TO_MARK,
              "%s: a drawn arrow at %r sits on the bridge at %r"
              % (name, tip, hop))

  def test_the_arrow_rule_actually_drops_something(self):
    """Otherwise the test above passes on a drawing where no arrow was ever
    near a dot, and would keep passing with the rule deleted."""
    doc = self.fanout()
    routes = routing.route_all(doc, default_registry())
    dots = routing.junctions(routes)

    def count(**kwargs):
      total = 0
      for _net, branches in routes:
        for points in branches:
          if len(points) >= 2:
            total += len(render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                                 **kwargs))
      return total

    kept = count(junctions=dots)
    self.assertLess(kept, count(), "the rule dropped no arrow here")
    self.assertGreater(kept, 0, "every arrow was dropped")


class TestPortStubs(unittest.TestCase):
  """A wire leaving an IO port runs straight before it may turn.

  A port is the edge of the sheet with no body between the connector and the
  first corner, so a wire that bends immediately reads as a vertical line
  stuck to the port rather than as a signal going somewhere.
  """

  def run_out_of_port(self, gate_x):
    doc = new_document("stub", 520, 340)
    doc.cells.extend([
      {"id": "a", "type": "port_in", "x": 40, "y": 100, "label": "a"},
      {"id": "U1", "type": "and2", "x": gate_x, "y": 200, "label": "U1"},
    ])
    doc.nets.append({"id": "n", "from": {"cell": "a", "pin": "p"},
                     "to": [{"cell": "U1", "pin": "a"}]})
    points = routing.route_all(doc, default_registry())[0][1][0]
    return abs(points[1][0] - points[0][0])

  def test_a_port_always_gets_its_straight_run(self):
    for gate_x in (85, 100, 130, 200, 320):
      with self.subTest(gate_x=gate_x):
        self.assertGreaterEqual(
          self.run_out_of_port(gate_x), drc.PORT_STUB - 1e-6,
          "the wire turned before clearing the port connector")

  def test_the_longer_stub_is_only_for_ports(self):
    """A gate has a body doing the same job as a port's straight run, and
    giving every pin a port's stub would push every corner outwards.

    Asked of the rule rather than of a route, because how far a wire actually
    runs before turning is mostly the corridor search's answer -- the stub is
    the floor under it, and the floor is what differs.
    """
    doc = new_document("stub", 600, 400)
    doc.cells.extend([
      {"id": "a", "type": "port_in", "x": 60, "y": 100, "label": "a"},
      {"id": "U1", "type": "and2", "x": 200, "y": 220, "label": "U1"},
    ])
    registry = default_registry()
    self.assertEqual(
      routing.stub_for(doc, {"cell": "a", "pin": "p"}, registry),
      drc.PORT_STUB)
    self.assertEqual(
      routing.stub_for(doc, {"cell": "U1", "pin": "a"}, registry),
      routing.STUB)
    self.assertLess(routing.STUB, drc.PORT_STUB)

  def test_a_free_endpoint_needs_no_stub(self):
    """A wire end dragged into empty space faces nowhere in particular."""
    doc = new_document("stub", 600, 400)
    self.assertEqual(routing.stub_for(doc, {"x": 10, "y": 10}), routing.STUB)
    self.assertEqual(routing.stub_for(doc, {"cell": "nope", "pin": "p"}),
                     routing.STUB)


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
    own = sum(len(render_svg._arrow_spots(points, theme.ARROW_SIZE))
              for points in routing.route(self.doc, self.doc.nets[0]))
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


class TestWrittenContentIsContentToo(unittest.TestCase):
  """A text annotation has to survive a cropped export.

  A text shape carries an anchor and no width or height, so measuring it the
  way a rectangle is measured gave a box of nothing at all. Cropping to the
  content then cut a long annotation down to whatever fell within a few units
  of where it began -- a single letter, in the drawing that found this. The
  drawing still had the text; the delivered file did not.
  """

  ANNOTATION = "A VERY LONG SIGNAL ANNOTATION"

  def _annotated(self, size=40):
    doc = new_document("annotated")
    doc.shapes.append({"id": "t", "kind": "text", "x": 100, "y": 100,
                       "text": self.ANNOTATION, "style": {"fontSize": size}})
    doc.normalize()
    return doc

  def test_the_bounds_cover_the_whole_string(self):
    box = self._annotated().content_bbox()
    self.assertGreater(
      box[2], len(self.ANNOTATION) * 10,
      "%d characters at size 40 cannot fit in %.0f units"
      % (len(self.ANNOTATION), box[2]))

  def test_a_longer_annotation_takes_more_room(self):
    """Otherwise any fixed guess would pass the test above."""
    short = self._annotated().content_bbox()
    doc = self._annotated()
    doc.shapes[0]["text"] = self.ANNOTATION * 3
    self.assertGreater(doc.content_bbox()[2], short[2])

  def test_a_bigger_font_takes_more_room(self):
    small = self._annotated(size=10).content_bbox()
    large = self._annotated(size=40).content_bbox()
    self.assertGreater(large[2], small[2])

  def test_a_cropped_export_still_contains_it(self):
    doc = self._annotated()
    svg = render_svg.render(doc, crop=True)
    view = [float(v) for v in
            re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    box = doc.content_bbox()
    self.assertLessEqual(view[0], box[0])
    self.assertGreaterEqual(
      view[0] + view[2], box[0] + box[2],
      "the crop is narrower than the writing it is supposed to contain")

  def test_an_empty_annotation_does_not_invent_a_box(self):
    """The other direction: text with nothing in it should not push the
    bounds out around a string that is not there."""
    doc = new_document("empty")
    doc.shapes.append({"id": "t", "kind": "text", "x": 100, "y": 100,
                       "text": "", "style": {"fontSize": 40}})
    doc.normalize()
    box = doc.content_bbox()
    self.assertTrue(box is None or box[2] == 0, box)


class TestContentBounds(unittest.TestCase):
  """A cropped export has to contain the wires, not just the cells.

  content_bbox used to read net["waypoints"] and an x/y off each endpoint --
  version 1's shape. Version 2 puts waypoints on each load and names a cell
  and pin instead of a coordinate, so every wire contributed nothing and a
  crop cut off whatever the wire did between its two ends.
  """

  def _detour(self):
    doc = new_document("detour")
    doc.data["canvas"].update(width=600, height=400)
    doc.cells.extend([{"id": "a", "type": "port_out", "x": 10, "y": 10},
                      {"id": "b", "type": "port_in", "x": 500, "y": 10}])
    doc.nets.append({
      "id": "n1", "name": "sig", "width": 1,
      "from": {"cell": "a", "pin": "p"},
      "to": [{"cell": "b", "pin": "p", "waypoints": [[500, 300], [10, 300]]}],
    })
    doc.normalize()
    return doc

  def test_bounds_reach_the_far_end_of_a_detouring_wire(self):
    doc = self._detour()
    box = doc.content_bbox()
    self.assertGreaterEqual(
      box[1] + box[3], 300,
      "the wire runs down to y=300; the bounds stop at %.0f" % (box[1] + box[3]))

  def test_a_cropped_render_keeps_the_whole_wire(self):
    doc = self._detour()
    svg = render_svg.render(doc, crop=True)
    view = [float(v) for v in
            re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    lowest = max(point[1]
                 for _net, start, end in routing.segments_of(
                   routing.route_all(doc))
                 for point in (start, end))
    self.assertLessEqual(
      lowest, view[1] + view[3],
      "crop viewBox ends at y=%.0f but the wire reaches y=%.0f"
      % (view[1] + view[3], lowest))


class TestLongNamesWrap(unittest.TestCase):
  """An instance name too long for its cell reaches across whatever is beside
  it, which in a dense drawing is a wire. Two lines is half the reach."""

  def test_a_short_name_stays_on_one_line(self):
    """Single line is the preference, not the fallback."""
    for name in ("U1", "and2", "clk", "a_b"):
      self.assertEqual(geometry.label_lines(name), [name])

  def test_a_long_name_splits_at_an_underscore(self):
    self.assertEqual(geometry.label_lines("in_part1_clock"),
                     ["in_part1_", "clock"])

  def test_it_picks_the_seam_that_makes_the_longer_line_shortest(self):
    """Of several underscores, the one nearest the middle wins -- which is
    exactly the one that minimises the longer of the two lines, since that
    length is max(split, rest)."""
    self.assertEqual(geometry.label_lines("aaaa_bbbb_cccc"),
                     ["aaaa_", "bbbb_cccc"])          # 9, against 10 the other way
    self.assertEqual(geometry.label_lines("a_bbbbbbbbbb_c"),
                     ["a_", "bbbbbbbbbb_c"])          # 12, against 13

  def test_no_split_makes_the_longer_line_longer_than_the_name_would_be(self):
    """The property the choice above is for, stated directly."""
    for name in ("in_part1_clock", "aaaa_bbbb_cccc", "out_branch_99",
                 "a_bbbbbbbbbb_c"):
      lines = geometry.label_lines(name)
      if len(lines) == 1:
        continue
      # The split goes after the underscore, so the lines are index+1 long
      # and the rest.
      best = min(max(index + 1, len(name) - index - 1)
                 for index, ch in enumerate(name)
                 if ch == "_" and index < len(name) - 1)
      self.assertEqual(max(len(line) for line in lines), best,
                       "%s split worse than it had to" % name)

  def test_a_long_name_with_no_underscore_is_left_alone(self):
    """Breaking mid-word trades a name that overhangs for one that cannot be
    read, which is the worse of the two."""
    self.assertEqual(geometry.label_lines("verylongnamehere"),
                     ["verylongnamehere"])

  def test_the_box_gets_narrower_and_taller(self):
    """The DRCs and the renderer share this box, so wrapping has to move it."""
    registry = default_registry()
    doc = new_document("wrap", 600, 300)
    doc.cells.append({"id": "u", "type": "and2", "x": 200, "y": 120,
                      "label": "in_part1_clock"})
    doc.normalize(registry)
    cell = doc.cells[0]
    symbol = registry.for_cell(cell)
    wrapped = render_svg.cell_label_box(symbol, cell, doc.symbol_scale)

    cell["label"] = "in_part1_clockxx".replace("_", "")   # same length, no seam
    flat = render_svg.cell_label_box(symbol, cell, doc.symbol_scale)

    self.assertLess(wrapped[2] - wrapped[0], flat[2] - flat[0],
                    "a wrapped name should be narrower")
    self.assertGreater(wrapped[3] - wrapped[1], flat[3] - flat[1],
                       "a wrapped name should be taller")

  def test_a_wire_keeps_clear_of_the_upper_line(self):
    """The room reserved above a cell has to grow with the name, or a wire
    routes straight through the line that was added."""
    doc = new_document("wrap", 600, 300)
    doc.cells.append({"id": "u", "type": "and2", "x": 200, "y": 120,
                      "label": "short"})
    doc.normalize()
    one = routing.obstacle_boxes(doc)[0]
    doc.cells[0]["label"] = "in_part1_clock"
    two = routing.obstacle_boxes(doc)[0]
    self.assertLess(two[1], one[1],
                    "a two-line name must reserve more room above the cell")



if __name__ == "__main__":
  unittest.main()
