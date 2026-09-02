---
name: lit-expand
description: Grow a literature corpus with papers related to the ones already in it — harvest the citation frontier of the existing sources, rank candidates by citation degree, and ingest approved ones as texts, index rows, routing blocks and bibliography entries. Use when the user asks to find related or missing literature, extend or expand the corpus, look for papers that cite or are cited by what is already there, check what the bibliography is missing, or add a specific paper to the corpus. Works on any subject.
---

# Corpus expansion

Sibling to `lit-claim-search`, which *searches* a corpus. This skill *grows* it, in
the same formats, so anything ingested is immediately searchable by that skill. To
create a corpus in the first place, use `lit-corpus-init`.

**Discovery is structural, not lexical.** Candidates come from the citation graph of
the existing corpus — what its sources cite, and what cites them — because a corpus
worth building this way spans traditions with disjoint vocabulary for the same ideas.
A keyword sweep both misses papers that word things differently and drowns in papers
sharing only surface terms. A citation edge to a seed is far stronger evidence of
belonging than any phrase.

For a focused subject this is near-exhaustive: seeds have citing sets of tens to a
few hundred works, not thousands.

## Running the scripts

```bash
LT="${CLAUDE_PLUGIN_ROOT}"      # if unset, derive it: this file is at
                                # <plugin root>/skills/lit-expand/SKILL.md
S="$LT/skills/lit-expand/scripts"
```

Every script finds the corpus by walking up from the working directory to a
`lit-corpus.json`; override with `--corpus PATH` or `$LIT_CORPUS`. All paths, the
tradition vocabulary, the hub rules and the bibliography location come from that
config — the scripts hold no knowledge of any subject.

## Providers and budget

Two different APIs, deliberately:

| stage | provider | metered? |
|---|---|---|
| `resolve_seeds` | OpenAlex + **Crossref** | OpenAlex: 1000 req/day, then 429 until midnight UTC |
| `harvest` | **Semantic Scholar**, keyed by DOI | no key, no hard quota (transient 429s) |

The harvest deliberately does *not* use OpenAlex: DOIs resolve far more of a typical
corpus than OpenAlex ids do (on the first corpus built this way, 38 of 47 seeds had a
DOI but only 13 an OpenAlex id), and S2 keeps working when the OpenAlex budget is gone.

- Every response from both providers is cached under `<corpus>/index/.cache/`.
  Re-runs and resumes are free; deleting the cache is what costs you. The cache never
  expires by itself, so a frontier harvested a year ago is missing a year of citers:
  `harvest.py --refresh` (and `resolve_seeds.py --refresh`) fetch again and re-cache.
- `_lib.get()` raises `RateLimited` on 429. **Never catch it and record an absence.**
  A rate limit is not a missing paper. Every stage stops, keeps what it has, exits 2.
- `OPENALEX_MAILTO=<address>` opts into the faster polite pool. Not set by default —
  do not put the user's email in a third-party request they did not ask for.
- Crossref is unmetered and needs no key. It carries title→DOI resolution.

## Pipeline

Four stages, each writing a durable artefact, each resumable.

```bash
python3 $S/resolve_seeds.py     # corpus       -> index/SEEDS.tsv
python3 $S/harvest.py           # SEEDS        -> index/candidates.jsonl
python3 $S/rank.py              # candidates   -> index/CANDIDATES.md   <- REVIEW GATE
python3 $S/ingest.py --from-queue   # marked rows -> texts/ + bibmap + bibliography
python3 $S/wanted.py                # stubs        -> index/WANTED.md
```

### 1. resolve_seeds.py

Seeds are the **corpus** (`index/bibmap.tsv`), not the attached paper's bibliography —
the goal is to grow the body of texts, and a paper's `.bib` is usually full of general
background whose citation neighbourhoods would flood the harvest. Resolution is a
ladder: DOI → OpenAlex title search → trimmed title search → **Crossref bibliographic
search** → give up.

Crossref is not a nicety. Publisher digitisations of old journals mangle the deposited
titles — one 1966 paper is deposited with its notation replaced by lookalike
characters — so no title query against OpenAlex can ever reach the papers such a
corpus is built on. Crossref's fuzzy bibliographic query does.

Nothing below a 0.80 title-similarity cutoff is ever accepted. An early version took
the top hit and silently filed one author's 1982 paper under another's slug; the
cutoff exists because of that, and the calibration is in `_lib.title_ratio`.

Columns to check by hand after a run:
- `match` — `crossref-doi-only` means no OpenAlex record, so **no citers to harvest**.
  `none` means unresolved; some are correctly unresolvable (unpublished notes,
  preprints with no deposit) and should simply stay that way.
- `hub` — a seed whose citers are overwhelmingly off-topic; contributes references but
  not citers. Auto-flagged only for traditions the config lists in
  `harvest.hub_traditions`, above `harvest.hub_cited_by` citations. That restriction
  matters: a central work *of* the field can have 700 citers and they are exactly the
  ones you want, so never let the field's own tradition be a hub source. Edit the
  column when it guesses wrong.
- `pin` — set to `y` to freeze a hand-corrected row; it is never re-resolved.

### 2. harvest.py

Backward references plus forward citers per seed, deduplicated against the corpus and
against the bibkeys actually cited in the attached paper's `.bbl` (when the corpus
declares one). Uncited bibliography entries are deliberately *not* excluded — they
were collected once and dropped, so re-surfacing one with a citation-degree score is
signal.

**Forward edges are the strong signal; backward edges are sparse.** Semantic Scholar
has no reference lists for most pre-1990 papers, and Crossref's deposits for them are
unstructured text with no DOIs, so ancestors are only recoverable for modern seeds.
Treat a low-degree old paper as under-measured, not as unimportant — its edges mostly
cannot be counted.

Each edge also keeps what Semantic Scholar knows about the citation itself: the
sentence it is made in, its intent (background, methodology, result) and the
influential flag. They cost nothing extra, and the queue shows them — as the `infl`
and `flags` columns and as quoted citing sentences in the Detail section — so a
reviewer sees *how* a candidate cites a seed without opening it. Older records have
none; absence of a context is not a weak edge.

### 3. rank.py — and why degree, not keywords

Score is `4 × (distinct seeds connected) + vocabulary weight`. Degree dominates by
construction. Lexical scoring over a multi-tradition corpus inverts the truth: one
test query scored the corpus's foundational-but-irrelevant text 435 and the only
relevant source 1. Degree cannot be gamed by a common word, and it still surfaces an
OCR-mangled paper with no abstract at all — the exact case keyword search structurally
cannot reach. `<corpus>/index/topic-terms.txt` only breaks ties and filters the
single-edge tail; a corpus with no terms file ranks by degree alone, which is safe.

The terms file asks of every term "if a paper contains this and nothing else, is it
about my subject?" — and the only way to answer is to see what it actually fires on:

```bash
python3 $S/rank.py --term-stats      # fires · share of frontier · weight · term
```

A positive term that fires on a third of the frontier is generic vocabulary wearing a
topical weight; a term that never fires is dead weight (54 of 90 on one corpus); and a
term contained in another — a singular and its plural — always fires with it and the
two weights add, since matching is by substring. The vocabulary route into tier A is
only as good as these weights: on that corpus two off-topic network-science papers
reached tier A on the field's own signature phrase, `graph dynamical system(s)`,
listed twice at weight 5 and so worth 10, and used by an adjacent literature. Run this
after every harvest and fix the weights before reading the queue; it is the
calibration loop the template promises.

Tiers: **A** = degree ≥ 3, or degree ≥ 2 with strong vocabulary. **B** = degree ≥ 2.
**C** = one edge, kept on vocabulary alone; treat C as a reading list, not a queue.

Degree can be gamed after all — by a survey, or a group's later paper in another
field, that names five seeds in one background sentence. One queue held a
mathematical-epidemiology prospectus at degree 5 in tier A while the paper that
originated a seed's central definition sat at degree 1. No structural rule separated
the two cleanly on that corpus: the same group wrote the prospectus *and* the most
relevant follow-ups, and Semantic Scholar flagged one of the prospectus's citations
influential. So the queue does not demote; it shows the evidence and leaves the call
at the gate. Per row: `infl` = influential / classified edges; `flags` = `self` (most
connected seeds share an author with the candidate), `bg` (every classified edge is
background, none influential), `noabs` (no abstract, so a vocabulary score of zero is
silence, not a judgement — old scans and encyclopedia entries). The Detail section
quotes the sentences in which the citations are made. Read a tier-A row with `self`
and no vocabulary as a question, not an answer.

The tier split matters at scale. On one full frontier of 1006 works, 343 had an OA
PDF but 312 of those were tier C — a single citation edge plus a topical word.
Ingesting them would have quintupled the corpus with material one weak link from the
subject. Fetch A/B in bulk; make C a deliberate, separate decision.

`rank.py` excludes anything already in `bibmap.tsv`, so the queue always shows only
untriaged work. `candidates.jsonl` stays the raw frontier and is never pruned — it is
a record of what the citation graph contained, not a worklist. Note `--limit`
(default 120) caps the queue: raise it when bulk-marking, or high-scoring papers stay
invisible.

### 4. Review gate — this is the point of the design

`rank.py` stops. **Do not ingest without the user marking the queue.**

When the queue is long, hand the reading to a batch of cheap subagents
(`model: "haiku"`) — one per block of candidates, each returning a one-line verdict and
what the candidate connects to — rather than pulling every abstract into this session's
context. Presenting the queue is orchestration; reading it is grunt work. Corpus curation
is theirs; a bad screening call silently becomes a corpus entry that later gets cited
in published work. Present the A/B tiers, say what each candidate connects to and why
it scored, and let them mark:

`[x]` ingest full text · `[s]` stub, metadata only · `[ ]` skip

Mark by ref id rather than by editing the file — the queue runs to thousands of lines,
and reading it back into context to issue a text edit per row costs more than the
decision does:

```bash
python3 $S/mark.py find hecke kiselman        # rows whose title has the words, with refs
python3 $S/mark.py x f3f5474aa5 7e4e0946cb    # ingest full text
python3 $S/mark.py s 0d0bf69491               # stub
python3 $S/mark.py list                       # what is marked
```

A ref may be shortened to a unique prefix of four or more characters; anything that
matches nothing is reported, never guessed.

### 5. ingest.py

Fetches the PDF, extracts with `pdftotext`, writes `texts/<slug>.txt` in the corpus
naming convention, appends a `bibmap.tsv` row and a generated bibliography entry
(fenced under an `UNVERIFIED` banner — a starting point, not a citation), then re-runs
`normalize.py` and `build_manifest.py` on the same corpus.

**Acquisition is a ladder, because an OA link is usually not a PDF.** In one bulk run
36 of 51 "open access" URLs failed: 14 were bare `doi.org` links resolving to HTML
landing pages, the rest mostly repository pages. The ladder tries, in order: arXiv (via
the S2 `ArXiv` id) → Europe PMC (DOI → PMCID → rendered PDF) → the given URL → and, if
that returns HTML, the `citation_pdf_url` Highwire meta tag on it. That recovered 9 more.

Elsevier (403) and MDPI (Cloudflare) block programmatic fetches outright and are not
recoverable this way — they are exactly what `WANTED.md` is for.

**Papers behind a paywall are the normal case, not an edge case.** They live in
`index/WANTED.md`, ordered by citation degree. When the user obtains them through
institutional access, one command ingests the lot:

```bash
python3 $S/ingest.py --promote-dir ~/Downloads
```

Each PDF is matched to its stub by the DOI embedded in the file (read with
`pdftotext -l 2`), falling back to a fuzzy filename match, so opaque publisher
filenames work unchanged. Unmatched files are reported rather than guessed at.

`--retry-stubs` re-attempts every `fulltext=no` row against the current ladder and
promotes any that now succeed. Run it after improving acquisition, or later when a
paper becomes open access.

**Three `fulltext` states** in `bibmap.tsv`: `yes` (text in `texts/`), `no` (a
metadata-only stub, listed in `WANTED.md`, reported by `lit-claim-search` as
unsearched), and `rejected` — triaged and deliberately excluded, e.g. a one-page
erratum that is not a paper. `rejected` rows get no manifest row and are never
re-offered by `rank.py`; deleting a row instead of rejecting it just makes the queue
hand it back next run.

**Papers with no reachable full text are never silently dropped.** They become stubs,
so a null search result can never masquerade as evidence of novelty. Drop a PDF in
later and promote it:

```bash
python3 $S/ingest.py --pdf ~/Downloads/paper.pdf --slug <existing-slug>
```

Then do the judgement half — **`references/ingest-checklist.md`**. An ingested paper
with no `CORPUS-MAP.md` routing block is nearly invisible to the sibling skill, which
ranks by that map and explicitly not by hit count. Ingestion is not finished until the
block exists.

## Shared state with lit-claim-search

`<corpus>/index/bibmap.tsv` is the curated slug ⇄ bibkey ⇄ tradition mapping, read by
`build_manifest.py` and appended to by `ingest.py`. Filenames lie (see the corpus's
`index/TRAPS.md`), so the mapping stays curated — never regenerate it from filenames.

## Known traps

These are properties of the method, not of any one subject. Traps specific to a corpus
belong in that corpus's `index/TRAPS.md`.

- **A 429 is not an absence.** The single most damaging failure mode here; it silently
  demoted 25 correctly resolved seeds once. Every stage must stop rather than record.
- **The same paper can carry two DOIs.** A 1973 paper deposited by both Springer and
  Elsevier is one work with two identifiers; duplicate provider records are common too.
  Dedup runs on normalised title *and* DOI for this reason.
- **Near-duplicate titles still slip through.** One queue surfaced "A biochemically-
  realisable model of X" while the corpus held "A biochemically-realisable *relational*
  model of X" — one word apart, so exact-title dedup misses it. Eyeball the queue for
  titles that look like something already in `MANIFEST.tsv` before ingesting.
- **Bibliography DOIs are not all correct.** One entry carried a DOI resolving to
  nothing. Verify a DOI via Crossref before trusting a null lookup.
- **Old scans have mangled titles and no abstracts.** They will never score on
  vocabulary. This is why the ranking is degree-first.
