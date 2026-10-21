"""Containers: titled boundaries that own part of a drawing.

What matters is that ownership is the `parentId` field and nothing else: it
survives a save, the checker catches every way it can be wrong, and the box is
drawn beneath what it holds, the same in the editor as in an exported file.

Usage:

    python3 -m unittest tests.test_containers
"""

import re
import unittest

from drawlogic import containers, render_svg
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
