"""Wire routing and SVG rendering."""

import os
import re
import unittest

from drawlogic import drc, geometry, layout, render_svg, routing, theme
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry
from tests import EXAMPLE, ROOT, open_example


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


def _through_body(points, box):
  """Does the path run through the inside of `box` (a body, x0 y0 x1 y1)?
  Touching its edge -- where the pins are -- does not count."""
  x0, y0, x1, y1 = box
  for (ax, ay), (bx, by) in zip(points, points[1:]):
    lo_x, hi_x = sorted((ax, bx))
    lo_y, hi_y = sorted((ay, by))
    if (min(hi_x, x1) - max(lo_x, x0) > 0.5 and y0 < ay < y1
        and ay == by):
      return True
    if (min(hi_y, y1) - max(lo_y, y0) > 0.5 and x0 < ax < x1
        and ax == bx):
      return True
  return False


class TestFeedbackLoops(unittest.TestCase):
  """A gate's output wired back into the flip-flop that feeds it.

  The flip-flop's D and Q sit on one row and so do the gate's pins, so the
  two stub ends of the loop face away from each other on that row. The
  straight line between them was taken as the route: back through the gate,
  back through the flip-flop, and along the Q wire the other way -- a short
  the DRCs reported on every imported counter.
  """

  def loop(self):
    doc = new_document("loop", 700, 300)
    doc.cells.append({"id": "ff", "type": "dff", "x": 235, "y": 115})
    doc.cells.append({"id": "g", "type": "inv", "x": 425, "y": 110})
    doc.cells.append({"id": "k", "type": "port_in", "x": 105, "y": 150,
                      "label": "clk"})
    doc.nets.append({"id": "q", "from": {"cell": "ff", "pin": "q"},
                     "to": {"cell": "g", "pin": "a"}})
    doc.nets.append({"id": "back", "from": {"cell": "g", "pin": "y"},
                     "to": {"cell": "ff", "pin": "d"}})
    doc.nets.append({"id": "clk", "from": {"cell": "k", "pin": "p"},
                     "to": {"cell": "ff", "pin": "ck"}})
    doc.normalize()
    return doc

  def test_the_wire_back_goes_round_both_cells(self):
    doc = self.loop()
    registry = default_registry()
    routes = dict((net["id"], branches)
                  for net, branches in routing.route_all(doc, registry))
    [points] = routes["back"]
    bodies = dict(zip([c["id"] for c in doc.cells],
                      routing.body_boxes(doc, registry)))
    for cell_id in ("ff", "g"):
      self.assertFalse(_through_body(points, bodies[cell_id]),
                       "the loop runs through %s: %r" % (cell_id, points))

  def test_the_loop_passes_the_drcs(self):
    doc = self.loop()
    registry = default_registry()
    errors = [str(v) for v in drc.check(doc, registry) if v.level == "error"]
    self.assertEqual(errors, [])

  def test_a_line_touching_another_nets_wire_end_is_not_free(self):
    """Half a unit past the end of another net's stub is on it, as far as
    the DRCs are concerned; the router used to call it free."""
    sheet = routing.Sheet()
    sheet.reserve(frozenset([("ff", "rn")]), [(750.0, 380.0), (750.0, 392.0)],
                  "reset")
    view = sheet.for_net((), frozenset([("g", "y")]), "other")
    self.assertFalse(view.free(True, 392.5, 300.0, 800.0, False,
                               routing.TOUCHING))
    self.assertFalse(view.free(False, 750.5, 300.0, 400.0, False,
                               routing.TOUCHING))
    self.assertTrue(view.free(True, 400.0, 300.0, 800.0, False,
                              routing.TOUCHING))


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


class TestRender(unittest.TestCase):

  def setUp(self):
    self.doc = Document.load(EXAMPLE)

  def test_renders_well_formed_svg(self):
    svg = render_svg.render(self.doc)
    self.assertTrue(svg.startswith('<?xml version="1.0"'))
    self.assertIn("<svg ", svg)
    self.assertTrue(svg.rstrip().endswith("</svg>"))
    self.assertEqual(svg.count("<svg "), 1)

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


class TestTextInsideTheSheet(unittest.TestCase):
  """Nothing drawn may fall outside the canvas.

  An instance name is centred on its cell and drawn above it, so a name wider
  than the body reaches past it on three sides. content_bbox measured the
  bodies, the wires and the shapes but not the names, so auto layout sized a
  sheet that the names hung over the edge of -- and both the canvas and a
  cropped export then clipped them.
  """

  def drawing(self, label):
    doc = new_document("clip", 400, 200)
    doc.cells.append({"id": "u", "type": "and2", "x": 40, "y": 40,
                      "label": label})
    doc.normalize()
    return doc

  def label_box(self, doc):
    registry = default_registry()
    cell = doc.cells[0]
    return render_svg.cell_label_box(registry.for_cell(cell), cell,
                                     doc.symbol_scale, doc.font_scale)

  def test_a_name_wider_than_the_margin_still_fits_the_sheet(self):
    registry = default_registry()
    doc = self.drawing("an_extremely_long_instance_name_that_keeps_going")
    layout.arrange(doc, registry)
    box = self.label_box(doc)
    self.assertGreaterEqual(box[0], 0, "the name runs off the left edge")
    self.assertGreaterEqual(box[1], 0, "the name runs off the top edge")
    self.assertLessEqual(box[2], doc.canvas["width"],
                         "the name runs off the right edge")
    self.assertLessEqual(box[3], doc.canvas["height"],
                         "the name runs off the bottom edge")

  def test_the_name_sits_inside_the_margin_like_everything_else(self):
    """Not merely on the sheet: auto layout puts the leftmost thing it draws
    at the margin, and the name is one of the things it draws. Measuring the
    body alone left the name a few units from the edge while the cell it
    belongs to sat a full margin in."""
    registry = default_registry()
    doc = self.drawing("an_extremely_long_instance_name_that_keeps_going")
    layout.arrange(doc, registry)
    box = self.label_box(doc)
    self.assertGreaterEqual(
      round(box[0], 3), drc.SHEET_MARGIN,
      "the name sits %.0f from the edge, inside the %g margin"
      % (box[0], drc.SHEET_MARGIN))

  def test_the_sheet_grows_only_for_a_name_that_needs_it(self):
    """The negative control: a short name must not inflate the canvas."""
    registry = default_registry()
    small = self.drawing("u1")
    layout.arrange(small, registry)
    big = self.drawing("an_extremely_long_instance_name_that_keeps_going")
    layout.arrange(big, registry)
    self.assertGreater(big.canvas["width"], small.canvas["width"])

  def test_the_bounds_cover_the_name_as_well_as_the_body(self):
    """Stated on content_bbox directly, since the crop uses the same box."""
    registry = default_registry()
    doc = self.drawing("an_extremely_long_instance_name_that_keeps_going")
    box = doc.content_bbox(registry)
    written = self.label_box(doc)
    self.assertLessEqual(box[0], written[0])
    self.assertLessEqual(box[1], written[1])
    self.assertGreaterEqual(box[0] + box[2], written[2])
    self.assertGreaterEqual(box[1] + box[3], written[3])


if __name__ == "__main__":
  unittest.main()


class TestTheTitleKeepsOutOfTheDrawing(unittest.TestCase):
  """The sheet title sits in a band along the top, clear of everything.

  It used to sit along the bottom, where a drawing that reached far enough
  down put a port's name straight through it. Nothing caught that: the title
  is not a cell, so no DRC watches it, and content_bbox does not know it
  exists. A cropped export was the worst case, because cropping pulls the
  bottom edge up to whatever the drawing ends at.
  """

  def drawing(self):
    """Cells all the way down to the bottom edge, and named."""
    doc = new_document("a title", 400, 300)
    for index in range(3):
      doc.cells.append({"id": "u%d" % index, "type": "and2",
                        "x": 60, "y": 60 + index * 100,
                        "label": "gate_%d" % index})
    doc.normalize()
    return doc

  def title_baseline(self, svg):
    found = re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*'
                       r'font-size="16"[^>]*>a title</text>', svg)
    self.assertEqual(len(found), 1, "expected exactly one title in the SVG")
    return float(found[0][0]), float(found[0][1])

  def test_the_title_sits_above_everything_drawn(self):
    doc = self.drawing()
    registry = default_registry()
    box = doc.content_bbox(registry)
    svg = render_svg.render(doc, registry, crop=True, margin=16)
    _x, baseline = self.title_baseline(svg)
    self.assertLess(
      baseline, box[1],
      "the title's baseline (%.1f) is level with or below the top of the "
      "drawing (%.1f), so it is drawn over it" % (baseline, box[1]))

  def test_cropping_leaves_room_for_the_title(self):
    """Cropping tight to the drawing must not crop the title off instead."""
    doc = self.drawing()
    registry = default_registry()
    svg = render_svg.render(doc, registry, crop=True, margin=16)
    view = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
    self.assertIsNotNone(view, "no viewBox in the rendered SVG")
    top = float(view.group(2))
    _x, baseline = self.title_baseline(svg)
    self.assertGreater(baseline - theme.FONT_SIZES["title"], top,
                       "the title is drawn above the top of the viewBox")


class TestTheArrowGivesWayToText(unittest.TestCase):
  """A name outranks the arrowhead that would sit on it.

  An arrow is the most redundant mark on a schematic: which way a wire runs is
  usually plain from the pins at its ends. A name is the opposite -- it is the
  one thing a reader cannot work out by looking. So where the two want the
  same spot the arrow moves along the wire, and where the whole run is spoken
  for it is not drawn at all.
  """

  # Long enough that the name's box reaches the arrows spaced along the wire.
  # A shorter one sits between two of them and collides with neither, which
  # passes every assertion here with the rule taken out.
  NAME = "a_very_long_signal_name_that_runs_on"

  def drawing(self):
    """A long wire whose name lies across where the arrows want to go."""
    doc = new_document("arrows", 900, 300)
    doc.cells.append({"id": "a", "type": "port_in", "x": 40, "y": 140,
                      "label": "src"})
    doc.cells.append({"id": "b", "type": "port_out", "x": 800, "y": 140,
                      "label": "dst"})
    doc.nets.append({"id": "n1", "name": self.NAME, "label": self.NAME,
                     "width": 1,
                     "from": {"cell": "a", "pin": "p"},
                     "to": [{"cell": "b", "pin": "p", "waypoints": []}]})
    doc.normalize()
    return doc

  def test_the_fixture_really_does_put_an_arrow_on_the_name(self):
    """Without this the two tests below prove nothing at all."""
    doc = self.drawing()
    registry = default_registry()
    routes, marks, names = self.marks_and_names(doc, registry)
    half = theme.ARROW_SIZE / 2.0
    clashes = sum(
      1
      for _net, branches in routes for points in branches
      if len(points) >= 2
      for tip, _d in render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                             junctions=marks)
      for x0, y0, x1, y1 in names
      if x0 - half <= tip[0] <= x1 + half and y0 - half <= tip[1] <= y1 + half)
    self.assertGreater(clashes, 0,
                       "no arrow wanted the name's spot, so this fixture "
                       "cannot tell whether the rule does anything")

  def marks_and_names(self, doc, registry):
    routes = routing.route_all(doc, registry)
    marks = render_svg.arrow_marks(routing.junctions(routes),
                                   routing.hop_points(routes))
    names = render_svg.text_marks(doc, registry, routes, doc.symbol_scale,
                                  doc.font_scale)
    return routes, marks, names

  def test_no_arrow_is_drawn_on_a_name(self):
    doc = self.drawing()
    registry = default_registry()
    routes, marks, names = self.marks_and_names(doc, registry)
    self.assertTrue(names, "the fixture wrote no names, so it tests nothing")

    half = theme.ARROW_SIZE / 2.0
    for _net, branches in routes:
      for points in branches:
        if len(points) < 2:
          continue
        for tip, _direction in render_svg._arrow_spots(
            points, theme.ARROW_SIZE, junctions=marks, text=names):
          for x0, y0, x1, y1 in names:
            on_it = (x0 - half <= tip[0] <= x1 + half
                     and y0 - half <= tip[1] <= y1 + half)
            self.assertFalse(
              on_it, "an arrow at %s sits on the name in %s"
              % (tuple(round(v, 1) for v in tip),
                 tuple(round(v, 1) for v in (x0, y0, x1, y1))))

  def test_it_moves_the_arrow_rather_than_losing_it(self):
    """Dropping every blocked arrow would pass the test above and be worse."""
    doc = self.drawing()
    registry = default_registry()
    routes, marks, names = self.marks_and_names(doc, registry)

    def count(text):
      return sum(len(render_svg._arrow_spots(points, theme.ARROW_SIZE,
                                             junctions=marks, text=text))
                 for _net, branches in routes for points in branches
                 if len(points) >= 2)

    free = count(())
    guarded = count(names)
    self.assertGreater(free, 0, "the fixture draws no arrows at all")
    self.assertEqual(
      guarded, free,
      "the name cost %d arrow(s) on a wire with room to slide along"
      % (free - guarded))


class TestWireLabelsAndStyle(unittest.TestCase):
  """What a wire shows is chosen per wire: label, line pattern, arrows."""

  def setUp(self):
    self.registry = default_registry()

  def wire(self, **extra):
    doc = new_document("wire", 600, 300)
    doc.cells.append({"id": "a", "type": "port_in", "x": 40, "y": 140})
    doc.cells.append({"id": "b", "type": "port_out", "x": 500, "y": 140})
    net = {"id": "n1", "name": "sig_name", "width": 1,
           "from": {"cell": "a", "pin": "p"},
           "to": [{"cell": "b", "pin": "p", "waypoints": []}]}
    net.update(extra)
    doc.nets.append(net)
    doc.normalize()
    return doc

  def test_a_name_alone_is_not_drawn(self):
    svg = render_svg.render(self.wire(), registry=self.registry)
    self.assertNotIn(">sig_name<", svg)

  def test_a_label_is_drawn_instead_of_the_name(self):
    svg = render_svg.render(self.wire(label="data out"), registry=self.registry)
    self.assertIn(">data out<", svg)
    self.assertNotIn(">sig_name<", svg)

  def test_line_patterns(self):
    for dash in ("dashed", "dotted"):
      svg = render_svg.render(self.wire(style={"dash": dash}), registry=self.registry)
      self.assertIn('stroke-dasharray="%s"' % theme.WIRE_DASHES[dash]["dash"], svg)
    plain = render_svg.render(self.wire(), registry=self.registry)
    self.assertNotIn("stroke-dasharray", plain.split('<g class="dl-nets">')[1]
                     .split("</g>")[0])

  def test_an_inout_pin_gets_no_arrow_unless_asked(self):
    doc = new_document("pad", 600, 300)
    doc.cells.append({"id": "p", "type": "port_inout", "x": 40, "y": 140})
    doc.cells.append({"id": "io", "type": "iocell", "x": 300, "y": 105})
    doc.nets.append({"id": "n1", "from": {"cell": "p", "pin": "p"},
                     "to": [{"cell": "io", "pin": "pad"}]})
    doc.normalize()
    self.assertEqual(routing.arrow_mode(doc, doc.nets[0], self.registry), "none")
    plain = self.wire()
    self.assertEqual(routing.arrow_mode(plain, plain.nets[0], self.registry),
                     "forward")
    doc.nets[0]["style"] = {"arrow": "both"}
    self.assertEqual(routing.arrow_mode(doc, doc.nets[0], self.registry), "both")

  def test_the_old_off_switch_still_means_none(self):
    doc = self.wire(style={"arrow": False})
    self.assertEqual(routing.arrow_mode(doc, doc.nets[0], self.registry), "none")


class TestNamesClearOfTopPins(unittest.TestCase):
  """A cell with a pin on top keeps its name off that pin's wire."""

  def setUp(self):
    self.registry = default_registry()

  def drawing(self):
    doc = new_document("names", 900, 500)
    doc.cells.extend([
      {"id": "en", "type": "port_in", "x": 60, "y": 60, "label": "en"},
      {"id": "d", "type": "port_in", "x": 60, "y": 215, "label": "d"},
      {"id": "t1", "type": "tbuf", "x": 300, "y": 190, "label": "T1"},
      {"id": "io", "type": "iocell", "x": 560, "y": 160, "label": "IO1"},
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

  def name_faults(self, doc):
    return [v for v in drc.check(doc, self.registry)
            if v.rule.startswith("text-to") and ("T1" in v.where or "IO1" in v.where)]

  def test_the_names_move_beside_the_cell(self):
    doc = self.drawing()
    for cell_id in ("t1", "io"):
      cell = doc.cell(cell_id)
      _x, _y, anchor = render_svg.cell_label_place(
        self.registry.for_cell(cell), cell, doc.symbol_scale, doc.font_scale)
      self.assertNotEqual(anchor, "middle", cell_id)

  def test_no_name_lands_on_a_wire_or_a_body(self):
    self.assertEqual(self.name_faults(self.drawing()), [])

  def test_the_fixture_really_would_collide_above(self):
    """Without the move, the top pin's wire runs through the name -- else the
    test above proves nothing."""
    original = render_svg.cell_label_place

    def always_above(symbol, cell, symbol_scale=1.0, font_scale=1.0):
      x, y, anchor = original(symbol, cell, symbol_scale, font_scale)
      if anchor == "middle":
        return x, y, anchor
      box = render_svg._cell_bbox(symbol, cell, symbol_scale)
      return box[0] + box[2] / 2.0, box[1] - 5, "middle"

    render_svg.cell_label_place = always_above
    try:
      self.assertTrue(self.name_faults(self.drawing()))
    finally:
      render_svg.cell_label_place = original

  def test_a_cell_without_a_top_pin_keeps_its_name_above(self):
    doc = self.drawing()
    cell = doc.cell("q")
    self.assertEqual(render_svg.cell_label_place(
      self.registry.for_cell(cell), cell, doc.symbol_scale, doc.font_scale)[2], "middle")


class TestTextInsideCells(unittest.TestCase):
  """Lines written inside a cell, and a cell drawn as a stack of copies."""

  def setUp(self):
    self.registry = default_registry()

  def block(self, **extra):
    doc = new_document("blocks", 600, 400)
    cell = {"id": "b", "type": "block", "x": 100, "y": 100, "label": "u_cpu"}
    cell.update(extra)
    doc.cells.append(cell)
    doc.normalize()
    return doc

  def layout(self, doc):
    cell = doc.cells[0]
    return render_svg.cell_text_layout(self.registry.for_cell(cell), cell,
                                       doc.symbol_scale, doc.font_scale)

  def test_the_box_grows_to_hold_the_text(self):
    lines = ["CPU cluster", "a", "b", "c", "d", "e", "a much longer line here"]
    doc = self.block(text=lines)
    cell = doc.cells[0]
    symbol = self.registry.for_cell(cell)
    self.assertGreater(cell["h"], symbol.height)
    self.assertGreater(cell["w"], symbol.width)
    placed, clipped = self.layout(doc)
    self.assertFalse(clipped)
    self.assertEqual([text for _x, _y, text in placed], lines)

  def test_it_never_shrinks_a_box(self):
    doc = self.block(text=["x"], w=300, h=200)
    self.assertEqual((doc.cells[0]["w"], doc.cells[0]["h"]), (300, 200))

  def test_fitting_twice_changes_nothing(self):
    doc = self.block(text=["one", "two", "three", "four", "five", "six"])
    size = (doc.cells[0]["w"], doc.cells[0]["h"])
    doc.normalize()
    self.assertEqual((doc.cells[0]["w"], doc.cells[0]["h"]), size)

  def test_without_fitting_the_text_is_cut_short(self):
    doc = self.block(text=["short", "x" * 60] + ["l"] * 9, textFit=False)
    placed, clipped = self.layout(doc)
    self.assertTrue(clipped)
    self.assertTrue(placed[1][2].endswith("…"))
    self.assertTrue(placed[-1][2].endswith("…"))
    self.assertEqual(doc.cells[0]["h"], self.registry.for_cell(doc.cells[0]).height)

  def test_text_is_centred_across_and_down_the_box(self):
    doc = self.block(text=["one", "two"])
    cell = doc.cells[0]
    placed, _ = self.layout(doc)
    xs = {round(x, 3) for x, _y, _t in placed}
    self.assertEqual(xs, {round(100 + cell["w"] / 2.0, 3)})
    self.assertLess(placed[0][1], placed[1][1])
    # The block's middle -- half a line above the last baseline's descent
    # line, measured as the renderer measures a line -- is the box's.
    size = theme.FONT_SIZES["cell_text"]
    top = placed[0][1] - size * 0.8
    bottom = placed[-1][1] + size * 0.2
    self.assertAlmostEqual((top + bottom) / 2.0, 100 + cell["h"] / 2.0, places=3)
    svg = render_svg.render(doc, registry=self.registry)
    self.assertIn('class="dl-cell-text"', svg)
    self.assertRegex(svg, r'class="dl-cell-text" [^>]*text-anchor="middle"')

  def test_every_alignment_puts_the_text_where_it_says(self):
    size = theme.FONT_SIZES["cell_text"]
    pad = theme.CELL_TEXT["pad"]
    for across in ("left", "center", "right"):
      for down in ("top", "middle", "bottom"):
        with self.subTest(across=across, down=down):
          doc = self.block(text=["one"], textAlign=across, textVAlign=down)
          cell = doc.cells[0]
          [(x, y, _t)], _ = self.layout(doc)
          self.assertAlmostEqual(x, {"left": 100 + pad,
                                     "center": 100 + cell["w"] / 2.0,
                                     "right": 100 + cell["w"] - pad}[across])
          top = y - size * 0.8
          bottom = y + size * 0.2
          expect = {"top": top - (100 + pad),
                    "middle": (top + bottom) / 2.0 - (100 + cell["h"] / 2.0),
                    "bottom": bottom - (100 + cell["h"] - pad)}[down]
          self.assertAlmostEqual(expect, 0.0, places=3)
          svg = render_svg.render(doc, registry=self.registry)
          anchor = {"left": "start", "center": "middle", "right": "end"}[across]
          self.assertIn('text-anchor="%s"' % anchor,
                        re.search(r'<text class="dl-cell-text"[^>]*>', svg).group(0))

  def test_an_alignment_it_does_not_know_reads_as_the_default(self):
    odd = self.layout(self.block(text=["one"], textAlign="diagonal",
                                 textVAlign="sideways"))
    plain = self.layout(self.block(text=["one"]))
    self.assertEqual(odd, plain)

  def test_text_cut_short_still_starts_at_the_top(self):
    doc = self.block(text=["a"] * 12, textFit=False)
    placed, clipped = self.layout(doc)
    self.assertTrue(clipped)
    size = theme.FONT_SIZES["cell_text"]
    self.assertAlmostEqual(placed[0][1],
                           100 + theme.CELL_TEXT["pad"] + size * 0.8, places=3)

  def test_copies_draw_one_outline_behind_and_a_count(self):
    svg = render_svg.render(self.block(copies=4), registry=self.registry)
    self.assertEqual(svg.count('class="dl-stack"'), 1)
    self.assertIn("×4", svg)
    one = render_svg.render(self.block(copies=1), registry=self.registry)
    self.assertNotIn("dl-stack", one)

  def test_a_copy_is_the_symbols_own_body_not_its_bounding_box(self):
    """Reported: a stacked gate or flop showed a big rectangle behind it,
    reaching out to the ends of its pin stubs."""
    for type_id, shape in (("and2", "path"), ("dff", "rect"),
                           ("iocell", "rect")):
      with self.subTest(symbol=type_id):
        doc = new_document("one", 400, 300)
        doc.cells.append({"id": "c", "type": type_id, "x": 100, "y": 100,
                          "copies": 2})
        doc.normalize()
        svg = render_svg.render(doc, registry=self.registry)
        [inner] = re.findall(r'<g class="dl-stack" transform="[^"]+">(.*?)</g>',
                             svg, re.S)
        drawn = re.findall(r"<(\w+) ", inner)
        self.assertEqual(drawn, [shape], "the copy should be the body alone")

  def test_the_copy_sits_further_back_behind_a_bigger_cell(self):
    """Reported: a fixed 6 looked too deep behind a small gate. The offset is
    a share of the cell's smaller side, with a floor so a small cell's two
    outlines do not run together."""
    registry = self.registry

    def offset(type_id, **size):
      cell = dict({"id": "c", "type": type_id, "x": 0, "y": 0, "copies": 2},
                  **size)
      doc = new_document("one", 900, 600)
      doc.cells.append(cell)
      doc.normalize()
      return render_svg.stack_offset(registry.for_cell(doc.cells[0]),
                                     doc.cells[0])

    big = offset("block", w=400, h=300)
    self.assertAlmostEqual(big, theme.CELL_TEXT["stack"] * 300)
    self.assertLess(offset("block", w=200, h=120), big)
    self.assertEqual(offset("and2"), theme.CELL_TEXT["stackMin"])
    svg = render_svg.render(self.block(copies=2, w=400, h=300),
                            registry=registry)
    self.assertIn('translate(%s %s)' % (render_svg.fmt(big), render_svg.fmt(big)),
                  svg)

  def test_a_symbol_with_no_body_still_gets_a_rectangle(self):
    doc = new_document("tie", 400, 300)
    doc.cells.append({"id": "t", "type": "tie0", "x": 100, "y": 100,
                      "copies": 2})
    doc.normalize()
    svg = render_svg.render(doc, registry=self.registry)
    self.assertIn('<rect class="dl-stack"', svg)

  def test_a_cell_without_either_draws_as_before(self):
    plain = render_svg.render(self.block(), registry=self.registry)
    self.assertNotIn("dl-stack", plain)
    self.assertNotIn("dl-copies", plain)

  def test_any_cell_can_hold_text(self):
    doc = new_document("gate", 400, 300)
    doc.cells.append({"id": "g", "type": "and2", "x": 100, "y": 100,
                      "text": ["enable gate"]})
    doc.normalize()
    cell = doc.cells[0]
    placed, clipped = render_svg.cell_text_layout(
      self.registry.for_cell(cell), cell, 1, 1)
    self.assertEqual(placed[0][2], "enable gate")
    self.assertFalse(clipped)


CROWDED_PORT = os.path.join(ROOT, "tests", "fixtures", "crowded_port.dlg")


class TestNoWobbleBesideAPin(unittest.TestCase):
  """A wire crossing over to another row never stops a few units off a pin's.

  The fixture is alu_slice as auto-layout once left it: the cin port sat just
  inside the keep-out band of the AND gate beside it, so the crossover row
  could not be the port's own. The nearest clear one was 2.5 units away, and
  the leg between them read as a wobble -- a wire-jog warning and a visible
  kink at the port. Saved rather than laid out afresh, because layout now
  arranges alu_slice differently and the case would quietly stop arising.
  """

  def setUp(self):
    self.doc, self.registry, _ = open_example(CROWDED_PORT)

  def test_the_wire_steps_a_readable_distance_or_not_at_all(self):
    jogs = [str(v) for v in drc.check(self.doc, self.registry)
            if v.rule == "wire-jog"]
    self.assertEqual(jogs, [])

  def test_the_fixture_really_does_crowd_the_port(self):
    """Otherwise the test above passes on a drawing with nothing at stake:
    the port's own row has to be blocked, so the wire must leave it."""
    port = routing.endpoint_position(
      self.doc, {"cell": "p_cin", "pin": "p"}, self.registry)
    [first] = [branches[0] for net, branches
               in routing.route_all(self.doc, self.registry)
               if net["id"] == "n10"]
    self.assertEqual(tuple(first[0]), tuple(port))
    self.assertNotEqual(first[2][1], port[1],
                        "the cin wire runs along the port's own row now, so "
                        "no crossover row is being chosen")


class TestLineArrowheads(unittest.TestCase):
  """A drawn line can end in any of PowerPoint's arrowheads, at either end."""

  def line(self, **style):
    doc = new_document("arrow", 400, 300)
    doc.shapes.append({"id": "s1", "kind": "line",
                       "points": [[100, 150], [300, 150]], "style": style})
    doc.normalize()
    return doc

  def test_each_kind_draws_its_own_head(self):
    expected = {"triangle": "polygon", "open": "polyline",
                "stealth": "polygon", "diamond": "polygon", "oval": "ellipse"}
    self.assertEqual(sorted(expected), sorted(k for k in theme.LINE_HEADS
                                              if k != "none"))
    for kind, tag in expected.items():
      with self.subTest(head=kind):
        svg = render_svg.render(self.line(headEnd=kind))
        self.assertEqual(re.findall(r'<(\w+) class="dl-head"', svg), [tag])

  def test_none_and_no_style_draw_no_head(self):
    for doc in (self.line(), self.line(headEnd="none", headStart="none")):
      self.assertNotIn("dl-head", render_svg.render(doc))

  def test_a_double_arrow_has_one_at_each_end(self):
    svg = render_svg.render(self.line(headStart="triangle", headEnd="triangle"))
    self.assertEqual(svg.count('class="dl-head"'), 2)

  def test_a_solid_head_trims_the_line_and_an_open_one_does_not(self):
    doc = self.line(headEnd="triangle", headEndSize="l", strokeWidth=2)
    points, _ = render_svg.line_heads(doc.shapes[0])
    self.assertAlmostEqual(points[-1][0],
                           300 - theme.LINE_HEAD_SIZES["l"] * 2)
    points, _ = render_svg.line_heads(self.line(headEnd="open").shapes[0])
    self.assertEqual(points[-1], (300, 150))

  def test_a_bigger_size_or_a_heavier_line_makes_a_bigger_head(self):
    def length(**style):
      points, _ = render_svg.line_heads(self.line(headEnd="triangle",
                                                  **style).shapes[0])
      return 300 - points[-1][0]
    self.assertLess(length(headEndSize="s"), length(headEndSize="m"))
    self.assertLess(length(headEndSize="m"), length(headEndSize="l"))
    self.assertLess(length(strokeWidth=1), length(strokeWidth=3))

  def test_a_polygon_has_no_ends_to_put_a_head_on(self):
    doc = new_document("poly", 400, 300)
    doc.shapes.append({"id": "p", "kind": "polygon",
                       "points": [[50, 50], [150, 50], [100, 120]],
                       "style": {"headEnd": "triangle"}})
    doc.normalize()
    self.assertNotIn("dl-head", render_svg.render(doc))

  def test_a_cropped_export_keeps_the_whole_head(self):
    doc = self.line(headEnd="diamond", headEndSize="l", strokeWidth=3)
    box = doc.content_bbox(default_registry())
    self.assertGreater(box[0] + box[2], 300,
                       "a diamond centred on the end reaches past it")


class TestPinNamesStayInsideARotatedCell(unittest.TestCase):
  """Reported: a flop rotated from the properties panel had its pin names
  outside the box. The label's anchor was carried round with the cell, but
  the text still ran the way it did upright, off the edge."""

  def label_boxes(self, rotate, mirror=False):
    doc = new_document("turn", 400, 300)
    doc.cells.append({"id": "ff", "type": "dff", "x": 150, "y": 100,
                      "rotate": rotate, "mirror": mirror})
    doc.normalize()
    registry = default_registry()
    symbol = registry.for_cell(doc.cells[0])
    svg = render_svg.render(doc, registry=registry)
    size = theme.FONT_SIZES["pin_label"]
    found = re.findall(
      r'<text x="([^"]+)" y="([^"]+)" text-anchor="([^"]+)" [^>]*fill="%s">'
      r'([^<]*)<' % re.escape(theme.COLORS["pin_label"]), svg)
    boxes = []
    for x, y, anchor, text in found:
      width = len(text) * size * render_svg.LABEL_CHAR
      left = {"start": 0, "middle": width / 2, "end": width}[anchor]
      boxes.append((text, float(x) - left, float(y) - size * 0.75,
                    float(x) - left + width, float(y)))
    return boxes, render_svg._cell_bbox(symbol, doc.cells[0], 1.0)

  def test_every_name_is_inside_the_body_at_every_angle(self):
    for rotate in (0, 90, 180, 270):
      for mirror in (False, True):
        with self.subTest(rotate=rotate, mirror=mirror):
          boxes, (bx, by, bw, bh) = self.label_boxes(rotate, mirror)
          self.assertEqual(len(boxes), 3)
          # The body is the box less its pin stubs, which are 10 long.
          inner = (bx + 10 - 0.5, by - 0.5, bx + bw - 10 + 0.5, by + bh + 0.5) \
            if rotate in (0, 180) else \
            (bx - 0.5, by + 10 - 0.5, bx + bw + 0.5, by + bh - 10 + 0.5)
          for text, x0, y0, x1, y1 in boxes:
            self.assertTrue(inner[0] <= x0 and x1 <= inner[2]
                            and inner[1] <= y0 and y1 <= inner[3],
                            "%s at %s sits outside %s"
                            % (text, (round(x0), round(y0), round(x1), round(y1)),
                               tuple(round(v) for v in inner)))
