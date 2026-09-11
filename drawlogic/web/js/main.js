// Boots the editor and wires the pieces together.

import * as actions from "./actions.js";
import { Properties } from "./properties.js";
import * as render from "./render.js";
import { Selection, drawHandles } from "./selection.js";
import { Store } from "./store.js";
import * as symbols from "./symbols.js";
import { PlaceTool } from "./tools/place.js";
import { SelectTool } from "./tools/select.js";
import { WireTool } from "./tools/wire.js";
import { Viewport } from "./viewport.js";

const store = new Store();
const selection = new Selection(store);
const ui = {};

let viewport = null;
let properties = null;
let tools = {};
let activeTool = "select";
let clipboard = null;
let lastOverlayOptions = {};

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

function say(message, kind) {
  ui.message.textContent = message;
  ui.message.className = "push" + (kind ? ` ${kind}` : "");
}

// ---- drawing ----

function drawOverlay(options) {
  lastOverlayOptions = options || {};
  if (!store.doc) return;
  drawHandles(ui.canvas, selection, viewport.zoom, lastOverlayOptions);
}

function redraw() {
  if (!store.doc) return;
  render.render(ui.canvas, store.doc);
  drawOverlay(lastOverlayOptions);
  refreshStatus();
}

function refreshStatus() {
  const doc = store.doc;
  if (!doc) return;
  ui.counts.textContent =
    `${doc.cells.length} cells | ${doc.nets.length} nets`
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
};

function setTool(name) {
  const previous = tools[activeTool];
  if (previous && previous.onDeactivate) previous.onDeactivate();
  activeTool = name;
  for (const button of document.querySelectorAll("[data-tool]")) {
    button.setAttribute("aria-pressed",
                        String(button.getAttribute("data-tool") === name));
  }
  const tool = tools[name];
  if (tool && tool.onActivate) tool.onActivate();
  else drawOverlay({});
  ui.canvas.style.cursor = name === "wire" ? "crosshair" : "default";
}

function bindCanvas() {
  const canvas = ui.canvas;

  canvas.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    if (event.shiftKey && activeTool === "select"
        && !event.target.closest(".dl-cell")
        && !event.target.closest("[data-handle]")) {
      return; // shift-drag on empty space pans, handled by the viewport
    }
    if (viewport.spaceHeld) return;
    const tool = tools[activeTool];
    if (tool && tool.onPointerDown) {
      tool.onPointerDown(event, viewport.toDoc(event.clientX, event.clientY));
      redraw();
      properties.render();
    }
  });

  window.addEventListener("mousemove", (event) => {
    if (!store.doc) return;
    const point = viewport.toDoc(event.clientX, event.clientY);
    ui.cursor.textContent = `x ${Math.round(point[0])} y ${Math.round(point[1])}`;

    const tool = tools[activeTool];
    if (tool && tool.onPointerMove && tool.onPointerMove(event, point)) {
      redraw();
    }
    if (activeTool === "select" && tool.cursorFor) {
      canvas.style.cursor = viewport.spaceHeld ? "grab" : tool.cursorFor(event.target);
    }
  });

  window.addEventListener("mouseup", (event) => {
    const tool = tools[activeTool];
    if (tool && tool.onPointerUp) {
      const changed = tool.onPointerUp(event, viewport.toDoc(event.clientX, event.clientY));
      if (changed) redraw();
      properties.render();
      refreshStatus();
    }
  });
}

// ---- commands ----

function withSelection(label, change) {
  if (!selection.size) return;
  store.mutate(label, (doc) => change(doc, selection.ids));
  redraw();
  properties.render();
}

function deleteSelection() {
  if (!selection.size) return;
  const ids = new Set(selection.ids);
  store.mutate("delete", (doc) => actions.deleteCells(doc, ids));
  selection.clear();
  redraw();
  properties.render();
  say(`deleted ${ids.size} cell(s)`);
}

function copySelection(cut) {
  if (!selection.size) return;
  clipboard = actions.copyCells(store.doc, selection.ids);
  say(`${cut ? "cut" : "copied"} ${clipboard.cells.length} cell(s)`);
  if (cut) deleteSelection();
}

function paste() {
  if (!clipboard || !clipboard.cells.length) return;
  const step = actions.gridStep(store.doc);
  const added = store.mutate("paste",
                             (doc) => actions.pasteCells(doc, clipboard, step * 2, step * 2));
  if (added) {
    selection.set(added);
    redraw();
    properties.render();
    say(`pasted ${added.length} cell(s)`);
  }
}

function nudge(dx, dy, big) {
  if (!selection.size) return;
  const step = actions.gridStep(store.doc) * (big ? 10 : 1);
  withSelection("nudge",
                (doc, ids) => actions.moveCells(doc, ids, dx * step, dy * step));
}

function undo() {
  const label = store.undo();
  if (label === false) return;
  // Cells may have vanished, so drop anything selected that no longer exists.
  const alive = new Set(store.doc.cells.map((c) => c.id));
  selection.set([...selection.ids].filter((id) => alive.has(id)));
  redraw();
  properties.render();
  say(`undid ${label}`);
}

function redo() {
  const label = store.redo();
  if (label === false) return;
  const alive = new Set(store.doc.cells.map((c) => c.id));
  selection.set([...selection.ids].filter((id) => alive.has(id)));
  redraw();
  properties.render();
  say(`redid ${label}`);
}

// ---- files ----

async function openDrawing(path) {
  if (store.dirty && !window.confirm("Discard unsaved changes?")) {
    ui.fileSelect.value = store.path || "";
    return;
  }
  try {
    const payload = await api(`/api/doc?path=${encodeURIComponent(path)}`);
    store.load(payload.doc, payload.path);
    selection.clear();
    ui.filePath.textContent = payload.path;
    ui.fileSelect.value = payload.path;
    syncControls();
    redraw();
    viewport.fit(store.doc.canvas.width, store.doc.canvas.height);
    properties.render();
    say(`opened ${payload.path}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

async function save() {
  if (!store.doc || !store.path) return;
  try {
    await api(`/api/doc?path=${encodeURIComponent(store.path)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc }),
    });
    store.markSaved();
    refreshStatus();
    say(`saved ${store.path}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

async function exportSvg() {
  if (!store.doc || !store.path) return;
  const target = window.prompt("Export SVG to (relative to the served folder):",
                               store.path.replace(/\.dlg$/, ".svg"));
  if (!target) return;
  try {
    const result = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: store.doc, path: target, options: { zoom: 1 } }),
    });
    say(`exported ${result.path} (${result.bytes} bytes)`, "good");
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

// ---- palette ----

function buildPalette() {
  const groups = symbols.byCategory();
  ui.paletteBody.textContent = "";

  for (const category of Object.keys(groups).sort()) {
    const heading = document.createElement("div");
    heading.className = "palette-category";
    heading.textContent = category;
    ui.paletteBody.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "palette-grid";
    for (const id of groups[category]) {
      const symbol = symbols.get(id);
      const item = document.createElement("button");
      item.className = "palette-item";
      item.type = "button";
      item.title = `${symbol.name} (${id}) - click, then click the canvas`;
      item.appendChild(render.symbolThumbnail(symbol));
      item.addEventListener("click", () => {
        tools.place.arm(id);
        setTool("place");
        for (const other of document.querySelectorAll(".palette-item")) {
          other.classList.toggle("armed", other === item);
        }
        say(`click the canvas to place ${id} (shift-click to keep placing)`);
      });
      grid.appendChild(item);
    }
    ui.paletteBody.appendChild(grid);
  }
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

  ui.fontSlider.addEventListener("input", () => {
    const value = Number(ui.fontSlider.value);
    ui.fontValue.value = `${value}%`;
    store.mutate("text size", (doc) => { doc.canvas.font.scale = value / 100; });
    redraw();
  });

  ui.symbolSlider.addEventListener("input", () => {
    const value = Number(ui.symbolSlider.value);
    ui.symbolValue.value = `${value}%`;
    store.mutate("symbol size", (doc) => { doc.canvas.symbolScale = value / 100; });
    redraw();
  });

  ui.fileSelect.addEventListener("change", () => openDrawing(ui.fileSelect.value));
  ui.btnSave.addEventListener("click", save);
  ui.btnExport.addEventListener("click", exportSvg);
  ui.undo.addEventListener("click", undo);
  ui.redo.addEventListener("click", redo);

  for (const button of document.querySelectorAll("[data-tool]")) {
    button.addEventListener("click", () => {
      setTool(button.getAttribute("data-tool"));
      for (const item of document.querySelectorAll(".palette-item")) {
        item.classList.remove("armed");
      }
    });
  }

  for (const button of document.querySelectorAll("[data-command]")) {
    button.addEventListener("click", () => runCommand(button.getAttribute("data-command")));
  }
}

function runCommand(command) {
  switch (command) {
    case "rotate-cw":
      withSelection("rotate", (doc, ids) => actions.rotateCells(doc, ids, 90));
      break;
    case "rotate-ccw":
      withSelection("rotate", (doc, ids) => actions.rotateCells(doc, ids, -90));
      break;
    case "flip-h":
      withSelection("flip", (doc, ids) => actions.flipCells(doc, ids, false));
      break;
    case "flip-v":
      withSelection("flip", (doc, ids) => actions.flipCells(doc, ids, true));
      break;
    case "group":
      if (selection.size > 1) {
        withSelection("group", (doc, ids) => actions.groupCells(doc, ids));
        say(`grouped ${selection.size} cells`);
      }
      break;
    case "ungroup":
      withSelection("ungroup", (doc, ids) => actions.ungroupCells(doc, ids));
      say("ungrouped");
      break;
    case "delete":
      deleteSelection();
      break;
    default:
      break;
  }
}

function bindKeyboard() {
  window.addEventListener("keydown", (event) => {
    const typing = event.target.matches("input, select, textarea");
    if (typing) return;

    const mod = event.ctrlKey || event.metaKey;

    if (mod) {
      const key = event.key.toLowerCase();
      const handlers = {
        s: save,
        e: exportSvg,
        z: () => (event.shiftKey ? redo() : undo()),
        y: redo,
        a: () => { selection.selectAll(); redraw(); properties.render(); },
        c: () => copySelection(false),
        x: () => copySelection(true),
        v: paste,
        d: () => {
          if (!selection.size) return;
          const clip = actions.copyCells(store.doc, selection.ids);
          const step = actions.gridStep(store.doc);
          const added = store.mutate("duplicate",
                                     (doc) => actions.pasteCells(doc, clip, step * 2, step * 2));
          if (added) { selection.set(added); redraw(); properties.render(); }
        },
        g: () => runCommand(event.shiftKey ? "ungroup" : "group"),
        r: () => runCommand(event.shiftKey ? "rotate-ccw" : "rotate-cw"),
        h: () => runCommand(event.shiftKey ? "flip-v" : "flip-h"),
        "0": () => viewport.fit(store.doc.canvas.width, store.doc.canvas.height),
      };
      const handler = handlers[key];
      if (handler) {
        event.preventDefault();
        handler();
      }
      return;
    }

    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelection();
    } else if (event.key === "Escape") {
      const tool = tools[activeTool];
      if (tool && tool.reset) tool.reset();
      selection.clear();
      setTool("select");
      redraw();
      properties.render();
    } else if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      const deltas = {
        ArrowLeft: [-1, 0], ArrowRight: [1, 0],
        ArrowUp: [0, -1], ArrowDown: [0, 1],
      }[event.key];
      nudge(deltas[0], deltas[1], event.shiftKey);
    } else {
      const shortcuts = { v: "select", w: "wire" };
      const name = shortcuts[event.key.toLowerCase()];
      if (name) setTool(name);
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!store.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

// ---- start ----

async function start() {
  Object.assign(ui, {
    canvas: $("canvas"),
    fileSelect: $("file-select"),
    filePath: $("file-path"),
    dirty: $("dirty"),
    btnSave: $("btn-save"),
    btnExport: $("btn-export"),
    btnFit: $("btn-fit"),
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
    propertiesBody: $("properties-body"),
    counts: $("status-counts"),
    cursor: $("status-cursor"),
    message: $("status-message"),
  });

  viewport = new Viewport(ui.canvas, (view) => {
    const percent = Math.round(view.zoom * 100);
    ui.zoomSlider.value = Math.min(400, Math.max(10, percent));
    ui.zoomValue.value = `${percent}%`;
    drawOverlay(lastOverlayOptions);
  });

  tools = {
    select: new SelectTool(context),
    wire: new WireTool(context),
    place: new PlaceTool(context),
  };

  properties = new Properties($("properties-body"), store, selection, () => redraw());
  selection.subscribe(() => { refreshStatus(); });

  try {
    const [theme, library, listing] = await Promise.all([
      api("/api/theme"), api("/api/symbols"), api("/api/files"),
    ]);
    render.setTheme(theme);
    symbols.setLibrary(library);
    buildPalette();

    for (const file of listing.files) {
      const option = document.createElement("option");
      option.value = file;
      option.textContent = file;
      ui.fileSelect.appendChild(option);
    }

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
