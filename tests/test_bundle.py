"""tools/pack_repo.py and tools/unpack_repo.py: the repository as one text file.

For a workstation that cannot clone the repository but can take a pasted file.
What matters is that the tree comes back byte for byte -- doctor checks every
file against manifest.txt -- and that a paste that damaged something says
which file, rather than leaving a quietly broken copy.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT

PACK = os.path.join(ROOT, "tools", "pack_repo.py")
UNPACK = os.path.join(ROOT, "tools", "unpack_repo.py")


def run(*args, cwd=None):
  return subprocess.run([sys.executable] + list(args), cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True)


class TestBundle(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.TemporaryDirectory()
    cls.bundle = os.path.join(cls.tmp.name, "bundle.txt")
    result = run(PACK, "--root", ROOT, "-o", cls.bundle)
    assert result.returncode == 0, result.stdout
    with open(cls.bundle, encoding="utf-8") as handle:
      cls.text = handle.read()

  @classmethod
  def tearDownClass(cls):
    cls.tmp.cleanup()

  def unpack(self, text, *extra):
    path = os.path.join(self.tmp.name, "pasted.txt")
    with open(path, "w", encoding="utf-8", newline="") as handle:
      handle.write(text)
    return run(UNPACK, path, *extra)

  def test_the_tree_comes_back_byte_for_byte(self):
    dest = os.path.join(self.tmp.name, "rebuilt")
    result = run(UNPACK, self.bundle, "-d", dest)
    self.assertEqual(result.returncode, 0, result.stdout)
    checked = 0
    for rel in ("drawlogic/render_svg.py", "drawlogic/symbols.json",
                "manifest.txt", "tools/unpack_repo.py", "examples/soc_top.dlg"):
      with open(os.path.join(ROOT, rel), "rb") as a, \
           open(os.path.join(dest, rel), "rb") as b:
        self.assertEqual(a.read(), b.read(), rel)
      checked += 1
    self.assertEqual(checked, 5)

  def test_windows_line_endings_from_a_paste_are_forgiven(self):
    result = self.unpack(self.text.replace("\n", "\r\n"), "--check")
    self.assertEqual(result.returncode, 0, result.stdout)

  def test_a_dropped_line_is_named(self):
    lines = self.text.split("\n")
    at = lines.index(next(l for l in lines if "path=drawlogic/doc.py" in l)) + 40
    result = self.unpack("\n".join(lines[:at] + lines[at + 1:]), "--check")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("BAD  drawlogic/doc.py", result.stdout)

  def test_a_changed_character_is_named(self):
    start = self.text.index("path=drawlogic/theme.py")
    at = self.text.index("INK", start)
    result = self.unpack(self.text[:at] + "INC" + self.text[at + 3:], "--check")
    self.assertIn("BAD  drawlogic/theme.py: content changed", result.stdout)

  def test_a_paste_cut_short_says_files_are_missing(self):
    result = self.unpack(self.text[:len(self.text) // 3], "--check")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("were cut off", result.stdout)


if __name__ == "__main__":
  unittest.main()
