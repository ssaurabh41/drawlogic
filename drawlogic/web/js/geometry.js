// Affine geometry. A direct port of drawlogic/geometry.py -- the canvas and
// the exporter must place a pin in exactly the same spot.

export function fmt(value, places = 3) {
  let text = Number(value).toFixed(places);
  if (text.indexOf(".") >= 0) {
    text = text.replace(/0+$/, "").replace(/\.$/, "");
  }
  if (text === "" || text === "-" || text === "-0") return "0";
  return text;
}

export class Affine {
  constructor(a = 1, b = 0, c = 0, d = 1, e = 0, f = 0) {
    this.a = a; this.b = b; this.c = c;
    this.d = d; this.e = e; this.f = f;
  }

  static translate(tx, ty) {
    return new Affine(1, 0, 0, 1, tx, ty);
  }

  static scale(sx, sy) {
    if (sy === undefined) sy = sx;
    return new Affine(sx, 0, 0, sy, 0, 0);
  }

  static rotate(degrees) {
    const rad = (degrees * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    return new Affine(cos, sin, -sin, cos, 0, 0);
  }

  // Returns the transform that applies `other` first, then this one.
  multiply(other) {
    return new Affine(
      this.a * other.a + this.c * other.b,
      this.b * other.a + this.d * other.b,
      this.a * other.c + this.c * other.d,
      this.b * other.c + this.d * other.d,
      this.a * other.e + this.c * other.f + this.e,
      this.b * other.e + this.d * other.f + this.f
    );
  }

  apply(x, y) {
    return [this.a * x + this.c * y + this.e, this.b * x + this.d * y + this.f];
  }

  scaleFactor() {
    const sx = Math.hypot(this.a, this.b);
    const sy = Math.hypot(this.c, this.d);
    return (sx + sy) / 2;
  }

  toSvg() {
    return `matrix(${[this.a, this.b, this.c, this.d, this.e, this.f]
      .map((v) => fmt(v, 4))
      .join(",")})`;
  }
}

// `x, y` is the top-left of the unrotated box, and rotation happens about its
// centre, so rotating a cell never moves it.
export function cellMatrix(x, y, w, h, sw, sh, rotate = 0, mirror = false) {
  const cx = x + w / 2;
  const cy = y + h / 2;
  let sx = w / sw;
  const sy = h / sh;
  if (mirror) sx = -sx;

  let m = Affine.translate(cx, cy);
  m = m.multiply(Affine.rotate(rotate));
  m = m.multiply(Affine.scale(sx, sy));
  m = m.multiply(Affine.translate(-sw / 2, -sh / 2));
  return m;
}

export function corners(x, y, w, h) {
  return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
}

export function boundsOf(points) {
  if (!points.length) return null;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const y0 = Math.min(...ys);
  return [x0, y0, Math.max(...xs) - x0, Math.max(...ys) - y0];
}

// ---- the symbol library ----

let library = {};

export function setLibrary(data) {
  library = data || {};
}

// Blocks standing in for referenced drawings arrive with the drawing that
// references them, not with the library, so they are merged in on open. The
// previous drawing's are dropped first: the same ref means a different file
// from a different folder, and a stale one would draw the wrong pins.
export function setSheets(data) {
  for (const id of Object.keys(library)) {
    if (id.startsWith("sheet:")) delete library[id];
  }
  Object.assign(library, data || {});
}

export function get(typeId) {
  return library[typeId] || null;
}

// The symbol a placed cell draws with. A cell that references another drawing
// takes its symbol from that drawing's ports, so the lookup is by ref rather
// than by type; null when the reference has not been resolved, which reads the
// same as an unknown type.
export function forCell(cell) {
  if (!cell) return null;
  if (cell.ref) return library[`sheet:${cell.ref}`] || null;
  return library[cell.type] || null;
}

export function ids() {
  return Object.keys(library).sort();
}

// The palette: only symbols you can pick up and place. A block standing in
// for another drawing is a real symbol to everything that draws or routes, but
// it comes from that drawing's ports rather than from the library, so there is
// nothing to offer.
export function byCategory() {
  const groups = {};
  for (const id of ids()) {
    if (library[id].listed === false) continue;
    const category = library[id].category || "misc";
    (groups[category] = groups[category] || []).push(id);
  }
  return groups;
}

export function findPin(symbol, name) {
  if (!symbol) return null;
  return symbol.pins.find((pin) => pin.name === name) || null;
}

// `scale` is the document-wide symbol scale. It grows a cell about its own
// centre, so turning every gate up does not drag the layout sideways.
export function matrixFor(symbol, cell, scale = 1) {
  let x = cell.x || 0;
  let y = cell.y || 0;
  let w = cell.w === undefined ? symbol.size[0] : cell.w;
  let h = cell.h === undefined ? symbol.size[1] : cell.h;

  if (scale !== 1) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    w *= scale;
    h *= scale;
    x = cx - w / 2;
    y = cy - h / 2;
  }

  return cellMatrix(x, y, w, h, symbol.size[0], symbol.size[1],
                    cell.rotate || 0, Boolean(cell.mirror));
}

export function pinPosition(symbol, cell, pinName, scale = 1) {
  const pin = findPin(symbol, pinName);
  if (!pin) return null;
  return matrixFor(symbol, cell, scale).apply(pin.x, pin.y);
}

export function cellBounds(symbol, cell, scale = 1) {
  const matrix = matrixFor(symbol, cell, scale);
  const points = corners(0, 0, symbol.size[0], symbol.size[1])
    .map(([px, py]) => matrix.apply(px, py));
  return boundsOf(points);
}



// Mirrors LABEL_CHAR and LINE_STEP in render_svg.py: how wide a character of
// a name is taken to be, and the baseline step between its lines.
export const LABEL_CHAR = 0.62;
export const LABEL_LINE_STEP = 1.15;

// Where a cell's name goes: [x, baseline of the first line, anchor]. Mirrors
// render_svg.cell_label_place: above and centred, unless a pin comes in at
// the top, when it moves beside the cell -- left of the top-left corner, or
// right of the top-right if a left pin is in the way.
export function cellLabelPlace(symbol, cell, scale, size, textToCell, textToWire) {
  const [bx, by, bw] = cellBounds(symbol, cell, scale);
  const lines = labelLines(cell.label || "");
  const count = lines.length || 1;
  const spots = symbol.pins.map((pin) => pinPosition(symbol, cell, pin.name, scale))
    .filter(Boolean);
  const above = [bx + bw / 2, by - 5 - (count - 1) * size * LABEL_LINE_STEP, "middle"];
  if (!spots.some(([, y]) => Math.abs(y - by) < 0.5)) return above;
  const reach = by + size * (count - 1) * LABEL_LINE_STEP + size + textToWire;
  const baseline = by + size * 0.8;
  const sideFree = (edge) => !spots.some(([x, y]) => Math.abs(x - edge) < 0.5 && y <= reach);
  if (sideFree(bx)) return [bx - textToCell, baseline, "end"];
  if (sideFree(bx + bw)) return [bx + bw + textToCell, baseline, "start"];
  return above;
}

// The rectangle a cell's name covers, as [x0, y0, x1, y1], or null.
// Mirrors render_svg.cell_label_box.
export function cellLabelBox(symbol, cell, scale, size, textToCell, textToWire) {
  if (!cell.label) return null;
  const lines = labelLines(cell.label);
  const [x, top, anchor] = cellLabelPlace(symbol, cell, scale, size, textToCell, textToWire);
  const width = Math.max(...lines.map((line) => line.length), 1) * size * LABEL_CHAR;
  const x0 = anchor === "middle" ? x - width / 2 : anchor === "end" ? x - width : x;
  return [x0, top - size * 0.8, x0 + width,
          top + size * 0.2 + (lines.length - 1) * size * LABEL_LINE_STEP];
}

// ---- text inside a cell, and replicated cells ----
//
// Mirrors cell_text_lines, cell_copies, cell_text_needs, cell_text_layout and
// fit_cell_text in render_svg.py. The sizes come from the theme the server
// sends; these defaults are theme.py's, for when this runs on its own.
let cellText = { size: 11.5, pad: 8, step: 1.3, char: 0.62, stack: 6 };

export function setCellTextMetrics(sizes, metrics) {
  cellText = { ...cellText, ...(metrics || {}) };
  if (sizes && sizes.cell_text) cellText.size = sizes.cell_text;
}

export function cellTextMetrics() {
  return cellText;
}

export function cellTextLines(cell) {
  let lines;
  if (typeof cell.text === "string") lines = cell.text.split("\n");
  else if (Array.isArray(cell.text)) lines = cell.text.map((line) => String(line));
  else return [];
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  return lines;
}

// Cells you move but never resize: ports, and the tie cells that stand for a
// constant 0 or 1. Each is small and mostly outline, so resize grips would
// cover most of it and a press meant to drag it would catch a corner instead;
// the canvas gives them a grab pad rather than grips. One list, so the pad and
// the grips cannot disagree about which cells these are.
export const FIXED_SIZE_TYPES = new Set(
  ["port_in", "port_out", "port_inout", "tie0", "tie1"]);

export function cellCopies(cell) {
  const value = cell.copies;
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  const whole = Math.trunc(value);
  return whole >= 2 ? whole : 0;
}

function textSizes(fontScale) {
  const size = cellText.size * fontScale;
  return [size, cellText.pad, size * cellText.step, size * cellText.char];
}

export function cellTextNeeds(lines, fontScale = 1) {
  if (!lines.length) return [0, 0];
  const [size, pad, step, char] = textSizes(fontScale);
  const widest = Math.max(...lines.map((line) => line.length));
  return [2 * pad + widest * char, 2 * pad + size + (lines.length - 1) * step];
}

function ellipsis(line, room, force = false) {
  if (room <= 0) return "";
  if (!force && line.length <= room) return line;
  return `${line.slice(0, Math.max(0, Math.min(line.length, room - 1))).trimEnd()}\u2026`;
}

// [[x, baseline, text], ...] and whether anything had to be cut.
// How text inside a cell can be aligned, default first. Mirrors TEXT_ALIGN,
// TEXT_VALIGN and TEXT_ANCHOR in render_svg.py.
export const TEXT_ALIGN = ["center", "left", "right"];
export const TEXT_VALIGN = ["middle", "top", "bottom"];
export const TEXT_ANCHOR = { left: "start", center: "middle", right: "end" };

// A cell's text alignment as [across, down], defaults filled in.
export function cellTextAlign(cell) {
  return [TEXT_ALIGN.includes(cell.textAlign) ? cell.textAlign : TEXT_ALIGN[0],
          TEXT_VALIGN.includes(cell.textVAlign) ? cell.textVAlign : TEXT_VALIGN[0]];
}

export function cellTextLayout(symbol, cell, scale = 1, fontScale = 1) {
  const lines = cellTextLines(cell);
  if (!lines.length) return [[], false];
  const [x, y, w, h] = cellBounds(symbol, cell, scale);
  const [size, pad, step, char] = textSizes(fontScale);
  const room = Math.max(0, Math.trunc((w - 2 * pad) / char + 1e-6));
  const [across, down] = cellTextAlign(cell);
  const at = { left: x + pad, center: x + w / 2, right: x + w - pad }[across];
  const placed = [];
  let clipped = false;
  for (let index = 0; index < lines.length; index += 1) {
    let line = lines[index];
    const baseline = y + pad + size * 0.8 + index * step;
    if (baseline + size * 0.2 > y + h - pad + 1e-6) {
      clipped = true;
      if (placed.length) {
        const last = placed[placed.length - 1];
        placed[placed.length - 1] = [last[0], last[1], ellipsis(last[2], room, true)];
      }
      break;
    }
    if (line.length > room) {
      clipped = true;
      line = ellipsis(line, room);
    }
    placed.push([at, baseline, line]);
  }
  if (placed.length && !clipped && down !== "top") {
    // Mirrors cell_text_layout in render_svg.py.
    const block = size + (placed.length - 1) * step;
    const spare = Math.max(0, h - 2 * pad - block);
    const drop = down === "bottom" ? spare : spare / 2;
    return [placed.map(([px, py, text]) => [px, py + drop, text]), clipped];
  }
  return [placed, clipped];
}

// Grow a cell until its text fits, unless fitting is off. Only ever grows.
export function fitCellText(symbol, cell, scale = 1, fontScale = 1) {
  if (cell.textFit === false) return false;
  const lines = cellTextLines(cell);
  if (!lines.length) return false;
  const [needW, needH] = cellTextNeeds(lines, fontScale);
  const [, , w, h] = cellBounds(symbol, cell, scale);
  const turned = ((Number(cell.rotate) || 0) % 180 + 180) % 180 === 90;
  let grew = false;
  for (const [sheet, need, key] of [[w, needW, turned ? "h" : "w"],
                                    [h, needH, turned ? "w" : "h"]]) {
    const own = Number(cell[key]) || 0;
    if (own <= 0 || sheet >= need - 1e-6) continue;
    cell[key] = Math.ceil(own * need / sheet);
    grew = true;
  }
  return grew;
}

// An instance name longer than this wants two lines. Mirrors
// LABEL_WRAP_CHARS in geometry.py.
export const LABEL_WRAP_CHARS = 12;

// An instance name as the one or two lines it should be drawn on. One line is
// always preferred; the split goes at the underscore nearest the middle,
// because that is where a signal name has a seam. A long name with no
// underscore stays on one line on purpose: breaking it mid-word trades a name
// that overhangs for one that cannot be read. Mirrors label_lines in
// geometry.py.
export function labelLines(text) {
  if (typeof text !== "string") return [text == null ? "" : String(text)];
  if (text.length <= LABEL_WRAP_CHARS) return [text];
  const middle = text.length / 2;
  let best = null;
  for (let i = 0; i < text.length - 1; i += 1) {
    if (text[i] !== "_") continue;
    const distance = Math.abs((i + 1) - middle);
    if (best === null || distance < best[0]) best = [distance, i + 1];
  }
  if (best === null) return [text];
  return [text.slice(0, best[1]), text.slice(best[1])];
}


// A bridge radius for each crossing, shrunk where neighbours are close. The
// crossings cannot be moved -- a bridge is drawn where the wires actually
// cross -- but how wide it is can be, so each takes at most half the room
// beside it and never less than `smallest`. `positions` must be sorted.
// Mirrors hop_radii in geometry.py.
export function hopRadii(positions, radius, flat, smallest) {
  const count = positions.length;
  if (!count) return [];
  return positions.map((here, index) => {
    let room = null;
    if (index) room = here - positions[index - 1];
    if (index + 1 < count) {
      const after = positions[index + 1] - here;
      room = room === null ? after : Math.min(room, after);
    }
    if (room === null) return radius;
    return Math.max(smallest, Math.min(radius, (room - flat) / 2));
  });
}

// The arrowhead at `tip` of a line arriving from `before`: [shape, trim], with
// `shape` ["polygon", points], ["polyline", points] or ["ellipse",
// [cx, cy, rx, ry, angleDegrees]], or null for no head, and `trim` where the
// line itself stops. Mirrors line_head in geometry.py line for line.
export function lineHead(tip, before, kind, length, spread) {
  const dx = tip[0] - before[0];
  const dy = tip[1] - before[1];
  const run = Math.hypot(dx, dy);
  if (!kind || kind === "none" || run < 1e-9 || length <= 0) return [null, tip];
  const ux = dx / run;
  const uy = dy / run;
  const nx = -uy;
  const ny = ux;
  const half = length * spread;
  const at = (back, side) => [tip[0] - ux * back + nx * side,
                              tip[1] - uy * back + ny * side];

  if (kind === "triangle") {
    return [["polygon", [tip, at(length, half), at(length, -half)]], at(length, 0)];
  }
  if (kind === "open") {
    return [["polyline", [at(length, half), tip, at(length, -half)]], tip];
  }
  if (kind === "stealth") {
    const notch = at(length * 0.6, 0);
    return [["polygon", [tip, at(length, half), notch, at(length, -half)]], notch];
  }
  if (kind === "diamond") {
    return [["polygon", [at(-length / 2, 0), at(0, half), at(length / 2, 0),
                         at(0, -half)]],
            at(length / 2, 0)];
  }
  if (kind === "oval") {
    const angle = Math.atan2(uy, ux) * 180 / Math.PI;
    return [["ellipse", [tip[0], tip[1], length / 2, half, angle]], at(length / 2, 0)];
  }
  return [null, tip];
}

