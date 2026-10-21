// Assertions for the parts of the editor that exist only in JavaScript:
// drag-time alignment and the Tidy command.
//
// Run by tests/test_js_editor.py. Prints one line per check and exits non-zero
// on the first failure, so the Python side can just report the output.
//
// What has to be covered is written down in EXPECTED below, area by area,
// and the run fails if any area is missing or has a different number of
// checks than it says.
//
// Two earlier attempts at this guard were not enough. The first accepted any
// zero-exit run containing one "ok" line, so cutting this file down to a
// single console.log kept the suite green. The second printed "DONE ran/N"
// with the script's own count on both sides of the slash -- which cannot
// disagree with itself, so deleting a whole section just printed a smaller
// number and still passed. A count taken from the checks that ran can never
// notice the ones that did not.
//
// So the expected figures come from somewhere the checks cannot move: this
// table, and a list of area names in tests/test_js_editor.py. Deleting a
// section fails here; deleting the section and its row fails in Python.
//
// Usage: node tests/js/editor_check.mjs SYMBOLS.json

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as guides from "../../drawlogic/web/js/guides.js";
import * as model from "../../drawlogic/web/js/model.js";
import * as routing from "../../drawlogic/web/js/routing.js";
import { Selection } from "../../drawlogic/web/js/selection.js";
import { SelectTool, constrainShape } from "../../drawlogic/web/js/tools.js";

geometry.setLibrary(JSON.parse(readFileSync(process.argv[2], "utf8")));

// Area -> how many checks it must run. Written down on purpose: this is the
// half of the comparison that does not come from running the checks.
const EXPECTED = [
  ["drag-time alignment", 8],
  ["the Tidy command", 9],
  ["nets with more than one load", 10],
  ["dragging a wire by one of its runs", 13],
  ["the step a wire is dragged on", 4],
  ["auto-connect on drop", 5],
  ["placing onto a pin", 6],
  ["placing onto a wire end", 3],
  ["undo through a gesture", 8],
  ["duplicating a group", 8],
  ["stale answers", 8],
  ["drawing a shape with Shift", 7],
  ["carrying a placed cell to a pin", 5],
  ["stacking and writing on shapes", 8],
  ["containers", 27],
  ["headings and named styles", 14],
  ["linked components", 9],
];
const TOTAL = EXPECTED.reduce((sum, [, n]) => sum + n, 0);

let failures = 0;
let ran = 0;
let area = null;
const counted = new Map();

function section(name) {
  area = name;
  counted.set(name, 0);
}

function check(what, condition, detail = "") {
  ran += 1;
  if (area === null) {
    failures += 1;
    console.log(`FAIL ${what} -- check outside any section`);
    return;
  }
  counted.set(area, counted.get(area) + 1);
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
section("drag-time alignment");

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

{
  // A gate dragged near a port used to snap its edge to the port's, which is
  // a 20x10 connector at the edge of the sheet: lining a gate up with one
  // means nothing to a reader and only got in the way of placing the gate.
  // Here nothing is wired to the port, so only a box match could fire.
  const doc = {
    canvas: { width: 700, height: 400, symbolScale: 1 },
    cells: [
      { id: "u1", type: "and2", x: 200, y: 203, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "p1", type: "port_in", x: 40, y: 200, w: 20, h: 10, rotate: 0, mirror: false },
    ],
    nets: [],
  };
  const fix = guides.suggest(doc, ["u1"], 20);
  check("a gate does not snap to an unrelated port",
        fix.dy === 0, `dy=${fix.dy}`);
}

{
  // Two ports still line up with each other: a column of ports down the edge
  // of a sheet is exactly the thing that should be flush.
  const doc = {
    canvas: { width: 700, height: 400, symbolScale: 1 },
    cells: [
      { id: "p1", type: "port_in", x: 40, y: 200, w: 20, h: 10, rotate: 0, mirror: false },
      { id: "p2", type: "port_in", x: 43, y: 260, w: 20, h: 10, rotate: 0, mirror: false },
    ],
    nets: [],
  };
  const fix = guides.suggest(doc, ["p2"], 20);
  check("two ports still line up with each other",
        fix.dx === -3, `dx=${fix.dx}`);
}

{
  // And a wire between a cell and a port is still straightened, because that
  // one is about the wire rather than about the boxes.
  const doc = {
    canvas: { width: 700, height: 400, symbolScale: 1 },
    cells: [
      { id: "u1", type: "and2", x: 200, y: 203, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "p1", type: "port_in", x: 40, y: 200, w: 20, h: 10, rotate: 0, mirror: false },
    ],
    nets: [{ id: "n1", from: { cell: "p1", pin: "p" },
             to: [{ cell: "u1", pin: "a" }] }],
  };
  const fix = guides.suggest(doc, ["u1"], 20);
  check("a wire to a port is still straightened",
        fix.dy !== 0, `dy=${fix.dy}`);
}

// ---- the Tidy command ----
section("the Tidy command");

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
section("nets with more than one load");

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

// ---- the step a wire is dragged on ----
//
// Not the step a cell is dropped on. A cell lands on the drawing's grid and a
// pin sits at a fixed offset inside its symbol, so a port dropped on a 10
// grid puts its connector at a multiple of 10 plus 5. A wire dragged on 10
// can never meet it: it stops five short every time, and that near-miss is
// drawn as a kink.
section("the step a wire is dragged on");

{
  const doc = {
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 10 } },
    cells: [], nets: [], shapes: [], groups: [],
  };
  check("a wire drags on a finer step than a cell",
        model.wireStep(doc) === 5 && model.gridStep(doc) === 10,
        `wire ${model.wireStep(doc)}, cell ${model.gridStep(doc)}`);

  const port = { id: "p", type: "port_in", x: 100, y: 60, w: 20, h: 10,
                 rotate: 0, mirror: false };
  doc.cells.push(port);
  const symbol = geometry.forCell(port);
  const spot = geometry.pinPosition(symbol, port, "p", 1);
  check("a port on the grid puts its pin off the cell step",
        spot[1] % model.gridStep(doc) !== 0, `pin at ${spot[1]}`);
  check("but on the wire step, so a drag can reach it",
        spot[1] % model.wireStep(doc) === 0, `pin at ${spot[1]}`);

  // A drawing asking for something finer keeps it: the rule is a ceiling.
  doc.canvas.grid.size = 2;
  check("a finer grid than the pins is honoured as it stands",
        model.wireStep(doc) === 2, `wire ${model.wireStep(doc)}`);
}

// ---- auto-connect on drop ----
//
// A cell dropped so one of its free pins lands on another's is joined to it,
// Logisim style -- but only free pins, only across the drop, and only within
// a grid half-step, or a drop near something would wire it on its own.
section("auto-connect on drop");

{
  const inv = (id, x, y) => ({ id, type: "inv", x, y, w: 40, h: 30,
                               rotate: 0, mirror: false });
  const pin = (cell, name) =>
    geometry.pinPosition(geometry.forCell(cell), cell, name, 1);
  const doc = {
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 10 } },
    cells: [inv("a", 100, 100), inv("b", 300, 100)], nets: [], shapes: [], groups: [],
  };
  // Put b's input exactly on a's output.
  const [out, into] = [pin(doc.cells[0], "y"), pin(doc.cells[1], "a")];
  doc.cells[1].x += out[0] - into[0];
  doc.cells[1].y += out[1] - into[1];
  const joined = model.autoConnect(doc, ["b"]);
  const net = doc.nets[0];
  check("a pin dropped on a free pin is joined to it", joined.length === 1
        && net && net.from.cell === "a" && net.to[0].cell === "b",
        JSON.stringify(doc.nets));
  check("the driver ends up as the net's source", net && net.from.pin === "y",
        net && JSON.stringify(net.from));
  check("dropping it there again joins nothing more",
        model.autoConnect(doc, ["b"]).length === 0 && doc.nets.length === 1);

  const far = { ...doc, nets: [], cells: [inv("a", 100, 100), inv("b", 300, 100)] };
  far.cells[1].x += out[0] - into[0] + 10;
  far.cells[1].y += out[1] - into[1];
  check("a pin landing a grid step away is left alone",
        model.autoConnect(far, ["b"]).length === 0, JSON.stringify(far.nets));

  const both = { ...doc, nets: [], cells: [inv("a", 100, 100), inv("b", 300, 100)] };
  both.cells[1].x += out[0] - into[0];
  both.cells[1].y += out[1] - into[1];
  check("two cells dropped together are not joined to each other",
        model.autoConnect(both, ["a", "b"]).length === 0, JSON.stringify(both.nets));
}

// ---- placing onto a pin ----
section("placing onto a pin");
//
// Dropped from the palette near a free pin, a cell lands in line with it, a
// short wire away, and is wired to it -- one gesture, where auto-connect on
// its own needed a second drag to line the pins up.
{
  const inv = (id, x, y) => ({ id, type: "inv", x, y, w: 40, h: 30,
                               rotate: 0, mirror: false });
  const pin = (cell, name) =>
    geometry.pinPosition(geometry.forCell(cell), cell, name, 1);
  const fresh = () => ({
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 10 } },
    cells: [inv("a", 100, 100)], nets: [], shapes: [], groups: [],
  });

  // Let go a little off to the right of a's output, and a little low.
  let doc = fresh();
  const out = pin(doc.cells[0], "y");
  const placed = model.placeCell(doc, "inv", [out[0] + 45, out[1] + 8]);
  const into = pin(placed.cell, "a");
  check("a cell let go near a free output lands in line with it",
        Math.abs(into[1] - out[1]) < 1e-9, `${into} vs ${out}`);
  check("a short wire away rather than pin on pin",
        Math.abs(into[0] - out[0] - model.SNAP_LEAD) < 1e-9, `${into} vs ${out}`);
  check("and is wired to it, driver first", doc.nets.length === 1
        && doc.nets[0].from.cell === "a" && doc.nets[0].from.pin === "y"
        && doc.nets[0].to[0].cell === placed.cell.id, JSON.stringify(doc.nets));

  // Near a free input: the new cell's output is the one that lines up.
  doc = fresh();
  const input = pin(doc.cells[0], "a");
  const before = model.placeCell(doc, "inv", [input[0] - 45, input[1] - 6]);
  check("near an input it lands on the left and drives it", doc.nets.length === 1
        && doc.nets[0].from.cell === before.cell.id
        && Math.abs(pin(before.cell, "y")[0] - (input[0] - model.SNAP_LEAD)) < 1e-9,
        JSON.stringify(doc.nets));

  doc = fresh();
  model.placeCell(doc, "inv", [out[0] + 200, out[1] + 150]);
  check("let go far from any pin, nothing is joined", doc.nets.length === 0,
        JSON.stringify(doc.nets));

  doc = fresh();
  model.placeCell(doc, "inv", [out[0] + 45, out[1] + 8], false);
  check("with auto-connect off it is only placed", doc.nets.length === 0
        && doc.cells.length === 2, JSON.stringify(doc.nets));
}

// ---- placing onto a wire end ----
section("placing onto a wire end");
//
// A wire that stops on nothing is a free pin too. Dropped near it, the cell
// lands on the end and the wire is joined to it -- the same one gesture, with
// the snap doing the aiming rather than auto-connect's six units.
{
  const gate = (id, x, y) => ({ id, type: "inv", x, y, w: 40, h: 30,
                                rotate: 0, mirror: false });
  const pin = (cell, name) =>
    geometry.pinPosition(geometry.forCell(cell), cell, name, 1);
  const end = { x: 200, y: 115, waypoints: [] };
  const fresh = () => ({
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 10 } },
    cells: [gate("a", 100, 100)],
    // A fresh loose end each time: joining one rewrites it in place.
    nets: [{ id: "n1", from: { cell: "a", pin: "y" },
             to: [{ x: end.x, y: end.y, waypoints: [] }] }],
    shapes: [], groups: [],
  });

  let doc = fresh();
  const placed = model.placeCell(doc, "inv", [end.x + 45, end.y + 8]);
  check("a cell let go near a loose wire end lands on it", doc.nets.length === 1
        && doc.nets[0].to.length === 1 && doc.nets[0].to[0].cell === placed.cell.id
        && doc.nets[0].to[0].pin === "a", JSON.stringify(doc.nets));
  const driver = doc.nets[0].from;
  const joinedAt = pin(placed.cell, "a");
  check("the wire keeps its driver and reaches the new pin",
        driver.cell === "a" && driver.pin === "y"
        && Math.abs(joinedAt[0] - end.x) < 1e-9
        && Math.abs(joinedAt[1] - end.y) < 1e-9,
        `${JSON.stringify(driver)} ${joinedAt}`);

  doc = fresh();
  model.placeCell(doc, "inv", [end.x + 45, end.y + 8], false);
  check("with auto-connect off the wire end is left alone",
        doc.nets.length === 1 && doc.nets[0].to[0].x === end.x
        && doc.nets[0].to[0].y === end.y, JSON.stringify(doc.nets));
}

// ---- dragging a wire by one of its runs ----
section("dragging a wire by one of its runs");

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

// ---- undo through a gesture ----
section("undo through a gesture");
//
// mutate() only keeps the first snapshot of a gesture, so it only takes one.
// These pin the behaviour that optimisation must not change.
{
  const store = new model.Store();
  store.load({ title: "start", n: 0 }, "a.dlg");

  store.beginGesture("drag");
  for (let i = 1; i <= 5; i += 1) store.mutate("drag", (d) => { d.n = i; });
  store.endGesture();
  check("a drag of five moves undoes as one step",
        store._undo.length === 1, `${store._undo.length}`);
  check("back to the state before the drag began",
        store._undo[0].doc.n === 0, `${store._undo[0].doc.n}`);

  const before = store._undo.length;
  store.mutate("refused", () => false);
  check("a refused mutation records nothing",
        store._undo.length === before);

  store.mutate("one", (d) => { d.n = 10; });
  store.mutate("two", (d) => { d.n = 20; });
  check("two edits outside a gesture record two steps",
        store._undo.length === before + 2);
  check("each holding what was there before it",
        store._undo[store._undo.length - 1].doc.n === 10,
        `${store._undo[store._undo.length - 1].doc.n}`);

  // Made and named as one gesture -- a container drawn, then titled -- is
  // one undo step; made and abandoned -- a text box left empty -- leaves
  // nothing at all behind, not even a dirty mark.
  const made = new model.Store();
  made.load({ cells: [], nets: [], shapes: [], groups: [] }, "b.dlg");
  made.beginGesture("container");
  made.mutate("container", (d) => { d.containers = [{ id: "k1", title: "Container 1" }]; });
  made.mutate("rename", (d) => { d.containers[0].title = "GPC 0"; });
  made.endGesture();
  check("drawing and naming a container undo as one step",
        made._undo.length === 1 && made.undo() && !(made.doc.containers || []).length);
  const empty = new model.Store();
  empty.load({ cells: [], nets: [], shapes: [], groups: [] }, "c.dlg");
  empty.beginGesture("text");
  empty.mutate("text", (d) => { d.shapes.push({ id: "s1", kind: "text", text: "" }); });
  empty.cancelGesture();
  check("a text box made and left empty leaves nothing to undo",
        empty._undo.length === 0 && empty.doc.shapes.length === 0, `${empty._undo.length}`);
  check("and does not mark the drawing unsaved", empty.dirty === false);
}

// ---- duplicating a group ----
section("duplicating a group");
//
// Copy, paste and Ctrl+D all go through copyItems/pasteItems, which carried
// cells, shapes and nets but never groups -- so duplicating a grouped block
// gave back a pile of loose parts that had to be grouped again by hand.
//
// And a group moved carries the bends of the wires among its members; a
// wire leaving the group is left to the router.
{
  const moved = sketch(0);
  moved.nets[0].to = [{ cell: "ff1", pin: "d", waypoints: [[320, 100]] }];
  moved.nets[1].to = [{ cell: "pq", pin: "p", waypoints: [[520, 170]] }];
  model.moveItems(moved, new Set(["u1", "ff1"]), 10, 20);
  check("a group moved takes the bends of the wires among it",
        moved.nets[0].to[0].waypoints[0][0] === 330 && moved.nets[0].to[0].waypoints[0][1] === 120);
  check("but not of a wire leaving it", moved.nets[1].to[0].waypoints[0][0] === 520);
}
{
  const doc = sketch(0);
  doc.shapes = [{ id: "s1", kind: "rect", x: 0, y: 0, w: 40, h: 40 }];
  const ids = new Set([doc.cells[0].id, doc.cells[1].id, "s1"]);
  model.groupItems(doc, ids);

  const clip = model.copyItems(doc, ids);
  check("a whole group travels with the things it groups",
        (clip.groups || []).length === 1,
        JSON.stringify((clip.groups || []).length));

  const before = doc.groups.length;
  const added = model.pasteItems(doc, clip, 200, 200);
  check("pasting it makes a second group",
        doc.groups.length === before + 1);

  const fresh = doc.groups[doc.groups.length - 1];
  check("whose members are the copies, not the originals",
        fresh.members.every((m) => added.includes(m)),
        JSON.stringify(fresh.members));
  check("and which groups as many things as the original did",
        fresh.members.length === ids.size,
        `${fresh.members.length} vs ${ids.size}`);
  check("including the shape, not only the cells",
        fresh.members.some((m) => m.startsWith("s")),
        JSON.stringify(fresh.members));

  // Half a group is not a group: pasting one would name members that were
  // never copied.
  const half = new Set([doc.cells[0].id]);
  check("copying part of a group carries no group at all",
        (model.copyItems(doc, half).groups || []).length === 0);
}

// ---- stale answers ----
section("stale answers");
//
// Saving and laying out are round trips. Whatever the user does while one is
// in flight, the answer must not be applied to a document it was not about.
{
  const store = new model.Store();
  store.load({ title: "A" }, "a.dlg");

  const sending = store.stamp();
  store.mutate("typed something", (doc) => { doc.title = "A, edited"; });
  check("an edit during a save leaves the file marked unsaved",
        store.markSaved(sending) === false && store.dirty === true,
        `dirty=${store.dirty}`);

  const clean = store.stamp();
  check("and a save with nothing typed since does mark it saved",
        store.markSaved(clean) === true && store.dirty === false,
        `dirty=${store.dirty}`);

  // The layout case: ask on one drawing, switch to another, answer arrives.
  const asked = store.stamp();
  store.load({ title: "B" }, "b.dlg");
  check("a layout answer is not applied after switching drawings",
        store.matches(asked, { edits: false }) === false);
  check("and the drawing now open is left alone",
        store.doc.title === "B" && store.path === "b.dlg",
        `${store.path}: ${store.doc.title}`);

  // Re-opening the same file while a layout for it is in flight. The path is
  // unchanged, so the path alone cannot tell these apart -- what is open is a
  // different document object now, holding whatever is on disk, and the
  // answer in flight is about the copy that was replaced.
  store.load({ title: "A again" }, "a.dlg");
  const beforeReopen = store.stamp();
  store.load({ title: "A reloaded from disk" }, "a.dlg");
  check("a layout answer is not applied after reopening the same drawing",
        store.matches(beforeReopen, { edits: false }) === false);

  // Still the same drawing, edited while the layout was computed. This used
  // to be allowed, on the reasoning that the layout was just another edit --
  // but a layout answer replaces the whole document, so whatever was done in
  // the meantime went with it. main.js now requires both: the same drawing,
  // and the same version of it.
  store.load({ title: "C" }, "c.dlg");
  const onC = store.stamp();
  store.mutate("nudged a gate", (doc) => { doc.title = "C, nudged"; });
  check("a layout answer is still about the drawing that asked for it",
        store.matches(onC, { edits: false }) === true);
  check("but an edit since means the answer no longer describes it",
        store.matches(onC) === false);
  check("and a save from before that edit does not mark it clean",
        store.markSaved(onC) === false);
}

// ---- drawing a shape with Shift ----
//
// As in a slide editor: a box or ellipse comes out square whichever way it is
// dragged, and a line goes straight across, straight down or at 45 degrees.
section("drawing a shape with Shift");
{
  const same = (a, b) => a[0] === b[0] && a[1] === b[1];
  check("a box dragged wide comes out square",
        same(constrainShape("rect", [0, 0], [30, 10]), [30, 30]));
  check("dragged up and left it is square that way",
        same(constrainShape("rect", [0, 0], [-10, -40]), [-40, -40]));
  check("an ellipse comes out a circle",
        same(constrainShape("ellipse", [10, 10], [15, 50]), [50, 50]));
  check("a line drawn nearly flat runs straight across",
        same(constrainShape("line", [0, 0], [100, 20]), [100, 0]));
  check("a line drawn nearly upright runs straight down",
        same(constrainShape("line", [0, 0], [15, -100]), [0, -100]));
  check("a line drawn near the diagonal runs at 45 degrees",
        same(constrainShape("line", [0, 0], [60, -50]), [60, -60]));
  check("a polygon edge is held the same way from its last point",
        same(constrainShape("polygon", [20, 20], [25, 90]), [20, 90]));
}

// ---- carrying a placed cell to a pin ----
//
// Reported: dropping from the palette rings the pin a cell will join, but
// carrying a cell already on the sheet to a pin showed nothing, and joined
// only if the two pins were laid almost exactly on each other. The move asks
// the same question the drop does.
section("carrying a placed cell to a pin");
{
  const inv = (id, x, y) => ({ id, type: "inv", x, y, w: 40, h: 30,
                               rotate: 0, mirror: false });
  const pin = (cell, name) =>
    geometry.pinPosition(geometry.forCell(cell), cell, name, 1);
  const doc = {
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 5 } },
    cells: [inv("a", 100, 100), inv("b", 300, 300)], nets: [], shapes: [], groups: [],
  };
  const out = pin(doc.cells[0], "y");
  // Carry b so its input sits a little short of a's output and a little low.
  const b = doc.cells[1];
  const into = pin(b, "a");
  b.x += out[0] + model.SNAP_LEAD - 4 - into[0];
  b.y += out[1] + 6 - into[1];
  const snapped = model.snapCell(doc, b);
  check("a placed cell carried near a free pin finds it",
        snapped && snapped.target.cell === "a" && snapped.target.pin === "y",
        JSON.stringify(snapped));
  check("and would land in line with it, a lead away", snapped
        && Math.abs(snapped.wire[0][1] - out[1]) < 1e-9
        && Math.abs(snapped.wire[0][0] - out[0] - model.SNAP_LEAD) < 1e-9,
        JSON.stringify(snapped && snapped.wire));
  check("the ring goes on the pin it will join", snapped
        && snapped.wire[1][0] === out[0] && snapped.wire[1][1] === out[1]);
  check("it is never offered one of its own pins", snapped
        && snapped.target.cell !== "b");
  // Once b.a is wired, it has somewhere to go and no longer snaps.
  doc.nets.push({ id: "n1", from: { cell: "x", pin: "y" },
                  to: [{ cell: "b", pin: "a", waypoints: [] }] });
  check("a pin already wired does not snap",
        model.snapCell(doc, b) === null, JSON.stringify(model.snapCell(doc, b)));
}

// ---- stacking and writing on shapes ----
//
// Asked for: shapes behind symbols unless brought forward, front and back
// working across shapes and symbols alike, and writing and copies on a shape
// as on a cell.
section("stacking and writing on shapes");
{
  const doc = {
    canvas: { width: 600, height: 400, symbolScale: 1, grid: { size: 5 } },
    cells: [{ id: "u", type: "inv", x: 100, y: 100, w: 40, h: 30, rotate: 0, mirror: false }],
    nets: [], shapes: [], groups: [],
  };
  const box = model.addShape(doc, "rect", { x: 60, y: 60, w: 160, h: 100 });
  const line = model.addShape(doc, "line", { x: 0, y: 0, w: 0, h: 0,
                                             points: [[0, 300], [200, 300]] });
  check("a new shape has no fill and no place in the stack",
        !("fill" in box.style) && box.z === undefined);
  model.bringToFront(doc, new Set([box.id]));
  check("brought to front, a shape is above every symbol",
        box.z > Math.max(...doc.cells.map((c) => c.z || 0)));
  model.bringToFront(doc, new Set(["u"]));
  check("and a symbol brought to front goes back above it", doc.cells[0].z > box.z);
  model.sendToBack(doc, new Set(["u"]));
  check("sent to back, a symbol is below every shape",
        doc.cells[0].z < Math.min(...doc.shapes.map((s) => s.z || 0)));
  model.setCellText(doc, box.id, "one\ntwo\n");
  check("a shape takes lines of writing", JSON.stringify(box.text) === '["one","two"]',
        JSON.stringify(box.text));
  check("and is not grown to fit them, as a cell would be", box.w === 160 && box.h === 100);
  model.setCopies(doc, box.id, "3");
  model.setTextAlign(doc, box.id, "textAlign", "left");
  check("copies and alignment, as a cell", box.copies === 3 && box.textAlign === "left");
  model.setCopies(doc, line.id, "4");
  check("a line says what it was told but stands for no copies",
        geometry.shapeCopies(line) === 0 && geometry.shapeCopies(box) === 3);
}

section("containers");
//
// A container owns what names it as parentId, at any depth. Moving it moves
// all of that once, with the bends of the wires running among it; resizing
// it moves none of it; and nothing about a drag changes what owns what.
{
  const nested = () => ({
    canvas: { width: 1200, height: 800, symbolScale: 1, grid: { size: 5 } },
    cells: [
      { id: "a", parentId: "tpc", type: "and2", x: 140, y: 160, w: 60, h: 40, rotate: 0, mirror: false },
      { id: "b", parentId: "tpc", type: "inv", x: 260, y: 160, w: 40, h: 30, rotate: 0, mirror: false },
      { id: "c", parentId: "gpc", type: "inv", x: 420, y: 300, w: 40, h: 30, rotate: 0, mirror: false },
      { id: "out", type: "inv", x: 800, y: 300, w: 40, h: 30, rotate: 0, mirror: false },
    ],
    nets: [
      { id: "inner", from: { cell: "a", pin: "y" },
        to: [{ cell: "b", pin: "a", waypoints: [[230, 180]] }] },
      { id: "across", from: { cell: "c", pin: "y" },
        to: [{ cell: "out", pin: "a", waypoints: [[600, 315]] }] },
    ],
    shapes: [{ id: "note", parentId: "gpc", kind: "text", x: 120, y: 380, text: "SMs", style: {} }],
    groups: [],
    containers: [
      { id: "gpc", title: "GPC 0", x: 100, y: 80, w: 420, h: 340, padding: 20, headerHeight: 32, style: {} },
      { id: "tpc", parentId: "gpc", title: "TPC 0", x: 120, y: 120, w: 220, h: 100, padding: 20, headerHeight: 32, style: {} },
    ],
  });

  // The real select tool, pressed on the outer container's header and
  // dragged, with the inner container selected too: everything inside moves
  // once, not once per container round it.
  const store = new model.Store();
  store.load(nested(), "c.dlg");
  const selection = new Selection(store);
  const tool = new SelectTool({ store, selection, zoom: () => 1, drawOverlay() {},
                                say() {}, setTool() {} });
  selection.set(["gpc", "tpc"]);
  const on = (id) => ({ closest: (what) => (what.includes(".dl-container")
    ? { getAttribute: () => id } : null) });
  tool.onPointerDown({ target: on("gpc"), ctrlKey: false, metaKey: false }, [110, 90]);
  tool.onPointerMove({ shiftKey: false, altKey: true }, [160, 130]);
  tool.onPointerUp({ ctrlKey: false, metaKey: false });
  const doc = store.doc;
  const at = (id) => model.itemById(doc, id);
  check("dragging a container moves it", at("gpc").x === 150 && at("gpc").y === 120,
        JSON.stringify([at("gpc").x, at("gpc").y]));
  check("and what it holds two levels down, by the same amount, once",
        at("a").x === 190 && at("a").y === 200 && at("tpc").x === 170,
        JSON.stringify([at("a").x, at("a").y, at("tpc").x]));
  check("a shape it holds moves too", at("note").x === 170 && at("note").y === 420);
  check("something outside it stays", at("out").x === 800 && at("out").y === 300);
  const inner = doc.nets.find((n) => n.id === "inner").to[0].waypoints[0];
  const across = doc.nets.find((n) => n.id === "across").to[0].waypoints[0];
  check("a wire wholly inside keeps its shape, bends and all",
        inner[0] === 280 && inner[1] === 220, JSON.stringify(inner));
  check("a wire leaving it is left to the router", across[0] === 600 && across[1] === 315,
        JSON.stringify(across));
  check("no drag changed what owns what",
        at("a").parentId === "tpc" && at("tpc").parentId === "gpc" && at("out").parentId === undefined);
  check("the whole drag undoes as one step", store._undo.length === 1, `${store._undo.length}`);
  store.undo();
  check("which puts everything back where it was",
        model.itemById(store.doc, "gpc").x === 100 && model.itemById(store.doc, "a").x === 140
        && store.doc.nets[0].to[0].waypoints[0][0] === 230);

  // Moving by command goes through moveItems, which must not move a cell
  // twice when both it and its container are asked to move.
  const twice = nested();
  model.moveItems(twice, new Set(["gpc", "tpc", "a"]), 10, 0);
  check("moveItems moves each thing once however many of its containers move",
        model.itemById(twice, "a").x === 150, `${model.itemById(twice, "a").x}`);

  // Fit and resize.
  const sized = nested();
  model.fitContainer(sized, "tpc");
  const tpc = model.containerById(sized, "tpc");
  check("fitting hugs the contents with padding round them and the header above",
        tpc.x === 120 && tpc.y === 108 && tpc.w === 200 && tpc.h === 112,
        JSON.stringify([tpc.x, tpc.y, tpc.w, tpc.h]));
  const before = JSON.stringify(sized.cells);
  tpc.w = 50;
  tpc.h = 20;
  model.keepContentsInside(sized, tpc);
  check("a container cannot be made smaller than what it holds",
        tpc.w === 200 && tpc.h === 112, JSON.stringify([tpc.w, tpc.h]));
  check("and resizing it moves nothing inside", JSON.stringify(sized.cells) === before);

  // The commands.
  const loose = nested();
  check("a container cannot be moved into itself or into something it holds",
        model.moveIntoContainer(loose, new Set(["gpc"]), "tpc") === false
        && model.itemById(loose, "gpc").parentId === undefined);
  check("anything else can", model.moveIntoContainer(loose, new Set(["out"]), "tpc") === 1
        && model.itemById(loose, "out").parentId === "tpc");
  model.removeFromContainer(loose, new Set(["out"]));
  check("removing takes it out one level", model.itemById(loose, "out").parentId === "gpc");
  check("the picker knows where a selection already is",
        model.sharedContainer(loose, new Set(["out", "c"])) === "gpc"
        && model.sharedContainer(loose, new Set(["out", "a"])) === undefined);
  check("moving to the sheet takes it out of every container, and counts only what moved",
        model.moveIntoContainer(loose, new Set(["out", "c"]), null) === 2
        && model.itemById(loose, "out").parentId === undefined
        && model.moveIntoContainer(loose, new Set(["out"]), null) === false);
  const made = model.containerFromSelection(loose, new Set(["a", "b"]), "Pair");
  check("a container made from a selection holds it, inside what held it",
        model.itemById(loose, "a").parentId === made.id && made.parentId === "tpc",
        JSON.stringify([model.itemById(loose, "a").parentId, made.parentId]));

  const ungrouped = nested();
  model.ungroupContainers(ungrouped, new Set(["tpc"]));
  check("ungrouping a container keeps what it held, given to the one round it",
        model.itemById(ungrouped, "a").parentId === "gpc" && !model.containerById(ungrouped, "tpc"));
  const gone = nested();
  model.deleteItems(gone, model.withContents(gone, ["gpc"]));
  check("deleting with contents takes every level, and the wires on them",
        gone.cells.map((c) => c.id).join() === "out" && !gone.containers
        && gone.nets.length === 0, JSON.stringify(gone.cells.map((c) => c.id)));

  // Copies of a container are a copy of everything in it, pointed at each other.
  const copied = nested();
  const added = model.pasteItems(copied, model.copyItems(copied, new Set(["tpc"])), 0, 300);
  const copyBox = copied.containers.find((b) => added.includes(b.id) && b.title === "TPC 0");
  const copyA = copied.cells.find((c) => added.includes(c.id) && c.type === "and2");
  check("a pasted container comes with copies of what it held, inside it",
        copyBox && copyA && copyA.parentId === copyBox.id);
  check("and sits where the original did, in the same outer container",
        copyBox.parentId === "gpc");
  check("the wire between the copies comes along", copied.nets.length === 3);

  // Groups and containers are kept apart; a cell placed inside a container
  // belongs to it, which is the only time where a thing sits decides that.
  const grouped = nested();
  const group = model.groupItems(grouped, new Set(["gpc", "a", "b"]));
  check("a group never takes a container in", group && !group.members.includes("gpc"));
  const placed = model.placeCell(grouped, "inv", [180, 270], false).cell;
  check("a cell placed inside a container belongs to the innermost round it",
        placed.parentId === "gpc", `${placed.parentId}`);
  check("and one placed on bare sheet to none",
        model.placeCell(grouped, "inv", [900, 600], false).cell.parentId === undefined);
}

section("headings and named styles");
//
// A heading and text styles on a block, and named styles: saving one from a
// block moves the block's own settings into it, editing it reaches every
// block using it, and a block's own override survives that.
{
  const doc = {
    canvas: { width: 900, height: 500, symbolScale: 1, grid: { size: 5 }, font: { scale: 1 } },
    cells: [0, 1, 2].map((i) => ({ id: `sm${i}`, type: "block", x: 60 + 220 * i, y: 100,
                                   w: 140, h: 90, rotate: 0, mirror: false, style: {},
                                   text: ["Warp scheduler"] })),
    nets: [], shapes: [], groups: [],
  };
  const before = doc.cells[0].h;
  model.setHeading(doc, "sm0", "  SM 0  ");
  model.setTextStyle(doc, ["sm0"], "headingStyle", "fontSize", "70");
  check("a heading is kept trimmed, and the block grows to hold it",
        doc.cells[0].heading === "SM 0" && doc.cells[0].h > before, `${doc.cells[0].h}`);
  check("a nonsense size is refused",
        model.setTextStyle(doc, ["sm0"], "textStyle", "fontSize", "big") === false);
  model.setStyle(doc, new Set(["sm0"]), "fill", "#d8edb4");
  model.setTextStyle(doc, ["sm0"], "textStyle", "fill", "#52656f");
  const key = model.saveNamedStyle(doc, "compute", "sm0", new Set(["sm0", "sm1"]));
  check("saving a style names it and points the selection at it",
        key === "compute" && doc.cells[0].styleRef === "compute" && doc.cells[1].styleRef === "compute"
        && doc.cells[2].styleRef === undefined);
  check("and moves the block's own settings into it",
        doc.styles.compute.style.fill === "#d8edb4" && doc.styles.compute.headingStyle.fontSize === 70
        && doc.cells[0].style.fill === undefined && doc.cells[0].headingStyle === undefined);
  check("so the second block now looks like the first",
        geometry.effectiveStyle(doc.styles, doc.cells[1]).style.fill === "#d8edb4");
  model.setStyle(doc, new Set(["sm1"]), "fill", "#ffe0b2");
  model.updateNamedStyle(doc, "compute", { style: { fill: "#000001", stroke: "#123456" },
                                           headingStyle: { fontSize: 70 }, textStyle: {} });
  const look0 = geometry.effectiveStyle(doc.styles, doc.cells[0]);
  const look1 = geometry.effectiveStyle(doc.styles, doc.cells[1]);
  check("editing the style reaches every block using it",
        look0.style.fill === "#000001" && look1.style.stroke === "#123456");
  check("but not what a block set itself", look1.style.fill === "#ffe0b2");
  check("a part left empty is dropped from the style", !("textStyle" in doc.styles.compute));
  model.setStyleRef(doc, new Set(["sm0"]), null);
  check("taking the style off leaves the block's own settings only",
        doc.cells[0].styleRef === undefined
        && geometry.effectiveStyle(doc.styles, doc.cells[0]) === doc.cells[0]);
  doc.cells[2].style = { fill: "#abcdef", strokeWidth: 3 };
  model.setStyleRef(doc, new Set(["sm2"]), "compute");
  check("choosing a style lets go of the block's own settings of what the style sets, only",
        doc.cells[2].style.fill === undefined && doc.cells[2].style.strokeWidth === 3
        && geometry.effectiveStyle(doc.styles, doc.cells[2]).style.fill === "#000001");
  // Rename and delete.
  doc.styles.other = { style: { fill: "#eeeeee" } };
  check("a style cannot be renamed onto another's name",
        model.renameNamedStyle(doc, "compute", "other") === false && doc.styles.compute);
  model.renameNamedStyle(doc, "compute", "sm");
  check("renaming a style takes everything naming it along",
        !doc.styles.compute && doc.styles.sm && doc.cells[1].styleRef === "sm"
        && doc.cells.every((c) => c.styleRef !== "compute"));
  const looked = JSON.stringify(geometry.effectiveStyle(doc.styles, doc.cells[1]).style);
  model.deleteNamedStyle(doc, "sm");
  check("deleting a style leaves everything that used it looking as it did",
        !doc.styles.sm && doc.cells[1].styleRef === undefined
        && JSON.stringify(doc.cells[1].style) === looked, JSON.stringify(doc.cells[1].style));
  doc.styles.compute = doc.styles.compute || { style: { fill: "#000001" } };
  check("and a style that is not there cannot be named",
        model.setStyleRef(doc, new Set(["sm1"]), "nope") === false && doc.cells[1].styleRef === undefined);
}

section("linked components");
//
// Repeat makes linked copies with ids of their own and names in sequence; a
// pin a definition no longer has is reported, not swapped; refs are written
// relative to the drawing using them.
{
  geometry.setSheets({ "sheet:components/sm.dlg": {
    name: "SM", category: "sheets", size: [150, 70],
    pins: [{ name: "in", x: 0, y: 35, dir: "in", width: 0 },
           { name: "out", x: 150, y: 35, dir: "out", width: 0 }],
    draw: [{ op: "rect", x: 10, y: 0, w: 130, h: 70, role: "body" }] } });
  const doc = {
    canvas: { width: 1600, height: 900, symbolScale: 1, grid: { size: 5 } },
    cells: [{ id: "u1", parentId: "tpc", type: "sheet", ref: "components/sm.dlg", label: "SM 0",
              x: 100, y: 100, w: 150, h: 70, rotate: 0, mirror: false, style: {} },
            { id: "drv", type: "inv", x: 0, y: 300, w: 40, h: 30, rotate: 0, mirror: false }],
    nets: [{ id: "n1", from: { cell: "drv", pin: "y" }, to: [{ cell: "u1", pin: "in" }] }],
    shapes: [], groups: [],
    containers: [{ id: "tpc", title: "TPC", x: 60, y: 40, w: 300, h: 200, padding: 20,
                   headerHeight: 32, style: {} }],
  };
  const added = model.repeatItems(doc, "u1", { rows: 2, columns: 4, gapX: 20, gapY: 30,
                                               prefix: "SM ", start: 0 });
  const all = doc.cells.filter((c) => c.ref === "components/sm.dlg");
  check("repeat makes rows x columns instances in all", added.length === 7 && all.length === 8,
        `${added.length} ${all.length}`);
  check("every one with an id of its own", new Set(all.map((c) => c.id)).size === 8);
  check("named in sequence from the start index",
        JSON.stringify(all.map((c) => c.label)) === JSON.stringify(
          ["SM 0", "SM 1", "SM 2", "SM 3", "SM 4", "SM 5", "SM 6", "SM 7"]),
        JSON.stringify(all.map((c) => c.label)));
  check("all linked to the one definition, in the same container",
        all.every((c) => c.ref === "components/sm.dlg" && c.parentId === "tpc"));
  const last = all[all.length - 1];
  check("laid out on the grid asked for", last.x === 100 + 3 * 170 && last.y === 100 + 100,
        `${last.x},${last.y}`);
  check("a repeat of nonsense does nothing",
        model.repeatItems(doc, "u1", { rows: 0, columns: 2 }) === null);
  check("a pin still there is not reported", model.interfaceProblems(doc).length === 0);
  doc.nets[0].to[0].pin = "gone";
  const lost = model.interfaceProblems(doc);
  check("a wire naming a pin the definition lost is reported and left as it is",
        lost.length === 1 && lost[0].pin === "gone" && doc.nets[0].to[0].pin === "gone");
  check("refs are relative to the drawing using them",
        model.relativeRef("lanes/top.dlg", "lanes/components/sm.dlg") === "components/sm.dlg"
        && model.relativeRef("lanes/top.dlg", "other/x.dlg") === "../other/x.dlg"
        && model.relativeRef("top.dlg", "components/sm.dlg") === "components/sm.dlg");
  geometry.setSheets({});
}

// Every area has to have run, and to have run the number of checks it says.
// This is where deleting a section is caught: its row is still here, and its
// count comes back zero.
for (const [name, expected] of EXPECTED) {
  const actual = counted.has(name) ? counted.get(name) : 0;
  console.log(`area ${name} ${actual}/${expected}`);
  if (actual !== expected) {
    failures += 1;
    console.log(`FAIL area "${name}" ran ${actual} checks, expected ${expected}`
                + " -- add its row to EXPECTED if this was deliberate");
  }
}
for (const name of counted.keys()) {
  if (!EXPECTED.some(([known]) => known === name)) {
    failures += 1;
    console.log(`FAIL area "${name}" is not listed in EXPECTED`);
  }
}

if (failures) {
  console.log(`${failures} check(s) failed`);
  console.log(`DONE ${ran}/${TOTAL}`);
  process.exit(1);
}

// Reaching here means every check above ran to the end. An early exit, a
// throw, or a file cut down to nothing never prints this. The denominator is
// the table's total, not the tally -- so the two sides can disagree.
console.log(`DONE ${ran}/${TOTAL}`);
