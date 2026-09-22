"""The command line, exercised as a user would type it.

Everything else in the suite calls render_svg.render() directly. This file
exists because cmd_export() sits between the command line and that call, and
a bug can live entirely in how it translates flags into arguments -- which is
exactly what happened here.
"""

import contextlib
import io
import os
import tempfile
import unittest

from drawlogic import cli, render_svg
from drawlogic.doc import new_document


def _export(argv):
  # export reports the file it wrote on stderr, which is noise in a test run.
  with contextlib.redirect_stderr(io.StringIO()):
    return cli.main(argv)


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
      _export(["export", src, "-o", out])
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
      _export(["export", src, "-o", out, "--no-arrows"])
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
      _export(["export", src, "-o", out])
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
          _export(["export", src, "-o", out])
          with open(out) as handle:
            cli_svg = handle.read()
        direct_svg = render_svg.render(doc)
        self.assertEqual(cli_svg, direct_svg,
                         "CLI export must match what the document itself "
                         "renders to, the same claim the manual makes about "
                         "editor and CLI export agreeing byte for byte")


def _shorted_document():
  """Two nets forced onto one corridor: the drawing says they are joined."""
  doc = new_document("shorted", 600, 420)
  doc.cells.extend([
    {"id": "in1", "type": "port_in", "x": 60, "y": 100, "label": "in1"},
    {"id": "in2", "type": "port_in", "x": 60, "y": 160, "label": "in2"},
    {"id": "U1", "type": "and2", "x": 105, "y": 100},
  ])
  doc.nets.extend([
    {"id": "n1", "name": "s1", "from": {"cell": "in2", "pin": "p"},
     "to": [{"cell": "U1", "pin": "a"}]},
    {"id": "n2", "name": "s2", "from": {"cell": "in1", "pin": "p"},
     "to": [{"cell": "U1", "pin": "b"}]},
  ])
  doc.normalize()
  return doc


def _validate(doc, *flags):
  """Run `validate` over a document and hand back (exit code, output)."""
  out = io.StringIO()
  with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "d.dlg")
    doc.save(path)
    with contextlib.redirect_stdout(out):
      code = cli.main(["validate", path] + list(flags))
  return code, out.getvalue()


class TestValidateRunsTheDrcs(unittest.TestCase):
  """`validate` checks how a drawing reads, not only what it references.

  Reference faults and rule failures are two halves of one question -- is
  this drawing fit to hand to someone else -- so they come out of one command
  and one exit code rather than needing two runs to find out.
  """

  def test_a_drc_error_fails_the_command(self):
    code, output = _validate(_shorted_document())
    self.assertEqual(code, 1, "a drawing with a hidden short exited 0")
    self.assertIn("on top of each other", output)
    self.assertIn("wire-short", output,
                  "the rule that found it is the heading to look up, so the "
                  "message has to name it")

  def test_no_drc_skips_them(self):
    """The escape hatch has to actually let a drawing through, or it is not
    an escape hatch."""
    code, output = _validate(_shorted_document(), "--no-drc")
    self.assertEqual(code, 0)
    self.assertNotIn("on top of each other", output)

  def test_a_clean_drawing_still_passes(self):
    doc = _wired_document("clean")
    code, _ = _validate(doc)
    self.assertEqual(code, 0)


class TestDoctor(unittest.TestCase):
  """`doctor` answers "do the pieces of this copy still fit each other".

  Three bug reports in a row were one thing: files copied over one at a time,
  leaving the Python and the JavaScript from different versions of the project
  calling into functions the other half no longer had. Each looked like a real
  bug -- a browser that would not draw, a Check that crashed, a colour picker
  that was not there -- and none of them was visible by reading a file.
  """

  def run_doctor(self):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
      code = cli.main(["doctor"])
    return code, out.getvalue()

  def test_a_healthy_copy_passes(self):
    code, output = self.run_doctor()
    self.assertEqual(code, 0, output)
    self.assertIn("consistent with itself", output)

  def test_it_exercises_the_python_rather_than_inspecting_it(self):
    code, output = self.run_doctor()
    self.assertEqual(code, 0)
    for step in ("route a wire", "check the rules", "lay it out",
                 "render to SVG"):
      self.assertIn(step, output)

  def test_it_notices_a_module_missing_a_function_another_calls(self):
    """The Check crash: drc asks render_svg for cell_label_box, and an older
    render_svg does not have one."""
    real = render_svg.cell_label_box
    del render_svg.cell_label_box
    try:
      code, output = self.run_doctor()
    finally:
      render_svg.cell_label_box = real
    self.assertEqual(code, 1)
    self.assertIn("cell_label_box", output)

  def test_it_notices_a_browser_import_nothing_exports(self):
    """The blank editor: tools.js imported handlePoints from a selection.js
    that had not been updated to export it."""
    from drawlogic import cli as cli_module
    problems, count = cli_module._js_imports(
      os.path.join(os.path.dirname(os.path.abspath(cli_module.__file__)),
                   "web", "js"))
    self.assertGreater(count, 0, "found no browser modules to check")
    self.assertEqual(problems, [])

  def test_the_browser_check_can_actually_fail(self):
    """Otherwise it reports a clean bill on anything, which is the shape of
    bug it exists to catch."""
    from drawlogic import cli as cli_module
    with tempfile.TemporaryDirectory() as tmp:
      with open(os.path.join(tmp, "one.js"), "w") as handle:
        handle.write('import { missing } from "./two.js";\n')
      with open(os.path.join(tmp, "two.js"), "w") as handle:
        handle.write("export function present() {}\n")
      problems, count = cli_module._js_imports(tmp)
    self.assertEqual(count, 2)
    self.assertEqual(len(problems), 1)
    self.assertIn("missing", problems[0])


if __name__ == "__main__":
  unittest.main()
