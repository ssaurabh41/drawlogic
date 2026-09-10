// The symbol library, fetched from the server so the browser draws from the
// very same definitions the exporter uses, --symbols-dir overrides included.

import { boundsOf, cellMatrix, corners } from "./geometry.js";

let library = {};

export function setLibrary(data) {
  library = data || {};
}

export function get(typeId) {
  return library[typeId] || null;
}

export function ids() {
  return Object.keys(library).sort();
}

export function byCategory() {
  const groups = {};
  for (const id of ids()) {
    const category = library[id].category || "misc";
    (groups[category] = groups[category] || []).push(id);
  }
  return groups;
}

export function findPin(symbol, name) {
  if (!symbol) return null;
  return symbol.pins.find((pin) => pin.name === name) || null;
}

// `scale` is the document-wide symbol scale. It grows a cell about its own
// centre, so turning every gate up does not drag the layout sideways.
export function matrixFor(symbol, cell, scale = 1) {
  let x = cell.x || 0;
  let y = cell.y || 0;
  let w = cell.w === undefined ? symbol.size[0] : cell.w;
  let h = cell.h === undefined ? symbol.size[1] : cell.h;

  if (scale !== 1) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    w *= scale;
    h *= scale;
    x = cx - w / 2;
    y = cy - h / 2;
  }

  return cellMatrix(x, y, w, h, symbol.size[0], symbol.size[1],
                    cell.rotate || 0, Boolean(cell.mirror));
}

export function pinPosition(symbol, cell, pinName, scale = 1) {
  const pin = findPin(symbol, pinName);
  if (!pin) return null;
  return matrixFor(symbol, cell, scale).apply(pin.x, pin.y);
}

export function cellBounds(symbol, cell, scale = 1) {
  const matrix = matrixFor(symbol, cell, scale);
  const points = corners(0, 0, symbol.size[0], symbol.size[1])
    .map(([px, py]) => matrix.apply(px, py));
  return boundsOf(points);
}
