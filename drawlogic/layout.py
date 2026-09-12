"""Laying a drawing out from what it is wired to, rather than by hand.

Dropping cells and wiring them gets you a correct drawing and a crooked one.
Making it read well means putting each cell in a column according to how far
along the signal path it sits, ordering the columns so wires cross as little as
possible, and then choosing each cell's height so the pins it connects to line
up -- which is what makes a wire straight.

That is the classic layered graph drawing, and it is the one thing the editor
could not do for you. Four passes:

1. **Rank.** Longest path from the sources, so a cell sits one column right of
   everything that drives it. Feedback loops would make that impossible, so
   the edges that close a loop are found first and left out of the ranking;
   they are drawn as the wires that come back, which is what they are.
2. **Order.** Sweep back and forth taking the median position of each cell's
   neighbours in the next column along. Wires cross when the order in one
   column disagrees with the order in the next, and the median is the standard
   cheap way to make them agree.
3. **Place.** Columns left to right; within a column, each cell at the height
   that makes its incoming wire straight, then pushed apart where two cells
   want the same room.
4. **Fit.** Grow the sheet to hold the result.

Only cells move. Shapes -- bands, captions, dividers -- are left where they
are, because there is no way to know which cell one belongs to; expect to
nudge them after a layout.

Usage:

    from drawlogic import layout

    note = layout.arrange(doc, registry)     # doc is modified in place
    print(note)          # "6 columns, 14 cells, 2 feedback wires"
"""

from . import routing
from .doc import loads_of
from .geometry import corners
from .symbols import default_registry

# Room between columns, and between cells stacked in one column.
GAP_X = 100.0
GAP_Y = 40.0
MARGIN = 90.0

# How many back-and-forth passes the ordering gets. Past about four it stops
# finding anything.
SWEEPS = 4

PORT_IN = ("port_in", "port_inout")
PORT_OUT = ("port_out",)


class Result(object):
  """What a layout did, for the caller to report."""

  def __init__(self, columns, cells, feedback):
    self.columns = columns
    self.cells = cells
    self.feedback = feedback

  def __str__(self):
    parts = ["%d cells in %d columns" % (self.cells, self.columns)]
    if self.feedback:
      parts.append("%d feedback wire%s"
                   % (self.feedback, "" if self.feedback == 1 else "s"))
    return ", ".join(parts)


def arrange(doc, registry=None, gap_x=GAP_X, gap_y=GAP_Y, margin=MARGIN):
  """Lay the drawing out left to right. Modifies `doc` and returns a Result."""
  registry = registry or default_registry()
  cells = [c for c in doc.cells if registry.for_cell(c) is not None]
  if not cells:
    return Result(0, 0, 0)

  _face_forward(cells)
  _forget_waypoints(doc)

  edges, feedback = _edges(doc, cells)
  ranks = _ranks(doc, cells, edges)
  order = _order(cells, edges, ranks)
  _place(doc, registry, cells, edges, ranks, order, gap_x, gap_y)
  _normalise(doc, registry, cells, margin)
  _fit(doc, registry, margin)

  return Result(len(order), len(cells), feedback)


def _face_forward(cells):
  """Turn every cell the way the drawing now reads.

  A mirrored block has its inputs on the east, which in a left-to-right layout
  means every wire into it has to come round the back. Laying a drawing out
  and leaving a block facing backwards is not laying it out.
  """
  for cell in cells:
    cell["rotate"] = 0
    cell["mirror"] = False


def _forget_waypoints(doc):
  """Drop the points wires were told to pass through.

  A waypoint is a coordinate on the old sheet. After everything has moved it
  names a place with nothing at it, and the wire dutifully goes there -- which
  is what turns a laid-out drawing into a drawing with wires wandering off the
  bottom of it.
  """
  for net in doc.nets:
    for load in loads_of(net):
      load["waypoints"] = []


# ---- the graph ----

def _edges(doc, cells):
  """Driver-to-load edges, and how many of them close a feedback loop.

  A loop cannot be ranked -- some cell would have to sit right of itself -- so
  the edges that close one are dropped from the ranking. They are still drawn;
  they are simply not allowed to decide what goes where.
  """
  known = {cell["id"] for cell in cells}
  raw = []
  for net in doc.nets:
    source = net.get("from")
    if not isinstance(source, dict) or "cell" not in source:
      continue
    # A net drives any number of loads, and each one is an edge: what decides
    # where a cell goes is what reaches it, not which net it arrived on.
    for target in loads_of(net):
      if "cell" not in target or source["cell"] == target["cell"]:
        continue
      if source["cell"] not in known or target["cell"] not in known:
        continue
      raw.append((source["cell"], target["cell"], source.get("pin"),
                  target.get("pin")))

  back = _back_edges([(a, b) for a, b, _, _ in raw])
  forward = [e for e in raw if (e[0], e[1]) not in back]
  return forward, len(raw) - len(forward)


def _back_edges(pairs):
  """Edges that point at a cell already open above them in a depth-first walk.

  Those are the ones closing a loop. Which edge of a loop gets picked depends
  on where the walk starts, so cells are visited in document order to keep the
  answer the same every time.
  """
  outgoing = {}
  nodes = []
  for a, b in pairs:
    if a not in outgoing:
      outgoing[a] = []
      nodes.append(a)
    if b not in outgoing:
      outgoing[b] = []
      nodes.append(b)
    outgoing[a].append(b)

  OPEN, DONE = 1, 2
  state = {}
  back = set()
  for start in nodes:
    if state.get(start):
      continue
    stack = [(start, iter(outgoing[start]))]
    state[start] = OPEN
    while stack:
      node, children = stack[-1]
      advanced = False
      for child in children:
        if state.get(child) == OPEN:
          back.add((node, child))
        elif not state.get(child):
          state[child] = OPEN
          stack.append((child, iter(outgoing[child])))
          advanced = True
          break
      if not advanced:
        state[node] = DONE
        stack.pop()
  return back


def _ranks(doc, cells, edges):
  """Which column each cell belongs in: one right of everything driving it."""
  rank = {cell["id"]: 0 for cell in cells}
  incoming = {cell["id"]: [] for cell in cells}
  outgoing = {cell["id"]: [] for cell in cells}
  for source, target, _, _ in edges:
    incoming[target].append(source)
    outgoing[source].append(target)

  # Longest path, settled by repeated relaxation. The graph has no loops left,
  # so this terminates in at most one pass per cell.
  for _ in range(len(cells)):
    changed = False
    for cell in cells:
      cell_id = cell["id"]
      for source in incoming[cell_id]:
        if rank[source] + 1 > rank[cell_id]:
          rank[cell_id] = rank[source] + 1
          changed = True
    if not changed:
      break

  # Output ports belong on the right edge, not one step past whatever happens
  # to drive them, or they stagger.
  widest = max(rank.values()) if rank else 0
  for cell in cells:
    if cell.get("type") in PORT_OUT and not outgoing[cell["id"]]:
      rank[cell["id"]] = widest
  return rank


def _order(cells, edges, ranks):
  """The cells in each column, top to bottom, ordered to cut wire crossings.

  Two wires cross when the order of their ends disagrees between one column
  and the next. Taking the median position of a cell's neighbours and sorting
  by it makes the two agree, and repeating it back and forth settles.
  """
  columns = {}
  for cell in cells:
    columns.setdefault(ranks[cell["id"]], []).append(cell["id"])
  # Document order to start with, so a layout is the same every time.
  order = [columns.get(index, []) for index in range(max(columns) + 1)]

  neighbours_left = {cell["id"]: [] for cell in cells}
  neighbours_right = {cell["id"]: [] for cell in cells}
  for source, target, _, _ in edges:
    neighbours_left[target].append(source)
    neighbours_right[source].append(target)

  for sweep in range(SWEEPS):
    forward = sweep % 2 == 0
    indices = range(1, len(order)) if forward else range(len(order) - 2, -1, -1)
    for index in indices:
      side = neighbours_left if forward else neighbours_right
      other = order[index - 1] if forward else order[index + 1]
      position = {cell_id: place for place, cell_id in enumerate(other)}
      order[index] = _by_median(order[index], side, position)
  return order


def _by_median(column, side, position):
  """Sort one column by where each cell's neighbours sit in the next one."""
  keyed = []
  for place, cell_id in enumerate(column):
    spots = sorted(position[n] for n in side[cell_id] if n in position)
    if spots:
      middle = spots[len(spots) // 2] if len(spots) % 2 else (
        (spots[len(spots) // 2 - 1] + spots[len(spots) // 2]) / 2.0)
    else:
      # Nothing to line up with, so it keeps the place it had.
      middle = place
    keyed.append((middle, place, cell_id))
  keyed.sort()
  return [cell_id for _, _, cell_id in keyed]


# ---- coordinates ----

def _headroom(cell):
  """Room above a cell for the instance name drawn there.

  Without it a column packs cells tight enough that each name lands on the one
  above, which is a tidy-looking layout that cannot be read.
  """
  return 20.0 if cell.get("label") else 0.0


def _box(registry, doc, cell):
  """A cell's footprint as (x0, y0, width, height)."""
  symbol = registry.for_cell(cell)
  matrix = symbol.matrix_for(cell, doc.symbol_scale)
  points = [matrix.apply(px, py)
            for px, py in corners(0, 0, symbol.width, symbol.height)]
  xs = [p[0] for p in points]
  ys = [p[1] for p in points]
  return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _pin_offset(registry, doc, cell, pin_name):
  """Where a pin sits relative to the cell's own x and y.

  Taken from the cell where it stands, so it survives rotation and mirroring
  without this having to know about either.
  """
  symbol = registry.for_cell(cell)
  spot = symbol.pin_position(cell, pin_name, doc.symbol_scale)
  if spot is None:
    return (0.0, 0.0)
  return (spot[0] - cell["x"], spot[1] - cell["y"])


def _place(doc, registry, cells, edges, ranks, order, gap_x, gap_y):
  by_id = {cell["id"]: cell for cell in cells}
  boxes = {cell["id"]: _box(registry, doc, cell) for cell in cells}

  x = 0.0
  for column in order:
    width = max([boxes[c][2] for c in column] or [0])
    for cell_id in column:
      cell = by_id[cell_id]
      box = boxes[cell_id]
      # Centred in its column, so a narrow gate does not sit against the left
      # edge of a column some wide block set.
      cell["x"] = x + (width - box[2]) / 2.0 + (cell["x"] - box[0])
    x += width + gap_x

  # Wires arriving from an earlier column: a cell cannot line up with
  # something that has not been placed yet.
  arriving = {cell["id"]: [] for cell in cells}
  for source, target, source_pin, target_pin in edges:
    if ranks[source] < ranks[target]:
      arriving[target].append((ranks[target] - ranks[source], source,
                               source_pin, target_pin))

  for column in order:
    desired = {}
    for cell_id in column:
      cell = by_id[cell_id]
      # One wire dead straight beats two half-straight, so the cell follows a
      # single driver rather than the average of them: the nearest column
      # first, and within that the first net stated.
      best = None
      for gap, source, source_pin, target_pin in arriving[cell_id]:
        if best is not None and gap >= best[0]:
          continue
        driver = by_id[source]
        driver_y = driver["y"] + _pin_offset(registry, doc, driver, source_pin)[1]
        best = (gap, driver_y - _pin_offset(registry, doc, cell, target_pin)[1])
      if best is not None:
        desired[cell_id] = best[1]
    _stack(by_id, boxes, column, desired, gap_y)


def _stack(by_id, boxes, column, desired, gap_y):
  """Give one column its heights: what each cell wants, then pushed apart.

  A cell with a wire to follow goes where that wire wants it. One with nothing
  to follow keeps the place the ordering pass gave it, slotted in after.
  """
  following = sorted((desired[c], index, c)
                     for index, c in enumerate(column) if c in desired)
  loose = [c for c in column if c not in desired]

  bottom = None
  for cell_id in [c for _, _, c in following] + loose:
    cell = by_id[cell_id]
    box = boxes[cell_id]
    offset = cell["y"] - box[1]
    want = desired.get(cell_id)
    if want is None:
      want = (bottom if bottom is not None else 0.0) + offset
    if bottom is not None:
      want = max(want, bottom + offset + _headroom(cell))
    cell["y"] = want
    bottom = (want - offset) + box[3] + gap_y


def _normalise(doc, registry, cells, margin):
  """Shift every cell so the drawing starts at the margin.

  Done once at the end rather than by clamping each column to the margin as it
  is placed -- clamping the first cell in a column moves it off the row its
  wire wanted, which is the one thing this is all for.
  """
  boxes = [_box(registry, doc, cell) for cell in cells]
  left = min(box[0] for box in boxes)
  top = min(box[1] - _headroom(cell) for box, cell in zip(boxes, cells))
  for cell in cells:
    cell["x"] += margin - left
    cell["y"] += margin - top


def _fit(doc, registry, margin):
  """Size the sheet to what is actually drawn, wires included.

  Both ways: a layout that leaves half a sheet of white space below it reads
  as a drawing with something missing.
  """
  box = doc.content_bbox(registry)
  if box is None:
    return
  right = box[0] + box[2]
  bottom = box[1] + box[3]
  # Wires can reach past every cell -- a feedback path returning underneath
  # the row it came from, for one -- so the sheet has to hold them too.
  for _, _a, b in routing.segments_of(routing.route_all(doc, registry)):
    right = max(right, b[0])
    bottom = max(bottom, b[1])
  doc.canvas["width"] = int(right + margin)
  doc.canvas["height"] = int(bottom + margin)
