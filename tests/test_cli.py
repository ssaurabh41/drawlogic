"""The command line, exercised as a user would type it.

Everything else in the suite calls render_svg.render() directly. This file
exists because cmd_export() sits between the command line and that call, and
a bug can live entirely in how it translates flags into arguments -- which is
exactly what happened here.
"""

import os
import tempfile
import unittest

from drawlogic import cli, render_svg
from drawlogic.doc import new_document


def _wired_document(title, **canvas):
  doc = new_document(title)
  doc.data["canvas"].update(canvas)
  doc.cells.extend([
    {"id": "a", "type": "port_out", "x": 10, "y": 10},
    {"id": "b", "type": "port_in", "x": 200, "y": 10},
  ])
  doc.nets.append({
    "id": "n1", "name": "sig", "width": 1,
    "from": {"cell": "a", "pin": "p"},
    "to": [{"cell": "b", "pin": "p", "waypoints": []}],
  })
  doc.normalize()
  return doc


class TestExportRespectsTheDocument(unittest.TestCase):
  """`export` must agree with what the document itself asks for.

  cmd_export() used to pass a concrete True/False for `arrows` and `hops` on
  every run, because `not args.no_arrows` is True whenever the flag is simply
  absent -- there is no way to tell "absent" from "explicitly wanted" once it
  has gone through `not`. render_svg.render() treats None, not True, as "defer
  to canvas.arrows" (see its docstring), so every CLI export silently forced
  both on regardless of what the file said, while the same document exported
  through the editor's /api/export correctly left them off. A document saved
  with canvas.arrows: false rendered with arrows anyway, every time.
  """

  def test_arrows_off_in_the_document_stays_off_with_no_flag(self):
    doc = _wired_document("no-arrows", arrows=False)
    with tempfile.TemporaryDirectory() as tmp:
      src = os.path.join(tmp, "d.dlg")
      out = os.path.join(tmp, "d.svg")
      doc.save(src)
      cli.main(["export", src, "-o", out])
      with open(out) as handle:
        svg = handle.read()
    self.assertNotIn("<polygon", svg,
                     "canvas.arrows is false; the CLI must not add arrows "
                     "just because --no-arrows was not typed")

  def test_no_arrows_flag_still_forces_it_off(self):
    doc = _wired_document("arrows-on")  # canvas.arrows defaults to True
    with tempfile.TemporaryDirectory() as tmp:
      src = os.path.join(tmp, "d.dlg")
      out = os.path.join(tmp, "d.svg")
      doc.save(src)
      cli.main(["export", src, "-o", out, "--no-arrows"])
      with open(out) as handle:
        svg = handle.read()
    self.assertNotIn("<polygon", svg,
                     "--no-arrows is an explicit override and must still work")

  def test_no_flag_and_no_override_keeps_the_default_on(self):
    doc = _wired_document("arrows-on")
    with tempfile.TemporaryDirectory() as tmp:
      src = os.path.join(tmp, "d.dlg")
      out = os.path.join(tmp, "d.svg")
      doc.save(src)
      cli.main(["export", src, "-o", out])
      with open(out) as handle:
        svg = handle.read()
    self.assertIn("<polygon", svg,
                  "a document with nothing said about arrows still defaults "
                  "to drawing them")

  def test_cli_and_direct_render_agree_for_every_combination(self):
    for arrows_flag, hops_flag in ((False, False), (False, True),
                                   (True, False), (True, True)):
      with self.subTest(canvas_arrows=arrows_flag, canvas_hops=hops_flag):
        doc = _wired_document("combo", arrows=arrows_flag, hops=hops_flag)
        with tempfile.TemporaryDirectory() as tmp:
          src = os.path.join(tmp, "d.dlg")
          out = os.path.join(tmp, "d.svg")
          doc.save(src)
          cli.main(["export", src, "-o", out])
          with open(out) as handle:
            cli_svg = handle.read()
        direct_svg = render_svg.render(doc)
        self.assertEqual(cli_svg, direct_svg,
                         "CLI export must match what the document itself "
                         "renders to, the same claim the manual makes about "
                         "editor and CLI export agreeing byte for byte")


if __name__ == "__main__":
  unittest.main()
