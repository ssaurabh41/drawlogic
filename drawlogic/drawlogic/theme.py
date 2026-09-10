"""Default visual constants.

Documents override any of these per element; these are only the fallbacks.
Keeping them in one place means restyling the whole tool is a single-file
change rather than a hunt through the renderer.
"""

# IBM Plex first, then faces that exist on essentially every machine, so a
# drawing opened somewhere without Plex installed still lays out sensibly.
FONT_SANS = "'IBM Plex Sans','IBM Plex Sans Text',Arial,Helvetica,sans-serif"
FONT_MONO = "'IBM Plex Mono','DejaVu Sans Mono','Courier New',monospace"

PAPER = "#ffffff"
INK = "#16202b"

COLORS = {
  "background": PAPER,
  "fill": PAPER,
  "stroke": INK,
  "net": INK,
  "junction": INK,
  "label": INK,
  "pin_label": "#5b6b74",
  "net_label": "#0d7490",
  "title": INK,
  "grid": "#b9c7cc",
  "grid_major": "#c3d0d5",
  "ghost": "#84969c",
}

WIDTHS = {
  "stroke": 1.6,
  "pin": 1.4,
  "net": 1.6,
  "bus": 3.0,
  "decor": 1.2,
  "ghost": 1.2,
}

# Base point sizes, before canvas.font.scale is applied.
FONT_SIZES = {
  "label": 11.0,
  "pin_label": 9.0,
  "net_label": 9.5,
  "title": 13.0,
  "shape_text": 12.0,
}

JUNCTION_RADIUS = 3.0
GHOST_DASH = "4 3"

# How a symbol draw-op role is painted. "fill" and "stroke" name where the
# colour comes from: "cell" means the cell's own style wins.
ROLE_STYLES = {
  "body": {"fill": "cell", "stroke": "cell", "width": "stroke"},
  "pin": {"fill": "none", "stroke": "cell", "width": "pin"},
  "bubble": {"fill": "cell", "stroke": "cell", "width": "pin"},
  "decor": {"fill": "none", "stroke": "cell", "width": "decor"},
  "ghost": {"fill": "none", "stroke": "ghost", "width": "ghost", "dash": GHOST_DASH},
  "pin_label": {"fill": "pin_label", "stroke": "none", "font": "pin_label"},
}

GRID_STYLES = ("blank", "dots", "dots-wide", "lines", "lines-heavy")
