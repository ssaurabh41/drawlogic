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

from . import routing
from . import theme
from .geometry import corners, fmt
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


def _color(spec, cell_style, key):
  """Resolve a role's colour spec against the element's own style."""
  if spec == "none":
    return "none"
  if spec == "cell":
    return cell_style.get(key, theme.COLORS[key if key in theme.COLORS else "stroke"])
  return theme.COLORS.get(spec, spec)


def _role_paint(role, cell_style, scale, font_scale):
  """SVG paint attributes for one symbol draw-op role."""
  spec = theme.ROLE_STYLES.get(role) or theme.ROLE_STYLES["body"]
  paint = {}

  paint["fill"] = _color(spec.get("fill", "none"), cell_style, "fill")
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


def _render_cell(symbol, cell, font_scale, out, symbol_scale=1.0):
  """Draw one placed cell: its shapes transformed, its text kept upright."""
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
    x, y = matrix.apply(op["x"], op["y"])
    anchor = op.get("anchor", "start")
    if mirrored:
      anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
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
    box = _cell_bbox(symbol, cell, symbol_scale)
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(box[0] + box[2] / 2.0)),
        ("y", fmt(box[1] - 5)),
        ("text-anchor", "middle"),
        ("font-family", theme.FONT_SANS),
        ("font-size", fmt(theme.FONT_SIZES["label"] * font_scale, 2)),
        ("font-weight", "600"),
        ("fill", theme.COLORS["label"])]),
      esc(label)))


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


def _arrow_spots(points, size, spacing=None):
  """Where a wire's direction arrows go, and which way each one points.

  One always sits near the receiving end, which is where a reader looks to ask
  "what drives this?". On a long run that arrow is nowhere near most of the
  wire, so more are spaced along it -- close enough that the direction reads
  wherever the eye lands, far enough apart that the wire does not turn into a
  dotted line. Arrows are kept off corners, where a head pointing into the
  bend is worse than no head at all.
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

  return extra + spots


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
      on_this.sort(reverse=direction < 0)

      for hx in on_this:
        parts.append("L%s %s" % (fmt(hx - radius * direction), fmt(ay)))
        # With y pointing down, sweep 1 bulges upward when travelling right.
        sweep = 1 if direction > 0 else 0
        parts.append("A%s %s 0 0 %d %s %s"
                     % (fmt(radius), fmt(radius), sweep,
                        fmt(hx + radius * direction), fmt(ay)))

    parts.append("L%s %s" % (fmt(bx), fmt(by)))

  return " ".join(parts)


def _cell_boxes(doc, registry):
  """Every cell's footprint, as (x0, y0, x1, y1), with room for its name.

  The instance name is drawn above the cell, so the box is taller than the
  cell to keep a net's name from landing on it.
  """
  boxes = []
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    x, y, w, h = _cell_bbox(symbol, cell, doc.symbol_scale)
    boxes.append((x - 2, y - 18, x + w + 2, y + h + 2))
  return boxes


# Where along a run a name may sit, as a fraction of the run.
LABEL_STOPS = (0.5, 0.32, 0.68, 0.16, 0.84)

# One character of the mono face, as a fraction of the font size. Close enough
# to reserve the right amount of room without measuring text properly.
LABEL_CHAR = 0.62


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
  """Where every net's name goes, keyed by net id.

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

  placed = []
  spots = {}
  for net, branches in routes:
    text = net.get("name")
    if not text or not branches:
      continue
    net_id = net.get("id")

    best = None
    for spot, anchor, horizontal, length, stop, far_side in _label_candidates(
        branches, text, size):
      box = _label_box(spot, anchor, text, size)

      score = 0.0
      if sheet and (box[0] < 2 or box[1] < 2
                    or box[2] > sheet[0] - 2 or box[3] > sheet[1] - 2):
        score += 500
      for cell_box in cell_boxes:
        if _boxes_overlap(box, cell_box):
          score += 120
      for other_id, seg_box in segments:
        if other_id != net_id and _boxes_overlap(box, seg_box):
          score += 45
      for other in placed:
        if _boxes_overlap(box, other):
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
      spots[net_id] = (best[1], best[2])
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
  routes = routing.route_all(doc, registry)
  hop_map = routing.hop_points(routes) if hops else {}

  for net, branches in routes:
    if not branches:
      continue
    style = net.get("style") or {}
    # One path element per net, with a subpath per branch: a net is one thing,
    # so clicking any part of it should find the same thing.
    hops = hop_map.get(net.get("id"))
    d = " ".join(_net_path(points, hops, theme.HOP_RADIUS)
                 for points in branches)
    out.append("<path %s />" % _attrs([
      ("class", "dl-net"),
      ("data-id", net.get("id")),
      ("d", d),
      ("fill", "none"),
      ("stroke", style.get("stroke", theme.COLORS["net"])),
      ("stroke-width", fmt(style.get("strokeWidth", routing.stroke_width(net)), 3)),
      ("stroke-linejoin", "miter"),
      ("stroke-linecap", "square")]))

  spots = _label_spots(routes, _cell_boxes(doc, registry),
                       (doc.canvas.get("width"), doc.canvas.get("height")),
                       font_scale)
  for net, _branches in routes:
    name = net.get("name")
    if not name or net.get("id") not in spots:
      continue
    (x, y), anchor = spots[net["id"]]
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
      if style.get("arrow") is False:
        continue
      # Per branch: every load wants to know which way the signal reaches it.
      for points in branches:
        if len(points) < 2:
          continue
        for tip, direction in _arrow_spots(points, theme.ARROW_SIZE):
          _render_arrow(tip, direction, theme.ARROW_SIZE,
                        style.get("stroke", theme.COLORS["net"]), out)

  for point in routing.junctions(routes):
    out.append("<circle %s />" % _attrs([
      ("cx", fmt(point[0])), ("cy", fmt(point[1])),
      ("r", fmt(theme.JUNCTION_RADIUS)),
      ("fill", theme.COLORS["junction"])]))


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
    points = shape.get("points", [])
    if kind == "line" and len(points) < 2:
      return
    coords = " ".join("%s,%s" % (fmt(p[0]), fmt(p[1])) for p in points)
    tag = "polygon" if kind == "polygon" else "polyline"
    out.append("<%s %s />" % (tag, _attrs([("points", coords)] + paint)))
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
  _render_nets(doc, registry, font_scale, out, show_arrows, show_hops)
  out.append("</g>")

  out.append('<g class="dl-cells">')
  for cell in doc.cells:
    symbol = registry.for_cell(cell)
    if symbol is None:
      continue
    _render_cell(symbol, cell, font_scale, out, doc.symbol_scale)
  out.append("</g>")

  if title and doc.title:
    out.append("<text %s>%s</text>" % (
      _attrs([
        ("x", fmt(view[0] + 14)),
        ("y", fmt(view[1] + view[3] - 14)),
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
