"""Linked components: a part of a drawing defined once and placed many times.

A component is an ordinary drawing -- its definition -- and each placed copy
is a cell whose `ref` names it, exactly as a hierarchical block always has
been (see sheets.py). Its pins are the definition's ports, read off it every
time the drawing using it is opened, so editing the definition changes every
copy, and an instance can only ever be wired to pins the definition has.

This module turns a selection into one: the selected cells, shapes and
containers, and the wires among them, are copied into a new drawing; every
wire crossing the selection's edge becomes a port there and a pin on the new
instance; and the selection is replaced by that one instance, with the wires
from outside reattached to its pins by name.

What stays the instance's own, and what comes from the definition:

    the instance's own     id, label, position, parent container, rotation,
                           size, colours and text written on it (style,
                           heading, text, styleRef)
    from the definition    its pins (the definition's ports) and its title

Usage:

    from drawlogic import components

    plan = components.plan(doc, registry, {"u1", "u2"})
    plan["ports"]      # [{"key": "n3", "name": "en", "dir": "in", "width": 1}, ...]
    plan["problems"]   # why it cannot be done as asked, or []

    child, ref, instance = components.extract(doc, registry, {"u1", "u2"}, "SM",
                                              names={"n3": "enable"})
    child.save(os.path.join(folder, ref))     # the caller writes the file
"""

import copy
import os
import posixpath
import re

from . import containers
from .doc import Document, loads_of, new_document

FOLDER = "components"

# Room round the copied drawing, and where its ports stand.
MARGIN = 80.0
PORT_GAP = 70.0
PORT_STEP = 40.0


class ComponentError(Exception):
  pass


def slug(name):
  """The file name a component of this name is kept in, without .dlg."""
  text = re.sub(r"[^A-Za-z0-9_]+", "_", str(name or "").strip()).strip("_").lower()
  return text or "component"


def ref_for(name):
  """The ref, relative to the drawing using it, of a new component's file."""
  return "%s/%s.dlg" % (FOLDER, slug(name))


def _ends(net):
  return [net.get("from")] + loads_of(net)


def _inside(doc, ids):
  """Every id the selection takes in: what was chosen, and all inside it."""
  known = set(c.get("id") for c in doc.cells) | set(s.get("id") for s in doc.shapes) \
    | set(b.get("id") for b in doc.containers)
  return containers.descendants(doc, set(i for i in ids if i in known))


def _crossing(doc, inside):
  """(internal, crossing, problems) for the wires against a selection."""
  internal, crossing, problems = [], [], []
  for net in doc.nets:
    ends = _ends(net)
    within = [isinstance(e, dict) and e.get("cell") in inside for e in ends]
    if not any(within):
      continue
    if all(within):
      internal.append(net)
      continue
    if any(isinstance(e, dict) and "cell" not in e for e in ends):
      problems.append("wire %s has a loose end; connect it to a pin, or take the "
                      "loose end out of the selection, first"
                      % (net.get("name") or net.get("label") or net.get("id")))
      continue
    crossing.append(net)
  return internal, crossing, problems


def _pin_name(doc, end):
  return "%s" % end.get("pin")


def plan(doc, registry, ids):
  """What turning `ids` into a component would make, before making it.

  Returns {"ports": [...], "problems": [...]}: one port per wire crossing
  the selection's edge, keyed by that wire's id so a name chosen for it
  cannot land on another, suggested from the wire's name, then its label,
  then the pin inside; and anything that stops it being done safely.
  """
  inside = _inside(doc, ids)
  problems = []
  if not any(c.get("id") in inside for c in doc.cells):
    problems.append("select at least one cell to make a component of")
  _internal, crossing, wire_problems = _crossing(doc, inside)
  problems.extend(wire_problems)
  ports = []
  used = set()
  for net in crossing:
    driver = net.get("from")
    driven_inside = isinstance(driver, dict) and driver.get("cell") in inside
    end = driver if driven_inside else next(
      e for e in loads_of(net) if isinstance(e, dict) and e.get("cell") in inside)
    base = net.get("name") or net.get("label") or _pin_name(doc, end) or "p"
    name, n = str(base), 2
    while name in used:
      name, n = "%s_%d" % (base, n), n + 1
    used.add(name)
    ports.append({"key": net.get("id"), "name": name,
                  "dir": "out" if driven_inside else "in",
                  "width": net.get("width", 1), "y": _end_y(doc, registry, end)})
  ports.sort(key=lambda p: (p["dir"] != "in", p["y"]))
  for port in ports:
    port.pop("y")
  return {"ports": ports, "problems": problems}


def _end_y(doc, registry, end):
  from . import routing
  at = routing.endpoint_position(doc, end, registry)
  return at[1] if at else 0.0


def extract(doc, registry, ids, name, names=None):
  """Make the component and put an instance of it where the selection was.

  `doc` is changed in place; returns (definition Document, ref, the new
  instance's id). `names` maps
  a crossing wire's id to the port name chosen for it -- by wire, never by
  position in a list, so a reordered dialog cannot swap two names. Raises
  ComponentError, changing nothing, if it cannot be done.
  """
  found = plan(doc, registry, ids)
  if found["problems"]:
    raise ComponentError("; ".join(found["problems"]))
  names = dict(names or {})
  ports = found["ports"]
  for port in ports:
    chosen = str(names.get(port["key"], port["name"])).strip()
    if not chosen:
      raise ComponentError("every port needs a name")
    port["name"] = chosen
  if len(set(p["name"] for p in ports)) != len(ports):
    raise ComponentError("two ports cannot share a name: %s" % ", ".join(
      sorted(set(p["name"] for p in ports if [q["name"] for q in ports].count(p["name"]) > 1))))

  inside = _inside(doc, ids)
  internal, crossing, _problems = _crossing(doc, inside)
  by_key = dict((p["key"], p) for p in ports)

  cells = [c for c in doc.cells if c.get("id") in inside]
  shapes = [s for s in doc.shapes if s.get("id") in inside]
  boxes = [b for b in doc.containers if b.get("id") in inside]
  bounds = None
  for kind, items in (("cell", cells), ("shape", shapes), ("container", boxes)):
    for item in items:
      bounds = _union(bounds, containers.item_box(doc, registry, kind, item))
  dx, dy = MARGIN + PORT_GAP - bounds[0], MARGIN - bounds[1]

  child = new_document(str(name).strip() or "component")
  child.canvas.update({k: copy.deepcopy(v) for k, v in doc.canvas.items()
                       if k in ("grid", "font", "symbolScale", "arrows", "hops")})
  for item in copy.deepcopy(cells):
    child.cells.append(item)
  for item in copy.deepcopy(shapes):
    child.shapes.append(item)
  if boxes:
    child.data["containers"] = copy.deepcopy(boxes)
  ref = ref_for(name)
  for kind, items in (("cell", child.cells), ("shape", child.shapes),
                      ("container", child.containers)):
    for item in items:
      if item.get("parentId") not in inside:
        item.pop("parentId", None)
  containers.move(child, set(i.get("id") for i in child.cells + child.shapes
                             + child.containers), dx, dy)
  used = set()
  for item in child.cells + child.shapes + child.containers:
    if item.get("styleRef") and item["styleRef"] in doc.styles:
      used.add(item["styleRef"])
  if used:
    child.data["styles"] = {k: copy.deepcopy(doc.styles[k]) for k in sorted(used)}
  for net in internal:
    moved = copy.deepcopy(net)
    for load in loads_of(moved):
      load["waypoints"] = []
    child.nets.append(moved)

  # Ports: inputs down the left, outputs down the right, in the order their
  # pins inside run down the sheet.
  right = bounds[2] + MARGIN + 2 * PORT_GAP
  rows = {"in": 0, "out": 0}
  for port in ports:
    side = port["dir"]
    y = MARGIN + rows[side] * PORT_STEP
    rows[side] += 1
    port["cell"] = "port_%s" % slug(port["name"])
    while child.cell(port["cell"]) is not None:
      port["cell"] += "_"
    child.cells.append({"id": port["cell"], "type": "port_in" if side == "in" else "port_out",
                        "x": MARGIN if side == "in" else right, "y": y,
                        "label": port["name"]})

  # The instance, where the selection was, in the container that held it.
  parent = _common_parent(doc, inside)
  instance_id = _fresh_id(doc, slug(name))
  # Shown with a miniature of what it holds: it was made from that.
  instance = {"id": instance_id, "type": "sheet", "ref": ref, "x": bounds[0], "y": bounds[1],
              "label": str(name).strip(), "preview": True}
  if parent is not None:
    instance["parentId"] = parent

  rewired = []
  for net in crossing:
    port = by_key[net.get("id")]
    driver = net.get("from")
    inner = copy.deepcopy(net)
    inner["id"] = "n_%s" % port["cell"]
    if port["dir"] == "out":
      inner["to"] = [dict(load, waypoints=[]) for load in loads_of(inner)
                     if load.get("cell") in inside] + [
        {"cell": port["cell"], "pin": "p", "waypoints": []}]
      outer = dict(net, **{"from": {"cell": instance_id, "pin": port["name"]}})
      outer["to"] = [dict(load, waypoints=[]) for load in loads_of(net)
                     if load.get("cell") not in inside]
    else:
      inner["from"] = {"cell": port["cell"], "pin": "p"}
      inner["to"] = [dict(load, waypoints=[]) for load in loads_of(inner)
                     if load.get("cell") in inside]
      outer = dict(net, to=[dict(load, waypoints=[]) for load in loads_of(net)
                            if load.get("cell") not in inside]
                   + [{"cell": instance_id, "pin": port["name"], "waypoints": []}])
      outer["from"] = driver
    child.nets.append(inner)
    rewired.append(outer)

  child.canvas["width"] = int(right + 20 + MARGIN)
  child.canvas["height"] = int(max(bounds[3] + 2 * MARGIN,
                                   MARGIN * 2 + max(rows.values() or [0]) * PORT_STEP))
  child.normalize(registry)
  problems = [str(i) for i in child.validate(registry) if i.level == "error"]
  if problems:
    raise ComponentError("the component would not be sound: %s" % "; ".join(problems[:3]))
  # A linked block taken into the component keeps pointing at the same file:
  # its ref is relative to the drawing that holds it, and that is now the
  # component, one folder down -- `components/sm.dlg` from the drawing is
  # `sm.dlg` from beside it. Rebased only now, as the check above resolves
  # refs against the drawing's registry; the server opens the result where
  # it will be written before writing it.
  for item in child.cells:
    if item.get("ref"):
      item["ref"] = rebase(item["ref"], posixpath.dirname(ref))

  keep = [n for n in doc.nets if n not in internal and n not in crossing]
  doc.data["nets"] = keep + rewired
  doc.data["cells"] = [c for c in doc.cells if c.get("id") not in inside] + [instance]
  doc.data["shapes"] = [s for s in doc.shapes if s.get("id") not in inside]
  if doc.containers:
    doc.data["containers"] = [b for b in doc.containers if b.get("id") not in inside]
  doc.data["groups"] = [g for g in doc.groups
                        if not any(m in inside for m in g.get("members", []))]
  return child, ref, instance_id


def _union(box, other):
  if other is None:
    return box
  if box is None:
    return other
  x0, y0 = min(box[0], other[0]), min(box[1], other[1])
  x1 = max(box[0] + box[2], other[0] + other[2])
  y1 = max(box[1] + box[3], other[1] + other[3])
  return (x0, y0, x1 - x0, y1 - y0)


def _common_parent(doc, inside):
  """The container holding all of the selection's outermost things, or None."""
  parents = set()
  for item in doc.cells + doc.shapes + doc.containers:
    if item.get("id") in inside and item.get("parentId") not in inside:
      parents.add(item.get("parentId"))
  return parents.pop() if len(parents) == 1 else None


def _fresh_id(doc, base):
  used = set(c.get("id") for c in doc.cells) | set(s.get("id") for s in doc.shapes) \
    | set(b.get("id") for b in doc.containers) | set(n.get("id") for n in doc.nets)
  candidate, n = "u_%s" % base, 2
  while candidate in used:
    candidate, n = "u_%s_%d" % (base, n), n + 1
  return candidate


def rebase(ref, folder):
  """`ref`, written beside a drawing, as seen from `folder` under it.

  Both are relative to the same drawing's folder, with forward slashes as a
  ref is stored.
  """
  target = posixpath.normpath(ref.replace("\\", "/"))
  return posixpath.relpath(target, folder or ".")


def independent_ref(ref, existing):
  """A ref for a copy of `ref`'s definition that is not one of `existing`."""
  folder, name = os.path.split(ref)
  stem = name[:-4] if name.endswith(".dlg") else name
  n = 2
  while True:
    candidate = "%s/%s_%d.dlg" % (folder, stem, n) if folder else "%s_%d.dlg" % (stem, n)
    if candidate not in existing:
      return candidate
    n += 1
