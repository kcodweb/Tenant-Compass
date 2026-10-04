"""One command to add a law document from outside the corpus (e.g. extending to a new jurisdiction): add it,
extract it, rerun everything.

  python -m navigator.new_doc ordinance.pdf --jurisdiction "Cambridge, MA" --url https://...

The added document is research context, not supplied corpus text, so its rules are labeled research-only.

Equivalent to add_doc + extract (only the new document) + run --new-doc, then prints what the new
document changes: its extracted rules and the affected sample addresses.
"""
import argparse
import json
import time

from . import add_doc, corpus, extract, run


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("path", help=".txt, .pdf, .html file or an http(s) URL")
    p.add_argument("--jurisdiction", required=True)
    p.add_argument("--url", default="")
    p.add_argument("--doc-id", default=None)
    a = p.parse_args(argv)
    t0 = time.time()
    before = set(corpus.text_docs())
    add_doc.main([a.path, "--jurisdiction", a.jurisdiction] + (["--url", a.url] if a.url else [])
                 + (["--doc-id", a.doc_id] if a.doc_id else []))
    corpus.manifest.cache_clear()
    corpus.doc_text.cache_clear()
    new = a.doc_id or sorted(set(corpus.text_docs()) - before)[-1]
    extract.main([new, "--force"])
    run.main(["--new-doc", new])
    ch = json.loads((corpus.ROOT / "out" / "changes.json").read_text())[f"NEW-{new}"]
    print(f"\n=== {new} ({a.jurisdiction}) processed in {time.time() - t0:.0f}s ===")
    for r in ch["mapped_rules"] or ["no in-scope rule extracted (see audit/extraction_log.jsonl)"]:
        print("  rule:", r)
    print(f"  {ch['notes']}")
    print("  open the demo (python -m http.server -d web 8000) and pick the 'Law changes' tab to see it")


if __name__ == "__main__":
    main()
