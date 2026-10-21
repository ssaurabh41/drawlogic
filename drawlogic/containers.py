"""Containers: titled boundaries that hold part of a drawing.

A container is a box with a heading -- "GPC 0", "Memory subsystem" -- that
owns whatever names it as its `parentId`: cells, shapes and other containers.
Ownership is that field and nothing else. Something sitting inside the box
without naming it is not in it, so dragging a cell across a container never
quietly changes what it belongs to.

Coordinates stay absolute. A cell inside a container keeps its own x and y
on the sheet, so routing, rendering and every geometry helper read it exactly
as they read any other cell; moving a container means moving each thing it
holds by the same amount (see `move`).

Containers are painted beneath everything else, outer before inner, so a
container is the background of what it holds.

Usage:

    from drawlogic import containers

    containers.paint_order(doc)              # outer first, as drawn
    containers.descendants(doc, {"gpc0"})    # every id inside, at any depth
    containers.fit(doc, registry, box)       # box grows/shrinks round its contents
"""

from . import theme
from .geometry import corners, fmt, union_bbox


def by_id(doc):
  """{id: container}, the first of any repeated id winning."""
  found = {}
  for box in doc.containers:
    found.setdefault(box.get("id"), box)
  return found


def padding(box):
  try:
    return max(0.0, float(box.get("padding", theme.CONTAINER["padding"])))
  except (TypeError, ValueError):
    return theme.CONTAINER["padding"]


def header(box):
  try:
    return max(0.0, float(box.get("headerHeight", theme.CONTAINER["header"])))
  except (TypeError, ValueError):
    return theme.CONTAINER["header"]


def _owned(doc):
  """Every cell, shape and container, as (kind, item)."""
  return ([("cell", c) for c in doc.cells]
          + [("shape", s) for s in doc.shapes]
          + [("container", b) for b in doc.containers])


def children(doc, container_id):
  """What a container holds directly, as (kind, item), in file order."""
  return [(kind, item) for kind, item in _owned(doc)
          if item.get("parentId") == container_id]


def descendants(doc, ids):
  """The ids in `ids` and everything inside any of them, at any depth.

  Walked breadth-first with a seen set, so a containment loop -- which
  validate() reports -- ends the walk instead of hanging it.
  """
  found = set(ids)
  frontier = list(ids)
  owned = _owned(doc)
  while frontier:
    parents = set(frontier)
    frontier = []
    for _kind, item in owned:
      item_id = item.get("id")
      if item.get("parentId") in parents and item_id not in found:
        found.add(item_id)
        frontier.append(item_id)
  return found


def paint_order(doc):
  """Containers in the order they are painted: each before what it holds.

  Depth first from the containers nobody holds, in file order, so a
  container's whole subtree is painted together. One whose parent is missing
  counts as unheld; one caught in a loop is painted last, once, rather than
  not at all -- a box you cannot see is a box you cannot select to fix.
  """
  boxes = by_id(doc)
  order = []
  seen = set()

  def visit(box):
    if id(box) in seen:
      return
    seen.add(id(box))
    order.append(box)
    for other in doc.containers:
      if other.get("parentId") == box.get("id") and other is not box:
        visit(other)

  for box in doc.containers:
    if box.get("parentId") not in boxes:
      visit(box)
  for box in doc.containers:
    visit(box)
  return order


def item_box(doc, registry, kind, item):
  """(x, y, w, h) of a cell's body, a shape or a container, or None."""
  if kind == "container":
    return (float(item["x"]), float(item["y"]), float(item["w"]), float(item["h"]))
  if kind == "shape":
    points = item.get("points")
    if points:
      xs = [p[0] for p in points]
      ys = [p[1] for p in points]
      return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if "x" in item and "y" in item:
      return (float(item["x"]), float(item["y"]),
              float(item.get("w", 0)), float(item.get("h", 0)))
    return None
  symbol = registry.for_cell(item)
  if symbol is None:
    return None
  matrix = symbol.matrix_for(item, doc.symbol_scale)
  points = [matrix.apply(px, py)
            for px, py in corners(0, 0, symbol.width, symbol.height)]
  xs = [p[0] for p in points]
  ys = [p[1] for p in points]
  return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def contents_box(doc, registry, box):
  """The bounds of what a container directly holds, or None if it is empty."""
  found = None
  for kind, item in children(doc, box.get("id")):
    found = union_bbox(found, item_box(doc, registry, kind, item))
  return found


def needed_box(doc, registry, box):
  """The smallest box that still holds a container's contents with its
  padding round them and its header above them, or None if it is empty."""
  inner = contents_box(doc, registry, box)
  if inner is None:
    return None
  pad = padding(box)
  x, y, w, h = inner
  top = y - pad - header(box)
  return (x - pad, top, w + 2 * pad, (y + h + pad) - top)


def fit(doc, registry, box):
  """Size a container to its contents, padding and header. False if empty."""
  need = needed_box(doc, registry, box)
  if need is None:
    return False
  box["x"], box["y"], box["w"], box["h"] = need
  return True


# ---- drawing ----
#
# Shared with web/js/render.js, which mirrors these line for line: what the
# canvas paints and what an export paints must be the same marks.

def style_of(box):
  """The container's colours, its own style over the theme's."""
  style = box.get("style") or {}
  base = theme.CONTAINER
  return {
    "fill": style.get("fill") or base["fill"],
    "stroke": style.get("stroke") or base["stroke"],
    "headerFill": style.get("headerFill") or base["headerFill"],
    "titleFill": style.get("titleFill") or base["titleFill"],
    "strokeWidth": float(style.get("strokeWidth") or base["width"]),
  }


def header_path(box):
  """The header band's outline: rounded at the top corners, square below."""
  x, y, w = float(box["x"]), float(box["y"]), float(box["w"])
  depth = min(header(box), float(box["h"]))
  r = min(theme.CONTAINER["radius"], w / 2.0, depth)
  return ("M%s %s V%s A%s %s 0 0 1 %s %s H%s A%s %s 0 0 1 %s %s V%s Z"
          % tuple(fmt(v) for v in (x, y + depth, y + r, r, r, x + r, y,
                                    x + w - r, r, r, x + w, y + r, y + depth)))


def title_layout(box, font_scale=1.0):
  """(x, baseline, text, size) for a container's title, or None.

  Centred down the header band and cut short with an ellipsis where the box
  is too narrow, by the same character estimate cell text uses.
  """
  title = box.get("title")
  if not isinstance(title, str) or not title.strip() or header(box) <= 0:
    return None
  size = theme.FONT_SIZES["container_title"] * font_scale
  inset = theme.CONTAINER["titleInset"]
  room = int(max(0.0, float(box["w"]) - 2 * inset) / (size * theme.CONTAINER["char"]) + 1e-6)
  text = title if len(title) <= room else (
    title[:max(0, room - 1)].rstrip() + "\u2026" if room > 0 else "")
  depth = min(header(box), float(box["h"]))
  return (float(box["x"]) + inset, float(box["y"]) + depth / 2.0 + size * 0.35,
          text, size)
