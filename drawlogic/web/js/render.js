// Draws a document into live SVG DOM.
//
// The on-screen canvas only has to look right while you work; every file that
// leaves the tool is rendered by Python. That keeps the stakes here low and
// guarantees the GUI and the CLI cannot disagree about an export.

import { fmt } from "./geometry.js";
import * as routing from "./routing.js";
import * as symbols from "./symbols.js";

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
    paint["stroke-width"] = fmt(scale ? width / scale : width, 3);
  }
  if (spec.dash) paint["stroke-dasharray"] = spec.dash;
  if (spec.font) {
    paint["font-size"] = fmt(theme.fontSizes[spec.font] * fontScale, 2);
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
  const matrix = symbols.matrixFor(symbol, cell, scale);
  const factor = matrix.scaleFactor();
  const style = cell.style || {};

  const group = el("g", {
    class: "dl-cell", "data-id": cell.id, "data-type": cell.type,
    transform: matrix.toSvg(),
  });
  for (const op of symbol.draw) {
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
      x: fmt(x), y: fmt(y), "text-anchor": anchor,
      "font-family": theme.fontSans,
      "font-size": fmt(theme.fontSizes.pin_label * fontScale, 2),
      fill: theme.colors.pin_label,
    });
    text.textContent = op.text;
    into.appendChild(text);
  }

  if (cell.label) {
    const box = symbols.cellBounds(symbol, cell, scale);
    const text = el("text", {
      x: fmt(box[0] + box[2] / 2), y: fmt(box[1] - 5),
      "text-anchor": "middle",
      "font-family": theme.fontSans,
      "font-size": fmt(theme.fontSizes.label * fontScale, 2),
      "font-weight": "600",
      fill: theme.colors.label,
    });
    text.textContent = cell.label;
    into.appendChild(text);
  }
}

function renderNets(doc, fontScale, into) {
  const routes = routing.routeAll(doc);

  for (const { net, points } of routes) {
    if (points.length < 2) continue;
    const style = net.style || {};
    into.appendChild(el("path", {
      class: "dl-net", "data-id": net.id,
      d: `M${points.map((p) => `${fmt(p[0])} ${fmt(p[1])}`).join(" L")}`,
      fill: "none",
      stroke: style.stroke || theme.colors.net,
      "stroke-width": fmt(style.strokeWidth || theme.widths.net, 3),
      "stroke-linecap": "square",
    }));
  }

  for (const { net, points } of routes) {
    if (!net.name || points.length < 2) continue;
    const text = el("text", {
      x: fmt((points[0][0] + points[1][0]) / 2),
      y: fmt((points[0][1] + points[1][1]) / 2 - 4),
      "text-anchor": "middle",
      "font-family": theme.fontMono,
      "font-size": fmt(theme.fontSizes.net_label * fontScale, 2),
      fill: theme.colors.net_label,
    });
    text.textContent = net.name;
    into.appendChild(text);
  }

  for (const point of routing.junctions(routes)) {
    into.appendChild(el("circle", {
      cx: fmt(point[0]), cy: fmt(point[1]),
      r: fmt(theme.junctionRadius), fill: theme.colors.junction,
    }));
  }
}

function renderShape(shape, fontScale, into) {
  const style = shape.style || {};
  const paint = {
    fill: style.fill || "none",
    stroke: style.stroke || theme.colors.stroke,
    "stroke-width": fmt(style.strokeWidth || theme.widths.stroke, 3),
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
      "font-size": fmt((style.fontSize || theme.fontSizes.shape_text) * fontScale, 2),
      fill: style.fill || theme.colors.label,
    });
    text.textContent = shape.text || "";
    into.appendChild(text);
  }
}

export function render(svg, doc) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const canvas = doc.canvas || {};
  const fontScale = Number((canvas.font || {}).scale) || 1;
  const scale = routing.symbolScale(doc);

  const defs = el("defs");
  const pattern = gridPattern(canvas.grid || {});
  if (Array.isArray(pattern)) pattern.forEach((p) => defs.appendChild(p));
  else if (pattern) defs.appendChild(pattern);
  svg.appendChild(defs);

  // The sheet is a fixed size, so draw it as a page sitting on the workspace.
  svg.appendChild(el("rect", {
    class: "dl-sheet", x: 0, y: 0,
    width: canvas.width, height: canvas.height,
    fill: canvas.background || theme.colors.background,
  }));
  if (pattern) {
    svg.appendChild(el("rect", {
      x: 0, y: 0, width: canvas.width, height: canvas.height,
      fill: "url(#dl-grid)",
    }));
  }

  const shapes = el("g", { class: "dl-shapes" });
  for (const shape of doc.shapes || []) renderShape(shape, fontScale, shapes);
  svg.appendChild(shapes);

  const nets = el("g", { class: "dl-nets" });
  renderNets(doc, fontScale, nets);
  svg.appendChild(nets);

  const cells = el("g", { class: "dl-cells" });
  for (const cell of doc.cells || []) {
    const symbol = symbols.get(cell.type);
    if (symbol) renderCell(symbol, cell, fontScale, scale, cells);
  }
  svg.appendChild(cells);

  if (doc.title) {
    const text = el("text", {
      x: 14, y: canvas.height - 14,
      "font-family": theme.fontSans,
      "font-size": fmt(theme.fontSizes.title * fontScale, 2),
      "font-weight": "600",
      fill: theme.colors.title,
    });
    text.textContent = doc.title;
    svg.appendChild(text);
  }
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
