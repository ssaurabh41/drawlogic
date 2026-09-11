// The properties panel: what is selected, and the fields that change it.

import * as actions from "./actions.js";
import * as routing from "./routing.js";
import * as symbols from "./symbols.js";

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

export class Properties {
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

    const cells = this.selection.cells();
    if (!cells.length) {
      root.appendChild(element("p", "empty",
        "Nothing selected. Click a cell, or drag a box around several."));
      this.renderDocument();
      return;
    }

    if (cells.length > 1) {
      root.appendChild(element("div", "ptitle", `${cells.length} selected`));
      const group = actions.groupOf(this.store.doc, cells[0].id);
      if (group) {
        root.appendChild(element("p", "note",
          "Grouped. Ctrl+Shift+G ungroups."));
      }
      this.renderAppearance(cells);
      this.renderDocument();
      return;
    }

    this.renderCell(cells[0]);
    this.renderAppearance(cells);
    this.renderDocument();
  }

  renderCell(cell) {
    const root = this.root;
    const symbol = symbols.get(cell.type);

    root.appendChild(element("div", "ptitle", "Cell"));
    root.appendChild(row("Type", element("div", "pval", cell.type)));

    const name = input(cell.label || "");
    name.addEventListener("change", () => {
      this.store.mutate("rename", (doc) => actions.setLabel(doc, cell.id, name.value));
      this.onChange();
    });
    root.appendChild(row("Name", name));

    root.appendChild(element("div", "ptitle", "Geometry"));
    for (const [key, label] of [["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]]) {
      const field = input(Math.round(cell[key]), "number");
      field.addEventListener("change", () => {
        const value = Number(field.value);
        if (!Number.isFinite(value)) return;
        this.store.mutate("edit", (doc) => {
          const target = doc.cells.find((c) => c.id === cell.id);
          if (target) target[key] = key === "w" || key === "h"
            ? Math.max(4, value) : value;
        });
        this.onChange();
      });
      root.appendChild(row(label, field));
    }

    const rotation = document.createElement("select");
    rotation.className = "pinput";
    for (const value of [0, 90, 180, 270]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = `${value} deg`;
      rotation.appendChild(option);
    }
    rotation.value = String(cell.rotate || 0);
    rotation.addEventListener("change", () => {
      this.store.mutate("rotate", (doc) => {
        const target = doc.cells.find((c) => c.id === cell.id);
        if (target) target.rotate = Number(rotation.value);
      });
      this.onChange();
    });
    root.appendChild(row("Rotation", rotation));

    if (symbol) this.renderPins(cell, symbol);
  }

  // Showing what each pin actually connects to is the cheap way to catch a
  // wire that only looks attached.
  renderPins(cell, symbol) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Pins"));
    const doc = this.store.doc;

    for (const pin of symbol.pins) {
      const nets = doc.nets.filter((net) =>
        ["from", "to"].some((side) =>
          net[side] && net[side].cell === cell.id && net[side].pin === pin.name));

      const value = element("div", "pval");
      if (!nets.length) {
        value.textContent = `${pin.dir} - unconnected`;
        value.classList.add("unconnected");
      } else {
        const names = nets.map((n) => n.name || n.id).join(", ");
        value.textContent = `${pin.dir} - ${names}`;
      }
      root.appendChild(row(pin.name, value));
    }
  }

  renderAppearance(cells) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Appearance"));
    const first = cells[0].style || {};

    for (const [key, label, fallback] of [
      ["fill", "Fill", "#ffffff"],
      ["stroke", "Line", "#16202b"],
    ]) {
      const wrap = element("div", "swatch");
      const picker = input(first[key] || fallback, "color");
      picker.classList.add("pcolor");
      picker.addEventListener("input", () => {
        this.store.mutate("colour",
                          (doc) => actions.setStyle(doc, this.selection.ids, key, picker.value));
        this.onChange();
      });
      const reset = element("button", "linkish", "reset");
      reset.addEventListener("click", () => {
        this.store.mutate("colour",
                          (doc) => actions.setStyle(doc, this.selection.ids, key, null));
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
    weight.addEventListener("change", () => {
      this.store.mutate("weight", (doc) =>
        actions.setStyle(doc, this.selection.ids, "strokeWidth", Number(weight.value)));
      this.onChange();
    });
    root.appendChild(row("Weight", weight));
  }

  renderDocument() {
    const root = this.root;
    const doc = this.store.doc;
    root.appendChild(element("div", "ptitle", "Drawing"));

    const title = input(doc.title || "");
    title.addEventListener("change", () => {
      this.store.mutate("title", (d) => { d.title = title.value || "untitled"; });
      this.onChange();
    });
    root.appendChild(row("Title", title));

    for (const [key, label] of [["width", "Sheet W"], ["height", "Sheet H"]]) {
      const field = input(doc.canvas[key], "number");
      field.addEventListener("change", () => {
        const value = Number(field.value);
        if (!Number.isFinite(value) || value < 50) return;
        this.store.mutate("sheet", (d) => { d.canvas[key] = value; });
        this.onChange();
      });
      root.appendChild(row(label, field));
    }

    const step = input(actions.gridStep(doc), "number");
    step.min = "1";
    step.addEventListener("change", () => {
      const value = Number(step.value);
      if (!Number.isFinite(value) || value < 1) return;
      this.store.mutate("grid", (d) => { d.canvas.grid.size = value; });
      this.onChange();
    });
    root.appendChild(row("Grid", step));
  }
}
