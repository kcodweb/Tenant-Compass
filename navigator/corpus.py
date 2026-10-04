"""Corpus loading and verbatim-span verification."""
import csv
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "data" / "starter"
CORPUS = STARTER / "corpus"
EXTRA_CORPUS = ROOT / "data" / "extra_corpus"  # research captures and added docs (not supplied corpus)


@lru_cache(maxsize=None)
def manifest():
    """doc_id -> manifest row, for every document that has text (starter + extra)."""
    rows = {}
    for path in [CORPUS / "corpus_manifest.csv", EXTRA_CORPUS / "corpus_manifest.csv"]:
        if not path.exists():
            continue
        for r in csv.DictReader(open(path, encoding="utf-8")):
            base = CORPUS if path.parent == CORPUS else EXTRA_CORPUS
            r["_base"] = str(base)
            rows[r["doc_id"]] = r
    return rows


def supplied(doc_id):
    """True for documents whose text the organizers distributed (starter corpus/text). Pages we captured ourselves
    (data/extra_corpus) are research context only: v5 rules say they do not count as corpus citations."""
    r = manifest().get(doc_id)
    return bool(r) and r["_base"] == str(CORPUS)


def text_docs():
    return {d: r for d, r in manifest().items() if r.get("text_file") and r.get("status") == "ok"}


@lru_cache(maxsize=None)
def doc_text(doc_id):
    r = manifest()[doc_id]
    return (Path(r["_base"]) / r["text_file"]).read_text(encoding="utf-8")


def doc_header(doc_id):
    """(source_url, retrieved) from the SOURCE:/RETRIEVED: header lines."""
    t = doc_text(doc_id)
    url = re.search(r"^SOURCE:\s*(\S+)", t, re.M)
    ret = re.search(r"^RETRIEVED:\s*(.+)$", t, re.M)
    r = manifest()[doc_id]
    return (url.group(1) if url else r["url"]), (ret.group(1).strip() if ret else r.get("retrieved_at"))


_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " ", "–": "-", "—": "-"})


def _norm(s):
    return _WS.sub(" ", s.translate(_QUOTES)).strip()


def locate_span(doc_id, span):
    """Return the exact substring of the document matching `span`, or None.

    Exact match first; otherwise a whitespace/quote-insensitive match mapped back to the
    original characters, so the stored quoted_span is always verbatim source text.
    """
    text = doc_text(doc_id)
    if span and span in text:
        return span
    target = _norm(span or "")
    if len(target) < 20:
        return None
    # Build a normalized copy with an index map back to the original text.
    norm_chars, index = [], []
    prev_space = True
    for i, ch in enumerate(text.translate(_QUOTES)):
        if ch.isspace():
            if prev_space:
                continue
            norm_chars.append(" ")
            prev_space = True
        else:
            norm_chars.append(ch)
            prev_space = False
        index.append(i)
    norm = "".join(norm_chars)
    k = norm.find(target)
    if k < 0:
        return None
    start, end = index[k], index[k + len(target) - 1] + 1
    return text[start:end]
