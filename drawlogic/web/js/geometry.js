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
