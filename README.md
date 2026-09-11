# drawlogic

Draw logic circuit schematics and export them as SVG.

Gates, flip-flops, muxes, clock gates, transistors, blocks and ports, wired
**pin to pin** so that moving a gate carries its wires with it -- the thing
PowerPoint cannot do. Drawings are plain JSON, so they diff and review like
code.

**[Full manual: DOCUMENTATION.md](DOCUMENTATION.md)** -- every command, every
field, every key.

Status: feature complete for the plan. Format, symbol library, renderer and
command line all work; the browser editor places, selects, moves, resizes,
styles, groups, arranges and wires cells, draws autoshapes and text, and
embeds custom cell pictures.

## Requirements

Python 3.8 or newer. Nothing else -- no pip packages, no Node, no network.

## Getting started

```bash
git clone <repo-url> drawlogic
cd drawlogic
python3 -m drawlogic help
```

To type `drawlogic` rather than `python3 -m drawlogic`, without installing:

```bash
export PYTHONPATH=$PWD:$PYTHONPATH
alias drawlogic='python3 -m drawlogic'
```

With pip available, `pip install -e .` gives the same short command.

## The editor

```bash
drawlogic serve examples/dff_slice.dlg
```

Binds to loopback and serves exactly one folder, so nothing outside the
directory you point it at is reachable. **If the machine is remote**, tunnel
rather than opening it up with `--host`:

```bash
ssh -L 8080:localhost:8080 you@workstation
```

Click a symbol in the palette, then click the canvas. Press `W` and click two
pins to wire them. Drag a wire to bend it.

| | |
|---|---|
| `V` `W` | select, wire |
| `L` `B` `P` `T` | line, box, polygon, text |
| drag, `Ctrl`+drag | move (grid-snapped), duplicate as you drag |
| handles, `Alt`+handle | resize, ratio locked / free |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo |
| `Ctrl+C` `Ctrl+X` `Ctrl+V` `Ctrl+D` | copy, cut, paste, duplicate |
| `Ctrl+G` / `Ctrl+Shift+G` | group / ungroup |
| `Ctrl+R` / `Ctrl+H` | rotate / flip |
| `Ctrl+]` / `Ctrl+[` | bring to front / send to back |
| `Ctrl+S` `Ctrl+E` `Ctrl+0` | save, export, fit |

The full key list, including the Arrange menu, is in the
[manual](DOCUMENTATION.md#the-editor).

Saving is manual and nothing else writes to disk. The one automatic behaviour
is the browser refusing to close a tab with unsaved changes.

## Command line

```bash
drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --zoom 2
drawlogic export *.dlg --outdir svg/
drawlogic export alu_ctrl.dlg -o -        # SVG to stdout

drawlogic validate alu_ctrl.dlg           # exits non-zero on errors
drawlogic info alu_ctrl.dlg
drawlogic symbols list
drawlogic symbols preview and2 -o and2.svg

drawlogic help export                     # detail for any command
```

`--zoom` scales only the SVG `width` and `height`; geometry stays in the
`viewBox`, so output is vector-perfect at any size. It is the same mechanism
the editor's zoom control uses.

## Two things worth knowing up front

**Symbols are data, not code.** Every cell type is an entry in
`drawlogic/symbols.json` naming its outline and its pins. Adding a gate, flop
or custom cell means adding one entry and changing no Python and no
JavaScript. Both renderers read that file, which is what stops them drifting
apart. Point `--symbols-dir` at your own file or folder to add cells without
touching the built-ins.

**Wires store pin references, not coordinates.** A net records
`u1.y -> ff1.d`, and the path is re-routed from the pins on every draw. That
is what keeps wires attached when a gate moves, and what lets `validate` catch
a pin that only *looks* connected.

## Layout

```
drawlogic/
  geometry.py     affine transforms; pins and shapes share one matrix
  symbols.py      symbol registry, pin resolution
  symbols.json    the cell library
  doc.py          .dlg load, save, normalise, validate, bus names
  routing.py      orthogonal routing, corridors, junction dots
  render_svg.py   the only path from document to SVG
  theme.py        colours, line weights, font stacks
  cli.py          serve, export, symbols, info, validate, help
  server.py       stdlib HTTP server for the editor
  web/            the browser editor (9 modules, no build step)
tests/            unittest, no dependencies
examples/         a worked schematic
```

Every module opens with a usage section showing how to call it.

## Tests

```bash
python3 -m unittest discover
```

The Python side is unit tested. The JavaScript is exercised by hand through a
headless browser, because adding a JS toolchain would cost the
zero-dependency property that makes this installable on a locked-down
machine -- see the [manual](DOCUMENTATION.md#tests) for the reasoning.

## Not built yet

Hierarchy (the `ref` field is reserved), netlist export and electrical rule
checks, a sheet border and title block. PDF export is out of scope; print to
PDF from the browser.
