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
| `Ctrl+S`, `Ctrl+E` | save, export SVG |
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
| `style` | `fill`, `stroke`, `strokeWidth` overrides |
| `image` | data URI for a `custom` cell's picture; exported too |
| `ref` | reserved for hierarchy; ignored today |

### nets

| Field | Meaning |
|---|---|
| `from`, `to` | `{cell, pin}` or a free `{x, y}` |
| `name` | net name; carries bus width |
| `width` | bit width, derived from the name |
| `waypoints` | points the route must pass through |
| `style` | `stroke`, `strokeWidth`, `arrow: false` |

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
| `pin` | stroke only, thinner |
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
  routing.py      orthogonal routing, corridors, junction dots
  render_svg.py   the only path from document to SVG
  theme.py        colours, line weights, font stacks
  cli.py          serve, export, symbols, info, validate, help
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
    js/main.js       bootstrap and controls
tests/            unittest plus a golden-file regression suite
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

The suite is in four parts:

| File | Covers |
|---|---|
| `tests/test_model.py` | document format, symbol library, bus naming |
| `tests/test_draw.py` | routing and SVG rendering |
| `tests/test_server.py` | HTTP endpoints, path-traversal refusal |
| `tests/test_regression.py` | golden files and whole-library invariants |
| `tests/test_js_parity.py` | routing.js against routing.py, net for net |

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

`test_js_parity.py` guards the one place where the same algorithm is written
twice: `routing.js` against `routing.py`. It routes every example through both
and compares every point, junction dot and crossing bridge.

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

- **Hierarchy.** The `ref` field is reserved on every cell but ignored.
  Drill-down can be added without migrating files you have already drawn.
- **Netlist export** (Verilog, SPICE) and electrical rule checks. The net
  model supports it; `validate` is where it would grow.
- **Sheet border and title block.** Today there is just a title name at the
  bottom left.
- **PDF export.** Out of scope; print to PDF from the browser.
