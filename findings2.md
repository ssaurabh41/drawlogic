# Review of the findings1 fixes

Audited revision: `d00a3f6222a71a1ce02564d5c6b2a8d6c47f1bd5` on `main`.
Compared with `558ccaf`, which introduced `findings1.md`.

The fixes substantially improve the implementation. The clean tracked checkout passes **637 tests, 0 failures, 5 skips**. Fresh focused checks confirm the ordinary workflows repaired by the commits. However, three reproducible defects remain, detailed below. They are incomplete coverage or previously missed weaknesses; this review does not claim that all three were introduced by the fixes.

Only this report is committed by the review. Application code and existing user diagrams were left unchanged.

## Status of findings1

| Original finding | Result of this review |
|---|---|
| 1. Extracting a linked instance breaks nested refs | Original reproduction fixed: extracted `components/sm.dlg` becomes `sm.dlg`, and the definition reopens cleanly. Custom-symbol dependencies remain a separate issue below. |
| 2. Repeated layout drifts with notes | Unpinned Row, Column, Grid and Flow reproductions fixed. A pinned-cell variant still drifts; see R2. |
| 3. Undo Make independent loses the old sheet symbol | Ordinary undo fixed: merging retained sheet symbols leaves the restored ref drawable. |
| 4. Cross-document paste loses named styles | Ordinary copy/paste carries definitions and remaps conflicts, preserving both the pasted look and the destination style. |
| 5. Fit ignores text annotation bounds | Original reproduction fixed: the container now measures the rendered note, including its style. |
| 6. A pin disables top-to-bottom Flow | Original one-pin chain fixed: a=(200,200), b=(200,292), c=(200,384), with the pin unchanged. |
| 7. Cross-document linked paste loses reference context | Ordinary Copy fixed. Duplicate leaves an unmarked global clipboard and bypasses the fix; see R1. |
| 8. Paste adopts an unrelated container with the same ID | Ordinary Copy fixed. The Duplicate clipboard still adopts it; see R1. |
| 9. Named-font text clipped in cropped export | Original reproduction fixed: effective text bounds are included in the crop. |
| 10. Repeated hierarchies cause excessive file reads | Original nine-file fixture now needs 9 loads instead of 29,125. |

## R1 — P2: Duplicate leaves a clipboard that bypasses cross-document protections

**Location:** `drawlogic/web/js/main.js:2725` (Ctrl+D handler), with `model.clipFor()` and `model.pasteItems()` in `drawlogic/web/js/model.js`.

**Impact:** After duplicating an item, pasting into another drawing can produce an invisible linked instance, save the wrong component reference, and attach it to an unrelated container. The three symptoms share one missing clipboard-origin field, so they are one finding.

**Reproduction, verified in Chromium with real keyboard input:**

1. Open `a/top.dlg`. It contains a linked cell `sm0`, ref `components/sm.dlg`, owned by container `k1`. The definition exists at `a/components/sm.dlg`.
2. Select `sm0` and press Ctrl+D.
3. Open `b/top.dlg`, which has its own unrelated container `k1` and no linked symbols.
4. Press Ctrl+V and save.

The destination saves a cell with:

```json
{
  "id": "c1",
  "parentId": "k1",
  "type": "sheet",
  "ref": "components/sm.dlg",
  "x": 210,
  "y": 210
}
```

The drawing contains zero rendered cells. The correct ref would be `../a/components/sm.dlg`; the unrelated `parentId` should be absent. On reopen, the saved ref looks under `b/components/`.

**Cause:** Ordinary `copySelection()` now supplies `store.path` and captures `geometry.sheetData()`. Ctrl+D still assigns the shared `clipboard` using `copyItems(store.doc, selection.ids)` without either. An undefined `clip.from` explicitly means same-document in `clipFor()` and `pasteItems()`, even after switching tabs. It also supplies no sheet symbols and triggers no reference refresh.

**Suggested fix:** Route every assignment to the shared clipboard through one helper that records origin and sheet symbols. Alternatively, keep Duplicate's temporary clip local and preserve the previous user clipboard. Continue allowing unmarked clips only for internal operations that cannot cross documents, such as Repeat.

**Regression test:** Exercise Ctrl+D, switch documents, Paste, Save, and reopen. Check the reference, owner, rendered symbol and unchanged original file. Include a destination with a conflicting same-name component, so a wrong visible symbol is caught as well as an invisible one. A test calling only `copyItems(..., sourcePath)` will miss the faulty keyboard handler.

## R2 — P2: pinned cells make notes drift on every packed-layout run

**Locations:** `drawlogic/layout.py:1723` and `_pack_level()` at `drawlogic/layout.py:1835`.

**Impact:** Repeated Layout contents moves an annotation away from stable cells and grows its container indefinitely. Reproduced in Row, Column and Grid. The unpinned fix does not cover this combination.

**Minimal fixture:**

```python
from drawlogic import layout
from drawlogic.doc import new_document
from drawlogic.symbols import default_registry

doc = new_document("pins and notes")
doc.data["containers"] = [{
  "id": "k", "x": 100, "y": 100, "w": 600, "h": 500,
  "layout": {"mode": "row"}
}]
doc.cells.extend([
  {"id": "a", "type": "inv", "x": 120, "y": 152,
   "parentId": "k", "pinned": True},
  {"id": "b", "type": "inv", "x": 400, "y": 300, "parentId": "k"}
])
doc.shapes.append({
  "id": "note", "kind": "text", "x": 140, "y": 190,
  "text": "annotation", "parentId": "k"
})
doc.normalize()
for _ in range(4):
  layout.arrange(doc, default_registry(), container="k")
  print(doc.shapes[0]["y"])
```

Observed note y positions: **260, 330, 400, 470**. After the first layout, the cells remain at a=(120,152), b=(120,222). Container heights grow **182.8, 252.8, 322.8, 392.8**.

**Cause:** `before` includes pinned and movable nodes, but `_pack_level()` returns positions only for movable nodes. The annotation adjustment compares `_corner(before.values())` with `_corner(after.values())`. Thus the old corner stays anchored on the pin at y=152 while the new corner starts at the movable cell at y=222. Every run invents another 70-unit movement, even when no cell moves.

**Suggested fix:** Compare matching populations. For example, construct a complete post-layout position map with unchanged positions for fixed nodes before calculating the annotation delta. Preserve pinned coordinates and verify idempotence rather than shifting the entire subtree to hide the error.

**Regression tests:** Run each packed mode at least twice with a pinned cell defining the upper/left corner and an owned note. Assert identical document state after the first layout, fixed pinned coordinates, and stable note-to-content position. Also cover a fixed child container containing a pinned descendant, since it follows the same path.

## R3 — P2: component extraction loses folder-local custom symbols

**Locations:** `drawlogic/components.py:180`, `drawlogic/server.py:508`, and `drawlogic/sheets.py:274`.

**Impact:** A valid selection containing a custom palette symbol can be extracted successfully, yet its new definition fails to validate or export independently. This matters for architecture diagrams built with custom SM, cache or memory-controller symbols.

**Reproduction:**

1. Put a custom `custom_sm` symbol in `symbols.json` beside `top.dlg`.
2. Place a `custom_sm` cell in `top.dlg`. Open it normally with `sheets.open_document()`; validation returns no errors.
3. Create component `GPC` from that cell using the editor's component handler.
4. Open `components/gpc.dlg` independently, using the ordinary folder-loading rules, and validate it.

Observed handler response: **200**, with `problems: []`. Reopened definition:

```text
error: cell sm: unknown cell type 'custom_sm'
```

The reproduction invoked the real `_component()` handler with captured responses and temporary files. It did not substitute a mock extraction implementation.

**Cause:** Extraction copies cell objects but neither relocates their custom symbol definitions nor supplies a persistent dependency mechanism. Standalone loading reads `symbols.json` only from the definition's own directory, now `components/`. The new pre-write check calls `sheets.resolve()` using the server's already-loaded registry; that checks sheet references, not ordinary unknown cell types, and does not establish that the definition will work in its destination environment.

This is a previously missed dependency weakness, not a failure of the new relative-sheet-ref arithmetic.

**Suggested fix:** Establish how custom-symbol dependencies travel with extracted definitions. A straightforward option is to make required definitions available in the destination folder's symbol library, reusing identical entries and handling conflicts without overwriting unrelated symbols. Then validate the proposed child with a registry constructed under the same rules as a fresh standalone open. If preserving dependencies is not implemented yet, refuse the operation with a clear message before writing a broken definition.

**Regression tests:** Extract a custom cell and export/validate the generated definition with a fresh registry. Include a destination `symbols.json` containing a conflicting same-name symbol. Confirm both source and destination drawings retain their intended artwork and pins.

## Additional weaknesses to consider

These are design or coverage concerns, not additional confirmed defects:

- Sheet symbols are retained by merging every server response. The ordinary undo regression is repaired, but retained historical entries have no explicit lifetime/version policy. Add tests for undo/redo after a referenced definition changes, and for stale asynchronous refresh responses, before relying on this cache as a complete history solution.
- Style equality uses `JSON.stringify()`. Equal objects with different property insertion order can create unnecessary `(... pasted)` styles. Canonical comparison would improve behavior for hand-edited DLG files, though appearance is preserved.
- Several new editor tests exercise helpers directly. The Duplicate finding shows why a small number of real keyboard/tab workflows are also needed.
- Multiple pinned stages can make top-to-bottom dependency order impossible at their fixed coordinates. The new code deliberately pushes movable rows below collisions; do not treat every resulting upward connection as a defect without checking whether the requested constraints are feasible. A clear explanation when constraints conflict would help users.

## Verification

- Full existing suite in an isolated checkout made with `git archive` at the audited revision: **637 tests, 0 failures, 5 skips, 56.1 seconds**. This avoids incorporating the user's older untracked GPU artwork into the regression corpus.
- Original Python reproductions rerun: relative refs, unpinned annotation stability, text bounds, pinned vertical Flow, styled crop bounds, repeated-hierarchy reads.
- Focused Node checks: normal cross-document ref/style/ownership transfer, retained symbol after undo, and the Duplicate clipboard failure.
- Chromium: real Ctrl+D, document switch, Ctrl+V and Ctrl+S; captured saved document and verified that the pasted instance was not rendered.
- Focused Python checks: four packed-layout runs per mode, and custom-symbol extraction through the actual component handler followed by standalone reopen/validation.

The supporting scripts and screenshot were retained as review-session artifacts, not added to the application repository. The minimal reproduction and expected outcomes above are sufficient to create regression tests alongside the fixes.
