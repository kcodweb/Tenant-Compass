"""Renter-facing plain-language summaries of each rule, in English and Spanish (stretch goal).

  python -m navigator.plain        # summarizes rules that have no cached summary (needs ANTHROPIC_API_KEY)

Each summary is written from the rule record only (requirement, key value, coverage, exemptions, citation),
never from outside knowledge, and is cached in cache/plain/ by a hash of those fields, so an unchanged rule is
never re-sent. export_web attaches the summaries to the rules; the demo labels them machine-written.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import sys

from . import corpus
from .extract import MODEL

CACHE = corpus.ROOT / "cache" / "plain"
FIELDS = ("jurisdiction", "category", "status", "effective_date", "title", "requirement", "key_value",
          "coverage_conditions", "exemptions", "citation")
SCHEMA = {
    "type": "object",
    "properties": {"en": {"type": "string"}, "es": {"type": "string"}},
    "required": ["en", "es"],
    "additionalProperties": False,
}
PROMPT = """Rewrite this housing-law rule record as a short plain-language note for a renter.

Rules:
- English ("en"): at most 45 words, 8th-grade reading level, second person ("you", "your landlord").
- Spanish ("es"): the same note in clear, neutral Latin American Spanish, not a word-for-word calque.
- Use ONLY facts in the record. Do not add numbers, dates, exceptions or advice that the record does not state.
- Lead with what the rule does for the renter (the cap, the protection, the ban). Mention the most important
  limit on who is covered if the record states one.
- If status is pending or failed, say plainly that it is not law.
- No legal advice, no "you should", no greetings.

Record:
{record}
"""


def key(rule):
    return hashlib.sha256(json.dumps({f: rule.get(f) for f in FIELDS}, sort_keys=True).encode()).hexdigest()[:16]


def cached(rule):
    p = CACHE / f"{key(rule)}.json"
    return json.loads(p.read_text()) if p.exists() else None


def summarize(client, rule):
    record = json.dumps({f: rule.get(f) for f in FIELDS}, ensure_ascii=False, indent=1)
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT.format(record=record)}])
    out = json.loads(next(b.text for b in msg.content if b.type == "text"))
    out["model"] = getattr(msg, "model", MODEL)
    (CACHE / f"{key(rule)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return rule["team_rule_id"]


def main(argv=None):
    rules = json.loads((corpus.ROOT / "out" / "rules.json").read_text())["rules"]
    todo = [r for r in rules if not cached(r)]
    if not todo:
        print("plain-language summaries: all cached")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"plain-language summaries: {len(todo)} rules missing, skipped (no ANTHROPIC_API_KEY)", file=sys.stderr)
        return
    import anthropic
    client = anthropic.Anthropic()
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"plain-language summaries for {len(todo)} rules with {MODEL}", file=sys.stderr)
    with cf.ThreadPoolExecutor(8) as ex:
        for fut in cf.as_completed([ex.submit(summarize, client, r) for r in todo]):
            try:
                fut.result()
            except Exception as e:  # a missing summary only hides the plain-language box for that rule
                print(f"  summary failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
