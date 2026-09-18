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
    GET  /api/drc          the DRC limits from drc.py
    GET  /api/theme        colours, weights and role painting from theme.py
    GET  /api/symbols      the symbol library, registry overrides included
    GET  /api/files        .dlg files under the served root
    GET  /api/doc?path=    one drawing
    POST /api/check        the DRC failures in the drawing in the body
    POST /api/doc?path=    save a drawing, re-emitted canonically
    POST /api/export       render to SVG, optionally writing it to disk
    POST /api/layout       rearrange a drawing and hand it back unwritten
    POST /api/symbol       turn the drawing into a symbol the palette offers

A drawing that references others comes back with a block symbol for each,
under `sheets`, because those blocks are built from the referenced drawings'
ports rather than read from the symbol library.

Client-supplied paths are resolved inside the served root and refused if they
escape it.
"""

import json
import os
import re
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import render_svg
from . import drc
from . import theme
from . import authoring
from . import layout
from . import sheets
from .doc import Document, DocumentError
from .symbols import (FOLDER_FILE, Symbol, SymbolError,
                      default_registry, load_folder)

# Letters, digits and underscores: a symbol id is a key in a JSON file and a
# type name in every drawing that uses it.
_SYMBOL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

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
  """Resolve a client-supplied path inside root, or None if it escapes.

  The name is checked first, then the destination it actually resolves to.
  Both are needed, and the second is the one that matters: `abspath` only
  tidies a path up as text, so a directory link inside the served folder --
  a symlink, or a junction on Windows -- reads as an ordinary child and lets
  a request walk straight out of the root, to read and to overwrite. The
  hierarchy loader has resolved links since a ref could point out; the
  requests that name a document directly were still going on the spelling.

  A file being saved for the first time does not exist yet. `realpath`
  resolves the part of the path that does, which is what settles this: the
  parent is where the link would be, so a new file under one still lands
  outside and is still refused.
  """
  if not relative:
    return None
  relative = unquote(relative).lstrip("/")
  if os.path.isabs(relative) or ".." in relative.split("/"):
    return None
  candidate = os.path.abspath(os.path.join(root, relative))
  if not sheets.inside(candidate, root):
    return None
  return candidate


def _issue_data(issue):
  """A reference fault in the same shape the browser already draws.

  `rule` is what the DRC pane prints as the name of the thing that failed, and
  a reference fault has no rule -- so it gets the word "reference", rather
  than the pane rendering a null.
  """
  return {
    "rule": issue.rule or "reference",
    "level": issue.level,
    "where": issue.where,
    "message": issue.message,
    "at": None,
  }


def _revision(path):
  """A cheap stand-in for "the version of this file I last saw".

  Size and modification time, which is all the editor needs to notice that a
  file changed underneath it between opening and saving. Not a hash: this is
  here to catch two tabs and stale responses, not to defend against anyone.
  """
  try:
    info = os.stat(path)
  except OSError:
    return None
  return "%d-%d" % (info.st_size, info.st_mtime_ns)


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
    self._started = True
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

  # ---- answering every request ----

  def _guard(self, handler):
    """Run a handler, and answer even when it goes wrong.

    Without this, an exception in a handler propagates out of the request,
    the socket is closed with nothing written, and the browser reports
    "Failed to fetch" -- which says only that the request did not finish, not
    what went wrong or even which end was at fault. A user hit exactly that on
    the Check button and there was nothing to go on from either side.

    So: the reason goes back as a 500 the editor can show, and the whole
    traceback goes to the terminal running the server, where the file and line
    are. The response is deliberately short on detail; the terminal is where
    you look, and it is the same machine.
    """
    self._started = False
    try:
      handler()
    except Exception as exc:
      sys.stderr.write("\n%s while handling %s %s\n%s\n"
                       % (type(exc).__name__, self.command, self.path,
                          traceback.format_exc()))
      if self._started:
        # The status line is already out, so there is nothing left to say
        # with. Closing the connection is all that is left.
        return
      self._fail(500, "%s: %s -- the terminal running drawlogic has the "
                      "traceback" % (type(exc).__name__, exc))

  # ---- GET ----

  def do_GET(self):
    self._guard(self._get)

  def do_POST(self):
    self._guard(self._post)

  def _get(self):
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
      return self._send_json(self.registry.as_data())

    if route == "/api/drc":
      # The drafting distances -- wire separation, cell spacing, label
      # clearance. Served for the same reason the theme is: a drag on the
      # canvas and a file from the exporter must obey one set of DRCs.
      return self._send_json(drc.as_data())

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
        "arrowSpacing": theme.ARROW_SPACING,
        "hopRadius": theme.HOP_RADIUS,
        "pinLabelInset": theme.PIN_LABEL_INSET,
        "titlePad": theme.TITLE_PAD,
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
        document, registry, problems = sheets.open_document(
          target, self.registry, confine=self.root)
      except DocumentError as exc:
        return self._fail(422, str(exc))
      except OSError as exc:
        return self._fail(500, "cannot read: %s" % exc)
      # A block standing in for another drawing belongs to this drawing, not
      # to the library, so it travels with it. The editor merges it in on open.
      return self._send_json({
        "path": relative,
        "revision": _revision(target),
        "doc": document.ordered(),
        "sheets": {type_id: data
                   for type_id, data in registry.as_data().items()
                   if type_id.startswith("sheet:")},
        "problems": [{"level": p.level, "where": p.where, "message": p.message}
                     for p in problems],
      })

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

  def _post(self):
    route = urlparse(self.path).path
    payload = self._body()
    if payload is None:
      return self._fail(400, "expected a JSON body")
    # Every handler below reads the body with .get(). A JSON array or string
    # parses happily and then fails on that call, which killed the connection
    # without ever sending a status line.
    if not isinstance(payload, dict):
      return self._fail(400, "expected a JSON object, not %s"
                        % type(payload).__name__)

    if route == "/api/doc":
      return self._save(payload)
    if route == "/api/export":
      return self._export(payload)
    if route == "/api/layout":
      return self._layout(payload)
    if route == "/api/check":
      return self._check(payload)
    if route == "/api/symbol":
      return self._save_symbol(payload)
    return self._fail(404, "no such endpoint")

  def _save(self, payload):
    relative = self._param("path") or payload.get("path")
    target = _safe_join(self.root, relative)
    if target is None:
      return self._fail(400, "path is outside the served directory")
    if not target.endswith(".dlg"):
      return self._fail(400, "drawings must be saved as .dlg")

    # "create" means the caller believes this file does not exist yet. The
    # browser used to decide that for itself by matching the typed name
    # against its own file list, which is a list of exact spellings: typing
    # "./sheet.dlg" for a file listed as "sheet.dlg" looked like a new name,
    # skipped the overwrite warning, and replaced the drawing. Only the
    # server knows what the path really resolves to, so only the server can
    # answer the question.
    if payload.get("create") and os.path.exists(target):
      return self._fail(409, "%s already exists" % relative)

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

    return self._send_json({"path": relative, "bytes": len(text),
                            "revision": _revision(target)})

  def _layout(self, payload):
    """Lay a drawing out and hand it back, without writing anything.

    The editor replaces its document with the answer, as one undo step. Doing
    the work here rather than in the browser keeps the arranging in one place,
    the same way rendering is; a layout is not a gesture, so a round trip
    costs nothing.
    """
    try:
      document = Document.from_data(payload.get("doc") or {})
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    registry = self.registry
    source = payload.get("source")
    if source:
      resolved = _safe_join(self.root, source)
      if resolved is None:
        return self._fail(400, "source is outside the served directory")
      document.path = resolved
      registry = self.registry.copy()
      # Confined to the served folder: a ref is written by whoever wrote the
      # document, and this one arrived in a request body.
      sheets.resolve(document, registry, confine=self.root)

    options = payload.get("options") or {}
    try:
      result = layout.arrange(
        document, registry,
        gap_x=float(options.get("gapX", layout.GAP_X)),
        gap_y=float(options.get("gapY", layout.GAP_Y)))
    except (TypeError, ValueError) as exc:
      return self._fail(422, "cannot lay out: %s" % exc)

    return self._send_json({"doc": document.ordered(), "note": str(result),
                            "shapes": len(document.shapes)})


  def _check(self, payload):
    """Report everything wrong with the drawing in the request.

    The editor sends what is on the canvas rather than what is on disk, so the
    answer is about the drawing being worked on, and it comes from the same
    modules the command line uses -- so a drawing that passes here passes
    `drawlogic validate` too.

    Both halves of that, which is the point. This used to run the geometric
    DRCs alone and throw away what resolving the hierarchy said, so a drawing
    naming a cell type that does not exist came back "clean" from Check and
    was rejected by the command line a moment later. A checker that reports a
    drawing as fine when a supported command calls it broken is worse than one
    that does not run: the clean bill is what stops you looking further.

    Reference faults arrive with no `at`, because there is no one point on the
    sheet to walk to -- an unknown cell type is about the cell, not a place --
    so they list without a marker rather than ringing the wrong spot.
    """
    try:
      document = Document.from_data(payload.get("doc") or {})
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    registry = self.registry
    issues = []
    source = payload.get("source")
    if source:
      resolved = _safe_join(self.root, source)
      if resolved is None:
        return self._fail(400, "source is outside the served directory")
      document.path = resolved
      registry = self.registry.copy()
      issues.extend(sheets.resolve(document, registry, confine=self.root))

    issues.extend(document.validate(registry))
    found = [_issue_data(issue) for issue in issues]
    found.extend(violation.as_data() for violation in drc.check(document, registry))
    return self._send_json({
      "violations": found,
      "errors": len([v for v in found if v["level"] == "error"]),
      "warnings": len([v for v in found if v["level"] != "error"]),
    })


  def _save_symbol(self, payload):
    """Turn the open drawing into a symbol and add it to the folder's library.

    Written next to the drawings, under the name every reader already looks
    for, so `drawlogic export` sees it without being told about it.
    """
    try:
      document = Document.from_data(payload.get("doc") or {})
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    symbol_id = str(payload.get("id") or "").strip()
    if not _SYMBOL_ID.match(symbol_id):
      return self._fail(400, "a symbol id is letters, digits and underscores")

    try:
      data = authoring.symbol_from(document, symbol_id,
                                   name=payload.get("name"),
                                   category=payload.get("category") or "custom")
      authoring.add_to_file(os.path.join(self.root, FOLDER_FILE),
                            symbol_id, data)
    except (authoring.AuthoringError, SymbolError) as exc:
      return self._fail(422, str(exc))
    except OSError as exc:
      return self._fail(500, "cannot write: %s" % exc)

    self.registry.add(Symbol(symbol_id, data),
                      source=os.path.join(self.root, FOLDER_FILE))
    return self._send_json({"id": symbol_id, "symbols": self.registry.as_data()})


  def _export(self, payload):
    try:
      document = Document.from_data(payload.get("doc") or {})
    except (DocumentError, TypeError, ValueError) as exc:
      return self._fail(422, "document is not valid: %s" % exc)

    # Where the drawing came from, so a `ref` in it still means the same file.
    # Without this an export of a hierarchy would draw its blocks as empty.
    registry = self.registry
    source = payload.get("source")
    if source:
      resolved = _safe_join(self.root, source)
      if resolved is None:
        return self._fail(400, "source is outside the served directory")
      document.path = resolved
      registry = self.registry.copy()
      # Confined to the served folder: a ref is written by whoever wrote the
      # document, and this one arrived in a request body.
      sheets.resolve(document, registry, confine=self.root)

    options = payload.get("options") or {}
    try:
      svg = render_svg.render(
        document,
        registry=registry,
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

  registry = (registry or default_registry()).copy()
  folder_file = load_folder(registry, root)

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
  if folder_file:
    print("  with your own symbols from %s" % os.path.basename(folder_file))
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
