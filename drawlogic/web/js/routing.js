// Wire routing. A port of drawlogic/routing.py.
//
// Endpoints are pin references, never coordinates, so a wire is re-resolved
// from scratch on every draw. That is what makes dragging a gate carry its
// wires instead of leaving them behind.

import { corners } from "./geometry.js";
import * as symbols from "./symbols.js";

const STUB = 12;
const EPSILON = 1e-6;
const CLEARANCE = 8;
const CORRIDOR_STEP = 10;
const CORRIDOR_TRIES = 16;

function cellOf(doc, id) {
  return doc.cells.find((cell) => cell.id === id) || null;
}

export function endpointPosition(doc, endpoint) {
  if (!endpoint) return null;
  if (endpoint.cell !== undefined) {
    const cell = cellOf(doc, endpoint.cell);
    if (!cell) return null;
    const symbol = symbols.get(cell.type);
    if (!symbol) return null;
    return symbols.pinPosition(symbol, cell, endpoint.pin, symbolScale(doc));
  }
  if (endpoint.x !== undefined && endpoint.y !== undefined) {
    return [endpoint.x, endpoint.y];
  }
  return null;
}

export function symbolScale(doc) {
  const value = Number((doc.canvas || {}).symbolScale);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

export function endpointDirection(doc, endpoint) {
  if (!endpoint || endpoint.cell === undefined) return null;
  const cell = cellOf(doc, endpoint.cell);
  if (!cell) return null;
  const symbol = symbols.get(cell.type);
  if (!symbol) return null;
  const pin = symbols.findPin(symbol, endpoint.pin);
  if (!pin) return null;

  const [sw, sh] = symbol.size;
  let local;
  if (pin.x <= EPSILON) local = [-1, 0];
  else if (pin.x >= sw - EPSILON) local = [1, 0];
  else if (pin.y <= EPSILON) local = [0, -1];
  else if (pin.y >= sh - EPSILON) local = [0, 1];
  else local = [1, 0];

  const matrix = symbols.matrixFor(symbol, cell, symbolScale(doc));
  const origin = matrix.apply(0, 0);
  const tip = matrix.apply(local[0], local[1]);
  const dx = tip[0] - origin[0];
  const dy = tip[1] - origin[1];
  if (Math.abs(dx) >= Math.abs(dy)) return [dx > 0 ? 1 : -1, 0];
  return [0, dy > 0 ? 1 : -1];
}

export function obstacleBoxes(doc, exclude = new Set()) {
  const scale = symbolScale(doc);
  const boxes = [];
  for (const cell of doc.cells) {
    if (exclude.has(cell.id)) continue;
    const symbol = symbols.get(cell.type);
    if (!symbol) continue;
    const matrix = symbols.matrixFor(symbol, cell, scale);
    const points = corners(0, 0, symbol.size[0], symbol.size[1])
      .map(([px, py]) => matrix.apply(px, py));
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    boxes.push([
      Math.min(...xs) - CLEARANCE, Math.min(...ys) - CLEARANCE,
      Math.max(...xs) + CLEARANCE, Math.max(...ys) + CLEARANCE,
    ]);
  }
  return boxes;
}

function verticalClear(x, y0, y1, boxes) {
  const lo = Math.min(y0, y1);
  const hi = Math.max(y0, y1);
  return !boxes.some(([bx0, by0, bx1, by1]) =>
    bx0 <= x && x <= bx1 && !(hi < by0 || lo > by1));
}

function horizontalClear(y, x0, x1, boxes) {
  const lo = Math.min(x0, x1);
  const hi = Math.max(x0, x1);
  return !boxes.some(([bx0, by0, bx1, by1]) =>
    by0 <= y && y <= by1 && !(hi < bx0 || lo > bx1));
}

// Checks all three legs, not just the corridor: a corridor that dodges a gate
// is no use if the leg leading into it still ploughs through one.
function pickCorridor(preferred, spanLo, spanHi, pathIsClear) {
  if (pathIsClear(preferred)) return preferred;
  for (let step = 1; step <= CORRIDOR_TRIES; step += 1) {
    for (const candidate of [preferred + step * CORRIDOR_STEP,
                             preferred - step * CORRIDOR_STEP]) {
      if (candidate <= spanLo || candidate >= spanHi) continue;
      if (pathIsClear(candidate)) return candidate;
    }
  }
  return preferred;
}

function clean(points) {
  const out = [];
  for (const point of points) {
    const last = out[out.length - 1];
    if (last && Math.abs(last[0] - point[0]) < EPSILON
        && Math.abs(last[1] - point[1]) < EPSILON) continue;
    out.push(point);
  }
  if (out.length < 3) return out;

  const merged = [out[0]];
  for (let i = 1; i < out.length - 1; i += 1) {
    const prev = merged[merged.length - 1];
    const here = out[i];
    const next = out[i + 1];
    const sameX = Math.abs(prev[0] - here[0]) < EPSILON
      && Math.abs(here[0] - next[0]) < EPSILON;
    const sameY = Math.abs(prev[1] - here[1]) < EPSILON
      && Math.abs(here[1] - next[1]) < EPSILON;
    if (sameX || sameY) continue;
    merged.push(here);
  }
  merged.push(out[out.length - 1]);
  return merged;
}

function directRoute(start, end, startDir, endDir, boxes) {
  if (Math.abs(start[0] - end[0]) < EPSILON
      || Math.abs(start[1] - end[1]) < EPSILON) {
    return [start, end];
  }

  const startHorizontal = !startDir || Math.abs(startDir[0]) > Math.abs(startDir[1]);
  const endHorizontal = !endDir || Math.abs(endDir[0]) > Math.abs(endDir[1]);

  if (startHorizontal && endHorizontal) {
    const forward = (end[0] - start[0]) * (startDir ? startDir[0] : 1);
    if (forward > 2 * STUB) {
      const mid = pickCorridor(
        (start[0] + end[0]) / 2,
        Math.min(start[0], end[0]) + STUB, Math.max(start[0], end[0]) - STUB,
        (m) => verticalClear(m, start[1], end[1], boxes)
          && horizontalClear(start[1], start[0], m, boxes)
          && horizontalClear(end[1], m, end[0], boxes));
      return [start, [mid, start[1]], [mid, end[1]], end];
    }
    // Target sits behind the driving pin: break out, cross on a mid-line and
    // come back in rather than drawing through the cell.
    const outX = start[0] + (startDir ? startDir[0] : 1) * STUB;
    const inX = end[0] - (endDir ? endDir[0] : -1) * STUB;
    const midY = (start[1] + end[1]) / 2;
    return [start, [outX, start[1]], [outX, midY], [inX, midY], [inX, end[1]], end];
  }

  if (!startHorizontal && !endHorizontal) {
    const forward = (end[1] - start[1]) * (startDir ? startDir[1] : 1);
    if (forward > 2 * STUB) {
      const mid = pickCorridor(
        (start[1] + end[1]) / 2,
        Math.min(start[1], end[1]) + STUB, Math.max(start[1], end[1]) - STUB,
        (m) => horizontalClear(m, start[0], end[0], boxes)
          && verticalClear(start[0], start[1], m, boxes)
          && verticalClear(end[0], m, end[1], boxes));
      return [start, [start[0], mid], [end[0], mid], end];
    }
    const outY = start[1] + (startDir ? startDir[1] : 1) * STUB;
    const inY = end[1] - (endDir ? endDir[1] : -1) * STUB;
    const midX = (start[0] + end[0]) / 2;
    return [start, [start[0], outY], [midX, outY], [midX, inY], [end[0], inY], end];
  }

  if (startHorizontal) return [start, [end[0], start[1]], end];
  return [start, [start[0], end[1]], end];
}

function elbow(a, b, horizontalFirst) {
  if (Math.abs(a[0] - b[0]) < EPSILON || Math.abs(a[1] - b[1]) < EPSILON) return [];
  return horizontalFirst ? [[b[0], a[1]]] : [[a[0], b[1]]];
}

export function route(doc, net) {
  const start = endpointPosition(doc, net.from);
  const end = endpointPosition(doc, net.to);
  if (!start || !end) return [];

  const waypoints = (net.waypoints || []).map((p) => [p[0], p[1]]);

  if (!waypoints.length) {
    const exclude = new Set();
    for (const side of ["from", "to"]) {
      const endpoint = net[side];
      if (endpoint && endpoint.cell !== undefined) exclude.add(endpoint.cell);
    }
    return clean(directRoute(start, end,
                             endpointDirection(doc, net.from),
                             endpointDirection(doc, net.to),
                             obstacleBoxes(doc, exclude)));
  }

  const points = [start, ...waypoints, end];
  const chain = [points[0]];
  const startDir = endpointDirection(doc, net.from);
  let horizontalFirst = startDir
    ? Math.abs(startDir[0]) > Math.abs(startDir[1]) : true;
  for (let i = 0; i < points.length - 1; i += 1) {
    const corner = elbow(points[i], points[i + 1], horizontalFirst);
    chain.push(...corner, points[i + 1]);
    if (corner.length) horizontalFirst = !horizontalFirst;
  }
  return clean(chain);
}

export function routeAll(doc) {
  return doc.nets.map((net) => ({ net, points: route(doc, net) }));
}

function touches(point, [a, b]) {
  const [px, py] = point;
  if (Math.abs(a[0] - b[0]) < EPSILON) {
    if (Math.abs(px - a[0]) > EPSILON) return false;
    return Math.min(a[1], b[1]) - EPSILON <= py
      && py <= Math.max(a[1], b[1]) + EPSILON;
  }
  if (Math.abs(a[1] - b[1]) < EPSILON) {
    if (Math.abs(py - a[1]) > EPSILON) return false;
    return Math.min(a[0], b[0]) - EPSILON <= px
      && px <= Math.max(a[0], b[0]) + EPSILON;
  }
  return false;
}

// Counting rays rather than segments is what tells a tee (three) apart from an
// ordinary corner (two), so crossings stay undotted.
export function junctions(routes) {
  const segments = [];
  for (const { points } of routes) {
    for (let i = 0; i < points.length - 1; i += 1) {
      segments.push([points[i], points[i + 1]]);
    }
  }

  const candidates = new Map();
  for (const { points } of routes) {
    for (const point of points) {
      candidates.set(`${point[0].toFixed(3)},${point[1].toFixed(3)}`, point);
    }
  }

  const found = [];
  for (const point of candidates.values()) {
    const rays = new Set();
    for (const segment of segments) {
      if (!touches(point, segment)) continue;
      for (const other of segment) {
        const dx = other[0] - point[0];
        const dy = other[1] - point[1];
        if (Math.abs(dx) < EPSILON && Math.abs(dy) < EPSILON) continue;
        rays.add(Math.abs(dx) >= Math.abs(dy)
          ? `${dx > 0 ? 1 : -1},0` : `0,${dy > 0 ? 1 : -1}`);
      }
    }
    if (rays.size >= 3) found.push(point);
  }
  return found;
}
