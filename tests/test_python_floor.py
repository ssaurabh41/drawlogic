"""The oldest Python this claims to run on, checked against the code.

The floor was stated as 3.8 for a long time and no 3.8 interpreter had ever
run the suite. Nothing failed, because nothing was looking: a version number
in a sentence is not a thing that can go red. It is the same shape as the DRC
that had no test and the parity check that compared two copies of itself --
something written down, believed, and never exercised.

So the number lives in drawlogic.MIN_PYTHON, and this file asks two questions
about it. Does the code actually stay inside it? And does the documentation
still quote it?

What this cannot do is run an old interpreter. Parsing under 3.9 rules proves
no newer *syntax* is used; it says nothing about behaviour that differs
between versions. The real check is CI running the suite on the floor itself
-- .github/workflows/tests.yml -- and this file is what catches the mistake
before it gets that far.

Usage:

    python3 -m unittest tests.test_python_floor
"""

import ast
import io
import os
import re
import unittest

import drawlogic

from tests import ROOT


FLOOR = drawlogic.MIN_PYTHON
FLOOR_TEXT = "%d.%d" % FLOOR


def sources():
  """Every Python file that has to run on the floor version."""
  for folder in ("drawlogic", "tests"):
    for base, dirs, names in os.walk(os.path.join(ROOT, folder)):
      dirs[:] = [d for d in dirs if d != "__pycache__"]
      for name in sorted(names):
        if name.endswith(".py"):
          yield os.path.join(base, name)


class TestTheCodeStaysInsideTheFloor(unittest.TestCase):

  def test_every_file_parses_under_the_oldest_supported_python(self):
    """One walrus in a comprehension, one `match`, one `int | None` and the
    floor is a fiction -- on an interpreter none of us is running, so the
    suite here would stay green either way."""
    broken = []
    for path in sources():
      with io.open(path, encoding="utf-8") as handle:
        text = handle.read()
      try:
        ast.parse(text, filename=path, feature_version=FLOOR)
      except SyntaxError as error:
        broken.append("%s:%s %s"
                      % (os.path.relpath(path, ROOT), error.lineno, error.msg))
    self.assertEqual(
      broken, [],
      "these use syntax newer than Python %s, which drawlogic.MIN_PYTHON says "
      "is the floor:\n  %s" % (FLOOR_TEXT, "\n  ".join(broken)))

  def test_the_check_would_notice_something_newer(self):
    """The negative control. A parse check that cannot fail is exactly the
    kind of thing this file exists to stop existing.

    `match` is used because it is a real grammar change and `feature_version`
    rejects it. Not everything newer is: `int | None` in an annotation parses
    happily under any version, because an annotation is not evaluated and `|`
    has always been valid in an expression. That is the honest limit of this
    approach, and the reason the stdlib names are checked separately below --
    and the reason CI runs the suite on the floor rather than trusting this.
    """
    with self.assertRaises(SyntaxError):
      ast.parse("match x:\n    case 1:\n        pass\n", feature_version=FLOOR)

  def test_no_standard_library_call_newer_than_the_floor(self):
    """Syntax is only half of it: `str.removeprefix` parses fine on 3.8 and
    raises AttributeError there. These are the ones worth naming."""
    too_new = {
      "removeprefix": (3, 9), "removesuffix": (3, 9),
      "graphlib": (3, 9), "zoneinfo": (3, 9),
      "math.lcm": (3, 9), "functools.cache": (3, 9),
      "itertools.pairwise": (3, 10), "datetime.UTC": (3, 11),
      "tomllib": (3, 11), "itertools.batched": (3, 12),
    }
    found = []
    for path in sources():
      # This file names every one of them in the table above, so scanning it
      # would report itself.
      if os.path.basename(path) == os.path.basename(__file__):
        continue
      with io.open(path, encoding="utf-8") as handle:
        text = handle.read()
      for name, since in sorted(too_new.items()):
        if since > FLOOR and re.search(r"\b%s\b" % re.escape(name), text):
          found.append("%s uses %s (new in %d.%d)"
                       % (os.path.relpath(path, ROOT), name, since[0], since[1]))
    self.assertEqual(found, [], "\n  ".join([""] + found))


class TestTheDocumentationAgrees(unittest.TestCase):
  """A floor nobody has written down is one nobody can rely on, and a floor
  written down in two places is one that will disagree with itself."""

  def read(self, name):
    with io.open(os.path.join(ROOT, name), encoding="utf-8") as handle:
      return handle.read()

  def test_the_manual_names_the_same_version(self):
    text = self.read("DOCUMENTATION.md")
    claimed = set(re.findall(r"Python (\d+\.\d+) or newer", text))
    self.assertTrue(claimed, "DOCUMENTATION.md no longer states a floor")
    self.assertEqual(
      claimed, {FLOOR_TEXT},
      "DOCUMENTATION.md says Python %s; drawlogic.MIN_PYTHON says %s"
      % (", ".join(sorted(claimed)), FLOOR_TEXT))

  def test_no_document_still_advertises_an_older_floor(self):
    """The specific way this went wrong: the number was corrected in one
    file and left standing in another."""
    for name in ("DOCUMENTATION.md", "REVIEW.md"):
      text = self.read(name)
      for stale in re.findall(r"Python (\d+\.\d+)\+", text):
        self.assertGreaterEqual(
          tuple(int(part) for part in stale.split(".")), FLOOR,
          "%s advertises Python %s+, below the floor of %s"
          % (name, stale, FLOOR_TEXT))


if __name__ == "__main__":
  unittest.main()
