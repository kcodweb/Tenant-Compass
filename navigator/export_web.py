"""Bundle everything the demo page needs into web/data.json."""
import datetime as dt
import json

from . import corpus, jurisdiction, plain

OUT = corpus.ROOT / "out"
WEB = corpus.ROOT / "web"


def main():
    rules_doc = json.loads((OUT / "rules.json").read_text())
    changes = json.loads((OUT / "changes.json").read_text()) if (OUT / "changes.json").exists() else {}
    audit = []
    log = corpus.ROOT / "audit" / "extraction_log.jsonl"
    if log.exists():
        audit = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    research = json.loads((OUT / "research_context.json").read_text())["rules"] \
        if (OUT / "research_context.json").exists() else []
    for r in rules_doc["rules"] + research:
        r["plain"] = plain.cached(r)
    extractors = sorted({r.get("extractor") or "?" for r in rules_doc["rules"]})
    data = {
        "meta": {
            "default_as_of": "2026-10-01",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "documents": len(corpus.text_docs()),
            "extractors": extractors,
        },
        "rules": rules_doc["rules"],
        "no_rule_findings": rules_doc.get("no_rule_findings", []),
        "research_rules": research,
        "addresses": jurisdiction.resolve_all(),
        "changes": changes,
        "selfcheck": json.loads((OUT / "selfcheck.json").read_text()) if (OUT / "selfcheck.json").exists() else None,
        "audit": audit[-200:],
        "sources": [{"doc_id": d, "url": corpus.doc_header(d)[0], "retrieved": corpus.doc_header(d)[1],
                     "jurisdictions": r["jurisdictions"], "source_type": r["source_type"],
                     "supplied": corpus.supplied(d)}
                    for d, r in sorted(corpus.text_docs().items())],
    }
    (WEB / "data.json").write_text(json.dumps(data, ensure_ascii=False))
    print(f"web/data.json: {len(data['rules'])} rules, {len(data['addresses'])} addresses")


if __name__ == "__main__":
    main()
