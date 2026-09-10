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
