"""Phase 0: the constraint graph behind the shorts, and whether it has cycles.

A net routed between two facing pins is a Z: out along the source row, down one
corridor, in along the load row. Where one net leaves a row and another arrives
at the same row, both have a horizontal leg at that height, and they stay apart
only if the leaving net's corridor is left of the arriving net's. That is an
ordering constraint between two nets, and every such pair contributes one.

Collect them all and you have a directed graph. If it is acyclic, assigning
corridors in topological order is always possible -- a left-edge assignment
will find it, and no router change beyond that is needed. If it has a cycle,
no assignment of one corridor per net can satisfy it, and the only remedy is a
dogleg: splitting one net's vertical run in two so its node splits with it.

This script decides which of those we are looking at. It changes nothing.

    python3 benchmarks/channel_graph.py [--rebuild]

Arranged layouts are cached under benchmarks/.cache because laying out a
72-gate drawing takes about a minute and the analysis takes milliseconds.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drawlogic import drc, layout, routing, symbols          # noqa: E402
from drawlogic.doc import Document                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "auto-layout")
CACHE = os.path.join(HERE, ".cache")


def arranged(path, registry, rebuild=False):
  """The fixture after auto layout, cached on disk."""
  if not os.path.isdir(CACHE):
    os.makedirs(CACHE)
  cached = os.path.join(CACHE, os.path.basename(path))
  if os.path.isfile(cached) and not rebuild:
    doc = Document.load(cached)
    doc.normalize(registry)
    return doc
  doc = Document.load(path)
  doc.normalize(registry)
  layout.arrange(doc, registry)
  doc.save(cached)
  return doc


def legs_of(points):
  """Horizontal legs as (y, pin_end_x, corridor_end_x).

  A leg's corridor end is whichever end meets the vertical run; the other end
  is the pin. Legs that are not part of a corner are ignored: they belong to
  no corridor and impose no ordering.
  """
  found = []
  for index in range(len(points) - 1):
    a, b = points[index], points[index + 1]
    if abs(a[1] - b[1]) > 1e-6:
      continue
    before = points[index - 1] if index else None
    after = points[index + 2] if index + 2 < len(points) else None
    if after is not None and abs(after[0] - b[0]) < 1e-6:
      found.append((a[1], a[0], b[0]))          # corridor at the far end
    elif before is not None and abs(before[0] - a[0]) < 1e-6:
      found.append((a[1], b[0], a[0]))          # corridor at the near end
  return found


def constraints(doc, registry):
  """Edges `A -> B` meaning A's corridor must be left of B's."""
  legs = {}
  for net, branches in routing.route_all(doc, registry):
    mine = []
    for points in branches:
      mine.extend(legs_of(points))
    if mine:
      legs[net["id"]] = mine

  edges = set()
  ids = sorted(legs)
  for i, one in enumerate(ids):
    for two in ids[i + 1:]:
      for y1, pin1, cor1 in legs[one]:
        for y2, pin2, cor2 in legs[two]:
          if abs(y1 - y2) >= drc.WIRE_GAP:
            continue
          # Opposite-facing legs are the ones that order two nets: one runs
          # out to its corridor, the other runs in from its own. Two legs
          # facing the same way constrain a pin, not each other.
          one_right = cor1 > pin1
          two_right = cor2 > pin2
          if one_right == two_right:
            continue
          lo1, hi1 = min(pin1, cor1), max(pin1, cor1)
          lo2, hi2 = min(pin2, cor2), max(pin2, cor2)
          if min(hi1, hi2) - max(lo1, lo2) <= drc.TOUCHING:
            continue                             # already disjoint
          edges.add((one, two) if one_right else (two, one))
  return sorted(legs), sorted(edges)


def cycles(nodes, edges):
  """Strongly connected components bigger than one node, by Tarjan."""
  graph = {node: [] for node in nodes}
  for source, target in edges:
    graph[source].append(target)

  index = {}
  low = {}
  stack = []
  on_stack = set()
  found = []
  counter = [0]

  def strong(node):
    # Iterative: a deep graph would blow the recursion limit.
    work = [(node, iter(graph[node]))]
    index[node] = low[node] = counter[0]
    counter[0] += 1
    stack.append(node)
    on_stack.add(node)
    while work:
      here, children = work[-1]
      advanced = False
      for child in children:
        if child not in index:
          index[child] = low[child] = counter[0]
          counter[0] += 1
          stack.append(child)
          on_stack.add(child)
          work.append((child, iter(graph[child])))
          advanced = True
          break
        if child in on_stack:
          low[here] = min(low[here], index[child])
      if advanced:
        continue
      work.pop()
      if work:
        low[work[-1][0]] = min(low[work[-1][0]], low[here])
      if low[here] == index[here]:
        group = []
        while True:
          out = stack.pop()
          on_stack.discard(out)
          group.append(out)
          if out == here:
            break
        if len(group) > 1:
          found.append(sorted(group))

  for node in nodes:
    if node not in index:
      strong(node)
  return found


def main():
  rebuild = "--rebuild" in sys.argv
  registry = symbols.default_registry()
  names = sorted(n for n in os.listdir(FIXTURES) if n.endswith(".dlg"))

  print("%-20s %6s %7s %7s %8s %s"
        % ("fixture", "nets", "edges", "shorts", "cycles", "cycle sizes"))
  totals = [0, 0, 0, 0]
  for name in names:
    doc = arranged(os.path.join(FIXTURES, name), registry, rebuild)
    nodes, edges = constraints(doc, registry)
    loops = cycles(nodes, edges)
    shorts = sum(1 for v in drc.check(doc, registry) if v.rule == "wire-short")
    sizes = ", ".join(str(len(group)) for group in loops) or "-"
    print("%-20s %6d %7d %7d %8d %s"
          % (name, len(nodes), len(edges), shorts, len(loops), sizes))
    sys.stdout.flush()
    totals[0] += len(nodes)
    totals[1] += len(edges)
    totals[2] += shorts
    totals[3] += len(loops)
  print("%-20s %6d %7d %7d %8d" % ("TOTAL", *totals))

  print()
  if totals[3] == 0:
    print("Acyclic everywhere: a left-edge assignment per channel can satisfy")
    print("every constraint. Phase 1 alone should reach zero shorts; doglegs")
    print("(Phase 2) are not needed for this corpus.")
  else:
    print("Cycles present: no assignment of one corridor per net can satisfy")
    print("them. Phase 2 (doglegs) is required for the %d cycle(s) above."
          % totals[3])


if __name__ == "__main__":
  main()
