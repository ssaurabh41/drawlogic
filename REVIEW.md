# Reviewing drawlogic

A guide for an independent team asked to review and verify this tool. It is
written to be used by a person or by an automated reviewer, and it assumes no
prior contact with the project or its author.

It tries to be useful rather than flattering. Where something is untested,
uncertain or likely to be wrong, this document says so and points at it.

**What the tool is.** A schematic editor and renderer for logic circuits.
Gates, flops, muxes, blocks and ports are placed on a sheet and wired **pin to
pin**, so moving a cell carries its wires. Drawings are plain JSON. Output is
SVG. It runs on Python 3.8+ with nothing installed -- no pip packages, no
Node, no network.

**Size.** About 4,700 lines of Python across 14 modules, 4,400 lines of
JavaScript across 11 browser modules, 224 tests, 33 built-in symbols, 7 worked
examples.

---

## 1. Get it running

Five minutes, no install:

```bash
git clone <this repo> drawlogic && cd drawlogic
python3 -m unittest discover            # expect: Ran 224 tests ... OK
python3 -m drawlogic export examples/soc_top.dlg -o /tmp/soc.svg
python3 -m drawlogic serve examples/dff_slice.dlg   # editor on 127.0.0.1:8080
```

`serve` takes the drawing to open; `--dir DIR` chooses the folder it serves
when that is not the drawing's own. `python3 -m drawlogic help` lists every
subcommand and `help <command>` details one. If you would rather type
`drawlogic`, `export PYTHONPATH=$PWD` and `alias drawlogic='python3 -m drawlogic'`.

The server binds loopback and serves exactly one folder. If you are reviewing
on a remote machine, tunnel (`ssh -L 8080:localhost:8080 host`) rather than
passing `--host` -- see section 6 for what that flag gives up.

---

## 2. Verify the claims

Each row is a claim the documentation makes, and the cheapest way to check it
independently. Treat a claim with no check as unverified.

| Claim | Check it | Expected |
|---|---|---|
| Runs on a bare machine | `python3 -m unittest discover` in a container with no pip cache | 224 pass; nothing is downloaded |
| Wires follow their cells | open an example, drag a gate, watch the wires | paths re-route, stay attached |
| One place to tune the drawing | change `WIRE_GAP` in `drawlogic/rules.py`, re-export | every wire spacing moves; no other file edited |
| Canvas and exporter obey one rule set | `python3 -m unittest tests.test_js_parity` | 5 tests, incl. that `routing.js`'s fallback rules still match `rules.py` |
| Wires store pins, not coordinates | open `examples/dff_slice.dlg`, read `nets[0].from` and `nets[0].to` | endpoints name `cell` and `pin`; no x/y anywhere |
| One renderer for every export | `tests/test_server.py::test_export_writes_svg_through_the_python_renderer` | browser export goes through Python, not a canvas screenshot |
| The browser and Python route identically | `python3 -m unittest tests.test_js_parity` (needs node) | 4 tests pass -- but read section 4, this is narrower than it sounds |
| Adding a symbol needs no code | add an entry to a `symbols.json`, run `symbols list` | new id appears; no `.py` touched |
| Symbols are shared, not drifting | `tests/test_server.py::test_symbols_match_the_python_registry` | the browser is served the same library the CLI uses |
| The server refuses paths outside its root | `python3 -m unittest tests.test_server` | 5 tests on the path helper (incl. a prefix-match case) plus 2 end-to-end refusals |
| Drawings diff as text | `python3 -m drawlogic info examples/soc_top.dlg`, then edit and re-save | stable key order; diffs read as "moved U1" |
| Format v1 files still load | `python3 -m unittest tests.test_nets` | upgrade path tested, including that it is idempotent |

Warnings are expected, not a defect: `validate` reports unconnected pins, and
every example has a few (`soc_top.dlg` has 2). Errors are the thing to care
about; all seven examples have zero.

---

## 3. Convince yourself the tests are not lying

A suite that passes proves nothing until you know it can fail. Please run
these -- they are the checks that matter most, and they are quick.

**Break something and confirm the suite notices.** Pick any of these, run the
suite, then revert:

```bash
# routing: nudge a corner
sed -i 's/HOP_RADIUS = 5.0/HOP_RADIUS = 6.0/' drawlogic/theme.py

# layout: break the pin-alignment pass
#   in drawlogic/layout.py, make _place() ignore its chosen driver

# rendering: shift where labels go
sed -i 's/LABEL_CHAR = 0.62/LABEL_CHAR = 0.70/' drawlogic/render_svg.py
```

Each should turn the suite red. If one does not, that is a finding worth
reporting -- it means the behaviour is unowned.

**The golden files can be regenerated, which is exactly how a regression
suite goes vacuous.** `tests/test_regression.py` compares rendered SVG against
committed goldens in `tests/golden/` (7 files), and
`DRAWLOGIC_REGOLD=1 python3 -m unittest tests.test_regression` rewrites them.
Two things to confirm:

1. `git status` is clean after a normal run -- the goldens in git match what
   the code produces today.
2. Nothing in any CI config sets `DRAWLOGIC_REGOLD`. A pipeline that
   regenerates its own reference files checks nothing.

**Seven tests skip silently without Node, and the run still says OK.** This is
the sharpest edge in the suite. On a machine without `node`:

```
Ran 224 tests ... OK (skipped=7)
```

Those 7 are the entire cross-language safety net: 4 parity tests comparing
the two routers, 1 anchoring arrow direction to the drawing rather than to
agreement, 1 checking that `routing.js`'s fallback design rules still match
`rules.py`, and 1 wrapper around 55 editor checks. A reviewer on a Node-less
machine sees a green run
with the most important tests absent. Confirm your environment has Node
(`node --version`) before trusting a pass.

**The vacuity guards now in place**, for reference: the editor runner counts
its own checks and prints a completion record the wrapper validates, so
deleting assertions fails rather than passing quietly. It used to accept any
zero-exit run containing one "ok" line -- a cold review found that gutting
the runner to a single console.log kept the suite green. The older wording
below describes that weaker guard, which is what a script that
silently did nothing fails rather than passes.

---

## 4. The architecture, and the four decisions worth arguing with

```
drawlogic/
  geometry.py     affine transforms; pins and shapes share one matrix
  symbols.py      symbol registry, pin resolution
  symbols.json    the cell library -- data, not code
  doc.py          .dlg load, save, normalise, validate, bus names
  layout.py       arranging a drawing from what it is wired to
  routing.py      orthogonal routing, corridors, junction dots
  sheets.py       hierarchy: a block built from another drawing's ports
  authoring.py    turning a drawing of shapes and ports into a symbol
  render_svg.py   the only path from document to SVG
  theme.py        colours, line weights, font stacks
  cli.py / server.py
  web/js/         the browser editor, 11 ES modules, no build step
```

**(a) Symbols are data.** Every cell type is a JSON entry naming its outline
and pins. Adding a gate changes no Python and no JavaScript, and both
renderers read the same file. *Argue with it:* the format is undocumented as a
schema -- there is no validator for a hand-written symbol beyond what
`Symbol()` rejects at load. A malformed entry fails late.

**(b) One renderer for every exported file.** The editor's Export and Copy
PNG post the document to Python and render there; the canvas is never
screenshotted. This is why an exported file matches the CLI byte for byte.
*Argue with it:* it makes export a round trip, and it means the canvas you
look at and the file you ship are produced by two different code paths that
only agree because of (c).

**(c) `routing.js` and `render.js` are hand ports of `routing.py` and
`render_svg.py`.** Routing must run during a drag, so it cannot be a server
call; rendering must match the exporter, so it cannot diverge. Two
implementations of the same algorithm, kept honest by `tests/test_js_parity.py`.

*This is the single largest structural risk in the project, and the parity
suite is narrower than its name suggests.* It compares four things across all
7 examples: route geometry, junction dots and crossing bridges, label
positions, and arrow positions. **It does not diff the rendered SVG.** Two
implementations could agree on every one of those and still paint differently
-- colours, stroke weights, text, symbol artwork, z-order. If you review one
thing in this codebase, review whether that gap matters.

**(d) Auto layout runs in Python, called over HTTP.** A layout is not a
gesture, so the round trip is free and one implementation suffices -- unlike
routing. *Argue with it:* it makes the editor's most visible command depend on
the server being reachable, in a tool that otherwise degrades gracefully.

---

## 5. Where the bugs will be

Ranked by where I would look first, with reasoning rather than a flat list.

1. **`routing.py` (694 lines) and its JS twin.** The most geometry per line in
   the project: corridor reservation, branch overlap near a driver, junction
   detection, crossing bridges. Edge cases to try: two loads whose branches
   overlap for most of their length; a wire that must leave a pin facing into
   the cell it came from; nets on a sheet too small for a corridor.

2. **The v1 -> v2 net upgrade (`doc.py`).** v1 had one driver and one load;
   v2 has one driver and many, each with its own waypoints. The upgrade merges
   v1 nets that share a driver pin, but only when their names agree. It is
   tested for idempotency (running it twice equals running it once -- a real
   bug that was caught this way), but the merge rule is a judgement call:
   two same-driver nets with *different* names stay separate. Decide whether
   that is right.

3. **`layout.py` pin alignment.** It chooses one driver per cell to align on
   rather than averaging, on the theory that one dead-straight wire beats two
   half-straight ones. Three bugs were found here during development, all of
   the same shape: a coordinate computed correctly then clamped or re-keyed
   somewhere downstream. Look at `_place`, `_stack`, `_normalise`.

4. **`authoring.py` pin snapping.** A port snaps to the edge it is furthest
   *outside* of, not the nearest edge -- because a port to the left of a tall
   block is geometrically nearer the top. Fallback to nearest edge only when
   the port is inside the body. Try pathological placements: a port at a
   corner, two ports on the same edge at the same spot, a port dead centre.

5. **The two-ordering choice in `layout.py`.** Auto layout runs the whole
   place-and-route twice and keeps the better result. Worth checking: that
   the losing attempt leaves nothing behind in the document, that the score
   is stable rather than flipping between runs, and that a drawing where both
   orderings tie comes out the same every time.

6. **Label placement (`render_svg.py`).** A scoring function with seven
   weighted terms (off-sheet, cell overlap, wire overlap, label overlap,
   vertical, far side, distance from midpoint). Hand-tuned constants. It will
   have inputs where it picks a poor spot; the question is whether it ever
   picks an *illegible* one.

---

## 6. What is not covered

Stated plainly so nobody assumes more than exists.

**~3,400 lines of browser JavaScript have no automated tests.** Parity covers
`routing.js` and `render.js` (1,251 of 4,686 lines). The remaining modules -- `main.js`,
`tools.js`, `model.js`, `selection.js`, `panels.js`, `viewport.js`,
`picture.js` -- are exercised by 55 Node checks (drag alignment, Tidy, net
building) and otherwise verified by hand in a headless browser. Selection,
resize handles, undo/redo, clipboard, grouping, rotation and the properties
panel have no standing test. **This is the biggest hole in the project.**

The deliberate reason is that adding a JS toolchain would cost the
zero-dependency property that makes this installable on a locked-down machine.
Whether that trade is correct is a fair thing to challenge; if you think it is
wrong, the counter-proposal to make is a test runner that is itself
dependency-free.

**No visual regression testing beyond 7 golden SVGs.** A schematic's real
output is a picture. The goldens catch a changed byte, not an ugly drawing. If
routing produces a technically-correct path that a hardware engineer would
call unreadable, nothing here fails. **Please look at the output with your own
eyes** -- render all seven examples and judge them as schematics, not as
strings.

**`--host` widens the server beyond loopback and there is no authentication of
any kind.** It is documented as "tunnel instead", but the flag exists and
nothing stops it being used on a shared machine. If this ever runs anywhere
but a workstation, that is a finding.

**Not built:** netlist export (Verilog, SPICE), electrical rule checks, sheet
border and title block, multiple sheets in one file. PDF is out of scope --
print to PDF from the browser.

**Auto layout is measured, not merely asserted.** It lays each drawing out two
ways and keeps whichever scores better on crossings and wire length
(`layout._score`). Across the seven examples that is 118 crossings against 129
for the previous single-pass version. The score is two numbers and one
weighting constant, `CROSSING_COST`, set by judgement rather than experiment;
whether a crossing really is worth about a gate's width of wire is a fair
thing to challenge.

**A known inconsistency:** `export` accepts many files (`export *.dlg
--outdir svg/`) but `validate` takes exactly one and errors on a glob.
Validating a folder is the more natural batch operation of the two, so the
asymmetry is backwards.

---

## 7. Fitness for purpose

Automated checks will not answer the question that matters: can somebody who
is not the author draw a real schematic with this? Please spend thirty minutes
doing that, from a cold start, and record where you got stuck.

Suggested exercise -- draw a 4-bit register file slice:

1. `python3 -m drawlogic serve .` and place a flop, a mux and two ports.
2. Wire them (`W`, then click two pins). Bend a wire by dragging a run.
3. Rename a net to `d[3:0]` and check the bus is validated as 4 bits.
4. Use Arrange > Auto layout. Judge the result: is it better than what you
   had, or did it destroy your intent?
5. Draw a custom symbol -- shapes plus ports, then Save as symbol -- and
   place it on a second drawing.
6. Export, and open the SVG in something that is not a browser.

Things to note as you go: what you reached for and did not find; where the
keyboard shortcut was not what your hands expected; whether the properties
panel told you what you needed; whether anything was lost when you saved.
Saving is manual and there is no autosave -- notice whether that bit you.

The manual is [DOCUMENTATION.md](DOCUMENTATION.md) -- the only user-facing
document, there is deliberately no README. Every module also
opens with a usage section explaining how to call it and why it works the way
it does.

---

## 8. What a first cold review already found

A pass of this kind has been run once, by a different model reading the code
cold. It produced eleven demonstrated defects and two suspected ones, and all
eleven reproduced. They are fixed; the point of listing them here is that they
say what kind of thing this codebase gets wrong, which is a better guide to
where to look than any assurance in this document.

Four were bugs of the same shape: **something was written down as a rule and
never enforced.** `CELL_MIN_GAP` was documented, served over the API and read
by nothing. The CLI's export flags overrode the document they were exporting.
The served-folder boundary held for the path the server was asked to open and
not for the references inside it. Group validation accepted cells and called
every grouped shape a missing member.

Three were **stale state**: a save that marked a file clean while the newer
edit was still in the browser, a layout answer applied to whichever drawing
happened to be open when it returned, and a New command that decided whether
a file existed by matching strings against its own dropdown.

Two were **tests that could not fail**: the arrow parity check threw away the
direction vector on both sides, and the editor wrapper accepted any run that
printed one "ok" line.

Two were **inputs nobody typed**: a malformed request body crashed the
connection instead of answering, and concurrent symbol saves lost all but one
of them -- filed as unconfirmed by that review, and in fact reproducible every
run, losing 58 of 60.

Worth knowing when reading the rest of this document: several of the things it
asserted were measured wrong. The test count was stale, the skip count was
stale, and the untested-JavaScript figure was out of date. They are re-measured
now, but the lesson stands -- check the numbers here against the code rather
than quoting them.

---

## 9. Reporting back

Most useful to least:

1. **A failing test.** A case that should pass and does not, as a test we can
   add, beats any description.
2. **A drawing that renders wrong**, attached as the `.dlg` plus the SVG it
   produced, saying what you expected instead.
3. **A design objection** -- especially on the four decisions in section 4.
   Say what breaks and roughly when, not only that you would have done it
   differently.
4. **Friction from section 7**, in your own words. "I could not work out how
   to X" is a real finding and does not need a repro.

For anything security-relevant (the `--host` flag, path handling in the
server, the data-URI embedding in custom cells), please report privately
rather than in a public issue.
