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

// The arrowheads a drawn line can end in, in the order the panel offers them.
// Held equal to theme.LINE_HEADS by a test, so a head added there cannot go
// missing here.
export const HEAD_KINDS = ["none", "triangle", "open", "stealth", "diamond", "oval"];

// Three short lines showing where text would sit: across, ragged to a side
// or centred; down, a block at the top, middle or bottom of a frame.
function alignIcon(key, value) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "align-ico");
  const line = (x1, y, x2) => {
    const node = document.createElementNS(ns, "line");
    node.setAttribute("x1", x1);
    node.setAttribute("y1", y);
    node.setAttribute("x2", x2);
    node.setAttribute("y2", y);
    svg.appendChild(node);
  };
  if (key === "textAlign") {
    [12, 8, 10].forEach((length, index) => {
      const x1 = value === "left" ? 2 : value === "right" ? 14 - length : 8 - length / 2;
      line(x1, 4 + index * 4, x1 + length);
    });
  } else {
    const frame = document.createElementNS(ns, "rect");
    frame.setAttribute("x", "1.5");
    frame.setAttribute("y", "1.5");
    frame.setAttribute("width", "13");
    frame.setAttribute("height", "13");
    frame.setAttribute("class", "frame");
    svg.appendChild(frame);
    const top = { top: 4.5, middle: 7, bottom: 9.5 }[value];
    line(4, top, 12);
    line(5, top + 2.5, 11);
  }
  return svg;
}

// ---- folding the properties panel ----

// Which sections are folded, by name, kept per browser like the palette's.
// Stored as name -> folded rather than a list of the folded ones, so a
// section folded by default -- Pins -- stays open once someone opens it.
const PANEL_FOLDED_KEY = "drawlogic.panelFolded";
const FOLDED_BY_DEFAULT = { pins: true };

function panelFolded() {
  try {
    return { ...FOLDED_BY_DEFAULT,
             ...JSON.parse(window.localStorage.getItem(PANEL_FOLDED_KEY) || "{}") };
  } catch (error) {
    return { ...FOLDED_BY_DEFAULT };
  }
}

function savePanelFolded(folded) {
  try {
    window.localStorage.setItem(PANEL_FOLDED_KEY, JSON.stringify(folded));
  } catch (error) {
    // Private browsing: folding still works, it just is not remembered.
  }
}

// A section's name for remembering it: its title, except "3 selected", whose
// number changes with every selection while the section stays the same one.
function sectionKey(title) {
  const text = title.trim().toLowerCase();
  return /^\d+ selected$/.test(text) ? "selection" : text;
}

// Turn each section title in the panel into a header that folds what follows
// it, up to the next title. Done after the panel is drawn, over whatever it
// drew, so every kind of selection folds the same way without each one being
// written to.
function foldSections(root) {
  const folded = panelFolded();
  const titles = [...root.children].filter((n) => n.classList.contains("ptitle"));
  for (const title of titles) {
    const key = sectionKey(title.textContent);
    const body = element("div", "psec");
    while (title.nextSibling && !(title.nextSibling.classList
                                  && title.nextSibling.classList.contains("ptitle"))) {
      body.appendChild(title.nextSibling);
    }
    title.after(body);
    if (!body.childNodes.length) continue;
    title.classList.add("pfold");
    title.tabIndex = 0;
    title.setAttribute("role", "button");
    const show = (open) => {
      title.setAttribute("aria-expanded", String(open));
      body.hidden = !open;
    };
    show(!folded[key]);
    const toggle = () => {
      const open = body.hidden;
      show(open);
      const now = panelFolded();
      now[key] = !open;
      savePanelFolded(now);
    };
    // On the press, not the click: a press here takes focus from whatever
    // field had it, its change redraws the panel, and the header the click
    // would have landed on is gone by the time the button comes up. The press
    // also keeps focus where it was, so nothing half typed is committed.
    title.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      toggle();
    });
    title.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
  }
}

// One option in a row of exclusive choices.
function segButton(content, title, pressed) {
  const button = element("button", "seg-btn");
  button.type = "button";
  button.title = title;
  button.setAttribute("role", "radio");
  button.setAttribute("aria-label", title);
  button.setAttribute("aria-checked", String(pressed));
  if (typeof content === "string") button.textContent = content;
  else button.appendChild(content);
  return button;
}

// A short line ending in `kind`, drawn with the renderer's own head geometry
// so the picture on the button is the head you get.
function headPreview(kind, atStart) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 22 12");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "head-ico");
  const ends = atStart ? [[20, 6], [3, 6]] : [[2, 6], [19, 6]];
  const [head, trim] = geometry.lineHead(ends[1], ends[0], kind, 10, 0.45);
  const line = document.createElementNS(ns, "line");
  line.setAttribute("x1", ends[0][0]);
  line.setAttribute("y1", ends[0][1]);
  line.setAttribute("x2", trim[0]);
  line.setAttribute("y2", trim[1]);
  svg.appendChild(line);
  if (head) {
    const [shape, data] = head;
    const node = document.createElementNS(ns, shape);
    if (shape === "ellipse") {
      node.setAttribute("cx", data[0]);
      node.setAttribute("cy", data[1]);
      node.setAttribute("rx", data[2]);
      node.setAttribute("ry", data[3]);
    } else {
      node.setAttribute("points", data.map((p) => p.join(",")).join(" "));
    }
    node.setAttribute("class", shape === "polyline" ? "open" : "solid");
    svg.appendChild(node);
  }
  return svg;
}

function row(label, control) {
  const wrap = element("div", "prow");
  wrap.appendChild(element("span", null, label));
  const isNumber = control.tagName === "INPUT" && control.type === "number";
  wrap.appendChild(isNumber ? stepper(control) : control);
  return wrap;
}

// A number field with up and down arrows inside its right end.
//
// The browser's own spinner is the right shape -- it takes no room beside the
// field -- but each arrow is about 7px tall and drawn only while the pointer
// is over the field, so it was hard to hit. These are the same two arrows,
// always shown, each the full width of the strip and half the field's height,
// and lit under the pointer. A minus and a plus beside the field were tried
// first and took too much of a narrow panel.
//
// Holding an arrow repeats, as the browser's does. The value shown changes on
// every step, but the drawing is changed once, on release: a press-and-hold is
// one edit, so one undo step.
function stepper(field) {
  const wrap = element("div", "pstep");
  wrap.appendChild(field);
  const spin = element("div", "pspin");
  for (const [sign, title] of [[1, "increase"], [-1, "decrease"]]) {
    const button = element("button", sign > 0 ? "pspin-btn up" : "pspin-btn down");
    button.type = "button";
    button.tabIndex = -1;
    button.title = title;
    button.setAttribute("aria-label", title);
    let timer = null;
    let changed = false;
    const finish = () => {
      if (timer === null) return;
      clearTimeout(timer);
      timer = null;
      if (changed) field.dispatchEvent(new Event("change"));
      changed = false;
    };
    const tick = (delay) => {
      changed = nudgeNumber(field, sign) || changed;
      timer = setTimeout(() => tick(60), delay);
    };
    button.addEventListener("mousedown", (event) => {
      // Keep focus where it was: taking it would blur the field, and a blur
      // fires `change` on whatever was half typed there.
      event.preventDefault();
      if (event.button !== 0) return;
      finish();
      tick(400);
    });
    button.addEventListener("mouseup", finish);
    button.addEventListener("mouseleave", finish);
    spin.appendChild(button);
  }
  wrap.appendChild(spin);
  return wrap;
}

// One step up or down, kept inside the field's min and max. Done by hand
// rather than with stepUp(), which throws on step="any" and, on an empty field,
// starts from zero -- and an empty field here means "mixed", where there is no
// single value to step from.
// Returns whether the value changed; the caller decides when to commit it.
//
// An empty field steps from its placeholder when that is a number: Copies
// shows a grey "1" for a cell that has never been copied, and pressing up
// there has to give 2 -- refusing it meant a cell could never be made into a
// stack with the arrows at all. A placeholder that is not a number ("mixed",
// "default") has no single value to step from, so those still do nothing.
function nudgeNumber(field, sign) {
  const shown = field.value === "" ? field.placeholder : field.value;
  if (shown === "") return false;
  const current = Number(shown);
  if (!Number.isFinite(current)) return false;
  const step = Number(field.step) > 0 ? Number(field.step) : 1;
  let next = Math.round((current + sign * step) / step) * step;
  // A step of 0.1 adds float noise; the field shows what a person would type.
  next = Number(next.toFixed(6));
  if (field.min !== "" && next < Number(field.min)) next = Number(field.min);
  if (field.max !== "" && next > Number(field.max)) next = Number(field.max);
  if (next === current) return false;
  field.value = String(next);
  return true;
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
  // The click that focuses the field is taken here rather than let through.
  //
  // A browser places the caret as the default action of *mousedown*, not
  // mouseup -- so the first attempt at this, which called preventDefault on
  // mouseup, was already too late: the selection went in on focus and the
  // caret collapsed it again a moment later. Reported as "it selects the
  // name, but the selection disappears when I let go of the mouse", which is
  // exactly what that looks like.
  //
  // So the first click is intercepted before the caret is placed, and focus
  // is asked for by hand, which selects. Once the field has focus this does
  // nothing, so a second click places a caret and a drag selects a range, the
  // way they should.
  node.addEventListener("mousedown", (event) => {
    if (document.activeElement === node) return;
    event.preventDefault();
    node.focus();
  });
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
// `noFill` adds a "No fill" choice above the grid: transparent, which is not
// the same as white -- white covers whatever is behind it.
function openPalette(anchor, current, apply, noFill = false) {
  closePalette();

  const popup = element("div", "cpop");
  if (noFill) {
    const none = element("button", "cnone");
    none.type = "button";
    none.appendChild(element("span", "cswatch-none"));
    none.appendChild(document.createTextNode("No fill"));
    none.title = "transparent: whatever is behind shows through";
    if (current === "none") none.classList.add("current");
    none.addEventListener("click", () => {
      closePalette();
      apply("none");
    });
    popup.appendChild(none);
  }
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
  native.value = /^#[0-9a-f]{6}$/i.test(current) ? current : "#ffffff";
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

  showPopup(anchor, popup);
}

// The arrowheads as a small gallery under the button that opened it.
function openHeadPicker(anchor, current, atStart, apply) {
  closePalette();
  const popup = element("div", "cpop headpop");
  popup.setAttribute("role", "listbox");
  for (const kind of HEAD_KINDS) {
    const option = element("button", "headopt");
    option.type = "button";
    option.title = kind === "none" ? "no arrowhead" : kind;
    option.setAttribute("role", "option");
    option.setAttribute("aria-label", option.title);
    option.setAttribute("aria-selected", String(kind === current));
    option.appendChild(headPreview(kind, atStart));
    option.addEventListener("click", () => {
      closePalette();
      apply(kind);
    });
    popup.appendChild(option);
  }
  showPopup(anchor, popup);
}

// Put a popup under the control that opened it, and close it on a click
// elsewhere or Escape. Shared by the colour grid and the arrowhead picker.
function showPopup(anchor, popup) {
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

// The order sections are listed in: what a schematic is mostly made of first.
// A category not named here -- one from a folder's own symbols.json, or the
// blocks standing for other drawings -- follows, alphabetically.
const CATEGORY_ORDER = ["blocks", "sequential", "gates", "ports", "bus", "analog"];

// Which sections are folded away, kept per browser like any other habit of
// the person drawing rather than of the drawing.
const FOLDED_KEY = "drawlogic.paletteFolded";

function foldedSections() {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(FOLDED_KEY) || "[]"));
  } catch (error) {
    return new Set();
  }
}

function saveFolded(folded) {
  try {
    window.localStorage.setItem(FOLDED_KEY, JSON.stringify([...folded]));
  } catch (error) {
    // Private browsing: folding still works, it just is not remembered.
  }
}

function categoryRank(category) {
  const index = CATEGORY_ORDER.indexOf(category);
  return index < 0 ? CATEGORY_ORDER.length : index;
}

// Palette sections that gather more than one symbol category. A mux is filed
// apart from the gates because auto layout may turn a gate over and must
// never turn a mux (its select pin would end up on the wrong side), but on
// the palette it is just another gate.
const SECTION_OF = { mux: "gates" };

export function buildPalette(root, { onPick }) {
  const groups = {};
  for (const [category, ids] of Object.entries(geometry.byCategory())) {
    const section = SECTION_OF[category] || category;
    groups[section] = (groups[section] || []).concat(ids);
  }
  root.textContent = "";
  const folded = foldedSections();

  // Typing narrows every section at once, by id or by name -- the quick way
  // to "nand3" when you know what you want and not where it is filed.
  const search = document.createElement("input");
  search.type = "search";
  search.className = "palette-search";
  search.placeholder = "Search symbols";
  search.setAttribute("aria-label", "Search symbols");
  root.appendChild(search);

  const sections = [];
  const categories = Object.keys(groups).sort((a, b) =>
    categoryRank(a) - categoryRank(b) || a.localeCompare(b));
  for (const category of categories) {
    const section = document.createElement("details");
    section.className = "palette-section";
    section.open = !folded.has(category);
    section.addEventListener("toggle", () => {
      if (search.value.trim()) return;
      if (section.open) folded.delete(category);
      else folded.add(category);
      saveFolded(folded);
    });

    const head = document.createElement("summary");
    head.className = "palette-category";
    head.appendChild(element("span", null, category));
    const count = element("span", "palette-count", String(groups[category].length));
    head.appendChild(count);
    section.appendChild(head);

    const grid = element("div", "palette-grid");
    const items = [];
    for (const id of groups[category]) {
      const symbol = geometry.get(id);
      const item = document.createElement("button");
      item.className = "palette-item";
      item.type = "button";
      item.dataset.symbol = id;
      item.title = `${symbol.name} (${id}) - drag onto the canvas, or click then click`;
      const art = element("span", "palette-art");
      art.appendChild(symbolThumbnail(symbol, 34, 30));
      item.appendChild(art);
      item.appendChild(element("span", "palette-caption", id));

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
      items.push({ item, text: `${id} ${symbol.name}`.toLowerCase() });
    }
    section.appendChild(grid);
    root.appendChild(section);
    sections.push({ section, items, count, category, total: items.length });
  }

  const empty = element("p", "palette-empty", "No symbol matches.");
  empty.hidden = true;
  root.appendChild(empty);

  search.addEventListener("input", () => {
    const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const entry of sections) {
      let here = 0;
      for (const { item, text } of entry.items) {
        const match = words.every((word) => text.includes(word));
        item.hidden = !match;
        if (match) here += 1;
      }
      entry.section.hidden = here === 0;
      entry.count.textContent = words.length ? `${here}/${entry.total}` : String(entry.total);
      // While searching every section with a hit is open; clearing the box
      // puts the folding back the way it was.
      entry.section.open = words.length ? here > 0 : !folded.has(entry.category);
      shown += here;
    }
    empty.hidden = shown > 0;
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      search.value = "";
      search.dispatchEvent(new Event("input"));
      search.blur();
    }
    event.stopPropagation();
  });
}

export function clearPaletteSelection(root) {
  for (const item of root.querySelectorAll(".palette-item")) {
    item.classList.remove("armed");
  }
}

// ---- properties ----

export class Inspector {
  constructor(root, store, selection, onChange, onRefuse = () => {}) {
    this.root = root;
    this.store = store;
    this.selection = selection;
    this.onChange = onChange;
    this.onRefuse = onRefuse;
  }

  render() {
    this.renderBody();
    foldSections(this.root);
  }

  renderBody() {
    const root = this.root;
    root.textContent = "";
    if (!this.store.doc) return;

    if (this.selection.net !== null) {
      const net = this.store.doc.nets.find((n) => n.id === this.selection.net);
      if (net) {
        this.renderNet(net);
        this.renderDocument();
        return;
      }
    }

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
      this.renderShared(items);
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
      let accepted = false;
      this.store.mutate(label, (doc) => {
        const result = apply(doc, field.value);
        accepted = result !== false;
        return result;
      });
      // A value the document refused -- a width of "abc" -- used to stay in
      // the box as if it had been taken, and typing it again did nothing
      // because it already matched. Put back what the drawing holds.
      if (!accepted) {
        this.onRefuse(`"${field.value}" is not a usable value`);
        field.value = committed;
        return;
      }
      committed = field.value;
      this.onChange();
    });
    return field;
  }

  // X and Y for everything selected at once: typing a value puts every item's
  // left (or top) there. A field shows the value when they all agree and is
  // blank, marked "mixed", when they do not.
  renderShared(items) {
    for (const [key, label] of [["x", "X"], ["y", "Y"]]) {
      const values = items.map((item) => item[key]).filter((v) => v !== undefined);
      if (!values.length) continue;
      const same = values.every((v) => v === values[0]);
      const field = input(same ? Math.round(values[0]) : "", "number");
      field.placeholder = "mixed";
      this.bind(field, (doc, value) => {
        const number = numberFrom(value);
        if (!Number.isFinite(number)) return false;
        for (const id of this.selection.ids) {
          const target = model.itemById(doc, id);
          if (target && target[key] !== undefined) target[key] = number;
        }
      }, "edit");
      this.root.appendChild(row(label, field));
    }
  }

  renderGeometry(item, keys) {
    for (const [key, label] of keys) {
      if (item[key] === undefined) continue;
      const field = input(Math.round(item[key]), "number");
      this.bind(field, (doc, value) => {
        const number = numberFrom(value);
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

    // A port or a tie cell is moved, never resized, and holds no text: the
    // fields for those would only be things that do nothing.
    const fixed = geometry.FIXED_SIZE_TYPES.has(cell.type);
    root.appendChild(element("div", "ptitle", "Geometry"));
    this.renderGeometry(cell, fixed ? [["x", "X"], ["y", "Y"]]
      : [["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]]);

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

    // Auto layout arranges everything else around a pinned cell and never
    // moves it -- for the part of a drawing that is already where you want it.
    const pinned = document.createElement("input");
    pinned.type = "checkbox";
    pinned.className = "pcheck";
    pinned.checked = cell.pinned === true;
    pinned.title = "auto layout leaves a pinned cell where it is";
    pinned.addEventListener("change", () => {
      this.store.mutate(pinned.checked ? "pin" : "unpin", (doc) => {
        const target = doc.cells.find((c) => c.id === cell.id);
        if (!target) return false;
        if (pinned.checked) target.pinned = true;
        else delete target.pinned;
      });
      this.onChange();
    });
    root.appendChild(row("Pinned", pinned));

    if (!fixed) this.renderCellText(cell);

    // A custom cell can carry its own picture, embedded so the .dlg stays one
    // shippable file.
    if (cell.type === "custom") this.renderImagePicker(cell);

    const symbol = geometry.forCell(cell);
    if (symbol) this.renderPins(cell, symbol);
  }

  // Where the text sits in the box, as a slide editor offers it: three
  // buttons across and three down, each drawing what it does.
  renderTextAlign(cell) {
    const [across, down] = geometry.cellTextAlign(cell);
    for (const [key, label, now, order] of [
      ["textAlign", "Align", across, ["left", "center", "right"]],
      ["textVAlign", "Vertical", down, ["top", "middle", "bottom"]],
    ]) {
      const group = element("div", "seg seg-align");
      group.setAttribute("role", "radiogroup");
      group.setAttribute("aria-label", `${label} text`);
      for (const value of order) {
        const button = segButton(alignIcon(key, value), value, value === now);
        button.addEventListener("click", () => {
          this.store.mutate("align text",
                            (doc) => model.setTextAlign(doc, cell.id, key, value));
          this.onChange();
          this.render();
        });
        group.appendChild(button);
      }
      this.root.appendChild(row(label, group));
    }
  }

  // What a block in a block diagram says: lines written inside it, and how
  // many copies it stands for.
  //
  // A shape takes the same, less what does not apply: a box drawn by hand is
  // the size it was drawn, so it does not grow to fit; a line's caption sits
  // above its middle, so there is nothing to align; and a line has no copies.
  renderCellText(cell, { fit = true, align = true, copies: stacks = true } = {}) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Text inside"));

    // A box for several lines. Enter is a new line here, so the edit is kept
    // when the box is left (or Ctrl+Enter), not on Enter as in other fields.
    const text = document.createElement("textarea");
    text.className = "pinput ptext";
    text.rows = 4;
    text.placeholder = "one line per line";
    text.value = geometry.cellTextLines(cell).join("\n");
    text.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        text.blur();
      } else if (event.key === "Escape") {
        text.blur();
      }
    });
    this.bind(text, (doc, value) => model.setCellText(doc, cell.id, value), "cell text");
    // The box may have grown to fit, so the size fields above are redrawn.
    text.addEventListener("change", () => this.render());
    root.appendChild(row("Text", text));
    if (align) this.renderTextAlign(cell);
    if (fit) this.renderTextFit(cell);
    if (stacks) this.renderCopies(cell);
  }

  renderTextFit(cell) {
    const root = this.root;
    const fit = document.createElement("input");
    fit.type = "checkbox";
    fit.className = "pcheck";
    fit.checked = cell.textFit !== false;
    fit.title = "grow the box so the text fits; off, text that does not fit is cut short";
    fit.addEventListener("change", () => {
      this.store.mutate("fit text", (doc) => model.setTextFit(doc, cell.id, fit.checked));
      this.onChange();
      this.render();
    });
    root.appendChild(row("Fit box", fit));
  }

  renderCopies(cell) {
    const copies = input(cell.copies || "", "number");
    copies.min = "1";
    copies.step = "1";
    copies.placeholder = "1";
    copies.title = "2 or more draws it as a stack with a count";
    this.bind(copies, (doc, value) => model.setCopies(doc, cell.id, value), "copies");
    this.root.appendChild(row("Copies", copies));
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

    if (shape.kind === "line" || shape.kind === "polyline") this.renderHeads(shape);
    if (geometry.SHAPE_TEXT_KINDS.includes(shape.kind)) {
      const line = shape.kind === "line" || shape.kind === "polyline";
      this.renderCellText(shape, { fit: false, align: !line,
                                   copies: geometry.SHAPE_STACK_KINDS.includes(shape.kind) });
    }

    root.appendChild(element("div", "ptitle", "Geometry"));
    this.renderGeometry(shape, [["x", "X"], ["y", "Y"], ["w", "Width"], ["h", "Height"]]);
    if (shape.points) {
      root.appendChild(row("Points", element("div", "pval",
                                             `${shape.points.length} points`)));
    }
  }

  // Arrowheads for an open line, as a slide editor offers them: one row per
  // end, holding a button that shows the head now on it -- press it for a
  // gallery of the others -- and the size beside it. Picked by looking, not
  // by name. The start is the end the line was drawn from.
  renderHeads(shape) {
    const root = this.root;
    const style = shape.style || {};
    root.appendChild(element("div", "ptitle", "Arrows"));
    for (const [key, label] of [["headStart", "Begin"], ["headEnd", "End"]]) {
      const atStart = key === "headStart";
      const current = style[key] || "none";
      const line = element("div", "headrow");

      const pick = element("button", "headpick");
      pick.type = "button";
      pick.title = `${label} arrowhead: ${current}`;
      pick.setAttribute("aria-label", `${label} arrowhead: ${current}`);
      pick.setAttribute("aria-haspopup", "true");
      pick.appendChild(headPreview(current, atStart));
      // A real chevron, in its own end of the button behind a divider, as a
      // slide editor's split button has it: the small text triangle that was
      // here read as a speck.
      const chev = element("span", "headpick-open");
      chev.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><use href="#i-chevron"/></svg>';
      pick.appendChild(chev);
      pick.addEventListener("click", (event) => {
        event.stopPropagation();
        openHeadPicker(pick, current, atStart, (kind) => this.setShapeStyle(
          shape, key, kind === "none" ? null : kind, "arrowhead"));
      });
      line.appendChild(pick);

      const size = element("div", "seg seg-size");
      size.setAttribute("role", "radiogroup");
      size.setAttribute("aria-label", `${label} arrowhead size`);
      const now = style[key + "Size"] || "m";
      for (const [value, text, title] of [["s", "S", "small"], ["m", "M", "medium"],
                                          ["l", "L", "large"]]) {
        const button = segButton(text, `${title} ${label.toLowerCase()} arrowhead`,
                                 value === now);
        button.disabled = current === "none";
        // Medium is the default, so choosing it clears the key rather than
        // writing the default into the file.
        button.addEventListener("click", () => this.setShapeStyle(
          shape, key + "Size", value === "m" ? null : value, "arrowhead size"));
        size.appendChild(button);
      }
      line.appendChild(size);
      root.appendChild(row(label, line));
    }
  }

  setShapeStyle(shape, key, value, label) {
    this.store.mutate(label, (doc) => model.setStyle(doc, [shape.id], key, value));
    this.onChange();
    this.render();
  }

  // A wire: what it says on the sheet, what it is called, and how it is drawn.
  renderNet(net) {
    const root = this.root;
    const doc = this.store.doc;
    root.appendChild(element("div", "ptitle", "Wire"));

    const label = input(net.label || "");
    label.placeholder = "nothing drawn";
    this.bind(label, (d, value) => model.setNetLabel(d, net.id, value), "label wire");
    root.appendChild(row("Label", label));

    // The name is an identifier, not text on the sheet: d[7:0] makes the
    // wire eight bits wide, and validation holds it to the pins it meets.
    const name = input(net.name || "");
    name.placeholder = net.id;
    this.bind(name, (d, value) => model.setNetName(d, net.id, value.trim()), "rename wire");
    root.appendChild(row("Name", name));
    root.appendChild(row("Bits", element("div", "pval", String(net.width || 1))));

    const ends = (endpoint) => (endpoint && endpoint.cell !== undefined
      ? `${endpoint.cell}.${endpoint.pin}` : "free end");
    root.appendChild(row("From", element("div", "pval", ends(net.from))));
    root.appendChild(row("To", element("div", "pval",
      routing.loadsOf(net).map(ends).join(", ") || "-")));

    root.appendChild(element("div", "ptitle", "Appearance"));
    const style = net.style || {};
    root.appendChild(row("Colour", this.netColourControl(net, style.stroke)));

    const weight = input(style.strokeWidth || "", "number");
    weight.step = "0.1";
    weight.min = "0.2";
    weight.placeholder = "default";
    this.bind(weight, (d, value) => {
      if (String(value).trim() === "") return model.setNetStyle(d, net.id, "strokeWidth", null);
      const number = numberFrom(value);
      if (!(number > 0)) return false;
      model.setNetStyle(d, net.id, "strokeWidth", number);
    }, "wire weight");
    root.appendChild(row("Weight", weight));

    const line = this.choice([["", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"]],
                             style.dash || "");
    this.bind(line, (d, value) => model.setNetStyle(d, net.id, "dash", value || null),
              "wire line");
    root.appendChild(row("Line", line));

    // Unset means the drawing decides: driver to loads, or none at all on a
    // wire that meets a bidirectional pin. Saying which it decided saves
    // guessing why a wire has no arrow.
    const chosen = style.arrow === false ? "none" : (style.arrow || "");
    const automatic = routing.arrowMode(doc, { ...net, style: { ...style, arrow: undefined } });
    const arrows = this.choice([
      ["", `Auto (${automatic === "none" ? "none - meets an inout pin" : "forward"})`],
      ["none", "None"], ["forward", "Forward"], ["backward", "Backward"],
      ["both", "Both ways"]], chosen);
    this.bind(arrows, (d, value) => model.setNetStyle(d, net.id, "arrow", value || null),
              "wire arrows");
    root.appendChild(row("Arrows", arrows));
  }

  choice(options, current) {
    const select = document.createElement("select");
    select.className = "pinput";
    for (const [value, text] of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      select.appendChild(option);
    }
    select.value = current;
    return select;
  }

  netColourControl(net, current) {
    const wrap = element("div", "swatch");
    const shown = current || "#16202b";
    const button = element("button", "pswatch");
    button.type = "button";
    button.style.background = shown;
    button.title = current ? shown : `${shown} (default)`;
    button.setAttribute("aria-label", "wire colour");
    const apply = (value) => {
      this.store.mutate("wire colour", (d) => model.setNetStyle(d, net.id, "stroke", value));
      this.onChange();
      this.render();
    };
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openPalette(button, shown, apply);
    });
    const reset = element("button", "linkish", "reset");
    reset.type = "button";
    reset.title = "back to the default wire colour";
    reset.addEventListener("click", () => apply(null));
    wrap.appendChild(button);
    wrap.appendChild(reset);
    return wrap;
  }

  // Showing what each pin actually connects to is the cheap way to catch a
  // wire that only looks attached.
  renderPins(cell, symbol) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Pins"));
    const doc = this.store.doc;

    const labels = cell.pins || {};

    // One line per pin: its name on this instance. What it is wired to is on
    // the canvas already, and a line under each pin saying so doubled the
    // section's length; the direction and the wire stay in the tooltip.
    for (const pin of symbol.pins) {
      const touches = (endpoint) =>
        endpoint && endpoint.cell === cell.id && endpoint.pin === pin.name;
      const nets = doc.nets.filter(
        (net) => touches(net.from) || routing.loadsOf(net).some(touches));

      // Name the pin on this instance. Blank falls back to whatever the
      // symbol draws, which for a generic block is nothing at all.
      const field = input(labels[pin.name] || "");
      field.placeholder = pin.name;
      field.title = `${pin.dir}, ${nets.length
        ? nets.map((n) => n.name || n.id).join(", ") : "unconnected"}`;
      this.bind(field, (d, value) =>
        model.setPinLabel(d, cell.id, pin.name, value.trim()), "name pin");
      root.appendChild(row(pin.name, field));
    }
  }

  renderAppearance(items) {
    const root = this.root;
    root.appendChild(element("div", "ptitle", "Appearance"));
    const first = items[0].style || {};

    // A line has no inside, so a fill for it would do nothing.
    const open = items.every((item) => item.kind === "line" || item.kind === "polyline");
    // A shape starts with no fill, so what is behind it shows through; a
    // symbol's body starts white. Text is coloured by its fill, and
    // transparent text is no text, so it is not offered "No fill".
    const shapes = items.every((item) => model.isShape(item));
    const text = items.some((item) => item.kind === "text");
    for (const [key, label, fallback] of [
      ["fill", "Fill", shapes && !text ? "none" : "#ffffff"],
      ["stroke", "Line", "#16202b"],
    ]) {
      if (key === "fill" && open) continue;
      root.appendChild(row(label, this.colourControl(key, first[key], fallback,
                                                     key === "fill" && !text)));
    }

    // A soft shadow down and to the right, as a slide editor's default. Shapes
    // only: a cell is a symbol, and a shadow under a gate is not schematic.
    if (items.every((item) => model.isShape(item))) {
      const shadow = document.createElement("input");
      shadow.type = "checkbox";
      shadow.className = "pcheck";
      shadow.checked = items.every((item) => (item.style || {}).shadow);
      shadow.title = "a soft shadow below and to the right";
      shadow.addEventListener("change", () => {
        this.store.mutate(shadow.checked ? "shadow" : "no shadow", (doc) =>
          model.setStyle(doc, this.selection.ids, "shadow", shadow.checked || null));
        this.onChange();
      });
      root.appendChild(row("Shadow", shadow));
    }

    const weight = input(first.strokeWidth || 1.6, "number");
    weight.step = "0.1";
    weight.min = "0.2";
    this.bind(weight, (doc, value) => {
      const number = numberFrom(value);
      if (!(number > 0)) return false;
      model.setStyle(doc, this.selection.ids, "strokeWidth", number);
    }, "weight");
    root.appendChild(row("Weight", weight));
  }

  // Clicking the swatch opens a grid to pick from, the way a slide editor
  // does. The native colour dialog is still there behind "Custom", because a
  // grid of two dozen colours is the fast path and not the only one.
  colourControl(key, current, fallback, noFill = false) {
    const wrap = element("div", "swatch");
    const shown = current || fallback;

    const button = element("button", "pswatch");
    button.type = "button";
    if (shown === "none") button.classList.add("none");
    else button.style.background = shown;
    const named = shown === "none" ? "no fill" : shown;
    button.title = current ? named : `${named} (default)`;
    button.setAttribute("aria-label", `${key} colour`);

    const apply = (value) => {
      this.store.mutate("colour",
                        (doc) => model.setStyle(doc, this.selection.ids, key, value));
      this.onChange();
      this.render();
    };

    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openPalette(button, shown, apply, noFill);
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
        const number = numberFrom(value);
        if (!Number.isFinite(number) || number < 50) return false;
        d.canvas[key] = number;
      }, "sheet");
      root.appendChild(row(label, field));
    }

    const step = input(model.gridStep(doc), "number");
    step.min = "1";
    this.bind(step, (d, value) => {
      const number = numberFrom(value);
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

// A number field holding anything but a number reports "", and Number("") is
// 0 -- so clearing the X box moved the cell to the edge of the sheet, and
// clearing the weight drew its lines at width 0. Blank is not a number.
function numberFrom(value) {
  return String(value).trim() === "" ? NaN : Number(value);
}
