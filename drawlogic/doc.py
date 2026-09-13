"""The .dlg document: load, save, normalise and check.

The file is plain JSON written with a stable key order, so `git diff` on a
schematic reads as "moved U1, added net en" rather than as one unreadable
line. That makes a drawing reviewable in the same way code is.

Usage:

    from drawlogic.doc import Document, new_document

    doc = Document.load("alu_ctrl.dlg")       # checked; raises DocumentError
    doc = new_document("alu_ctrl", 900, 560)

    doc.cells.append({"id": "u1", "type": "and2", "x": 220, "y": 120})
    doc.normalize()                           # fills defaults, e.g. w and h

    for issue in doc.validate():              # [] means the drawing is sound
        print(issue.level, issue.where, issue.message)

    doc.save("alu_ctrl.dlg")

Anything arriving from outside -- a file, or the editor over HTTP -- goes
through Document.load or Document.from_data, which check format and version.
The plain constructor trusts its input and is for code that just built one.

This module also owns bus naming: net_name_width("d[7:0]") is 8.
"""

import json
import re

from . import rules
from . import theme
from .geometry import corners, union_bbox
from .symbols import default_registry

FORMAT = "drawlogic"
VERSION = 2

DOC_KEYS = ["format", "version", "title", "canvas", "cells", "nets", "shapes", "groups"]
CANVAS_KEYS = ["width", "height", "background", "grid", "font", "symbolScale",
               "arrows", "hops"]
GRID_KEYS = ["style", "size", "color"]
FONT_KEYS = ["family", "scale"]
CELL_KEYS = ["id", "type", "x", "y", "w", "h", "rotate", "mirror", "label",
             "pins", "style", "image", "ref"]
NET_KEYS = ["id", "name", "width", "from", "to", "style"]
POINT_KEYS = ["cell", "pin", "x", "y"]
# A load is a point that may also say which way the wire to it should go.
LOAD_KEYS = POINT_KEYS + ["waypoints"]
SHAPE_KEYS = ["id", "kind", "x", "y", "w", "h", "points", "text", "rotate", "style"]
GROUP_KEYS = ["id", "label", "members"]

SHAPE_KINDS = ("rect", "ellipse", "line", "polygon", "polyline", "text")

DEFAULT_CANVAS = {
  # One sheet size for every new drawing, so a folder of them prints and
  # pastes at a consistent scale. Change it per drawing in the properties
  # panel when one needs more room; the number itself lives in rules.py.
  "width": rules.SHEET_W,
  "height": rules.SHEET_H,
  "background": theme.PAPER,
  "grid": {"style": "dots", "size": 10, "color": theme.COLORS["grid"]},
  "font": {"family": "IBM Plex Sans", "scale": 1.0},
  "symbolScale": 1.0,
  "arrows": True,
  "hops": True,
}


# ---- bus names ----
#
# A net named `d[7:0]` carries eight bits; `d[3]` carries one. Width lives
# in the name rather than only in a field, so what you read on the drawing
# and what the checker enforces cannot drift apart.

_RANGE = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_.$]*)\[(?P<msb>\d+):(?P<lsb>\d+)\]$")
_INDEX = re.compile(r"^(?P<base>[A-Za-z_][A-Za-z0-9_.$]*)\[(?P<bit>\d+)\]$")
_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.$]*$")


def parse_net_name(name):
  """Split a net name into (base, msb, lsb).

  Returns None if the name is not a legal net name at all. A plain name and a
  single-bit index both come back with msb == lsb.
  """
  if not name:
    return None

  match = _RANGE.match(name)
  if match:
    return (match.group("base"), int(match.group("msb")), int(match.group("lsb")))

  match = _INDEX.match(name)
  if match:
    bit = int(match.group("bit"))
    return (match.group("base"), bit, bit)

  if _PLAIN.match(name):
    return (name, 0, 0)

  return None


def net_name_width(name):
  """Bit width implied by a net name; 1 for plain or unparseable names."""
  parsed = parse_net_name(name)
  if parsed is None:
    return 1
  _, msb, lsb = parsed
  return abs(msb - lsb) + 1


def is_bus_name(name):
  return net_name_width(name) > 1


def bus_bits(name):
  """Expand `d[7:0]` into ['d[7]', 'd[6]', ... 'd[0]'], msb first."""
  parsed = parse_net_name(name)
  if parsed is None:
    return []
  base, msb, lsb = parsed
  if msb == lsb and "[" not in (name or ""):
    return [base]
  step = -1 if msb >= lsb else 1
  return ["%s[%d]" % (base, i) for i in range(msb, lsb + step, step)]


def loads_of(net):
  """A net's loads, as a list, whatever shape the net is in.

  Version 1 gave a net one load and put it in `to` directly. Version 2 lets a
  net drive several, so `to` is a list -- and every reader goes through here so
  nothing has to care which it is holding.
  """
  target = net.get("to")
  if isinstance(target, dict):
    return [target]
  if isinstance(target, list):
    return [load for load in target if isinstance(load, dict)]
  return []


def upgrade_from_v1(data):
  """Bring a version 1 document up to version 2.

  In version 1 a net had exactly one load, so a signal reaching three places
  was three separate nets that happened to share a driving pin and happened to
  be drawn on top of each other. That illusion is what junction dots were
  hiding. Here those nets are merged into one, which is what they always were.

  Nets are only merged when their names agree -- two names on one pin is
  either a mistake or a deliberate alias, and silently dropping one of them
  would be worse than leaving the drawing as it was.
  """
  data = dict(data)
  merged = []
  by_driver = {}

  for net in data.get("nets") or []:
    net = dict(net)
    source = net.get("from")
    waypoints = net.pop("waypoints", None)

    if isinstance(net.get("to"), list):
      # Already in the new shape. Upgrading has to be safe to repeat, or a
      # caller being careful destroys the document it was protecting.
      net["to"] = [dict(load) for load in net["to"] if isinstance(load, dict)]
    else:
      load = dict(net["to"]) if isinstance(net.get("to"), dict) else {}
      if waypoints:
        load["waypoints"] = waypoints
      net["to"] = [load] if load else []

    key = None
    if isinstance(source, dict) and "cell" in source:
      key = (source["cell"], source.get("pin"))

    host = by_driver.get(key) if key else None
    if host is not None and _names_agree(host.get("name"), net.get("name")):
      host["to"].extend(net["to"])
      if host.get("name") is None:
        host["name"] = net.get("name")
        host["width"] = net.get("width", host.get("width"))
      continue

    merged.append(net)
    if key is not None and host is None:
      by_driver[key] = net

  data["nets"] = merged
  data["version"] = 2
  return data


def _names_agree(one, other):
  return one is None or other is None or one == other


class DocumentError(Exception):
  pass


def _object(data, key, where=None):
  """The object at `key`, defaulting to a new one, or a DocumentError.

  setdefault alone is not enough: it leaves a key that is present but holds
  the wrong type exactly as it found it, and the failure then surfaces
  somewhere far less useful.
  """
  value = data.get(key)
  if value is None and key not in data:
    value = {}
    data[key] = value
  if not isinstance(value, dict):
    raise DocumentError("%s must be an object, not %s"
                        % (where or key, type(value).__name__))
  return value


def _list_of_objects(data, key):
  """The list at `key`, defaulting to a new one, or a DocumentError."""
  value = data.get(key)
  if value is None and key not in data:
    value = []
    data[key] = value
  if not isinstance(value, list):
    raise DocumentError("%s must be a list, not %s"
                        % (key, type(value).__name__))
  for index, item in enumerate(value):
    if not isinstance(item, dict):
      raise DocumentError("%s[%d] must be an object, not %s"
                          % (key, index, type(item).__name__))
  return value


class Issue(object):
  """One problem found by validate(); level is 'error' or 'warning'."""

  __slots__ = ("level", "where", "message")

  def __init__(self, level, where, message):
    self.level = level
    self.where = where
    self.message = message

  def __str__(self):
    return "%s: %s: %s" % (self.level, self.where, self.message)

  def __repr__(self):
    return "Issue(%r, %r, %r)" % (self.level, self.where, self.message)


def _ordered(source, keys):
  """Re-emit a dict with known keys first in a fixed order, extras after."""
  out = {}
  for key in keys:
    if key in source:
      out[key] = source[key]
  for key in sorted(source):
    if key not in out:
      out[key] = source[key]
  return out


def new_document(title="untitled", width=None, height=None):
  canvas = json.loads(json.dumps(DEFAULT_CANVAS))
  if width is not None:
    canvas["width"] = width
  if height is not None:
    canvas["height"] = height
  return Document({
    "format": FORMAT,
    "version": VERSION,
    "title": title,
    "canvas": canvas,
    "cells": [],
    "nets": [],
    "shapes": [],
    "groups": [],
  })


class Document(object):
  """A schematic. Thin wrapper over the JSON structure, not a hiding layer."""

  def __init__(self, data=None, path=None):
    self.data = data if data is not None else {}
    self.path = path
    self.normalize()

  # ---- loading and saving ----

  @classmethod
  def from_data(cls, data, path=None):
    """Build from an already-parsed structure, checking it is really ours.

    The plain constructor trusts its input, which is right for code that just
    built a document. Anything arriving from outside -- a file, or the editor
    over HTTP -- comes through here instead, so a malformed document is
    refused rather than written back out as an unopenable file.
    """
    if not isinstance(data, dict):
      raise DocumentError("a document must be a JSON object")

    fmt = data.get("format")
    if fmt != FORMAT:
      raise DocumentError("not a drawlogic document (format is %r)" % fmt)
    version = data.get("version")
    if version == 1:
      data = upgrade_from_v1(data)
      version = data.get("version")
    if version != VERSION:
      raise DocumentError(
        "document version %r is not supported by this build (expected %d)"
        % (version, VERSION))
    return cls(data, path=path)

  @classmethod
  def loads(cls, text, path=None):
    try:
      data = json.loads(text)
    except ValueError as exc:
      raise DocumentError("not valid JSON: %s" % exc)
    return cls.from_data(data, path=path)

  @classmethod
  def load(cls, path):
    with open(path, "r") as handle:
      return cls.loads(handle.read(), path=path)

  def dumps(self):
    return json.dumps(self.ordered(), indent=2, ensure_ascii=True) + "\n"

  def save(self, path=None):
    target = path or self.path
    if not target:
      raise DocumentError("no path to save to")
    with open(target, "w") as handle:
      handle.write(self.dumps())
    self.path = target
    return target

  def ordered(self):
    """The document with every dict emitted in a stable key order."""
    out = _ordered(self.data, DOC_KEYS)
    out["canvas"] = _ordered(self.canvas, CANVAS_KEYS)
    if isinstance(out["canvas"].get("grid"), dict):
      out["canvas"]["grid"] = _ordered(out["canvas"]["grid"], GRID_KEYS)
    if isinstance(out["canvas"].get("font"), dict):
      out["canvas"]["font"] = _ordered(out["canvas"]["font"], FONT_KEYS)
    out["cells"] = [_ordered(c, CELL_KEYS) for c in self.cells]
    nets = []
    for net in self.nets:
      item = _ordered(net, NET_KEYS)
      if isinstance(item.get("from"), dict):
        item["from"] = _ordered(item["from"], POINT_KEYS)
      item["to"] = [_ordered(load, LOAD_KEYS) for load in loads_of(net)]
      nets.append(item)
    out["nets"] = nets
    out["shapes"] = [_ordered(s, SHAPE_KEYS) for s in self.shapes]
    out["groups"] = [_ordered(g, GROUP_KEYS) for g in self.groups]
    return out

  # ---- accessors ----

  @property
  def title(self):
    return self.data.get("title", "untitled")

  @property
  def canvas(self):
    return self.data.setdefault("canvas", {})

  @property
  def cells(self):
    return self.data.setdefault("cells", [])

  @property
  def nets(self):
    return self.data.setdefault("nets", [])

  @property
  def shapes(self):
    return self.data.setdefault("shapes", [])

  @property
  def groups(self):
    return self.data.setdefault("groups", [])

  @property
  def symbol_scale(self):
    """One multiplier for every cell's size, leaving each cell centred."""
    try:
      scale = float(self.canvas.get("symbolScale", 1.0))
    except (TypeError, ValueError):
      return 1.0
    return scale if scale > 0 else 1.0

  @property
  def font_scale(self):
    font = self.canvas.get("font") or {}
    try:
      scale = float(font.get("scale", 1.0))
    except (TypeError, ValueError):
      return 1.0
    return scale if scale > 0 else 1.0

  def cell(self, cell_id):
    for cell in self.cells:
      if cell.get("id") == cell_id:
        return cell
    return None

  # ---- normalisation ----

  def normalize(self, registry=None):
    """Fill in defaults so the rest of the code never guards for missing keys.

    Every container is type-checked on the way in. `setdefault` only fills a
    key that is absent, so a key present but holding the wrong type -- a null
    canvas, a list where an object belongs -- used to sail through here and
    fail later as an AttributeError deep in the call stack. Over HTTP that
    killed the connection without a status code, and on the command line it
    printed a traceback instead of saying which part of the file was wrong.
    """
    registry = registry or default_registry()
    data = self.data
    if not isinstance(data, dict):
      raise DocumentError("a document must be a JSON object")

    data.setdefault("format", FORMAT)
    data.setdefault("version", VERSION)
    data.setdefault("title", "untitled")

    canvas = _object(data, "canvas")
    for key in ("width", "height", "background", "symbolScale", "arrows", "hops"):
      canvas.setdefault(key, DEFAULT_CANVAS[key])
    grid = _object(canvas, "grid", "canvas.grid")
    for key, value in DEFAULT_CANVAS["grid"].items():
      grid.setdefault(key, value)
    font = _object(canvas, "font", "canvas.font")
    for key, value in DEFAULT_CANVAS["font"].items():
      font.setdefault(key, value)

    for cell in _list_of_objects(data, "cells"):
      symbol = registry.for_cell(cell)
      if symbol is not None:
        cell.setdefault("w", symbol.width)
        cell.setdefault("h", symbol.height)
      cell.setdefault("x", 0)
      cell.setdefault("y", 0)
      cell.setdefault("rotate", 0)
      cell.setdefault("mirror", False)
      cell.setdefault("style", {})

    for net in _list_of_objects(data, "nets"):
      name = net.get("name")
      if name and "width" not in net:
        net["width"] = net_name_width(name)
      net.setdefault("width", 1)
      net.setdefault("style", {})
      loads = loads_of(net)
      for load in loads:
        load.setdefault("waypoints", [])
      net["to"] = loads

    for shape in _list_of_objects(data, "shapes"):
      shape.setdefault("style", {})
      shape.setdefault("rotate", 0)

    _list_of_objects(data, "groups")
    return self

  # ---- geometry ----

  def content_bbox(self, registry=None):
    """Bounding box of everything drawn, or None for an empty document."""
    registry = registry or default_registry()
    box = None
    scale = self.symbol_scale

    for cell in self.cells:
      symbol = registry.for_cell(cell)
      if symbol is None:
        continue
      matrix = symbol.matrix_for(cell, scale)
      points = [matrix.apply(px, py) for px, py in
                corners(0, 0, symbol.width, symbol.height)]
      xs = [p[0] for p in points]
      ys = [p[1] for p in points]
      box = union_bbox(box, (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))

    # Ask the router where the wires actually go, rather than guessing from
    # the document. This used to read net["waypoints"] and an x/y off each
    # endpoint -- version 1's shape. In version 2 a net has a list of loads,
    # each carrying its own waypoints, and endpoints name a cell and a pin
    # rather than a coordinate, so none of those keys exist any more and
    # every wire contributed nothing at all. A cropped export then cut off
    # whatever the wires did between their two ends.
    #
    # routing imports doc, so this import is local rather than at the top.
    from . import routing
    for _net_id, start, end in routing.segments_of(
        routing.route_all(self, registry)):
      for point in (start, end):
        box = union_bbox(box, (point[0], point[1], 0, 0))

    for shape in self.shapes:
      if "x" in shape and "y" in shape:
        box = union_bbox(box, (shape["x"], shape["y"],
                               shape.get("w", 0), shape.get("h", 0)))
      for point in shape.get("points", []):
        box = union_bbox(box, (point[0], point[1], 0, 0))

    return box

  # ---- checking ----

  def validate(self, registry=None):
    """Return a list of Issue. An empty list means the document is sound."""
    registry = registry or default_registry()
    issues = []

    grid_style = (self.canvas.get("grid") or {}).get("style")
    if grid_style not in theme.GRID_STYLES:
      issues.append(Issue("error", "canvas.grid",
                          "unknown grid style %r (expected one of %s)"
                          % (grid_style, ", ".join(theme.GRID_STYLES))))

    for name, items in (("cell", self.cells), ("net", self.nets),
                        ("shape", self.shapes), ("group", self.groups)):
      seen = set()
      for item in items:
        item_id = item.get("id")
        if not item_id:
          issues.append(Issue("error", name, "an entry has no id"))
        elif item_id in seen:
          issues.append(Issue("error", "%s %s" % (name, item_id), "duplicate id"))
        else:
          seen.add(item_id)

    for cell in self.cells:
      where = "cell %s" % cell.get("id")
      symbol = registry.for_cell(cell)
      if symbol is None:
        if cell.get("ref"):
          # Resolving a ref means opening the drawing it names, which is the
          # job of whoever opened this one -- see sheets.resolve.
          issues.append(Issue("error", where,
                              "references %r, which has not been resolved"
                              % cell.get("ref")))
        else:
          issues.append(Issue("error", where,
                              "unknown cell type %r" % cell.get("type")))
        continue
      if cell.get("w", 0) <= 0 or cell.get("h", 0) <= 0:
        issues.append(Issue("error", where, "size must be positive"))
      if cell.get("rotate", 0) % 90 != 0:
        issues.append(Issue("warning", where,
                            "rotation %r is not a multiple of 90"
                            % cell.get("rotate")))
      for pin_name in (cell.get("pins") or {}):
        if symbol.pin(pin_name) is None:
          issues.append(Issue("error", where,
                              "pin label names %r, which %s has no such pin"
                              % (pin_name, symbol.id)))

    # Two ports of the same name make an ambiguous pin the moment another
    # drawing instantiates this one, so it is worth saying early.
    port_labels = {}
    for cell in self.cells:
      if not str(cell.get("type", "")).startswith("port_"):
        continue
      name = (cell.get("label") or "").strip()
      if name:
        port_labels.setdefault(name, []).append(cell.get("id"))
    for name, owners in sorted(port_labels.items()):
      if len(owners) > 1:
        issues.append(Issue("warning", "ports",
                            "%d ports are named %r (%s); a drawing that "
                            "instantiates this one can only see the first"
                            % (len(owners), name, ", ".join(sorted(owners)))))

    for shape in self.shapes:
      kind = shape.get("kind")
      if kind not in SHAPE_KINDS:
        issues.append(Issue("error", "shape %s" % shape.get("id"),
                            "unknown shape kind %r" % kind))

    connected = set()
    for net in self.nets:
      where = "net %s" % (net.get("name") or net.get("id"))
      name = net.get("name")
      if name and parse_net_name(name) is None:
        issues.append(Issue("warning", where, "net name %r is not a legal name" % name))
      if name and net_name_width(name) != net.get("width", 1):
        issues.append(Issue("error", where,
                            "name implies width %d but width is %d"
                            % (net_name_width(name), net.get("width", 1))))

      endpoint_widths = []
      ends = [("from", net.get("from"))]
      loads = loads_of(net)
      if not loads:
        issues.append(Issue("error", where, "the net drives nothing"))
      for index, load in enumerate(loads):
        ends.append(("load %d" % (index + 1) if len(loads) > 1 else "to", load))

      for end, endpoint in ends:
        if not isinstance(endpoint, dict):
          issues.append(Issue("error", where, "%s endpoint is missing" % end))
          continue
        if "cell" in endpoint:
          cell = self.cell(endpoint["cell"])
          if cell is None:
            issues.append(Issue("error", where,
                                "%s endpoint refers to missing cell %r"
                                % (end, endpoint["cell"])))
            continue
          symbol = registry.for_cell(cell)
          if symbol is None:
            continue
          pin = symbol.pin(endpoint.get("pin"))
          if pin is None:
            issues.append(Issue("error", where,
                                "%s endpoint refers to pin %r, which %s has no such pin (has: %s)"
                                % (end, endpoint.get("pin"), cell.get("type"),
                                   ", ".join(symbol.pin_names()))))
            continue
          endpoint_widths.append(pin.get("width", 1))
          connected.add((endpoint["cell"], endpoint.get("pin")))
        elif not ("x" in endpoint and "y" in endpoint):
          issues.append(Issue("error", where,
                              "%s endpoint needs either cell+pin or x+y" % end))

      net_width = net.get("width", 1)
      for pin_width in endpoint_widths:
        # Width 0 means the pin takes a bus of any width, which is what a
        # generic block port or a bus ripper declares.
        if pin_width != 0 and pin_width != net_width:
          issues.append(Issue("error", where,
                              "connects a %d-bit pin to a %d-bit net"
                              % (pin_width, net_width)))

    # A load pin driven by two different nets is a short. That could not be
    # said before: every fan-out looked like several nets sharing a pin, so
    # there was nothing to tell a rail apart from a short.
    driven = {}
    for net in self.nets:
      for load in loads_of(net):
        if "cell" not in load:
          continue
        key = (load["cell"], load.get("pin"))
        driven.setdefault(key, []).append(net.get("name") or net.get("id"))
    for (cell_id, pin_name), owners in sorted(driven.items()):
      if len(owners) > 1:
        issues.append(Issue("error", "cell %s" % cell_id,
                            "pin %r is driven by %d nets (%s)"
                            % (pin_name, len(owners), ", ".join(owners))))

    for cell in self.cells:
      symbol = registry.for_cell(cell)
      if symbol is None:
        continue
      for pin in symbol.pins:
        if (cell.get("id"), pin["name"]) not in connected:
          issues.append(Issue("warning", "cell %s" % cell.get("id"),
                              "pin %r is unconnected" % pin["name"]))

    # Shapes group exactly like cells do -- the editor's groupItems() takes
    # whatever is selected, and a box drawn round a gate is the ordinary
    # reason to group anything. Checking only cell ids called every grouped
    # annotation a missing member and failed a file the editor had just
    # written.
    known_members = set(c.get("id") for c in self.cells)
    known_members.update(s.get("id") for s in self.shapes)
    grouped = {}
    for group in self.groups:
      where = "group %s" % group.get("id")
      for member in group.get("members", []):
        if member not in known_members:
          issues.append(Issue("error", where, "member %r does not exist" % member))
        elif member in grouped:
          issues.append(Issue("error", where,
                              "member %r is already in group %s"
                              % (member, grouped[member])))
        else:
          grouped[member] = group.get("id")

    return issues


def load(path):
  return Document.load(path)
