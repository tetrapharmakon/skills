---
name: lit-claim-search
description: Check a claim against a full-text literature corpus — find who already said it, who said something weaker or stronger, and who contradicts it, with verbatim quotes, line numbers and citation keys. Use when the user gives a claim, sentence, theorem or paragraph and asks whether it is in the literature, whether it is novel, who to cite for it, or asks to add pointwise citations to a passage. Works on any subject; the corpus is found from a lit-corpus.json. Also covers building and refreshing the corpus index.
---

# Literature claim search

Answers one question: **for this claim, who in the corpus said it, said less, said
more, or said the opposite?**

Nothing here is subject-specific. Everything the tools know about *this* literature
lives in the corpus itself and must be read from there at the start of a search:

| file | what it is |
|---|---|
| `<corpus>/lit-corpus.json` | identity, layout, the traditions this corpus spans |
| `<corpus>/index/MANIFEST.tsv` | slug ⇄ bibkey ⇄ tradition ⇄ OCR quality ⇄ status |
| `<corpus>/index/CORPUS-MAP.md` | one routing block per source — the ranking fix |
| `<corpus>/index/glossary.md` | the dialects each tradition uses for one idea |
| `<corpus>/index/TRAPS.md` | filenames that lie, duplicate deposits, failed extractions |
| `<corpus>/index/<slug>.md` | per-source cards, written lazily (see Phase 1) |

To *add* sources rather than search them, use the **`lit-expand`** skill; to create a
corpus from a folder of PDFs or a `.bib`, use **`lit-corpus-init`**.

## Running the scripts

```bash
LT="${CLAUDE_PLUGIN_ROOT}"      # if unset, derive it: this file is at
                                # <plugin root>/skills/lit-claim-search/SKILL.md
S="$LT/skills/lit-claim-search/scripts"
```

Every script finds the corpus by walking up from the working directory to a
`lit-corpus.json` (or one in an immediate subdirectory). Override with `--corpus PATH`
or `$LIT_CORPUS`. Two corpora side by side is an error, never a guess — name one.

Refresh after texts change (`lit-expand` does this for you on ingest):

```bash
python3 $S/normalize.py
python3 $S/build_manifest.py
```

## find.py is the only acceptable search tool over a corpus

```bash
python3 $S/find.py "closure to efficient causation"
python3 $S/find.py -C3 "noncomputable" "non computable"      # OR over patterns
python3 $S/find.py -l -f Arbib "entailment"                  # counts only
```

Plain `grep` silently misses OCR'd scans, where a word can come out letter-spaced
(`a u t o m a t a`) or run together, and notation is mangled beyond recognition —
and those scans are usually the old papers a priority claim depends on. On one real
test query grep found 2 of 3 files and missed the only relevant one.

`find.py` matches against a whitespace- and punctuation-free mirror, so punctuation
and spacing in the query are ignored: `(M,R)-system` and `mr system` are the same
pattern, and a phrase broken across lines still matches. Consequences: short patterns
match inside longer words, and a pattern spanning more than 3 lines will not match.
Prefer distinctive phrases of a few words.

## Phase 1 — routing assets

Two artefacts, deliberately cheap. There is **no up-front full read of the corpus**:
summarising a million tokens against queries you have not seen yet compresses away
the one sentence that will matter, and once routing trusts a summary that miss is
invisible.

- `MANIFEST.tsv` and `CORPUS-MAP.md` (built from abstracts and section maps, not full
  text). The map exists to fix *ranking*, which is the actual weakness of lexical
  search: the right source is almost always in the hit list, buried under
  generic-word noise.
- `index/<slug>.md` — a full card per `references/card-template.md`, holding a claim
  inventory and a "does not prove" section. **Written lazily**: whenever a Phase 2
  deep read opens a source, write or extend its card from the reading you just did.
  Never build these speculatively. Over time the sources the work leans on acquire
  detailed cards and the rest cost nothing.

Rows with status `no-fulltext` are metadata-only stubs for papers known to be
relevant but not obtainable — **always report them as unsearched.**

## Phase 2 — searching a claim

**1. Decompose.** Restate the claim as its formal content, then list the phrasings
each tradition would use for it. This step is mandatory and does most of the work: in
a corpus worth searching this way, the communities rarely share a word.
`index/glossary.md` has the clusters — extend it whenever a search turns up a
phrasing it lacks.

**2. Route.** Read `CORPUS-MAP.md`, `TRAPS.md` and any existing `<slug>.md` cards, and
run `find.py` with the expanded vocabulary. Rank by the map, **not by hit count** — on
one real test query the corpus's foundational-but-irrelevant text scored 435 hits and
the single relevant source scored 1. Then add 2-3 **cold reads**: sources the map
shows are topically adjacent but whose dialect differs enough that no query of yours
would reach them. That is where uncited priority hides, and lexical search
structurally cannot find it.

**3. Fan out.** One reader per candidate source (typically 4–8, in a single parallel
batch). Give each: the claim, the decomposition from step 1, its one file, and the
output contract below. Each runs `find.py` restricted to its file (`-f`) for anchors,
then reads the surrounding argument — a lexical hit is a pointer, not evidence — and
writes or extends that source's `index/<slug>.md` card from what it read.

**4. Verify.** For every reported hit, re-run `find.py` on a distinctive fragment of
the quoted text to confirm it exists at the stated line. **Drop any hit that fails.**
Output here becomes citations in published work; an invented quote is the one
unrecoverable failure mode.

**5. Record.** Write `<corpus>/findings/<claim-slug>.md` — the claim, the
decomposition, the hit table, the sources searched with nothing found, and the
sources not searched.

## Output contract

Every hit is a *relation to the claim*, never a similarity score:

| verdict | meaning |
|---|---|
| `same` | priority citation — someone got there first |
| `weaker` | special case or extra hypotheses → cite as antecedent, say what you drop |
| `stronger` | ⚠️ the claim may be subsumed by existing work |
| `assumed` | asserted without proof → proving it is the contribution |
| `contradicts` | must be addressed in the text |
| `adjacent` | cite as context, not as priority |

Each hit: `bibkey` · `slug:Lstart-Lend` · verbatim quote · verdict · one line of
rationale. Then a paste-ready citation line, e.g.
`This is proved for the finite case in \cite[Thm.~2]{key}; we drop that hypothesis.`

Close with three explicit sections — they are as valuable as the hits:

- **Searched, nothing found** — per source. This is the evidence for a novelty claim.
- **Not in corpus** — anything in the bibliography with no `MANIFEST.tsv` row, plus
  rows marked `EXTRACTION-FAILED` or `no-fulltext`. Never let a null result imply
  coverage that does not exist.
- **Confidence** — lower it for `ocr-poor` sources: a missed hit there is likelier.

## Before trusting a filename, read the corpus's TRAPS.md

Every corpus accumulates them: two deposits of one paper under different titles,
a file whose name matches a famous paper it is not, an extraction that produced 2
bytes. `index/TRAPS.md` is where that knowledge lives, and it is the difference
between a citation and a retraction. Add to it whenever a search turns one up.

Note also that the `ocr%` column in the manifest overstates damage — it counts
single-letter tokens, so a mathematical text scores high while reading cleanly.
Trust it as a warning, not a verdict; keep using `find.py` regardless.
