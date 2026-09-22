"""Run the suite across every core, and print only what went wrong.

    python3 tests/run.py                  # everything
    python3 tests/run.py test_layout      # modules whose name contains this

The same tests `python3 -m unittest discover -s tests` runs, split by test
class rather than by module: one module (test_layout) is most of the
suite's time, so splitting by module leaves the other cores idle while it
runs. A class stays whole so its setUpClass runs once, as it would serially.

A passing run prints one line. That is the point: the full verbose output of
a green suite is a few hundred lines nobody reads, and on a failure it buries
the one traceback that matters.
"""

import multiprocessing
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _classes(pattern):
  suite = unittest.defaultTestLoader.discover(HERE, top_level_dir=ROOT)
  found = []

  def walk(node):
    for item in node:
      if isinstance(item, unittest.TestSuite):
        walk(item)
      else:
        name = "%s.%s" % (type(item).__module__, type(item).__name__)
        if pattern in type(item).__module__ and name not in found:
          found.append(name)
  walk(suite)
  return found


def _run(name):
  suite = unittest.defaultTestLoader.loadTestsFromName(name)
  result = unittest.TestResult()
  suite.run(result)
  problems = [("FAIL", test.id(), trace) for test, trace in result.failures]
  problems += [("ERROR", test.id(), trace) for test, trace in result.errors]
  return name, result.testsRun, len(result.skipped), problems


def main(argv):
  sys.path.insert(0, ROOT)
  names = _classes(argv[0] if argv else "")
  started = time.time()
  ran = skipped = 0
  problems = []
  with multiprocessing.Pool() as pool:
    for _name, count, skips, found in pool.imap_unordered(_run, names):
      ran += count
      skipped += skips
      problems.extend(found)

  for kind, test_id, trace in sorted(problems, key=lambda p: p[1]):
    print("=" * 70)
    print("%s: %s" % (kind, test_id))
    print(trace)
  print("%d tests, %d failed, %d skipped, %.1fs"
        % (ran, len(problems), skipped, time.time() - started))
  return 1 if problems else 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
