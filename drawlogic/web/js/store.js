// The document, plus undo/redo.
//
// Undo keeps whole-document snapshots rather than inverse operations. A
// schematic is a few hundred kilobytes at worst, and a snapshot cannot get out
// of step with the thing it is meant to undo -- which inverse operations
// routinely do once features start interacting.

const LIMIT = 120;

export class Store {
  constructor() {
    this.doc = null;
    this.path = null;
    this.dirty = false;
    this._undo = [];
    this._redo = [];
    this._listeners = [];
  }

  subscribe(listener) {
    this._listeners.push(listener);
    return () => {
      this._listeners = this._listeners.filter((l) => l !== listener);
    };
  }

  emit(reason) {
    for (const listener of this._listeners) listener(this, reason);
  }

  load(doc, path) {
    this.doc = doc;
    this.path = path;
    this.dirty = false;
    this._undo = [];
    this._redo = [];
    this.emit("load");
  }

  snapshot() {
    return JSON.parse(JSON.stringify(this.doc));
  }

  // A drag fires a mutation per pointer move, but should undo as one step.
  // Opening a gesture makes every mutation inside it share the first snapshot.
  beginGesture(label) {
    this._gesture = label;
    this._gestureOpen = false;
  }

  endGesture() {
    this._gesture = null;
    this._gestureOpen = false;
  }

  // Every document change goes through here, so undo and the dirty marker can
  // never be forgotten at a call site.
  mutate(label, change) {
    if (!this.doc) return null;
    const before = this.snapshot();
    const result = change(this.doc);
    if (result === false) return null;

    const inGesture = this._gesture !== null && this._gesture !== undefined;
    if (!inGesture || !this._gestureOpen) {
      this._undo.push({ label, doc: before });
      if (this._undo.length > LIMIT) this._undo.shift();
      if (inGesture) this._gestureOpen = true;
    }

    this._redo = [];
    this.dirty = true;
    this.emit("mutate");
    return result;
  }

  canUndo() { return this._undo.length > 0; }

  canRedo() { return this._redo.length > 0; }

  undo() {
    if (!this._undo.length) return false;
    const entry = this._undo.pop();
    this._redo.push({ label: entry.label, doc: this.snapshot() });
    this.doc = entry.doc;
    this.dirty = true;
    this.emit("undo");
    return entry.label;
  }

  redo() {
    if (!this._redo.length) return false;
    const entry = this._redo.pop();
    this._undo.push({ label: entry.label, doc: this.snapshot() });
    this.doc = entry.doc;
    this.dirty = true;
    this.emit("redo");
    return entry.label;
  }

  markSaved() {
    this.dirty = false;
    this.emit("saved");
  }
}
