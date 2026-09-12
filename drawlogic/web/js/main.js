// Boots the editor and wires the pieces together.
//
// Usage: loaded by index.html as a module. Talks to the server over
// /api/theme, /api/symbols, /api/files, /api/doc and /api/export.

import * as geometry from "./geometry.js";
import * as model from "./model.js";
import { Inspector, buildPalette, clearPaletteSelection } from "./panels.js";
import * as picture from "./picture.js";
import * as render from "./render.js";
import { Selection, drawHandles } from "./selection.js";
import { makeTools } from "./tools.js";
import { Viewport } from "./viewport.js";

const store = new model.Store();
const selection = new Selection(store);
const ui = {};

let viewport = null;
let inspector = null;
let tools = {};
let activeTool = "select";
let clipboard = null;
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

function say(message, kind) {
  ui.message.textContent = message;
  ui.message.className = "push" + (kind ? ` ${kind}` : "");
}

// ---- drawing ----

function drawOverlay(options) {
  overlayOptions = options || {};
  if (!store.doc) return;
  drawHandles(ui.canvas, selection, viewport.zoom, overlayOptions);
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
  ui.canvas.style.cursor = tool && tool.cursorFor ? tool.cursorFor(null) : "default";
}

function bindCanvas() {
  ui.canvas.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || viewport.spaceHeld) return;
    if (event.shiftKey && activeTool === "select"
        && !event.target.closest(".dl-cell, .dl-shape, .dl-net, [data-handle]")) {
      return; // shift-drag on empty space pans, handled by the viewport
    }
    const tool = tools[activeTool];
    if (tool && tool.onPointerDown) {
      tool.onPointerDown(event, viewport.toDoc(event.clientX, event.clientY));
      redraw();
      inspector.render();
    }
  });

  ui.canvas.addEventListener("dblclick", () => {
    if (activeTool === "shape" && tools.shape.polygon) {
      tools.shape.finishPolygon();
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
      ui.canvas.style.cursor = viewport.spaceHeld ? "grab" : tool.cursorFor(event.target);
    }
  });

  window.addEventListener("mouseup", (event) => {
    const tool = tools[activeTool];
    if (tool && tool.onPointerUp) {
      if (tool.onPointerUp(event, viewport.toDoc(event.clientX, event.clientY))) {
        redraw();
      }
      inspector.render();
      refreshStatus();
    }
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

function deleteSelection() {
  if (!selection.size) return;
  const ids = new Set(selection.ids);
  store.mutate("delete", (doc) => model.deleteItems(doc, ids));
  selection.clear();
  redraw();
  inspector.render();
  say(`deleted ${ids.size} item(s)`);
}

function copySelection(cut) {
  if (!selection.size) return;
  clipboard = model.copyItems(store.doc, selection.ids);
  const count = clipboard.cells.length + clipboard.shapes.length;
  say(`${cut ? "cut" : "copied"} ${count} item(s)`);
  if (cut) deleteSelection();
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

function stepHistory(back) {
  const label = back ? store.undo() : store.redo();
  if (label === false) return;
  // Items may have vanished, so drop anything selected that no longer exists.
  const alive = new Set(model.items(store.doc).map((i) => i.id));
  selection.set([...selection.ids].filter((id) => alive.has(id)));
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
    delete: deleteSelection,
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
    inspector.render();
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
    // Rendered by Python, the same code the CLI uses, so this file is
    // byte-for-byte what `drawlogic export` would produce.
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

// Ask Python for the drawing as SVG, without writing it anywhere.
async function renderedSvg() {
  return api("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc: store.doc, options: { zoom: 1 } }),
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
  ui.btnPng.addEventListener("click", copyPng);
  ui.undo.addEventListener("click", () => stepHistory(true));
  ui.redo.addEventListener("click", () => stepHistory(false));

  for (const button of document.querySelectorAll("[data-tool]")) {
    button.addEventListener("click", () => {
      const name = button.getAttribute("data-tool");
      const shape = button.getAttribute("data-shape");
      if (shape) tools.shape.arm(shape);
      setTool(name);
      clearPaletteSelection(ui.paletteBody);
    });
  }

  for (const button of document.querySelectorAll("[data-command]")) {
    button.addEventListener("click",
                            () => runCommand(button.getAttribute("data-command")));
  }

  ui.arrange.addEventListener("change", () => {
    if (!ui.arrange.value) return;
    runCommand(ui.arrange.value);
    ui.arrange.value = "";
  });
}

function bindKeyboard() {
  window.addEventListener("keydown", (event) => {
    if (event.target.matches("input, select, textarea")) return;
    const mod = event.ctrlKey || event.metaKey;

    if (mod) {
      const handlers = {
        s: save,
        // Shift makes it a picture. Ctrl+P is left alone: printing to PDF
        // from the browser is the way to get a PDF out of drawlogic.
        e: () => (event.shiftKey ? copyPng() : exportSvg()),
        z: () => stepHistory(!event.shiftKey),
        y: () => stepHistory(false),
        a: () => { selection.selectAll(); redraw(); inspector.render(); },
        c: () => copySelection(false),
        x: () => copySelection(true),
        v: () => paste(),
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
      if (key === "v") setTool("select");
      else if (key === "w") setTool("wire");
      else if (shapes[key]) {
        tools.shape.arm(shapes[key]);
        setTool("shape");
      }
    }
  });

  // Saving is manual, so the one thing done automatically is refusing to let
  // the tab close on unsaved work.
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
    btnPng: $("btn-png"),
    btnFit: $("btn-fit"),
    undo: $("btn-undo"),
    redo: $("btn-redo"),
    gridSelect: $("grid-select"),
    arrange: $("arrange-select"),
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
  });

  viewport = new Viewport(ui.canvas, (view) => {
    const percent = Math.round(view.zoom * 100);
    ui.zoomSlider.value = Math.min(400, Math.max(10, percent));
    ui.zoomValue.value = `${percent}%`;
    drawOverlay(overlayOptions);
  });

  tools = makeTools(context);
  inspector = new Inspector($("properties-body"), store, selection, () => redraw());
  selection.subscribe(() => refreshStatus());

  try {
    const [theme, library, listing] = await Promise.all([
      api("/api/theme"), api("/api/symbols"), api("/api/files"),
    ]);
    render.setTheme(theme);
    geometry.setLibrary(library);
    buildPalette(ui.paletteBody, {
      onPick: (id) => {
        tools.place.arm(id);
        setTool("place");
        say(`click the canvas to place ${id} (shift-click to keep placing)`);
      },
    });

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
