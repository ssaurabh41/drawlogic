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
from .geometry import corners, label_lines
from . import drc
from .doc import loads_of
from .symbols import default_registry

STUB = 12.0
EPSILON = 1e-6

# How far a wire keeps away from a cell it is not connected to, and how far
# apart the candidate corridors are when the first choice is blocked.
CLEARANCE = drc.WIRE_TO_CELL

# How far a wire keeps above a cell that has an instance name: the room the
# name takes, plus the air text needs to stay readable.
TEXT_HEADROOM = drc.LABEL_HEADROOM + drc.TEXT_TO_WIRE
# One more line of a wrapped instance name. theme is not imported here, so
# this is the label font size times the renderer's line spacing, written out:
# 13.5 * 1.15, rounded up to keep the reservation on the generous side.
LABEL_LINE = 16.0
CORRIDOR_STEP = drc.CORRIDOR_STEP
CORRIDOR_TRIES = drc.CORRIDOR_TRIES

# How far apart two wires that have nothing to do with each other must sit
# before they read as two wires rather than one, and the much smaller distance
# that only asks them not to be drawn on top of each other.
WIRE_GAP = drc.WIRE_GAP
TOUCHING = drc.TOUCHING
# Corridors this far apart give any wire crossing both of them two bridges
# with visible wire between, instead of one squiggle.
HOP_GAP = drc.HOP_GAP

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
    symbol = registry.for_cell(cell)
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
  symbol = registry.for_cell(cell)
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


def _stub_end(point, direction, length=STUB):
  """The point a wire reaches after leaving a pin along the side it faces."""
  return (point[0] + direction[0] * length, point[1] + direction[1] * length)


def stub_for(doc, endpoint, registry=None):
  """How long a straight run this endpoint's pin is entitled to.

  A port gets more than an ordinary pin: it is the edge of the sheet, with no
  body between the connector and the first turn, so a wire that bends
  immediately reads as a line stuck to the port rather than as a signal
  leaving it.
  """
  if not isinstance(endpoint, dict) or "cell" not in endpoint:
    return STUB
  registry = registry or default_registry()
  cell = doc.cell(endpoint["cell"])
  if cell is None:
    return STUB
  symbol = registry.for_cell(cell)
  if symbol is None or symbol.category != drc.PORT_CATEGORY:
    return STUB
  return drc.PORT_STUB


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

  A labelled cell reaches higher than its body, because its instance name is
  drawn above it and a wire through a name is worse than a wire through a
  body: a body can still be read around the wire, a word cannot. Only the top
  grows, and only over the cell's own width -- a name wider than the cell it
  belongs to still sticks out past this, which the text-to-wire DRC reports.
  """
  registry = registry or default_registry()
  boxes = []
  for cell in doc.cells:
    if cell.get("id") in exclude:
      continue
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    matrix = symbol.matrix_for(cell, doc.symbol_scale)
    points = [matrix.apply(px, py)
              for px, py in corners(0, 0, symbol.width, symbol.height)]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    # A name split over two lines reaches a line higher, so the room kept
    # above the cell grows with it -- otherwise a wire routes straight
    # through the upper line of a wrapped name.
    lines = len(label_lines(cell["label"])) if cell.get("label") else 0
    headroom = (TEXT_HEADROOM + (lines - 1) * LABEL_LINE
                if lines else CLEARANCE)
    boxes.append((min(xs) - CLEARANCE, min(ys) - headroom,
                  max(xs) + CLEARANCE, max(ys) + CLEARANCE))
  return boxes


def body_boxes(doc, registry=None, exclude=()):
  """Cell bodies as they are drawn, without the clearance a router keeps.

  `obstacle_boxes` pads every cell so a wire is steered well clear of it and
  of the name above it. That is the right question when choosing a corridor
  and the wrong one when asking whether a finished route is acceptable: a
  wire passing snugly by a cell is untidy, and one drawn across its body is
  an error. This is the second question, and it is the one the DRC asks.
  """
  registry = registry or default_registry()
  boxes = []
  for cell in doc.cells:
    if cell.get("id") in exclude:
      continue
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    matrix = symbol.matrix_for(cell, doc.symbol_scale)
    points = [matrix.apply(px, py)
              for px, py in corners(0, 0, symbol.width, symbol.height)]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    boxes.append((min(xs), min(ys), max(xs), max(ys)))
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

  def __init__(self, boxes=(), own=()):
    self.boxes = boxes
    # The bodies of the net's own cells, which `boxes` leaves out because the
    # wire has to reach them. Only a crossover leg that has been moved off its
    # stub looks at these: nothing else can wander into its own cells.
    self.own = own
    self._runs = []
    self._keys = frozenset()
    self._net = None

  def reserve(self, keys, points, net_id=None):
    """Remember the runs of a wire that has been routed."""
    for index in range(len(points) - 1):
      a = points[index]
      b = points[index + 1]
      if abs(a[1] - b[1]) < EPSILON:
        self._runs.append((net_id, keys, True, a[1],
                           min(a[0], b[0]), max(a[0], b[0])))
      elif abs(a[0] - b[0]) < EPSILON:
        self._runs.append((net_id, keys, False, a[0],
                           min(a[1], b[1]), max(a[1], b[1])))

  def for_net(self, boxes, keys, net_id=None, own=()):
    """A view of this sheet for one net: its own obstacles, shared history.

    The net's own branches are exempt from the reserved runs, so a fan-out
    does not block itself -- that overlap is the rail, and the junction dots
    on it are the point.
    """
    view = Sheet(boxes, own)
    view._runs = self._runs
    view._keys = keys
    view._net = net_id
    return view

  def free(self, horizontal, fixed, v0, v1, crossings=True, gap=None):
    """True if this line stays clear of the wires already placed.

    Two faults, of very different weight. Shadowing -- running alongside
    another wire close enough that the pair reads as one line -- is always
    worth avoiding. Crossing one is only worth avoiding if there is somewhere
    better to go, since in a busy drawing every route crosses something.

    `crossings=False` asks the milder question, which is what the second pass
    of a corridor search uses. `gap` lowers the bar further: the last pass
    asks only that the wire not be drawn on top of another, which is a
    different question from being far enough from it to read as separate.
    """
    if gap is None:
      gap = WIRE_GAP
    lo, hi = min(v0, v1), max(v0, v1)
    for net_id, keys, run_h, run_fixed, run_lo, run_hi in self._runs:
      # A net never crowds itself, and neither does anything sharing a pin
      # with it: two wires off one pin are one signal, drawn as one rail.
      if (net_id is not None and net_id == self._net) or (keys & self._keys):
        continue
      if run_h == horizontal:
        if abs(run_fixed - fixed) >= gap:
          continue
        # Meeting end to end counts: two unrelated wires that share a single
        # point are drawn with a junction dot, which says they are connected.
        if hi + EPSILON < run_lo or lo - EPSILON > run_hi:
          continue
        return False
      if crossings and run_lo + EPSILON < fixed < run_hi - EPSILON \
          and lo < run_fixed < hi:
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
  """Corridor tests to try in turn, from fussiest to bare.

  The middle passes matter more than they look. Without them, a wire that can
  find no crossing-free corridor falls straight back to its preferred one --
  and since every wire between the same two columns prefers the same corridor,
  they would all pile onto it and be drawn on top of each other. Giving up on
  crossings first, then on separation, and only then on everything, keeps them
  apart.

  The third pass is the one that matters in a drawing with no room left. It
  asks only that the wire not be drawn on top of another, which is a much
  weaker question than being far enough away to read as separate -- and the
  difference between the two is the difference between a drawing that is
  crowded and a drawing that claims a connection nobody made.
  """
  if is_free is None:
    return [path_is_clear]
  return [
    lambda value: path_is_clear(value) and is_free(value, True, WIRE_GAP),
    lambda value: path_is_clear(value) and is_free(value, False, WIRE_GAP),
    lambda value: path_is_clear(value) and is_free(value, False, TOUCHING),
    path_is_clear,
  ]


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
                       lambda x, cross, gap:
                       sheet.free(False, x, a[1], b[1], cross, gap))
    return [a, (x, a[1]), (x, b[1]), b]

  def clear_at(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))
  y = _pick_corridor(a[1], NEG_SPAN, POS_SPAN, clear_at,
                     lambda y, cross, gap:
                     sheet.free(True, y, a[0], b[0], cross, gap))
  return [a, (a[0], y), (b[0], y), b]


def _route_hh(a, b, a_dir, b_dir, sheet):
  """Both ends face sideways: cross over on a shared column."""
  boxes = sheet.boxes

  def clear_at(x):
    return (_vertical_clear(x, a[1], b[1], boxes)
            and _horizontal_clear(a[1], a[0], x, boxes)
            and _horizontal_clear(b[1], x, b[0], boxes))

  def free_at(x, crossings, gap):
    # All three legs, to match clear_at, which has always checked all three
    # against cells. Testing only the corridor was the bug: a column with
    # nothing in it is no use if the leg leading into it lies along another
    # net's leg, and that overlap is exactly what a wire-short is.
    #
    # The legs are asked the weaker question, always, whatever the ladder is
    # asking of the corridor. Two legs close together read as crowded and the
    # DRCs call it a warning; two legs on top of each other read as one wire
    # and the DRCs call it an error. Demanding full separation of the legs
    # made the search reject well-spaced corridors over a mere warning and
    # settle for a cramped one, which is a worse drawing by the measure that
    # matters.
    return (sheet.free(False, x, a[1], b[1], crossings, gap)
            and sheet.free(True, a[1], a[0], x, False, TOUCHING)
            and sheet.free(True, b[1], x, b[0], False, TOUCHING))

  # Both pins face each other, so a column between them carries the crossover
  # -- unless a block sits on one of the two rows, which no choice of column
  # can dodge, because those rows are the pins' own. Then the wire has to
  # leave the rows entirely and cross on a row of its own.
  def row_clear(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))

  facing = ((b[0] - a[0]) * a_dir[0] > EPSILON
            and (a[0] - b[0]) * b_dir[0] > EPSILON)
  if facing:
    lo, hi = sorted((a[0], b[0]))
    x = _pick_corridor((a[0] + b[0]) / 2.0, lo, hi, clear_at, free_at)
    if clear_at(x):
      return [a, (x, a[1]), (x, b[1]), b]
    return _row_crossover(a, b, a_dir, b_dir, sheet, row_clear)

  if a_dir[0] * b_dir[0] > 0:
    direction = a_dir[0]
    base = max(a[0], b[0]) if direction > 0 else min(a[0], b[0])
    x = _pick_outward(base, direction, clear_at, free_at)
    return [a, (x, a[1]), (x, b[1]), b]

  # Back to back, so no column between them can be used either way.
  return _row_crossover(a, b, a_dir, b_dir, sheet, row_clear)


def _row_crossover(a, b, a_dir, b_dir, sheet, row_clear):
  """Out of each pin and across on a shared row.

  The answer both when no column between the pins can be used and when every
  one of them is blocked: the wire leaves the pins' own rows, which is the
  only way past a block standing on one.
  """
  y = _pick_corridor((a[1] + b[1]) / 2.0, NEG_SPAN, POS_SPAN, row_clear,
                     lambda y, cross, gap:
                     sheet.free(True, y, a[0], b[0], cross, gap))
  xa = _leg_column(a, a_dir[0], y, sheet)
  xb = _leg_column(b, b_dir[0], y, sheet)
  return [a, (xa, a[1]), (xa, y), (xb, y), (xb, b[1]), b]


def _leg_column(end, direction, y, sheet):
  """The column a crossover's leg runs down, from a pin's row to its own.

  The leg sits on the stub end, which is the same column for every pin down
  one side of a cell -- so two unrelated wires leaving that side both dropped
  down it and were drawn on top of each other: every wire-short the examples
  had after auto-layout. The row was searched for a free place and the legs
  never were. A leg with nothing under it stays exactly where it was; one
  that would lie on another net moves outward, away from its pin, until it
  does not.
  """
  if sheet.free(False, end[0], end[1], y, False, TOUCHING):
    return end[0]
  boxes = sheet.boxes

  def clear_at(x):
    return all(_vertical_clear(x, end[1], y, found)
               and _horizontal_clear(end[1], end[0], x, found)
               for found in (boxes, sheet.own))

  def free_at(x, crossings, gap):
    return (sheet.free(False, x, end[1], y, crossings, gap)
            and sheet.free(True, end[1], end[0], x, False, TOUCHING))

  return _pick_outward(end[0], direction, clear_at, free_at)


def _route_vv(a, b, a_dir, b_dir, sheet):
  """Both ends face up or down: cross over on a shared row."""
  boxes = sheet.boxes

  def clear_at(y):
    return (_horizontal_clear(y, a[0], b[0], boxes)
            and _vertical_clear(a[0], a[1], y, boxes)
            and _vertical_clear(b[0], y, b[1], boxes))

  def free_at(y, crossings, gap):
    return sheet.free(True, y, a[0], b[0], crossings, gap)

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
                     lambda x, cross, gap:
                     sheet.free(False, x, a[1], b[1], cross, gap))
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


def _direct_route(start, end, start_dir, end_dir, sheet,
                  start_stub=STUB, end_stub=STUB):
  """Route between two pins with no waypoints to honour.

  The wire leaves each pin along the side that pin faces and only then is
  allowed to turn. That short stub is what makes the joint at, say, a
  flip-flop clock pin read as a continuation of the wire instead of a line
  that arrived from the wrong side, and it keeps the first and last leg clear
  of the cells the net belongs to. How long the stub is depends on the pin --
  see stub_for.
  """
  a_dir = start_dir or _free_direction(start, end)
  b_dir = end_dir or _free_direction(end, start)
  a = _stub_end(start, a_dir, start_stub) if start_dir else start
  b = _stub_end(end, b_dir, end_stub) if end_dir else end
  return [start] + _middle_route(a, b, a_dir, b_dir, sheet) + [end]


def route(doc, net, registry=None, sheet=None):
  """The branches of one wire: a list of paths, one per load it drives.

  A net has one driver and any number of loads, so what comes back is a list
  of paths rather than a single one. Branches are routed one at a time from
  the driving pin, which is why they lie on top of each other near it and part
  company where they have to -- the junction dots mark exactly where.

  Pass the `sheet` from `route_all` to let a wire see the ones routed before
  it; on its own a wire only dodges cells.
  """
  registry = registry or default_registry()
  start = endpoint_position(doc, net.get("from"), registry)
  if start is None:
    return []

  start_dir = endpoint_direction(doc, net.get("from"), registry)
  sheet = sheet or Sheet()
  keys = _endpoint_keys(net)

  branches = []
  # Only a wire with somewhere to fork needs any of the tapping machinery, and
  # most wires have one load, so the terminals are worked out only if asked for.
  terminals = None
  late = forks_late(doc)
  for load in loads_of(net):
    points = _branch(doc, net, load, start, start_dir, registry, sheet, keys)
    tap, tap_dir = (_tap(branches, endpoint_position(doc, load, registry))
                    if late else (None, None))
    if tap is not None:
      if terminals is None:
        terminals = _foreign_terminals(doc, net, registry)
      shorter = _branch(doc, net, load, tap, tap_dir, registry, sheet, keys,
                        from_pin=False)
      # Both ways are routed and the shorter clean one wins. Leaving late is
      # the point of the exercise, but it is worth doing only when it actually
      # saves wire: a tap that comes out no shorter has bought nothing and
      # still moved the wire, which shifts what every net routed after it has
      # to dodge. Measuring rather than assuming keeps that from happening.
      if (_run_length(shorter) < _run_length(points) - EPSILON
          and _lands_clear(shorter, doc, net, load, registry, sheet, keys,
                           terminals)):
        points = shorter
    if points:
      branches.append(points)
  return branches


def _run_length(points):
  """How far a path travels, corner to corner."""
  return sum(abs(points[i + 1][0] - points[i][0])
             + abs(points[i + 1][1] - points[i][1])
             for i in range(len(points) - 1)) if points else 0.0


def forks_late(doc):
  """Whether this drawing's wires share a trunk and divide near their loads.

  Off unless the drawing says so, which means a file written before any of
  this existed is routed exactly as it always was, and the flag only ever
  appears on a drawing that measured better with it.

  It is not a property of wires in general, which is why it is recorded per
  drawing rather than simply switched on. Sharing a trunk shortens most
  drawings and lengthens a few: the branch that leaves late takes a line of
  its own across the sheet, and every wire routed after it has to dodge that
  line instead of the old one. Whether that trade comes out ahead is a
  question only measuring the drawing can settle, so `layout.arrange` routes
  it both ways and writes the answer here.
  """
  canvas = getattr(doc, "canvas", None) or {}
  return bool(canvas.get("forkLate"))


def _tap(branches, end):
  """Where a new branch should leave the wire already drawn, and going which way.

  Routing every branch from the driving pin gives each one its own way across
  the sheet, and they part company as soon as their routes differ -- usually a
  step outside the pin. Two loads to the right of a port then leave it as two
  wires running side by side, and the junction dot lands next to the port
  rather than next to the load it serves.

  A wire is a tree, though, not a bundle of paths that happen to start
  together: the run is shared until it has to divide. So a later branch starts
  from whichever point of the wire so far is nearest the pin it is heading
  for, which is the last moment it can leave. The dot ends up beside the load,
  and the shared run is drawn once instead of twice.
  """
  if not branches or end is None:
    return None, None

  best = None
  for points in branches:
    for index in range(len(points) - 1):
      a, b = points[index], points[index + 1]
      spot = _closest_on_run(end, a, b)
      away = abs(spot[0] - end[0]) + abs(spot[1] - end[1])
      if best is None or away < best[0] - EPSILON:
        # Which way the run travels, so the new branch leaves along the wire
        # rather than doubling back down it.
        best = (away, spot, (b[0] - a[0], b[1] - a[1]))
  if best is None:
    return None, None

  _away, spot, run = best
  length = max(abs(run[0]), abs(run[1]))
  if length < EPSILON:
    return None, None
  return spot, (run[0] / length, run[1] / length)


def _closest_on_run(point, a, b):
  """The point of an axis-aligned run lying nearest `point`."""
  x = min(max(point[0], min(a[0], b[0])), max(a[0], b[0]))
  y = min(max(point[1], min(a[1], b[1])), max(a[1], b[1]))
  return (x, y)


def _foreign_terminals(doc, net, registry):
  """Where every other wire in the drawing begins and ends.

  The sheet remembers the runs wires have taken, which is what keeps a wire
  from being drawn along another. It does not remember where they stop, and
  that is a different question: a wire laid across the pin another wire ends
  at is drawn with a junction dot on it, and the drawing then says the two are
  connected when the file says they are not.

  It never came up while every branch set off from its own driving pin, since
  a branch then went much the same way as the one before it. A branch that
  leaves late takes a line of its own across the sheet, and that line has to
  miss these.

  Read from the document rather than from what has been routed so far,
  because a wire has to miss the pins of the wires that come after it too.
  """
  mine = _endpoint_keys(net)
  spots = []
  for other in doc.nets:
    if other is net or other.get("id") == net.get("id"):
      continue
    keys = _endpoint_keys(other)
    if keys & mine:
      # Two wires off one pin are one signal; a dot between them says so
      # truthfully.
      continue
    for endpoint in [other.get("from")] + loads_of(other):
      spot = endpoint_position(doc, endpoint, registry)
      if spot is not None:
        spots.append(spot)
  return spots


def _on_run(point, a, b):
  """True if a point lies on an axis-aligned run, ends included."""
  if abs(a[1] - b[1]) < EPSILON:
    return (abs(point[1] - a[1]) < EPSILON
            and min(a[0], b[0]) - EPSILON <= point[0] <= max(a[0], b[0]) + EPSILON)
  if abs(a[0] - b[0]) < EPSILON:
    return (abs(point[0] - a[0]) < EPSILON
            and min(a[1], b[1]) - EPSILON <= point[1] <= max(a[1], b[1]) + EPSILON)
  return False


def _lands_clear(points, doc, net, load, registry, sheet, keys, terminals):
  """True when a branch that left the wire late lands on nothing already taken.

  Leaving late is only worth doing when the shorter way round is also a clear
  one. Starting in the middle of a wire rather than at a pin changes which
  corridors the search will consider, and on a crowded sheet that can walk the
  branch along another net or across the pin a third one ends at -- both of
  which read as a connection that is not in the file. The shortcut is taken
  when it is clean and the branch is routed from the driving pin when it is
  not, which is the arrangement that was there before.
  """
  if not points or len(points) < 2:
    return False
  exclude = set()
  for endpoint in (net.get("from"), load):
    if isinstance(endpoint, dict) and "cell" in endpoint:
      exclude.add(endpoint["cell"])
  view = sheet.for_net(obstacle_boxes(doc, registry, exclude), keys,
                       net.get("id"))
  bodies = body_boxes(doc, registry, exclude)
  for index in range(len(points) - 1):
    a, b = points[index], points[index + 1]
    # Cells, wires and the pins other wires stop at, in that order: a corridor
    # search that finds nothing clear falls back to a route that crosses
    # things, and a branch leaving late gets its own line across the sheet
    # rather than following the one before it, so it has to be asked.
    if not _leg_clear(a, b, bodies):
      return False
    if abs(a[1] - b[1]) < EPSILON:
      if not view.free(True, a[1], a[0], b[0]):
        return False
    elif abs(a[0] - b[0]) < EPSILON:
      if not view.free(False, a[0], a[1], b[1]):
        return False
    for spot in terminals:
      if _on_run(spot, a, b):
        return False
  return True


def _branch(doc, net, load, start, start_dir, registry, sheet, keys,
            from_pin=True):
  """One path, from the driving pin -- or from a tap on the wire -- to a load.

  `from_pin` is false when the branch leaves the middle of a wire already
  drawn. There is no pin to stand off from there, so it gets no stub.
  """
  end = endpoint_position(doc, load, registry)
  if end is None:
    return []

  waypoints = [(float(p[0]), float(p[1])) for p in load.get("waypoints", [])]

  if not waypoints:
    end_dir = endpoint_direction(doc, load, registry)
    exclude = set()
    for endpoint in (net.get("from"), load):
      if isinstance(endpoint, dict) and "cell" in endpoint:
        exclude.add(endpoint["cell"])
    boxes = obstacle_boxes(doc, registry, exclude)
    others = set(cell.get("id") for cell in doc.cells) - exclude
    view = sheet.for_net(boxes, keys, net.get("id"),
                         body_boxes(doc, registry, others))
    return _clean(_direct_route(
      start, end, start_dir, end_dir, view,
      stub_for(doc, net.get("from"), registry) if from_pin else 0.0,
      stub_for(doc, load, registry)))

  points = [start] + waypoints + [end]
  chain = [points[0]]
  horizontal_first = True
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
  """Every net's branches, in document order.

  Wires are routed one after another and each remembers where it ran, so a
  later wire picks a corridor of its own rather than landing on an earlier
  one. Order therefore matters: the first net stated gets the straightest run.
  """
  registry = registry or default_registry()
  sheet = Sheet()
  routes = []
  for net in doc.nets:
    branches = route(doc, net, registry, sheet)
    keys = _endpoint_keys(net)
    for points in branches:
      sheet.reserve(keys, points, net.get("id"))
    routes.append((net, branches))
  return routes


def segments_of(routes):
  """Every straight run in a drawing, as (net id, a, b).

  Branches of one net are separate paths, so anything looking at the drawing
  as a whole -- junction dots, crossing bridges -- goes through here rather
  than assuming one path per net.
  """
  found = []
  for net, branches in routes:
    net_id = net.get("id")
    for points in branches:
      for index in range(len(points) - 1):
        found.append((net_id, points[index], points[index + 1]))
  return found


def _segments(routes):
  return [(a, b) for _, a, b in segments_of(routes)]


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
  for _, branches in routes:
    for points in branches:
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
  for net_id, a, b in segments_of(routes):
    vertices.add(_key(a))
    vertices.add(_key(b))
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
