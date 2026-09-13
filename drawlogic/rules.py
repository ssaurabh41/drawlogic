"""Design rules: the distances that decide whether a drawing reads well.

A schematic is legible or not for reasons that have nothing to do with being
correct. Two wires a hair apart read as one thick line. A gate pressed against
its neighbour reads as one part. A net name sitting on a wire is unreadable
even though every coordinate is right. Those are drafting conventions, and
every drawing office writes them down rather than leaving them to whoever is
holding the pen.

So they live here, in one file, instead of being scattered as magic numbers
through the router, the layout pass and the renderer. Tuning how a drawing
looks is editing this file; nothing else needs to change.

Distances are in document units, the same units cells and wires use. A small
logic gate is 40x40, so a unit is roughly "a twentieth of a gate".

The browser fetches these from /api/rules rather than restating them, so a
drag in the editor and a file from the exporter obey the same rules.

Usage:

    from drawlogic import rules

    rules.WIRE_GAP        # how far apart two parallel wires must sit
    rules.CELL_GAP_Y      # how far apart two stacked cells must sit
"""

# ---- wires ----------------------------------------------------------------

# Two parallel wires closer than this read as one line with a thick edge
# rather than as two signals. This is the single most important number here:
# below about 12 the eye stops separating them at normal zoom.
WIRE_GAP = 18.0

# How far a wire keeps from a cell it does not connect to. Touching a block
# it has nothing to do with suggests a connection that is not there.
WIRE_TO_CELL = 10.0

# How far apart the router tries successive corridors when its first choice is
# taken. Smaller finds a gap more often; larger keeps wires on rounder
# coordinates. Kept below WIRE_GAP so a rejected corridor is retried at a
# distance that could actually be free.
CORRIDOR_STEP = 10.0

# How many corridors to try either side before giving up and drawing the wire
# where it wanted to go. A crowded drawing should still produce a wire.
CORRIDOR_TRIES = 18

# ---- text -----------------------------------------------------------------

# Clear space demanded around a net name. A label touching a wire is as bad as
# one crossing it, so the box is grown by this before overlaps are counted.
LABEL_CLEARANCE = 5.0

# How far above a cell its instance name sits, and so how much room a layout
# has to leave for it.
LABEL_HEADROOM = 20.0

# ---- cells ----------------------------------------------------------------

# Room between one column of cells and the next. This is where the wires
# between them run, so it has to hold a few corridors side by side.
CELL_GAP_X = 110.0

# Room between two cells stacked in the same column.
CELL_GAP_Y = 52.0

# The least space allowed between any two cells, whichever way they sit.
# Closer than this and two parts read as one.
CELL_MIN_GAP = 24.0

# Space left around everything when a layout decides where the drawing starts.
SHEET_MARGIN = 90.0

# ---- sheet ----------------------------------------------------------------

# The sheet a new drawing gets. One size for every drawing means a folder of
# them prints and pastes consistently; change it per drawing in the properties
# panel when one needs more room.
SHEET_W = 1200.0
SHEET_H = 780.0


def as_data():
  """The rules as plain data, for /api/rules and the browser."""
  return {
    "wireGap": WIRE_GAP,
    "wireToCell": WIRE_TO_CELL,
    "corridorStep": CORRIDOR_STEP,
    "corridorTries": CORRIDOR_TRIES,
    "labelClearance": LABEL_CLEARANCE,
    "labelHeadroom": LABEL_HEADROOM,
    "cellGapX": CELL_GAP_X,
    "cellGapY": CELL_GAP_Y,
    "cellMinGap": CELL_MIN_GAP,
    "sheetMargin": SHEET_MARGIN,
    "sheetW": SHEET_W,
    "sheetH": SHEET_H,
  }
