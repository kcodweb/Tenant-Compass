# Rental Housing Law Navigator

HackNation 7th Global AI Hackathon · Challenge 2 (RealPage) · Team Tenant Compass (Karan, sole member). For any sample apartment address: which housing rules apply on a
given date, with citations and exact source quotes, and which addresses a law change affects.

**Live demo: https://kcodweb.github.io/Tenant-Compass/** (guided tour: https://kcodweb.github.io/Tenant-Compass/#tour)

**Not legal advice.** Every interface says so.

## Results

From `out/selfcheck.txt`, our own validation (official scoring is done by the judges):

| Check | Result |
|---|---|
| Rules the challenge brief names, found by extraction | 25 of 25 |
| T1–T5 change tests, affected address sets | 5 of 5 exact (T3 conflict flags 90 of 90) |
| "Applies" answers whose quote is found word for word in supplied corpus text | 3,804 of 3,894 (98%); the other 90 are the Hoboken and Jersey City bans, which only research pages describe |
| Participant guide coverage spot checks | 100%, including no SF-only rule at California addresses outside San Francisco |
| Browser engine vs Python engine | 2,000 of 2,000 lookups identical |

Output: 62 rules (54 in force, 1 not yet effective, 4 pending, 3 failed) and answers for all 500 sample addresses.

## How it works

| Module | Code | What it does |
|---|---|---|
| A · Extract | `navigator/extract.py`, `extract_prompt.md`, `extract_schema.json` | Sends each corpus document to Claude (`claude-opus-5-5`, structured JSON output). One record per rule: category, jurisdiction, status, effective date, key value, machine-checkable coverage (unit thresholds, certificate-of-occupancy cutoffs, rolling age exemptions, owner/subsidy facts), citation and quoted span. Every quoted span is checked word for word against the source; failures get one repair round, then are dropped and logged. Cached per document in `cache/extractions/`, logged to `audit/extraction_log.jsonl`. |
| A · Consolidate | `navigator/consolidate.py` | Merges duplicates across documents by (jurisdiction, category, citation), keeps the most authoritative source, records corroborating sources, flags disagreeing dates. A city code section joins the record citing its whole chapter (S.F. Admin. Code § 37.3 into ch. 37). A state rule whose title or coverage names exactly one in-scope city (Cal. Civ. Code § 1947.9, San Francisco only) gets `applies_only_in` and is applied in that city only. Citations come from supplied corpus text: when the best record is from a page we captured ourselves, a supplied document of the same law is cited instead. A rule described only by our own captures is labeled `citation_basis: research_only`, flagged for review, and submitted only when a T1–T5 test names it or the supplied text has no rule for its jurisdiction and category; otherwise it goes to `out/research_context.json`. Writes `out/rules.json`. |
| B · Resolve | `navigator/jurisdiction.py` | Census Geocoder (Incorporated Places) when reachable, cached in `cache/geocode.json`; otherwise a postal-city table (Dorchester → Boston, Van Nuys → Los Angeles). Unit counts are read from the assessor row or, when blank, from the use code (NJ MOD-IV class strings like `3S-F-D-6U`, Boston `A5 Apartment 5 to 14 Units`). Flags bad ZIPs. |
| B · Apply | `navigator/apply.py` (and `web/engine.js`, a port kept identical by `tests/parity.mjs`) | Tests each rule on a query date: `applies`, `unknown` (a needed fact is missing, or the year built equals a certificate-date cutoff year), `superseded` (a covering local rule governs), `not_yet_effective`, `pending`. Flags possible state preemption of local rules. When a rule's date only starts its current rate period or latest amendment (SF's 3/1/26–2/28/27 increase, an indexed relocation amount), consolidation sets `effective_date_basis: current_version` and the rule stays in force before that date, with a note. Writes `out/lookups.json`. |
| C · Changes | `navigator/changes.py` | Maps answer-key ids like `HOB-ALG-01` to our rules by jurisdiction and category, reruns lookups on the test dates, writes `out/changes.json`. `--new-doc` reports what an added document changes. |
| Self-check | `navigator/selfcheck.py` | Our own validation (the scoring script and dev key are judge materials, not shared with participants in v5): rules the brief names, expected T1–T5 sets, quotes verified in supplied corpus text only, and the guide's coverage spot checks. Writes `out/selfcheck.txt` and `out/selfcheck.json`. |
| Plain language | `navigator/plain.py` | Renter-facing summary of each rule in English and Spanish, written by a second model call from the rule record only, cached in `cache/plain/`. Shown in the demo as machine-written, next to the citation. |
| Demo | `web/` | Static page, no build step. Address search and "as of" date; an at-a-glance tile per category; a timeline of when each rule took effect at the address; rules by category with status chips, explanation, quote, source link and audit details; a notice when the address's city code was link-only and not read; English and Spanish; law-change tests; sources, self-check and extraction log. |

## Run it

```bash
pip install anthropic jsonschema
export ANTHROPIC_API_KEY=...            # needed only for extraction
python -m navigator.extract             # extracts documents that have no cache file (add --force to redo)
python -m navigator.jurisdiction        # optional: fills the geocode cache from the Census Geocoder
python -m navigator.run                 # rules.json, lookups.json, changes.json, selfcheck.txt, web/data.json
python -m http.server -d web 8000       # open http://localhost:8000
```

Works on Windows, macOS and Linux (all files are read and written as UTF-8). Without an API key, `navigator.run` rebuilds
everything from the cached extractions and summaries.

Check that the browser engine matches the Python one (needs Node):

```bash
python tests/dump_py.py > py.json && node tests/parity.mjs py.json
```

### Adding a document from outside the corpus (optional)

```bash
python -m navigator.new_doc ordinance.pdf --jurisdiction "Cambridge, MA" --url <source url>
```

Accepts a .txt, .pdf or .html file or an http(s) URL; adds it, extracts only it, rebuilds every output and reports which
addresses change (`NEW-<doc_id>` in changes.json). Useful for extending to a new jurisdiction. Added documents are research
context, not supplied corpus text, so their rules are labeled research-only. The v5 event has no surprise document: change
tracking is evaluated on T1–T5 only.

## Submission

- Live demo: https://kcodweb.github.io/Tenant-Compass/ (the `web/` folder on GitHub Pages; also runs locally, see above).
  To redeploy after `python -m navigator.run`: `git subtree split --prefix web -b gh-pages` then `git push -f origin gh-pages`.
- `out/rules.json`, `out/lookups.json`, `out/changes.json`: the three required files.
- `submission/method_note.md`: one-page method note.

## Data

- `data/starter/`: the organizers' v5 participant pack (87-document manifest, 54 with text, 500 addresses, schema, T1–T5). Byte-identical to `MIT-hackathon-PARTICIPANT-PACK-CLEAN-NO-HOUR16.zip`.
- `data/extra_corpus/`: research context only. Public pages the starter pack lists as link-only (law-firm and news articles,
  Justia statute mirrors), captured once each with URL and retrieval time. Under the v5 rules they do not count as corpus
  citations; the pipeline labels any rule that rests on them. Code-publisher pages (ecode360, American Legal, gocodebook) were not
  captured because the starter pack marks their terms as under review.

## Known limits

- Extraction: every cached record was produced through the API (`extractor: claude-opus-5-5`, full `--force` run on 2026-10-03). Earlier hand-run "bootstrap" records are gone.
- Owner names are not in the data, so owner-based exceptions are `unknown` unless the building is too large for them.
- Year built is not the certificate-of-occupancy date: a building in a cutoff year is `unknown`.
- Sources the manifest lists as link-only code-publisher pages (Hoboken D032–D034, Newark D070–D072, LA D038, San Diego D074–D075) were not read, so Hoboken and Newark rent control are missing. The demo says so on each affected address.

## License

Code and outputs: [MIT](LICENSE). The source texts in `data/starter/` (the organizers' participant pack) and
`data/extra_corpus/` (public pages captured with their URLs) remain under their original owners' terms.
