// Print the DRC limits routing.js falls back to when nobody sets them.
//
// Run by tests/test_js_parity.py. The editor overwrites these from /api/drc
// at startup, so they matter only when the module is loaded on its own -- but
// a stale copy means the browser routes a drawing differently from the file
// Python exports, which is the one failure the parity suite exists to catch.
//
// Usage: node tests/js/drc_dump.mjs

import * as routing from "../../drawlogic/web/js/routing.js";

process.stdout.write(JSON.stringify(routing.currentLimits()));
