# Findings 3: verified defects and usability review

Reviewed commit: `aca5f90` on main, fetched October 24, 2026. Compared with `69ae6a1`, the findings2 report. No application source was modified.

## Verification of findings2

| Issue | Verification | Result |
|---|---|---|
| Duplicate overwrites the shared clipboard with an unmarked copy | Real Chromium input: Copy a linked cell, Duplicate, switch folders/tabs, Paste, Save. Saved ref was `../a/components/sm.dlg`, no unrelated parentId, one rendered cell. | Fixed for the reproduced workflow. Duplicate now uses a private clip and leaves Copy intact. |
| Packed layout drifts with pinned cells and notes | Repeated Row, Column and Grid four times. Note y stayed 190 on every run; fixed cells stayed fixed. | Fixed for the reproduced workflow. |
| Extracted custom symbols are unavailable when reopened independently | Invoked the actual component handler, opened the generated definition with a fresh standalone registry, and validated it. | Original standalone-open failure fixed. Browser integration and built-in name conflicts still need work; see B1 and B2. |

Historical full suite in a clean tracked checkout: **644 tests, 0 failures, 5 skips, 63.5 seconds**. The subsequent independent verification audit did not rerun that suite; it reran six focused commands, all completing successfully. These reproduce the four defects below and verify the repaired workflows above. A successful defect reproduction confirms an application bug, not correct behavior.

The independent review strengthened the original evidence by adding explicit pinned-cell coordinate assertions and a fresh browser test of heading focus. An initial browser fixture failed before reaching the heading field; it was corrected to select a block and verify that Heading/Text controls existed before testing Tab. The corrected run reproduced focus landing on BODY. Reviewer inspection accepted the resulting evidence, and tracked application source remained unchanged.

## Confirmed defects

### B1 — P1: copying a custom symbol can break unrelated existing diagrams

Location: `drawlogic/components.py:341` (`carry_symbols`); shared library write in `drawlogic/server.py:553`.

**Reproduction:**

1. The source folder's `symbols.json` overrides the built-in ID `inv` with a custom block whose input is `custom_in`. Local library overrides are supported by the symbol loader.
2. `components/existing.dlg` already contains ordinary built-in inverters wired via pins `y` and `a`. It has no local library and validates successfully when opened independently.
3. Extract the source custom block into `components/newpart.dlg`.
4. Reopen the untouched `components/existing.dlg` independently.

Creation returns 200, but the existing sibling now reports:

```text
error: net n: from endpoint refers to pin 'y', which inv has no such pin (has: custom_in)
error: net n: to endpoint refers to pin 'a', which inv has no such pin (has: custom_in)
```

The sibling's DLG bytes were unchanged. The generated `components/symbols.json` now overrides `inv` for every drawing in that folder.

**Cause:** Collision detection checks only entries already present in the destination JSON file. It ignores names supplied by the destination's built-in/base registry. A missing JSON entry does not mean that symbol ID is unused.

**Fix:** Check against the destination's effective symbol namespace, including built-ins and configured base libraries. Rename the incoming custom definition when its meaning differs; rewrite only the new definition's cells. Preserve sibling diagrams' effective symbols and interfaces. Test an existing wired sibling before and after extraction, not only the new child.

This is a regression risk introduced by the new shared-library copying behavior. It is high priority because an operation on one component can change other diagrams without editing their DLG files.

### B2 — P2: generated definitions with renamed custom symbols are invisible in the editor

Location: `drawlogic/server.py:312` (`GET /api/doc` response), particularly the response that includes only `sheet:` entries; browser library loading in `drawlogic/web/js/main.js`.

**Reproduction:**

1. Source `symbols.json` defines `custom_sm`.
2. Destination `components/symbols.json` already defines a different `custom_sm`.
3. Extract a source instance. The new conflict logic correctly copies it as `custom_sm_2` and rewrites the child's type.
4. Open the generated `components/gpc.dlg` in the browser, as through Edit component definition.

Standalone CLI loading and validation succeed. In Chromium, the child contains one cell but renders **zero**. Browser geometry has `custom_sm` from the served root and lacks `custom_sm_2`.

**Cause:** The server loads the destination's library when reading the document, but sends only resolved sheet symbols to the browser. The browser's ordinary palette/symbol library still comes from the served root. Thus the file fix is not propagated through the editor's document-loading contract. The same underlying problem can misrender an unrenamed folder-local type when its definition differs from the root's.

**Fix:** Deliver and switch the full effective per-document symbol registry, or a complete override set, when opening/switching tabs. Keep different folders' definitions isolated. Audit layout/check/export endpoints for the same source-folder dependency, as several start from the server registry rather than a document-local registry. Test extraction, Edit definition, browser rendering, and tab switching with conflicting local symbol IDs.

Confirmed with the actual component handler, a fresh standalone open, and a real browser session. See `custom-definition-missing.png` and `custom_browser.py` beside this report.

### B3 — P2: changing palette choices before placement silently disables placement

Locations: `drawlogic/web/js/main.js:2267`, `main.js:187`, and `drawlogic/web/js/tools.js:671`.

**User steps:**

1. Start in Select mode.
2. Click `block` in the symbol palette.
3. Before placing it, change your mind and click `inv`.
4. Click the canvas.

No cell is added. The interface still says to click the canvas to place the chosen symbol. Escape, choose a symbol again, then place works.

**Cause:** `onPick` arms the new type before calling `setTool("place")`. If Place is already active, `setTool` calls its `onDeactivate()`, clearing the newly armed type. The tool is active with no type to place.

**Fix:** Activate/deactivate before arming, or avoid deactivating a tool when remaining in that tool while changing its options. Test switching between palette choices, selecting the same symbol twice, and changing choices after Shift-place.

Found while trying to place blocks in the actual editor, then independently reproduced with trusted Chromium mouse input. In the independent empty-drawing test, switching from Block to Inverter and clicking the canvas added zero cells; Escape, choosing Inverter again, and placing added one. Selecting the same symbol twice follows the same source-code path, but that variant was not independently exercised.

### B4 — P2: committing a heading destroys keyboard focus

Locations: `drawlogic/web/js/panels.js:1067` and `panels.js:1089`.

**User steps:**

1. Select a block.
2. Edit its Heading field in Properties.
3. Press Tab to continue into Text.

The heading commits, but focus lands on the page body instead of the next field. The measured active element was `{tag: "BODY", cls: ""}`. Clicking Text explicitly and typing then works.

**Cause:** Heading and text change handlers rebuild the inspector while the browser is completing the focus transition. The current and next controls are replaced. This interrupts normal keyboard entry and can leave subsequent keys eligible for canvas shortcuts instead of text input. The focus loss is confirmed; unintended shortcut actions were not needed to establish the finding.

**Fix:** Update geometry/readouts without replacing the editing controls, or restore focus using stable field identity and intended tab direction after a render. Test Heading → Tab → Text, Shift+Tab, clicking directly from Heading to Text, and multiline text commit.

## What I exercised in the editor

Used Chromium with actual mouse and keyboard input rather than changing document state through injected application code:

- Started with a blank drawing, placed a block, and edited its heading and body text.
- Repeated it into a 2×2 grid, selected the blocks, created and named a container, chose Grid layout, and applied Layout contents.
- Created a linked component from the selection, opened its definition, edited a block, and saved. The parent reported that it refreshed.
- Connected an output pin to another block's input, producing one net.
- Saved and exported SVG successfully to a temporary served-folder path.
- Separately checked cross-document Copy/Duplicate/Paste and generated custom-symbol definitions.

All fixture files and exports were created in temporary/audit folders. The user's existing diagrams were not edited. Automated locator retries during pin clicking were resolved with actual pointer coordinates; those automation failures are not counted as product defects.

## Usability feedback, separate from bugs

These are task-based observations and recommendations, not claims that a representative human-user study was conducted.

### 1. Make SVG export deliver a file to the user

**Observed:** Export SVG opens a native prompt saying “Export SVG to (relative to the served folder)” and reports a server-side path after success. It does not download the SVG. This is awkward when the editor is running remotely and the user wants a diagram for a slide or document.

**Recommendation:** Make Download SVG the primary action. Keep “Save on server” as a secondary option. Show the resulting filename and offer Open/Download after export. The existing render-without-writing endpoint can support this without a new renderer.

### 2. Give Repeat a small preview and explicit counts

**Observed:** Repeat is a form with Rows, Columns, gaps, prefix and starting index. There is no live preview, final count, or indication of which visible text will be numbered. I had to apply it to see the result.

**Recommendation:** Show “4 total, 3 new” and a simple thumbnail grid as values change. Show a naming example such as “SM 1 … SM 4.” Make clear that the original is included. Preserve one-step undo.

### 3. Clarify Name, Heading, Copies and Repeat

**Observed:** The cell has an external Name and an internal Heading. Repeat numbered the external names while the internal heading stayed `SM`. The inspector's “Copies” control is another concept: a visual stack rather than separate editable instances.

**Recommendation:** Use labels such as “Instance label (outside)” and “Heading (inside).” Rename Copies to “Stack appearance.” Add a concise explanation next to Repeat: “Create separate instances.” These small wording changes avoid surprising results without adding controls.

### 4. Put common architecture styling near the top

**Observed:** On a 1440×1000 viewport, the block inspector opens several sections: Cell, Geometry, Text inside, Appearance and Drawing. Styling requires substantial scrolling; unrelated sheet settings occupy the same panel. Collapsible sections exist and are useful, but the initial arrangement emphasizes coordinates over authoring.

**Recommendation:** Offer a compact common-controls area for label, heading, fill, text size and named style. Keep detailed geometry and sheet settings in collapsible sections or the existing Sheet controls. Remember the user's preference; do not remove precise numeric controls.

### 5. Give repeated architecture groups a useful starting layout

**Observed:** After making a container around an intentionally repeated grid, its default layout mode is Flow by wiring. To preserve a grid on the next layout, I needed to change Arrange to Grid first. This is a reasonable circuit default but an extra step for architecture diagrams.

**Recommendation:** Let container creation preserve/infer a simple existing row/grid, or offer a small choice such as “Keep this grid / Arrange by wires.” Add a few presets like SM grid, pipeline row and memory-bank column, using the existing layout engine.

### 6. Help users create component interfaces

**Observed:** Creating a linked component from unconnected blocks correctly explains that no wires cross the selection, so the component has no ports. A new architecture-diagram user still needs to know how to open the definition and add port cells before connecting the component itself.

**Recommendation:** Keep the existing explanation and add an action such as “Create and add ports” or a short next-step hint in the new instance's inspector. Show Inputs/Outputs in user-facing language alongside the technical port names.

### 7. Associate field labels with their controls

**Observed in the DOM:** Many inspector labels are spans, and the Repeat form's labels lack `for`/input IDs. Visible text is not consistently an accessible name for its field. I did not run a screen-reader session, so this is an accessibility implementation finding rather than a claimed screen-reader experience.

**Recommendation:** Use real labels with stable IDs or `aria-labelledby`. Test accessible names for Heading, Name, Rows, Columns and Gap. This also makes keyboard/automation tests more robust and complements the focus fix.

### 8. Explain contextually disabled actions

**Observed:** Edit component definition and Make independent are disabled for an ordinary block; Layout contents is disabled when cells rather than a container are selected. The distinction makes sense once learned, but the disabled menu does not explain it at the point of use.

**Recommendation:** Provide short reasons such as “Select one linked component” or “Select a container.” Distinguish plain blocks, containers and linked instances clearly in the inspector heading.

## Priorities

1. Prevent symbol copying from changing unrelated diagrams (B1).
2. Complete per-document symbol handling in the editor (B2).
3. Fix palette switching and inspector focus (B3/B4): both interrupt routine work.
4. Improve Download SVG, Repeat feedback, and naming terminology.
5. Add presets and contextual guidance after the core editing paths are reliable.

Useful existing behavior: Repeat is easy to locate; container creation opens an inline title editor; Grid layout produced a tidy 2×2 group; linked-definition edits refreshed the parent; ordinary Copy/Paste now preserves reference identity. These should remain simple as the issues above are fixed.

## Independent verification record

Audited baseline: `aca5f901722c47f5197afe8d7bc4fce80dda215a`.

| Focused check | Outcome |
|---|---|
| Copy, Duplicate, cross-folder Paste and Save in Chromium | Exit 0; correct rebased ref, no unrelated parent, one visible cell. |
| Repeated packed layout and uncomplicated custom-symbol extraction | Exit 0; stable notes and standalone child validates. |
| Explicit pinned-coordinate check | Exit 0; pin remains at (120,152) over four runs in each of Row, Column and Grid. |
| Custom built-in override collision | Exit 0; reproduces missing-pin errors in an otherwise unchanged sibling drawing. |
| Generated custom-symbol definition in Chromium | Exit 0; reproduces zero rendered cells despite valid standalone loading. |
| Palette switching and Heading-to-Tab in Chromium | Corrected run exits 0; reproduces both editing failures. |

The original full-suite result is historical, as stated above. No new unsupported bug count was inferred from test success. The usability section remains a set of observed workflow recommendations, not a representative human-user study or additional confirmed defects.

Scripts, command logs, screenshots, a sample SVG and editable fixtures were retained as audit-session artifacts. They are not included in this documentation-only commit. Reproduction steps and expected outcomes are recorded above so regression tests can be implemented alongside the fixes.

This is a targeted audit, not proof that the rest of the application is bug-free. No application code fixes were made during this review.
