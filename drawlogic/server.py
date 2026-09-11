"""Local web server for the browser editor.

Binds to the loopback interface and serves exactly one directory of drawings,
so nothing outside the folder you point it at is reachable. Export goes
through render_svg, the same code path the CLI uses, so what you export from
the browser and what you export from the terminal are the same bytes.

Usage:

    from drawlogic.server import serve
    from drawlogic.symbols import default_registry

    serve(root="~/schematics", port=8080, registry=default_registry())

Endpoints:

    GET  /                 the editor page
    GET  /api/theme        colours, weights and role painting from theme.py
    GET  /api/symbols      the symbol library, registry overrides included
    GET  /api/files        .dlg files under the served root
    GET  /api/doc?path=    one drawing
    POST /api/doc?path=    save a drawing, re-emitted canonically
    POST /api/export       render to SVG, optionally writing it to disk

Client-supplied paths are resolved inside the served root and refused if they
escape it.
"""

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import render_svg
from . import theme
from .doc import Document, DocumentError

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
}

# A schematic is text; anything near this size is a mistake or an attack.
MAX_BODY = 16 * 1024 * 1024


def _safe_join(root, relative):
  """Resolve a client-supplied path inside root, or None if it escapes."""
  if not relative:
    return None
  relative = unquote(relative).lstrip("/")
  if os.path.isabs(relative) or ".." in relative.split("/"):
    return None
  candidate = os.path.abspath(os.path.join(root, relative))
  root = os.path.abspath(root)
  if candidate != root and not candidate.startswith(root + os.sep):
    return None
  return candidate


def _symbol_payload(registry):
  """The symbol library as the browser needs it, straight from the registry.

  The editor draws from the same definitions the exporter uses, including any
  --symbols-dir overrides, so the two cannot disagree about a shape.
  """
  out = {}
  for type_id in registry.ids():
    symbol = registry.require(type_id)
    out[type_id] = {
      "name": symbol.name,
      "category": symbol.category,
      "size": [symbol.width, symbol.height],
      "pins": symbol.pins,
      "draw": symbol.draw,
    }
  return out


class Handler(BaseHTTPRequestHandler):

  server_version = "drawlogic"
  root = "."
  registry = None
  quiet = False

  def log_message(self, fmt, *args):
    if not self.quiet:
      BaseHTTPRequestHandler.log_message(self, fmt, *args)

  # ---- plumbing ----

  def _send(self, status, content_type, body):
    if isinstance(body, str):
      body = body.encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    if self.command != "HEAD":
      self.wfile.write(body)

  def _send_json(self, payload, status=200):
    self._send(status, CONTENT_TYPES[".json"], json.dumps(payload))

  def _fail(self, status, message):
    self._send_json({"error": message}, status)

  def _body(self):
    try:
      length = int(self.headers.get("Content-Length", 0))
    except ValueError:
      return None
    if length <= 0 or length > MAX_BODY:
      return None
    try:
      return json.loads(self.rfile.read(length).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
      return None

  def _query(self):
    return parse_qs(urlparse(self.path).query)

  def _param(self, name):
    values = self._query().get(name)
    return values[0] if values else None

  # ---- GET ----

  def do_GET(self):
    route = urlparse(self.path).path

    if route.startswith("/api/"):
      return self._api_get(route)

    if route == "/favicon.ico":
      # Browsers ask for this unprompted; answering "nothing here" keeps the
      # console clean without shipping an icon.
      self.send_response(204)
      self.send_header("Content-Length", "0")
      self.end_headers()
      return None

    if route == "/":
      route = "/index.html"
    target = _safe_join(WEB_DIR, route)
    if target is None or not os.path.isfile(target):
      return self._fail(404, "not found")

    extension = os.path.splitext(target)[1]
    with open(target, "rb") as handle:
      self._send(200, CONTENT_TYPES.get(extension, "application/octet-stream"),
                 handle.read())

  def _api_get(self, route):
    if route == "/api/symbols":
      return self._send_json(_symbol_payload(self.registry))

    if route == "/api/theme":
      # Served rather than restated in JS, so the canvas and the exporter
      # cannot drift apart on colours, weights or role painting.
      return self._send_json({
        "colors": theme.COLORS,
        "widths": theme.WIDTHS,
        "fontSizes": theme.FONT_SIZES,
        "roleStyles": theme.ROLE_STYLES,
        "fontSans": theme.FONT_SANS,
        "fontMono": theme.FONT_MONO,
        "junctionRadius": theme.JUNCTION_RADIUS,
        "arrowSize": theme.ARROW_SIZE,
        "hopRadius": theme.HOP_RADIUS,
        "gridStyles": list(theme.GRID_STYLES),
      })

    if route == "/api/files":
      return self._send_json({"root": os.path.abspath(self.root),
                              "files": self._list_drawings()})

    if route == "/api/doc":
      relative = self._param("path")
      target = _safe_join(self.root, relative)
      if target is None:
        return self._fail(400, "path is outside the served directory")
      if not target.endswith(".dlg"):
        return self._fail(400, "only .dlg files can be opened")
      if not os.path.isfile(target):
        return self._fail(404, "no such drawing")
      try:
        document = Document.load(target)
      except DocumentError as exc:
        return self._fail(422, str(exc))
      except OSError as exc:
        return self._fail(500, "cannot read: %s" % exc)
      return self._send_json({"path": relative, "doc": document.ordered()})

    return self._fail(404, "no such endpoint")

  def _list_drawings(self):
    found = []
    root = os.path.abspath(self.root)
    for directory, subdirs, names in os.walk(root):
      subdirs[:] = [d for d in subdirs if not d.startswith(".")]
      for name in sorted(names):
        if name.endswith(".dlg"):
          full = os.path.join(directory, name)
          found.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return sorted(found)

  # ---- POST ----

  def do_POST(self):
    route = urlparse(self.path).path
    payload = self._body()
    if payload is None:
      return self._fail(400, "expected a JSON body")

    if route == "/api/doc":
      return self._save(payload)
    if route == "/api/export":
      return self._export(payload)
    return self._fail(404, "no such endpoint")

  def _save(self, payload):
    relative = self._param("path") or payload.get("path")
    target = _safe_join(self.root, relative)
    if target is None:
      return self._fail(400, "path is outside the served directory")
    if not target.endswith(".dlg"):
      return self._fail(400, "drawings must be saved as .dlg")

    try:
      # Round-tripping through Document is what keeps the file canonical:
      # stable key order and filled defaults regardless of what the browser
      # sent, so saved files stay diffable.
      document = Document.from_data(payload.get("doc") or {})
      text = document.dumps()
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    try:
      parent = os.path.dirname(target)
      if parent and not os.path.isdir(parent):
        os.makedirs(parent)
      with open(target, "w") as handle:
        handle.write(text)
    except OSError as exc:
      return self._fail(500, "cannot write: %s" % exc)

    return self._send_json({"path": relative, "bytes": len(text)})

  def _export(self, payload):
    try:
      document = Document.from_data(payload.get("doc") or {})
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    options = payload.get("options") or {}
    try:
      svg = render_svg.render(
        document,
        registry=self.registry,
        zoom=float(options.get("zoom", 1.0)),
        width=options.get("width"),
        margin=options.get("margin"),
        background=options.get("background"),
        show_grid=bool(options.get("grid", False)),
        crop=bool(options.get("crop", False)),
        title=bool(options.get("title", True)))
    except (TypeError, ValueError) as exc:
      return self._fail(422, "cannot render: %s" % exc)

    relative = payload.get("path")
    if not relative:
      return self._send(200, CONTENT_TYPES[".svg"], svg)

    target = _safe_join(self.root, relative)
    if target is None:
      return self._fail(400, "path is outside the served directory")
    if not target.endswith(".svg"):
      return self._fail(400, "exports must be written as .svg")
    try:
      with open(target, "w") as handle:
        handle.write(svg)
    except OSError as exc:
      return self._fail(500, "cannot write: %s" % exc)
    return self._send_json({"path": relative, "bytes": len(svg)})


def serve(root=".", host="127.0.0.1", port=8080, registry=None,
          open_browser=True, initial=None, quiet=False):
  """Run the editor server until interrupted."""
  root = os.path.abspath(root)
  if not os.path.isdir(root):
    raise ValueError("no such directory: %s" % root)

  handler = type("BoundHandler", (Handler,), {
    "root": root,
    "registry": registry,
    "quiet": quiet,
  })

  httpd = ThreadingHTTPServer((host, port), handler)
  url = "http://%s:%d/" % (host, httpd.server_port)
  if initial:
    url += "?open=" + initial

  print("drawlogic serving %s" % root)
  print("  %s" % url)
  if host in ("127.0.0.1", "localhost"):
    print("  (loopback only; for a remote box use: ssh -L %d:localhost:%d you@host)"
          % (httpd.server_port, httpd.server_port))
  print("  Ctrl+C to stop")

  if open_browser:
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()

  try:
    httpd.serve_forever()
  except KeyboardInterrupt:
    print("")
  finally:
    httpd.server_close()
  return 0
