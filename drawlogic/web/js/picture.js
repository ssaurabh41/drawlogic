// Turning the drawing into a picture you can paste.
//
// A schematic usually ends up in a slide, and pasting is how it gets there.
// The SVG comes from Python -- the same render the CLI and Export SVG use --
// and is rasterised here, so the PNG on the clipboard is a picture of the
// exported file rather than a screenshot of the canvas with its selection
// handles, grid and scroll position in it.
//
// Usage:
//
//   import * as picture from "./picture.js";
//
//   const blob = await picture.rasterise(svgText, 2);   // 2x for slides
//   await picture.copy(blob);                            // may reject
//   picture.download(blob, "cdc_fifo.png");
//
// One caveat worth knowing: text inside a rasterised SVG is drawn with the
// fonts the system has, not the web font the page loaded, so a machine
// without IBM Plex falls back to Arial in the PNG. The SVG itself is
// unaffected.

// Sheet units are points; 2x reads crisply on a projector without being huge.
export const SCALE = 2;

export async function rasterise(svgText, scale = SCALE) {
  const size = sheetSize(svgText);
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
  try {
    const image = await load(url);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(size[0] * scale));
    canvas.height = Math.max(1, Math.round(size[1] * scale));
    const context = canvas.getContext("2d");
    // The SVG paints its own background, but a transparent export would
    // otherwise land on whatever colour the slide happens to be.
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await toBlob(canvas);
  } finally {
    URL.revokeObjectURL(url);
  }
}

// Width and height off the root element, falling back to the viewBox.
function sheetSize(svgText) {
  const width = /<svg[^>]*\bwidth="([\d.]+)"/.exec(svgText);
  const height = /<svg[^>]*\bheight="([\d.]+)"/.exec(svgText);
  if (width && height) return [Number(width[1]), Number(height[1])];
  const box = /viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"/.exec(svgText);
  if (box) return [Number(box[1]), Number(box[2])];
  return [1000, 700];
}

function load(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("could not read the drawing as an image"));
    image.src = url;
  });
}

function toBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("could not encode the picture"));
    }, "image/png");
  });
}

// Rejects when the browser will not allow a clipboard write -- an insecure
// origin, a missing permission, or a browser without ClipboardItem. The caller
// is expected to fall back to a download rather than leave the user with
// nothing.
export async function copy(blob) {
  if (!navigator.clipboard || typeof ClipboardItem === "undefined") {
    throw new Error("this browser cannot put a picture on the clipboard");
  }
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

export function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
