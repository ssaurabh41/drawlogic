"""The symbol library.

Every cell type is a JSON entry describing its outline and its pins, so
adding a gate, flop or custom cell means dropping a file in symbols/ -- no
code changes anywhere. Both the Python exporter and the browser editor read
these same files, which is what stops the two renderers drifting apart.
"""

import json
import os

from .geometry import cell_matrix

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbols")

VALID_DIRECTIONS = ("in", "out", "inout")
VALID_OPS = ("path", "line", "rect", "circle", "polygon", "text")


class SymbolError(Exception):
  pass


class Symbol(object):
  """One cell type: a natural-size box, a pin list and a list of draw ops."""

  __slots__ = ("id", "name", "category", "width", "height", "pins", "draw")

  def __init__(self, symbol_id, data):
    self.id = symbol_id
    self.name = data.get("name", symbol_id)
    self.category = data.get("category", "misc")

    size = data.get("size")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
      raise SymbolError("symbol %r needs a size of [width, height]" % symbol_id)
    self.width = float(size[0])
    self.height = float(size[1])
    if self.width <= 0 or self.height <= 0:
      raise SymbolError("symbol %r has a non-positive size" % symbol_id)

    self.pins = []
    seen = set()
    for pin in data.get("pins", []):
      name = pin.get("name")
      if not name:
        raise SymbolError("symbol %r has a pin with no name" % symbol_id)
      if name in seen:
        raise SymbolError("symbol %r has duplicate pin %r" % (symbol_id, name))
      seen.add(name)
      direction = pin.get("dir", "inout")
      if direction not in VALID_DIRECTIONS:
        raise SymbolError(
          "symbol %r pin %r has unknown direction %r" % (symbol_id, name, direction))
      self.pins.append({
        "name": name,
        "x": float(pin.get("x", 0)),
        "y": float(pin.get("y", 0)),
        "dir": direction,
        "width": int(pin.get("width", 1)),
      })

    self.draw = []
    for op in data.get("draw", []):
      kind = op.get("op")
      if kind not in VALID_OPS:
        raise SymbolError("symbol %r has unknown draw op %r" % (symbol_id, kind))
      self.draw.append(op)

  def pin(self, name):
    for pin in self.pins:
      if pin["name"] == name:
        return pin
    return None

  def pin_names(self):
    return [p["name"] for p in self.pins]

  def matrix_for(self, cell, scale=1.0):
    """Transform placing this symbol per a cell's position, size and rotation.

    `scale` is the document-wide symbol scale. It grows a cell about its own
    centre, so turning every gate up does not drag the layout sideways.
    """
    x = cell.get("x", 0)
    y = cell.get("y", 0)
    w = cell.get("w", self.width)
    h = cell.get("h", self.height)
    if scale != 1.0:
      cx = x + w / 2.0
      cy = y + h / 2.0
      w *= scale
      h *= scale
      x = cx - w / 2.0
      y = cy - h / 2.0
    return cell_matrix(x, y, w, h, self.width, self.height,
                       cell.get("rotate", 0), bool(cell.get("mirror", False)))

  def pin_position(self, cell, pin_name, scale=1.0):
    """Where a pin lands in sheet coordinates, or None if there is no such pin."""
    pin = self.pin(pin_name)
    if pin is None:
      return None
    return self.matrix_for(cell, scale).apply(pin["x"], pin["y"])

  def __repr__(self):
    return "<Symbol %s %gx%g %d pins>" % (
      self.id, self.width, self.height, len(self.pins))


class Registry(object):
  """All known symbols, keyed by type id."""

  def __init__(self):
    self._symbols = {}
    self._sources = {}

  def add(self, symbol, source=None):
    self._symbols[symbol.id] = symbol
    self._sources[symbol.id] = source

  def get(self, type_id):
    return self._symbols.get(type_id)

  def require(self, type_id):
    symbol = self._symbols.get(type_id)
    if symbol is None:
      raise SymbolError("unknown cell type %r" % type_id)
    return symbol

  def source_of(self, type_id):
    return self._sources.get(type_id)

  def ids(self):
    return sorted(self._symbols)

  def categories(self):
    groups = {}
    for symbol in self._symbols.values():
      groups.setdefault(symbol.category, []).append(symbol.id)
    for ids in groups.values():
      ids.sort()
    return groups

  def __contains__(self, type_id):
    return type_id in self._symbols

  def __len__(self):
    return len(self._symbols)


def load_dir(registry, directory):
  """Load every *.json in a directory into the registry."""
  if not os.path.isdir(directory):
    return registry
  for filename in sorted(os.listdir(directory)):
    if not filename.endswith(".json"):
      continue
    path = os.path.join(directory, filename)
    with open(path, "r") as handle:
      try:
        data = json.load(handle)
      except ValueError as exc:
        raise SymbolError("%s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict):
      raise SymbolError("%s must hold an object of symbol definitions" % path)
    for symbol_id, definition in data.items():
      registry.add(Symbol(symbol_id, definition), source=path)
  return registry


def load_registry(extra_dirs=None):
  """Built-in symbols, then any extra directories, which may override them."""
  registry = Registry()
  load_dir(registry, BUILTIN_DIR)
  for directory in (extra_dirs or []):
    load_dir(registry, directory)
  return registry


_default = None


def default_registry():
  """Process-wide registry, loaded once."""
  global _default
  if _default is None:
    _default = load_registry()
  return _default
