"""Command line entry points.

Usage:

    drawlogic help                      # overview with examples
    drawlogic help export               # detail for one command

    drawlogic serve alu_ctrl.dlg        # open the browser editor
    drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --zoom 2
    drawlogic validate alu_ctrl.dlg     # references and DRCs; non-zero on errors
    drawlogic doctor                    # is this copy of drawlogic consistent?
    drawlogic info alu_ctrl.dlg
    drawlogic symbols list

Run with nothing, or with --help, for the same overview.
"""

import argparse
import hashlib
import os
import re
import sys

from . import drc
from . import render_svg
from .doc import Document, DocumentError
from . import layout
from . import sheets
from .symbols import SymbolError, load_registry
from . import MIN_PYTHON

PROG = "drawlogic"
VERSION = "0.1.0"


def _quiet(args):
  return getattr(args, "quiet", False)


def _registry(args):
  extra = []
  for directory in (getattr(args, "symbols_dir", None) or []):
    extra.append(directory)
  return load_registry(extra)


def _load(path):
  try:
    return Document.load(path)
  except (IOError, OSError) as exc:
    raise SystemExit("%s: cannot read %s: %s" % (PROG, path, exc))
  except DocumentError as exc:
    raise SystemExit("%s: %s: %s" % (PROG, path, exc))


def _open(path, registry):
  """Load a drawing and the symbols it needs, references included.

  Returns the drawing, its own registry, and whatever went wrong resolving
  those references, which each caller reports in its own way.
  """
  try:
    return sheets.open_document(path, registry)
  except (IOError, OSError) as exc:
    raise SystemExit("%s: cannot read %s: %s" % (PROG, path, exc))
  except DocumentError as exc:
    raise SystemExit("%s: %s: %s" % (PROG, path, exc))


def _report_refs(path, problems):
  """Warn about unresolved references without refusing to do the work.

  A broken reference is drawn as a labelled empty box, so the output says what
  is wrong far better than a refusal to produce it would.
  """
  for problem in problems:
    sys.stderr.write("%s: %s: %s: %s\n"
                     % (PROG, path, problem.where, problem.message))


def _output_path(source, args, count):
  if args.output and count == 1:
    return args.output
  base = os.path.splitext(os.path.basename(source))[0] + ".svg"
  if args.outdir:
    return os.path.join(args.outdir, base)
  return os.path.join(os.path.dirname(source), base)


def cmd_export(args):
  registry = _registry(args)
  background = None
  if args.bg:
    background = "none" if args.bg == "transparent" else args.bg

  if args.output and args.outdir:
    raise SystemExit("%s: use either --output or --outdir, not both" % PROG)
  if args.output == "-" and len(args.files) > 1:
    raise SystemExit("%s: cannot write several drawings to stdout" % PROG)
  if args.outdir and not os.path.isdir(args.outdir):
    os.makedirs(args.outdir)

  for source in args.files:
    doc, sheet_registry, problems = _open(source, registry)
    _report_refs(source, problems)
    svg = render_svg.render(
      doc, registry=sheet_registry, zoom=args.zoom, width=args.width,
      margin=args.margin, background=background,
      show_grid=args.grid, crop=args.crop, title=not args.no_title,
      # None means "do what the document's own canvas.arrows/hops say" --
      # passing False here whenever the flag was merely absent overrode that
      # choice on every export, so a document saved with either turned off
      # came out through the CLI with both back on, disagreeing with what
      # the same document exports as through the editor.
      arrows=False if args.no_arrows else None,
      hops=False if args.no_hops else None)

    if args.output == "-":
      sys.stdout.write(svg)
      continue

    target = _output_path(source, args, len(args.files))
    with open(target, "w") as handle:
      handle.write(svg)
    if not _quiet(args):
      sys.stderr.write("wrote %s\n" % target)
  return 0


def cmd_serve(args):
  from . import server

  root = args.dir
  initial = None
  if args.file:
    if not os.path.isfile(args.file):
      raise SystemExit("%s: no such drawing: %s" % (PROG, args.file))
    if root is None:
      root = os.path.dirname(os.path.abspath(args.file)) or "."
    initial = os.path.relpath(os.path.abspath(args.file), os.path.abspath(root))
    if initial.startswith(".."):
      raise SystemExit("%s: %s is outside --dir" % (PROG, args.file))
  if root is None:
    root = "."

  try:
    return server.serve(
      root=root, host=args.host, port=args.port,
      registry=_registry(args), open_browser=not args.no_browser,
      initial=initial, quiet=_quiet(args))
  except ValueError as exc:
    raise SystemExit("%s: %s" % (PROG, exc))
  except OSError as exc:
    raise SystemExit("%s: cannot serve on %s:%d: %s"
                     % (PROG, args.host, args.port, exc))


def cmd_info(args):
  registry = _registry(args)
  doc, registry, problems = _open(args.file, registry)
  _report_refs(args.file, problems)
  box = doc.content_bbox(registry)

  print("title    %s" % doc.title)
  print("canvas   %g x %g" % (doc.canvas["width"], doc.canvas["height"]))
  grid = doc.canvas.get("grid") or {}
  print("grid     %s, step %g" % (grid.get("style"), grid.get("size", 0)))
  print("font     %s, scale %g" % ((doc.canvas.get("font") or {}).get("family"),
                                   doc.font_scale))
  print("cells    %d" % len(doc.cells))
  print("nets     %d" % len(doc.nets))
  print("shapes   %d" % len(doc.shapes))
  print("groups   %d" % len(doc.groups))
  if box:
    print("content  x %g y %g w %g h %g" % box)
  else:
    print("content  empty")

  counts = {}
  for cell in doc.cells:
    counts[cell.get("type")] = counts.get(cell.get("type"), 0) + 1
  if counts:
    print("")
    print("by type")
    for type_id in sorted(counts):
      print("  %-12s %d" % (type_id, counts[type_id]))

  rows = sheets.tree(doc, registry)
  if rows:
    print("")
    print("hierarchy")
    for depth, ref, child in rows:
      detail = "%d cells, %d nets" % (len(child.cells), len(child.nets)) \
        if child is not None else "cannot be read"
      print("  %s%s  (%s)" % ("  " * depth, ref, detail))
  return 0


def cmd_layout(args):
  """Rearrange a drawing so it reads left to right, and write it back."""
  registry = _registry(args)
  doc, registry, problems = _open(args.file, registry)
  _report_refs(args.file, problems)

  result = layout.arrange(doc, registry, gap_x=args.gap_x, gap_y=args.gap_y)
  target = args.output or args.file
  try:
    doc.save(target)
  except OSError as exc:
    raise SystemExit("%s: cannot write %s: %s" % (PROG, target, exc))

  if not _quiet(args):
    print("%s: %s" % (target, result))
    if doc.shapes:
      # Only cells are moved, because nothing says which cell a band or a
      # caption belongs to.
      print("%d shape%s left where they were; they may need nudging"
            % (len(doc.shapes), "" if len(doc.shapes) == 1 else "s"))
  return 0


def _issue_line(issue):
  """One problem, with the rule that found it when there was one.

  Naming the rule is what makes the message actionable: it is the heading to
  look up in drc.py, where the distance and the reason for it are written
  down. Reference faults have no rule to name, so they simply have none.
  """
  if issue.rule:
    return "%s  %s: %s" % (issue.rule, issue.where, issue.message)
  return "%s: %s" % (issue.where, issue.message)


def cmd_doctor(args):
  """Check that this copy of drawlogic is internally consistent.

  Three separate bug reports in a row turned out to be one thing: files copied
  across one at a time, so the Python and the JavaScript were from different
  versions of the project and called into functions the other half no longer
  had. Every one of them surfaced as something that looked like a real bug --
  a browser that would not draw, a Check that crashed, a colour picker that
  was not there.

  None of that is visible by reading a file. It is visible by asking whether
  the pieces still fit each other, which is what this does: run the Python end
  to end on a drawing built here, then read every browser module and check
  that each thing it imports is really exported by the file it names.

  It also hashes this copy against manifest.txt. That used to say "deliberately
  not a checksum against a manifest", for two good reasons -- a manifest goes
  stale, and a byte-for-byte one fails on a changed line ending as loudly as on
  a missing function. Both are answered rather than ignored: the hash is of
  normalised text, and the manifest is generated with --write-manifest and
  guarded by tests/test_manifest.py, so a stale one turns the suite red.
  """
  if getattr(args, "write_manifest", False):
    target = os.path.join(_repo_root(), MANIFEST_NAME)
    with open(target, "w") as handle:
      handle.write(manifest_text())
    print("wrote %s (%d files)" % (target, len(manifest_files())))
    return 0

  problems = []

  def report(what, detail=None):
    problems.append(what if detail is None else "%s: %s" % (what, detail))

  print("drawlogic %s" % VERSION)
  running = sys.version_info[:2]
  if running < MIN_PYTHON:
    # Not an error -- it may well work, and saying so is more useful than
    # refusing to run. It is simply untested below the floor, and anything
    # odd that follows should be read in that light.
    print("python    %s (below the tested floor of %d.%d -- untested here)"
          % (sys.version.split()[0], MIN_PYTHON[0], MIN_PYTHON[1]))
  else:
    print("python    %s" % sys.version.split()[0])
  print("here      %s" % os.path.dirname(os.path.abspath(__file__)))
  print("")

  # ---- the Python half, exercised rather than inspected ----
  try:
    from . import doc as doc_module
    from . import drc, layout, routing, symbols
    registry = symbols.default_registry()
    sheet = doc_module.new_document("doctor", 600, 400)
    sheet.cells.extend([
      {"id": "p", "type": "port_in", "x": 60, "y": 180, "label": "p"},
      {"id": "u", "type": "and2", "x": 300, "y": 160, "label": "u"},
    ])
    sheet.nets.append({"id": "n", "name": "w",
                       "from": {"cell": "p", "pin": "p"},
                       "to": [{"cell": "u", "pin": "a"}]})
    sheet.normalize()

    steps = [
      ("route a wire", lambda: routing.route_all(sheet, registry)),
      ("check the rules", lambda: drc.check(sheet, registry)),
      ("lay it out", lambda: layout.arrange(sheet, registry)),
      ("render to SVG", lambda: render_svg.render(sheet, registry)),
    ]
    for what, run in steps:
      try:
        run()
        print("ok    %s" % what)
      except Exception as exc:
        print("FAIL  %s" % what)
        report(what, "%s: %s" % (type(exc).__name__, exc))
  except Exception as exc:
    print("FAIL  load the python modules")
    report("importing drawlogic", "%s: %s" % (type(exc).__name__, exc))

  print("%d built-in symbols" % len(_registry(args).ids()))

  # ---- the browser half, read rather than run ----
  web = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "js")
  mismatches, modules = _js_imports(web)
  if modules is None:
    print("FAIL  read %s" % web)
    report("browser modules", "cannot read %s" % web)
  else:
    for line in mismatches:
      report("browser modules", line)
    print("%s  %d browser modules, %d import mismatches"
          % ("ok   " if not mismatches else "FAIL ", modules, len(mismatches)))

  # ---- the files themselves, against the manifest ----
  listed, counted = _check_manifest()
  if counted is None:
    print("--    no %s here, so file contents were not checked"
          % MANIFEST_NAME)
  else:
    for line in listed:
      report("files", line)
    print("%s  %d files against %s, %d differ"
          % ("ok   " if not listed else "FAIL ", counted, MANIFEST_NAME,
             len(listed)))

  print("")
  if not problems:
    print("this copy is consistent with itself")
    return 0
  print("%d problem(s):" % len(problems))
  for line in problems:
    print("  %s" % line)
  print("")
  print("Files from different versions of the project cannot work together.")
  print("Take the whole repository at once rather than file by file:")
  print("  git clone https://github.com/ssaurabh41/drawlogic")
  print("or download and unzip .../drawlogic/archive/refs/heads/main.zip")
  return 1


# Files whose contents have to be right for drawlogic to work: the package
# itself, the symbol library and everything the browser is served. Not the
# examples or the tests -- a broken example announces itself the moment you
# open it, and a broken test announces itself when you run the suite.
MANIFEST_NAME = "manifest.txt"


def _package_root():
  return os.path.dirname(os.path.abspath(__file__))


def _repo_root():
  return os.path.dirname(_package_root())


def content_hash(path):
  """A file's SHA-256, taken after line endings are made uniform.

  Not the hash of the bytes on disk. Git rewrites line endings on checkout by
  default on Windows, so a byte-for-byte manifest reports every single file as
  wrong on a perfectly good clone -- which is exactly what happened when one
  was handed over: all 28 files "mismatched", none of them actually different.

  A checker that cries wolf is worse than none, because the next real
  mismatch gets ignored too. So CRLF and LF hash the same, and what is left is
  a difference in what the file actually says.
  """
  with open(path, "rb") as handle:
    raw = handle.read()
  text = raw.decode("utf-8-sig")
  text = text.replace("\r\n", "\n").replace("\r", "\n")
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Files outside drawlogic/ that the manifest covers anyway. sample.txt is the
# fixture for trying verify.ps1 by hand: edit it and the check should say
# MISMATCH. It is named here rather than being re-added to manifest.txt after
# every regeneration, because a manifest that needs a manual step afterwards
# goes stale the first time someone forgets -- which is the exact failure the
# manifest exists to prevent.
EXTRA_FILES = ("sample.txt",)


def manifest_files(root=None):
  """Every file the manifest covers, as repo-relative paths with / separators."""
  root = root or _repo_root()
  package = os.path.join(root, "drawlogic")
  found = []
  for folder, dirs, names in os.walk(package):
    dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git"))
    for name in sorted(names):
      if name.endswith((".pyc", ".pyo")):
        continue
      full = os.path.join(folder, name)
      found.append(os.path.relpath(full, root).replace(os.sep, "/"))
  for name in EXTRA_FILES:
    if os.path.isfile(os.path.join(root, name.replace("/", os.sep))):
      found.append(name)
  return sorted(found)


def manifest_text(root=None):
  """The manifest as it should be on disk."""
  root = root or _repo_root()
  lines = []
  for relative in manifest_files(root):
    full = os.path.join(root, relative.replace("/", os.sep))
    lines.append("%s  %s" % (content_hash(full), relative))
  return "\n".join(lines) + "\n"


def _check_manifest(root=None):
  """Compare the tree against the committed manifest.

  Returns (problems, checked). `problems` is empty when every file is present
  and says what the manifest says; `checked` is None when there is no manifest
  to check against, which is not itself a fault.
  """
  root = root or _repo_root()
  path = os.path.join(root, MANIFEST_NAME)
  if not os.path.isfile(path):
    return [], None

  problems = []
  listed = set()
  count = 0
  with open(path) as handle:
    for line in handle:
      line = line.strip()
      if not line or line.startswith("#"):
        continue
      parts = line.split(None, 1)
      if len(parts) != 2:
        continue
      expected, relative = parts[0], parts[1].strip()
      listed.add(relative)
      count += 1
      full = os.path.join(root, relative.replace("/", os.sep))
      if not os.path.isfile(full):
        problems.append("%s is missing" % relative)
        continue
      try:
        actual = content_hash(full)
      except (OSError, UnicodeDecodeError) as exc:
        problems.append("%s cannot be read: %s" % (relative, exc))
        continue
      if actual != expected:
        problems.append("%s does not match the manifest" % relative)

  for relative in manifest_files(root):
    if relative not in listed:
      problems.append("%s is not in the manifest" % relative)
  return problems, count


def _js_imports(folder):
  """Every named import in the browser modules that nothing exports.

  Reads the files rather than running them, because there is no browser here
  -- but a name imported from a module that does not export it is a hard
  failure in the browser, and it is exactly what a half-copied install looks
  like.
  """
  try:
    names = sorted(n for n in os.listdir(folder) if n.endswith(".js"))
  except OSError:
    return [], None

  exported = {}
  source = {}
  for name in names:
    try:
      with open(os.path.join(folder, name)) as handle:
        text = handle.read()
    except OSError:
      continue
    source[name] = text
    found = set(re.findall(r"^export\s+(?:async\s+)?"
                           r"(?:function|class|const|let|var)\s+(\w+)",
                           text, re.M))
    for group in re.findall(r"^export\s*\{([^}]*)\}", text, re.M):
      for piece in group.split(","):
        piece = piece.strip().split(" as ")[0].strip()
        if piece:
          found.add(piece)
    exported[name] = found

  problems = []
  pattern = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*[\"\']\./([\w.]+\.js)[\"\']')
  for name, text in sorted(source.items()):
    for group, target in pattern.findall(text):
      if target not in exported:
        problems.append("%s imports from %s, which is not here" % (name, target))
        continue
      for piece in group.split(","):
        piece = piece.strip().split(" as ")[0].strip()
        if piece and piece not in exported[target]:
          problems.append("%s imports '%s' from %s, which does not export it"
                          % (name, piece, target))
  return problems, len(source)


def cmd_validate(args):
  registry = _registry(args)
  doc, registry, problems = _open(args.file, registry)
  # A reference that will not resolve is a fault in this drawing, so it is
  # reported alongside everything else rather than shouted about separately.
  issues = problems + doc.validate(registry)
  if not args.no_drc:
    # The DRCs read the drawing as drawn rather than as stated, which is where
    # the faults a reader actually trips over live: a wire lying on another
    # net, a name on a wire, two parts in one place. So they run by default.
    issues = issues + drc.check(doc, registry)

  errors = [i for i in issues if i.level == "error"]
  warnings = [i for i in issues if i.level == "warning"]

  for issue in errors:
    print("error   %s" % _issue_line(issue))
  if not _quiet(args):
    for issue in warnings:
      print("warning %s" % _issue_line(issue))

  if errors:
    print("")
    print("%d error(s), %d warning(s)" % (len(errors), len(warnings)))
    return 1
  if not _quiet(args):
    print("")
    print("no errors, %d warning(s)" % len(warnings))
  return 0


def cmd_symbols(args):
  registry = _registry(args)

  if args.action == "list":
    groups = registry.categories()
    for category in sorted(groups):
      if args.category and category != args.category:
        continue
      print(category)
      for type_id in groups[category]:
        symbol = registry.require(type_id)
        pins = ", ".join("%s(%s)" % (p["name"], p["dir"]) for p in symbol.pins)
        print("  %-12s %-28s %gx%g  %s"
              % (type_id, symbol.name, symbol.width, symbol.height, pins))
    return 0

  try:
    symbol = registry.require(args.name)
  except SymbolError as exc:
    raise SystemExit("%s: %s" % (PROG, exc))

  if args.action == "show":
    print("id       %s" % symbol.id)
    print("name     %s" % symbol.name)
    print("category %s" % symbol.category)
    print("size     %g x %g" % (symbol.width, symbol.height))
    print("source   %s" % registry.source_of(symbol.id))
    print("pins")
    for pin in symbol.pins:
      width = "" if pin["width"] == 1 else "  [%d bits]" % pin["width"]
      print("  %-6s %-6s at %g,%g%s"
            % (pin["name"], pin["dir"], pin["x"], pin["y"], width))
    return 0

  svg = render_svg.render_symbol(symbol, zoom=args.zoom)
  if args.output in (None, "-"):
    sys.stdout.write(svg)
  else:
    with open(args.output, "w") as handle:
      handle.write(svg)
    if not _quiet(args):
      sys.stderr.write("wrote %s\n" % args.output)
  return 0


EXAMPLES = """
examples:
  drawlogic serve                       open the editor on the current folder
  drawlogic serve alu_ctrl.dlg          open one drawing straight away
  drawlogic serve --dir ~/schematics --port 9000

  drawlogic export alu_ctrl.dlg -o alu_ctrl.svg
  drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --zoom 2
  drawlogic export *.dlg --outdir svg/
  drawlogic export alu_ctrl.dlg -o -    write SVG to stdout

  drawlogic validate alu_ctrl.dlg       references and DRCs; non-zero on errors
  drawlogic info alu_ctrl.dlg
  drawlogic symbols list
  drawlogic symbols show and2
  drawlogic symbols preview and2 -o and2.svg

  drawlogic help export                 detail for one command

If the machine is remote, tunnel rather than binding to the network:
  ssh -L 8080:localhost:8080 you@workstation
"""


def cmd_help(args):
  parser = build_parser()
  topic = getattr(args, "topic", None)
  if not topic:
    parser.print_help()
    return 0

  # Reach into the subparser table so `help export` prints that command's
  # own usage rather than the top-level summary.
  for action in parser._subparsers._group_actions:
    if topic in getattr(action, "choices", {}):
      action.choices[topic].print_help()
      return 0
  raise SystemExit("%s: no such command: %s" % (PROG, topic))


def build_parser():
  # Options shared by every subcommand. SUPPRESS keeps an unset flag from
  # overwriting one given before the subcommand, so `drawlogic -q export ...`
  # and `drawlogic export ... -q` both do what you would expect.
  common = argparse.ArgumentParser(add_help=False)
  common.add_argument("--symbols-dir", action="append", metavar="DIR",
                      default=argparse.SUPPRESS,
                      help="extra directory of symbol definitions "
                           "(may be given more than once)")
  common.add_argument("-q", "--quiet", action="store_true",
                      default=argparse.SUPPRESS,
                      help="only report problems")

  parser = argparse.ArgumentParser(
    prog=PROG, parents=[common],
    description="Draw and export logic circuit schematics.",
    epilog=EXAMPLES,
    formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--version", action="version",
                      version="%s %s" % (PROG, VERSION))

  subs = parser.add_subparsers(dest="command")

  export = subs.add_parser("export", parents=[common],
                           help="render drawings to SVG")
  export.add_argument("files", nargs="+", metavar="FILE")
  export.add_argument("-o", "--output", metavar="PATH",
                      help="output file, or - for stdout")
  export.add_argument("--outdir", metavar="DIR",
                      help="write alongside originals into this directory")
  export.add_argument("--zoom", type=float, default=1.0,
                      help="scale the output size; geometry is unchanged "
                           "(default 1.0)")
  export.add_argument("--width", type=float, metavar="PX",
                      help="absolute output width; overrides --zoom")
  export.add_argument("--margin", type=float, metavar="UNITS",
                      help="padding around the drawing")
  export.add_argument("--bg", metavar="COLOR",
                      help="background colour, or 'transparent'")
  export.add_argument("--grid", action="store_true",
                      help="include the canvas grid in the output")
  export.add_argument("--crop", action="store_true",
                      help="trim to the drawing instead of the full canvas")
  export.add_argument("--no-title", action="store_true",
                      help="leave the title off the sheet")
  export.add_argument("--no-arrows", action="store_true",
                      help="leave direction arrows off the wires")
  export.add_argument("--no-hops", action="store_true",
                      help="draw crossing wires flat instead of bridging them")
  export.set_defaults(func=cmd_export)

  serve = subs.add_parser("serve", parents=[common],
                          help="run the browser editor")
  serve.add_argument("file", nargs="?", metavar="FILE",
                     help="drawing to open on startup")
  serve.add_argument("--dir", metavar="DIR",
                     help="folder to serve (default: the file's folder, or .)")
  serve.add_argument("--port", type=int, default=8080)
  serve.add_argument("--host", default="127.0.0.1",
                     help="interface to bind (default loopback only)")
  serve.add_argument("--no-browser", action="store_true",
                     help="do not open a browser window")
  serve.set_defaults(func=cmd_serve)

  info = subs.add_parser("info", parents=[common], help="summarise a drawing")
  info.add_argument("file", metavar="FILE")
  info.set_defaults(func=cmd_info)

  arrange = subs.add_parser("layout", parents=[common],
                            help="lay a drawing out from what it is wired to")
  arrange.add_argument("file")
  arrange.add_argument("-o", "--output", metavar="PATH",
                       help="write here instead of over the original")
  arrange.add_argument("--gap-x", type=float, default=layout.GAP_X,
                       metavar="N", help="room between columns")
  arrange.add_argument("--gap-y", type=float, default=layout.GAP_Y,
                       metavar="N", help="room between cells in a column")
  arrange.set_defaults(func=cmd_layout)

  doctor = subs.add_parser("doctor", parents=[common],
                           help="check this copy of drawlogic is consistent")
  doctor.add_argument("--write-manifest", action="store_true",
                      help="rewrite manifest.txt from the files as they are")
  doctor.set_defaults(func=cmd_doctor)

  validate = subs.add_parser("validate", parents=[common],
                             help="check a drawing for problems")
  validate.add_argument("file", metavar="FILE")
  validate.add_argument("--no-drc", action="store_true",
                        help="check references only, not how it reads")
  validate.set_defaults(func=cmd_validate)

  symbols = subs.add_parser("symbols", parents=[common],
                            help="inspect the symbol library")
  actions = symbols.add_subparsers(dest="action")

  listing = actions.add_parser("list", parents=[common],
                               help="list every known cell type")
  listing.add_argument("--category", help="restrict to one category")
  listing.set_defaults(action="list")

  show = actions.add_parser("show", parents=[common],
                            help="print one symbol's definition")
  show.add_argument("name", metavar="TYPE")
  show.set_defaults(action="show")

  preview = actions.add_parser("preview", parents=[common],
                               help="render one symbol to SVG")
  preview.add_argument("name", metavar="TYPE")
  preview.add_argument("-o", "--output", metavar="PATH",
                       help="output file, or - for stdout")
  preview.add_argument("--zoom", type=float, default=4.0)
  preview.set_defaults(action="preview")

  symbols.set_defaults(func=cmd_symbols)

  helper = subs.add_parser("help", help="show help, optionally for one command")
  helper.add_argument("topic", nargs="?", metavar="COMMAND")
  helper.set_defaults(func=cmd_help)

  return parser


def main(argv=None):
  parser = build_parser()
  args = parser.parse_args(argv)

  if not getattr(args, "command", None):
    parser.print_help()
    return 0
  if args.command == "symbols" and not getattr(args, "action", None):
    raise SystemExit("%s: symbols needs one of: list, show, preview" % PROG)

  try:
    return args.func(args)
  except SymbolError as exc:
    raise SystemExit("%s: %s" % (PROG, exc))
  except BrokenPipeError:
    # Something downstream closed the pipe, as `| head` does. Point stdout at
    # devnull so the interpreter does not complain again while shutting down.
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return 0


if __name__ == "__main__":
  sys.exit(main())
