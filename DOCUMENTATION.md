# drawlogic manual

Complete reference. For a quick start, see [README.md](README.md).

- [Install and run](#install-and-run)
- [Command line](#command-line)
- [The editor](#the-editor)
- [The .dlg file](#the-dlg-file)
- [Symbols](#symbols)
- [Nets and buses](#nets-and-buses)
- [Checking a drawing](#checking-a-drawing)
- [How it is put together](#how-it-is-put-together)
- [Extending it](#extending-it)

---

## Install and run

Python 3.8 or newer. No pip packages, no Node, no network access.

```bash
git clone <repo-url> drawlogic
cd drawlogic
python3 -m drawlogic --version
```

To type `drawlogic` rather than `python3 -m drawlogic`, without installing:

```bash
export PYTHONPATH=$PWD:$PYTHONPATH
alias drawlogic='python3 -m drawlogic'
```

With pip available, `pip install -e .` gives the same short command.

Every command is discoverable from the tool itself:

```bash
drawlogic help            # overview with examples
drawlogic help export     # detail for one command
```

---

## Command line

### serve

Runs the browser editor.

```bash
drawlogic serve                          # serves . on http://127.0.0.1:8080
drawlogic serve alu_ctrl.dlg             # open one drawing straight away
drawlogic serve --dir ~/schematics --port 9000
drawlogic serve --no-browser
```

| Option | Meaning |
|---|---|
| `--dir DIR` | folder to serve (default: the file's folder, or `.`) |
| `--port N` | port to listen on (default 8080) |
| `--host H` | interface to bind (default `127.0.0.1`, loopback only) |
| `--no-browser` | do not open a browser window |

The server binds to loopback and serves exactly one folder; nothing outside
that directory is reachable. **If the machine is remote, tunnel rather than
opening it up with `--host`:**

```bash
ssh -L 8080:localhost:8080 you@workstation
```

### export

```bash
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --zoom 2
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --width 1600
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --crop --margin 20
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --bg transparent --grid
drawlogic export alu_ctrl.dlg -o -              # SVG to stdout
drawlogic export *.dlg --outdir svg/
```

| Option | Meaning |
|---|---|
| `-o PATH` | output file, or `-` for stdout |
| `--outdir DIR` | write each input's SVG into this directory |
| `--zoom N` | scale the output size; geometry unchanged (default 1.0) |
| `--width PX` | absolute output width; overrides `--zoom` |
| `--margin N` | padding around the drawing |
| `--bg COLOR` | background colour, or `transparent` |
| `--grid` | include the canvas grid in the output |
| `--crop` | trim to the drawing instead of the full sheet |
| `--no-title` | leave the title off the sheet |
| `--no-arrows` | leave direction arrows off the wires |
| `--no-hops` | draw crossing wires flat instead of bridging them |

**How `--zoom` works.** The drawing's true geometry lives in the SVG
`viewBox` and never changes; `--zoom` scales only the `width` and `height`
attributes. `--zoom 2` produces a file that lands twice as large with no loss
of quality, and it is the identical mechanism the editor's zoom control uses.
`--width` is the same idea expressed as an absolute pixel target.

### info, validate

```bash
drawlogic info alu_ctrl.dlg       # counts, canvas, bounding box, cells by type
drawlogic validate alu_ctrl.dlg   # schema errors, unconnected pins, bus widths
```

`validate` exits non-zero when it finds errors, so it drops into a pre-commit
hook or a CI job unchanged.

### symbols

```bash
drawlogic symbols list
drawlogic symbols list --category gates
drawlogic symbols show and2
drawlogic symbols preview and2 -o and2.svg
```

`preview` renders one symbol on its own, which is how to eyeball a cell you
have just added without opening the editor.

### Global options

| Option | Meaning |
|---|---|
| `--symbols-dir PATH` | extra symbol file or directory; repeatable |
| `-q`, `--quiet` | only report problems |
| `--version` | print the version |

Both work before or after the subcommand: `drawlogic -q export f.dlg` and
`drawlogic export f.dlg -q` behave the same.

---

## The editor

### Placing and wiring

Click a symbol in the palette, then click the canvas. Shift-click the canvas
to keep placing the same one. Press `W` for the wire tool, then click one pin
and the next to connect them.

Wires are stored as **pin references, never coordinates**. Once a wire exists
it stays attached no matter what moves, and the path is re-routed from the
pins on every redraw.

### Keys

| | |
|---|---|
| `V` `W` | select tool, wire tool |
| `L` `B` `P` `T` | line, box, polygon, text |
| click, shift-click, drag a box | select one, add to selection, marquee |
| drag | move, snapped to the grid |
| `Ctrl`+drag | duplicate as you drag |
| drag a wire | slide that run of it; the wire becomes hand-routed |
| double-click a wire | hand it back to the router |
| drag a wire | bend it: the drag point becomes a waypoint |
| handles, `Alt`+handle | resize with ratio locked / free |
| arrows, `Shift`+arrows | nudge one grid step / ten |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo |
| `Ctrl+C` `Ctrl+X` `Ctrl+V` `Ctrl+D` | copy, cut, paste, duplicate |
| `Ctrl+G` / `Ctrl+Shift+G` | group / ungroup |
| `Ctrl+R` / `Ctrl+Shift+R` | rotate 90 clockwise / anticlockwise |
| `Ctrl+H` / `Ctrl+Shift+H` | flip horizontal / vertical |
| `Ctrl+]` / `Ctrl+[` | bring to front / send to back |
| `Delete`, `Esc` | delete, cancel and deselect |
| `Ctrl+A`, `Ctrl+0` | select all, fit to window |
| `Alt`+drag | move without any alignment help |
| `Ctrl+S`, `Ctrl+E` | save, export SVG |
| `Ctrl+Shift+E` | copy the drawing as a picture, for pasting into a slide |
| scroll, `Space`+drag, shift-drag | zoom, pan, pan |

Selecting one member of a group selects all of it, so a group drags and
resizes as a single object.

### Autoshapes

Line, box and text are drag-or-click. Polygon is click-by-click: each click
adds a point, double-click or `Esc` closes it.

Shapes are selected, moved, resized, coloured, grouped and z-ordered exactly
like cells. An unfilled shape is clickable across its whole area, not just its
outline, and cells always draw above shapes so a box drawn as an annotation
never swallows a click meant for a gate inside it.

### Arrange

The **Arrange** menu aligns edges, distributes evenly (three or more items),
and moves things front or back.

### View

The **Zoom**, **Text** and **Symbols** sliders control view scale,
`canvas.font.scale` and `canvas.symbolScale`. The last two change the
document, so they mark it unsaved; zoom does not.

### Saving

`Ctrl+S` saves; nothing else writes to disk. There is no autosave and no
backup file. The one automatic behaviour is the browser refusing to close a
tab with unsaved changes.

`Ctrl+E` exports. **Export is rendered by Python**, the same code path the CLI
uses, so a file exported from the browser is byte-for-byte what
`drawlogic export` would produce.

### Custom pictures

Place a `custom` cell, select it, and pick an image file in the properties
panel. The picture is embedded in the `.dlg` as a data URI, so the drawing
stays one shippable file rather than a file plus a folder of images.

### Making your own symbol

There is no separate symbol editor, because a symbol is already very nearly a
drawing: a box, a pin list and some draw ops. So a custom cell is authored as
an ordinary drawing, with the tools that are already there.

1. Draw the outline and any markings with the shape tools -- box, line,
   polygon, text.
2. Drop a port on each edge where a wire should land. `port_in` becomes an
   input pin, `port_out` an output, `port_inout` a bidirectional one, and the
   port's name becomes the pin's name.
3. **Save as symbol**, and give it an id (letters, digits and underscores).

It appears immediately in the palette under **custom**, and is placed by
clicking it and then clicking the canvas, the same as any built-in.

Two things the conversion decides, both worth knowing before you draw:

**The artwork sets the body.** The body box is the bounding box of the
*shapes*, not of the ports. A port sits beside the thing it connects to, so
counting it would leave every pin sunk inside the outline rather than sitting
on it.

**Each pin snaps to the nearest edge it is outside of.** A pin on an edge
faces outwards, and which way it faces is what the router reads to decide
which side a wire leaves from. So a port dropped roughly in the right place is
moved exactly onto the edge it was nearest -- you do not have to land it on
the pixel.

The result is written to `symbols.json` in the folder you are serving, in the
same format as the built-in library, so it is a text file you can diff, edit
by hand, and commit alongside the drawings that use it. Every reader picks it
up automatically:

```bash
drawlogic validate board.dlg        # knows my_block, no flags needed
drawlogic symbols preview my_block -o my_block.svg
```

A drawing that uses a custom cell needs `symbols.json` beside it, the same way
a hierarchical block needs the drawing it refers to.

---

## The .dlg file

One JSON file per drawing, pretty-printed with a stable key order so
`git diff` reads as "moved U1, added net en" rather than one unreadable line.
A schematic is reviewable the same way code is.

```json
{
  "format": "drawlogic",
  "version": 1,
  "title": "dff_slice",
  "canvas": {
    "width": 900,
    "height": 560,
    "background": "#ffffff",
    "grid": { "style": "dots", "size": 10, "color": "#b9c7cc" },
    "font": { "family": "IBM Plex Sans", "scale": 1.0 },
    "symbolScale": 1.0,
    "arrows": true
  },
  "cells": [
    { "id": "u1", "type": "and2", "x": 220, "y": 120, "w": 60, "h": 40,
      "rotate": 0, "mirror": false, "label": "U1", "style": {} }
  ],
  "nets": [
    { "id": "n3", "name": "en", "width": 1,
      "from": { "cell": "u1", "pin": "y" },
      "to":   { "cell": "ff1", "pin": "d" },
      "waypoints": [], "style": {} }
  ],
  "shapes": [],
  "groups": []
}
```

### canvas

| Field | Meaning |
|---|---|
| `width`, `height` | sheet size; the drawing area is fixed |
| `background` | sheet colour |
| `grid.style` | `blank`, `dots`, `dots-wide`, `lines`, `lines-heavy` |
| `grid.size` | grid step, also the snap step |
| `font.family`, `font.scale` | text face and a multiplier on every label |
| `symbolScale` | one multiplier on the size of every cell |
| `arrows` | draw direction arrows on wires |
| `hops` | bridge a wire over any wire it merely crosses |

The grid is a drawing aid and stays out of exported SVG unless `--grid` is
passed.

### cells

| Field | Meaning |
|---|---|
| `id` | unique within the document |
| `type` | a symbol id, e.g. `and2` |
| `x`, `y` | top-left of the unrotated box |
| `w`, `h` | size; defaults to the symbol's natural size |
| `rotate` | 0, 90, 180 or 270, about the cell's centre |
| `mirror` | flipped left-to-right |
| `label` | instance name, drawn above the cell |
| `pins` | per-pin names, e.g. `{"in1": "wptr"}`; see below |
| `style` | `fill`, `stroke`, `strokeWidth` overrides |
| `image` | data URI for a `custom` cell's picture; exported too |
| `ref` | path to another drawing this cell stands for; see Hierarchy |

### nets

| Field | Meaning |
|---|---|
| `from` | the driver: `{cell, pin}` or a free `{x, y}` |
| `to` | the loads: a **list** of the same, each with its own `waypoints` |
| `name` | net name; carries bus width |
| `width` | bit width, derived from the name |
| `style` | `stroke`, `strokeWidth`, `arrow: false` |

### One driver, many loads

A net has one driver and any number of loads:

```json
{ "id": "n4", "name": "wclk", "width": 1,
  "from": { "cell": "p_wclk", "pin": "p" },
  "to": [ { "cell": "sr1", "pin": "ck", "waypoints": [] },
          { "cell": "sr2", "pin": "ck", "waypoints": [] } ] }
```

Each load is routed from the driving pin in turn, which is why the branches
lie on top of each other near the driver and part company where they must --
the junction dots mark exactly where. They are drawn as one path element with
a subpath per branch, so clicking any part of a rail finds the same net.

Waypoints belong to a load rather than to the net, because branches go
different ways.

**Why it is worth the format version.** Before version 2 a net had exactly one
load, so a signal reaching three places was three separate nets that happened
to share a driving pin and happened to be drawn on top of each other. That was
a convincing picture and a poor model: a rail could not carry one name (only
one of the three nets could hold it), its width could not be checked as a
whole, renaming it meant editing three things, and nothing could tell a
fan-out apart from a short. Two nets driving one pin is now a validation
error, which could not previously be said at all.

### Opening an older drawing

A version 1 file is upgraded when it is loaded, and nets that share a driving
pin are merged into one. Nets whose names disagree are left alone: two names
on one pin is either a mistake or a deliberate alias, and silently dropping
one would be worse than leaving the drawing as it was.

Saving writes version 2. Upgrading is safe to repeat.

### shapes

`kind` is `rect`, `ellipse`, `line`, `polygon`, `polyline` or `text`. Boxed
kinds use `x`, `y`, `w`, `h`; line-like kinds use `points`; `text` uses `x`,
`y` and `text`.

### groups

`{ "id": "g1", "label": null, "members": ["u1", "u2"] }`. A cell belongs to at
most one group.

---

## Symbols

Every cell type is an entry in `drawlogic/symbols.json`:

```json
{
  "and2": {
    "name": "2-input AND",
    "category": "gates",
    "size": [60, 40],
    "pins": [
      { "name": "a", "x": 0,  "y": 10, "dir": "in" },
      { "name": "b", "x": 0,  "y": 30, "dir": "in" },
      { "name": "y", "x": 60, "y": 20, "dir": "out" }
    ],
    "draw": [
      { "op": "path", "d": "M10 0 H30 A20 20 0 0 1 30 40 H10 Z", "role": "body" }
    ]
  }
}
```

**Symbols are data, not code.** Adding a gate, flop or custom cell means
adding one entry and changing no Python and no JavaScript. Both renderers read
this same file, which is what stops them drifting apart.

### Draw ops

`path` (`d`), `line` (`x1 y1 x2 y2`), `rect` (`x y w h`), `circle`
(`cx cy r`), `polygon` (`points`), `text` (`x y text anchor`).

### Roles

A `role` decides how an op is painted, so restyling the whole library is a
change to `theme.py`.

| Role | Painted as |
|---|---|
| `body` | the cell's fill and stroke |
| `pin` | stroke only, at wire weight so joints look continuous |
| `bubble` | filled, for inversion circles |
| `decor` | stroke only, no fill, for open marks |
| `ghost` | dashed grey, for placeholders |
| `pin_label` | small grey text |

### Pins

| Field | Meaning |
|---|---|
| `name` | unique within the symbol |
| `x`, `y` | position in the symbol's own coordinates |
| `dir` | `in`, `out` or `inout` |
| `width` | bit width; `0` means "any width" |

### Setting default sizes

**Per type**: `size` in the symbol entry. A 2-input gate is 60x40, a flop
70x60, a port 20x10.

**Per drawing**: `canvas.symbolScale` multiplies every cell at once. Each cell
grows about its own centre, so turning the whole drawing up does not drag the
layout sideways, and wires stay attached because they re-resolve from the
moved pins.

### Your own symbols

```bash
drawlogic --symbols-dir ~/my-cells.json symbols list
drawlogic --symbols-dir ~/my-cells/ export foo.dlg -o foo.svg
```

Accepts a file or a directory of `.json` files. An entry with the same id as a
built-in overrides it.

A `symbols.json` sitting **beside the drawings** is loaded without any flag,
by the editor and by every CLI subcommand. That is where
[Save as symbol](#making-your-own-symbol) writes, and it means a folder of
drawings plus the cells they use is self-contained: clone it and everything
resolves. `--symbols-dir` is for a library you share across folders.

Load order is built-ins, then `--symbols-dir` in the order given, then the
folder's own file -- so the nearest definition wins.

---

## Nets and buses

Width lives in the **name**: `d[7:0]` is eight bits, `d[3]` is one, `clk` is
one. `validate` complains if a declared width disagrees with the name, or if a
bus lands on a single-bit pin.

Buses are drawn with the same line weight as a single bit; the name carries
the width, not the stroke.

A pin may declare `"width": 0`, meaning it accepts a bus of any width. Ports,
generic block ports and the bus ripper use this. An ordinary gate pin is one
bit and rejects a bus.

`ripper` and `bus_tap` symbols are provided for pulling a bit off a bus.

A bus synchroniser stage is an n-bit `reg`, not a single `dff`: a `dff`'s D pin
is one bit, so wiring a bus to it is an error the checker will catch.

### Naming the pins on one instance

A symbol's pin labels are part of the symbol: every `dff` says `D`, `CK`, `Q`.
A generic `block` says nothing at all, which leaves a reader tracing wires to
find out what a pin is for.

`cell.pins` names the pins on one instance without touching the symbol:

```json
{ "id": "wfull", "type": "block",
  "pins": { "in1": "wptr_g", "in2": "rptr_g2", "out1": "wfull" } }
```

- Where the symbol already labels that pin, the name replaces it in the same
  spot -- `{"ck": "wclk"}` on a flip-flop writes `wclk` where `CK` was.
- Where it does not, the name is placed just inside the body on the face the
  pin sits on, so a block labels itself.
- An empty string hides the symbol's own label.

Naming a pin the symbol does not have is a validation error. In the editor the
Pins panel has a field per pin; clearing it goes back to the symbol's default.

## Hierarchy

A cell with a `ref` stands for another drawing, the way a module instance
stands for a module:

```json
{ "id": "u_fifo", "type": "sheet", "ref": "cdc_fifo.dlg",
  "x": 420, "y": 120, "label": "U_FIFO" }
```

The path is read relative to the drawing that holds it.

### The block's pins are the child's ports

They are not written down anywhere. Every `port_in`, `port_out` and
`port_inout` in the child becomes a pin on the parent's block: the port's
label is the pin name, its type gives the direction, and the pins run down the
block's faces in the order the ports run down the child's sheet -- inputs west,
outputs east. The block is sized to fit them.

So the two cannot quietly disagree. Add a port to the child and the parent
grows a pin. Rename one and the parent's pin is renamed with it, which makes
any wire still using the old name a validation error rather than a wire
pointing at nothing.

The block's `w` and `h` are stored like any other cell's, so a child that
later grows a port keeps the size you gave it. Delete `w` and `h` to take the
natural size again.

### Opening the child

In the editor, double-click a block to open what it references; a trail at the
top right leads back up. The Properties panel names the reference and opens it
too. From the command line:

```bash
drawlogic info top.dlg          # prints the hierarchy under it
drawlogic validate top.dlg      # reports references that do not resolve
drawlogic export top.dlg        # draws the block from the child's ports
```

### When a reference does not resolve

A missing, unreadable or looping reference is a validation error, and the cell
is drawn as a labelled empty box saying which. It is drawn rather than left
out on purpose: a cell you cannot see is a cell you cannot click on to fix.

A drawing can reference another that references a third, to sixteen levels. A
loop back to a drawing already open above is caught and reported.

### One drawing never affects another

A `ref` is a path relative to the drawing holding it, so the same text names
different files in different folders. Each open drawing therefore resolves
into its own copy of the symbol library, and the shared library is never
touched.

---

### Help while you drag

Dropping cells on a grid gets you close; it does not get you a straight wire.
A wire runs straight only when the two pins it joins share a row (or a column),
and being one grid step out is enough to put a kink in it.

So while you drag, drawlogic looks for a small nudge that would line something
up, and draws the line it found:

- a pin on a moving cell with the pin it is wired to -- the one that matters,
  since it is what turns an elbow into a straight line
- an edge or centre of a moving cell with one that is staying put

Pin alignment wins even when the edge match is closer. The pull reaches about
8 screen pixels, so it feels the same however far you are zoomed in. Hold
`Alt` while dragging to turn it off and place a cell exactly where you put it.

### Bending a wire by hand

Drag any run of a wire and it slides: a horizontal run moves in y, a vertical
one in x. A run slides across itself, not along itself. Grab an end run -- one
with a pin on it -- and a corner is inserted for it, because a pin cannot
move; that is how a straight wire is bent into a Z.

**Dragging a wire is what decides it is routed by hand.** Every corner becomes
a waypoint, so it stays exactly where you put it rather than being re-derived
into something else on the next redraw. Double-click a wire to clear those and
hand it back to the router.

Each branch is dragged on its own, so bending one leg of a rail leaves the
others alone.

Wires carry a wide invisible stroke underneath them for the pointer to catch;
a 1.6-unit line is too thin to grab reliably, and it is only on the canvas --
the exported file has no use for it.

### Auto layout

`Arrange > Auto layout`, or `drawlogic layout FILE`, rearranges the whole
drawing from what it is wired to. It is the difference between a correct
drawing and a readable one, and it is the thing hand-placing cells cannot
give you.

Four passes:

1. **Rank.** Each cell goes one column right of everything that drives it.
   Feedback loops make that impossible, so the edges that close a loop are
   found first and left out of the ranking -- they are still drawn, as the
   wires that come back. Output ports are pushed to the right edge rather than
   one step past whatever drives them, or the sheet ends in a staircase.
2. **Order.** Cells within a column are sorted by the median position of their
   neighbours in the next column along, swept back and forth. Wires cross when
   the order in one column disagrees with the next; the median is the cheap
   way to make them agree.
3. **Place.** Columns left to right. Within a column each cell sits at the
   height that makes its incoming wire straight -- following one driver
   rather than the average of several, because one wire dead straight beats
   two half-straight -- then cells are pushed apart where two want the same
   room.
4. **Fit.** The sheet is resized to what is actually drawn, wires included.

It also turns every cell to face forward and drops every waypoint. A mirrored
block has its inputs on the east, so in a left-to-right layout every wire into
it comes round the back; and a waypoint is a coordinate on the old sheet,
which after everything moves names a place with nothing at it.

**Only cells move.** Bands, captions and dividers stay where they are, because
nothing says which cell a shape belongs to -- expect to nudge them after. The
status bar and the CLI both say how many were left behind.

Running it twice changes nothing the second time, so you can always tell
whether it did something.

The work happens in Python, in `layout.py`, and the editor calls it over
`/api/layout`. A layout is not a gesture, so the round trip costs nothing, and
there is one implementation of it the way there is one renderer.

### Tidy up

`Arrange > Tidy up` pulls the selected cells into line with what they are wired
to, so a rough sketch becomes a clean one. The status bar says how many wires
it straightened.

Only the selected cells move. Everything else anchors them, so you can tidy one
block at a time -- and selecting a single cell snaps just that cell to its
neighbours.

Two rules keep it predictable:

- **A cell that already has a straight wire keeps it.** Tidying never trades
  one alignment for another, so running it twice changes nothing the second
  time.
- **Nothing moves sideways.** Only the coordinate across the flow changes, so
  the left-to-right order you placed things in survives. For even spacing along
  the flow, use `Distribute across` after.

### Getting the drawing into a slide

**Copy PNG** (`Ctrl+Shift+E`) puts the drawing on the clipboard as a picture,
at twice sheet size so it holds up on a projector. Paste straight into
PowerPoint, a doc or a chat.

It is a picture of the *exported file*, not a screenshot of the canvas: the
browser asks Python for the SVG -- the same render `drawlogic export` and the
Export SVG button produce -- and rasterises that. Selection handles, the grid
and wherever you happened to be scrolled never appear in it.

If the browser refuses the clipboard write, the PNG is downloaded instead and
the status bar says so.

One caveat: text in a rasterised SVG uses the fonts the machine has, not the
web font the page loaded, so a machine without IBM Plex falls back to Arial in
the PNG. The SVG itself is unaffected.

For PDF, print the drawing from the browser.

### Direction arrows

Arrows point from driver to load. One always sits near the receiving end,
which is where a reader looks to ask "what drives this?", and on a long run
more are spaced along the wire at `theme.ARROW_SPACING` -- a single arrow says
nothing about a run that is mostly somewhere else. Arrows are kept off
corners, where a head pointing into a bend reads worse than no head at all.

Turn them off for a drawing with `"canvas": { "arrows": false }`, for one
export with `--no-arrows`, or for one net with `"style": { "arrow": false }`.

### Where a name goes

A name that lands on a wire it has nothing to do with is worse than no name at
all. Each name is tried in several places along its own route -- along each
run, at a few points, on either side -- and scored against the cells, the
other wires, and the names already placed. The clearest spot wins, with ties
broken towards a horizontal run, near its middle, on the near side.

Nets are considered in document order, so the first net stated gets the
clearest spot: the same rule the router follows.

### Junction dots and crossing hops

A dot is drawn where three or more wire branches meet. Where one wire merely
crosses another, the horizontal one is drawn with a small semicircular bridge
over the vertical, so a crossing and a connection can never be mistaken for
each other.

Hops are on by default. Turn them off for a drawing with
`"canvas": { "hops": false }`, or for one export with `--no-hops`. Only the
horizontal wire hops, so a crossing pair never both bulge at the same spot.

### Routing

Wires are orthogonal, and the router follows three rules.

**Leave and enter on the pin's own side.** Every wire takes a short stub
straight out of the pin before it is allowed to turn, so a clock pin on the
west face of a flip-flop is always approached from the west. Pin stubs are
drawn at the same weight as wires, so the joint reads as one continuous line
rather than two lines meeting.

**Clear every cell.** No leg of a route is drawn without checking it misses
every cell the net is not connected to -- including a run that happens to be
dead straight, which is where a wire is most likely to be quietly laid across
a block. When the straight line is blocked the router sidesteps around it.

**Stay off other wires.** Nets are routed in document order and each one
remembers where it ran, so a later wire prefers a corridor that neither
shadows nor crosses an earlier one. Wires that share a pin are exempt: a
fanned-out clock is *meant* to lie on top of itself and show up as one rail
with junction dots. Both are preferences -- in a crowded drawing the router
falls back to any corridor that clears the cells.

Order therefore matters: the first net stated gets the straightest run. Drag a
wire to add a waypoint the route must pass through, which is the way to draw
something the router cannot guess, such as a clock rail that has to run below
the whole sheet.

---

## Checking a drawing

`validate` reports:

**Errors** (exit code 1): unknown cell type, duplicate id, a net pointing at a
missing cell or a pin that does not exist, a bus width that disagrees with the
net name, a bus on a single-bit pin, a group member that does not exist.

**Warnings** (exit code 0): unconnected pins, a rotation that is not a
multiple of 90, a net name that is not a legal identifier.

---

## How it is put together

```
drawlogic/
  geometry.py     affine transforms; pins and shapes share one matrix
  symbols.py      symbol registry, pin resolution
  symbols.json    the cell library -- add entries here, not code
  doc.py          .dlg load, save, normalise, validate, bus names
  layout.py       arranging a drawing from what it is wired to
  routing.py      orthogonal routing, corridors, junction dots
  sheets.py       hierarchy: a block built from another drawing's ports
  authoring.py    turning a drawing of shapes and ports into a symbol
  render_svg.py   the only path from document to SVG
  theme.py        colours, line weights, font stacks
  cli.py          serve, export, layout, symbols, info, validate, help
  server.py       stdlib HTTP server for the editor
  web/
    index.html, css/app.css
    js/geometry.js   affine maths and symbol placement
    js/routing.js    wire routing
    js/render.js     document to live SVG DOM
    js/model.js      document state, undo/redo, every mutation
    js/selection.js  selection and its handles
    js/tools.js      select, wire, place, shape
    js/panels.js     palette and properties inspector
    js/viewport.js   pan and zoom
    js/guides.js     drag-time alignment and the Tidy rule
    js/picture.js    rasterise the export to a pasteable PNG
    js/main.js       bootstrap and controls
tests/            unittest, a golden-file regression suite, a JS parity check
examples/         worked schematics, including a CDC FIFO
```

### One renderer for every exported file

The editor's Export hands its document to `render_svg.py` rather than
screenshotting the canvas. The GUI and the CLI cannot disagree about output.

### Why JavaScript duplicates two modules

`web/js/geometry.js` and `web/js/routing.js` are ports of their Python
counterparts, because the canvas must reroute a wire while you drag a gate and
cannot wait on a server round trip. Four things keep them honest: both sides
read the same `symbols.json`, the theme is served from `theme.py` rather than
restated in JS, every export goes through Python, and `tests/test_js_parity.py`
routes every example through both and fails if a single point differs.

### Undo

Whole-document snapshots, not inverse operations. A schematic is small, and a
snapshot cannot fall out of step with the edit it undoes. A drag opens a
"gesture" so the whole drag undoes in one step.

### Text and line weight

Enlarging or rotating a gate does not stretch its pin names: text is drawn
upright at a fixed size. Stroke weight is divided back out of the cell's own
scaling, so a big gate keeps normal line weight instead of turning bold.

### Fonts

Exported SVG asks for IBM Plex Sans and falls back to Arial and Helvetica, so
a drawing opened on a machine without Plex still lays out sensibly.

---

## Extending it

### A new gate

Add an entry to `drawlogic/symbols.json`. No code changes. Check it with:

```bash
drawlogic symbols preview mygate -o mygate.svg
```

### A new export format

Add a module beside `render_svg.py` and a subcommand in `cli.py`.

### A new editing tool

Add a class to `web/js/tools.js` with `onPointerDown`, `onPointerMove` and
`onPointerUp`, register it in `makeTools`, and add a button with
`data-tool="yourname"` to `index.html`.

### A new document change

Add a function to `web/js/model.js` and call it through `store.mutate`, which
is what gives it undo and the dirty marker for free.

### Restyling

`theme.py` holds every colour, line weight and font size. The browser fetches
it from `/api/theme` rather than restating it.

---

## Tests

```bash
python3 -m unittest discover          # everything
python3 -m unittest tests.test_regression
```

The suite is in ten parts:

| File | Covers |
|---|---|
| `tests/test_model.py` | document format, symbol library, bus naming |
| `tests/test_draw.py` | routing and SVG rendering |
| `tests/test_server.py` | HTTP endpoints, path-traversal refusal |
| `tests/test_regression.py` | golden files and whole-library invariants |
| `tests/test_js_parity.py` | routing.js against routing.py, net for net |
| `tests/test_js_editor.py` | drag-time alignment and Tidy |
| `tests/test_sheets.py` | hierarchy: derived pins, loops, broken references |
| `tests/test_layout.py` | auto layout: flow, overlap, settling |
| `tests/test_nets.py` | one driver and many loads, and the v1 upgrade |
| `tests/test_authoring.py` | turning a drawing into a symbol |

### The regression suite

`test_regression.py` is the safety net for changes that unit tests miss.

**Golden files.** Every drawing in `examples/` is rendered with fixed options
and compared byte for byte against `tests/golden/<name>.svg`. Any unintended
change to the renderer, the router or a symbol shows up as a diff naming the
first line that moved. After a deliberate change:

```bash
DRAWLOGIC_REGOLD=1 python3 -m unittest tests.test_regression
git diff tests/golden/
```

Read that diff before committing it. A golden updated without being read is
worse than no golden at all.

**Invariants**, checked against every example and every symbol rather than one
hand-picked case:

- no validation errors, and every net resolves to a path
- every wire segment is axis-aligned
- wires stay clear of cells they are not connected to
- documents round-trip unchanged, and files on disk are already canonical
- every symbol places, renders and previews
- every pin resolves inside its symbol's own box
- rotating a cell a full turn returns it exactly where it started
- an embedded picture reaches the exported SVG, not just the canvas

Adding a drawing to `examples/` automatically adds it to all of the above.

### The parity suite

`test_js_parity.py` guards the places where the same algorithm is written
twice: `routing.js` against `routing.py`, and the layout decisions in
`render.js` against `render_svg.py`. It puts every example through both and
compares every route point, junction dot, crossing bridge, name position and
arrow position.

`test_js_editor.py` covers alignment and Tidy, which exist only in JavaScript
and so have no Python counterpart to compare against.

It shells out to `node`, which is **not** a dependency of drawlogic, so it
skips itself when node is not installed and the rest of the suite still runs.
Where node is available it is cheap and worth running:

```bash
python3 -m unittest tests.test_js_parity
```

The rest of the JavaScript -- tools, selection, panels, the canvas itself --
has no automated tests, because covering it needs a browser toolchain and that
would cost the zero-dependency property that makes this installable on a
locked-down machine. It is exercised by hand through a headless browser
instead. If that trade stops being worth it, a Playwright suite kept outside
the install path would be the way to fix it.

---

## Not built yet

- **Several sheets inside one file.** Today a drawing is one sheet, and a
  hierarchy is a folder of them tied together by `ref`. Pages in one file,
  with off-sheet connectors, would be a different thing.
- **Netlist export** (Verilog, SPICE) and electrical rule checks. The net
  model supports it; `validate` is where it would grow.
- **Sheet border and title block.** Today there is just a title name at the
  bottom left.
- **PDF export.** Out of scope; print to PDF from the browser.
