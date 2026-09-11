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
  for (const op of symbol.draw) {
    if (op.op !== "text") continue;
    const [x, y] = matrix.apply(op.x, op.y);
    let anchor = op.anchor || "start";
    if (mirrored) anchor = { start: "end", end: "start" }[anchor] || anchor;
    const text = el("text", {
      x: geometry.fmt(x), y: geometry.fmt(y), "text-anchor": anchor,
      "font-family": theme.fontSans,
      "font-size": geometry.fmt(theme.fontSizes.pin_label * fontScale, 2),
      fill: theme.colors.pin_label,
    });
    text.textContent = op.text;
    into.appendChild(text);
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
function arrowAt(points, size) {
  let best = null;
  for (let i = 0; i < points.length - 1; i += 1) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];
    const length = Math.abs(bx - ax) + Math.abs(by - ay);
    if (!best || length > best[0]) best = [length, points[i], points[i + 1]];
  }

  let [ax, ay] = points[points.length - 2];
  let [bx, by] = points[points.length - 1];
  const last = Math.abs(bx - ax) + Math.abs(by - ay);

  let tip;
  if (last < size * 3 && best) {
    [, [ax, ay], [bx, by]] = best;
    tip = [(ax + bx) / 2, (ay + by) / 2];
  } else {
    const total = Math.max(last, 1e-6);
    const offset = size * 1.6;
    tip = [bx - ((bx - ax) / total) * offset, by - ((by - ay) / total) * offset];
  }

  const dx = bx - ax;
  const dy = by - ay;
  const total = Math.max(Math.abs(dx) + Math.abs(dy), 1e-6);
  return [tip, [dx / total, dy / total]];
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


// Where a net's name goes: the middle of its longest run. Using the first
// segment would stack the names of every net leaving the same pin.
function labelSpot(points) {
  let best = null;
  for (let i = 0; i < points.length - 1; i += 1) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];
    const length = Math.abs(bx - ax) + Math.abs(by - ay);
    if (!best || length > best[0]) best = [length, points[i], points[i + 1]];
  }
  const [, [ax, ay], [bx, by]] = best;
  const midX = (ax + bx) / 2;
  const midY = (ay + by) / 2;
  if (Math.abs(bx - ax) >= Math.abs(by - ay)) return [[midX, midY - 4], "middle"];
  return [[midX + 5, midY], "start"];
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

  for (const { net, points } of routes) {
    if (points.length < 2) continue;
    const style = net.style || {};
    into.appendChild(el("path", {
      class: "dl-net", "data-id": net.id,
      d: netPath(points, hops.get(net.id), theme.hopRadius || 5),
      fill: "none",
      stroke: style.stroke || theme.colors.net,
      "stroke-width": geometry.fmt(style.strokeWidth || theme.widths.net, 3),
      "stroke-linecap": "square",
    }));
  }

  for (const { net, points } of routes) {
    if (!net.name || points.length < 2) continue;
    const [[lx, ly], anchor] = labelSpot(points);
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
    for (const { net, points } of routes) {
      if (points.length < 2) continue;
      if ((net.style || {}).arrow === false) continue;
      const [tip, direction] = arrowAt(points, theme.arrowSize || 7);
      into.appendChild(arrowElement(tip, direction, theme.arrowSize || 7,
                                    (net.style || {}).stroke || theme.colors.net));
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
    const symbol = geometry.get(cell.type);
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
