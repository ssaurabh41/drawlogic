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

  # Raising this when checks are added is the point: it is the one number
  # that notices if a whole area of the editor quietly stops being tested.
  MINIMUM_CHECKS = 30

  def test_alignment_and_tidy(self):
    result = subprocess.run([NODE, CHECK, SYMBOLS], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout.decode("utf-8", "replace")
    self.assertEqual(result.returncode, 0, "\n" + output)

    # Exit zero and an "ok" line used to be the whole guard, which a file cut
    # down to a single console.log satisfied completely -- every real
    # assertion could disappear without the suite noticing. The runner now
    # ends with a record of how many checks it ran, counted by itself, and
    # that record only prints if it reached the end.
    done = [line for line in output.splitlines() if line.startswith("DONE ")]
    self.assertEqual(
      len(done), 1,
      "the runner did not report completion; it exited early or was "
      "replaced:\n" + output)

    ran, expected = (int(part) for part in done[0].split()[1].split("/"))
    self.assertEqual(ran, expected, "\n" + output)
    self.assertGreaterEqual(
      ran, self.MINIMUM_CHECKS,
      "only %d editor checks ran, expected at least %d -- either checks were "
      "deleted or the runner stopped early:\n%s"
      % (ran, self.MINIMUM_CHECKS, output))
    self.assertEqual(
      sum(line.startswith("ok   ") for line in output.splitlines()), ran,
      "the runner's own count disagrees with the lines it printed:\n"
      + output)


if __name__ == "__main__":
  unittest.main()
