// Pointer behaviour for the select tool: click, marquee, move, resize.

import * as actions from "../actions.js";
import { handlePoints } from "../selection.js";
import * as symbols from "../symbols.js";

const DRAG_THRESHOLD = 3;

export class SelectTool {
  constructor(context) {
    this.ctx = context;
    this.mode = null;
    this.reset();
  }

  reset() {
    this.mode = null;
    this.origin = null;
    this.last = null;
    this.handle = null;
    this.startBoxes = null;
    this.startBounds = null;
    this.marquee = null;
    this.duplicated = false;
    this.moved = false;
  }

  cursorFor(target) {
    const handle = target && target.closest
      ? target.closest("[data-handle]") : null;
    if (handle) {
      const key = handle.getAttribute("data-handle");
      const cursors = {
        nw: "nwse-resize", se: "nwse-resize",
        ne: "nesw-resize", sw: "nesw-resize",
        n: "ns-resize", s: "ns-resize",
        e: "ew-resize", w: "ew-resize",
      };
      return cursors[key] || "default";
    }
    return target && target.closest && target.closest(".dl-cell")
      ? "move" : "default";
  }

  onPointerDown(event, point) {
    const { store, selection } = this.ctx;
    this.origin = point;
    this.last = point;
    this.moved = false;

    const handle = event.target.closest("[data-handle]");
    if (handle && selection.size) {
      this.mode = "resize";
      this.gestureLabel = "resize";
      this.handle = handle.getAttribute("data-handle");
      this.startBounds = selection.bounds();
      this.startBoxes = new Map(
        selection.cells().map((c) => [c.id, { x: c.x, y: c.y, w: c.w, h: c.h }]));
      return;
    }

    const node = event.target.closest(".dl-cell");
    if (node) {
      const id = node.getAttribute("data-id");
      if (event.shiftKey) {
        selection.toggle(id);
      } else if (!selection.has(id)) {
        selection.set([id]);
      }
      this.mode = "move";
      this.startBoxes = new Map(
        selection.cells().map((c) => [c.id, { x: c.x, y: c.y }]));
      // Ctrl-drag duplicates, the way it does in a slide editor. The copy is
      // made on the first actual movement, not on the click.
      this.pendingDuplicate = event.ctrlKey || event.metaKey;
      this.gestureLabel = this.pendingDuplicate ? "duplicate" : "move";
      return;
    }

    if (!event.shiftKey) selection.clear();
    this.mode = "marquee";
  }

  onPointerMove(event, point) {
    if (!this.mode) return false;
    const { store, selection } = this.ctx;
    const dx = point[0] - this.origin[0];
    const dy = point[1] - this.origin[1];

    if (!this.moved && Math.hypot(dx, dy) * this.ctx.zoom() < DRAG_THRESHOLD) {
      return false;
    }
    if (!this.moved && this.gestureLabel) store.beginGesture(this.gestureLabel);
    this.moved = true;

    if (this.mode === "marquee") {
      this.marquee = [
        Math.min(this.origin[0], point[0]), Math.min(this.origin[1], point[1]),
        Math.abs(dx), Math.abs(dy),
      ];
      this.ctx.drawOverlay({ marquee: this.marquee });
      return true;
    }

    if (this.mode === "move") {
      if (this.pendingDuplicate && !this.duplicated) {
        this.duplicate();
      }
      const step = actions.gridStep(store.doc);
      store.mutate(this.gestureLabel, (doc) => {
        for (const [id, start] of this.startBoxes) {
          const cell = doc.cells.find((c) => c.id === id);
          if (!cell) continue;
          cell.x = actions.snap(start.x + dx, step);
          cell.y = actions.snap(start.y + dy, step);
        }
      });
      return true;
    }

    if (this.mode === "resize") {
      this.applyResize(point, event.altKey);
      return true;
    }
    return false;
  }

  duplicate() {
    const { store, selection } = this.ctx;
    const clip = actions.copyCells(store.doc, selection.ids);
    const added = store.mutate(this.gestureLabel,
                               (doc) => actions.pasteCells(doc, clip, 0, 0));
    if (added) {
      selection.set(added);
      this.startBoxes = new Map(
        selection.cells().map((c) => [c.id, { x: c.x, y: c.y }]));
    }
    this.duplicated = true;
  }

  applyResize(point, freeAspect) {
    const { store, selection } = this.ctx;
    const box = this.startBounds;
    if (!box) return;

    const [bx, by, bw, bh] = box;
    const anchors = handlePoints(bx, by, bw, bh);
    const moving = anchors[this.handle];
    if (!moving) return;

    const fixed = {
      nw: anchors.se, se: anchors.nw, ne: anchors.sw, sw: anchors.ne,
      n: anchors.s, s: anchors.n, e: anchors.w, w: anchors.e,
    }[this.handle];

    const horizontal = this.handle.includes("e") || this.handle.includes("w");
    const vertical = this.handle.includes("n") || this.handle.includes("s");

    let scaleX = horizontal && Math.abs(moving[0] - fixed[0]) > 1e-6
      ? (point[0] - fixed[0]) / (moving[0] - fixed[0]) : 1;
    let scaleY = vertical && Math.abs(moving[1] - fixed[1]) > 1e-6
      ? (point[1] - fixed[1]) / (moving[1] - fixed[1]) : 1;

    // Gates look wrong stretched, so the ratio is locked unless Alt is held.
    if (!freeAspect) {
      const uniform = horizontal && vertical
        ? Math.max(Math.abs(scaleX), Math.abs(scaleY))
        : Math.abs(horizontal ? scaleX : scaleY);
      scaleX = uniform;
      scaleY = uniform;
    }

    scaleX = Math.max(0.05, Math.abs(scaleX));
    scaleY = Math.max(0.05, Math.abs(scaleY));

    store.mutate(this.gestureLabel, (doc) => {
      for (const [id, start] of this.startBoxes) {
        const cell = doc.cells.find((c) => c.id === id);
        if (!cell) continue;
        cell.x = fixed[0] + (start.x - fixed[0]) * scaleX;
        cell.y = fixed[1] + (start.y - fixed[1]) * scaleY;
        cell.w = Math.max(4, start.w * scaleX);
        cell.h = Math.max(4, start.h * scaleY);
      }
    });
  }

  onPointerUp(event, point) {
    const { store, selection } = this.ctx;

    if (this.mode === "marquee" && this.marquee) {
      const [mx, my, mw, mh] = this.marquee;
      const scale = Number(store.doc.canvas.symbolScale) || 1;
      const hits = [];
      for (const cell of store.doc.cells) {
        const symbol = symbols.get(cell.type);
        if (!symbol) continue;
        const [cx, cy, cw, ch] = symbols.cellBounds(symbol, cell, scale);
        if (cx >= mx && cy >= my && cx + cw <= mx + mw && cy + ch <= my + mh) {
          hits.push(cell.id);
        }
      }
      if (event.shiftKey) selection.add(hits);
      else selection.set(hits);
    }

    if (this.mode === "move" && !this.moved && !event.shiftKey) {
      const node = event.target.closest(".dl-cell");
      if (node) selection.set([node.getAttribute("data-id")]);
    }

    const changed = this.moved;
    store.endGesture();
    this.reset();
    this.ctx.drawOverlay();
    return changed;
  }
}
