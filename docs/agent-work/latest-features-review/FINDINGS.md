# Review: new features in 8717527..0f53171

Reviewer: Flash implementation worker (task `/root/verify_features`), sole
worker, review artifacts only. Baseline `0f53171`, branch
`codex/auto-layout-optimization`, range `8717527..0f53171` (13 commits).
Workspace `D:\Work\claude_code\project\drawlogic-latest`. No production code
was changed and nothing was committed, pushed, reset or stashed.

## Confirmed bugs, most serious first

### 1. [P2] Verilog import refuses ordinary sequential Verilog instead of warning

`drawlogic/hdl.py:321` (raise in `_parse_body`, reached from `parse` at
`hdl.py:288`), against the promise at `hdl.py:27` and
`DOCUMENTATION.md:276`.

`_parse_body` splits a module body on `;` with no notion of `begin`/`end`
and then requires every remaining fragment to be a declaration, an `assign`
or an instance: anything else raises `HdlError`. Inside a behavioural block
the fragments after an `always`/`initial` are keyword-led statements, so the
first one that is not in `BEHAVIOUR` ends the import.

Impact: `drawlogic import` and `POST /api/import` (and therefore the editor's
**Import Verilog** button) reject files that are exactly with the feature
they document as the friendly case -- "Everything else is reported as a
warning and left out rather than refused: `always` and `initial` blocks"
(`DOCUMENTATION.md:276`). The message also blames a statement the user never
meant as a statement: `line 5: cannot read 'else q <= d'`.

Reproduction (run from this directory -- `unittest` discovery cannot take a
hyphenated path from the repository root -- and unsandboxed if the sandbox
blocks temp directories):

```powershell
python -m unittest discover -s . -p "probe_hdl.py" -v
```

or by hand, from the repository root:

```powershell
python -m drawlogic import docs/agent-work/latest-features-review/fixtures/always_else.v
python -m drawlogic import docs/agent-work/latest-features-review/fixtures/always_case.v
```

Observed: `HdlError: line 5: cannot read 'else q <= d'` (and
`line 8: cannot read "default: q <= 1'b1"` for the `case` fixture), exit
non-zero, nothing written. Expected: the drawing is produced and a warning
such as `<module> line 4: behavioural code is not drawn` is reported, which
is what the file's own docstring and the manual describe.

Suggested remedy: give `_parse_body` a notion of a behavioural region -- e.g.
track `begin`/`end`/`endcase`/`endmodule` depth while splitting, and from the
moment an `always`/`initial`/`generate` opener is seen, treat unreadable
fragments as more behavioural code (one warning for the block, not one per
fragment) -- or, more simply, keep the module-level statement-strictness and
drop the strict `raise` for fragments that follow a behavioural opener.

### 2. [P2] `wire x = a & b;` is dropped silently

`drawlogic/hdl.py:305-308` with `hdl.py:179` (`_declare`) and the `DECLARATION`
pattern at `hdl.py:197`, against `DOCUMENTATION.md:276`.

`DECLARATION` matches `wire x = a & b` as a plain declaration; `_declare` then
takes `raw.split("=")[0]`, so `x` is created with no driver and the expression
is thrown away without a word. The drawing then loses the connection too: the
net that carried `x` has a single endpoint, and `_build` skips nets with fewer
than two ends (`hdl.py`, `if len(found) < 2: continue`).

Impact: a real connection disappears from the drawing with no warning at all,
which is the failure mode the module docstring is written to prevent ("what
cannot be drawn is said out loud rather than dropped"). Every other
ununderstood construct warns; this one does not.

Reproduction: `python -m drawlogic import docs/agent-work/latest-features-review/fixtures/wire_assign.v`

Observed: `warnings == []` (probe
`probe_hdl.TestBehaviourIsWarnedNotRefused.test_an_expression_in_a_declaration_is_a_warning`),
and the imported drawing has no net for `x`. Expected: a warning naming `x`
and the expression, e.g. `cont line 3: x is driven by an expression the
drawing cannot show`.

Suggested remedy: in the declaration branch of `_parse_body`, if the matched
names contain `=` outside a range, split the assignment off and report it the
same way an unreadable `assign` is reported.

### 3. [P2] The new save test is POSIX-only, so the suite is red on Windows

`tests/test_model.py:94` (test `TestSavingCannotLoseADrawing.test_it_keeps_the_file_readable_by_whoever_could_read_it`).

```python
self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o644)
```

On Windows Python maps only the read-only bit into `st_mode`, so a writable
file reports `0o666`. The assertion cannot hold there, and the code under
test is in fact correct: `drawlogic/doc.py:407` (`write_file`) copies the
target's mode onto the replacement (`shutil.copymode`) and my probe compares
the mode before and after a save and finds it unchanged.

Impact: `python -m unittest discover -s tests` is red on Windows for a reason
that has nothing to do with the change under review, and a real regression on
Windows would be hard to spot in the noise.

Reproduction:

```powershell
python -m unittest tests.test_model.TestSavingCannotLoseADrawing -v
```

Observed: 1 failure, `AssertionError: 438 != 420`
(`438 == 0o666`, `420 == 0o644`). Expected: the test passes on the platform
the repository is used on, and still fails if a save really does change who
can read the file.

Suggested remedy: compare against the mode captured before the save, or skip
on `sys.platform == "win32"` with a reason, the way the symlink tests in
`tests/test_server.py`/`tests/test_sheets.py` are skipped when the platform
cannot express the case.

### 4. The full suite is red because of the untracked `examples/untitled.dlg`

`tests/test_regression.py` and `tests/test_js_parity.py` walk `examples/*.dlg`,
and `examples/untitled.dlg` is an untracked file in the working tree (the
user's, preserved, not part of the range). Four of the five failures in a
clean run of the suite name that example.

Observed (`suite-unsandboxed.log`), 5 failures of 439 tests:

| Test | Subtest | Cause |
| --- | --- | --- |
| `test_regression.TestEveryExample.test_no_validation_errors` | `example='untitled'` | `cell c7: pin 'rn' is driven by 2 nets (n3, n7)` |
| `test_regression.TestEveryExample.test_saved_file_is_already_canonical` | `example='untitled'` | file is not in canonical form (net endpoint `c1.d` vs `c2.y`) |
| `test_js_parity.TestRouterParity.test_every_example_routes_the_same_in_both` | `example='untitled.dlg'` | routes differ between Python and JS |
| `test_js_parity.TestRouterParity.test_every_example_puts_its_arrows_in_the_same_place` | `example='untitled.dlg'` | arrow placement differs |
| `test_model...test_it_keeps_the_file_readable...` | -- | finding 3 above; not related to the example |

Every tracked example passes both the regression and the parity tests. These
four failures are triggered by the untracked file; this does not prove the
parity differences are harmless or pre-existing. Their regression provenance
was not established and needs a separate comparison against the old code.

Secondary defect found while tracing that: `tests/test_regression.py:70-76`
writes a golden file when one is missing (`if REGOLD or not os.path.isfile(golden)`),
so simply running the suite *creates* `tests/golden/untitled.svg` from the
untracked example and leaves the working tree dirty. I deleted that generated
file; the suite will recreate it on the next run.

## Unconfirmed weaknesses (no reproduction, or reasoned only)

These are worth a look but I did not confirm them, so they are not findings
to act on without more evidence.

- **Durability, not atomicity, of `write_file`.** `drawlogic/doc.py:407` has
  no `fsync` before `os.replace` (`doc.py:439`) and does not flush the
  directory. That is enough for the documented cases (a killed process, a
  full disk, `os.replace` failing -- all three are covered by
  `tests/test_model.py` and pass), but a power cut can still leave the new
  name pointing at unwritten data on a journalled filesystem. The prose at
  `DOCUMENTATION.md:558-562` claims "a crash or a full disk part way through".
  Needs a real power-cut or fault-injection harness to confirm.
- **Auto-connect after a duplicate drag.** `drawlogic/web/js/tools.js:323-331`
  passes `[...this.startBoxes.keys()]` to `model.autoConnect`, and
  `startBoxes` is filled from the selection on press (`tools.js:120-123`).
  For a Ctrl/Shift drag the *duplicate* is what lands on the pin, so the copy
  may not be the cell that gets joined. Reasoning from the code only -- needs
  a browser session with CDP `Input.dispatchMouseEvent` to confirm. The
  single-cell place path (`tools.js:470-478`) passes the new cell id and looks
  right, and the node-based editor check "auto-connect on drop" covers that
  path only.
- **`_arrange_part` leaves the drawing's `forkLate` decision stale.**
  `drawlogic/layout.py` (selection layout) copies the canvas and pops
  `forkLate` from the *copy* before laying out the group, then moves the
  group's cells back into the real document; the document's own `forkLate`
  is never reconsidered. Could make a later CLI layout or export fork
  differently from the editor. Not reproduced.
- **`_refusal` rejects some genuine loopback names.** `drawlogic/server.py:233`
  compares the lower-cased `Host` name against `{"127.0.0.1", "localhost", "::1"}`,
  so `Host: localhost.` (trailing dot, a legal FQDN spelling) or an
  IPv4-mapped `[::ffff:127.0.0.1]` is answered 403. Cosmetic denial of a
  legitimate local user; not a hole. I did not run a request to confirm the
  exact status.
- **Reads are gated only by `Host`.** `_refusal` (`server.py:233`) returns
  early for anything but `POST`, so `Origin`/`Sec-Fetch-Site` are not
  consulted for `GET`. That is sound against a browser attacker because there
  are no CORS headers to expose the body, but a non-browser local client can
  read drawings. Worth a sentence in the docstring rather than a code change.
- **`drc.check` returns only `duplicate-id` for a file with repeated ids**
  (`drawlogic/drc.py`, early return in `check`). Deliberate per the comment
  and covered by `tests/test_model.py`, but it means `validate` hides every
  other fault in such a file; a warning-level companion note might be kinder.

## What was verified and how

Commands, all from `D:\Work\claude_code\project\drawlogic-latest`:

| Command | Exit | Result |
| --- | --- | --- |
| `python tests/run.py` | 1 | cannot start: `PermissionError [WinError 5]` making its multiprocessing pipes. Sandbox limitation, not a repo defect; `suite-discover.log`. |
| `python -m unittest discover -s tests` (sandboxed) | 1 | 411 tests, 4 failures, 108 errors -- all 108 are `PermissionError` writing inside temp directories the process creates at runtime. Sandbox limitation; `suite-discover.log`, `suite-discover-tempfix.log`. |
| `python -m unittest discover -s tests -v` (unsandboxed) | 1 | **439 tests, 5 failures, 4 skipped**; the canonical run, `suite-unsandboxed.log`. Failures = finding 3 and finding 4. Skips are the four symlink tests ("symlinks are not available here"). |
| `python -m unittest tests.test_model.TestSavingCannotLoseADrawing -v` | 1 | 3 pass, 1 fail: `438 != 420` (finding 3). |
| `python -m unittest discover -s . -p "probe_*.py" -v` (in this directory) | 1 | 15 probes: 12 pass, 3 fail = findings 1 and 2. `probe-results.log`. |

Features covered by tests that passed in the unsandboxed run, i.e. evidence
against the change range rather than my reading of it:

- **Cross-site write protection** -- `tests/test_server.py`
  `TestOnlyTheEditorMayWrite` (plain-text cross-site form post, cross-origin
  JSON post, rebound `Host` for both a write and a read, and the editor's own
  same-origin save) all pass. I also checked that every `fetch` in
  `drawlogic/web/js/main.js` posts `Content-Type: application/json`, so the
  new refusal cannot lock the editor out of its own endpoints.
- **Atomic saves** -- `tests/test_model.py` `TestSavingCannotLoseADrawing`
  (`os.replace` patched to fail leaves the old file and no `.tmp` litter),
  plus my `probe_save.py` (backup made once per change, backup not
  re-overwritten by an identical save, mode unchanged across a save).
- **Verilog import, happy path** -- `tests/test_hdl.py` (24 tests: gate
  primitives, hierarchy, bit rippers, older header style, warnings for
  behaviour and unreadable assigns, unknown modules, error lines) and
  `tests/test_cli.py::TestImport`, and `tests/test_server.py` import endpoint
  tests, all pass.
- **Selection layout and pinning** -- `tests/test_layout.py`
  (`test_ports_stack_as_close_as_the_drcs_allow`,
  `test_soc_top_keeps_clear_of_its_title_and_subtitle`, ...) plus my
  `probe_layout_pin.py`: a pinned cell never moves, cells outside `only` never
  move, an unknown `only` name changes nothing, repeated selection layout is
  idempotent, and the result still validates clean with no DRC errors.
- **Routing, DRC and renderer changes** -- `tests/test_drc.py`,
  `tests/test_js_parity.py` (JS/Python parity over every example, including
  the new wrapped-label case), `tests/test_regression.py` goldens, all pass
  for the tracked examples. I read the bucketing rewrite in
  `routing.Sheet.free`/`junctions` and `drc._check_text`/`_check_wires_and_cells`/
  `_check_hops` and worked through the index arithmetic: the bucket ranges
  (32-unit run buckets, `int(fixed // 1)` for contact, `limit + 1` grow boxes)
  are wide enough to include every pair the old loops considered, and the
  reported order is preserved by sorting indices.
- **Editor DOM features** -- the node-based checks in
  `tests/js/editor_check.mjs` run by `tests/test_js_editor.py` pass, including
  "auto-connect on drop", the shortcut list matching `DOCUMENTATION.md`, and
  the no-leftover-`console.log` check. `tests/test_model.py` covers the
  `prefs`-driven grid defaults indirectly through `blankDocument`.

## Coverage gaps and limitations

- **No browser evidence.** I did not run a browser or CDP session, so tabs
  (open/close/restore, closing a tab whose file was replaced by an import),
  the crash-recovery offer, the preferences panel, rename-in-place and the
  format painter are verified only by the repo's node DOM checks and by
  reading `main.js`, `prefs.js`, `recovery.js`, `panels.js`, `model.js` and
  `tools.js`. Treat any UI complaint about those as unverified.
- **Cancel** (`Esc` during a layout/check request) is exercised only through
  the abort-signal code path in `main.js`; no test names it and I did not
  drive it.
- **Cross-site protection** was verified by replaying request headers through
  urllib, not by a hostile page in a real browser, and not against a
  `Sec-Fetch-Site`-less browser that can still set `Content-Type:
  application/json` (no preflight restriction applies to `text/plain` only,
  so JSON is safe, but a non-browser local client is not covered by design).
- **A real crash/kill during a save** was not performed; atomicity is verified
  only through the patched-`os.replace` fault injection in the repo's test and
  my probe.
- **Windows-only result.** All of the above is Python 3.14.7 on Windows 11,
  which is where finding 3 comes from and where the four symlink tests skip.
  I did not run the suite on Linux, which is what CI uses.
- Investigation time was bounded (~35 minutes of wall clock, well past the
  ~20 minutes suggested); the last unchecked areas are listed above rather
  than searched further.

## Artifacts in this directory

| File | What it is |
| --- | --- |
| `FINDINGS.md` | this report |
| `CHECKPOINT.md` | state, what is done, what remains, for resumption |
| `probe_hdl.py`, `probe_layout_pin.py`, `probe_save.py` | dependency-free `unittest` probes; run `python -m unittest discover -s . -p "probe_*.py" -v` from this directory |
| `fixtures/always_case.v`, `fixtures/always_else.v`, `fixtures/wire_assign.v` | the Verilog that reproduces findings 1 and 2 |
| `probe-results.log` | probe run, 15 tests, 3 failures |
| `suite-unsandboxed.log` | the one trustworthy full-suite run: 439 tests, 5 failures, 4 skipped |
| `suite-discover.log`, `suite-discover-tempfix.log` | the two sandbox-blocked runs, kept only to show that the 108 `PermissionError`s were my environment |
