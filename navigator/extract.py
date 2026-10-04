"""Module A: automated rule extraction with Claude.

Each corpus document is sent to Claude with the prompt in extract_prompt.md and a JSON
schema (extract_schema.json) enforced through structured outputs. Every quoted span is
checked against the source text; records whose span is not verbatim get one repair
round-trip, then are dropped and logged. Raw outputs are cached per document in
cache/extractions/ and every call is appended to audit/extraction_log.jsonl.

Usage:
  export ANTHROPIC_API_KEY=...
  python -m navigator.extract                 # all documents without a cache file
  python -m navigator.extract --force D069    # re-extract specific documents
  python -m navigator.extract --doc-dir data/extra_corpus   # after adding a document
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from . import corpus

HERE = Path(__file__).resolve().parent
CACHE = corpus.ROOT / "cache" / "extractions"
AUDIT = corpus.ROOT / "audit" / "extraction_log.jsonl"
MODEL = "claude-opus-5-5"
AS_OF = "2026-10-01"


def load_schema():
    return json.loads((HERE / "extract_schema.json").read_text())


def build_prompt(doc_id, as_of=AS_OF):
    r = corpus.manifest()[doc_id]
    url, retrieved = corpus.doc_header(doc_id)
    tmpl = (HERE / "extract_prompt.md").read_text()
    return (tmpl.replace("{as_of}", as_of).replace("{doc_id}", doc_id)
            .replace("{jurisdictions}", r["jurisdictions"]).replace("{url}", url)
            .replace("{retrieved}", retrieved or "unknown").replace("{text}", corpus.doc_text(doc_id)))


def _call(client, messages, use_fallbacks=True):
    kwargs = dict(
        model=MODEL,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": load_schema()}},
        messages=messages,
    )
    if use_fallbacks:
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        with client.beta.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    else:
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {getattr(msg, 'stop_details', None)}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("output truncated at max_tokens")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text), msg


def extract_doc(client, doc_id, as_of=AS_OF, use_fallbacks=True):
    prompt = build_prompt(doc_id, as_of)
    messages = [{"role": "user", "content": prompt}]
    out, msg = _call(client, messages, use_fallbacks)
    bad = [i for i, r in enumerate(out["rules"]) if not corpus.locate_span(doc_id, r["quoted_span"])]
    repaired = False
    if bad:
        # One repair round: ask for verbatim spans for the failing records only.
        messages += [
            {"role": "assistant", "content": json.dumps(out)},
            {"role": "user", "content": (
                "These rule indexes have a quoted_span that is not a verbatim substring of the document: "
                f"{bad}. Return the full JSON again with those quoted_span values replaced by text copied "
                "exactly from the document. Change nothing else.")},
        ]
        out2, msg = _call(client, messages, use_fallbacks)
        if len(out2["rules"]) == len(out["rules"]):
            out, repaired = out2, True
    dropped = []
    kept = []
    for r in out["rules"]:
        exact = corpus.locate_span(doc_id, r["quoted_span"])
        if exact:
            r["quoted_span"] = exact
            kept.append(r)
        else:
            dropped.append(r)
    out["rules"] = kept
    out["no_rule_findings"] = [f for f in out["no_rule_findings"] if corpus.locate_span(doc_id, f["quoted_span"])]
    record = {
        "doc_id": doc_id,
        "extractor": MODEL,
        "served_by": getattr(msg, "model", MODEL),
        "as_of": as_of,
        "extracted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "repair_round": repaired,
        "dropped_unverifiable": dropped,
        "output": out,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{doc_id}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT, "a") as f:
        usage = getattr(msg, "usage", None)
        f.write(json.dumps({k: record[k] for k in ("doc_id", "extractor", "served_by", "as_of", "extracted_at",
                                                     "prompt_sha256", "repair_round")}
                           | {"rules": len(kept), "dropped": len(dropped),
                              "input_tokens": getattr(usage, "input_tokens", None),
                              "output_tokens": getattr(usage, "output_tokens", None)}) + "\n")
    return doc_id, len(kept), len(dropped)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_ids", nargs="*")
    ap.add_argument("--force", action="store_true", help="re-extract even if cached")
    ap.add_argument("--as-of", default=AS_OF)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-fallbacks", action="store_true")
    a = ap.parse_args(argv)
    import anthropic
    client = anthropic.Anthropic()
    ids = a.doc_ids or sorted(corpus.text_docs())
    todo = [d for d in ids if a.force or not (CACHE / f"{d}.json").exists()]
    print(f"extracting {len(todo)} of {len(ids)} documents with {MODEL}", file=sys.stderr)

    def doc_as_of(d):
        # A document added during the event (add_doc) may have been adopted after the corpus query date;
        # judge enacted vs pending as of today so it is not mislabeled pending. Dates are applied later.
        if corpus.manifest()[d].get("capture") == "added":
            return max(a.as_of, dt.date.today().isoformat())
        return a.as_of

    failed = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(extract_doc, client, d, doc_as_of(d), not a.no_fallbacks): d for d in todo}
        for fut in cf.as_completed(futs):
            try:
                d, n, nd = fut.result()
                print(f"  {d}: {n} rules ({nd} dropped: span not verbatim)", file=sys.stderr)
            except Exception as e:  # keep going; retried below
                failed[futs[fut]] = e
                print(f"  {futs[fut]}: FAILED {e}", file=sys.stderr)
    for d in sorted(failed):  # one sequential retry (rate limits, transient API errors)
        try:
            _, n, nd = extract_doc(client, d, doc_as_of(d), not a.no_fallbacks)
            print(f"  {d}: {n} rules on retry ({nd} dropped)", file=sys.stderr)
            del failed[d]
        except Exception as e:
            print(f"  {d}: FAILED again {e}", file=sys.stderr)
    if failed:
        sys.exit(f"{len(failed)} document(s) not extracted: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
