// What is selected, and the handles drawn on top of it.
//
// Usage:
//
//   const selection = new Selection(store);
//   selection.set(["u1", "u2"]);
//   drawHandles(svg, selection, viewport.zoom,
//               { marquee, guides, pins, wirePreview });
//
// Cells and shapes are both selectable, so this works in item ids rather than
// cell ids. Selecting one member of a group selects the whole group.

import * as model from "./model.js";
import { overlayLayer } from "./render.js";

const NS = "http://www.w3.org/2000/svg";

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
      ? model.expandGroups(this.store.doc, new Set(ids)) : new Set(ids);
    this.emit();
  }

  add(ids) {
    const merged = new Set([...this.ids, ...ids]);
    this.ids = this.store.doc ? model.expandGroups(this.store.doc, merged) : merged;
    this.emit();
  }

  toggle(id) {
    const group = this.store.doc ? model.groupOf(this.store.doc, id) : null;
    const affected = group ? group.members : [id];
    if (this.ids.has(id)) affected.forEach((m) => this.ids.delete(m));
    else affected.forEach((m) => this.ids.add(m));
    this.emit();
  }

  selectAll() {
    if (!this.store.doc) return;
    this.ids = new Set(model.items(this.store.doc).map((i) => i.id));
    this.emit();
  }

  items() {
    if (!this.store.doc) return [];
    return [...this.ids]
      .map((id) => model.itemById(this.store.doc, id))
      .filter(Boolean);
  }

  bounds() {
    if (!this.store.doc) return null;
    return model.boundsOfIds(this.store.doc, this.ids);
  }
}

export function handlePoints(x, y, w, h) {
  return {
    nw: [x, y], n: [x + w / 2, y], ne: [x + w, y],
    e: [x + w, y + h / 2], se: [x + w, y + h],
    s: [x + w / 2, y + h], sw: [x, y + h], w: [x, y + h / 2],
  };
}

// Handle size is given in screen pixels and divided by zoom, so grips stay the
// same size to the hand however far you are zoomed in.
export function drawHandles(svg, selection, zoom, options = {}) {
  const layer = overlayLayer(svg);
  while (layer.firstChild) layer.removeChild(layer.firstChild);

  if (options.marquee) {
    const [x, y, w, h] = options.marquee;
    layer.appendChild(el("rect", {
      class: "dl-marquee", x, y, width: w, height: h, "stroke-width": 1 / zoom,
    }));
  }

  // Alignment guides: why the thing you are dragging just jumped into line.
  for (const guide of options.guides || []) {
    const horizontal = guide.axis === "y";
    layer.appendChild(el("line", {
      class: "dl-guide",
      x1: horizontal ? guide.from : guide.at,
      y1: horizontal ? guide.at : guide.from,
      x2: horizontal ? guide.to : guide.at,
      y2: horizontal ? guide.at : guide.to,
      "stroke-width": 1 / zoom,
      "stroke-dasharray": `${4 / zoom} ${3 / zoom}`,
    }));
  }

  if (options.pins) {
    for (const pin of options.pins) {
      layer.appendChild(el("circle", {
        class: `dl-pin${pin.active ? " active" : ""}`,
        cx: pin.x, cy: pin.y, r: 4 / zoom, "stroke-width": 1.2 / zoom,
        "data-cell": pin.cell, "data-pin": pin.pin,
      }));
    }
  }

  if (options.wirePreview && options.wirePreview.length > 1) {
    layer.appendChild(el("path", {
      class: "dl-wire-preview",
      d: `M${options.wirePreview.map((p) => `${p[0]} ${p[1]}`).join(" L")}`,
      "stroke-width": 1.6 / zoom,
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
