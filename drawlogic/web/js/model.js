// The document: state, undo/redo, and every change it can undergo.
//
// Usage:
//
//   const store = new Store();
//   store.load(doc, "alu_ctrl.dlg");
//   store.mutate("place", (doc) => addCell(doc, "and2", 120, 80));
//   store.undo();
//
// Every change goes through Store.mutate, so undo and the dirty marker can
// never be forgotten at a call site. Undo keeps whole-document snapshots
// rather than inverse operations: a schematic is small, and a snapshot cannot
// fall out of step with the edit it is meant to undo.

import * as geometry from "./geometry.js";
import * as guides from "./guides.js";
import * as routing from "./routing.js";

const UNDO_LIMIT = 120;

export class Store {
  constructor() {
    this.doc = null;
    this.path = null;
    this.dirty = false;
    this._undo = [];
    this._redo = [];
    this._listeners = [];
  }

  subscribe(listener) {
    this._listeners.push(listener);
  }

  emit(reason) {
    for (const listener of this._listeners) listener(this, reason);
  }

  load(doc, path) {
    this.doc = doc;
    this.path = path;
    this.dirty = false;
    this._undo = [];
    this._redo = [];
    this.emit("load");
  }

  snapshot() {
    return JSON.parse(JSON.stringify(this.doc));
  }

  // A drag fires a mutation per pointer move but should undo as one step.
  // Opening a gesture makes every mutation inside it share the first snapshot.
  beginGesture(label) {
    this._gesture = label;
    this._gestureOpen = false;
  }

  endGesture() {
    this._gesture = null;
    this._gestureOpen = false;
  }

  mutate(label, change) {
    if (!this.doc) return null;
    const before = this.snapshot();
    const result = change(this.doc);
    if (result === false) return null;

    const inGesture = this._gesture !== null && this._gesture !== undefined;
    if (!inGesture || !this._gestureOpen) {
      this._undo.push({ label, doc: before });
      if (this._undo.length > UNDO_LIMIT) this._undo.shift();
      if (inGesture) this._gestureOpen = true;
    }

    this._redo = [];
    this.dirty = true;
    this.emit("mutate");
    return result;
  }

  canUndo() { return this._undo.length > 0; }

  canRedo() { return this._redo.length > 0; }

  undo() {
    if (!this._undo.length) return false;
    const entry = this._undo.pop();
    this._redo.push({ label: entry.label, doc: this.snapshot() });
    this.doc = entry.doc;
    this.dirty = true;
    this.emit("undo");
    return entry.label;
  }

  redo() {
    if (!this._redo.length) return false;
    const entry = this._redo.pop();
    this._undo.push({ label: entry.label, doc: this.snapshot() });
    this.doc = entry.doc;
    this.dirty = true;
    this.emit("redo");
    return entry.label;
  }

  markSaved() {
    this.dirty = false;
    this.emit("saved");
  }
}

// ---- identity and lookup ----

function uniqueId(doc, prefix) {
  const used = new Set([
    ...doc.cells.map((c) => c.id),
    ...doc.nets.map((n) => n.id),
    ...(doc.shapes || []).map((s) => s.id),
    ...(doc.groups || []).map((g) => g.id),
  ]);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

function labelFor(doc, type) {
  const prefixes = {
    port_in: "in", port_out: "out", port_inout: "io", block: "B", dff: "FF",
    dffr: "FF", dlatch: "L", icg: "ICG", mux2: "M", mux4: "M",
    nmos: "MN", pmos: "MP", resistor: "R", capacitor: "C",
  };
  const prefix = prefixes[type] || "U";
  const used = new Set(doc.cells.map((c) => c.label).filter(Boolean));
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

export function gridStep(doc) {
  return Number((doc.canvas.grid || {}).size) || 10;
}

export function snap(value, step) {
  return step ? Math.round(value / step) * step : value;
}

export function symbolScale(doc) {
  const value = Number(doc.canvas.symbolScale);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

// Cells and shapes are both selectable, movable and resizable, so most of the
// editor treats them as one kind of thing: an item with a bounding box.
export function items(doc) {
  return [...doc.cells, ...(doc.shapes || [])];
}

export function itemById(doc, id) {
  return doc.cells.find((c) => c.id === id)
    || (doc.shapes || []).find((s) => s.id === id)
    || null;
}

export function isShape(item) {
  return item && item.kind !== undefined;
}

export function itemBounds(doc, item) {
  if (!item) return null;
  if (isShape(item)) {
    if (item.points && item.points.length) {
      return geometry.boundsOf(item.points);
    }
    return [item.x, item.y, item.w || 0, item.h || 0];
  }
  const symbol = geometry.forCell(item);
  if (!symbol) return null;
  return geometry.cellBounds(symbol, item, symbolScale(doc));
}

export function boundsOfIds(doc, ids) {
  const points = [];
  for (const id of ids) {
    const box = itemBounds(doc, itemById(doc, id));
    if (box) points.push([box[0], box[1]], [box[0] + box[2], box[1] + box[3]]);
  }
  return geometry.boundsOf(points);
}

// ---- cells ----

export function addCell(doc, type, x, y) {
  const symbol = geometry.get(type);
  if (!symbol) return null;
  const step = gridStep(doc);
  const cell = {
    id: uniqueId(doc, "c"),
    type,
    x: snap(x - symbol.size[0] / 2, step),
    y: snap(y - symbol.size[1] / 2, step),
    w: symbol.size[0],
    h: symbol.size[1],
    rotate: 0,
    mirror: false,
    label: labelFor(doc, type),
    style: {},
  };
  doc.cells.push(cell);
  return cell;
}

export function moveItems(doc, ids, dx, dy) {
  for (const id of ids) {
    const item = itemById(doc, id);
    if (!item) continue;
    if (item.points) {
      item.points = item.points.map((p) => [p[0] + dx, p[1] + dy]);
    }
    if (item.x !== undefined) item.x += dx;
    if (item.y !== undefined) item.y += dy;
  }
}

export function rotateCells(doc, ids, degrees) {
  for (const cell of doc.cells) {
    if (!ids.has(cell.id)) continue;
    cell.rotate = (((cell.rotate || 0) + degrees) % 360 + 360) % 360;
  }
}

export function flipCells(doc, ids, vertical) {
  for (const cell of doc.cells) {
    if (!ids.has(cell.id)) continue;
    if (vertical) {
      // A vertical flip is a horizontal flip turned half a turn, which keeps
      // rotation and mirror as the only two state fields.
      cell.mirror = !cell.mirror;
      cell.rotate = (((cell.rotate || 0) + 180) % 360 + 360) % 360;
    } else {
      cell.mirror = !cell.mirror;
    }
  }
}

// Deleting a cell has to take its wires with it, or the document is left with
// nets pointing at something that no longer exists.
export function deleteItems(doc, ids) {
  doc.cells = doc.cells.filter((cell) => !ids.has(cell.id));
  doc.shapes = (doc.shapes || []).filter((shape) => !ids.has(shape.id));
  doc.nets = doc.nets.filter((net) => {
    if (ids.has(net.id)) return false;
    if (net.from && net.from.cell !== undefined && ids.has(net.from.cell)) {
      return false;
    }
    // Losing one load does not lose the net; losing the last one does.
    net.to = routing.loadsOf(net)
      .filter((load) => load.cell === undefined || !ids.has(load.cell));
    return net.to.length > 0;
  });
  doc.groups = (doc.groups || [])
    .map((group) => ({
      ...group,
      members: group.members.filter((m) => !ids.has(m)),
    }))
    .filter((group) => group.members.length > 1);
}

export function setStyle(doc, ids, key, value) {
  for (const id of ids) {
    const item = itemById(doc, id);
    if (!item) continue;
    item.style = item.style || {};
    if (value === null || value === "") delete item.style[key];
    else item.style[key] = value;
  }
}

// Name one pin on one instance. An empty name drops back to whatever the
// symbol itself draws, so clearing the field is always a way back.
export function setPinLabel(doc, cellId, pinName, label) {
  const cell = doc.cells.find((c) => c.id === cellId);
  if (!cell) return;
  const pins = { ...(cell.pins || {}) };
  if (label) pins[pinName] = label;
  else delete pins[pinName];
  if (Object.keys(pins).length) cell.pins = pins;
  else delete cell.pins;
}

export function setLabel(doc, id, label) {
  const item = itemById(doc, id);
  if (!item) return;
  if (isShape(item)) item.text = label;
  else item.label = label || null;
}

// A custom cell's picture is embedded as a data URI, so a .dlg stays one
// shippable file rather than a file plus a folder of images.
export function setCellImage(doc, id, dataUri) {
  const cell = doc.cells.find((c) => c.id === id);
  if (!cell) return;
  if (dataUri) cell.image = dataUri;
  else delete cell.image;
}

// ---- shapes ----

export function addShape(doc, kind, box) {
  const shape = {
    id: uniqueId(doc, "s"),
    kind,
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    rotate: 0,
    style: {},
  };
  if (kind === "text") {
    shape.text = "Text";
    delete shape.w;
    delete shape.h;
  }
  if (kind === "line" || kind === "polygon" || kind === "polyline") {
    shape.points = box.points || [[box.x, box.y], [box.x + box.w, box.y + box.h]];
    delete shape.x;
    delete shape.y;
    delete shape.w;
    delete shape.h;
  }
  doc.shapes = doc.shapes || [];
  doc.shapes.push(shape);
  return shape;
}

// ---- z-order ----

export function bringToFront(doc, ids) {
  const move = (list) => {
    const staying = list.filter((i) => !ids.has(i.id));
    const moving = list.filter((i) => ids.has(i.id));
    return [...staying, ...moving];
  };
  doc.cells = move(doc.cells);
  doc.shapes = move(doc.shapes || []);
}

export function sendToBack(doc, ids) {
  const move = (list) => {
    const moving = list.filter((i) => ids.has(i.id));
    const staying = list.filter((i) => !ids.has(i.id));
    return [...moving, ...staying];
  };
  doc.cells = move(doc.cells);
  doc.shapes = move(doc.shapes || []);
}

// ---- alignment ----

export function align(doc, ids, edge) {
  const outer = boundsOfIds(doc, ids);
  if (!outer) return;
  for (const id of ids) {
    const item = itemById(doc, id);
    const box = itemBounds(doc, item);
    if (!box) continue;
    let dx = 0;
    let dy = 0;
    if (edge === "left") dx = outer[0] - box[0];
    else if (edge === "right") dx = outer[0] + outer[2] - (box[0] + box[2]);
    else if (edge === "hcenter") {
      dx = outer[0] + outer[2] / 2 - (box[0] + box[2] / 2);
    } else if (edge === "top") dy = outer[1] - box[1];
    else if (edge === "bottom") dy = outer[1] + outer[3] - (box[1] + box[3]);
    else if (edge === "vcenter") {
      dy = outer[1] + outer[3] / 2 - (box[1] + box[3] / 2);
    }
    if (dx || dy) moveItems(doc, new Set([id]), dx, dy);
  }
}

// Pull the selected cells into line with what they are wired to, so their
// wires run straight instead of dog-legging.
//
// Only the selected cells move. Everything else anchors them, which is what
// makes tidying one block at a time safe -- and it means selecting a single
// cell snaps just that cell to its neighbours.
//
// Cells are settled left to right, and each takes its line from the nearest
// thing already fixed, so a chain of gates collapses onto one row rather than
// one stray cell dragging the lot across the sheet.
export function tidy(doc, ids) {
  const moving = new Set([...ids].filter((id) => doc.cells.some((c) => c.id === id)));
  if (!moving.size) return 0;

  const order = doc.cells
    .filter((cell) => moving.has(cell.id))
    .slice()
    .sort((a, b) => (a.x - b.x) || (a.y - b.y));

  const settled = new Set();
  let straightened = 0;

  for (const cell of order) {
    const fix = bestLine(doc, cell.id, moving, settled);
    if (fix) {
      if (fix.axis === "x") cell.x += fix.delta;
      else cell.y += fix.delta;
      straightened += 1;
    }
    settled.add(cell.id);
  }
  return straightened;
}

// The line this cell should take.
//
// A cell that already has a straight wire keeps it: tidying must not trade one
// alignment for another, or a second Tidy would undo the first. Otherwise the
// cell lines up with whatever is staying put (rank 0) in preference to a cell
// that only settled this pass (rank 1), and with the neighbour on its left in
// preference to the one on its right, because drawings read that way. Among
// equals the shortest move wins, so nothing is flung across the sheet.
function bestLine(doc, cellId, moving, settled) {
  const cell = doc.cells.find((c) => c.id === cellId);
  const locked = new Set();
  let best = null;

  for (const net of doc.nets || []) {
    // Each branch is its own chance to line something up.
    for (const [mine, other] of branchPairs(net, cellId)) {
    const fix = guides.straighten(doc, mine, other);
    if (!fix) continue;
    if (!fix.delta) {
      locked.add(fix.axis);
      continue;
    }

    const rank = moving.has(other.cell) ? 1 : 0;
    if (rank === 1 && !settled.has(other.cell)) continue;

    const neighbour = doc.cells.find((c) => c.id === other.cell);
    const side = neighbour && cell && neighbour.x < cell.x ? 0 : 1;
    const score = [rank, side, Math.abs(fix.delta)];
    if (best && !better(score, best.score)) continue;
    best = { axis: fix.axis, delta: fix.delta, score };
    }
  }

  if (!best || locked.has(best.axis)) return null;
  return best;
}

// The ends of each branch of a net that touch this cell, paired with the end
// at the other side of that branch.
function branchPairs(net, cellId) {
  const pairs = [];
  const driver = net.from;
  for (const load of routing.loadsOf(net)) {
    if (!driver || !load) continue;
    if (load.cell === cellId && driver.cell !== undefined
        && driver.cell !== cellId) {
      pairs.push([load, driver]);
    } else if (driver.cell === cellId && load.cell !== undefined
               && load.cell !== cellId) {
      pairs.push([driver, load]);
    }
  }
  return pairs;
}

function better(score, than) {
  for (let i = 0; i < score.length; i += 1) {
    if (score[i] !== than[i]) return score[i] < than[i];
  }
  return false;
}

export function distribute(doc, ids, axis) {
  if (ids.size < 3) return false;
  const entries = [...ids]
    .map((id) => ({ id, box: itemBounds(doc, itemById(doc, id)) }))
    .filter((e) => e.box)
    .sort((a, b) => (axis === "h" ? a.box[0] - b.box[0] : a.box[1] - b.box[1]));

  const first = entries[0].box;
  const last = entries[entries.length - 1].box;
  const span = axis === "h"
    ? (last[0] + last[2] / 2) - (first[0] + first[2] / 2)
    : (last[1] + last[3] / 2) - (first[1] + first[3] / 2);
  const step = span / (entries.length - 1);

  entries.forEach((entry, index) => {
    if (index === 0 || index === entries.length - 1) return;
    const box = entry.box;
    if (axis === "h") {
      const target = first[0] + first[2] / 2 + step * index;
      moveItems(doc, new Set([entry.id]), target - (box[0] + box[2] / 2), 0);
    } else {
      const target = first[1] + first[3] / 2 + step * index;
      moveItems(doc, new Set([entry.id]), 0, target - (box[1] + box[3] / 2));
    }
  });
  return true;
}

// ---- clipboard ----

export function copyItems(doc, ids) {
  const cells = doc.cells.filter((c) => ids.has(c.id));
  const shapes = (doc.shapes || []).filter((s) => ids.has(s.id));
  // Wires between two copied cells travel with them; a wire with one end
  // outside the selection would have nothing to attach to.
  const inside = (endpoint) =>
    endpoint && endpoint.cell !== undefined && ids.has(endpoint.cell);
  const nets = doc.nets
    .filter((net) => inside(net.from) && routing.loadsOf(net).some(inside))
    .map((net) => ({ ...net, to: routing.loadsOf(net).filter(inside) }));
  return JSON.parse(JSON.stringify({ cells, shapes, nets }));
}

export function pasteItems(doc, clip, dx, dy) {
  const remap = new Map();
  const added = [];

  for (const source of clip.cells || []) {
    const cell = JSON.parse(JSON.stringify(source));
    cell.id = uniqueId(doc, "c");
    remap.set(source.id, cell.id);
    cell.x += dx;
    cell.y += dy;
    if (cell.label) cell.label = labelFor(doc, cell.type);
    doc.cells.push(cell);
    added.push(cell.id);
  }

  for (const source of clip.shapes || []) {
    const shape = JSON.parse(JSON.stringify(source));
    shape.id = uniqueId(doc, "s");
    if (shape.points) shape.points = shape.points.map((p) => [p[0] + dx, p[1] + dy]);
    if (shape.x !== undefined) shape.x += dx;
    if (shape.y !== undefined) shape.y += dy;
    doc.shapes = doc.shapes || [];
    doc.shapes.push(shape);
    added.push(shape.id);
  }

  for (const source of clip.nets || []) {
    const net = JSON.parse(JSON.stringify(source));
    net.id = uniqueId(doc, "n");
    if (net.from && remap.has(net.from.cell)) {
      net.from.cell = remap.get(net.from.cell);
    }
    net.to = routing.loadsOf(net).map((load) => {
      if (remap.has(load.cell)) load.cell = remap.get(load.cell);
      load.waypoints = (load.waypoints || []).map((p) => [p[0] + dx, p[1] + dy]);
      return load;
    });
    doc.nets.push(net);
  }

  return added;
}

// ---- groups ----

export function groupItems(doc, ids) {
  if (ids.size < 2) return null;
  doc.groups = doc.groups || [];
  // A cell belongs to at most one group, so grouping absorbs any existing
  // groups the selection overlapped.
  doc.groups = doc.groups
    .map((group) => ({
      ...group,
      members: group.members.filter((m) => !ids.has(m)),
    }))
    .filter((group) => group.members.length > 1);

  const group = { id: uniqueId(doc, "g"), label: null, members: [...ids] };
  doc.groups.push(group);
  return group;
}

export function ungroupItems(doc, ids) {
  doc.groups = (doc.groups || []).filter(
    (group) => !group.members.some((m) => ids.has(m)));
}

export function groupOf(doc, id) {
  return (doc.groups || []).find((g) => g.members.includes(id)) || null;
}

// Selecting one member of a group selects the whole group, which is what makes
// a group feel like a single object to drag and resize.
export function expandGroups(doc, ids) {
  const out = new Set(ids);
  for (const id of ids) {
    const group = groupOf(doc, id);
    if (group) group.members.forEach((m) => out.add(m));
  }
  return out;
}

// ---- nets ----

function sameEnd(a, b) {
  if (!a || !b) return false;
  return a.cell === b.cell && a.pin === b.pin;
}

function pinWidth(doc, endpoint) {
  if (!endpoint || endpoint.cell === undefined) return 1;
  const cell = doc.cells.find((c) => c.id === endpoint.cell);
  if (!cell) return 1;
  const pin = geometry.findPin(geometry.forCell(cell), endpoint.pin);
  return pin ? (pin.width === undefined ? 1 : pin.width) : 1;
}

// Wiring a second load onto a pin that already drives one extends that net
// rather than making another. That is what a net is: one driver, many loads.
export function addNet(doc, from, to) {
  const already = doc.nets.some((net) =>
    routing.loadsOf(net).some((load) =>
      (sameEnd(net.from, from) && sameEnd(load, to))
      || (sameEnd(net.from, to) && sameEnd(load, from))));
  if (already) return null;

  const load = { ...to, waypoints: [] };
  const existing = doc.nets.find((net) => sameEnd(net.from, from));
  if (existing) {
    existing.to = [...routing.loadsOf(existing), load];
    return existing;
  }

  // Width 0 means "any width", so it never decides the net's width.
  const net = {
    id: uniqueId(doc, "n"),
    name: null,
    width: pinWidth(doc, from) || pinWidth(doc, to) || 1,
    from,
    to: [load],
    style: {},
  };
  doc.nets.push(net);
  return net;
}

export function setNetName(doc, id, name) {
  const net = doc.nets.find((n) => n.id === id);
  if (!net) return;
  net.name = name || null;
  net.width = busWidth(name);
}

// Waypoints belong to one branch, since a net may have several and they go
// different ways. `branch` is the index of the load the wire ends at.
export function setWaypoints(doc, id, points, branch = 0) {
  const net = doc.nets.find((n) => n.id === id);
  if (!net) return;
  const loads = routing.loadsOf(net);
  if (loads[branch]) loads[branch].waypoints = points;
  net.to = loads;
}

// `d[7:0]` is eight bits; a plain name is one. Mirrors doc.py.
export function busWidth(name) {
  if (!name) return 1;
  const range = /^[A-Za-z_][A-Za-z0-9_.$]*\[(\d+):(\d+)\]$/.exec(name);
  if (range) return Math.abs(Number(range[1]) - Number(range[2])) + 1;
  return 1;
}
