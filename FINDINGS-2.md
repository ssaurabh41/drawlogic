## Demonstrated

Reviewed upstream **216463e**, including the changes since 06911a4, on Windows with Python 3.14.7 and Node 24.19.0. One agent; no implementation fixes. Commands below run from the repository root in PowerShell; `python` is this machine's Python 3 launcher. Temporary mutations were restored byte-for-byte. AGENTS.md/agents.md is absent from the reviewed tree.

Baseline: `python -m unittest discover` ran **312 tests in 33.148s, OK (skipped=1)**. Final verification after restoring all mutations ran **312 in 32.300s, OK (skipped=1)**. The skipped confinement test requires a symlink privilege unavailable here. This is 311 executed tests, not 312 passes. Targeted parity/DRC/manifest verification ran 58 tests in 5.172s; the subsequent server/net/editor checks ran 47 in 0.224s. `doctor` reported 33 symbols, 11 browser modules, no import mismatch, and 28 matching manifest files. No goldens changed. The separate original checkout has local edits, including an AGENTS.md file; those were preserved rather than conflated with the reviewed upstream tree.

**1. Title: A directory link bypasses the server's root boundary for both reading and saving**

- Location: `drawlogic/server.py:75` (`_safe_join`).
- Repro: Create a disposable outside drawing and a Windows junction inside the served directory. Start the server in another terminal; these commands intentionally modify only the new fixture:

  ```powershell
  New-Item -ItemType Directory -Path ../pass2-outside
  Copy-Item examples/dff_slice.dlg ../pass2-outside/private.dlg
  New-Item -ItemType Junction -Path examples/pass2-link -Target (Resolve-Path ../pass2-outside).Path
  python -m drawlogic serve examples/dff_slice.dlg --no-browser --port 8094
  ```

  In a second terminal at the repository root:

  ```powershell
  @'
  import json
  from urllib.request import Request, urlopen
  from drawlogic.doc import Document
  url='http://127.0.0.1:8094/api/doc?path=pass2-link/private.dlg'
  print('GET',urlopen(url).status)
  d=Document.load('../pass2-outside/private.dlg')
  d.data['title']='LATEST_OUTSIDE_WRITE'
  body=json.dumps({'path':'pass2-link/private.dlg','doc':d.data}).encode()
  print('POST',urlopen(Request('http://127.0.0.1:8094/api/doc',data=body,
      headers={'Content-Type':'application/json'})).status)
  print(Document.load('../pass2-outside/private.dlg').data['title'])
  '@ | python -
  ```

- Expected vs actual: Both requests should reject a resolved destination outside the root. Both returned 200; the actual outside file acquired the marker title. `abspath` checks the lexical path, not the junction destination. The hierarchy-reference fix does not cover these direct document requests. Prerequisite: an existing link under the served root; this does not demonstrate creating that link remotely.
- Severity: **major** — the advertised file boundary allows unauthorized reads and overwrites of files reachable through such a link.
- Fix sketch: Check resolved filesystem destinations for every read/write operation, including the real parent of a new file; apply the same confinement policy to direct documents and references. Account for link replacement races if other users can modify the served folder.

**2. Title: A delayed layout response still discards edits made to the same drawing**

- Location: `drawlogic/web/js/main.js:793`.
- Repro: This executes the production Store and request-completion functions in Node, replacing only transport and UI sinks with controlled stubs. It also reproduces finding 9.

  ```powershell
  @'
  import fs from 'node:fs';
  import vm from 'node:vm';
  import * as model from './drawlogic/web/js/model.js';
  const source=fs.readFileSync('drawlogic/web/js/main.js','utf8')
    .replace(/^import .*;\r?\n/gm,'').replace(/start\(\);\s*$/,'');
  const c=vm.createContext({model,Selection:class {clear(){}},console,
    window:{clearTimeout(){},localStorage:{setItem(){}}}});
  vm.runInContext(source+`
    globalThis.test={store,autoLayout,runCheck,setLive};
    say=()=>{};syncControls=()=>{};redraw=()=>{};
    inspector={render(){}};viewport={fit(){}};ui.btnCheck={};
    globalThis.pending=null;api=()=>new Promise(r=>{pending=r});
    globalThis.painted=0;showViolations=()=>{painted++};
  `,c);
  const doc=title=>({title,canvas:{width:500,height:300},
    cells:[{id:'a',type:'inv',x:50,y:50}],nets:[],shapes:[],groups:[]});
  c.test.store.load(doc('before'),'a.dlg');
  let op=c.test.autoLayout();
  c.test.store.mutate('new note',d=>{
    d.title='EDIT AFTER REQUEST';d.shapes.push({id:'note',kind:'text',text:'KEEP'});
  });
  c.pending({doc:doc('before'),shapes:0,note:'done'});await op;
  console.log('LATE_LAYOUT',JSON.stringify(c.test.store.doc));
  op=c.test.runCheck({quiet:true});c.test.setLive(false);
  c.pending({errors:0,warnings:1,violations:[]});await op;
  console.log('PAINTED_AFTER_LIVE_OFF',c.painted);
  '@ | node --input-type=module -
  ```

- Expected vs actual: Preserve the newer edit, reject the outdated result, or prevent editing while layout is outstanding. Actual title is `before`, shapes are `[]`. The guard deliberately ignores the edit revision, then replaces the entire document. This part of cold finding 2 remains unfixed, although changing to a different drawing is now protected. Undo can recover the edit; this is not demonstrated irreversible disk loss.
- Severity: **major** — a normal asynchronous command silently removes subsequent work, which the next save can persist.
- Fix sketch: Require an unchanged edit revision before applying layout, or apply a verified position-only transformation to the current revision. Cover edits arriving between request and response, separately from switching documents.

**3. Title: Browser arrows intersect crossing bridges while exported arrows avoid them, with every parity test green**

- Location: `drawlogic/web/js/render.js:564`; `drawlogic/render_svg.py:646`; `tests/test_js_parity.py:175`; `tests/js/route_dump.mjs:53`.
- Repro:

  ```powershell
  @'
  from drawlogic.doc import new_document
  from drawlogic import render_svg
  d=new_document('Arrow at crossing',650,250)
  d.canvas['grid']['style']='blank'
  d.nets.extend([
    {'id':'h','from':{'x':50,'y':100},'to':[{'x':550,'y':100}]},
    {'id':'v','from':{'x':290,'y':50},'to':[{'x':290,'y':180}]}])
  d.normalize();d.save('examples/pass2-hop.dlg')
  open('examples/pass2-hop.svg','w').write(render_svg.render(d))
  '@ | python -
  python -m unittest tests.test_js_parity
  python -m drawlogic serve examples/pass2-hop.dlg --no-browser --port 8094
  ```

  Open `http://127.0.0.1:8094/?open=pass2-hop.dlg` in a browser. Also open the generated SVG file in a browser. Compare the crossing at drawing coordinate (290,100).
- Expected vs actual: The same arrows should be visible. The actual editor has three arrows, including one on the bridge; the Python SVG has two, with tips (538.8,100) and (290,168.8). I viewed both. All six parity tests passed **in 3.269s with this new fixture included**. Python rendering excludes arrows near hops as well as junctions. Browser rendering and both parity helper calls exclude only junctions. Thus even the advertised arrow-position comparison does not exercise the actual exporter call path.
- Severity: **major** — the preview and delivered schematic disagree while the designated cross-language safety net reports success.
- Fix sketch: Make actual renderer inputs consistent and compare observable rendered primitives for constructed cases, including bridge/arrow interactions. Helper-to-helper parity alone cannot establish renderer parity.

**4. Title: Cropped export reduces a long text annotation to a clipped first letter**

- Location: `drawlogic/doc.py:542`; `drawlogic/drc.py:443`.
- Repro:

  ```powershell
  @'
  from drawlogic.doc import new_document
  from drawlogic import render_svg,drc
  d=new_document('')
  d.shapes.append({'id':'text','kind':'text','x':100,'y':100,
    'text':'A VERY LONG SIGNAL ANNOTATION','style':{'fontSize':40}})
  d.normalize()
  print('bounds',d.content_bbox(),'DRC',drc.check(d))
  open('pass2-text.svg','w').write(render_svg.render(d,crop=True))
  '@ | python -
  ```

  Open `pass2-text.svg` in a browser.
- Expected vs actual: Crop includes the complete annotation. Actual content bounds are `(100,100,0,0)` and the SVG is 48 by 48 with viewBox `76 76 48 48`; I saw only a clipped `A`. DRC returns `[]`. Text shapes contribute their anchor, not their text extent; DRC text boxes cover cell/net labels rather than arbitrary annotation shapes. The cold wire-bounds correction does not solve this separate case.
- Severity: **major** — a supported export operation silently removes substantive drawing content.
- Fix sketch: Include transformed text extents in bounds, with the same font scaling and anchoring as rendering; include annotation text in applicable containment/overlap checks.

**5. Title: The Check API reports a clean drawing that CLI validation rejects**

- Location: `drawlogic/server.py:393` and `drawlogic/server.py:418`.
- Repro: With the local server from finding 1 running:

  ```powershell
  @'
  import json,subprocess,sys
  from urllib.request import Request,urlopen
  from drawlogic.doc import new_document
  d=new_document('invalid')
  d.cells.append({'id':'bad','type':'missing','x':100,'y':100,'w':60,'h':40})
  d.normalize();d.save('pass2-invalid.dlg')
  req=Request('http://127.0.0.1:8094/api/check',
    data=json.dumps({'doc':d.data}).encode(),
    headers={'Content-Type':'application/json'})
  print(urlopen(req).read().decode())
  print('CLI exit',subprocess.run([sys.executable,'-m','drawlogic',
    'validate','pass2-invalid.dlg']).returncode)
  '@ | python -
  ```

- Expected vs actual: The unknown symbol must be reported, or Check must explicitly distinguish unchecked document validity. Actual HTTP 200 returns `{"violations":[],"errors":0,"warnings":0}`; CLI exits 1 with `cell bad: unknown cell type 'missing'`. `_check` invokes only geometric DRC and also discards the issues returned by hierarchy resolution. Its assertion that a drawing passing here passes everywhere is false.
- Severity: **major** — a clean result conceals a document error that prevents reliable interpretation/rendering.
- Fix sketch: Combine schema/reference issues with geometric violations, preserving their locations and severity, or expose separate clearly named validity and DRC results.

**6. Title: Removing the wire-spacing checker leaves all 34 DRC tests green**

- Location: `drawlogic/drc.py:469`; `tests/test_drc.py`; `REVIEW.md:74`.
- Repro: Substitute each production checker with a no-op independently, run its suite, and restore it. This is behaviorally equivalent to removing its call from `check()`.

  ```powershell
  @'
  import io,pathlib,re,unittest
  from drawlogic import drc
  names=re.findall(r'^  (_check_\w+)\(scene, report\)',
    pathlib.Path('drawlogic/drc.py').read_text(),re.M)
  for name in names:
    old=getattr(drc,name);setattr(drc,name,lambda *args:None)
    try:
      r=unittest.TextTestRunner(stream=io.StringIO()).run(
        unittest.defaultTestLoader.loadTestsFromName('tests.test_drc'))
      print(name,'GREEN' if r.wasSuccessful() else 'RED',r.testsRun,
        len(r.failures),len(r.errors))
    finally:setattr(drc,name,old)
  '@ | python -
  ```

- Expected vs actual: The author explicitly promises red for every one of nine checks. `_check_wire_spacing` stays green: 34 tests, zero failures/errors. The other eight go red: contact 1 failure; crossings 1; wires/cells 1; wire shape 1; cell spacing 3 failures/2 errors; text 1; hops 2; sheet 2. This is a targeted behavior test, not the manifest's detection of a changed source file.
- Severity: **major** — an entire advertised DRC can disappear without its behavioral suite noticing.
- Fix sketch: Add a specific positive case requiring `wire-spacing`, and a nearby negative control; verify the same mutation turns that test red.

**7. Title: The strengthened editor wrapper still accepts deletion of 18 checks**

- Location: `tests/test_js_editor.py:32`; `tests/js/editor_check.mjs:372`; `tests/js/editor_check.mjs:498`; `REVIEW.md:148`.
- Repro:

  ```powershell
  @'
  import pathlib,subprocess,sys
  p=pathlib.Path('tests/js/editor_check.mjs');original=p.read_bytes()
  try:
    s=original.decode();a=s.index('// ---- undo through a gesture ----')
    b=s.index('if (failures)',a);p.write_text(s[:a]+s[b:])
    subprocess.run(['node',str(p),'drawlogic/symbols.json'])
    subprocess.run([sys.executable,'-m','unittest','tests.test_js_editor'],check=True)
  finally:p.write_bytes(original)
  '@ | python -
  ```

- Expected vs actual: Removing undo/group/stale-state checks should fail the documented missing-check guard. The runner prints `DONE 40/40` instead of 58/58 and the wrapper passes (one test, 0.080s). The expected denominator is the same self-count as the numerator; the independent minimum remains 30. The old single-console-line stub is caught now, but the stronger assertion that deleting assertions fails is still false.
- Severity: **major** — whole behavioral areas can stop being tested without changing the Python test count or success result.
- Fix sketch: Track an independent expected set of named checks or explicit per-area expectations. Keep completion and exit checks, but do not use a count calculated from executed assertions as both actual and expected.

**8. Title: Save-as-symbol rejects ellipse artwork produced by its own converter**

- Location: `drawlogic/authoring.py:196`; `drawlogic/symbols.py:32`.
- Repro:

  ```powershell
  @'
  import tempfile,os
  from drawlogic.doc import new_document
  from drawlogic import authoring
  d=new_document()
  d.shapes.append({'id':'s','kind':'ellipse','x':50,'y':50,'w':100,'h':60})
  d.cells.append({'id':'p','type':'port_in','x':0,'y':60,'label':'a'})
  d.normalize()
  with tempfile.TemporaryDirectory() as td:
    authoring.add_to_file(os.path.join(td,'symbols.json'),'ellipse',
      authoring.symbol_from(d,'ellipse'))
  '@ | python -
  ```

- Expected vs actual: Supported ellipse artwork should become a reusable symbol. `symbol_from` emits `op: ellipse`, but saving raises `SymbolError: symbol 'ellipse' has unknown draw op 'ellipse'`. Both rendering implementations already support ellipses; the registry's allowed operations disagree with the converter.
- Severity: **minor** — a specific supported authoring workflow fails immediately rather than corrupting existing drawings.
- Fix sketch: Align the symbol schema, authoring converter and renderers, and test authoring through actual registry acceptance rather than conversion alone.

**9. Title: Turning live checking off does not suppress an already outstanding automatic result**

- Location: `drawlogic/web/js/main.js:532`; `drawlogic/web/js/main.js:574`.
- Repro: Run the complete Node reproduction in finding 2; its final three operations begin a quiet check, disable live checking, and deliver its response without a document change.
- Expected vs actual: Switching to manual mode should invalidate outstanding automatic presentation. Actual `PAINTED_AFTER_LIVE_OFF` is 1. Clearing the debounce timer does not invalidate an already dispatched request, and the response guard checks document stamps only. This is a production-handler reproduction with UI sinks stubbed, not a timed browser observation.
- Severity: **minor** — manual mode can still receive an unsolicited update; no incorrect document content or persistent loss was demonstrated here.
- Fix sketch: Associate automatic checks with a live-mode generation and discard responses from a disabled generation, while allowing explicitly requested manual checks to complete.

**Claims-table audit (REVIEW section 2, all 19 rows)**

The following is a verification ledger, not additional unreproduced defect findings. A passing finite check is distinguished from the broader claim it purports to establish.

| Claim/check | Executed result and evidential limit |
|---|---|
| Bare machine / discovery | Local discovery passed as recorded above; Docker and Python 3.8 are unavailable. The exact bare-container check remains unexecuted. Local success proves neither minimum-version support nor a container without dependencies. Node was present. |
| Wires follow cells / drag | Opened dff_slice, dragged U1 onto FF1, observed attached rerouting; Undo restored it. Establishes this gesture, not every transform or branch topology. |
| One tuning point / WIRE_GAP | Temporarily changed 18 to 36 in drc.py, exported all seven through fresh Python processes, restored bytes. Three SVGs changed (alu, cdc, soc); four did not (dff, fifo, mac, spi). It affects constrained routing, not “every wire spacing.” Rendering-only constants also live elsewhere. |
| One canvas/export rule set / parity | Six tests pass, including fallback constants. The constants comparison is useful; it does not establish all renderer behavior. Finding 3 directly disproves the broad reading. |
| Pin endpoints / inspect dff nets[0] | The example uses cell/pin references. This establishes the example's representation; coordinate endpoints remain supported, as finding 3 demonstrates. It does not prove that no wire anywhere stores x/y. |
| One export renderer / server test | `python -m unittest tests.test_server.TestEndpoints.test_export_writes_svg_through_the_python_renderer` passes. Actual cold CLI/HTTP setting reproduction also now agrees. Good evidence for these entry points and options; not evidence that preview matches export. |
| Identical routing / parity | Six pass over the fixtures, including the added crossing. Actual route, junction, hop, label and arrow helper comparisons exist. There is no final rendered SVG comparison, and the arrow helper setup differs from production Python rendering. |
| No-code symbols / add and list | Copied the built-in inv data as pass2_gate into a temporary symbols.json; `python -m drawlogic --symbols-dir DIR symbols list` exits 0 and lists it. Establishes discovery, not renderability or authoring compatibility (finding 8). |
| Shared symbols / server test | `python -m unittest tests.test_server.TestEndpoints.test_symbols_match_the_python_registry` passes. Its assertion compares IDs and an and2 size, not every pin, draw primitive or property. API sharing is implemented, but this check is weaker than complete content identity. |
| Root confinement / server suite | Server tests pass, including lexical traversal/prefix refusals. Actual junction read/write escapes (finding 1); lexical cases do not establish filesystem confinement. |
| Text diffs / info, edit, save | Ran info on soc_top and round-tripped all seven after a title edit; serialized round-trips are stable. This is evidence of deterministic serialization, not that arbitrary layout/migration edits create a small human-readable diff. |
| v1 loading / test_nets | Module passed in the 47-test targeted run; same-driver/name and idempotency coverage exists. Establishes covered migrations, not electrical equivalence of differently named aliases. |
| Real DRC faults / test_drc | 34 tests pass and eight disabled checks are detected. There is real behavioral coverage, with the ninth-rule hole in finding 6. |
| Nonvacuous DRC / nine deletions | Executed all nine independent no-op mutations; eight red, one green. Claim disproved, finding 6. |
| No false alarms / validate examples | Exported all seven and collected schema/reference plus DRC results: errors 0 for all; warning totals alu 3, cdc 2, dff 4, fifo 0, mac 7, soc 13, spi 17. Also viewed all seven rendered SVGs. This supports their general readability, not that every one of 46 warnings is justified; not every warning was individually adjudicated. “Every example has a few” is false for fifo. |
| Live checking keeps up / overlap | Real browser drag produced a cell-overlap ring and matching pane/status count of 1 error, 12 warnings; Undo settled to 0 errors, 1 warning. No sub-second timing instrumentation: “about half a second” is not measured. |
| Count never stale / drag | Exercised drag and Undo, observed eventual fresh matching counts. Those observations cannot establish “never”; did not capture the exact first-move gray transition. Controlled outstanding-response test finds the manual-toggle defect, not a wrong-document count. |
| Copy integrity / doctor and PowerShell | Doctor: 28/28 match. `powershell -NoProfile -ExecutionPolicy Bypass -File verify.ps1`: 28 files, all as they should be. Default execution policy initially refused the script; that is an environment restriction, not a hash defect. Establishes both implementations agree on this checkout. |
| Manifest rot / append newline | Appended a newline to theme.py, ran tests.test_manifest, restored bytes: 18 tests, 3 failures, including the regeneration command. This check works for a covered file; the manifest covers the declared 28 runtime files, not every possible file one might add under drawlogic. |

**The four decisions: concrete arguments against them**

| Decision | Case against it and assessment of the alternative |
|---|---|
| (a) Symbols as data | The contract already fractures at a single ellipse, before library size matters (finding 8). Listing a JSON key does not establish a usable symbol; the load validator checks operation names rather than all operation fields. Executable symbol plugins would add two implementations for each new gate and undermine the shared-library advantage. Keep data, but make one explicit schema govern authoring, loading and both renderers. The disclosed late-validation risk is understated because valid converter output itself is rejected. |
| (b) Central Python export | The first preview/export crossing fixture is enough to invalidate WYSIWYG (finding 3). A network-dependent export also has a failure point absent from local interaction. Nevertheless, making browser export another independent renderer would lose the CLI/HTTP equality now verified and add another output contract. Centralization is defensible; the missing requirement is testing the actual preview against that canonical output. Copy PNG still depends on browser rasterization after Python SVG, so byte identity of SVG does not establish PNG identity. |
| (c) Hand ports and parity | The author's description of the comparisons and lack of an SVG diff is substantially accurate, but optimistic about what “arrow positions” means: the production Python exclusion inputs are missing from both test helper calls. The visible mismatch survives all six tests on its own fixture. Server routing per pointer movement would burden the drag loop, so that obvious alternative is worse for current interaction. Keep local routing if needed, but test actual rendered output and a matrix of styles/topologies, rather than treating common helper inputs as proof. |
| (d) Python layout over HTTP | A single in-flight response loses a subsequent edit (finding 2); it does not require a huge drawing. Current soc_top layout plus measurement took 2.725s locally, already a meaningful editing window. “The round trip is free” is false as a state-management claim even when network latency is negligible. A JS port would add another routing/DRC scoring implementation without curing stale responses. Revision protection and explicit command state are required irrespective of implementation language. |

**Author weaknesses: calibration against sections 5 and 6**

| Author topic | Assessment and evidence |
|---|---|
| 5.1 Router/fallback ladder | **About right.** Current all-example layout actually produces 11 DRC errors; geometry is not guaranteed readable. No new isolated fallback-reachability counterexample was established; do not treat this review as proof that every fallback is necessary. |
| 5.2 v1 merge policy | **About right.** Tests exercise preserving separately named same-driver nets and idempotency. Distinct names can represent annotations/aliases in a drawing-only tool; merging them would discard a name. Electrical consistency remains outside this check's evidence. |
| 5.3 Pin alignment | **About right.** Alignment tests pass and the exported examples were viewed. Downstream clamping remains a legitimate boundary to test, but I did not establish a new current alignment defect. |
| 5.4 Authoring/snapping | **Understated overall.** The concern is not confined to pathological pin positions: the ordinary ellipse conversion fails registry acceptance (finding 8). No new claim of incorrect corner snapping is made here. |
| 5.5 Ordering/refinement | **About right for computational cost; incomplete about impact.** The supplied measurement runs and current soc_top took 2.725s including route/DRC measurement. The real user-visible asynchronous failure is finding 2. I did not isolate a losing-candidate state leak or a nonterminating refinement loop. |
| 5.6 Labels | **Understated.** The checker is not a general legibility oracle: a long text shape exports clipped while DRC is empty (finding 4). This is distinct from whether a net-label score is locally optimal. |
| 5.7 DRC soundness | **Understated.** Rule distances may be sensible, but a complete spacing rule can vanish undetected; Check also omits schema validity. Findings 5 and 6 challenge the instrument, not aesthetic thresholds. |
| 5.8 Live scheduling | **Understated.** Real overlap/Undo works, but switching to manual fails to invalidate an outstanding automatic update (finding 9). The concern is broader than checking a different document revision. Slow-check disabling, exception recovery and sustained editing were not exhaustively exercised. |
| 5.9 Cross-language hashing | **About right.** Executed both hash implementations on this Windows checkout; both match all 28 files. The tests' textual inspection of PowerShell cannot substitute for that execution. This run does not establish all BOM/line-ending combinations in PowerShell. |
| 6 Browser coverage | **Overstated for “no standing test” of undo/grouping; understated for integration.** Actual editor_check has gesture undo and group duplication assertions, among 58 checks. The missing tests are especially main.js transport/timer integration, as findings 2 and 9 show. Optional development-only browser tests need not add a runtime dependency; Node is already an optional test dependency. The asserted choice between browser tests and a dependency-free application is unnecessarily absolute. |
| 6 Visual regression | **About right, with a demonstrated consequence.** Seven SVG goldens do not compare browser paint. All seven current exports were viewed; the constructed bridge/arrow case proves the practical gap. |
| 6 Unauthenticated --host | **About right about exposure, understated about confinement.** Network exposure is intentionally documented, not discovered here as a new exploit. Even on loopback, direct filesystem confinement fails for directory links (finding 1). No cross-origin attack was established. |
| 6 Not built: ERC/netlists/title blocks/multi-sheet/PDF | **About right as scope exclusions.** Their absence alone is not a defect. It makes precise labeling of schema checks versus geometric DRC particularly important (finding 5). |
| 6 Measured layout quality | **Numbers correct; acceptability understated.** Executed the exact supplied algorithm: 118 crossings, 11 errors, 49 warnings. Per drawing (crossings/errors/warnings): alu 10/1/0, cdc 24/2/11, dff 0/0/0, fifo 8/0/15, mac 5/0/4, soc 48/5/10, spi 23/3/9. Automatically turning zero-error inputs into error-bearing outputs is observable degradation; calling it a design choice does not establish user acceptability. The disclosed figures are not a newly discovered defect, and I have not established that a zero-error alternative exists for each example. |
| 6 Batch validate | **About right.** `python -m drawlogic validate examples/alu_slice.dlg examples/dff_slice.dlg` exits 2 on the second filename. This is a real workflow asymmetry, but a shell loop works; it is not data corruption. |

**Cold-pass corrections and omissions**

The latest changes correct the specific cold cases for normalized New filenames, save revision handling, cross-document layout, hierarchical reference traversal, v2 wire crop bounds, CLI arrow/hop defaults, arrow-vector assertions, CELL_MIN_GAP use, shape-group validation, group duplication and malformed request handling. Replayed applicable cold reproductions and ran the relevant current tests. Concurrent symbol updates now have synchronization and regression coverage; the full suite passes. This is case-specific verification, not a claim that related surfaces are now safe: same-document layout and the editor missing-check guard remain partial fixes (2 and 7), and direct linked paths remain outside the hierarchy fix (1).

REVIEW section 8 omits three specific cold topics: v2 crop bounds, duplicated groups losing membership, and per-pointer-move full-document snapshots. Its accounting also mixes the originally suspected concurrent-symbol race into the demonstrated list. The current REVIEW is more informative than the original cold report in these seven pre-existing risk areas: complete rendered-SVG parity, symbol schema completeness, differently named v1 aliases, coincident authored pins, label legibility, unauthenticated non-loopback serving, and batch-validation asymmetry. **The author's list of topics I missed in the cold pass is longer: seven versus three.** These are risk-topic counts, not seven newly reproduced defects; newly added DRC/live/manifest features are excluded from that historical comparison.

What is missing from the author's account, beyond those historical omissions: the concrete hop-exclusion mismatch inside supposedly covered arrows; same-document layout edit loss; direct junction writes; annotation crop/DRC blind spots; clean Check versus failed schema validation; the missing wire-spacing test; the still-weak editor completion guard; and the ellipse converter/registry contradiction. Findings above provide reproductions rather than asking the author to accept those as architectural opinions.

## Suspected

**1. Title: The claimed Python 3.8 bare-machine verification is not established by this run**

- Location: `REVIEW.md:61` (bare-machine claim/check); Python-version claim in the introduction.
- Expected vs actual: The claimed supported minimum and clean-container behavior need execution in that environment. Local Python 3.14.7 with Node runs the suite successfully, with one skip; this neither disproves nor establishes Python 3.8 compatibility. Section 3's example still says 261 tests and 55 editor checks, while this checkout runs 312 and 58.
- Severity: **minor** — this is a verification gap and misleading evidence presentation, not a demonstrated minimum-version failure.
- Fix sketch: Add an explicit minimum-Python job and report missing Node-dependent checks separately from executed passes; derive displayed counts from current results.
- What stopped confirmation: No Docker executable or Python 3.8 runtime was available; I did not install another runtime or claim a substitute local run was the requested container check.

**Coverage limits:** No exhaustive fallback-removal experiment, large generated-layout benchmark, every-warning visual adjudication, complete live-check slow/error/continuous-edit matrix, PowerShell normalization corpus, cross-origin exploit attempt, or full 30-minute register-file authoring exercise. The first-move gray-state timing and half-second latency promise remain unmeasured. No implementation fixes, PR, or main-branch push are part of this review.

One thing done well: the current layout-quality numbers and Windows manifest agreement both survive independent execution.
