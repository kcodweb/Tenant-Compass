// Coverage engine for the browser. A line-for-line port of navigator/apply.py so the demo
// page can answer "as of" any date without a server. tests/parity.mjs checks that both
// engines return identical results for every address on several dates.
(function (root) {
  const TRUE = true, FALSE = false, UNKNOWN = null;

  function parseDate(s) {
    if (!s) return null;
    const p = s.split("-").map(Number);
    while (p.length < 3) p.push(1);
    return { y: p[0], m: p[1], d: p[2], iso: `${p[0]}-${String(p[1]).padStart(2, "0")}-${String(p[2]).padStart(2, "0")}` };
  }
  const cmp = (a, b) => (a.iso < b.iso ? -1 : a.iso > b.iso ? 1 : 0);

  function and(results) {
    const vals = results.map(r => r[0]);
    if (vals.includes(FALSE)) return [FALSE, results.filter(r => r[0] === FALSE).map(r => r[1])];
    if (vals.includes(UNKNOWN)) return [UNKNOWN, results.filter(r => r[0] === UNKNOWN).map(r => r[1])];
    return [TRUE, results.map(r => r[1])];
  }

  function coverage(rule, a, asOf) {
    const c = rule.coverage || {};
    const checks = [];
    const units = a.units, umin = a.units_min, umax = a.units_max;
    if (c.min_units) {
      const n = c.min_units;
      if (units !== null) checks.push([units >= n, `${units} units ${units >= n ? "≥" : "<"} ${n}`]);
      else if (umin !== null && umin >= n) checks.push([TRUE, `use code implies ≥${umin} units (≥${n} needed)`]);
      else if (umax !== null && umax < n) checks.push([FALSE, `use code implies ≤${umax} units (<${n})`]);
      else checks.push([UNKNOWN, `unit count not in the data (rule needs ≥${n})`]);
    }
    if (c.max_units) {
      const n = c.max_units;
      if (units !== null) checks.push([units <= n, `${units} units ${units <= n ? "≤" : ">"} ${n}`]);
      else if (umin !== null && umin > n) checks.push([FALSE, `use code implies ≥${umin} units (>${n})`]);
      else if (umax !== null && umax <= n) checks.push([TRUE, `use code implies ≤${umax} units`]);
      else checks.push([UNKNOWN, `unit count not in the data (rule covers ≤${n})`]);
    }
    const yb = a.year_built;
    for (const [field, before] of [["co_on_or_before", true], ["co_after", false]]) {
      const d = parseDate(c[field]);
      if (!d) continue;
      const label = `certificate of occupancy ${before ? "on or before" : "after"} ${d.iso}`;
      if (yb === null) checks.push([UNKNOWN, `year built not in the data (${label} needed)`]);
      else if (yb === d.y) checks.push([UNKNOWN, `built in ${yb}, the cutoff year; year built ≠ certificate date (${label} needed)`]);
      else {
        const ok = before ? yb < d.y : yb > d.y;
        checks.push([ok, `built ${yb}; ${label} ${ok ? "met" : "not met"}`]);
      }
    }
    if (c.exempt_if_newer_than_years) {
      const n = c.exempt_if_newer_than_years, cutoff = asOf.y - n;
      if (yb === null) checks.push([UNKNOWN, `year built not in the data (buildings under ${n} years old are exempt)`]);
      else if (yb < cutoff) checks.push([TRUE, `built ${yb}, more than ${n} years before ${asOf.iso}`]);
      else if (yb > cutoff) checks.push([FALSE, `built ${yb}, less than ${n} years old (exempt)`]);
      else checks.push([UNKNOWN, `built ${yb}, exactly at the ${n}-year rolling cutoff`]);
    }
    if (c.owner_fact_dependent) {
      const cap = c.owner_fact_max_units;
      const lo = units !== null ? units : umin;
      if (cap && lo !== null && lo > cap)
        checks.push([TRUE, `owner-based exception only possible at ≤${cap} units; building has ${units !== null ? "" : "≥"}${lo}`]);
      else checks.push([UNKNOWN, "depends on owner facts (identity, occupancy, holdings) that are not in the data"]);
    }
    if (c.subsidy_dependent) checks.push([UNKNOWN, "depends on subsidy status, which is not in the data"]);
    if (c.other_unknown_fact) checks.push([UNKNOWN, `depends on: ${c.other_unknown_fact}`]);
    if (!checks.length) return [TRUE, ["covers residential rentals in this jurisdiction"]];
    return and(checks);
  }

  function temporalStatus(rule, asOf) {
    const st = rule.status;
    if (st === "pending" || st === "failed") return st;
    const eff = parseDate(rule.effective_date);
    if (eff) return cmp(eff, asOf) <= 0 ? "in_force" : "not_yet_effective";
    return st;
  }

  function dateConflict(rule, asOf) {
    const ds = (rule.alt_effective_dates || []).map(d => parseDate(d.split(" ")[0]));
    if (!ds.length) return false;
    ds.sort(cmp);
    return cmp(ds[0], asOf) <= 0 && cmp(asOf, ds[ds.length - 1]) < 0;
  }

  function inJurisdiction(rule, a) {
    if (rule.level === "state") return rule.jurisdiction === a.state;
    return a.city !== null && rule.jurisdiction === `${a.city}, ${a.state}`;
  }

  const ORDER = { applies: 0, superseded: 1, unknown: 2, not_yet_effective: 3, pending: 4 };

  function lookup(a, rules, asOfStr) {
    const asOf = parseDate(asOfStr);
    const evaluated = new Map();
    for (const r of rules.filter(r => inJurisdiction(r, a))) {
      const ts = temporalStatus(r, asOf);
      if (ts === "failed") continue;
      const [cov, why] = coverage(r, a, asOf);
      if (cov === FALSE) continue;
      evaluated.set(r.team_rule_id, [r, ts, cov, why]);
    }
    const vals = [...evaluated.values()];
    const results = [];
    for (const [rid, [r, ts, cov, why]] of evaluated) {
      let conflict = dateConflict(r, asOf);
      const notes = [];
      let result;
      if (ts === "pending") { result = "pending"; notes.push("Proposed, not law. Shown so you can see what would change if it passed."); }
      else if (ts === "not_yet_effective") { result = "not_yet_effective"; notes.push(`Enacted; takes effect ${r.effective_date || "on a future date"}.`); }
      else result = cov === TRUE ? "applies" : "unknown";
      if (r.level === "state" && r.yields_to_local && (result === "applies" || result === "unknown")) {
        const locals = vals.filter(([l, lts]) => l.level === "city" && l.category === r.category && lts === "in_force");
        const covering = locals.find(([, , lcov]) => lcov === TRUE);
        if (covering) { result = "superseded"; notes.push(`${covering[0].title} (${covering[0].citation}) covers this building and governs instead.`); }
        else if (locals.length) { const l = locals[0][0]; result = "unknown"; notes.push(`Whether ${l.title} (${l.citation}) displaces this rule depends on facts not in the data.`); }
      }
      if (r.may_preempt_local && (ts === "in_force" || ts === "not_yet_effective")) {
        const loc = vals.filter(([l]) => l.level === "city" && l.category === r.category).map(([l]) => l);
        if (loc.length) {
          conflict = true;
          notes.push("Possible conflict with " + loc.map(l => `${l.title} (${l.citation})`).join(", ") + ". " + (r.conflict_note || "") + " Flagged for human review.");
        }
      }
      if (r.level === "city") {
        const pre = vals.filter(([s, sts]) => s.may_preempt_local && s.category === r.category && (sts === "in_force" || sts === "not_yet_effective")).map(([s]) => s);
        if (pre.length) {
          conflict = true;
          notes.push("A state law may preempt this ordinance: " + pre.map(s => `${s.title} (${s.citation}, effective ${s.effective_date || "date not stated"})`).join(", ") + ". Flagged for human review.");
        }
      }
      if (conflict && !r.may_preempt_local && dateConflict(r, asOf))
        notes.push("Sources disagree on the effective date around this query date: " + (r.alt_effective_dates || []).join(", ") + ". Flagged for human review.");
      let expl = why.join("; ") + (why.length ? "." : "");
      if (notes.length) expl += " " + notes.join(" ");
      results.push({ team_rule_id: rid, result, explanation: expl.trim(), conflict_flag: conflict });
    }
    results.sort((x, y) => ORDER[x.result] - ORDER[y.result] || (x.team_rule_id < y.team_rule_id ? -1 : 1));
    return results;
  }

  const api = { lookup, coverage, temporalStatus };
  if (typeof module !== "undefined") module.exports = api; else root.NavigatorEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
