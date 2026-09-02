---
slug: <manifest slug, exact>
bibkey: <bibliography key, or "-" if none yet>
author: <Surname, Initials>
year: <YYYY>
tradition: <one of the traditions declared in lit-corpus.json>
ocr_quality: ok | fair | poor
status: ok | truncated | extraction-failed
---

## What it argues
Three to five sentences. The thesis, not the abstract.

## Claim inventory
Numbered, one line each, with a line number into `texts/<slug>.txt`. Record what the
source *stakes*, not what it mentions. 5-15 per source.

1. (L142) Every X with property P is a Y — proved in full generality.
2. (L310) ... proved only for finite A, B; the infinite case is raised and left open.

## Does not prove
What the source explicitly assumes, leaves open, or conjectures. This is where an
`assumed` verdict comes from, and it is the most useful section on the card.

## Idiolect
Terms this source uses for ideas your own text names differently. Feed these back
into `index/glossary.md` — that is how the next search finds this source.
`<their term>` = `<your term>` · ...

## Relation to the work in hand
Which section of your own text this bears on, if any.
