"""Command line entry points.

Usage:

    drawlogic help                      # overview with examples
    drawlogic help export               # detail for one command

    drawlogic serve alu_ctrl.dlg        # open the browser editor
    drawlogic export alu_ctrl.dlg -o alu_ctrl.svg --zoom 2
    drawlogic validate alu_ctrl.dlg     # non-zero exit on errors
    drawlogic info alu_ctrl.dlg
    drawlogic symbols list

Run with nothing, or with --help, for the same overview.
"""

import argparse
import os
import sys

from . import render_svg
from .doc import Document, DocumentError
from . import sheets
from .symbols import SymbolError, load_registry

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
      arrows=not args.no_arrows, hops=not args.no_hops)

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


def cmd_validate(args):
  registry = _registry(args)
  doc, registry, problems = _open(args.file, registry)
  # A reference that will not resolve is a fault in this drawing, so it is
  # reported alongside everything else rather than shouted about separately.
  issues = problems + doc.validate(registry)

  errors = [i for i in issues if i.level == "error"]
  warnings = [i for i in issues if i.level == "warning"]

  for issue in errors:
    print("error   %s: %s" % (issue.where, issue.message))
  if not _quiet(args):
    for issue in warnings:
      print("warning %s: %s" % (issue.where, issue.message))

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

  drawlogic validate alu_ctrl.dlg       exits non-zero if there are errors
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

  validate = subs.add_parser("validate", parents=[common],
                             help="check a drawing for problems")
  validate.add_argument("file", metavar="FILE")
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
