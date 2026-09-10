"""Turning net endpoints into drawable wire paths.

Endpoints are stored as pin references, never as coordinates, so a wire is
re-resolved from scratch every time anything is drawn. That is what makes
moving a gate carry its wires with it instead of leaving them behind.
"""

from . import theme
from .geometry import corners
from .symbols import default_registry

STUB = 12.0
EPSILON = 1e-6

# How far a wire keeps away from a cell it is not connected to, and how far
# apart the candidate corridors are when the first choice is blocked.
CLEARANCE = 8.0
CORRIDOR_STEP = 10.0
CORRIDOR_TRIES = 16


def _key(point):
  return (round(point[0], 3), round(point[1], 3))


def endpoint_position(doc, endpoint, registry=None):
  """Sheet coordinates of a net endpoint, or None if it cannot be resolved."""
  if not isinstance(endpoint, dict):
    return None
  if "cell" in endpoint:
    registry = registry or default_registry()
    cell = doc.cell(endpoint["cell"])
    if cell is None:
      return None
    symbol = registry.get(cell.get("type"))
    if symbol is None:
      return None
    return symbol.pin_position(cell, endpoint.get("pin"))
  if "x" in endpoint and "y" in endpoint:
    return (float(endpoint["x"]), float(endpoint["y"]))
  return None


def endpoint_direction(doc, endpoint, registry=None):
  """Unit vector pointing away from the cell at this endpoint.

  Free endpoints have no direction, so the router treats them as flexible.
  """
  if not isinstance(endpoint, dict) or "cell" not in endpoint:
    return None
  registry = registry or default_registry()
  cell = doc.cell(endpoint["cell"])
  if cell is None:
    return None
  symbol = registry.get(cell.get("type"))
  if symbol is None:
    return None
  pin = symbol.pin(endpoint.get("pin"))
  if pin is None:
    return None

  if pin["x"] <= EPSILON:
    local = (-1.0, 0.0)
  elif pin["x"] >= symbol.width - EPSILON:
    local = (1.0, 0.0)
  elif pin["y"] <= EPSILON:
    local = (0.0, -1.0)
  elif pin["y"] >= symbol.height - EPSILON:
    local = (0.0, 1.0)
  else:
    local = (1.0, 0.0)

  matrix = symbol.matrix_for(cell)
  origin = matrix.apply(0, 0)
  tip = matrix.apply(local[0], local[1])
  dx = tip[0] - origin[0]
  dy = tip[1] - origin[1]
  if abs(dx) >= abs(dy):
    return (1.0 if dx > 0 else -1.0, 0.0)
  return (0.0, 1.0 if dy > 0 else -1.0)


def _clean(points):
  """Drop repeated points and merge runs that carry straight on."""
  out = []
  for point in points:
    if out and _key(out[-1]) == _key(point):
      continue
    out.append(point)
  if len(out) < 3:
    return out
  merged = [out[0]]
  for i in range(1, len(out) - 1):
    prev = merged[-1]
    here = out[i]
    nxt = out[i + 1]
    same_x = abs(prev[0] - here[0]) < EPSILON and abs(here[0] - nxt[0]) < EPSILON
    same_y = abs(prev[1] - here[1]) < EPSILON and abs(here[1] - nxt[1]) < EPSILON
    if same_x or same_y:
      continue
    merged.append(here)
  merged.append(out[-1])
  return merged


def _elbow(a, b, horizontal_first):
  """One corner joining two points with axis-aligned segments."""
  if abs(a[0] - b[0]) < EPSILON or abs(a[1] - b[1]) < EPSILON:
    return []
  if horizontal_first:
    return [(b[0], a[1])]
  return [(a[0], b[1])]


def obstacle_boxes(doc, registry=None, exclude=()):
  """Cell footprints a wire should avoid, as (x0, y0, x1, y1) with clearance.

  The cells at each end of the net are excluded -- a wire is expected to
  touch the thing it connects to.
  """
  registry = registry or default_registry()
  boxes = []
  for cell in doc.cells:
    if cell.get("id") in exclude:
      continue
    symbol = registry.get(cell.get("type"))
    if symbol is None:
      continue
    matrix = symbol.matrix_for(cell)
    points = [matrix.apply(px, py)
              for px, py in corners(0, 0, symbol.width, symbol.height)]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    boxes.append((min(xs) - CLEARANCE, min(ys) - CLEARANCE,
                  max(xs) + CLEARANCE, max(ys) + CLEARANCE))
  return boxes


def _vertical_clear(x, y0, y1, boxes):
  lo, hi = min(y0, y1), max(y0, y1)
  for bx0, by0, bx1, by1 in boxes:
    if bx0 <= x <= bx1 and not (hi < by0 or lo > by1):
      return False
  return True


def _horizontal_clear(y, x0, x1, boxes):
  lo, hi = min(x0, x1), max(x0, x1)
  for bx0, by0, bx1, by1 in boxes:
    if by0 <= y <= by1 and not (hi < bx0 or lo > bx1):
      return False
  return True


def _pick_corridor(preferred, span_lo, span_hi, from_value, to_value,
                   boxes, clear):
  """Choose a corridor near `preferred` that does not cut through a cell.

  Falls back to the preferred position when nothing is clear, so a crowded
  drawing still produces a wire rather than nothing at all.
  """
  if clear(preferred, from_value, to_value, boxes):
    return preferred
  for step in range(1, CORRIDOR_TRIES + 1):
    for candidate in (preferred + step * CORRIDOR_STEP,
                      preferred - step * CORRIDOR_STEP):
      if candidate <= span_lo or candidate >= span_hi:
        continue
      if clear(candidate, from_value, to_value, boxes):
        return candidate
  return preferred


def _direct_route(start, end, start_dir, end_dir, boxes=()):
  """Route between two pins with no waypoints to honour."""
  if abs(start[0] - end[0]) < EPSILON or abs(start[1] - end[1]) < EPSILON:
    return [start, end]

  start_horizontal = start_dir is None or abs(start_dir[0]) > abs(start_dir[1])
  end_horizontal = end_dir is None or abs(end_dir[0]) > abs(end_dir[1])

  if start_horizontal and end_horizontal:
    forward = (end[0] - start[0]) * (start_dir[0] if start_dir else 1.0)
    if forward > 2 * STUB:
      mid = _pick_corridor(
        (start[0] + end[0]) / 2.0,
        min(start[0], end[0]) + STUB, max(start[0], end[0]) - STUB,
        start[1], end[1], boxes, _vertical_clear)
      return [start, (mid, start[1]), (mid, end[1]), end]
    # The target sits behind the driving pin, so break out, cross over on a
    # mid-line, and come back in rather than drawing through the cell.
    out_x = start[0] + (start_dir[0] if start_dir else 1.0) * STUB
    in_x = end[0] - (end_dir[0] if end_dir else -1.0) * STUB
    mid_y = (start[1] + end[1]) / 2.0
    return [start, (out_x, start[1]), (out_x, mid_y),
            (in_x, mid_y), (in_x, end[1]), end]

  if not start_horizontal and not end_horizontal:
    forward = (end[1] - start[1]) * (start_dir[1] if start_dir else 1.0)
    if forward > 2 * STUB:
      mid = _pick_corridor(
        (start[1] + end[1]) / 2.0,
        min(start[1], end[1]) + STUB, max(start[1], end[1]) - STUB,
        start[0], end[0], boxes, _horizontal_clear)
      return [start, (start[0], mid), (end[0], mid), end]
    out_y = start[1] + (start_dir[1] if start_dir else 1.0) * STUB
    in_y = end[1] - (end_dir[1] if end_dir else -1.0) * STUB
    mid_x = (start[0] + end[0]) / 2.0
    return [start, (start[0], out_y), (mid_x, out_y),
            (mid_x, in_y), (end[0], in_y), end]

  if start_horizontal:
    return [start, (end[0], start[1]), end]
  return [start, (start[0], end[1]), end]


def route(doc, net, registry=None):
  """Points making up one wire, or an empty list if it cannot be resolved."""
  registry = registry or default_registry()
  start = endpoint_position(doc, net.get("from"), registry)
  end = endpoint_position(doc, net.get("to"), registry)
  if start is None or end is None:
    return []

  waypoints = [(float(p[0]), float(p[1])) for p in net.get("waypoints", [])]

  if not waypoints:
    start_dir = endpoint_direction(doc, net.get("from"), registry)
    end_dir = endpoint_direction(doc, net.get("to"), registry)
    exclude = set()
    for side in ("from", "to"):
      endpoint = net.get(side) or {}
      if "cell" in endpoint:
        exclude.add(endpoint["cell"])
    boxes = obstacle_boxes(doc, registry, exclude)
    return _clean(_direct_route(start, end, start_dir, end_dir, boxes))

  points = [start] + waypoints + [end]
  chain = [points[0]]
  horizontal_first = True
  start_dir = endpoint_direction(doc, net.get("from"), registry)
  if start_dir is not None:
    horizontal_first = abs(start_dir[0]) > abs(start_dir[1])
  for index in range(len(points) - 1):
    a = points[index]
    b = points[index + 1]
    corner = _elbow(a, b, horizontal_first)
    chain.extend(corner)
    chain.append(b)
    if corner:
      horizontal_first = not horizontal_first
  return _clean(chain)


def route_all(doc, registry=None):
  """Every net's path, keyed by net id, in document order."""
  registry = registry or default_registry()
  routes = []
  for net in doc.nets:
    routes.append((net, route(doc, net, registry)))
  return routes


def _segments(routes):
  out = []
  for _, points in routes:
    for index in range(len(points) - 1):
      out.append((points[index], points[index + 1]))
  return out


def _touches(point, segment):
  """True if an axis-aligned segment passes through or ends at a point."""
  (ax, ay), (bx, by) = segment
  px, py = point
  if abs(ax - bx) < EPSILON:
    if abs(px - ax) > EPSILON:
      return False
    return min(ay, by) - EPSILON <= py <= max(ay, by) + EPSILON
  if abs(ay - by) < EPSILON:
    if abs(py - ay) > EPSILON:
      return False
    return min(ax, bx) - EPSILON <= px <= max(ax, bx) + EPSILON
  return False


def _rays_at(point, segments):
  """Distinct compass directions in which wire leaves a point.

  A segment ending here contributes one ray; a segment passing straight
  through contributes two. Counting rays rather than segments is what tells a
  tee (three) apart from an ordinary corner (two).
  """
  rays = set()
  for segment in segments:
    if not _touches(point, segment):
      continue
    for other in segment:
      dx = other[0] - point[0]
      dy = other[1] - point[1]
      if abs(dx) < EPSILON and abs(dy) < EPSILON:
        continue
      if abs(dx) >= abs(dy):
        rays.add((1 if dx > 0 else -1, 0))
      else:
        rays.add((0, 1 if dy > 0 else -1))
  return rays


def junctions(routes):
  """Points where three or more wire branches meet, which get a solid dot.

  Wires that merely cross without a shared vertex are left undotted, which is
  the whole point: a crossing and a connection must not look the same.
  """
  segments = _segments(routes)
  candidates = {}
  for _, points in routes:
    for point in points:
      candidates.setdefault(_key(point), point)

  found = []
  for _, point in sorted(candidates.items()):
    if len(_rays_at(point, segments)) >= 3:
      found.append(point)
  return found


def stroke_width(net):
  """Buses are drawn heavier so width is readable without reading the label."""
  if net.get("width", 1) > 1:
    return theme.WIDTHS["bus"]
  return theme.WIDTHS["net"]
