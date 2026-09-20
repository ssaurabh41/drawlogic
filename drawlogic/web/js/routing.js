// Wire routing. A port of drawlogic/routing.py.
//
// Endpoints are pin references, never coordinates, so a wire is re-resolved
// from scratch on every draw. That is what makes dragging a gate carry its
// wires instead of leaving them behind.

import * as geometry from "./geometry.js";

const STUB = 12;
const EPSILON = 1e-6;

// Cell types that stand for the edge of the sheet rather than for a part.
const PORT_CATEGORY = "ports";

// The DRC limits, mirrored from drawlogic/drc.py. The editor overwrites these
// from /api/drc at startup so a drag obeys the same distances the exporter
// does; the defaults are here only so this module still routes when it is
// loaded on its own, as the parity harness does. tests/test_js_parity.py
// checks the defaults still match the Python, since a stale copy here would
// route the canvas differently from the file it exports.
let limits = {
  wireToCell: 10,
  textToWire: 6,
  corridorStep: 10,
  corridorTries: 18,
  wireGap: 18,
  touching: 0.5,
  arrowToJunction: 12,
  hopGap: 17,
  hopFlat: 12,
  portStub: 26,
  labelClearance: 5,
  labelHeadroom: 20,
  sheetW: 1200,
  sheetH: 780,
};

export function setLimits(data) {
  if (data) limits = { ...limits, ...data };
}

export function currentLimits() {
  return { ...limits };
}

function cellOf(doc, id) {
  return doc.cells.find((cell) => cell.id === id) || null;
}

// A net's loads, as a list, whatever shape it is in. Version 1 gave a net one
// load and put it in `to` directly; version 2 lets a net drive several.
export function loadsOf(net) {
  if (!net) return [];
  if (Array.isArray(net.to)) return net.to.filter((load) => load && typeof load === "object");
  if (net.to && typeof net.to === "object") return [net.to];
  return [];
}

export function endpointPosition(doc, endpoint) {
  if (!endpoint) return null;
  if (endpoint.cell !== undefined) {
    const cell = cellOf(doc, endpoint.cell);
    if (!cell) return null;
    const symbol = geometry.forCell(cell);
    if (!symbol) return null;
    return geometry.pinPosition(symbol, cell, endpoint.pin, symbolScale(doc));
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
  const symbol = geometry.forCell(cell);
  if (!symbol) return null;
  const pin = geometry.findPin(symbol, endpoint.pin);
  if (!pin) return null;

  const [sw, sh] = symbol.size;
  let local;
  if (pin.x <= EPSILON) local = [-1, 0];
  else if (pin.x >= sw - EPSILON) local = [1, 0];
  else if (pin.y <= EPSILON) local = [0, -1];
  else if (pin.y >= sh - EPSILON) local = [0, 1];
  else local = [1, 0];

  const matrix = geometry.matrixFor(symbol, cell, symbolScale(doc));
  const origin = matrix.apply(0, 0);
  const tip = matrix.apply(local[0], local[1]);
  const dx = tip[0] - origin[0];
  const dy = tip[1] - origin[1];
  if (Math.abs(dx) >= Math.abs(dy)) return [dx > 0 ? 1 : -1, 0];
  return [0, dy > 0 ? 1 : -1];
}

// Cell footprints a wire should avoid, with clearance. A labelled cell reaches
// higher than its body, because its instance name is drawn above it and a wire
// through a name is worse than a wire through a body: a body can still be read
// around the wire, a word cannot.
export function obstacleBoxes(doc, exclude = new Set()) {
  const scale = symbolScale(doc);
  const boxes = [];
  for (const cell of doc.cells) {
    if (exclude.has(cell.id)) continue;
    const symbol = geometry.forCell(cell);
    if (!symbol) continue;
    const matrix = geometry.matrixFor(symbol, cell, scale);
    const points = geometry.corners(0, 0, symbol.size[0], symbol.size[1])
      .map(([px, py]) => matrix.apply(px, py));
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    boxes.push([
      Math.min(...xs) - limits.wireToCell,
      Math.min(...ys) - (cell.label ? limits.labelHeadroom + limits.textToWire
                                    : limits.wireToCell),
      Math.max(...xs) + limits.wireToCell, Math.max(...ys) + limits.wireToCell,
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

// What a route needs to know about the rest of the drawing: the cell
// footprints to dodge, and the runs other wires have already taken, so a later
// wire picks a corridor of its own instead of landing on an earlier one.
// Nets that share an endpoint are exempt -- a fan-out from one pin is meant to
// lie on top of itself and show as a rail with junction dots.
export class Sheet {
  constructor(boxes = []) {
    this.boxes = boxes;
    this.runs = [];
    this.keys = new Set();
    this.net = null;
  }

  reserve(keys, points, netId = null) {
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = points[i];
      const b = points[i + 1];
      if (Math.abs(a[1] - b[1]) < EPSILON) {
        this.runs.push([netId, keys, true, a[1],
                        Math.min(a[0], b[0]), Math.max(a[0], b[0])]);
      } else if (Math.abs(a[0] - b[0]) < EPSILON) {
        this.runs.push([netId, keys, false, a[0],
                        Math.min(a[1], b[1]), Math.max(a[1], b[1])]);
      }
    }
  }

  forNet(boxes, keys, netId = null) {
    const view = new Sheet(boxes);
    view.runs = this.runs;
    view.keys = keys;
    view.net = netId;
    return view;
  }

  // Two faults of very different weight. Shadowing -- running alongside
  // another wire close enough that the pair reads as one line, meeting it end
  // to end included -- is always worth avoiding. Crossing one is only worth
  // avoiding if there is somewhere better to go, since in a busy drawing every
  // route crosses something; `crossings: false` asks the milder question.
  // `gap` lowers the bar further: the last pass asks only that the wire not be
  // drawn on top of another, which is a different question from being far
  // enough from it to read as separate.
  free(horizontal, fixed, v0, v1, crossings = true, gap = limits.wireGap) {
    const lo = Math.min(v0, v1);
    const hi = Math.max(v0, v1);
    return !this.runs.some(([netId, keys, runH, runFixed, runLo, runHi]) => {
      // A net never crowds itself, and neither does anything sharing a pin
      // with it: two wires off one pin are one signal, drawn as one rail.
      if (netId !== null && netId === this.net) return false;
      for (const key of keys) if (this.keys.has(key)) return false;
      if (runH === horizontal) {
        if (Math.abs(runFixed - fixed) >= gap) return false;
        return !(hi + EPSILON < runLo || lo - EPSILON > runHi);
      }
      return crossings && runLo + EPSILON < fixed && fixed < runHi - EPSILON
        && lo < runFixed && runFixed < hi;
    });
  }
}

function endpointKeys(net) {
  const keys = new Set();
  for (const endpoint of [net.from, ...loadsOf(net)]) {
    if (endpoint && endpoint.cell) keys.add(`${endpoint.cell}.${endpoint.pin}`);
  }
  return keys;
}

// Corridor tests to try in turn, from fussiest to bare. The middle passes
// matter more than they look: without them a wire that can find no
// crossing-free corridor falls straight back to its preferred one, and since
// every wire between the same two columns prefers the same corridor they would
// all pile onto it and be drawn on top of each other.
//
// The third pass is the one that matters in a drawing with no room left. It
// asks only that the wire not be drawn on top of another, which is a much
// weaker question than being far enough away to read as separate -- and the
// difference between the two is the difference between a drawing that is
// crowded and a drawing that claims a connection nobody made.
function corridorTests(pathIsClear, isFree) {
  if (!isFree) return [pathIsClear];
  const gap = limits.wireGap;
  return [
    (v) => pathIsClear(v) && isFree(v, true, gap),
    (v) => pathIsClear(v) && isFree(v, false, gap),
    (v) => pathIsClear(v) && isFree(v, false, limits.touching),
    pathIsClear,
  ];
}

// Checks all three legs, not just the corridor: a corridor that dodges a gate
// is no use if the leg leading into it still ploughs through one.
function pickCorridor(preferred, spanLo, spanHi, pathIsClear, isFree) {
  for (const test of corridorTests(pathIsClear, isFree)) {
    if (test(preferred)) return preferred;
    for (let step = 1; step <= limits.corridorTries; step += 1) {
      for (const candidate of [preferred + step * limits.corridorStep,
                               preferred - step * limits.corridorStep]) {
        if (candidate <= spanLo || candidate >= spanHi) continue;
        if (test(candidate)) return candidate;
      }
    }
  }
  return preferred;
}

// Both pins face the same way, so the wire has to come round to the far side
// of both before it can turn in: only one search direction makes sense.
function pickOutward(preferred, direction, pathIsClear, isFree) {
  for (const test of corridorTests(pathIsClear, isFree)) {
    for (let step = 0; step <= limits.corridorTries; step += 1) {
      const candidate = preferred + step * limits.corridorStep * direction;
      if (test(candidate)) return candidate;
    }
  }
  return preferred;
}

function legClear(p, q, boxes) {
  if (Math.abs(p[0] - q[0]) < EPSILON) return verticalClear(p[0], p[1], q[1], boxes);
  if (Math.abs(p[1] - q[1]) < EPSILON) return horizontalClear(p[1], p[0], q[0], boxes);
  return true;
}

// A free endpoint has no side of its own, so it faces the other end of the net.
function freeDirection(point, other) {
  const dx = other[0] - point[0];
  const dy = other[1] - point[1];
  if (Math.abs(dx) >= Math.abs(dy)) return [dx >= 0 ? 1 : -1, 0];
  return [0, dy >= 0 ? 1 : -1];
}

function stubEnd(point, direction, length = STUB) {
  return [point[0] + direction[0] * length, point[1] + direction[1] * length];
}

// How long a straight run this endpoint's pin is entitled to. A port gets more
// than an ordinary pin: it is the edge of the sheet, with no body between the
// connector and the first turn, so a wire that bends immediately reads as a
// line stuck to the port rather than as a signal leaving it.
export function stubFor(doc, endpoint) {
  if (!endpoint || endpoint.cell === undefined) return STUB;
  const cell = cellOf(doc, endpoint.cell);
  if (!cell) return STUB;
  const symbol = geometry.forCell(cell);
  if (!symbol || symbol.category !== PORT_CATEGORY) return STUB;
  return limits.portStub;
}

export function clean(points) {
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

// Detour around whatever blocks the straight line between two points.
function sidestep(a, b, sheet, vertical) {
  const { boxes } = sheet;
  if (vertical) {
    const x = pickCorridor(a[0], -Infinity, Infinity,
      (m) => verticalClear(m, a[1], b[1], boxes)
        && horizontalClear(a[1], a[0], m, boxes)
        && horizontalClear(b[1], m, b[0], boxes),
      (m, cross, gap) => sheet.free(false, m, a[1], b[1], cross, gap));
    return [a, [x, a[1]], [x, b[1]], b];
  }
  const y = pickCorridor(a[1], -Infinity, Infinity,
    (m) => horizontalClear(m, a[0], b[0], boxes)
      && verticalClear(a[0], a[1], m, boxes)
      && verticalClear(b[0], m, b[1], boxes),
    (m, cross, gap) => sheet.free(true, m, a[0], b[0], cross, gap));
  return [a, [a[0], y], [b[0], y], b];
}

// Both ends face sideways: cross over on a shared column.
function routeHH(a, b, aDir, bDir, sheet) {
  const { boxes } = sheet;
  const clearAt = (m) => verticalClear(m, a[1], b[1], boxes)
    && horizontalClear(a[1], a[0], m, boxes)
    && horizontalClear(b[1], m, b[0], boxes);
  // All three legs, to match clearAt. Testing only the corridor was the bug:
  // a column with nothing in it is no use if the leg leading into it lies
  // along another net's leg, and that overlap is what a wire-short is. The
  // legs are asked the weaker question whatever the ladder asks of the
  // corridor: close legs are a warning, legs on top of each other are an
  // error. Mirrors routing.py.
  const freeAt = (m, cross, gap) => sheet.free(false, m, a[1], b[1], cross, gap)
    && sheet.free(true, a[1], a[0], m, false, limits.touching)
    && sheet.free(true, b[1], m, b[0], false, limits.touching);

  const rowClear = (m) => horizontalClear(m, a[0], b[0], boxes)
    && verticalClear(a[0], a[1], m, boxes)
    && verticalClear(b[0], m, b[1], boxes);

  // Both pins face each other, so a column between them carries the crossover
  // -- unless a block sits on one of the two rows, which no choice of column
  // can dodge, because those rows are the pins' own. Then the wire has to
  // leave the rows entirely and cross on a row of its own.
  const facing = (b[0] - a[0]) * aDir[0] > EPSILON && (a[0] - b[0]) * bDir[0] > EPSILON;
  if (facing) {
    const lo = Math.min(a[0], b[0]);
    const hi = Math.max(a[0], b[0]);
    const x = pickCorridor((a[0] + b[0]) / 2, lo, hi, clearAt, freeAt);
    if (clearAt(x)) return [a, [x, a[1]], [x, b[1]], b];
    return rowCrossover(a, b, sheet, rowClear);
  }
  if (aDir[0] * bDir[0] > 0) {
    const direction = aDir[0];
    const base = direction > 0 ? Math.max(a[0], b[0]) : Math.min(a[0], b[0]);
    const x = pickOutward(base, direction, clearAt, freeAt);
    return [a, [x, a[1]], [x, b[1]], b];
  }
  // Back to back, so no column between them can be used either way.
  return rowCrossover(a, b, sheet, rowClear);
}

// Out of each pin and across on a shared row: the answer both when no column
// between the pins can be used and when every one of them is blocked, since
// leaving the pins' own rows is the only way past a block standing on one.
function rowCrossover(a, b, sheet, rowClear) {
  const y = pickCorridor((a[1] + b[1]) / 2, -Infinity, Infinity, rowClear,
    (m, cross, gap) => sheet.free(true, m, a[0], b[0], cross, gap));
  return [a, [a[0], y], [b[0], y], b];
}

// Both ends face up or down: cross over on a shared row.
function routeVV(a, b, aDir, bDir, sheet) {
  const { boxes } = sheet;
  const clearAt = (m) => horizontalClear(m, a[0], b[0], boxes)
    && verticalClear(a[0], a[1], m, boxes)
    && verticalClear(b[0], m, b[1], boxes);
  const freeAt = (m, cross, gap) => sheet.free(true, m, a[0], b[0], cross, gap);

  const facing = (b[1] - a[1]) * aDir[1] > EPSILON && (a[1] - b[1]) * bDir[1] > EPSILON;
  if (facing) {
    const lo = Math.min(a[1], b[1]);
    const hi = Math.max(a[1], b[1]);
    const y = pickCorridor((a[1] + b[1]) / 2, lo, hi, clearAt, freeAt);
    return [a, [a[0], y], [b[0], y], b];
  }
  if (aDir[1] * bDir[1] > 0) {
    const direction = aDir[1];
    const base = direction > 0 ? Math.max(a[1], b[1]) : Math.min(a[1], b[1]);
    const y = pickOutward(base, direction, clearAt, freeAt);
    return [a, [a[0], y], [b[0], y], b];
  }
  const x = pickCorridor((a[0] + b[0]) / 2, -Infinity, Infinity,
    (m) => verticalClear(m, a[1], b[1], boxes)
      && horizontalClear(a[1], a[0], m, boxes)
      && horizontalClear(b[1], m, b[0], boxes),
    (m, cross, gap) => sheet.free(false, m, a[1], b[1], cross, gap));
  return [a, [x, a[1]], [x, b[1]], b];
}

// One end faces sideways and the other up or down: a single corner.
function routeCorner(a, b, boxes, aHorizontal) {
  const alongA = aHorizontal ? [b[0], a[1]] : [a[0], b[1]];
  const alongB = aHorizontal ? [a[0], b[1]] : [b[0], a[1]];
  for (const corner of [alongA, alongB]) {
    if (legClear(a, corner, boxes) && legClear(corner, b, boxes)) return [a, corner, b];
  }
  return [a, alongA, b];
}

// Orthogonal path between two stub ends, dodging every cell on the way.
function middleRoute(a, b, aDir, bDir, sheet) {
  if (Math.abs(a[0] - b[0]) < EPSILON) {
    if (verticalClear(a[0], a[1], b[1], sheet.boxes)) return [a, b];
    return sidestep(a, b, sheet, true);
  }
  if (Math.abs(a[1] - b[1]) < EPSILON) {
    if (horizontalClear(a[1], a[0], b[0], sheet.boxes)) return [a, b];
    return sidestep(a, b, sheet, false);
  }
  const aHorizontal = Math.abs(aDir[0]) > Math.abs(aDir[1]);
  const bHorizontal = Math.abs(bDir[0]) > Math.abs(bDir[1]);
  if (aHorizontal && bHorizontal) return routeHH(a, b, aDir, bDir, sheet);
  if (!aHorizontal && !bHorizontal) return routeVV(a, b, aDir, bDir, sheet);
  return routeCorner(a, b, sheet.boxes, aHorizontal);
}

// The wire leaves each pin along the side that pin faces and only then is
// allowed to turn. That short stub is what makes the joint at, say, a
// flip-flop clock pin read as a continuation of the wire instead of a line
// that arrived from the wrong side.
function directRoute(start, end, startDir, endDir, sheet,
                     startStub = STUB, endStub = STUB) {
  const aDir = startDir || freeDirection(start, end);
  const bDir = endDir || freeDirection(end, start);
  const a = startDir ? stubEnd(start, aDir, startStub) : start;
  const b = endDir ? stubEnd(end, bDir, endStub) : end;
  return [start, ...middleRoute(a, b, aDir, bDir, sheet), end];
}

function elbow(a, b, horizontalFirst) {
  if (Math.abs(a[0] - b[0]) < EPSILON || Math.abs(a[1] - b[1]) < EPSILON) return [];
  return horizontalFirst ? [[b[0], a[1]]] : [[a[0], b[1]]];
}

// Pass the `sheet` from routeAll to let a wire see the ones routed before it;
// on its own a wire only dodges cells.
// The branches of one wire: a list of paths, one per load it drives. Branches
// are routed one at a time from the driving pin, which is why they lie on top
// of each other near it and part company where they have to -- the junction
// dots mark exactly where.
export function route(doc, net, sheet = null) {
  const start = endpointPosition(doc, net.from);
  if (!start) return [];

  const startDir = endpointDirection(doc, net.from);
  const board = sheet || new Sheet();
  const keys = endpointKeys(net);

  const branches = [];
  // Only a wire with somewhere to fork needs any of the tapping machinery, and
  // most wires have one load, so the terminals are worked out only if asked for.
  let terminals = null;
  const late = forksLate(doc);
  for (const load of loadsOf(net)) {
    let points = branchTo(doc, net, load, start, startDir, board, keys);
    const [tap, tapDir] = late
      ? tapPoint(branches, endpointPosition(doc, load)) : [null, null];
    if (tap) {
      if (terminals === null) terminals = foreignTerminals(doc, net);
      const shorter = branchTo(doc, net, load, tap, tapDir, board, keys, false);
      // Both ways are routed and the shorter clean one wins. Leaving late is
      // the point of the exercise, but it is worth doing only when it actually
      // saves wire: a tap that comes out no shorter has bought nothing and
      // still moved the wire, which shifts what every net routed after it has
      // to dodge.
      if (runLength(shorter) < runLength(points) - EPSILON
          && landsClear(shorter, doc, net, load, board, keys, terminals)) {
        points = shorter;
      }
    }
    if (points.length) branches.push(points);
  }
  return branches;
}

// Whether this drawing's wires share a trunk and divide near their loads.
// Off unless the drawing says so, so a file written before any of this existed
// is routed exactly as it always was. See routing.forks_late.
export function forksLate(doc) {
  return Boolean(doc && doc.canvas && doc.canvas.forkLate);
}

function runLength(points) {
  let total = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    total += Math.abs(points[i + 1][0] - points[i][0])
           + Math.abs(points[i + 1][1] - points[i][1]);
  }
  return total;
}

// Where a new branch should leave the wire already drawn, and going which way.
// See routing._tap: a wire is a tree, so the run is shared until it has to
// divide, and the last moment to leave is the point nearest the pin served.
function tapPoint(branches, end) {
  if (!branches.length || !end) return [null, null];
  let best = null;
  for (const points of branches) {
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = points[i];
      const b = points[i + 1];
      const spot = closestOnRun(end, a, b);
      const away = Math.abs(spot[0] - end[0]) + Math.abs(spot[1] - end[1]);
      if (!best || away < best.away - EPSILON) {
        best = { away, spot, run: [b[0] - a[0], b[1] - a[1]] };
      }
    }
  }
  if (!best) return [null, null];
  const length = Math.max(Math.abs(best.run[0]), Math.abs(best.run[1]));
  if (length < EPSILON) return [null, null];
  return [best.spot, [best.run[0] / length, best.run[1] / length]];
}

function closestOnRun(point, a, b) {
  return [
    Math.min(Math.max(point[0], Math.min(a[0], b[0])), Math.max(a[0], b[0])),
    Math.min(Math.max(point[1], Math.min(a[1], b[1])), Math.max(a[1], b[1])),
  ];
}

// Where every other wire in the drawing begins and ends. A wire laid across
// the pin another wire stops at is drawn with a junction dot on it, which says
// the two are connected when the file says they are not. See
// routing._foreign_terminals.
function foreignTerminals(doc, net) {
  const mine = endpointKeys(net);
  const spots = [];
  for (const other of doc.nets || []) {
    if (other === net || other.id === net.id) continue;
    const keys = endpointKeys(other);
    if ([...keys].some((key) => mine.has(key))) continue;
    for (const endpoint of [other.from, ...loadsOf(other)]) {
      const spot = endpointPosition(doc, endpoint);
      if (spot) spots.push(spot);
    }
  }
  return spots;
}

// Cell bodies as drawn, without the clearance a router keeps around them.
// See routing.body_boxes: the padded boxes are the right question when
// choosing a corridor and the wrong one when judging a finished route.
function bodyBoxes(doc, exclude = new Set()) {
  const scale = symbolScale(doc);
  const boxes = [];
  for (const cell of doc.cells) {
    if (exclude.has(cell.id)) continue;
    const symbol = geometry.forCell(cell);
    if (!symbol) continue;
    const matrix = geometry.matrixFor(symbol, cell, scale);
    const points = geometry.corners(0, 0, symbol.size[0], symbol.size[1])
      .map(([px, py]) => matrix.apply(px, py));
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    boxes.push([Math.min(...xs), Math.min(...ys),
                Math.max(...xs), Math.max(...ys)]);
  }
  return boxes;
}

function onRun(point, a, b) {
  if (Math.abs(a[1] - b[1]) < EPSILON) {
    return Math.abs(point[1] - a[1]) < EPSILON
      && Math.min(a[0], b[0]) - EPSILON <= point[0]
      && point[0] <= Math.max(a[0], b[0]) + EPSILON;
  }
  if (Math.abs(a[0] - b[0]) < EPSILON) {
    return Math.abs(point[0] - a[0]) < EPSILON
      && Math.min(a[1], b[1]) - EPSILON <= point[1]
      && point[1] <= Math.max(a[1], b[1]) + EPSILON;
  }
  return false;
}

// See routing._lands_clear.
function landsClear(points, doc, net, load, sheet, keys, terminals) {
  if (!points || points.length < 2) return false;
  const exclude = new Set();
  for (const endpoint of [net.from, load]) {
    if (endpoint && endpoint.cell !== undefined) exclude.add(endpoint.cell);
  }
  const view = sheet.forNet(obstacleBoxes(doc, exclude), keys, net.id);
  const bodies = bodyBoxes(doc, exclude);
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    if (!legClear(a, b, bodies)) return false;
    if (Math.abs(a[1] - b[1]) < EPSILON) {
      if (!view.free(true, a[1], a[0], b[0])) return false;
    } else if (Math.abs(a[0] - b[0]) < EPSILON) {
      if (!view.free(false, a[0], a[1], b[1])) return false;
    }
    for (const spot of terminals) {
      if (onRun(spot, a, b)) return false;
    }
  }
  return true;
}

// One path, from the driving pin -- or from a tap on the wire -- to a load.
// `fromPin` is false when the branch leaves the middle of a wire already
// drawn: there is no pin to stand off from there, so it gets no stub.
function branchTo(doc, net, load, start, startDir, sheet, keys, fromPin = true) {
  const end = endpointPosition(doc, load);
  if (!end) return [];

  const waypoints = (load.waypoints || []).map((p) => [p[0], p[1]]);

  if (!waypoints.length) {
    const exclude = new Set();
    for (const endpoint of [net.from, load]) {
      if (endpoint && endpoint.cell !== undefined) exclude.add(endpoint.cell);
    }
    const view = sheet.forNet(obstacleBoxes(doc, exclude), keys, net.id);
    return clean(directRoute(start, end, startDir,
                             endpointDirection(doc, load), view,
                             fromPin ? stubFor(doc, net.from) : 0,
                             stubFor(doc, load)));
  }

  const points = [start, ...waypoints, end];
  const chain = [points[0]];
  let horizontalFirst = startDir
    ? Math.abs(startDir[0]) > Math.abs(startDir[1]) : true;
  for (let i = 0; i < points.length - 1; i += 1) {
    const corner = elbow(points[i], points[i + 1], horizontalFirst);
    chain.push(...corner, points[i + 1]);
    if (corner.length) horizontalFirst = !horizontalFirst;
  }
  return clean(chain);
}

// Wires are routed one after another and each remembers where it ran, so a
// later wire picks a corridor of its own rather than landing on an earlier
// one. Order therefore matters: the first net stated gets the straightest run.
export function routeAll(doc) {
  const sheet = new Sheet();
  return (doc.nets || []).map((net) => {
    const branches = route(doc, net, sheet);
    const keys = endpointKeys(net);
    for (const points of branches) sheet.reserve(keys, points, net.id);
    return { net, branches };
  });
}

// Every straight run in a drawing, as [net id, a, b]. Branches of one net are
// separate paths, so anything looking at the drawing as a whole -- junction
// dots, crossing bridges -- comes through here.
export function segmentsOf(routes) {
  const found = [];
  for (const { net, branches } of routes) {
    for (const points of branches) {
      for (let i = 0; i < points.length - 1; i += 1) {
        found.push([net.id, points[i], points[i + 1]]);
      }
    }
  }
  return found;
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
// Where one wire crosses another without joining it, keyed by net id. A
// crossing and a connection must not look the same: junction dots mark the
// connections, these mark the crossings. By convention the horizontal wire
// hops, so a crossing pair never both bulge at the same spot.
export function hopPoints(routes) {
  const segments = [];
  const vertices = new Set();
  for (const [netId, a, b] of segmentsOf(routes)) {
    for (const p of [a, b]) vertices.add(`${p[0].toFixed(3)},${p[1].toFixed(3)}`);
    if (Math.abs(a[1] - b[1]) < EPSILON) segments.push([netId, a, b, "h"]);
    else if (Math.abs(a[0] - b[0]) < EPSILON) segments.push([netId, a, b, "v"]);
  }

  const found = new Map();
  for (const [id, a, b, orientation] of segments) {
    if (orientation !== "h") continue;
    const y = a[1];
    const low = Math.min(a[0], b[0]);
    const high = Math.max(a[0], b[0]);
    for (const [otherId, c, d, otherOrientation] of segments) {
      if (otherOrientation !== "v" || otherId === id) continue;
      const x = c[0];
      const vLow = Math.min(c[1], d[1]);
      const vHigh = Math.max(c[1], d[1]);
      if (!(low + EPSILON < x && x < high - EPSILON)) continue;
      if (!(vLow + EPSILON < y && y < vHigh - EPSILON)) continue;
      if (vertices.has(`${x.toFixed(3)},${y.toFixed(3)}`)) continue;
      if (!found.has(id)) found.set(id, []);
      // Two wires of the same rail can cross this one at the same spot; one
      // bridge is enough, and drawing it twice only thickens the arc.
      const spots = found.get(id);
      if (spots.some((s) => Math.abs(s[0] - x) < EPSILON
                         && Math.abs(s[1] - y) < EPSILON)) continue;
      spots.push([x, y]);
    }
  }
  return found;
}

export function junctions(routes) {
  const segments = segmentsOf(routes).map(([, a, b]) => [a, b]);

  const candidates = new Map();
  for (const [, a, b] of segmentsOf(routes)) {
    for (const point of [a, b]) {
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
