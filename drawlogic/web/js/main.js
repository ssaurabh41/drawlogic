// Boots the editor and wires the pieces together.
//
// Usage: loaded by index.html as a module. Talks to the server over
// /api/theme, /api/symbols, /api/files, /api/doc and /api/export.

import * as geometry from "./geometry.js";
import * as model from "./model.js";
import { bindMenus } from "./menus.js";
import { Inspector, buildPalette, clearPaletteSelection } from "./panels.js";
import * as picture from "./picture.js";
import * as prefs from "./prefs.js";
import * as recovery from "./recovery.js";
import * as shortcuts from "./shortcuts.js";
import * as render from "./render.js";
import * as routing from "./routing.js";
import { Selection, drawHandles } from "./selection.js";
import { makeTools, placementPreview } from "./tools.js";
import { Viewport } from "./viewport.js";

const store = new model.Store();
const selection = new Selection(store);
const ui = {};

let viewport = null;
let inspector = null;
let tools = {};
let activeTool = "select";
let clipboard = null;
// Where we came from while drilling into referenced drawings.
const trail = [];
let overlayOptions = {};

function $(id) { return document.getElementById(id); }

async function api(url, options) {
  const response = await fetch(url, options);
  const isJson = (response.headers.get("Content-Type") || "").includes("json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error((payload && payload.error) || `request failed (${response.status})`);
  }
  return payload;
}

// Did a press land on something, rather than on bare canvas? Shift means
// "pan" on the empty sheet and "copy as you drag" on an item, so the tool
// hand-off in bindCanvas and the viewport's pan guard in start both ask this
// one question -- which is why it lives out here rather than inside either.
function onSomething(event) {
  return Boolean(event.target.closest(
    ".dl-cell, .dl-shape, .dl-container, .dl-net, .dl-hit, [data-handle], [data-sheet-handle]"));
}

let toastTimer = null;
// The message a busy run is showing, or null when nothing is running, and
// whatever `say` was asked for while that was true. Between them they are the
// rule that only one thing talks at a time and the slow thing wins. Declared
// up here beside the timer they work with, rather than down beside `busy`,
// because `say` reads them and is defined first.
let busyNow = null;
let deferredSay = null;

// Two places, on purpose. The status bar keeps the last thing that happened
// for anyone who looks later; the toast puts it where the eye already is,
// because a message in the bottom-right corner after a click in the top-left
// is a message nobody reads. Reported as "after clicking save, display a
// message if successful or not" -- it did, just invisibly.
function say(message, kind) {
  // Something slow has the floor. This message fades and that one is still
  // true, so this one waits its turn rather than replacing it: a "laying
  // out..." that vanishes while the layout is still running is what makes
  // people press the button a second time. It is said when the floor clears.
  if (busyNow) {
    deferredSay = [message, kind];
    return;
  }
  ui.message.textContent = message;
  ui.message.className = "push" + (kind ? ` ${kind}` : "");

  if (!ui.toast) return;
  ui.toast.textContent = message;
  ui.toast.className = "toast shown" + (kind ? ` ${kind}` : "");
  ui.toast.hidden = false;
  window.clearTimeout(toastTimer);
  // Failures stay up longer: they are the ones worth reading twice.
  toastTimer = window.setTimeout(() => {
    ui.toast.classList.remove("shown");
  }, kind === "bad" ? 6000 : 2800);
}


// ---- work that takes longer than a message stays up for ----

let busyTimer = null;

/* Say that something is still running, and keep saying it.
 *
 * `say` fades after 2.8 seconds, which is right for "saved" and wrong for
 * anything slow: auto layout on a hundred gates runs for a minute, the
 * message went away after three seconds, and the editor then looked idle
 * while it was still working. People pressed the button again.
 *
 * So this one does not fade, and it counts up, because a number that keeps
 * moving is the difference between "still going" and "stuck". Returns the
 * function that ends it; call it in a `finally` so a failure clears the
 * message too.
 */
function busy(message) {
  const started = Date.now();
  const tick = () => {
    const seconds = Math.round((Date.now() - started) / 1000);
    const elapsed = seconds >= 2 ? ` (${seconds}s)` : "";
    ui.message.textContent = message + elapsed;
    ui.message.className = "push";
    if (ui.toast) {
      ui.toast.textContent = message + elapsed;
      ui.toast.className = "toast shown busy";
      ui.toast.hidden = false;
    }
  };

  window.clearTimeout(toastTimer);
  window.clearInterval(busyTimer);
  busyNow = message;
  tick();
  busyTimer = window.setInterval(tick, 1000);

  return () => {
    window.clearInterval(busyTimer);
    busyTimer = null;
    busyNow = null;
    if (ui.toast) ui.toast.classList.remove("busy");
    // Whatever tried to speak while the floor was taken says it now, which
    // is how the layout's own "9 cells in 4 columns" gets through.
    if (deferredSay) {
      const [message, kind] = deferredSay;
      deferredSay = null;
      say(message, kind);
    }
  };
}

// ---- drawing ----

function drawOverlay(options) {
  overlayOptions = options || {};
  if (!store.doc) return;
  // The DRC marks are merged in rather than passed by the caller: a tool
  // mid-drag sets its own overlay options, and the marks should not blink out
  // every time it does.
  drawHandles(ui.canvas, selection, viewport.zoom,
              { ...overlayOptions, drc: liveMarks });
}

function redraw() {
  if (!store.doc) return;
  render.render(ui.canvas, store.doc);
  drawOverlay(overlayOptions);
  refreshStatus();
}

function refreshStatus() {
  if (!store.doc) return;
  const doc = store.doc;
  ui.counts.textContent =
    `${doc.cells.length} cells | ${doc.nets.length} nets`
    + ((doc.shapes || []).length ? ` | ${doc.shapes.length} shapes` : "")
    + (selection.size ? ` | ${selection.size} selected` : "");
  ui.dirty.hidden = !store.dirty;
  ui.undo.disabled = !store.canUndo();
  ui.redo.disabled = !store.canRedo();
}

// ---- tools ----

const context = {
  store,
  selection,
  zoom: () => viewport.zoom,
  drawOverlay,
  say,
  setTool: (name) => setTool(name),
  editText: (id, fresh) => editTextInPlace(id, fresh),
  renameContainer: (id, fresh) => renameContainer(id, fresh),
};

function setTool(name) {
  const previous = tools[activeTool];
  if (previous && previous.onDeactivate) previous.onDeactivate();
  activeTool = name;
  for (const button of document.querySelectorAll("[data-tool]")) {
    button.setAttribute("aria-pressed",
                        String(button.getAttribute("data-tool") === name));
  }
  // The Shapes button stands for all four, so it lights up for any of them
  // and wears the icon of the one in hand.
  const shapes = document.getElementById("menu-shape-button");
  if (shapes) {
    shapes.setAttribute("aria-pressed", String(name === "shape"));
    const kind = name === "shape" && tools.shape
      ? (tools.shape.preset || tools.shape.kind) : null;
    document.getElementById("shape-button-icon")
      .setAttribute("href", kind ? `#i-shape-${kind}` : "#i-shapes");
  }
  const tool = tools[name];
  if (tool && tool.onActivate) tool.onActivate();
  else drawOverlay({});
  ui.canvas.style.cursor = tool && tool.cursorFor ? tool.cursorFor(null) : "default";
}

// Long enough to be comfortable, short enough not to catch two deliberate
// clicks in the same spot.
const DOUBLE_CLICK_MS = 400;
const DOUBLE_CLICK_SLOP = 4;

function bindCanvas() {
  // A redraw replaces the clicked node between the two clicks, so the browser
  // never gets two clicks on the same element and never fires `dblclick` here.
  // Recognising it from the timing is the only reliable way.
  let lastPress = { at: -Infinity, x: 0, y: 0 };

  ui.canvas.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || viewport.spaceHeld) return;
    if (event.shiftKey && activeTool === "select" && !onSomething(event)) {
      // Shift-drag on empty space pans, handled by the viewport. Shift is
      // free for that because adding to a selection is Ctrl, not Shift.
      return;
    }

    const now = performance.now();
    const again = now - lastPress.at < DOUBLE_CLICK_MS
      && Math.abs(event.clientX - lastPress.x) < DOUBLE_CLICK_SLOP
      && Math.abs(event.clientY - lastPress.y) < DOUBLE_CLICK_SLOP;
    lastPress = { at: now, x: event.clientX, y: event.clientY };
    if (again && onDoubleClick(event)) {
      // Anything the double-click opened -- a rename box -- keeps the focus
      // the browser would otherwise hand back to the canvas.
      event.preventDefault();
      return;
    }

    if (painting) {
      const node = event.target.closest(".dl-cell, .dl-shape");
      if (node && pasteStyle([node.getAttribute("data-id")], copiedStyle)) {
        if (!event.shiftKey) setPainting(false);
      } else {
        setPainting(false);
      }
      return;
    }

    const tool = tools[activeTool];
    if (tool && tool.onPointerDown) {
      tool.onPointerDown(event, viewport.toDoc(event.clientX, event.clientY));
      redraw();
      inspector.render();
    }
  });

  window.addEventListener("mousemove", (event) => {
    if (!store.doc) return;
    const point = viewport.toDoc(event.clientX, event.clientY);
    ui.cursor.textContent = `x ${Math.round(point[0])} y ${Math.round(point[1])}`;

    const tool = tools[activeTool];
    if (tool && tool.onPointerMove && tool.onPointerMove(event, point)) redraw();
    if (activeTool === "select" && tool.cursorFor) {
      // While a drag is in flight the pointer often outruns the thing it is
      // holding, so the element under it is no longer the cell. Ask the tool
      // what it is doing rather than what the pointer happens to be over.
      const holding = tool.mode === "move" || tool.mode === "resize"
        || tool.mode === "sheet";
      ui.canvas.style.cursor = viewport.spaceHeld ? "grab"
        : holding ? tool.cursorFor(event.target === ui.canvas ? null : event.target)
        : tool.cursorFor(event.target);
    }
  });

  // Dropping a symbol from the palette. The drag gives a position the
  // click-then-click path never had, so the cell lands where it was let go
  // rather than where the next click happens to be.
  //
  // A drag only says what it carries on the drop, so the type is noted when
  // it starts -- that is what lets the outline follow the pointer and snap to
  // a pin before anything is let go.
  let carrying = null;
  ui.paletteBody.addEventListener("dragstart", (event) => {
    const item = event.target.closest && event.target.closest(".palette-item");
    carrying = item ? item.dataset.symbol : null;
  });
  const stopCarrying = () => {
    carrying = null;
    drawOverlay();
  };
  ui.paletteBody.addEventListener("dragend", stopCarrying);
  ui.canvas.addEventListener("dragleave", (event) => {
    if (!ui.canvas.contains(event.relatedTarget)) drawOverlay();
  });

  ui.canvas.addEventListener("dragover", (event) => {
    if (![...event.dataTransfer.types].includes("application/x-drawlogic-symbol")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    if (carrying && store.doc) {
      drawOverlay(placementPreview(store.doc, carrying,
                                   viewport.toDoc(event.clientX, event.clientY)));
    }
  });

  ui.canvas.addEventListener("drop", (event) => {
    const type = event.dataTransfer.getData("application/x-drawlogic-symbol");
    if (!type) return;
    event.preventDefault();
    stopCarrying();
    const point = viewport.toDoc(event.clientX, event.clientY);
    let joined = [];
    const cell = store.mutate("place", (doc) => {
      // Placed and wired in one step, so one undo takes both back.
      const placed = model.placeCell(doc, type, point, prefs.get("autoConnect"));
      joined = placed.joined;
      return placed.cell;
    });
    if (!cell) {
      say(`could not place ${type}`, "bad");
      return;
    }
    selection.set([cell.id]);
    clearPaletteSelection(ui.paletteBody);
    setTool("select");
    redraw();
    inspector.render();
    say(joined.length ? `placed ${cell.label || cell.type}; joined ${joined.join(", ")}`
                      : `placed ${cell.label || cell.type}`, "good");
  });

  // Every mouse release anywhere in the window, because a drag that started
  // on the canvas has to finish even if the pointer left it -- but a release
  // that lands on a control was never part of a canvas gesture, and rebuilding
  // the properties panel underneath one destroys whatever is being typed into
  // it. That is what "the name I clicked gets deselected when I let go of the
  // mouse" was: the field was not losing its selection, it was being replaced.
  window.addEventListener("mouseup", (event) => {
    const tool = tools[activeTool];
    if (!tool || !tool.onPointerUp) return;
    if (event.target instanceof Element
        && event.target.closest("input, select, textarea, button, label")) {
      return;
    }
    if (tool.onPointerUp(event, viewport.toDoc(event.clientX, event.clientY))) {
      redraw();
    }
    inspector.render();
    refreshStatus();
  });
}

// ---- commands ----

function apply(label, change, note) {
  if (!selection.size) return;
  store.mutate(label, (doc) => change(doc, selection.ids));
  redraw();
  inspector.render();
  if (note) say(note);
}

async function deleteSelection({ contents = false } = {}) {
  if (selection.net !== null) {
    const ids = new Set([selection.net]);
    store.mutate("delete wire", (doc) => model.deleteItems(doc, ids));
    selection.clear();
    redraw();
    inspector.render();
    say("deleted 1 wire");
    return;
  }
  if (!selection.size) return;
  let ids = new Set(selection.ids);
  // A container that holds things asks first: the boundary alone, or the
  // boundary and everything in it. Never decided for you either way.
  // Cut takes a container's contents with it, as the copy it made did.
  if (contents) ids = model.withContents(store.doc, ids);
  const holding = [...ids].filter((id) => model.containerById(store.doc, id)
    && [...model.withContents(store.doc, [id])].some((inner) => !ids.has(inner)));
  if (holding.length) {
    const inside = [...model.withContents(store.doc, holding)].filter((id) => !ids.has(id)).length;
    const box = model.containerById(store.doc, holding[0]);
    const what = holding.length === 1 ? `"${box.title || box.id}"` : `${holding.length} containers`;
    const answer = await choose(
      "Delete container",
      `${what} ${holding.length === 1 ? "holds" : "hold"} ${inside} item${inside === 1 ? "" : "s"}.`,
      [{ label: "Delete container and contents", value: "all", danger: true },
       { label: "Keep contents", value: "keep" }]);
    if (!answer) return;
    if (answer === "all") ids = model.withContents(store.doc, ids);
  }
  store.mutate("delete", (doc) => model.deleteItems(doc, ids));
  selection.clear();
  redraw();
  inspector.render();
  say(`deleted ${ids.size} item(s)`);
}

// A small dialog asking which of a few things to do. Resolves to the chosen
// option's value, or null when it was closed without one.
function choose(title, message, options) {
  const dialog = ui.choiceDialog;
  dialog.querySelector(".choice-title").textContent = title;
  dialog.querySelector(".choice-message").textContent = message || "";
  const list = dialog.querySelector(".choice-options");
  list.textContent = "";
  return new Promise((resolve) => {
    let answer = null;
    for (const option of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `choice-option${option.danger ? " danger" : ""}`;
      button.textContent = option.label;
      if (option.indent) button.style.paddingLeft = `${12 + option.indent * 16}px`;
      button.addEventListener("click", () => {
        answer = option.value;
        dialog.close();
      });
      list.appendChild(button);
    }
    dialog.addEventListener("close", () => resolve(answer), { once: true });
    dialog.showModal();
    const first = list.querySelector("button");
    if (first) first.focus();
  });
}

function copySelection(cut) {
  if (!selection.size) return;
  clipboard = model.copyItems(store.doc, selection.ids);
  const count = clipboard.cells.length + clipboard.shapes.length;
  say(`${cut ? "cut" : "copied"} ${count} item(s)`);
  if (cut) deleteSelection({ contents: true });
}

function paste(offset) {
  if (!clipboard) return;
  const step = model.gridStep(store.doc) * (offset === undefined ? 2 : offset);
  const added = store.mutate("paste",
                             (doc) => model.pasteItems(doc, clipboard, step, step));
  if (added && added.length) {
    selection.set(added);
    redraw();
    inspector.render();
    say(`pasted ${added.length} item(s)`);
  }
}

function nudge(dx, dy, big) {
  const step = model.gridStep(store.doc) * (big ? 10 : 1);
  apply("nudge", (doc, ids) => model.moveItems(doc, ids, dx * step, dy * step));
}

// ---- hierarchy ----

// Where a ref points, read relative to the drawing that holds it. The server
// serves one folder, so these stay relative to its root.
function refPath(fromPath, ref) {
  const parts = (fromPath || "").split("/").slice(0, -1).concat(ref.split("/"));
  const out = [];
  for (const part of parts) {
    if (!part || part === ".") continue;
    if (part === ".." && out.length && out[out.length - 1] !== "..") out.pop();
    else out.push(part);
  }
  return out.join("/");
}

async function drillInto(cell) {
  const target = refPath(store.path, cell.ref);
  trail.push({ path: store.path, label: cell.label || cell.id });
  await openDrawing(target);
}

function drawBreadcrumb() {
  const bar = ui.breadcrumb;
  bar.textContent = "";
  // The trail only makes sense while it leads to where we actually are.
  if (!trail.length) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  trail.forEach((step, index) => {
    const link = document.createElement("button");
    link.className = "crumb";
    link.textContent = step.label;
    link.title = `back to ${step.path}`;
    link.addEventListener("click", async () => {
      const back = trail[index];
      trail.length = index;
      await openDrawing(back.path);
    });
    bar.appendChild(link);
    bar.appendChild(document.createTextNode(" / "));
  });
  const here = document.createElement("span");
  here.className = "crumb here";
  here.textContent = (store.doc && store.doc.title) || store.path || "";
  bar.appendChild(here);
}

// What a second click in the same spot means. Returns true when it meant
// something, so the tool's own press handler is left out of it.
function onDoubleClick(event) {
  if (activeTool === "shape" && tools.shape.polygon) {
    tools.shape.finishPolygon();
    redraw();
    inspector.render();
    return true;
  }
  // A name is edited where it is drawn. Checked before the wire, because a
  // net's name sits on its wire and the name is what was aimed at.
  const named = activeTool === "select" && store.doc
    ? render.nameAt(store.doc, viewport.toDoc(event.clientX, event.clientY)) : null;
  if (named) {
    renameInPlace(named);
    return true;
  }
  // Double-clicking a wire hands it back to the router, which is the way out
  // of a hand-routed wire you no longer want.
  const wire = event.target.closest(".dl-net, .dl-hit");
  if (wire && store.doc) {
    const netId = wire.getAttribute("data-id");
    const point = viewport.toDoc(event.clientX, event.clientY);
    const run = model.grabRun(store.doc, netId, point);
    if (run) {
      store.mutate("straighten wire",
                   (doc) => model.straighten(doc, netId, run.branch));
      redraw();
      inspector.render();
      say("wire handed back to the router");
      return true;
    }
  }

  // Double-clicking a shape edits what is written in it, where it is.
  const shapeNode = activeTool === "select" ? event.target.closest(".dl-shape") : null;
  if (shapeNode && store.doc) {
    const shape = (store.doc.shapes || []).find((s) => s.id === shapeNode.getAttribute("data-id"));
    if (shape && (shape.kind === "text" || geometry.SHAPE_TEXT_KINDS.includes(shape.kind))) {
      editTextInPlace(shape.id, false);
      return true;
    }
  }

  // Double-clicking a container's header renames it, where its title is.
  const boxNode = activeTool === "select" ? event.target.closest(".dl-container") : null;
  if (boxNode && store.doc) {
    renameContainer(boxNode.getAttribute("data-id"));
    return true;
  }

  // Double-clicking a block that stands for another drawing opens it, the way
  // double-clicking a folder opens it.
  const node = event.target.closest(".dl-cell");
  if (!node || !store.doc) return false;
  const cell = store.doc.cells.find((c) => c.id === node.getAttribute("data-id"));
  if (!cell || !cell.ref) return false;
  drillInto(cell);
  return true;
}

// Edit a container's title over its header band.
// `fresh` is a container just drawn: drawing it opened a gesture, and naming
// it closes that gesture, so the two are one undo step.
function renameContainer(id, fresh = false) {
  const box = model.containerById(store.doc, id);
  if (!box) {
    if (fresh) store.endGesture();
    return;
  }
  const depth = render.containerHeader(box);
  renameInPlace({ kind: "container", id,
                  box: [box.x + 6, box.y + Math.max(0, depth / 2 - 10), box.x + box.w - 6, box.y + depth] },
                fresh ? () => store.endGesture() : null);
}

// ---- format painter ----

// The style copied from an item, waiting to be pasted: Ctrl+Shift+C / V, or
// the Painter button, which applies it to the next item clicked. Only the
// style is copied -- colours, line weight, text size -- never geometry or
// names, the way a format painter works in every office tool.
let copiedStyle = null;
let painting = false;

function styleOfSelection() {
  const first = selection.items()[0];
  return first ? JSON.parse(JSON.stringify(first.style || {})) : null;
}

function pasteStyle(ids, style) {
  const targets = [...ids];
  if (!targets.length || !style) return false;
  store.mutate("paste style", (doc) => {
    for (const id of targets) {
      const item = model.itemById(doc, id);
      if (item) item.style = JSON.parse(JSON.stringify(style));
    }
  });
  redraw();
  inspector.render();
  return true;
}

function setPainting(on) {
  painting = on;
  ui.btnPainter.setAttribute("aria-pressed", String(on));
  ui.canvas.classList.toggle("painting", on);
}

function startPainter() {
  if (painting) {
    setPainting(false);
    return;
  }
  const style = styleOfSelection();
  if (!style) {
    say("select the item whose style you want to copy first", "warn");
    return;
  }
  copiedStyle = style;
  setPainting(true);
  say("click an item to give it this style (Shift+click for several, Esc to stop)");
}

// A text box over the name, in the name's own place: Enter or clicking away
// keeps it, Esc leaves it as it was. The same edit the properties panel makes,
// so it is one undo step. On a wire this is its label, which is what is drawn
// there; the net's name is edited in the panel.
function renameInPlace({ kind, id, box }, onDone = null) {
  const doc = store.doc;
  const current = kind === "cell"
    ? (doc.cells.find((c) => c.id === id) || {}).label
    : kind === "container" ? (model.containerById(doc, id) || {}).title
      : (doc.nets.find((n) => n.id === id) || {}).label;
  const rect = ui.canvas.getBoundingClientRect();
  const field = document.createElement("input");
  field.className = "rename-in-place";
  field.value = current || "";
  field.style.left = `${rect.left + (box[0] - viewport.panX) * viewport.zoom - 4}px`;
  field.style.top = `${rect.top + (box[1] - viewport.panY) * viewport.zoom - 4}px`;
  field.style.minWidth = `${Math.max(80, (box[2] - box[0]) * viewport.zoom + 24)}px`;
  document.body.appendChild(field);

  let finished = false;
  const finish = (keep) => {
    if (finished) return;
    finished = true;
    const value = field.value.trim();
    field.remove();
    if (keep && value !== (current || "")) {
      store.mutate("rename", (d) => {
        if (kind === "cell" || kind === "container") model.setLabel(d, id, value);
        else model.setNetLabel(d, id, value);
      });
    }
    if (onDone) onDone();
    redraw();
    inspector.render();
  };
  field.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") finish(true);
    else if (event.key === "Escape") finish(false);
  });
  // Focused a tick later, and only then listening for blur: the press that
  // opened it is still being handled, and would otherwise take the focus
  // straight back and close the box before anything could be typed.
  window.setTimeout(() => {
    field.focus();
    field.select();
    field.addEventListener("blur", () => finish(true));
  }, 0);
}

// Type into a shape on the canvas, as in a slide editor: a text shape where
// its words are, anything else over its box, the box's writing centred. A
// text shape is one line, kept on Enter; a box takes several, Enter starting
// a new one and Ctrl+Enter or a click elsewhere keeping them. Escape drops
// the edit -- and a text shape just made, with nothing typed, is removed.
function editTextInPlace(id, fresh) {
  const shape = (store.doc.shapes || []).find((s) => s.id === id);
  if (!shape) return;
  const single = shape.kind === "text";
  const rect = ui.canvas.getBoundingClientRect();
  const toScreen = (x, y) => [rect.left + (x - viewport.panX) * viewport.zoom,
                              rect.top + (y - viewport.panY) * viewport.zoom];
  const scale = Number(((store.doc.canvas || {}).font || {}).scale) || 1;
  const field = document.createElement(single ? "input" : "textarea");
  field.className = "text-in-place";
  if (single) {
    const size = render.shapeTextSize(shape) * scale * viewport.zoom;
    const [left, baseline] = toScreen(shape.x || 0, shape.y || 0);
    field.value = shape.text || "";
    field.style.fontSize = `${size}px`;
    field.style.left = `${left - 3}px`;
    field.style.top = `${baseline - size * 1.05 - 3}px`;
    field.style.minWidth = `${Math.max(60, size * 6)}px`;
  } else {
    const box = geometry.shapeBox(shape) || [0, 0, 80, 40];
    const [left, top] = toScreen(box[0], box[1]);
    field.value = geometry.cellTextLines(shape).join("\n");
    field.classList.add("boxed");
    field.style.fontSize = `${geometry.cellTextMetrics().size * scale * viewport.zoom}px`;
    field.style.left = `${left}px`;
    field.style.top = `${top}px`;
    field.style.width = `${Math.max(80, box[2] * viewport.zoom)}px`;
    field.style.height = `${Math.max(32, box[3] * viewport.zoom)}px`;
    const [across, down] = geometry.cellTextAlign(shape);
    field.style.textAlign = across;
    // Down, as it will be drawn: the lines' room left over goes above them,
    // all of it or half, as the box's vertical alignment says.
    const settle = () => {
      const lineHeight = parseFloat(getComputedStyle(field).lineHeight) || 16;
      const used = field.value.split("\n").length * lineHeight;
      const spare = Math.max(0, field.clientHeight - used - 16);
      field.style.paddingTop = `${8 + (down === "top" ? 0 : down === "bottom" ? spare : spare / 2)}px`;
    };
    field.addEventListener("input", settle);
    window.setTimeout(settle, 0);
  }
  // The shape's own writing is hidden while it is being rewritten, or the
  // old words show through under the new.
  const hide = document.createElement("style");
  hide.textContent = `.dl-shape[data-id="${CSS.escape(id)}"] ${single ? "text" : ".dl-shape-text"}`
    + " { visibility: hidden; }";
  document.head.appendChild(hide);
  document.body.appendChild(field);

  let finished = false;
  const finish = (keep) => {
    if (finished) return;
    finished = true;
    const value = single ? field.value.trim() : field.value;
    field.remove();
    hide.remove();
    const before = single ? (shape.text || "") : geometry.cellTextLines(shape).join("\n");
    if (fresh && (!keep || !value)) {
      // Made and left empty: as if it had never been, nothing to undo.
      store.cancelGesture();
      selection.set([]);
    } else {
      if (keep && value !== before) {
        store.mutate("text", (d) => {
          if (single) model.setLabel(d, id, value);
          else model.setCellText(d, id, value);
        });
      }
      if (fresh) store.endGesture();
    }
    redraw();
    inspector.render();
  };
  field.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Escape") finish(false);
    else if (event.key === "Enter" && (single || event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      finish(true);
    }
  });
  // As renameInPlace: focused a tick later, and only then listening for blur.
  window.setTimeout(() => {
    field.focus();
    field.select();
    field.addEventListener("blur", () => finish(true));
  }, 0);
}

// ---- tabs ----

// Every drawing open in this window. The one in front lives in the store; the
// others are kept here whole -- document, undo history, unsaved flag, the
// block symbols their hierarchy needs, and where the view was -- so going
// back to one is exactly as it was left, not the file read again.
const openTabs = [];

function findTab(path) {
  return openTabs.find((tab) => tab.path === path) || null;
}

function captureActive() {
  const tab = store.doc ? findTab(store.path) : null;
  if (!tab) return;
  Object.assign(tab, store.capture(), {
    view: { zoom: viewport.zoom, panX: viewport.panX, panY: viewport.panY },
    selection: [...selection.ids],
  });
}

function switchTab(path, { keepTrail = false } = {}) {
  if (path === store.path) return;
  const tab = findTab(path);
  if (!tab || !tab.doc) return;
  captureActive();
  geometry.setSheets(tab.sheets);
  store.restore(tab);
  // A different drawing: nothing half-done carries over (see openDrawing).
  setTool("select");
  selection.set(tab.selection || []);
  if (!keepTrail) trail.length = 0;
  ui.filePath.textContent = path;
  ui.fileSelect.value = path;
  syncControls();
  redraw();
  if (tab.view) {
    viewport.zoom = tab.view.zoom;
    viewport.panX = tab.view.panX;
    viewport.panY = tab.view.panY;
    viewport.apply();
  } else {
    viewport.fit(store.doc.canvas.width, store.doc.canvas.height);
  }
  inspector.render();
  drawBreadcrumb();
  renderTabs();
  refreshStatus();
}

function closeTab(path) {
  const tab = findTab(path);
  if (!tab || openTabs.length < 2) return;
  const dirty = path === store.path ? store.dirty : tab.dirty;
  if (dirty && !window.confirm(`${path} has unsaved changes. Close it and lose them?`)) {
    return;
  }
  if (dirty) recovery.discard(path);
  const index = openTabs.indexOf(tab);
  openTabs.splice(index, 1);
  if (path === store.path) {
    switchTab(openTabs[Math.min(index, openTabs.length - 1)].path);
  } else {
    renderTabs();
  }
}

function renderTabs() {
  const bar = ui.tabs;
  if (!bar) return;
  const buttons = openTabs.map((tab) => {
    const active = tab.path === store.path;
    const dirty = active ? store.dirty : tab.dirty;
    const button = document.createElement("div");
    button.className = "tab";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(active));
    button.title = tab.path;
    const name = document.createElement("span");
    name.className = "tab-name";
    name.textContent = tab.path.split("/").pop();
    button.append(name);
    if (dirty) {
      const mark = document.createElement("span");
      mark.className = "tab-dirty";
      mark.textContent = "\u25CF";
      mark.title = "unsaved changes";
      button.append(mark);
    }
    if (openTabs.length > 1) {
      const close = document.createElement("button");
      close.className = "tab-close";
      close.type = "button";
      close.textContent = "\u00D7";
      close.title = `close ${tab.path}`;
      close.addEventListener("click", (event) => {
        event.stopPropagation();
        closeTab(tab.path);
      });
      button.append(close);
    }
    button.addEventListener("click", () => switchTab(tab.path));
    return button;
  });
  bar.replaceChildren(...buttons);
}

function stepHistory(back) {
  const label = back ? store.undo() : store.redo();
  if (label === false) return;
  // Items may have vanished, so drop anything selected that no longer exists.
  const alive = new Set(model.items(store.doc).map((i) => i.id));
  selection.set([...selection.ids].filter((id) => alive.has(id)));
  // The sheet controls show the document's own values, and undoing a text or
  // symbol size change left the slider where the undone drag had put it.
  syncControls();
  redraw();
  inspector.render();
  say(`${back ? "undid" : "redid"} ${label}`);
}

function runCommand(command) {
  const commands = {
    "rotate-cw": () => apply("rotate", (d, ids) => model.rotateCells(d, ids, 90)),
    "rotate-ccw": () => apply("rotate", (d, ids) => model.rotateCells(d, ids, -90)),
    "flip-h": () => apply("flip", (d, ids) => model.flipCells(d, ids, false)),
    "flip-v": () => apply("flip", (d, ids) => model.flipCells(d, ids, true)),
    group: () => {
      if (selection.size > 1) {
        apply("group", (d, ids) => model.groupItems(d, ids),
              `grouped ${selection.size} items`);
      }
    },
    ungroup: () => apply("ungroup", (d, ids) => model.ungroupItems(d, ids), "ungrouped"),
    front: () => apply("z-order", (d, ids) => model.bringToFront(d, ids),
                       "brought to front"),
    back: () => apply("z-order", (d, ids) => model.sendToBack(d, ids), "sent to back"),
    layout: () => autoLayout(),
    tidy: () => {
      if (!selection.size) {
        say("select the cells to tidy", "bad");
        return;
      }
      // Counted inside the mutation so the message can say what happened
      // rather than just that something did.
      let straightened = 0;
      store.mutate("tidy", (doc) => { straightened = model.tidy(doc, selection.ids); });
      redraw();
      inspector.render();
      say(straightened
        ? `tidied: ${straightened} wire${straightened === 1 ? "" : "s"} now run straight`
        : "nothing to line up -- those cells already sit square");
    },
    delete: deleteSelection,
    "container-create": () => {
      if (!selection.size) {
        say("select what the container should hold first", "bad");
        return;
      }
      const box = store.mutate("container", (doc) => model.containerFromSelection(doc, selection.ids));
      if (!box) return;
      selection.set([box.id]);
      redraw();
      inspector.render();
      renameContainer(box.id);
    },
    "container-fit": () => {
      const boxes = selection.items().filter(model.isContainer);
      if (!boxes.length) {
        say("select a container to fit", "bad");
        return;
      }
      let fitted = 0;
      store.mutate("fit container", (doc) => {
        // Inner ones first, so an outer one fits round its children's new size.
        const order = boxes.slice().sort((a, b) => model.containerAncestors(doc, b.id).length
                                                    - model.containerAncestors(doc, a.id).length);
        for (const box of order) if (model.fitContainer(doc, box.id)) fitted += 1;
        if (!fitted) return false;
      });
      redraw();
      inspector.render();
      say(fitted ? `fitted ${count(fitted, "container")} to contents`
                 : "an empty container has nothing to fit to", fitted ? undefined : "warn");
    },
    "container-ungroup": () => {
      const n = selection.items().filter(model.isContainer).length;
      if (!n) {
        say("select a container to ungroup", "bad");
        return;
      }
      const ids = new Set(selection.ids);
      store.mutate("ungroup container", (doc) => model.ungroupContainers(doc, ids));
      selection.set([...ids].filter((id) => model.itemById(store.doc, id)));
      redraw();
      inspector.render();
      say(`removed ${count(n, "container")}; what ${n === 1 ? "it" : "they"} held stays`);
    },
    "container-remove": () => {
      const moved = store.mutate("remove from container",
                                 (doc) => model.removeFromContainer(doc, selection.ids));
      redraw();
      inspector.render();
      if (moved) say(`moved ${count(moved, "item")} out of ${moved === 1 ? "its" : "their"} container`);
      else say("nothing selected is in a container", "warn");
    },
    "container-move": moveIntoContainerAsked,
    "style-save": saveStyleAsked,
    "component-create": createComponentAsked,
    "component-insert": insertComponentAsked,
    "component-repeat": repeatAsked,
    "component-edit": () => {
      const [cell] = selection.items();
      if (cell && cell.ref) drillInto(cell);
      else say("select an instance of a component to edit its definition", "bad");
    },
    "component-independent": makeIndependentAsked,
    "component-refresh": () => refreshComponents({ announce: true }),
    "style-edit": () => {
      const refs = new Set(selection.items().map((item) => item.styleRef).filter(Boolean));
      if (refs.size === 1) editNamedStyle([...refs][0]);
    },
    "container-layout": () => {
      const boxes = selection.items().filter(model.isContainer);
      if (boxes.length !== 1) {
        say("select one container to lay out its contents", "bad");
        return;
      }
      autoLayout(boxes[0].id);
    },
  };

  if (command.startsWith("align-")) {
    const edge = command.slice(6);
    apply("align", (d, ids) => model.align(d, ids, edge), `aligned ${edge}`);
    return;
  }
  if (command.startsWith("distribute-")) {
    const axis = command.slice(11);
    if (selection.size < 3) {
      say("distributing needs three or more items", "bad");
      return;
    }
    apply("distribute", (d, ids) => model.distribute(d, ids, axis), "distributed");
    return;
  }
  const handler = commands[command];
  if (handler) handler();
}

// Move into container...: a tree of the containers the selection can go into,
// with the sheet itself at the top for taking it out of every one. Each row
// shows the container's header colour and how much it holds; the one the
// selection is already in is marked and cannot be chosen. The row under the
// pointer or the keyboard is outlined on the canvas, so the choice is made
// looking at the drawing rather than at a list of names.
async function moveIntoContainerAsked() {
  if (!selection.size) {
    say("select what to move into a container first", "bad");
    return;
  }
  const ids = new Set(selection.ids);
  const allowed = new Set(model.containerChoices(store.doc, ids).map((box) => box.id));
  if (!allowed.size && model.sharedContainer(store.doc, ids) === null) {
    say("there is no container to move that into", "warn");
    return;
  }
  const target = await pickContainer(ids, allowed);
  if (target === undefined) return;
  const moved = store.mutate("move into container",
                             (doc) => model.moveIntoContainer(doc, ids, target));
  redraw();
  inspector.render();
  if (!moved) return;
  const box = target === null ? null : model.containerById(store.doc, target);
  say(box ? `moved ${count(moved, "item")} into ${box.title || box.id}`
          : `moved ${count(moved, "item")} out onto the sheet`);
}

// The picker itself. Resolves to a container id, null for the sheet, or
// undefined when closed without a choice.
function pickContainer(ids, allowed) {
  const doc = store.doc;
  const dialog = ui.containerDialog;
  const list = dialog.querySelector(".pick-list");
  const search = dialog.querySelector(".pick-search");
  const n = [...ids].length;
  dialog.querySelector(".pick-title").textContent = `Move ${count(n, "item")} into\u2026`;
  const current = model.sharedContainer(doc, ids);
  const defaults = model.containerDefaults();
  const title = (box) => box.title || box.id;

  // Every allowed container, in tree order, with its depth and whether it is
  // the last of its siblings -- which is what the guide lines need.
  const rows = [{ id: null, label: "Sheet", note: "no container", depth: 0,
                  path: "", swatch: null }];
  for (const box of render.containerPaintOrder(doc)) {
    if (!allowed.has(box.id)) continue;
    const trail = model.containerAncestors(doc, box.id).reverse();
    const held = model.withContents(doc, [box.id]).size - 1;
    rows.push({
      id: box.id, label: title(box), depth: trail.length + 1,
      path: trail.map(title).join(" \u203a "),
      note: `${held} item${held === 1 ? "" : "s"}`,
      swatch: (box.style || {}).headerFill || defaults.headerFill,
    });
  }

  return new Promise((resolve) => {
    let answer;
    let active = -1;
    let shown = [];

    const outline = (row) => {
      const box = row && row.id !== null ? model.containerById(doc, row.id) : null;
      drawOverlay(box ? { target: [box.x, box.y, box.w, box.h] } : {});
    };
    const usable = (row) => row.id !== current;
    const focus = (index) => {
      active = index;
      list.querySelectorAll(".pick-row").forEach((node, i) => {
        node.classList.toggle("active", i === index);
        if (i === index) node.scrollIntoView({ block: "nearest" });
      });
      outline(shown[index]);
    };
    const choose = (row) => {
      if (!row || !usable(row)) return;
      answer = row.id;
      dialog.close();
    };

    const fill = () => {
      const query = search.value.trim().toLowerCase();
      // Searching flattens the tree: matches only, each with where it is.
      shown = query ? rows.filter((row) => row.label.toLowerCase().includes(query)) : rows;
      list.textContent = "";
      shown.forEach((row, index) => {
        const node = document.createElement("button");
        node.type = "button";
        node.className = "pick-row";
        node.setAttribute("role", "option");
        if (!usable(row)) {
          node.classList.add("current");
          node.setAttribute("aria-disabled", "true");
        }
        const depth = query ? 0 : row.depth;
        node.style.setProperty("--depth", depth);
        if (depth > 0) node.classList.add("nested");
        const swatch = document.createElement("span");
        swatch.className = row.swatch ? "pick-swatch" : "pick-swatch sheet";
        if (row.swatch && row.swatch !== "none") swatch.style.background = row.swatch;
        const name = document.createElement("span");
        name.className = "pick-name";
        name.textContent = row.label;
        if (query && row.path) {
          const where = document.createElement("span");
          where.className = "pick-path";
          where.textContent = row.path;
          name.appendChild(where);
        }
        const note = document.createElement("span");
        note.className = "pick-note";
        note.textContent = usable(row) ? row.note : "current";
        node.append(swatch, name, note);
        node.addEventListener("mouseenter", () => focus(index));
        node.addEventListener("click", () => choose(row));
        list.appendChild(node);
      });
      if (!shown.length) {
        const empty = document.createElement("p");
        empty.className = "pick-empty";
        empty.textContent = "No container by that name";
        list.appendChild(empty);
      }
      const first = shown.findIndex((row) => usable(row) && row.id !== null);
      focus(first >= 0 ? first : shown.findIndex(usable));
    };

    const step = (by) => {
      if (!shown.length) return;
      let index = active;
      for (let tries = 0; tries < shown.length; tries += 1) {
        index = (index + by + shown.length) % shown.length;
        if (usable(shown[index])) break;
      }
      focus(index);
    };
    const onKey = (event) => {
      if (event.key === "ArrowDown") { event.preventDefault(); step(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); step(-1); }
      else if (event.key === "Enter") { event.preventDefault(); choose(shown[active]); }
    };

    search.value = "";
    // A search box is only worth its room when there is something to search.
    search.hidden = rows.length <= 8;
    search.oninput = fill;
    dialog.addEventListener("keydown", onKey);
    dialog.addEventListener("close", () => {
      dialog.removeEventListener("keydown", onKey);
      drawOverlay({});
      resolve(answer);
    }, { once: true });
    fill();
    dialog.showModal();
    (search.hidden ? list.querySelector(".pick-row.active") || list : search).focus();
  });
}

// ---- linked components ----

// A form with OK and Cancel. `build(body)` fills it and returns a function
// reading the answer, or a string saying what is wrong with it. Resolves to
// the answer, or null when cancelled.
function formDialog(title, note, okLabel, build) {
  const dialog = ui.formDialog;
  dialog.querySelector(".form-title").textContent = title;
  dialog.querySelector(".form-note").textContent = note || "";
  const body = dialog.querySelector(".form-body");
  body.textContent = "";
  const read = build(body);
  const ok = dialog.querySelector(".form-ok");
  const cancel = dialog.querySelector(".form-cancel");
  ok.textContent = okLabel;
  return new Promise((resolve) => {
    let answer = null;
    const onOk = () => {
      const value = read();
      if (typeof value === "string") {
        say(value, "bad");
        return;
      }
      answer = value;
      dialog.close();
    };
    const onCancel = () => dialog.close();
    const onKey = (event) => {
      if (event.key === "Enter" && event.target.tagName === "INPUT") {
        event.preventDefault();
        onOk();
      }
    };
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    dialog.addEventListener("keydown", onKey);
    dialog.addEventListener("close", () => {
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      dialog.removeEventListener("keydown", onKey);
      resolve(answer);
    }, { once: true });
    dialog.showModal();
    const first = body.querySelector("input");
    if (first) first.focus();
  });
}

function formRow(body, label, field, after = null) {
  const node = document.createElement("label");
  node.textContent = label;
  body.append(node, field, after || document.createElement("span"));
}

function formInput(value, type = "text") {
  const field = document.createElement("input");
  field.type = type;
  field.value = value;
  return field;
}

// An answer from the server that replaces the drawing, applied as one undo
// step if it is still about the drawing as it was asked about -- the same
// rule a layout answer follows.
function applyAnswer(asked, result, label) {
  if (!store.matches(asked)) {
    say("edited while that was being done -- nothing changed here, do it again", "bad");
    return false;
  }
  store.mutate(label, (doc) => {
    for (const key of Object.keys(doc)) delete doc[key];
    Object.assign(doc, result.doc);
  });
  useSheets(result.sheets);
  if (result.path && ![...ui.fileSelect.options].some((o) => o.value === result.path)) {
    const option = document.createElement("option");
    option.value = result.path;
    option.textContent = result.path;
    ui.fileSelect.appendChild(option);
  }
  return true;
}

// What a component action did, unless resolving the drawing afterwards found
// something wrong, which matters more than the success.
function sayMade(result, note) {
  const problems = result.problems || [];
  if (problems.length) say(`${note}, but ${problems[0].where}: ${problems[0].message}`, "bad");
  else say(note, "good");
}

// The block symbols the drawing in front needs, kept with its tab too.
function useSheets(data) {
  geometry.setSheets(data);
  const tab = findTab(store.path);
  if (tab) tab.sheets = data;
}

// Create linked component from selection: name it, review the ports the
// server found -- one per wire crossing the selection's edge, named from the
// wire -- and the selection becomes one instance of a new drawing kept in
// components/ beside this one.
async function createComponentAsked() {
  if (!selection.size) {
    say("select what the component should contain first", "bad");
    return;
  }
  if (!store.path) {
    say("save this drawing first: a component is kept beside it", "bad");
    return;
  }
  const raw = window.prompt("Name for the component (e.g. SM):", "");
  const name = (raw || "").trim();
  if (!name) return;
  const ids = [...selection.ids];
  const asked = store.stamp();
  let plan;
  try {
    plan = await api("/api/component", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "plan", doc: store.doc, source: asked.path, ids, name }),
    });
  } catch (error) {
    say(error.message, "bad");
    return;
  }
  if (plan.problems.length) {
    say(`cannot make a component of that: ${plan.problems.join("; ")}`, "bad");
    return;
  }
  const fields = new Map();
  const names = await formDialog(
    `Create component "${name}"`,
    `Kept in ${plan.path}${plan.exists ? " -- which already exists and will be replaced" : ""}. `
    + (plan.ports.length
      ? "Each wire crossing the edge of the selection becomes a port. Name them:"
      : "Nothing is wired across the edge of the selection, so it has no ports."),
    plan.exists ? "Replace and create" : "Create",
    (body) => {
      for (const port of plan.ports) {
        const field = formInput(port.name);
        const badge = document.createElement("span");
        badge.className = `dir ${port.dir}`;
        badge.textContent = port.dir === "in" ? "in" : "out";
        badge.title = port.width > 1 ? `${port.width} bits` : "1 bit";
        formRow(body, port.width > 1 ? `[${port.width}]` : "", field, badge);
        fields.set(port.key, field);
      }
      return () => {
        const chosen = {};
        const seen = new Set();
        for (const [key, field] of fields) {
          const value = field.value.trim();
          if (!value) return "every port needs a name";
          if (seen.has(value)) return `two ports cannot both be called "${value}"`;
          seen.add(value);
          chosen[key] = value;
        }
        return chosen;
      };
    });
  if (!names) return;
  const done = busy(`making component ${name}...`);
  try {
    const result = await api("/api/component", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "create", doc: store.doc, source: asked.path, ids, name,
                             names, overwrite: plan.exists }),
    });
    if (!applyAnswer(asked, result, "create component")) return;
    selection.set(result.instance ? [result.instance] : []);
    redraw();
    inspector.render();
    sayMade(result, `${result.note}; this drawing now has one instance of it`);
  } catch (error) {
    say(error.message, "bad");
  } finally {
    done();
  }
}

// Insert component: any drawing in the served folder, components/ beside
// this drawing first, placed in the middle of the view as an instance.
async function insertComponentAsked() {
  if (!store.path) {
    say("save this drawing first: a component is named relative to it", "bad");
    return;
  }
  let listing;
  try {
    listing = await api("/api/files");
  } catch (error) {
    say(error.message, "bad");
    return;
  }
  const here = store.path.split("/").slice(0, -1).join("/");
  const near = `${here ? `${here}/` : ""}components/`;
  const files = listing.files.filter((f) => f !== store.path)
    .sort((a, b) => (b.startsWith(near) - a.startsWith(near)) || a.localeCompare(b));
  if (!files.length) {
    say("there is no other drawing to insert", "warn");
    return;
  }
  const picked = await choose("Insert component",
                              "Every drawing in the folder can be placed as a block; its ports become the pins.",
                              files.map((f) => ({ label: f, value: f })));
  if (!picked) return;
  const ref = model.relativeRef(store.path, picked);
  const stem = picked.split("/").pop().replace(/\.dlg$/, "");
  const rect = ui.canvas.getBoundingClientRect();
  const at = viewport.toDoc(rect.left + rect.width / 2, rect.top + rect.height / 2);
  const asked = store.stamp();
  const probe = JSON.parse(JSON.stringify(store.doc));
  probe.cells.push({ id: "__probe", type: "sheet", ref, x: 0, y: 0 });
  try {
    const result = await api("/api/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: probe, source: asked.path }),
    });
    if (!store.matches(asked)) return;
    useSheets(result.sheets);
    const symbol = geometry.get(`sheet:${ref}`);
    if (!symbol) {
      say(`cannot use ${picked} as a component`, "bad");
      return;
    }
    const cell = store.mutate("insert component", (doc) => {
      const made = model.placeCell(doc, `sheet:${ref}`, at, false).cell;
      if (!made) return false;
      made.type = "sheet";
      made.ref = ref;
      made.label = stem.toUpperCase();
      made.preview = true;
      return made;
    });
    if (cell) selection.set([cell.id]);
    redraw();
    inspector.render();
    say(`placed ${picked}; Component > Repeat... places more`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// Repeat: the selected item copied into a grid, linked copies of an
// instance, named in sequence.
async function repeatAsked() {
  const items = selection.items();
  if (items.length !== 1) {
    say("select the one item to repeat", "bad");
    return;
  }
  const [item] = items;
  const current = item.label || item.title || "";
  const match = /^(.*?)(\d+)$/.exec(current);
  const fields = {};
  const answer = await formDialog(
    "Repeat",
    item.ref ? "Each copy is linked to the same definition: editing it changes them all."
      : "Copies of the selected item, in a grid.",
    "Repeat",
    (body) => {
      fields.rows = formInput("2", "number");
      fields.columns = formInput("4", "number");
      fields.gapX = formInput("30", "number");
      // Down, room for the name above each copy as well as the gap.
      fields.gapY = formInput("40", "number");
      fields.prefix = formInput(match ? match[1] : (current ? `${current} ` : ""));
      fields.start = formInput(match ? match[2] : "0", "number");
      formRow(body, "Rows", fields.rows);
      formRow(body, "Columns", fields.columns);
      formRow(body, "Gap across", fields.gapX);
      formRow(body, "Gap down", fields.gapY);
      formRow(body, "Name prefix", fields.prefix);
      formRow(body, "Starting index", fields.start);
      return () => {
        const value = Object.fromEntries(Object.entries(fields).map(([k, f]) => [k, f.value]));
        const count2 = Number(value.rows) * Number(value.columns);
        if (!(Number(value.rows) >= 1 && Number(value.columns) >= 1)) return "rows and columns start at 1";
        if (count2 > 400) return "that is more than 400 copies";
        return value;
      };
    });
  if (!answer) return;
  const added = store.mutate("repeat", (doc) => model.repeatItems(doc, item.id, answer));
  if (!added) {
    say("could not repeat that", "bad");
    return;
  }
  selection.set([item.id, ...added]);
  redraw();
  inspector.render();
  say(`${added.length + 1} ${added.length ? "copies" : "copy"} in ${answer.rows} x ${answer.columns}`
      + (item.ref ? ", all linked to the same definition" : ""), "good");
}

// Make independent: this instance gets a copy of the definition of its own,
// and stops changing when the original does. The other instances do not.
async function makeIndependentAsked() {
  const [cell] = selection.items();
  if (!cell || !cell.ref || selection.size !== 1) {
    say("select one instance of a component", "bad");
    return;
  }
  const asked = store.stamp();
  try {
    const result = await api("/api/component", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "copy", doc: store.doc, source: asked.path, cell: cell.id }),
    });
    if (!applyAnswer(asked, result, "make independent")) return;
    redraw();
    inspector.render();
    sayMade(result, result.note);
  } catch (error) {
    say(error.message, "bad");
  }
}

// Read every component this drawing uses again, and redraw its instances
// with their pins as the definitions now have them. Wires naming a pin that
// is gone are reported, never moved to another one.
async function refreshComponents({ announce = false } = {}) {
  if (!store.doc || !store.path) return;
  const asked = store.stamp();
  try {
    const result = await api("/api/resolve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, source: asked.path }),
    });
    if (!store.matches(asked, { edits: false })) return;
    useSheets(result.sheets);
    redraw();
    inspector.render();
    reportInterface(announce ? "components refreshed" : null);
  } catch (error) {
    say(error.message, "bad");
  }
}

function reportInterface(fine) {
  const lost = model.interfaceProblems(store.doc);
  if (lost.length) {
    const first = lost.slice(0, 3).map((p) => `${p.label}.${p.pin}`).join(", ");
    say(`unresolved interface: ${count(lost.length, "wire")} name${lost.length === 1 ? "s" : ""} `
        + `a pin the component no longer has (${first}${lost.length > 3 ? ", ..." : ""}); `
        + "reconnect or delete them", "bad");
  } else if (fine) {
    say(fine, "good");
  }
}

// After a drawing is saved, every open drawing using it as a component is
// read again, so its instances show the definition as it now is.
async function refreshUsersOf(path) {
  const users = openTabs.filter((tab) => tab.path !== path
    && (tab.path === store.path ? store.doc : tab.doc)
    && (tab.path === store.path ? store.doc : tab.doc).cells
      .some((c) => c.ref && refPath(tab.path, c.ref) === path));
  let lost = 0;
  for (const tab of users) {
    const doc = tab.path === store.path ? store.doc : tab.doc;
    try {
      const result = await api("/api/resolve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc, source: tab.path }),
      });
      tab.sheets = result.sheets;
      if (tab.path === store.path) useSheets(result.sheets);
      lost += model.interfaceProblems(doc, result.sheets).length;
    } catch (error) {
      // The next open or refresh will try again.
    }
  }
  if (users.length) {
    const where = users.map((t) => t.path).join(", ");
    if (lost) {
      say(`component updated; in ${where}, ${count(lost, "wire")} now name${lost === 1 ? "s" : ""} `
          + "a pin it no longer has -- reconnect or delete them", "bad");
    } else {
      say(`component updated: ${where} redrawn with it`, "good");
    }
  }
}

// ---- named styles ----

// Save selection's style: the first selected item's look, named, and every
// selected item pointed at it.
function saveStyleAsked() {
  const items = selection.items();
  if (!items.length) {
    say("select the item whose look to keep first", "bad");
    return;
  }
  const raw = window.prompt("Name for this style (e.g. compute, memory, io):",
                            items[0].styleRef || "");
  const name = (raw || "").trim();
  if (!name) return;
  if ((store.doc.styles || {})[name] && name !== items[0].styleRef
      && !window.confirm(`There is already a style called "${name}". Replace it?`)) return;
  const ids = new Set(selection.ids);
  store.mutate("save style", (doc) => model.saveNamedStyle(doc, name, items[0].id, ids));
  redraw();
  inspector.render();
  say(`saved style "${name}"; ${count(ids.size, "item")} now use${ids.size === 1 ? "s" : ""} it`);
}

// Edit named style: every setting a named style can make, each blank for
// "not set" -- the theme's then, or the item's own. Saving it is one step,
// and changes every item using the style.
function editNamedStyle(name) {
  const doc = store.doc;
  const spec = JSON.parse(JSON.stringify((doc.styles || {})[name] || {}));
  const dialog = ui.styleDialog;
  const users = model.items(doc).filter((item) => item.styleRef === name).length;
  dialog.querySelector(".style-title").textContent = `Edit style "${name}"`;
  dialog.querySelector(".style-note").textContent =
    `Used by ${count(users, "item")}. A blank field is not set by the style: the theme's, or what an item sets itself, is used.`;
  const form = dialog.querySelector(".style-form");
  form.textContent = "";
  const fields = [];

  const head = (text) => {
    const h = document.createElement("div");
    h.className = "sf-head";
    h.textContent = text;
    form.appendChild(h);
  };
  const label = (text) => {
    const node = document.createElement("label");
    node.textContent = text;
    form.appendChild(node);
  };
  const colour = (part, key) => {
    const wrap = document.createElement("div");
    wrap.className = "sf-colour";
    const text = document.createElement("input");
    text.type = "text";
    text.placeholder = "not set";
    text.value = (spec[part] || {})[key] || "";
    const swatch = document.createElement("input");
    swatch.type = "color";
    swatch.value = /^#[0-9a-f]{6}$/i.test(text.value) ? text.value : "#ffffff";
    swatch.addEventListener("input", () => { text.value = swatch.value; });
    text.addEventListener("input", () => {
      if (/^#[0-9a-f]{6}$/i.test(text.value)) swatch.value = text.value;
    });
    wrap.append(text, swatch);
    form.appendChild(wrap);
    fields.push([part, key, () => text.value.trim()]);
  };
  const number = (part, key, placeholder) => {
    const field = document.createElement("input");
    field.type = "number";
    field.step = "0.5";
    field.min = "0";
    field.placeholder = placeholder;
    const value = (spec[part] || {})[key];
    field.value = value === undefined ? "" : value;
    form.appendChild(field);
    fields.push([part, key, () => (field.value === "" ? "" : Number(field.value))]);
  };
  const weight = (part) => {
    const field = document.createElement("select");
    for (const [value, text] of [["", "not set"], ["400", "Regular"], ["600", "Bold"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      field.appendChild(option);
    }
    const now = (spec[part] || {}).fontWeight;
    field.value = now === undefined ? "" : (Number(now) >= 600 ? "600" : "400");
    form.appendChild(field);
    fields.push([part, "fontWeight", () => (field.value === "" ? "" : Number(field.value))]);
  };
  const blank = () => form.appendChild(document.createElement("span"));

  head("Shape");
  label("Fill, line, weight");
  colour("style", "fill");
  colour("style", "stroke");
  number("style", "strokeWidth", "weight");
  label("Header, title");
  colour("style", "headerFill");
  colour("style", "titleFill");
  blank();
  head("Heading");
  label("Size, weight, colour");
  number("headingStyle", "fontSize", "size");
  weight("headingStyle");
  colour("headingStyle", "fill");
  head("Text");
  label("Size, weight, colour");
  number("textStyle", "fontSize", "size");
  weight("textStyle");
  colour("textStyle", "fill");
  label("Font, spacing");
  const face = document.createElement("select");
  for (const [value, text] of [["", "Sans (default)"], ["mono", "Mono"], ["serif", "Serif"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    face.appendChild(option);
  }
  face.value = (spec.textStyle || {}).fontFamily || "";
  form.appendChild(face);
  fields.push(["textStyle", "fontFamily", () => face.value]);
  number("textStyle", "lineHeight", "spacing");
  blank();

  const save = dialog.querySelector(".style-save");
  const cancel = dialog.querySelector(".style-cancel");
  const rename = dialog.querySelector(".style-rename");
  const remove = dialog.querySelector(".style-delete");
  const onRename = () => {
    const next = (window.prompt(`Rename style "${name}" to:`, name) || "").trim();
    if (!next || next === name) return;
    let done = false;
    store.mutate("rename style", (d) => {
      done = model.renameNamedStyle(d, name, next);
      return done;
    });
    if (!done) {
      say(`there is already a style called "${next}"`, "bad");
      return;
    }
    dialog.close();
    redraw();
    inspector.render();
    say(`style "${name}" is now "${next}"; ${count(users, "item")} follow it`, "good");
  };
  const onDelete = () => {
    if (!window.confirm(`Delete style "${name}"? The ${count(users, "item")} using it keep `
                        + "how they look; they just stop following the style.")) return;
    store.mutate("delete style", (d) => model.deleteNamedStyle(d, name));
    dialog.close();
    redraw();
    inspector.render();
    say(`deleted style "${name}"; ${count(users, "item")} kept their look`, "good");
  };
  rename.addEventListener("click", onRename);
  remove.addEventListener("click", onDelete);
  const onSave = () => {
    const next = { style: { ...(spec.style || {}) }, headingStyle: { ...(spec.headingStyle || {}) },
                   textStyle: { ...(spec.textStyle || {}) } };
    for (const [part, key, read] of fields) {
      const value = read();
      if (value === "" || Number.isNaN(value)) delete next[part][key];
      else next[part][key] = value;
    }
    store.mutate("edit style", (d) => model.updateNamedStyle(d, name, next));
    dialog.close();
    redraw();
    inspector.render();
    say(`style "${name}" changed; ${count(users, "item")} redrawn`);
  };
  const onCancel = () => dialog.close();
  save.addEventListener("click", onSave);
  cancel.addEventListener("click", onCancel);
  dialog.addEventListener("close", () => {
    save.removeEventListener("click", onSave);
    cancel.removeEventListener("click", onCancel);
    rename.removeEventListener("click", onRename);
    remove.removeEventListener("click", onDelete);
  }, { once: true });
  dialog.showModal();
}

// ---- files ----

async function openDrawing(path) {
  // Open in a tab already: go to it, with its history and unsaved work as
  // they were, rather than reading the file again over them.
  if (path !== store.path && findTab(path)) {
    switchTab(path, { keepTrail: true });
    return;
  }
  // Only reopening the drawing in front of you throws anything away; any
  // other drawing opens in a tab of its own beside it.
  if (path === store.path && store.dirty) {
    if (!window.confirm("Reload it from disk and discard unsaved changes?")) {
      ui.fileSelect.value = store.path || "";
      return;
    }
    // Said no to them on purpose, so they are not offered back later.
    recovery.discard(store.path);
  }
  try {
    const payload = await api(`/api/doc?path=${encodeURIComponent(path)}`);
    captureActive();
    // Blocks for the drawings this one references, built from their ports.
    geometry.setSheets(payload.sheets);
    store.load(payload.doc, payload.path);
    const tab = findTab(payload.path);
    if (tab) tab.sheets = payload.sheets;
    else openTabs.push({ path: payload.path, sheets: payload.sheets });
    renderTabs();
    selection.clear();
    // A tool keeps state between clicks -- the wire tool holds the pin a wire
    // started from -- and cell ids repeat between drawings, so a wire begun
    // in the last drawing finished on whatever cell in this one had the same
    // id. Every drawing starts with the select tool and nothing half-done.
    setTool("select");
    ui.filePath.textContent = payload.path;
    ui.fileSelect.value = payload.path;
    syncControls();
    redraw();
    viewport.fit(store.doc.canvas.width, store.doc.canvas.height);
    inspector.render();
    drawBreadcrumb();

    if (offerRecovery(payload.path)) return;

    const problems = payload.problems || [];
    if (problems.length) {
      say(`${payload.path}: ${problems[0].where}: ${problems[0].message}`, "bad");
    } else {
      say(`opened ${payload.path}`, "good");
    }
  } catch (error) {
    say(error.message, "bad");
  }
}

async function save() {
  if (!store.doc || !store.path) return;
  // What is being written, noted before the request goes. A save takes a
  // moment, and anything typed during that moment is not in the bytes on
  // their way to disk.
  const sending = store.stamp();
  try {
    await api(`/api/doc?path=${encodeURIComponent(sending.path)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc }),
    });
    if (!store.markSaved(sending)) {
      // Either the user edited while it was in flight, or they switched
      // drawings. The file on disk is fine; what is on screen is simply
      // newer than it, so it stays marked unsaved.
      refreshStatus();
      return;
    }
    refreshStatus();
    say(`saved ${sending.path}`, "good");
    await refreshUsersOf(sending.path);
  } catch (error) {
    say(error.message, "bad");
  }
}

// ---- design rule checks ----

// Checked by Python, from the same drc.py the exporter and the command line
// use, so a drawing that passes here passes `drawlogic validate` too. The
// canvas is sent rather than the file on disk: the point is to check the
// drawing being worked on, unsaved edits included.
// How long to wait after the last edit before checking. Long enough that
// typing a name or dragging a gate is one check rather than twenty; short
// enough that it still feels like the drawing is answering back.
const LIVE_DELAY = 400;

// A check that takes longer than this has stopped being free. The checker is
// quadratic in wire segments -- 4ms on a ten-cell drawing, 17ms on twenty-two
// -- so somewhere above that it turns into a stutter every time you pause.
// Rather than let the editor feel sticky and leave the reason to be guessed
// at, live checking switches itself off and says so.
const LIVE_BUDGET = 250;

// Set while a layout is in flight; aborting it stops waiting for the answer.
let layoutAbort = null;
let liveOn = true;
let liveEra = 0;
// Why live checking is off when it turned itself off, for the status bar.
let liveOffReason = "";
let liveTimer = null;
let liveBusy = false;
let liveMarks = [];

// Checked by Python, from the same drc.py the exporter and the command line
// use, so a drawing that passes here passes `drawlogic validate` too. The
// canvas is sent rather than the file on disk: the point is to check the
// drawing being worked on, unsaved edits included.
//
// `quiet` is the live pass: it updates the panel and the canvas but says
// nothing in the status bar, because a message every time you stop typing is
// noise. Pressing Check is never quiet -- you asked, so you get an answer
// even when the answer is "nothing changed".
async function runCheck({ quiet = false } = {}) {
  if (!store.doc) return;
  if (liveBusy) {
    // One check at a time, but the drawing has moved on since this one went
    // out -- so come back rather than dropping the request. Without this the
    // last edit before a pause could be the one that never gets checked,
    // which is the one that matters.
    if (quiet) {
      window.clearTimeout(liveTimer);
      liveTimer = window.setTimeout(() => runCheck({ quiet: true }), LIVE_DELAY);
    }
    return;
  }
  liveBusy = true;
  // Which run of live mode this check belongs to. Turning live off bumps the
  // counter, so a quiet check already on its way back is recognised as
  // belonging to a mode nobody is in any more and is dropped. Clearing the
  // debounce timer cannot do this: the request has already gone.
  const era = liveEra;
  if (!quiet) ui.btnCheck.disabled = true;
  // What the document looked like when this request went out. The answer is
  // only about that version, so if anything has changed by the time it comes
  // back it is thrown away rather than shown against a drawing it never saw.
  const asked = store.stamp();
  const started = Date.now();
  try {
    const result = await api("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, source: store.path }),
    });
    if (!store.matches(asked)) return;
    // An explicit press always shows its answer; only automatic ones are
    // subject to the mode having changed underneath them.
    if (quiet && (!liveOn || era !== liveEra)) return;
    showViolations(result);

    const { errors, warnings } = result;
    if (!quiet) {
      if (!errors && !warnings) say("no design rule violations", "good");
      else say(`${errors} error(s), ${warnings} warning(s)`,
               errors ? "bad" : "warn");
    }

    const took = Date.now() - started;
    // Not while something else is running. A check that overlapped a layout
    // spent most of its time waiting behind it -- same process, one drawing's
    // worth of Python at a time -- so `took` is the measure of what else was
    // going on, not of this drawing. Turning live checking off over that
    // number, and saying so over the top of the layout's own message, is how
    // pressing Auto layout on a big drawing used to lose both at once. The
    // next quiet check measures it honestly.
    if (quiet && took > LIVE_BUDGET && !busyNow) {
      setLive(false);
      liveOffReason = "slow drawing";
      say(`this drawing takes ${took}ms to check, so live checking is off; `
          + "press Check when you want one", "warn");
    }
  } catch (error) {
    // A live check that fails says so once and stops trying. Retrying on a
    // timer against a server that is not answering would bury the reason
    // under a message every 400ms.
    if (quiet) setLive(false);
    say(error.message, "bad");
  } finally {
    liveBusy = false;
    ui.btnCheck.disabled = false;
  }
}

// An edit makes the last answer stale. Which way it goes stale depends: with
// live checking on the answer is replaced, and with it off the answer is
// withdrawn, because a stale clean bill is worse than none -- it says the
// thing you just broke is fine.
function afterEdit() {
  window.clearTimeout(liveTimer);
  if (!liveOn) {
    clearViolations();
    return;
  }
  markStale();
  liveTimer = window.setTimeout(() => runCheck({ quiet: true }), LIVE_DELAY);
}

function setLive(on) {
  const was = liveOn;
  liveOn = Boolean(on);
  liveOffReason = "";
  window.clearTimeout(liveTimer);
  // Anything automatic that is still in flight belongs to the mode being left.
  if (was !== liveOn) liveEra += 1;
  if (ui.drcLive) {
    ui.drcLive.setAttribute("aria-pressed", String(liveOn));
    ui.drcLive.textContent = liveOn ? "live" : "manual";
    ui.drcLive.title = liveOn
      ? "checking as you draw; click to check only when you press Check"
      : "checking only when you press Check; click to check as you draw";
  }
  // Remembered as a preference; the DRC panel's toggle and the Preferences
  // panel are two switches for the same thing.
  if (prefs.get("live") !== liveOn) prefs.set("live", liveOn);
  if (liveOn) afterEdit();
}

function storedLive() {
  return prefs.get("live");
}

// The count goes grey while a fresh answer is on its way, so a number on
// screen is never quietly describing a drawing that has moved on.
function markStale() {
  for (const node of [ui.drcCount, ui.statusDrc]) {
    if (node && node.textContent) node.classList.add("stale");
  }
}

function showStatusCount(errors, warnings) {
  const node = ui.statusDrc;
  if (!node) return;
  node.hidden = false;
  node.className = "status-drc " + (errors ? "bad" : (warnings ? "" : "good"));
  node.textContent = errors || warnings
    ? `DRC ${count(errors, "error")}, ${count(warnings, "warning")}`
    : "DRC clean";
}

function showViolations(result) {
  const { violations, errors, warnings } = result;
  liveMarks = violations.filter((v) => v.at)
    .map((v) => ({ level: v.level, at: v.at }));
  drawOverlay(overlayOptions);
  ui.drcCount.classList.remove("stale");
  showStatusCount(errors, warnings);
  ui.drcCount.textContent = violations.length
    ? `${count(errors, "error")}, ${count(warnings, "warning")}`
    : "clean";
  ui.drcCount.className = "drc-count " + (errors ? "bad" : "good");

  ui.drcBody.replaceChildren();
  if (!violations.length) {
    ui.drcBody.append(drcNote("Nothing to fix: the references resolve and every rule in drc.py passes."));
    return;
  }

  const list = document.createElement("ul");
  list.className = "drc-list";
  for (const violation of violations) {
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = `drc-item ${violation.level}`;
    button.title = violation.message;

    const rule = document.createElement("span");
    rule.className = "drc-rule";
    rule.textContent = violation.rule;
    const where = document.createElement("span");
    where.className = "drc-where";
    where.textContent = ` ${violation.where}`;
    button.append(rule, where);

    if (violation.at) {
      button.addEventListener("click", () => goTo(violation));
      button.addEventListener("mouseenter", () => highlight(violation));
      button.addEventListener("mouseleave", () => highlight(null));
    } else {
      button.disabled = true;
    }
    row.append(button);
    list.append(row);
  }
  ui.drcBody.append(list);
}

// Walk to a violation and ring it. The ring is drawn straight into the canvas
// rather than through the renderer: it is not part of the drawing, and the
// next redraw is exactly when it should stop being shown.
function goTo(violation) {
  const [x, y] = violation.at;
  viewport.centreOn(x, y);
  say(violation.message, violation.level === "error" ? "bad" : "warn");
  highlight(violation);
}

// Bring one violation's ring forward and leave the rest faint. Every mark is
// already on the canvas, so this is a change of emphasis rather than
// something drawn and cleared -- which is what it used to be, and why it
// disappeared on the next redraw.
function highlight(violation) {
  const key = violation && violation.at
    ? `${violation.at[0]},${violation.at[1]}` : null;
  for (const mark of liveMarks) {
    mark.active = key !== null && `${mark.at[0]},${mark.at[1]}` === key;
  }
  drawOverlay(overlayOptions);
}

// A drawing that has changed is a drawing whose last check no longer applies,
// and a stale clean bill is worse than none: it says the thing you just broke
// is fine. So an edit clears the list rather than leaving it to be misread.
function clearViolations() {
  liveMarks = [];
  drawOverlay(overlayOptions);
  if (ui.statusDrc) {
    // Said, not hidden: with no answer on screen the one thing worth knowing
    // is that the drawing has not been checked, and a count that simply
    // vanished -- or live checking that turned itself off with a message
    // that faded -- looked the same as a drawing with nothing wrong.
    ui.statusDrc.hidden = false;
    ui.statusDrc.className = "status-drc off";
    if (liveOn) ui.statusDrc.textContent = "DRC checking...";
    else if (liveOffReason) {
      ui.statusDrc.textContent = `DRC paused (${liveOffReason}) - click to check`;
    } else ui.statusDrc.textContent = "DRC not checked - click to check";
  }
  ui.drcCount.textContent = "";
  ui.drcCount.className = "drc-count";
  ui.drcBody.replaceChildren(drcNote(
    "Press Check to read the drawing back the way a reader will: wires lying "
    + "on other wires, parts too close to tell apart, names sitting on wires."));
}

function count(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function drcNote(text) {
  const note = document.createElement("p");
  note.className = "drc-note";
  note.textContent = text;
  return note;
}

async function exportSvg() {
  if (!store.doc || !store.path) return;
  const target = window.prompt("Export SVG to (relative to the served folder):",
                               store.path.replace(/\.dlg$/, ".svg"));
  if (!target) return;
  try {
    // Rendered by Python, the same code the CLI uses, so this file is
    // byte-for-byte what `drawlogic export` would produce.
    const result = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, source: store.path,
                             path: target, options: { zoom: 1 } }),
    });
    say(`exported ${result.path} (${result.bytes} bytes)`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// Ask Python for the drawing as SVG, without writing it anywhere.
async function renderedSvg() {
  return api("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc: store.doc, source: store.path,
                           options: { zoom: 1 } }),
  });
}

// Put the drawing on the clipboard as a picture, ready to paste into a slide.
// A browser that will not allow the clipboard write gets the file instead,
// which is the difference between a small annoyance and a dead button.
async function copyPng() {
  if (!store.doc) return;
  const name = `${(store.path || "drawing").replace(/\.dlg$/, "")}.png`;
  say("making a picture...");
  try {
    const blob = await picture.rasterise(await renderedSvg());
    try {
      await picture.copy(blob);
      say(`copied a ${picture.SCALE}x picture -- paste it anywhere`, "good");
    } catch (clipboardError) {
      picture.download(blob, name.split("/").pop());
      say(`clipboard refused (${clipboardError.message}); downloaded instead`,
          "good");
    }
  } catch (error) {
    say(error.message, "bad");
  }
}

// Rearrange the whole drawing from what it is wired to. Python does the work
// -- see server._layout -- so there is one implementation of it, the same way
// there is one renderer. A layout is not a gesture, so the round trip costs
// nothing, and the answer lands as a single undo step.
async function autoLayout(containerId = null) {
  if (!store.doc) return;
  if (!store.doc.cells.length) {
    say("nothing to lay out", "bad");
    return;
  }
  // Auto layout is the slowest thing the editor does, by a wide margin, and
  // the button is the one people press twice when nothing appears to happen.
  // Two or more cells selected: lay out just those, leaving the rest where
  // it is. One selected is almost always an accident, not a request.
  //
  // In a drawing with containers the parts are the containers: a selection
  // of loose cells would be pulled out of whatever boxes they sit in, so the
  // button lays out the whole drawing, and Layout contents one container.
  const nested = (store.doc.containers || []).length > 0;
  const chosen = store.doc.cells.filter((c) => selection.has(c.id)).map((c) => c.id);
  const only = !nested && !containerId && chosen.length >= 2 ? chosen : null;
  const box = containerId ? model.containerById(store.doc, containerId) : null;
  const partial = Boolean(only || box);
  const done = busy(box ? `laying out ${box.title || box.id}...`
                    : only ? `laying out ${only.length} selected cells...`
                      : "laying out...");
  const button = document.querySelector('[data-command="layout"]');
  if (button) button.disabled = true;
  // A large drawing can take a while, and waiting was the only option. The
  // server finishes its sum regardless; cancelling stops waiting for it and
  // throws the answer away, which leaves the drawing exactly as it was.
  layoutAbort = new AbortController();
  ui.btnCancel.hidden = false;
  // Which drawing asked, and which version of it. The answer is a whole
  // document that replaces what is open, so both halves matter.
  //
  // The drawing, because store.mutate hands the callback whatever is open at
  // the time it runs: without this a layout for one drawing would overwrite
  // whichever drawing had been switched to while it was computed, and the
  // next save would write it to that file.
  //
  // The version, because an answer built from the drawing as it was does not
  // contain anything done since. This used to ignore edits on the theory that
  // the layout was just another edit -- but it is not an edit, it is a
  // replacement, so a gate moved or a note added while the server was working
  // was simply gone. Undo could bring it back, if you noticed. A layout that
  // takes two seconds on a large drawing is a wide enough window to type
  // something into.
  const asked = store.stamp();
  try {
    const result = await api("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, source: asked.path,
                             options: box ? { container: box.id } : only ? { only } : {} }),
      signal: layoutAbort.signal,
    });
    if (!store.matches(asked, { edits: false })) return;
    if (!store.matches(asked)) {
      // Dropping the answer is the safe half of the trade: the layout can be
      // asked for again, and what was typed cannot.
      say("edited while laying out -- layout dropped, press it again", "bad");
      return;
    }
    store.mutate(box ? "lay out container" : only ? "lay out selection" : "auto layout", (doc) => {
      // Replacing the contents rather than the object keeps every other
      // reference to the document valid.
      for (const key of Object.keys(doc)) delete doc[key];
      Object.assign(doc, result.doc);
    });
    // A partial layout keeps its cells selected and the view where it was:
    // the point was to tidy one part of a drawing you are looking at.
    if (!partial) selection.clear();
    syncControls();
    redraw();
    inspector.render();
    if (!partial) viewport.fit(store.doc.canvas.width, store.doc.canvas.height);
    // In a drawing with containers, notes inside one move with it; only
    // the ones on the sheet itself stay where they were.
    const loose = nested ? (store.doc.shapes || []).filter((sh) => sh.parentId === undefined).length
      : result.shapes;
    const stranded = loose && !partial
      ? `; ${loose} shape(s) on the sheet stayed put and may need nudging` : "";
    say(`${result.note}${stranded}`, "good");
  } catch (error) {
    if (error.name === "AbortError") say("layout cancelled; nothing changed", "warn");
    else say(error.message, "bad");
  } finally {
    // In `finally` so a failure, a dropped answer and a success all clear it.
    layoutAbort = null;
    ui.btnCancel.hidden = true;
    done();
    if (button) button.disabled = false;
  }
}

// The palette is rebuilt rather than patched when a symbol is added, because
// it is grouped by category and a new symbol may open a new group.
function rebuildPalette() {
  buildPalette(ui.paletteBody, {
    onPick: (id) => {
      tools.place.arm(id);
      setTool("place");
      say(`click the canvas to place ${id} (shift-click to keep placing)`);
    },
  });
}

// ---- appearance ----
//
// Three states, not two: "auto" follows the operating system, and the other
// two override it. Light until someone picks otherwise: the sheet is white,
// and chrome that matches it is the calmer default. The drawing itself never changes -- the sheet is a
// document and a document is white -- so this is the chrome only, and an
// exported file looks the same whichever is picked.
const THEMES = ["auto", "light", "dark"];
const THEME_KEY = "drawlogic.theme";

function applyTheme(name) {
  const root = document.documentElement;
  if (name === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", name);
  try {
    window.localStorage.setItem(THEME_KEY, name);
  } catch (error) {
    // A browser with storage blocked still gets the theme, just not next time.
  }
}

function storedTheme() {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    return THEMES.includes(saved) ? saved : "light";
  } catch (error) {
    return "light";
  }
}


// Start a fresh drawing. It needs a name up front because saving writes to a
// path, and a drawing with nowhere to go is a drawing you lose.
// Unsaved changes to this drawing that the browser kept when the page went
// away without saving them -- see recovery.js. Taking them is one undo step,
// and leaves the drawing unsaved, because nothing is on disk until Ctrl+S.
function offerRecovery(path) {
  const entry = recovery.pending(path, store.doc);
  if (!entry) return false;
  const when = new Date(entry.savedAt).toLocaleString();
  if (!window.confirm(`${path} has unsaved changes from ${when} that were `
                      + "never saved - the page closed first.\n\n"
                      + "Restore them? (Cancel throws them away.)")) {
    recovery.discard(path);
    return false;
  }
  store.mutate("restore unsaved changes", (doc) => {
    for (const key of Object.keys(doc)) delete doc[key];
    Object.assign(doc, entry.doc);
  });
  syncControls();
  redraw();
  inspector.render();
  say(`restored unsaved changes to ${path} - save to keep them`, "warn");
  return true;
}

async function newDrawing() {

  const raw = window.prompt("Name for the new drawing:", "untitled.dlg");
  if (!raw) return;
  const name = raw.trim().replace(/\.dlg$/i, "") + ".dlg";

  try {
    const existing = [...ui.fileSelect.options].map((option) => option.value);
    const blank = model.blankDocument(name.replace(/\.dlg$/i, ""));

    // `create: true` means "only if it is not there". The server answers 409
    // if it is, because only the server knows what a name resolves to: this
    // list holds exact spellings, and "./sheet.dlg" is a different string
    // from "sheet.dlg" while being the same file. Matching names here let
    // an equivalent spelling past the warning and overwrite the drawing.
    const write = (create) => api(
      `/api/doc?path=${encodeURIComponent(name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc: blank, create }),
      });

    try {
      await write(true);
    } catch (conflict) {
      if (!/already exists/i.test(conflict.message)) throw conflict;
      if (!window.confirm(`${name} already exists. Overwrite it?`)) return;
      await write(false);
    }

    if (!existing.includes(name)) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      ui.fileSelect.appendChild(option);
    }
    ui.fileSelect.value = name;
    await openDrawing(name);
    say(`created ${name}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// A drawing from anywhere on this computer. The server only reads and writes
// inside the folder it serves -- that is its security boundary -- so the file
// is read here, copied into that folder under its own name, and opened from
// there like any other. Asks before replacing a drawing of the same name.
async function openFromDisk(file) {
  let doc;
  try {
    doc = JSON.parse(await file.text());
  } catch (error) {
    say(`${file.name} is not a drawing: ${error.message}`, "bad");
    return;
  }
  if (!doc || typeof doc !== "object" || !Array.isArray(doc.cells)
      || !Array.isArray(doc.nets)) {
    say(`${file.name} is not a drawing: it has no cells and nets`, "bad");
    return;
  }
  const name = file.name.replace(/\.dlg$/i, "") + ".dlg";

  try {
    const write = (create) => api(
      `/api/doc?path=${encodeURIComponent(name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc, create }),
      });
    try {
      await write(true);
    } catch (conflict) {
      if (!/already exists/i.test(conflict.message)) throw conflict;
      if (!window.confirm(`${name} already exists in this folder. Replace it `
          + "with the one you picked? If it is open, unsaved changes to it "
          + "are lost.")) return;
      await write(false);
    }

    // A tab still showing the old copy would put it back on the next save.
    const tab = findTab(name);
    if (tab) {
      if (store.path === name) store.markSaved();
      else openTabs.splice(openTabs.indexOf(tab), 1);
      recovery.discard(name);
    }
    if (![...ui.fileSelect.options].some((option) => option.value === name)) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      ui.fileSelect.appendChild(option);
    }
    ui.fileSelect.value = name;
    await openDrawing(name);
    say(`opened ${file.name}, copied into this folder as ${name}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// Turn the open drawing into a symbol the palette offers.
//
// There is no separate symbol editor, because a symbol is very nearly a
// drawing already: the shapes are the artwork and the ports say where the
// pins go. So it is made with the tools that are already here, and this is
// the one command that converts it. The same rule hierarchy uses -- a
// drawing's ports are the pins of the block standing for it -- one level down.
async function saveAsSymbol() {
  if (!store.doc) return;
  const suggested = (store.doc.title || "my_symbol")
    .replace(/[^A-Za-z0-9_]/g, "_").replace(/^[^A-Za-z]+/, "") || "my_symbol";
  const id = window.prompt(
    "Save this drawing as a symbol.\n\n"
    + "Its shapes become the artwork and its ports become the pins.\n"
    + "Symbol id (letters, digits and underscores):", suggested);
  if (!id) return;

  try {
    const result = await api("/api/symbol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, id, name: store.doc.title }),
    });
    geometry.setLibrary(result.symbols);
    rebuildPalette();
    say(`${result.id} is in the palette now, and in this folder's symbols.json`,
        "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// A netlist becomes one drawing per module, written beside the others, and
// the top one opens. The server does the reading and the layout; all this
// has to settle is what happens to drawings already there.
async function importVerilog(file) {
  const text = await file.text();
  const send = async (overwrite) => {
    const done = busy(`drawing the modules in ${file.name}...`);
    try {
      return await api("/api/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, overwrite }),
      });
    } finally {
      done();
    }
  };

  try {
    let result;
    try {
      result = await send(false);
    } catch (conflict) {
      if (!/^would overwrite/i.test(conflict.message)) throw conflict;
      const names = conflict.message.replace(/^would overwrite /i, "");
      if (!window.confirm(`Importing ${file.name} would replace ${names}.\n\n`
          + "Replace them? Any of them open in a tab is closed first, and "
          + "unsaved changes to it are lost.")) return;
      result = await send(true);
    }

    // A tab showing a drawing that was just replaced would show the old one,
    // and saving it would put the old one back. Such tabs go; the drawing in
    // front is dropped once the top one has taken its place.
    const listed = [...ui.fileSelect.options].map((option) => option.value);
    const stale = store.path && result.written.includes(store.path)
      && store.path !== result.top ? store.path : null;
    for (const name of result.written) {
      const tab = findTab(name);
      if (tab && name !== store.path) {
        openTabs.splice(openTabs.indexOf(tab), 1);
        recovery.discard(name);
      }
      if (!listed.includes(name)) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        ui.fileSelect.appendChild(option);
      }
    }
    // Already agreed to lose its changes above, so reopening it from disk
    // should not ask a second time; the file now holds what is wanted.
    if (result.top === store.path) store.markSaved();
    await openDrawing(result.top);
    if (stale && findTab(stale)) {
      openTabs.splice(openTabs.indexOf(findTab(stale)), 1);
      recovery.discard(stale);
      renderTabs();
    }

    const count = result.written.length;
    // "note: ..." says how it was drawn (through Yosys, say); the rest are
    // things the drawing leaves out.
    const notes = result.warnings.filter((w) => w.startsWith("note: "))
      .map((w) => w.slice(6).split(":")[0]);
    const warnings = result.warnings.filter((w) => !w.startsWith("note: "));
    say(`${count} drawing${count === 1 ? "" : "s"} from ${file.name}`
        + (notes.length ? ` (${notes.join("; ")})` : "")
        + (warnings.length ? `; ${warnings.length} things in it are not drawn`
          : ""), warnings.length ? "warn" : "good");
    if (warnings.length) {
      // Each is something in the Verilog the drawing does not show, which
      // someone reading the drawing would otherwise never find out.
      const shown = warnings.slice(0, 15);
      const more = warnings.length - shown.length;
      window.alert(`Not drawn, or drawn differently:\n\n${shown.join("\n")}`
        + (more ? `\n\n...and ${more} more; \`drawlogic import\` lists them all.` : ""));
    }
  } catch (error) {
    say(error.message, "bad");
  }
}

function syncControls() {
  const canvas = store.doc.canvas || {};
  ui.gridSelect.value = (canvas.grid || {}).style || "dots";
  const fontScale = Math.round((Number((canvas.font || {}).scale) || 1) * 100);
  ui.fontSlider.value = fontScale;
  ui.fontValue.value = `${fontScale}%`;
  const symbolScale = Math.round((Number(canvas.symbolScale) || 1) * 100);
  ui.symbolSlider.value = symbolScale;
  ui.symbolValue.value = `${symbolScale}%`;
}

// ---- controls ----

function bindControls() {
  ui.gridSelect.addEventListener("change", () => {
    store.mutate("grid", (doc) => { doc.canvas.grid.style = ui.gridSelect.value; });
    redraw();
  });

  ui.zoomSlider.addEventListener("input",
                                 () => viewport.setZoom(Number(ui.zoomSlider.value) / 100));
  ui.btnFit.addEventListener("click",
                             () => viewport.fit(store.doc.canvas.width, store.doc.canvas.height));

  // One drag of a slider is one undo step. "input" fires per tick and each
  // was its own snapshot, so undoing a drag took dozens of Ctrl+Z; "change"
  // fires once, on release, and closes the gesture the first tick opened.
  const slider = (element, label, apply) => {
    let sliding = false;
    element.addEventListener("input", () => {
      if (!sliding) {
        // disabled
        sliding = true;
      }
      apply(Number(element.value));
      redraw();
    });
    element.addEventListener("change", () => {
      store.endGesture();
      sliding = false;
    });
  };

  slider(ui.fontSlider, "text size", (value) => {
    ui.fontValue.value = `${value}%`;
    store.mutate("text size", (doc) => { doc.canvas.font.scale = value / 100; });
  });

  slider(ui.symbolSlider, "symbol size", (value) => {
    ui.symbolValue.value = `${value}%`;
    store.mutate("symbol size", (doc) => { doc.canvas.symbolScale = value / 100; });
  });

  ui.fileSelect.addEventListener("change", () => {
    // Picking a file outright is not drilling in, so the trail is over.
    trail.length = 0;
    openDrawing(ui.fileSelect.value);
  });
  ui.btnSave.addEventListener("click", save);
  ui.btnExport.addEventListener("click", exportSvg);
  ui.btnPng.addEventListener("click", copyPng);
  ui.btnCheck.addEventListener("click", () => runCheck());
  ui.drcLive.addEventListener("click", () => setLive(!liveOn));
  ui.statusKeys.addEventListener("click", toggleShortcuts);
  ui.btnPrefs.addEventListener("click", openPrefs);
  ui.btnPainter.addEventListener("click", startPainter);
  prefs.subscribe((key, value) => {
    if (key === "live" && value !== liveOn) setLive(value);
  });
  ui.btnCancel.addEventListener("click", () => {
    if (layoutAbort) layoutAbort.abort();
  });
  ui.statusDrc.addEventListener("click", () => {
    // With no answer showing, the useful thing to do is get one.
    if (ui.statusDrc.classList.contains("off")) runCheck();
    ui.drcBody.scrollIntoView({ block: "nearest" });
  });
  ui.btnNew.addEventListener("click", newDrawing);
  ui.btnOpen.addEventListener("click", () => ui.openFile.click());
  ui.openFile.addEventListener("change", () => {
    const file = ui.openFile.files[0];
    ui.openFile.value = "";
    if (file) openFromDisk(file);
  });
  ui.btnSymbol.addEventListener("click", saveAsSymbol);
  ui.btnImport.addEventListener("click", () => ui.importFile.click());
  ui.importFile.addEventListener("change", () => {
    const file = ui.importFile.files[0];
    // Cleared so choosing the same file again still counts as a change.
    ui.importFile.value = "";
    if (file) importVerilog(file);
  });
  ui.undo.addEventListener("click", () => stepHistory(true));
  ui.redo.addEventListener("click", () => stepHistory(false));

  for (const button of document.querySelectorAll("[data-tool]")) {
    button.addEventListener("click", () => {
      const name = button.getAttribute("data-tool");
      const shape = button.getAttribute("data-shape");
      if (shape) tools.shape.arm(shape, button.getAttribute("data-preset"));
      setTool(name);
      clearPaletteSelection(ui.paletteBody);
    });
  }

  for (const button of document.querySelectorAll("[data-command]")) {
    button.addEventListener("click",
                            () => runCommand(button.getAttribute("data-command")));
  }

  // Read as each menu opens, not kept up to date on every selection change:
  // nobody sees the items until then.
  bindMenus(document, {
    beforeOpen: (panel) => {
      for (const item of panel.querySelectorAll("[data-min]")) {
        item.disabled = selection.size < Number(item.getAttribute("data-min"));
      }
      // The container commands that need a container, or something in one.
      const chosen = selection.items();
      for (const item of panel.querySelectorAll("[data-needs]")) {
        const needs = item.getAttribute("data-needs");
        if (needs === "container") item.disabled = !chosen.some(model.isContainer);
        if (needs === "inside") item.disabled = !chosen.some((i) => i.parentId !== undefined);
        if (needs === "instance") item.disabled = !(chosen.length === 1 && chosen[0].ref);
        if (needs === "containers") {
          item.disabled = !chosen.length
            || (!model.containerChoices(store.doc, selection.ids).length
                && model.sharedContainer(store.doc, selection.ids) === null);
        }
      }
    },
  });

}

function bindKeyboard() {
  window.addEventListener("keydown", (event) => {
    if (ui.prefsDialog.open) return;
    if ((event.ctrlKey || event.metaKey) && event.key === ",") {
      event.preventDefault();
      openPrefs();
      return;
    }
    // While the list is open, keys belong to it: Esc closes it natively, and
    // ? toggles it, but nothing reaches the drawing underneath.
    if (ui.shortcuts.open) {
      if (event.key === "?") {
        event.preventDefault();
        ui.shortcuts.close();
      }
      return;
    }
    if (event.target.matches("input, select, textarea")) return;
    const mod = event.ctrlKey || event.metaKey;

    if (event.key === "?" && !mod) {
      event.preventDefault();
      toggleShortcuts();
      return;
    }

    if (mod) {
      const handlers = {
        s: save,
        // Shift makes it a picture. Ctrl+P is left alone: printing to PDF
        // from the browser is the way to get a PDF out of drawlogic.
        e: () => (event.shiftKey ? copyPng() : exportSvg()),
        n: () => newDrawing(),
        z: () => stepHistory(!event.shiftKey),
        y: () => stepHistory(false),
        a: () => { selection.selectAll(); redraw(); inspector.render(); },
        c: () => {
          if (!event.shiftKey) return copySelection(false);
          copiedStyle = styleOfSelection();
          if (copiedStyle) say("style copied; Ctrl+Shift+V gives it to the selection");
        },
        x: () => copySelection(true),
        v: () => (event.shiftKey ? pasteStyle(selection.ids, copiedStyle) : paste()),
        d: () => {
          if (!selection.size) return;
          clipboard = model.copyItems(store.doc, selection.ids);
          paste();
        },
        g: () => runCommand(event.shiftKey ? "ungroup" : "group"),
        r: () => runCommand(event.shiftKey ? "rotate-ccw" : "rotate-cw"),
        h: () => runCommand(event.shiftKey ? "flip-v" : "flip-h"),
        "]": () => runCommand("front"),
        "[": () => runCommand("back"),
        "0": () => viewport.fit(store.doc.canvas.width, store.doc.canvas.height),
      };
      const handler = handlers[event.key.toLowerCase()];
      if (handler) {
        event.preventDefault();
        handler();
      }
      return;
    }

    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelection();
    } else if (event.key === "Escape" && painting) {
      setPainting(false);
    } else if (event.key === "Escape" && layoutAbort) {
      layoutAbort.abort();
    } else if (event.key === "Escape") {
      const tool = tools[activeTool];
      if (activeTool === "shape" && tools.shape.polygon) tools.shape.finishPolygon();
      else if (tool && tool.reset) tool.reset();
      selection.clear();
      setTool("select");
      clearPaletteSelection(ui.paletteBody);
      redraw();
      inspector.render();
    } else if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      const delta = {
        ArrowLeft: [-1, 0], ArrowRight: [1, 0],
        ArrowUp: [0, -1], ArrowDown: [0, 1],
      }[event.key];
      nudge(delta[0], delta[1], event.shiftKey);
    } else {
      const shapes = { l: "line", b: "rect", p: "polygon", t: "text" };
      const key = event.key.toLowerCase();
      if (key === "f") zoomToSelection();
      else if (key === "v") setTool("select");
      else if (key === "w") setTool("wire");
      else if (key === "e") setTool("erase");
      else if (shapes[key]) {
        tools.shape.arm(shapes[key]);
        setTool("shape");
      }
    }
  });

  // Saving is manual, so the one thing done automatically is refusing to let
  // the tab close on unsaved work.
  window.addEventListener("beforeunload", (event) => {
    const anyDirty = store.dirty
      || openTabs.some((tab) => tab.path !== store.path && tab.dirty);
    if (!anyDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

// F: fill the view with what is selected, or with the sheet if nothing is.
// Ctrl+0 only ever fitted the whole sheet, which on a big drawing leaves the
// part you are working on a few pixels high.
function zoomToSelection() {
  const box = selection.size ? model.boundsOfIds(store.doc, selection.ids) : null;
  // At most 200%: filling the view with one small port is not "showing the
  // selection", it is losing where it is.
  if (box && box[2] + box[3] > 0) viewport.fitBox(box[0], box[1], box[2], box[3], 120, 2);
  else viewport.fit(store.doc.canvas.width, store.doc.canvas.height);
}

function openPrefs() {
  const body = $("prefs-body");
  const rows = prefs.PREFS.map((pref) => {
    const label = document.createElement("label");
    label.className = "pref-row";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = prefs.get(pref.key);
    box.addEventListener("change", () => prefs.set(pref.key, box.checked));
    const text = document.createElement("span");
    text.className = "pref-text";
    const name = document.createElement("strong");
    name.textContent = pref.label;
    text.append(name);
    if (pref.risk) {
      const tag = document.createElement("em");
      tag.className = "pref-risk";
      tag.textContent = "changes the drawing";
      text.append(" ", tag);
    }
    const help = document.createElement("small");
    help.textContent = pref.help;
    text.append(help);
    label.append(box, text);
    return label;
  });

  // Appearance was a button of its own that cycled blind through three
  // states; it is a choice made once, so it is a row here with all three in
  // view. Kept under its own storage key, as before.
  const appearance = document.createElement("label");
  appearance.className = "pref-row";
  const text = document.createElement("span");
  text.className = "pref-text";
  const name = document.createElement("strong");
  name.textContent = "Appearance";
  const help = document.createElement("small");
  help.textContent = "The editor around the sheet. The sheet, and every export, stays white.";
  text.append(name, help);
  const choice = document.createElement("select");
  for (const [value, label] of [["auto", "Follow the system"], ["light", "Light"],
                                ["dark", "Dark"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    choice.appendChild(option);
  }
  choice.value = storedTheme();
  choice.addEventListener("change", () => applyTheme(choice.value));
  appearance.append(text, choice);

  body.replaceChildren(appearance, ...rows);
  ui.prefsDialog.showModal();
}

function toggleShortcuts() {
  if (ui.shortcuts.open) {
    ui.shortcuts.close();
    return;
  }
  shortcuts.fill($("shortcuts-body"));
  ui.shortcuts.showModal();
}

// ---- start ----

async function start() {
  // First: everything below may ask a preference.
  prefs.load();
  Object.assign(ui, {
    canvas: $("canvas"),
    fileSelect: $("file-select"),
    filePath: $("file-path"),
    dirty: $("dirty"),
    btnSave: $("btn-save"),
    btnExport: $("btn-export"),
    btnPng: $("btn-png"),
    btnSymbol: $("btn-symbol"),
    btnImport: $("btn-import"),
    btnOpen: $("btn-open"),
    openFile: $("open-file"),
    importFile: $("import-file"),
    breadcrumb: $("breadcrumb"),
    btnFit: $("btn-fit"),
    shortcuts: $("shortcuts"),
    prefsDialog: $("prefs-dialog"),
    choiceDialog: $("choice-dialog"),
    containerDialog: $("container-dialog"),
    styleDialog: $("style-dialog"),
    formDialog: $("form-dialog"),
    tabs: $("tabs"),
    btnPrefs: $("btn-prefs"),
    btnPainter: $("btn-painter"),
    btnCancel: $("btn-cancel"),
    statusKeys: $("status-keys"),
    undo: $("btn-undo"),
    redo: $("btn-redo"),
    gridSelect: $("grid-select"),
    zoomSlider: $("zoom-slider"),
    zoomValue: $("zoom-value"),
    fontSlider: $("font-slider"),
    fontValue: $("font-value"),
    symbolSlider: $("symbol-slider"),
    symbolValue: $("symbol-value"),
    paletteBody: $("palette-body"),
    counts: $("status-counts"),
    cursor: $("status-cursor"),
    message: $("status-message"),
    toast: $("toast"),
    btnNew: $("btn-new"),
    btnCheck: $("btn-check"),
    drcBody: $("drc-body"),
    drcCount: $("drc-count"),
    drcLive: $("drc-live"),
    statusDrc: $("status-drc"),
  });

  applyTheme(storedTheme());

  // The viewport and the select tool listen on the same element, so the one
  // rule about what a press landed on has to be the same rule for both.
  viewport = new Viewport(ui.canvas, (view) => {
    const percent = Math.round(view.zoom * 100);
    ui.zoomSlider.value = Math.min(400, Math.max(10, percent));
    ui.zoomValue.value = `${percent}%`;
    drawOverlay(overlayOptions);
  }, (event) => !onSomething(event)
    // A Shift-drag on empty sheet pans only with the select tool, as the
    // canvas's own handler assumes. With a shape tool in hand, Shift is what
    // makes the shape square or the line straight, and panning there took the
    // drag away from the tool: the shape came out at its smallest size.
    // The middle button pans with any tool.
    && (event.button !== 0 || activeTool === "select"));

  tools = makeTools(context);
  inspector = new Inspector($("properties-body"), store, selection, () => redraw(),
                            (message) => say(message, "bad"));
  inspector.onOpenRef = (cell) => drillInto(cell);
  inspector.onCommand = (command) => runCommand(command);
  selection.subscribe(() => refreshStatus());
  // Anything that changes the drawing makes the last check stale, and a stale
  // clean bill is worse than none: it says the thing just broken is fine.
  // Saving is the one thing that changes nothing on the canvas.
  store.subscribe((_store, reason) => {
    if (reason !== "saved") afterEdit();
  });
  // The dot on a tab follows the drawing's unsaved flag. Redrawn only when
  // that flag changes, not on every pointer move of a drag.
  let shownDirty = null;
  store.subscribe((_store, reason) => {
    if (reason === "load" || reason === "saved" || store.dirty !== shownDirty) {
      shownDirty = store.dirty;
      renderTabs();
    }
  });
  recovery.watch(store, () => say(
    "this drawing is too big for the browser to keep a recovery copy of; "
    + "save often", "warn"));

  try {
    const [theme, library, listing, drcLimits] = await Promise.all([
      api("/api/theme"), api("/api/symbols"), api("/api/files"),
      api("/api/drc"),
    ]);
    render.setTheme(theme);
    model.setContainerDefaults(theme.container);
    routing.setLimits(drcLimits);
    geometry.setLibrary(library);
    rebuildPalette();

    for (const file of listing.files) {
      const option = document.createElement("option");
      option.value = file;
      option.textContent = file;
      ui.fileSelect.appendChild(option);
    }

    setLive(storedLive());
    clearViolations();
    bindControls();
    bindCanvas();
    bindKeyboard();
    setTool("select");

    const requested = new URLSearchParams(window.location.search).get("open");
    const first = requested || listing.files[0];
    if (first) await openDrawing(first);
    else say("no .dlg files found in the served folder", "bad");
  } catch (error) {
    say(error.message, "bad");
  }
}

start();
