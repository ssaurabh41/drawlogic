// The two side panels: the symbol palette and the properties inspector.
//
// Usage:
//
//   buildPalette(container, { onPick: (typeId) => ... });
//   const inspector = new Inspector(el, store, selection, () => redraw());
//   inspector.render();

import * as geometry from "./geometry.js";
import * as routing from "./routing.js";
import * as model from "./model.js";
import { symbolThumbnail } from "./render.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function row(label, control) {
  const wrap = element("div", "prow");
  wrap.appendChild(element("span", null, label));
  wrap.appendChild(control);
  return wrap;
}

function input(value, type = "text") {
  const node = document.createElement("input");
  node.type = type;
  node.className = "pinput";
  node.value = value === null || value === undefined ? "" : value;
  if (type !== "color" && type !== "file") editable(node);
  return node;
}

// What a field has to do to be worth typing in.
//
// Reported as: "I have to click in the Name box, drag the cursor to select the
// text, and type the new name while still holding the mouse down." Three
// separate things were missing.
//
// One click selects what is there, so typing replaces it. Without this a click
// only puts a caret somewhere in the middle of the old name, and the only way
// to replace the whole thing is to drag across it.
//
// Escape commits and hands focus back to the canvas. Escape conventionally
// cancels, but in a properties panel there is nothing to cancel back to that
// the user can see, and every value here is one undo away anyway -- so the key
// that means "I am done with this box" should mean it.
//
// Enter does the same, and clicking anywhere else already did: the browser
// fires `change` on blur. That part was working and is left alone.
function editable(node) {
  node.addEventListener("focus", () => node.select());
  // A click inside an unfocused field would otherwise put a caret down and
  // undo the select() above; this keeps the selection and lets a second click
  // place a caret as usual.
  node.addEventListener("mouseup", (event) => {
    if (node.dataset.caret) return;
    node.dataset.caret = "1";
    event.preventDefault();
  });
  node.addEventListener("blur", () => { delete node.dataset.caret; });
  node.addEventListener("keydown", (event) => {
    if (event.key === "Escape" || event.key === "Enter") {
      event.preventDefault();
      // Committed here rather than left to the `change` the browser fires on
      // blur, because that one only fires for a value the browser considers
      // user-edited -- which is a heuristic, and not one worth resting "did
      // my edit take effect" on. bind() ignores a value it has already
      // applied, so the browser's own change afterwards costs nothing.
      node.dispatchEvent(new Event("change", { bubbles: true }));
      node.blur();
    }
  });
  return node;
}

// ---- the colour palette ----

// Colours worth reaching for on a schematic, as a grid. Greys first, because
// most of a drawing is ink on paper and the useful choice is usually how dark
// rather than which hue. Then two rows of hues, a pale one for filling a body
// and a strong one for drawing a line with, so a fill and the line around it
// can be picked from the same column and look related.
//
// Not in theme.py with the drawing colours: nothing here is ever rendered, and
// nothing else has to agree with it. It is a list of suggestions for a person
// clicking, which is why "Custom" is right beside it.
const SWATCHES = [
  "#ffffff", "#f1f5f6", "#d7e0e3", "#9fb0b6", "#5b6b71", "#16202b", "#000000",
  "#fde2e2", "#fde9cf", "#fbf3c9", "#dcf0d8", "#d3ecf3", "#dfe0f6", "#f6dcec",
  "#c0392b", "#b45309", "#a98307", "#3f7d3a", "#0d7490", "#4b4fa6", "#9b3d77",
];

let openPopup = null;

function closePalette() {
  if (!openPopup) return;
  openPopup.remove();
  openPopup = null;
  document.removeEventListener("mousedown", onOutside, true);
  document.removeEventListener("keydown", onEscape, true);
}

function onOutside(event) {
  if (openPopup && !openPopup.contains(event.target)) closePalette();
}

function onEscape(event) {
  if (event.key === "Escape") {
    event.stopPropagation();
    closePalette();
  }
}

// Anchored to the button rather than placed inside the panel, so it can spill
// out over the canvas instead of being clipped by the panel's own scrollbox.
function openPalette(anchor, current, apply) {
  closePalette();

  const popup = element("div", "cpop");
  const grid = element("div", "cgrid");
  for (const colour of SWATCHES) {
    const cell = element("button", "cswatch");
    cell.type = "button";
    cell.style.background = colour;
    cell.title = colour;
    if (colour.toLowerCase() === String(current).toLowerCase()) {
      cell.classList.add("current");
    }
    cell.addEventListener("click", () => {
      closePalette();
      apply(colour);
    });
    grid.appendChild(cell);
  }
  popup.appendChild(grid);

  // The native dialog, for the colour that is not on the grid. Hidden rather
  // than removed: clicking a label is how an <input type="color"> is opened
  // without showing its own swatch, which would be a second swatch saying the
  // same thing as the button that opened this.
  const more = element("label", "cmore", "Custom");
  const native = document.createElement("input");
  native.type = "color";
  native.value = current;
  // Browsers disagree about which event a colour dialog sends: some stream
  // "input" as you drag inside it, others stay silent until it closes and
  // then send only "change". Binding one leaves the control dead for whoever
  // is on the other browser, so both are bound and the value is remembered.
  let applied = null;
  const fromDialog = () => {
    if (native.value === applied) return;
    applied = native.value;
    apply(native.value);
  };
  native.addEventListener("input", fromDialog);
  native.addEventListener("change", fromDialog);
  more.appendChild(native);
  popup.appendChild(more);

  document.body.appendChild(popup);
  // Measured after it is in the document, then kept on screen: the fill
  // swatch sits low in a tall properties panel, so below the button is often
  // off the bottom of the window.
  const box = anchor.getBoundingClientRect();
  const width = popup.offsetWidth;
  const height = popup.offsetHeight;
  const below = box.bottom + 4;
  popup.style.left = `${Math.max(8, Math.min(box.left,
    window.innerWidth - width - 8))}px`;
  popup.style.top = below + height + 8 <= window.innerHeight
    ? `${below}px`
    : `${Math.max(8, box.top - height - 4)}px`;

  openPopup = popup;
  document.addEventListener("mousedown", onOutside, true);
  document.addEventListener("keydown", onEscape, true);
}

// ---- palette ----

export function buildPalette(root, { onPick }) {
  const groups = geometry.byCategory();
  root.textContent = "";

  for (const category of Object.keys(groups).sort()) {
    root.appendChild(element("div", "palette-category", category));
    const grid = element("div", "palette-grid");

    for (const id of groups[category]) {
      const symbol = geometry.get(id);
      const item = document.createElement("button");
      item.className = "palette-item";
      item.type = "button";
      item.dataset.symbol = id;
      item.title = `${symbol.name} (${id}) - drag onto the canvas, or click then click`;
      item.appendChild(symbolThumbnail(symbol));

      // Dragging one out is the gesture people arrive expecting; the
      // click-then-click path stays because it is the only one that works
      // from a keyboard and the only one that can place several in a row.
      item.draggable = true;
      item.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("application/x-drawlogic-symbol", id);
        event.dataTransfer.setData("text/plain", id);
        event.dataTransfer.effectAllowed = "copy";
        item.classList.add("dragging");
      });
      item.addEventListener("dragend", () => item.classList.remove("dragging"));

      item.addEventListener("click", () => {
        for (const other of root.querySelectorAll(".palette-item")) {
          other.classList.toggle("armed", other === item);
        }
        onPick(id);
      });
      grid.appendChild(item);
    }
    root.appendChild(grid);
  }
}

export function clearPaletteSelection(root) {
  for (const item of root.querySelectorAll(".palette-item")) {
    item.classList.remove("armed");
  }
}

// ---- properties ----

export class Inspector {
  constructor(root, store, selection, onChange) {
    this.root = root;
    this.store = store;
    this.selection = selection;
    this.onChange = onChange;
  }

  render() {
    const root = this.root;
    root.textContent = "";
    if (!this.store.doc) return;

    const items = this.selection.items();
    if (!items.length) {
      root.appendChild(element("p", "empty",
        "Nothing selected. Click an item, or drag a box around several."));
      this.renderDocument();
      return;
    }

    if (items.length > 1) {
      root.appendChild(element("div", "ptitle", `${items.length} selected`));
      if (model.groupOf(this.store.doc, items[0].id)) {
        root.appendChild(element("p", "note", "Grouped. Ctrl+Shift+G ungroups."));
      }
      this.renderAppearance(items);
      this.renderDocument();
      return;
    }

    const item = items[0];
    if (model.isShape(item)) this.renderShape(item);
    else this.renderCell(item);
    this.renderAppearance(items);
    this.renderDocument();
  }

  bind(field, apply, label) {
    // What was last written to the document through this field. A field can
    // report `change` twice for one edit -- once because Escape asked it to,
    // once because the browser does it on blur -- and applying the same value
    // twice would put two steps in the undo history for one rename.
    let committed = field.value;
    field.addEventListener("change", () => {
      if (field.value === committed) return;
      committed = field.value;
      this.store.mutate(label, (doc) => apply(doc, field.value));
      this.onChange();
    });
    return field;
  }

  renderGeometry(item, keys) {
    for (const [key, label] of keys) {
      if (item[key] === undefined) continue;
      const field = input(Math.round(item[key]), "number");
      this.bind(field, (doc, value) => {
        const number = Number(value);
        if (!Number.isFinite(number)) return false;
        const target = model.itemById(doc, item.id);
        if (target) {
          target[key] = (key === "w" || key === "h") ? Math.max(4, number) : number;
        }
      }, "edit");
      this.root.appendChild(row(label, field));
    }
  }

  renderCell(cell) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Cell"));
    root.appendChild(row("Type", element("div", "pval", cell.type)));

    // A block that stands for another drawing says so, with the way in --
    // double-clicking it works too, but nothing on screen would tell you that.
    if (cell.ref) {
      const open = document.createElement("button");
      open.className = "linkish";
      open.textContent = cell.ref;
      open.title = "open this drawing";
      open.addEventListener("click", () => this.onOpenRef && this.onOpenRef(cell));
      root.appendChild(row("Sheet", open));
    }

    const name = input(cell.label || "");
    this.bind(name, (doc, value) => model.setLabel(doc, cell.id, value), "rename");
    root.appendChild(row("Name", name));

    root.appendChild(element("div", "ptitle", "Geometry"));
    this.renderGeometry(cell, [["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]]);

    const rotation = document.createElement("select");
    rotation.className = "pinput";
    for (const value of [0, 90, 180, 270]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `${value} deg`;
      rotation.appendChild(option);
    }
    rotation.value = String(cell.rotate || 0);
    this.bind(rotation, (doc, value) => {
      const target = doc.cells.find((c) => c.id === cell.id);
      if (target) target.rotate = Number(value);
    }, "rotate");
    root.appendChild(row("Rotation", rotation));

    // A custom cell can carry its own picture, embedded so the .dlg stays one
    // shippable file.
    if (cell.type === "custom") this.renderImagePicker(cell);

    const symbol = geometry.forCell(cell);
    if (symbol) this.renderPins(cell, symbol);
  }

  renderImagePicker(cell) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Picture"));

    const picker = document.createElement("input");
    picker.type = "file";
    picker.accept = "image/png,image/jpeg,image/svg+xml,image/gif";
    picker.className = "pinput pfile";
    picker.addEventListener("change", () => {
      const file = picker.files && picker.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        this.store.mutate("picture",
                          (doc) => model.setCellImage(doc, cell.id, reader.result));
        this.onChange();
        this.render();
      };
      reader.readAsDataURL(file);
    });
    root.appendChild(row("File", picker));

    if (cell.image) {
      const clear = element("button", "linkish", "remove picture");
      clear.addEventListener("click", () => {
        this.store.mutate("picture", (doc) => model.setCellImage(doc, cell.id, null));
        this.onChange();
        this.render();
      });
      root.appendChild(row("", clear));
    }
  }

  renderShape(shape) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Shape"));
    root.appendChild(row("Kind", element("div", "pval", shape.kind)));

    if (shape.kind === "text") {
      const text = input(shape.text || "");
      this.bind(text, (doc, value) => model.setLabel(doc, shape.id, value), "text");
      root.appendChild(row("Text", text));
    }

    root.appendChild(element("div", "ptitle", "Geometry"));
    this.renderGeometry(shape, [["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]]);
    if (shape.points) {
      root.appendChild(row("Points", element("div", "pval",
                                             `${shape.points.length} points`)));
    }
  }

  // Showing what each pin actually connects to is the cheap way to catch a
  // wire that only looks attached.
  renderPins(cell, symbol) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Pins"));
    const doc = this.store.doc;

    const labels = cell.pins || {};

    for (const pin of symbol.pins) {
      const touches = (endpoint) =>
        endpoint && endpoint.cell === cell.id && endpoint.pin === pin.name;
      const nets = doc.nets.filter(
        (net) => touches(net.from) || routing.loadsOf(net).some(touches));

      // Name the pin on this instance. Blank falls back to whatever the
      // symbol draws, which for a generic block is nothing at all.
      const field = input(labels[pin.name] || "");
      field.placeholder = pin.name;
      this.bind(field, (d, value) =>
        model.setPinLabel(d, cell.id, pin.name, value.trim()), "name pin");

      const value = element("div", "pval pinwire");
      if (!nets.length) {
        value.textContent = `${pin.dir} - unconnected`;
        value.classList.add("unconnected");
      } else {
        value.textContent = `${pin.dir} - ${nets.map((n) => n.name || n.id).join(", ")}`;
      }

      const wrap = element("div", "pinrow");
      wrap.appendChild(field);
      wrap.appendChild(value);
      root.appendChild(row(pin.name, wrap));
    }
  }

  renderAppearance(items) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Appearance"));
    const first = items[0].style || {};

    for (const [key, label, fallback] of [
      ["fill", "Fill", "#ffffff"],
      ["stroke", "Line", "#16202b"],
    ]) {
      root.appendChild(row(label, this.colourControl(key, first[key], fallback)));
    }

    const weight = input(first.strokeWidth || 1.6, "number");
    weight.step = "0.1";
    weight.min = "0.2";
    this.bind(weight, (doc, value) =>
      model.setStyle(doc, this.selection.ids, "strokeWidth", Number(value)), "weight");
    root.appendChild(row("Weight", weight));
  }

  // Clicking the swatch opens a grid to pick from, the way a slide editor
  // does. The native colour dialog is still there behind "Custom", because a
  // grid of two dozen colours is the fast path and not the only one.
  colourControl(key, current, fallback) {
    const wrap = element("div", "swatch");
    const shown = current || fallback;

    const button = element("button", "pswatch");
    button.type = "button";
    button.style.background = shown;
    button.title = current ? shown : `${shown} (default)`;
    button.setAttribute("aria-label", `${key} colour`);

    const apply = (value) => {
      this.store.mutate("colour",
                        (doc) => model.setStyle(doc, this.selection.ids, key, value));
      this.onChange();
      this.render();
    };

    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openPalette(button, shown, apply);
    });

    const reset = element("button", "linkish", "reset");
    reset.type = "button";
    reset.title = "back to the colour the symbol came with";
    reset.addEventListener("click", () => apply(null));

    wrap.appendChild(button);
    wrap.appendChild(reset);
    return wrap;
  }

  renderDocument() {
    const root = this.root;
    const doc = this.store.doc;
    root.appendChild(element("div", "ptitle", "Drawing"));

    const title = input(doc.title || "");
    this.bind(title, (d, value) => { d.title = value || "untitled"; }, "title");
    root.appendChild(row("Title", title));

    for (const [key, label] of [["width", "Sheet W"], ["height", "Sheet H"]]) {
      const field = input(doc.canvas[key], "number");
      this.bind(field, (d, value) => {
        const number = Number(value);
        if (!Number.isFinite(number) || number < 50) return false;
        d.canvas[key] = number;
      }, "sheet");
      root.appendChild(row(label, field));
    }

    const step = input(model.gridStep(doc), "number");
    step.min = "1";
    this.bind(step, (d, value) => {
      const number = Number(value);
      if (!Number.isFinite(number) || number < 1) return false;
      d.canvas.grid.size = number;
    }, "grid");
    root.appendChild(row("Grid", step));

    const arrows = document.createElement("input");
    arrows.type = "checkbox";
    arrows.className = "pcheck";
    arrows.checked = doc.canvas.arrows !== false;
    arrows.addEventListener("change", () => {
      this.store.mutate("arrows", (d) => { d.canvas.arrows = arrows.checked; });
      this.onChange();
    });
    root.appendChild(row("Arrows", arrows));
  }
}
