# Submission video scripts

Three short videos for team Tenant Compass (Karan, solo). They show the system's own output and validation (the self-check and the T1–T5 results); the official
scoring script is a judge-only material and is not shown.
Bracketed lines are what to show; everything else is the voice-over.

---

## 1 · Team video (about 1 minute)

[Karan on camera, with "Tenant Compass · Karan" on screen.]

Hi, I'm Karan, and I'm team Tenant Compass. I built the Rental Housing Law Navigator for the RealPage challenge.

[Cut to the demo's address lookup with an address loaded.]

Renting in the US is regulated in layers: state law, city ordinances, and new laws with future start dates. Whether a rent cap
or an eviction protection covers your apartment depends on your exact address and the date. Renters, advocates and small
landlords rarely have a lawyer to work that out.

My system reads the law itself. An AI model turns the 54 supplied statutes, ordinances and agency pages into structured rules, checks
every quote word for word against the source text, and answers for any of 500 sample addresses: which rules apply today, with the
citation and the exact sentence it came from.

[Show the "Not legal advice" banner.]

It is not legal advice, and it says so everywhere. When a fact is missing, like who owns the building, it says Unknown instead of
guessing.

---

## 2 · Demo video (about 3 minutes)

[Open the live demo. Address lookup tab.]

This is the Navigator. I'll start with one of the example cases.

[Click "San Francisco, pre-1979".]

A 1926 building in San Francisco with 21 units. The jurisdiction stack is California, then San Francisco. Under rent increases,
the city's rent ordinance applies, and the statewide rent cap shows as superseded, because state law steps aside where local
rent control covers the unit.

[Open "Source text" on the SF rule.]

Every answer carries its source: the document, the exact quote, when it was retrieved, the as-of date, and whether a person
should review it.

[Click "Español".]

For renters there's a plain-language summary of each rule in English and Spanish, marked as machine-written next to the legal
source.

[Switch back. Click "San Diego, year built missing".]

Here the assessor record has no year built. The state cap exempts newer buildings, so the system can't know whether it applies. It says
Unknown and explain which fact is missing.

[Click "Hoboken". Then click the 7/2/2027 date chip.]

Hoboken bans algorithmic rent-setting software. New Jersey's FAIR Act is enacted but not yet in effect today. Move the date to
July 2027 and it applies, and both laws carry a conflict flag for human review, because the state law may preempt the city's.

[Open the "Law changes" tab. Scroll T1 to T5.]

These are the five supplied change cases. For each: what the brief expects, what the system found, how statuses moved, and whether the
affected set matches. California's AB 325: 250 addresses go from not yet effective to applies. The Massachusetts bills are
pending, not law. The rent-control ballot question was struck, so no Boston or Cambridge address shows a cap. All five match.

[Open "Sources & audit". Show the self-check panel and the extraction log.]

The audit tab shows my own validation, the open questions the guide lists (each flagged where the sources disagree), every
source with its retrieval date, and the extraction log: model, time and token count for each document, so anyone can
reproduce the result. Each source is marked as supplied corpus text or a research page. A few laws, like the Hoboken and Jersey
City software bans, exist only as link-only entries in the manifest, so those rules are labeled "Research source" and flagged
for review rather than presented as corpus citations.

---

## 3 · Technical video (about 3 minutes)

[Terminal and editor side by side. README visible.]

The pipeline has five steps, all in Python, with a static web page on top.

[Show navigator/extract_prompt.md and extract_schema.json.]

One: extraction. Each document goes to Claude Opus 5.5 with one prompt and a JSON schema. Besides the text fields, it fills
machine-checkable coverage: unit thresholds, certificate-of-occupancy cutoffs, rolling exemptions, and whether owner facts
decide coverage. No rule is hand-coded.

[Show corpus.locate_span.]

Every quoted span is checked word for word against the source. A failure gets one repair round, then it's dropped and logged.

[Show consolidate.py briefly.]

Two: consolidation merges duplicates across documents, keeps the most authoritative source and flags disagreeing dates.

[Show jurisdiction.py unit_range.]

Three: resolution. Unit counts come from the assessor row or are read from use codes like New Jersey's MOD-IV class strings.

[Show apply.py temporal_status and the coverage checks.]

Four: the engine tests each rule on the query date and returns applies, unknown, superseded, not yet effective or pending. The
browser runs a JavaScript port of the same engine, and a parity test checks they agree on all 2,000 lookups.

[Run: python -m navigator.run. Show the T1–T5 lines it prints, then out/selfcheck.txt.]

Five: change tracking reruns lookups on each test's dates. For each of T1 to T5 it prints the affected addresses and conflict
flags. Then my validation: every rule the brief names is found, all five change tests match their expected address sets,
the guide's coverage spot checks pass, and 98% of "applies" answers quote supplied corpus text word for word. The others rely on
research pages for laws whose official text isn't in the corpus, and I label those instead of hiding them.

[Show out/rules.json, out/lookups.json and out/changes.json briefly.]

These are the three submission files, rebuilt from the cached extractions with one command, so a judge can reproduce them.
