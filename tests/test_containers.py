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


class TestWiresKeepOffTitles(unittest.TestCase):

  def test_a_wire_does_not_run_through_a_title(self):
    from drawlogic import routing
    doc = across_a_title()
    title = containers.title_box(doc.containers[0])
    [(_net, [points])] = routing.route_all(doc)
    for a, b in zip(points, points[1:]):
      if abs(a[1] - b[1]) < 1e-6:
        crosses = (title[1] <= a[1] <= title[3]
                   and min(a[0], b[0]) < title[2] and max(a[0], b[0]) > title[0])
        self.assertFalse(crosses, "run %s-%s goes through the title %s" % (a, b, title))
    # And it is not that the wire happened to miss: straight, it would not.
    start = points[0]
    self.assertTrue(title[1] <= start[1] <= title[3])

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
