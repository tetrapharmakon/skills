# Vocabulary clusters — template  →  `<corpus>/index/glossary.md`

A corpus worth searching this way usually spans several research communities that
use **disjoint words for the same idea**. Expanding a claim across the relevant
row before searching is what makes lexical search work at all; without it, a
search in one tradition's dialect is blind to the other three.

**This file is the skill's memory. Extend it whenever a search surfaces a phrasing
it lacks** — that is the single highest-value maintenance action in the whole
workflow, and it costs one line.

Rows feed straight into `find.py` as alternatives:

```bash
find.py "<idea in tradition A>" "<same idea in tradition B>" "<...in C>"
```

## The table

One row per *idea*, one column per *tradition* (the same tradition names the
corpus config declares, so the `tradition` column of `MANIFEST.tsv` routes to
the right column here). Use `—` where a tradition has no word for the idea —
that absence is itself information: it is where uncited priority hides.

| idea | tradition A | tradition B | tradition C |
|---|---|---|---|
| <the field's central condition> | <A's phrase, its abbreviation, its variants> | <B's phrase> | — |
| <the object under study> | | | |
| <the key construction> | | | |
| <the central obstruction or no-go> | | | |
| <the formal apparatus> | | | |

## Search notes

Record here anything that defeats a naive query on this corpus:

- notation the OCR mangles (e.g. a bracketed symbol that scans as `(~,~R)`) —
  and what to search instead;
- terms too short or too common to search alone;
- spelling splits (organisational/organizational, modelling/modeling) — both
  spellings need their own entry, since matching is literal after normalisation.
