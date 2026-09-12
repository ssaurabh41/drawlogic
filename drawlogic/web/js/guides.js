// Snapping a drag so the result looks deliberate.
//
// Dropping cells on a grid gets you close; it does not get you a straight
// wire. A wire runs straight only when the two pins it joins share a row (or a
// column), and being one grid step out is enough to put a kink in it. So while
// you drag, this looks for a nudge -- smaller than half a grid step's worth of
// slop -- that would line something up, and reports the line to draw so you
// can see why the cell just moved.
//
// Two kinds of alignment, in order of preference:
//
//   1. A pin on a moving cell with the pin it is wired to. This is the one
//      that matters: it is what turns an elbow into a straight line.
//   2. An edge or centre of a moving cell with one that is staying put.
//
// Usage:
//
//   import * as guides from "./guides.js";
//
//   const fix = guides.suggest(doc, movingIds, 7 / zoom);
//   // fix.dx, fix.dy: the nudge to apply, 0 when nothing lines up
//   // fix.guides: [{ axis: "x"|"y", at, from, to }] lines to draw
//
// `straighten` is the same question asked about one wire with no tolerance at
// all, which is what the Tidy command is built from.

import * as geometry from "./geometry.js";
import * as routing from "./routing.js";

// A pin alignment is worth more than an edge alignment, so it wins even when
// the edge one needs a smaller nudge.
const PIN_RANK = 0;
const BOX_RANK = 1;

export function suggest(doc, movingIds, tolerance) {
  const moving = new Set(movingIds);
  const best = { x: null, y: null };

  const offer = (axis, delta, rank, guide) => {
    if (!Number.isFinite(delta) || Math.abs(delta) > tolerance) return;
    const current = best[axis];
    if (current && (current.rank < rank
                    || (current.rank === rank
                        && Math.abs(current.delta) <= Math.abs(delta)))) return;
    best[axis] = { delta, rank, guide };
  };

  pinAlignments(doc, moving, offer);
  boxAlignments(doc, moving, offer);

  const result = { dx: 0, dy: 0, guides: [] };
  if (best.x) { result.dx = best.x.delta; result.guides.push(best.x.guide); }
  if (best.y) { result.dy = best.y.delta; result.guides.push(best.y.guide); }
  return result;
}

// What it would take to make one wire run straight: which way to move the
// mover, and by how much. Null when the two pins face different ways, since
// then an elbow is correct and there is nothing to line up.
export function straighten(doc, mover, anchor) {
  const moverAt = routing.endpointPosition(doc, mover);
  const anchorAt = routing.endpointPosition(doc, anchor);
  if (!moverAt || !anchorAt) return null;

  const moverDir = routing.endpointDirection(doc, mover);
  const anchorDir = routing.endpointDirection(doc, anchor);
  if (!moverDir || !anchorDir) return null;

  const moverH = Math.abs(moverDir[0]) > Math.abs(moverDir[1]);
  const anchorH = Math.abs(anchorDir[0]) > Math.abs(anchorDir[1]);
  if (moverH !== anchorH) return null;

  const i = moverH ? 1 : 0;
  const other = moverH ? 0 : 1;
  return {
    axis: moverH ? "y" : "x",
    delta: anchorAt[i] - moverAt[i],
    guide: {
      axis: moverH ? "y" : "x",
      at: anchorAt[i],
      from: Math.min(moverAt[other], anchorAt[other]),
      to: Math.max(moverAt[other], anchorAt[other]),
    },
  };
}

function pinAlignments(doc, moving, offer) {
  for (const net of doc.nets || []) {
    // Each branch of a net is its own wire, and each can be straightened.
    for (const load of routing.loadsOf(net)) {
      const ends = endsToAlign(net.from, load, moving);
      if (!ends) continue;
      const fix = straighten(doc, ends[0], ends[1]);
      if (fix) offer(fix.axis, fix.delta, PIN_RANK, fix.guide);
    }
  }
}

// The moving end and the staying end of one branch, or null when both ends
// move together or neither does -- either way there is nothing to line up.
export function endsToAlign(from, to, moving) {
  if (!from || !to || from.cell === undefined || to.cell === undefined) return null;
  const fromMoves = moving.has(from.cell);
  const toMoves = moving.has(to.cell);
  if (fromMoves === toMoves) return null;
  return fromMoves ? [from, to] : [to, from];
}

function boxAlignments(doc, moving, offer) {
  const scale = routing.symbolScale(doc);
  const movers = [];
  const anchors = [];
  for (const cell of doc.cells || []) {
    const symbol = geometry.forCell(cell);
    if (!symbol) continue;
    const box = geometry.cellBounds(symbol, cell, scale);
    (moving.has(cell.id) ? movers : anchors).push(box);
  }
  if (!movers.length || !anchors.length) return;

  for (const mover of movers) {
    for (const anchor of anchors) {
      for (const [axis, i, size] of [["x", 0, 2], ["y", 1, 3]]) {
        const other = axis === "x" ? 1 : 0;
        const otherSize = axis === "x" ? 3 : 2;
        const span = {
          from: Math.min(mover[other], anchor[other]),
          to: Math.max(mover[other] + mover[otherSize],
                       anchor[other] + anchor[otherSize]),
        };
        const edges = [
          [anchor[i], mover[i]],
          [anchor[i] + anchor[size] / 2, mover[i] + mover[size] / 2],
          [anchor[i] + anchor[size], mover[i] + mover[size]],
        ];
        for (const [at, mine] of edges) {
          offer(axis, at - mine, BOX_RANK, { axis, at, ...span });
        }
      }
    }
  }
}
