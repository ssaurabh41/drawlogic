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

**Size.** About 6,400 lines of Python across 14 modules, 5,250 lines of
JavaScript across 11 browser modules, 312 tests, 33 built-in symbols, 7 worked
examples.

---

## 1. Get it running

Five minutes, no install:

```bash
git clone <this repo> drawlogic && cd drawlogic
python3 -m unittest discover            # expect: Ran 312 tests ... OK
python3 -m drawlogic doctor             # expect: this copy is consistent with itself
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

`doctor` is the second line above because a copy assembled file by file is the
single most common way this has broken for a real user, and its symptoms
(blank canvas, empty icons, `Check` answering "failed to fetch") look like
product bugs rather than a bad copy. It exercises Python end to end, checks
every browser import resolves, and hashes all 28 files against `manifest.txt`.
On Windows, `verify.ps1` does the manifest half without needing Python to run
at all. If either reports a mismatch, stop and re-take the repository whole --
nothing found after that point is trustworthy.

---

## 2. Verify the claims

Each row is a claim the documentation makes, and the cheapest way to check it
independently. Treat a claim with no check as unverified.

| Claim | Check it | Expected |
|---|---|---|
| Runs on a bare machine | `python3 -m unittest discover` in a container with no pip cache | 312 pass; nothing is downloaded |
| Wires follow their cells | open an example, drag a gate, watch the wires | paths re-route, stay attached |
| One place to tune the drawing | change `WIRE_GAP` in `drawlogic/drc.py`, re-export | every wire spacing moves; no other file edited |
| Canvas and exporter obey one rule set | `python3 -m unittest tests.test_js_parity` | 6 tests, incl. that `routing.js`'s fallback limits still match `drc.py` |
| Wires store pins, not coordinates | open `examples/dff_slice.dlg`, read `nets[0].from` and `nets[0].to` | endpoints name `cell` and `pin`; no x/y anywhere |
| One renderer for every export | `tests/test_server.py::test_export_writes_svg_through_the_python_renderer` | browser export goes through Python, not a canvas screenshot |
| The browser and Python route identically | `python3 -m unittest tests.test_js_parity` (needs node) | 6 tests pass -- but read section 4, this is narrower than it sounds |
| Adding a symbol needs no code | add an entry to a `symbols.json`, run `symbols list` | new id appears; no `.py` touched |
| Symbols are shared, not drifting | `tests/test_server.py::test_symbols_match_the_python_registry` | the browser is served the same library the CLI uses |
| The server refuses paths outside its root | `python3 -m unittest tests.test_server` | 5 tests on the path helper (incl. a prefix-match case) plus 2 end-to-end refusals |
| Drawings diff as text | `python3 -m drawlogic info examples/soc_top.dlg`, then edit and re-save | stable key order; diffs read as "moved U1" |
| Format v1 files still load | `python3 -m unittest tests.test_nets` | upgrade path tested, including that it is idempotent |
| The DRCs find a real fault | `python3 -m unittest tests.test_drc` | 34 tests; the first is the reported case -- two nets into one gate drawn as one wire |
| The DRCs are not vacuous | delete a `_check_*` call from `drc.check()`, re-run `tests.test_drc` | red, for every one of the nine |
| The DRCs do not cry wolf | `for f in examples/*.dlg; do drawlogic validate $f; done` | warnings, none of them errors; each one findable in the picture |
| Checking keeps up while you draw | serve an example, drag a gate onto another, stop | a ring appears within about half a second; the status-bar count matches the pane |
| The live count is never stale | drag something and watch the count during the drag | it greys out on the first move and only goes solid again with a fresh answer |
| This copy is the copy | `python3 -m drawlogic doctor`, or `verify.ps1` on Windows | 28 files against `manifest.txt`, 0 differ |
| The manifest cannot rot | append a blank line to any file under `drawlogic/`, `python3 -m unittest tests.test_manifest` | red, naming the command that regenerates it |

Warnings are expected, not a defect: `validate` reports unconnected pins, and
every example has a few (`soc_top.dlg` has 2). It also reports design rule
warnings -- wires closer than `WIRE_GAP`, names against bodies -- which are
judgements about spacing rather than faults. Errors are the thing to care
about; all seven examples have zero of both kinds.

The DRCs are worth a sceptical look in particular, because a checker that
fires on everything is as useless as one that fires on nothing. Every rule in
`tests/test_drc.py` is tested twice: once on a drawing built to break it, and
once on a drawing that does not, so a rule that always fires fails its second
test. The numbers themselves are judgements, not measurements -- `PORT_GAP`
started at 30 and came down to 20 after rendering `fifo_top.dlg` and looking
at a port stack 22 apart, which was perfectly readable. Read `drc.py`'s
comments as arguments to disagree with rather than as findings.

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
Ran 261 tests ... OK (skipped=7)
```

Those 7 are the entire cross-language safety net: 4 parity tests comparing
the two routers, 1 anchoring arrow direction to the drawing rather than to
agreement, 1 checking that `routing.js`'s fallback DRC limits still match
`drc.py`, and 1 wrapper around 55 editor checks. A reviewer on a Node-less
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

1. **`routing.py` (~720 lines) and its JS twin.** The most geometry per line
   in the project: corridor reservation, branch overlap near a driver,
   junction detection, crossing bridges. Edge cases to try: two loads whose
   branches overlap for most of their length; a wire that must leave a pin
   facing into the cell it came from; nets on a sheet too small for a
   corridor.

   The corridor search is a ladder of four passes, each giving up something
   the one before insisted on, ending in a pass that gives up everything and
   draws the wire where it wanted to go. Two of the four were added because a
   drawing with no room left came out claiming connections nobody made. Worth
   asking: does each pass actually bite, or is one of them unreachable? The
   DRCs are the measuring instrument -- build a crowded drawing, delete a
   pass, and see whether `wire-short` appears.

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

5. **The two-ordering choice in `layout.py`, and the refinement after it.**
   Auto layout runs the whole place-and-route twice, keeps the better result,
   then tries swapping neighbours within each column and keeps a swap when the
   score improves. Worth checking: that a losing attempt leaves nothing behind
   in the document, that the score is stable rather than flipping between
   runs, that a drawing where two arrangements tie comes out the same every
   time, and that the sweep loop really does stop early rather than always
   running to its ceiling. The refinement calls `_score` -- a full re-route --
   once per candidate swap, so a pathological drawing is where the Layout
   button gets slow.

6. **Label placement (`render_svg.py`).** A scoring function with seven
   weighted terms (off-sheet, cell overlap, wire overlap, label overlap,
   vertical, far side, distance from midpoint). Hand-tuned constants. It will
   have inputs where it picks a poor spot; the question is whether it ever
   picks an *illegible* one. The `net-label` DRC answers that question for a
   given drawing, which is a better test than reading the weights.

7. **`drc.py`'s limits.** Every number is a judgement about what the eye
   separates at normal zoom, and none of them is measured. Too strict and the
   checker buries a good drawing in warnings; too loose and it misses what a
   reader trips over. Run it over your own drawings and argue with the ones
   that fire. The checks themselves are the sounder half: they measure
   distances, and the distances are either right or not.

   The pair-level parts are worth reading closely: `same_node`, which exempts
   two nets that share a pin from the shorting rule, and `_pair_key`, which
   collapses several complaints about one pair into the worst of them. A bug
   in either would hide real faults rather than invent false ones, which is
   the failure that does not announce itself.

8. **Live DRC's scheduling, in `main.js`.** The checking itself is `drc.py`
   and is tested; what is new and untested is *when* it runs. Three pieces of
   state -- a debounce timer, a "one check at a time" flag, and a stamp of the
   document that was sent -- decide whether an answer is shown or thrown away.
   Every bug in that shape looks the same from outside: a count that is right
   for a drawing you no longer have.

   Specific things to try. Edit continuously for longer than a check takes,
   then stop: the last edit must be the one that gets checked. (It was not,
   in the first version -- an edit arriving mid-check was dropped rather than
   re-arming the timer, so the pane was stalest exactly when someone would
   read it.) Undo past the edit that caused a violation and confirm the ring
   goes with it. Change the drawing while a check is in flight and confirm the
   late answer is discarded rather than painted. Turn **live** off with
   failures showing, edit, and confirm nothing silently updates.

   The time budget is the other half: the feature switches itself off after a
   check that takes longer than 250ms, on the reasoning that a delay felt
   under the cursor is worse than not checking. That threshold is a guess, and
   the graceful-degradation path is the one a reviewer should try to make
   misbehave -- back-to-back slow checks, a check that throws, a check
   outstanding when the document is replaced wholesale by opening another
   file.

9. **`manifest.txt` and the two things that hash.** `cli.content_hash` and
   `verify.ps1` have to agree exactly, in two languages, and nothing fails
   loudly if they drift -- one side just starts calling good files bad. The
   agreement is: read as UTF-8, drop a byte order mark, fold CRLF and lone CR
   to LF, SHA-256 the result. `tests/test_manifest.py` checks the shapes
   around it (every path parses with the script's own regular expression, no
   path needs escaping, the script still names both replacements) but cannot
   run PowerShell, so the two implementations are checked by reading, not by
   execution. If you have Windows, the highest-value thing you can do in ten
   minutes is run `verify.ps1` on a fresh `git clone` and confirm it says all
   28 files are fine. A byte-for-byte version of this manifest reported every
   file in a healthy clone as broken; that is the failure mode to re-check,
   not a missed mismatch.

---

## 6. What is not covered

Stated plainly so nobody assumes more than exists.

**~3,900 lines of browser JavaScript have no automated tests.** Parity covers
`routing.js` and `render.js` (1,333 of 5,250 lines). The remaining modules --
`main.js`, `tools.js`, `model.js`, `selection.js`, `panels.js`, `viewport.js`,
`picture.js` -- are exercised by 58 Node checks (drag alignment, Tidy, net
building) and otherwise verified by hand in a headless browser. Selection,
resize handles, undo/redo, clipboard, grouping, rotation and the properties
panel have no standing test. **This is the biggest hole in the project.**

Live DRC is the newest thing in that hole, and the most worth pointing at.
Everything it decides -- when to run, what to discard, when to give up -- lives
in `main.js` and is DOM behaviour: a debounce timer, a stamp comparison
against the document that was checked, a time budget that switches the feature
off. None of it is unit-tested. It was verified by driving a real headless
Chromium over CDP with trusted input events, which is worth one specific
warning: an earlier round of that verification used synthetic
`new MouseEvent()` calls, which fire no default actions, and so passed against
an editor that was visibly broken in the browser. If you test this area, use
`Input.dispatchMouseEvent`. A standing test would need a browser in the suite,
which would cost the "runs on a bare machine" property the rest of this
section defends -- so it is recorded here instead of quietly assumed.

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

**Auto layout is measured, not merely asserted.** It lays each drawing out
four ways -- every combination of two ordering choices -- keeps the best, then
refines it by swapping neighbours within a column while that helps
(`layout._score`). Across the seven examples that is 118 crossings, 11 DRC
errors and 49 warnings; the previous single-pass version scored 129 crossings.

Those 11 errors are worth being clear about: they are what auto layout
*produces* when it re-arranges the examples, not what the examples ship with.
As committed all seven validate with zero errors. Auto layout scores DRC
failures rather than being forbidden them, so it will accept one when the
alternative costs more elsewhere -- which is a design choice to challenge, not
a bug to report.

Reproduce it -- no command prints this, so it is a few lines:

```python
import glob
from tests import open_example
from drawlogic import layout, drc, routing

crossings = errors = warnings = 0
for path in sorted(glob.glob("examples/*.dlg")):
    doc, registry, _ = open_example(path)
    layout.arrange(doc, registry)
    segments = list(routing.segments_of(routing.route_all(doc, registry)))
    crossings += layout._crossings(segments)
    for violation in drc.check(doc, registry):
        if violation.level == "error":
            errors += 1
        else:
            warnings += 1
print(crossings, errors, warnings)     # 118 11 49
```

`open_example` rather than `Document.load` matters: plain loading leaves a
`ref` block unresolved, which reads as an unknown cell type and quietly
undercounts every hierarchical drawing.

The score has five weighted terms: crossings, total wire length, bounding-box
spread, DRC errors and DRC warnings. Four of the five weights are judgement,
not measurement. `ERROR_COST` and `WARNING_COST` were the exception -- they
were swept, and the sweep is worth knowing about because it is a useful
warning: raising `ERROR_COST` to 4000 did cut errors to 10, and took warnings
to 75 and crossings to 134. Optimising hard on one term of a hand-weighted
score buys it from the others. The shipped 1000/150 was the best of what was
tried, which is not the same as right; whether a crossing really is worth
about a gate's width of wire is still a fair thing to challenge.

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

One thing to judge rather than test, because no assertion can: the live DRC
count sitting in the corner while you work. It is meant to be the difference
between finding a short as you make it and finding it ten minutes later. The
honest failure mode is the opposite -- a number that nags at something you
have not finished drawing yet, so you learn to stop reading it. If it becomes
wallpaper within thirty minutes, that is the finding, and it is a more useful
one than any bug in this section.

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
by nothing. That shape is why the design rules became DRCs: the distances had
no checker, so the only thing keeping a drawing to them was the router trying
its best and giving up quietly when it could not. The CLI's export flags overrode the document they were exporting.
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
