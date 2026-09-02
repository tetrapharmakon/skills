# Ingest checklist

`ingest.py` does the mechanical half. This is the half that needs judgement, and
it is the half that makes the new source *findable* — a paper in `texts/` with no
routing block is nearly invisible to `lit-claim-search`, which ranks by
`CORPUS-MAP.md` and explicitly not by hit count.

Do this per ingested paper, in order. `$C` is the corpus directory.

## 1. Check the extraction actually worked

```bash
head -40 $C/texts/<slug>.txt
grep -c '' $C/texts/<slug>.txt
awk -F'\t' '$1=="<slug>"' $C/index/MANIFEST.tsv
```

Look for: a title page (not a cover sheet or a "download this PDF" interstitial),
running text rather than one word per line, and no repeated journal furniture.
If the manifest says `EXTRACTION-FAILED`, or the text is a reference list only,
delete the file and re-register as a stub — a corrupt text is worse than a known
absence, because it reads as coverage.

Two-column scans sometimes extract better with `--layout` and sometimes far
worse. If the default is interleaved nonsense, retry with it.

## 2. Set the tradition honestly

The traditions are the ones `lit-corpus.json` declares for this corpus:

```bash
python3 -c "import json,sys;print(*json.load(open(sys.argv[1]))['traditions'],sep=' · ')" $C/lit-corpus.json
```

The tradition column is what makes cross-dialect routing work, so record where the
paper's *vocabulary* comes from, not what it is about. A paper applying one field's
machinery to another field's subject belongs to the tradition it borrows its words
from — that is what a reader searching in those words will find it by.

If the paper genuinely belongs to no declared tradition, that is a signal about the
corpus, not about the paper: consider adding a tradition to the config (and a column
to `index/glossary.md`) rather than forcing a bad label.

## 3. Write the CORPUS-MAP block

Append to `$C/index/CORPUS-MAP.md`, under the right heading, in exactly the
existing four-field shape:

```markdown
### <slug>
- **key**: <bibkey> · **tradition**: <t> · **ocr**: <status from MANIFEST>
- **What**: What it establishes and, as precisely as possible, what it does NOT.
  Name theorems by number. Say which hypotheses are load-bearing.
- **Dialect**: the terms THIS source uses for ideas your own work words differently.
  This is the field that matters most; it is what lets a claim be found in a
  tradition that phrases it another way.
- **Route here for**: the questions this source is the right answer to.
```

Write **Dialect** and **What** from the actual text — abstract plus a skim of the
section headings and theorem statements. Do not paraphrase the abstract alone: an
abstract states results, and routing needs vocabulary and scope limits.

## 4. Extend the glossary if the dialect is new

If the paper words a known idea in a way `$C/index/glossary.md` does not list, add
it to the right row, and add the discriminating phrases to `$C/index/topic-terms.txt`
with a weight. Those two files are the search's memory; a phrasing missing from them
is a claim that cannot be found.

## 5. Verify the bibliography entry

`ingest.py` appends a generated `@article` under an `UNVERIFIED` banner. Check the
author list, journal name and year against the paper's own title page, and fix the
entry type (`@book`, `@incollection`) if it guessed wrong. Generated entries are a
starting point, not a citation.

## 6. Record any trap you hit

If the filename lied, the deposit was a duplicate under a second DOI, or the title
page disagrees with the metadata — write it into `$C/index/TRAPS.md` now, in one
line. Every entry in that file exists because someone lost an hour to it twice.

## 7. Leave cards alone

Do **not** write `index/<slug>.md`. Cards are written lazily, only when a claim
search deep-reads a source. Building them speculatively is what the sibling skill
deliberately avoids: summarising against queries you have not seen compresses away
the one sentence that will matter.
