"""The integrity manifest, and the guarantee that it is not stale.

A manifest is only worth having if it describes the files that are actually
here. One that has drifted is worse than none: it reports a healthy copy as
broken, and once it has done that a few times nobody reads its output, which
is the moment the next real mismatch goes past unnoticed.

So the manifest is generated rather than maintained -- `drawlogic doctor
--write-manifest` writes it -- and this file fails the moment the committed
one stops matching the tree. It cannot be forgotten, because forgetting it
goes red.

Usage:

    python3 -m unittest tests.test_manifest
"""

import hashlib
import os
import shutil
import tempfile
import unittest

from drawlogic import cli

from tests import ROOT


MANIFEST = os.path.join(ROOT, cli.MANIFEST_NAME)


class TestTheManifestIsCurrent(unittest.TestCase):

  def test_the_committed_manifest_matches_the_tree(self):
    with open(MANIFEST) as handle:
      committed = handle.read()
    self.assertEqual(
      committed, cli.manifest_text(ROOT),
      "manifest.txt no longer describes the files here. Regenerate it with "
      "`python3 -m drawlogic doctor --write-manifest` and commit the result.")

  def test_it_covers_every_file_that_has_to_be_right(self):
    listed = set()
    with open(MANIFEST) as handle:
      for line in handle:
        parts = line.split(None, 1)
        if len(parts) == 2:
          listed.add(parts[1].strip())
    self.assertEqual(listed, set(cli.manifest_files(ROOT)))

  def test_the_files_outside_the_package_are_covered_too(self):
    """sample.txt is the fixture for trying verify.ps1 by hand: edit it and
    the check should say MISMATCH.

    It sits outside the package tree the walk covers, so it was re-added to
    manifest.txt by hand after each regeneration. That is a step someone
    forgets, and the forgotten version of it is a manifest that disagrees
    with the tree -- so generation names these files instead.
    """
    self.assertIn("sample.txt", cli.EXTRA_FILES)
    for name in cli.EXTRA_FILES:
      self.assertIn(name, cli.manifest_files(ROOT),
                    "%s is declared but not generated into the manifest" % name)

  def test_doctor_is_happy_with_this_copy(self):
    problems, counted = cli._check_manifest(ROOT)
    self.assertEqual(problems, [])
    self.assertGreater(counted, 20)


class TestHashingIgnoresLineEndings(unittest.TestCase):
  """The whole reason the hash is not of the bytes on disk.

  Git rewrites line endings on checkout by default on Windows. A byte-for-byte
  manifest therefore reports every file in a perfectly good clone as wrong --
  which is exactly what happened when one was handed over: all 28 files
  "mismatched", not one of them actually different.
  """

  def write(self, folder, name, data):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
      handle.write(data)
    return path

  def test_crlf_and_lf_hash_the_same(self):
    with tempfile.TemporaryDirectory() as tmp:
      unix = self.write(tmp, "unix.py", b"one\ntwo\nthree\n")
      dos = self.write(tmp, "dos.py", b"one\r\ntwo\r\nthree\r\n")
      self.assertEqual(cli.content_hash(unix), cli.content_hash(dos))

  def test_an_old_mac_line_ending_hashes_the_same_too(self):
    with tempfile.TemporaryDirectory() as tmp:
      unix = self.write(tmp, "unix.py", b"one\ntwo\n")
      mac = self.write(tmp, "mac.py", b"one\rtwo\r")
      self.assertEqual(cli.content_hash(unix), cli.content_hash(mac))

  def test_a_byte_order_mark_hashes_the_same(self):
    """Notepad has put one on the front of files for years."""
    with tempfile.TemporaryDirectory() as tmp:
      plain = self.write(tmp, "plain.py", b"x = 1\n")
      marked = self.write(tmp, "marked.py", b"\xef\xbb\xbfx = 1\n")
      self.assertEqual(cli.content_hash(plain), cli.content_hash(marked))

  def test_a_real_difference_still_changes_the_hash(self):
    """Otherwise the forgiving part has quietly made it forgive everything."""
    with tempfile.TemporaryDirectory() as tmp:
      one = self.write(tmp, "one.py", b"x = 1\n")
      two = self.write(tmp, "two.py", b"x = 2\n")
      self.assertNotEqual(cli.content_hash(one), cli.content_hash(two))

  def test_whitespace_inside_a_line_still_counts(self):
    with tempfile.TemporaryDirectory() as tmp:
      tight = self.write(tmp, "tight.py", b"x = 1\n")
      loose = self.write(tmp, "loose.py", b"x  =  1\n")
      self.assertNotEqual(cli.content_hash(tight), cli.content_hash(loose))

  def test_a_missing_trailing_newline_hashes_the_same(self):
    """Pasting a file by hand -- viewing it on GitHub, selecting the text,
    dropping it into Notepad -- routinely loses the newline at the end
    without anything else having changed."""
    with tempfile.TemporaryDirectory() as tmp:
      with_nl = self.write(tmp, "with_nl.py", b"one\ntwo\n")
      without_nl = self.write(tmp, "without_nl.py", b"one\ntwo")
      self.assertEqual(cli.content_hash(with_nl), cli.content_hash(without_nl))

  def test_extra_trailing_blank_lines_hash_the_same(self):
    with tempfile.TemporaryDirectory() as tmp:
      one = self.write(tmp, "one.py", b"one\ntwo\n")
      several = self.write(tmp, "several.py", b"one\ntwo\n\n\n")
      self.assertEqual(cli.content_hash(one), cli.content_hash(several))

  def test_a_blank_line_in_the_middle_still_counts(self):
    with tempfile.TemporaryDirectory() as tmp:
      tight = self.write(tmp, "tight.py", b"one\ntwo\n")
      spaced = self.write(tmp, "spaced.py", b"one\n\ntwo\n")
      self.assertNotEqual(cli.content_hash(tight), cli.content_hash(spaced))


class TestCheckingFindsWhatItShould(unittest.TestCase):

  def copy(self, tmp):
    """A working copy of the package, with its manifest beside it."""
    shutil.copytree(os.path.join(ROOT, "drawlogic"),
                    os.path.join(tmp, "drawlogic"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(MANIFEST, os.path.join(tmp, cli.MANIFEST_NAME))
    for relative in cli.EXTRA_FILES:
      shutil.copy(os.path.join(ROOT, relative), os.path.join(tmp, relative))
    return tmp

  def test_a_clean_copy_has_nothing_to_report(self):
    with tempfile.TemporaryDirectory() as tmp:
      problems, counted = cli._check_manifest(self.copy(tmp))
      self.assertEqual(problems, [])
      self.assertGreater(counted, 20)

  def test_a_changed_file_is_reported(self):
    with tempfile.TemporaryDirectory() as tmp:
      self.copy(tmp)
      with open(os.path.join(tmp, "drawlogic", "theme.py"), "a") as handle:
        handle.write("\n# an edit from somewhere else\n")
      problems, _ = cli._check_manifest(tmp)
      self.assertTrue(any("theme.py" in p for p in problems), problems)

  def test_a_missing_file_is_reported(self):
    with tempfile.TemporaryDirectory() as tmp:
      self.copy(tmp)
      os.remove(os.path.join(tmp, "drawlogic", "web", "js", "selection.js"))
      problems, _ = cli._check_manifest(tmp)
      self.assertTrue(any("selection.js" in p and "missing" in p
                          for p in problems), problems)

  def test_a_file_nobody_asked_for_is_reported(self):
    """Usually a leftover from an older copy, which Python will happily
    import instead of the one meant to be there."""
    with tempfile.TemporaryDirectory() as tmp:
      self.copy(tmp)
      with open(os.path.join(tmp, "drawlogic", "web", "js", "old.js"),
                "w") as handle:
        handle.write("// left behind\n")
      problems, _ = cli._check_manifest(tmp)
      self.assertTrue(any("old.js" in p for p in problems), problems)

  def test_no_manifest_is_not_a_fault(self):
    """A copy without one is unchecked, not broken."""
    with tempfile.TemporaryDirectory() as tmp:
      problems, counted = cli._check_manifest(tmp)
      self.assertEqual(problems, [])
      self.assertIsNone(counted)


class TestTheWindowsScriptAgrees(unittest.TestCase):
  """verify.ps1 has to compute the same hash as content_hash does.

  It cannot be run here, so what is checked is that it is present, that it
  hashes the same way in words, and that the manifest it reads is in the
  shape it parses. The script itself was exercised against PowerShell 7.4 on
  a CRLF copy, a copy with a byte order mark, a changed file, a missing file
  and a leftover file -- see REVIEW.md.
  """

  def script(self):
    with open(os.path.join(ROOT, "verify.ps1")) as handle:
      return handle.read()

  def test_the_script_is_here(self):
    self.assertTrue(os.path.isfile(os.path.join(ROOT, "verify.ps1")))

  def test_it_normalises_line_endings_before_hashing(self):
    text = self.script()
    self.assertIn('-replace "`r`n", "`n"', text)
    self.assertIn('-replace "`r", "`n"', text)

  def test_it_normalises_trailing_newlines_before_hashing(self):
    text = self.script()
    self.assertIn('TrimEnd("`n")', text)

  def test_it_hashes_with_sha256(self):
    self.assertIn("SHA256", self.script())

  def test_every_manifest_line_matches_what_the_script_parses(self):
    """The script reads lines with ^([0-9a-fA-F]{64})\\s+(.+)$ -- so every
    line the manifest writes has to be one of those."""
    import re
    pattern = re.compile(r"^([0-9a-fA-F]{64})\s+(.+)$")
    with open(MANIFEST) as handle:
      lines = [line.rstrip("\n") for line in handle if line.strip()]
    self.assertTrue(lines)
    for line in lines:
      self.assertRegex(line, pattern)

  def test_no_path_in_the_manifest_needs_escaping(self):
    """Backslashes, spaces and quotes in a path would each be a way for the
    PowerShell side to read a line differently from the Python side."""
    with open(MANIFEST) as handle:
      for line in handle:
        parts = line.split(None, 1)
        if len(parts) != 2:
          continue
        path = parts[1].strip()
        self.assertNotIn("\\", path)
        self.assertNotIn('"', path)
        self.assertNotIn("'", path)
        self.assertNotIn(" ", path)


if __name__ == "__main__":
  unittest.main()
