"""Module B, part 2: test every rule's coverage against an address on a query date.

Results follow the participant guide:
  applies            in force on the query date and covers this address
  unknown            coverage turns on a fact the data does not contain
  superseded         covered, but a stricter local rule of the same category governs
  not_yet_effective  enacted, effective date after the query date
  pending            a bill or proposal, not law
Rules that do not cover the address (other jurisdiction, failed proposals, building
outside the coverage test) are left out. When a fact is missing the engine answers
"unknown" rather than guessing, because missing an applicable rule costs the most.
"""
import datetime as dt
import json

from . import corpus, jurisdiction

OUT = corpus.ROOT / "out"
DEFAULT_AS_OF = "2026-10-01"
TRUE, FALSE, UNKNOWN = True, False, None


def _date(s):
    if not s:
        return None
    parts = [int(p) for p in s.split("-")]
    while len(parts) < 3:
        parts.append(1)
    return dt.date(*parts)


def _and(results):
    vals = [r for r, _ in results]
    if FALSE in vals:
        return FALSE, [why for r, why in results if r is FALSE]
    if UNKNOWN in vals:
        return UNKNOWN, [why for r, why in results if r is UNKNOWN]
    return TRUE, [why for r, why in results]


def coverage(rule, a, as_of):
    """(True/False/None, reasons) for the rule's building-level coverage test."""
    c = rule.get("coverage") or {}
    checks = []
    units, umin, umax = a["units"], a["units_min"], a["units_max"]
    if c.get("min_units"):
        n = c["min_units"]
        if units is not None:
            checks.append((units >= n, f"{units} units {'≥' if units >= n else '<'} {n}"))
        elif umin is not None and umin >= n:
            checks.append((TRUE, f"use code implies ≥{umin} units (≥{n} needed)"))
        elif umax is not None and umax < n:
            checks.append((FALSE, f"use code implies ≤{umax} units (<{n})"))
        else:
            checks.append((UNKNOWN, f"unit count not in the data (rule needs ≥{n})"))
    if c.get("max_units"):
        n = c["max_units"]
        if units is not None:
            checks.append((units <= n, f"{units} units {'≤' if units <= n else '>'} {n}"))
        elif umin is not None and umin > n:
            checks.append((FALSE, f"use code implies ≥{umin} units (>{n})"))
        elif umax is not None and umax <= n:
            checks.append((TRUE, f"use code implies ≤{umax} units"))
        else:
            checks.append((UNKNOWN, f"unit count not in the data (rule covers ≤{n})"))
    yb = a["year_built"]
    for field, before in (("co_on_or_before", True), ("co_after", False)):
        d = _date(c.get(field))
        if not d:
            continue
        label = f"certificate of occupancy {'on or before' if before else 'after'} {d.isoformat()}"
        if yb is None:
            checks.append((UNKNOWN, f"year built not in the data ({label} needed)"))
        elif yb == d.year:
            checks.append((UNKNOWN, f"built in {yb}, the cutoff year; year built ≠ certificate date ({label} needed)"))
        else:
            ok = (yb < d.year) if before else (yb > d.year)
            checks.append((ok, f"built {yb}; {label} {'met' if ok else 'not met'}"))
    if c.get("exempt_if_newer_than_years"):
        n = c["exempt_if_newer_than_years"]
        cutoff = as_of.year - n
        if yb is None:
            checks.append((UNKNOWN, f"year built not in the data (buildings under {n} years old are exempt)"))
        elif yb < cutoff:
            checks.append((TRUE, f"built {yb}, more than {n} years before {as_of.isoformat()}"))
        elif yb > cutoff:
            checks.append((FALSE, f"built {yb}, less than {n} years old (exempt)"))
        else:
            checks.append((UNKNOWN, f"built {yb}, exactly at the {n}-year rolling cutoff"))
    if c.get("owner_fact_dependent"):
        cap = c.get("owner_fact_max_units")
        lo = units if units is not None else umin
        if cap and lo is not None and lo > cap:
            checks.append((TRUE, f"owner-based exception only possible at ≤{cap} units; building has {'' if units is not None else '≥'}{lo}"))
        else:
            checks.append((UNKNOWN, "depends on owner facts (identity, occupancy, holdings) that are not in the data"))
    if c.get("subsidy_dependent"):
        checks.append((UNKNOWN, "depends on subsidy status, which is not in the data"))
    if c.get("other_unknown_fact"):
        checks.append((UNKNOWN, f"depends on: {c['other_unknown_fact']}"))
    if not checks:
        return TRUE, ["covers residential rentals in this jurisdiction"]
    return _and(checks)


def temporal_status(rule, as_of):
    """Status of the rule on as_of: in_force / not_yet_effective / pending / failed."""
    st = rule["status"]
    if st in ("pending", "failed"):
        return st
    eff = _date(rule.get("effective_date"))
    if eff:
        return "in_force" if eff <= as_of else "not_yet_effective"
    return st


def _date_conflict(rule, as_of):
    """True when sources give effective dates on both sides of the query date."""
    ds = [_date(d.split(" ")[0]) for d in rule.get("alt_effective_dates", [])]
    return bool(ds) and min(ds) <= as_of < max(ds)


def in_jurisdiction(rule, a):
    if rule["level"] == "state":
        return rule["jurisdiction"] == a["state"]
    return a["city"] is not None and rule["jurisdiction"] == f"{a['city']}, {a['state']}"


def lookup(a, rules, as_of):
    as_of = _date(as_of) if isinstance(as_of, str) else as_of
    mine = [r for r in rules if in_jurisdiction(r, a)]
    evaluated = {}
    for r in mine:
        ts = temporal_status(r, as_of)
        if ts == "failed":
            continue
        cov, why = coverage(r, a, as_of)
        if cov is FALSE:
            continue
        evaluated[r["team_rule_id"]] = (r, ts, cov, why)
    results = []
    for rid, (r, ts, cov, why) in evaluated.items():
        conflict = _date_conflict(r, as_of)
        notes = []
        if ts == "pending":
            result = "pending"
            notes.append("Proposed, not law. Shown so you can see what would change if it passed.")
        elif ts == "not_yet_effective":
            result = "not_yet_effective"
            notes.append(f"Enacted; takes effect {r.get('effective_date') or 'on a future date'}.")
        else:
            result = "applies" if cov is TRUE else "unknown"
        # State rule that yields to a covering local rule of the same category.
        if r["level"] == "state" and r.get("yields_to_local") and result in ("applies", "unknown"):
            locals_ = [(l, lts, lcov) for l, lts, lcov, _ in evaluated.values()
                       if l["level"] == "city" and l["category"] == r["category"] and lts == "in_force"]
            if any(lcov is TRUE for _, _, lcov in locals_):
                l = next(l for l, _, lcov in locals_ if lcov is TRUE)
                result = "superseded"
                notes.append(f"{l['title']} ({l['citation']}) covers this building and governs instead.")
            elif locals_:
                l = locals_[0][0]
                result = "unknown"
                notes.append(f"Whether {l['title']} ({l['citation']}) displaces this rule depends on facts not in the data.")
        # State rule that may preempt local rules on the same subject: flag both for review.
        if r.get("may_preempt_local") and ts in ("in_force", "not_yet_effective"):
            loc = [l for l, lts, _, _ in evaluated.values() if l["level"] == "city" and l["category"] == r["category"]]
            if loc:
                conflict = True
                notes.append("Possible conflict with " + ", ".join(f"{l['title']} ({l['citation']})" for l in loc)
                             + ". " + (r.get("conflict_note") or "") + " Flagged for human review.")
        if r["level"] == "city":
            pre = [s for s, sts, _, _ in evaluated.values() if s.get("may_preempt_local")
                   and s["category"] == r["category"] and sts in ("in_force", "not_yet_effective")]
            if pre:
                conflict = True
                notes.append("A state law may preempt this ordinance: " + ", ".join(
                    f"{s['title']} ({s['citation']}, effective {s.get('effective_date') or 'date not stated'})" for s in pre)
                    + ". Flagged for human review.")
        if conflict and not r.get("may_preempt_local") and _date_conflict(r, as_of):
            notes.append("Sources disagree on the effective date around this query date: "
                         + ", ".join(r.get("alt_effective_dates", [])) + ". Flagged for human review.")
        expl = "; ".join(why) + ("." if why else "")
        if notes:
            expl += " " + " ".join(notes)
        results.append({"team_rule_id": rid, "result": result, "explanation": expl.strip(), "conflict_flag": conflict})
    order = {"applies": 0, "superseded": 1, "unknown": 2, "not_yet_effective": 3, "pending": 4}
    results.sort(key=lambda x: (order[x["result"]], x["team_rule_id"]))
    return results


def load_rules():
    return json.loads((OUT / "rules.json").read_text())["rules"]


def run(as_of=DEFAULT_AS_OF, rules=None, addresses=None):
    rules = rules if rules is not None else load_rules()
    addresses = addresses if addresses is not None else jurisdiction.resolve_all()
    return {"as_of": as_of, "lookups": {a["address_id"]: lookup(a, rules, as_of) for a in addresses}}


def main(as_of=DEFAULT_AS_OF):
    res = run(as_of)
    (OUT / "lookups.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"lookups for {len(res['lookups'])} addresses as of {as_of} -> out/lookups.json")
    return res


if __name__ == "__main__":
    import sys
    main(*(sys.argv[1:2] or [DEFAULT_AS_OF]))
