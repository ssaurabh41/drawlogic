// Assertions for the parts of the editor that exist only in JavaScript:
// drag-time alignment and the Tidy command.
//
// Run by tests/test_js_editor.py. Prints one line per check and exits non-zero
// on the first failure, so the Python side can just report the output.
//
// Usage: node tests/js/editor_check.mjs SYMBOLS.json

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as guides from "../../drawlogic/web/js/guides.js";
import * as model from "../../drawlogic/web/js/model.js";
import * as routing from "../../drawlogic/web/js/routing.js";

geometry.setLibrary(JSON.parse(readFileSync(process.argv[2], "utf8")));

let failures = 0;

function check(what, condition, detail = "") {
  if (condition) {
    console.log(`ok   ${what}`);
  } else {
    failures += 1;
    console.log(`FAIL ${what}${detail ? ` -- ${detail}` : ""}`);
  }
}

// A gate driving a flip-flop, with the flop one unit out of line: the wire
// between them bends for the sake of a single unit.
function sketch(flopY) {
  return {
    canvas: { width: 700, height: 400, symbolScale: 1 },
    cells: [
      { id: "u1", type: "and2", x: 200, y: 80, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "ff1", type: "dff", x: 380, y: flopY, w: 70, h: 60, rotate: 0, mirror: false },
      { id: "pq", type: "port_out", x: 590, y: 165, w: 20, h: 10, rotate: 0, mirror: false },
    ],
    nets: [
      { id: "n1", from: { cell: "u1", pin: "y" }, to: { cell: "ff1", pin: "d" },
        waypoints: [] },
      { id: "n2", from: { cell: "ff1", pin: "q" }, to: { cell: "pq", pin: "p" },
        waypoints: [] },
    ],
    shapes: [], groups: [],
  };
}

// u1.y sits at (260, 100); ff1.d sits at (380, flopY + 15).

// ---- drag-time alignment ----

{
  const fix = guides.suggest(sketch(87), ["ff1"], 8);
  check("a near miss is pulled into line", fix.dy === -2, `dy=${fix.dy}`);
  check("and says why, with a guide along the wire",
        fix.guides.length === 1 && fix.guides[0].axis === "y"
        && fix.guides[0].at === 100,
        JSON.stringify(fix.guides));
}

{
  // A guide may still be reported here: ff1 and the port already share a
  // centre line, and saying so is the point of a guide. What must not happen
  // is the cell moving.
  const fix = guides.suggest(sketch(140), ["ff1"], 8);
  check("a miss beyond tolerance does not move anything",
        fix.dx === 0 && fix.dy === 0, JSON.stringify(fix));
}

{
  // Both ends moving together: their wire cannot be straightened by moving
  // them, and nothing should twitch.
  const fix = guides.suggest(sketch(87), ["u1", "ff1", "pq"], 8);
  check("a net wholly inside the drag offers nothing",
        fix.dy === 0, JSON.stringify(fix));
}

{
  // ff1's top edge is 3 from u1's top edge, and its d pin is 12 out of line.
  // The box match is the smaller move, but the pin match is the one that
  // makes a wire straight, so it has to win.
  const doc = sketch(83);
  const fix = guides.suggest(doc, ["ff1"], 20);
  check("lining up a pin beats lining up an edge", fix.dy === 2, `dy=${fix.dy}`);
}

// ---- the Tidy command ----

{
  const doc = sketch(137);
  const straightened = model.tidy(doc, new Set(["u1", "ff1", "pq"]));
  const ff1 = doc.cells.find((c) => c.id === "ff1");
  const pq = doc.cells.find((c) => c.id === "pq");
  check("tidy straightens a chain end to end", straightened === 2,
        `straightened=${straightened}`);
  check("the flop lands on the gate's row", ff1.y === 85, `y=${ff1.y}`);
  check("and the port lands on the flop's", pq.y === ff1.y + 15 - 5, `y=${pq.y}`);
  check("tidy never moves anything sideways",
        ff1.x === 380 && pq.x === 590, `${ff1.x} ${pq.x}`);
}

{
  const doc = sketch(137);
  const before = doc.cells.find((c) => c.id === "u1").y;
  model.tidy(doc, new Set(["ff1"]));
  check("an unselected cell anchors rather than moves",
        doc.cells.find((c) => c.id === "u1").y === before);
  check("and the selected one comes to it",
        doc.cells.find((c) => c.id === "ff1").y === 85);
}

{
  const doc = sketch(85);
  const straightened = model.tidy(doc, new Set(["u1", "ff1"]));
  check("a drawing that is already square is left alone", straightened === 0,
        `straightened=${straightened}`);
}

{
  // The locked-axis rule exists so tidying cannot trade one alignment for
  // another. If it could, a second Tidy would keep shuffling the drawing.
  const doc = sketch(137);
  model.tidy(doc, new Set(["u1", "ff1", "pq"]));
  const once = JSON.stringify(doc.cells);
  const again = model.tidy(doc, new Set(["u1", "ff1", "pq"]));
  check("tidying twice changes nothing the second time",
        again === 0 && JSON.stringify(doc.cells) === once, `straightened=${again}`);
}

{
  const doc = sketch(137);
  doc.nets = [];
  const straightened = model.tidy(doc, new Set(["u1", "ff1"]));
  check("cells with no wires between them are left alone", straightened === 0);
}

// ---- nets with more than one load ----

function wired() {
  const doc = {
    canvas: { width: 900, height: 400, symbolScale: 1 },
    cells: [
      { id: "u1", type: "and2", x: 100, y: 100, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "a", type: "inv", x: 300, y: 60, w: 50, h: 40, rotate: 0, mirror: false },
      { id: "b", type: "inv", x: 300, y: 160, w: 50, h: 40, rotate: 0, mirror: false },
    ],
    nets: [], shapes: [], groups: [],
  };
  return doc;
}

{
  const doc = wired();
  const first = model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "a", pin: "a" });
  check("wiring a pin to a pin makes a net", doc.nets.length === 1 && !!first);
  check("with one load", routing.loadsOf(doc.nets[0]).length === 1);

  const second = model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "b", pin: "a" });
  check("wiring the same pin somewhere else extends that net",
        doc.nets.length === 1 && second === doc.nets[0],
        `nets=${doc.nets.length}`);
  check("which now has two loads", routing.loadsOf(doc.nets[0]).length === 2);

  const again = model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "b", pin: "a" });
  check("and wiring the same pair twice does nothing", again === null
        && routing.loadsOf(doc.nets[0]).length === 2);
}

{
  const doc = wired();
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "a", pin: "a" });
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "b", pin: "a" });

  model.deleteItems(doc, new Set(["b"]));
  check("deleting one load leaves the net with the others",
        doc.nets.length === 1 && routing.loadsOf(doc.nets[0]).length === 1,
        `nets=${doc.nets.length}`);

  model.deleteItems(doc, new Set(["a"]));
  check("deleting the last load takes the net with it", doc.nets.length === 0);
}

{
  const doc = wired();
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "a", pin: "a" });
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "b", pin: "a" });
  // Branches go different ways, so a bend belongs to one of them.
  model.setWaypoints(doc, doc.nets[0].id, [[200, 200]], 1);
  const loads = routing.loadsOf(doc.nets[0]);
  check("a bend belongs to the branch it was made on",
        loads[0].waypoints.length === 0 && loads[1].waypoints.length === 1,
        JSON.stringify(loads.map((l) => l.waypoints)));
}

{
  const doc = wired();
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "a", pin: "a" });
  model.addNet(doc, { cell: "u1", pin: "y" }, { cell: "b", pin: "a" });
  const branches = routing.route(doc, doc.nets[0]);
  check("one net routes to one path per load", branches.length === 2,
        `branches=${branches.length}`);
  check("and both start at the driving pin",
        branches[0][0][0] === branches[1][0][0]
        && branches[0][0][1] === branches[1][0][1]);
}

// ---- dragging a wire by one of its runs ----

function twoCorners() {
  // A gate driving a flop that sits lower: the wire leaves, drops, arrives.
  const doc = {
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 10 } },
    cells: [
      { id: "u1", type: "and2", x: 100, y: 100, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "ff", type: "dff", x: 400, y: 260, w: 70, h: 60, rotate: 0, mirror: false },
    ],
    nets: [{ id: "n1", name: null, width: 1,
             from: { cell: "u1", pin: "y" },
             to: [{ cell: "ff", pin: "d", waypoints: [] }], style: {} }],
    shapes: [], groups: [],
  };
  return doc;
}

{
  const doc = twoCorners();
  const [before] = routing.route(doc, doc.nets[0]);
  check("the wire starts with a corner in it", before.length > 2,
        JSON.stringify(before));

  // Grab the vertical run in the middle and slide it left.
  const middle = before[Math.floor(before.length / 2)];
  const run = model.grabRun(doc, "n1", [middle[0], middle[1]]);
  check("grabbing finds a run", !!run && !run.horizontal, JSON.stringify(run && run.horizontal));

  model.slideRun(doc, "n1", run, 200);
  const [after] = routing.route(doc, doc.nets[0]);
  const verticals = after.filter((p, i) =>
    i < after.length - 1 && Math.abs(p[0] - after[i + 1][0]) < 1e-6);
  check("sliding it puts the run where it was put",
        verticals.some((p) => Math.abs(p[0] - 200) < 1e-6),
        JSON.stringify(after));
  check("and the wire still starts and ends on its pins",
        after[0][0] === before[0][0] && after[0][1] === before[0][1]
        && after[after.length - 1][0] === before[before.length - 1][0],
        JSON.stringify([before[0], after[0]]));
}

{
  // Every corner becomes a waypoint, so the wire stays put rather than being
  // re-derived into something else on the next redraw.
  const doc = twoCorners();
  const run = model.grabRun(doc, "n1", [330, 200]);
  model.slideRun(doc, "n1", run, 250);
  const once = JSON.stringify(routing.route(doc, doc.nets[0]));
  const twice = JSON.stringify(routing.route(doc, doc.nets[0]));
  check("a dragged wire is stable across redraws", once === twice);
  check("and is held by waypoints",
        routing.loadsOf(doc.nets[0])[0].waypoints.length > 0);
}

{
  // A straight wire has a pin at each end, so there is nothing to absorb a
  // drag until a corner is inserted for it.
  const doc = twoCorners();
  // and2's y pin sits 20 down its box, dff's d pin 15 down its own.
  doc.cells[1].y = 105;
  const [straight] = routing.route(doc, doc.nets[0]);
  check("the wire is straight to begin with", straight.length === 2,
        JSON.stringify(straight));

  const run = model.grabRun(doc, "n1", [300, straight[0][1]]);
  model.slideRun(doc, "n1", run, straight[0][1] + 80);
  const [bent] = routing.route(doc, doc.nets[0]);
  check("dragging a straight wire bends it", bent.length > 2, JSON.stringify(bent));
  check("without moving either pin",
        bent[0][1] === straight[0][1]
        && bent[bent.length - 1][1] === straight[1][1],
        JSON.stringify(bent));
}

{
  const doc = twoCorners();
  const run = model.grabRun(doc, "n1", [330, 200]);
  model.slideRun(doc, "n1", run, 250);
  model.straighten(doc, "n1", 0);
  check("straightening hands the wire back to the router",
        routing.loadsOf(doc.nets[0])[0].waypoints.length === 0);
  check("and it routes itself again",
        JSON.stringify(routing.route(doc, doc.nets[0]))
        === JSON.stringify(routing.route(twoCorners(), twoCorners().nets[0])));
}

{
  // Each branch of a rail is dragged on its own.
  const doc = twoCorners();
  doc.cells.push({ id: "ff2", type: "dff", x: 400, y: 380, w: 70, h: 60,
                   rotate: 0, mirror: false });
  doc.nets[0].to.push({ cell: "ff2", pin: "d", waypoints: [] });
  const branches = routing.route(doc, doc.nets[0]);
  const low = branches[1][Math.floor(branches[1].length / 2)];
  const run = model.grabRun(doc, "n1", [low[0], low[1]]);
  check("grabbing picks the branch it was nearest to", run.branch === 1,
        `branch=${run.branch}`);
  model.slideRun(doc, "n1", run, 220);
  const loads = routing.loadsOf(doc.nets[0]);
  check("and only that branch is bent by hand",
        loads[0].waypoints.length === 0 && loads[1].waypoints.length > 0,
        JSON.stringify(loads.map((l) => l.waypoints.length)));
}

if (failures) {
  console.log(`${failures} check(s) failed`);
  process.exit(1);
}
