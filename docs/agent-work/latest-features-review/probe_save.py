"""Independent probes of atomic saves, backups and the write path.

Run (from this directory):

    python -m unittest discover -s . -p "probe_*.py" -v
"""

import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

from drawlogic import doc as docmod
from drawlogic.doc import Document, new_document


class TestAtomicSave(unittest.TestCase):

  def setUp(self):
    self.folder = tempfile.mkdtemp()
    self.path = os.path.join(self.folder, "d.dlg")
    with open(self.path, "w") as handle:
      handle.write("the good version\n")

  def test_a_save_that_cannot_be_renamed_leaves_the_old_file_and_no_litter(self):
    with mock.patch("os.replace", side_effect=OSError("disk full")):
      with self.assertRaises(OSError):
        docmod.write_file(self.path, "new\n", backup=True)
    with open(self.path) as handle:
      self.assertEqual(handle.read(), "the good version\n")
    self.assertEqual([f for f in os.listdir(self.folder) if f.endswith(".tmp")],
                     [])

  def test_the_posting_style_write_of_the_editor_makes_one_backup(self):
    docmod.write_file(self.path, "one\n", backup=True)
    docmod.write_file(self.path, "two\n", backup=True)
    docmod.write_file(self.path, "two\n", backup=True)
    with open(self.path) as handle:
      self.assertEqual(handle.read(), "two\n")
    with open(self.path + ".bak") as handle:
      self.assertEqual(handle.read(), "one\n")

  def test_the_mode_is_kept_as_the_platform_reports_it(self):
    """The docstring promises the save does not change who can read the file.
    On Windows there is no POSIX mode to preserve, so this records what
    actually comes back rather than asserting the POSIX answer."""
    os.chmod(self.path, 0o644)
    before = stat.S_IMODE(os.stat(self.path).st_mode)
    docmod.write_file(self.path, "new\n")
    after = stat.S_IMODE(os.stat(self.path).st_mode)
    self.assertEqual(before, after,
                     "mode changed across a save on %s" % sys.platform)


class TestDocumentSaveUsesIt(unittest.TestCase):

  def test_saving_a_document_makes_a_backup_beside_it(self):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "drawing.dlg")
    doc = new_document("drawing", 400, 300)
    doc.save(path)
    doc.data["title"] = "changed"
    doc.save()
    with open(path + ".bak") as handle:
      self.assertIn('"drawing"', handle.read())


if __name__ == "__main__":
  unittest.main()
