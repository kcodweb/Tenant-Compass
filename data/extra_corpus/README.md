# Research captures (not supplied corpus)

Pages listed as link-only in `data/starter/corpus/links_only.csv`, saved once each from their public URLs with the retrieval
time in each file's header. Under the v5 participant rules these are research context: they do not count toward the
citation metric unless the organizers add them to the distributed corpus. `navigator/consolidate.py` prefers a supplied
corpus quote for every rule and labels rules that rest only on these pages `citation_basis: research_only`.
