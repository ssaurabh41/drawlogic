"""The symbol library.

Every cell type is an entry in symbols.json describing its outline and its
pins, so adding a gate, flop or custom cell means adding one entry -- no code
changes anywhere. Both the Python exporter and the browser editor read the
same file, which is what stops the two renderers drifting apart.

Usage:

    from drawlogic.symbols import default_registry

    registry = default_registry()
    symbol = registry.require("and2")
    symbol.pin_names()                      # ['a', 'b', 'y']
    symbol.pin_position(cell, "y")          # where that pin lands on the sheet
    symbol.matrix_for(cell)                 # transform used to draw the cell

    # Your own cells, without touching the built-ins. A later entry with the
    # same id overrides an earlier one.
    registry = load_registry(["~/my-cells.json", "~/my-cells/"])
"""

import json
import os

from .geometry import cell_matrix

BUILTIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "symbols.json")

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
  """All known symbols, keyed by type id.

  Most symbols are read from symbol files and offered in the palette. A few
  are built at load time instead -- the block standing in for a drawing a cell
  references -- and those are unlisted: real symbols to everything that draws
  or routes, but not something you can pick up and place.
  """

  def __init__(self):
    self._symbols = {}
    self._sources = {}
    self._listed = set()

  def add(self, symbol, source=None, listed=True):
    self._symbols[symbol.id] = symbol
    self._sources[symbol.id] = source
    if listed:
      self._listed.add(symbol.id)
    else:
      self._listed.discard(symbol.id)

  def copy(self):
    """An independent registry holding the same symbols.

    Resolving one drawing's references must not change what another sees, so
    each open drawing works from its own copy of the shared library.
    """
    other = Registry()
    other._symbols = dict(self._symbols)
    other._sources = dict(self._sources)
    other._listed = set(self._listed)
    return other

  def get(self, type_id):
    return self._symbols.get(type_id)

  def for_cell(self, cell):
    """The symbol a placed cell draws with.

    A cell that references another drawing takes its symbol from that
    drawing's ports, so the lookup is by ref rather than by type. Returns None
    when the ref has not been resolved, which reads the same as an unknown
    type and is reported the same way.
    """
    if not isinstance(cell, dict):
      return None
    ref = cell.get("ref")
    if ref:
      return self._symbols.get("sheet:%s" % ref)
    return self._symbols.get(cell.get("type"))

  def require(self, type_id):
    symbol = self._symbols.get(type_id)
    if symbol is None:
      raise SymbolError("unknown cell type %r" % type_id)
    return symbol

  def source_of(self, type_id):
    return self._sources.get(type_id)

  def as_data(self, listed_only=False):
    """The library as plain JSON-able data, keyed by type id.

    What the browser is handed, so the editor draws from the same definitions
    the exporter does -- symbol-directory overrides and resolved sheets alike.
    """
    return {
      type_id: {
        "name": symbol.name,
        "category": symbol.category,
        "size": [symbol.width, symbol.height],
        "pins": symbol.pins,
        "draw": symbol.draw,
        "listed": type_id in self._listed,
      }
      for type_id, symbol in self._symbols.items()
      if not listed_only or type_id in self._listed
    }

  def ids(self, listed_only=True):
    if listed_only:
      return sorted(self._listed)
    return sorted(self._symbols)

  def categories(self):
    groups = {}
    for type_id in self._listed:
      symbol = self._symbols[type_id]
      groups.setdefault(symbol.category, []).append(symbol.id)
    for ids in groups.values():
      ids.sort()
    return groups

  def __contains__(self, type_id):
    return type_id in self._symbols

  def __len__(self):
    return len(self._symbols)


def load_file(registry, path):
  """Load one JSON file of symbol definitions into the registry."""
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


def load_path(registry, path):
  """Load a JSON file, or every *.json in a directory."""
  path = os.path.expanduser(path)
  if os.path.isdir(path):
    for filename in sorted(os.listdir(path)):
      if filename.endswith(".json"):
        load_file(registry, os.path.join(path, filename))
  elif os.path.isfile(path):
    load_file(registry, path)
  else:
    raise SymbolError("no such symbol file or directory: %s" % path)
  return registry


def load_registry(extra=None):
  """Built-in symbols, then any extra files or directories, which override."""
  registry = Registry()
  load_file(registry, BUILTIN_FILE)
  for path in (extra or []):
    load_path(registry, path)
  return registry


_default = None


def default_registry():
  """Process-wide registry, loaded once."""
  global _default
  if _default is None:
    _default = load_registry()
  return _default
