"""drawlogic: draw logic circuit schematics and export them as SVG."""

from .doc import Document, new_document
from .symbols import Registry, Symbol, default_registry, load_registry

__version__ = "0.1.0"

# The oldest Python this is tested on, and the one the test suite is run
# against. Held here so there is one place that says it: the documentation
# quotes this number, `doctor` compares the running interpreter to it, and
# tests/test_python_floor.py fails if any source file uses something newer.
#
# It was 3.8 for a while on nobody's evidence -- no 3.8 interpreter had ever
# run the suite. A supported version that is never exercised is a guess with
# a version number on it, so the floor is now the oldest one actually run.
MIN_PYTHON = (3, 9)

__all__ = [
  "Document",
  "MIN_PYTHON",
  "Registry",
  "Symbol",
  "__version__",
  "default_registry",
  "load_registry",
  "new_document",
]
