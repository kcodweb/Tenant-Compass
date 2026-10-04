# Rental Housing Law Navigator · Method note

HackNation · Challenge 2 (RealPage) · Team **Tenant Compass** · Karan (sole member). **Not legal advice.** Every screen and
output says so.

**Question answered:** for any of the 500 sample apartment addresses, which rules apply on a given date in six
categories (rent increase limits, just-cause eviction, security deposits, application and screening fees, screening
restrictions, algorithmic rent-setting), with the citation and the exact source quote, and which addresses each supplied law
change affects.

## Pipeline

1. **Extract (Module A).** The 54 supplied corpus documents with text are sent to Claude (`claude-opus-5-5`) with one prompt (`navigator/extract_prompt.md`) and a JSON
   schema, along with 22 link-only pages we saved from their public URLs as research context. One record per rule: category, jurisdiction, requirement, coverage conditions, exemptions, effective date, status,
   penalty, citation, quoted span. Coverage is also captured as machine-checkable fields: unit thresholds, certificate-of-
   occupancy cutoffs, rolling age exemptions, and whether owner or subsidy facts decide coverage. Nothing is hand-coded.
2. **Verify.** Every quoted span is matched word for word against the source text. A failed quote gets one repair round, then is
   dropped and logged. The last full run dropped none.
3. **Consolidate.** Duplicate records across documents merge by jurisdiction, category and citation. The most authoritative
   source is kept, the others are listed as corroborating, and disagreeing effective dates are flagged for review. Every
   citation comes from supplied corpus text where any supplied document covers the law. Six rules rest only on our research
   captures, mainly the Hoboken, Jersey City and Santa Ana software bans, whose official text is link-only in the manifest.
   They are labeled research-only and flagged for review; two more that duplicate supplied topics are left out. Result: 65
   rules (56 in force, 1 not yet effective, 5 pending, 3 failed) in `out/rules.json`.
4. **Resolve (Module B).** Each address is mapped to its state and legal city (postal-city table; Census Geocoder used when
   reachable). Year built and unit count come from the assessor row; where units are blank they are read from the use code
   (NJ MOD-IV class strings, Boston and LA use codes). A NJ class 4C parcel is 5+ units by definition, so a smaller count on
   one is treated as a partial description.
5. **Apply.** Each rule's coverage test runs on the query date. Results: `applies`, `unknown` (a needed fact is missing, or the
   year built equals a certificate-date cutoff year), `superseded` (a covering local rule governs), `not_yet_effective`,
   `pending`. State rules that may preempt local ones flag both for human review. `out/lookups.json` covers all 500 addresses.
6. **Changes (Module C).** Test ids map to our rules by jurisdiction and category, and lookups are rerun on each test's dates.
   `out/changes.json` lists affected addresses, conflict flags and the before/after status of each.
7. **Explain.** A second model call rewrites each rule record in plain English and Spanish for renters, using only the record.
   The demo labels it machine-written and shows it next to the citation and quote.

## Validation (our own; official scoring is done by the judges)

`navigator/selfcheck.py` checks what the v5 guide states publicly: rules the brief names 100%; T1–T5 expected address sets
100% (T3 conflict flags 90 of 90); the guide's coverage spot checks 100%; and 98% of "applies" answers (4,045 of 4,135) quote
supplied corpus text word for word. The other 90 are the Hoboken and Jersey City bans, which T2 requires and which only
research pages describe.

## Responsible design

- Unknown, never a guess, when a fact is missing (owner identity, certificate-of-occupancy date, tenant facts).
- Enacted, not yet effective, pending and failed law are kept separate on every screen.
- Every answer shows source document, quote, retrieval date, as-of date, extractor and a reasoning boundary, and says whether
  its citation is supplied corpus text or a research page.
- The open questions in the guide (Berkeley and LA dates, FAIR Act preemption, the CA fee cap) are surfaced and flagged.
- Public data only. Code-publisher sites whose terms are under review were not scraped.
- Reproducible: `audit/extraction_log.jsonl` records model, prompt hash, time and token counts per document; cached outputs
  rebuild identically with `python -m navigator.run`, which also writes `out/run_manifest.json` (hashes of every input,
  prompt, schema and output) so a second person can confirm they got the same result.
- Failed and pending changes are shown beside the rules that apply, marked as not law, never applied.

## Known limits

Owner names are not in the data, so owner-based exceptions stay unknown for small buildings. Year built is a proxy for the
certificate-of-occupancy date. Jurisdiction uses the postal city because the Census Geocoder was unreachable from our build
environment. The corpus has not been reviewed by counsel.
