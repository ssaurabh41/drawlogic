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
let cellText = { size: 11.5, pad: 8, step: 1.3, char: 0.62, stack: 0.03, stackMin: 3,
                 headingGap: 3, bold: 1.08 };

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
  return textLayoutIn(cellBounds(symbol, cell, scale), cell, fontScale);
}

// cellTextLayout for any box [x, y, w, h] and any item carrying text and its
// alignment -- a cell, or a shape. Mirrors text_layout_in in render_svg.py.
export function textLayoutIn(box, item, fontScale = 1) {
  const [placed, clipped] = textBlockIn(box, item, fontScale);
  return [placed.map(([x, y, text]) => [x, y, text]), clipped];
}

// ---- headings, body text and how each is set ----
//
// Mirrors the section of the same name in render_svg.py, line for line: a
// heading above the lines of text, each set as its headingStyle or textStyle
// says, and with neither the lines land exactly where they always did.

// The theme's text colour, faces and heading size, from /api/theme; these
// defaults are theme.py's, for when this runs on its own.
let textTheme = {
  label: "#16202b", headingSize: 13,
  fontSans: "'IBM Plex Sans','IBM Plex Sans Text',Arial,Helvetica,sans-serif",
  stacks: {},
};

// The sizes a heading and the text are set at when nothing says otherwise.
export function textDefaults() {
  return { text: cellText.size, heading: textTheme.headingSize, step: cellText.step };
}

export function setTextTheme(data) {
  if (!data) return;
  textTheme = {
    label: (data.colors && data.colors.label) || textTheme.label,
    headingSize: (data.fontSizes && data.fontSizes.cell_heading) || textTheme.headingSize,
    fontSans: data.fontSans || textTheme.fontSans,
    stacks: data.fontStacks || textTheme.stacks,
  };
}

// The look an item is drawn with: its named style, if it names one that is
// there, under its own overrides. Mirrors effective in styles.py.
export const STYLE_PARTS = ["style", "headingStyle", "textStyle"];

export function effectiveStyle(named, item) {
  const ref = item && item.styleRef;
  const base = typeof ref === "string" && named && typeof named === "object"
    && named[ref] && typeof named[ref] === "object" ? named[ref] : null;
  if (!base) return item;
  const out = { ...item };
  for (const part of STYLE_PARTS) {
    const shared = base[part];
    const own = item[part];
    if (shared && typeof shared === "object" && Object.keys(shared).length) {
      out[part] = { ...shared, ...(own && typeof own === "object" ? own : {}) };
    }
  }
  return out;
}

export function headingLines(item) {
  return cellTextLines({ text: item.heading });
}

export function fontFamily(name) {
  if (typeof name !== "string" || !name.trim()) return textTheme.fontSans;
  const stack = textTheme.stacks[name.trim().toLowerCase()];
  if (stack) return stack;
  const clean = [...name].filter((ch) => !"'\\\";<>{}".includes(ch)).join("").trim();
  return clean ? `'${clean}',${textTheme.fontSans}` : textTheme.fontSans;
}

export function positive(value, fallback) {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value > 0 && value < 1000 ? value : fallback;
}

export function weight(value, fallback) {
  if (value === "bold") return 700;
  if (value === "normal") return 400;
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value >= 100 && value <= 900 ? Math.trunc(value) : fallback;
}

// Every line written in a box, heading first: [[text, paint], ...].
export function textRuns(item, fontScale = 1) {
  const runs = [];
  for (const [heading, lines, spec, size, bold] of [
    [true, headingLines(item), item.headingStyle, textTheme.headingSize, 600],
    [false, cellTextLines(item), item.textStyle, cellText.size, null]]) {
    if (!lines.length) continue;
    const s = spec && typeof spec === "object" ? spec : {};
    const paint = {
      size: positive(s.fontSize, size) * fontScale,
      weight: weight(s.fontWeight, bold),
      fill: typeof s.fill === "string" && s.fill ? s.fill : textTheme.label,
      family: fontFamily(s.fontFamily),
      step: positive(s.lineHeight, cellText.step),
      heading,
    };
    for (const line of lines) runs.push([line, paint]);
  }
  return runs;
}

function charOf(paint) {
  const bold = paint.weight !== null && paint.weight >= 600;
  return paint.size * cellText.char * (bold ? cellText.bold : 1);
}

function advance(before, after) {
  let gap = before.size === after.size
    ? after.size * after.step
    : (before.size * 0.2 + after.size * 0.8) * after.step;
  if (before.heading && !after.heading) gap += cellText.headingGap;
  return gap;
}

export function textNeeds(item, fontScale = 1) {
  const runs = textRuns(item, fontScale);
  if (!runs.length) return [0, 0];
  const pad = cellText.pad;
  const widest = Math.max(...runs.map(([line, paint]) => line.length * charOf(paint)));
  let block = runs[0][1].size * 0.8 + runs[runs.length - 1][1].size * 0.2;
  for (let i = 1; i < runs.length; i += 1) block += advance(runs[i - 1][1], runs[i][1]);
  return [2 * pad + widest, 2 * pad + block];
}

// [[x, baseline, text, paint], ...] and whether anything had to be cut.
// Mirrors text_block_in.
export function textBlockIn(box, item, fontScale = 1) {
  const runs = textRuns(item, fontScale);
  if (!runs.length) return [[], false];
  const [x, y, w, h] = box;
  const pad = cellText.pad;
  const [across, down] = cellTextAlign(item);
  const at = { left: x + pad, center: x + w / 2, right: x + w - pad }[across];
  const room = (paint) => Math.max(0, Math.trunc((w - 2 * pad) / charOf(paint) + 1e-6));
  let placed = [];
  let clipped = false;
  let baseline = y + pad + runs[0][1].size * 0.8;
  for (let index = 0; index < runs.length; index += 1) {
    let [line, paint] = runs[index];
    if (index) baseline += advance(runs[index - 1][1], paint);
    if (baseline + paint.size * 0.2 > y + h - pad + 1e-6) {
      clipped = true;
      if (placed.length) {
        const [lx, ly, last, lastPaint] = placed[placed.length - 1];
        placed[placed.length - 1] = [lx, ly, ellipsis(last, room(lastPaint), true), lastPaint];
      }
      break;
    }
    if (line.length > room(paint)) {
      clipped = true;
      line = ellipsis(line, room(paint));
    }
    placed.push([at, baseline, line, paint]);
  }
  if (placed.length && !clipped && down !== "top") {
    const block = runs[0][1].size * 0.8 + (placed[placed.length - 1][1] - placed[0][1])
      + placed[placed.length - 1][3].size * 0.2;
    const spare = Math.max(0, h - 2 * pad - block);
    const drop = down === "bottom" ? spare : spare / 2;
    placed = placed.map(([px, py, text, paint]) => [px, py + drop, text, paint]);
  }
  return [placed, clipped];
}

// Grow a cell until its text fits, unless fitting is off. Only ever grows.
export function fitCellText(symbol, cell, scale = 1, fontScale = 1, named = null) {
  if (cell.textFit === false) return false;
  const look = effectiveStyle(named, cell);
  if (!textRuns(look, fontScale).length) return false;
  const [needW, needH] = textNeeds(look, fontScale);
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

// Shapes that can have writing in them, and those that can stand for several
// copies. Mirrors SHAPE_TEXT_KINDS, SHAPE_STACK_KINDS and LINE_TEXT_LIFT in
// render_svg.py.
export const SHAPE_TEXT_KINDS = ["rect", "ellipse", "polygon", "line", "polyline"];
export const SHAPE_STACK_KINDS = ["rect", "ellipse", "polygon"];
const LINE_TEXT_LIFT = 5;

// A shape's box [x, y, w, h], or null for a text shape. Mirrors shape_box.
export function shapeBox(shape) {
  const points = shape.points;
  if (["line", "polyline", "polygon"].includes(shape.kind) && points && points.length) {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys),
            Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
  }
  if (shape.kind === "rect" || shape.kind === "ellipse") {
    return [shape.x || 0, shape.y || 0, shape.w || 0, shape.h || 0];
  }
  return null;
}

// Halfway along a line, measured along it, and which way it runs there:
// [point, [ux, uy]]. Mirrors line_middle.
export function lineMiddle(points) {
  const pairs = points.slice(1).map((b, i) => [points[i], b]);
  const lengths = pairs.map(([a, b]) => Math.hypot(b[0] - a[0], b[1] - a[1]));
  let left = lengths.reduce((sum, l) => sum + l, 0) / 2;
  for (let i = 0; i < pairs.length; i += 1) {
    const [a, b] = pairs[i];
    if (lengths[i] > 0 && left <= lengths[i]) {
      const t = left / lengths[i];
      return [[a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
              [(b[0] - a[0]) / lengths[i], (b[1] - a[1]) / lengths[i]]];
    }
    left -= lengths[i];
  }
  return [points[0], [1, 0]];
}

// A line's caption, [[[x, baseline, text], ...], anchor]: above a level-ish
// line and raised by its climb under half the caption, right of a steep one.
// Mirrors _line_caption.
export function lineCaption(shape, fontScale = 1) {
  const lines = cellTextLines(shape);
  const points = shape.points || [];
  if (!lines.length || points.length < 2) return [[], "middle"];
  const [[mx, my], [ux, uy]] = lineMiddle(points);
  const [size, , step, char] = textSizes(fontScale);
  const block = size + (lines.length - 1) * step;
  if (Math.abs(uy) <= Math.abs(ux)) {
    const climb = Math.max(...lines.map((l) => l.length)) * char / 2 * Math.abs(uy / ux);
    const last = my - LINE_TEXT_LIFT - climb;
    return [lines.map((line, i) => [mx, last - (lines.length - 1 - i) * step, line]), "middle"];
  }
  const lean = block / 2 * Math.abs(ux / uy);
  const first = my - block / 2 + size * 0.8;
  return [lines.map((line, i) => [mx + LINE_TEXT_LIFT + lean, first + i * step, line]), "start"];
}

export function shapeCopies(shape) {
  return SHAPE_STACK_KINDS.includes(shape.kind) ? cellCopies(shape) : 0;
}

export function shapeStackOffset(shape) {
  const [, , w, h] = shapeBox(shape);
  return Math.max(cellText.stackMin, cellText.stack * Math.min(w, h));
}

// [[x, baseline, text], ...] for the writing in a shape. Mirrors
// shape_text_layout: in the box, in the box an ellipse's curve leaves room
// for, or centred just above a line's middle.
export function shapeTextLayout(shape, fontScale = 1) {
  return shapeTextBlock(shape, fontScale).map(([x, y, text]) => [x, y, text]);
}

// shapeTextLayout with how each line is set. Mirrors shape_text_block.
export function shapeTextBlock(shape, fontScale = 1) {
  if (!SHAPE_TEXT_KINDS.includes(shape.kind)) return [];
  let box = shapeBox(shape);
  if (!box) return [];
  if (shape.kind === "line" || shape.kind === "polyline") {
    const plain = textRuns({ text: shape.text }, fontScale);
    const paint = plain.length ? plain[0][1] : null;
    return lineCaption(shape, fontScale)[0].map(([x, y, text]) => [x, y, text, paint]);
  }
  if (shape.kind === "ellipse") {
    const [x, y, w, h] = box;
    const iw = w / Math.SQRT2;
    const ih = h / Math.SQRT2;
    box = [x + (w - iw) / 2, y + (h - ih) / 2, iw, ih];
  }
  return textBlockIn(box, shape, fontScale)[0];
}

// How far the copy behind a replicated cell sits, right and down: a share of
// the cell's smaller side, never under a floor. Mirrors stack_offset in
// render_svg.py.
export function stackOffset(symbol, cell, scale = 1) {
  const [, , w, h] = cellBounds(symbol, cell, scale);
  return Math.max(cellText.stackMin, cellText.stack * Math.min(w, h));
}
