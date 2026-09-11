// What is selected, and the handles drawn on top of it.

import * as actions from "./actions.js";
import { boundsOf } from "./geometry.js";
import { overlayLayer } from "./render.js";
import * as symbols from "./symbols.js";

const NS = "http://www.w3.org/2000/svg";
const HANDLE_KEYS = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

export class Selection {
  constructor(store) {
    this.store = store;
    this.ids = new Set();
    this._listeners = [];
  }

  subscribe(listener) {
    this._listeners.push(listener);
  }

  emit() {
    for (const listener of this._listeners) listener(this);
  }

  get size() { return this.ids.size; }

  has(id) { return this.ids.has(id); }

  clear() {
    if (!this.ids.size) return;
    this.ids.clear();
    this.emit();
  }

  set(ids) {
    this.ids = this.store.doc
      ? actions.expandGroups(this.store.doc, new Set(ids)) : new Set(ids);
    this.emit();
  }

  add(ids) {
    const merged = new Set([...this.ids, ...ids]);
    this.ids = this.store.doc
      ? actions.expandGroups(this.store.doc, merged) : merged;
    this.emit();
  }

  toggle(id) {
    const group = actions.groupOf(this.store.doc, id);
    const affected = group ? group.members : [id];
    if (this.ids.has(id)) affected.forEach((m) => this.ids.delete(m));
    else affected.forEach((m) => this.ids.add(m));
    this.emit();
  }

  selectAll() {
    this.ids = new Set(this.store.doc.cells.map((c) => c.id));
    this.emit();
  }

  cells() {
    if (!this.store.doc) return [];
    return this.store.doc.cells.filter((c) => this.ids.has(c.id));
  }

  // Combined bounds of everything selected, in document units.
  bounds() {
    if (!this.store.doc) return null;
    const scale = Number(this.store.doc.canvas.symbolScale) || 1;
    const points = [];
    for (const cell of this.cells()) {
      const symbol = symbols.get(cell.type);
      if (!symbol) continue;
      const box = symbols.cellBounds(symbol, cell, scale);
      points.push([box[0], box[1]], [box[0] + box[2], box[1] + box[3]]);
    }
    return boundsOf(points);
  }
}

// Handle size is given in screen pixels and divided by zoom, so grips stay the
// same size to the hand however far you are zoomed in.
export function drawHandles(svg, selection, zoom, options = {}) {
  const layer = overlayLayer(svg);
  while (layer.firstChild) layer.removeChild(layer.firstChild);

  if (options.marquee) {
    const [x, y, w, h] = options.marquee;
    layer.appendChild(el("rect", {
      class: "dl-marquee", x, y, width: w, height: h,
      "stroke-width": 1 / zoom,
    }));
  }

  if (options.pins) {
    for (const pin of options.pins) {
      layer.appendChild(el("circle", {
        class: `dl-pin${pin.active ? " active" : ""}`,
        cx: pin.x, cy: pin.y, r: 4 / zoom,
        "stroke-width": 1.2 / zoom,
        "data-cell": pin.cell, "data-pin": pin.pin,
      }));
    }
  }

  if (options.wirePreview && options.wirePreview.length > 1) {
    layer.appendChild(el("path", {
      class: "dl-wire-preview",
      d: `M${options.wirePreview.map((p) => `${p[0]} ${p[1]}`).join(" L")}`,
      "stroke-width": 1.6,
    }));
  }

  const box = selection.bounds();
  if (!box || options.hideHandles) return layer;

  const pad = 5 / zoom;
  const x = box[0] - pad;
  const y = box[1] - pad;
  const w = box[2] + pad * 2;
  const h = box[3] + pad * 2;

  layer.appendChild(el("rect", {
    class: "dl-selbox", x, y, width: w, height: h,
    "stroke-width": 1 / zoom,
    "stroke-dasharray": `${3 / zoom} ${2.5 / zoom}`,
  }));

  const size = 7 / zoom;
  for (const [key, [hx, hy]] of Object.entries(handlePoints(x, y, w, h))) {
    layer.appendChild(el("rect", {
      class: "dl-handle", "data-handle": key,
      x: hx - size / 2, y: hy - size / 2, width: size, height: size,
      "stroke-width": 1.2 / zoom,
    }));
  }
  return layer;
}

export function handlePoints(x, y, w, h) {
  return {
    nw: [x, y], n: [x + w / 2, y], ne: [x + w, y],
    e: [x + w, y + h / 2], se: [x + w, y + h],
    s: [x + w / 2, y + h], sw: [x, y + h], w: [x, y + h / 2],
  };
}

export { HANDLE_KEYS };
