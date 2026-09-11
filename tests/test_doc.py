import json
import unittest

from drawlogic import buses
from drawlogic.doc import Document, DocumentError, new_document
from tests import EXAMPLE


class TestRoundTrip(unittest.TestCase):

  def test_new_document_round_trips(self):
    doc = new_document("alu_ctrl")
    doc.cells.append({"id": "u1", "type": "and2", "x": 10, "y": 20})
    doc.normalize()

    reloaded = Document.loads(doc.dumps())
    self.assertEqual(reloaded.title, "alu_ctrl")
    self.assertEqual(len(reloaded.cells), 1)
    self.assertEqual(reloaded.cell("u1")["type"], "and2")

  def test_missing_size_is_filled_from_the_symbol(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.normalize()
    self.assertEqual(doc.cell("u1")["w"], 60)
    self.assertEqual(doc.cell("u1")["h"], 40)

  def test_key_order_is_stable_so_diffs_stay_readable(self):
    doc = new_document()
    doc.cells.append({"style": {}, "type": "inv", "y": 5, "x": 1, "id": "u9"})
    doc.normalize()
    emitted = json.loads(doc.dumps())
    self.assertEqual(list(emitted.keys())[:4], ["format", "version", "title", "canvas"])
    self.assertEqual(list(emitted["cells"][0].keys())[:4], ["id", "type", "x", "y"])

  def test_dumps_is_idempotent(self):
    doc = Document.load(EXAMPLE)
    once = doc.dumps()
    twice = Document.loads(once).dumps()
    self.assertEqual(once, twice)

  def test_rejects_foreign_files(self):
    with self.assertRaises(DocumentError):
      Document.loads('{"format": "something-else", "version": 1}')
    with self.assertRaises(DocumentError):
      Document.loads("not json at all")
    with self.assertRaises(DocumentError):
      Document.loads('{"format": "drawlogic", "version": 99}')


class TestValidate(unittest.TestCase):

  def _errors(self, doc):
    return [i for i in doc.validate() if i.level == "error"]

  def test_example_has_no_errors(self):
    self.assertEqual(self._errors(Document.load(EXAMPLE)), [])

  def test_unknown_cell_type_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "flux_capacitor", "x": 0, "y": 0,
                      "w": 10, "h": 10})
    self.assertTrue(any("unknown cell type" in i.message for i in self._errors(doc)))

  def test_net_to_a_pin_that_does_not_exist_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "zzz"}})
    doc.normalize()
    self.assertTrue(any("no such pin" in i.message for i in self._errors(doc)))

  def test_net_to_a_missing_cell_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.nets.append({"id": "n1", "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "ghost", "pin": "a"}})
    doc.normalize()
    self.assertTrue(any("missing cell" in i.message for i in self._errors(doc)))

  def test_duplicate_ids_are_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u1", "type": "inv", "x": 100, "y": 0})
    doc.normalize()
    self.assertTrue(any("duplicate id" in i.message for i in self._errors(doc)))

  def test_bus_name_must_match_declared_width(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]", "width": 4,
                     "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    self.assertTrue(any("implies width" in i.message for i in self._errors(doc)))

  def test_a_bus_on_a_single_bit_pin_is_an_error(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.cells.append({"id": "u2", "type": "inv", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]",
                     "from": {"cell": "u1", "pin": "y"},
                     "to": {"cell": "u2", "pin": "a"}})
    doc.normalize()
    self.assertTrue(any("8-bit net" in i.message for i in self._errors(doc)))

  def test_a_bus_on_a_width_zero_pin_is_allowed(self):
    # Width 0 declares a pin that takes a bus of any width, which is what a
    # generic block port and a bus ripper use.
    doc = new_document()
    doc.cells.append({"id": "pd", "type": "port_in", "x": 0, "y": 0})
    doc.cells.append({"id": "b1", "type": "block", "x": 200, "y": 0})
    doc.nets.append({"id": "n1", "name": "d[7:0]",
                     "from": {"cell": "pd", "pin": "p"},
                     "to": {"cell": "b1", "pin": "in1"}})
    doc.normalize()
    self.assertEqual(self._errors(doc), [])

  def test_unconnected_pin_is_only_a_warning(self):
    doc = new_document()
    doc.cells.append({"id": "u1", "type": "and2", "x": 0, "y": 0})
    doc.normalize()
    issues = doc.validate()
    self.assertEqual([i for i in issues if i.level == "error"], [])
    self.assertTrue(any("unconnected" in i.message for i in issues))

  def test_group_member_must_exist(self):
    doc = new_document()
    doc.groups.append({"id": "g1", "members": ["nope"]})
    self.assertTrue(any("does not exist" in i.message for i in self._errors(doc)))


class TestBusNames(unittest.TestCase):

  def test_width_from_name(self):
    self.assertEqual(buses.width_of("d[7:0]"), 8)
    self.assertEqual(buses.width_of("d[3]"), 1)
    self.assertEqual(buses.width_of("clk"), 1)
    self.assertEqual(buses.width_of("addr[31:16]"), 16)

  def test_is_bus(self):
    self.assertTrue(buses.is_bus("d[7:0]"))
    self.assertFalse(buses.is_bus("d[0]"))
    self.assertFalse(buses.is_bus("reset_n"))

  def test_expansion_is_msb_first(self):
    self.assertEqual(buses.bits("d[3:0]"), ["d[3]", "d[2]", "d[1]", "d[0]"])
    self.assertEqual(buses.bits("d[0:2]"), ["d[0]", "d[1]", "d[2]"])

  def test_illegal_names_are_rejected(self):
    self.assertIsNone(buses.parse("9lives"))
    self.assertIsNone(buses.parse("a b"))
    self.assertIsNone(buses.parse(""))


if __name__ == "__main__":
  unittest.main()
