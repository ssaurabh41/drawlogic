## Demonstrated

Reviewed upstream commit `15bb0f4` (latest fetched for this pass) on `codex/findings-1`. Read `DOCUMENTATION.md` first; `README.md` is absent in this revision. The original checkout's uncommitted `examples/spi_master.dlg` was preserved and excluded from testing. This report supersedes the earlier report: every demonstrated finding below was reproduced against `15bb0f4`, rather than assumed to survive from an older revision.

Environment: Windows/PowerShell, Python **3.14.7**, Node **24.19.0**. Run the PowerShell blocks from the repository root. Python repros use only the standard library; JavaScript probes need Node, just like the existing JavaScript suite. Only this report is changed relative to the reviewed upstream code.

Baseline, before mutations or defect hunting: `python3 -m unittest discover` passed **200 tests in 5.845s**, no skips. The command containing Python/Node version queries and the suite took 6.995s wall time. The count is unittest test methods, not individual assertions; one wrapper normally runs 37 JavaScript editor checks.

Final verification: all ten scripted repro blocks were executed directly from this report and checked against their stated outputs; finding 10 was verified in the live editor. After restoring mutations, `python3 -m unittest discover` passed **200 tests in 4.636s**, with no skips. The temporary server was stopped, and only this report differs from upstream.

Calibration was performed in this order, one module at a time, restoring original bytes in `finally` after each full-suite run:

| Module | Exact deliberate break | Result | Suite time / process wall time |
| --- | --- | --- | --- |
| `drawlogic/rules.py` | `WIRE_GAP = 18.0` -> `WIRE_GAP = 36.0` | RED: 200 tests, 4 failures | 5.029s / 5.269s |
| `drawlogic/layout.py` | Replace `load["waypoints"] = []` with `pass`, retaining pre-layout branch waypoints | RED: 200 tests, 2 failures | 4.907s / 5.156s |
| `drawlogic/web/js/geometry.js` | `if (mirror) sx = -sx;` -> `if (mirror) sx = sx;` | RED: 200 tests, 4 failures | 5.075s / 5.358s |

All three expected regressions were caught. Later coverage probes found two different blind spots, documented below; they were not substituted for the original three mutations. All mutations were reverted.

Runtime work: CLI help and hierarchical info; validation of all seven examples; CLI export of all seven to SVG and XML parsing; layout twice on each example (all seven settled); starting the CLI server and opening the current editor; visual inspection of the displayed schematic and actual group/duplicate/select interaction; real HTTP read/write/export requests using disposable files. The New-command file-loss probe executes its production handler with scripted dialog answers against a real HTTP server. The embedded browser rejects JavaScript `prompt()`, and Chrome automation was unavailable, so this is explicitly not an end-to-end native-dialog test. No private files were used by the security probes.

**1. Title: New can erase an existing drawing without its overwrite confirmation**

- **Location:** `drawlogic/web/js/main.js:594`, `drawlogic/web/js/main.js:598`, `drawlogic/web/js/main.js:606`; `drawlogic/server.py:274`.
- **Repro:** The actual New handler is loaded into a Node VM with scripted dialog answers, a small DOM stub for the file list, and real HTTP requests. Python creates a disposable drawing and starts the production HTTP handler; no existing user drawing is touched.

```powershell
@'
import pathlib,tempfile,threading,subprocess
from http.server import ThreadingHTTPServer
from drawlogic import server
from drawlogic.doc import new_document,Document
from drawlogic.symbols import default_registry
with tempfile.TemporaryDirectory() as tmp:
    path=pathlib.Path(tmp)/'existing.dlg'
    d=new_document('KEEP_ME')
    d.cells.append({'id':'a','type':'inv','x':0,'y':0})
    d.normalize(); d.save(str(path))
    H=type('Probe',(server.Handler,),{'root':tmp,
        'registry':default_registry(),'quiet':True})
    httpd=ThreadingHTTPServer(('127.0.0.1',0),H)
    t=threading.Thread(target=httpd.serve_forever,daemon=True); t.start()
    js=r"""
import fs from 'node:fs';
import vm from 'node:vm';
import * as model from './drawlogic/web/js/model.js';
const source=fs.readFileSync('drawlogic/web/js/main.js','utf8')
 .replace(/^import .*;\r?\n/gm,'').replace(/start\(\);\s*$/,'');
const base=process.argv[1];
let confirmations=0, answer='existing.dlg';
const ctx=vm.createContext({model,Selection:class{},console,
 window:{prompt:()=>answer,confirm:()=>{confirmations++;return false;}},
 document:{createElement:()=>({})},
 fetch:(url,options)=>fetch(base+url,options)});
vm.runInContext(source+`;globalThis.test={newDrawing};
 ui.fileSelect={options:[{value:'existing.dlg'}],appendChild(){}};
 openDrawing=async()=>{};say=console.log;`,ctx);
await ctx.test.newDrawing();
console.log('exact-name confirmation count:',confirmations);
confirmations=0;answer='./existing.dlg';
await ctx.test.newDrawing();
console.log('alias confirmation count:',confirmations);
"""
    try:
        print('before:',Document.load(str(path)).title,
              len(Document.load(str(path)).cells),flush=True)
        subprocess.run(['node','--input-type=module','-e',js,
            'http://127.0.0.1:%d'%httpd.server_port],check=True)
        print('after:',Document.load(str(path)).title,
              len(Document.load(str(path)).cells),flush=True)
    finally:
        httpd.shutdown();httpd.server_close();t.join()
'@ | python3 -
```

- **Expected vs actual:** Both names designate the same file and must offer the same overwrite protection. Actual: `existing.dlg` asks once and respects refusal; `./existing.dlg` asks zero times and replaces the file. Output changes from `before: KEEP_ME 1` to `after: ./existing 0`. The client compares raw spelling against a cached dropdown, while the server normalizes the path and opens the destination with `w`. The write occurs during New, before any Save click, also contradicting the manual's statement that nothing is written until saving.
- **Severity:** major -- a supported file-creation command silently destroys an existing schematic using an ordinary equivalent relative path.
- **Fix sketch:** Enforce create-versus-replace semantics atomically on the server, returning a conflict if the canonical destination already exists. An explicitly confirmed overwrite should be a separate operation; a client-side filename list is not sufficient protection.

**2. Title: Delayed save and layout responses can lose edits or replace a different drawing**

- **Location:** `drawlogic/web/js/main.js:443`, `drawlogic/web/js/main.js:524`; `drawlogic/web/js/model.js:107`.
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
- **Severity:** major -- normal asynchronous interaction can silently lose work or overwrite the wrong file on the next save.
- **Fix sketch:** Capture document identity, path, and revision at dispatch and validate them on completion. Mark only the submitted revision saved, and discard or explicitly reconcile stale layout responses.

**3. Title: Hierarchical references escape the HTTP server's advertised served-folder boundary**

- **Location:** `drawlogic/server.py:204`, `drawlogic/sheets.py:160`, `drawlogic/sheets.py:224`, `drawlogic/sheets.py:245`.
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
- **Severity:** major -- the claimed HTTP file-access boundary can be bypassed through an ordinary supported document field.
- **Fix sketch:** Propagate an optional allowed root through server-side hierarchy resolution and enforce it for every referenced file, including descendants. Resolve filesystem links before checking containment; the unrestricted CLI can retain its existing relative-reference behavior.

**4. Title: Cropped SVG export drops version-2 load endpoints and branch waypoints from its bounds**

- **Location:** `drawlogic/doc.py:453`, `drawlogic/render_svg.py:690`.
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
- **Severity:** major -- export succeeds while removing meaningful circuit geometry from the visible output.
- **Fix sketch:** Compute bounds from all resolved branch paths and drawn objects, using the current multi-load representation. Include rendered labels and stroke extents where necessary for a crop that actually contains the drawing.

**5. Title: CLI export overrides stored arrow and hop settings, disagreeing with editor export**

- **Location:** `drawlogic/cli.py:105`, `drawlogic/render_svg.py:748`, `drawlogic/server.py:368`.
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
- **Severity:** major -- exporting a saved schematic through the CLI silently changes its chosen visual notation.
- **Fix sketch:** Pass `None` when a CLI override is absent and `False` when its negative flag is present. Add a comparison of HTTP and CLI exports for documents with both canvas flags disabled.

**6. Title: Arrow parity tests stay green when every browser arrow is reversed**

- **Location:** `tests/test_js_parity.py:169`, `tests/test_js_parity.py:173`; mutation target `drawlogic/web/js/render.js:311`.
- **Repro:** A follow-up coverage probe after the initial three calibration mutations; this command restores the file even when the suite fails. Run only in a disposable/clean checkout with no server serving the mutated file.

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

- **Expected vs actual:** A left-to-right route should produce direction `[1,0]`; the mutation gives `[-1,0]` without moving its arrow tip. The suite should fail its direction-arrow parity check. Actual: **200 tests passed in 4.602s**, exit 0. Both sides of the parity assertion explicitly throw away the direction vectors with `for tip, _`, so direction correctness is unowned even though the returned data includes it.
- **Severity:** major -- a plausible renderer regression that communicates the opposite signal direction is invisible to the claimed parity protection.
- **Fix sketch:** Compare rounded direction vectors as well as tip coordinates, and assert a known source-to-load orientation independently of Python/JavaScript agreement.

**7. Title: The full suite reports the same success after all 37 JavaScript editor assertions are removed**

- **Location:** `tests/test_js_editor.py:34`, `tests/test_js_editor.py:36`.
- **Repro:** This is a follow-up coverage probe, after the three-module calibration. It replaces only the test runner and restores it afterward.

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

- **Expected vs actual:** Losing every editor assertion should fail or visibly reduce reported coverage. Actual: **200 tests passed in 4.572s**, exit 0, no skips; the restored runner reports **37** successful checks. The wrapper accepts any zero-exit process with one `ok   ` substring; it has no completion marker or inventory. An early successful exit after just one real check has the same weakness. This is a loss of execution detection in the subprocess wrapper, not a claim that unittest's individual assertions are broken.
- **Severity:** major -- the normal success signal can conceal the disappearance of an entire area of verification.
- **Fix sketch:** Have the runner emit structured results and an end-of-run completion record with the expected check IDs, and validate that record in Python. Do not treat a single success-looking log line as proof the runner completed.

**8. Title: The documented CELL_MIN_GAP rule is unused and cannot control layout spacing**

- **Location:** `drawlogic/rules.py:70`, `drawlogic/layout.py:398`, `drawlogic/layout.py:461`; `DOCUMENTATION.md:866`.
- **Repro:** Uses the real layout pass with two unconnected cells, then changes the supposedly global minimum. No source file is edited.

```powershell
@'
from drawlogic import layout,rules
from drawlogic.doc import new_document
d=new_document('gap')
d.cells.extend([{'id':'a','type':'inv','x':0,'y':0},
                {'id':'b','type':'inv','x':0,'y':0}])
d.normalize();layout.arrange(d);before=d.dumps()
old=rules.CELL_MIN_GAP
try:
    rules.CELL_MIN_GAP=200
    layout.arrange(d)
    print('unchanged:',before==d.dumps())
    print('required minimum:',rules.CELL_MIN_GAP)
    print('actual gap:',d.cells[1]['y']-d.cells[0]['y']-d.cells[0]['h'])
finally:
    rules.CELL_MIN_GAP=old
'@ | python3 -
```

- **Expected vs actual:** The manual describes this as the least permitted space between any two cells and says tuning rules.py is sufficient. Actual: `unchanged: True`, `required minimum: 200`, `actual gap: 52.0`. The rule is declared and returned by the rules endpoint, but no layout or placement code reads it; layout only uses the separate column/row gap arguments.
- **Severity:** minor -- a documented drafting control is ineffective, so users cannot impose the advertised minimum spacing.
- **Fix sketch:** Enforce the minimum when calculating both row and column separations, or remove the unused setting and its guarantee. Test a minimum greater than both nominal gaps so a silently unused rule is detectable.

**9. Title: Validation rejects supported groups of shapes as nonexistent members**

- **Location:** `drawlogic/doc.py:623`, `drawlogic/doc.py:628`.
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
- **Severity:** minor -- it produces false errors and blocks validation workflows for otherwise valid grouped annotations.
- **Fix sketch:** Validate group membership against the supported selectable object types, including shapes, while retaining missing-member and overlapping-group checks.

**10. Title: Duplicating a group drops the group relationship**

- **Location:** `drawlogic/web/js/model.js:535`, `drawlogic/web/js/model.js:545`, `drawlogic/web/js/model.js:548`.
- **Repro:** These steps were executed in the actual browser editor, without saving the changed example.

```powershell
python3 -m drawlogic serve examples/dff_slice.dlg --no-browser --port 8091
```

Open `http://127.0.0.1:8091/?open=dff_slice.dlg`. Click the canvas, press Ctrl+A, click **Group**, then press Ctrl+D. The status shows `20 cells | 14 nets | 10 selected`. Press Escape to clear selection, then click the duplicated AND gate labeled **U3**. Observe `20 cells | 14 nets | 1 selected`. The original group can still be selected as a group; the duplicate cannot. Stop the server with Ctrl+C and discard these test edits.

- **Expected vs actual:** Duplicating a grouped object should preserve its internal grouping under fresh IDs. Actual: the duplicate's components are independent. Clipboard data contains only cells, shapes, and nets; neither copying nor pasting transfers groups. Consequently the duplicate ceases to move/resize as one object after deselection.
- **Severity:** minor -- an ordinary duplication operation silently removes editing structure and requires manual regrouping.
- **Fix sketch:** Copy complete selected groups and remap their member IDs and group IDs during paste. Define how partial groups behave and test copying, cutting, and Ctrl-drag duplication through the same path.

**11. Title: Malformed JSON structure crashes request handling instead of returning a validation response**

- **Location:** `drawlogic/server.py:239`, `drawlogic/server.py:265`, `drawlogic/doc.py:395`.
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
- **Severity:** minor -- malformed input defeats the advertised validation/error-response path and makes clients see an unexplained transport failure.
- **Fix sketch:** Check request-object and nested document types before normalization. Raise `DocumentError` for schema violations and translate them consistently into CLI diagnostics and HTTP 422 responses.

## Suspected

**1. Title: Concurrent custom-symbol saves can overwrite one another or expose a truncated library**

- **Location:** `drawlogic/authoring.py:257`, `drawlogic/authoring.py:263`, `drawlogic/authoring.py:267`; `drawlogic/server.py:336`.
- **Expected vs actual:** Saving different symbols concurrently should retain both definitions and readers should see a complete JSON file. Inspection shows an unlocked read-modify-write sequence against one `symbols.json`, called by `ThreadingHTTPServer`, with direct truncating writes. Two requests appear able to read the same old library and commit incompatible replacements; an I/O failure can also interrupt the write. These outcomes were not reproduced.
- **Severity:** major -- if confirmed, it loses reusable symbols and can prevent the folder's library from loading.
- **Fix sketch:** Serialize library updates and write a complete replacement to a sibling temporary file before atomic replacement. Include a concurrency test for distinct symbol IDs and a failed-write preservation test.
- **What stopped confirmation:** I did not run an overlapping two-client symbol-save test or inject a mid-write filesystem failure; normal symbol authorship and failure recovery remain coverage gaps.

**2. Title: Dragging scales with a full-document JSON copy on every pointer movement**

- **Location:** `drawlogic/web/js/model.js:48`, `drawlogic/web/js/model.js:66`, `drawlogic/web/js/model.js:70`.
- **Expected vs actual:** A gesture should make one undo snapshot and keep pointer updates responsive on larger drawings. Inspection shows that every mutation serializes and reparses the entire document before checking whether the gesture already has its undo snapshot. Most of those copies are discarded; embedded image strings are included. I have not measured the point at which this becomes a user-visible problem.
- **Severity:** minor -- repeated allocation is a credible editing-performance risk as drawings and embedded assets grow, but a stall threshold is unconfirmed.
- **Fix sketch:** Avoid creating unused full-document snapshots within an already-open gesture, and measure pointer latency and retained undo memory on drawings with many cells and images. Keep undo correctness tests independent of the storage strategy.
- **What stopped confirmation:** No large-drawing/browser-memory benchmark was completed; the executed interactive checks used the supplied small example.

Remaining coverage gaps: the Python 3.8 minimum and older Node versions; sustained large-drawing performance; interrupted and concurrent disk writes; filesystem symlinks/junctions; end-to-end hostile-origin browser requests and native dialog flows; PNG clipboard behavior and print/PDF; and full custom-symbol editing across nested folders. The delayed save/layout repro is an isolated execution of production handlers, not a throttled end-to-end browser test.

One good result: all three initial calibration mutations were detected.
