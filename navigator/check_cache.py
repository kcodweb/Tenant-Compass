"""Validate cached extraction files: schema shape and verbatim quoted spans.

Usage: python -m navigator.check_cache [D001 D003 ...]
"""
import json
import sys

from . import corpus
from .extract import CACHE, load_schema

try:
    import jsonschema
except ImportError:  # optional
    jsonschema = None


def check(doc_id):
    path = CACHE / f"{doc_id}.json"
    if not path.exists():
        return [f"{doc_id}: no cache file"]
    data = json.loads(path.read_text(encoding="utf-8"))
    out = data.get("output", {})
    problems = []
    if jsonschema:
        for e in jsonschema.Draft202012Validator(load_schema()).iter_errors(out):
            problems.append(f"{doc_id}: schema: {e.message} at {list(e.path)}")
    for i, r in enumerate(out.get("rules", [])):
        if not corpus.locate_span(doc_id, r.get("quoted_span", "")):
            problems.append(f"{doc_id}: rule {i} quoted_span not found verbatim: {r.get('quoted_span','')[:80]!r}")
    for i, f in enumerate(out.get("no_rule_findings", [])):
        if not corpus.locate_span(doc_id, f.get("quoted_span", "")):
            problems.append(f"{doc_id}: finding {i} quoted_span not found verbatim")
    return problems


if __name__ == "__main__":
    ids = sys.argv[1:] or sorted(p.stem for p in CACHE.glob("D*.json"))
    bad = [p for d in ids for p in check(d)]
    print("\n".join(bad) if bad else f"OK: {len(ids)} file(s) valid")
    sys.exit(1 if bad else 0)
