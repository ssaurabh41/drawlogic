// What is selected, and the handles drawn on top of it.
//
// Usage:
//
//   const selection = new Selection(store);
//   selection.set(["u1", "u2"]);
//   drawHandles(svg, selection, viewport.zoom,
//               { marquee, round, guides, pins, wirePreview });
//
// Cells and shapes are both selectable, so this works in item ids rather than
// cell ids. Selecting one member of a group selects the whole group.

import * as geometry from "./geometry.js";
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
    // A wire is selected on its own, never alongside cells: it cannot be
    // moved, resized or grouped like them, so it is kept out of `ids`.
    this.net = null;
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
    if (!this.ids.size && this.net === null) return;
    this.ids.clear();
    this.net = null;
    this.emit();
  }

  selectNet(id) {
    this.ids.clear();
    this.net = id;
    this.emit();
  }

  set(ids) {
    this.net = null;
    this.ids = this.store.doc
      ? model.expandGroups(this.store.doc, new Set(ids)) : new Set(ids);
    this.emit();
  }

  add(ids) {
    this.net = null;
    const merged = new Set([...this.ids, ...ids]);
    this.ids = this.store.doc ? model.expandGroups(this.store.doc, merged) : merged;
    this.emit();
  }

  toggle(id) {
    this.net = null;
    const group = this.store.doc ? model.groupOf(this.store.doc, id) : null;
    const affected = group ? group.members : [id];
    if (this.ids.has(id)) affected.forEach((m) => this.ids.delete(m));
    else affected.forEach((m) => this.ids.add(m));
    this.emit();
  }

  selectAll() {
    if (!this.store.doc) return;
    this.net = null;
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
    // An ellipse being drawn is previewed as the ellipse, not the box round it.
    layer.appendChild(options.round
      ? el("ellipse", { class: "dl-marquee", cx: x + w / 2, cy: y + h / 2,
                        rx: w / 2, ry: h / 2, "stroke-width": 1 / zoom })
      : el("rect", { class: "dl-marquee", x, y, width: w, height: h,
                     "stroke-width": 1 / zoom }));
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

  // Every DRC violation, marked where it is. The list in the panel says what
  // is wrong; this says where, which is the half you cannot get from a list --
  // and it is drawn in the overlay rather than poked into the canvas so it
  // survives a redraw and scales with the zoom like everything else here.
  for (const mark of options.drc || []) {
    layer.appendChild(el("circle", {
      class: `dl-drc-mark ${mark.level === "error" ? "error" : "warning"}`
             + (mark.active ? " active" : ""),
      cx: mark.at[0], cy: mark.at[1], r: 13 / zoom,
      "stroke-width": 2 / zoom,
      "stroke-dasharray": `${5 / zoom} ${4 / zoom}`,
    }));
  }

  // Where a cell being placed will land: its outline, and the pin it has
  // snapped to ringed, so the join can be judged before letting go.
  // A cell being moved is its own outline already, and has the selection box
  // round it, so a move passes no box: only the ring.
  if (options.ghost) {
    if (options.ghost.box) {
      const [gx, gy, gw, gh] = options.ghost.box;
      layer.appendChild(el("rect", {
        class: "dl-ghost", x: gx, y: gy, width: gw, height: gh,
        "stroke-width": 1.2 / zoom,
        "stroke-dasharray": `${4 / zoom} ${3 / zoom}`,
      }));
    }
    if (options.ghost.target) {
      const [tx, ty] = options.ghost.target;
      layer.appendChild(el("circle", {
        class: "dl-pin active", cx: tx, cy: ty, r: 5 / zoom, "stroke-width": 1.4 / zoom,
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

  // The selected wire, traced over in a wide translucent stroke so it shows
  // which wire the properties panel is talking about.
  if (selection.net !== null) {
    const path = svg.querySelector(`.dl-net[data-id="${CSS.escape(String(selection.net))}"]`);
    if (path) {
      layer.appendChild(el("path", {
        class: "dl-net-selected", d: path.getAttribute("d"),
        "stroke-width": Math.max(6, 10 / zoom),
      }));
    }
  }

  // The sheet's right edge, bottom edge and corner can be dragged like a
  // window's. Nothing is drawn there until the pointer is over one: a thin
  // strip along the edge is the target, and it lights up on hover, with the
  // cursor saying which way it pulls. Its top-left is the origin everything
  // is placed from, so only those sides move.
  const doc = selection.store.doc;
  if (doc && !options.hideHandles && !options.hideSheetHandles) {
    const sw = Number(doc.canvas.width) || 0;
    const sh = Number(doc.canvas.height) || 0;
    const reach = 7 / zoom;
    const corner = 16 / zoom;
    const strips = {
      e: [sw - reach, 0, reach * 2, sh],
      s: [0, sh - reach, sw, reach * 2],
      se: [sw - corner / 2, sh - corner / 2, corner, corner],
    };
    for (const [key, [x, y, width, height]] of Object.entries(strips)) {
      layer.appendChild(el("rect", {
        class: `dl-sheet-edge ${key}${options.sheetEdge === key ? " active" : ""}`,
        "data-sheet-handle": key,
        x, y, width, height, rx: key === "se" ? 3 / zoom : 0,
      }));
    }
    // While dragging, the size it will be, beside the corner.
    if (options.sheetEdge) {
      const label = el("text", {
        class: "dl-sheet-size", x: sw - 6 / zoom, y: sh + 18 / zoom,
        "text-anchor": "end", "font-size": 12 / zoom,
      });
      label.textContent = `${Math.round(sw)} x ${Math.round(sh)}`;
      layer.appendChild(label);
    }
  }

  const box = selection.bounds();
  if (!box || options.hideHandles) return layer;
  // Nobody resizes a port or a tie cell; they move it. Its box is so small
  // that the grips covered most of it, and a press meant to drag it grabbed a
  // corner.
  const items = selection.items();
  const onlyFixed = items.length > 0
    && items.every((item) => geometry.FIXED_SIZE_TYPES.has(item.type));

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
  if (onlyFixed) return layer;

  // Two rectangles per grip. The visible one is small enough not to hide the
  // corner it sits on; the transparent one behind it is twice the size,
  // because a 7px square is a target the hand keeps missing. Reported as
  // "my cursor always misses the corners", and it was right.
  const size = 9 / zoom;
  const grab = 20 / zoom;
  for (const [key, [hx, hy]] of Object.entries(handlePoints(x, y, w, h))) {
    layer.appendChild(el("rect", {
      class: "dl-grip", "data-handle": key,
      x: hx - grab / 2, y: hy - grab / 2, width: grab, height: grab,
    }));
    layer.appendChild(el("rect", {
      class: "dl-handle", "data-handle": key,
      x: hx - size / 2, y: hy - size / 2, width: size, height: size,
      rx: 1.5 / zoom,
      "stroke-width": 1.4 / zoom,
    }));
  }
  return layer;
}
