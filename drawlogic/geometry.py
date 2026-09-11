"""Affine geometry for placing symbols and resolving pin locations.

Drawn shapes and pin coordinates are pushed through the same matrix, so a
pin can never resolve to a place the symbol is not actually drawn.

Usage:

    from drawlogic.geometry import Affine, cell_matrix, fmt

    m = cell_matrix(x=100, y=50, w=60, h=40,      # where the cell sits
                    sw=60, sh=40,                 # the symbol's natural size
                    rotate=90, mirror=False)
    m.apply(60, 20)      # a symbol-local point in sheet coordinates
    m.to_svg()           # "matrix(a,b,c,d,e,f)" for an SVG transform
    fmt(3.140000)        # "3.14" -- trims trailing zeros for smaller output
"""

import math


def fmt(value, places=3):
  """Format a number for SVG output without trailing zeros."""
  text = ("%.*f" % (places, float(value))).rstrip("0").rstrip(".")
  if text in ("", "-", "-0"):
    return "0"
  return text


class Affine(object):
  """A 2D affine transform, stored as the SVG matrix(a, b, c, d, e, f).

      | a  c  e |
      | b  d  f |
  """

  __slots__ = ("a", "b", "c", "d", "e", "f")

  def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
    self.a = float(a)
    self.b = float(b)
    self.c = float(c)
    self.d = float(d)
    self.e = float(e)
    self.f = float(f)

  @staticmethod
  def identity():
    return Affine()

  @staticmethod
  def translate(tx, ty):
    return Affine(1, 0, 0, 1, tx, ty)

  @staticmethod
  def scale(sx, sy=None):
    if sy is None:
      sy = sx
    return Affine(sx, 0, 0, sy, 0, 0)

  @staticmethod
  def rotate(degrees):
    rad = math.radians(degrees)
    cos = math.cos(rad)
    sin = math.sin(rad)
    return Affine(cos, sin, -sin, cos, 0, 0)

  def multiply(self, other):
    """Return the transform that applies `other` first, then `self`."""
    return Affine(
      self.a * other.a + self.c * other.b,
      self.b * other.a + self.d * other.b,
      self.a * other.c + self.c * other.d,
      self.b * other.c + self.d * other.d,
      self.a * other.e + self.c * other.f + self.e,
      self.b * other.e + self.d * other.f + self.f,
    )

  def apply(self, x, y):
    return (self.a * x + self.c * y + self.e,
            self.b * x + self.d * y + self.f)

  def scale_factor(self):
    """Average linear scale, used to keep stroke widths visually stable."""
    sx = math.hypot(self.a, self.b)
    sy = math.hypot(self.c, self.d)
    return (sx + sy) / 2.0

  def to_svg(self):
    parts = [fmt(v, 4) for v in (self.a, self.b, self.c, self.d, self.e, self.f)]
    return "matrix(%s)" % ",".join(parts)

  def is_identity(self):
    return (self.a == 1.0 and self.b == 0.0 and self.c == 0.0
            and self.d == 1.0 and self.e == 0.0 and self.f == 0.0)

  def __repr__(self):
    return "Affine(%s)" % ", ".join(
      fmt(v, 4) for v in (self.a, self.b, self.c, self.d, self.e, self.f))


def cell_matrix(x, y, w, h, sw, sh, rotate=0, mirror=False):
  """Build the transform placing a symbol into sheet coordinates.

  The symbol's natural box is (sw, sh); it is scaled to (w, h), optionally
  mirrored left-to-right, then rotated about the centre of that box. `x, y`
  is the top-left of the unrotated box, so rotating a cell never moves its
  centre -- which is what makes repeated rotation feel predictable.
  """
  if sw <= 0 or sh <= 0:
    raise ValueError("symbol size must be positive, got %r x %r" % (sw, sh))

  cx = x + w / 2.0
  cy = y + h / 2.0
  sx = w / float(sw)
  sy = h / float(sh)
  if mirror:
    sx = -sx

  m = Affine.translate(cx, cy)
  m = m.multiply(Affine.rotate(rotate))
  m = m.multiply(Affine.scale(sx, sy))
  m = m.multiply(Affine.translate(-sw / 2.0, -sh / 2.0))
  return m


def bbox_of_points(points):
  """Return (x, y, w, h) covering the given (x, y) pairs, or None if empty."""
  if not points:
    return None
  xs = [p[0] for p in points]
  ys = [p[1] for p in points]
  return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def union_bbox(a, b):
  if a is None:
    return b
  if b is None:
    return a
  x0 = min(a[0], b[0])
  y0 = min(a[1], b[1])
  x1 = max(a[0] + a[2], b[0] + b[2])
  y1 = max(a[1] + a[3], b[1] + b[3])
  return (x0, y0, x1 - x0, y1 - y0)


def expand_bbox(box, margin):
  if box is None:
    return None
  return (box[0] - margin, box[1] - margin,
          box[2] + 2 * margin, box[3] + 2 * margin)


def corners(x, y, w, h):
  return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def snap(value, step):
  if not step:
    return value
  return round(value / float(step)) * step
