// Drawing wires pin to pin.
//
// A wire is stored as two pin references, so once it exists the router keeps
// it attached no matter what moves. The only job here is picking the two pins.

import * as actions from "../actions.js";
import * as routing from "../routing.js";
import * as symbols from "../symbols.js";

const SNAP_RADIUS = 14;

export class WireTool {
  constructor(context) {
    this.ctx = context;
    this.from = null;
    this.hover = null;
  }

  reset() {
    this.from = null;
    this.hover = null;
  }

  cursorFor() {
    return "crosshair";
  }

  // Every pin in the drawing, in document coordinates, so they can be shown as
  // targets and hit-tested by proximity rather than by pixel-perfect clicking.
  allPins() {
    const doc = this.ctx.store.doc;
    const scale = routing.symbolScale(doc);
    const pins = [];
    for (const cell of doc.cells) {
      const symbol = symbols.get(cell.type);
      if (!symbol) continue;
      for (const pin of symbol.pins) {
        const at = symbols.pinPosition(symbol, cell, pin.name, scale);
        if (at) {
          pins.push({ cell: cell.id, pin: pin.name, x: at[0], y: at[1],
                      width: pin.width || 1 });
        }
      }
    }
    return pins;
  }

  nearestPin(point) {
    const zoom = this.ctx.zoom();
    let best = null;
    let bestDistance = SNAP_RADIUS / zoom;
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
    const hover = this.hover;
    for (const pin of pins) {
      pin.active = Boolean(
        hover && hover.cell === pin.cell && hover.pin === pin.pin);
    }

    const options = { pins, hideHandles: true };
    if (this.from && point) {
      const target = hover ? [hover.x, hover.y] : point;
      options.wirePreview = this.previewPath(target);
    }
    return options;
  }

  // Preview using the real router, so what you see while dragging is the path
  // you will actually get.
  previewPath(target) {
    const doc = this.ctx.store.doc;
    const probe = {
      id: "__preview", from: this.from.endpoint,
      to: this.hover
        ? { cell: this.hover.cell, pin: this.hover.pin }
        : { x: target[0], y: target[1] },
      waypoints: [],
    };
    const points = routing.route(doc, probe);
    return points.length ? points : [[this.from.x, this.from.y], target];
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
    const net = this.ctx.store.mutate("wire", (doc) => actions.addNet(doc, from, to));
    this.reset();
    this.ctx.drawOverlay(this.overlay(point));
    this.ctx.say(net ? `wired ${from.cell}.${from.pin} to ${to.cell}.${to.pin}`
                     : "those pins are already wired together");
  }

  onPointerMove(event, point) {
    const pin = this.nearestPin(point);
    const changed = (pin && pin.cell) !== (this.hover && this.hover.cell)
      || (pin && pin.pin) !== (this.hover && this.hover.pin);
    this.hover = pin;
    if (this.from || changed) {
      this.ctx.drawOverlay(this.overlay(point));
      return false;
    }
    return false;
  }

  onPointerUp() {
    return false;
  }

  onActivate() {
    this.reset();
    this.ctx.drawOverlay(this.overlay(null));
  }

  onDeactivate() {
    this.reset();
  }
}
