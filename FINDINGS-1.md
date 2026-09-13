## Demonstrated

Reviewed commit `505b865` in a clean worktree on `codex/findings-1`. The original working directory's modified `examples/spi_master.dlg` was preserved and excluded from the baseline. Environment: Windows/PowerShell, Python **3.14.7**, Node **24.19.0**. Read README.md and DOCUMENTATION.md before calibration. Run the PowerShell repro blocks below from the repository root; they require no Python packages. Node is required for the JavaScript repros, as it is for the existing JavaScript tests.

Baseline: `python3 -m unittest discover` passed **195 tests in 4.134s** (process command, including the version query, took 5.144s). This is unittest's test count, not a count of individual assertions; its one editor-wrapper test normally runs 37 JavaScript assertions. No tests were skipped in this baseline.

Final verification after restoring all mutations: **195 tests passed in 3.994s**, no skips. All eight scripted repro blocks below were executed directly from this report and their expected failure evidence checked; the ninth repro is the browser interaction described in finding 8. The review server was stopped afterward.

Before defect hunting, I applied these mutations individually, ran the full suite after each, and restored the original bytes in `finally`:

| Module | Exact mutation | Full-suite result | Suite time / process wall time |
| --- | --- | --- | --- |
| `drawlogic/geometry.py` | Replace `return Affine(1, 0, 0, 1, tx, ty)` with `return Affine(1, 0, 0, 1, tx + 10, ty)` | RED: 195 tests, 75 failures | 4.153s / 4.370s |
| `drawlogic/server.py` | Immediately before `relative = unquote(relative).lstrip("/")`, return `os.path.abspath(os.path.join(root, relative))`, bypassing confinement | RED: 195 tests, 4 failures, 1 error | 4.001s / 4.214s |
| `drawlogic/web/js/render.js` | Replace `return extra.concat(spots);` with `return extra.concat(spots).map(([p, d]) => [p, [-d[0], -d[1]]]);` | GREEN: 195 tests, no skips; browser arrows now face backwards | 3.983s / 4.192s |

The third result is finding 5. No calibration mutation is part of this branch. Subsequent runtime work included CLI help/info/validate/export/layout, exporting all seven examples and parsing their SVG XML, starting the actual CLI server on loopback, opening the editor and using its grouping/duplication controls, real HTTP requests against the production Handler, and delayed-response execution of the actual editor command handlers. Each supplied example validates successfully; a second layout leaves each unchanged. PowerShell does not expand the documented `examples/*.dlg` argument for native executables, so batch export was exercised with an explicitly expanded file list; validate accepts one file per invocation.

**1. Title: Delayed save and layout responses can lose edits or replace a different drawing**

- **Location:** `drawlogic/web/js/main.js:389`, `drawlogic/web/js/main.js:470`; `drawlogic/web/js/model.js:107`.
- **Repro:** This executes the real Store and real `save`/`autoLayout` functions. It replaces the HTTP boundary with a controllable promise and stubs UI painting; it does not simulate an entire browser or write files. The first case edits during a pending save. The second switches from A to B during A's pending layout.

```powershell
@'
import fs from 'node:fs';
import vm from 'node:vm';
import * as model from './drawlogic/web/js/model.js';
const source = fs.readFileSync('drawlogic/web/js/main.js','utf8')
  .replace(/^import .*;\r?\n/gm,'').replace(/start\(\);\s*$/,'');
const ctx = vm.createContext({model, Selection: class {clear(){}}, console});
vm.runInContext(source + `
  globalThis.test={store,save,autoLayout};
  say=()=>{}; refreshStatus=()=>{}; syncControls=()=>{}; redraw=()=>{};
  inspector={render(){}}; viewport={fit(){}};
  globalThis.pending=null; api=()=>new Promise(r=>{pending=r});
`, ctx);
const doc = title => ({title, canvas:{width:100,height:100},
  cells:[{id:'c1',type:'and2',x:0,y:0}], nets:[], shapes:[], groups:[]});
ctx.test.store.load(doc('A'),'a.dlg');
let operation = ctx.test.save();
ctx.test.store.mutate('edit',d=>{d.title='UNSAVED EDIT'});
ctx.pending({}); await operation;
console.log('SAVE', JSON.stringify({title:ctx.test.store.doc.title,
  dirty:ctx.test.store.dirty}));
ctx.test.store.load(doc('A'),'a.dlg');
operation = ctx.test.autoLayout();
ctx.test.store.load(doc('B'),'b.dlg');
ctx.pending({doc:doc('A layout response'),shapes:0,note:'done'});
await operation;
console.log('LAYOUT', JSON.stringify({path:ctx.test.store.path,
  title:ctx.test.store.doc.title}));
'@ | node --input-type=module
```

- **Expected vs actual:** Save should leave the later edit dirty; actual: `SAVE {"title":"UNSAVED EDIT","dirty":false}`. Layout should apply only to the document/revision submitted; actual: `LAYOUT {"path":"b.dlg","title":"A layout response"}`. B now contains A's response and the next save targets B. The dirty flag also controls the close-tab warning, so the first case suppresses that protection. Layout can likewise discard edits made to A while its request is pending.
- **Severity:** major — normal asynchronous interaction can silently lose work or overwrite the wrong file on the next save.
- **Fix sketch:** Capture document identity, path, and revision at dispatch and validate them on completion. Mark only the submitted revision saved, and discard or explicitly reconcile stale layout responses.

**2. Title: Hierarchical references escape the HTTP server's advertised served-folder boundary**

- **Location:** `drawlogic/server.py:196`, `drawlogic/sheets.py:160`, `drawlogic/sheets.py:224`, `drawlogic/sheets.py:245`.
- **Repro:** Uses real files, a real loopback HTTP server, and the production request handler. The outside file is a disposable marker drawing created by this repro; no private files are used.

```powershell
@'
import json, tempfile, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from drawlogic import server
from drawlogic.doc import new_document
from drawlogic.symbols import default_registry
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp); served = base/'served'; served.mkdir()
    new_document('OUTSIDE_SECRET_TITLE').save(str(base/'outside.dlg'))
    parent = new_document('parent')
    parent.cells.append({'id':'b','type':'sheet','ref':'../outside.dlg',
                         'x':0,'y':0})
    parent.save(str(served/'parent.dlg'))
    H = type('Probe',(server.Handler,),{'root':str(served),
        'registry':default_registry(),'quiet':True})
    httpd = ThreadingHTTPServer(('127.0.0.1',0),H)
    t = threading.Thread(target=httpd.serve_forever,daemon=True); t.start()
    url = 'http://127.0.0.1:%d' % httpd.server_port
    try:
        try:
            urlopen(url+'/api/doc?path=../outside.dlg')
        except HTTPError as e:
            print('direct:',e.code); e.close()
        with urlopen(url+'/api/doc?path=parent.dlg') as r:
            body = r.read().decode()
            print('reference:',r.status,'leaked title:',
                  'OUTSIDE_SECRET_TITLE' in body)
    finally:
        httpd.shutdown(); httpd.server_close(); t.join()
'@ | python3 -
```

- **Expected vs actual:** README and the manual promise that nothing outside the served directory is reachable. Direct traversal returns 400, but opening the parent returns 200 and includes `OUTSIDE_SECRET_TITLE` in its derived sheet symbol. Only the parent path is confined; `ref` is resolved without that boundary. This demonstrates disclosure of another drawing's title; it does not establish arbitrary raw-file disclosure or remote code execution.
- **Severity:** major — the claimed HTTP file-access boundary can be bypassed through an ordinary supported document field.
- **Fix sketch:** Propagate an optional allowed root through server-side hierarchy resolution and enforce it for every referenced file, including descendants. Resolve filesystem links before checking containment; the unrestricted CLI can retain its existing relative-reference behavior.

**3. Title: Cropped SVG export drops version-2 load endpoints and branch waypoints from its bounds**

- **Location:** `drawlogic/doc.py:449`, `drawlogic/render_svg.py:668`.
- **Repro:**

```powershell
@'
import subprocess, sys, tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from drawlogic.doc import new_document
from drawlogic import routing
with tempfile.TemporaryDirectory() as tmp:
    d = new_document('crop')
    d.nets.append({'id':'n1','from':{'x':10,'y':10},
        'to':[{'x':500,'y':10,'waypoints':[[10,300],[500,300]]}]})
    d.normalize()
    source = str(Path(tmp)/'crop.dlg'); out = str(Path(tmp)/'crop.svg')
    d.save(source)
    subprocess.run([sys.executable,'-m','drawlogic','export',source,
                    '--crop','-o',out],check=True)
    print('viewBox:',ET.parse(out).getroot().get('viewBox'))
    print('bbox:',d.content_bbox())
    print('route:',routing.route_all(d)[0][1])
'@ | python3 -
```

- **Expected vs actual:** The cropped image must contain the whole wire through x=500 and y=300. Actual `viewBox` is `-14 -14 48 48`; the route still contains `(10,300)`, `(500,300)`, and `(500,10)`, outside that viewport. The bounding box is `(10,10,0,0)`: it reads the obsolete net-level waypoints and treats `to` as a single endpoint, although normalization now makes it a list. Most of the exported wire is clipped, and `info` reports the same incorrect bounds.
- **Severity:** major — export succeeds while removing meaningful circuit geometry from the visible output.
- **Fix sketch:** Compute bounds from all resolved branch paths and drawn objects, using the current multi-load representation. Include rendered labels and stroke extents where necessary for a crop that actually contains the drawing.

**4. Title: CLI export overrides stored arrow and hop settings, disagreeing with editor export**

- **Location:** `drawlogic/cli.py:105`, `drawlogic/render_svg.py:726`, `drawlogic/server.py:360`.
- **Repro:** The same document is saved once and sent to the actual HTTP export endpoint as well as the CLI.

```powershell
@'
import json, subprocess, sys, tempfile, threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET
from drawlogic import server
from drawlogic.doc import Document
from drawlogic.symbols import default_registry
with tempfile.TemporaryDirectory() as tmp:
    d = Document.load('examples/dff_slice.dlg')
    d.canvas['arrows'] = False; d.canvas['hops'] = False
    source = str(Path(tmp)/'flags.dlg'); out = Path(tmp)/'flags.svg'
    d.save(source)
    subprocess.run([sys.executable,'-m','drawlogic','export',source,
                    '-o',str(out)],check=True)
    H = type('Probe',(server.Handler,),{'root':tmp,
        'registry':default_registry(),'quiet':True})
    httpd = ThreadingHTTPServer(('127.0.0.1',0),H)
    t = threading.Thread(target=httpd.serve_forever,daemon=True); t.start()
    try:
        req = Request('http://127.0.0.1:%d/api/export'%httpd.server_port,
            data=json.dumps({'doc':d.ordered(),'source':'flags.dlg'}).encode(),
            headers={'Content-Type':'application/json'})
        with urlopen(req) as r: http_svg = r.read().decode()
        def arrows(svg):
            return len(ET.fromstring(svg).findall(
                ".//s:g[@class='dl-nets']/s:polygon",
                {'s':'http://www.w3.org/2000/svg'}))
        print('CLI arrows:',arrows(out.read_text()))
        print('HTTP arrows:',arrows(http_svg))
        print('same:',out.read_text()==http_svg)
    finally:
        httpd.shutdown(); httpd.server_close(); t.join()
'@ | python3 -
```

- **Expected vs actual:** The manual documents `canvas.arrows=false` and `canvas.hops=false`, and claims byte-for-byte agreement between editor and CLI export. Actual: CLI output contains **9 arrows**, HTTP output contains **0**, and the files differ. The CLI always passes `True` for both options unless its negative flags are explicitly supplied, preventing the renderer from honoring the document. The executed comparison counts arrows; hop override is the adjacent identical argument-handling defect.
- **Severity:** major — exporting a saved schematic through the CLI silently changes its chosen visual notation.
- **Fix sketch:** Pass `None` when a CLI override is absent and `False` when its negative flag is present. Add a comparison of HTTP and CLI exports for documents with both canvas flags disabled.

**5. Title: Arrow parity tests stay green when every browser arrow is reversed**

- **Location:** `tests/test_js_parity.py:146`, `tests/test_js_parity.py:150`; mutation target `drawlogic/web/js/render.js:304`.
- **Repro:** The third calibration mutation; this command restores the file even when the suite fails. Run only in a disposable/clean checkout with no server serving the mutated file.

```powershell
@'
from pathlib import Path
import subprocess,sys
p = Path('drawlogic/web/js/render.js')
original = p.read_bytes()
old = b'return extra.concat(spots);'
new = b'return extra.concat(spots).map(([p, d]) => [p, [-d[0], -d[1]]]);'
assert original.count(old)==1
try:
    p.write_bytes(original.replace(old,new))
    subprocess.run(['node','--input-type=module','-e',
        "import {arrowSpots} from './drawlogic/web/js/render.js'; "
        "console.log(arrowSpots([[0,0],[100,0]],7,240));"],check=True)
    r = subprocess.run([sys.executable,'-m','unittest','discover'])
    print('suite exit:',r.returncode)
finally:
    p.write_bytes(original)
'@ | python3 -
```

- **Expected vs actual:** A left-to-right route should produce direction `[1,0]`; the mutation gives `[-1,0]` without moving its arrow tip. The suite should fail its direction-arrow parity check. Actual calibration: **195 tests passed in 3.983s**, exit 0. Both sides of the parity assertion explicitly throw away the direction vectors with `for tip, _`, so direction correctness is unowned even though the returned data includes it.
- **Severity:** major — a plausible renderer regression that communicates the opposite signal direction is invisible to the claimed parity protection.
- **Fix sketch:** Compare rounded direction vectors as well as tip coordinates, and assert a known source-to-load orientation independently of Python/JavaScript agreement.

**6. Title: The full suite reports the same success after all 37 JavaScript editor assertions are removed**

- **Location:** `tests/test_js_editor.py:34`, `tests/test_js_editor.py:36`.
- **Repro:** This is a separate follow-up coverage probe, after the three-module calibration. It replaces only the test runner and restores it afterward.

```powershell
@'
from pathlib import Path
import subprocess,sys
p = Path('tests/js/editor_check.mjs'); original = p.read_bytes()
try:
    p.write_text('console.log("ok   placeholder; no editor assertions ran");\n',
                 encoding='utf-8')
    r = subprocess.run([sys.executable,'-m','unittest','discover'])
    print('suite exit:',r.returncode)
finally:
    p.write_bytes(original)
r = subprocess.run(['node',str(p),'drawlogic/symbols.json'],
                    capture_output=True,text=True,check=True)
print('restored runner assertions:',
      sum(line.startswith('ok   ') for line in r.stdout.splitlines()))
'@ | python3 -
```

- **Expected vs actual:** Losing every editor assertion should fail or visibly reduce reported coverage. Actual: **195 tests passed in 3.978s**, exit 0, no skips; the restored runner reports **37** successful checks. The wrapper accepts any zero-exit process with one `ok   ` substring; it has no completion marker or inventory. An early successful exit after just one real check has the same weakness. This is a loss of execution detection in the subprocess wrapper, not a claim that unittest's individual assertions are broken.
- **Severity:** major — the normal success signal can conceal the disappearance of an entire area of verification.
- **Fix sketch:** Have the runner emit structured results and an end-of-run completion record with the expected check IDs, and validate that record in Python. Do not treat a single success-looking log line as proof the runner completed.

**7. Title: Validation rejects supported groups of shapes as nonexistent members**

- **Location:** `drawlogic/doc.py:619`, `drawlogic/doc.py:624`.
- **Repro:**

```powershell
@'
import subprocess,sys,tempfile
from pathlib import Path
from drawlogic.doc import new_document
with tempfile.TemporaryDirectory() as tmp:
    d = new_document('shape group')
    d.shapes.extend([
        {'id':'s1','kind':'rect','x':0,'y':0,'w':40,'h':40},
        {'id':'s2','kind':'rect','x':60,'y':0,'w':40,'h':40}])
    d.groups.append({'id':'g1','members':['s1','s2']})
    path = str(Path(tmp)/'group.dlg'); d.save(path)
    r = subprocess.run([sys.executable,'-m','drawlogic','validate',path])
    print('exit:',r.returncode)
'@ | python3 -
```

- **Expected vs actual:** The manual explicitly allows shapes to be grouped like cells, and the editor's `groupItems` supports them. Both members exist. Actual: two errors, `member 's1' does not exist` and `member 's2' does not exist`, exit 1. Group validation checks only the set of cell IDs. A file produced through a supported editor operation therefore fails command-line validation.
- **Severity:** minor — it produces false errors and blocks validation workflows for otherwise valid grouped annotations.
- **Fix sketch:** Validate group membership against the supported selectable object types, including shapes, while retaining missing-member and overlapping-group checks.

**8. Title: Duplicating a group drops the group relationship**

- **Location:** `drawlogic/web/js/model.js:510`, `drawlogic/web/js/model.js:520`, `drawlogic/web/js/model.js:523`.
- **Repro:** These steps were executed in the actual browser editor, without saving the changed example.

```powershell
python3 -m drawlogic serve examples/dff_slice.dlg --no-browser --port 8091
```

Open `http://127.0.0.1:8091/?open=dff_slice.dlg`. Click the canvas, press Ctrl+A, click **Group**, then press Ctrl+D. The status shows `20 cells | 14 nets | 10 selected`. Press Escape to clear selection, then click the duplicated AND gate labeled **U3**. Observe `20 cells | 14 nets | 1 selected`. The original group can still be selected as a group; the duplicate cannot. Stop the server with Ctrl+C and discard these test edits.

- **Expected vs actual:** Duplicating a grouped object should preserve its internal grouping under fresh IDs. Actual: the duplicate's components are independent. Clipboard data contains only cells, shapes, and nets; neither copying nor pasting transfers groups. Consequently the duplicate ceases to move/resize as one object after deselection.
- **Severity:** minor — an ordinary duplication operation silently removes editing structure and requires manual regrouping.
- **Fix sketch:** Copy complete selected groups and remap their member IDs and group IDs during paste. Define how partial groups behave and test copying, cutting, and Ctrl-drag duplication through the same path.

**9. Title: Malformed JSON structure crashes request handling instead of returning a validation response**

- **Location:** `drawlogic/server.py:231`, `drawlogic/server.py:257`, `drawlogic/doc.py:391`.
- **Repro:** Actual requests, rather than direct calls to private handlers:

```powershell
@'
import json,tempfile,threading
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from drawlogic import server
from drawlogic.symbols import default_registry
with tempfile.TemporaryDirectory() as tmp:
    H = type('Probe',(server.Handler,),{'root':tmp,
        'registry':default_registry(),'quiet':True})
    httpd = ThreadingHTTPServer(('127.0.0.1',0),H)
    t = threading.Thread(target=httpd.serve_forever,daemon=True); t.start()
    url = 'http://127.0.0.1:%d/api/doc?path=bad.dlg'%httpd.server_port
    try:
        for payload in ([], {'doc':{'format':'drawlogic','version':2,
                                   'canvas':None}}):
            req = Request(url,data=json.dumps(payload).encode(),
                          headers={'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=5) as r: print('HTTP',r.status)
            except HTTPError as e:
                print('HTTP',e.code,e.read().decode()); e.close()
            except Exception as e:
                print(type(e).__name__,str(e))
    finally:
        httpd.shutdown(); httpd.server_close(); t.join()
'@ | python3 -
```

- **Expected vs actual:** Invalid request shape should produce a 400/422 JSON error. Both bodies instead cause `RemoteDisconnected: Remote end closed connection without response`; the server logs `AttributeError` for `.get` on a list or `.setdefault` on None. A `.dlg` containing `{"format":"drawlogic","version":2,"canvas":null}` likewise makes CLI `validate` print a Python traceback. The server process remains alive: this is a per-request crash, not a demonstrated service-wide outage.
- **Severity:** minor — malformed input defeats the advertised validation/error-response path and makes clients see an unexplained transport failure.
- **Fix sketch:** Check request-object and nested document types before normalization. Raise `DocumentError` for schema violations and translate them consistently into CLI diagnostics and HTTP 422 responses.

## Suspected

**1. Title: Concurrent custom-symbol saves can overwrite one another or expose a truncated library**

- **Location:** `drawlogic/authoring.py:257`, `drawlogic/authoring.py:263`, `drawlogic/authoring.py:267`; `drawlogic/server.py:328`.
- **Expected vs actual:** Saving different symbols concurrently should retain both definitions and readers should see a complete JSON file. Inspection shows an unlocked read-modify-write sequence against one `symbols.json`, called by `ThreadingHTTPServer`, with direct truncating writes. Two requests appear able to read the same old library and commit incompatible replacements; an I/O failure can also interrupt the write. These outcomes were not reproduced.
- **Severity:** major — if confirmed, it loses reusable symbols and can prevent the folder's library from loading.
- **Fix sketch:** Serialize library updates and write a complete replacement to a sibling temporary file before atomic replacement. Include a concurrency test for distinct symbol IDs and a failed-write preservation test.
- **What stopped confirmation:** I did not run an overlapping two-client symbol-save test or inject a mid-write filesystem failure; normal symbol authorship and failure recovery remain coverage gaps.

**2. Title: Dragging scales with a full-document JSON copy on every pointer movement**

- **Location:** `drawlogic/web/js/model.js:48`, `drawlogic/web/js/model.js:66`, `drawlogic/web/js/model.js:70`.
- **Expected vs actual:** A gesture should make one undo snapshot and keep pointer updates responsive on larger drawings. Inspection shows that every mutation serializes and reparses the entire document before checking whether the gesture already has its undo snapshot. Most of those copies are discarded; embedded image strings are included. I have not measured the point at which this becomes a user-visible problem.
- **Severity:** minor — repeated allocation is a credible editing-performance risk as drawings and embedded assets grow, but a stall threshold is unconfirmed.
- **Fix sketch:** Avoid creating unused full-document snapshots within an already-open gesture, and measure pointer latency and retained undo memory on drawings with many cells and images. Keep undo correctness tests independent of the storage strategy.
- **What stopped confirmation:** No large-drawing/browser-memory benchmark was completed; the executed interactive checks used the supplied small example.

Remaining coverage gaps: the Python 3.8 minimum and older Node versions; sustained large-drawing performance; interrupted and concurrent disk writes; filesystem symlinks/junctions; end-to-end hostile-origin browser requests; PNG clipboard behavior and print/PDF; and full custom-symbol editing across nested folders. The delayed save/layout repro is an isolated execution of production handlers, not a throttled end-to-end browser test. The earlier cross-type z-order concern is excluded because DOCUMENTATION.md explicitly states that cells always draw above shapes.

One good result: the suite caught the coordinate and direct path-confinement mutations immediately.
