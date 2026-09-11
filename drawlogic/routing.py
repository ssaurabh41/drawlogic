"""Turning net endpoints into drawable wire paths.

Endpoints are stored as pin references, never as coordinates, so a wire is
re-resolved from scratch every time anything is drawn. That is what makes
moving a gate carry its wires with it instead of leaving them behind.

Usage:

    from drawlogic import routing

    points = routing.route(doc, doc.nets[0])   # [(x, y), ...], orthogonal
    routes = routing.route_all(doc)            # [(net, points), ...]
    dots = routing.junctions(routes)           # where three branches meet

Every wire leaves and enters on the side its pin faces -- a short stub is
taken first, and only then may the route turn -- so a joint at a pin reads as
one continuous line. Routes also avoid other cells: no leg is drawn without
checking it clears every cell the wire is not connected to. A net's
`waypoints` force the route through given points.
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

# How far apart two wires that have nothing to do with each other must sit
# before they read as two wires rather than one.
WIRE_GAP = 16.0

# Corridor searches that may run anywhere on the sheet.
NEG_SPAN = float("-inf")
POS_SPAN = float("inf")


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
    return symbol.pin_position(cell, endpoint.get("pin"), doc.symbol_scale)
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

  matrix = symbol.matrix_for(cell, doc.symbol_scale)
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


def _stub_end(point, direction):
  """The point a wire reaches after leaving a pin along the side it faces."""
  return (point[0] + direction[0] * STUB, point[1] + direction[1] * STUB)


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
    matrix = symbol.matrix_for(cell, doc.symbol_scale)
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


class Sheet:
  """What a route needs to know about the rest of the drawing.

  Holds the cell footprints to dodge and the runs other wires have already
  taken, so a later wire can pick a corridor of its own instead of being drawn
  on top of an earlier one.

  Nets that share an endpoint are exempt from that: a fan-out from one pin is
  meant to lie on top of itself and show as a rail with junction dots.
  """

  def __init__(self, boxes=()):
    self.boxes = boxes
    self._runs = []
    self._keys = frozenset()

  def reserve(self, keys, points):
    """Remember the runs of a wire that has been routed."""
    for index in range(len(points) - 1):
      a = points[index]
      b = points[index + 1]
      if abs(a[1] - b[1]) < EPSILON:
        self._runs.append((keys, True, a[1], min(a[0], b[0]), max(a[0], b[0])))
      elif abs(a[0] - b[0]) < EPSILON:
        self._runs.append((keys, False, a[0], min(a[1], b[1]), max(a[1], b[1])))

  def for_net(self, boxes, keys):
    """A view of this sheet for one net: its own obstacles, shared history.

    The net's own endpoints are exempt from the reserved runs, so its fan-out
    does not block itself.
    """
    view = Sheet(boxes)
    view._runs = self._runs
    view._keys = keys
    return view

  def free(self, horizontal, fixed, v0, v1):
    """True if this line neither shadows nor crosses an unrelated wire.

    Shadowing is the worse of the two -- two wires drawn nearly on top of each
    other cannot be told apart at all -- but crossings are worth avoiding as
    well, since the corridor one step the other way usually has none. Both are
    preferences: `_pick_corridor` falls back to a merely cell-free corridor
    when every candidate is taken.
    """
    lo, hi = min(v0, v1), max(v0, v1)
    for keys, run_h, run_fixed, run_lo, run_hi in self._runs:
      if keys & self._keys:
        continue
      if run_h == horizontal:
        if abs(run_fixed - fixed) >= WIRE_GAP:
          continue
        if hi - EPSILON <= run_lo or lo + EPSILON >= run_hi:
          continue
        return False
      if run_lo + EPSILON < fixed < run_hi - EPSILON and lo < run_fixed < hi:
        return False
    return True


def _endpoint_keys(net):
  """The pins a net touches, used to spot wires that share a source."""
  keys = set()
  for side in ("from", "to"):
    endpoint = net.get(side) or {}
    if isinstance(endpoint, dict) and "cell" in endpoint:
      keys.add((endpoint["cell"], endpoint.get("pin")))
  return frozenset(keys)


def _leg_clear(p, q, boxes):
  """True if one axis-aligned segment misses every obstacle box."""
  if abs(p[0] - q[0]) < EPSILON:
    return _vertical_clear(p[0], p[1], q[1], boxes)
  if abs(p[1] - q[1]) < EPSILON:
    return _horizontal_clear(p[1], p[0], q[0], boxes)
  return True


def _pick_corridor(preferred, span_lo, span_hi, path_is_clear, is_free=None):
  """Choose a corridor near `preferred` whose whole path misses every cell.

  `path_is_clear` checks all three legs, not just the corridor itself -- a
  corridor that dodges a gate is no use if the leg leading into it still
  ploughs straight through one.

  `is_free` marks corridors no unrelated wire has already taken. A corridor
  that is merely clear of cells is accepted only when no free one can be
  found, so two wires are not drawn one on top of the other.

  Falls back to the preferred position when nothing is clear, so a crowded
  drawing still produces a wire rather than nothing at all.
  """
  for test in _tests(path_is_clear, is_free):
    if test(preferred):
      return preferred
    for step in range(1, CORRIDOR_TRIES + 1):
      for candidate in (preferred + step * CORRIDOR_STEP,
                        preferred - step * CORRIDOR_STEP):
        if candidate <= span_lo or candidate >= span_hi:
          continue
        if test(candidate):
          return candidate
  return preferred


def _pick_outward(preferred, direction, path_is_clear, is_free=None):
  """Choose a corridor at `preferred` or further along `direction`.

  Used when both pins face the same way and the wire has to come round to the
  far side of both before it can turn in, so only one search direction makes
  sense.
  """
  for test in _tests(path_is_clear, is_free):
    for step in range(CORRIDOR_TRIES + 1):
      candidate = preferred + step * CORRIDOR_STEP * direction
      if test(candidate):
        return candidate
  return preferred


def _tests(path_is_clear, is_free):
  """Corridor tests to try in turn: the fussy one first, then the bare one."""
  if is_free is None:
    return [path_is_clear]
  return [lambda value: path_is_clear(value) and is_free(value), path_is_clear]


def _free_direction(point, other):
  """Which way a free endpoint faces: towards the other end of the net."""
  dx = other[0] - point[0]
  dy = other[1] - point[1]
  if abs(dx) >= abs(dy):
    return (1.0 if dx >= 0 else -1.0, 0.0)
  return (0.0, 1.0 if dy >= 0 else -1.0)


def _sidestep(a, b, sheet, vertical):
  """Detour around whatever blocks the straight line between two points.

  `vertical` says the blocked run was vertical, so the detour shifts sideways
  in x; otherwise it shifts in y.
  """
  boxes = sheet.boxes
  if vertical:
    def clear_at(x):
      return (_vertical_clear(x, a[1], b[1], boxes)
              and _horizontal_clear(a[1], a[0], x, boxes)
              and _horizontal_clear(b[1], x, b[0], boxes))
    x = _pick_corridor(a[0], NEG_SPAN, POS_SPAN, clear_at,
                       lambda x: sheet.free(False, x, a[1], b[1]))
    return [a, (x, a[1]), (x, b[1]), b]

  def clear_at(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))
  y = _pick_corridor(a[1], NEG_SPAN, POS_SPAN, clear_at,
                     lambda y: sheet.free(True, y, a[0], b[0]))
  return [a, (a[0], y), (b[0], y), b]


def _route_hh(a, b, a_dir, b_dir, sheet):
  """Both ends face sideways: cross over on a shared column."""
  boxes = sheet.boxes

  def clear_at(x):
    return (_vertical_clear(x, a[1], b[1], boxes)
            and _horizontal_clear(a[1], a[0], x, boxes)
            and _horizontal_clear(b[1], x, b[0], boxes))

  def free_at(x):
    return sheet.free(False, x, a[1], b[1])

  facing = ((b[0] - a[0]) * a_dir[0] > EPSILON
            and (a[0] - b[0]) * b_dir[0] > EPSILON)
  if facing:
    lo, hi = sorted((a[0], b[0]))
    x = _pick_corridor((a[0] + b[0]) / 2.0, lo, hi, clear_at, free_at)
    return [a, (x, a[1]), (x, b[1]), b]

  if a_dir[0] * b_dir[0] > 0:
    direction = a_dir[0]
    base = max(a[0], b[0]) if direction > 0 else min(a[0], b[0])
    x = _pick_outward(base, direction, clear_at, free_at)
    return [a, (x, a[1]), (x, b[1]), b]

  # Back to back, so no column between them can be used: go out of each pin
  # and across on a shared row instead.
  def row_clear(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))
  y = _pick_corridor((a[1] + b[1]) / 2.0, NEG_SPAN, POS_SPAN, row_clear,
                     lambda y: sheet.free(True, y, a[0], b[0]))
  return [a, (a[0], y), (b[0], y), b]


def _route_vv(a, b, a_dir, b_dir, sheet):
  """Both ends face up or down: cross over on a shared row."""
  boxes = sheet.boxes

  def clear_at(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))

  def free_at(y):
    return sheet.free(True, y, a[0], b[0])

  facing = ((b[1] - a[1]) * a_dir[1] > EPSILON
            and (a[1] - b[1]) * b_dir[1] > EPSILON)
  if facing:
    lo, hi = sorted((a[1], b[1]))
    y = _pick_corridor((a[1] + b[1]) / 2.0, lo, hi, clear_at, free_at)
    return [a, (a[0], y), (b[0], y), b]

  if a_dir[1] * b_dir[1] > 0:
    direction = a_dir[1]
    base = max(a[1], b[1]) if direction > 0 else min(a[1], b[1])
    y = _pick_outward(base, direction, clear_at, free_at)
    return [a, (a[0], y), (b[0], y), b]

  def column_clear(x):
    return (_vertical_clear(x, a[1], b[1], boxes)
            and _horizontal_clear(a[1], a[0], x, boxes)
            and _horizontal_clear(b[1], x, b[0], boxes))
  x = _pick_corridor((a[0] + b[0]) / 2.0, NEG_SPAN, POS_SPAN, column_clear,
                     lambda x: sheet.free(False, x, a[1], b[1]))
  return [a, (x, a[1]), (x, b[1]), b]


def _route_corner(a, b, sheet, a_horizontal):
  """One end faces sideways and the other up or down: a single corner."""
  boxes = sheet.boxes
  along_a = (b[0], a[1]) if a_horizontal else (a[0], b[1])
  along_b = (a[0], b[1]) if a_horizontal else (b[0], a[1])
  for corner in (along_a, along_b):
    if _leg_clear(a, corner, boxes) and _leg_clear(corner, b, boxes):
      return [a, corner, b]
  return [a, along_a, b]


def _middle_route(a, b, a_dir, b_dir, sheet):
  """Orthogonal path between two stub ends, dodging every cell on the way."""
  if abs(a[0] - b[0]) < EPSILON:
    if _vertical_clear(a[0], a[1], b[1], sheet.boxes):
      return [a, b]
    return _sidestep(a, b, sheet, True)
  if abs(a[1] - b[1]) < EPSILON:
    if _horizontal_clear(a[1], a[0], b[0], sheet.boxes):
      return [a, b]
    return _sidestep(a, b, sheet, False)

  a_horizontal = abs(a_dir[0]) > abs(a_dir[1])
  b_horizontal = abs(b_dir[0]) > abs(b_dir[1])
  if a_horizontal and b_horizontal:
    return _route_hh(a, b, a_dir, b_dir, sheet)
  if not a_horizontal and not b_horizontal:
    return _route_vv(a, b, a_dir, b_dir, sheet)
  return _route_corner(a, b, sheet, a_horizontal)


def _direct_route(start, end, start_dir, end_dir, sheet):
  """Route between two pins with no waypoints to honour.

  The wire leaves each pin along the side that pin faces and only then is
  allowed to turn. That short stub is what makes the joint at, say, a
  flip-flop clock pin read as a continuation of the wire instead of a line
  that arrived from the wrong side, and it keeps the first and last leg clear
  of the cells the net belongs to.
  """
  a_dir = start_dir or _free_direction(start, end)
  b_dir = end_dir or _free_direction(end, start)
  a = _stub_end(start, a_dir) if start_dir else start
  b = _stub_end(end, b_dir) if end_dir else end
  return [start] + _middle_route(a, b, a_dir, b_dir, sheet) + [end]


def route(doc, net, registry=None, sheet=None):
  """Points making up one wire, or an empty list if it cannot be resolved.

  Pass the `sheet` from `route_all` to let a wire see the ones routed before
  it; on its own a wire only dodges cells.
  """
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
    sheet = sheet or Sheet()
    view = sheet.for_net(boxes, _endpoint_keys(net))
    return _clean(_direct_route(start, end, start_dir, end_dir, view))

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
  """Every net's path, in document order.

  Wires are routed one after another and each remembers where it ran, so a
  later wire picks a corridor of its own rather than landing on an earlier
  one. Order therefore matters: the first net stated gets the straightest run.
  """
  registry = registry or default_registry()
  sheet = Sheet()
  routes = []
  for net in doc.nets:
    points = route(doc, net, registry, sheet)
    sheet.reserve(_endpoint_keys(net), points)
    routes.append((net, points))
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


def hop_points(routes):
  """Where one wire crosses another without joining it, keyed by net id.

  A crossing and a connection must not look the same. Junction dots mark the
  connections; these points mark the crossings, which the renderer draws as a
  little bridge so the eye can follow each wire through.

  By convention the horizontal wire hops over the vertical one, so only one
  of the two gets a bridge and the pair never both bulge at the same spot.
  """
  segments = []
  vertices = set()
  for net, points in routes:
    net_id = net.get("id")
    for point in points:
      vertices.add(_key(point))
    for index in range(len(points) - 1):
      a = points[index]
      b = points[index + 1]
      if abs(a[1] - b[1]) < EPSILON:
        segments.append((net_id, a, b, "h"))
      elif abs(a[0] - b[0]) < EPSILON:
        segments.append((net_id, a, b, "v"))

  found = {}
  for net_id, a, b, orientation in segments:
    if orientation != "h":
      continue
    y = a[1]
    low, high = sorted((a[0], b[0]))
    for other_id, c, d, other_orientation in segments:
      if other_orientation != "v" or other_id == net_id:
        continue
      x = c[0]
      v_low, v_high = sorted((c[1], d[1]))
      # Strictly interior to both, so a wire ending on another is a junction.
      if not (low + EPSILON < x < high - EPSILON):
        continue
      if not (v_low + EPSILON < y < v_high - EPSILON):
        continue
      if _key((x, y)) in vertices:
        continue
      # Two wires of the same rail can cross this one at the same spot; one
      # bridge is enough, and drawing it twice only thickens the arc.
      spots = found.setdefault(net_id, [])
      if all(_key(spot) != _key((x, y)) for spot in spots):
        spots.append((x, y))

  return found


def stroke_width(net):
  """Wire weight. Buses look the same as single bits; the name carries width."""
  return theme.WIDTHS["net"]
