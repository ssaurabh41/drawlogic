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

from . import theme
from .geometry import corners, union_bbox
from .symbols import default_registry

FORMAT = "drawlogic"
VERSION = 1

DOC_KEYS = ["format", "version", "title", "canvas", "cells", "nets", "shapes", "groups"]
CANVAS_KEYS = ["width", "height", "background", "grid", "font", "symbolScale",
               "arrows", "hops"]
GRID_KEYS = ["style", "size", "color"]
FONT_KEYS = ["family", "scale"]
CELL_KEYS = ["id", "type", "x", "y", "w", "h", "rotate", "mirror", "label",
             "style", "image", "ref"]
NET_KEYS = ["id", "name", "width", "from", "to", "waypoints", "style"]
POINT_KEYS = ["cell", "pin", "x", "y"]
SHAPE_KEYS = ["id", "kind", "x", "y", "w", "h", "points", "text", "rotate", "style"]
GROUP_KEYS = ["id", "label", "members"]

SHAPE_KINDS = ("rect", "ellipse", "line", "polygon", "polyline", "text")

DEFAULT_CANVAS = {
  "width": 1600,
  "height": 1000,
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


class DocumentError(Exception):
  pass


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
      for end in ("from", "to"):
        if isinstance(item.get(end), dict):
          item[end] = _ordered(item[end], POINT_KEYS)
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
    """Fill in defaults so the rest of the code never guards for missing keys."""
    registry = registry or default_registry()
    data = self.data

    data.setdefault("format", FORMAT)
    data.setdefault("version", VERSION)
    data.setdefault("title", "untitled")

    canvas = data.setdefault("canvas", {})
    for key in ("width", "height", "background", "symbolScale", "arrows", "hops"):
      canvas.setdefault(key, DEFAULT_CANVAS[key])
    grid = canvas.setdefault("grid", {})
    for key, value in DEFAULT_CANVAS["grid"].items():
      grid.setdefault(key, value)
    font = canvas.setdefault("font", {})
    for key, value in DEFAULT_CANVAS["font"].items():
      font.setdefault(key, value)

    for cell in data.setdefault("cells", []):
      symbol = registry.get(cell.get("type"))
      if symbol is not None:
        cell.setdefault("w", symbol.width)
        cell.setdefault("h", symbol.height)
      cell.setdefault("x", 0)
      cell.setdefault("y", 0)
      cell.setdefault("rotate", 0)
      cell.setdefault("mirror", False)
      cell.setdefault("style", {})

    for net in data.setdefault("nets", []):
      name = net.get("name")
      if name and "width" not in net:
        net["width"] = net_name_width(name)
      net.setdefault("width", 1)
      net.setdefault("waypoints", [])
      net.setdefault("style", {})

    for shape in data.setdefault("shapes", []):
      shape.setdefault("style", {})
      shape.setdefault("rotate", 0)

    data.setdefault("groups", [])
    return self

  # ---- geometry ----

  def content_bbox(self, registry=None):
    """Bounding box of everything drawn, or None for an empty document."""
    registry = registry or default_registry()
    box = None
    scale = self.symbol_scale

    for cell in self.cells:
      symbol = registry.get(cell.get("type"))
      if symbol is None:
        continue
      matrix = symbol.matrix_for(cell, scale)
      points = [matrix.apply(px, py) for px, py in
                corners(0, 0, symbol.width, symbol.height)]
      xs = [p[0] for p in points]
      ys = [p[1] for p in points]
      box = union_bbox(box, (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))

    for net in self.nets:
      for point in net.get("waypoints", []):
        box = union_bbox(box, (point[0], point[1], 0, 0))
      for end in ("from", "to"):
        endpoint = net.get(end) or {}
        if "x" in endpoint and "y" in endpoint:
          box = union_bbox(box, (endpoint["x"], endpoint["y"], 0, 0))

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
      symbol = registry.get(cell.get("type"))
      if symbol is None:
        issues.append(Issue("error", where, "unknown cell type %r" % cell.get("type")))
        continue
      if cell.get("w", 0) <= 0 or cell.get("h", 0) <= 0:
        issues.append(Issue("error", where, "size must be positive"))
      if cell.get("rotate", 0) % 90 != 0:
        issues.append(Issue("warning", where,
                            "rotation %r is not a multiple of 90"
                            % cell.get("rotate")))

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
      for end in ("from", "to"):
        endpoint = net.get(end)
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
          symbol = registry.get(cell.get("type"))
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

    for cell in self.cells:
      symbol = registry.get(cell.get("type"))
      if symbol is None:
        continue
      for pin in symbol.pins:
        if (cell.get("id"), pin["name"]) not in connected:
          issues.append(Issue("warning", "cell %s" % cell.get("id"),
                              "pin %r is unconnected" % pin["name"]))

    known_cells = set(c.get("id") for c in self.cells)
    grouped = {}
    for group in self.groups:
      where = "group %s" % group.get("id")
      for member in group.get("members", []):
        if member not in known_cells:
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
