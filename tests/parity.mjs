// Check that web/engine.js and navigator/apply.py agree for every address on several dates.
// Usage: python -m navigator.export_web && python tests/dump_py.py > /tmp/py.json && node tests/parity.mjs /tmp/py.json
import fs from "fs";
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const engine = require("../web/engine.js");
const data = JSON.parse(fs.readFileSync(new URL("../web/data.json", import.meta.url)));
const py = JSON.parse(fs.readFileSync(process.argv[2]));
let diffs = 0, total = 0;
for (const [asOf, lookups] of Object.entries(py)) {
  for (const a of data.addresses) {
    total++;
    const js = engine.lookup(a, data.rules, asOf);
    if (JSON.stringify(js) !== JSON.stringify(lookups[a.address_id])) {
      if (diffs++ < 3) console.log("DIFF", asOf, a.address_id, JSON.stringify(js).slice(0, 300), "\nPY  ", JSON.stringify(lookups[a.address_id]).slice(0, 300));
    }
  }
}
console.log(diffs ? `FAIL: ${diffs}/${total} lookups differ` : `OK: ${total} lookups identical`);
process.exit(diffs ? 1 : 0);
