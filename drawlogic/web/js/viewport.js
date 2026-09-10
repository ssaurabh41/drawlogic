// Pan and zoom.
//
// Geometry always stays in document units; only the viewBox moves. That is
// the same mechanism the exporter's --zoom uses, so what you see on screen
// and what lands in the file agree.

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 8;

export class Viewport {
  constructor(svg, onChange) {
    this.svg = svg;
    this.onChange = onChange || (() => {});
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this._bind();
  }

  size() {
    const rect = this.svg.getBoundingClientRect();
    return [Math.max(rect.width, 1), Math.max(rect.height, 1)];
  }

  apply() {
    const [w, h] = this.size();
    this.svg.setAttribute(
      "viewBox",
      `${this.panX} ${this.panY} ${w / this.zoom} ${h / this.zoom}`
    );
    this.onChange(this);
  }

  setZoom(zoom, anchor) {
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
    if (anchor) {
      // Keep the point under the cursor still while the scale changes.
      const before = this.toDoc(anchor[0], anchor[1]);
      this.zoom = next;
      const after = this.toDoc(anchor[0], anchor[1]);
      this.panX += before[0] - after[0];
      this.panY += before[1] - after[1];
    } else {
      const [w, h] = this.size();
      const cx = this.panX + w / this.zoom / 2;
      const cy = this.panY + h / this.zoom / 2;
      this.zoom = next;
      this.panX = cx - w / this.zoom / 2;
      this.panY = cy - h / this.zoom / 2;
    }
    this.apply();
  }

  toDoc(clientX, clientY) {
    const rect = this.svg.getBoundingClientRect();
    return [
      this.panX + (clientX - rect.left) / this.zoom,
      this.panY + (clientY - rect.top) / this.zoom,
    ];
  }

  fit(canvasWidth, canvasHeight, margin = 40) {
    const [w, h] = this.size();
    this.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.min(
      (w - margin) / canvasWidth, (h - margin) / canvasHeight)));
    this.panX = canvasWidth / 2 - w / this.zoom / 2;
    this.panY = canvasHeight / 2 - h / this.zoom / 2;
    this.apply();
  }

  _bind() {
    let panning = false;
    let last = [0, 0];

    const start = (event) => {
      // Middle button, or space held, or any drag on empty workspace.
      if (event.button !== 1 && event.button !== 0) return;
      if (event.button === 0 && !event.shiftKey && !this.spaceHeld) return;
      panning = true;
      last = [event.clientX, event.clientY];
      this.svg.classList.add("panning");
      event.preventDefault();
    };

    const move = (event) => {
      if (!panning) return;
      this.panX -= (event.clientX - last[0]) / this.zoom;
      this.panY -= (event.clientY - last[1]) / this.zoom;
      last = [event.clientX, event.clientY];
      this.apply();
    };

    const stop = () => {
      panning = false;
      this.svg.classList.remove("panning");
    };

    this.svg.addEventListener("mousedown", start);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);

    this.svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0015);
      this.setZoom(this.zoom * factor, [event.clientX, event.clientY]);
    }, { passive: false });

    window.addEventListener("keydown", (event) => {
      if (event.code === "Space" && !event.repeat
          && event.target === document.body) {
        this.spaceHeld = true;
        this.svg.classList.add("grabbable");
        event.preventDefault();
      }
    });
    window.addEventListener("keyup", (event) => {
      if (event.code === "Space") {
        this.spaceHeld = false;
        this.svg.classList.remove("grabbable");
      }
    });

    window.addEventListener("resize", () => this.apply());
  }
}
