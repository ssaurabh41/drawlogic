"""Test package.

Puts the project root on sys.path so the tests run without the package being
installed, which keeps `python3 -m unittest discover` working from a fresh
clone with nothing set up.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
  sys.path.insert(0, _ROOT)

ROOT = _ROOT
EXAMPLE = os.path.join(_ROOT, "examples", "dff_slice.dlg")


def open_example(path):
  """Open an example the way the CLI does: references resolved.

  Loading one with Document.load alone leaves any `ref` unresolved, which
  reads as an unknown cell type -- so every check that walks the examples has
  to come through here or it will fail on a hierarchical drawing.
  """
  from drawlogic import sheets

  doc, registry, issues = sheets.open_document(path)
  return doc, registry, issues
