# Drawlogic audit recheck and extended review

Reviewed commit: `e912c74` (unchanged from the original audit). Findings apply to the audited revision. No application code was changed during the review.

## Verdict on the original audit

All six defects remain supported. Fresh Python reproductions confirm findings 1, 2, 5 and 6; fresh JavaScript reproductions confirm 3 and 4. For finding 3, this pass reproduced the Store/geometry state transition and inspected the actual UI integration; it did not repeat the previous audit's Chromium session. The original reproduction scripts were unavailable during the recheck, so fresh focused reproductions were written.

| ID | Severity | Confirmed defect | Evidence from this pass |
|---|---|---|---|
| 1 | P1 | Extracting a linked instance breaks its nested relative reference | Reopening reports `error: cell sm0: no such drawing: components/sm.dlg`. |
| 2 | P2 | Layout contents drifts when owned notes sit above/left of cells | Container origin becomes (50,30), (0,-40), (-50,-110). Reproduced in Row, Column, Grid and Flow. |
| 3 | P2 | Undo Make independent restores the ref but loses its symbol | After Undo the ref is `components/sm.dlg`, while `geometry.forCell()` returns null. |
| 4 | P2 | Cross-document paste drops or changes named formatting | Missing destination style removes inherited appearance; same-name red style replaces green. |
| 5 | P2 | Fit to contents treats text annotations as points | Container becomes 40 units wide while text spans x=100 to x=844. |
| 6 | P2 | Pinning disables Flow / Top to bottom | Unpinned stages are vertical; pinned case puts b=(400,400), c=(560,400). |

P1 means high priority because a core creation workflow produces a broken saved hierarchy; it does not imply irreversible data loss. P2 means a substantive correctness or performance defect under the documented conditions.

### Refinements to the original recommendations

- **1:** Rebase references against the destination definition folder. Validate using a fresh registry at that destination, not the parent's already-resolved registry. The server's `_write_and_answer` currently ignores resolution issues: include those issues in the response and avoid reporting an invalid creation as successful. Add save/reopen coverage.
- **2:** Preserve the selected container's anchor while accounting for notes in layout. Do not blindly translate a subtree that contains pinned cells. Test both repeated-run stability and fixed coordinates.
- **3:** Keep reference resolution consistent with history. Re-resolving restored refs or restoring a suitable sheet registry are options; if asynchronous, reject stale responses after a tab switch or subsequent edit.
- **4:** Carry used named styles in clipboard metadata and remap conflicting names without overwriting destination styles.
- **5:** Share effective text-bound measurement across Fit, resize protection and export, in Python and JavaScript. Cell bodies intentionally differ from visible label extents; decide that policy explicitly rather than treating every omitted label as a separate confirmed bug.
- **6:** Honor vertical direction with fixed cells. A UI limitation message would only be an interim mitigation, not completion of the requested combination.

## Additional confirmed defects

### 7. P2: linked instances pasted between drawings disappear or refer to a different definition

Locations: `drawlogic/web/js/main.js:441`, `drawlogic/web/js/model.js:952`.

Copy a linked instance into another open drawing. Clipboard data preserves its literal `ref`, but carries no source path. Paste does not resolve the new reference. If the destination registry lacks that ref, `geometry.forCell()` returns null and the instance has no drawable symbol. If the destination already resolves the same string, it uses that destination symbol. When drawings are in different folders, `components/sm.dlg` can refer to a different file, or no file at all, after saving/reopening.

This is separate from named-style loss: it changes the component's identity and pins, not just its appearance.

**Fix:** Store the source drawing path in clipboard metadata, rebase references relative to the target drawing, and resolve pasted references before finishing the operation. For an unsaved destination, explicitly handle the missing base path. Keep definitions within the served root. Test same-folder/different-folder copies, a destination with no sheet symbols, and an identical ref string resolving to a different definition.

### 8. P2: cross-document paste silently adopts an unrelated container

Location: `drawlogic/web/js/model.js:991`.

Copy a cell owned by container `k1`, without copying that container. Paste into another document that happens to have its own `k1`. The pasted cell keeps `parentId: k1`, even if that destination container is somewhere else on the page. A later drag/layout/delete-with-contents acts on this unexpected member.

The reproduction pastes at (120,120) into a document whose unrelated `k1` starts at (1000,1000); the pasted cell still belongs to it. IDs such as `k1` are generated locally and commonly repeat between drawings.

**Fix:** Preserve an uncopied parent only for same-document duplication/paste, using stable document identity. Across documents, retain only relationships to copied/remapped containers, or an explicitly chosen destination owner. Test cross-document ID collisions and same-document duplication separately.

### 9. P2: cropped exports cut off text using named font styles

Location: `drawlogic/doc.py:802`.

Create a text annotation `GPU ARCHITECTURE OVERVIEW` at (100,150), with `styleRef: big` and named `style.fontSize: 60`. Rendering resolves the named style, but `content_bbox()` calls `text_shape_box(shape)` on the raw shape, without the named style or document font scale.

Measured rendered bounds are (100,102)-(1030,162). The crop viewBox is `76 114.8 265 62`, ending at x=341 and clipping most of the title and part of its height. This also affects canvas sizing that relies on content bounds. Explicit document font scaling follows the same faulty measurement path.

**Fix:** Measure `styles.effective(doc.styles, shape)` using `doc.font_scale`. Audit other bounds consumers for the same raw/effective-style mismatch. Add a cropped-SVG test asserting the viewBox contains the effective text bounds with margin.

### 10. P2: repeated component hierarchies trigger excessive recursive file reads

Locations: `drawlogic/sheets.py:344`, `drawlogic/sheets.py:352`, `drawlogic/sheets.py:364`.

Each definition in the test places four instances of the same next-level definition. All instances are valid and reuse a small set of files. Resolution deduplicates at depth zero, but recursively walks repeated references at deeper levels; miniature generation also resolves descendants. There is no per-operation parsed-document cache or completed-subtree reuse.

| Unique definition files | Document.load calls |
|---:|---:|
| 3 | 7 |
| 4 | 28 |
| 5 | 113 |
| 6 | 454 |
| 7 | 1,819 |
| 8 | 7,280 |
| 9 | 29,125 |

The nine-file case took about 1.29 seconds locally with minimal definitions. Timings vary; the load counts establish the scaling problem. Real definitions add routing/preview work. Deeper repeated hierarchies can make Open, Refresh and export slow despite very few unique files.

**Fix:** Use a request-scoped cache keyed by canonical file path for parsed definitions. Reuse validated subtrees and preview data where their context allows. Keep active recursion-stack cycle detection separate from completed-node caching, and retain confinement/depth checks. Do not use an indefinite cache that makes Refresh stale. Add an instrumented repeated-hierarchy test that bounds read counts, rather than a timing-only assertion.

## Other weaknesses and boundaries

- **Shallow independence is a design limitation, not an additional confirmed defect.** Make independent copies the immediate definition; references inside it remain shared. Documentation promises an immediate-definition copy. Clarify this in the UI for nested GPC/SM designs before considering a separate deep-copy option.
- **Preview fidelity is limited by design.** Miniatures depict boxes and wires, not the complete styled artwork. This may limit NVIDIA-style presentation, but is not counted as a correctness regression.
- **The test coverage gap is integration-heavy.** Existing tests cover individual features, but omit cross-document identity/style/reference transfer, undo after registry replacement, layout idempotence with notes and pins, effective-style crop bounds, and repeated hierarchy scaling.

## Validation and artifacts

Existing targeted tests: **72 passed** (57 container/component/editor checks plus 15 style tests). The original report's full-suite result of 625 tests with 5 skips is historical; this pass did not rerun the full suite.

Fresh Python and JavaScript reproductions produced the evidence above. Those scripts and raw outputs were retained as audit-session artifacts and are not included in this repository commit. The Python script printed diagnostic evidence; the JavaScript script also asserted selected failure states. These were defect reproductions, not fixed-behavior regression tests.

Recommended implementation order: reference relocation and clipboard identity; registry/history consistency; text measurement and stable layout; hierarchy caching. Convert each reproduction into an expected-correctness regression test alongside its fix.
