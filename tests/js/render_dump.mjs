// Render a drawing with the browser renderer and print the primitives it
// actually produced, for tests/test_js_parity.py to compare against the SVG
// render_svg.py produces from the same drawing.
//
// Why this exists, rather than calling the helpers directly as route_dump.mjs
// does: the arrow comparison used to ask both renderers' `arrowSpots` the
// same question, with an exclusion set the test built itself. It left the
// crossing bridges out. Both helpers agreed, all six parity tests passed, and
// the editor drew an arrow on top of a bridge that the exported file did not
// have -- because neither renderer's real drawing code was ever called. Two
// helpers matching says nothing about the two renderers matching.
//
// So this walks the same path the editor walks: render.render(), into a DOM
// small enough to build here. Node has no DOM, and adding one as a dependency
// would cost the property that the whole suite runs on a bare machine, so the
// few methods render.js touches are stubbed below. If render.js starts using
// another one, this throws rather than quietly rendering less.
//
// Usage: node tests/js/render_dump.mjs SYMBOLS.json DOC.json THEME.json

import { readFileSync } from "node:fs";
import * as geometry from "../../drawlogic/web/js/geometry.js";
import * as render from "../../drawlogic/web/js/render.js";
import * as routing from "../../drawlogic/web/js/routing.js";

function node(tag) {
  const self = {
    tag,
    attrs: {},
    children: [],
    setAttribute(key, value) { self.attrs[key] = String(value); },
    getAttribute(key) { return self.attrs[key]; },
    removeAttribute(key) { delete self.attrs[key]; },
    appendChild(child) { self.children.push(child); return child; },
    append(...kids) { self.children.push(...kids); },
    replaceChildren(...kids) { self.children = kids; },
    remove() {},
    // The renderer looks for a content layer to reuse; there is never one
    // here, so it makes a fresh one every time, which is what we want.
    querySelector() { return null; },
    querySelectorAll() { return []; },
    classList: {
      add(...names) {
        self.attrs.class = `${self.attrs.class || ""} ${names.join(" ")}`.trim();
      },
      remove() {},
      contains() { return false; },
    },
    set textContent(value) { self._text = String(value); },
    get textContent() { return self._text || ""; },
  };
  return self;
}

globalThis.document = {
  createElementNS: (_ns, tag) => node(tag),
  createElement: (tag) => node(tag),
  createTextNode: (text) => ({ tag: "#text", _text: text, children: [] }),
};

geometry.setLibrary(JSON.parse(readFileSync(process.argv[2], "utf8")));
const doc = JSON.parse(readFileSync(process.argv[3], "utf8"));
render.setTheme(JSON.parse(readFileSync(process.argv[4], "utf8")));
// The DRC limits decide how the router picks corridors. Without them
// routing.js falls back to its own defaults and draws a different
// drawing from the exporter, which is the drift this file exists to catch.
if (process.argv[5]) {
  routing.setLimits(JSON.parse(readFileSync(process.argv[5], "utf8")));
}

const svg = node("svg");
render.render(svg, doc);

function flatten(root, out = []) {
  out.push(root);
  for (const child of root.children || []) flatten(child, out);
  return out;
}

const all = flatten(svg);
// An arrow is the only polygon the net layer draws. Symbol artwork can be a
// polygon too, so they are told apart by which group they are in rather than
// by shape.
function arrowsUnder(root) {
  const found = [];
  const walk = (n, inNets) => {
    const mine = inNets || (n.attrs.class || "").includes("dl-nets");
    if (mine && n.tag === "polygon") found.push(n.attrs.points);
    for (const child of n.children || []) walk(child, mine);
  };
  walk(root, false);
  return found;
}

console.log(JSON.stringify({
  arrows: arrowsUnder(svg).sort(),
  junctions: all.filter((n) => n.tag === "circle"
                        && (n.attrs.class || "").includes("dl-junction"))
    .map((n) => [n.attrs.cx, n.attrs.cy]).sort(),
}));
