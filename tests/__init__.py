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
