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
python3 $S/find.py -l -f Arbib "entailment"                  # per-file counts + hits/kL
python3 $S/find.py --index -C1 "covering map"                # also the routing assets
```

`--index` searches `CORPUS-MAP.md`, `glossary.md`, `TRAPS.md` and the cards with the
same folding as the texts, so routing can be a query — probe the map's Dialect fields
for each phrasing in your decomposition — instead of a read of the whole map.

Two things make raw counts lie and `find.py` corrects both: lines that repeat through
a file (running heads, journal banners) are not anchors unless you pass
`--keep-repeats`, and `-l` prints hits per thousand lines next to the count and sorts
by it, because a 14,000-line book outscores an 800-line paper on any common word.
Compare sources by that density, never by the raw count.

Plain `grep` silently misses OCR'd scans, where a word can come out letter-spaced
(`a u t o m a t a`) or run together, and notation is mangled beyond recognition —
and those scans are usually the old papers a priority claim depends on. On one real
test query grep found 2 of 3 files and missed the only relevant one.

`find.py` matches against a mirror that folds ligatures and accents (`ﬁxed` → `fixed`,
`Möbius` → `mobius`) and then drops all whitespace and punctuation, so typography,
punctuation and spacing in the query are ignored: `(M,R)-system` and `mr system` are
the same pattern, and a phrase broken across lines still matches. Consequences: short
patterns match inside longer words, and a pattern spanning more than 3 lines will not
match. Prefer distinctive phrases of a few words. The mirror is stamped with the
normaliser version; if `find.py` warns that it is stale, run `normalize.py` before
trusting any result.

OCR that replaced a glyph outright is handled per corpus: one scan prints every `fi`
ligature as `®`, another as `ÿ`. List the pairs under `normalize.substitutions` in
`lit-corpus.json` (`{"®": "fi", "ÿ": "fi"}`) and re-run `normalize.py`. They apply to
the mirror of every text, so only list characters that never occur legitimately in
this corpus. Add one the moment a search turns up a word the scan mangled.

## Phase 1 — routing assets

Two artefacts, deliberately cheap. There is **no up-front full read of the corpus**:
summarising a million tokens against queries you have not seen yet compresses away
the one sentence that will matter, and once routing trusts a summary that miss is
invisible.

- `MANIFEST.tsv` and `CORPUS-MAP.md` (built from abstracts and section maps, not full
  text). The map exists to fix *ranking*, which is the actual weakness of lexical
  search: the right source is almost always in the hit list, buried under
  generic-word noise. Keep a routing block to routing — what to route here for, its
  dialect, what it does *not* prove — a paragraph, not a theorem inventory. Every
  search reads the whole map before it does anything, so a block that is a full summary
  taxes every future search with its length and duplicates the card; one corpus's map
  reached 30 KB for seven sources, some 12k tokens per search before a subagent ran.
- `index/<slug>.md` — a full card per `references/card-template.md`, holding a claim
  inventory and a "does not prove" section. **Written lazily**: whenever a Phase 2
  deep read opens a source, write or extend its card from the reading you just did.
  Never build these speculatively. Over time the sources the work leans on acquire
  detailed cards and the rest cost nothing. A card records only what was read at a
  line number the card cites; when a verified quote and a card line disagree, the
  quote wins and the card is corrected on the spot. One corpus's card for its main
  monograph stated a morphism's direction backwards in two places out of three,
  against the verified quote on the same page, and nothing had checked it.

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

**3. Fan out — and never read the texts yourself.** One subagent per candidate source
(typically 4–8, in a single parallel batch), each spawned with an explicitly **cheap
model** (`model: "haiku"`). The binding constraint on this work is not capability, it is
the context window and the token budget: a single deep read of an OCR'd paper can cost
more context than the whole answer it feeds, and a filled window degrades the session
exactly when the synthesis matters. The orchestrator reads only the routing assets and
the `find.py` hit lists.

Give each subagent: the claim, the decomposition from step 1, its **one** file, and the
extraction contract: for every passage that bears on the claim, the verbatim quote
with `slug:Lstart-Lend`, one or two sentences of the surrounding argument (what is
assumed, what is proved, for which case), and the source's own words for the ideas in
the decomposition. Each runs `find.py` restricted to its file (`-f`) for anchors, then
reads the surrounding argument — a lexical hit is a pointer, not evidence. Each also
writes or extends that source's `index/<slug>.md` card from what it read, so the
reading survives the subagent's context.

**Subagents extract; the orchestrator judges.** A verdict — `same`, `weaker`,
`stronger`, `assumed`, `contradicts` — is a mathematical judgement about hypotheses
and subsumption, and it needs the whole decomposition and every source's quotes in
view at once. A cheap model is the right tool for finding and copying passages
faithfully; it is the wrong tool for deciding whether a theorem subsumes yours. Assign
the verdicts yourself, from the returned quotes, after step 4 has verified them.

**4. Record.** Write `<corpus>/findings/<claim-slug>.md` — the claim, the
decomposition, the hit table, the sources searched with nothing found, and the
sources not searched. Keep the hit table in the shape of the output contract below,
with the location cell as `slug:Lstart-Lend`; that is what the next step reads.

**5. Verify — mechanically, not by assertion.** Output here becomes citations in
published work; an invented quote is the one unrecoverable failure mode, and a
model's own claim to have re-checked its quotes is not a check.

```bash
python3 $S/verify.py findings/<claim-slug>.md
```

Every quote in every table row with a location is split into fragments and matched,
after the same normalisation the mirror uses, inside the stated line range. A fragment
found elsewhere in the file is a wrong line number: fix the range. A fragment found
nowhere is not verbatim: **re-quote it from `texts/` or drop the row.** The exit code
is non-zero while any row fails; do not report a search whose findings file does not
pass.

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

The manifest carries two extraction-quality columns, both warnings rather than
verdicts: `dict%` (share of longer tokens that are dictionary words; clean mathematical
prose sits around 70–78%) and `spaced%` (share of letters inside runs of single-letter
tokens, the letter-spaced OCR the mirror exists for; clean maths scores 1–4%). A text
is `ocr-poor` or `ocr-fair` on either. Keep using `find.py` regardless; lower the
confidence of a null result there.
