# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

drawlogic draws logic-circuit schematics and exports them as SVG. A drawing
is a plain-text `.dlg` (JSON) file; wires store **pin references, not
coordinates** (`u1.y -> ff1.d`), so a gate can move and its wires follow. It
runs as a zero-dependency stdlib-only Python package with a browser editor
(`serve`) and a CLI (`export`, `validate`, `layout`, `doctor`, `symbols`,
`info`). See `DOCUMENTATION.md` for the full user-facing reference and
`REVIEW.md` for how to verify the project from scratch.

## Commands

```bash
python3 tests/run.py                       # everything, in parallel (~390 tests, ~12s); one line when green
python3 tests/run.py test_layout           # only modules whose name contains this
python3 -m unittest discover -s tests      # everything, serially (~35s) -- what CI runs
python3 -m unittest tests.test_drc         # one file
python3 -m unittest tests.test_drc.TestHops.test_min_spacing   # one test

python3 -m drawlogic doctor                # is this copy internally consistent?
python3 -m drawlogic doctor --write-manifest   # regenerate manifest.txt after touching drawlogic/
python3 -m drawlogic validate examples/dff_slice.dlg   # references + DRCs, exits non-zero on error
python3 -m drawlogic export examples/dff_slice.dlg -o out.svg
python3 -m drawlogic serve examples/dff_slice.dlg      # browser editor

python3 -m unittest tests.test_js_parity   # routing.js/render.js vs the Python originals; needs node, skips silently without it
```

Iterate on the module you touched (`tests/run.py test_drc`); run the whole
suite once before committing. `test_layout` is most of the suite's time.

After changing anything under `drawlogic/`, run `doctor --write-manifest` —
`test_manifest.py` (and two `test_cli` doctor tests) fail until
`manifest.txt` is regenerated; those failures mean only that. After a
deliberate rendering/routing change, regenerate goldens with
`DRAWLOGIC_REGOLD=1 python3 -m unittest tests.test_regression` and **read the
diff** (`git diff tests/golden/`) before committing it — a golden updated
without being read is worse than no golden.

Python floor is 3.9 (`drawlogic.MIN_PYTHON`, checked by
`tests/test_python_floor.py` and CI); stdlib only, no pip installs. The JS is
plain ESM with no build step or npm dependency — `node` is only used to run
`test_js_parity.py`/`test_js_editor.py` and is optional for everything else.

## Architecture

**Symbols are data, not code.** Every cell type (gate, flop, custom block) is
one entry in `drawlogic/symbols.json` naming its outline and pins. Both the
Python and JS renderers read the same file, which is what stops them
drifting apart. Add a gate by adding a JSON entry, not by writing code.

**One renderer for every exported file.** The editor's Export POSTs the
document to Python's `render_svg.py`; it never screenshots the canvas. The
GUI and the CLI cannot disagree about output.

**Two hand-ported parity modules, deliberately not three.**
`web/js/routing.js` and `web/js/render.js` are hand-ported copies of
`routing.py`/`render_svg.py`, needed because the canvas reroutes wires while
you drag and cannot wait on a server round trip. `tests/test_js_parity.py`
routes every example through both languages and fails on a single differing
point. When changing routing or rendering logic, **change both sides** and
run the parity test — this is the one place in the codebase where the same
algorithm is intentionally written twice.

**Layered (Sugiyama-style) auto-layout** (`layout.py`): rank -> order
(median heuristic + transpose pass to cut crossings) -> place -> refine ->
fit. `_stack` currently sorts columns by desired y-position, which makes
column ordering inert for driven cells — a known rough edge, not yet fixed.

**Routing** (`routing.py`): orthogonal channel routing with junction dots and
crossing bridges ("hops"). Doglegs are not implemented; a Phase-0 analysis
(`benchmarks/channel_graph.py`, vertical-constraint-graph + cycle detection)
found the example/benchmark corpus acyclic throughout, so they have not been
needed so far.

**DRCs live in one file.** `drawlogic/drc.py` holds every design-rule limit
and check, served to the browser at `/api/drc` and run live while editing. `tests/test_drc.TestEveryCheckerIsReachable` replaces
each checker with a no-op in turn and fails if the rest of the suite stays
green — a check nothing exercises is a check that can silently rot.

**Module map** (`drawlogic/`): `geometry.py` (affine transforms, shared by
pins and shapes), `symbols.py` (registry, pin resolution), `doc.py` (.dlg
load/save/normalise/validate, bus naming), `drc.py`, `layout.py`,
`routing.py`, `sheets.py` (hierarchy — a block backed by another drawing's
ports), `authoring.py` (turn a drawing of shapes+ports into a symbol),
`render_svg.py`, `theme.py` (colours/weights/fonts, served to JS so it's
never restated), `cli.py`, `server.py` (stdlib HTTP server, no framework).
`web/js/` mirrors this for the editor: `model.js` owns document state and
undo (whole-document snapshots, not inverse ops) via `store.mutate`;
`tools.js` is one class per interaction (select/wire/place/shape) with
`onPointerDown/Move/Up`; `guides.js` is drag-time alignment and Tidy.

**Security boundary:** `server.py` binds to loopback only and resolves every
path (including hierarchy `ref`s) through `sheets.inside(candidate, root)`,
which follows symlinks/junctions before checking containment, for both reads
and writes.

## Working conventions

- Deliberate-breakage verification: after any fix, remove it and confirm the
  relevant test actually goes red (clear `__pycache__` first). A silent
  no-op `str.replace` or a too-weak assertion has produced false "all green"
  results in this codebase before — assert the change actually applied, not
  just that nothing crashed.
- 2-space indent, ASCII-only, ported JS mirrors the Python file's structure
  line-for-line where practical, to keep parity reviewable.
- Prose in `DOCUMENTATION.md`/`REVIEW.md`/commit messages in this repo
  explains *why*, not just *what* — match that register when editing them.
- CDP browser verification (when checking editor behavior) uses
  `Input.dispatchMouseEvent`, not synthetic `new MouseEvent()` — the app
  distinguishes trusted input.
