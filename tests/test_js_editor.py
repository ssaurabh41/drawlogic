"""The editor behaviour that exists only in JavaScript.

Drag-time alignment (`guides.js`) and the Tidy command (`model.tidy`) have no
Python counterpart, so nothing else in the suite can reach them. The checks
themselves live in tests/js/editor_check.mjs and run under node; this wrapper
exists so they fail the ordinary `python3 -m unittest discover` run rather than
waiting to be remembered.

Node is not a dependency of drawlogic, so this skips itself when node is not
installed. Run it directly with:

    python3 -m unittest tests.test_js_editor
"""

import os
import shutil
import subprocess
import unittest

from tests import ROOT

NODE = shutil.which("node")
CHECK = os.path.join(ROOT, "tests", "js", "editor_check.mjs")
SYMBOLS = os.path.join(ROOT, "drawlogic", "symbols.json")


@unittest.skipUnless(NODE, "node is not installed")
class TestEditorBehaviour(unittest.TestCase):

  def test_alignment_and_tidy(self):
    result = subprocess.run([NODE, CHECK, SYMBOLS], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout.decode("utf-8", "replace")
    self.assertEqual(result.returncode, 0, "\n" + output)
    # A script that printed nothing would pass vacuously.
    self.assertIn("ok   ", output)


if __name__ == "__main__":
  unittest.main()
