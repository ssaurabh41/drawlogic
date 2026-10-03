"""Document to SVG.

This is the only place that turns a drawing into a file. The GUI's Export
hands its document to this same function rather than screenshotting the
canvas, so what you export from the browser and what you export from the
terminal are the same bytes.

Usage:

    from drawlogic.doc import Document
    from drawlogic import render_svg

    document = Document.load("alu_ctrl.dlg")

    svg = render_svg.render(document)                  # the whole sheet
    svg = render_svg.render(document, zoom=2.0)        # twice the output size
    svg = render_svg.render(document, crop=True)       # trimmed to the drawing
    svg = render_svg.render(document, show_grid=True, background="none")

    open("alu_ctrl.svg", "w").write(svg)

Geometry always lives in the viewBox; `zoom` and `width` only scale the
width/height attributes, so output stays vector-perfect at any size.
"""

import math
from . import routing
from . import drc
from . import theme
from .geometry import Buckets, corners, fmt, hop_radii, label_lines, line_head
from .symbols import default_registry

DEFAULT_MARGIN = 24.0


def esc(text):
  """Escape text for use in XML content or a double-quoted attribute."""
  return (str(text)
          .replace("&", "&amp;")
          .replace("<", "&lt;")
          .replace(">", "&gt;")
          .replace('"', "&quot;"))


def _attrs(pairs):
  parts = []
  for name, value in pairs:
    if value is None:
      continue
    parts.append('%s="%s"' % (name, esc(value)))
  return " ".join(parts)


def _color(spec, cell_style, key, fallback=None):
  """Resolve a role's colour spec against the element's own style.

  `fallback` is the role's own default, used only when the element sets no
  colour of its own -- so a port comes out tinted, and a port somebody has
  recoloured comes out the colour they chose.
  """
  if spec == "none":
    return "none"
  if spec == "cell":
    if key in cell_style:
      return cell_style[key]
    if fallback:
      return theme.COLORS.get(fallback, fallback)
    return theme.COLORS[key if key in theme.COLORS else "stroke"]
  return theme.COLORS.get(spec, spec)


def _role_paint(role, cell_style, scale, font_scale):
  """SVG paint attributes for one symbol draw-op role."""
  spec = theme.ROLE_STYLES.get(role) or theme.ROLE_STYLES["body"]
  paint = {}

  paint["fill"] = _color(spec.get("fill", "none"), cell_style, "fill",
                         spec.get("fillDefault"))
  paint["stroke"] = _color(spec.get("stroke", "none"), cell_style, "stroke")

  width_key = spec.get("width")
  if width_key:
    if width_key == "stroke" and "strokeWidth" in cell_style:
      width = float(cell_style["strokeWidth"])
    else:
      width = theme.WIDTHS.get(width_key, theme.WIDTHS["stroke"])
    # Undo the cell's own scaling so a gate drawn at double size keeps the
    # same line weight instead of turning into a fat blob.
    paint["stroke-width"] = fmt(width / scale if scale else width, 3)

  if spec.get("dash"):
    paint["stroke-dasharray"] = spec["dash"]

  if spec.get("font"):
    paint["font-size"] = fmt(theme.FONT_SIZES[spec["font"]] * font_scale, 2)
    paint["font-family"] = theme.FONT_SANS

  return paint


def _op_element(op, paint):
  """One symbol draw op as an SVG element, in the symbol's own coordinates."""
  kind = op["op"]
  pairs = sorted(paint.items())

  if kind == "path":
    return "<path %s />" % _attrs([("d", op["d"])] + pairs)

  if kind == "line":
    # A line can never be filled; leaving fill set makes open paths look solid.
    pairs = [(k, v) for k, v in pairs if k != "fill"]
    return "<line %s />" % _attrs([
      ("x1", fmt(op["x1"])), ("y1", fmt(op["y1"])),
      ("x2", fmt(op["x2"])), ("y2", fmt(op["y2"]))] + pairs)

  if kind == "rect":
    return "<rect %s />" % _attrs([
      ("x", fmt(op["x"])), ("y", fmt(op["y"])),
      ("width", fmt(op["w"])), ("height", fmt(op["h"]))] + pairs)

  if kind == "ellipse":
    return "<ellipse %s />" % _attrs([
      ("cx", fmt(op["cx"])), ("cy", fmt(op["cy"])),
      ("rx", fmt(op["rx"])), ("ry", fmt(op["ry"]))] + pairs)

  if kind == "circle":
    return "<circle %s />" % _attrs([
      ("cx", fmt(op["cx"])), ("cy", fmt(op["cy"])), ("r", fmt(op["r"]))] + pairs)

  if kind == "polygon":
    points = " ".join("%s,%s" % (fmt(p[0]), fmt(p[1])) for p in op["points"])
    return "<polygon %s />" % _attrs([("points", points)] + pairs)

  return ""


def _grid_defs(grid):
  """Pattern definitions for the canvas grid, only emitted when it is shown."""
  size = float(grid.get("size", 10) or 10)
  color = grid.get("color", theme.COLORS["grid"])
  style = grid.get("style", "dots")

  if style == "dots":
    return ('<pattern id="dl-grid" width="%s" height="%s" patternUnits="userSpaceOnUse">'
            '<circle cx="0.6" cy="0.6" r="0.75" fill="%s" /></pattern>'
            % (fmt(size), fmt(size), esc(color)))
  if style == "dots-wide":
    wide = size * 2.5
    return ('<pattern id="dl-grid" width="%s" height="%s" patternUnits="userSpaceOnUse">'
            '<circle cx="1" cy="1" r="1.15" fill="%s" /></pattern>'
            % (fmt(wide), fmt(wide), esc(color)))
  if style == "lines":
    return ('<pattern id="dl-grid" width="%s" height="%s" patternUnits="userSpaceOnUse">'
            '<path d="M%s 0 H0 V%s" fill="none" stroke="%s" stroke-width="0.7" />'
            '</pattern>' % (fmt(size), fmt(size), fmt(size), fmt(size), esc(color)))
  if style == "lines-heavy":
    major = size * 5
    return (
      '<pattern id="dl-grid-minor" width="%s" height="%s" patternUnits="userSpaceOnUse">'
      '<path d="M%s 0 H0 V%s" fill="none" stroke="%s" stroke-width="0.7" /></pattern>'
      '<pattern id="dl-grid" width="%s" height="%s" patternUnits="userSpaceOnUse">'
      '<rect width="%s" height="%s" fill="url(#dl-grid-minor)" />'
      '<path d="M%s 0 H0 V%s" fill="none" stroke="%s" stroke-width="1" /></pattern>'
      % (fmt(size), fmt(size), fmt(size), fmt(size), esc(color),
         fmt(major), fmt(major), fmt(major), fmt(major),
         fmt(major), fmt(major), esc(theme.COLORS["grid_major"])))
  return ""


def _cell_bbox(symbol, cell, scale=1.0):
  matrix = symbol.matrix_for(cell, scale)
  points = [matrix.apply(px, py) for px, py in corners(0, 0, symbol.width, symbol.height)]
  xs = [p[0] for p in points]
  ys = [p[1] for p in points]
  return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def cell_text_lines(cell):
  """The lines written inside a cell, as a list; [] when it has none.

  Stored as a list of lines, one per string. A single string is accepted too,
  split at newlines, since that is what a hand-written file is likely to hold.
  Blank lines at the end say nothing and would only make the box taller.
  """
  text = cell.get("text")
  if isinstance(text, str):
    lines = text.split("\n")
  elif isinstance(text, list):
    lines = [line if isinstance(line, str) else str(line) for line in text]
  else:
    return []
  while lines and not lines[-1].strip():
    lines.pop()
  return lines


def cell_copies(cell):
  """How many copies a cell stands for, or 0 when it is just the one."""
  value = cell.get("copies")
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return 0
  value = int(value)
  return value if value >= 2 else 0


def _cell_text_metrics(font_scale):
  size = theme.FONT_SIZES["cell_text"] * font_scale
  metrics = theme.CELL_TEXT
  return size, metrics["pad"], size * metrics["step"], size * metrics["char"]


def cell_text_needs(lines, font_scale=1.0):
  """The (width, height) a box needs on the sheet to hold these lines."""
  if not lines:
    return 0.0, 0.0
  size, pad, step, char = _cell_text_metrics(font_scale)
  widest = max(len(line) for line in lines)
  return (2 * pad + widest * char, 2 * pad + size + (len(lines) - 1) * step)


def cell_text_layout(symbol, cell, symbol_scale=1.0, font_scale=1.0):
  """Where each line inside a cell is drawn, and whether any had to be cut.

  Returns ([(x, baseline, text), ...], clipped), `x` being each line's
  middle. Centred in the cell's box on the sheet, across and down, upright
  whatever the cell's rotation: a block reads as a label on the thing, and a
  label sits in the middle. A line too wide for the box ends in an ellipsis,
  and the lines that do not fit are dropped with an ellipsis on the last one
  shown -- `clipped` says so, which is what the DRC reports. Text cut short
  that way fills the box from the top, there being no room left to centre it
  in. With fit-to-text on, nothing is clipped.
  """
  lines = cell_text_lines(cell)
  if not lines:
    return [], False
  x, y, w, h = _cell_bbox(symbol, cell, symbol_scale)
  size, pad, step, char = _cell_text_metrics(font_scale)
  room = max(0, int((w - 2 * pad) / char + 1e-6))
  placed = []
  clipped = False
  for index, line in enumerate(lines):
    baseline = y + pad + size * 0.8 + index * step
    if baseline + size * 0.2 > y + h - pad + 1e-6:
      clipped = True
      if placed:
        last_x, last_y, last = placed[-1]
        placed[-1] = (last_x, last_y, _ellipsis(last, room, force=True))
      break
    if len(line) > room:
      clipped = True
      line = _ellipsis(line, room)
    placed.append((x + w / 2.0, baseline, line))
  if placed and not clipped:
    # Down the middle: what is left over below the block, shared above it.
    block = size + (len(placed) - 1) * step
    drop = max(0.0, (h - 2 * pad - block) / 2.0)
    placed = [(px, py + drop, text) for px, py, text in placed]
  return placed, clipped


def _ellipsis(line, room, force=False):
  """Cut a line to `room` characters, the last of them an ellipsis."""
  if room <= 0:
    return ""
  if not force and len(line) <= room:
    return line
  return line[:max(0, min(len(line), room - 1))].rstrip() + "\u2026"


def fit_cell_text(symbol, cell, symbol_scale=1.0, font_scale=1.0):
  """Grow a cell until its text fits, unless fitting is switched off.

  Only ever grows: a box someone made bigger on purpose stays that size, and
  one with no text keeps the size its symbol gave it. Returns True if it grew.
  """
  if cell.get("textFit") is False:
    return False
  lines = cell_text_lines(cell)
  if not lines:
    return False
  need_w, need_h = cell_text_needs(lines, font_scale)
  _x, _y, w, h = _cell_bbox(symbol, cell, symbol_scale)
  turned = int(cell.get("rotate", 0) or 0) % 180 == 90
  grew = False
  # The box on the sheet against the cell's own w and h, which swap places
  # when the cell is turned a quarter.
  for sheet, need, key in ((w, need_w, "h" if turned else "w"),
                           (h, need_h, "w" if turned else "h")):
    own = float(cell.get(key) or 0)
    if own <= 0 or sheet >= need - 1e-6:
      continue
    cell[key] = math.ceil(own * need / sheet)
    grew = True
  return grew


# The draw-op roles that make up a symbol's outline, as against its pin stubs,
# decoration and labels. A copy drawn behind a cell is these and nothing else.
STACK_ROLES = ("body", "bubble", "port_in", "port_out", "port_inout")


def _render_stack(symbol, cell, symbol_scale, out):
  """The outline behind a cell that stands for several copies.

  It is the symbol's own body, offset: a gate behind a gate, a flop's box
  behind a flop's box. It was the cell's bounding box once, which is the body
  only for a plain block; anything with pin stubs got a rectangle reaching out
  to their ends, and a gate got a rectangle behind a curve. A symbol with no
  body to copy -- a tie cell is a label and a stub -- keeps the rectangle.
  """
  if not cell_copies(cell):
    return
  style = cell.get("style") or {}
  offset = theme.CELL_TEXT["stack"]
  body = [op for op in symbol.draw
          if op["op"] != "text" and op.get("role", "body") in STACK_ROLES]
  if body:
    matrix = symbol.matrix_for(cell, symbol_scale)
    factor = matrix.scale_factor()
    for step in (1,):
      out.append('<g %s>' % _attrs([
        ("class", "dl-stack"),
        ("transform", "translate(%s %s) %s" % (
          fmt(offset * step), fmt(offset * step), matrix.to_svg()))]))
      for op in body:
        element = _op_element(op, _role_paint(op.get("role", "body"), style,
                                              factor, 1.0))
        if element:
          out.append("  " + element)
      out.append("</g>")
    return
  x, y, w, h = _cell_bbox(symbol, cell, symbol_scale)
  for step in (1,):
    out.append("<rect %s />" % _attrs([
      ("class", "dl-stack"),
      ("x", fmt(x + offset * step)), ("y", fmt(y + offset * step)),
      ("width", fmt(w)), ("height", fmt(h)),
      ("fill", style.get("fill", theme.COLORS["fill"])),
      ("stroke", style.get("stroke", theme.COLORS["stroke"])),
      ("stroke-width", fmt(style.get("strokeWidth", theme.WIDTHS["stroke"]), 3))]))


def _render_cell_text(symbol, cell, symbol_scale, font_scale, out):
  """The lines written inside a cell, and the count badge of a replicated one."""
  size = theme.FONT_SIZES["cell_text"] * font_scale
  placed, _clipped = cell_text_layout(symbol, cell, symbol_scale, font_scale)
  for x, y, line in placed:
    out.append("<text %s>%s</text>" % (_attrs([
      ("class", "dl-cell-text"),
      ("x", fmt(x)), ("y", fmt(y)),
      ("text-anchor", "middle"),
      ("font-family", theme.FONT_SANS),
      ("font-size", fmt(size, 2)),
      ("fill", theme.COLORS["label"])]), esc(line)))
  copies = cell_copies(cell)
  if copies:
    bx, by, bw, _bh = _cell_bbox(symbol, cell, symbol_scale)
    text = "\u00d7%d" % copies
    width = 12 + len(text) * 6.5
    left = bx + bw - width + 4
    out.append("<rect %s />" % _attrs([
      ("class", "dl-copies"),
      ("x", fmt(left)), ("y", fmt(by - 9)),
      ("width", fmt(width)), ("height", "18"), ("rx", "9"),
      ("fill", theme.COLORS["label"])]))
    out.append("<text %s>%s</text>" % (_attrs([
      ("x", fmt(left + width / 2.0)), ("y", fmt(by + 4)),
      ("text-anchor", "middle"),
      ("font-family", theme.FONT_SANS),
      ("font-size", "11"),
      ("font-weight", "700"),
      ("fill", theme.COLORS["fill"])]), esc(text)))


def _render_cell(symbol, cell, font_scale, out, symbol_scale=1.0):
  """Draw one placed cell: its shapes transformed, its text kept upright."""
  _render_stack(symbol, cell, symbol_scale, out)
  matrix = symbol.matrix_for(cell, symbol_scale)
  # Distinct from symbol_scale: this is how much the matrix magnifies, and it
  # is what stroke widths are divided by so line weight stays constant.
  stroke_factor = matrix.scale_factor()
  style = cell.get("style") or {}

  shape_ops = [op for op in symbol.draw if op["op"] != "text"]
  text_ops = [op for op in symbol.draw if op["op"] == "text"]

  out.append('<g %s>' % _attrs([
    ("class", "dl-cell"),
    ("data-id", cell.get("id")),
    ("data-type", cell.get("type")),
    ("transform", matrix.to_svg())]))

  image = cell.get("image")
  if image:
    # Older renderers still want xlink:href, so emit both spellings; the
    # root element declares the xlink namespace when any image is present.
    out.append("  <image %s />" % _attrs([
      ("href", image), ("xlink:href", image),
      ("x", "0"), ("y", "0"),
      ("width", fmt(symbol.width)), ("height", fmt(symbol.height)),
      ("preserveAspectRatio", "xMidYMid meet")]))

  for op in shape_ops:
    # A picture replaces the placeholder outline rather than sitting under it.
    if image and op.get("role") == "ghost":
      continue
    element = _op_element(
      op, _role_paint(op.get("role", "body"), style, stroke_factor, font_scale))
    if element:
      out.append("  " + element)
  out.append("</g>")

  # Pin labels ride along with the cell but are drawn upright and at a fixed
  # size, so a rotated or enlarged gate still has readable pin names.
  mirrored = bool(cell.get("mirror", False))
  overrides = dict(cell.get("pins") or {})
  for op in text_ops:
    # A cell may rename a pin the symbol already labels: same spot, new word.
    text = op["text"]
    named = op.get("pin")
    if named in overrides:
      text = overrides.pop(named)
      if not text:
        continue
    x, y, anchor = pin_label_spot(op, text, cell, matrix, font_scale)
    _pin_label(x, y, anchor, text, font_scale, out)

  # Whatever is left names a pin the symbol draws no label for -- a generic
  # block, say -- so place one from the pin's own geometry instead.
  for pin_name, text in overrides.items():
    if not text:
      continue
    spot = _free_pin_label(symbol, cell, pin_name, symbol_scale)
    if spot:
      (x, y), anchor = spot
      _pin_label(x, y, anchor, text, font_scale, out)

  label = cell.get("label")
  if label:
    lines = label_lines(label)
    size = theme.FONT_SIZES["label"] * font_scale
    x, top, anchor = cell_label_place(symbol, cell, symbol_scale, font_scale)
    # A name that fits on one line is drawn exactly as it always was: no
    # tspan, so the markup for the common case does not change at all.
    if len(lines) == 1:
      spans = esc(lines[0])
    else:
      spans = "".join(
        "<tspan %s>%s</tspan>" % (
          _attrs([("x", fmt(x)),
                  ("y", fmt(top + index * size * LINE_STEP))]),
          esc(line))
        for index, line in enumerate(lines))
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(x)),
        ("y", fmt(top)),
        ("text-anchor", anchor),
        ("font-family", theme.FONT_SANS),
        ("font-size", fmt(size, 2)),
        ("font-weight", "600"),
        ("fill", theme.COLORS["label"])]),
      spans))

  _render_cell_text(symbol, cell, symbol_scale, font_scale, out)


# Where a pin name's middle sits above its baseline, as a fraction of the font
# size: near enough the centre of a capital for a label to be centred on it.
PIN_LABEL_RISE = 0.35


def pin_label_spot(op, text, cell, matrix, font_scale=1.0):
  """Where a symbol's own pin label is drawn: (x, baseline, anchor).

  The symbol places it for the cell standing upright: an anchor point inside
  the body and a direction for the text to run. Mirrored, the direction
  flips and that is all. Rotated, carrying only the anchor point round left
  the text running the way it always did -- off the edge the point now sat
  by, so a turned flop had its pin names outside the box.

  So a rotated label is placed by its middle instead: the middle of where
  the text sits upright, carried through the rotation, with the text centred
  on it. A label inside the body stays inside the body at any angle. Upright
  cells are drawn exactly as before.
  """
  anchor = op.get("anchor", "start")
  if not (cell.get("rotate") or 0) % 360:
    x, y = matrix.apply(op["x"], op["y"])
    if cell.get("mirror"):
      anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
    return x, y, anchor
  size = theme.FONT_SIZES["pin_label"] * font_scale
  # The text is a fixed size whatever the cell's scale, so its width in the
  # symbol's own units is its drawn width undone by the cell's magnification.
  factor = matrix.scale_factor() or 1.0
  half = len(text) * size * LABEL_CHAR / 2.0 / factor
  shift = {"start": half, "end": -half}.get(anchor, 0.0)
  x, y = matrix.apply(op["x"] + shift, op["y"] - size * PIN_LABEL_RISE / factor)
  return x, y + size * PIN_LABEL_RISE, "middle"


def _pin_label(x, y, anchor, text, font_scale, out):
  """One pin name, upright and at a fixed size whatever the cell is doing."""
  out.append("<text %s>%s</text>" % (
    _attrs([
      ("x", fmt(x)), ("y", fmt(y)),
      ("text-anchor", anchor),
      ("font-family", theme.FONT_SANS),
      ("font-size", fmt(theme.FONT_SIZES["pin_label"] * font_scale, 2)),
      ("fill", theme.COLORS["pin_label"])]),
    esc(text)))


def _free_pin_label(symbol, cell, pin_name, symbol_scale):
  """Where to write a name for a pin the symbol itself does not label.

  Set just inside the body, on the face the pin sits on, so it reads as the
  block's own labelling rather than as a stray note. Returns sheet
  coordinates and a text anchor, or None if the pin does not exist.
  """
  pin = symbol.pin(pin_name)
  if pin is None:
    return None

  inset = theme.PIN_LABEL_INSET
  if pin["x"] <= 1e-6:
    local, anchor = (pin["x"] + inset, pin["y"] + 4), "start"
  elif pin["x"] >= symbol.width - 1e-6:
    local, anchor = (pin["x"] - inset, pin["y"] + 4), "end"
  elif pin["y"] <= 1e-6:
    local, anchor = (pin["x"], pin["y"] + inset + 4), "middle"
  else:
    local, anchor = (pin["x"], pin["y"] - inset), "middle"

  matrix = symbol.matrix_for(cell, symbol_scale)
  if cell.get("mirror"):
    anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
  return matrix.apply(local[0], local[1]), anchor


def _walk(points, distance):
  """The point a given way along a path, and the direction of travel there."""
  for index in range(len(points) - 1):
    ax, ay = points[index]
    bx, by = points[index + 1]
    length = abs(bx - ax) + abs(by - ay)
    if length <= 0:
      continue
    if distance <= length:
      ratio = distance / length
      return ((ax + (bx - ax) * ratio, ay + (by - ay) * ratio),
              ((bx - ax) / length, (by - ay) / length),
              min(distance, length - distance))
    distance -= length
  return None


def _path_length(points):
  return sum(abs(points[i + 1][0] - points[i][0])
             + abs(points[i + 1][1] - points[i][1])
             for i in range(len(points) - 1))


def text_marks(doc, registry, routes, scale, font_scale):
  """Every name on the sheet, as boxes an arrow should stay out of.

  Public, and the browser has the same function, for the reason arrow_marks
  is: the parity test has to ask the renderer the question it asks itself,
  not a reconstruction of it.
  """
  boxes = []
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    written = cell_label_box(symbol, cell, scale, font_scale)
    if written is not None:
      boxes.append(written)
  for written in net_label_boxes(doc, registry, routes).values():
    if written is not None:
      boxes.append(written)
  return boxes


def arrow_marks(junctions, hop_map):
  """Everything an arrow has to keep clear of: junction dots and hop bridges.

  Public, and the browser has the same function, because the parity test has
  to ask what the renderer asks. It used to build its own list and leave the
  hops out -- and so did the browser, so the two agreed with each other and
  the test passed while the editor drew an arrow on a bridge the exported
  file did not have. Two copies matching is not the same as either being
  right, and only one of them was being rendered.
  """
  return list(junctions) + [spot for spots in hop_map.values()
                            for spot in spots]


def _arrow_spots(points, size, spacing=None, junctions=(), text=()):
  """Where a wire's direction arrows go, and which way each one points.

  One always sits near the receiving end, which is where a reader looks to ask
  "what drives this?". On a long run that arrow is nowhere near most of the
  wire, so more are spaced along it -- close enough that the direction reads
  wherever the eye lands, far enough apart that the wire does not turn into a
  dotted line. Arrows are kept off corners, where a head pointing into the
  bend is worse than no head at all.

  They are kept off junction dots too. Both are small solid marks in the same
  ink, so an arrow on a dot reads as one slightly fatter arrow, and the
  connection the dot announced is lost. The dot is the more important of the
  two -- it is the only thing saying these wires are joined -- so the arrow is
  the one that gives way.

  `text` is every name on the sheet, and the same rule applies to it, only
  more so: a name is the one thing on a wire that cannot be worked out from
  looking at the drawing, and an arrowhead through the middle of one costs a
  reader far more than a missing arrow does. An arrow with nowhere clear to go
  is not drawn at all.
  """
  if len(points) < 2:
    return []

  spacing = spacing or theme.ARROW_SPACING
  total = _path_length(points)

  ax, ay = points[-2]
  bx, by = points[-1]
  last = abs(bx - ax) + abs(by - ay)

  if last < size * 3:
    # The final run is too short to hold a head clear of the pin, so the arrow
    # goes in the middle of the longest run instead.
    best = None
    for index in range(len(points) - 1):
      px, py = points[index]
      qx, qy = points[index + 1]
      length = abs(qx - px) + abs(qy - py)
      if best is None or length > best[0]:
        best = (length, (px, py), (qx, qy))
    _, (px, py), (qx, qy) = best
    length = max(best[0], 1e-6)
    spots = [(((px + qx) / 2.0, (py + qy) / 2.0),
              ((qx - px) / length, (qy - py) / length))]
    keep_clear = total
  else:
    # Back off from the pin so the head does not sit on top of it.
    offset = size * 1.6
    run = max(last, 1e-6)
    spots = [((bx - (bx - ax) / run * offset, by - (by - ay) / run * offset),
              ((bx - ax) / run, (by - ay) / run))]
    keep_clear = total - offset

  extra = []
  distance = spacing
  while distance < keep_clear - spacing * 0.5:
    found = _walk(points, distance)
    if found is not None:
      spot, direction, from_corner = found
      if from_corner >= size * 2:
        extra.append((spot, direction))
    distance += spacing

  found = extra + spots
  if not junctions and not text:
    return found
  # An arrow is the most expendable mark on the sheet. Everything else it
  # might land on -- a junction dot, a crossing bridge, a name -- carries
  # something the reader cannot work out for themselves, while the direction
  # of a wire is usually obvious from the pins at its ends. So the arrow moves
  # along the wire to somewhere clear, and goes without rather than sit on top
  # of any of them.
  clear = []
  for tip, direction in found:
    moved = _slide_clear(points, tip, direction, size, junctions, text)
    if moved is not None:
      clear.append(moved)
  return clear


def arrow_spots_for(branches, mode, size, junctions=(), text=()):
  """Every arrowhead on one wire, for an arrow mode from routing.ARROW_MODES.

  Per branch: every load wants to know which way the signal reaches it. A
  wire pointing backward is the same wire walked from the load end, so its
  heads gather near the driver; "both" is the two together. Branches share
  their trunk near the driver, so heads walked from that end land on the
  same spots more than once; there a spot is only drawn the first time.
  """
  if mode == "none":
    return []
  walks = []
  for points in branches:
    if len(points) < 2:
      continue
    if mode in ("forward", "both"):
      walks.append(points)
    if mode in ("backward", "both"):
      walks.append(list(reversed(points)))
  found = []
  seen = set()
  for points in walks:
    for tip, direction in _arrow_spots(points, size, junctions=junctions,
                                       text=text):
      # Floor rather than round(), which rounds halves to even where the
      # browser's copy of this rounds them up.
      key = (math.floor(tip[0] * 10 + 0.5), math.floor(tip[1] * 10 + 0.5),
             math.floor(direction[0] * 1000 + 0.5),
             math.floor(direction[1] * 1000 + 0.5))
      if key in seen and mode != "forward":
        continue
      seen.add(key)
      found.append((tip, direction))
  return found


def _blocked(tip, size, junctions, text):
  """Whether an arrowhead here would land on something that matters more."""
  if not _clear_of(tip, junctions, drc.ARROW_TO_JUNCTION):
    return True
  half = size / 2.0
  for x0, y0, x1, y1 in text:
    if (x0 - half <= tip[0] <= x1 + half
        and y0 - half <= tip[1] <= y1 + half):
      return True
  return False


# How far along the wire an arrow will shuffle looking for a clear spot, and
# in what steps. Far enough to clear a name, short enough that the head stays
# on the stretch of wire it was describing.
SLIDE_REACH = 44.0
SLIDE_STEP = 4.0


def _slide_clear(points, tip, direction, size, junctions, text):
  """Move an arrow along its wire until it sits clear, or give it up.

  Tried where it wanted to be first, then a little either way, so an arrow
  only moves as far as it has to and a wire with room keeps its head where it
  reads best -- near the end that receives the signal.
  """
  if not _blocked(tip, size, junctions, text):
    return (tip, direction)

  at = _distance_along(points, tip)
  if at is None:
    return None
  step = SLIDE_STEP
  while step <= SLIDE_REACH:
    for away in (-step, step):
      found = _walk(points, at + away)
      if found is None:
        continue
      spot, heading, from_corner = found
      if from_corner < size * 2:
        continue
      if not _blocked(spot, size, junctions, text):
        return (spot, heading)
    step += SLIDE_STEP
  return None


def _distance_along(points, tip):
  """How far along a path a point sits, or None if it is not on it."""
  travelled = 0.0
  for index in range(len(points) - 1):
    a = points[index]
    b = points[index + 1]
    length = abs(b[0] - a[0]) + abs(b[1] - a[1])
    if length <= 0:
      continue
    if _on_segment(tip, a, b):
      return travelled + abs(tip[0] - a[0]) + abs(tip[1] - a[1])
    travelled += length
  return None


def _on_segment(point, a, b):
  slack = 1e-6
  return (min(a[0], b[0]) - slack <= point[0] <= max(a[0], b[0]) + slack
          and min(a[1], b[1]) - slack <= point[1] <= max(a[1], b[1]) + slack)


def _clear_of(point, others, distance):
  """True if a point keeps its distance from every one of `others`."""
  for other in others:
    if (abs(point[0] - other[0]) < distance
        and abs(point[1] - other[1]) < distance):
      return False
  return True


def _net_path(points, hops, radius):
  """The `d` for a wire, bridging over any wire it merely crosses.

  A hop is a half-circle bulging away from the reading direction, so the eye
  follows the wire through the crossing instead of stopping at it.
  """
  parts = ["M%s %s" % (fmt(points[0][0]), fmt(points[0][1]))]

  for index in range(len(points) - 1):
    ax, ay = points[index]
    bx, by = points[index + 1]

    on_this = []
    if hops and abs(ay - by) < 1e-6:
      direction = 1.0 if bx > ax else -1.0
      low, high = sorted((ax, bx))
      for hx, hy in hops:
        # Leave room for the whole arc, or it would overrun the corner.
        if abs(hy - ay) < 1e-6 and low + radius < hx < high - radius:
          on_this.append(hx)
      # Each bridge is drawn no wider than the room beside it allows, so two
      # crossings close together still show wire between their bulges rather
      # than running into one squiggle. See geometry.hop_radii.
      on_this.sort()
      radii = hop_radii(on_this, radius, drc.HOP_FLAT, MIN_HOP_RADIUS)
      if direction < 0:
        on_this.reverse()
        radii.reverse()

      for hx, hop_radius in zip(on_this, radii):
        parts.append("L%s %s" % (fmt(hx - hop_radius * direction), fmt(ay)))
        # With y pointing down, sweep 1 bulges upward when travelling right.
        sweep = 1 if direction > 0 else 0
        parts.append("A%s %s 0 0 %d %s %s"
                     % (fmt(hop_radius), fmt(hop_radius), sweep,
                        fmt(hx + hop_radius * direction), fmt(ay)))

    parts.append("L%s %s" % (fmt(bx), fmt(by)))

  return " ".join(parts)


# A whisker of air around a cell before a name counts as landing on it.
CELL_BOX_PAD = 2.0


def _cell_boxes(doc, registry):
  """Every cell's footprint, as (x0, y0, x1, y1), with room for its name.

  The instance name is drawn above the cell, so a labelled cell's box is
  taller than the cell to keep a net's name from landing on it. An unlabelled
  cell gets no headroom -- reserving space for text that is not there pushes
  net names further away than they need to go.
  """
  boxes = []
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    x, y, w, h = _cell_bbox(symbol, cell, doc.symbol_scale)
    beside = side_label_box(symbol, cell, doc.symbol_scale, doc.font_scale)
    # A wrapped name reaches a line higher, so the box grows with it.
    lines = (len(label_lines(cell["label"]))
             if cell.get("label") and beside is None else 0)
    headroom = (drc.LABEL_HEADROOM
                + (lines - 1) * theme.FONT_SIZES["label"] * LINE_STEP
                if lines else 0.0)
    boxes.append((x - CELL_BOX_PAD, y - headroom,
                  x + w + CELL_BOX_PAD, y + h + CELL_BOX_PAD))
    if beside is not None:
      boxes.append(beside)
  return boxes


def cell_label_box(symbol, cell, symbol_scale=1.0, font_scale=1.0):
  """The rectangle a cell's instance name occupies, or None if it has none.

  The DRCs need the same rectangle the renderer will draw into, so both come
  from here rather than from two guesses that can drift apart. A name long
  enough to be split sits on two lines, so the rectangle is half as wide and
  a line taller -- see geometry.label_lines.
  """
  label = cell.get("label")
  if not label:
    return None
  size = theme.FONT_SIZES["label"] * font_scale
  lines = label_lines(label)
  widest = max(lines, key=len)
  x, top, anchor = cell_label_place(symbol, cell, symbol_scale, font_scale)
  first = _label_box((x, top), anchor, widest, size)
  return (first[0], first[1], first[2],
          first[3] + (len(lines) - 1) * size * LINE_STEP)


def _pin_spots(symbol, cell, symbol_scale):
  for pin in symbol.pins:
    spot = symbol.pin_position(cell, pin["name"], symbol_scale)
    if spot is not None:
      yield spot


def cell_label_place(symbol, cell, symbol_scale=1.0, font_scale=1.0):
  """Where a cell's name goes: (x, baseline of the first line, anchor).

  Above the cell, centred, is where a reader looks for it -- unless a pin
  comes in at the top. Then that pin's wire runs straight up through the
  middle of the name, which is unreadable and a DRC fault besides. Such a
  cell's name sits beside it instead, outside the top-left corner, or the
  top-right if a pin on the left would be in the way, and only goes back
  above the cell if both sides are taken.
  """
  box = _cell_bbox(symbol, cell, symbol_scale)
  size = theme.FONT_SIZES["label"] * font_scale
  lines = label_lines(cell.get("label") or "") or [""]
  spots = list(_pin_spots(symbol, cell, symbol_scale))
  above = (box[0] + box[2] / 2.0,
           box[1] - 5 - (len(lines) - 1) * size * LINE_STEP, "middle")
  if not any(abs(y - box[1]) < 0.5 for _x, y in spots):
    return above

  # How far down the side the name reaches, and the air a wire needs from it.
  reach = box[1] + size * (len(lines) - 1) * LINE_STEP + size + drc.TEXT_TO_WIRE
  baseline = box[1] + size * 0.8

  def side_free(edge):
    return not any(abs(x - edge) < 0.5 and y <= reach for x, y in spots)

  if side_free(box[0]):
    return (box[0] - drc.TEXT_TO_CELL, baseline, "end")
  right = box[0] + box[2]
  if side_free(right):
    return (right + drc.TEXT_TO_CELL, baseline, "start")
  return above


def side_label_box(symbol, cell, symbol_scale=1.0, font_scale=1.0):
  """The name's rectangle when it sits beside its cell rather than above.

  None for a name above the cell: the router already keeps room there, as
  headroom on the cell's own box. A name beside the cell is outside that box,
  so it is handed to the router separately, to be kept clear of like a body.
  """
  if not cell.get("label"):
    return None
  _x, _top, anchor = cell_label_place(symbol, cell, symbol_scale, font_scale)
  if anchor == "middle":
    return None
  return cell_label_box(symbol, cell, symbol_scale, font_scale)


def net_label_boxes(doc, registry=None, routes=None):
  """The rectangle every net name lands in, as {net id: box}.

  The placer takes the least bad spot it can find, which in a crowded drawing
  still lands on something. Handing the chosen rectangles out lets the DRCs
  say so rather than letting a name quietly sit on a wire.
  """
  registry = registry or default_registry()
  if routes is None:
    routes = routing.route_all(doc, registry)
  placed = _label_spots(routes, _cell_boxes(doc, registry),
                        (doc.canvas.get("width"), doc.canvas.get("height")),
                        doc.font_scale)
  return dict((net_id, box)
              for net_id, (_spot, _anchor, box, _score) in placed.items())


# Where along a run a name may sit, as a fraction of the run.
LABEL_STOPS = (0.5, 0.32, 0.68, 0.16, 0.84)

# One character of the mono face, as a fraction of the font size. Close enough
# to reserve the right amount of room without measuring text properly.
LABEL_CHAR = 0.62

# A bridge squeezed between close neighbours never shrinks past this: one
# nobody can see is worse than a tight one.
MIN_HOP_RADIUS = 2.5

# Baseline-to-baseline spacing for a wrapped instance name.
LINE_STEP = 1.15


def _label_box(spot, anchor, text, size):
  """The rectangle a name will occupy, as (x0, y0, x1, y1)."""
  width = max(len(text), 1) * size * LABEL_CHAR
  if anchor == "middle":
    x0 = spot[0] - width / 2.0
  elif anchor == "end":
    x0 = spot[0] - width
  else:
    x0 = spot[0]
  # The spot is the text baseline, so most of the ink is above it.
  return (x0, spot[1] - size * 0.8, x0 + width, spot[1] + size * 0.2)


def text_shape_box(shape, font_scale=1.0):
  """The rectangle a text shape covers, as (x0, y0, x1, y1), or None.

  Public because a text annotation is content like any other, and two places
  outside this module have to know how much room it takes: the bounding box a
  cropped export is cut to, and any rule that asks what a piece of text runs
  into.

  Without this a text shape contributed only its anchor point -- a box of no
  width and no height -- so cropping an export to the content cut a long
  annotation down to whatever happened to fall within a few units of where it
  started. One letter, in the case that found this.

  The width is estimated the same way labels are, by counting characters.
  There is no font metric here and never will be; the number only has to be
  close enough to reserve the right room.
  """
  if shape.get("kind") != "text":
    return None
  text = shape.get("text")
  if not isinstance(text, str) or not text:
    return None
  style = shape.get("style") or {}
  size = float(style.get("fontSize", theme.FONT_SIZES["shape_text"])) * font_scale
  spot = (float(shape.get("x", 0)), float(shape.get("y", 0)))
  return _label_box(spot, style.get("anchor", "start"), text, size)


def _grown(box, pad):
  """A box with clear space around it.

  Overlaps are tested against this rather than the label's own rectangle, so a
  name that merely touches a wire counts as landing on it. Text needs air to
  stay readable, and zero separation is not air.
  """
  return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _boxes_overlap(a, b):
  return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _segment_box(a, b, pad=1.5):
  return (min(a[0], b[0]) - pad, min(a[1], b[1]) - pad,
          max(a[0], b[0]) + pad, max(a[1], b[1]) + pad)


def _label_candidates(branches, text, size):
  """Every place a name could reasonably go on one wire.

  Along each run of each branch, at a few points, on either side of it. The
  caller scores them; this only says what the options are.
  """
  found = []
  for points in branches:
    found.extend(_candidates_on(points, size))
  return found


def _candidates_on(points, size):
  found = []
  for index in range(len(points) - 1):
    ax, ay = points[index]
    bx, by = points[index + 1]
    horizontal = abs(by - ay) < abs(bx - ax)
    length = abs(bx - ax) + abs(by - ay)
    if length < size * 2:
      continue
    for stop in LABEL_STOPS:
      x = ax + (bx - ax) * stop
      y = ay + (by - ay) * stop
      if horizontal:
        found.append(((x, y - 4), "middle", horizontal, length, stop, False))
        found.append(((x, y + size + 2), "middle", horizontal, length, stop, True))
      else:
        found.append(((x + 5, y + 4), "start", horizontal, length, stop, False))
        found.append(((x - 5, y + 4), "end", horizontal, length, stop, True))
  return found


def _label_spots(routes, cell_boxes, sheet, font_scale):
  """Where every net's name goes, as {net id: (spot, anchor, box, score)}.

  A name that lands on a wire it has nothing to do with is worse than no name
  at all -- and picking the middle of the longest run, which is all this used
  to do, lands on one constantly. So each name is tried in several places and
  scored against the cells, the other wires, and the names already placed.

  Nets are considered in document order, so the first net stated gets the
  clearest spot, the same rule the router follows.
  """
  size = theme.FONT_SIZES["net_label"] * font_scale
  segments = [(net_id, _segment_box(a, b))
              for net_id, a, b in routing.segments_of(routes)]
  cell_index = Buckets(list(cell_boxes))
  segment_index = Buckets([box for _, box in segments])

  placed = []
  spots = {}
  for net, branches in routes:
    text = routing.net_label(net)
    if not text or not branches:
      continue
    net_id = net.get("id")

    best = None
    for spot, anchor, horizontal, length, stop, far_side in _label_candidates(
        branches, text, size):
      box = _label_box(spot, anchor, text, size)
      near = _grown(box, drc.LABEL_CLEARANCE)

      score = 0.0
      if sheet and (box[0] < 2 or box[1] < 2
                    or box[2] > sheet[0] - 2 or box[3] > sheet[1] - 2):
        score += 500
      score += 120 * cell_index.count(near)
      score += 45 * segment_index.count(
        near, lambda i: segments[i][0] != net_id)
      for other in placed:
        if _boxes_overlap(near, other):
          score += 220

      # Among equally clear spots: along a horizontal run, near the middle of
      # it, on the near side, on the longest run available.
      score += 0 if horizontal else 55
      score += 18 if far_side else 0
      score += abs(stop - 0.5) * 12
      score -= min(length, 400) / 25.0

      if best is None or score < best[0]:
        best = (score, spot, anchor, box)

    if best is not None:
      spots[net_id] = (best[1], best[2], best[3], best[0])
      placed.append(best[3])
  return spots


def _render_arrow(tip, direction, size, color, out):
  ux, uy = direction
  # Perpendicular, for the two trailing corners.
  px, py = -uy, ux
  back_x = tip[0] - ux * size
  back_y = tip[1] - uy * size
  half = size * 0.45
  points = [
    (tip[0], tip[1]),
    (back_x + px * half, back_y + py * half),
    (back_x - px * half, back_y - py * half),
  ]
  out.append("<polygon %s />" % _attrs([
    ("points", " ".join("%s,%s" % (fmt(x), fmt(y)) for x, y in points)),
    ("fill", color)]))


def _render_nets(doc, registry, font_scale, out, arrows=True, hops=True):
  """Draw every wire, and hand back the junction dots for the caller to draw.

  The dots come back rather than going down here because they have to be drawn
  after the cells. A junction dot says two wires are connected, and a dot
  painted over by the gate it sits beside says nothing at all -- which is how
  a connection quietly disappeared from drawings where a fan-out happened to
  split close to a body.
  """
  routes = routing.route_all(doc, registry)
  hop_map = routing.hop_points(routes) if hops else {}
  junctions = routing.junctions(routes)
  marks = arrow_marks(junctions, hop_map)
  names = text_marks(doc, registry, routes, doc.symbol_scale, font_scale)

  for net, branches in routes:
    if not branches:
      continue
    style = net.get("style") or {}
    # One path element per net, with a subpath per branch: a net is one thing,
    # so clicking any part of it should find the same thing.
    hops = hop_map.get(net.get("id"))
    d = " ".join(_net_path(points, hops, theme.HOP_RADIUS)
                 for points in branches)
    pattern = theme.WIRE_DASHES.get(style.get("dash"))
    out.append("<path %s />" % _attrs([
      ("class", "dl-net"),
      ("data-id", net.get("id")),
      ("d", d),
      ("fill", "none"),
      ("stroke", style.get("stroke", theme.COLORS["net"])),
      ("stroke-width", fmt(style.get("strokeWidth", routing.stroke_width(net)), 3)),
      ("stroke-dasharray", pattern["dash"] if pattern else None),
      ("stroke-linejoin", "miter"),
      ("stroke-linecap", pattern["cap"] if pattern else "square")]))

  spots = _label_spots(routes, _cell_boxes(doc, registry),
                       (doc.canvas.get("width"), doc.canvas.get("height")),
                       font_scale)
  for net, _branches in routes:
    name = routing.net_label(net)
    if not name or net.get("id") not in spots:
      continue
    (x, y), anchor = spots[net["id"]][:2]
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(x)),
        ("y", fmt(y)),
        ("text-anchor", anchor),
        ("font-family", theme.FONT_MONO),
        ("font-size", fmt(theme.FONT_SIZES["net_label"] * font_scale, 2)),
        ("fill", theme.COLORS["net_label"])]),
      esc(name)))

  if arrows:
    for net, branches in routes:
      style = net.get("style") or {}
      mode = routing.arrow_mode(doc, net, registry)
      for tip, direction in arrow_spots_for(branches, mode, theme.ARROW_SIZE,
                                            junctions=marks, text=names):
        _render_arrow(tip, direction, theme.ARROW_SIZE,
                      style.get("stroke", theme.COLORS["net"]), out)

  return junctions


def line_heads(shape):
  """A line shape's arrowheads, and its points trimmed to meet them.

  Returns (points, heads): `points` is the line to draw, each end pulled back
  to where its head begins, and `heads` the heads as line_head gives them.
  Only open lines -- line and polyline -- take heads; a polygon has no ends.
  """
  points = [tuple(p) for p in shape.get("points") or []]
  if shape.get("kind") not in ("line", "polyline") or len(points) < 2:
    return points, []
  style = shape.get("style") or {}
  width = float(style.get("strokeWidth", theme.WIDTHS["stroke"]))
  heads = []
  for key, tip, before, where in (("headStart", points[0], points[1], 0),
                                  ("headEnd", points[-1], points[-2], -1)):
    kind = style.get(key) or "none"
    size = theme.LINE_HEAD_SIZES.get(style.get(key + "Size") or "m",
                                     theme.LINE_HEAD_SIZES["m"])
    head, trim = line_head(tip, before, kind, size * width,
                           theme.LINE_HEAD_SPREAD)
    if head is not None:
      heads.append(head)
      points[where] = trim
  return points, heads


def line_head_points(head):
  """Points that bound one head, for measuring how far a drawing reaches."""
  kind, data = head
  if kind == "ellipse":
    cx, cy, rx, ry, _angle = data
    reach = max(rx, ry)
    return [(cx - reach, cy - reach), (cx + reach, cy + reach)]
  return list(data)


def _render_head(head, stroke, width, out):
  kind, data = head
  if kind == "ellipse":
    cx, cy, rx, ry, angle = data
    out.append("<ellipse %s />" % _attrs([
      ("class", "dl-head"), ("cx", fmt(cx)), ("cy", fmt(cy)),
      ("rx", fmt(rx)), ("ry", fmt(ry)),
      ("transform", "rotate(%s %s %s)" % (fmt(angle), fmt(cx), fmt(cy))),
      ("fill", stroke), ("stroke", "none")]))
    return
  coords = " ".join("%s,%s" % (fmt(x), fmt(y)) for x, y in data)
  if kind == "polyline":
    out.append("<polyline %s />" % _attrs([
      ("class", "dl-head"), ("points", coords), ("fill", "none"),
      ("stroke", stroke), ("stroke-width", fmt(width, 3)),
      ("stroke-linejoin", "miter"), ("stroke-linecap", "round")]))
    return
  out.append("<polygon %s />" % _attrs([
    ("class", "dl-head"), ("points", coords), ("fill", stroke),
    ("stroke", "none")]))


def _render_shape(shape, font_scale, out):
  style = shape.get("style") or {}
  kind = shape.get("kind")
  paint = [
    ("fill", style.get("fill", "none")),
    ("stroke", style.get("stroke", theme.COLORS["stroke"])),
    ("stroke-width", fmt(style.get("strokeWidth", theme.WIDTHS["stroke"]), 3)),
  ]
  if style.get("dash"):
    paint.append(("stroke-dasharray", style["dash"]))

  if kind == "rect":
    out.append("<rect %s />" % _attrs([
      ("x", fmt(shape["x"])), ("y", fmt(shape["y"])),
      ("width", fmt(shape.get("w", 0))), ("height", fmt(shape.get("h", 0)))] + paint))
  elif kind == "ellipse":
    out.append("<ellipse %s />" % _attrs([
      ("cx", fmt(shape["x"] + shape.get("w", 0) / 2.0)),
      ("cy", fmt(shape["y"] + shape.get("h", 0) / 2.0)),
      ("rx", fmt(shape.get("w", 0) / 2.0)),
      ("ry", fmt(shape.get("h", 0) / 2.0))] + paint))
  elif kind in ("polygon", "polyline", "line"):
    if kind == "line" and len(shape.get("points") or []) < 2:
      return
    points, heads = line_heads(shape)
    coords = " ".join("%s,%s" % (fmt(p[0]), fmt(p[1])) for p in points)
    tag = "polygon" if kind == "polygon" else "polyline"
    out.append("<%s %s />" % (tag, _attrs([("points", coords)] + paint)))
    for head in heads:
      _render_head(head, style.get("stroke", theme.COLORS["stroke"]),
                   float(style.get("strokeWidth", theme.WIDTHS["stroke"])), out)
  elif kind == "text":
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(shape.get("x", 0))), ("y", fmt(shape.get("y", 0))),
        ("text-anchor", style.get("anchor", "start")),
        ("font-family", theme.FONT_SANS),
        ("font-size", fmt(style.get("fontSize", theme.FONT_SIZES["shape_text"])
                          * font_scale, 2)),
        ("fill", style.get("fill", theme.COLORS["label"]))]),
      esc(shape.get("text", ""))))


def title_band(font_scale=1.0):
  """The room the sheet title needs along the top: air, text, air.

  Shared with web/js/render.js, which is handed TITLE_PAD and the font size
  by /api/theme rather than restating either.
  """
  return theme.TITLE_PAD * 2 + theme.FONT_SIZES["title"] * font_scale


def render(doc, registry=None, zoom=1.0, width=None, margin=None,
           background=None, show_grid=False, crop=False, title=True,
           arrows=None, hops=None):
  """Render a document to an SVG string.

  Geometry lives in the viewBox and never changes; `zoom` and `width` only
  scale the width/height attributes. That keeps the output vector-perfect at
  any size and means the GUI's zoom control and the CLI's --zoom flag are
  doing exactly the same thing.
  """
  registry = registry or default_registry()
  canvas = doc.canvas
  font_scale = doc.font_scale

  if crop:
    box = doc.content_bbox(registry)
    pad = DEFAULT_MARGIN if margin is None else float(margin)
    if box is None:
      box = (0.0, 0.0, float(canvas["width"]), float(canvas["height"]))
    view = (box[0] - pad, box[1] - pad, box[2] + 2 * pad, box[3] + 2 * pad)
    # The title sits in a band along the top of the view. Cropping tight to
    # the drawing would put that band over the first row of it, so the view
    # opens upward far enough to hold the title clear of anything drawn.
    if title and doc.title:
      band = title_band(font_scale) - pad
      if band > 0:
        view = (view[0], view[1] - band, view[2], view[3] + band)
  else:
    pad = 0.0 if margin is None else float(margin)
    view = (-pad, -pad,
            float(canvas["width"]) + 2 * pad,
            float(canvas["height"]) + 2 * pad)

  if view[2] <= 0 or view[3] <= 0:
    view = (view[0], view[1], max(view[2], 1.0), max(view[3], 1.0))

  if width is not None:
    out_width = float(width)
    out_height = out_width * view[3] / view[2]
  else:
    out_width = view[2] * float(zoom)
    out_height = view[3] * float(zoom)

  paper = background if background is not None else canvas.get("background", theme.PAPER)

  has_image = any(cell.get("image") for cell in doc.cells)

  out = []
  out.append('<?xml version="1.0" encoding="UTF-8"?>')
  out.append("<svg %s>" % _attrs([
    ("xmlns", "http://www.w3.org/2000/svg"),
    ("xmlns:xlink", "http://www.w3.org/1999/xlink" if has_image else None),
    ("width", fmt(out_width, 2)),
    ("height", fmt(out_height, 2)),
    ("viewBox", "%s %s %s %s" % (fmt(view[0]), fmt(view[1]),
                                 fmt(view[2]), fmt(view[3]))),
    ("font-family", theme.FONT_SANS)]))
  out.append("<title>%s</title>" % esc(doc.title))

  grid_defs = _grid_defs(canvas.get("grid") or {}) if show_grid else ""
  if grid_defs:
    out.append("<defs>%s</defs>" % grid_defs)

  if paper and paper != "none":
    out.append("<rect %s />" % _attrs([
      ("x", fmt(view[0])), ("y", fmt(view[1])),
      ("width", fmt(view[2])), ("height", fmt(view[3])),
      ("fill", paper)]))
  if grid_defs:
    out.append("<rect %s />" % _attrs([
      ("x", fmt(view[0])), ("y", fmt(view[1])),
      ("width", fmt(view[2])), ("height", fmt(view[3])),
      ("fill", "url(#dl-grid)")]))

  out.append('<g class="dl-shapes">')
  for shape in doc.shapes:
    _render_shape(shape, font_scale, out)
  out.append("</g>")

  show_arrows = canvas.get("arrows", True) if arrows is None else arrows
  show_hops = canvas.get("hops", True) if hops is None else hops
  out.append('<g class="dl-nets">')
  junctions = _render_nets(doc, registry, font_scale, out,
                           show_arrows, show_hops)
  out.append("</g>")

  out.append('<g class="dl-cells">')
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    _render_cell(symbol, cell, font_scale, out, doc.symbol_scale)
  out.append("</g>")

  # Last, so nothing can paint over them: a junction dot is the only mark that
  # says two wires are connected, and one hidden behind a gate is a connection
  # the drawing has stopped claiming.
  out.append('<g class="dl-junctions">')
  for point in junctions:
    out.append("<circle %s />" % _attrs([
      ("cx", fmt(point[0])), ("cy", fmt(point[1])),
      ("r", fmt(theme.JUNCTION_RADIUS)),
      ("fill", theme.COLORS["junction"])]))
  out.append("</g>")

  if title and doc.title:
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(view[0] + theme.TITLE_PAD)),
        ("y", fmt(view[1] + theme.TITLE_PAD
                  + theme.FONT_SIZES["title"] * font_scale)),
        ("font-family", theme.FONT_SANS),
        ("font-size", fmt(theme.FONT_SIZES["title"] * font_scale, 2)),
        ("font-weight", "600"),
        ("fill", theme.COLORS["title"])]),
      esc(doc.title)))

  out.append("</svg>")
  return "\n".join(out) + "\n"


def render_symbol(symbol, zoom=4.0, margin=16.0, font_scale=1.0):
  """Render a single symbol on its own, for previewing a new cell definition."""
  view = (-margin, -margin, symbol.width + 2 * margin, symbol.height + 2 * margin)
  cell = {"id": symbol.id, "type": symbol.id, "x": 0, "y": 0,
          "w": symbol.width, "h": symbol.height, "rotate": 0,
          "mirror": False, "style": {}}

  out = []
  out.append('<?xml version="1.0" encoding="UTF-8"?>')
  out.append("<svg %s>" % _attrs([
    ("xmlns", "http://www.w3.org/2000/svg"),
    ("width", fmt(view[2] * zoom, 2)),
    ("height", fmt(view[3] * zoom, 2)),
    ("viewBox", "%s %s %s %s" % (fmt(view[0]), fmt(view[1]),
                                 fmt(view[2]), fmt(view[3]))),
    ("font-family", theme.FONT_SANS)]))
  out.append("<title>%s</title>" % esc(symbol.name))
  out.append("<rect %s />" % _attrs([
    ("x", fmt(view[0])), ("y", fmt(view[1])),
    ("width", fmt(view[2])), ("height", fmt(view[3])),
    ("fill", theme.PAPER)]))
  _render_cell(symbol, cell, font_scale, out)

  for pin in symbol.pins:
    out.append("<circle %s />" % _attrs([
      ("cx", fmt(pin["x"])), ("cy", fmt(pin["y"])), ("r", "2"),
      ("fill", theme.COLORS["net_label"])]))

  out.append("</svg>")
  return "\n".join(out) + "\n"
