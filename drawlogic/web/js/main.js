// Boots the editor: load the library, load a drawing, draw it, wire controls.

import * as render from "./render.js";
import * as symbols from "./symbols.js";
import { Viewport } from "./viewport.js";

const state = {
  doc: null,
  path: null,
  dirty: false,
};

const ui = {};
let viewport = null;

function $(id) {
  return document.getElementById(id);
}

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

function markDirty(dirty) {
  state.dirty = dirty;
  ui.dirty.hidden = !dirty;
}

function draw() {
  if (!state.doc) return;
  render.render(ui.canvas, state.doc);
  const grid = (state.doc.canvas || {}).grid || {};
  ui.counts.textContent =
    `${state.doc.cells.length} cells | ${state.doc.nets.length} nets`;
  ui.gridStatus.textContent = `grid ${grid.style} ${grid.size}`;
}

// ---- loading ----

async function openDrawing(path) {
  if (state.dirty && !window.confirm("Discard unsaved changes?")) {
    ui.fileSelect.value = state.path || "";
    return;
  }
  try {
    const payload = await api(`/api/doc?path=${encodeURIComponent(path)}`);
    state.doc = payload.doc;
    state.path = payload.path;
    markDirty(false);

    ui.filePath.textContent = payload.path;
    ui.fileSelect.value = payload.path;
    syncControlsFromDoc();
    draw();
    viewport.fit(state.doc.canvas.width, state.doc.canvas.height);
    say(`opened ${payload.path}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

function syncControlsFromDoc() {
  const canvas = state.doc.canvas || {};
  ui.gridSelect.value = (canvas.grid || {}).style || "dots";

  const fontScale = Math.round((Number((canvas.font || {}).scale) || 1) * 100);
  ui.fontSlider.value = fontScale;
  ui.fontValue.value = `${fontScale}%`;

  const symbolScale = Math.round((Number(canvas.symbolScale) || 1) * 100);
  ui.symbolSlider.value = symbolScale;
  ui.symbolValue.value = `${symbolScale}%`;
}

// ---- saving and exporting ----

async function save() {
  if (!state.doc || !state.path) return;
  try {
    await api(`/api/doc?path=${encodeURIComponent(state.path)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: state.doc }),
    });
    markDirty(false);
    say(`saved ${state.path}`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

async function exportSvg() {
  if (!state.doc || !state.path) return;
  const suggested = state.path.replace(/\.dlg$/, ".svg");
  const target = window.prompt("Export SVG to (relative to the served folder):",
                               suggested);
  if (!target) return;
  try {
    // Rendered by Python, the same code the CLI uses, so this file is
    // byte-for-byte what `drawlogic export` would produce.
    const result = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc: state.doc,
        path: target,
        options: { zoom: viewport.zoom },
      }),
    });
    say(`exported ${result.path} (${result.bytes} bytes)`, "good");
  } catch (error) {
    say(error.message, "bad");
  }
}

// ---- palette ----

function buildPalette() {
  const groups = symbols.byCategory();
  const body = ui.paletteBody;
  body.textContent = "";

  for (const category of Object.keys(groups).sort()) {
    const heading = document.createElement("div");
    heading.className = "palette-category";
    heading.textContent = category;
    body.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "palette-grid";
    for (const id of groups[category]) {
      const symbol = symbols.get(id);
      const item = document.createElement("div");
      item.className = "palette-item";
      item.title = `${symbol.name} (${id})`;
      item.appendChild(render.symbolThumbnail(symbol));
      grid.appendChild(item);
    }
    body.appendChild(grid);
  }
}

// ---- controls ----

function bindControls() {
  ui.gridSelect.addEventListener("change", () => {
    state.doc.canvas.grid.style = ui.gridSelect.value;
    markDirty(true);
    draw();
  });

  ui.zoomSlider.addEventListener("input", () => {
    viewport.setZoom(Number(ui.zoomSlider.value) / 100);
  });

  ui.btnFit.addEventListener("click", () => {
    viewport.fit(state.doc.canvas.width, state.doc.canvas.height);
  });

  ui.fontSlider.addEventListener("input", () => {
    const value = Number(ui.fontSlider.value);
    ui.fontValue.value = `${value}%`;
    state.doc.canvas.font.scale = value / 100;
    markDirty(true);
    draw();
  });

  ui.symbolSlider.addEventListener("input", () => {
    const value = Number(ui.symbolSlider.value);
    ui.symbolValue.value = `${value}%`;
    state.doc.canvas.symbolScale = value / 100;
    markDirty(true);
    draw();
  });

  ui.fileSelect.addEventListener("change", () => openDrawing(ui.fileSelect.value));
  ui.btnSave.addEventListener("click", save);
  ui.btnExport.addEventListener("click", exportSvg);

  ui.canvas.addEventListener("mousemove", (event) => {
    const [x, y] = viewport.toDoc(event.clientX, event.clientY);
    ui.cursor.textContent = `x ${Math.round(x)} y ${Math.round(y)}`;
  });

  window.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key === "s") {
      event.preventDefault();
      save();
    } else if (event.key === "e") {
      event.preventDefault();
      exportSvg();
    } else if (event.key === "0") {
      event.preventDefault();
      viewport.fit(state.doc.canvas.width, state.doc.canvas.height);
    }
  });

  // Saving is manual, so the one thing we do automatically is refuse to let
  // the tab close on unsaved work.
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
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
    gridStatus: $("status-grid"),
    message: $("status-message"),
  });

  viewport = new Viewport(ui.canvas, (view) => {
    const percent = Math.round(view.zoom * 100);
    ui.zoomSlider.value = Math.min(400, Math.max(10, percent));
    ui.zoomValue.value = `${percent}%`;
  });

  try {
    const [theme, library, listing] = await Promise.all([
      api("/api/theme"),
      api("/api/symbols"),
      api("/api/files"),
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

    const requested = new URLSearchParams(window.location.search).get("open");
    const first = requested || listing.files[0];
    if (first) {
      await openDrawing(first);
    } else {
      say("no .dlg files found in the served folder", "bad");
    }
  } catch (error) {
    say(error.message, "bad");
  }
}

start();
