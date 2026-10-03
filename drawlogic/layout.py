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

import json
import math

from . import drc
from . import routing
from .doc import Document, loads_of, repeated_ids
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

# A very long chain -- a 32-bit shift register is 66 columns and 11,000
# units wide -- is wrapped onto rows, like text onto lines. Only a very long
# one: a drawing needs at least this many columns and this much width before
# it is wrapped, so every ordinary drawing is laid out exactly as before.
# The widest drawing in examples/ and benchmarks/ is 19 columns and 3,300
# units.
WRAP_COLUMNS = 24
WRAP_WIDTH = 3 * drc.SHEET_W
# The shape the wrapped rows aim for, width over height: the sheet's own.
WRAP_ASPECT = drc.SHEET_W / drc.SHEET_H

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


def arrange(doc, registry=None, gap_x=GAP_X, gap_y=GAP_Y, margin=MARGIN,
            only=None):
  """Lay the drawing out left to right. Modifies `doc` and returns a Result.

  `only` names the cells to arrange, and a cell whose `pinned` is true is
  never moved. With either, the chosen cells are laid out as a group of their
  own -- see _arrange_part -- and everything else stays exactly where it is.
  """
  registry = registry or default_registry()
  repeated = repeated_ids(doc)
  if repeated:
    raise ValueError("ids must be unique to lay a drawing out: %s is used "
                     "more than once" % ", ".join(repeated))
  chosen = set(c.get("id") for c in doc.cells
               if (only is None or c.get("id") in only) and not c.get("pinned"))
  if len(chosen) < len(doc.cells):
    return _arrange_part(doc, registry, chosen, gap_x, gap_y, margin)
  return _arrange_all(doc, registry, gap_x, gap_y, margin)


def _arrange_part(doc, registry, chosen, gap_x, gap_y, margin):
  """Lay out some cells and leave the rest alone.

  The chosen cells, and the wires wholly between them, are laid out as a
  drawing of their own; the group then goes back where those cells were,
  moved down just far enough to clear every cell that stayed. A wire from the
  group to the rest has nothing to say about arrangement inside the group,
  so it is left to the router; its hand-drawn waypoints are dropped, because
  a point chosen for where the cells used to be now means nothing.
  """
  moving = [c for c in doc.cells
            if c.get("id") in chosen and registry.for_cell(c) is not None]
  if not moving:
    return Result(0, 0, 0)
  staying = [c for c in doc.cells
             if c.get("id") not in chosen and registry.for_cell(c) is not None]

  def cells_of(net):
    return set(end.get("cell") for end in [net.get("from")] + loads_of(net)
               if isinstance(end, dict) and "cell" in end)

  inner = [net for net in doc.nets if cells_of(net) and cells_of(net) <= chosen]
  for net in doc.nets:
    if cells_of(net) & chosen:
      for load in loads_of(net):
        load["waypoints"] = []

  was = _extent(registry, doc, moving)
  canvas = json.loads(json.dumps(doc.canvas))
  canvas.pop("forkLate", None)
  part = Document({"format": doc.data.get("format"),
                   "version": doc.data.get("version"),
                   "title": doc.title, "canvas": canvas,
                   "cells": moving, "nets": inner, "shapes": [],
                   "groups": []}, doc.path)
  result = _arrange_all(part, registry, gap_x, gap_y, margin)

  now = _extent(registry, doc, moving)
  dx, dy = was[0] - now[0], was[1] - now[1]
  fixed = [_box(registry, doc, c) for c in staying]
  step = max(drc.PIN_GRID, 1.0)
  for _attempt in range(2000):
    if not any(_near(_box(registry, doc, c), dx, dy, box)
               for c in moving for box in fixed):
      break
    dy += step
  for cell in moving:
    cell["x"] += dx
    cell["y"] += dy

  needed = doc.content_bbox(registry)
  if needed is not None:
    doc.canvas["width"] = max(doc.canvas.get("width", 0),
                              int(needed[0] + needed[2] + margin))
    doc.canvas["height"] = max(doc.canvas.get("height", 0),
                               int(needed[1] + needed[3] + margin))
  return result


def _extent(registry, doc, cells):
  boxes = [_box(registry, doc, c) for c in cells]
  return (min(b[0] for b in boxes), min(b[1] for b in boxes))


def _near(box, dx, dy, other, gap=drc.CELL_MIN_GAP):
  """True if `box`, moved by (dx, dy), comes within `gap` of `other`."""
  return not (box[0] + dx + box[2] + gap <= other[0]
              or other[0] + other[2] + gap <= box[0] + dx
              or box[1] + dy + box[3] + gap <= other[1]
              or other[1] + other[3] + gap <= box[1] + dy)


def _arrange_all(doc, registry, gap_x, gap_y, margin):
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
  top_at = _below_headings(doc, registry, cells, margin)

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
      _normalise(doc, registry, cells, margin, top_at)
      score = _score(doc, registry, margin)
      if best is None or score < best[0]:
        best = (score, order, settle)

  # Then improve the winner by hand, so to speak: the median ordering is a
  # good guess at which cell goes where in a column, and a good guess is not
  # the same as the best arrangement. Swapping two neighbours and measuring is.
  # Whether wires share a trunk changes the drawing a great deal, so it is
  # settled once on the arrangement about to be refined and the swaps are
  # measured with it -- they were measured with trunks off, and the answer
  # then changed under them at the end, sometimes for the worse.
  _place(doc, registry, cells, edges, ranks, best[1], gap_x, gap_y, best[2])
  _normalise(doc, registry, cells, margin, top_at)
  _choose_forking(doc, registry)
  order = _refine(doc, registry, cells, edges, ranks, best[1],
                  gap_x, gap_y, margin, best[2], top_at)
  _level_ports(doc, registry, cells, margin, top_at)
  _fit(doc, registry, margin)
  # Onto the grid first, because moving a cell changes which way its wires
  # want to fork, and then the forking, on the arrangement that is staying.
  _settle_on_grid(doc, registry, margin)
  _choose_forking(doc, registry)

  return Result(len(order), len(cells), feedback)


def _settle_on_grid(doc, registry, margin):
  """Round the finished arrangement onto the grid, where that is safe to do.

  Placing works in real numbers -- a column's width is averaged and a cell is
  centred in it -- so cells come to rest on values like 113.48. Nothing
  downstream minds, but the person who presses the button next does: a drag
  snaps to the grid, and a grid the drawing is no longer on cannot line
  anything up with anything.

  Rounding is only safe when every pin offset in the drawing is a multiple of
  the step, and then it is exactly safe. `_place` lines two cells up by
  setting one's y to the other's pin height less its own pin offset, so two
  aligned cells differ by the difference of their offsets. If those are
  multiples of the step the two ys have the same fractional part, so both
  round the same way and the wire between them stays straight.

  Where they are not -- block8 sits at 26, 58, 102 and 134, and stretching a
  cell multiplies whatever the offset was -- rounding moves the two ends by
  different amounts and straightens nothing while bending plenty. Tried
  without this guard, spi_master went from four straight wires out of
  nineteen to one.

  So the drawing is asked first, and the result is measured afterwards anyway.
  """
  step = drc.PIN_GRID
  if step <= 0 or not _offsets_on_grid(doc, registry, step):
    return

  before = _violation_count(doc, registry)
  was = [(cell["x"], cell["y"]) for cell in doc.cells]
  canvas = dict(doc.canvas)

  for cell in doc.cells:
    cell["x"] = round(cell["x"] / step) * step
    cell["y"] = round(cell["y"] / step) * step
  _fit(doc, registry, margin)

  if _violation_count(doc, registry) > before:
    for cell, (x, y) in zip(doc.cells, was):
      cell["x"], cell["y"] = x, y
    doc.canvas.clear()
    doc.canvas.update(canvas)


def _offsets_on_grid(doc, registry, step):
  """True when every pin in the drawing sits a whole step from its cell."""
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    for pin in symbol.pins:
      for value in _pin_offset(registry, doc, cell, pin["name"]):
        if abs(value / step - round(value / step)) > EPSILON:
          return False
  return True


def _violation_count(doc, registry):
  """Errors and warnings, worst first, and deliberately nothing else.

  `_score` folds violations, wire length and area into one number, which is
  what the search above wants when it is choosing between arrangements that
  are much of a muchness. It is the wrong measure for the grid, because the
  thing the grid buys does not appear in it at all: a drawing sitting on the
  step its pins use is one whose next hand edit lines up, and no term in the
  score knows that.

  Measured against the score, rounding was refused on three of the examples
  for a twelfth of a percent of wire -- alu_slice 8552 against 8564 -- with
  the error and warning counts identical either way. That is a trade not
  worth making, so only the counts are compared, and a drawing that reads
  exactly as well goes on the grid.
  """
  errors = warnings = 0
  for issue in drc.check(doc, registry):
    if issue.level == "error":
      errors += 1
    elif issue.level == "warning":
      warnings += 1
  return (errors, warnings)


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
            settle=True, top_at=None):
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
    _normalise(doc, registry, cells, margin, top_at)
    return _judge(doc, registry, margin)

  # A step is taken only if it makes the drawing better and adds no DRC
  # error. Priced in with everything else, an error could be bought: a swap
  # that saved enough wire and corners elsewhere was taken with a short in
  # it. A drawing that says something untrue is not better for being tidier.
  def better(found, than):
    return found[1] <= than[1] and found[0] < than[0] - EPSILON

  # Placing is not quite a pure function of the order: a cell with no wire
  # to follow keeps the height it had. So the winner is kept as it was
  # measured, rather than laid out again at the end -- laying it out again
  # after a string of rejected candidates could land somewhere else, and
  # somewhere never scored: a drawing with a short in it, once.
  state = {"best": lay_out(order), "order": order, "kept": _snapshot(cells)}

  def keep(score, candidate):
    state["best"], state["order"] = score, candidate
    state["kept"] = _snapshot(cells)

  def swaps(columns=None, sweeps=REFINE_SWEEPS):
    for _sweep in range(sweeps):
      improved = False
      current = state["order"]
      for column in (range(len(current)) if columns is None else columns):
        for index in range(len(current[column]) - 1):
          candidate = [list(group) for group in state["order"]]
          candidate[column][index], candidate[column][index + 1] = (
            candidate[column][index + 1], candidate[column][index])
          score = lay_out(candidate)
          if better(score, state["best"]):
            keep(score, candidate)
            improved = True
      if not improved:
        return

  # Turning a gate over puts its inputs the other way up. A gate is the
  # same shape either way up, so this changes nothing but which wire meets
  # which pin -- and two inputs arriving the wrong way round cross in front
  # of it, or one comes round the long way. Tried only once the swaps have
  # settled, and the swaps tried again after: mixed in from the start, an
  # early turn steered the swaps somewhere worse than they found without it.
  def turns():
    turned = set()
    _restore(cells, state["kept"])
    crossed = _crossed_inputs(doc, registry, cells, edges)
    for cell in cells:
      if cell["id"] not in crossed:
        continue
      _turn_over(cell)
      score = lay_out(state["order"])
      if better(score, state["best"]):
        keep(score, state["order"])
        turned.add(ranks[cell["id"]])
      else:
        _turn_over(cell)
    return turned

  swaps()
  # A turned gate changes what suits the cells either side of it, so those
  # columns get their swaps again -- only those: the rest of the drawing
  # has not changed, and sweeping it again doubled the time for nothing.
  turned = turns()
  if turned:
    swaps(sorted(set(c for rank in turned for c in (rank - 1, rank, rank + 1)
                     if 0 <= c < len(state["order"]))), sweeps=1)
  order, kept = state["order"], state["kept"]

  _restore(cells, kept)
  _normalise(doc, registry, cells, margin, top_at)
  return order


PORT_ROWS = 3


def _level_ports(doc, registry, cells, margin, top_at=None):
  """Move each port level with the wire that reaches it, where that helps.

  A port is first placed level with the pin at the other end of its wire,
  which is right when the wire can run straight across. When it cannot --
  something stands in the way, so the router takes the wire over the top on
  a row of its own -- the port is left where the straight wire would have
  been, and the wire has to come back down to it: two corners and a drop
  for nothing. Reported on a drawing whose output ran along the top, over a
  flip-flop, then down to a port level with the flip-flop's D pin.

  So each port is tried at the height of every row its own wire runs along,
  and kept there if the drawing measures better and nothing new is wrong.
  Two passes, because moving one port can free the place another wants.
  """
  ports = [cell for cell in cells
           if registry.for_cell(cell).category == drc.PORT_CATEGORY]
  if not ports:
    return
  best = _judge(doc, registry, margin)
  for _sweep in range(2):
    moved = False
    for port in ports:
      pin = registry.for_cell(port).pins[0]["name"]
      at = _pin_offset(registry, doc, port, pin)[1] + port["y"]
      rows = set()
      for net, branches in routing.route_all(doc, registry):
        if not any(end.get("cell") == port["id"]
                   for end in [net.get("from")] + loads_of(net)
                   if isinstance(end, dict)):
          continue
        for points in branches:
          for a, b in zip(points, points[1:]):
            if abs(a[1] - b[1]) < EPSILON and abs(a[1] - at) > EPSILON:
              rows.add(round(a[1], 6))
      home = port["y"]
      # Two ports may stand closer than two blocks (drc.PORT_GAP); whether
      # the names still clear each other is the DRCs' to say, in the score.
      others = [(_box(registry, doc, c), c in ports)
                for c in cells if c is not port]
      # The nearest few: a row far away is a long way from where the
      # port's neighbours were placed to suit it.
      for row in sorted(rows, key=lambda y: abs(y - at))[:PORT_ROWS]:
        port["y"] = home + (row - at)
        box = _box(registry, doc, port)
        # Not up into a title written above the drawing. (Above the other
        # cells is fine otherwise: the sheet is sized to the drawing after.)
        if top_at is not None and box[1] - _headroom(port) < top_at:
          continue
        if any(_near(box, 0, 0, other,
                     drc.PORT_GAP if both_ports else drc.CELL_MIN_GAP)
               for other, both_ports in others):
          continue
        score = _judge(doc, registry, margin)
        # Tidying, so it may not make anything else wrong: no new finding
        # of any kind, not even one the saving would pay for -- a port moved
        # up to its wire took the wire through the drawing's subtitle.
        if (score[1] <= best[1] and score[2] <= best[2]
            and score[0] < best[0] - EPSILON):
          best, home, moved = score, port["y"], True
          break
      port["y"] = home
    if not moved:
      return


def _snapshot(cells):
  return {cell["id"]: (cell["x"], cell["y"], cell.get("rotate", 0),
                       cell.get("mirror", False)) for cell in cells}


def _restore(cells, kept):
  for cell in cells:
    cell["x"], cell["y"], cell["rotate"], cell["mirror"] = kept[cell["id"]]


def _crossed_inputs(doc, registry, cells, edges):
  """The gates worth turning over: those whose inputs arrive crossed, the
  wire into the top pin coming from lower down than the wire into the one
  below it. Turning any other gate over can only cross what was straight,
  and trying every gate made a seventy-cell layout four times slower."""
  by_id = {cell["id"]: cell for cell in cells}
  arriving = {}
  for source, target, source_pin, target_pin in edges:
    cell = by_id.get(target)
    if cell is None or not _can_turn_over(registry, cell):
      continue
    driver = by_id[source]
    at = cell["y"] + _pin_offset(registry, doc, cell, target_pin)[1]
    come = driver["y"] + _pin_offset(registry, doc, driver, source_pin)[1]
    arriving.setdefault(target, []).append((at, come))
  crossed = set()
  for target, pairs in arriving.items():
    pairs.sort()
    if any(later[1] < earlier[1] - EPSILON
           for earlier, later in zip(pairs, pairs[1:])):
      crossed.add(target)
  return crossed


def _can_turn_over(registry, cell):
  """A gate with more than one input: symmetric top to bottom, so it reads
  the same turned over, and turning it over swaps where its inputs are."""
  symbol = registry.for_cell(cell)
  return (symbol is not None and symbol.category == "gates"
          and sum(1 for pin in symbol.pins if pin.get("dir") == "in") > 1)


def _turn_over(cell):
  """Flip a cell top to bottom -- half a turn, then mirrored -- or back."""
  if cell.get("rotate") == 180 and cell.get("mirror"):
    cell["rotate"], cell["mirror"] = 0, False
  else:
    cell["rotate"], cell["mirror"] = 180, True


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

# A corner costs about as much as this much wire. A wire that turns twice to
# save a few units reads worse than a straight one a little longer: every
# corner is a place the eye has to stop and find where the line went.
CORNER_COST = 20.0

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
# 4000 the layout chases shorts it cannot remove (they came from the router,
# not from cell order -- see routing._leg_column) and pays for the chase
# elsewhere: 10 errors but 75 warnings and 134 crossings, a worse drawing by
# every other measure.
ERROR_COST = 1000.0
WARNING_COST = 150.0

EPSILON = 1e-9


def _score(doc, registry, margin=None):
  return _judge(doc, registry, margin)[0]


def _judge(doc, registry, margin=None):
  """(score, errors, warnings): _score, and the DRC findings in it.

  How hard the laid-out drawing is to read. Lower is better.

  Four things a reader pays for. Every crossing is a moment of doubt about
  which line is which, and a bridge drawn over it is the same doubt with a
  bump on it. Every extra unit of wire is distance the eye has to travel.
  Every extra unit of sheet is drawing that has to be scrolled or shrunk to be
  seen at all. And every DRC failure is the drawing either saying something
  untrue or being harder to read than it needs to be -- which is the question
  this score is asking, so there is no reason to ask it a second, weaker way.

  Measured by routing and checking the drawing, not by a proxy for it, so what
  is scored is what would be exported. Given a `margin`, the sheet is first
  sized to this candidate as _fit will size the winner: the DRCs read the
  sheet, and scoring against whatever canvas the file arrived with made a
  second layout of the same drawing search differently from the first.
  """
  # Routed and labelled once and handed on: the bounding box and the DRCs
  # would otherwise each do both again, and this runs once per candidate swap.
  # The labels are placed before the sheet is sized to the candidate below;
  # the sized sheet is the box they helped measure plus the margin, so every
  # one of them still fits on it.
  from . import render_svg

  routes = routing.route_all(doc, registry)
  labels = render_svg.net_label_boxes(doc, registry, routes)
  segments = list(routing.segments_of(routes))
  length, corners = drawn_wire(routes)

  box = doc.content_bbox(registry, routes, labels)
  spread = (box[2] + box[3]) if box else 0.0
  if margin is not None and box is not None:
    _size_sheet(doc, box, margin)

  errors = warnings = 0
  for violation in drc.check(doc, registry, routes, labels):
    if violation.level == "error":
      errors += 1
    else:
      warnings += 1

  return (_crossings(segments) * CROSSING_COST
          + length
          + corners * CORNER_COST
          + spread * SPREAD_COST
          + errors * ERROR_COST
          + warnings * WARNING_COST), errors, warnings


def drawn_wire(routes):
  """(length, corners) of the wire as it is drawn.

  A net with several loads is routed as one branch per load, and the
  branches lie on top of each other from the driver to where they part.
  Adding up the branches counted that shared trunk once per load -- a clock
  to four flip-flops paid four times for the same line -- so the score
  steered away from exactly the shared trunks a reader wants. This counts
  each net's ink once: runs on one line are merged, and a corner the
  branches share is one corner.
  """
  length = 0.0
  corners = 0
  for _net, branches in routes:
    lines = {}
    bends = set()
    for points in branches:
      for a, b in zip(points, points[1:]):
        if abs(a[1] - b[1]) < EPSILON and abs(a[0] - b[0]) > EPSILON:
          key, span = (True, round(a[1], 6)), sorted((a[0], b[0]))
        elif abs(a[0] - b[0]) < EPSILON and abs(a[1] - b[1]) > EPSILON:
          key, span = (False, round(a[0], 6)), sorted((a[1], b[1]))
        else:
          continue
        lines.setdefault(key, []).append(span)
      for p, q, r in zip(points, points[1:], points[2:]):
        if (abs(p[0] - q[0]) < EPSILON) != (abs(q[0] - r[0]) < EPSILON):
          bends.add((round(q[0], 6), round(q[1], 6)))
    for spans in lines.values():
      spans.sort()
      low, high = spans[0]
      for start, end in spans[1:]:
        if start > high:
          length += high - low
          low, high = start, end
        else:
          high = max(high, end)
      length += high - low
    corners += len(bends)
  return length, corners


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
  def relax():
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

  relax()
  # Bits put onto one bus meet it in one column. Each joiner would otherwise
  # sit one step right of whatever drives its bit -- a register bit-blasted
  # into a chain of flip-flops put every joiner in a different column, and the
  # bus between them looped back across the sheet.
  joins = _joins_by_bus(doc, cells)
  if joins:
    for members in joins:
      column = max(rank[member] for member in members)
      for member in members:
        rank[member] = column
    relax()

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


def _joins_by_bus(doc, cells):
  """The bus joiners in `cells`, grouped by the bus their `bus` pin is on."""
  joiners = set(cell["id"] for cell in cells if cell.get("type") == "bus_join")
  if not joiners:
    return []
  groups = []
  for net in doc.nets:
    members = [end["cell"] for end in [net.get("from")] + loads_of(net)
               if isinstance(end, dict) and end.get("cell") in joiners
               and end.get("pin") == "bus"]
    if len(members) > 1:
      groups.append(members)
  return groups


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
  ports = frozenset(cell["id"] for cell in cells
                    if registry.for_cell(cell).category == drc.PORT_CATEGORY)

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
      rows = []
      for gap, source, source_pin, target_pin in arriving[cell_id]:
        driver = by_id[source]
        driver_y = driver["y"] + _pin_offset(registry, doc, driver, source_pin)[1]
        mine = _pin_offset(registry, doc, cell, target_pin)[1]
        rows.append((driver_y, mine))
        if best is not None and gap >= best[0]:
          continue
        best = (gap, driver_y - mine)
      if best is not None:
        desired[cell_id] = _without_wobble(best[1], rows)
    _stack(by_id, boxes, column, desired, gap_y, ports)

  if settle:
    # Fresh boxes: the pass above moved every cell, and _box reports absolute
    # coordinates, so the ones measured at the top of this function describe
    # where the cells used to be.
    _settle_followers(doc, registry, by_id,
                      {c["id"]: _box(registry, doc, c) for c in by_id.values()},
                      order, ranks, edges, gap_y, ports)
  _wrap(doc, registry, by_id, order, gap_x, gap_y)


def _bands(widths, gap_x, heights, gap_y):
  """Where to break the columns into rows: a list of (first, last) column
  indices, or None to leave the drawing as one row.

  Only for a very long chain (WRAP_COLUMNS, WRAP_WIDTH). How many rows is
  chosen so the wrapped drawing comes out about the shape of the sheet, and
  the breaks so the rows come out about the same width. It is worked out
  from the column widths and how tall each column's cells are stacked, not
  from where they happen to be, so every arrangement _refine tries is
  wrapped the same way.
  """
  width = sum(widths) + gap_x * (len(widths) - 1)
  if len(widths) < WRAP_COLUMNS or width < WRAP_WIDTH:
    return None
  height = max(heights) + gap_y
  rows = int(round(math.sqrt(width / (height * WRAP_ASPECT))))
  rows = min(rows, len(widths) // 2)
  if rows < 2:
    return None
  bands, first, done = [], 0, 0.0
  for index, column in enumerate(widths):
    done += column + gap_x
    if len(bands) < rows - 1 and done >= width * (len(bands) + 1) / rows:
      bands.append((first, index))
      first = index + 1
  bands.append((first, len(widths) - 1))
  return bands


def _wrap(doc, registry, by_id, order, gap_x, gap_y):
  """Wrap a very long drawing onto rows, each under the one before.

  Each row starts back at the left and keeps its own cells' heights, so the
  wires inside a row are exactly as they were. The wire from the end of one
  row to the start of the next runs back through the room left between them.
  """
  boxes = {cell_id: _box(registry, doc, cell) for cell_id, cell in by_id.items()}
  widths = [max([boxes[c][2] for c in column] or [0]) for column in order]
  heights = [sum(boxes[c][3] + gap_y + _headroom(by_id[c]) for c in column)
             for column in order]
  bands = _bands(widths, gap_x, heights, gap_y)
  if bands is None:
    return
  # Between two rows: the gap cells keep, twice over -- once for the wires
  # leaving the row above and once for those entering the row below -- and
  # a name's room.
  between = 3 * gap_y + drc.LABEL_HEADROOM
  top = None
  for first, last in bands:
    members = [c for column in order[first:last + 1] for c in column]
    if not members:
      continue
    left = min(boxes[c][0] for c in members)
    high = min(boxes[c][1] - _headroom(by_id[c]) for c in members)
    low = max(boxes[c][1] + boxes[c][3] for c in members)
    dx = 0.0 if top is None else origin - left
    dy = 0.0 if top is None else top - high
    if top is None:
      origin = left
    for cell_id in members:
      by_id[cell_id]["x"] += dx
      by_id[cell_id]["y"] += dy
    top = low + dy + between


def _settle_followers(doc, registry, by_id, boxes, order, ranks, edges, gap_y,
                      ports=frozenset()):
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
      rows = []
      for gap, target, source_pin, target_pin in leaving[cell_id]:
        load = by_id.get(target)
        if load is None:
          continue
        load_y = load["y"] + _pin_offset(registry, doc, load, target_pin)[1]
        mine = _pin_offset(registry, doc, cell, source_pin)[1]
        rows.append((load_y, mine))
        if best is not None and gap >= best[0]:
          continue
        best = (gap, load_y - mine)
      if best is None:
        desired[cell_id] = cell["y"]
      else:
        desired[cell_id] = _without_wobble(best[1], rows)
        settling = True
    if settling:
      _stack(by_id, boxes, column, desired, gap_y, ports)


def _without_wobble(y, rows):
  """`y`, or the nearest height to it at which no wire wobbles.

  A cell follows one wire, which then runs dead straight. Any other wire it
  shares with a cell already placed lands wherever the two cells' pin spacing
  puts it, and when the spacings differ -- wptr's outputs 45 apart, the
  memory's inputs 40 -- the second wire comes out a few units off its pin's
  row: a jog too short to read as anything but a wobble, and a wire-jog
  warning. Every such wire has to be straight or at least WIRE_MIN_JOG out;
  if lining one up leaves another 5 off, the cell steps away until both are
  plainly steps.

  `rows` holds (row the wire comes from, pin offset on this cell) for each
  wire to a cell already placed. Moves are in pin-grid steps, so the cell
  stays where a hand edit can line it up; the nearest that works wins, down
  before up when they are as near.
  """
  step = max(drc.PIN_GRID, 1.0)

  def wobbles(at):
    return any(EPSILON < abs(row - (at + offset)) < drc.WIRE_MIN_JOG
               for row, offset in rows)

  if len(rows) < 2 or not wobbles(y):
    return y
  for count in range(1, int(4 * drc.WIRE_MIN_JOG / step) + 1):
    for candidate in (y + count * step, y - count * step):
      if not wobbles(candidate):
        return candidate
  return y


def _stack(by_id, boxes, column, desired, gap_y, ports=frozenset()):
  """Give one column its heights, top to bottom in the column's own order.

  A cell with a wire to follow goes where that wire wants it, or as near as
  the cell above lets it. One with nothing to follow sits just below the cell
  above it.

  The order is kept rather than re-sorted by the heights wanted. Sorting made
  every choice of order for driven cells come out the same -- the crossing
  cuts in _order and every swap _refine measured were thrown away here -- and
  sent every loose cell to the bottom of its column whatever slot it had.

  A port under a port needs only drc.PORT_GAP and room for its name, not the
  space two blocks keep for the wires between them. Stacking every port a
  cell gap apart spread a column of ports down the sheet with nothing running
  between them -- the distance was the rule's, not the drawing's. A port whose wire is straighter
  further down still goes there; this is only how close it may come.
  """
  bottom = None
  above = None
  for cell_id in column:
    cell = by_id[cell_id]
    box = boxes[cell_id]
    offset = cell["y"] - box[1]
    want = desired.get(cell_id)
    if bottom is not None:
      if above in ports and cell_id in ports:
        # The outline gap the DRC asks of two ports, plus the air the lower
        # port's name needs from the port above -- not the headroom a
        # block's name gets, which is sized for a gate.
        least = bottom + drc.PORT_GAP + drc.TEXT_TO_CELL + offset
      else:
        least = bottom + gap_y + offset + _headroom(cell)
      want = least if want is None else max(want, least)
    elif want is None:
      want = offset
    cell["y"] = want
    bottom = (want - offset) + box[3]
    above = cell_id


def _below_headings(doc, registry, cells, margin):
  """Where the drawing may start so that it stays under its heading notes.

  A title or a subtitle written above the drawing is a note that sits above
  every cell. Laying the drawing out used to put its first row at the margin,
  straight through them, and route a wire along the top that crossed the
  subtitle. Notes anywhere else are left where they are: nothing says which
  part of the drawing a note in the middle of it was about.
  """
  from . import render_svg

  tops = [_box(registry, doc, cell)[1] - _headroom(cell) for cell in cells]
  if not tops:
    return None
  highest = min(tops)
  bottoms = []
  for shape in doc.shapes:
    box = render_svg.text_shape_box(shape, doc.font_scale)
    if box is not None and box[3] <= highest:
      bottoms.append(box[3])
  if not bottoms:
    return None
  return max(margin, max(bottoms) + drc.LABEL_HEADROOM)


def _normalise(doc, registry, cells, margin, top_at=None):
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
  start = margin if top_at is None else top_at
  for cell in cells:
    cell["x"] += margin - left
    cell["y"] += start - top


def _fit(doc, registry, margin):
  """Size the sheet to what is actually drawn, wires included.

  Both ways: a layout that leaves half a sheet of white space below it reads
  as a drawing with something missing.
  """
  # content_bbox routes the wires itself, so it already covers the feedback
  # path that returns underneath the row it came from. It did not always --
  # this function used to walk the segments separately to make up for it.
  box = doc.content_bbox(registry)
  if box is not None:
    _size_sheet(doc, box, margin)


def _size_sheet(doc, box, margin):
  doc.canvas["width"] = int(box[0] + box[2] + margin)
  doc.canvas["height"] = int(box[1] + box[3] + margin)
