"""Nets with one driver and many loads, and the upgrade that made them.

Before version 2, a net had exactly one load. A signal reaching three places
was three separate nets that happened to share a driving pin and happened to be
drawn on top of each other; junction dots were what hid the seam. That was a
convincing illusion, not a model -- it meant a rail could not carry one name,
its width could not be checked as a whole, and nothing could tell a fan-out
apart from a short.

Usage:

    python3 -m unittest tests.test_nets
"""

import json
import os
import tempfile
import unittest

from drawlogic import routing
from drawlogic.doc import Document, loads_of, new_document, upgrade_from_v1
from drawlogic.symbols import default_registry

from tests import ROOT


def v1(nets, cells=None):
  """A version 1 document, as one would have been written on disk."""
  return {
    "format": "drawlogic", "version": 1, "title": "old",
    "canvas": {"width": 800, "height": 400},
    "cells": cells or [
      {"id": "u1", "type": "and2", "x": 100, "y": 100},
      {"id": "a", "type": "inv", "x": 300, "y": 60},
      {"id": "b", "type": "inv", "x": 300, "y": 200},
    ],
    "nets": nets, "shapes": [], "groups": [],
  }


def net(net_id, source, target, name=None, waypoints=None):
  out = {"id": net_id, "name": name, "width": 1,
         "from": {"cell": source[0], "pin": source[1]},
         "to": {"cell": target[0], "pin": target[1]}, "style": {}}
  if waypoints is not None:
    out["waypoints"] = waypoints
  return out


class TestTheUpgrade(unittest.TestCase):

  def test_nets_off_one_pin_become_one_net(self):
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a")),
      net("n2", ("u1", "y"), ("b", "a")),
    ]))
    self.assertEqual(len(data["nets"]), 1)
    self.assertEqual(len(data["nets"][0]["to"]), 2)

  def test_the_surviving_net_keeps_the_name_that_was_given(self):
    # A rail was usually one named net and several unnamed ones, because only
    # one of them could carry the name.
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a"), name="clk"),
      net("n2", ("u1", "y"), ("b", "a")),
    ]))
    self.assertEqual(data["nets"][0]["name"], "clk")

  def test_a_name_arriving_second_is_still_kept(self):
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a")),
      net("n2", ("u1", "y"), ("b", "a"), name="clk"),
    ]))
    self.assertEqual(data["nets"][0]["name"], "clk")

  def test_two_different_names_are_left_as_two_nets(self):
    # Two names on one pin is either a mistake or a deliberate alias, and
    # silently dropping one would be worse than leaving the drawing alone.
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a"), name="clk"),
      net("n2", ("u1", "y"), ("b", "a"), name="gclk"),
    ]))
    self.assertEqual(len(data["nets"]), 2)

  def test_nets_from_different_pins_stay_apart(self):
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a")),
      net("n2", ("a", "y"), ("b", "a")),
    ]))
    self.assertEqual(len(data["nets"]), 2)

  def test_a_waypoint_moves_onto_the_branch_it_belonged_to(self):
    data = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a"), waypoints=[[200, 200]]),
      net("n2", ("u1", "y"), ("b", "a")),
    ]))
    loads = data["nets"][0]["to"]
    self.assertEqual(loads[0]["waypoints"], [[200, 200]])
    self.assertNotIn("waypoints", loads[1])

  def test_an_old_file_still_opens(self):
    handle, path = tempfile.mkstemp(suffix=".dlg")
    with os.fdopen(handle, "w") as out:
      json.dump(v1([net("n1", ("u1", "y"), ("a", "a"))]), out)
    try:
      doc = Document.load(path)
      self.assertEqual(doc.data["version"], 2)
      self.assertEqual(len(loads_of(doc.nets[0])), 1)
    finally:
      os.unlink(path)

  def test_upgrading_twice_is_the_same_as_once(self):
    once = upgrade_from_v1(v1([
      net("n1", ("u1", "y"), ("a", "a")),
      net("n2", ("u1", "y"), ("b", "a")),
    ]))
    self.assertEqual(upgrade_from_v1(once)["nets"], once["nets"])


class TestEveryShippedExample(unittest.TestCase):

  def test_they_are_all_version_2_on_disk(self):
    # An example still written as version 1 would be upgraded silently on
    # every load, so its file and its meaning would drift apart.
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      with self.subTest(example=name):
        with open(os.path.join(ROOT, "examples", name)) as handle:
          self.assertEqual(json.load(handle)["version"], 2)

  def test_at_least_one_of_them_has_a_net_with_several_loads(self):
    found = 0
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
      if not name.endswith(".dlg"):
        continue
      doc = Document.load(os.path.join(ROOT, "examples", name))
      found += sum(1 for n in doc.nets if len(loads_of(n)) > 1)
    self.assertGreater(found, 0, "nothing here exercises a multi-load net")


class TestWhatTheModelBuys(unittest.TestCase):

  def setUp(self):
    self.registry = default_registry()

  def rail(self, loads=3):
    doc = new_document("rail", 900, 500)
    doc.cells.append({"id": "p", "type": "port_in", "x": 60, "y": 100,
                      "label": "clk"})
    for index in range(loads):
      doc.cells.append({"id": "f%d" % index, "type": "dff",
                        "x": 300, "y": 60 + index * 120})
    doc.nets.append({
      "id": "n1", "name": "clk", "width": 1,
      "from": {"cell": "p", "pin": "p"},
      "to": [{"cell": "f%d" % i, "pin": "ck"} for i in range(loads)],
      "style": {}})
    doc.normalize()
    return doc

  def test_a_rail_is_one_net_that_routes_to_one_path_per_load(self):
    doc = self.rail()
    [(net, branches)] = routing.route_all(doc, self.registry)
    self.assertEqual(len(branches), 3)
    self.assertEqual(net["name"], "clk")

  def test_the_whole_rail_carries_one_name(self):
    # It could not before: the name lived on one of the several nets, so two
    # thirds of the rail was anonymous.
    from drawlogic import render_svg
    svg = render_svg.render(self.rail(), registry=self.registry)
    self.assertEqual(svg.count(">clk<"), 2)  # the port's label and the net's

  def test_branches_of_one_net_are_drawn_as_one_thing(self):
    from drawlogic import render_svg
    svg = render_svg.render(self.rail(), registry=self.registry)
    self.assertEqual(svg.count('class="dl-net"'), 1)

  def test_a_fan_out_still_gets_its_junction_dots(self):
    doc = self.rail()
    dots = routing.junctions(routing.route_all(doc, self.registry))
    self.assertTrue(dots, "a rail splitting three ways should be dotted")

  def test_two_nets_driving_one_pin_is_now_an_error(self):
    # This could not be said before. Every fan-out looked like several nets
    # sharing a pin, so there was nothing to tell a rail apart from a short.
    doc = self.rail(loads=1)
    doc.cells.append({"id": "q", "type": "port_in", "x": 60, "y": 300})
    doc.nets.append({"id": "n2", "name": None, "width": 1,
                     "from": {"cell": "q", "pin": "p"},
                     "to": [{"cell": "f0", "pin": "ck"}], "style": {}})
    doc.normalize()
    errors = [i for i in doc.validate(self.registry) if i.level == "error"]
    self.assertTrue(any("driven by 2 nets" in i.message for i in errors),
                    [str(i) for i in errors])

  def test_a_net_that_drives_nothing_is_an_error(self):
    doc = self.rail(loads=1)
    doc.nets[0]["to"] = []
    errors = [i for i in doc.validate(self.registry) if i.level == "error"]
    self.assertTrue(any("drives nothing" in i.message for i in errors))

  def test_a_rail_round_trips_through_a_file(self):
    doc = self.rail()
    again = Document.loads(doc.dumps())
    self.assertEqual(len(loads_of(again.nets[0])), 3)
    self.assertEqual(again.dumps(), doc.dumps())


if __name__ == "__main__":
  unittest.main()
