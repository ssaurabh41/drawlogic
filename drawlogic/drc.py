"""Design rule checks -- the DRCs a drawing has to pass to read well.

A schematic can be correct and still unreadable. Two wires a hair apart read
as one thick line. A gate pressed against its neighbour reads as one part. A
net name sitting on a wire is unreadable even though every coordinate is
right. Worst of all, two unrelated wires drawn on top of each other read as a
short that nothing in the file says is there.

Those are drafting conventions, and every drawing office writes them down
rather than leaving them to whoever is holding the pen. So they live here, in
one file: the limits at the top, and the checks that enforce them below.
Tuning how a drawing looks is editing this file; nothing else needs to change.

Distances are in document units, the same units cells and wires use. A small
logic gate is 40x40, so a unit is roughly "a twentieth of a gate".

The browser fetches the limits from /api/drc rather than restating them, so a
drag in the editor and a file from the exporter obey the same DRCs.

Usage:

    from drawlogic import drc

    drc.WIRE_GAP                # how far apart two parallel wires must sit
    drc.CELL_GAP_Y              # how far apart two stacked cells must sit
    drc.check(doc, registry)    # [Violation, ...], worst first
"""

import math

from .geometry import corners

# ---- wires ----------------------------------------------------------------

# Two parallel wires closer than this read as one line with a thick edge
# rather than as two signals. This is the single most important number here:
# below about 12 the eye stops separating them at normal zoom.
WIRE_GAP = 18.0

# How far a wire keeps from a cell it does not connect to. Touching a block
# it has nothing to do with suggests a connection that is not there.
WIRE_TO_CELL = 10.0

# How far apart the router tries successive corridors when its first choice is
# taken. Deliberately smaller than WIRE_GAP: the first step either side can
# never clear a wire it was rejected for crowding, but keeping the step small
# makes the rest of the grid -- 20, 30, 40 -- finer than stepping by a whole
# gap would, so a displaced wire lands nearer to where it wanted to be.
CORRIDOR_STEP = 10.0

# How many corridors to try either side before giving up and drawing the wire
# where it wanted to go. A crowded drawing should still produce a wire -- and
# when the router does give up, `check` reports the wire it drew on top of.
CORRIDOR_TRIES = 18

# Two runs at the same coordinate to within this are drawn as one line. Not a
# floating-point epsilon: half a unit of separation is invisible on paper, so
# this is the distance below which two wires have become one. The router's last
# resort asks only for this much, and the DRCs call anything closer a short.
TOUCHING = 0.5

# The shortest jog worth drawing. A run this short between two turns reads as
# a wobble in a straight wire rather than as a deliberate step around
# something, so the drawing is clearer with the wire moved to avoid it.
WIRE_MIN_JOG = 8.0

# ---- text -----------------------------------------------------------------

# Clear space demanded around a net name. A label touching a wire is as bad as
# one crossing it, so the box is grown by this before overlaps are counted.
LABEL_CLEARANCE = 5.0

# How far above a cell its instance name sits, and so how much room a layout
# has to leave for it.
LABEL_HEADROOM = 20.0

# Air around a cell's instance name. Text set against a wire, a neighbouring
# body or another name is the first thing to become unreadable when a drawing
# gets crowded, and unlike a wire it cannot be followed by eye to recover it.
TEXT_TO_WIRE = 6.0
TEXT_TO_CELL = 6.0
TEXT_TO_TEXT = 8.0

# ---- cells ----------------------------------------------------------------

# Room between one column of cells and the next. This is where the wires
# between them run, so it has to hold a few corridors side by side.
CELL_GAP_X = 110.0

# Room between two cells stacked in the same column.
CELL_GAP_Y = 52.0

# The least space allowed between any two cells, whichever way they sit.
# Closer than this and two parts read as one.
CELL_MIN_GAP = 24.0

# ---- ports ----------------------------------------------------------------

# The least space between two ports. A port is a 10-unit outline with its
# signal name set above it, so this is about the outlines: the room the names
# need is the text rules' business, and asking twice only produces the same
# complaint twice. Stacks at 22 read cleanly; below about 20 they merge.
PORT_GAP = 20.0

# A port pressed against a gate reads as part of that gate rather than as the
# edge of the sheet, which is the one thing a port is there to say.
PORT_TO_CELL = 30.0

# A wire passing close by a port it does not connect to invites the reader to
# join them. Held tighter than WIRE_TO_CELL because a port is mostly outline.
PORT_TO_WIRE = 12.0

# ---- hops -----------------------------------------------------------------

# Two crossing bridges closer than this merge into one squiggle and stop
# reading as two separate crossings. A bridge is 5 units across, so this is
# roughly "a bridge's width of flat wire between them".
HOP_GAP = 16.0

# A bridge drawn over a corner or a junction dot deforms it, and a deformed
# junction is a connection the reader is no longer sure about.
HOP_TO_CORNER = 12.0

# A bridge sitting on a cell body or a name is unreadable for the same reason
# a wire on one is: there is nothing behind it to see it against.
HOP_TO_CELL = 8.0
HOP_TO_TEXT = 6.0

# ---- sheet ----------------------------------------------------------------

# Space left around everything when a layout decides where the drawing starts.
SHEET_MARGIN = 90.0

# The least clearance from the sheet edge before the drawing looks cramped --
# and before a printer's own margin starts eating into it. Much smaller than
# SHEET_MARGIN, which is what a layout aims for rather than what it must have.
SHEET_EDGE = 20.0

# The sheet a new drawing gets. One size for every drawing means a folder of
# them prints and pastes consistently; change it per drawing in the properties
# panel when one needs more room.
SHEET_W = 1200.0
SHEET_H = 780.0


def as_data():
  """The limits as plain data, for /api/drc and the browser."""
  return {
    "wireGap": WIRE_GAP,
    "wireToCell": WIRE_TO_CELL,
    "corridorStep": CORRIDOR_STEP,
    "corridorTries": CORRIDOR_TRIES,
    "wireMinJog": WIRE_MIN_JOG,
    "touching": TOUCHING,
    "labelClearance": LABEL_CLEARANCE,
    "labelHeadroom": LABEL_HEADROOM,
    "textToWire": TEXT_TO_WIRE,
    "textToCell": TEXT_TO_CELL,
    "textToText": TEXT_TO_TEXT,
    "cellGapX": CELL_GAP_X,
    "cellGapY": CELL_GAP_Y,
    "cellMinGap": CELL_MIN_GAP,
    "portGap": PORT_GAP,
    "portToCell": PORT_TO_CELL,
    "portToWire": PORT_TO_WIRE,
    "hopGap": HOP_GAP,
    "hopToCorner": HOP_TO_CORNER,
    "hopToCell": HOP_TO_CELL,
    "hopToText": HOP_TO_TEXT,
    "sheetMargin": SHEET_MARGIN,
    "sheetEdge": SHEET_EDGE,
    "sheetW": SHEET_W,
    "sheetH": SHEET_H,
  }


# ---- what a failure looks like --------------------------------------------

# Cell types that stand for the edge of the sheet rather than for a part.
PORT_CATEGORY = "ports"


class Violation(object):
  """One DRC failure: which rule, how bad, where, and what it is about.

  Carries the same three fields doc.Issue does -- level, where, message -- so
  `drawlogic validate` can print rule failures and reference failures in one
  list, plus the rule name and a point for anything that wants to jump to it.
  """

  __slots__ = ("rule", "level", "where", "message", "at")

  def __init__(self, rule, level, where, message, at=None):
    self.rule = rule
    self.level = level
    self.where = where
    self.message = message
    self.at = at

  def as_data(self):
    return {
      "rule": self.rule,
      "level": self.level,
      "where": self.where,
      "message": self.message,
      "at": list(self.at) if self.at else None,
    }

  def __str__(self):
    return "%s: %s: %s" % (self.level, self.where, self.message)

  def __repr__(self):
    return "Violation(%r, %r, %r, %r)" % (
      self.rule, self.level, self.where, self.message)


class _Report(object):
  """Collects violations, keeping only the worst one per offending pair.

  A wire that runs too close to another does so along every segment of the
  run, and reporting each one separately buries the drawing in duplicates of
  one problem. So each pair of things is reported once, at its tightest point.
  """

  def __init__(self):
    self._worst = {}
    self._order = []

  def add(self, key, severity, violation):
    """Record `violation` for `key`, replacing a milder one for the same key.

    `severity` is how bad this instance is, smaller being worse -- usually the
    measured gap -- so the reported spot is the tightest one, not the first.
    """
    if key in self._worst:
      if severity >= self._worst[key][0]:
        return
    else:
      self._order.append(key)
    self._worst[key] = (severity, violation)

  def violations(self):
    """Every violation, errors first, then in the order they were found."""
    found = [self._worst[key][1] for key in self._order]
    return ([v for v in found if v.level == "error"]
            + [v for v in found if v.level != "error"])


# ---- geometry --------------------------------------------------------------


def _box_gap(a, b):
  """Distance between two rectangles, 0 when they touch or overlap."""
  dx = max(b[0] - a[2], a[0] - b[2], 0.0)
  dy = max(b[1] - a[3], a[1] - b[3], 0.0)
  return math.hypot(dx, dy)


def _boxes_overlap(a, b):
  return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _point_box(point, radius=0.0):
  return (point[0] - radius, point[1] - radius,
          point[0] + radius, point[1] + radius)


def _segment_box(a, b):
  return (min(a[0], b[0]), min(a[1], b[1]),
          max(a[0], b[0]), max(a[1], b[1]))


def _overlap(lo_a, hi_a, lo_b, hi_b):
  """How much two intervals share; negative when they are apart."""
  return min(hi_a, hi_b) - max(lo_a, lo_b)


def _midpoint(a, b):
  return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


# ---- the drawing, measured once --------------------------------------------


class _Placed(object):
  """One cell as the checks see it: where it sits and what text it carries."""

  __slots__ = ("id", "cell", "symbol", "box", "port", "label", "label_box")

  def __init__(self, cell, symbol, box, label_box):
    self.id = cell.get("id")
    self.cell = cell
    self.symbol = symbol
    self.box = box
    self.port = symbol.category == PORT_CATEGORY
    self.label = cell.get("label")
    self.label_box = label_box

  def name(self):
    return self.label or self.id


class _Run(object):
  """One straight length of wire, with the interval it covers."""

  __slots__ = ("net_id", "horizontal", "fixed", "lo", "hi", "a", "b", "inner")

  def __init__(self, net_id, a, b, inner):
    self.net_id = net_id
    self.a = a
    self.b = b
    self.inner = inner
    self.horizontal = abs(a[1] - b[1]) < abs(a[0] - b[0])
    if self.horizontal:
      self.fixed = (a[1] + b[1]) / 2.0
      self.lo, self.hi = min(a[0], b[0]), max(a[0], b[0])
    else:
      self.fixed = (a[0] + b[0]) / 2.0
      self.lo, self.hi = min(a[1], b[1]), max(a[1], b[1])

  def length(self):
    return self.hi - self.lo

  def box(self):
    return _segment_box(self.a, self.b)


class _Scene(object):
  """Everything the checks measure, resolved once.

  Routing a drawing is the expensive part and every wire rule needs the same
  answer, so it happens here rather than once per check.
  """

  def __init__(self, doc, registry=None):
    from . import render_svg
    from . import routing
    from .doc import loads_of
    from .symbols import default_registry

    self.doc = doc
    self.registry = registry or default_registry()
    self.hops_drawn = doc.canvas.get("hops", True) is not False

    self.cells = []
    for cell in doc.cells:
      symbol = self.registry.for_cell(cell)
      if symbol is None:
        # A cell whose type is unknown has no geometry to measure. validate()
        # already reports it as a reference fault, so it is not reported twice.
        continue
      matrix = symbol.matrix_for(cell, doc.symbol_scale)
      points = [matrix.apply(px, py)
                for px, py in corners(0, 0, symbol.width, symbol.height)]
      box = (min(p[0] for p in points), min(p[1] for p in points),
             max(p[0] for p in points), max(p[1] for p in points))
      label_box = render_svg.cell_label_box(
        symbol, cell, doc.symbol_scale, doc.font_scale)
      self.cells.append(_Placed(cell, symbol, box, label_box))
    self.by_id = dict((placed.id, placed) for placed in self.cells)

    self.net_pins = {}
    self.net_cells = {}
    for net in doc.nets:
      pins = set()
      touched = set()
      endpoints = [net.get("from")] + loads_of(net)
      for endpoint in endpoints:
        if isinstance(endpoint, dict) and "cell" in endpoint:
          pins.add((endpoint["cell"], endpoint.get("pin")))
          touched.add(endpoint["cell"])
      self.net_pins[net.get("id")] = frozenset(pins)
      self.net_cells[net.get("id")] = touched

    self.routes = routing.route_all(doc, self.registry)
    self.runs = []
    self.vertices = []
    for net, branches in self.routes:
      net_id = net.get("id")
      for points in branches:
        self.vertices.extend(points)
        last = len(points) - 2
        for index in range(len(points) - 1):
          self.runs.append(_Run(net_id, points[index], points[index + 1],
                                inner=0 < index < last))

    self.junctions = routing.junctions(self.routes)
    self.hops = []
    if self.hops_drawn:
      for net_id, spots in routing.hop_points(self.routes).items():
        self.hops.extend((net_id, spot) for spot in spots)

    self.net_label_boxes = render_svg.net_label_boxes(
      doc, self.registry, self.routes)

  def net(self, net_id):
    for net in self.doc.nets:
      if net.get("id") == net_id:
        return net
    return None

  def net_name(self, net_id):
    net = self.net(net_id)
    name = net.get("name") if net else None
    return "%s (%s)" % (net_id, name) if name else str(net_id)

  def same_node(self, one, other):
    """True if two nets share a pin, and so are one electrical node.

    Two wires off one pin are one signal drawn as a rail, so they are allowed
    to lie on top of each other -- the router relies on the same exemption.
    """
    return bool(self.net_pins.get(one, frozenset())
                & self.net_pins.get(other, frozenset()))

  def connects(self, net_id, cell_id):
    return cell_id in self.net_cells.get(net_id, ())

  def text_boxes(self):
    """Every piece of text in the drawing, as (what it is, box)."""
    found = [("name of %s" % placed.id, placed.label_box)
             for placed in self.cells if placed.label_box]
    found.extend(("name of net %s" % net_id, box)
                 for net_id, box in sorted(self.net_label_boxes.items()))
    return found


# ---- the checks ------------------------------------------------------------


def check(doc, registry=None):
  """Every DRC failure in a drawing, errors first.

  Errors are the drawing saying something untrue -- a wire lying on another
  net so the pair reads as one signal, a wire through a block it has nothing
  to do with, two parts in the same place. Warnings are the drawing being
  harder to read than it needs to be, which is a judgement about spacing
  rather than a fault, so they never fail a build on their own.

  Every pair of things is reported once, at the tightest point between them,
  rather than once per segment; one crowded wire is one problem to fix.
  """
  scene = _Scene(doc, registry)
  report = _Report()
  _check_wire_spacing(scene, report)
  _check_wire_contact(scene, report)
  _check_wire_crossings(scene, report)
  _check_wires_and_cells(scene, report)
  _check_wire_shape(scene, report)
  _check_cell_spacing(scene, report)
  _check_text(scene, report)
  _check_hops(scene, report)
  _check_sheet(scene, report)
  return report.violations()


def _pair_key(one, other):
  """One key for one pair of nets, whichever way round they were found.

  Shadowing and a wire ending on another wire are the same complaint about the
  same pair -- "these two are drawn as one" -- so they share a key and the
  worst of them is what gets reported.
  """
  return ("wire-pair", tuple(sorted((str(one), str(other)))))


def _unrelated(scene, one, other):
  """True if two runs belong to nets that are genuinely different signals."""
  return one.net_id != other.net_id and not scene.same_node(one.net_id,
                                                           other.net_id)


def _check_wire_spacing(scene, report):
  """Parallel runs of different nets: touching is a short, near is a crowd.

  The two faults are the same measurement at different distances, so they are
  found together. Runs that merely meet end to end are left alone: that is a
  junction, and junctions are drawn with a dot to say so.
  """
  runs = scene.runs
  for index, one in enumerate(runs):
    for other in runs[index + 1:]:
      if one.horizontal != other.horizontal or not _unrelated(scene, one, other):
        continue
      gap = abs(one.fixed - other.fixed)
      if gap >= WIRE_GAP:
        continue
      shared = _overlap(one.lo, one.hi, other.lo, other.hi)
      if shared <= TOUCHING:
        continue

      key = _pair_key(one.net_id, other.net_id)
      middle = (max(one.lo, other.lo) + min(one.hi, other.hi)) / 2.0
      fixed = (one.fixed + other.fixed) / 2.0
      at = (middle, fixed) if one.horizontal else (fixed, middle)
      names = (scene.net_name(one.net_id), scene.net_name(other.net_id))

      if gap <= TOUCHING:
        report.add(key, gap, Violation(
          "wire-short", "error", "nets %s and %s" % names,
          "drawn on top of each other for %d units: two different nets that "
          "share no pin, so this reads as one wire and hides a short"
          % round(shared), at))
      else:
        report.add(key, gap, Violation(
          "wire-spacing", "warning", "nets %s and %s" % names,
          "run %.1f apart for %d units, closer than the %.0f two wires need "
          "to read as two" % (gap, round(shared), WIRE_GAP), at))


def _check_wire_contact(scene, report):
  """A wire ending on another net's wire, which is drawn as a connection.

  Three wire ends meeting at a point get a junction dot, and a junction dot
  means connected. When the third one belongs to a different net the dot is a
  lie -- and it is the drawing's most convincing lie, because a dot is exactly
  what a real connection looks like.
  """
  by_net = {}
  for run in scene.runs:
    by_net.setdefault(run.net_id, []).append(run)

  for net_id, runs in sorted(by_net.items()):
    points = set()
    for run in runs:
      points.add(run.a)
      points.add(run.b)
    for point in sorted(points):
      for other in scene.runs:
        if other.net_id == net_id or scene.same_node(net_id, other.net_id):
          continue
        along, across = (point[0], point[1]) if other.horizontal \
            else (point[1], point[0])
        if abs(across - other.fixed) > TOUCHING:
          continue
        # Strictly inside the other run: an end meeting an end is two wires
        # stopping at the same place, which the spacing check already sees.
        if not (other.lo + TOUCHING < along < other.hi - TOUCHING):
          continue
        report.add(_pair_key(net_id, other.net_id), 0.0, Violation(
          "wire-short", "error",
          "nets %s and %s" % (scene.net_name(net_id),
                              scene.net_name(other.net_id)),
          "net %s ends on the middle of net %s, which is drawn as a junction "
          "dot: the drawing says these are connected and the file does not"
          % (scene.net_name(net_id), scene.net_name(other.net_id)), point))


def _check_wire_crossings(scene, report):
  """Crossings that get no bridge, and so read as connections.

  The renderer bridges a crossing so the eye can follow each wire through, but
  it skips any crossing that lands on a wire corner -- including a third net's
  corner, which has nothing to do with either wire. That leaves two nets
  meeting at a bare point, which is what a connection looks like.
  """
  if not scene.hops_drawn:
    return
  bridged = set()
  for net_id, spot in scene.hops:
    bridged.add((net_id, round(spot[0], 3), round(spot[1], 3)))

  for one in scene.runs:
    if not one.horizontal:
      continue
    for other in scene.runs:
      if other.horizontal or not _unrelated(scene, one, other):
        continue
      x, y = other.fixed, one.fixed
      if not (one.lo + TOUCHING < x < one.hi - TOUCHING):
        continue
      if not (other.lo + TOUCHING < y < other.hi - TOUCHING):
        continue
      if (one.net_id, round(x, 3), round(y, 3)) in bridged:
        continue
      report.add(("wire-crossing", one.net_id, other.net_id, round(x), round(y)),
                 0.0, Violation(
        "wire-crossing", "error",
        "nets %s and %s" % (scene.net_name(one.net_id),
                            scene.net_name(other.net_id)),
        "cross with no bridge drawn, so the crossing reads as a connection",
        (x, y)))


def _check_wires_and_cells(scene, report):
  """Wires through and alongside blocks they do not connect to.

  A wire drawn across a gate is the worst of these: the reader cannot tell
  whether it stops at the block or passes behind it, and neither reading is
  written down anywhere. A wire merely grazing one is milder, but it still
  suggests a connection that is not there.
  """
  for run in scene.runs:
    box = run.box()
    for placed in scene.cells:
      if scene.connects(run.net_id, placed.id):
        continue
      limit = PORT_TO_WIRE if placed.port else WIRE_TO_CELL
      rule = "port-to-wire" if placed.port else "wire-to-cell"
      key = (rule, run.net_id, placed.id)
      where = "net %s and %s %s" % (scene.net_name(run.net_id),
                                    "port" if placed.port else "cell",
                                    placed.name())
      if _boxes_overlap(box, placed.box):
        report.add(("wire-over-cell", run.net_id, placed.id), -1.0, Violation(
          "wire-over-cell", "error", where,
          "the wire is drawn across the body, so it reads either as stopping "
          "there or as passing behind it and the drawing does not say which",
          _midpoint(run.a, run.b)))
        continue
      gap = _box_gap(box, placed.box)
      if gap < limit:
        report.add(key, gap, Violation(
          rule, "warning", where,
          "the wire passes %.1f away, closer than the %.0f needed to read as "
          "passing rather than joining" % (gap, limit),
          _midpoint(run.a, run.b)))


def _check_wire_shape(scene, report):
  """Jogs too short to read as deliberate.

  A step of a few units between two turns does not read as a wire going round
  something. It reads as a wire that missed, which makes a reader look for the
  obstacle that is not there.
  """
  for run in scene.runs:
    if not run.inner or run.length() >= WIRE_MIN_JOG:
      continue
    report.add(("wire-jog", run.net_id, round(run.a[0]), round(run.a[1])),
               run.length(), Violation(
      "wire-jog", "warning", "net %s" % scene.net_name(run.net_id),
      "a %.1f-unit jog reads as a wobble rather than a step around something; "
      "%.0f is the shortest that reads as deliberate"
      % (run.length(), WIRE_MIN_JOG), _midpoint(run.a, run.b)))


def _check_cell_spacing(scene, report):
  """How close two parts may sit, with ports held further apart than gates.

  A port is a small outline and carries the name of a signal leaving the
  sheet. Two of them at gate spacing still read as one connector block with
  two arrows in it, so they get a rule of their own rather than the one
  written for parts with bodies.
  """
  cells = scene.cells
  for index, one in enumerate(cells):
    for other in cells[index + 1:]:
      if _boxes_overlap(one.box, other.box):
        report.add(("cell-overlap", one.id, other.id), -1.0, Violation(
          "cell-overlap", "error", "%s and %s" % (one.name(), other.name()),
          "the two bodies are drawn in the same place and read as one part",
          _midpoint((one.box[0], one.box[1]), (other.box[2], other.box[3]))))
        continue

      if one.port and other.port:
        rule, limit = "port-spacing", PORT_GAP
      elif one.port or other.port:
        rule, limit = "port-to-cell", PORT_TO_CELL
      else:
        rule, limit = "cell-spacing", CELL_MIN_GAP

      gap = _box_gap(one.box, other.box)
      if gap >= limit:
        continue
      report.add((rule, one.id, other.id), gap, Violation(
        rule, "warning", "%s and %s" % (one.name(), other.name()),
        "sit %.1f apart, closer than the %.0f two of these need to read as "
        "two" % (gap, limit),
        _midpoint((one.box[0], one.box[1]), (other.box[2], other.box[3]))))


def _check_text(scene, report):
  """Names against wires, bodies and other names.

  Text is the first thing a crowded drawing loses. A wire can be followed by
  eye through whatever it crosses; a word with a wire through it is simply
  gone, and no amount of squinting recovers which word it was.
  """
  wires = [(run, run.box()) for run in scene.runs]

  for placed in scene.cells:
    if not placed.label_box:
      continue
    box = placed.label_box
    where = "name of %s" % placed.name()

    for run, run_box in wires:
      gap = _box_gap(box, run_box)
      if gap >= TEXT_TO_WIRE:
        continue
      report.add(("text-to-wire", placed.id, run.net_id), gap, Violation(
        "text-to-wire", "warning",
        "%s and net %s" % (where, scene.net_name(run.net_id)),
        "the name sits %.1f from the wire, and text needs %.0f of air to stay "
        "readable" % (gap, TEXT_TO_WIRE), _midpoint(run.a, run.b)))

    for other in scene.cells:
      if other is placed:
        continue
      gap = _box_gap(box, other.box)
      if gap >= TEXT_TO_CELL:
        continue
      report.add(("text-to-cell", placed.id, other.id), gap, Violation(
        "text-to-cell", "warning", "%s and %s" % (where, other.name()),
        "the name sits %.1f from the neighbouring body, so it reads as "
        "belonging to that one rather than to its own cell"
        % gap, (box[0], box[1])))

  texts = scene.text_boxes()
  for index, (what, box) in enumerate(texts):
    for other_what, other_box in texts[index + 1:]:
      gap = _box_gap(box, other_box)
      if gap >= TEXT_TO_TEXT:
        continue
      report.add(("text-to-text", what, other_what), gap, Violation(
        "text-to-text", "warning", "%s and %s" % (what, other_what),
        "two names sit %.1f apart and run into each other" % gap,
        (box[0], box[1])))

  cell_boxes = [(placed, placed.box) for placed in scene.cells]
  for net_id, box in sorted(scene.net_label_boxes.items()):
    for run, run_box in wires:
      if run.net_id == net_id or _box_gap(box, run_box) >= LABEL_CLEARANCE:
        continue
      report.add(("net-label", net_id, run.net_id), 0.0, Violation(
        "net-label", "warning", "name of net %s" % scene.net_name(net_id),
        "there was nowhere clear to write it, so it sits on net %s"
        % scene.net_name(run.net_id), _midpoint((box[0], box[1]),
                                                (box[2], box[3]))))
    for placed, cell_box in cell_boxes:
      if _box_gap(box, cell_box) >= LABEL_CLEARANCE:
        continue
      report.add(("net-label", net_id, placed.id), 0.0, Violation(
        "net-label", "warning", "name of net %s" % scene.net_name(net_id),
        "there was nowhere clear to write it, so it sits on %s"
        % placed.name(), _midpoint((box[0], box[1]), (box[2], box[3]))))


def _check_hops(scene, report):
  """Crossing bridges against each other, the corners, the bodies and the text.

  A bridge is a bulge in a wire, and a bulge only reads as "this crossing is
  not a connection" when there is flat wire either side of it. Two of them
  touching become one squiggle; one over a corner deforms the corner, which is
  how a junction is drawn, so the reader loses the connection as well.
  """
  hops = scene.hops
  for index, (net_id, spot) in enumerate(hops):
    for other_id, other in hops[index + 1:]:
      gap = math.hypot(spot[0] - other[0], spot[1] - other[1])
      if gap >= HOP_GAP:
        continue
      where = "net %s" % scene.net_name(net_id) if net_id == other_id else \
          "nets %s and %s" % (scene.net_name(net_id), scene.net_name(other_id))
      report.add(("hop-spacing", round(spot[0]), round(spot[1]),
                  round(other[0]), round(other[1])), gap, Violation(
        "hop-spacing", "warning", where,
        "two crossing bridges %.1f apart merge into one squiggle; %.0f keeps "
        "them separate" % (gap, HOP_GAP), spot))

    corners_near = [point for point in scene.vertices
                    if math.hypot(spot[0] - point[0],
                                  spot[1] - point[1]) < HOP_TO_CORNER]
    if corners_near:
      nearest = min(math.hypot(spot[0] - p[0], spot[1] - p[1])
                    for p in corners_near)
      report.add(("hop-to-corner", round(spot[0]), round(spot[1])), nearest,
                 Violation(
        "hop-to-corner", "warning", "net %s" % scene.net_name(net_id),
        "a crossing bridge sits %.1f from a wire corner and deforms it, and a "
        "deformed corner is a junction the reader stops trusting" % nearest,
        spot))

    for placed in scene.cells:
      gap = _box_gap(_point_box(spot), placed.box)
      if gap >= HOP_TO_CELL:
        continue
      report.add(("hop-to-cell", round(spot[0]), round(spot[1]), placed.id),
                 gap, Violation(
        "hop-to-cell", "warning",
        "net %s and %s" % (scene.net_name(net_id), placed.name()),
        "a crossing bridge sits %.1f from the body, with nothing behind it to "
        "be seen against" % gap, spot))

    for what, text_box in scene.text_boxes():
      gap = _box_gap(_point_box(spot), text_box)
      if gap >= HOP_TO_TEXT:
        continue
      report.add(("hop-to-text", round(spot[0]), round(spot[1]), what), gap,
                 Violation(
        "hop-to-text", "warning",
        "net %s and %s" % (scene.net_name(net_id), what),
        "a crossing bridge sits %.1f from the text and breaks it up" % gap,
        spot))


def _check_sheet(scene, report):
  """Drawing against the edge of the paper.

  Off the sheet is an error because the exporter crops to the sheet, so those
  parts are not in the file anyone else opens. Close to the edge is a warning
  because a printer's own margin will eat into it.
  """
  try:
    width = float(scene.doc.canvas.get("width") or 0)
    height = float(scene.doc.canvas.get("height") or 0)
  except (TypeError, ValueError):
    return
  if width <= 0 or height <= 0:
    return

  pieces = [(placed.name(), placed.box) for placed in scene.cells]
  pieces.extend(("net %s" % scene.net_name(run.net_id), run.box())
                for run in scene.runs)
  pieces.extend(scene.text_boxes())

  for what, box in pieces:
    outside = max(-box[0], -box[1], box[2] - width, box[3] - height)
    if outside > 0:
      report.add(("off-sheet", what), -outside, Violation(
        "off-sheet", "error", what,
        "sticks %.1f outside the %dx%d sheet, so the exporter crops it away"
        % (outside, round(width), round(height)), (box[0], box[1])))
      continue
    margin = min(box[0], box[1], width - box[2], height - box[3])
    if margin < SHEET_EDGE:
      report.add(("sheet-edge", what), margin, Violation(
        "sheet-edge", "warning", what,
        "sits %.1f from the edge of the sheet, inside the %.0f a printer's "
        "own margin needs" % (margin, SHEET_EDGE), (box[0], box[1])))
