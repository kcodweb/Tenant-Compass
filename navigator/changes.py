"""Module C: change tracking.

Each test names answer-key rule ids such as "CA-ALG-01" or "MA-RENT-P1". We map a key id
to our own rules by jurisdiction + category (+ pending/failed for P-suffixed ids), so the
same code handles any new test without hand edits. For each test we compute lookups on
the relevant dates and report the affected addresses and conflict flags.

  as_of     affected = addresses whose result for the mapped rules differs between the two dates
  boundary  affected = addresses where any mapped rule applies on the date
  pending   affected = addresses that would be covered if the pending bills were enacted
  negative  affected = addresses where the mapped rule would be reported as in force (should be empty)
  new_law   affected = addresses whose rule set changes when a newly added document's rules are
            included (navigator.new_doc adds a document to data/extra_corpus/, extracts it and
            runs with --new-doc <doc_id>)
"""
import argparse
import json
import re

from . import apply as ap
from . import corpus, jurisdiction

STARTER_TESTS = corpus.STARTER / "dev" / "change_tests.json"
EXTRA_TESTS = corpus.ROOT / "data" / "extra_tests.json"
OUT = corpus.ROOT / "out"

JUR = {"CA": "CA", "NJ": "NJ", "MA": "MA", "LA": "Los Angeles, CA", "SF": "San Francisco, CA", "SD": "San Diego, CA",
       "BER": "Berkeley, CA", "BRK": "Berkeley, CA", "SA": "Santa Ana, CA", "JC": "Jersey City, NJ",
       "HOB": "Hoboken, NJ", "NWK": "Newark, NJ", "NEW": "Newark, NJ", "BOS": "Boston, MA", "CAM": "Cambridge, MA"}
CAT = {"ALG": "algorithmic_rent_setting", "RENT": "rent_increase_limits", "RC": "rent_increase_limits",
       "JC": "just_cause_eviction", "EVIC": "just_cause_eviction", "DEP": "security_deposits",
       "FEE": "application_screening_fees", "SCR": "screening_restrictions", "SCRN": "screening_restrictions"}


def map_key_id(key_id, rules):
    """Our rules that correspond to an answer-key id like 'HOB-ALG-01' or 'MA-ALG-P1'."""
    parts = key_id.split("-")
    jur, cat, num = JUR.get(parts[0]), CAT.get(parts[1]), parts[2] if len(parts) > 2 else ""
    proposed = num.startswith("P")
    out = [r for r in rules if r["jurisdiction"] == jur and r["category"] == cat
           and ((r["status"] in ("pending", "failed")) == proposed)]
    return out


_BILL = re.compile(r"\b(AB|SB|S|H)\.?\s?(\d{2,5})\b")


def mapped_rules(t, rules):
    """Our rules for a test. When the test title names bills ("S.2983 and H.5222") and some mapped rules cite them,
    only those count: another pending bill on the same subject (MA H.1564) is not part of the test."""
    mapped = list({r["team_rule_id"]: r for kid in t.get("rule_ids", []) for r in map_key_id(kid, rules)}.values())
    bills = {(a.upper(), n) for a, n in _BILL.findall(t.get("title") or "")}
    named = [r for r in mapped if {(a.upper(), n) for a, n in _BILL.findall(r["citation"])} & bills]
    return named or mapped


def _results(lookups, ids):
    return {aid: {e["team_rule_id"]: e for e in entries if e["team_rule_id"] in ids}
            for aid, entries in lookups.items()}


def run_test(t, rules, addresses, cache):
    def look(as_of, rs=rules):
        k = (as_of, id(rs))
        if k not in cache:
            cache[k] = ap.run(as_of, rs, addresses)["lookups"]
        return cache[k]

    mapped = mapped_rules(t, rules)
    ids = {r["team_rule_id"] for r in mapped}
    res = {"title": t.get("title"), "mapped_rules": [f"{r['team_rule_id']} {r['citation']} ({r['jurisdiction']}, "
                                                    f"{r['status']}, eff. {r.get('effective_date')})" for r in mapped]}
    typ = t["type"]
    res.update(type=typ, expected_behavior=t.get("expected_behavior"),
               dates=[d for d in (t.get("as_of_before"), t.get("as_of_after"), t.get("as_of")) if d])
    if typ == "as_of":
        before, after = _results(look(t["as_of_before"]), ids), _results(look(t["as_of_after"]), ids)
        affected, conflicts, detail = [], [], {}
        for aid in after:
            b = {k: v["result"] for k, v in before[aid].items()}
            a = {k: v["result"] for k, v in after[aid].items()}
            if a != b:
                affected.append(aid)
                detail[aid] = {"before": b, "after": a}
            if any(v["conflict_flag"] for v in list(after[aid].values()) + list(before[aid].values())):
                conflicts.append(aid)
        res.update(affected_address_ids=sorted(affected), conflict_flag_address_ids=sorted(conflicts),
                   before_after=detail,
                   notes=f"Result of {', '.join(sorted(ids)) or 'no mapped rule'} changes between "
                         f"{t['as_of_before']} and {t['as_of_after']} at {len(affected)} addresses.")
    elif typ in ("boundary", "pending", "negative"):
        cur = _results(look(t.get("as_of", ap.DEFAULT_AS_OF)), ids)
        want = {"boundary": {"applies", "unknown"}, "pending": {"pending"}, "negative": {"applies", "unknown"}}[typ]
        affected = sorted(aid for aid, rs in cur.items() if any(v["result"] in want for v in rs.values()))
        conflicts = sorted(aid for aid, rs in cur.items() if any(v["conflict_flag"] for v in rs.values()))
        if typ == "negative":
            failed = [r for r in mapped if r["status"] == "failed"]
            note = ("Recorded as failed: " + "; ".join(f"{r['title']} ({r['citation']})" for r in failed) + ". "
                    if failed else "No enacted rule found in the corpus. ")
            note += f"{len(affected)} addresses would show it in force (expected 0)."
        elif typ == "pending":
            note = f"Pending, not in force. {len(affected)} addresses would be affected if enacted."
        else:
            by_city = {}
            for aid in affected:
                for v in cur[aid].values():
                    by_city.setdefault(v["team_rule_id"], set()).add(aid)
            note = "; ".join(f"{rid}: {len(s)} addresses" for rid, s in sorted(by_city.items()))
        res.update(affected_address_ids=affected, conflict_flag_address_ids=conflicts, notes=note)
    elif typ == "new_law":
        new_ids = {r["team_rule_id"] for r in rules if r["source_doc_id"] == t["doc_id"]
                   or any(c["source_doc_id"] == t["doc_id"] for c in r.get("corroborating_sources", []))}
        without = [r for r in rules if r["team_rule_id"] not in new_ids]
        as_of = t.get("as_of", ap.DEFAULT_AS_OF)
        w, wo = look(as_of), look(as_of, without)
        affected, detail = [], {}
        for aid in w:
            a = {e["team_rule_id"]: e["result"] for e in w[aid]}
            b = {e["team_rule_id"]: e["result"] for e in wo[aid]}
            if a != b:
                affected.append(aid)
                detail[aid] = {"before": b, "after": a}
        new = [r for r in rules if r["team_rule_id"] in new_ids]
        conflicts = sorted(aid for aid in w if any(e["conflict_flag"] for e in w[aid] if e["team_rule_id"] in new_ids))
        res.update(affected_address_ids=sorted(affected), conflict_flag_address_ids=conflicts, before_after=detail,
                   mapped_rules=[f"{r['team_rule_id']} {r['citation']} ({r['status']}, eff. {r.get('effective_date')})"
                                 for r in new],
                   notes=f"{len(new)} rule(s) extracted from {t['doc_id']}; {len(affected)} addresses affected"
                         f"{f', {len(conflicts)} flagged for review' if conflicts else ''}.")
    if res.get("before_after"):  # e.g. {"not_yet_effective -> applies": 250}
        trans = {}
        for d in res["before_after"].values():
            for rid in sorted(set(d["before"]) | set(d["after"])):
                b, a = d["before"].get(rid, "not listed"), d["after"].get(rid, "not listed")
                if b != a:
                    trans[f"{b} -> {a}"] = trans.get(f"{b} -> {a}", 0) + 1
        res["transitions"] = trans
    return res


def load_tests():
    tests = json.loads(STARTER_TESTS.read_text(encoding="utf-8"))
    if EXTRA_TESTS.exists():
        tests += json.loads(EXTRA_TESTS.read_text(encoding="utf-8"))
    return tests


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--new-doc", action="append", default=[], help="doc_id of a newly added law (adds a new_law test)")
    a = p.parse_args(argv)
    rules = ap.load_rules()
    addresses = jurisdiction.resolve_all()
    tests = load_tests() + [{"test_id": f"NEW-{d}", "type": "new_law", "doc_id": d, "title": f"New document {d}"}
                            for d in a.new_doc]
    cache, out = {}, {}
    for t in tests:
        out[t["test_id"]] = run_test(t, rules, addresses, cache)
        r = out[t["test_id"]]
        print(f"{t['test_id']}: {len(r['affected_address_ids'])} affected, "
              f"{len(r['conflict_flag_address_ids'])} conflict flags | {r['notes']}")
    (OUT / "changes.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    main()
