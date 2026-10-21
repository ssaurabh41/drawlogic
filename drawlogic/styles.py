"""Named styles: one look, kept in the drawing, shared by many things.

A drawing may keep a table of named styles -- "compute", "memory", "io" --
and any cell, shape or container may name one in `styleRef`. What it looks
like is then worked out in three layers, each over the one before:

1. the theme's defaults (theme.py),
2. the named style,
3. the object's own `style`, `headingStyle` and `textStyle`.

The layers are merged when the drawing is drawn, measured or checked, and
never written back: an object keeps only what it overrides, so changing the
named style changes every object using it, and a colour set on one block by
hand stays on that block.

Usage:

    from drawlogic import styles

    look = styles.effective(doc.styles, cell)    # cell itself if nothing to merge
    look["textStyle"]["fontSize"]

    "styles": {
      "compute": {"style": {"fill": "#d8edb4", "stroke": "#adc18e"},
                  "headingStyle": {"fontSize": 16, "fontWeight": 600},
                  "textStyle": {"fontSize": 12, "fill": "#52656f"}}
    }

web/js/geometry.js mirrors `effective` line for line, so the canvas and an
export resolve a look the same way.
"""

# What a named style may set: the same three objects an item carries.
PARTS = ("style", "headingStyle", "textStyle")


def named(styles, item):
  """The named style an item refers to, or None."""
  ref = item.get("styleRef") if isinstance(item, dict) else None
  if not isinstance(ref, str) or not isinstance(styles, dict):
    return None
  found = styles.get(ref)
  return found if isinstance(found, dict) else None


def effective(styles, item):
  """`item` with its named style merged under its own overrides.

  The item itself when it names no style, or one that is not there -- so a
  drawing with no named styles is drawn from exactly the objects it holds. A
  shallow copy otherwise, with each part a fresh dict: nothing here writes to
  the drawing.
  """
  base = named(styles, item)
  if base is None:
    return item
  out = dict(item)
  for part in PARTS:
    shared = base.get(part)
    own = item.get(part)
    if isinstance(shared, dict) and shared:
      merged = dict(shared)
      if isinstance(own, dict):
        merged.update(own)
      out[part] = merged
  return out
