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

if (failures) {
  console.log(`${failures} check(s) failed`);
  process.exit(1);
}
