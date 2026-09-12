"""Making a symbol out of a drawing.

A symbol is a box, a pin list and some draw ops -- which is very nearly what a
drawing already is. So rather than a separate editor with its own tools, a
custom cell is authored as an ordinary drawing: the shapes are the artwork and
the ports say where the pins go. Draw a box and an arrow with the shape tools,
drop an input port on its left edge and an output port on its right, and this
turns the result into something the palette can offer.

That is the same rule hierarchy uses -- a drawing's ports are the pins of the
block that stands for it -- applied one level down.

Two things the conversion decides, both worth knowing:

**The artwork sets the body.** The box is the bounding box of the shapes
alone, not of the ports. A port sits beside the thing it connects to, so
counting it would leave every pin sunk inside the outline instead of on it.

**Each pin snaps to the nearest edge.** A pin on an edge faces outwards, which
is what the router reads to decide which way a wire leaves. A pin left in the
middle of the body has no side to face, so a port dropped roughly in the right
place is put exactly on the edge it was nearest.

Usage:

    from drawlogic import authoring

    data = authoring.symbol_from(doc, "my_block", name="My block")
    authoring.add_to_file("symbols.json", "my_block", data)
"""

import json
import os

from .doc import loads_of
from .symbols import Symbol, SymbolError

PORT_DIRECTIONS = {"port_in": "in", "port_out": "out", "port_inout": "inout"}
MIN_SIZE = 20.0


class AuthoringError(Exception):
  """The drawing cannot be made into a symbol, with the reason why."""


def symbol_from(doc, symbol_id, name=None, category="custom"):
  """Build symbol data from a drawing of shapes and ports.

  Raises AuthoringError when the drawing has nothing to make a symbol out of,
  which is a message worth showing rather than an empty symbol worth placing.
  """
  if not str(symbol_id or "").strip():
    raise AuthoringError("a symbol needs an id")

  shapes = list(doc.shapes)
  extents = [_extent(shape) for shape in shapes]
  measurable = [box for box in extents if box is not None]
  if not measurable:
    raise AuthoringError(
      "draw the outline first: a symbol is made from the shapes on the sheet")

  # Text rides along with the artwork but does not decide how big it is: there
  # is no way to measure a string here, and a caption should not inflate the
  # body it is written on.
  box = _bounds(measurable)
  width = max(box[2] - box[0], MIN_SIZE)
  height = max(box[3] - box[1], MIN_SIZE)

  pins = _pins(doc, box, width, height)
  if not pins:
    raise AuthoringError(
      "add at least one port: the ports are what become the symbol's pins")

  draw = []
  for shape in shapes:
    op = _op(shape, box, {pin["name"] for pin in pins})
    if op is not None:
      draw.append(op)

  return {
    "name": name or symbol_id,
    "category": category or "custom",
    "size": [width, height],
    "pins": pins,
    "draw": draw,
  }


# ---- geometry ----

def _extent(shape):
  """A shape's bounding box, or None for one that covers no ground."""
  kind = shape.get("kind")
  if kind in ("rect", "ellipse"):
    x = float(shape.get("x", 0))
    y = float(shape.get("y", 0))
    return (x, y, x + float(shape.get("w", 0)), y + float(shape.get("h", 0)))
  if kind in ("line", "polygon", "polyline"):
    points = shape.get("points") or []
    if len(points) < 2:
      return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))
  if kind == "text":
    # Text has no measurable extent here, so it rides along with the artwork
    # rather than deciding how big the artwork is.
    return None
  return None


def _bounds(boxes):
  return (min(b[0] for b in boxes), min(b[1] for b in boxes),
          max(b[2] for b in boxes), max(b[3] for b in boxes))


def _pins(doc, box, width, height):
  """The ports of the drawing, as pins on the body's edges."""
  found = []
  seen = set()
  for cell in doc.cells:
    direction = PORT_DIRECTIONS.get(cell.get("type"))
    if direction is None:
      continue
    name = (cell.get("label") or "").strip() or cell.get("id")
    if name in seen:
      continue
    seen.add(name)

    # The port's own centre, which is near enough: a port is 20 by 10 and the
    # edge it is aimed at is what matters, not which end of it.
    x = float(cell.get("x", 0)) + float(cell.get("w", 20)) / 2.0 - box[0]
    y = float(cell.get("y", 0)) + float(cell.get("h", 10)) / 2.0 - box[1]
    found.append(dict(_snap(x, y, width, height),
                      name=name, dir=direction, width=0))

  found.sort(key=lambda pin: (pin["x"] > 0, pin["y"], pin["x"]))
  return found


def _snap(x, y, width, height):
  """Put a pin on whichever edge of the body it belongs to.

  A pin has to be on an edge to have a side to face, and facing is what the
  router reads to decide which way a wire leaves a cell.

  Which edge is decided by how far outside the body the port was dropped,
  not by which edge is nearest: a port placed to the left of a tall block sits
  closer to the top of it than to the left side, and still means the left.
  Only a port inside the body falls back to the nearest edge.
  """
  outside = (
    (-x, {"x": 0.0, "y": _clamp(y, height)}),
    (x - width, {"x": width, "y": _clamp(y, height)}),
    (-y, {"x": _clamp(x, width), "y": 0.0}),
    (y - height, {"x": _clamp(x, width), "y": height}),
  )
  furthest = max(outside, key=lambda pair: pair[0])
  if furthest[0] > 0:
    return furthest[1]

  nearest = (
    (x, {"x": 0.0, "y": _clamp(y, height)}),
    (width - x, {"x": width, "y": _clamp(y, height)}),
    (y, {"x": _clamp(x, width), "y": 0.0}),
    (height - y, {"x": _clamp(x, width), "y": height}),
  )
  return min(nearest, key=lambda pair: pair[0])[1]


def _clamp(value, limit):
  return max(0.0, min(float(value), float(limit)))


# ---- artwork ----

def _op(shape, box, pin_names):
  """One shape as a draw op, moved into the symbol's own coordinates."""
  style = shape.get("style") or {}
  kind = shape.get("kind")
  dx = -box[0]
  dy = -box[1]
  # A symbol's parts are painted by role rather than by colour, so the cell
  # can be recoloured and the theme can be changed. A filled shape is the
  # body; an unfilled one is a mark on it.
  filled = style.get("fill") not in (None, "", "none")
  role = "body" if filled else "decor"

  if kind == "rect":
    return {"op": "rect", "x": float(shape["x"]) + dx, "y": float(shape["y"]) + dy,
            "w": float(shape.get("w", 0)), "h": float(shape.get("h", 0)),
            "role": role}

  if kind == "ellipse":
    return {"op": "ellipse",
            "cx": float(shape["x"]) + float(shape.get("w", 0)) / 2.0 + dx,
            "cy": float(shape["y"]) + float(shape.get("h", 0)) / 2.0 + dy,
            "rx": float(shape.get("w", 0)) / 2.0,
            "ry": float(shape.get("h", 0)) / 2.0,
            "role": role}

  if kind == "line":
    points = shape.get("points") or []
    if len(points) < 2:
      return None
    return {"op": "line",
            "x1": float(points[0][0]) + dx, "y1": float(points[0][1]) + dy,
            "x2": float(points[-1][0]) + dx, "y2": float(points[-1][1]) + dy,
            "role": "decor"}

  if kind == "polygon":
    points = shape.get("points") or []
    if len(points) < 3:
      return None
    return {"op": "polygon",
            "points": [[float(p[0]) + dx, float(p[1]) + dy] for p in points],
            "role": role}

  if kind == "polyline":
    points = shape.get("points") or []
    if len(points) < 2:
      return None
    # There is no open-polygon op, and a path is what one is.
    steps = ["M%g %g" % (float(points[0][0]) + dx, float(points[0][1]) + dy)]
    steps.extend("L%g %g" % (float(p[0]) + dx, float(p[1]) + dy)
                 for p in points[1:])
    return {"op": "path", "d": " ".join(steps), "role": "decor"}

  if kind == "text":
    text = shape.get("text") or ""
    op = {"op": "text", "x": float(shape.get("x", 0)) + dx,
          "y": float(shape.get("y", 0)) + dy, "text": text,
          "anchor": style.get("anchor", "start"), "role": "pin_label"}
    # Text that names a pin is that pin's label, so renaming the pin on a
    # placed cell renames what is drawn.
    if text in pin_names:
      op["pin"] = text
    return op

  return None


# ---- the file the palette reads ----

def add_to_file(path, symbol_id, data):
  """Add or replace one symbol in a symbol file, creating it if need be.

  Checked by building it before it is written: a file the registry cannot load
  would take the whole palette down with it.
  """
  Symbol(symbol_id, data)      # raises SymbolError if the shape is wrong

  library = {}
  if os.path.isfile(path):
    try:
      with open(path) as handle:
        library = json.load(handle)
    except ValueError as exc:
      raise AuthoringError("%s is not readable as JSON: %s" % (path, exc))
    if not isinstance(library, dict):
      raise AuthoringError("%s is not a symbol file" % path)

  library[symbol_id] = data
  parent = os.path.dirname(os.path.abspath(path))
  if parent and not os.path.isdir(parent):
    os.makedirs(parent)
  with open(path, "w") as handle:
    json.dump(library, handle, indent=2, sort_keys=True)
    handle.write("\n")
  return library
