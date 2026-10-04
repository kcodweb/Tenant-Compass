"""Add a new law document (research context, e.g. a new jurisdiction) to the corpus without hand edits.

  python -m navigator.add_doc path/to/ordinance.txt --jurisdiction "Cambridge, MA" --url https://...
  (the path may also be a .pdf, an .html page, or an http(s) URL to fetch)
  python -m navigator.extract           # extracts only documents without a cache file
  python -m navigator.run --new-doc X01 # rebuild rules, lookups and changes, with a new_law test for it
"""
import argparse
import csv
import datetime as dt
import hashlib
import re
import subprocess
import sys
import urllib.request
from html import unescape
from pathlib import Path

from . import corpus

FIELDS = ["doc_id", "jurisdictions", "url", "source_type", "capture", "retrieved_at", "sha256", "text_file", "status"]


SCOPE = {"CA", "NJ", "MA", "Los Angeles, CA", "San Francisco, CA", "San Diego, CA", "Berkeley, CA", "Santa Ana, CA",
         "Jersey City, NJ", "Hoboken, NJ", "Newark, NJ", "Boston, MA", "Cambridge, MA"}


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    lines = (ln.strip() for ln in re.sub(r"[ \t\xa0]+", " ", text).splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def pdf_to_text(path):
    try:
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        from pypdf import PdfReader  # fallback when poppler is not installed
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


def read_source(src):
    """Plain text from a .txt/.md, .pdf or .html file, or from an http(s) URL."""
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "housing-law-navigator/1.0"})
        data = urllib.request.urlopen(req, timeout=60).read()
        if data[:5] == b"%PDF-":
            tmp = Path("/tmp/navigator_add_doc.pdf")
            tmp.write_bytes(data)
            return pdf_to_text(tmp)
        return html_to_text(data.decode("utf-8", "replace"))
    path = Path(src)
    if path.suffix.lower() == ".pdf":
        return pdf_to_text(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    return html_to_text(raw) if path.suffix.lower() in (".html", ".htm") or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")) else raw


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--jurisdiction", required=True, help="'Cambridge, MA' or a state code")
    p.add_argument("--url", default="")
    p.add_argument("--doc-id", default=None)
    a = p.parse_args(argv)
    extra = corpus.EXTRA_CORPUS
    (extra / "text").mkdir(parents=True, exist_ok=True)
    man = extra / "corpus_manifest.csv"
    rows = list(csv.DictReader(open(man))) if man.exists() else []
    doc_id = a.doc_id or f"X{len([r for r in rows if r['doc_id'].startswith('X')]) + 1:02d}"
    now = dt.datetime.now(dt.timezone.utc)
    if a.jurisdiction not in SCOPE:
        print(f"warning: '{a.jurisdiction}' is not one of the in-scope jurisdictions; no sample address will match it "
              f"unless it is spelled like {sorted(SCOPE)[:3]}...", file=sys.stderr)
    body = read_source(a.path)
    if len(body.split()) < 40:
        sys.exit(f"only {len(body.split())} words of text found in {a.path}; is it a scanned PDF or a script-rendered page?")
    if re.match(r"https?://", a.path) and not a.url:
        a.url = a.path
    if not body.startswith("SOURCE:"):
        body = f"SOURCE: {a.url or Path(a.path).name}\nRETRIEVED: {now:%Y-%m-%d %H:%M} UTC\n\n" + body
    dest = extra / "text" / f"{doc_id}.txt"
    dest.write_text(body, encoding="utf-8")
    rows = [r for r in rows if r["doc_id"] != doc_id] + [{
        "doc_id": doc_id, "jurisdictions": a.jurisdiction, "url": a.url or Path(a.path).name, "source_type": "official",
        "capture": "added", "retrieved_at": f"{now:%Y-%m-%dT%H:%MZ}", "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "text_file": f"text/{doc_id}.txt", "status": "ok"}]
    with open(man, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"added {doc_id} -> {dest} ({len(body.split())} words)")
    print(f"next: python -m navigator.extract && python -m navigator.run --new-doc {doc_id}")


if __name__ == "__main__":
    main()
