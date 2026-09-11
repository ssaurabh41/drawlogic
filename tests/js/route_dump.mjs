// Print every net's route for one drawing, using the browser router.
//
// Run by tests/test_js_parity.py, which compares the output against the same
// drawing routed by drawlogic/routing.py. The two routers are separate
// implementations of the same algorithm; nothing else in the suite would
// notice them drifting apart.
//
// Usage: node tests/js/route_dump.mjs SYMBOLS.json DRAWING.dlg

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as routing from "../../drawlogic/web/js/routing.js";

const [symbolsPath, drawingPath] = process.argv.slice(2);
geometry.setLibrary(JSON.parse(readFileSync(symbolsPath, "utf8")));
const doc = JSON.parse(readFileSync(drawingPath, "utf8"));

const routes = routing.routeAll(doc);
const hops = routing.hopPoints(routes);
process.stdout.write(JSON.stringify({
  routes: routes.map(({ net, points }) => [net.id, points]),
  junctions: routing.junctions(routes),
  hops: [...hops.entries()],
}));
