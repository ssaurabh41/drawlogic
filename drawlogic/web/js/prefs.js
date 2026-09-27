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
export const PREFS = [
  { key: "autoConnect", label: "Auto-connect on drop", risk: true,
    help: "Dropping a cell so one of its pins lands on a free wire end joins them." },
  { key: "dragDuplicate", label: "Ctrl/Shift+drag duplicates", risk: true,
    help: "Dragging a cell with Ctrl or Shift held drags a copy instead." },
  { key: "layoutSelection", label: "Auto layout arranges only a selection", risk: true,
    help: "With two or more cells selected, Auto layout leaves everything else alone." },
  { key: "guides", label: "Alignment guides while dragging", risk: false,
    help: "Snap to line up with nearby cells; Alt disables it for one drag." },
  { key: "recovery", label: "Keep unsaved work to recover after a crash", risk: false,
    help: "A copy of unsaved changes stays in this browser until you save." },
  { key: "live", label: "Check the drawing as you edit (live DRC)", risk: false,
    help: "Runs the design rule checks after each edit." },
];

const DEFAULTS = {
  autoConnect: true,
  dragDuplicate: true,
  layoutSelection: true,
  guides: true,
  recovery: true,
  live: true,
  gridStyle: "dots",
  gridSize: 10,
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
