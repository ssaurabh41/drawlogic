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
    // Two counters, because there are two different questions.
    //
    // `opening` changes only when a document is loaded -- a different file,
    // or the same file re-read from disk. `generation` changes on that and
    // on every edit besides.
    //
    // A request that takes a moment notes both before it goes. A layout
    // answer asks the first question: is this still the same open document?
    // It may be applied over edits made while it was computed, because it is
    // applied as an edit of its own. A save asks both: the bytes that went
    // to disk are only what was there at the time, so anything typed since
    // is still unsaved.
    this.opening = 0;
    this.generation = 0;
    this._undo = [];
    this._redo = [];
    this._listeners = [];
  }

  // What a pending request has to match to still be about this document.
  stamp() {
    return {
      path: this.path,
      opening: this.opening,
      generation: this.generation,
    };
  }

  // `edits: false` asks only whether this is still the same open document --
  // not whether it has been edited since. Checking the path alone is not
  // enough for that: re-opening the same file gives a different document
  // under the same name, and an answer about the copy that was replaced must
  // not be applied to the one that replaced it.
  matches(stamp, { edits = true } = {}) {
    if (!stamp || stamp.path !== this.path) return false;
    if (stamp.opening !== this.opening) return false;
    return !edits || stamp.generation === this.generation;
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
    this.opening += 1;
    this.generation += 1;
    this._undo = [];
    this._redo = [];
    this.emit("load");
  }

  // Everything about the open drawing that belongs to it rather than to the
  // editor, so a tab can put it away and bring it back as it was -- history
  // included, which is the difference between a tab and reopening the file.
  capture() {
    return { doc: this.doc, path: this.path, dirty: this.dirty,
             undo: this._undo, redo: this._redo };
  }

  restore(state) {
    this.doc = state.doc;
    this.path = state.path;
    this.dirty = state.dirty;
    this._undo = state.undo;
    this._redo = state.redo;
    // A different drawing is open now, so an answer still on its way for the
    // one before -- a layout, a check -- must be recognised as stale.
    this.opening += 1;
    this.generation += 1;
    this._gesture = null;
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

    // Only the first mutation of a gesture keeps its snapshot, so only the
    // first one needs to take it. A drag fires a mutation per pointer move
    // and every one of them used to serialise and reparse the whole
    // document -- embedded images included -- to build an undo entry that
    // was then thrown away.
    const inGesture = this._gesture !== null && this._gesture !== undefined;
    const recording = !inGesture || !this._gestureOpen;
    const before = recording ? this.snapshot() : null;

    const result = change(this.doc);
    if (result === false) return null;

    if (recording) {
      this._undo.push({ label, doc: before });
      if (this._undo.length > UNDO_LIMIT) this._undo.shift();
      if (inGesture) this._gestureOpen = true;
    }

    this._redo = [];
    this.dirty = true;
    this.generation += 1;
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

  // Only the state that was actually written is clean. Clearing the flag
  // unconditionally told the user their work was safe when an edit made
  // during the save had never left the browser -- and the flag is what the
  // close-tab warning reads.
  markSaved(stamp) {
    if (stamp && !this.matches(stamp)) return false;
    this.dirty = false;
    this.emit("saved");
    return true;
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
    dffr: "FF", dlatch: "L", mux2: "M", mux4: "M",
    nmos: "MN", pmos: "MP", resistor: "R", capacitor: "C",
  };
  const prefix = prefixes[type] || "U";
  const used = new Set(doc.cells.map((c) => c.label).filter(Boolean));
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

export function gridStep(doc) {
  return Number((doc.canvas.grid || {}).size) || 5;
}

export function snap(value, step) {
  return step ? Math.round(value / step) * step : value;
}

// The step a wire is dragged on, which is not the step a cell is dropped on.
// Pins land on multiples of drc.PIN_GRID, so a wire dragged on the drawing's
// own grid -- 10 in many drawings -- could never meet a pin sitting at a multiple of
// 5 that is not a multiple of 10, which is where a port's connector always is.
// It stopped short every time and the near-miss was drawn as a kink. A finer
// grid than that is honoured as it stands: the rule is a ceiling, not a step
// of its own.
export function wireStep(doc) {
  const grid = gridStep(doc);
  const pins = routing.currentLimits().pinGrid || 5;
  return Math.min(grid, pins);
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

// A fresh drawing, in the shape doc.py normalises to. The sheet size comes
// from the DRC limits the server sent, so a new drawing here is the same
// size as one made by `drawlogic` on the command line.
export function blankDocument(title) {
  const size = routing.currentLimits();
  return {
    format: "drawlogic",
    version: 2,
    title: title || "untitled",
    canvas: {
      width: size.sheetW,
      height: size.sheetH,
      grid: { style: "blank", size: 5 },
      font: { family: "IBM Plex Sans", scale: 1 },
      symbolScale: 1,
      arrows: true,
      hops: true,
    },
    cells: [],
    nets: [],
    shapes: [],
    groups: [],
  };
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

// Text written inside a cell, one line per line typed. The box grows to hold
// it unless fitting has been switched off -- the same rule doc.py applies on
// load, so a file reads back the size the editor left it.
export function fitCell(doc, cell) {
  const symbol = geometry.forCell(cell);
  if (!symbol) return false;
  const fontScale = Number(((doc.canvas || {}).font || {}).scale) || 1;
  return geometry.fitCellText(symbol, cell, routing.symbolScale(doc), fontScale);
}

export function setCellText(doc, id, raw) {
  // A shape with writing in it takes the same.
  const cell = itemById(doc, id);
  if (!cell) return;
  const lines = String(raw || "").replace(/\r/g, "").split("\n")
    .map((line) => line.replace(/\s+$/, ""));
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  if (lines.length) cell.text = lines;
  else delete cell.text;
  fitCell(doc, cell);
}

export function setTextFit(doc, id, fit) {
  const cell = doc.cells.find((c) => c.id === id);
  if (!cell) return;
  if (fit) delete cell.textFit;
  else cell.textFit = false;
  fitCell(doc, cell);
}

// Where a cell's text sits: `key` is "textAlign" (across) or "textVAlign"
// (down). The default -- centre, middle -- is left out of the file rather
// than written into it, so a drawing that never chose says nothing.
export function setTextAlign(doc, id, key, value) {
  // A shape with writing in it takes the same.
  const cell = itemById(doc, id);
  const choices = key === "textAlign" ? geometry.TEXT_ALIGN : geometry.TEXT_VALIGN;
  if (!cell || !choices.includes(value)) return false;
  if (value === choices[0]) delete cell[key];
  else cell[key] = value;
  return true;
}

// How many copies a cell stands for; anything under two is just the one.
export function setCopies(doc, id, value) {
  // A shape with writing in it takes the same.
  const cell = itemById(doc, id);
  if (!cell) return false;
  const number = Math.trunc(Number(value));
  if (String(value).trim() === "" || number < 2) delete cell.copies;
  else if (Number.isFinite(number)) cell.copies = Math.min(number, 999);
  else return false;
  return true;
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

// Shapes and symbols share one stacking order: each may carry a `z`, and the
// drawing is painted from the lowest up, a shape before a symbol at the same
// z (see drawOrder in render.js). Nothing carries one by default, which is
// what keeps shapes behind symbols until someone says otherwise. Front and
// back set the selection past everything else, keeping its own order.
function stack(doc, ids, toFront) {
  const all = [...(doc.cells || []), ...(doc.shapes || [])];
  const others = all.filter((i) => !ids.has(i.id)).map((i) => i.z || 0);
  const z = toFront ? Math.max(0, ...others) + 1 : Math.min(0, ...others) - 1;
  for (const item of all) {
    if (ids.has(item.id)) item.z = z;
  }
  const move = (list) => {
    const staying = list.filter((i) => !ids.has(i.id));
    const moving = list.filter((i) => ids.has(i.id));
    return toFront ? [...staying, ...moving] : [...moving, ...staying];
  };
  doc.cells = move(doc.cells);
  doc.shapes = move(doc.shapes || []);
}

export function bringToFront(doc, ids) { stack(doc, ids, true); }

export function sendToBack(doc, ids) { stack(doc, ids, false); }

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

  // Whole groups only. A group half inside the selection would paste as a
  // group naming members that were never copied, so a partial one is left
  // behind and its copied members arrive loose. Without this the clipboard
  // carried no groups at all, and duplicating a grouped block gave you a
  // pile of separate parts that had to be grouped again by hand.
  const groups = (doc.groups || [])
    .filter((group) => group.members.length > 1
                       && group.members.every((m) => ids.has(m)));

  return JSON.parse(JSON.stringify({ cells, shapes, nets, groups }));
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
    // Shapes go in the remap too, not because a wire can land on one, but
    // because a group can contain one -- ids are unique across the document,
    // so the two kinds share the map safely.
    remap.set(source.id, shape.id);
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

  for (const source of clip.groups || []) {
    // Every member was remapped above, or the group would not have been
    // copied. Anything that somehow was not is dropped rather than left
    // pointing at the original, which would tie the copy to the thing it
    // was copied from.
    const members = source.members
      .map((id) => remap.get(id))
      .filter((id) => id !== undefined);
    if (members.length < 2) continue;
    doc.groups = doc.groups || [];
    doc.groups.push({ id: uniqueId(doc, "g"), label: source.label || null,
                      members });
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

function pinDir(doc, endpoint) {
  if (!endpoint || endpoint.cell === undefined) return null;
  const cell = doc.cells.find((c) => c.id === endpoint.cell);
  if (!cell) return null;
  const pin = geometry.findPin(geometry.forCell(cell), endpoint.pin);
  return pin ? (pin.dir || "inout") : null;
}

// Wiring a second load onto a pin that already drives one extends that net
// rather than making another. That is what a net is: one driver, many loads.
// How near a dropped cell's pin has to land to join something. Cells snap to
// the drawing's grid -- 5 by default, 10 in many drawings -- while pins sit on
// the pin grid (5), so on a 10 grid a drop can land a
// pin up to 5 from the one it was aimed at; just over that reaches it, and
// stays well short of the next pin along a side.
const JOIN_REACH = 6;

// Join a just-dropped cell's free pins to whatever they landed on: another
// cell's free pin, or a wire end that stops on nothing. Only pins with nothing
// on them yet are joined, and never two cells of the same drop to each other,
// since a group that was already side by side has not landed on anything.
// Returns what was joined, as ["u1.y to ff1.d", ...], for the caller to say.
export function autoConnect(doc, cellIds) {
  const moving = new Set(cellIds);
  const scale = symbolScale(doc);
  const used = new Set();
  const loose = [];
  for (const net of doc.nets) {
    for (const end of [net.from, ...routing.loadsOf(net)]) {
      if (!end) continue;
      if (end.cell !== undefined) used.add(`${end.cell}|${end.pin}`);
      else if (end.x !== undefined && end.y !== undefined) loose.push(end);
    }
  }
  const pinsOf = (cell) => {
    const symbol = geometry.forCell(cell);
    if (!symbol) return [];
    return symbol.pins.map((pin) => ({
      cell: cell.id, pin: pin.name,
      at: geometry.pinPosition(symbol, cell, pin.name, scale),
    })).filter((p) => p.at && !used.has(`${p.cell}|${p.pin}`));
  };
  const near = (a, b) => Math.abs(a[0] - b[0]) <= JOIN_REACH
    && Math.abs(a[1] - b[1]) <= JOIN_REACH;

  const others = doc.cells.filter((c) => !moving.has(c.id)).flatMap(pinsOf);
  const joined = [];
  for (const cell of doc.cells.filter((c) => moving.has(c.id))) {
    for (const mine of pinsOf(cell)) {
      const end = loose.find((e) => near([e.x, e.y], mine.at));
      if (end) {
        delete end.x;
        delete end.y;
        end.cell = mine.cell;
        end.pin = mine.pin;
        loose.splice(loose.indexOf(end), 1);
        joined.push(`${mine.cell}.${mine.pin} to a loose wire end`);
        continue;
      }
      const other = others.find((p) => !used.has(`${p.cell}|${p.pin}`)
                                        && near(p.at, mine.at));
      if (!other) continue;
      if (addNet(doc, { cell: mine.cell, pin: mine.pin },
                 { cell: other.cell, pin: other.pin })) {
        used.add(`${other.cell}|${other.pin}`);
        joined.push(`${mine.cell}.${mine.pin} to ${other.cell}.${other.pin}`);
      }
    }
  }
  return joined;
}

// Placing from the palette in one step: while a new cell is carried over the
// sheet, a pin of it that comes near a free pin facing it snaps into line,
// and dropping it there wires the two. Aimed by eye, with a preview showing
// the result before the button is let go, so the reach is generous.
const SNAP_REACH = 30;
// The two snapped pins sit a short straight wire apart rather than on top of
// each other: the join can be seen, and the cells do not touch -- which the
// DRCs would rightly ring.
export const SNAP_LEAD = 20;

// Which way a pin leaves its cell, "left" or "right", or null for one on the
// top or bottom edge. Read from where it sits on the placed cell, so a
// rotated or mirrored cell answers for how it is drawn.
function pinFacing(cell, at, scale) {
  const symbol = geometry.forCell(cell);
  const box = symbol && geometry.cellBounds(symbol, cell, scale);
  if (!box || !at) return null;
  if (Math.abs(at[0] - box[0]) < 0.5) return "left";
  if (Math.abs(at[0] - (box[0] + box[2])) < 0.5) return "right";
  return null;
}

// Where a cell of `type` let go at `point` would land, snapped to the nearest
// free pin it could join, or null when none is in reach. `wire` is the join
// to preview; `box` is the cell's outline there.
export function snapPlacement(doc, type, point) {
  const symbol = geometry.get(type);
  if (!symbol) return null;
  const step = gridStep(doc);
  return snapCell(doc, {
    id: "\u0000probe", type, rotate: 0, mirror: false,
    x: snap(point[0] - symbol.size[0] / 2, step),
    y: snap(point[1] - symbol.size[1] / 2, step),
    w: symbol.size[0], h: symbol.size[1],
  });
}

// The same question for a cell already on the sheet, as it is being dragged:
// where it would land snapped to a free pin in reach, or null. Its own pins
// are never targets, and a pin of it that is already wired does not snap --
// it has somewhere to go. Used by the move, so carrying a placed cell to a
// pin rings that pin and joins it, exactly as dropping one from the palette.
export function snapCell(doc, probe) {
  const symbol = geometry.forCell(probe);
  if (!symbol) return null;
  const scale = symbolScale(doc);

  const used = new Set();
  const loose = [];
  for (const net of doc.nets) {
    for (const end of [net.from, ...routing.loadsOf(net)]) {
      if (!end) continue;
      if (end.cell !== undefined) used.add(`${end.cell}|${end.pin}`);
      else if (end.x !== undefined && end.y !== undefined) loose.push([end.x, end.y]);
    }
  }
  const targets = [];
  for (const cell of doc.cells) {
    if (cell.id === probe.id) continue;
    const other = geometry.forCell(cell);
    if (!other) continue;
    for (const pin of other.pins) {
      if (used.has(`${cell.id}|${pin.name}`)) continue;
      const at = geometry.pinPosition(other, cell, pin.name, scale);
      const facing = pinFacing(cell, at, scale);
      if (facing) targets.push({ cell: cell.id, pin: pin.name, at, facing });
    }
  }

  let best = null;
  for (const pin of symbol.pins) {
    if (used.has(`${probe.id}|${pin.name}`)) continue;
    const at = geometry.pinPosition(symbol, probe, pin.name, scale);
    const facing = pinFacing(probe, at, scale);
    if (!at) continue;
    const offers = loose.map((end) => ({ want: end, target: { loose: end } }));
    for (const target of targets) {
      // Only pins that face each other: an input on the left of the new cell
      // meets an output on the right of the old one, and the other way round.
      if (facing === "left" && target.facing === "right") {
        offers.push({ want: [target.at[0] + SNAP_LEAD, target.at[1]], target });
      } else if (facing === "right" && target.facing === "left") {
        offers.push({ want: [target.at[0] - SNAP_LEAD, target.at[1]], target });
      }
    }
    for (const { want, target } of offers) {
      const distance = Math.hypot(want[0] - at[0], want[1] - at[1]);
      if (distance > SNAP_REACH || (best && distance >= best.distance)) continue;
      const dx = want[0] - at[0];
      const dy = want[1] - at[1];
      best = {
        distance, pin: pin.name, target,
        x: probe.x + dx, y: probe.y + dy,
        box: [probe.x + dx, probe.y + dy, probe.w || symbol.size[0],
              probe.h || symbol.size[1]],
        wire: [want, target.loose || target.at],
      };
    }
  }
  return best;
}

// Place a cell where it was let go -- snapped to a pin in reach when
// `connect` is on -- and wire it to what it landed by. Returns the cell and
// what was joined, as autoConnect does.
export function placeCell(doc, type, point, connect = true) {
  const snapped = connect ? snapPlacement(doc, type, point) : null;
  const cell = addCell(doc, type, point[0], point[1]);
  if (!cell) return { cell: null, joined: [] };
  const joined = [];
  if (snapped) {
    cell.x = snapped.x;
    cell.y = snapped.y;
    const { target } = snapped;
    if (!target.loose && addNet(doc, { cell: cell.id, pin: snapped.pin },
                                { cell: target.cell, pin: target.pin })) {
      joined.push(`${cell.id}.${snapped.pin} to ${target.cell}.${target.pin}`);
    }
  }
  if (connect) joined.push(...autoConnect(doc, [cell.id]));
  return { cell, joined };
}

export function addNet(doc, from, to) {
  // Clicking the flip-flop's D and then the gate that feeds it is an ordinary
  // way to draw a wire, and it is the same connection either way -- but the
  // net is stored driver-first, and the arrowhead reads that order. So the
  // ends are put the right way round here, as the wire is made, rather than
  // being left for the next time the drawing is opened. `inout` is left alone:
  // deciding one of those is the layout's job, which knows where the cell sits.
  if (pinDir(doc, from) === "in" && pinDir(doc, to) === "out") {
    [from, to] = [to, from];
  }
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

// The text drawn on a wire. Separate from the name: a name is an identifier
// that sets the bus width, a label is whatever the drawing should say.
export function setNetLabel(doc, id, label) {
  const net = doc.nets.find((n) => n.id === id);
  if (!net) return;
  const text = String(label || "").trim();
  if (text) net.label = text;
  else delete net.label;
}

// One key of a wire's style; null or "" puts the default back.
export function setNetStyle(doc, id, key, value) {
  const net = doc.nets.find((n) => n.id === id);
  if (!net) return;
  net.style = net.style || {};
  if (value === null || value === "" || value === undefined) delete net.style[key];
  else net.style[key] = value;
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

// ---- dragging a wire by one of its runs ----

// Which run of which branch a point is nearest, ready to be dragged.
//
// The run is returned with a copy of its whole path, and with a duplicate
// point inserted when the run is at either end. An end run has a pin on one
// side that cannot move, so there is nothing to absorb the drag; the
// duplicate starts as a zero-length segment and becomes the corner that
// holds the new position.
export function grabRun(doc, netId, point) {
  const net = (doc.nets || []).find((n) => n.id === netId);
  if (!net) return null;

  let best = null;
  routing.route(doc, net).forEach((points, branch) => {
    for (let i = 0; i < points.length - 1; i += 1) {
      const away = distanceToRun(point, points[i], points[i + 1]);
      if (!best || away < best.away) best = { away, branch, index: i, points };
    }
  });
  if (!best) return null;

  const points = best.points.map((p) => [p[0], p[1]]);
  let index = best.index;
  if (index === 0) {
    points.splice(1, 0, [points[0][0], points[0][1]]);
    index = 1;
  }
  if (index === points.length - 2) {
    const last = points[points.length - 1];
    points.splice(points.length - 1, 0, [last[0], last[1]]);
  }

  const a = points[index];
  const b = points[index + 1];
  return {
    branch: best.branch,
    index,
    points,
    horizontal: Math.abs(a[1] - b[1]) < Math.abs(a[0] - b[0]) || a[1] === b[1],
  };
}

// Which branch of which net passes nearest a point, within `reach` sheet
// units, or null when nothing does. Used by the eraser, which has no element
// under the cursor to go on: it is asked about a position, not a click.
export function branchAt(doc, point, reach) {
  let best = null;
  for (const net of doc.nets || []) {
    routing.route(doc, net).forEach((points, branch) => {
      for (let i = 0; i < points.length - 1; i += 1) {
        const away = distanceToRun(point, points[i], points[i + 1]);
        if (away <= reach && (!best || away < best.away)) {
          best = { away, netId: net.id, branch };
        }
      }
    });
  }
  return best;
}

// Erase one branch of a net: the run from one load back to wherever it parts
// company with the rest.
//
// This is what there is to erase. A net is one driver and its loads, so the
// wire from the junction dot to a reset pin is not a piece of drawing that
// can be rubbed out on its own -- it is that load's whole share of the net,
// and taking the load away is what makes it go. The trunk stays, because the
// other loads are still using it. Erasing the last load leaves a net driving
// nothing, which is not a net, so the net goes too.
export function deleteBranch(doc, netId, branch) {
  const net = (doc.nets || []).find((n) => n.id === netId);
  if (!net) return null;
  const loads = routing.loadsOf(net);
  if (branch < 0 || branch >= loads.length) return null;
  const gone = loads[branch];
  loads.splice(branch, 1);
  if (loads.length) {
    net.to = loads;
  } else {
    doc.nets = doc.nets.filter((n) => n.id !== netId);
  }
  return { netId, pin: gone && gone.pin, cell: gone && gone.cell,
           netGone: loads.length === 0 };
}

function distanceToRun(point, a, b) {
  const x = Math.min(Math.max(point[0], Math.min(a[0], b[0])), Math.max(a[0], b[0]));
  const y = Math.min(Math.max(point[1], Math.min(a[1], b[1])), Math.max(a[1], b[1]));
  return Math.hypot(point[0] - x, point[1] - y);
}

// Put a grabbed run at `value` -- a y for a horizontal run, an x for a
// vertical one -- and hand the branch over to hand routing.
//
// Dragging a wire is what decides it is routed by hand: every corner becomes
// a waypoint, so it stays exactly where it was put rather than being
// re-derived into something else on the next redraw. `straighten` gives it
// back to the router.
export function slideRun(doc, netId, run, value) {
  const points = run.points.map((p) => [p[0], p[1]]);
  const axis = run.horizontal ? 1 : 0;
  points[run.index][axis] = value;
  points[run.index + 1][axis] = value;

  const tidy = routing.clean(points);
  setWaypoints(doc, netId, tidy.slice(1, -1), run.branch);
}

// Hand a branch back to the router.
export function straighten(doc, netId, branch = 0) {
  setWaypoints(doc, netId, [], branch);
}

// `d[7:0]` is eight bits; a plain name is one. Mirrors doc.py.
export function busWidth(name) {
  if (!name) return 1;
  const range = /^[A-Za-z_][A-Za-z0-9_.$]*\[(\d+):(\d+)\]$/.exec(name);
  if (range) return Math.abs(Number(range[1]) - Number(range[2])) + 1;
  return 1;
}
