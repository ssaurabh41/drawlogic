// Pointer behaviour, one class per tool.
//
// Usage:
//
//   const tools = makeTools(context);   // { select, wire, place, shape }
//   tools.select.onPointerDown(event, [docX, docY]);
//
// A tool owns only its gesture. Anything that changes the document calls
// through context.store.mutate, so undo works the same however an edit began.

import * as geometry from "./geometry.js";
import * as guides from "./guides.js";
import * as model from "./model.js";
import * as routing from "./routing.js";
import { handlePoints } from "./selection.js";

const DRAG_THRESHOLD = 3;
const PIN_SNAP = 14;

// How close, in screen pixels, a drag has to come before it is pulled into
// line. Screen pixels rather than sheet units, so the pull feels the same
// however far you are zoomed in.
const SNAP_PIXELS = 8;

// ---- select, move, resize ----

export class SelectTool {
  constructor(context) {
    this.ctx = context;
    this.reset();
  }

  reset() {
    this.mode = null;
    this.origin = null;
    this.handle = null;
    this.startBoxes = null;
    this.startBounds = null;
    this.marquee = null;
    this.duplicated = false;
    this.moved = false;
    this.waypointNet = null;
    this.run = null;
  }

  cursorFor(target) {
    const handle = target && target.closest ? target.closest("[data-handle]") : null;
    if (handle) {
      return {
        nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize",
        n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
      }[handle.getAttribute("data-handle")] || "default";
    }
    if (target && target.closest && target.closest(".dl-net, .dl-hit")) return "crosshair";
    return target && target.closest && target.closest(".dl-cell, .dl-shape")
      ? "move" : "default";
  }

  onPointerDown(event, point) {
    const { store, selection } = this.ctx;
    this.origin = point;
    this.moved = false;

    const handle = event.target.closest("[data-handle]");
    if (handle && selection.size) {
      this.mode = "resize";
      this.gestureLabel = "resize";
      this.handle = handle.getAttribute("data-handle");
      this.startBounds = selection.bounds();
      this.startBoxes = new Map(selection.ids.size
        ? [...selection.ids].map((id) => {
          const item = model.itemById(store.doc, id);
          return [id, JSON.parse(JSON.stringify(item))];
        }) : []);
      return;
    }

    const node = event.target.closest(".dl-cell, .dl-shape");
    if (node) {
      const id = node.getAttribute("data-id");
      if (event.shiftKey) selection.toggle(id);
      else if (!selection.has(id)) selection.set([id]);

      this.mode = "move";
      this.startBoxes = new Map([...selection.ids].map((id2) => {
        const item = model.itemById(store.doc, id2);
        return [id2, JSON.parse(JSON.stringify(item))];
      }));
      // Ctrl-drag duplicates, the way it does in a slide editor. The copy is
      // made on the first actual movement, not on the click.
      this.pendingDuplicate = event.ctrlKey || event.metaKey;
      this.gestureLabel = this.pendingDuplicate ? "duplicate" : "move";
      return;
    }

    // Dragging a wire slides the run you grabbed. A net is one path with a
    // subpath per branch, so the element alone does not say what was grabbed;
    // the nearest run did.
    const wire = event.target.closest(".dl-net, .dl-hit");
    if (wire) {
      this.waypointNet = wire.getAttribute("data-id");
      this.run = model.grabRun(store.doc, this.waypointNet, point);
      if (this.run) {
        this.mode = "waypoint";
        this.gestureLabel = this.run.horizontal ? "move wire" : "move wire";
      }
      selection.clear();
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

    if (this.mode === "waypoint") {
      const step = model.gridStep(store.doc);
      // A horizontal run moves in y and a vertical one in x: a run slides
      // across itself, it does not travel along itself.
      const value = model.snap(this.run.horizontal ? point[1] : point[0], step);
      store.mutate(this.gestureLabel,
                   (doc) => model.slideRun(doc, this.waypointNet, this.run, value));
      return true;
    }

    if (this.mode === "move") {
      if (this.pendingDuplicate && !this.duplicated) this.duplicate();
      const step = model.gridStep(store.doc);
      const sdx = model.snap(dx, step);
      const sdy = model.snap(dy, step);
      // Alt is the escape hatch: hold it to place a cell exactly where you
      // put it, with no help.
      const helping = !event.altKey;
      let lines = [];

      store.mutate(this.gestureLabel, (doc) => {
        const shift = (fx, fy) => {
          for (const [id, start] of this.startBoxes) {
            const item = model.itemById(doc, id);
            if (!item) continue;
            if (start.points) {
              item.points = start.points.map((p) => [p[0] + fx, p[1] + fy]);
            }
            if (start.x !== undefined) item.x = start.x + fx;
            if (start.y !== undefined) item.y = start.y + fy;
          }
        };
        shift(sdx, sdy);
        if (!helping) return;
        // Asked of the drawing as it now stands, so the answer is a nudge
        // from where the cell actually is rather than from where it started.
        const fix = guides.suggest(doc, selection.ids, SNAP_PIXELS / this.ctx.zoom());
        if (fix.dx || fix.dy) shift(sdx + fix.dx, sdy + fix.dy);
        lines = fix.guides;
      });

      this.ctx.drawOverlay({ guides: lines });
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
    const clip = model.copyItems(store.doc, selection.ids);
    const added = store.mutate(this.gestureLabel,
                               (doc) => model.pasteItems(doc, clip, 0, 0));
    if (added) {
      selection.set(added);
      this.startBoxes = new Map(added.map((id) => {
        const item = model.itemById(store.doc, id);
        return [id, JSON.parse(JSON.stringify(item))];
      }));
    }
    this.duplicated = true;
  }

  applyResize(point, freeAspect) {
    const { store } = this.ctx;
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
        const item = model.itemById(doc, id);
        if (!item) continue;
        if (start.points) {
          item.points = start.points.map((p) => [
            fixed[0] + (p[0] - fixed[0]) * scaleX,
            fixed[1] + (p[1] - fixed[1]) * scaleY,
          ]);
          continue;
        }
        item.x = fixed[0] + (start.x - fixed[0]) * scaleX;
        item.y = fixed[1] + (start.y - fixed[1]) * scaleY;
        if (start.w !== undefined) item.w = Math.max(4, start.w * scaleX);
        if (start.h !== undefined) item.h = Math.max(4, start.h * scaleY);
      }
    });
  }

  onPointerUp(event) {
    const { store, selection } = this.ctx;

    if (this.mode === "marquee" && this.marquee) {
      const [mx, my, mw, mh] = this.marquee;
      const hits = [];
      for (const item of model.items(store.doc)) {
        const box = model.itemBounds(store.doc, item);
        if (!box) continue;
        if (box[0] >= mx && box[1] >= my
            && box[0] + box[2] <= mx + mw && box[1] + box[3] <= my + mh) {
          hits.push(item.id);
        }
      }
      if (event.shiftKey) selection.add(hits);
      else selection.set(hits);
    }

    const changed = this.moved;
    store.endGesture();
    this.reset();
    this.ctx.drawOverlay();
    return changed;
  }
}

// ---- wiring ----

export class WireTool {
  constructor(context) {
    this.ctx = context;
    this.reset();
  }

  reset() {
    this.from = null;
    this.hover = null;
  }

  cursorFor() { return "crosshair"; }

  // Every pin in the drawing, in document coordinates, so they can be shown as
  // targets and hit-tested by proximity rather than pixel-perfect clicking.
  allPins() {
    const doc = this.ctx.store.doc;
    const scale = model.symbolScale(doc);
    const pins = [];
    for (const cell of doc.cells) {
      const symbol = geometry.forCell(cell);
      if (!symbol) continue;
      for (const pin of symbol.pins) {
        const at = geometry.pinPosition(symbol, cell, pin.name, scale);
        if (at) pins.push({ cell: cell.id, pin: pin.name, x: at[0], y: at[1] });
      }
    }
    return pins;
  }

  nearestPin(point) {
    let best = null;
    let bestDistance = PIN_SNAP / this.ctx.zoom();
    for (const pin of this.allPins()) {
      const distance = Math.hypot(pin.x - point[0], pin.y - point[1]);
      if (distance <= bestDistance) {
        best = pin;
        bestDistance = distance;
      }
    }
    return best;
  }

  overlay(point) {
    const pins = this.allPins();
    for (const pin of pins) {
      pin.active = Boolean(this.hover && this.hover.cell === pin.cell
                           && this.hover.pin === pin.pin);
    }
    const options = { pins, hideHandles: true };
    if (this.from && point) options.wirePreview = this.previewPath(point);
    return options;
  }

  // Preview with the real router, so what you see while dragging is the path
  // you will actually get.
  previewPath(target) {
    const probe = {
      id: "__preview",
      from: this.from.endpoint,
      to: [this.hover
        ? { cell: this.hover.cell, pin: this.hover.pin, waypoints: [] }
        : { x: target[0], y: target[1], waypoints: [] }],
    };
    const [points] = routing.route(this.ctx.store.doc, probe);
    return points && points.length ? points : [[this.from.x, this.from.y], target];
  }

  onPointerDown(event, point) {
    const pin = this.nearestPin(point);
    if (!pin) {
      // Clicking away cancels a half-drawn wire rather than leaving it hanging.
      this.reset();
      this.ctx.drawOverlay(this.overlay(point));
      return;
    }

    if (!this.from) {
      this.from = { endpoint: { cell: pin.cell, pin: pin.pin }, x: pin.x, y: pin.y };
      this.hover = null;
      this.ctx.drawOverlay(this.overlay(point));
      return;
    }

    if (this.from.endpoint.cell === pin.cell && this.from.endpoint.pin === pin.pin) {
      return;
    }

    const from = this.from.endpoint;
    const to = { cell: pin.cell, pin: pin.pin };
    const net = this.ctx.store.mutate("wire", (doc) => model.addNet(doc, from, to));
    this.reset();
    this.ctx.drawOverlay(this.overlay(point));
    this.ctx.say(net ? `wired ${from.cell}.${from.pin} to ${to.cell}.${to.pin}`
                     : "those pins are already wired together");
  }

  onPointerMove(event, point) {
    this.hover = this.nearestPin(point);
    this.ctx.drawOverlay(this.overlay(point));
    return false;
  }

  onPointerUp() { return false; }

  onActivate() {
    this.reset();
    this.ctx.drawOverlay(this.overlay(null));
  }

  onDeactivate() { this.reset(); }
}

// ---- placing a cell from the palette ----

export class PlaceTool {
  constructor(context) {
    this.ctx = context;
    this.type = null;
  }

  arm(type) { this.type = type; }

  cursorFor() { return "copy"; }

  onPointerDown(event, point) {
    if (!this.type) return;
    const { store, selection } = this.ctx;
    const cell = store.mutate("place",
                              (doc) => model.addCell(doc, this.type, point[0], point[1]));
    if (cell) {
      selection.set([cell.id]);
      this.ctx.say(`placed ${cell.label || cell.type}`);
    }
    // Shift keeps placing; a plain click drops one and returns to selecting.
    if (!event.shiftKey) this.ctx.setTool("select");
  }

  onPointerMove() { return false; }

  onPointerUp() { return false; }

  onDeactivate() { this.type = null; }
}

// ---- autoshapes ----

export class ShapeTool {
  constructor(context) {
    this.ctx = context;
    this.kind = "rect";
    this.reset();
  }

  reset() {
    this.origin = null;
    this.preview = null;
    this.polygon = null;
  }

  arm(kind) {
    this.kind = kind;
    this.reset();
  }

  cursorFor() { return "crosshair"; }

  onPointerDown(event, point) {
    const { store, selection } = this.ctx;
    const step = model.gridStep(store.doc);
    const at = [model.snap(point[0], step), model.snap(point[1], step)];

    if (this.kind === "text") {
      const text = window.prompt("Text:", "Text");
      if (!text) return;
      const shape = store.mutate("text", (doc) => {
        const made = model.addShape(doc, "text", { x: at[0], y: at[1] });
        made.text = text;
        return made;
      });
      if (shape) selection.set([shape.id]);
      this.ctx.setTool("select");
      return;
    }

    if (this.kind === "polygon") {
      // A polygon is built click by click; double-click or Escape closes it.
      if (!this.polygon) this.polygon = [at];
      else this.polygon.push(at);
      this.ctx.drawOverlay({ hideHandles: true, wirePreview: this.polygon });
      return;
    }

    this.origin = at;
  }

  onPointerMove(event, point) {
    if (!this.origin) {
      if (this.polygon) {
        const step = model.gridStep(this.ctx.store.doc);
        const at = [model.snap(point[0], step), model.snap(point[1], step)];
        this.ctx.drawOverlay({ hideHandles: true,
                               wirePreview: [...this.polygon, at] });
      }
      return false;
    }
    const step = model.gridStep(this.ctx.store.doc);
    const at = [model.snap(point[0], step), model.snap(point[1], step)];
    this.preview = at;
    if (this.kind === "line") {
      this.ctx.drawOverlay({ hideHandles: true, wirePreview: [this.origin, at] });
    } else {
      this.ctx.drawOverlay({
        hideHandles: true,
        marquee: [Math.min(this.origin[0], at[0]), Math.min(this.origin[1], at[1]),
                  Math.abs(at[0] - this.origin[0]), Math.abs(at[1] - this.origin[1])],
      });
    }
    return false;
  }

  onPointerUp(event, point) {
    if (!this.origin || !this.preview) return false;
    const { store, selection } = this.ctx;
    const a = this.origin;
    const b = this.preview;

    const shape = store.mutate("shape", (doc) => {
      if (this.kind === "line") {
        return model.addShape(doc, "line", { x: a[0], y: a[1], w: 0, h: 0,
                                             points: [a, b] });
      }
      return model.addShape(doc, this.kind, {
        x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]),
        w: Math.max(4, Math.abs(b[0] - a[0])),
        h: Math.max(4, Math.abs(b[1] - a[1])),
      });
    });

    this.reset();
    if (shape) selection.set([shape.id]);
    this.ctx.setTool("select");
    return true;
  }

  finishPolygon() {
    if (!this.polygon || this.polygon.length < 3) {
      this.reset();
      return false;
    }
    const points = this.polygon;
    const shape = this.ctx.store.mutate("shape", (doc) =>
      model.addShape(doc, "polygon", { x: points[0][0], y: points[0][1],
                                       w: 0, h: 0, points }));
    this.reset();
    if (shape) this.ctx.selection.set([shape.id]);
    this.ctx.setTool("select");
    return true;
  }

  onDeactivate() { this.reset(); }
}

export function makeTools(context) {
  return {
    select: new SelectTool(context),
    wire: new WireTool(context),
    place: new PlaceTool(context),
    shape: new ShapeTool(context),
  };
}
