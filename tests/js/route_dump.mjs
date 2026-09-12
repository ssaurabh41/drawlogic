// Print every net's route for one drawing, using the browser router.
//
// Run by tests/test_js_parity.py, which compares the output against the same
// drawing routed by drawlogic/routing.py. The two routers are separate
// implementations of the same algorithm; nothing else in the suite would
// notice them drifting apart.
//
// SYMBOLS.json is the whole resolved library, blocks for referenced drawings
// included -- dumped by the Python side rather than read from
// drawlogic/symbols.json, or a hierarchical drawing would route to nothing
// here while routing properly there, and the comparison would pass on two
// empty answers.
//
// Usage: node tests/js/route_dump.mjs SYMBOLS.json DRAWING.dlg THEME.json

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as render from "../../drawlogic/web/js/render.js";
import * as routing from "../../drawlogic/web/js/routing.js";

const [symbolsPath, drawingPath] = process.argv.slice(2);
geometry.setLibrary(JSON.parse(readFileSync(symbolsPath, "utf8")));
const doc = JSON.parse(readFileSync(drawingPath, "utf8"));

const routes = routing.routeAll(doc);
const hops = routing.hopPoints(routes);
const canvas = doc.canvas || {};
const fontScale = Number((canvas.font || {}).scale) || 1;

// Rendering decisions, not just routing ones: where each name ends up and
// where each direction arrow goes. Both are worked out twice, once per
// language, and both are easy to let drift.
const theme = JSON.parse(readFileSync(process.argv[4], "utf8"));
render.setTheme(theme);
const labels = render.labelSpots(routes, render.cellBoxes(doc),
                                 [canvas.width, canvas.height], fontScale);

process.stdout.write(JSON.stringify({
  routes: routes.map(({ net, branches }) => [net.id, branches]),
  junctions: routing.junctions(routes),
  hops: [...hops.entries()],
  labels: [...labels.entries()],
  arrows: routes.map(({ net, branches }) => [
    net.id,
    branches.filter((points) => points.length >= 2)
      .map((points) => render.arrowSpots(points, theme.arrowSize || 7)),
  ]),
}));
