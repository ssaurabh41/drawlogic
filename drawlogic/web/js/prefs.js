// How this person likes to work, kept in the browser rather than the drawing.
//
// A preference is about the person, not the file: someone who finds snapping
// intrusive finds it intrusive in every drawing, and a drawing handed to a
// colleague should not switch their auto-connect off. So these live in
// localStorage, one object, and every feature that can surprise someone --
// by wiring, copying or rearranging on its own -- asks here first.

const KEY = "drawlogic.prefs";

// What each preference is, in the order the panel lists them. `risk` marks
// the ones that change a drawing without an explicit command for it.
//
// Only real choices are here. Drag-to-duplicate, laying out just a
// selection, alignment guides and crash recovery were switches once; they
// are simply how the editor works now, since nobody turned them off and each
// switch was one more line to read past to find the ones that matter.
export const PREFS = [
  { key: "autoConnect", label: "Auto-connect on drop", risk: true,
    help: "A cell dropped with a pin near a free pin or wire end is wired to it." },
  { key: "live", label: "Check the drawing as you edit (live DRC)", risk: false,
    help: "Runs the design rule checks after each edit." },
];

const DEFAULTS = {
  autoConnect: true,
  live: true,
};

let values = { ...DEFAULTS };
const listeners = [];

export function load() {
  let saved = {};
  try {
    saved = JSON.parse(window.localStorage.getItem(KEY) || "{}") || {};
    // Live checking had its own key before there was a panel; keep its answer.
    const live = window.localStorage.getItem("drawlogic.live");
    if (live !== null && saved.live === undefined) saved.live = live !== "0";
  } catch (error) {
    // Storage switched off: every preference stays at its default.
  }
  values = { ...DEFAULTS };
  for (const key of Object.keys(DEFAULTS)) {
    if (typeof saved[key] === typeof DEFAULTS[key]) values[key] = saved[key];
  }
  return values;
}

export function get(key) {
  return values[key];
}

export function set(key, value) {
  if (!(key in DEFAULTS) || typeof value !== typeof DEFAULTS[key]) return;
  values[key] = value;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(values));
  } catch (error) {
    // Still in effect for this page, just not remembered.
  }
  for (const listener of listeners) listener(key, value);
}

export function subscribe(listener) {
  listeners.push(listener);
}

export function defaults() {
  return { ...DEFAULTS };
}
