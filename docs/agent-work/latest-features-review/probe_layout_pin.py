"""Independent probes of selection layout and pinning (`layout.arrange`).

Run (from this directory):

    python -m unittest discover -s . -p "probe_*.py" -v
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

from drawlogic import drc, layout
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry


def cell(cell_id, x, y, kind="and2", **extra):
  spec = {"id": cell_id, "type": kind, "x": x, "y": y}
  spec.update(extra)
  return spec


class TestSelectionKeepsTheRest(unittest.TestCase):

  def build(self):
    d = new_document("sel", 900, 700)
    d.data["cells"] = [
      cell("a", 300, 400), cell("b", 300, 520), cell("c", 300, 640),
      cell("far", 700, 300, pinned=True),
      cell("out", 700, 520),
    ]
    d.data["nets"] = [
      {"id": "n1", "from": {"cell": "a", "pin": "y"},
       "to": [{"cell": "b", "pin": "a"}]},
      {"id": "n2", "from": {"cell": "b", "pin": "y"},
       "to": [{"cell": "c", "pin": "a"}]},
      {"id": "n3", "from": {"cell": "out", "pin": "y"},
       "to": [{"cell": "far", "pin": "a"}]},
    ]
    d.normalize()
    return d

  def test_a_pinned_cell_is_never_moved(self):
    d = self.build()
    before = [c["x"] for c in d.cells if c["id"] == "far"]
    layout.arrange(d, default_registry())
    after = [c["x"] for c in d.cells if c["id"] == "far"]
    self.assertEqual(before, after)

  def test_the_cells_outside_a_selection_are_never_moved(self):
    d = self.build()
    before = {c["id"]: (c["x"], c["y"]) for c in d.cells
              if c["id"] not in ("a", "b", "c")}
    layout.arrange(d, default_registry(), only={"a", "b", "c"})
    after = {c["id"]: (c["x"], c["y"]) for c in d.cells}
    for cell_id, place in before.items():
      self.assertEqual(place, after[cell_id], "%s moved" % cell_id)

  def test_a_selection_layout_takes_the_grid_back_to_tidy_first(self):
    """Two runs of the same selection layout must agree, the way the whole
    drawing's does -- otherwise Ctrl+S after a re-layout shows a difference."""
    d = self.build()
    layout.arrange(d, default_registry(), only={"a", "b", "c"})
    first = [(c["x"], c["y"]) for c in d.cells]
    layout.arrange(d, default_registry(), only={"a", "b", "c"})
    self.assertEqual(first, [(c["x"], c["y"]) for c in d.cells])

  def test_an_unknown_only_name_changes_nothing(self):
    d = self.build()
    before = [(c["x"], c["y"]) for c in d.cells]
    layout.arrange(d, default_registry(), only={"nope"})
    self.assertEqual(before, [(c["x"], c["y"]) for c in d.cells])

  def test_a_selection_layout_leaves_a_valid_drawing(self):
    d = self.build()
    registry = default_registry()
    layout.arrange(d, registry, only={"a", "b", "c"})
    errors = [i for i in d.validate(registry) if i.level == "error"]
    errors += [v for v in drc.check(d, registry) if v.level == "error"]
    self.assertEqual([str(e) for e in errors], [])


class TestDuplicateIds(unittest.TestCase):

  def test_layout_refuses_and_says_which(self):
    d = new_document("dup", 400, 300)
    d.data["cells"] = [cell("a", 100, 100), cell("a", 300, 100)]
    d.normalize()
    with self.assertRaises(ValueError) as caught:
      layout.arrange(d, default_registry())
    self.assertIn("a", str(caught.exception))

  def test_the_drcs_stop_rather_than_guess(self):
    d = new_document("dup", 400, 300)
    d.data["cells"] = [cell("a", 100, 100), cell("a", 300, 100)]
    d.normalize()
    rules = sorted(set(v.rule for v in drc.check(d, default_registry())))
    self.assertEqual(rules, ["duplicate-id"])


if __name__ == "__main__":
  unittest.main()
