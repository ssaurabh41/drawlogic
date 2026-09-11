// Every change a document can undergo.
//
// Keeping these in one file means a new editing feature adds a function here
// and a binding in main.js, rather than spreading document surgery across the
// tools that happen to trigger it.

import * as symbols from "./symbols.js";

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

export function addCell(doc, type, x, y) {
  const symbol = symbols.get(type);
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

export function moveCells(doc, ids, dx, dy) {
  for (const cell of doc.cells) {
    if (!ids.has(cell.id)) continue;
    cell.x += dx;
    cell.y += dy;
  }
}

export function setCellBox(doc, id, box) {
  const cell = doc.cells.find((c) => c.id === id);
  if (!cell) return;
  cell.x = box.x;
  cell.y = box.y;
  cell.w = Math.max(4, box.w);
  cell.h = Math.max(4, box.h);
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
export function deleteCells(doc, ids) {
  doc.cells = doc.cells.filter((cell) => !ids.has(cell.id));
  doc.nets = doc.nets.filter((net) => {
    for (const side of ["from", "to"]) {
      const endpoint = net[side];
      if (endpoint && endpoint.cell !== undefined && ids.has(endpoint.cell)) {
        return false;
      }
    }
    return true;
  });
  doc.groups = (doc.groups || [])
    .map((group) => ({
      ...group,
      members: group.members.filter((m) => !ids.has(m)),
    }))
    .filter((group) => group.members.length > 1);
}

export function setStyle(doc, ids, key, value) {
  for (const cell of doc.cells) {
    if (!ids.has(cell.id)) continue;
    cell.style = cell.style || {};
    if (value === null || value === "") delete cell.style[key];
    else cell.style[key] = value;
  }
}

export function setLabel(doc, id, label) {
  const cell = doc.cells.find((c) => c.id === id);
  if (cell) cell.label = label || null;
}

// ---- clipboard ----

export function copyCells(doc, ids) {
  const cells = doc.cells.filter((c) => ids.has(c.id));
  // Wires between two copied cells travel with them; a wire with one end
  // outside the selection would have nothing to attach to.
  const nets = doc.nets.filter((net) =>
    ["from", "to"].every((side) => {
      const endpoint = net[side];
      return endpoint && endpoint.cell !== undefined && ids.has(endpoint.cell);
    }));
  return JSON.parse(JSON.stringify({ cells, nets }));
}

export function pasteCells(doc, clip, dx, dy) {
  const remap = new Map();
  const added = [];

  for (const source of clip.cells) {
    const cell = JSON.parse(JSON.stringify(source));
    cell.id = uniqueId(doc, "c");
    remap.set(source.id, cell.id);
    cell.x += dx;
    cell.y += dy;
    if (cell.label) cell.label = labelFor(doc, cell.type);
    doc.cells.push(cell);
    added.push(cell.id);
  }

  for (const source of clip.nets || []) {
    const net = JSON.parse(JSON.stringify(source));
    net.id = uniqueId(doc, "n");
    for (const side of ["from", "to"]) {
      if (net[side] && remap.has(net[side].cell)) {
        net[side].cell = remap.get(net[side].cell);
      }
    }
    net.waypoints = (net.waypoints || []).map((p) => [p[0] + dx, p[1] + dy]);
    doc.nets.push(net);
  }

  return added;
}

// ---- groups ----

export function groupCells(doc, ids) {
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

export function ungroupCells(doc, ids) {
  doc.groups = (doc.groups || []).filter(
    (group) => !group.members.some((m) => ids.has(m)));
}

export function groupOf(doc, cellId) {
  return (doc.groups || []).find((g) => g.members.includes(cellId)) || null;
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

export function addNet(doc, from, to) {
  const exists = doc.nets.some((net) =>
    (sameEnd(net.from, from) && sameEnd(net.to, to))
    || (sameEnd(net.from, to) && sameEnd(net.to, from)));
  if (exists) return null;

  const net = {
    id: uniqueId(doc, "n"),
    name: null,
    // Width 0 means "any width", so it never decides the net's width.
    width: pinWidth(doc, from) || pinWidth(doc, to) || 1,

    from,
    to,
    waypoints: [],
    style: {},
  };
  doc.nets.push(net);
  return net;
}

function sameEnd(a, b) {
  if (!a || !b) return false;
  return a.cell === b.cell && a.pin === b.pin;
}

function pinWidth(doc, endpoint) {
  if (!endpoint || endpoint.cell === undefined) return 1;
  const cell = doc.cells.find((c) => c.id === endpoint.cell);
  if (!cell) return 1;
  const symbol = symbols.get(cell.type);
  const pin = symbols.findPin(symbol, endpoint.pin);
  return pin ? (pin.width === undefined ? 1 : pin.width) : 1;
}

export function deleteNets(doc, ids) {
  doc.nets = doc.nets.filter((net) => !ids.has(net.id));
}

export function setNetName(doc, id, name) {
  const net = doc.nets.find((n) => n.id === id);
  if (!net) return;
  net.name = name || null;
  net.width = busWidth(name);
}

// `d[7:0]` is eight bits; a plain name is one. Mirrors buses.py.
export function busWidth(name) {
  if (!name) return 1;
  const range = /^[A-Za-z_][A-Za-z0-9_.$]*\[(\d+):(\d+)\]$/.exec(name);
  if (range) return Math.abs(Number(range[1]) - Number(range[2])) + 1;
  return 1;
}
