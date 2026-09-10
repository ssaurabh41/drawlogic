# drawlogic

Draw logic circuit schematics and export them as SVG.

Gates, flip-flops, muxes, clock gates, transistors, blocks and ports, wired
**pin to pin** so that moving a gate carries its wires with it -- the thing
PowerPoint cannot do. Drawings are plain JSON, so they diff and review like
code.

Status: **Phase 2**. The document format, symbol library, renderer and command
line all work, and the browser editor opens, draws and exports a drawing with
live zoom, text-size and symbol-size controls. Placing and wiring cells by
hand is the next phase.

## Requirements

Python 3.8 or newer. Nothing else -- no pip packages, no Node, no network.

## Getting started

```bash
git clone <repo-url> drawlogic
cd drawlogic
python3 -m drawlogic --version
```

To type `drawlogic` instead of `python3 -m drawlogic`, without installing
anything:

```bash
export PYTHONPATH=$PWD:$PYTHONPATH
alias drawlogic='python3 -m drawlogic'
```

If pip is available, `pip install -e .` gives you the same short command.

## The browser editor

```bash
drawlogic serve                          # serves . on http://127.0.0.1:8080
drawlogic serve examples/dff_slice.dlg   # open one drawing straight away
drawlogic serve --dir ~/schematics --port 9000
drawlogic serve --no-browser
```

The server binds to loopback and serves exactly one folder, so nothing outside
the directory you point it at is reachable. **If the machine is remote**,
tunnel rather than opening it up with `--host`:

```bash
ssh -L 8080:localhost:8080 you@workstation
```

In the editor: scroll to zoom, shift-drag or hold Space to pan, `Ctrl+0` to
fit. The **Zoom**, **Text** and **Symbols** sliders control view scale,
`canvas.font.scale` and `canvas.symbolScale` respectively; the last two change
the document, so they mark it unsaved.

`Ctrl+S` saves, `Ctrl+E` exports. Saving is manual and nothing else writes to
disk -- the one automatic behaviour is the browser refusing to close a tab
with unsaved changes. Export is rendered by Python, the same code path the CLI
uses, so a file exported from the browser is byte-for-byte what
`drawlogic export` would produce.

## Exporting

```bash
drawlogic export examples/dff_slice.dlg -o slice.svg
drawlogic export examples/dff_slice.dlg -o slice.svg --zoom 2.0
drawlogic export examples/dff_slice.dlg -o slice.svg --width 1600
drawlogic export examples/dff_slice.dlg -o slice.svg --crop --margin 20
drawlogic export examples/dff_slice.dlg -o slice.svg --bg transparent --grid
drawlogic export examples/dff_slice.dlg -o -            # SVG to stdout
```

`--zoom` scales only the SVG `width` and `height`; the geometry stays in the
`viewBox` and never changes. So `--zoom 2` produces a file that lands twice as
large with no loss of quality, and it is the same mechanism the editor's zoom
control will use. `--width` is the same idea as an absolute pixel target.

Batch work is ordinary shell:

```bash
drawlogic export *.dlg --outdir svg/
for f in blocks/*.dlg; do drawlogic export "$f" -o "${f%.dlg}.svg" --zoom 1.5; done
```

## Inspecting and checking

```bash
drawlogic info examples/dff_slice.dlg      # counts, canvas, bounding box
drawlogic validate examples/dff_slice.dlg  # schema errors, unconnected pins
```

`validate` exits non-zero when it finds errors, so it drops straight into a
pre-commit hook or CI job.

## The symbol library

```bash
drawlogic symbols list
drawlogic symbols list --category gates
drawlogic symbols show and2
drawlogic symbols preview and2 -o and2.svg
```

Symbols are **data, not code**. Each cell type is a JSON entry naming its
outline and its pins:

```json
{
  "and2": {
    "name": "2-input AND",
    "category": "gates",
    "size": [60, 40],
    "pins": [
      {"name": "a", "x": 0,  "y": 10, "dir": "in"},
      {"name": "b", "x": 0,  "y": 30, "dir": "in"},
      {"name": "y", "x": 60, "y": 20, "dir": "out"}
    ],
    "draw": [
      {"op": "path", "d": "M10 0 H30 A20 20 0 0 1 30 40 H10 Z", "role": "body"}
    ]
  }
}
```

Adding a gate, a flop or a custom cell means adding one entry to a file in
`drawlogic/symbols/` and changing no code at all. Point `--symbols-dir` at
your own directory to add cells without touching the built-in set; an entry
there with the same id overrides the built-in one.

### Setting default sizes

There are two levels, depending on whether you want to change one cell type
or all of them.

**Per type**, `size` in the symbol JSON is that cell's default. A 2-input
gate is 60x40, a flop 70x60, a port 44x16. To change a default without
editing the built-ins, copy the entry into your own `--symbols-dir` and give
it a different `size`.

**Per drawing**, `canvas.symbolScale` multiplies every cell at once:

```json
"canvas": { "symbolScale": 1.5 }
```

Each cell grows about its own centre, so turning the whole drawing up does
not drag the layout sideways, and wires stay attached because they are
re-resolved from the moved pins. Individual cells keep their own `w` and `h`
for one-off resizing.

Draw ops are `path`, `line`, `rect`, `circle`, `polygon` and `text`. A `role`
of `body`, `pin`, `bubble`, `decor`, `ghost` or `pin_label` decides how it is
painted, so restyling the whole library is a change to `theme.py`.

## The .dlg file

One JSON file per drawing, pretty-printed with a stable key order so
`git diff` reads as "moved U1, added net en" rather than one unreadable line.

```json
{
  "format": "drawlogic",
  "version": 1,
  "title": "dff_slice",
  "canvas": {
    "width": 900, "height": 560, "background": "#ffffff",
    "grid": {"style": "dots", "size": 10, "color": "#b9c7cc"},
    "font": {"family": "IBM Plex Sans", "scale": 1.0},
    "symbolScale": 1.0
  },
  "cells": [
    {"id": "u1", "type": "and2", "x": 220, "y": 120, "w": 60, "h": 40,
     "rotate": 0, "mirror": false, "label": "U1", "style": {}}
  ],
  "nets": [
    {"id": "n3", "name": "en", "width": 1,
     "from": {"cell": "u1", "pin": "y"},
     "to":   {"cell": "ff1", "pin": "d"},
     "waypoints": [], "style": {}}
  ],
  "shapes": [],
  "groups": []
}
```

A net stores `u1.y -> ff1.d`, never coordinates. Wire paths are recomputed
from the pins every time anything is drawn, which is what keeps wires
attached when a gate moves and lets `validate` catch a pin that only *looks*
connected.

Bus width lives in the name: `d[7:0]` is eight bits, and `validate` complains
if the declared width disagrees. Buses are drawn with the same line weight as
a single bit -- the name carries the width, not the stroke.

Grid styles are `blank`, `dots`, `dots-wide`, `lines` and `lines-heavy`. The
grid is a drawing aid and stays out of exported SVG unless you pass `--grid`.

## Layout

```
drawlogic/
  geometry.py     affine transforms; pins and shapes share one matrix
  symbols.py      symbol registry, pin resolution
  symbols/*.json  the cell library -- add files here, not code
  doc.py          .dlg load, save, normalise, validate
  buses.py        bus name parsing and width rules
  routing.py      orthogonal wire routing, corridors, junction dots
  render_svg.py   the only path from document to SVG
  theme.py        colours, line weights, font stacks
  cli.py          serve, export, symbols, info, validate
  server.py       stdlib HTTP server for the editor
  web/            the browser editor
    js/geometry.js  affine transforms, ported from geometry.py
    js/routing.js   wire routing, ported from routing.py
    js/symbols.js   symbol placement and pin resolution
    js/render.js    document to live SVG DOM
    js/viewport.js  pan and zoom
    js/main.js      bootstrap and controls
tests/            unittest, no dependencies
examples/         a worked schematic
```

Each concern sits in one file, so adding a feature touches one or two of
them.

## Tests

```bash
python3 -m unittest discover
```

## Design notes

**One renderer for every exported file.** When the browser editor arrives,
its Export will hand the document to `render_svg.py` rather than
screenshotting the canvas, so what you export from the GUI and what you
export from the terminal are the same bytes.

**Text stays upright and a fixed size.** Enlarging or rotating a gate does
not stretch its pin names, and stroke weight is divided back out of the
cell's own scaling, so a big gate keeps normal line weight instead of
turning bold.

**IBM Plex, with a real fallback.** Exported SVG asks for IBM Plex Sans and
falls back to Arial and Helvetica, so a drawing opened on a machine without
Plex still lays out sensibly.

## Not built yet

Editing, from Phase 3 on: placing cells from the palette, selection and resize
handles, the properties panel, drawing wires, undo/redo, copy/paste and
ctrl-drag duplicate, group and ungroup, alignment tools, autoshapes and text
boxes, and embedded custom cell images.

Two duplicated modules are worth knowing about. `web/js/geometry.js` and
`web/js/routing.js` are ports of their Python counterparts, because the canvas
has to route a wire while you drag a gate and cannot wait on the server. They
are covered by tests on the Python side and kept honest by the fact that both
read the same symbol data and the same theme, which the server sends rather
than the browser restating.
