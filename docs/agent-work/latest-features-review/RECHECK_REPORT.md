# Recheck report: old findings against latest main

STATUS: **accepted**, with verification limits recorded in ACCEPTANCE.md.

Root clarification: temporary-directory writes failed under the sandbox;
the precise cause is not established. Claims below attributing this to a
directory-name prefix are the worker's hypothesis, not a verified rule.
The root reran the new HDL tests and editor wrappers outside the sandbox
without the shim: 9 tests, OK with one expected failure. Only the if/else
test simulates next-state values; the case test checks structure and DRCs.
Deliberate-breakage evidence establishes the new wire-end test's sensitivity.
Keep the documented expectedFailure; changing example discovery is outside
this findings/test update. The original comparison establishes that parity
failures predate this range, not that the local file alone is at fault.

Task: `/root/reverify_main`. Workspace:
`D:\Work\claude_code\project\drawlogic-latest`.

Baseline captured before any edit: HEAD
`01d5715b6e61d4867de4fe5e75363c6d16cbf8b3` (merge of `origin/main` `e594be8`
into `ec7b5cf`, branch `codex/findings_v1`). Range rechecked:
`0f53171..e594be8`. Dirty tracked file at baseline and at the end:
`benchmarks/auto-layout/01-linear.dlg` (not mine, unmodified). Untracked and
left alone: `.codex/`, `AGENTS.md`, `RTK.md`, `examples/untitled.dlg`,
`examples/verilog/`, `shift_register_4bit.dlg`, `user1.dlg`,
`suite-discover*.log`. No production code changed; no commit, merge, push,
stash, reset or deploy.

## Changed paths

| Path | Change |
| --- | --- |
| `tests/test_hdl.py` | +126 lines: `TestWhatTheFirstReviewReported`, 6 tests -- the two fixed importer behaviours (if/else without `begin`/`end`, `case`), the declaration defect as a documented `expectedFailure` with its `assign`-form positive control, and two negative controls (an unreadable module-level statement after an `always` still raises with its line; an `initial` block is reported and left out) |
| `tests/js/editor_check.mjs` | +42 lines: new area "placing onto a wire end", 3 checks -- a cell dropped near a loose wire end lands on it and joins it, the wire keeps its driver, and with auto-connect off the end is left alone |
| `tests/test_js_editor.py` | `MINIMUM_CHECKS` 45 -> 48 and the new area added to the list of areas that must exist |
| `docs/agent-work/latest-features-review/FINDINGS.md` | recheck section appended: classification of all four findings against `e594be8`, reassessed weaknesses, new artifacts |
| `docs/agent-work/latest-features-review/CHECKPOINT.md` | state, done, not done |
| `docs/agent-work/latest-features-review/RECHECK_REPORT.md` | this report |
| `docs/agent-work/latest-features-review/*-recheck-*.log`, `parity-at-0f53171-untitled.log` | new logs, distinct from the historical ones |

`drawlogic/web/js/model.js` shows as ` M` in `git status` only because the
index could not be refreshed (`.git` is read-only here): `git hash-object`
equals `HEAD:drawlogic/web/js/model.js` exactly, i.e. the file is byte-equal
after the repository's clean filter. It was edited temporarily for the
deliberate-breakage check below and restored. `ACCEPTANCE.md` was not touched
(left for root).

## The four old findings

| # | Finding at 0f53171 | Status now | Evidence |
| --- | --- | --- | --- |
| 1 | Importer refused ordinary `always` bodies (`HdlError: line 5: cannot read 'else q <= d'`) | **fixed** | both fixtures import, exit 0, drawings written, `warnings == []`; `seq2.dlg` is `dff q_reg` + `inv` + `and2` whose D is `d & ~rst`; `seq.dlg` is `dff q_reg` + 2 `inv` + `nand2` + 2 `ripper` and validates clean; new tests simulate the next state through the drawn gates |
| 2 | `wire x = a & b;` dropped silently | **persistent** | `rtl.items` returns it as an opaque `"text"` item (`rtl.py:170`), `_parse_text_item` matches `DECLARATION` (`hdl.py:333`) and `_declare` keeps only the name; import exits 0 with `warnings == []`, and the drawing has one net (`y`) with `p_a.p`, `p_b.p` and `g.a` unconnected. Written as `assign x = a & b;` the same logic becomes an `and2`, so the reader can draw it |
| 3 | Windows-red save test (`tests/test_model.py:94`, `0o644` vs `0o666`) | **persistent** | unchanged file; targeted run: 40 tests, 1 failure, `AssertionError: 438 != 420`. The code under test is right -- `probe_save.py` shows the mode unchanged across a save |
| 4 | Untracked `examples/untitled.dlg` breaks the suite | **persistent**, and its provenance is now settled | four failures name that example, exactly as before. A clean `0f53171` checkout with the same untracked file copied in fails the same two parity tests (`parity-at-0f53171-untitled.log`, 12 tests, 2 failures), so the `routing.js`/`routing.py` disagreement is the local file's, not this range's. `tests/test_regression.py:72` still writes a missing golden, so a suite run recreates `tests/golden/untitled.svg`; I deleted it again after my runs |

Reassessed weaknesses (detail in `FINDINGS.md`): the duplicate-drag
auto-connect concern no longer holds as described -- `SelectTool.duplicate()`
re-points `startBoxes` at the copies (`tools.js:226-238`) before the drop uses
them (`tools.js:322-330`); `write_file` durability, `_arrange_part`'s
`forkLate`, `_refusal`'s loopback spellings, `GET` gated only by `Host`, and
`drc.check`'s duplicate-id early return are all unchanged and still
unconfirmed for the same reasons as before.

## Verification

All Windows 11 / Python 3.14.7, from
`D:\Work\claude_code\project\drawlogic-latest` unless stated. `PATH`
`PYTHONPATH` and `DRAWLOGIC_SCRATCH` were set to keep temp files inside the
workspace -- see "Constraints" below; the repository itself is untouched by
that.

| Command | Exit | Result |
| --- | --- | --- |
| `python -m unittest discover -s tests -v` (baseline, before my tests) -> `suite-recheck-e594be8.log` | 1 | **451 tests, 5 failures, 9 skipped**; failures = 2 untitled parity, 2 untitled regression, 1 `test_model` mode; skips = 4 `TestYosys` (Yosys is not installed) + 4 symlink + 1 golden written |
| `python -m unittest discover -s tests -v` (with my tests, final bytes) -> `suite-recheck-e594be8-after-tests.log` | 1 | **457 tests, 5 failures, 9 skipped, 1 expected failure**; the same five failures and no others; the expected failure is the finding-2 probe. (The skip count moves between 8 and 9 with the regenerated `tests/golden/untitled.svg`: `test_examples_match_their_golden` skips once for the example whose golden it just wrote.) |
| `python -m unittest tests.test_hdl tests.test_model.TestSavingCannotLoseADrawing tests.test_js_editor -v` -> `tests-recheck-targeted.log` | 1 | 40 tests, 1 failure (finding 3), 4 skipped (Yosys), 1 expected failure |
| `python -m unittest discover -s . -p "probe_*.py" -v` (in this directory) -> `probe-recheck-e594be8.log` | 1 | 15 tests, 3 failures: `probe_hdl`'s two "behavioural code is not drawn" assertions and the `wire x` warning assertion. The first two are obsolete expectations (fixed finding 1); the third is finding 2, still open |
| `python -m unittest tests.test_js_editor -v` | 0 | 3 tests ok; the node run itself reports `DONE 77/77` with the new area `placing onto a wire end 3/3` |
| Deliberate breakage: `if (false && connect) joined.push(...autoConnect(...))` in `model.placeCell` | 1 | `FAIL a cell let go near a loose wire end lands on it`; reverted, and `model.js` is byte-equal to `HEAD` |
| `python -m drawlogic import docs/.../fixtures/always_else.v` and `always_case.v` and `wire_assign.v` | 0 | each writes its drawing; the sequential fixtures draw flip-flops, `wire_assign` draws with the expression silently missing |
| `python -m unittest tests.test_js_parity` in a clean `0f53171` extraction with the untracked example copied in -> `parity-at-0f53171-untitled.log` | 1 | 12 tests, 2 failures, both `example='untitled.dlg'` |
| `git status --porcelain` at baseline and at the end | 0 | same tracked dirt (`benchmarks/auto-layout/01-linear.dlg`) plus the same untracked set; my additions are `tests/js/editor_check.mjs`, `tests/test_hdl.py`, `tests/test_js_editor.py`, this directory |

Windows line endings were normalised to CRLF in the three touched files so
the diff is not a whole-file rewrite under `core.autocrlf=true`.

## Confirmed issues and constraints

**Confirmed open defect:** the declaration-with-an-expression import defect
(finding 2) at `drawlogic/hdl.py:333-336` with `rtl.py:170` and `hdl.py:185`.
Reproduced, with a passing positive control, and pinned by an
`expectedFailure` test.

**Confirmed test-side defects:** `tests/test_model.py:94` (POSIX-only
assertion, red on Windows) and `tests/test_regression.py:72` (a missing
golden is written instead of failing, so a suite run dirties the tree).

**Environment constraints:**

- This sandbox denies every write inside a directory whose name starts with
  `tmp`, which is what `tempfile.mkdtemp` creates: the stock call succeeds and
  then nothing can be written into the directory, and even `os.chmod` on it
  is refused. Every temp-file test (`probe_save.py`, `test_hdl`, the smoke
  tests) fails there for that reason alone. Workaround used, kept in the
  workspace as scratch and not part of the repo:
  `.recheck-tmp/site/sitecustomize.py` (a `PYTHONPATH` shim that makes
  `mkdtemp`/`mkstemp`/`TemporaryDirectory` create their directory with
  `os.makedirs`), plus `DRAWLOGIC_SCRATCH` pointing at a workspace scratch
  directory it creates on demand. The scratch copies used for the
  `0f53171` comparison were removed again; `git archive --format=zip -o
  <zip> 0f53171` plus `Expand-Archive` reproduces that extraction. The
  previous review's sandbox-blocked logs show the
  same wall. A run without the shim is not a valid result here; `-v` output in
  the logs above is from the shimmed runs.
- That same wall cannot be undone: one empty directory,
  `.recheck-scratch/scratchg8_7eclf` (made by the stock `mkdtemp` before the
  shim was in place), refuses deletion by any means available here, so it is
  left behind. It holds nothing. `.recheck-tmp/site/sitecustomize.py` is
  deliberately kept so these runs can be repeated; both are scratch, not part
  of the review's diff, and can be removed with normal permissions.
- `python tests/run.py` (the parallel runner) cannot start here, as before;
  the serial CI command is what the evidence uses.
- Yosys is not installed, so `synth="auto"` exercises the built-in reader and
  the four `TestYosys` tests skip. The Yosys path is therefore still
  unverified by execution.
- No browser and no CDP session, so the palette-drag preview, the port grips
  and the tab/recovery flows are covered only by the repo's node checks and
  by reading `tools.js`/`selection.js`. Trusted-input QA is a coverage gap,
  not a pass.

**Decisions requiring Astra:** whether to keep the finding-2
`expectedFailure` probe in the shipped suite (it turns an eventual fix into an
unexpected success, i.e. a red run) or move it into this review directory
alone; and whether the untracked `examples/untitled.dlg` should be excluded
from the example walk rather than left to fail four tests locally.

## Next checkpoint if work continues

Nothing in this bundle is unfinished. The obvious follow-ups, in order:
fix finding 2 in `_parse_text_item`, run the new expected-failure probe to
confirm it flips to an unexpected success, and re-check the two remaining
review items with a browser (`tools.js` duplicate-drag join, and the
palette-drag preview over a loose wire end).
