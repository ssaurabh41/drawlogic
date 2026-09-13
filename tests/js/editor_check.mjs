// Assertions for the parts of the editor that exist only in JavaScript:
// drag-time alignment and the Tidy command.
//
// Run by tests/test_js_editor.py. Prints one line per check and exits non-zero
// on the first failure, so the Python side can just report the output.
//
// The last line is a completion record -- "DONE ran/N" -- counted by this
// script itself rather than written down in two places. The Python wrapper
// used to accept any zero-exit run containing a single "ok" line, so gutting
// this file down to one console.log left the whole suite green with every
// editor assertion gone. A count the script reports about itself cannot go
// stale the way a number hardcoded in the wrapper would.
//
// Usage: node tests/js/editor_check.mjs SYMBOLS.json

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as guides from "../../drawlogic/web/js/guides.js";
import * as model from "../../drawlogic/web/js/model.js";
import * as routing from "../../drawlogic/web/js/routing.js";

geometry.setLibrary(JSON.parse(readFileSync(process.argv[2], "utf8")));

let failures = 0;
let ran = 0;

function check(what, condition, detail = "") {
  ran += 1;
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

// ---- undo through a gesture ----
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
}

// ---- duplicating a group ----
//
// Copy, paste and Ctrl+D all go through copyItems/pasteItems, which carried
// cells, shapes and nets but never groups -- so duplicating a grouped block
// gave back a pile of loose parts that had to be grouped again by hand.
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

  // Still the same drawing, edited while the layout was computed: the layout
  // is applied as an edit of its own, so it is allowed.
  store.load({ title: "C" }, "c.dlg");
  const onC = store.stamp();
  store.mutate("nudged a gate", (doc) => { doc.title = "C, nudged"; });
  check("a layout answer still applies to the drawing that asked for it",
        store.matches(onC, { edits: false }) === true);
  check("but a save from before that edit does not mark it clean",
        store.markSaved(onC) === false);
}

if (failures) {
  console.log(`${failures} check(s) failed`);
  console.log(`DONE ${ran}/${ran}`);
  process.exit(1);
}

// Reaching here means every check above ran to the end. An early exit, a
// throw, or a file cut down to nothing never prints this.
console.log(`DONE ${ran}/${ran}`);
