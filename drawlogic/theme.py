"""Default visual constants.

Documents override any of these per element; these are only the fallbacks.
Keeping them in one place means restyling the whole tool is a single-file
change rather than a hunt through the renderer.

Usage:

    from drawlogic import theme

    theme.COLORS["net"]        # wire colour
    theme.WIDTHS["stroke"]     # default line weight
    theme.FONT_SIZES["label"]  # instance-name size, before font.scale
    theme.ROLE_STYLES["body"]  # how a symbol draw-op role is painted

The browser fetches all of this from /api/theme rather than restating it, so
the canvas and the exporter cannot drift apart on colours or weights.
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

  # Ports carry a default tint so the edge of a drawing reads at a glance:
  # what comes in, what goes out, what does both. Tints rather than strong
  # colour, because a port is punctuation, not the subject. A colour set on
  # the cell itself still wins over these.
  "port_in": "#dcecd8",
  "port_out": "#f7e2cd",
  "port_inout": "#e4dcf1",
}

# A symbol's pin stub and the wire that lands on it must be the same weight,
# or the joint reads as two different lines meeting rather than one line
# carrying on.
WIRE = 1.6

WIDTHS = {
  "stroke": 1.6,
  "pin": WIRE,
  "net": WIRE,
  "decor": 1.2,
  "ghost": 1.2,
}

# Base point sizes, before canvas.font.scale is applied.
FONT_SIZES = {
  "label": 13.5,
  "pin_label": 11.0,
  "net_label": 11.5,
  "title": 16.0,
  "shape_text": 14.0,
}

# Air above and below the sheet title, which sits in a band along the top.
# It was along the bottom, where a drawing that reached far enough down put a
# port's name straight through it -- and nothing noticed, because the title is
# not a cell and no DRC watches it. At the top it is out of the way of a
# drawing that grows downward, which is the direction they grow.
TITLE_PAD = 14.0

# How far inside the body a pin name sits when the symbol does not draw one
# itself, so a named block pin reads as the block's own labelling.
PIN_LABEL_INSET = 8.0

JUNCTION_RADIUS = 3.2
ARROW_SIZE = 7.0

# How far apart direction arrows sit along a wire. One arrow near the
# receiving end is enough on a short run and useless on a long one, where most
# of the wire is nowhere near it.
ARROW_SPACING = 240.0

# Radius of the little bridge drawn where one wire crosses another
# without connecting to it.
HOP_RADIUS = 5.0
GHOST_DASH = "4 3"

# How a symbol draw-op role is painted. "fill" and "stroke" name where the
# colour comes from: "cell" means the cell's own style wins.
# "fillDefault" names the colour a role falls back to when the cell does not
# set one of its own, which is how a port gets a tint without taking away the
# user's ability to recolour it.
ROLE_STYLES = {
  "body": {"fill": "cell", "stroke": "cell", "width": "stroke"},
  "port_in": {"fill": "cell", "fillDefault": "port_in",
              "stroke": "cell", "width": "stroke"},
  "port_out": {"fill": "cell", "fillDefault": "port_out",
               "stroke": "cell", "width": "stroke"},
  "port_inout": {"fill": "cell", "fillDefault": "port_inout",
                 "stroke": "cell", "width": "stroke"},
  "pin": {"fill": "none", "stroke": "cell", "width": "pin"},
  "bubble": {"fill": "cell", "stroke": "cell", "width": "pin"},
  "decor": {"fill": "none", "stroke": "cell", "width": "decor"},
  "ghost": {"fill": "none", "stroke": "ghost", "width": "ghost", "dash": GHOST_DASH},
  "pin_label": {"fill": "pin_label", "stroke": "none", "font": "pin_label"},
}

GRID_STYLES = ("blank", "dots", "dots-wide", "lines", "lines-heavy")
