// Draws a document into live SVG DOM.
//
// The on-screen canvas only has to look right while you work; every file that
// leaves the tool is rendered by Python. That keeps the stakes here low and
// guarantees the GUI and the CLI cannot disagree about an export.

import * as geometry from "./geometry.js";
import * as routing from "./routing.js";

const NS = "http://www.w3.org/2000/svg";

let theme = null;

export function setTheme(data) {
  theme = data;
}

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

function colorFor(spec, style, key) {
  if (spec === "none") return "none";
  if (spec === "cell") return style[key] || theme.colors[key] || theme.colors.stroke;
  return theme.colors[spec] || spec;
}

function rolePaint(role, style, scale, fontScale) {
  const spec = theme.roleStyles[role] || theme.roleStyles.body;
  const paint = {
    fill: colorFor(spec.fill || "none", style, "fill"),
    stroke: colorFor(spec.stroke || "none", style, "stroke"),
  };

  if (spec.width) {
    const width = spec.width === "stroke" && style.strokeWidth !== undefined
      ? Number(style.strokeWidth)
      : (theme.widths[spec.width] || theme.widths.stroke);
    // Undo the cell's own scaling so an enlarged gate keeps its line weight
    // instead of turning bold.
    paint["stroke-width"] = geometry.fmt(scale ? width / scale : width, 3);
  }
  if (spec.dash) paint["stroke-dasharray"] = spec.dash;
  if (spec.font) {
    paint["font-size"] = geometry.fmt(theme.fontSizes[spec.font] * fontScale, 2);
    paint["font-family"] = theme.fontSans;
  }
  return paint;
}

function opElement(op, paint) {
  switch (op.op) {
    case "path":
      return el("path", { d: op.d, ...paint });
    case "line": {
      const { fill, ...rest } = paint;
      return el("line", {
        x1: op.x1, y1: op.y1, x2: op.x2, y2: op.y2, ...rest,
      });
    }
    case "rect":
      return el("rect", { x: op.x, y: op.y, width: op.w, height: op.h, ...paint });
    case "ellipse":
      return el("ellipse", {
        cx: op.cx, cy: op.cy, rx: op.rx, ry: op.ry, ...paint,
      });
    case "circle":
      return el("circle", { cx: op.cx, cy: op.cy, r: op.r, ...paint });
    case "polygon":
      return el("polygon", {
        points: op.points.map((p) => `${p[0]},${p[1]}`).join(" "), ...paint,
      });
    default:
      return null;
  }
}

function gridPattern(grid) {
  const size = Number(grid.size) || 10;
  const color = grid.color || theme.colors.grid;
  const style = grid.style || "dots";
  if (style === "blank") return null;

  const pattern = el("pattern", {
    id: "dl-grid", width: size, height: size, patternUnits: "userSpaceOnUse",
  });

  if (style === "dots" || style === "dots-wide") {
    const step = style === "dots-wide" ? size * 2.5 : size;
    pattern.setAttribute("width", step);
    pattern.setAttribute("height", step);
    pattern.appendChild(el("circle", {
      cx: 0.6, cy: 0.6, r: style === "dots-wide" ? 1.15 : 0.75, fill: color,
    }));
    return pattern;
  }

  pattern.appendChild(el("path", {
    d: `M${size} 0 H0 V${size}`, fill: "none", stroke: color, "stroke-width": 0.7,
  }));

  if (style === "lines-heavy") {
    const major = size * 5;
    const minor = pattern;
    minor.setAttribute("id", "dl-grid-minor");
    const heavy = el("pattern", {
      id: "dl-grid", width: major, height: major, patternUnits: "userSpaceOnUse",
    });
    heavy.appendChild(el("rect", {
      width: major, height: major, fill: "url(#dl-grid-minor)",
    }));
    heavy.appendChild(el("path", {
      d: `M${major} 0 H0 V${major}`, fill: "none",
      stroke: theme.colors.grid_major, "stroke-width": 1,
    }));
    return [minor, heavy];
  }
  return pattern;
}

// Where to write a name for a pin the symbol itself does not label: just
// inside the body, on the face the pin sits on, so it reads as the block's own
// labelling rather than as a stray note.
function freePinLabel(symbol, cell, pinName, scale) {
  const pin = geometry.findPin(symbol, pinName);
  if (!pin) return null;

  const inset = theme.pinLabelInset || 8;
  const [w, h] = symbol.size;
  let local;
  let anchor;
  if (pin.x <= 1e-6) { local = [pin.x + inset, pin.y + 4]; anchor = "start"; }
  else if (pin.x >= w - 1e-6) { local = [pin.x - inset, pin.y + 4]; anchor = "end"; }
  else if (pin.y <= 1e-6) { local = [pin.x, pin.y + inset + 4]; anchor = "middle"; }
  else { local = [pin.x, pin.y - inset]; anchor = "middle"; }

  if (cell.mirror) anchor = { start: "end", end: "start" }[anchor] || anchor;
  return [geometry.matrixFor(symbol, cell, scale).apply(local[0], local[1]), anchor];
}

function renderCell(symbol, cell, fontScale, scale, into) {
  const matrix = geometry.matrixFor(symbol, cell, scale);
  const factor = matrix.scaleFactor();
  const style = cell.style || {};

  // One outer group per cell, holding both the transformed artwork and its
  // upright text, so a click anywhere on a cell -- label included -- finds it.
  const outer = el("g", {
    class: "dl-cell", "data-id": cell.id, "data-type": cell.type,
  });
  into.appendChild(outer);
  into = outer;

  const group = el("g", { transform: matrix.toSvg() });
  if (cell.image) {
    group.appendChild(el("image", {
      href: cell.image, x: 0, y: 0,
      width: symbol.size[0], height: symbol.size[1],
      preserveAspectRatio: "xMidYMid meet",
    }));
  }
  for (const op of symbol.draw) {
    if (cell.image && op.role === "ghost") continue;
    if (op.op === "text") continue;
    const node = opElement(op, rolePaint(op.role || "body", style, factor, fontScale));
    if (node) group.appendChild(node);
  }
  into.appendChild(group);

  // Pin labels travel with the cell but are drawn upright at a fixed size, so
  // a rotated or enlarged gate still has readable pin names.
  const mirrored = Boolean(cell.mirror);
  const overrides = { ...(cell.pins || {}) };
  const pinLabel = (x, y, anchor, content) => {
    const text = el("text", {
      x: geometry.fmt(x), y: geometry.fmt(y), "text-anchor": anchor,
      "font-family": theme.fontSans,
      "font-size": geometry.fmt(theme.fontSizes.pin_label * fontScale, 2),
      fill: theme.colors.pin_label,
    });
    text.textContent = content;
    into.appendChild(text);
  };

  for (const op of symbol.draw) {
    if (op.op !== "text") continue;
    // A cell may rename a pin the symbol already labels: same spot, new word.
    let content = op.text;
    if (op.pin !== undefined && op.pin in overrides) {
      content = overrides[op.pin];
      delete overrides[op.pin];
      if (!content) continue;
    }
    const [x, y] = matrix.apply(op.x, op.y);
    let anchor = op.anchor || "start";
    if (mirrored) anchor = { start: "end", end: "start" }[anchor] || anchor;
    pinLabel(x, y, anchor, content);
  }

  // Whatever is left names a pin the symbol draws no label for -- a generic
  // block, say -- so place one from the pin's own geometry instead.
  for (const [pinName, content] of Object.entries(overrides)) {
    if (!content) continue;
    const spot = freePinLabel(symbol, cell, pinName, scale);
    if (spot) pinLabel(spot[0][0], spot[0][1], spot[1], content);
  }

  if (cell.label) {
    const box = geometry.cellBounds(symbol, cell, scale);
    const text = el("text", {
      x: geometry.fmt(box[0] + box[2] / 2), y: geometry.fmt(box[1] - 5),
      "text-anchor": "middle",
      "font-family": theme.fontSans,
      "font-size": geometry.fmt(theme.fontSizes.label * fontScale, 2),
      "font-weight": "600",
      fill: theme.colors.label,
    });
    text.textContent = cell.label;
    into.appendChild(text);
  }
}


// Direction arrows. Mirrors _arrow_at / _render_arrow in render_svg.py: the
// head sits near the receiving end, which is where a reader looks to ask
// "what drives this?".
// The point a given way along a path, and the direction of travel there.
function walk(points, distance) {
  for (let i = 0; i < points.length - 1; i += 1) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];
    const length = Math.abs(bx - ax) + Math.abs(by - ay);
    if (length <= 0) continue;
    if (distance <= length) {
      const ratio = distance / length;
      return [[ax + (bx - ax) * ratio, ay + (by - ay) * ratio],
              [(bx - ax) / length, (by - ay) / length],
              Math.min(distance, length - distance)];
    }
    distance -= length;
  }
  return null;
}

function pathLength(points) {
  let total = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    total += Math.abs(points[i + 1][0] - points[i][0])
      + Math.abs(points[i + 1][1] - points[i][1]);
  }
  return total;
}

// One arrow always sits near the receiving end, which is where a reader looks
// to ask "what drives this?". On a long run that arrow is nowhere near most of
// the wire, so more are spaced along it -- close enough that the direction
// reads wherever the eye lands, far enough apart that the wire does not turn
// into a dotted line. Arrows are kept off corners.
export function arrowSpots(points, size, spacing) {
  if (points.length < 2) return [];
  const step = spacing || theme.arrowSpacing || 240;
  const total = pathLength(points);

  let [ax, ay] = points[points.length - 2];
  let [bx, by] = points[points.length - 1];
  const last = Math.abs(bx - ax) + Math.abs(by - ay);

  const spots = [];
  let keepClear;
  if (last < size * 3) {
    // The final run is too short to hold a head clear of the pin, so the
    // arrow goes in the middle of the longest run instead.
    let best = null;
    for (let i = 0; i < points.length - 1; i += 1) {
      const [px, py] = points[i];
      const [qx, qy] = points[i + 1];
      const length = Math.abs(qx - px) + Math.abs(qy - py);
      if (!best || length > best[0]) best = [length, points[i], points[i + 1]];
    }
    const [length, [px, py], [qx, qy]] = best;
    const run = Math.max(length, 1e-6);
    spots.push([[(px + qx) / 2, (py + qy) / 2],
                [(qx - px) / run, (qy - py) / run]]);
    keepClear = total;
  } else {
    const offset = size * 1.6;
    const run = Math.max(last, 1e-6);
    spots.push([[bx - ((bx - ax) / run) * offset, by - ((by - ay) / run) * offset],
                [(bx - ax) / run, (by - ay) / run]]);
    keepClear = total - offset;
  }

  const extra = [];
  for (let d = step; d < keepClear - step * 0.5; d += step) {
    const found = walk(points, d);
    if (!found) continue;
    const [spot, direction, fromCorner] = found;
    if (fromCorner >= size * 2) extra.push([spot, direction]);
  }
  return extra.concat(spots);
}

function arrowElement(tip, direction, size, color) {
  const [ux, uy] = direction;
  const px = -uy;
  const py = ux;
  const backX = tip[0] - ux * size;
  const backY = tip[1] - uy * size;
  const half = size * 0.45;
  const points = [
    tip,
    [backX + px * half, backY + py * half],
    [backX - px * half, backY - py * half],
  ];
  return el("polygon", {
    points: points.map((p) => `${geometry.fmt(p[0])},${geometry.fmt(p[1])}`).join(" "),
    fill: color,
  });
}


// Where along a run a name may sit, as a fraction of the run.
const LABEL_STOPS = [0.5, 0.32, 0.68, 0.16, 0.84];

// One character of the mono face, as a fraction of the font size.
const LABEL_CHAR = 0.62;

// The rectangle a name will occupy, as [x0, y0, x1, y1].
function labelBox(spot, anchor, text, size) {
  const width = Math.max(text.length, 1) * size * LABEL_CHAR;
  let x0 = spot[0];
  if (anchor === "middle") x0 -= width / 2;
  else if (anchor === "end") x0 -= width;
  return [x0, spot[1] - size * 0.8, x0 + width, spot[1] + size * 0.2];
}

function boxesOverlap(a, b) {
  return !(a[2] <= b[0] || a[0] >= b[2] || a[3] <= b[1] || a[1] >= b[3]);
}

function segmentBox(a, b, pad = 1.5) {
  return [Math.min(a[0], b[0]) - pad, Math.min(a[1], b[1]) - pad,
          Math.max(a[0], b[0]) + pad, Math.max(a[1], b[1]) + pad];
}

// Every place a name could reasonably go on one wire: along each run at a few
// points, on either side of it. The caller scores them.
// Along each run of each branch, at a few points, on either side of it.
function labelCandidates(branches, size) {
  const found = [];
  for (const points of branches) found.push(...candidatesOn(points, size));
  return found;
}

function candidatesOn(points, size) {
  const found = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];
    const horizontal = Math.abs(by - ay) < Math.abs(bx - ax);
    const length = Math.abs(bx - ax) + Math.abs(by - ay);
    if (length < size * 2) continue;
    for (const stop of LABEL_STOPS) {
      const x = ax + (bx - ax) * stop;
      const y = ay + (by - ay) * stop;
      if (horizontal) {
        found.push([[x, y - 4], "middle", horizontal, length, stop, false]);
        found.push([[x, y + size + 2], "middle", horizontal, length, stop, true]);
      } else {
        found.push([[x + 5, y + 4], "start", horizontal, length, stop, false]);
        found.push([[x - 5, y + 4], "end", horizontal, length, stop, true]);
      }
    }
  }
  return found;
}

// A name that lands on a wire it has nothing to do with is worse than no name
// at all, and the middle of the longest run -- which is all this used to pick
// -- lands on one constantly. Each name is tried in several places and scored
// against the cells, the other wires, and the names already placed. Nets are
// considered in document order, so the first net stated gets the clearest
// spot: the same rule the router follows.
export function labelSpots(routes, cellBoxes, sheet, fontScale) {
  const size = theme.fontSizes.net_label * fontScale;
  const segments = routing.segmentsOf(routes)
    .map(([netId, a, b]) => [netId, segmentBox(a, b)]);

  const placed = [];
  const spots = new Map();
  for (const { net, branches } of routes) {
    if (!net.name || !branches.length) continue;

    let best = null;
    for (const [spot, anchor, horizontal, length, stop, farSide]
         of labelCandidates(branches, size)) {
      const box = labelBox(spot, anchor, net.name, size);

      let score = 0;
      if (sheet && (box[0] < 2 || box[1] < 2
                    || box[2] > sheet[0] - 2 || box[3] > sheet[1] - 2)) score += 500;
      for (const cellBox of cellBoxes) if (boxesOverlap(box, cellBox)) score += 120;
      for (const [otherId, segBox] of segments) {
        if (otherId !== net.id && boxesOverlap(box, segBox)) score += 45;
      }
      for (const other of placed) if (boxesOverlap(box, other)) score += 220;

      score += horizontal ? 0 : 55;
      score += farSide ? 18 : 0;
      score += Math.abs(stop - 0.5) * 12;
      score -= Math.min(length, 400) / 25;

      if (!best || score < best[0]) best = [score, spot, anchor, box];
    }

    if (best) {
      spots.set(net.id, [best[1], best[2]]);
      placed.push(best[3]);
    }
  }
  return spots;
}

// Every cell's footprint, with room above it for the instance name.
export function cellBoxes(doc) {
  const scale = routing.symbolScale(doc);
  const boxes = [];
  for (const cell of doc.cells || []) {
    const symbol = geometry.forCell(cell);
    if (!symbol) continue;
    const [x, y, w, h] = geometry.cellBounds(symbol, cell, scale);
    boxes.push([x - 2, y - 18, x + w + 2, y + h + 2]);
  }
  return boxes;
}

// The `d` for a wire, bridging over any wire it merely crosses.
function netPath(points, hops, radius) {
  const parts = [`M${geometry.fmt(points[0][0])} ${geometry.fmt(points[0][1])}`];

  for (let i = 0; i < points.length - 1; i += 1) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];

    if (hops && hops.length && Math.abs(ay - by) < 1e-6) {
      const direction = bx > ax ? 1 : -1;
      const low = Math.min(ax, bx);
      const high = Math.max(ax, bx);
      const here = hops
        .filter(([hx, hy]) => Math.abs(hy - ay) < 1e-6
                              && hx > low + radius && hx < high - radius)
        .map(([hx]) => hx)
        .sort((p, q) => (direction > 0 ? p - q : q - p));

      for (const hx of here) {
        parts.push(`L${geometry.fmt(hx - radius * direction)} ${geometry.fmt(ay)}`);
        // With y pointing down, sweep 1 bulges upward when travelling right.
        const sweep = direction > 0 ? 1 : 0;
        parts.push(`A${geometry.fmt(radius)} ${geometry.fmt(radius)} 0 0 ${sweep} `
                   + `${geometry.fmt(hx + radius * direction)} ${geometry.fmt(ay)}`);
      }
    }
    parts.push(`L${geometry.fmt(bx)} ${geometry.fmt(by)}`);
  }
  return parts.join(" ");
}

function renderNets(doc, fontScale, into) {
  const routes = routing.routeAll(doc);
  const hops = (doc.canvas || {}).hops === false
    ? new Map() : routing.hopPoints(routes);

  for (const { net, branches } of routes) {
    if (!branches.length) continue;
    const style = net.style || {};
    // One path element per net, with a subpath per branch: a net is one thing,
    // so clicking any part of it should find the same thing.
    const spots = hops.get(net.id);
    const d = branches.map((points) => netPath(points, spots, theme.hopRadius || 5))
      .join(" ");
    // A wire is 1.6 units wide, which is a hard thing to hit with a mouse --
    // and dragging one is now a gesture that matters. This invisible stroke
    // underneath is what the pointer actually catches. It is a canvas-only
    // affordance: the exported file has no use for it.
    into.appendChild(el("path", {
      class: "dl-hit", "data-id": net.id, d, fill: "none",
      stroke: "transparent", "stroke-width": 12, "pointer-events": "stroke",
    }));
    into.appendChild(el("path", {
      class: "dl-net", "data-id": net.id,
      d,
      fill: "none",
      stroke: style.stroke || theme.colors.net,
      "stroke-width": geometry.fmt(style.strokeWidth || theme.widths.net, 3),
      "stroke-linecap": "square",
    }));
  }

  const canvas = doc.canvas || {};
  const spots = labelSpots(routes, cellBoxes(doc),
                           [canvas.width, canvas.height], fontScale);
  for (const { net } of routes) {
    if (!net.name || !spots.has(net.id)) continue;
    const [[lx, ly], anchor] = spots.get(net.id);
    const text = el("text", {
      x: geometry.fmt(lx),
      y: geometry.fmt(ly),
      "text-anchor": anchor,
      "font-family": theme.fontMono,
      "font-size": geometry.fmt(theme.fontSizes.net_label * fontScale, 2),
      fill: theme.colors.net_label,
    });
    text.textContent = net.name;
    into.appendChild(text);
  }

  if ((doc.canvas || {}).arrows !== false) {
    for (const { net, branches } of routes) {
      if ((net.style || {}).arrow === false) continue;
      // Per branch: every load wants to know which way the signal reaches it.
      for (const points of branches) {
        if (points.length < 2) continue;
        for (const [tip, direction] of arrowSpots(points, theme.arrowSize || 7)) {
          into.appendChild(arrowElement(tip, direction, theme.arrowSize || 7,
                                        (net.style || {}).stroke || theme.colors.net));
        }
      }
    }
  }

  for (const point of routing.junctions(routes)) {
    into.appendChild(el("circle", {
      cx: geometry.fmt(point[0]), cy: geometry.fmt(point[1]),
      r: geometry.fmt(theme.junctionRadius), fill: theme.colors.junction,
    }));
  }
}

function renderShape(shape, fontScale, parent) {
  const style = shape.style || {};
  const into = el("g", { class: "dl-shape", "data-id": shape.id,
                         "data-kind": shape.kind });
  parent.appendChild(into);
  const paint = {
    fill: style.fill || "none",
    stroke: style.stroke || theme.colors.stroke,
    "stroke-width": geometry.fmt(style.strokeWidth || theme.widths.stroke, 3),
  };
  if (style.dash) paint["stroke-dasharray"] = style.dash;

  if (shape.kind === "rect") {
    into.appendChild(el("rect", {
      x: shape.x, y: shape.y, width: shape.w, height: shape.h, ...paint,
    }));
  } else if (shape.kind === "ellipse") {
    into.appendChild(el("ellipse", {
      cx: shape.x + shape.w / 2, cy: shape.y + shape.h / 2,
      rx: shape.w / 2, ry: shape.h / 2, ...paint,
    }));
  } else if (["polygon", "polyline", "line"].includes(shape.kind)) {
    const points = (shape.points || []).map((p) => `${p[0]},${p[1]}`).join(" ");
    into.appendChild(el(shape.kind === "polygon" ? "polygon" : "polyline",
                        { points, ...paint }));
  } else if (shape.kind === "text") {
    const text = el("text", {
      x: shape.x, y: shape.y,
      "text-anchor": style.anchor || "start",
      "font-family": theme.fontSans,
      "font-size": geometry.fmt((style.fontSize || theme.fontSizes.shape_text) * fontScale, 2),
      fill: style.fill || theme.colors.label,
    });
    text.textContent = shape.text || "";
    into.appendChild(text);
  }
}

// Everything the document owns lives in one content layer that is rebuilt
// wholesale on each change. The selection overlay sits in its own layer above
// it, so redrawing the drawing never disturbs handles mid-drag.
export function contentLayer(svg) {
  let layer = svg.querySelector(".dl-content");
  if (!layer) {
    layer = el("g", { class: "dl-content" });
    svg.appendChild(layer);
  }
  return layer;
}

export function overlayLayer(svg) {
  let layer = svg.querySelector(".dl-overlay");
  if (!layer) {
    layer = el("g", { class: "dl-overlay" });
  }
  // Always last, so handles draw on top of whatever was just rendered.
  svg.appendChild(layer);
  return layer;
}

export function render(svg, doc) {
  const content = contentLayer(svg);
  while (content.firstChild) content.removeChild(content.firstChild);

  const canvas = doc.canvas || {};
  const fontScale = Number((canvas.font || {}).scale) || 1;
  const scale = routing.symbolScale(doc);

  const defs = el("defs");
  const pattern = gridPattern(canvas.grid || {});
  if (Array.isArray(pattern)) pattern.forEach((p) => defs.appendChild(p));
  else if (pattern) defs.appendChild(pattern);
  content.appendChild(defs);

  // The sheet is a fixed size, so draw it as a page sitting on the workspace.
  content.appendChild(el("rect", {
    class: "dl-sheet", x: 0, y: 0,
    width: canvas.width, height: canvas.height,
    fill: canvas.background || theme.colors.background,
  }));
  if (pattern) {
    content.appendChild(el("rect", {
      x: 0, y: 0, width: canvas.width, height: canvas.height,
      fill: "url(#dl-grid)",
    }));
  }

  const shapes = el("g", { class: "dl-shapes" });
  for (const shape of doc.shapes || []) renderShape(shape, fontScale, shapes);
  content.appendChild(shapes);

  const nets = el("g", { class: "dl-nets" });
  renderNets(doc, fontScale, nets);
  content.appendChild(nets);

  const cells = el("g", { class: "dl-cells" });
  for (const cell of doc.cells || []) {
    const symbol = geometry.forCell(cell);
    if (symbol) renderCell(symbol, cell, fontScale, scale, cells);
  }
  content.appendChild(cells);

  if (doc.title) {
    const text = el("text", {
      x: 14, y: canvas.height - 14,
      "font-family": theme.fontSans,
      "font-size": geometry.fmt(theme.fontSizes.title * fontScale, 2),
      "font-weight": "600",
      fill: theme.colors.title,
    });
    text.textContent = doc.title;
    content.appendChild(text);
  }

  overlayLayer(svg);
}

// A standalone preview of one symbol, used by the palette.
export function symbolThumbnail(symbol, boxSize = 34) {
  const [sw, sh] = symbol.size;
  const pad = 2;
  const svg = el("svg", {
    viewBox: `${-pad} ${-pad} ${sw + pad * 2} ${sh + pad * 2}`,
    width: boxSize, height: boxSize * (sh / sw) || boxSize,
  });
  const cell = { id: symbol.id, type: symbol.id, x: 0, y: 0, w: sw, h: sh, style: {} };
  renderCell(symbol, cell, 1, 1, svg);
  return svg;
}
