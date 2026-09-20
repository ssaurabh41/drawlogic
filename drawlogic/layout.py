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

from . import drc
from . import routing
from .doc import loads_of
from .geometry import corners
from .symbols import default_registry

# Room between columns, and between cells stacked in one column. The numbers
# themselves are drawing rules, so they live in drc.py with the rest.
GAP_X = drc.CELL_GAP_X
GAP_Y = drc.CELL_GAP_Y
MARGIN = drc.SHEET_MARGIN

# How many back-and-forth passes the ordering gets. Past about four it stops
# finding anything.
SWEEPS = 4

PORT_IN = ("port_in", "port_inout")
PORT_OUT = ("port_out",)
# Every cell that stands for a connection off the sheet. Which side of it a
# given one belongs on is `_flow`'s question, not the type name's: an inout
# port is an input or an output depending on which way its connector faces.
PORTS = PORT_IN + PORT_OUT


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

  # drc.CELL_MIN_GAP is documented as the least space allowed between any
  # two cells, so it has to hold even when a caller passes a smaller gap_x or
  # gap_y of its own -- otherwise it is a number nobody reads.
  gap_x = max(gap_x, drc.CELL_MIN_GAP)
  gap_y = max(gap_y, drc.CELL_MIN_GAP)

  _face_forward(cells)
  _forget_waypoints(doc)
  # The search below routes the drawing dozens of times to compare
  # arrangements, and it has to do that the same way every time: with the flag
  # left as the file happened to carry it, laying out a drawing a second time
  # searched differently from the first and settled somewhere else. So the
  # search always runs with wires forking early, and `_choose_forking` decides
  # the question once at the end, on the arrangement that won.
  doc.canvas.pop("forkLate", None)

  edges, feedback = _edges(doc, registry, cells)
  ranks = _ranks(doc, registry, cells, edges)

  # Two orderings, and the drawing itself decides. Following a wire through
  # the columns it skips (see _span_chain) helps some drawings a great deal
  # and makes others worse, which is not something the algorithm can know in
  # advance -- so lay the drawing out both ways and keep the one that
  # measures better. Layout is not a gesture; it can afford to be tried twice.
  # Four candidates, and the drawing itself decides between them.
  #
  # `spans` is whether to follow a wire through the columns it skips, which
  # helps some drawings a great deal and makes others worse. `settle` is
  # whether to place a cell with nothing arriving by the wire that leaves it
  # instead -- which straightens the wire out of every input port, and is
  # worth a lot on a flat drawing of gates and close to nothing on a sheet of
  # big hierarchy blocks, where dragging a port to line up with one pin of a
  # twelve-pin block spreads its whole column out.
  #
  # Neither is something the algorithm can know in advance, so it lays the
  # drawing out each way and keeps the one that measures better. Layout is not
  # a gesture; it can afford to be tried four times.
  best = None
  for spans in (True, False):
    for settle in (True, False):
      order = _order(cells, edges, ranks, spans=spans)
      _place(doc, registry, cells, edges, ranks, order, gap_x, gap_y, settle)
      _normalise(doc, registry, cells, margin)
      score = _score(doc, registry)
      if best is None or score < best[0]:
        best = (score, order, settle)

  # Then improve the winner by hand, so to speak: the median ordering is a
  # good guess at which cell goes where in a column, and a good guess is not
  # the same as the best arrangement. Swapping two neighbours and measuring is.
  order = _refine(doc, registry, cells, edges, ranks, best[1],
                  gap_x, gap_y, margin, best[2])
  _fit(doc, registry, margin)
  _choose_forking(doc, registry)

  return Result(len(order), len(cells), feedback)


def _choose_forking(doc, registry):
  """Route the finished drawing both ways and keep the wires that measure better.

  A wire with several loads can give each one its own way across the sheet, or
  it can run as one trunk that divides near the pins it serves. The second is
  shorter on most drawings and puts the junction dot beside the load rather
  than beside the driver, which is how a schematic is read -- but not always:
  a branch that leaves late takes a line of its own, and every wire routed
  after it then has to dodge that line instead of the old one. On the examples
  here that comes out ahead three times, level once and behind once, and
  nothing short of routing the drawing says which it will be.

  So it is asked rather than assumed, once, on the arrangement that won. Two
  extra routing passes against the dozens `_refine` has already done, and the
  answer is written into the drawing so that every later render -- the canvas,
  the exporter, the checker -- draws the wires the layout measured.
  """
  best = None
  for late in (False, True):
    if late:
      doc.canvas["forkLate"] = True
    else:
      doc.canvas.pop("forkLate", None)
    score = _score(doc, registry)
    if best is None or score < best[0] - EPSILON:
      best = (score, late)
  # Absent rather than false, so a drawing that gains nothing from this is
  # written exactly as it would have been before it existed.
  if best[1]:
    doc.canvas["forkLate"] = True
  else:
    doc.canvas.pop("forkLate", None)


# A ceiling on how many times to sweep every column looking for a swap worth
# making, not a target: the loop stops as soon as a sweep finds nothing, so on
# a drawing that settles in one pass the rest cost nothing at all.
#
# Four is where the examples stop improving -- six and eight give byte-for-byte
# the same drawings. Each sweep re-routes once per candidate swap, which puts
# the slowest example at about half a second for the whole button.
REFINE_SWEEPS = 4


def _refine(doc, registry, cells, edges, ranks, order, gap_x, gap_y, margin,
            settle=True):
  """Swap neighbours within a column while that makes the drawing better.

  Ordering by median neighbour position settles quickly and reads well, but it
  is answering "which cell is roughly where" rather than "is this the best
  arrangement". Two cells in one column can often be exchanged for shorter
  wires, and nothing in the median pass would ever try it -- reported as
  columns that look tidy with wires running much further than they need to.

  Every candidate is measured by actually routing it, so the answer is about
  the drawing rather than about a proxy for it. Leaves the document holding
  the arrangement it returns.
  """
  def lay_out(candidate):
    _place(doc, registry, cells, edges, ranks, candidate, gap_x, gap_y, settle)
    _normalise(doc, registry, cells, margin)
    return _score(doc, registry)

  best = lay_out(order)
  for _sweep in range(REFINE_SWEEPS):
    improved = False
    for column in range(len(order)):
      for index in range(len(order[column]) - 1):
        candidate = [list(group) for group in order]
        candidate[column][index], candidate[column][index + 1] = (
          candidate[column][index + 1], candidate[column][index])
        score = lay_out(candidate)
        if score < best - EPSILON:
          best, order, improved = score, candidate, True
    if not improved:
      break

  lay_out(order)
  return order


# What a layout is trying to make small, priced against each other in units of
# wire. These are judgements about reading a drawing, not measurements, and
# they are here rather than in drc.py because nothing outside the layout obeys
# them: they decide between two arrangements, they do not rule any drawing out.

# A crossing costs about as much legibility as this much wire. Roughly a small
# gate and a half: the drawing is better for losing a crossing even if the
# wires grow by that much to do it.
#
# This is also the price of a crossing bridge, because they are the same
# thing. A bridge is what a crossing is drawn as -- measured across the seven
# examples, crossings and drawn bridges track each other closely (37 and 37 on
# soc_top, 27 and 26 on spi_master). Costing both would be counting one fault
# twice and calling it two rules.
CROSSING_COST = 320.0

# How much a drawing pays for the room it takes, per unit of width plus
# height. Small on purpose: a sprawling drawing is worth tightening, but not
# at the price of the crossings and detours that cramming it would cost. At
# this weight a drawing has to save about two gates' worth of spread to be
# worth one extra crossing.
SPREAD_COST = 0.35

# What a DRC failure costs the arrangement that produced it.
#
# The score used to measure crossings, length and spread and nothing else --
# scoring a drawing by a proxy for legibility while the project already had a
# checker that measures legibility directly. It shipped arrangements holding
# wire-shorts quite happily, because two nets lying on top of each other cross
# nothing, add no length and take no room.
#
# An error is the drawing saying something untrue, so it outranks a warning,
# which is a judgement about spacing. A warning is priced near a crossing:
# both are one thing a reader has to work past.
#
# Measured over all seven examples, against the same layout with no DRC term:
#
#     errors     13 -> 11
#     warnings   63 -> 49
#     crossings 112 -> 118
#     length     +2%
#
# Two things worth knowing before tuning these. First, it is the *warning*
# weight doing that work: anywhere from 120 to 320 gives identical drawings,
# and so does dropping ERROR_COST to zero. The error weight is here because an
# untrue drawing should outrank an ugly one on principle, not because these
# examples demonstrate it. Second, pricing errors very high backfires -- at
# 4000 the layout chases shorts it cannot remove (they come from the router
# running out of corridor, not from cell order) and pays for the chase
# elsewhere: 10 errors but 75 warnings and 134 crossings, a worse drawing by
# every other measure.
ERROR_COST = 1000.0
WARNING_COST = 150.0

EPSILON = 1e-9


def _score(doc, registry):
  """How hard the laid-out drawing is to read. Lower is better.

  Four things a reader pays for. Every crossing is a moment of doubt about
  which line is which, and a bridge drawn over it is the same doubt with a
  bump on it. Every extra unit of wire is distance the eye has to travel.
  Every extra unit of sheet is drawing that has to be scrolled or shrunk to be
  seen at all. And every DRC failure is the drawing either saying something
  untrue or being harder to read than it needs to be -- which is the question
  this score is asking, so there is no reason to ask it a second, weaker way.

  Measured by routing and checking the drawing, not by a proxy for it, so what
  is scored is what would be exported.
  """
  segments = list(routing.segments_of(routing.route_all(doc, registry)))
  length = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for _, a, b in segments)

  box = doc.content_bbox(registry)
  spread = (box[2] + box[3]) if box else 0.0

  errors = warnings = 0
  for violation in drc.check(doc, registry):
    if violation.level == "error":
      errors += 1
    else:
      warnings += 1

  return (_crossings(segments) * CROSSING_COST
          + length
          + spread * SPREAD_COST
          + errors * ERROR_COST
          + warnings * WARNING_COST)


def _crossings(segments):
  """How many times one wire crosses another it is not connected to."""
  total = 0
  for index, (net_a, a0, a1) in enumerate(segments):
    a_flat = abs(a0[1] - a1[1]) < 1e-6
    for net_b, b0, b1 in segments[index + 1:]:
      if net_a == net_b or (abs(b0[1] - b1[1]) < 1e-6) == a_flat:
        continue
      flat, upright = ((a0, a1), (b0, b1)) if a_flat else ((b0, b1), (a0, a1))
      if (min(flat[0][0], flat[1][0]) < upright[0][0] < max(flat[0][0], flat[1][0])
          and min(upright[0][1], upright[1][1]) < flat[0][1]
          < max(upright[0][1], upright[1][1])):
        total += 1
  return total


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

def _flow(doc, registry, cell, pin_name):
  """Which way the signal runs at this pin: "out" if it drives, "in" if it takes.

  A net records which pin was clicked first, not which way the signal goes.
  Someone drawing a schematic clicks the flip-flop's D and then the gate that
  feeds it about as often as the other way round, and both are the same
  circuit -- so the order a wire was drawn in cannot be what decides which
  column a cell lands in. The pins already know: every symbol declares a
  direction for each of its pins, and that is the thing to ask.

  A pin that declares `in` or `out` is taken at its word. `inout` is the
  interesting case, and it is also what a pin that never said anything gets
  (see symbols.Symbol), so a custom symbol drawn without directions lands
  here rather than being refused. Those are settled by which side of the cell
  the pin comes out of: a connector on the right drives, one anywhere else
  takes. That is not a new convention -- it is the one the built-in library
  already follows, every declared `out` sitting on its symbol's right edge
  and every declared `in` somewhere else -- so an undeclared pin gets read
  the way the drawing already looks.

  Asked of the placed cell rather than of the symbol, so mirroring a port
  turns it round. That is the whole control the rule needs: an inout port is
  an input where its connector faces right and an output where it faces left.
  """
  symbol = registry.for_cell(cell)
  if symbol is None:
    return None
  pin = symbol.pin(pin_name)
  if pin is None:
    return None
  if pin["dir"] in ("in", "out"):
    return pin["dir"]
  spot = symbol.pin_position(cell, pin_name, doc.symbol_scale)
  if spot is None:
    return None
  left, _, width, _ = _box(registry, doc, cell)
  return "out" if spot[0] > left + width / 2.0 else "in"


def _edges(doc, registry, cells):
  """Driver-to-load edges, and how many of them close a feedback loop.

  A loop cannot be ranked -- some cell would have to sit right of itself -- so
  the edges that close one are dropped from the ranking. They are still drawn;
  they are simply not allowed to decide what goes where.

  Which end drives is asked of the pins rather than of the net (see `_flow`),
  so a wire drawn from the load back to its driver still ranks the way the
  circuit runs. A branch whose ends both take, or both drive, says nothing
  about order at all, and is left out of the ranking rather than obeyed
  backwards: it is still drawn, and `validate` still has something to say
  about it, but a wire with no driver is not a reason to put one cell to the
  right of another.
  """
  known = {cell["id"] for cell in cells}
  by_id = {cell["id"]: cell for cell in cells}
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
      driver, load = source["cell"], target["cell"]
      driver_pin, load_pin = source.get("pin"), target.get("pin")
      drives = _flow(doc, registry, by_id[driver], driver_pin)
      takes = _flow(doc, registry, by_id[load], load_pin)
      if drives == "in" and takes == "out":
        driver, load = load, driver
        driver_pin, load_pin = load_pin, driver_pin
      elif drives is not None and drives == takes:
        continue
      raw.append((driver, load, driver_pin, load_pin))

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


def _ranks(doc, registry, cells, edges):
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
  # to drive them, or they stagger. An input port needs no such help: its pin
  # drives, so nothing can arrive at it and it is already in column zero.
  #
  # Which ports those are is asked of the pins rather than of the type name,
  # so an inout port whose connector faces left -- an output port in all but
  # name -- goes to the edge with the rest of them.
  widest = max(rank.values()) if rank else 0
  for cell in cells:
    if cell.get("type") not in PORTS or outgoing[cell["id"]]:
      continue
    symbol = registry.for_cell(cell)
    names = symbol.pin_names() if symbol is not None else []
    if names and all(_flow(doc, registry, cell, name) == "in"
                     for name in names):
      rank[cell["id"]] = widest
  return rank


def _span_chain(edges, ranks):
  """Stand-ins for wires that skip a column, and the edges linking them.

  A wire from column 0 to column 2 is invisible to the ordering sweep: the
  sweep only ever compares a column with the one beside it, so neither end
  sees the other and both keep whatever place they started in. That is why an
  input port feeding something two columns along used to be left at the
  bottom of the sheet while the cell it drives sat at the top.

  The fix is the standard one: give the wire a stand-in in each column it
  passes through, so it becomes a chain of single-column steps the sweep can
  follow. The stand-ins are ordering fiction -- they are dropped before
  anything is placed -- but while they exist they pull both real ends into
  line with the path between them.
  """
  linked = []
  extra = {}
  for index, (source, target, _, _) in enumerate(edges):
    low, high = ranks[source], ranks[target]
    step = 1 if high >= low else -1
    if abs(high - low) <= 1:
      linked.append((source, target))
      continue
    previous = source
    for rank in range(low + step, high, step):
      stand_in = "\x00span%d@%d" % (index, rank)
      extra[stand_in] = rank
      linked.append((previous, stand_in))
      previous = stand_in
    linked.append((previous, target))
  return linked, extra


def _order(cells, edges, ranks, spans=True):
  """The cells in each column, top to bottom, ordered to cut wire crossings.

  Two wires cross when the order of their ends disagrees between one column
  and the next. Taking the median position of a cell's neighbours and sorting
  by it makes the two agree, and repeating it back and forth settles.

  Wires that skip a column are followed through stand-ins -- see _span_chain
  -- so a cell is pulled into line with everything it reaches, not only with
  whatever happens to sit in the column next door.
  """
  linked, extra = (_span_chain(edges, ranks) if spans
                   else ([(s, t) for s, t, _, _ in edges], {}))
  spread = dict(ranks)
  spread.update(extra)

  columns = {}
  for cell in cells:
    columns.setdefault(ranks[cell["id"]], []).append(cell["id"])
  for stand_in, rank in extra.items():
    columns.setdefault(rank, []).append(stand_in)
  # Document order to start with, so a layout is the same every time.
  order = [columns.get(index, []) for index in range(max(columns) + 1)]

  neighbours_left = {key: [] for key in spread}
  neighbours_right = {key: [] for key in spread}
  for source, target in linked:
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

  # Median ordering is a guess; this is the cheap correction to it.
  _transpose(order, neighbours_left, neighbours_right)

  # The stand-ins have done their work; only real cells get placed.
  return [[cell_id for cell_id in column if not cell_id.startswith("\x00")]
          for column in order]


# How many times to sweep the transpose pass. It settles quickly -- each pass
# only accepts swaps that strictly reduce crossings, so it cannot cycle -- and
# four matches the median sweeps it follows.
TRANSPOSE_SWEEPS = 4


def _pair_crossings(above, below, side, position):
  """Crossings between two neighbouring cells' wires, with `above` on top.

  Counted from the order alone rather than by routing anything: a wire from
  `above` crosses one from `below` exactly when it lands lower in the next
  column. That makes this thousands of times cheaper than laying the drawing
  out and measuring it, which is what lets it run over every adjacent pair
  instead of a chosen few.
  """
  upper = [position[n] for n in side[above] if n in position]
  lower = [position[n] for n in side[below] if n in position]
  if not upper or not lower:
    return 0
  return sum(1 for u in upper for l in lower if u > l)


def _transpose(order, neighbours_left, neighbours_right):
  """Swap neighbouring cells while that removes crossings.

  The median pass gets each column roughly right and then stops: it moves a
  cell to the middle of its neighbours, which is a good guess and not an
  answer. This is the cheap repair for what the guess leaves behind -- the
  classic companion to median ordering -- and it is worth having for a reason
  beyond tidiness.

  Two wires that cross in a column gap can be impossible to draw correctly.
  Where one net leaves a row and another arrives at the same row, their
  horizontal legs sit at the same height, and the only way to keep them apart
  is for the leaving net's corridor to be left of the arriving one's -- which
  the reverse pair demands in reverse. A fully crossed pair has no answer at
  all, and the router resolves it by drawing one wire on another, which is
  the `wire-short` these drawings are full of. So every crossing removed here
  is a chance for that removed downstream.
  """
  for _sweep in range(TRANSPOSE_SWEEPS):
    improved = False
    for index, column in enumerate(order):
      if len(column) < 2:
        continue
      left = {cell_id: place for place, cell_id
              in enumerate(order[index - 1])} if index else {}
      right = {cell_id: place for place, cell_id
               in enumerate(order[index + 1])} if index + 1 < len(order) else {}
      for position in range(len(column) - 1):
        one, two = column[position], column[position + 1]
        now = (_pair_crossings(one, two, neighbours_left, left)
               + _pair_crossings(one, two, neighbours_right, right))
        swapped = (_pair_crossings(two, one, neighbours_left, left)
                   + _pair_crossings(two, one, neighbours_right, right))
        if swapped < now:
          column[position], column[position + 1] = two, one
          improved = True
    if not improved:
      return


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
  return drc.LABEL_HEADROOM if cell.get("label") else 0.0


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


def _place(doc, registry, cells, edges, ranks, order, gap_x, gap_y,
           settle=True):
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

  if settle:
    # Fresh boxes: the pass above moved every cell, and _box reports absolute
    # coordinates, so the ones measured at the top of this function describe
    # where the cells used to be.
    _settle_followers(doc, registry, by_id,
                      {c["id"]: _box(registry, doc, c) for c in by_id.values()},
                      order, ranks, edges, gap_y)


def _settle_followers(doc, registry, by_id, boxes, order, ranks, edges, gap_y):
  """Place the cells that had nothing arriving by what leaves them instead.

  The pass above puts each cell where its incoming wire wants it, which says
  nothing at all about a cell with no incoming wire -- an input port, almost
  always. Those kept whatever height the ordering pass happened to give them,
  so a port would be packed neatly against its neighbours while the wire to
  the gate it feeds bent twice to get there. Reported as exactly that: a port
  placed to save room, at the cost of a long wire.

  A port drives something, so there is a straight line to aim for; it is just
  in the other direction. Left to right, because by the time a column is
  reconsidered the column it feeds has already been placed.
  """
  leaving = {cell_id: [] for cell_id in by_id}
  for source, target, source_pin, target_pin in edges:
    if ranks[source] < ranks[target]:
      leaving[source].append((ranks[target] - ranks[source], target,
                              source_pin, target_pin))

  for column in order:
    desired = {}
    settling = False
    for cell_id in column:
      cell = by_id[cell_id]
      arrived = any(ranks[s] < ranks[cell_id]
                    for s, t, _sp, _tp in edges if t == cell_id)
      if arrived:
        # Already placed by what feeds it; leave that alone.
        desired[cell_id] = cell["y"]
        continue
      best = None
      for gap, target, source_pin, target_pin in leaving[cell_id]:
        if best is not None and gap >= best[0]:
          continue
        load = by_id.get(target)
        if load is None:
          continue
        load_y = load["y"] + _pin_offset(registry, doc, load, target_pin)[1]
        best = (gap, load_y - _pin_offset(registry, doc, cell, source_pin)[1])
      if best is None:
        desired[cell_id] = cell["y"]
      else:
        desired[cell_id] = best[1]
        settling = True
    if settling:
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

  The instance name counts as part of the cell here. It is centred on the body
  and drawn above it, so a name wider than its cell reaches past it on three
  sides; measuring the body alone left the name hanging over the edge of the
  sheet, where it was clipped.
  """
  from . import render_svg

  boxes = [_box(registry, doc, cell) for cell in cells]
  lefts = []
  tops = []
  for box, cell in zip(boxes, cells):
    written = render_svg.cell_label_box(registry.for_cell(cell), cell,
                                        doc.symbol_scale, doc.font_scale)
    lefts.append(min(box[0], written[0]) if written else box[0])
    # _headroom is what the stacking reserved; the drawn name may want more.
    plain = box[1] - _headroom(cell)
    tops.append(min(plain, written[1]) if written else plain)

  left = min(lefts)
  top = min(tops)
  for cell in cells:
    cell["x"] += margin - left
    cell["y"] += margin - top


def _fit(doc, registry, margin):
  """Size the sheet to what is actually drawn, wires included.

  Both ways: a layout that leaves half a sheet of white space below it reads
  as a drawing with something missing.
  """
  # content_bbox routes the wires itself, so it already covers the feedback
  # path that returns underneath the row it came from. It did not always --
  # this function used to walk the segments separately to make up for it.
  box = doc.content_bbox(registry)
  if box is None:
    return
  doc.canvas["width"] = int(box[0] + box[2] + margin)
  doc.canvas["height"] = int(box[1] + box[3] + margin)
