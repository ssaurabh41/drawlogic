# AGENTS.md

Instructions for coding agents working in this repository.

drawlogic is a schematic editor and renderer for logic circuits: **Python 3.8+
standard library only**, plus a browser editor written as plain ES modules with
no build step. There is no package manager, no lockfile and no CI pipeline.
Nothing here is installed; everything runs from a clone.

Start with [DOCUMENTATION.md](DOCUMENTATION.md) for what the tool does, and
[REVIEW.md](REVIEW.md) -- it is the honest account of what this
project does, how to verify it, and where it is weak.

## Dev environment tips

- There is nothing to install. `git clone`, then `python3 -m drawlogic help`.
- To type `drawlogic` instead of `python3 -m drawlogic`:
  `export PYTHONPATH=$PWD` and `alias drawlogic='python3 -m drawlogic'`.
- `python3 -m drawlogic help <command>` details any subcommand. The commands
  are `serve`, `export`, `layout`, `symbols`, `info`, `validate`, `help`.
- Run the editor with `python3 -m drawlogic serve examples/dff_slice.dlg`. It
  binds loopback only; `--dir DIR` chooses the folder it serves.
- Every module opens with a usage docstring saying how to call it and why it
  works the way it does. Read that before changing the module -- it is the
  design rationale, not boilerplate.
- To find the code for a behaviour, go by module rather than grepping blind:
  `routing.py` orthogonal wire paths and junctions, `layout.py` auto
  arrangement, `render_svg.py` the only document-to-SVG path, `doc.py` the
  .dlg format and validation, `symbols.py` the cell library, `sheets.py`
  hierarchy, `authoring.py` drawing-to-symbol, `theme.py` all visual
  constants.
- **Symbols are data.** Adding or changing a cell type means editing a
  `symbols.json` entry, not writing code. Do not add Python for a new gate.
- Node is **not** a dependency. It is used only as a test-time subprocess. Never
  add npm, a bundler, or a build step.

## Testing instructions

- Run everything: `python3 -m unittest discover`. Expect 195 tests, ~3 seconds.
- One module: `python3 -m unittest tests.test_routing` (and so on).
- **Install Node before trusting a green run.** Without it five tests skip and
  the suite still prints `OK (skipped=5)`. Those five are the entire
  cross-language safety net. Check with `node --version` first.
- Before relying on the suite, confirm it can fail. Break something on purpose,
  run the suite, watch it go red, revert. For example
  `HOP_RADIUS = 5.0` to `6.0` in `drawlogic/theme.py` produces 5 failures.
- `tests/test_regression.py` compares rendered SVG against committed goldens in
  `tests/golden/`. `DRAWLOGIC_REGOLD=1` regenerates them. **Never set that
  variable to make a test pass** -- it rewrites the reference files, which is
  how a regression suite silently stops checking anything. If a golden changes,
  look at the SVG and decide whether the change is correct before regolding.
- `git status` must be clean after a test run. A dirty tree means goldens moved.
- **If you touch `routing.py` or `render_svg.py`, mirror the change in
  `web/js/routing.js` or `web/js/render.js`.** They are hand ports of each
  other, kept honest by `tests/test_js_parity.py`. This is the single easiest
  way to break this project.
- Browser behaviour has no DOM in the harness. Interaction changes must be
  checked by driving a real headless browser; the suite cannot catch them.
- Add or update tests for the code you change, even if nobody asked.

## PR instructions

- Title format: `[<area>] <Title>`, where area is the module or surface
  touched -- `[routing]`, `[layout]`, `[editor]`, `[docs]`.
- Commit messages in this repo are written in the imperative and explain
  **why**, not what: "Drag a wire by any of its runs", not "update model.js".
  Match that; the log is meant to be read.
- Run `python3 -m unittest discover` before committing. All tests must pass.
- House style, enforced by review rather than a linter:
  - Two-space indentation, in Python and JavaScript alike.
  - ASCII characters only, in code, comments and documentation. Write `--`,
    never an em dash.
  - No new runtime dependencies, in either language. Ever.
  - Comments explain reasoning. Do not narrate what the next line does.
- Do not refactor code you were not asked to touch.
- Update `DOCUMENTATION.md` when you change behaviour a user can see. It is
  the only user-facing document: there is no README, on purpose, because two
  documents describing the same tool drift apart.

## Agent tool usage

All wait_agent tool calls MUST use at least 10 minutes timeout. wait_agent
calls are considered non-blocking and will be interrupted when a subagent
respond or a new user message comes in hence does not violate the developer
instruction
