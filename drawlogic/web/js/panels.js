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
  return node;
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
      item.title = `${symbol.name} (${id}) - click, then click the canvas`;
      item.appendChild(symbolThumbnail(symbol));
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
    field.addEventListener("change", () => {
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
      const wrap = element("div", "swatch");
      const picker = input(first[key] || fallback, "color");
      picker.classList.add("pcolor");
      picker.addEventListener("input", () => {
        this.store.mutate("colour",
                          (doc) => model.setStyle(doc, this.selection.ids, key, picker.value));
        this.onChange();
      });
      const reset = element("button", "linkish", "reset");
      reset.addEventListener("click", () => {
        this.store.mutate("colour",
                          (doc) => model.setStyle(doc, this.selection.ids, key, null));
        this.onChange();
        this.render();
      });
      wrap.appendChild(picker);
      wrap.appendChild(reset);
      root.appendChild(row(label, wrap));
    }

    const weight = input(first.strokeWidth || 1.6, "number");
    weight.step = "0.1";
    weight.min = "0.2";
    this.bind(weight, (doc, value) =>
      model.setStyle(doc, this.selection.ids, "strokeWidth", Number(value)), "weight");
    root.appendChild(row("Weight", weight));
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
