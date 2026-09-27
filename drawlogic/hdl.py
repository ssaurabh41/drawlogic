"""Structural Verilog in, drawings out.

    top, drawings, warnings = hdl.import_verilog(text)
    # drawings: {module name: Document}; save each as "<module name>.dlg" in
    # one folder -- a parent refers to its children by that file name.

Every module becomes a drawing: its ports become port cells, and each
instance a cell. An instance of a gate primitive or of a symbol in the
library becomes that symbol; an instance of another module in the text
becomes a block standing for that module's own drawing (see sheets.py), so
the hierarchy comes through as hierarchy. Each drawing is then laid out, so
what comes back is a schematic to read rather than a pile of cells.

What is understood -- a netlist, the part of Verilog a schematic can show:

- module headers in either style, ANSI (`module m (input [7:0] a, ...)`) or
  the older list of names with the directions declared in the body;
- input / output / inout, wire / reg / logic, vector ranges, parameters
  (skipped), `#(...)` on instances (skipped);
- the gate primitives and, or, nand, nor, xor, xnor, not, buf;
- instances connected by name (`.a(x)`) or by position;
- `assign a = b;`, which joins the two nets.

One bit of a vector, `d[3]`, is a one-bit net of its own, joined to the
vector by a ripper (bit taken off) or a bus joiner (bit put on).

What is not, and is reported as a warning rather than refused: any other
assign, always/initial blocks, generate, expressions in connections. A slice
connects the whole vector, since no one-bit wire can show it; a constant or
a concatenation leaves that pin unconnected.

An instance of a module that is neither in the text nor in the library gets
a drawing of its own holding only ports, named after the connections made
to it, so the parent still reads; nothing says which way those ports face,
so they are drawn as inout.
"""

import os
import re
import shutil
import tempfile

from . import layout
from . import rtl
from . import yosys
from . import sheets
from .doc import Document, new_document
from .symbols import default_registry


class HdlError(Exception):
  """Text that cannot be read as Verilog; the message names the line."""


# Gate primitive -> symbol, by number of inputs. The output is the first
# terminal of a primitive, which is Verilog's rule, not a convention.
GATES = {
  ("not", 1): "inv", ("buf", 1): "buf",
  ("and", 2): "and2", ("or", 2): "or2", ("nand", 2): "nand2",
  ("nor", 2): "nor2", ("xor", 2): "xor2", ("xnor", 2): "xnor2",
  ("and", 3): "and3", ("or", 3): "or3", ("nand", 3): "nand3",
}
PRIMITIVES = ("and", "or", "nand", "nor", "xor", "xnor", "not", "buf")

DIRECTIONS = ("input", "output", "inout")
NET_KINDS = ("wire", "reg", "logic", "tri", "wand", "wor", "supply0", "supply1")
SKIPPED = ("parameter", "localparam", "genvar", "timeunit", "timeprecision",
           "`timescale", "specify", "function", "task", "integer", "real",
           "time", "event", "defparam")
BEHAVIOUR = ("always", "always_ff", "always_comb", "always_latch", "initial",
             "generate", "endgenerate", "if", "for", "case", "begin", "end")

IDENT = r"[A-Za-z_][A-Za-z0-9_$]*"
RANGE = re.compile(r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]")

# Where cells start before layout: a plain grid, so nothing is on top of
# anything else when the layout begins -- it rearranges them anyway.
START_PITCH = 160.0


class _Port(object):
  def __init__(self, name, direction):
    self.name = name
    self.direction = direction


class _Instance(object):
  def __init__(self, kind, name, named, positional, line):
    self.kind = kind
    self.name = name
    self.named = named          # {port: expr} or None
    self.positional = positional  # [expr] or None
    self.line = line


class _Module(object):
  def __init__(self, name, line):
    self.name = name
    self.line = line
    self.ports = []
    self.ranges = {}            # net or port name -> (msb, lsb)
    self.instances = []
    self.aliases = []
    self.behaviour = []         # rtl.Item: assigns with logic, processes
    self.params = {}            # parameter name -> rtl constant tree
    self.stub = False

  def port(self, name):
    for port in self.ports:
      if port.name == name:
        return port
    return None

  def width(self, name):
    msb, lsb = self.ranges.get(name, (0, 0))
    return abs(msb - lsb) + 1

  def label(self, name):
    """How a net or port is named in the drawing: `d[7:0]` for a vector.

    A block's pins are named by its drawing's port labels, so a parent has
    to name a child's pin this same way.
    """
    if name not in self.ranges:
      return name
    return "%s[%d:%d]" % ((name,) + self.ranges[name])


# ---- reading ---------------------------------------------------------------


def _strip_comments(text):
  """Comments out, newlines kept, so a line number still means that line."""
  def blank(match):
    return re.sub(r"[^\n]", " ", match.group(0))
  text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
  text = re.sub(r"//[^\n]*", "", text)
  # `timescale, `define and friends end at the line, not at a `;`.
  return re.sub(r"(?m)^[ \t]*`[^\n]*", "", text)


def _line_of(text, index):
  return text.count("\n", 0, index) + 1


def _range(range_text):
  """(msb, lsb) from a `[msb:lsb]`, or None when there is none to read."""
  match = RANGE.search(range_text or "")
  if not match:
    return None
  try:
    return int(match.group(1)), int(match.group(2))
  except ValueError:
    return None   # a parameter in the range: drawn one bit wide


def _split_top(text, separator):
  """Split on `separator` wherever it is not inside brackets."""
  parts, depth, start = [], 0, 0
  for index, char in enumerate(text):
    if char in "([{":
      depth += 1
    elif char in ")]}":
      depth -= 1
    elif char == separator and depth == 0:
      parts.append(text[start:index])
      start = index + 1
  parts.append(text[start:])
  return parts


def _balanced(text, start):
  """Index just past the bracket group opening at text[start]."""
  depth = 0
  for index in range(start, len(text)):
    if text[index] == "(":
      depth += 1
    elif text[index] == ")":
      depth -= 1
      if depth == 0:
        return index + 1
  return -1


def _declare(module, words, names_text, ranges_text):
  direction = words[0] if words and words[0] in DIRECTIONS else None
  bits = _range(ranges_text)
  for raw in _split_top(names_text, ","):
    name = raw.split("=")[0].strip()
    if not re.match(r"^%s$" % IDENT, name):
      continue
    # `output q; reg [3:0] q;` -- whichever declaration has the range says it.
    if bits is not None:
      module.ranges[name] = bits
    if direction:
      existing = module.port(name)
      if existing is None:
        module.ports.append(_Port(name, direction))
      else:
        existing.direction = direction


DECLARATION = re.compile(
  r"^(?P<words>(?:(?:input|output|inout|wire|reg|logic|tri|signed|unsigned|"
  r"var)\s+)*(?:input|output|inout|wire|reg|logic|tri))\b\s*"
  r"(?P<ranges>(?:\[[^\]]*\]\s*)*)(?P<names>.*)$", re.S)


def _parse_header_ports(module, text):
  """ANSI ports carry their direction; a bare list names ports declared later.

  In an ANSI list a direction and range apply to the names after them until
  the next one -- `input [7:0] a, b` makes both eight bits wide.
  """
  words, ranges = None, ""
  for item in _split_top(text, ","):
    item = item.strip()
    if not item:
      continue
    match = DECLARATION.match(item)
    if match:
      words = match.group("words").split()
      ranges = match.group("ranges")
      names = match.group("names")
    else:
      names = item
    if words:
      _declare(module, words, names, ranges)
    elif re.match(r"^%s$" % IDENT, item):
      module.ports.append(_Port(item, None))


def _parse_connections(body):
  """`.a(x), .b(y)` -> ({a: x, b: y}, None); `x, y` -> (None, [x, y])."""
  items = [item.strip() for item in _split_top(body, ",")]
  if items == [""]:
    return {}, None
  if all(item.startswith(".") or not item for item in items):
    named = {}
    for item in items:
      match = re.match(r"^\.\s*(%s)\s*\((.*)\)\s*$" % IDENT, item, re.S)
      if match:
        named[match.group(1)] = match.group(2).strip()
    return named, None
  return None, items


def parse(text):
  """The modules in `text`, in the order they are defined."""
  clean = _strip_comments(text)
  modules = []
  position = 0
  header = re.compile(r"\b(module|macromodule)\s+(%s)" % IDENT)
  while True:
    found = header.search(clean, position)
    if not found:
      break
    module = _Module(found.group(2), _line_of(clean, found.start()))
    cursor = found.end()
    rest = clean[cursor:]
    skip = re.match(r"\s*#\s*\(", rest)
    if skip:
      end = _balanced(clean, cursor + skip.end() - 1)
      if end < 0:
        raise HdlError("line %d: unclosed #( in module %s"
                       % (module.line, module.name))
      cursor = end
    opening = re.match(r"\s*\(", clean[cursor:])
    if opening:
      start = cursor + opening.end() - 1
      end = _balanced(clean, start)
      if end < 0:
        raise HdlError("line %d: unclosed port list in module %s"
                       % (module.line, module.name))
      _parse_header_ports(module, clean[start + 1:end - 1])
      cursor = end
    semicolon = re.match(r"\s*;", clean[cursor:])
    if not semicolon:
      raise HdlError("line %d: expected ; after the header of module %s"
                     % (_line_of(clean, cursor), module.name))
    cursor += semicolon.end()
    finish = re.compile(r"\bendmodule\b").search(clean, cursor)
    if not finish:
      raise HdlError("line %d: module %s has no endmodule"
                     % (module.line, module.name))
    _parse_body(module, clean, cursor, finish.start())
    modules.append(module)
    position = finish.end()
  if not modules:
    raise HdlError("line 1: no module found")
  return modules


def _parse_body(module, text, start, end):
  try:
    found = rtl.items(text, start, end, _line_of(text, start))
  except rtl.LowerError as exc:
    raise HdlError(str(exc) if str(exc).startswith("line") else
                   "line %d: %s" % (_line_of(text, start), exc))
  for item in found:
    if item.kind == "skipped":
      module.instances.append(_Instance("#skipped", item.text, None, None,
                                        item.line))
      continue
    if item.kind == "process":
      module.behaviour.append(item)
      continue
    if item.kind == "assign":
      # `assign a = b;` between two whole nets joins them, as a wire does;
      # anything else is logic, drawn by rtl.py.
      logic = []
      for lvalue, value, line in item.tree:
        if lvalue[0] == "id" and value[0] == "id":
          module.aliases.append((lvalue[1], value[1]))
        else:
          logic.append((lvalue, value, line))
      if logic:
        module.behaviour.append(rtl.Item("assign", item.line, tree=logic))
      continue
    _parse_text_item(module, item.text.strip(), item.line)


def _parse_text_item(module, statement, line):
  words = statement.split()
  if not words:
    return
  first = words[0]
  if first in ("parameter", "localparam"):
    module.params.update(rtl.parameters(statement))
    return
  if first in SKIPPED or first.startswith("`"):
    return
  declaration = DECLARATION.match(statement)
  if declaration and first in DIRECTIONS + NET_KINDS + ("signed",):
    _declare(module, declaration.group("words").split(),
             declaration.group("names"), declaration.group("ranges"))
    return
  match = re.match(r"^(%s)\s*(#\s*\(.*?\)\s*)?(%s)?\s*\((.*)\)\s*$"
                   % (IDENT, IDENT), statement, re.S)
  if not match:
    raise HdlError("line %d: cannot read %r" % (line, " ".join(words[:6])))
  kind, name, conns = match.group(1), match.group(3), match.group(4)
  if name is None and kind not in PRIMITIVES:
    raise HdlError("line %d: instance of %s has no name" % (line, kind))
  named, positional = _parse_connections(conns)
  module.instances.append(_Instance(kind, name, named, positional, line))


# ---- building --------------------------------------------------------------


def _net_of(module, expr, warnings, where, flagged):
  """What a connection names: a net, (net, bit) for one bit of a vector, or
  None for something a wire cannot show."""
  expr = (expr or "").strip()
  if not expr:
    return None
  match = re.match(r"^(%s)\s*(?:\[\s*([^\]]*?)\s*\])?$" % IDENT, expr)
  if not match:
    warnings.append("%s: %r is not a single net, so that pin is left "
                    "unconnected" % (where, expr))
    return None
  name, select = match.group(1), match.group(2)
  if select is None or module.width(name) == 1:
    return name
  if re.match(r"^\d+$", select):
    return (name, int(select))
  # A slice, or a bit picked by a parameter: no one-bit wire says which.
  if name not in flagged:
    flagged.add(name)
    warnings.append("%s: part of %s is connected; the drawing connects the "
                    "whole of it" % (where, name))
  return name


def _safe_id(text, taken):
  base = re.sub(r"[^A-Za-z0-9_]", "_", text) or "u"
  candidate, number = base, 2
  while candidate in taken:
    candidate = "%s_%d" % (base, number)
    number += 1
  taken.add(candidate)
  return candidate


class _Root(object):
  """Union-find over net names, for `assign a = b`."""

  def __init__(self):
    self.parent = {}

  def find(self, name):
    while self.parent.get(name, name) != name:
      name = self.parent[name]
    return name

  def join(self, one, other):
    self.parent[self.find(one)] = self.find(other)


def _build(module, modules, registry, warnings):
  """One module's drawing, before layout."""
  doc = new_document(module.name)
  taken = set()
  ends = {}        # net -> [(cell, pin, role)]; role is drive, load, either
  flagged = set()  # or part: a ripper that drives one bit of a vector
  root = _Root()
  for one, other in module.aliases:
    root.join(one, other)

  def connect(net, cell, pin, role):
    if isinstance(net, tuple):
      net = (root.find(net[0]), net[1])
    elif net is not None:
      net = root.find(net)
    else:
      return
    ends.setdefault(net, []).append((cell, pin, role))

  place = [0]

  def add_cell(spec):
    column, row = place[0] % 6, place[0] // 6
    place[0] += 1
    spec.setdefault("x", 60 + column * START_PITCH)
    spec.setdefault("y", 60 + row * START_PITCH)
    doc.cells.append(spec)
    return spec

  def wire(where, cell_id, pins_and_exprs, role_of):
    for pin, expr in pins_and_exprs:
      connect(_net_of(module, expr, warnings, where, flagged), cell_id, pin,
              role_of(pin))

  for port in module.ports:
    direction = port.direction or "inout"
    kind = {"input": "port_in", "output": "port_out"}.get(direction, "port_inout")
    cell = add_cell({"id": _safe_id("p_" + port.name, taken), "type": kind,
                     "label": module.label(port.name)})
    role = {"input": "drive", "output": "load"}.get(direction, "either")
    connect(port.name, cell["id"], "p", role)

  # Behaviour first becomes cells like any others: rtl.py lowers it to the
  # library's gates and flip-flops, with named connections.
  if module.behaviour:
    lowered, notes = rtl.lower(module)
    warnings.extend(notes)
    for symbol, name, pins, line in lowered:
      module.instances.append(_Instance(symbol, name, pins, None, line))
    module.behaviour = []

  counter = [0]
  for inst in module.instances:
    where = "%s line %d" % (module.name, inst.line)
    if inst.kind == "#skipped":
      warnings.append("%s: %s is not drawn" % (where, inst.name))
      continue
    if inst.name is None:
      counter[0] += 1
      inst.name = "g%d" % counter[0]
    cell_id = _safe_id(inst.name, taken)
    gate_role = lambda pin: "drive" if pin == "y" else "load"

    # A primitive is connected by position; a named `buf` is the library's
    # buffer, which is what rtl.py and Yosys emit.
    if inst.kind in PRIMITIVES and inst.named is None:
      terms = inst.positional or []
      symbol = GATES.get((inst.kind, len(terms) - 1))
      if symbol is None or inst.named:
        warnings.append("%s: %s with %d inputs has no symbol; drawn as a "
                        "block" % (where, inst.kind, len(terms) - 1))
        pins = ["y"] + ["in%d" % i for i in range(len(terms) - 1)]
        child = _stub(modules, "%s%d" % (inst.kind, len(terms) - 1), pins,
                      {"y": "output"})
        add_cell({"id": cell_id, "type": "sheet", "ref": child.name + ".dlg",
                  "label": inst.name})
      else:
        pins = ["y", "a", "b", "c"][:len(terms)]
        add_cell({"id": cell_id, "type": symbol, "label": inst.name})
      wire(where, cell_id, zip(pins, terms), gate_role)
      continue

    child = modules.get(inst.kind)
    symbol = registry.get(inst.kind) if child is None else None
    if symbol is not None and inst.named is not None:
      if not set(inst.named) <= set(symbol.pin_names()):
        symbol = None
    if child is None and symbol is not None:
      add_cell({"id": cell_id, "type": inst.kind, "label": inst.name})
      pairs = (inst.named.items() if inst.named is not None
               else zip(symbol.pin_names(), inst.positional))
      wire(where, cell_id, pairs, lambda pin: {
        "out": "drive", "in": "load"}.get(symbol.pin(pin)["dir"], "either"))
      continue

    if child is None:
      if inst.named is None:
        warnings.append("%s: %s is not defined and is connected by position, "
                        "so its pins cannot be named; instance %s left out"
                        % (where, inst.kind, inst.name))
        continue
      warnings.append("%s: %s is not defined here or in the library; drawn "
                      "as a block with the ports it is connected by"
                      % (where, inst.kind))
      child = _stub(modules, inst.kind, list(inst.named), {})
    add_cell({"id": cell_id, "type": "sheet", "ref": child.name + ".dlg",
              "label": inst.name})
    pairs = (inst.named.items() if inst.named is not None
             else zip([p.name for p in child.ports], inst.positional))
    for pin, expr in pairs:
      port = child.port(pin)
      if port is None:
        warnings.append("%s: %s has no port %s" % (where, child.name, pin))
        continue
      role = {"output": "drive", "input": "load"}.get(port.direction, "either")
      connect(_net_of(module, expr, warnings, where, flagged), cell_id,
              child.label(pin), role)

  # One bit of a vector is its own one-bit net, joined to the vector by a
  # ripper where the bit is taken off it, or a joiner where it is put on.
  # Layout reads an inout pin's direction from the side it is on and turns
  # every cell to face forward, so which way round it goes is chosen here.
  for key in sorted(k for k in ends if isinstance(k, tuple)):
    name, bit = key
    driven = any(end[2] == "drive" for end in ends[key])
    rip = _safe_id("%s_%s_%d" % ("join" if driven else "rip", name, bit), taken)
    add_cell({"id": rip, "type": "bus_join" if driven else "ripper",
              "label": "%s[%d]" % (name, bit)})
    ends[key].append((rip, "bit", "load" if driven else "drive"))
    ends.setdefault(name, []).append((rip, "bus", "part" if driven else "load"))

  number = 0
  for net, found in sorted(ends.items(), key=lambda item: str(item[0])):
    if len(found) < 2:
      continue
    if isinstance(net, tuple):
      name, width = "%s[%d]" % net, 1
    else:
      name, width = module.label(net), module.width(net)
    drivers = [end for end in found if end[2] == "drive"]
    if len(drivers) > 1:
      warnings.append("%s: %s has %d drivers; drawn from %s.%s"
                      % (module.name, name, len(drivers), drivers[0][0],
                         drivers[0][1]))
    # Rippers each drive a slice of a vector, so several are not a clash.
    drivers = drivers or [end for end in found if end[2] == "part"]
    if not drivers:
      drivers = [end for end in found if end[2] == "either"] or found
      warnings.append("%s: nothing drives %s; drawn from %s.%s"
                      % (module.name, name, drivers[0][0], drivers[0][1]))
    source = drivers[0]
    number += 1
    doc.nets.append({
      "id": "n%d" % number, "name": name, "width": width,
      "from": {"cell": source[0], "pin": source[1]},
      "to": [{"cell": end[0], "pin": end[1]} for end in found
             if end is not source],
    })
  return doc


def _synthesize(text, top, parsed, modules, registry, warnings):
  """The modules as Yosys synthesised them, ready for _build."""
  stubs = {}
  for module in parsed:
    for inst in module.instances:
      if inst.kind in modules or inst.kind in PRIMITIVES or inst.kind in stubs \
          or inst.kind.startswith("#"):
        continue
      symbol = registry.get(inst.kind)
      if symbol is not None:
        stubs[inst.kind] = [(pin["name"], pin["dir"]) for pin in symbol.pins]
      elif inst.named is not None:
        stubs[inst.kind] = [(pin, "inout") for pin in inst.named]
      else:
        raise yosys.YosysError("%s is defined nowhere and connected by "
                               "position" % inst.kind)
  data = yosys.synthesize(text, top, stubs)
  # A note, not a warning: nothing was left out. Callers tell the two apart
  # by the prefix.
  warnings.append("%ssynthesised with %s: its gates, and names it made up "
                  "for internal signals" % (NOTE, yosys.version()))
  found = {}
  for name, spec in data.items():
    module = _Module(name, 0)
    module.ports = [_Port(port, direction) for port, direction in spec["ports"]]
    module.ranges = dict(spec["ranges"])
    module.aliases = list(spec["aliases"])
    module.instances = [_Instance(kind, cell, pins, None, 0)
                        for kind, cell, pins in spec["cells"]]
    warnings.extend("%s: %s" % (name, note) for note in spec["notes"])
    found[name] = module
  return found


def _stub(modules, name, pins, directions):
  """A module known only by what is plugged into it."""
  existing = modules.get(name)
  if existing is not None:
    for pin in pins:
      if existing.port(pin) is None:
        existing.ports.append(_Port(pin, directions.get(pin, "inout")))
    return existing
  stub = _Module(name, 0)
  stub.stub = True
  stub.ports = [_Port(pin, directions.get(pin, "inout")) for pin in pins]
  modules[name] = stub
  return stub


def _children_first(modules):
  """Module names ordered so every module comes after those it instantiates."""
  order, state = [], {}

  def visit(name, trail):
    if state.get(name) == "done":
      return
    if state.get(name) == "visiting":
      raise HdlError("line %d: module %s instantiates itself, directly or "
                     "through others: %s" % (modules[name].line, name,
                                             " -> ".join(trail + [name])))
    state[name] = "visiting"
    for inst in modules[name].instances:
      if inst.kind in modules and inst.kind != name:
        visit(inst.kind, trail + [name])
      elif inst.kind == name:
        raise HdlError("line %d: module %s instantiates itself"
                       % (inst.line, name))
    state[name] = "done"
    order.append(name)

  for name in list(modules):
    visit(name, [])
  return order


SYNTH_CHOICES = ("auto", "yosys", "builtin")
# Starts a message that says how the drawing was made rather than what it
# leaves out.
NOTE = "note: "


def import_verilog(text, registry=None, top=None, synth="auto"):
  """Drawings for the modules in `text`: (top name, {name: Document}, warnings).

  Each drawing is laid out, with the blocks for its child modules sized from
  those children, so the answer is ready to save and open.

  `synth` says who turns behaviour into gates. "auto" uses Yosys when the
  text has behaviour in it and Yosys is installed, and rtl.py otherwise;
  "yosys" insists on Yosys; "builtin" never uses it. A netlist with no
  behaviour is read as it stands either way, unless Yosys is insisted on.
  """
  if synth not in SYNTH_CHOICES:
    raise HdlError("line 1: synth must be one of %s" % ", ".join(SYNTH_CHOICES))
  registry = registry or default_registry()
  parsed = parse(text)
  modules = {}
  for module in parsed:
    if module.name in modules:
      raise HdlError("line %d: module %s is defined twice"
                     % (module.line, module.name))
    modules[module.name] = module

  if top is None:
    used = set(inst.kind for m in parsed for inst in m.instances)
    roots = [m.name for m in parsed if m.name not in used]
    top = roots[0] if roots else parsed[0].name
  elif top not in modules:
    raise HdlError("line 1: no module named %s" % top)

  warnings = []
  behavioural = any(m.behaviour for m in parsed)
  if synth == "yosys" or (synth == "auto" and behavioural
                          and yosys.available()):
    try:
      modules = _synthesize(text, top, parsed, modules, registry, warnings)
    except yosys.YosysError as exc:
      if synth == "yosys":
        raise HdlError("line 1: %s" % exc)
      warnings.append("Yosys could not synthesise this (%s); drawn by "
                      "drawlogic's own reader instead" % exc)

  built = {}
  for name in list(modules):
    if not modules[name].stub:
      built[name] = _build(modules[name], modules, registry, warnings)
  # Stubs appear while their parents are built, so they are built last.
  for name, module in modules.items():
    if name not in built:
      built[name] = _build(module, modules, registry, warnings)

  # A parent's blocks are sized from its children's drawings, which have to
  # be files for sheets.resolve to read -- so the drawings are laid out
  # children first in a scratch folder, and read back from there.
  folder = tempfile.mkdtemp(prefix="drawlogic-import-")
  try:
    drawings = {}
    for name in _children_first(modules):
      doc = built[name]
      doc.path = os.path.join(folder, name + ".dlg")
      local = registry.copy()
      problems = sheets.resolve(doc, local)
      for issue in problems:
        warnings.append("%s: %s" % (name, issue.message))
      doc.normalize(local)
      layout.arrange(doc, local)
      doc.save()
      drawings[name] = Document.load(doc.path)
      drawings[name].path = None
  finally:
    shutil.rmtree(folder, ignore_errors=True)
  return top, drawings, warnings


def write_drawings(folder, drawings, overwrite=False):
  """Save each drawing as `<module>.dlg` in `folder`; the paths written.

  All or nothing when files are in the way: a half-written hierarchy, some
  blocks new and some left over from an older import, would open without a
  word and be wrong.
  """
  paths = [os.path.join(folder, name + ".dlg") for name in sorted(drawings)]
  if not overwrite:
    existing = [path for path in paths if os.path.exists(path)]
    if existing:
      raise FileExistsError(", ".join(os.path.basename(p) for p in existing))
  for name, path in zip(sorted(drawings), paths):
    drawings[name].save(path)
  return paths
