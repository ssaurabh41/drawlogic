// Placing a cell from the palette.
//
// Pick a symbol, then click the canvas. The tool stays armed so a run of the
// same gate can be dropped in without going back to the palette each time.

import * as actions from "../actions.js";

export class PlaceTool {
  constructor(context) {
    this.ctx = context;
    this.type = null;
  }

  arm(type) {
    this.type = type;
  }

  cursorFor() {
    return "copy";
  }

  onPointerDown(event, point) {
    if (!this.type) return;
    const { store, selection } = this.ctx;
    const cell = store.mutate("place",
                              (doc) => actions.addCell(doc, this.type, point[0], point[1]));
    if (cell) {
      selection.set([cell.id]);
      this.ctx.say(`placed ${cell.label || cell.type}`);
    }
    // Shift keeps placing; a plain click drops one and returns to selecting.
    if (!event.shiftKey) this.ctx.setTool("select");
  }

  onPointerMove() { return false; }

  onPointerUp() { return false; }

  onDeactivate() {
    this.type = null;
  }
}
