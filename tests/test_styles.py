"""Headings, text styles and named styles.

What matters: a block can carry a bold heading over smaller text without a
text shape laid on top of it; a named style changes every block using it and
none of what a block overrides itself; the box grows to hold what is written,
by the same measure the checker uses; and the editor draws all of it exactly
where an export does. A drawing using none of it must come out as it did --
which the golden files in test_regression already hold every example to.

Usage:

    python3 -m unittest tests.test_styles
"""

import copy
import re
import unittest

from drawlogic import drc, render_svg, styles
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry

from tests.test_js_parity import NODE, _browser_render

COMPUTE = {"style": {"fill": "#d8edb4", "stroke": "#6b8f2a"},
           "headingStyle": {"fontSize": 16, "fill": "#17252d"},
           "textStyle": {"fontSize": 12, "fill": "#52656f", "lineHeight": 1.4}}


def styled():
  """Three SMs sharing one named style, one of them with its own colour, a
  box shape using it too, and a container titled in it."""
  doc = new_document("styled", 900, 500)
  doc.data["styles"] = {"compute": copy.deepcopy(COMPUTE)}
  for index in range(3):
    doc.cells.append({"id": "sm%d" % index, "type": "block", "styleRef": "compute",
                      "x": 60 + index * 220, "y": 120,
                      "heading": "SM %d" % index,
                      "text": ["Warp scheduler", "128 FP32 lanes"]})
  doc.cells[2]["style"] = {"fill": "#ffe0b2"}
  doc.cells[2]["textStyle"] = {"fill": "#7a3e00", "fontWeight": 600}
  doc.shapes.append({"id": "note", "kind": "rect", "x": 60, "y": 330, "w": 260, "h": 90,
                     "styleRef": "compute", "heading": "L1 <shared> & tex",
                     "text": ["192 KB"], "textAlign": "left"})
  doc.data["containers"] = [{"id": "k", "title": "GPC 0", "x": 40, "y": 60, "w": 700,
                             "h": 400, "styleRef": "compute",
                             "headingStyle": {"fontSize": 15}}]
  for item in doc.cells + doc.shapes:
    item["parentId"] = "k"
  doc.normalize()
  return doc


def written(svg, css):
  """[(text, x, y, size, weight, fill), ...] for one class of writing."""
  found = []
  for attrs, text in re.findall(r'<text (class="%s"[^>]*)>([^<]*)</text>' % css, svg):
    get = dict(re.findall(r'([a-z-]+)="([^"]*)"', attrs))
    found.append((text, float(get["x"]), float(get["y"]), float(get["font-size"]),
                  get.get("font-weight"), get["fill"]))
  return found


class TestHeadings(unittest.TestCase):

  def setUp(self):
    self.doc = styled()
    self.svg = render_svg.render(self.doc)

  def test_a_bold_heading_over_smaller_text(self):
    heading = [w for w in written(self.svg, "dl-cell-heading") if w[0] == "SM 0"][0]
    body = [w for w in written(self.svg, "dl-cell-text") if w[0] == "Warp scheduler"][0]
    self.assertEqual(heading[3], 16)
    self.assertEqual(heading[4], "600")
    self.assertEqual(body[3], 12)
    self.assertIsNone(body[4])
    self.assertLess(heading[2], body[2])
    # A heading is followed by more air than a line by the next.
    lines = sorted(w[2] for w in written(self.svg, "dl-cell-text") if w[1] == body[1])
    self.assertGreater(body[2] - heading[2], lines[1] - lines[0] - 16 * 0.2)

  def test_the_box_grows_to_hold_heading_and_text(self):
    look = styles.effective(self.doc.styles, self.doc.cell("sm0"))
    need_w, need_h = render_svg.text_needs(look)
    self.assertGreaterEqual(self.doc.cell("sm0")["h"], need_h - 1e-6)
    self.assertGreaterEqual(self.doc.cell("sm0")["w"], need_w - 1e-6)
    # Grown to hold the heading too: more than the text alone needs.
    alone = render_svg.text_needs(dict(look, heading=None))
    self.assertGreater(need_h, alone[1])

  def test_a_named_style_setting_bigger_text_grows_the_box_on_load(self):
    doc = styled()
    doc.styles["compute"]["textStyle"]["fontSize"] = 22
    doc = Document.loads(doc.dumps())
    for cell_id in ("sm0", "sm1"):
      need_w, need_h = render_svg.text_needs(styles.effective(doc.styles, doc.cell(cell_id)))
      self.assertGreater(need_h, 90)
      self.assertGreaterEqual(doc.cell(cell_id)["h"], need_h - 1e-6)
      self.assertGreaterEqual(doc.cell(cell_id)["w"], need_w - 1e-6)

  def test_text_cut_short_with_fitting_off_is_reported(self):
    doc = styled()
    cell = doc.cell("sm1")
    cell["textFit"] = False
    cell["h"] = 50
    doc.normalize()
    found = [v for v in drc.check(doc, default_registry()) if v.rule == "cell-text-clipped"]
    self.assertEqual(len(found), 1)
    self.assertIn("of 3 lines", found[0].message)
    shown = written(render_svg.render(doc), "dl-cell-(?:heading|text)")
    self.assertTrue(any(w[0].endswith("\u2026") for w in shown if 280 < w[1] < 480))

  def test_writing_is_escaped(self):
    self.assertIn("L1 &lt;shared&gt; &amp; tex", self.svg)
    self.assertNotIn("<shared>", self.svg)

  def test_a_shape_takes_a_heading_too(self):
    self.assertEqual([w[0] for w in written(self.svg, "dl-shape-heading")],
                     ["L1 &lt;shared&gt; &amp; tex"])

  def test_a_container_title_is_set_by_its_heading_style(self):
    title = re.search(r'<text class="dl-container-title"[^>]*font-size="([^"]+)"[^>]*'
                      r'fill="([^"]+)"', self.svg)
    self.assertEqual(title.group(1), "15")      # its own size over the style's 16
    self.assertEqual(title.group(2), "#17252d")  # the style's colour


class TestNamedStyles(unittest.TestCase):

  def test_editing_a_named_style_changes_every_block_using_it(self):
    doc = styled()
    doc.styles["compute"]["style"]["stroke"] = "#123456"
    svg = render_svg.render(doc)
    for cell_id in ("sm0", "sm1", "sm2"):
      group = re.search(r'<g class="dl-cell" data-id="%s".*?</g>' % cell_id, svg, re.S).group(0)
      self.assertIn('stroke="#123456"', group)

  def test_what_a_block_overrides_stays_its_own(self):
    doc = styled()
    doc.styles["compute"]["style"]["fill"] = "#000001"
    svg = render_svg.render(doc)
    own = re.search(r'<g class="dl-cell" data-id="sm2".*?</g>', svg, re.S).group(0)
    shared = re.search(r'<g class="dl-cell" data-id="sm0".*?</g>', svg, re.S).group(0)
    self.assertIn('fill="#ffe0b2"', own)
    self.assertIn('fill="#000001"', shared)
    texts = [w for w in written(svg, "dl-cell-text") if w[0] == "128 FP32 lanes"]
    self.assertEqual(sorted(w[5] for w in texts), ["#52656f", "#52656f", "#7a3e00"])
    self.assertEqual(sorted(str(w[4]) for w in texts), ["600", "None", "None"])

  def test_nothing_is_written_into_the_blocks(self):
    doc = Document.loads(styled().dumps())
    self.assertNotIn("fill", doc.cell("sm0").get("style", {}))
    self.assertNotIn("textStyle", doc.cell("sm0"))
    self.assertEqual(doc.styles["compute"]["textStyle"]["lineHeight"], 1.4)
    self.assertEqual(Document.loads(doc.dumps()).dumps(), doc.dumps())

  def test_a_drawing_without_styles_writes_no_key(self):
    doc = new_document("plain")
    self.assertNotIn('"styles"', doc.dumps())

  def test_a_missing_style_is_a_warning_and_draws_as_none(self):
    doc = styled()
    doc.cell("sm0")["styleRef"] = "gone"
    warned = [str(i) for i in doc.validate() if "gone" in i.message]
    self.assertEqual(len(warned), 1, warned)
    self.assertIs(styles.effective(doc.styles, doc.cell("sm0")), doc.cell("sm0"))


@unittest.skipUnless(NODE, "node is not installed")
class TestTheEditorSetsTextTheSame(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.doc = styled()
    cls.svg = render_svg.render(cls.doc)
    cls.browser = _browser_render(cls.doc, default_registry())

  def test_every_line_in_the_same_place_size_weight_and_colour(self):
    exported = []
    for css, attrs, text in re.findall(
        r'<text class="(dl-(?:cell|shape)-(?:text|heading))"([^>]*)>([^<]*)</text>', self.svg):
      get = dict(re.findall(r'([a-z-]+)="([^"]*)"', attrs))
      exported.append([css, text.replace("&lt;", "<").replace("&gt;", ">")
                       .replace("&amp;", "&"), get["x"], get["y"], get["text-anchor"],
                       get["font-family"].replace("&#x27;", "'").replace("&#39;", "'"),
                       get["font-size"], get.get("font-weight"), get["fill"]])
    self.assertEqual(len(exported), 11)
    self.assertEqual(self.browser["writing"], sorted(exported))

  def test_the_named_style_paints_the_same_bodies(self):
    bodies = dict((row[0], row[1]) for row in self.browser["bodies"])
    self.assertEqual(bodies["sm0"], ["#d8edb4", "#6b8f2a"])
    self.assertEqual(bodies["sm2"], ["#ffe0b2", "#6b8f2a"])

  def test_the_container_title_is_the_same(self):
    title = [row for row in self.browser["containers"] if row[0] == "dl-container-title"]
    self.assertEqual(title[0][9], "15")
    self.assertEqual(title[0][7], "#17252d")


if __name__ == "__main__":
  unittest.main()
