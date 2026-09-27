// Unsaved work, kept in the browser until it is saved.
//
// The close-tab warning covers a tab closed on purpose, and nothing else: a
// crashed browser, a killed process or a laptop that ran out of battery lost
// every edit since the last Ctrl+S. So while a drawing has unsaved changes a
// copy of it sits in localStorage, and opening that drawing again offers it
// back. Saving it -- or saying no -- throws the copy away.
//
// It is a safety net, not autosave: nothing is written to the file on disk
// that the user did not save.


const PREFIX = "drawlogic.recover:";
const DELAY = 800;

function key(path) {
  // Keyed by server as well as file, so two servers on different ports
  // serving folders that both hold a "top.dlg" do not offer each other's work.
  return `${PREFIX}${window.location.host}|${path}`;
}

function read(path) {
  try {
    const raw = window.localStorage.getItem(key(path));
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    return null;
  }
}

export function discard(path) {
  try {
    window.localStorage.removeItem(key(path));
  } catch (error) {
    // Storage switched off: there was nothing kept to discard.
  }
}

// The kept copy for a drawing, if it says something the file does not.
export function pending(path, doc) {
  const entry = read(path);
  if (!entry || !entry.doc) return null;
  if (JSON.stringify(entry.doc) === JSON.stringify(doc)) {
    discard(path);
    return null;
  }
  return entry;
}

// Keep a copy whenever the drawing changes and is not saved; drop it when it
// is. `onFull` hears once if the browser refuses to store it -- a drawing
// with large embedded pictures can outgrow what localStorage allows.
export function watch(store, onFull) {
  let timer = null;
  let warned = false;

  const keep = () => {
    timer = null;
    if (!store.doc || !store.path || !store.dirty) return;
    try {
      window.localStorage.setItem(key(store.path), JSON.stringify({
        savedAt: Date.now(), doc: store.doc,
      }));
    } catch (error) {
      if (!warned) {
        warned = true;
        onFull();
      }
    }
  };

  store.subscribe((_store, reason) => {
    if (reason === "saved") {
      window.clearTimeout(timer);
      timer = null;
      if (store.path) discard(store.path);
      return;
    }
    if (reason === "load") return;
    window.clearTimeout(timer);
    timer = window.setTimeout(keep, DELAY);
  });

  // A tab closing mid-delay would lose the last edit, which is the one most
  // likely to matter.
  window.addEventListener("pagehide", () => {
    if (timer !== null) {
      window.clearTimeout(timer);
      keep();
    }
  });
}
