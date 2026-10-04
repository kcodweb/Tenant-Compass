# Rental Housing Law Navigator · Method note

HackNation · Challenge 2 (RealPage) · Team **Tenant Compass** · Karan (sole member). **Not legal advice.** Every screen and
output says so.

**Question answered:** for each of the 500 sample addresses, which rules apply on a given date in the six categories, with
citation and exact source quote, and which addresses each supplied law change (T1–T5) affects.

## Pipeline

1. **Extract (Module A).** Claude (`claude-opus-5-5`) reads the 54 supplied documents with text, plus 22 link-only pages we
   saved as research context, using one prompt and a JSON schema. One record per rule, with the schema's fields and
   machine-checkable coverage: unit thresholds, certificate-of-occupancy cutoffs, rolling age exemptions, owner or subsidy
   facts. Nothing is hand-coded.
2. **Verify.** Every quoted span is matched word for word against its source. A failed quote gets one repair round, then is
   dropped and logged. The last full run dropped none.
3. **Consolidate.** Records of the same law merge by jurisdiction, category and citation (a code section joins its chapter).
   The most authoritative source wins; the rest are corroborating, and disagreeing dates are flagged. Citations come from
   supplied text wherever any supplied document covers the law. Five rules rest only on research captures (mainly the
   Hoboken, Jersey City and Santa Ana software bans) and are labeled and flagged. A state law a city page describes for that
   city only (Cal. Civ. Code § 1947.9, San Francisco) applies there only. A date that only starts a rate period or the
   latest amendment (SF's 3/1/26–2/28/27 increase) does not make the law itself "not yet effective". Result: 62 rules
   (54 in force, 1 not yet effective, 4 pending, 3 failed).
4. **Resolve (Module B).** Each address maps to its state and legal city (postal-city table; Census Geocoder when
   reachable). Missing unit counts are read from use codes (NJ MOD-IV classes, Boston and LA codes).
5. **Apply.** Each coverage test runs on the query date: `applies`, `unknown` (a fact is missing, or the year built equals a
   certificate cutoff year), `superseded`, `not_yet_effective`, `pending`. Possible state preemption flags both rules for
   review. The demo runs the same engine in the browser, kept identical by a parity test on 2,000 lookups.
6. **Changes (Module C).** Test ids map to rules by jurisdiction, category and any bill named in the test title; lookups
   rerun on each test's dates. `out/changes.json` lists affected addresses, conflict flags and before/after status.
7. **Explain.** A second model call rewrites each record in plain English and Spanish, using only the record. The demo
   labels it machine-written next to the citation and quote.

## Validation (our own; official scoring is by the judges)

`navigator/selfcheck.py`: rules the brief names 100%; T1–T5 address sets 100% (T3 conflict flags 90 of 90); the guide's
coverage spot checks 100%, plus a check that no California address outside San Francisco gets § 1947.9; 98% of "applies"
answers (3,804 of 3,894) quote supplied corpus text word for word. The other 90 are the Hoboken and Jersey City bans, which
T2 requires and only research pages describe.

## Responsible design

- Unknown, never a guess, when a fact is missing (owner, certificate-of-occupancy date, tenant facts).
- Enacted, not yet effective, pending and failed law stay separate on every screen; failed and pending law is never applied.
- Every answer shows source document, quote, retrieval date, as-of date and reasoning boundary, and whether the citation is
  supplied text or a research page. Addresses whose city code was link-only (Hoboken, Newark) say which sources were not read.
- The guide's open questions (Berkeley and LA dates, FAIR Act preemption, the CA fee cap) are surfaced and flagged.
- Public data only. Code-publisher sites whose terms are under review were not scraped.
- Reproducible: `audit/extraction_log.jsonl` logs model, prompt hash and tokens per document; `python -m navigator.run`
  rebuilds every output from cache and writes `out/run_manifest.json` with hashes of every input and output.

## Known limits

No owner names, so owner-based exceptions stay unknown for small buildings. Year built stands in for the
certificate-of-occupancy date. Jurisdiction uses the postal city when the Census Geocoder is unreachable. Hoboken and Newark
rent control are missing because their ordinances were link-only. The corpus has not been reviewed by counsel.
