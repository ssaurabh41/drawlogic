# Session handoff

A summary of one long working session on drawlogic, so a new session can
carry on without the old conversation. Start a new session with: "read
SESSION.md and CLAUDE.md, then continue". CLAUDE.md has the commands and the
architecture; this file has what was done, what was decided and what is open.

## How the owner likes to work

- Work directly on `main` and push there. No pull requests unless asked.
- Commit messages end with the Co-Authored-By and Claude-Session lines; no
  model names in commits or code.
- Ask before assuming. When something is unclear, ask first; when running
  unattended, pick the most reasonable reading and say what was assumed.
- Simplest solution that works; no flexibility nobody asked for.
- Don't touch unrelated code, but do point out bad code or design smells so
  they can be dealt with separately.
- Say when unsure. A small, low-risk experiment beats confident guessing.
- Suggestions for better approaches are welcome.

## The architecture-diagram session (latest)

Four features from a spec the owner supplied, in order, each pushed to main
and reviewed before the next:

| Commit | What |
|---|---|
| 2d89b1a | Linked components (`components.py`, `/api/component`, `/api/resolve`): create from selection with a port-review dialog, Insert, Repeat (rows x columns, sequential names), Edit definition (saving refreshes open users), Make independent, Refresh. Examples `arch_mini.dlg`, `gpu_arch.dlg` + `examples/components/` |
| 43dcddc | `heading`, `headingStyle`, `textStyle` on cells/box shapes/containers; named `styles` + `styleRef` (`styles.py`, mirrored by `geometry.effectiveStyle`); Text panel Format section, Style picker, Save as style, Edit style dialog |
| ca43b5f | Layout with containers: innermost first, per-container `layout` (flow lr/tb, row, column, grid; gap; columns); Layout contents for one container; pinned holds its containers |
| 801b130 | Move into container picker: tree docked right, hovered target outlined on canvas, Sheet row, search |
| d163572 | Containers: top-level `containers`, `parentId` ownership, absolute coords, painted beneath everything; Container menu, delete asks keep/delete contents |

Decisions the owner made: deliver per feature; containers paint beneath
everything; components live in `components/` beside the drawing; a new GPU
example (`gpu_arch.dlg`) rather than reworking `gpu_top.dlg`; the
Move-into picker is a tree dialog.

Behaviour the owner confirmed afterwards (each was first an assumption):

- A new item made wholly inside a container (palette drop, shape or
  container drawn) belongs to the innermost one; dragging never reparents.
- Remove from container / Ungroup go up one level.
- In a drawing with containers, Auto layout with cells selected lays out the
  whole drawing (a selection-only layout would pull cells out of containers).
- Layout contents grows a container but does not push its neighbours.
- Choosing a named style drops the item's own settings of exactly what the
  style sets; Save as style does the same.
- Drawing a container and naming it is one undo step; so is placing a text
  box and typing in it, and one left empty leaves nothing to undo
  (Store.cancelGesture).

Open items from it were all done in a follow-up: wires keep off container
titles (routing.side_label_boxes and its JS twin; geometry.js now holds the
container title layout both routers and render.js use); a group or any
multi-selection carries its internal wire bends; the Inside row wraps;
named styles rename and delete (delete keeps every user's look); instances
show a live miniature of their definition (`"preview": true`, symbol ops in
the "preview" roles from sheets._preview, skipped by both renderers when
off).

Then examples/cpu_arch.dlg (quad-core SoC of linked components/ooo_core.dlg)
and, from what drawing it exposed: no unconnected-pin warning at all (user's
call: noise); wires keep CLEARANCE off container outlines on every corridor
pass (Sheet.add_borders / addBorders); packed rows and grids widen their gap
for the wires leaving them (layout._pack_gap, capped at CELL_GAP_X; columns
keep CONTAINER_GAP). The user said two-way ports on the left are not a bug.
For wires looping between blocks of a Column the user chose "tidy loops
only" (over staircase / rows-by-stage / leave it): the column stays one
line of blocks, layout._column_loops widens its sides by a lane per loop and
the gap above a block two loops turn into, and a crossover leg now moves
off another wire within WIRE_GAP, not only on top of it (_leg_column /
legColumn).

Then header bands made solid (user: "a hard cell for spacing"): routing
keeps CLEARANCE off containers.header_box, DRC wire-over-header (error) /
wire-to-header (warning). Wires into a container from above could not be
placed by the fixed shapes, so (user chose this over allowing a crossing)
routing._find_path / findPath: A* on a grid of obstacle-edge, outline and
wide-gap-middle lines, bends 30, crowding = length again, crossing 20,
closer than CLEARANCE barred, reach 300; used only when the shape route is
not clear. HDL layout tests cost ~15% more. A column's gaps now hold every
wire passing between blocks (_column_loops `across`). The pre-pathfinder
state is the branch `before-pathfinder` (a tag push was refused by the
session's git proxy).

Then examples/gpu_linked.dlg (the open item "hierarchical GPU", as a new
file; gpu_top.dlg untouched): 8 linked components/gpc.dlg (4 TPC rows of 2
linked sm.dlg) + linked components/xbar.dlg (10 in / 3 out, which no
built-in block has). Needed two fixes: sheets._child_registry resolves a
definition's own links before its miniature is drawn (else a GPC miniature
had no wires), and _find_path/findPath grow their window over anything it
touches (a column of GPCs taller than MAZE_REACH left no way round).
First attempts worth knowing: a 2-column grid of GPCs and a column-stacked
TPC both tangled badly; rows of SMs in a column of TPCs, and one column of
GPCs, read cleanly.

Then findings1.md (an outside review of e912c74, ten findings): all ten
reproduced and fixed, each with a test that fails without its fix.
1 extract rebases refs of linked blocks taken into a component
  (components.rebase); /api/component opens the definition at its target
  with a fresh registry and refuses to write it if a link would not resolve;
  answers carry `problems` and the editor shows them (sayMade).
2/5/9 one note measurement, render_svg.note_box / geometry.textShapeBox
  (named style + font scale), used by fit, crop, DRC and layout; layout
  places contents so notes, not blocks, sit at the inner corner (no drift).
3 the editor merges server sheet answers into the tab's (model.keptSheets)
  so Undo of Make independent still draws -- verified in Chromium.
4/7/8 copy records `from`, styles and sheet symbols; paste into another
  drawing rebases refs (model.clipFor), drops uncopied parentIds, adds or
  renames ("<name> (pasted)") clashing styles; unsaved target leaves linked
  blocks out with a message -- verified in Chromium across two folders.
6 tb flow with pins (_rows_of_ranks anchors on the first pin, pushes rows
  clear of others).
10 sheets._Reading: one parse per file and memoised walks per (path, seen,
  depth) for one resolve; duplicate deep issues reported once.
Not changed (the review agrees they are design limits): Make independent is
shallow; miniatures are boxes and wires only.

Then findings2.md (review of those fixes): three more, all reproduced, fixed.
R1 Ctrl+D pasted through the shared clipboard unmarked; it now pastes its
  own copy (paste(offset, source)) and only Copy/Cut write the clipboard
  (test_js_editor.TestOnlyCopyFillsTheClipboard). Verified in Chromium.
R2 notes walked down a box holding a pinned cell: the after-corner now counts
  fixed nodes where they stayed, and packing starts no further in than any
  pinned box.
R3 (user chose: carry the symbols) components.carry_symbols copies the
  folder-local symbols a component uses into components/symbols.json, reusing
  identical entries and renaming the component's copy (custom_sm_2) on a
  clash; the server checks the component with Handler.base (registry without
  the served folder's symbols) + that folder's library, as a standalone open.
Not done (review's "consider" list): canonical style comparison on paste,
  a lifetime for kept sheet symbols, a message when pins make tb order
  impossible. Noticed: _opened does not load a subfolder's symbols.json, so
  the editor and a CLI open can disagree for drawings below the served root.

## Earlier in the first session (newest first)

| Commit | What |
|---|---|
| 7830964 | `/bro` project skill (`.claude/skills/bro/SKILL.md`): restates the last reply in plain language. Only runs when typed; loads from the next session on |
| f27347e | `examples/gpu_top.dlg`: GPU top-level block diagram, 0 warnings, with its golden |
| 40c00da | `tools/pack_repo.py` / `tools/unpack_repo.py`: whole repo as one pasteable text file and back, checked per file by line count and SHA-256; `tests/test_bundle.py` |
| c6ecbae | The xN badge on stacked cells and shapes is grey (`theme.COLORS["badge"]`), not black |
| 8f0c591 | Editor: text typed on the canvas instead of a browser prompt; a line has two end handles; shapes resize freely (Shift keeps proportions); close button on Preferences |
| 1667fd3 | mac_pipe removed; 4-bit shift register example added; clock gates named U1, U2...; stack depth 5% -> 3%; clicks pass through the inside of an unfilled shape in front |
| b4d2820 | Shapes and symbols share one stacking order (`z`); front/back and group/ungroup moved to the toolbar; shapes take text, copies and shadows; "No fill" in the palette, shapes default to no fill |
| ba14e1a | `reg` symbol removed (`dff` takes buses); ICG has E on top, CK below, and the word "ICG" |

Decisions the owner made along the way:

- Remove `reg`; `dff` accepts any bus width.
- Full free ordering of shapes and symbols; shapes sit behind symbols until moved.
- Shadows are for shapes only.
- Text and copies on box, ellipse and polygon (and any future closed shape);
  lines take text but not copies.
- soc_top's U_MAC became a plain block with the same pins.

## The GPU example, briefly

`examples/gpu_top.dlg` was generated by a script (not kept in the repo) and
saved through `Document.loads(...).dumps()`. Layout: ports left and right, a
dashed "GPU die" outline, host/front end -> GigaThread -> 8 GPCs -> crossbar ->
12 memory partitions, display and NVLink; two shape-only panels underneath for
"inside one GPC" and "inside one SM". Unit counts are realistic but invented.
Every pin is connected because an unconnected pin was a warning then; that is why a
few blocks carry clock or status pins. One wire crossing (NVLink tx) cannot be
avoided and is drawn as a bridge.

## Open items (none requested yet)

- **Generic blocks have fixed pin counts** (`block` 2/2, `block6` 3/3,
  `block8` 4/4). Unused pins no longer warn; a block whose pin count you
  choose would still make block diagrams easier. Proposed, not started.
- soc_top and spi_master still have DRC warnings (spacing, hops).
- The xN badge can overlap a flop's Q stub.
- Possible: unit tests for the newest editor features, shadow presets, a test
  for the fork-late reset.

## Things worth knowing

- Suite: `python3 tests/run.py` -> 644 tests, 0 failed, 5 skipped (~30 s).
- After touching `drawlogic/`: `python3 -m drawlogic doctor --write-manifest`.
- After a rendering change: `DRAWLOGIC_REGOLD=1 python3 -m unittest
  tests.test_regression`, then read `git diff tests/golden/`.
- Clear `__pycache__` before a deliberate-breakage check; a stale cache once
  gave a false result.
- Screenshots of an exported SVG: load it into a Playwright page with
  `setContent` (navigating to the file hangs on fonts). Chromium is at
  `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.
- Push with `git push origin HEAD:main`; check which branch the session is
  on first (`git status -sb`).
- Editor server processes do not survive between turns here: start
  `drawlogic serve` in the same command as the browser script driving it.
- Cloud sessions can't be forked in the browser. To carry on with full
  history, `claude --teleport <session-id>` from a checkout of the repo gives a
  separate local copy; otherwise start a new session and point it at this file.
