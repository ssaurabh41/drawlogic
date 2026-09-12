"""Hierarchy: a cell that stands for another drawing.

A cell with a `ref` is an instance of the drawing that path names, the way a
module instance stands for a module. Its pins are not written down anywhere --
they are the ports of the child, read off it when the parent is loaded. Add a
port to the child and the parent grows a pin; rename one and the parent's pin
is renamed with it, so the two can never quietly disagree.

The block is drawn to mirror its child: inputs down the west face and outputs
down the east, each in the order its port sits down the child's sheet.

Usage:

    from drawlogic import sheets
    from drawlogic.doc import Document
    from drawlogic.symbols import default_registry

    doc, registry, issues = sheets.open_document("top.dlg")
    symbol = registry.for_cell(doc.cell("u_fifo"))

    sheets.tree(doc)      # [(depth, ref, Document or None), ...]

Nothing in `doc.py` knows about any of this: resolution is the job of whoever
opens the file, and a `ref` that has not been resolved simply has no symbol,
which `validate` reports like any other unknown cell type.
"""

import os

from .doc import Document, DocumentError, Issue
from .symbols import Symbol

# A drawing's ports become its parent's pins.
PORT_DIRECTIONS = {"port_in": "in", "port_out": "out", "port_inout": "inout"}

# Enough room for a name at pin-label size, plus somewhere for the eye to rest.
PIN_PITCH = 32.0
EDGE_MARGIN = 22.0
STUB = 10.0
NAME_WIDTH = 6.4      # rough width of one character at pin-label size
MIN_WIDTH = 150.0
MIN_HEIGHT = 70.0
MAX_DEPTH = 16


def is_sheet(cell):
  """True for a cell that stands for another drawing."""
  return bool(isinstance(cell, dict) and cell.get("ref"))


def sheet_symbol_id(ref):
  """The type id a resolved sheet symbol is registered under.

  Kept out of the file: a drawing stores `type: "sheet"` and the path in
  `ref`, and this is only how the two are tied together in memory.
  """
  return "sheet:%s" % ref


def ports(doc):
  """The ports of a drawing, in the order they run down the sheet.

  A port's label is its name -- that is what is already drawn beside it -- and
  its id is the fallback for a port nobody bothered to label.
  """
  found = []
  for cell in doc.cells:
    direction = PORT_DIRECTIONS.get(cell.get("type"))
    if direction is None:
      continue
    name = (cell.get("label") or "").strip() or cell.get("id")
    found.append({"name": name, "dir": direction,
                  "x": float(cell.get("x", 0)), "y": float(cell.get("y", 0))})
  found.sort(key=lambda port: (port["y"], port["x"]))

  # Two ports of the same name would make an ambiguous pin, so the second one
  # is left out; validate() reports it against the child.
  seen = set()
  unique = []
  for port in found:
    if port["name"] in seen:
      continue
    seen.add(port["name"])
    unique.append(port)
  return unique


def describe(ref, title, port_list):
  """The symbol data for a block standing in for a drawing."""
  left = [p for p in port_list if p["dir"] != "out"]
  right = [p for p in port_list if p["dir"] == "out"]

  rows = max(len(left), len(right), 1)
  height = max(MIN_HEIGHT, EDGE_MARGIN * 2 + (rows - 1) * PIN_PITCH)
  longest_left = max([len(p["name"]) for p in left] or [0])
  longest_right = max([len(p["name"]) for p in right] or [0])
  width = max(MIN_WIDTH,
              (longest_left + longest_right) * NAME_WIDTH + STUB * 4 + 30)

  pins = []
  draw = [
    {"op": "rect", "x": STUB, "y": 0, "w": width - STUB * 2, "h": height,
     "role": "body"},
    # A second outline just inside the first: the conventional mark for a box
    # that is really a drawing of its own.
    {"op": "rect", "x": STUB + 4, "y": 4, "w": width - STUB * 2 - 8,
     "h": height - 8, "role": "decor"},
  ]

  def place(port_group, side):
    for index, port in enumerate(port_group):
      y = EDGE_MARGIN + index * PIN_PITCH
      if len(port_group) == 1:
        y = height / 2.0
      x = 0.0 if side == "left" else width
      inner = STUB if side == "left" else width - STUB
      pins.append({"name": port["name"], "x": x, "y": y,
                   "dir": port["dir"], "width": 0})
      draw.append({"op": "line", "x1": x, "y1": y, "x2": inner, "y2": y,
                   "role": "pin"})
      draw.append({"op": "text", "x": inner + (6 if side == "left" else -6),
                   "y": y + 4, "text": port["name"],
                   "anchor": "start" if side == "left" else "end",
                   "role": "pin_label", "pin": port["name"]})

  place(left, "left")
  place(right, "right")

  return {
    "name": title or ref,
    "category": "sheets",
    "size": [width, height],
    "pins": pins,
    "draw": draw,
  }


def missing(ref, why):
  """A box standing in for a drawing that could not be read.

  Drawn rather than left out: a cell you cannot see is a cell you cannot
  select, and fixing a broken reference means being able to click on it.
  """
  return {
    "name": "%s (%s)" % (ref, why),
    "category": "sheets",
    "size": [MIN_WIDTH, MIN_HEIGHT],
    "pins": [],
    "draw": [
      {"op": "rect", "x": STUB, "y": 0, "w": MIN_WIDTH - STUB * 2,
       "h": MIN_HEIGHT, "role": "ghost"},
      {"op": "text", "x": MIN_WIDTH / 2.0, "y": MIN_HEIGHT / 2.0 - 4,
       "text": os.path.basename(ref), "anchor": "middle", "role": "ghost"},
      {"op": "text", "x": MIN_WIDTH / 2.0, "y": MIN_HEIGHT / 2.0 + 12,
       "text": why, "anchor": "middle", "role": "ghost"},
    ],
  }


def child_path(parent_path, ref):
  """Where a ref points, read relative to the drawing that holds it."""
  base = os.path.dirname(os.path.abspath(parent_path)) if parent_path else os.getcwd()
  return os.path.normpath(os.path.join(base, ref))


def open_document(path, base=None):
  """Open a drawing together with the symbols it needs.

  Returns the drawing, a registry holding the standard library plus a block
  for each drawing this one references, and whatever went wrong resolving
  them.

  The registry is a copy: a ref is a path relative to the drawing that holds
  it, so the same text names different files in different folders, and
  resolving one drawing must never change what another sees.
  """
  from .symbols import default_registry, load_folder

  registry = (base or default_registry()).copy()
  # A drawing's folder may carry symbols of its own, the way it may carry the
  # drawings it references. Picking them up here is what lets the editor's
  # Save as symbol be seen by `drawlogic export` without a flag.
  load_folder(registry, os.path.dirname(os.path.abspath(path)))
  doc = Document.load(path)
  issues = resolve(doc, registry)
  # Only now can a referenced block be given a size: until the reference
  # resolved there was no symbol to take one from.
  doc.normalize(registry)
  return doc, registry, issues


def resolve(doc, registry, seen=None, depth=0):
  """Add a symbol for each drawing `doc` itself references.

  Descendants are walked but not registered: they get their own registry when
  they are opened, for the reason `open_document` gives. Walking them anyway
  is what catches a loop or an unreadable drawing three levels down before it
  becomes a puzzle.

  Returns the problems found: a ref that does not resolve, a child that will
  not parse, or a loop back to a drawing already open above this one.
  """
  issues = []
  if doc.path is None and any(is_sheet(cell) for cell in doc.cells):
    issues.append(Issue("error", "document",
                        "this drawing references others, so it has to be "
                        "loaded from a file for the paths to mean anything"))
    return issues

  seen = set(seen or ())
  if doc.path:
    seen.add(os.path.abspath(doc.path))

  if depth >= MAX_DEPTH:
    issues.append(Issue("error", "document",
                        "hierarchy is more than %d deep" % MAX_DEPTH))
    return issues

  for cell in doc.cells:
    if not is_sheet(cell):
      continue
    ref = cell["ref"]
    where = "cell %s" % cell.get("id")
    target = child_path(doc.path, ref)

    def stand_in(why):
      if depth == 0:
        registry.add(Symbol(sheet_symbol_id(ref), missing(ref, why)),
                     source=target, listed=False)

    if target in seen:
      issues.append(Issue("error", where,
                          "%s refers back to a drawing already open above it"
                          % ref))
      stand_in("loops back")
      continue
    if depth == 0 and registry.get(sheet_symbol_id(ref)) is not None:
      continue
    if not os.path.isfile(target):
      issues.append(Issue("error", where, "no such drawing: %s" % ref))
      stand_in("not found")
      continue

    try:
      child = Document.load(target)
    except (DocumentError, OSError, ValueError) as exc:
      issues.append(Issue("error", where, "cannot read %s: %s" % (ref, exc)))
      stand_in("will not open")
      continue

    if depth == 0:
      registry.add(Symbol(sheet_symbol_id(ref),
                          describe(ref, child.title, ports(child))),
                   source=target, listed=False)
    issues.extend(resolve(child, registry, seen, depth + 1))

  return issues


def tree(doc, registry=None, depth=0, seen=None):
  """The hierarchy under a drawing, as (depth, ref, child or None) rows.

  Depth-first in document order, so it reads the way the drawing does. A ref
  that cannot be read comes back as None rather than stopping the walk.
  """
  rows = []
  seen = set(seen or ())
  if doc.path:
    seen.add(os.path.abspath(doc.path))
  if depth >= MAX_DEPTH:
    return rows

  for cell in doc.cells:
    if not is_sheet(cell):
      continue
    ref = cell["ref"]
    target = child_path(doc.path, ref)
    child = None
    if target not in seen and os.path.isfile(target):
      try:
        child = Document.load(target)
      except (DocumentError, OSError, ValueError):
        child = None
    rows.append((depth, ref, child))
    if child is not None:
      rows.extend(tree(child, registry, depth + 1, seen))
  return rows
