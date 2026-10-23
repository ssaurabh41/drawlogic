"""Containers: titled boundaries that own part of a drawing.

What matters is that ownership is the `parentId` field and nothing else: it
survives a save, the checker catches every way it can be wrong, and the box is
drawn beneath what it holds, the same in the editor as in an exported file.

Usage:

    python3 -m unittest tests.test_containers
"""

import re
import unittest

from drawlogic import containers, layout, render_svg
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry

from tests import EXAMPLE
from tests.test_js_parity import NODE, _browser_render


def nested():
  """A GPC holding a TPC holding two gates, a note, and a wire leaving it."""
  doc = new_document("nested", 900, 600)
  doc.data["containers"] = [
    {"id": "gpc", "title": "GPC 0", "x": 40, "y": 60, "w": 460, "h": 360},
    {"id": "tpc", "parentId": "gpc", "title": "TPC 0", "x": 60, "y": 110,
     "w": 260, "h": 140, "style": {"headerFill": "#76b900", "titleFill": "#ffffff"}},
  ]
  doc.cells.extend([
    {"id": "a", "parentId": "tpc", "type": "and2", "x": 80, "y": 170},
    {"id": "b", "parentId": "tpc", "type": "inv", "x": 200, "y": 175},
    {"id": "out", "type": "port_out", "x": 700, "y": 185},
  ])
  doc.shapes.append({"id": "note", "parentId": "gpc", "kind": "text",
                     "x": 60, "y": 400, "text": "two SMs"})
  doc.nets.extend([
    {"id": "n1", "from": {"cell": "a", "pin": "y"}, "to": [{"cell": "b", "pin": "a"}]},
    {"id": "n2", "from": {"cell": "b", "pin": "y"}, "to": [{"cell": "out", "pin": "p"}]},
  ])
  doc.normalize()
  return doc


def faults(doc):
  return [str(issue) for issue in doc.validate()
          if issue.level == "error"]


class TestTheFile(unittest.TestCase):

  def test_containment_survives_a_save(self):
    doc = nested()
    again = Document.loads(doc.dumps())
    self.assertEqual(again.cell("a")["parentId"], "tpc")
    self.assertEqual(again.shapes[0]["parentId"], "gpc")
    self.assertEqual([(b["id"], b.get("parentId")) for b in again.containers],
                     [("gpc", None), ("tpc", "gpc")])
    self.assertEqual(again.containers[1]["style"]["headerFill"], "#76b900")
    # And saving it again changes nothing: the file is canonical.
    self.assertEqual(again.dumps(), doc.dumps())

  def test_a_drawing_without_containers_saves_as_it_always_did(self):
    with open(EXAMPLE) as handle:
      text = handle.read()
    doc = Document.loads(text)
    doc.containers  # asking for them must not add an empty list to the file
    self.assertNotIn('"containers"', doc.dumps())
    self.assertEqual(doc.dumps(), text)

  def test_a_new_container_is_given_its_padding_and_header(self):
    doc = nested()
    self.assertEqual(doc.containers[0]["padding"], 20)
    self.assertEqual(doc.containers[0]["headerHeight"], 32)


class TestChecking(unittest.TestCase):

  def test_a_sound_nesting_has_no_faults(self):
    self.assertEqual(faults(nested()), [])

  def test_a_missing_parent(self):
    doc = nested()
    doc.cell("a")["parentId"] = "gone"
    self.assertEqual(faults(doc),
                     ["error: cell a: parent container 'gone' does not exist"])

  def test_a_parent_that_is_not_a_container(self):
    doc = nested()
    doc.cell("a")["parentId"] = "b"
    self.assertEqual(faults(doc), ["error: cell a: parent 'b' is a cell, not a container"])

  def test_a_loop(self):
    doc = nested()
    doc.containers[0]["parentId"] = "tpc"
    found = faults(doc)
    self.assertEqual(len(found), 1, found)
    self.assertIn("loop", found[0])
    # And it can still be drawn, so it can still be fixed.
    self.assertEqual(len(containers.paint_order(doc)), 2)

  def test_more_than_one_parent(self):
    doc = nested()
    doc.cell("a")["parentId"] = ["tpc", "gpc"]
    self.assertEqual(len(faults(doc)), 1)
    self.assertIn("must name one container", faults(doc)[0])

  def test_an_id_used_by_two_kinds_of_thing(self):
    doc = nested()
    doc.containers[1]["id"] = "a"
    found = faults(doc)
    self.assertIn("error: container a: id is also used by a cell", found)


class TestGeometry(unittest.TestCase):

  def test_descendants_go_all_the_way_down(self):
    self.assertEqual(containers.descendants(nested(), {"gpc"}),
                     {"gpc", "tpc", "a", "b", "note"})

  def test_fit_holds_the_contents_with_padding_and_header(self):
    doc = nested()
    registry = default_registry()
    box = doc.containers[1]
    self.assertTrue(containers.fit(doc, registry, box))
    inner = containers.contents_box(doc, registry, box)
    self.assertEqual(box["x"], inner[0] - 20)
    self.assertEqual(box["y"], inner[1] - 20 - 32)
    self.assertEqual(box["x"] + box["w"], inner[0] + inner[2] + 20)
    self.assertEqual(box["y"] + box["h"], inner[1] + inner[3] + 20)
    self.assertFalse(containers.fit(doc, registry, {"id": "empty", "x": 0, "y": 0,
                                                    "w": 10, "h": 10}))

  def test_a_cropped_export_takes_the_container_in(self):
    doc = nested()
    box = doc.content_bbox()
    self.assertLessEqual(box[0], 40)
    self.assertLessEqual(box[1], 60)


class TestDrawing(unittest.TestCase):

  def test_beneath_everything_outer_first(self):
    svg = render_svg.render(nested())
    self.assertLess(svg.index('class="dl-containers"'), svg.index('class="dl-shapes"'))
    self.assertLess(svg.index('data-id="gpc"'), svg.index('data-id="tpc"'))
    self.assertIn('fill="#76b900"', svg)

  def test_nothing_is_written_for_a_drawing_without_any(self):
    self.assertNotIn("dl-container", render_svg.render(Document.load(EXAMPLE)))

  def test_a_title_is_escaped(self):
    doc = nested()
    doc.containers[0]["title"] = "<GPC> & \"0\""
    svg = render_svg.render(doc)
    self.assertIn("&lt;GPC&gt; &amp; &quot;0&quot;", svg)
    self.assertNotIn("<GPC>", svg)

  def test_a_long_title_is_cut_short_in_a_narrow_box(self):
    doc = nested()
    doc.containers[1]["title"] = "Texture processing cluster number zero"
    doc.containers[1]["w"] = 120
    titles = re.findall(r'class="dl-container-title"[^>]*>([^<]*)<', render_svg.render(doc))
    self.assertEqual(titles[0], "GPC 0")
    self.assertTrue(titles[1].endswith("\u2026"), titles[1])
    self.assertLess(len(titles[1]), 20)


def gpcs(columns=2):
  """A GPU holding four GPCs in a row, each a grid of four SMs, placed badly
  on purpose, with wires from a host into each GPC and out to an L2."""
  doc = new_document("four GPCs", 1200, 800)
  doc.data["containers"] = [{"id": "gpu", "title": "GPU", "x": 40, "y": 60,
                             "w": 300, "h": 200, "layout": {"mode": "row"}}]
  spots = [(700, 300), (90, 500), (400, 80), (900, 600)]
  for g, (gx, gy) in enumerate(spots):
    doc.data["containers"].append({
      "id": "g%d" % g, "parentId": "gpu", "title": "GPC %d" % g, "x": gx, "y": gy,
      "w": 100, "h": 100, "layout": {"mode": "grid", "columns": columns}})
    for s in range(4):
      doc.cells.append({"id": "g%d_sm%d" % (g, s), "parentId": "g%d" % g,
                        "type": "block", "x": gx + 37 * (3 - s), "y": gy + 23 * s})
  doc.cells.append({"id": "host", "type": "block6", "x": 600, "y": 700})
  doc.cells.append({"id": "l2", "type": "block8", "x": 100, "y": 100})
  for g in range(4):
    doc.nets.append({"id": "in%d" % g, "from": {"cell": "host", "pin": "out%d" % (1 + g % 3)},
                     "to": [{"cell": "g%d_sm0" % g, "pin": "in1"}]})
    doc.nets.append({"id": "out%d" % g, "from": {"cell": "g%d_sm3" % g, "pin": "out1"},
                     "to": [{"cell": "l2", "pin": "in%d" % (1 + g)}]})
  doc.normalize()
  return doc


def box_of(doc, item_id):
  for kind, items in (("cell", doc.cells), ("container", doc.containers)):
    for item in items:
      if item["id"] == item_id:
        return containers.item_box(doc, default_registry(), kind, item)
  return None


class TestLayingOut(unittest.TestCase):

  def setUp(self):
    self.doc = gpcs()
    self.result = layout.arrange(self.doc, default_registry())

  def test_four_gpcs_in_a_row(self):
    boxes = [box_of(self.doc, "g%d" % g) for g in range(4)]
    # One row, in the order they read across before: GPC 1, 2, 0, 3.
    tops = set(round(b[1], 3) for b in boxes)
    self.assertEqual(len(tops), 1, boxes)
    lefts = sorted((b[0], name) for b, name in zip(boxes, ["g0", "g1", "g2", "g3"]))
    self.assertEqual([name for _x, name in lefts], ["g1", "g2", "g0", "g3"])
    for (a, _), (b, _) in zip(lefts, lefts[1:]):
      self.assertGreaterEqual(b - a, boxes[0][2])

  def test_each_gpc_is_a_two_column_grid(self):
    for g in range(4):
      sms = [box_of(self.doc, "g%d_sm%d" % (g, s)) for s in range(4)]
      self.assertEqual(len(set(round(b[0], 3) for b in sms)), 2)
      self.assertEqual(len(set(round(b[1], 3) for b in sms)), 2)
      outer = box_of(self.doc, "g%d" % g)
      for sm in sms:
        self.assertGreaterEqual(sm[0], outer[0])
        self.assertGreaterEqual(sm[1], outer[1] + containers.header(self.doc.containers[1 + g]))
        self.assertLessEqual(sm[0] + sm[2], outer[0] + outer[2])
        self.assertLessEqual(sm[1] + sm[3], outer[1] + outer[3])

  def test_every_container_holds_its_contents(self):
    registry = default_registry()
    for box in self.doc.containers:
      inner = containers.contents_box(self.doc, registry, box)
      self.assertGreaterEqual(inner[0], box["x"])
      self.assertGreaterEqual(inner[1], box["y"] + containers.header(box))
      self.assertLessEqual(inner[0] + inner[2], box["x"] + box["w"])
      self.assertLessEqual(inner[1] + inner[3], box["y"] + box["h"])

  def test_wires_still_name_the_real_pins(self):
    self.assertEqual(self.doc.nets[0]["to"][0], {"cell": "g0_sm0", "pin": "in1",
                                                 "waypoints": []})
    names = set(c["id"] for c in self.doc.cells)
    for net in self.doc.nets:
      for end in [net["from"]] + net["to"]:
        self.assertIn(end["cell"], names)
    self.assertFalse(any(str(c.get("type", "")).startswith("__container__")
                         for c in self.doc.cells))
    self.assertEqual(faults(self.doc), [])

  def test_a_second_layout_changes_nothing(self):
    first = self.doc.dumps()
    layout.arrange(self.doc, default_registry())
    self.assertEqual(self.doc.dumps(), first)

  def test_the_result_says_what_was_done(self):
    self.assertEqual(str(self.result), "18 cells in 5 containers")


class TestLayingOutWithNotes(unittest.TestCase):
  """A container's notes keep their place and the container keeps its own."""

  def noted(self, mode):
    doc = new_document("n", 1200, 800)
    doc.data["containers"] = [{"id": "k", "title": "K", "x": 100, "y": 100, "w": 400,
                               "h": 300, "layout": {"mode": mode}}]
    doc.cells.extend([{"id": "a", "parentId": "k", "type": "block", "x": 200, "y": 200},
                      {"id": "b", "parentId": "k", "type": "block", "x": 350, "y": 200}])
    # Above and left of both blocks.
    doc.shapes.append({"id": "t", "parentId": "k", "kind": "text", "x": 150, "y": 140,
                       "text": "a note about these"})
    doc.normalize()
    return doc

  def test_laying_out_a_container_again_and_again_leaves_it_where_it_is(self):
    for mode in ("row", "column", "grid", "flow"):
      doc = self.noted(mode)
      layout.arrange(doc, default_registry(), container="k")
      box = doc.containers[0]
      self.assertEqual((box["x"], box["y"]), (100, 100), mode)
      once = doc.dumps()
      layout.arrange(doc, default_registry(), container="k")
      self.assertEqual(doc.dumps(), once, mode)

  def test_the_note_stays_inside_and_above_the_blocks(self):
    from drawlogic import render_svg
    doc = self.noted("row")
    layout.arrange(doc, default_registry(), container="k")
    box = doc.containers[0]
    x0, y0, x1, y1 = render_svg.note_box(doc, doc.shapes[0])
    self.assertGreaterEqual(x0, box["x"])
    self.assertGreaterEqual(y0, box["y"] + containers.header(box))
    self.assertLessEqual(x1, box["x"] + box["w"])
    self.assertLess(y1, min(box_of(doc, c)[1] for c in ("a", "b")))


class TestNotesBesideAPin(unittest.TestCase):
  """A pinned cell at the top left and a note: laying out again moves
  nothing, and the note keeps its place."""

  def pinned(self, mode, nested=False):
    doc = new_document("pins and notes")
    doc.data["containers"] = [{"id": "k", "title": "K", "x": 100, "y": 100, "w": 600,
                               "h": 500, "layout": {"mode": mode}}]
    holder = "k"
    if nested:
      # The pin is inside a box of its own, which therefore stays put too.
      doc.data["containers"].append({"id": "kk", "parentId": "k", "title": "Inner",
                                     "x": 110, "y": 140, "w": 120, "h": 110})
      holder = "kk"
    doc.cells.extend([
      {"id": "a", "type": "inv", "x": 130, "y": 190 if nested else 152,
       "parentId": holder, "pinned": True},
      {"id": "b", "type": "inv", "x": 400, "y": 300, "parentId": "k"}])
    doc.shapes.append({"id": "note", "kind": "text", "x": 140, "y": 330,
                       "text": "annotation", "parentId": "k"})
    doc.normalize()
    return doc

  def test_laying_out_again_changes_nothing(self):
    for mode in ("row", "column", "grid", "flow"):
      for nested in (False, True):
        doc = self.pinned(mode, nested)
        pin = dict((c["id"], (c["x"], c["y"])) for c in doc.cells)["a"]
        layout.arrange(doc, default_registry(), container="k")
        once = doc.dumps()
        for _ in range(3):
          layout.arrange(doc, default_registry(), container="k")
          self.assertEqual(doc.dumps(), once, (mode, nested))
        self.assertEqual(dict((c["id"], (c["x"], c["y"])) for c in doc.cells)["a"], pin,
                         (mode, nested))

  def test_the_note_does_not_walk_down_the_box(self):
    for mode in ("row", "column", "grid"):
      doc = self.pinned(mode)
      # The pin is the top of the contents before and after, so however the
      # rest is packed, nothing moves the note up or down.
      for _ in range(4):
        layout.arrange(doc, default_registry(), container="k")
        self.assertEqual(doc.shapes[0]["y"], 330, mode)


class TestTopToBottomWithAPin(unittest.TestCase):
  """Flow top to bottom keeps its direction when something is pinned."""

  def staged(self, *pins):
    """Three stages a -> b -> c; each of `pins` is a name, or (name, x, y)
    to pin it somewhere else first."""
    doc = new_document("tb", 1200, 900)
    doc.data["containers"] = [{"id": "k", "title": "K", "x": 100, "y": 100, "w": 400,
                               "h": 300, "layout": {"mode": "flow", "direction": "tb"}}]
    for i, name in enumerate("abc"):
      doc.cells.append({"id": name, "parentId": "k", "type": "block",
                        "x": 200 + 160 * i, "y": 200})
    doc.nets.append({"id": "n1", "from": {"cell": "a", "pin": "out1"},
                     "to": [{"cell": "b", "pin": "in1"}]})
    doc.nets.append({"id": "n2", "from": {"cell": "b", "pin": "out1"},
                     "to": [{"cell": "c", "pin": "in1"}]})
    for pin in pins:
      name = pin if isinstance(pin, str) else pin[0]
      cell = next(c for c in doc.cells if c["id"] == name)
      cell["pinned"] = True
      if not isinstance(pin, str):
        cell["x"], cell["y"] = pin[1], pin[2]
    doc.normalize()
    layout.arrange(doc, default_registry(), container="k")
    return doc

  def test_the_stages_still_run_down_the_page_round_the_pin(self):
    for pinned in "abc":
      doc = self.staged(pinned)
      boxes = [box_of(doc, name) for name in "abc"]
      self.assertEqual(len(set(round(b[0], 3) for b in boxes)), 1, (pinned, boxes))
      self.assertTrue(boxes[0][1] < boxes[1][1] < boxes[2][1], (pinned, boxes))
      cell = next(c for c in doc.cells if c["id"] == pinned)
      self.assertEqual((cell["x"], cell["y"]), (200 + 160 * "abc".index(pinned), 200))

  def test_a_row_that_would_land_on_a_second_pin_moves_down_past_it(self):
    # Where b goes with a alone pinned...
    b = box_of(self.staged("a"), "b")
    # ...is where c is pinned too: b cannot go there, and goes below.
    doc = self.staged("a", ("c", b[0], b[1]))
    pinned = box_of(doc, "c")
    self.assertEqual((pinned[0], pinned[1]), (b[0], b[1]))
    moved = box_of(doc, "b")
    self.assertGreaterEqual(moved[1], pinned[1] + pinned[3], (moved, pinned))
    self.assertEqual(round(moved[0], 3), round(pinned[0], 3))

  def test_laying_it_out_twice_changes_nothing(self):
    doc = self.staged("b")
    once = doc.dumps()
    layout.arrange(doc, default_registry(), container="k")
    self.assertEqual(doc.dumps(), once)


class TestLayingOutAroundPins(unittest.TestCase):

  def test_a_pinned_cell_and_its_containers_stay(self):
    doc = gpcs()
    layout.arrange(doc, default_registry())
    doc.cell("g2_sm1")["pinned"] = True
    doc.cell("g2_sm1")["x"] += 40
    held = box_of(doc, "g2_sm1")
    gpc = box_of(doc, "g2")
    note = layout.arrange(doc, default_registry())
    self.assertEqual(box_of(doc, "g2_sm1"), held)
    self.assertEqual(box_of(doc, "g2")[:2], gpc[:2])
    self.assertIn("GPC 2, GPU stayed put", str(note))
    # Nothing packed on top of the pinned SM.
    for s in (0, 2, 3):
      other = box_of(doc, "g2_sm%d" % s)
      self.assertFalse(other[0] < held[0] + held[2] and held[0] < other[0] + other[2]
                       and other[1] < held[1] + held[3] and held[1] < other[1] + other[3])


class TestLayingOutOneContainer(unittest.TestCase):

  def test_nothing_outside_it_moves(self):
    doc = nested()
    doc.cell("b")["x"] += 77
    outside = (dict(doc.cell("out")), dict(doc.containers[0]))
    corner = (doc.containers[1]["x"], doc.containers[1]["y"])
    layout.arrange(doc, default_registry(), container="tpc")
    self.assertEqual((doc.cell("out"), doc.containers[0]), outside)
    self.assertEqual((doc.containers[1]["x"], doc.containers[1]["y"]), corner)
    # And the note held by the GPC, outside the TPC, stayed too.
    self.assertEqual(doc.shapes[0]["y"], 400)

  def test_top_to_bottom_puts_what_drives_above_what_it_drives(self):
    doc = nested()
    doc.containers[1]["layout"] = {"direction": "tb"}
    layout.arrange(doc, default_registry(), container="tpc")
    a, b = box_of(doc, "a"), box_of(doc, "b")
    self.assertLess(a[1] + a[3], b[1])

  def test_notes_in_a_container_travel_with_its_contents(self):
    doc = nested()
    registry = default_registry()
    # Moved well away from where the layout will put the GPC's contents, so
    # a note left behind would show.
    containers.move(doc, {"tpc"}, 300, 200)

    def offset():
      corner = containers.contents_box(doc, registry, doc.containers[0])
      return (doc.shapes[0]["x"] - corner[0], doc.shapes[0]["y"] - corner[1])

    before = offset()
    layout.arrange(doc, registry)
    self.assertNotEqual(containers.contents_box(doc, registry, doc.containers[0])[:2],
                        (360, 310))
    self.assertEqual(tuple(round(v, 6) for v in offset()),
                     tuple(round(v, 6) for v in before))

  def test_an_unknown_layout_is_a_warning(self):
    doc = nested()
    doc.containers[0]["layout"] = {"mode": "spiral"}
    warned = [str(i) for i in doc.validate() if "spiral" in i.message]
    self.assertEqual(len(warned), 1, warned)


def across_a_title():
  """A wire whose straight path runs along a container's header band, right
  through the words of its title."""
  doc = new_document("across", 1000, 400)
  doc.data["containers"] = [{"id": "mem", "title": "Memory subsystem",
                             "x": 300, "y": 100, "w": 400, "h": 200}]
  doc.cells.extend([
    {"id": "d", "type": "inv", "x": 100, "y": 101},
    {"id": "l", "type": "inv", "x": 800, "y": 101},
  ])
  doc.nets.append({"id": "n", "from": {"cell": "d", "pin": "y"},
                   "to": [{"cell": "l", "pin": "a"}]})
  doc.normalize()
  return doc


def through_band(points, band):
  """The runs of a path that touch a box: none, for a wire that keeps off."""
  hits = []
  for a, b in zip(points, points[1:]):
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    if not (x1 < band[0] or x0 > band[2] or y1 < band[1] or y0 > band[3]):
      hits.append((a, b))
  return hits


class TestWiresKeepOffTitles(unittest.TestCase):

  def test_a_wire_keeps_a_clearance_off_the_whole_header_band(self):
    from drawlogic import routing
    doc = across_a_title()
    band = containers.header_box(doc.containers[0], routing.CLEARANCE - 0.5)
    [(_net, [points])] = routing.route_all(doc)
    self.assertEqual(through_band(points, band), [])
    # And it is not that the wire happened to miss: straight, it would not.
    start = points[0]
    self.assertTrue(band[1] <= start[1] <= band[3])

  @unittest.skipUnless(NODE, "node is not installed")
  def test_the_editor_routes_it_the_same_way(self):
    import os
    import tempfile
    from drawlogic import routing
    from tests.test_js_parity import _browser_result, _rounded
    doc = across_a_title()
    handle, path = tempfile.mkstemp(suffix=".dlg")
    os.close(handle)
    try:
      doc.save(path)
      browser = _browser_result(path, default_registry())
    finally:
      os.unlink(path)
      if os.path.exists(path + ".bak"):
        os.unlink(path + ".bak")
    expected = [[net["id"], _rounded(branches)]
                for net, branches in routing.route_all(doc)]
    self.assertEqual([[i, _rounded(b)] for i, b in browser["routes"]], expected)


def into_from_above():
  """A driver above a container, wired to a block inside it whose pin faces
  left. No corner or crossover reaches the pin without cutting through the
  header band, so only a path round the side gets there."""
  doc = new_document("into", 1000, 700)
  doc.data["containers"] = [{"id": "sa", "title": "System agent",
                             "x": 300, "y": 300, "w": 500, "h": 200}]
  doc.cells.extend([
    {"id": "src", "type": "block", "x": 450, "y": 120},
    {"id": "a", "parentId": "sa", "type": "block", "x": 340, "y": 370},
    {"id": "b", "parentId": "sa", "type": "block", "x": 560, "y": 370},
  ])
  doc.nets.append({"id": "n", "from": {"cell": "src", "pin": "out1"},
                   "to": [{"cell": "b", "pin": "in1"}]})
  doc.normalize()
  return doc


class TestAPathRoundTheHeader(unittest.TestCase):

  def test_a_wire_into_a_container_from_above_goes_round_the_header(self):
    from drawlogic import drc, routing
    doc = into_from_above()
    band = containers.header_box(doc.containers[0], routing.CLEARANCE - 0.5)
    [(_net, [points])] = routing.route_all(doc)
    self.assertEqual(through_band(points, band), [])
    # In through a side of the box, below the band.
    box = doc.containers[0]
    sides = [(a, b) for a, b in zip(points, points[1:]) if abs(a[1] - b[1]) < 1e-6
             and min(a[0], b[0]) < box["x"] + box["w"] < max(a[0], b[0])]
    self.assertTrue(sides, points)
    self.assertEqual([v for v in drc.check(doc) if v.level == "error"], [])

  def test_without_the_path_finder_it_would_cut_the_band(self):
    from drawlogic import routing
    doc = into_from_above()
    band = containers.header_box(doc.containers[0])
    saved = routing._find_path
    routing._find_path = lambda *args: None
    try:
      [(_net, [points])] = routing.route_all(doc)
    finally:
      routing._find_path = saved
    self.assertNotEqual(through_band(points, band), [])

  def test_a_block_taller_than_the_reach_is_still_gone_round(self):
    from drawlogic import drc, routing
    doc = new_document("tall", 1400, 1400)
    doc.cells.extend([
      {"id": "src", "type": "block", "x": 100, "y": 650},
      {"id": "wall", "type": "block", "x": 600, "y": 50, "w": 120, "h": 1300},
      {"id": "dst", "type": "block", "x": 1100, "y": 650},
    ])
    doc.nets.append({"id": "n", "from": {"cell": "src", "pin": "out1"},
                     "to": [{"cell": "dst", "pin": "in1"}]})
    doc.normalize()
    [(_net, [points])] = routing.route_all(doc)
    # Over the top: the wall reaches 625 above the wire, past MAZE_REACH.
    self.assertLess(min(p[1] for p in points), 50)
    self.assertEqual([v.rule for v in drc.check(doc) if v.level == "error"], [])

  def test_a_boxed_in_end_finds_no_path(self):
    from drawlogic import routing
    sheet = routing.Sheet(boxes=[(0, 0, 100, 100)])
    self.assertIsNone(routing._find_path((50, 50), (300, 50), (1, 0), (-1, 0), sheet))

  @unittest.skipUnless(NODE, "node is not installed")
  def test_the_editor_finds_the_same_path(self):
    import os
    import tempfile
    from drawlogic import routing
    from tests.test_js_parity import _browser_result, _rounded
    doc = into_from_above()
    handle, path = tempfile.mkstemp(suffix=".dlg")
    os.close(handle)
    try:
      doc.save(path)
      browser = _browser_result(path, default_registry())
    finally:
      os.unlink(path)
      if os.path.exists(path + ".bak"):
        os.unlink(path + ".bak")
    expected = [[net["id"], _rounded(branches)]
                for net, branches in routing.route_all(doc)]
    self.assertEqual([[i, _rounded(b)] for i, b in browser["routes"]], expected)


def runs_along_outlines(doc, routes):
  """Every run lying closer than a cell's clearance to a container outline,
  alongside it -- the wire that reads as part of the box."""
  from drawlogic import routing
  found = []
  for net, branches in routes:
    for points in branches:
      for a, b in zip(points, points[1:]):
        for box in doc.containers:
          x, y, w, h = box["x"], box["y"], box["w"], box["h"]
          if abs(a[1] - b[1]) < 1e-6:
            lines = [(y, x, x + w), (y + h, x, x + w)]
            fixed, lo, hi = a[1], min(a[0], b[0]), max(a[0], b[0])
          else:
            lines = [(x, y, y + h), (x + w, y, y + h)]
            fixed, lo, hi = a[0], min(a[1], b[1]), max(a[1], b[1])
          for line, line_lo, line_hi in lines:
            if (abs(line - fixed) < routing.CLEARANCE
                and lo < line_hi and hi > line_lo):
              found.append((net["id"], a, b, box["id"]))
  return found


class TestWiresKeepOffOutlines(unittest.TestCase):

  def test_an_outline_is_crossed_but_not_followed(self):
    from drawlogic import routing
    sheet = routing.Sheet()
    sheet.add_borders([{"x": 0, "y": 0, "w": 100, "h": 100}])
    # Alongside the left edge, inside or out: not free, on any pass.
    for x in (-5, 0, 5):
      for gap in (routing.WIRE_GAP, routing.TOUCHING):
        self.assertFalse(sheet.free(False, x, 20, 80, False, gap), (x, gap))
    self.assertTrue(sheet.free(False, 15, 20, 80))
    # Straight across it is how a wire gets in, so it stays free.
    self.assertTrue(sheet.free(True, 50, -40, 40))
    # Past the end of the edge is not alongside it.
    self.assertTrue(sheet.free(False, 0, 120, 160))

  def test_four_cores_in_a_grid_wire_out_through_the_gaps(self):
    from drawlogic import routing
    from tests import ROOT, open_example
    import os
    doc, registry, _issues = open_example(os.path.join(ROOT, "examples", "cpu_arch.dlg"))
    self.assertEqual(layout_of_cores(doc), "grid")
    self.assertEqual(runs_along_outlines(doc, routing.route_all(doc, registry)), [])


def layout_of_cores(doc):
  return layout.layout_of(containers.by_id(doc)["cores"])[0]


class TestPackingLeavesRoomForWires(unittest.TestCase):

  def gaps(self, mode):
    """The gaps a packed container leaves between four blocks, each with a
    wire out to a ring beside it."""
    doc = new_document("packed", 1200, 800)
    doc.data["containers"] = [{"id": "c", "title": "Cores", "x": 0, "y": 0,
                               "w": 100, "h": 100, "layout": {"mode": mode}}]
    for i in range(4):
      doc.cells.append({"id": "b%d" % i, "parentId": "c", "type": "block",
                        "x": 200 * i, "y": 0})
    doc.cells.append({"id": "ring", "type": "block8", "x": 1000, "y": 0})
    for i in range(4):
      doc.nets.append({"id": "n%d" % i, "from": {"cell": "b%d" % i, "pin": "out1"},
                       "to": [{"cell": "ring", "pin": "in%d" % (i + 1)}]})
    doc.normalize()
    layout.arrange(doc, default_registry())
    boxes = sorted(box_of(doc, "b%d" % i) for i in range(4))
    if mode == "row":
      return [b[0] - (a[0] + a[2]) for a, b in zip(boxes, boxes[1:])]
    return [b[1] - (a[1] + a[3]) for a, b in zip(boxes, boxes[1:])]

  def test_a_row_widens_for_the_wires_leaving_it(self):
    from drawlogic import drc
    # Four wires: a wire gap each after the first, a cell's clearance either
    # side.
    want = 2 * drc.WIRE_TO_CELL + 3 * drc.WIRE_GAP
    for gap in self.gaps("row"):
      self.assertAlmostEqual(gap, want)

  def test_a_column_keeps_the_plain_gap(self):
    from drawlogic import drc
    for gap in self.gaps("column"):
      self.assertAlmostEqual(gap, drc.CONTAINER_GAP)

  def test_blocks_with_no_wires_keep_the_plain_gap(self):
    from drawlogic import drc
    doc = gpcs()
    doc.nets[:] = []
    layout.arrange(doc, default_registry())
    sms = sorted(box_of(doc, "g0_sm%d" % s) for s in range(4))
    self.assertAlmostEqual(sms[2][0] - (sms[0][0] + sms[0][2]), drc.CONTAINER_GAP)


def wired_column():
  """Rename above a reorder buffer above schedulers, in a column, rename
  wired to both: two wires that have to loop round the side."""
  doc = new_document("column", 1200, 800)
  doc.data["containers"] = [{"id": "oe", "title": "OoO engine", "x": 0, "y": 0,
                             "w": 100, "h": 100, "layout": {"mode": "column"}}]
  for i, name in enumerate(("ren", "rob", "sch")):
    doc.cells.append({"id": name, "parentId": "oe", "type": "block",
                      "x": 100, "y": 150 * i})
  doc.nets.append({"id": "alloc", "from": {"cell": "ren", "pin": "out1"},
                   "to": [{"cell": "rob", "pin": "in1"}]})
  doc.nets.append({"id": "disp", "from": {"cell": "ren", "pin": "out2"},
                   "to": [{"cell": "sch", "pin": "in1"}]})
  doc.normalize()
  layout.arrange(doc, default_registry())
  return doc


class TestColumnLoopsGetLanes(unittest.TestCase):

  def test_the_column_stays_one_column(self):
    doc = wired_column()
    lefts = set(round(box_of(doc, c)[0], 3) for c in ("ren", "rob", "sch"))
    self.assertEqual(len(lefts), 1)

  def test_each_side_has_room_for_its_loops(self):
    from drawlogic import drc
    doc = wired_column()
    box = doc.containers[0]
    pad = containers.padding(box)
    blocks = [box_of(doc, c) for c in ("ren", "rob", "sch")]
    left = min(b[0] for b in blocks) - box["x"]
    right = box["x"] + box["w"] - max(b[0] + b[2] for b in blocks)
    # Two wires leave on the right, two loads come in on the left.
    want = 2 * drc.WIRE_TO_CELL + drc.WIRE_GAP
    self.assertGreater(want, pad)
    self.assertAlmostEqual(left, want)
    self.assertAlmostEqual(right, want)

  def test_the_two_loops_run_in_lanes_of_their_own(self):
    from drawlogic import drc, routing
    doc = wired_column()
    routes = dict((net["id"], branches) for net, branches in routing.route_all(doc))
    right = max(b[0] + b[2] for b in (box_of(doc, c) for c in ("ren", "rob", "sch")))

    def side_columns(net_id):
      return set(a[0] for points in routes[net_id] for a, b in zip(points, points[1:])
                 if abs(a[0] - b[0]) < 1e-6 and a[0] > right)

    alloc, disp = side_columns("alloc"), side_columns("disp")
    self.assertTrue(alloc and disp)
    for x in alloc:
      for y in disp:
        self.assertGreaterEqual(abs(x - y), drc.WIRE_GAP)
    self.assertEqual(runs_along_outlines(doc, routing.route_all(doc)), [])

  def test_a_second_layout_changes_nothing(self):
    doc = wired_column()
    first = doc.dumps()
    layout.arrange(doc, default_registry())
    self.assertEqual(doc.dumps(), first)

  def test_two_loops_into_one_block_widen_the_gap_above_it(self):
    from drawlogic import drc
    doc = wired_column()
    doc.nets.append({"id": "wb", "from": {"cell": "rob", "pin": "out1"},
                     "to": [{"cell": "sch", "pin": "in2"}]})
    layout.arrange(doc, default_registry())
    rob, sch = box_of(doc, "rob"), box_of(doc, "sch")
    self.assertAlmostEqual(sch[1] - (rob[1] + rob[3]),
                           2 * drc.WIRE_TO_CELL + drc.WIRE_GAP)

  def test_a_column_of_unwired_blocks_keeps_its_padding(self):
    doc = wired_column()
    doc.nets[:] = []
    layout.arrange(doc, default_registry())
    box = doc.containers[0]
    self.assertAlmostEqual(box_of(doc, "ren")[0] - box["x"], containers.padding(box))


@unittest.skipUnless(NODE, "node is not installed")
class TestTheEditorDrawsTheSame(unittest.TestCase):

  def test_every_mark_in_the_same_place(self):
    doc = nested()
    doc.containers[1]["title"] = "A title far too long for the box it is in"
    svg = render_svg.render(doc)
    exported = []
    for tag, attrs, text in re.findall(
        r'<(rect|path|text) (class="dl-container-[a-z]+"[^>]*?)(?: />|>([^<]*)</text>)', svg):
      get = dict(re.findall(r'([a-z-]+)="([^"]*)"', attrs))
      exported.append([get["class"], tag, get.get("x"), get.get("y"),
                       get.get("width"), get.get("height"), get.get("d"),
                       get.get("fill"), get.get("stroke"), get.get("font-size"),
                       text if tag == "text" else None])
    self.assertEqual(len(exported), 8)
    browser = _browser_render(doc, default_registry())["containers"]
    self.assertEqual(browser, exported)


if __name__ == "__main__":
  unittest.main()
