"""Behavioural Verilog through Yosys, when Yosys is installed.

    if yosys.available():
      modules, version = yosys.synthesize(text, top, blackboxes)

drawlogic stays dependency-free: this is used only when a `yosys` command is
on the PATH, and only for Verilog with behaviour in it -- a structural netlist
is already a drawing, and resynthesising it would only scramble its gates.
rtl.py covers the common shapes of RTL without Yosys; Yosys covers the rest
(arithmetic, comparisons, casez, loops, functions), because it is a real
synthesiser and this project is not trying to be one.

Yosys synthesises to its own gate cells, and every one of them has a symbol
in the library: flip-flops are legalised to plain `dff` and `dffr` (Yosys
adds the inverters for set, active-high reset and falling clocks), and ABC
maps the logic onto 2-input gates and 2:1 muxes. What comes back is the same
plain data hdl.py builds from a netlist, so the drawing is made the same way.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile


class YosysError(Exception):
  """Yosys is missing, failed, or produced something with no drawing."""


# Yosys's internal cells -> (symbol, {yosys port: symbol pin}).
CELLS = {
  "$_NOT_": ("inv", {"A": "a", "Y": "y"}),
  "$_BUF_": ("buf", {"A": "a", "Y": "y"}),
  "$_AND_": ("and2", {"A": "a", "B": "b", "Y": "y"}),
  "$_OR_": ("or2", {"A": "a", "B": "b", "Y": "y"}),
  "$_XOR_": ("xor2", {"A": "a", "B": "b", "Y": "y"}),
  "$_NAND_": ("nand2", {"A": "a", "B": "b", "Y": "y"}),
  "$_NOR_": ("nor2", {"A": "a", "B": "b", "Y": "y"}),
  "$_XNOR_": ("xnor2", {"A": "a", "B": "b", "Y": "y"}),
  "$_MUX_": ("mux2", {"A": "d0", "B": "d1", "S": "s", "Y": "y"}),
  "$_DFF_P_": ("dff", {"C": "ck", "D": "d", "Q": "q"}),
  "$_DFF_PN0_": ("dffr", {"C": "ck", "D": "d", "Q": "q", "R": "rn"}),
  "$_DLATCH_P_": ("dlatch", {"E": "g", "D": "d", "Q": "q"}),
}
SEQUENTIAL = ("$_DFF_P_", "$_DFF_PN0_", "$_DLATCH_P_")

# Legalise every storage element to the three the library draws, then map
# the logic to gates it draws. opt_clean drops what that left unused.
SCRIPT = """\
read_verilog -sv {blackboxes} {source}
hierarchy -check {top}
synth {top}
dfflegalize -cell $_DFF_P_ 01 -cell $_DFF_PN0_ 01 -cell $_DLATCH_P_ 01
abc -g AND,NAND,OR,NOR,XOR,XNOR,MUX
opt_merge
opt_clean -purge
write_json {output}
"""

TIMEOUT = 300


def available():
  """The yosys command, or None when it is not installed."""
  return shutil.which("yosys")


def version():
  try:
    result = subprocess.run([available(), "-V"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=30)
  except (OSError, subprocess.SubprocessError):
    return "Yosys"
  return result.stdout.decode("utf-8", "replace").strip().split(" (")[0]


def blackbox_text(stubs):
  """Verilog declaring each of `stubs` -- {name: [(pin, direction)]} -- as a
  black box, so Yosys keeps an instance of it rather than failing on it."""
  words = {"in": "input", "out": "output"}
  lines = []
  for name, pins in sorted(stubs.items()):
    lines.append("(* blackbox *) module %s(%s);" % (
      name, ", ".join(pin for pin, _ in pins)))
    for pin, direction in pins:
      lines.append("  %s %s;" % (words.get(direction, "inout"), pin))
    lines.append("endmodule")
  return "\n".join(lines) + "\n"


def synthesize(text, top, stubs):
  """Run Yosys on `text`; the modules it made, as plain data.

  Returns {module name: {"ports": [(name, direction)], "ranges": {name:
  (msb, lsb)}, "cells": [(kind, name, {pin: net text})], "notes": [...]}}
  for every module but the black boxes.
  """
  command = available()
  if not command:
    raise YosysError("yosys is not installed")
  folder = tempfile.mkdtemp(prefix="drawlogic-yosys-")
  try:
    source = os.path.join(folder, "design.v")
    boxes = os.path.join(folder, "blackboxes.v")
    output = os.path.join(folder, "design.json")
    with open(source, "w") as handle:
      handle.write(text)
    with open(boxes, "w") as handle:
      handle.write(blackbox_text(stubs))
    script = SCRIPT.format(source=source, blackboxes=boxes, output=output,
                           top="-top %s" % top if top else "-auto-top")
    try:
      result = subprocess.run([command, "-q", "-p", script.replace("\n", "; ")],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=TIMEOUT, cwd=folder)
    except subprocess.TimeoutExpired:
      raise YosysError("yosys took longer than %d seconds" % TIMEOUT)
    if result.returncode != 0 or not os.path.exists(output):
      message = result.stdout.decode("utf-8", "replace").strip().splitlines()
      errors = [line for line in message if "ERROR" in line] or message[-1:]
      raise YosysError(errors[0].strip() if errors else "yosys failed")
    with open(output) as handle:
      data = json.load(handle)
  finally:
    shutil.rmtree(folder, ignore_errors=True)
  return convert(data)


# ---- JSON to plain modules -------------------------------------------------


def _clean(name, taken):
  """A Yosys name as an identifier a drawing can hold, unique in `taken`."""
  base = re.sub(r"[^A-Za-z0-9_]", "_", name.lstrip("\\$")) or "n"
  if not re.match(r"[A-Za-z_]", base):
    base = "n_" + base
  candidate, number = base, 2
  while candidate in taken:
    candidate = "%s_%d" % (base, number)
    number += 1
  taken.add(candidate)
  return candidate


def convert(data):
  modules = data.get("modules", {})
  names, taken = {}, set()
  for name, module in modules.items():
    if module.get("attributes", {}).get("blackbox"):
      names[name] = name
    else:
      names[name] = _clean(name, taken)
  found = {}
  for name, module in modules.items():
    if module.get("attributes", {}).get("blackbox"):
      continue
    found[names[name]] = _module(module, names)
  return found


def _preference(item):
  name, net = item
  hidden = net.get("hide_name", 0) or name.startswith("$")
  return (hidden, len(name), name)


def _module(module, names):
  ports = module.get("ports", {})
  nets = module.get("netnames", {})
  taken = set()
  label = {}           # yosys bit -> net text
  ranges = {}
  notes = []

  # Ports name their bits first, then the names in the source, then Yosys's
  # own; a bit with only an internal name gets a short one of its own.
  ordered = sorted(nets.items(), key=lambda item: (item[0] not in ports,)
                   + _preference(item))
  for name, net in ordered:
    bits = net.get("bits", [])
    hidden = net.get("hide_name", 0) or name.startswith("$")
    if hidden:
      continue
    clean = _clean(name, taken)
    offset = net.get("offset", 0)
    upto = net.get("upto", 0)
    width = len(bits)
    if width > 1:
      ranges[clean] = ((offset, offset + width - 1) if upto
                       else (offset + width - 1, offset))
    for index, bit in enumerate(bits):
      if not isinstance(bit, int) or bit in label:
        continue
      if width == 1:
        label[bit] = clean
      else:
        label[bit] = "%s[%d]" % (clean, offset + (width - 1 - index if upto
                                                  else index))

  def text(bit):
    if bit not in label:
      label[bit] = _clean("n%d" % bit, taken)
    return label[bit]

  cells = []
  ties = [0]

  def connect(bit, pins, pin):
    if isinstance(bit, int):
      pins[pin] = text(bit)
    elif bit in ("0", "1"):
      ties[0] += 1
      net = _clean("k%d" % ties[0], taken)
      cells.append(("tie" + bit, "tie%d" % ties[0], {"y": net}))
      pins[pin] = net
    # x and z: left unconnected, which validate reports.

  counter = [0]
  for cell_name, cell in sorted(module.get("cells", {}).items()):
    kind = cell.get("type", "")
    connections = cell.get("connections", {})
    if kind in CELLS:
      symbol, pinmap = CELLS[kind]
      pins = {}
      for port, bits in connections.items():
        if port in pinmap and bits:
          connect(bits[0], pins, pinmap[port])
      if kind in SEQUENTIAL and "q" in pins:
        name = pins["q"].replace("[", "_").replace("]", "") + "_reg"
      else:
        counter[0] += 1
        name = "g%d" % counter[0]
      cells.append((symbol, name, pins))
      continue
    if kind.startswith("$"):
      if not kind.startswith("$scopeinfo"):
        notes.append("Yosys left a %s cell, which has no symbol; left out"
                     % kind)
      continue
    # An instance of another module, or of a black box.
    pins = {}
    for port, bits in connections.items():
      whole = _whole(bits, nets, label, text)
      if whole is None:
        notes.append("%s.%s is connected to a mix of signals, which a "
                     "block's one pin cannot show; left unconnected"
                     % (cell_name, port))
        continue
      if whole:
        pins[port] = whole
      elif len(bits) == 1:
        connect(bits[0], pins, port)
    hidden = cell.get("hide_name", 0) or cell_name.startswith("$")
    instance = cell_name if not hidden else "u%d" % (len(cells) + 1)
    cells.append((names.get(kind, kind), instance, pins))

  # A port keeps its own name. When its bits were named after another
  # signal -- an output wired straight from an input shares that input's
  # bits -- it is joined to that signal: as a whole where it is the whole of
  # it, bit by bit through buffers where it is not.
  directions, aliases = [], []
  for name, port in ports.items():
    own = _clean(name, set())
    bits = port.get("bits", [])
    directions.append((own, port.get("direction", "inout")))
    texts = [own] if len(bits) == 1 else [
      "%s[%d]" % (own, index) for index in _indices(nets.get(name, {}), len(bits))]
    labels = [label.get(bit) if isinstance(bit, int) else None for bit in bits]
    if labels == texts:
      continue
    bases = set(text.split("[")[0] for text in labels if text)
    other = bases.pop() if len(bases) == 1 and None not in labels else None
    if other is not None and (len(bits) == 1 or _whole_of(other, labels, ranges)):
      aliases.append((own, other))
      continue
    for bit, target in zip(bits, texts):
      pins = {"y": target}
      connect(bit, pins, "a")
      if "a" in pins:
        counter[0] += 1
        cells.append(("buf", "g%d" % counter[0], pins))
  return {"ports": directions, "ranges": ranges, "cells": cells,
          "aliases": aliases, "notes": notes}


def _indices(net, width):
  offset, upto = net.get("offset", 0), net.get("upto", 0)
  return [offset + (width - 1 - i if upto else i) for i in range(width)]


def _whole_of(name, labels, ranges):
  """Do `labels`, least significant first, cover all of vector `name` in
  order?"""
  if name not in ranges:
    return False
  msb, lsb = ranges[name]
  step = 1 if msb >= lsb else -1
  return labels == ["%s[%d]" % (name, i) for i in range(lsb, msb + step, step)]


def _whole(bits, nets, label, text):
  """Net text for a multi-bit connection when it is exactly one named
  vector; "" for a single bit (handled by the caller); None otherwise."""
  if len(bits) == 1:
    return ""
  if not all(isinstance(bit, int) for bit in bits):
    return None
  first = text(bits[0])
  base = first.split("[")[0]
  if all(text(bit).split("[")[0] == base for bit in bits):
    for name, net in nets.items():
      if net.get("bits") == bits:
        return base
    return base   # part of a vector: hdl.py connects the whole and says so
  return None
