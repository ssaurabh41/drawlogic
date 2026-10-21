"""Linked components: part of a drawing defined once and placed many times.

What matters: a selection becomes a drawing of its own with a port for every
wire crossing its edge, named by the wire and never by where it sits in a
list; the selection is replaced by one instance with those wires reattached
to its pins; every instance follows its definition; one made independent
stops following it alone; and a pin that disappears from a definition is
reported, never quietly swapped for another.

Usage:

    python3 -m unittest tests.test_components
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from drawlogic import components, server, sheets
from drawlogic.doc import Document, new_document
from drawlogic.symbols import default_registry


def chain():
  """din -> a -> b -> c -> dout, with din also feeding b, all in a container."""
  doc = new_document("chain", 900, 400)
  doc.data["containers"] = [{"id": "k", "title": "Lane", "x": 120, "y": 120,
                             "w": 300, "h": 160}]
  doc.cells.extend([
    {"id": "pi", "type": "port_in", "x": 40, "y": 195, "label": "din"},
    {"id": "a", "parentId": "k", "type": "inv", "x": 150, "y": 180},
    {"id": "b", "parentId": "k", "type": "and2", "x": 280, "y": 175},
    {"id": "c", "type": "inv", "x": 520, "y": 180},
    {"id": "po", "type": "port_out", "x": 700, "y": 195, "label": "dout"},
  ])
  doc.nets.extend([
    {"id": "n1", "name": "x", "from": {"cell": "pi", "pin": "p"},
     "to": [{"cell": "a", "pin": "a"}, {"cell": "b", "pin": "b"}]},
    {"id": "n2", "from": {"cell": "a", "pin": "y"}, "to": [{"cell": "b", "pin": "a"}]},
    {"id": "n3", "label": "q", "from": {"cell": "b", "pin": "y"},
     "to": [{"cell": "c", "pin": "a"}]},
    {"id": "n4", "from": {"cell": "c", "pin": "y"}, "to": [{"cell": "po", "pin": "p"}]},
  ])
  doc.normalize()
  return doc


def errors(doc, registry=None):
  return [str(i) for i in doc.validate(registry) if i.level == "error"]


class TestPlanning(unittest.TestCase):

  def test_one_port_per_crossing_wire_named_from_it(self):
    found = components.plan(chain(), default_registry(), {"a", "b"})
    self.assertEqual(found["problems"], [])
    self.assertEqual(found["ports"], [
      {"key": "n1", "name": "x", "dir": "in", "width": 1},
      {"key": "n3", "name": "q", "dir": "out", "width": 1}])

  def test_a_loose_end_is_explained_before_anything_changes(self):
    doc = chain()
    doc.nets[2]["to"].append({"x": 600, "y": 300})
    before = doc.dumps()
    found = components.plan(doc, default_registry(), {"a", "b"})
    self.assertEqual(len(found["problems"]), 1)
    self.assertIn("loose end", found["problems"][0])
    with self.assertRaises(components.ComponentError):
      components.extract(doc, default_registry(), {"a", "b"}, "Half")
    self.assertEqual(doc.dumps(), before)

  def test_nothing_to_make_a_component_of(self):
    self.assertTrue(components.plan(chain(), default_registry(), {"k_nope"})["problems"])


class TestExtracting(unittest.TestCase):

  def setUp(self):
    self.root = tempfile.mkdtemp()
    self.doc = chain()
    self.doc.path = os.path.join(self.root, "top.dlg")
    self.child, self.ref, self.instance = components.extract(
      self.doc, default_registry(), {"k"}, "Half cell", names={"n3": "result"})
    target = sheets.child_path(self.doc.path, self.ref)
    os.makedirs(os.path.dirname(target))
    self.child.save(target)
    self.doc.save()

  def tearDown(self):
    shutil.rmtree(self.root, ignore_errors=True)

  def test_the_definition_is_a_sound_drawing_of_the_selection(self):
    child = Document.load(os.path.join(self.root, "components", "half_cell.dlg"))
    self.assertEqual(self.ref, "components/half_cell.dlg")
    self.assertEqual(errors(child), [])
    kinds = sorted((c.get("type"), c.get("label") or "") for c in child.cells)
    self.assertEqual(kinds, [("and2", ""), ("inv", ""), ("port_in", "x"),
                             ("port_out", "result")])
    # The container came along, holding what it held.
    self.assertEqual([b["id"] for b in child.containers], ["k"])
    self.assertEqual(child.cell("a")["parentId"], "k")
    self.assertNotIn("parentId", child.containers[0])
    # The wire between the two stayed inside.
    self.assertIn({"cell": "a", "pin": "y"}, [n["from"] for n in child.nets])

  def test_the_parent_holds_one_instance_wired_by_name(self):
    doc, registry, problems = sheets.open_document(os.path.join(self.root, "top.dlg"))
    self.assertEqual(problems, [])
    self.assertEqual(errors(doc, registry), [])
    self.assertEqual(sorted(c["id"] for c in doc.cells), ["c", "pi", "po", "u_half_cell"])
    self.assertEqual(self.instance, "u_half_cell")
    net = {n["id"]: n for n in doc.nets}
    self.assertEqual(net["n1"]["to"], [{"cell": "u_half_cell", "pin": "x", "waypoints": []}])
    self.assertEqual(net["n3"]["from"], {"cell": "u_half_cell", "pin": "result"})
    self.assertEqual(net["n3"]["label"], "q")
    symbol = registry.for_cell(doc.cell("u_half_cell"))
    self.assertEqual(sorted(p["name"] for p in symbol.pins), ["result", "x"])
    self.assertEqual(doc.containers, [])

  def test_port_names_go_by_wire_not_by_order(self):
    one = chain()
    two = chain()
    first = components.extract(one, default_registry(), {"a", "b"}, "H",
                               names={"n1": "IN", "n3": "OUT"})[0]
    second = components.extract(two, default_registry(), {"a", "b"}, "H",
                                names=dict(reversed(list({"n1": "IN", "n3": "OUT"}.items()))))[0]
    self.assertEqual(first.dumps(), second.dumps())
    self.assertEqual(one.dumps(), two.dumps())

  def test_two_ports_cannot_share_a_name(self):
    with self.assertRaises(components.ComponentError):
      components.extract(chain(), default_registry(), {"a", "b"}, "H",
                         names={"n1": "same", "n3": "same"})

  def test_definition_edits_reach_every_instance_and_lost_pins_are_reported(self):
    path = os.path.join(self.root, "top.dlg")
    doc = Document.load(path)
    doc.cells.append({"id": "u2", "type": "sheet", "ref": self.ref, "x": 300, "y": 300,
                      "label": "H2"})
    doc.save()
    child_path = os.path.join(self.root, "components", "half_cell.dlg")
    child = Document.load(child_path)
    # Rename the output port and add a new input.
    next(c for c in child.cells if c.get("label") == "result")["label"] = "renamed"
    child.cells.append({"id": "p_en", "type": "port_in", "x": 80, "y": 300, "label": "en"})
    child.save()
    doc, registry, _problems = sheets.open_document(path)
    for cell_id in ("u_half_cell", "u2"):
      pins = sorted(p["name"] for p in registry.for_cell(doc.cell(cell_id)).pins)
      self.assertEqual(pins, ["en", "renamed", "x"])
    # The wire that used "result" still says "result": reported, not moved.
    self.assertEqual(doc.nets[[n["id"] for n in doc.nets].index("n3")]["from"],
                     {"cell": "u_half_cell", "pin": "result"})
    self.assertTrue(any("pin 'result'" in e for e in errors(doc, registry)), errors(doc, registry))


class TestPreviews(unittest.TestCase):
  """An instance can show a miniature of what its definition holds."""

  def setUp(self):
    from tests import ROOT
    from drawlogic import render_svg
    self.render = render_svg.render
    self.doc, self.registry, problems = sheets.open_document(
      os.path.join(ROOT, "examples", "gpu_arch.dlg"))
    self.assertEqual(problems, [])
    self.colour = "#8a9ba4"

  def marks(self, svg):
    import re
    return re.findall(r'<(rect|path)[^>]*stroke="%s"' % self.colour, svg)

  def test_drawn_for_an_instance_that_asks(self):
    shown = len(self.marks(self.render(self.doc, self.registry)))
    # Eight SMs, each its five blocks and its internal wires.
    self.assertGreaterEqual(shown, 8 * 5)
    for cell in self.doc.cells:
      cell.pop("preview", None)
    self.assertEqual(self.marks(self.render(self.doc, self.registry)), [])

  def test_a_definition_edit_shows_in_the_preview(self):
    root = tempfile.mkdtemp()
    try:
      shutil.copytree(os.path.join(os.path.dirname(self.doc.path)), os.path.join(root, "ex"))
      top = os.path.join(root, "ex", "gpu_arch.dlg")
      before = len(self.marks(self.render(*sheets.open_document(top)[:2])))
      child = Document.load(os.path.join(root, "ex", "components", "sm.dlg"))
      child.cells.append({"id": "extra", "type": "block", "x": 1100, "y": 400})
      child.save()
      after = len(self.marks(self.render(*sheets.open_document(top)[:2])))
      self.assertEqual(after - before, 8)
    finally:
      shutil.rmtree(root, ignore_errors=True)

  def test_the_editor_draws_the_same_preview(self):
    from tests.test_js_parity import NODE, _browser_render
    if not NODE:
      self.skipTest("node is not installed")
    import re
    svg = self.render(self.doc, self.registry)
    exported = sorted(
      [tag, d if tag == "path" else "%s,%s,%s,%s" % (x, y, w, h)]
      for tag, x, y, w, h, d in [
        (m.group(1), *(re.search(r'%s="([^"]*)"' % k, m.group(0)).group(1)
                        if re.search(r'%s="([^"]*)"' % k, m.group(0)) else None
                        for k in ("x", "y", "width", "height", "d")))
        for m in re.finditer(r'<(rect|path)[^>]*stroke="%s"[^>]*>' % self.colour, svg)])
    browser = _browser_render(self.doc, self.registry)["preview"]
    self.assertEqual(len(browser), len(exported))
    self.assertEqual(browser, exported)


class TestThroughTheEditorsServer(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.root = tempfile.mkdtemp()
    handler = type("BoundHandler", (server.Handler,), {
      "root": cls.root, "registry": default_registry(), "quiet": True,
    })
    cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    cls.base = "http://127.0.0.1:%d" % cls.httpd.server_port
    threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

  @classmethod
  def tearDownClass(cls):
    cls.httpd.shutdown()
    cls.httpd.server_close()
    shutil.rmtree(cls.root, ignore_errors=True)

  def post(self, route, payload):
    request = Request(self.base + route, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
      with urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as caught:
      return caught.code, json.loads(caught.read().decode("utf-8") or "{}")

  def setUp(self):
    shutil.rmtree(os.path.join(self.root, "lanes"), ignore_errors=True)
    os.makedirs(os.path.join(self.root, "lanes"))
    self.doc = chain().ordered()

  def test_plan_then_create_then_make_one_independent(self):
    status, plan = self.post("/api/component", {
      "action": "plan", "doc": self.doc, "source": "lanes/top.dlg", "ids": ["a", "b"],
      "name": "Half"})
    self.assertEqual(status, 200, plan)
    self.assertEqual((plan["path"], plan["exists"]), ("lanes/components/half.dlg", False))
    status, made = self.post("/api/component", {
      "action": "create", "doc": self.doc, "source": "lanes/top.dlg", "ids": ["a", "b"],
      "name": "Half", "names": {"n1": "x", "n3": "y"}})
    self.assertEqual(status, 200, made)
    self.assertTrue(os.path.isfile(os.path.join(self.root, "lanes", "components", "half.dlg")))
    self.assertIn("sheet:components/half.dlg", made["sheets"])
    # Made again without asking to replace it: refused, nothing written.
    status, _ = self.post("/api/component", {
      "action": "create", "doc": self.doc, "source": "lanes/top.dlg", "ids": ["a", "b"],
      "name": "Half"})
    self.assertEqual(status, 409)

    doc = made["doc"]
    doc["cells"].append(dict(next(c for c in doc["cells"] if c["id"] == made["instance"]),
                             id="u_two", label="HALF 1", x=300, y=320))
    status, copied = self.post("/api/component", {
      "action": "copy", "doc": doc, "source": "lanes/top.dlg", "cell": "u_two"})
    self.assertEqual(status, 200, copied)
    refs = {c["id"]: c.get("ref") for c in copied["doc"]["cells"]}
    self.assertEqual(refs["u_two"], "components/half_2.dlg")
    self.assertEqual(refs[made["instance"]], "components/half.dlg")
    self.assertTrue(os.path.isfile(os.path.join(self.root, "lanes", "components", "half_2.dlg")))

  def test_a_component_needs_a_saved_drawing(self):
    status, answer = self.post("/api/component", {
      "action": "plan", "doc": self.doc, "ids": ["a"], "name": "x"})
    self.assertEqual(status, 400)
    self.assertIn("save this drawing first", answer.get("error", ""))

  def test_resolve_reads_definitions_fresh(self):
    os.makedirs(os.path.join(self.root, "lanes", "components"), exist_ok=True)
    child = new_document("blk")
    child.cells.append({"id": "p", "type": "port_in", "x": 40, "y": 40, "label": "go"})
    child.save(os.path.join(self.root, "lanes", "components", "blk.dlg"))
    self.doc["cells"].append({"id": "u9", "type": "sheet", "ref": "components/blk.dlg",
                              "x": 500, "y": 300})
    status, answer = self.post("/api/resolve", {"doc": self.doc, "source": "lanes/top.dlg"})
    self.assertEqual(status, 200, answer)
    self.assertEqual([p["name"] for p in answer["sheets"]["sheet:components/blk.dlg"]["pins"]],
                     ["go"])


if __name__ == "__main__":
  unittest.main()
