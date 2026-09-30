"""Corridors for crossover wires, decided a channel at a time.

A wire between two pins that face each other across a gap is a Z: out along
the source pin's row, down one corridor, in along the load pin's row. The
router used to choose that corridor one wire at a time, in document order,
each taking the free column nearest the middle of its own gap. That is greedy
and it cannot see ahead: where one wire leaves a row and another arrives at
the same row, both have a leg on that line, and they stay apart only if the
leaving wire's corridor is left of the arriving one's. An early wire that
took the middle of the gap could leave a later one no corridor on the right
side of it, and the router then drew the later wire on top of the earlier
one -- the wire-short that auto layout kept producing.

So every crossover is collected first and the corridors are handed out
together. Each ordering requirement is an edge of a directed graph; the
corridors are assigned in topological order of that graph, each as near the
middle of its own gap as its predecessors and successors allow. A graph with
a cycle has no assignment of one corridor per wire that satisfies it, so an
edge inside a cycle is dropped rather than obeyed -- the router's own search
still stands behind every corridor handed out here.

Everything in here is a pure function of the crossovers passed in, and every
collection is walked in a fixed order, so the same drawing always gets the
same corridors whatever order its nets are listed in.
"""

from . import drc

# The gap kept between two corridors that must not share a line, and between
# a corridor and the end of a leg that must not reach it. Two corridors this
# far apart read as two wires; closer, the DRCs call them crowded.
GAP = drc.WIRE_GAP


class Crossover:
  """One wire's Z between two facing pins, as the assignment sees it.

  `left` and `right` are the two stub ends, whichever the wire runs from.
  `candidates` are the corridor positions that clear every cell, on the same
  lattice the router's own search uses, so an assigned corridor is one it
  could have found by itself.
  """

  def __init__(self, key, net, keys, left, right, candidates):
    self.key = key
    self.net = net
    self.keys = keys
    self.left = left
    self.right = right
    self.candidates = sorted(candidates)
    self.preferred = (left[0] + right[0]) / 2.0
    self.lower = left[0]
    self.upper = right[0]
    self.top = min(left[1], right[1])
    self.bottom = max(left[1], right[1])

  def order(self):
    return (self.preferred, self.left[1], self.right[1], _text(self.key))


def _text(key):
  return repr(key)


def _related(one, two):
  """True when two crossovers are one signal and may share lines."""
  return one.net == two.net or bool(one.keys & two.keys)


def _same_row(y1, y2):
  return abs(y1 - y2) < GAP


def constraints(crossovers):
  """The ordering edges and the bounds each crossover's corridor must keep.

  Returns (edges, lower, upper): `edges` is a sorted list of (i, j), meaning
  crossover i's corridor must be left of crossover j's, and `lower`/`upper`
  are per-crossover limits on where the corridor may go.

  An edge comes from one wire leaving a row rightward and another arriving on
  the same row from the left: the leaving wire's leg ends at its corridor and
  the arriving wire's leg starts at its own, so the two legs miss only if the
  first corridor is left of the second. A bound comes from two wires leaving
  (or arriving at) the same row in the same direction: the one further left
  has to turn off before it reaches the other's pin.
  """
  count = len(crossovers)
  lower = [c.lower for c in crossovers]
  upper = [c.upper for c in crossovers]
  edges = set()
  for i in range(count):
    one = crossovers[i]
    for j in range(count):
      if i == j:
        continue
      two = crossovers[j]
      if _related(one, two):
        continue
      # One leaves the row `one.left[1]` rightward; two arrives at
      # `two.right[1]` from the left. They overlap only if one's pin is left
      # of two's.
      if (_same_row(one.left[1], two.right[1])
          and one.left[0] < two.right[0]):
        edges.add((i, j))
      # Both leave the same row rightward: the one starting further left must
      # turn down before it reaches the other's pin.
      if (_same_row(one.left[1], two.left[1])
          and one.left[0] < two.left[0] - drc.TOUCHING):
        upper[i] = min(upper[i], two.left[0] - GAP)
      # Both arrive at the same row from the left: the one ending further
      # right must come down after the other's pin.
      if (_same_row(one.right[1], two.right[1])
          and one.right[0] < two.right[0] - drc.TOUCHING):
        lower[j] = max(lower[j], one.right[0] + GAP)
  # A bound nothing can satisfy is not worth keeping: the corridor goes where
  # the router would have put it, and the DRCs report what is left.
  for i, c in enumerate(crossovers):
    if not any(lower[i] < x < upper[i] for x in c.candidates):
      lower[i], upper[i] = c.lower, c.upper
  return sorted(edges), lower, upper


def strongly_connected(count, edges):
  """Groups of crossovers that lie on a common cycle, by Tarjan.

  Iterative, so a long chain of constraints cannot exhaust the recursion
  limit. Groups of one are left out: a crossover on its own is not a cycle.
  """
  graph = [[] for _ in range(count)]
  for source, target in edges:
    graph[source].append(target)
  index = {}
  low = {}
  stack = []
  on_stack = set()
  found = []
  counter = [0]

  def visit(node):
    index[node] = low[node] = counter[0]
    counter[0] += 1
    stack.append(node)
    on_stack.add(node)
    work = [(node, iter(graph[node]))]
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

  for node in range(count):
    if node not in index:
      visit(node)
  return sorted(found)


def _acyclic(crossovers, edges):
  """The edges with every cycle broken.

  Within a cycle the crossovers are ranked by where they would like to sit,
  and an edge that points backwards against that ranking is dropped. What is
  left inside the group is ordered by that ranking, so it cannot loop.
  """
  rank = {}
  for number, group in enumerate(strongly_connected(len(crossovers), edges)):
    ordered = sorted(group, key=lambda i: crossovers[i].order())
    for position, i in enumerate(ordered):
      rank[i] = (number, position)
  kept = []
  for i, j in edges:
    if (i in rank and j in rank and rank[i][0] == rank[j][0]
        and rank[i][1] >= rank[j][1]):
      continue
    kept.append((i, j))
  return kept


def _topological(crossovers, edges):
  """Every crossover once, each after all it must be right of."""
  count = len(crossovers)
  successors = [[] for _ in range(count)]
  waiting = [0] * count
  for i, j in edges:
    successors[i].append(j)
    waiting[j] += 1
  ready = sorted((crossovers[i].order(), i) for i in range(count)
                 if not waiting[i])
  out = []
  while ready:
    _order, i = ready.pop(0)
    out.append(i)
    for j in successors[i]:
      waiting[j] -= 1
      if not waiting[j]:
        ready.append((crossovers[j].order(), j))
        ready.sort()
  return out


def assign(crossovers):
  """A corridor x for every crossover that has somewhere to go.

  Returns {crossover key: x}. A crossover whose gap has no candidate at all
  is left out, which leaves it to the router's own search.
  """
  if not crossovers:
    return {}
  edges, lower, upper = constraints(crossovers)
  edges = _acyclic(crossovers, edges)
  order = _topological(crossovers, edges)
  predecessors = [[] for _ in crossovers]
  successors = [[] for _ in crossovers]
  for i, j in edges:
    predecessors[j].append(i)
    successors[i].append(j)

  # The latest each corridor may sit and still leave room for everything
  # that has to be right of it.
  latest = [None] * len(crossovers)
  for i in reversed(order):
    limit = upper[i]
    for j in successors[i]:
      if latest[j] is not None:
        limit = min(limit, latest[j] - GAP)
    fits = [x for x in crossovers[i].candidates if lower[i] < x < limit]
    latest[i] = fits[-1] if fits else None

  chosen = {}
  placed = []
  for i in order:
    c = crossovers[i]
    floor = lower[i]
    for j in predecessors[i]:
      if j in chosen:
        floor = max(floor, chosen[j] + GAP)
    ceiling = upper[i] if latest[i] is None else min(upper[i], latest[i]
                                                     + drc.TOUCHING)
    inside = [x for x in c.candidates if floor < x < ceiling]
    if not inside:
      inside = [x for x in c.candidates if floor < x < upper[i]]
    if not inside:
      inside = [x for x in c.candidates if lower[i] < x < upper[i]]
    if not inside:
      continue
    spaced = [x for x in inside
              if all(abs(x - chosen[k]) >= GAP for k in placed
                     if _shares_column(c, crossovers[k]))]
    pool = spaced or inside
    best = min(pool, key=lambda x: (abs(x - c.preferred), x))
    chosen[i] = best
    placed.append(i)
  return {crossovers[i].key: x for i, x in chosen.items()}


def _shares_column(one, two):
  """True when two corridors would run alongside each other if too close."""
  if _related(one, two):
    return False
  return one.top < two.bottom + GAP and two.top < one.bottom + GAP
