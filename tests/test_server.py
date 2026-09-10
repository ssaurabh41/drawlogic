import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from drawlogic import server
from drawlogic.doc import Document
from drawlogic.symbols import default_registry
from tests import EXAMPLE


class TestSafeJoin(unittest.TestCase):

  def setUp(self):
    self.root = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.root, ignore_errors=True)

  def test_allows_paths_inside_the_root(self):
    self.assertIsNotNone(server._safe_join(self.root, "a.dlg"))
    self.assertIsNotNone(server._safe_join(self.root, "sub/a.dlg"))

  def test_rejects_traversal(self):
    for attempt in ("../secret", "sub/../../secret", "..", "../",
                    "%2e%2e/secret", "sub/%2e%2e/%2e%2e/secret"):
      self.assertIsNone(server._safe_join(self.root, attempt),
                        "%r should not resolve inside the root" % attempt)

  def test_absolute_paths_are_treated_as_root_relative(self):
    # A leading slash means "the served root", as it does in any URL. The
    # point is that it cannot reach the real /etc.
    resolved = server._safe_join(self.root, "/etc/passwd")
    self.assertEqual(resolved, os.path.join(self.root, "etc", "passwd"))

  def test_rejects_empty(self):
    self.assertIsNone(server._safe_join(self.root, None))
    self.assertIsNone(server._safe_join(self.root, ""))

  def test_a_prefix_match_is_not_inside_the_root(self):
    # /tmp/rootevil must not count as being under /tmp/root.
    sibling = self.root + "evil"
    self.assertIsNone(server._safe_join(self.root, "../%s/x.dlg"
                                        % os.path.basename(sibling)))


class TestEndpoints(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.root = tempfile.mkdtemp()
    shutil.copy(EXAMPLE, os.path.join(cls.root, "slice.dlg"))

    handler = type("BoundHandler", (server.Handler,), {
      "root": cls.root,
      "registry": default_registry(),
      "quiet": True,
    })
    cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    cls.base = "http://127.0.0.1:%d" % cls.httpd.server_port
    cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
    cls.thread.start()

  @classmethod
  def tearDownClass(cls):
    cls.httpd.shutdown()
    cls.httpd.server_close()
    shutil.rmtree(cls.root, ignore_errors=True)

  def setUp(self):
    # Restore the drawing before each test so one test writing to it cannot
    # change what another test sees.
    shutil.copy(EXAMPLE, os.path.join(self.root, "slice.dlg"))

  def get(self, path):
    with urlopen(self.base + path) as response:
      return json.loads(response.read().decode("utf-8"))

  def post(self, path, payload):
    request = Request(self.base + path,
                      data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"},
                      method="POST")
    with urlopen(request) as response:
      body = response.read().decode("utf-8")
      if "json" in (response.headers.get("Content-Type") or ""):
        return json.loads(body)
      return body

  def test_serves_the_editor_page(self):
    with urlopen(self.base + "/") as response:
      self.assertEqual(response.status, 200)
      self.assertIn("drawlogic", response.read().decode("utf-8"))

  def test_symbols_match_the_python_registry(self):
    payload = self.get("/api/symbols")
    self.assertEqual(sorted(payload), default_registry().ids())
    self.assertEqual(payload["and2"]["size"], [60, 40])

  def test_theme_is_served_so_the_browser_need_not_restate_it(self):
    payload = self.get("/api/theme")
    self.assertIn("colors", payload)
    self.assertIn("roleStyles", payload)
    self.assertIn("body", payload["roleStyles"])

  def test_lists_drawings(self):
    payload = self.get("/api/files")
    self.assertIn("slice.dlg", payload["files"])

  def test_opens_a_drawing(self):
    payload = self.get("/api/doc?path=slice.dlg")
    self.assertEqual(payload["doc"]["title"], "dff_slice")
    self.assertEqual(len(payload["doc"]["cells"]), 10)

  def test_save_round_trips_and_stays_canonical(self):
    payload = self.get("/api/doc?path=slice.dlg")
    document = payload["doc"]
    document["title"] = "renamed"
    # Deliberately out of order: the server should re-emit it canonically.
    document["cells"][0] = dict(reversed(list(document["cells"][0].items())))

    self.post("/api/doc?path=slice.dlg", {"doc": document})
    saved = Document.load(os.path.join(self.root, "slice.dlg"))
    self.assertEqual(saved.title, "renamed")
    self.assertEqual(list(saved.ordered()["cells"][0])[:2], ["id", "type"])

  def test_export_writes_svg_through_the_python_renderer(self):
    payload = self.get("/api/doc?path=slice.dlg")
    result = self.post("/api/export", {
      "doc": payload["doc"], "path": "out.svg", "options": {"zoom": 2},
    })
    target = os.path.join(self.root, result["path"])
    self.assertTrue(os.path.isfile(target))
    with open(target) as handle:
      self.assertIn("<svg ", handle.read())

  def test_export_without_a_path_returns_the_svg(self):
    payload = self.get("/api/doc?path=slice.dlg")
    body = self.post("/api/export", {"doc": payload["doc"]})
    self.assertIn("<svg ", body)

  def test_refuses_to_read_outside_the_root(self):
    with self.assertRaises(HTTPError) as caught:
      self.get("/api/doc?path=../../etc/passwd")
    self.assertEqual(caught.exception.code, 400)

  def test_refuses_to_write_outside_the_root(self):
    with self.assertRaises(HTTPError) as caught:
      self.post("/api/doc?path=../escaped.dlg", {"doc": {}})
    self.assertEqual(caught.exception.code, 400)

  def test_refuses_non_dlg_targets(self):
    with self.assertRaises(HTTPError) as caught:
      self.post("/api/doc?path=notes.txt", {"doc": {}})
    self.assertEqual(caught.exception.code, 400)

  def test_rejects_a_document_it_cannot_parse(self):
    with self.assertRaises(HTTPError) as caught:
      self.post("/api/doc?path=slice.dlg", {"doc": {"format": "nope"}})
    self.assertEqual(caught.exception.code, 422)

  def test_unknown_endpoint_is_a_404(self):
    with self.assertRaises(HTTPError) as caught:
      self.get("/api/nothing")
    self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
  unittest.main()
