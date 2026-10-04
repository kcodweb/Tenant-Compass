"""Our own validation of the system's outputs.

The organizers' scoring script and dev answer key are judge materials and are not shared with participants
(v5 release), so this script checks what the v5 guide and README state publicly:

  citations   share of "applies" answers whose quoted span is found verbatim in supplied corpus text
              (pages we captured ourselves do not count, per the v5 rules)
  changes     overlap with the expected affected sets stated in dev/change_tests.json (T1-T5)
  extraction  presence/status/date of the rules the challenge brief names explicitly
  coverage    spot checks the participant guide spells out (cutoff years, missing facts, MA no cap)

It is our own validation, not the official score.
"""
import json
import re

from . import apply as ap
from . import corpus, jurisdiction

OUT = corpus.ROOT / "out"

# Rules named in the challenge brief (jurisdiction, category, citation regex, status on 2026-10-01, effective date).
BRIEF_RULES = [
    ("CA", "rent_increase_limits", r"1947\.12", "in_force", None),
    ("San Francisco, CA", "rent_increase_limits", r"ch(apter)?\.? ?37|37\.3|Rent Ordinance", "in_force", None),
    ("Los Angeles, CA", "rent_increase_limits", r"RSO|XV|151\.", "in_force", None),
    ("MA", "rent_increase_limits", r"40P", "in_force", None),
    ("CA", "just_cause_eviction", r"1946\.2", "in_force", None),
    ("NJ", "just_cause_eviction", r"2A:18-61\.1", "in_force", None),
    ("CA", "security_deposits", r"1950\.5", "in_force", "2024-07-01"),
    ("NJ", "security_deposits", r"46:8-21\.2", "in_force", None),
    ("MA", "security_deposits", r"186.*15B", "in_force", None),
    ("CA", "application_screening_fees", r"1950\.6", "in_force", None),
    ("NJ", "application_screening_fees", r"2025.*405|405|46:8-18", "in_force", "2026-05-01"),
    ("MA", "application_screening_fees", r"186.*15B", "in_force", None),
    ("MA", "application_screening_fees", r"87DDD", "in_force", "2025-08-01"),
    ("NJ", "screening_restrictions", r"2021.*110|46:8-52|Fair Chance", "in_force", None),
    ("CA", "screening_restrictions", r"12955|FEHA|SB 329", "in_force", None),
    ("CA", "algorithmic_rent_setting", r"AB 325|16729|SB 763", "in_force", "2026-01-01"),
    ("San Francisco, CA", "algorithmic_rent_setting", r"37\.10C", "in_force", "2024-10"),
    ("San Diego, CA", "algorithmic_rent_setting", r"98\.110", "in_force", "2025-06"),
    ("Berkeley, CA", "algorithmic_rent_setting", r"13\.63", "in_force", "2026"),
    ("Santa Ana, CA", "algorithmic_rent_setting", r"3090|Santa Ana", "in_force", "2026-04"),
    ("Jersey City, NJ", "algorithmic_rent_setting", r"218", "in_force", "2025-06"),
    ("Hoboken, NJ", "algorithmic_rent_setting", r"158", "in_force", "2025-07"),
    ("NJ", "algorithmic_rent_setting", r"2026.*43|FAIR", "not_yet_effective", "2027-07-01"),
    ("MA", "algorithmic_rent_setting", r"2983", "pending", None),
    ("MA", "algorithmic_rent_setting", r"5222", "pending", None),
]


def jaccard(a, b):
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def main():
    rules = ap.load_rules()
    byid = {r["team_rule_id"]: r for r in rules}
    lookups = json.loads((OUT / "lookups.json").read_text())["lookups"]
    changes = json.loads((OUT / "changes.json").read_text())
    addrs = {a["address_id"]: a for a in jurisdiction.resolve_all()}
    report = []

    # Extraction against the brief's named rules
    hits = 0
    report.append("EXTRACTION (rules named in the brief)")
    for jur, cat, pat, status, eff in BRIEF_RULES:
        cands = [r for r in rules if r["jurisdiction"] == jur and r["category"] == cat and re.search(pat, r["citation"], re.I)]
        if not cands:
            report.append(f"  MISSING  {jur:18} {cat:27} /{pat}/")
            continue
        r = cands[0]
        ok_status = r["status"] == status or ap.temporal_status(r, ap._date("2026-10-01")) == status
        ok_date = eff is None or (r.get("effective_date") or "").startswith(eff)
        hits += 0.5 + 0.25 * ok_status + 0.25 * ok_date
        flag = "ok" if ok_status and ok_date else "CHECK"
        report.append(f"  {flag:8} {jur:18} {cat:27} {r['team_rule_id']} {r['citation'][:40]} | {r['status']} eff {r.get('effective_date')}"
                      + ("" if ok_date else f" (brief: {eff})") + ("" if ok_status else f" (brief: {status})"))
    ext = hits / len(BRIEF_RULES)

    # Citations
    applies = [(aid, e) for aid, es in lookups.items() for e in es if e["result"] == "applies"]
    # v5: only quotes found in supplied corpus text count; quotes from our own research captures do not.
    def corpus_cited(rid):
        r = byid[rid]
        return corpus.supplied(r["source_doc_id"]) and bool(corpus.locate_span(r["source_doc_id"], r["quoted_span"]))
    cited = sum(1 for _, e in applies if corpus_cited(e["team_rule_id"]))
    research = sum(1 for _, e in applies if byid[e["team_rule_id"]].get("citation_basis") == "research_only")
    cit = cited / len(applies) if applies else 0
    report.append("CITATIONS (applies answers whose quote is found word for word in supplied corpus text)")
    report.append(f"  {cited}/{len(applies)} verified in supplied corpus; {research} rest on research pages outside it "
                  f"(rules: {', '.join(sorted({e['team_rule_id'] for _, e in applies if byid[e['team_rule_id']].get('citation_basis') == 'research_only'})) or 'none'})")

    # Change tests vs stated expectations
    st = lambda s: [a for a, v in addrs.items() if v["state"] == s]
    city = lambda c: [a for a, v in addrs.items() if v["city"] == c]
    expect = {"T1": (st("CA"), []), "T2": (city("Hoboken") + city("Jersey City"), []),
              "T3": (st("NJ"), city("Hoboken") + city("Jersey City")), "T4": (st("MA"), []), "T5": ([], [])}
    report.append("CHANGE TESTS (expected sets from change_tests.json)")
    ch_scores, ch_detail = [], {}
    for t, (aff, conf) in expect.items():
        got = changes.get(t, {})
        j = jaccard(got.get("affected_address_ids", []), aff)
        score = j if t != "T3" else 0.8 * j + 0.2 * jaccard(got.get("conflict_flag_address_ids", []), conf)
        ch_scores.append(score)
        ch_detail[t] = {"overlap": round(j, 3), "got": len(got.get("affected_address_ids", [])), "expected": len(aff)}
        report.append(f"  {t}: overlap {j:.2f} ({len(got.get('affected_address_ids', []))} vs {len(aff)} expected)"
                      + (f", conflict flags {len(got.get('conflict_flag_address_ids', []))} vs {len(conf)}" if t == "T3" else ""))
    chg = sum(ch_scores) / len(ch_scores)

    # Coverage spot checks from the participant guide
    report.append("COVERAGE SPOT CHECKS")
    checks = []

    def results_for(aid, jur, cat):
        return [e["result"] for e in lookups[aid] if byid[e["team_rule_id"]]["jurisdiction"] == jur
                and byid[e["team_rule_id"]]["category"] == cat]

    for aid, a in addrs.items():
        if a["city"] == "San Francisco" and a["year_built"] and a["year_built"] < 1979:
            checks.append(("SF pre-1979: SF rent ordinance applies", "applies" in results_for(aid, "San Francisco, CA", "rent_increase_limits")))
            checks.append(("SF pre-1979: state cap superseded", set(results_for(aid, "CA", "rent_increase_limits")) <= {"superseded"}))
        if a["city"] == "San Francisco" and a["year_built"] == 1979:
            checks.append(("SF built 1979: rent ordinance unknown", "unknown" in results_for(aid, "San Francisco, CA", "rent_increase_limits")))
        if a["city"] == "Los Angeles" and a["year_built"] and a["year_built"] < 1978:
            checks.append(("LA pre-1978: RSO applies", "applies" in results_for(aid, "Los Angeles, CA", "rent_increase_limits")))
        if a["city"] in ("San Diego", "Berkeley"):
            checks.append(("SD/Berkeley: CA rent cap not 'applies' (no year built)",
                           "applies" not in results_for(aid, "CA", "rent_increase_limits")))
        if a["state"] == "MA":
            caps = [e for e in lookups[aid] if byid[e["team_rule_id"]]["category"] == "rent_increase_limits"
                    and byid[e["team_rule_id"]]["level"] == "city" and e["result"] == "applies"]
            checks.append(("MA: no local rent cap reported", not caps))
        if a["state"] == "NJ":
            checks.append(("NJ: deposit cap applies", "applies" in results_for(aid, "NJ", "security_deposits")))
    agg = {}
    for name, ok in checks:
        agg.setdefault(name, [0, 0])
        agg[name][0] += ok
        agg[name][1] += 1
    for name, (ok, n) in agg.items():
        report.append(f"  {ok:4}/{n:<4} {name}")
    cov = sum(ok for ok, _ in agg.values()) / max(1, sum(n for _, n in agg.values()))

    report.insert(0, "SELF-CHECK (our own validation; the official scoring is done by the judges). Not legal advice.\n"
                  f"  extraction (brief rules) {ext:.0%} · citations in supplied corpus {cit:.0%} · change tests {chg:.0%} · coverage spot checks {cov:.0%}\n"
                  "")
    txt = "\n".join(report)
    (OUT / "selfcheck.txt").write_text(txt)
    (OUT / "selfcheck.json").write_text(json.dumps({
        "citations_detail": {"verified_in_supplied_corpus": cited, "applies_answers": len(applies), "research_only": research},
        "summary": {"extraction": ext, "citations": cit, "change_tests": chg, "coverage_spot_checks": cov},
        "change_tests": ch_detail,
        "coverage_checks": {name: {"ok": ok, "n": n} for name, (ok, n) in agg.items()}}, indent=1))
    print(txt)


if __name__ == "__main__":
    main()
