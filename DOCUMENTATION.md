# drawlogic

**Draw logic circuit diagrams, and export them as SVG.**

## What this is for

You have a circuit in your head -- a few gates, a flip-flop, a block with a
bus going into it -- and you need a picture of it for a document, a review, or
a slide. Drawing that in PowerPoint works until you move one gate and spend
the next ten minutes dragging its wires back into place.

drawlogic exists because of that ten minutes. Wires here are attached to
**pins**, not to positions on the page. You say "the output of U1 goes to the
D input of FF1", and from then on the wire is the tool's problem: move the
gate anywhere and the wire follows, routes itself round whatever is in the
way, and stays connected.

The other half is that a drawing is a **plain text file**. It goes in git, it
shows up in a diff as "moved U1, added net en" rather than as an unreadable
binary blob, and a reviewer can read the change the same way they read code.

## Using it, in one minute

Nothing to install. You need Python 3.9 or newer and nothing else -- no pip
packages, no Node, no network.

```bash
git clone <repo-url> drawlogic
cd drawlogic
python3 -m drawlogic serve examples/dff_slice.dlg
```

That opens the editor in your browser. Then:

1. **Place a part.** Drag a gate out of the palette on the left onto the
   sheet, or click it and then click where you want it.
2. **Wire it up.** Press `W`, click one pin, click another. That is a net.
3. **Move things about.** Drag them. The wires re-route themselves.
4. **Make it tidy.** Press the auto-layout button and the whole drawing
   rearranges itself by what is wired to what.
5. **Save it** with `Ctrl+S`, and **export a picture** with `Ctrl+E`.

Nothing is written to disk until you save. There is no autosave and no backup
file, on purpose -- the only surprise the editor allows itself is refusing to
close a tab with unsaved changes.

If you would rather not open a browser at all, the command line does the same
work:

```bash
python3 -m drawlogic export mydrawing.dlg -o mydrawing.svg
python3 -m drawlogic validate mydrawing.dlg    # pins that only look connected, wires that only look separate
```

## Two things worth knowing up front

**Symbols are data, not code.** Every cell type is an entry in
`drawlogic/symbols.json` naming its outline and its pins. Adding a gate, flop
or custom cell means adding one entry and changing no Python and no
JavaScript. Both renderers read that file, which is what stops them drifting
apart. Point `--symbols-dir` at your own file or folder to add cells without
touching the built-ins, or draw one in the editor and press **Save as
symbol**.

**Wires store pin references, not coordinates.** A net records
`u1.y -> ff1.d`, and the path is re-routed from the pins on every draw. That
is what keeps wires attached when a gate moves, and what lets `validate` catch
a pin that only *looks* connected.

---

# Reference

Everything below is the complete reference.

- [Install and run](#install-and-run)
- [Command line](#command-line)
- [The editor](#the-editor)
- [The .dlg file](#the-dlg-file)
- [Symbols](#symbols)
- [Nets and buses](#nets-and-buses)
- [Design rule checks (DRCs)](#design-rule-checks-drcs)
- [Checking a drawing](#checking-a-drawing)
- [How it is put together](#how-it-is-put-together)
- [Extending it](#extending-it)
- [Tests](#tests)
- [Not built yet](#not-built-yet)

For how to review or verify this project, see [REVIEW.md](REVIEW.md).

---

## Install and run

Python 3.9 or newer. No pip packages, no Node, no network access.

3.9 is the floor because it is the oldest version the tests are actually run
on, not the oldest one the code might happen to work on. It said 3.8 for a
while and no 3.8 interpreter had ever run the suite -- a supported version
nobody exercises is a guess with a version number on it. Every push runs the
suite on 3.9 (`.github/workflows/tests.yml`), and `drawlogic.MIN_PYTHON` is
the one place the number lives: the sentence you are reading is checked
against it by `tests/test_python_floor.py`.

Newer versions are fine. 3.10, 3.11, 3.12 and 3.13 have all had the full
suite run on them, and nothing here imports a module that later versions
removed. If you are on something older than 3.9, it may well work -- nothing
in the code needs 3.9 specifically -- but nobody has checked, so do not
assume it.

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

On Windows, in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD;$env:PYTHONPATH"
function drawlogic { python -m drawlogic @args }
```

`python3` is often not a command there; `python` is. Take the repository whole
rather than file by file -- if you have had to copy files across one at a
time, run `verify.ps1` before anything else, because a mixed copy fails in
ways that look like bugs. See
[Checking the files themselves](#checking-the-files-themselves).

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
that directory is reachable. That applies to references too: a drawing served
here can only stand in for another drawing inside the same folder, and a `ref`
pointing out of it is refused and drawn as a broken-reference box. The command
line has no such limit -- it is run by somebody who already has the
filesystem, so a block kept one directory up resolves normally there.

**If the machine is remote, tunnel rather than opening it up with `--host`:**

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
drawlogic validate alu_ctrl.dlg   # references and design rule checks
```

Two kinds of problem: references that do not resolve, and drawings that read
as saying something they do not -- see
[Checking a drawing](#checking-a-drawing). `--no-drc` asks only the first
question.

`validate` exits non-zero when it finds errors, so it drops into a pre-commit
hook or a CI job unchanged.

### doctor

```bash
drawlogic doctor                   # is this copy sound?
drawlogic doctor --write-manifest  # record what it should be
```

Answers one question: do the pieces of this copy of drawlogic still fit each
other? It runs the Python end to end on a drawing it builds itself -- route,
check, lay out, render -- and then reads every browser module and confirms
that each thing it imports really is exported by the file it names. Exits
non-zero and says what to do if not.

Worth running first whenever something looks broken in a way that makes no
sense: a browser that will not draw, a Check that crashes, a control that is
not there. Those are what a half-updated copy looks like from the outside, and
none of it is visible by reading a file. Files from different versions of the
project cannot work together, so take the whole repository at once -- `git
clone`, or download and unzip
`https://github.com/ssaurabh41/drawlogic/archive/refs/heads/main.zip` --
rather than copying files across one at a time.

It also checks this copy against `manifest.txt`, which is the one thing
reading the code cannot tell you: whether a file is the version the rest of
the project was written against.

```
ok    route a wire
ok    check the rules
ok    lay it out
ok    render to SVG
33 built-in symbols
ok     11 browser modules, 0 import mismatches
ok     28 files against manifest.txt, 0 differ

this copy is consistent with itself
```

`--write-manifest` regenerates `manifest.txt` and does nothing else. Run it
after changing anything under `drawlogic/` -- the test suite fails until you
do, so this is not something to remember.

A manifest is usually a bad idea for two good reasons, and both had to be
answered before this one earned its place. See
[Checking the files themselves](#checking-the-files-themselves).

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

Nothing the editor does reaches past the machine it runs on. Every request
the page makes goes to its own server at `/api/...`; there is no web font, no
analytics, and no update check. Confirmed by routing every non-loopback
request through a proxy that aborts it and watching the log stay empty while
placing, wiring, saving and exporting a drawing. Useful to know on a
workstation whose network access is restricted -- point it at a folder and it
has nothing to ask permission for.

### Checking what you drew

The design rule checks run as you draw -- wires lying on other wires, parts
too close to tell apart, names sitting on wires. A moment after you stop
moving something, anything wrong with it is ringed on the canvas and listed
under Properties, with the count also in the status bar. Click a line in the
list and the view walks to it.

**live** in the DRC header turns that off; **Check** then runs it only when
you ask. See [Design rule checks](#design-rule-checks-drcs) and
[Live checking](#live-checking).

### Placing and wiring

Click a symbol in the palette, then click the canvas. Shift-click the canvas
to keep placing the same one. Press `W` for the wire tool, then click one pin
and the next to connect them.

Wires are stored as **pin references, never coordinates**. Once a wire exists
it stays attached no matter what moves, and the path is re-routed from the
pins on every redraw.

### Rubbing a wire out

Press `E` for the eraser, then drag the cursor across a wire. What goes is
that wire's **branch**: the run from one pin back to wherever it parts company
with the rest of the net. Wire a clock into a reset pin by mistake and the
eraser takes the run between the reset pin and the junction dot feeding it,
leaving the rest of the clock alone.

That is the unit because it is the only one that means anything. A net is one
driver and its loads, so the piece between a junction and a pin is not a
length of wire that can be rubbed out on its own -- it is that load's whole
share of the net, and the load going is what makes it disappear. Erasing the
last load takes the net with it, since a net driving nothing is not a net.

One sweep is one undo, however many wires it crossed, and the status line says
how many went.

### Keys

| | |
|---|---|
| `V` `W` `E` | select tool, wire tool, eraser |
| `L` `B` `P` `T` | line, box, polygon, text |
| click, `Ctrl`+click, drag a box | select one, add or remove one, marquee |
| drag | move, snapped to the grid (a wire snaps to 5, so it can reach a pin) |
| `Ctrl`+drag | duplicate as you drag |
| `Ctrl+N` | new drawing |
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
| scroll, `Space`+drag, `Shift`+drag | zoom, pan, pan |

`Ctrl` adds to the selection, not `Shift`, which is the slide-editor
convention rather than the browser one. `Shift` is the pan modifier on empty
canvas, and one key cannot mean both without the two fighting during a drag.
`Ctrl`+click on something already selected takes it back out; `Ctrl`+drag
duplicates, and the two are told apart by whether the pointer moved.

Symbols can be dragged from the palette straight onto the sheet. Clicking a
symbol and then clicking the sheet still works, and is the only route that
places several of the same part in a row.

The actions -- rotate, flip, group, align, distribute, auto layout, tidy,
front and back -- are the icon buttons in the second toolbar row. Hover any
of them for its name.

**Theme** cycles the application's appearance between following the operating
system, light, and dark, and remembers the choice. The drawing itself never
changes with it: the sheet is a document, and a document is white. An
exported file looks the same whichever is picked.

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
| `forkLate` | a wire with several loads runs as one trunk and divides near the pins it serves |

The grid is a drawing aid and stays out of exported SVG unless `--grid` is
passed.

`forkLate` is written by auto layout rather than set by hand, and only when it
measured better: see [How a wire forks](#how-a-wire-forks). A drawing that
gains nothing from it has no such key at all.

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

Five passes:

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
4. **Refine.** The whole place-and-route is run twice -- once following wires
   through the columns they skip, once not -- and the better result is kept.
   Then the winner is improved by trial: swap two neighbours in a column,
   re-route, measure, and keep the swap if the drawing got better. The median
   in pass 2 answers "which cell is roughly where"; only trying a swap answers
   "is this the best arrangement", and on the shipped examples this pass alone
   takes the crossings from 72 down to 63.
5. **Fit.** The sheet is resized to what is actually drawn, wires included.

**What "better" means** is one function, `_score` in `layout.py`, and it is the
whole of the layout's taste:

| Term | Weight | Why |
|---|---|---|
| wire length | 1 per unit | distance the eye has to travel |
| crossings | `CROSSING_COST`, 320 | a moment of doubt about which line is which. This is also the price of a crossing bridge, because a bridge is what a crossing is *drawn as* -- costing both would be counting one fault twice |
| spread | `SPREAD_COST`, 0.35 per unit of width plus height | drawing that has to be scrolled or shrunk to be seen |

Every candidate is judged by actually routing it, so what is scored is what
would be exported. The weights are judgements rather than measurements; on the
shipped examples they happen not to change the outcome, which is worth knowing
before tuning them.

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

If you edit the drawing while it is working, the result is dropped and the
status bar says so. The answer is a whole document built from the drawing as
it was, so applying it would take your edit with it -- which it used to do,
recoverable only by noticing and pressing undo. On a large drawing the round
trip is a couple of seconds, which is long enough to type something into.
Press Auto layout again once you have stopped.

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

One caveat: text in a rasterised SVG uses the fonts the machine has. The
editor loads no web font -- see below -- so a machine without IBM Plex
installed falls back to Arial in the PNG. The SVG itself is unaffected.

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

### How a wire forks

A wire with one driver and several loads has two ways to reach them. It can
give each load its own way across the sheet, which is what it has always done:
the branches lie on top of each other near the driving pin and part company as
soon as their routes differ. Or it can run as one trunk and divide near the
pins it serves, which is shorter and puts the junction dot beside the load
rather than beside the driver -- the way a schematic is normally read.

The second is better on most drawings and worse on some. A branch that leaves
late takes a line of its own across the sheet, and every wire routed after it
has to dodge that line instead of the old one; on a crowded sheet that can
cost more than the sharing saves. Of the drawings in `examples/`, forking late
wins on two, loses on one and makes no difference to the rest.

So it is not a rule, it is a measurement. Auto layout routes the finished
arrangement both ways, keeps the wires that score better, and records the
answer as `canvas.forkLate` so that everything drawing the file afterwards --
the canvas, the exporter, `validate` -- draws what the layout measured. A
drawing that gains nothing is written without the key, exactly as it would
have been before any of this existed.

A branch only leaves late when the shorter route is also a clean one: clear of
cell bodies, clear of other wires, and not across a pin some other wire stops
at, which would draw a junction dot claiming a connection the file does not
have. Otherwise that branch is routed from the driving pin as before.

---

## Design rule checks (DRCs)

A schematic can be correct and still unreadable. Two wires a hair apart read
as one thick line. A gate pressed against its neighbour reads as one part. A
name sitting on a wire is unreadable even though every coordinate is right.
Worst of all, two unrelated wires drawn on top of each other read as a short
that nothing in the file says is there.

Those are drafting conventions, and they live in one file,
`drawlogic/drc.py`: the distances at the top, and the checks that enforce them
below. Tuning how drawings look is editing that file; nothing else has to
change.

### The distances

| Limit | Default | What it decides |
|---|---|---|
| `WIRE_GAP` | 18 | how far apart two unrelated parallel wires must sit before they read as one line |
| `WIRE_TO_CELL` | 10 | how far a wire keeps from a block it does not connect to |
| `TOUCHING` | 0.5 | below this two wires have become one line; the router's last resort asks for this much and the DRCs call anything closer a short |
| `CORRIDOR_STEP` | 10 | how far apart the router tries successive corridors when its first choice is taken |
| `CORRIDOR_TRIES` | 18 | how many corridors either side before giving up |
| `WIRE_MIN_JOG` | 8 | the shortest step that reads as going round something rather than as a wobble |
| `ARROW_TO_JUNCTION` | 12 | how far a direction arrow keeps from a junction dot, since both are small solid marks in the same ink |
| `LABEL_CLEARANCE` | 5 | clear space demanded around a net name, so a label touching a wire counts as landing on it |
| `LABEL_HEADROOM` | 20 | room left above a cell for its instance name |
| `TEXT_TO_WIRE` | 6 | air an instance name needs from a wire |
| `TEXT_TO_CELL` | 6 | air an instance name needs from a neighbouring body |
| `TEXT_TO_TEXT` | 8 | air two names need from each other |
| `CELL_GAP_X` | 110 | room between one column of cells and the next, where the wires between them run |
| `CELL_GAP_Y` | 52 | room between two cells stacked in the same column |
| `CELL_MIN_GAP` | 24 | the least space allowed between any two cells, whichever way they sit |
| `PORT_STUB` | 26 | how far a wire runs straight out of an IO port before it may turn |
| `PORT_GAP` | 20 | the least space between two ports, which are smaller than gates and get their own rule |
| `PORT_TO_CELL` | 30 | how far a port keeps from a block, so it reads as the edge of the sheet rather than part of the block |
| `PORT_TO_WIRE` | 12 | how close a wire may pass a port it does not connect to |
| `HOP_GAP` | 16 | how far apart two crossing bridges must sit before they merge into one squiggle |
| `HOP_TO_CORNER` | 12 | how far a bridge keeps from a corner, since a deformed corner is a junction the reader stops trusting |
| `HOP_TO_CELL` | 8 | how far a bridge keeps from a body, which it would otherwise have nothing to be seen against |
| `HOP_TO_TEXT` | 6 | how far a bridge keeps from a name it would otherwise break up |
| `SHEET_MARGIN` | 90 | space left around everything when a layout decides where the drawing starts |
| `SHEET_EDGE` | 20 | the least clearance from the sheet edge before a printer's own margin eats into the drawing |
| `SHEET_W`, `SHEET_H` | 1200 x 780 | the sheet a new drawing gets |

Distances are in document units, the same units cells and wires use. A small
logic gate is 40x40, so a unit is roughly a twentieth of a gate.

The browser fetches these from `/api/drc` rather than restating them, the same
way it fetches the theme, so a drag on the canvas and a file from the exporter
obey the same DRCs. `routing.js` keeps a fallback copy for when it is loaded
on its own; `tests/test_js_parity.py` checks that copy still matches
`drc.py`, because a stale one would route the canvas differently from the file
it exports.

Changing a limit will move wires, which means the golden files move too. Look
at what changed before regenerating them -- see [Tests](#tests).

### The checks

`drc.check(doc, registry)` returns what failed, worst first. Each violation
names the rule, how bad it is, what it is about, the reason in words, and a
point to look at.

**Errors** are the drawing saying something untrue:

| Rule | What it catches |
|---|---|
| `wire-short` | two different nets drawn as one -- lying on top of each other, or one ending on the middle of the other where a junction dot is then drawn |
| `wire-crossing` | a crossing the renderer left unbridged, so it reads as a connection |
| `wire-over-cell` | a wire drawn across a body it does not connect to, which reads either as stopping there or as passing behind it |
| `cell-overlap` | two bodies in the same place |
| `off-sheet` | drawing outside the sheet, which the exporter crops away |

**Warnings** are the drawing being harder to read than it needs to be:

| Rule | What it catches |
|---|---|
| `wire-spacing` | parallel runs closer than `WIRE_GAP` |
| `wire-to-cell` | a wire passing close enough to a body to suggest a joint |
| `wire-jog` | a step shorter than `WIRE_MIN_JOG` |
| `cell-spacing` | two parts closer than `CELL_MIN_GAP` |
| `port-spacing`, `port-to-cell`, `port-to-wire` | the same questions for ports, at their own distances |
| `text-to-wire`, `text-to-cell`, `text-to-text` | an instance name against a wire, a body, or another name |
| `net-label` | a net name with nowhere clear to go, so it sits on something |
| `hop-spacing`, `hop-to-corner`, `hop-to-cell`, `hop-to-text` | crossing bridges against each other, the corners, the bodies and the text |
| `sheet-edge` | drawing inside a printer's own margin |

Each pair of things is reported once, at its tightest point, rather than once
per segment: one crowded wire is one line to read and one thing to fix.

Two nets that share a pin are one electrical node, so they are allowed to lie
on top of each other -- that is a rail, and the junction dots on it are the
point. The router relies on the same exemption.

---

## Checking a drawing

```bash
drawlogic validate alu_ctrl.dlg            # references and DRCs
drawlogic validate alu_ctrl.dlg --no-drc   # references only
```

Two kinds of problem come out of one command, because they are two halves of
one question -- is this drawing fit to hand to someone else.

**Reference faults.** Errors: unknown cell type, duplicate id, a net pointing
at a missing cell or a pin that does not exist, a bus width that disagrees
with the net name, a bus on a single-bit pin, a group member that does not
exist. Warnings: unconnected pins, a rotation that is not a multiple of 90, a
net name that is not a legal identifier.

**Rule failures**, from [the DRCs](#design-rule-checks-drcs). Each line names
the rule that found it, which is the heading to look up in `drc.py` where the
distance and the reason for it are written down.

Any error exits 1; warnings on their own exit 0.

### In the editor

The DRC pane under Properties lists what failed, red for errors and amber for
warnings. Click one and the view walks to it and rings the spot.

The editor sends what is on the canvas rather than the file on disk, so
unsaved edits are checked too. It runs the same two things `drawlogic
validate` runs -- the references and the DRCs -- so a drawing that passes in
one place passes in the other.

Both halves matter. Check used to run the geometric rules alone, so a drawing
naming a cell type that does not exist came back clean here and was rejected
on the command line a moment later. A reference fault lists with the rule
failures but has no marker on the sheet to walk to: an unknown cell type is
about the cell, not about a place.

### Live checking

The list keeps itself up to date while you draw. Move a cell, and about
four-tenths of a second after you stop, the drawing is checked and the
failures are ringed on the canvas -- a dashed red circle for an error, amber
for a warning. Click a line in the pane and its ring fills in.

That delay is the point. Checking on every mouse move would check forty
half-finished versions of a drag; checking only when you ask means you find
out about a short ten minutes after you drew it, when it is no longer obvious
which move caused it. Waiting for you to pause is the difference between the
two: one check per thing you did.

The count sits in two places, because the pane can be scrolled out of sight
and a warning nobody can see is not a warning. `3 / 1` in the DRC header is
errors and warnings; the same figure appears in the status bar at the bottom,
which is always on screen. Both grey out the instant you change something and
come back solid when the new answer arrives, so the number in front of you is
never a stale one presented as current.

**live** in the DRC header turns it off, and the choice is remembered. Off,
the pane goes back to whatever **Check** last found, and **Check** still works
exactly as before. A check that was already on its way back when you turned
live off is discarded rather than painted -- clearing the timer only stops the
next one, and an answer nobody asked for arriving in manual mode is exactly
what manual mode is supposed to prevent. Pressing **Check** always shows its
own answer.

It also turns itself off. A check that takes longer than a quarter of a second
would be felt as the editor hesitating under the cursor, so on the first one
that does, live mode stops and says so -- once, in the status bar, rather than
degrading quietly. Very large drawings are the case this is for; **live** puts
it back if you would rather have the lag. A check that fails outright does the
same thing rather than filling the status bar with the same error at every
pause.

Only one check runs at a time. An edit that lands while one is in flight
re-arms the timer instead of being dropped, so the last thing you did before
stopping is always the thing that gets checked -- an earlier version dropped
it, which made the pane wrong in exactly the situation it is most likely to be
read. Answers that arrive for a drawing you have since changed are discarded
rather than displayed.

---

## Checking the files themselves

Everything above checks a drawing. This checks the program: are the files in
this folder all from the same version of it?

That sounds like a strange question until it has cost you an afternoon. A copy
taken file by file -- which is what people do when they cannot clone -- ends up
with Python from today and browser modules from last week, and the symptoms
look nothing like the cause: a canvas that never appears, empty icons,
**Check** answering "failed to fetch", shapes that turn black when you move
them. Every file reads correctly on its own. Nothing in the code can tell you,
because the code is not what is wrong.

`manifest.txt` at the top of the repository is a hash of every file that has
to be right, 28 of them:

```
<64 hex digits>  drawlogic/__init__.py
<64 hex digits>  drawlogic/web/js/main.js
```

Three ways to check a copy against it:

```bash
drawlogic doctor                    # part of what doctor already reports
python3 -m drawlogic doctor         # same, without the alias
```

```powershell
powershell -ExecutionPolicy Bypass -File verify.ps1
```

`verify.ps1` is for Windows, where the trouble usually is, and needs nothing
installed -- not even a working Python, which matters because a copy too
broken to run is exactly the copy you want to check. It reports `MISSING`,
`MISMATCH`, `EXTRA` or `UNREADABLE` per file, exits 0 when the copy is sound,
1 when it is not and 2 when it cannot find a manifest to read. It takes
`-Root` if you run it from somewhere else. Tested on PowerShell 7.4 and
written to the subset Windows PowerShell 5.1 also accepts.

`EXTRA` is worth as much as the other three. A file the manifest has never
heard of is usually left over from an older version, and Python will import it
in preference to nothing at all.

### The two reasons not to do this, and what answers them

An earlier version of this document said a manifest was deliberately absent,
for two reasons. Both were right. Neither is a reason to go without one; they
are the two things a manifest has to get past first.

**It fails on line endings.** Git rewrites them on checkout on Windows by
default, so a byte-for-byte manifest calls every file in a perfectly healthy
clone broken. This is not hypothetical -- the first one handed over did exactly
that, all 28 files "mismatched" and not one of them actually different. A
checker that cries wolf is worse than none, because the next real mismatch is
ignored along with the noise. So the hash is not of the bytes on disk: the text
is read as UTF-8, any byte order mark dropped, CRLF and lone CR folded to LF,
and *that* is hashed. `verify.ps1` does the same thing in the same order.
Whitespace inside a line still counts; only the invisible differences are
forgiven.

**It goes stale.** A manifest is only maintained until the first person who
forgets, after which it is a liar. So it is not maintained. It is generated:

```bash
drawlogic doctor --write-manifest
```

and `tests/test_manifest.py` fails the moment the committed one stops
describing the tree. Change a file in `drawlogic/` without regenerating, and
the suite goes red and tells you the command to run. Forgetting is not
available.

That test is also what lets `verify.ps1` be trusted without running it here:
the suite checks that every path it will parse matches the regular expression
the script parses with, that no path needs quoting or escaping, and that the
script still normalises the same way. The script itself was run against
PowerShell 7.4 on a clean tree, on a copy with every file rewritten CRLF and a
byte order mark added, and on trees with a changed file, a deleted file and a
leftover file.

---

## How it is put together

```
drawlogic/
  geometry.py     affine transforms; pins and shapes share one matrix
  symbols.py      symbol registry, pin resolution
  symbols.json    the cell library -- add entries here, not code
  doc.py          .dlg load, save, normalise, validate, bus names
  drc.py          the DRC limits and the checks that enforce them
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
  js/             node-side runners: the editor checks, and dumps of what
                  routing.js and render.js produce for parity to compare
examples/         worked schematics, including a CDC FIFO
manifest.txt      a hash of every file above; generated, never hand-edited
.github/          one CI workflow: the suite on the oldest supported Python
sample.txt        a plain file to edit when trying verify.ps1 out by hand
verify.ps1        checks a copy against it on Windows, without Python
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

339 tests, in fourteen parts:

| File | Covers |
|---|---|
| `tests/test_model.py` | document format, symbol library, bus naming |
| `tests/test_draw.py` | routing and SVG rendering |
| `tests/test_drc.py` | every DRC, and what each one is supposed to miss |
| `tests/test_server.py` | HTTP endpoints, path-traversal refusal |
| `tests/test_cli.py` | the commands, including validate and doctor |
| `tests/test_regression.py` | golden files and whole-library invariants |
| `tests/test_js_parity.py` | routing.js against routing.py, net for net |
| `tests/test_js_editor.py` | drag-time alignment and Tidy |
| `tests/test_sheets.py` | hierarchy: derived pins, loops, broken references |
| `tests/test_layout.py` | auto layout: flow, overlap, settling, ordering choice |
| `tests/test_nets.py` | one driver and many loads, and the v1 upgrade |
| `tests/test_authoring.py` | turning a drawing into a symbol |
| `tests/test_manifest.py` | `manifest.txt` still describes the files here |
| `tests/test_python_floor.py` | the code stays inside the oldest Python supported |

Two of these are worth knowing about because of what they guard rather than
what they test. `tests.test_drc.TestEveryCheckerIsReachable` replaces each
checker with a no-op in turn and fails if the rest of the file stays green --
a rule nothing depends on is a rule that can be deleted in silence, and one
already had been. `tests.test_js_parity.TestWhatEachRendererActuallyDraws`
calls both renderers rather than their helpers, because a comparison that
recomputes its own inputs can only show that two copies agree.

They need nothing installed: no network, no browser, no third-party package.
That is a property worth keeping, and it is the
reason one or two things are checked by hand instead -- REVIEW.md, section 6,
says which and why.

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
  model supports it; `validate` is where it would grow. The DRCs check how a
  drawing reads, which is a different question from whether the circuit is
  right: a drawing can pass every rule here and still drive two outputs onto
  one net.
- **Automatic fixing.** The DRCs say what is wrong and where; moving the cell
  or rerouting the wire is still yours to do. The router avoids what it can
  see, but a drawing with no room left needs more room, not a cleverer router.
- **Sheet border and title block.** Today there is just a title name at the
  bottom left.
- **PDF export.** Out of scope; print to PDF from the browser.
