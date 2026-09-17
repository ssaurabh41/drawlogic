# Getting auto layout to zero DRC errors

A specification, not a change. Nothing here is implemented.

The goal is the one stated for the benchmark corpus: **zero DRC errors, with
warnings minimised and without paying for it in area, wire length or runtime.**
The last clause is what rules out the obvious answer; see *Rejected approaches*.

---

## 1. What is actually wrong

Auto layout leaves 46 DRC errors across the ten benchmark fixtures. They are
not spread evenly and they are not varied:

| rule | count | what it is |
|---|---:|---|
| `wire-short` | 31 | two unrelated nets drawn on the same line |
| `wire-crossing` | ~10 | a crossing the router could not bridge cleanly |
| `wire-over-cell` | ~5 | a wire run through a gate body |

The shorts dominate, and every one of them has the same shape.

A net routed between two facing pins is a Z: out along the source pin's row,
down a single **corridor** at some x, then in along the load pin's row.

```
    source ---------+                      <- horizontal leg, at source row
                    |                       <- vertical leg, the corridor
                    +---------- load       <- horizontal leg, at load row
```

Where one net *leaves* a row and another *arrives* at the same row, both have
a horizontal leg at that height. They stay apart only if the leaving net's
corridor is to the left of the arriving net's. Write that as a constraint
`A < B`. Every pair of nets sharing a row height contributes one.

The router does not solve those constraints. `route_all` walks `doc.nets` in
document order, and each net calls `_pick_corridor`, which searches outward
from its own preferred x for a slot no earlier wire has taken. It is greedy
and it is per-net: it has no view of the constraints the nets still to be
routed will impose. When it finds nothing free it returns `preferred`
anyway -- deliberately, so a crowded drawing still produces a wire rather
than nothing -- and that fallback is the short.

## 2. What was measured, and what it rules out

Four experiments, all reproducible against `benchmarks/auto-layout/`.

**Column width is not the answer.** On `10-mixed`, sweeping the column gap:

| gap | errors | warnings | width |
|---:|---:|---:|---:|
| 110 | 14 | 129 | 1010 |
| 200 | 16 | 64 | 1550 |
| 320 | 11 | 41 | 2270 |
| 480 | 11 | 41 | 3230 |

Warnings fall a long way; errors do not, and at gap 200 they get worse. On a
constructed channel of eight fully crossed nets, four shorts remain at every
width from 120 to 560. Room is not what is missing.

**No pair is individually impossible.** For each of the 31 shorts, checking
whether the two nets constrain each other in *both* directions -- a two-cycle,
which no single-corridor assignment can satisfy -- found **zero**. One case was
unclassifiable. So for every pair taken alone, a legal ordering exists.

**But order alone does not reach zero.** Re-routing `10-mixed` under twelve
random net orderings, layout held fixed:

```
document order   shorts 6   errors 10   warnings 118
best of twelve   shorts 5   errors  7   warnings 126
range            shorts 5-7 errors 7-10 warnings 104-145
```

Order matters and is worth about three errors. It never approaches zero.
Pairwise-satisfiable does not mean jointly satisfiable: fixing `A < B` can
break `A < C`. That is the signature of **cycles longer than two** in the
constraint graph, which the pairwise test cannot see.

**The failure is concentrated.** Seven of the ten fixtures already route with
zero errors. All 46 are in `02-branching`, `05-reconverging`, `08-dense`,
`09-crowded` and `10-mixed`.

## 3. The mechanism, named

This is textbook channel routing. The constraints form a **vertical constraint
graph** (VCG): a node per net crossing a channel, an edge `A -> B` when A's
corridor must be left of B's. Then:

- If the VCG is **acyclic**, a legal assignment exists and is found by
  processing nets in topological order -- the left-edge algorithm.
- If the VCG has a **cycle** of any length, no assignment of one corridor per
  net can satisfy it. The standard and only remedy is a **dogleg**: splitting
  one net's vertical run into two corridors joined by a short horizontal jog,
  which splits its node and breaks the cycle.

The evidence above says this drawing set has no 2-cycles but does not behave
like an acyclic system. So the honest position is that both parts are probably
needed, and which matters more is a measurement nobody has taken yet. That
measurement is Phase 0 and it is cheap.

## 4. Rejected approaches

**Per-channel widening** (implemented, measured, discarded -- see commit
`5ac4832`). Give each column gap the width its own net density needs. Halves
warnings on `10-mixed` (129 -> 59) for a third more width, but leaves one more
error than it started with and breaks the documented property that a second
layout pass changes nothing. Recorded because the warning result is real and
may be worth revisiting once errors are zero.

**A lane per net** (`codex/auto-layout-optimization`). Reaches zero errors by
giving every net its own horizontal track and stacking cells down a staircase.
It works, and it costs 327x the area and 136x the wire length on
`02-branching`. This is the approach the "without paying for it" clause exists
to exclude.

## 5. Phase 0 -- measure the cycle spectrum (prerequisite)

Before writing any router code, build the VCG for each channel of each fixture
and report, per channel: node count, edge count, whether it is acyclic, and if
not, the length and number of the cycles.

This is analysis only -- no production change -- and it decides the rest:

- Mostly acyclic: Phase 1 alone may reach zero. Phase 2 becomes contingency.
- Cycles common: Phase 2 is the substance and Phase 1 is its scaffolding.

Deliverable: a script under `benchmarks/` and a table. Half a day.

## 6. Phase 1 -- assign corridors per channel, not per net

Replace the greedy per-net search with one assignment per channel.

For each channel, collect the nets crossing it. Build the VCG. Take a
topological order; where the graph is cyclic, break it provisionally (Phase 2
replaces this with a dogleg). Then run the **left-edge algorithm**: sort nets by
the left end of their horizontal span and pack them into tracks, each net
taking the leftmost track whose occupants do not overlap it. The result is an
assignment using the minimum number of tracks the density allows.

Where it goes:

- New module `drawlogic/channels.py`. Pure function: takes the routed geometry
  and returns a corridor x per net per channel. No document mutation.
- `route_all` gains a pre-pass that computes assignments and hands them to
  `route`, which passes them to `_route_hh` as the preferred corridor.
- `_pick_corridor` keeps its existing search as the fallback for anything the
  assignment does not cover -- free endpoints, hierarchy blocks, the `vv` and
  corner cases. Nothing regresses for drawings that route cleanly today.

Determinism: the assignment must be a pure function of the document. Sort every
collection by net id, never by iteration order.

## 7. Phase 2 -- doglegs, for the cycles that remain

A dogleg changes the route shape from one corridor to two:

```
  before:  [a, (x, ay), (x, by), b]
  after:   [a, (x1, ay), (x1, ym), (x2, ym), (x2, by), b]
```

The net leaves on corridor `x1`, steps across at an intermediate row `ym`, and
arrives on corridor `x2`. In VCG terms its node is split, so a constraint that
demanded the net be both left of and right of another is satisfied by the two
halves separately.

Rules:

- Apply only to nets on a cycle, and only the minimum number needed to break
  it. A dogleg costs two bends and a horizontal run; unconditional use would
  trade shorts for hop and bend warnings.
- `ym` is chosen from the rows already free in that channel, by the same
  `Sheet.free` test the corridor search uses. If no row is free the net keeps
  its single corridor and the error is reported rather than hidden.
- The jog is a route shape, not a document change. Waypoints, the file format
  and both renderers are untouched: they already draw whatever point list the
  router returns.

## 8. Keeping warnings and the other costs down

Zero errors is the gate; it is not the whole goal.

- **Warnings.** Doglegs add bends and can add hops. Budget: total warnings must
  not rise above today's 558 across the corpus. Measure `bends`, `hops` and
  `text-to-wire` separately, since those are where a jog shows up.
- **Wire length and area.** Neither should move measurably. Assignment changes
  which corridor a net uses, not how far apart the columns are; a dogleg adds
  one short horizontal run. Budget: +2% wire length, 0% area.
- **Runtime.** Today a 72-gate layout takes about 75 s, and `drc.check` is 85%
  of it (1.28 s of every 1.50 s `_score` call). Channel assignment is
  O(n log n) per channel and runs once per route, not once per candidate, so it
  should be invisible. Budget: no regression. Worth noting separately that the
  85% figure is the real runtime target, and it is independent of this work.

## 9. Parity with the browser

`drawlogic/web/js/routing.js` is a hand port of `routing.py` and
`tests/test_js_parity.py` compares them net for net. This is the project's one
standing drift risk and the reason to keep the change narrow.

- Phase 1 and Phase 2 both live inside the routing layer, so both must be
  mirrored: `channels.py` needs a `channels.js`, and `routeHH` needs the same
  dogleg branch.
- Write Python first, get it green, then port, and let the parity suite be the
  acceptance test for the port. Do not develop both at once.
- `tests/test_js_parity.py` already compares routes, junctions, hops, label and
  arrow spots. It needs one addition: a fixture with a known cycle, so the
  dogleg path is exercised on both sides rather than only the common path.

## 10. Test plan

Each item names what must go red if the change is removed.

1. **Left-edge assignment, unit level.** A channel with a known-optimal packing
   gets that packing. Red if the assignment wastes a track.
2. **VCG construction.** A hand-built three-net cycle is detected as a cycle; a
   chain is not. Red if cycle detection is vacuous.
3. **The constructed channel.** Eight fully crossed nets, the case that holds
   four shorts at every width today, routes with zero shorts. This is the
   headline regression test.
4. **Dogleg shape.** A net on a cycle comes back with six points and two
   distinct corridor x values; the jog row is clear of other runs.
5. **Doglegs are not gratuitous.** On a drawing that routes cleanly today,
   every route still has four points. Red if doglegs fire when unneeded.
6. **Corpus gate.** All ten fixtures: zero DRC errors, warnings <= 558, wire
   length within 2%, area unchanged, runtime not worse.
7. **Determinism.** Two routes of the same document give identical points;
   shuffling `doc.nets` gives identical geometry. Red if assignment depends on
   iteration order.
8. **Parity.** `tests/test_js_parity.py` green, including the new cycle
   fixture.
9. **Idempotency.** `arrange` twice changes nothing -- the property the
   widening experiment broke.

## 11. Risks

- **The corpus is synthetic.** All ten fixtures are generated. Zero errors on
  them is not zero on a drawing somebody actually made. The seven shipped
  examples must be measured alongside, and they behave differently: the
  transpose pass helped the benchmarks and slightly worsened crossings on the
  examples.
- **Assignment can move a wire somewhere worse.** A corridor that is legal may
  still read badly -- through a label, or far from the pins it joins. Warnings
  are the guard, which is why the budget is stated.
- **Cycles may be rarer than the plateau suggests.** The shuffle experiment is
  indirect evidence. If Phase 0 finds few cycles, Phase 2 should be deferred,
  not built on principle.
- **The port is where this breaks.** Two implementations of a constraint solver
  will drift further than two implementations of a greedy search. If Phase 0
  says the assignment is substantial, it is worth asking whether routing should
  move behind the existing `/api/layout` call for large drawings rather than
  being ported at all -- a design question this spec does not settle.

## 12. Order of work

| step | outcome | rough size |
|---|---|---|
| Phase 0 | cycle spectrum table; decides scope | half a day |
| Phase 1 Python | `channels.py`, left-edge assignment, tests 1-3, 6-7 | 2-3 days |
| Phase 1 port | `channels.js`, parity green | 1 day |
| Phase 2 Python | doglegs, tests 4-5 | 2 days |
| Phase 2 port | dogleg branch in `routeHH`, parity fixture | 1 day |
| Corpus + docs | full gate, DOCUMENTATION and REVIEW updates | 1 day |

Phase 1 is independently shippable. If Phase 0 says the graphs are mostly
acyclic, stop after it and measure before deciding on Phase 2.
