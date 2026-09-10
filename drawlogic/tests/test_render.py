import re
import unittest

from drawlogic import render_svg
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry
from tests import EXAMPLE


def _viewbox(svg):
  match = re.search(r'viewBox="([^"]+)"', svg)
  return [float(v) for v in match.group(1).split()]


def _size(svg):
  width = float(re.search(r'\bwidth="([\d.]+)"', svg).group(1))
  height = float(re.search(r'\bheight="([\d.]+)"', svg).group(1))
  return width, height


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

  def test_bus_is_drawn_heavier(self):
    svg = render_svg.render(self.doc)
    bus = re.search(r'data-id="n8"[^>]*stroke-width="([\d.]+)"', svg)
    single = re.search(r'data-id="n1"[^>]*stroke-width="([\d.]+)"', svg)
    self.assertGreater(float(bus.group(1)), float(single.group(1)))


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


class TestSymbolPreview(unittest.TestCase):

  def test_previews_a_single_symbol(self):
    symbol = default_registry().require("mux2")
    svg = render_svg.render_symbol(symbol)
    self.assertIn("<svg ", svg)
    self.assertIn("2:1 multiplexer", svg)


if __name__ == "__main__":
  unittest.main()
