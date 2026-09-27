// Every key the editor answers to, for the sheet `?` opens.
//
// About thirty keys were documented only in DOCUMENTATION.md, which nobody has
// open while drawing. These rows are the same as the Keys table there, word
// for word less the backticks -- tests/test_js_editor.py fails if they drift.

export const SHORTCUTS = [
  ["V W E", "select tool, wire tool, eraser"],
  ["L B P T", "line, box, polygon, text"],
  ["click, Ctrl+click, drag a box", "select one, add or remove one, marquee"],
  ["drag", "move, snapped to the grid (a wire snaps to 5, so it can reach a pin)"],
  ["Ctrl+drag, Shift+drag a cell", "duplicate as you drag"],
  ["Ctrl+N", "new drawing"],
  ["drag a wire", "slide that run of it; the wire becomes hand-routed"],
  ["double-click a wire", "hand it back to the router"],
  ["drag a wire", "bend it: the drag point becomes a waypoint"],
  ["handles, Alt+handle", "resize with ratio locked / free"],
  ["arrows, Shift+arrows", "nudge one grid step / ten"],
  ["Ctrl+Z / Ctrl+Shift+Z", "undo / redo"],
  ["Ctrl+C Ctrl+X Ctrl+V Ctrl+D", "copy, cut, paste, duplicate"],
  ["Ctrl+G / Ctrl+Shift+G", "group / ungroup"],
  ["Ctrl+R / Ctrl+Shift+R", "rotate 90 clockwise / anticlockwise"],
  ["Ctrl+H / Ctrl+Shift+H", "flip horizontal / vertical"],
  ["Ctrl+] / Ctrl+[", "bring to front / send to back"],
  ["Delete, Esc", "delete, cancel and deselect"],
  ["Ctrl+A, Ctrl+0", "select all, fit to window"],
  ["F", "zoom to the selection, or to the sheet if nothing is selected"],
  ["Alt+drag", "move without any alignment help"],
  ["Ctrl+S, Ctrl+E", "save, export SVG"],
  ["Ctrl+Shift+E", "copy the drawing as a picture, for pasting into a slide"],
  ["scroll, Space+drag, Shift+drag", "zoom, pan, pan"],
  ["?", "show or hide this list"],
];

export function fill(table) {
  const rows = SHORTCUTS.map(([keys, what]) => {
    const row = document.createElement("tr");
    const key = document.createElement("th");
    key.textContent = keys;
    const text = document.createElement("td");
    text.textContent = what;
    row.append(key, text);
    return row;
  });
  table.replaceChildren(...rows);
}
