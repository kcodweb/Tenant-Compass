"""Merge per-document extractions into one deduplicated rule set (rules.json).

The same law is often described by several documents (statute text, a city FAQ, a rent
board page). Records are grouped by (jurisdiction, category, citation key); within a group
the record from the most authoritative source wins (official statute/ordinance text over
an agency page, higher model confidence), and the others are kept as corroborating sources.
Conflicting effective dates or statuses inside a group raise a conflict flag for review.
"""
import json
import re
from pathlib import Path

from . import corpus
from .extract import CACHE

OUT = corpus.ROOT / "out"
STATE_NAMES = {"california": "CA", "new jersey": "NJ", "massachusetts": "MA", "ca": "CA", "nj": "NJ", "ma": "MA"}
CITY_ALIASES = {"city and county of san francisco": "San Francisco", "city of los angeles": "Los Angeles"}


def norm_jurisdiction(j, level):
    j = (j or "").strip()
    low = j.lower().replace("state of ", "")
    if level == "state" or low in STATE_NAMES:
        return STATE_NAMES.get(low, j.upper()[:2])
    m = re.match(r"(?:city of\s+)?([^,]+),\s*([A-Za-z .]+)$", j, re.I)
    city, st = (m.group(1), m.group(2)) if m else (j, "")
    city = CITY_ALIASES.get(city.lower().strip(), city.strip().title())
    st = STATE_NAMES.get(st.lower().strip(), st.strip().upper())
    return f"{city}, {st}"


_SECTION = re.compile(r"\d+[A-Za-z]?(?:[.:\-]\d+[A-Za-z½]*)+|\d{2,}[A-Za-z½]*")


def citation_key(cite):
    """Coarse key for 'same law': code family + first section number.

    'Cal. Civ. Code § 1947.12(d)' -> 'civ:1947.12'; 'S.F. Admin. Code ch. 37' -> 'admin:37'.
    """
    c = cite.lower().replace("section", "§").replace("sec.", "§")
    m = re.search(r"p\.\s?l\.\s?(\d{4}),?\s*c(?:h)?\.\s?(\d+)", c)
    if m:  # a session-law chapter identifies one act, however the code sections are cited
        return f"pl:{m.group(1)}-{m.group(2)}"
    fam = "gen"
    for k, pat in [("civ", r"civ"), ("gov", r"gov"), ("admin", r"admin"), ("lamc", r"l\.?a\.?m\.?c|los angeles mun"),
                   ("bmc", r"berkeley|b\.m\.c"), ("sdmc", r"san diego|s\.d\.m\.c"), ("gl", r"g\.?\s?l\.|general laws|m\.g\.l"),
                   ("njsa", r"n\.j\.s\.a"), ("pl", r"p\.l\."), ("bill", r"\b(?:ab|sb|s|h)\.?\s?\d"),
                   ("ord", r"ord")]:
        if re.search(pat, c):
            fam = k
            break
    nums = _SECTION.findall(c)
    # "98.1101-98.1104" -> "98.1101" (a section range), but keep NJ-style "2A:18-61.1"
    nums = [n.split("-")[0] if "." in n.split("-")[0] else n for n in nums]
    if fam == "bill":
        nums = re.findall(r"\b((?:ab|sb|s|h)\.?\s?\d+)", c)
        nums = [n.replace(".", "").replace(" ", "") for n in nums]
    return f"{fam}:{nums[0] if nums else re.sub(r'[^a-z0-9]', '', c)[:30]}"


def source_rank(doc_id):
    r = corpus.manifest()[doc_id]
    url = r["url"].lower()
    official_text = any(s in url for s in ("leginfo.legislature", "malegislature.gov/laws", "malegislature.gov/bills",
                                           "pub.njleg", "municode", "ordinance", "cityclerk", "docs.sandiego.gov"))
    return (2 if official_text else 1 if r["source_type"].startswith("official") else 0)


def load_records():
    recs = []
    for p in sorted(CACHE.glob("*.json")):
        d = json.loads(p.read_text())
        doc_id = d["doc_id"]
        url, retrieved = corpus.doc_header(doc_id)
        for i, r in enumerate(d["output"]["rules"]):
            r = dict(r)
            r["jurisdiction"] = norm_jurisdiction(r["jurisdiction"], r["level"])
            r["level"] = "state" if len(r["jurisdiction"]) == 2 else "city"
            r["source_doc_id"], r["source_url"], r["retrieved_at"] = doc_id, url, retrieved
            r["extractor"] = d.get("extractor")
            ck = citation_key(r["citation"])
            if r["level"] == "city":  # one city's code: the section number alone identifies the law
                ck = "city:" + ck.split(":", 1)[1]
            r["_key"] = (r["jurisdiction"], r["category"], ck)
            r["_rank"] = (source_rank(doc_id), r.get("confidence") or 0)
            recs.append(r)
    return recs


def consolidate(recs):
    groups = {}
    for r in recs:
        groups.setdefault(r["_key"], []).append(r)
    # Second pass: a record whose citation has no section number (a page title, "Jersey City ordinance")
    # joins the only numbered group for the same jurisdiction and category, if there is exactly one.
    def coded(k):  # does any record in the group cite a code section or numbered ordinance?
        return any(re.search(r"§|\bch\.|\bchapter\b|\bcode\b|\bno\.|\bc\.\s?\d|\bord\.", g["citation"], re.I)
                   for g in groups[k])
    enacted = lambda k: {g["status"] in ("in_force", "not_yet_effective") for g in groups[k]}
    for key in [k for k in groups if not coded(k)]:
        same = [k for k in groups if k[:2] == key[:2] and k != key and coded(k) and enacted(k) == enacted(key)]
        if len(same) == 1:
            groups[same[0]] += groups.pop(key)
    # Third pass: a group backed only by secondary sources (news, law-firm notes) joins the one group
    # for the same jurisdiction and category that has an official source, if there is exactly one.
    official = lambda k: any(source_rank(g["source_doc_id"]) > 0 for g in groups[k])
    for key in [k for k in groups if not official(k)]:
        same = [k for k in groups if k[:2] == key[:2] and k != key and official(k) and enacted(k) == enacted(key)]
        if len(same) > 1:  # pick the official group whose section number the secondary source also cites
            cites = " ".join(g["citation"].lower() for g in groups[key])
            same = [k for k in same if k[2].split(":", 1)[1] in cites]
        if len(same) == 1:
            groups[same[0]] += groups.pop(key)
    # Fourth pass: a pending/failed-looking record about a proposal joins the one enacted law for the
    # same jurisdiction and category when the proposal is that law before its final vote (the enacted
    # record wins on status and date, the pending source stays as corroboration).
    for key in [k for k in groups if not any(enacted(k))]:
        if any(g["status"] == "failed" for g in groups[key]):
            continue
        same = [k for k in groups if k[:2] == key[:2] and k != key and all(enacted(k))]
        if len(key[0]) > 2 and len(same) == 1:  # city level only
            groups[same[0]] += groups.pop(key)
    rules = []
    for key, grp in groups.items():
        grp.sort(key=lambda r: r["_rank"], reverse=True)
        # A document showing a bill as pending cannot prove it was never enacted; when another
        # source reports the law as enacted, prefer the enacted record (status and date).
        enacted = [g for g in grp if g["status"] in ("in_force", "not_yet_effective")]
        if enacted and any(g["status"] == "pending" for g in grp):
            grp = enacted + [g for g in grp if g not in enacted]
        best = dict(grp[0])
        # A page about one program often omits its coverage test (e.g. an annual-increase notice that
        # doesn't restate the construction cutoff). Fill missing coverage fields from other sources of
        # the same law so the engine doesn't treat the rule as covering everything.
        cov = dict(best["coverage"])
        for g in grp[1:]:
            for k, v in g["coverage"].items():
                if cov.get(k) in (None, False) and v not in (None, False):
                    cov[k] = v
        best["coverage"] = cov
        # A state rule that yields to stricter local rules does not also preempt them.
        if best.get("yields_to_local") and best.get("may_preempt_local"):
            best["may_preempt_local"] = False
        dates ={g["effective_date"] for g in grp if g.get("effective_date")}
        statuses = {g["status"] for g in grp}
        notes = [best["conflict_note"]] if best.get("conflict_note") else []
        if len(dates) > 1:
            notes.append("Sources give different effective dates: " + "; ".join(
                f"{g['effective_date']} ({g['source_doc_id']})" for g in grp if g.get("effective_date")))
        if len(statuses) > 1:
            notes.append("Sources disagree on status: " + ", ".join(sorted(statuses)))
        if not best.get("effective_date") and dates:
            best["effective_date"] = sorted(dates)[0]
        best["conflict_note"] = " ".join(notes) or None
        best["conflict_flag"] = bool(notes) or bool(best.get("may_preempt_local"))
        # Only disagreement across *different* documents counts as a date conflict.
        by_doc = {}
        for g in grp:
            if g.get("effective_date") and g["status"] in ("in_force", "not_yet_effective"):
                by_doc.setdefault(g["effective_date"], set()).add(g["source_doc_id"])
        docs_per_date = [ds for ds in by_doc.values()]
        best["alt_effective_dates"] = sorted(f"{d} ({', '.join(sorted(s))})" for d, s in by_doc.items()) \
            if len(by_doc) > 1 and len(set().union(*docs_per_date)) > 1 else []
        # Citations must come from supplied corpus text (v5 rules). When the best record is from a page we captured
        # ourselves, cite a supplied document of the same law instead; with none, label the rule research-only.
        primary = grp[0]
        if not corpus.supplied(primary["source_doc_id"]):
            sup = [g for g in grp if corpus.supplied(g["source_doc_id"])]
            if sup:
                primary = sup[0]
                for k in ("source_doc_id", "source_url", "quoted_span", "retrieved_at"):
                    best[k] = primary[k]
                notes.append(f"Status and date also rely on research page {grp[0]['source_doc_id']}, which is outside "
                             f"the supplied corpus; the citation quote is from supplied document {primary['source_doc_id']}.")
                best["citation_basis"] = "supplied_corpus"
            else:
                notes.append("Only research pages outside the supplied corpus describe this rule, so its quote is not a "
                             "corpus citation. Verify against the official text before relying on it.")
                best["citation_basis"] = "research_only"
                best["confidence"] = min(best.get("confidence") or 0.6, 0.6)
        else:
            best["citation_basis"] = "supplied_corpus"
        if best.get("effective_date") and best["citation_basis"] == "supplied_corpus" \
                and not any(g.get("effective_date") == best["effective_date"] and corpus.supplied(g["source_doc_id"])
                            for g in grp):
            notes.append(f"The effective date {best['effective_date']} is stated only by research pages.")
        best["conflict_note"] = " ".join(notes) or None
        best["conflict_flag"] = bool(notes) or bool(best.get("may_preempt_local"))
        best["corroborating_sources"] = [
            {"source_doc_id": g["source_doc_id"], "source_url": g["source_url"], "citation": g["citation"],
             "quoted_span": g["quoted_span"], "in_supplied_corpus": corpus.supplied(g["source_doc_id"])}
            for g in grp if g is not primary]
        rules.append(best)
    order = {"state": 0, "city": 1}
    rules.sort(key=lambda r: (r["jurisdiction"][-2:], order[r["level"]], r["jurisdiction"], r["category"], r["citation"]))
    final = []
    for i, r in enumerate(rules, 1):
        r = {k: v for k, v in r.items() if not k.startswith("_")}
        rec = {
            "team_rule_id": f"r-{i:04d}",
            "jurisdiction": r["jurisdiction"], "level": r["level"], "category": r["category"], "status": r["status"],
            "title": r["title"], "requirement": r["requirement"], "key_value": r.get("key_value"),
            "coverage_conditions": r.get("coverage_conditions"), "exemptions": r.get("exemptions"),
            "overrides": [], "interaction": r.get("interaction"), "effective_date": r.get("effective_date"),
            "citation": r["citation"], "source_doc_id": r["source_doc_id"], "source_url": r["source_url"],
            "quoted_span": r["quoted_span"], "confidence": r.get("confidence"),
            "conflict_flag": r["conflict_flag"], "conflict_note": r["conflict_note"],
            # extensions used by the coverage engine and UI
            "coverage": r["coverage"], "yields_to_local": r.get("yields_to_local", False),
            "may_preempt_local": r.get("may_preempt_local", False), "penalty": r.get("penalty"),
            "retrieved_at": r["retrieved_at"], "extractor": r.get("extractor"),
            "citation_basis": r["citation_basis"],
            "corroborating_sources": r["corroborating_sources"],
            "alt_effective_dates": r["alt_effective_dates"],
        }
        final.append(rec)
    link_overrides(final)
    return final


def link_overrides(rules):
    """Fill `overrides` with the ids of rules this one yields to or may preempt."""
    for s in rules:
        if s["level"] != "state" or not (s["yields_to_local"] or s["may_preempt_local"]):
            continue
        for c in rules:
            if c["level"] == "city" and c["jurisdiction"].endswith(s["jurisdiction"]) and c["category"] == s["category"] \
                    and c["status"] in ("in_force", "not_yet_effective"):
                s["overrides"].append(c["team_rule_id"])
                c["overrides"].append(s["team_rule_id"])
        if s["yields_to_local"] and s["overrides"]:
            s["interaction"] = (s["interaction"] or "") + (" " if s["interaction"] else "") + \
                "Yields where a covering local rule of the same category applies: " + ", ".join(s["overrides"]) + "."


def no_rule_findings():
    out = []
    for p in sorted(CACHE.glob("*.json")):
        d = json.loads(p.read_text())
        for f in d["output"].get("no_rule_findings", []):
            out.append(dict(f, source_doc_id=d["doc_id"], source_url=corpus.doc_header(d["doc_id"])[0]))
    return out


def split_research(rules):
    """(submitted, research_context). A rule described only by research pages outside the supplied corpus is
    submitted (flagged for review) only when a change test (T1-T5) names it or when the supplied text has no rule at all
    for its jurisdiction and category (e.g. the Hoboken, Jersey City and Santa Ana software bans, whose official text
    is link-only in the manifest). Otherwise it stays out of rules.json and lookups.json and is shown in the demo as
    research context."""
    from . import changes
    tested = {r["team_rule_id"] for t in changes.load_tests() for kid in t.get("rule_ids", [])
              for r in changes.map_key_id(kid, rules)}
    covered = {(r["jurisdiction"], r["category"]) for r in rules if r["citation_basis"] == "supplied_corpus"}
    keep = lambda r: (r["citation_basis"] == "supplied_corpus" or r["team_rule_id"] in tested
                      or (r["jurisdiction"], r["category"]) not in covered)
    return [r for r in rules if keep(r)], [r for r in rules if not keep(r)]


def main():
    rules, research = split_research(consolidate(load_records()))
    OUT.mkdir(exist_ok=True)
    (OUT / "rules.json").write_text(json.dumps({"rules": rules, "no_rule_findings": no_rule_findings()},
                                               indent=1, ensure_ascii=False))
    (OUT / "research_context.json").write_text(json.dumps({"rules": research}, indent=1, ensure_ascii=False))
    print(f"{len(rules)} rules -> out/rules.json; {len(research)} research-only rules -> out/research_context.json")
    return rules


if __name__ == "__main__":
    main()
