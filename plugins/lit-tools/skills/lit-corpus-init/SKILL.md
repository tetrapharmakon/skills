---
name: lit-corpus-init
description: Create a searchable literature corpus on a new subject from a folder of PDFs and/or a .bib file — build the skeleton and config, resolve metadata, run the review gate, and write the domain knowledge (traditions, glossary, topic terms) the sibling skills need. Use when the user has a bulk of texts or a bibliography on some topic X and wants to start searching claims against it or expanding it, or asks to set up / bootstrap / create a corpus or dump.
---

# Corpus init

Turns a pile of PDFs and/or a `.bib` into a corpus the other two skills can work on:
`lit-claim-search` searches it, `lit-expand` grows it along its citation graph.

The mechanical half is one command. **The judgement half is the point** — a corpus with
texts but no domain knowledge is a folder, not a corpus, and the sibling skills will
underperform in ways that are invisible: routing falls back to hit counts, and
cross-dialect claims silently return nothing.

```bash
LT="${CLAUDE_PLUGIN_ROOT}"      # if unset, derive it: this file is at
                                # <plugin root>/skills/lit-corpus-init/SKILL.md
I="$LT/skills/lit-corpus-init/scripts/init_corpus.py"
```

## 1. Build the skeleton and the queue

```bash
python3 $I ~/corpora/<name> --name <name> --pdfs ~/Downloads/<folder>
python3 $I ~/corpora/<name> --name <name> --bib ~/paper/refs.bib --pdfs ~/Downloads/x
python3 $I ./dump --bib refs.bib --paper-bib ../refs.bib --cited-from ../main.bbl
```

Where to put it: inside the project it serves (`<project>/<name>-dump/`) if it belongs
to one piece of writing, or under `~/corpora/` if it is a standing resource. It is
self-describing either way and can be moved later.

What each input contributes:

- **`--pdfs DIR`** — full text, the thing that actually gets searched. Each PDF is
  identified by the DOI embedded in it, falling back to a first-page title lookup, so
  opaque publisher filenames are fine. Pre-marked `[x]`: you chose those files.
- **`--bib FILE`** — clean keys, titles and years, but **no text**. Bibliography rows
  become stubs unless acquisition succeeds later, and stubs are reported by
  `lit-claim-search` as *unsearched*. Expect a corpus seeded from a `.bib` alone to be
  mostly gaps at first; say so out loud when reporting ("48 entries, 11 with text, 37
  in WANTED.md"). Pre-marked `[ ]`: a paper's `.bib` is largely background that does
  not belong in a topical corpus.
- **both** — the good case: entries and PDFs are deduplicated on DOI and normalised
  title, the bib entry contributing the key and the PDF the text.

`--offline` skips every network call. `--paper-bib` / `--cited-from` attach the corpus
to an existing LaTeX project (generated entries are appended to that `.bib`, and keys
already cited in the `.bbl` are excluded from future harvests); omit both and the
corpus keeps its own `index/refs.bib`, which is the right default for a standing corpus
with no single paper attached.

## 2. Review the queue, then ingest

`index/CANDIDATES.md` is the same review gate the expansion pipeline uses, so the same
rule holds: **present it and let the user mark it.** Curation is theirs; a bad screening
call silently becomes a corpus entry that later gets cited.

`[x]` full text · `[s]` stub, metadata only · `[ ]` skip

```bash
python3 $LT/skills/lit-expand/scripts/ingest.py --from-queue --corpus <corpus>
```

Unresolved metadata is reported, never guessed: a title that no DOI matches above the
0.80 similarity cutoff stays unresolved rather than being filed under a near-miss.
Fix those rows by hand in `index/bibmap.tsv` afterwards.

## 3. Write the domain knowledge — do not skip this

Four artefacts, in this order. The first two are what make search work at all.

**a. Traditions** (`lit-corpus.json`). Which research communities does this corpus
span, and what vocabulary marks each? Read enough of the texts to answer honestly —
the point is *dialects*, not subjects: a paper applying one field's machinery to
another field's subject belongs to the tradition whose words it uses. Fill the cue
lists (they drive automatic classification on ingest) most-specific-first, since the
first match wins, and set `default_tradition`.

**b. Glossary** (`index/glossary.md`, from `lit-claim-search/references/glossary.template.md`).
One row per *idea*, one column per tradition, filled with the words each community
uses for it. This is the single highest-value file in the corpus: claim search
decomposes a claim across these rows before it searches anything. A `—` where a
tradition has no word for an idea is information, not a gap.

**c. Topic terms** (`index/topic-terms.txt`, from
`lit-expand/references/topic-terms.template.txt`). Weighted discriminating phrases,
seeded from the glossary. Include **anti-terms** with negative weights for the adjacent
literatures that will otherwise flood the expansion queue. Start small; the first
ranked queue will show you what the noise actually is.

**d. Routing blocks** (`index/CORPUS-MAP.md`). One four-field block per ingested source
— what it establishes and does *not*, its dialect, what to route to it for. Follow
`lit-expand/references/ingest-checklist.md`. Write them from the text, not from the
abstract alone. Until a source has a block it is nearly invisible to claim search,
which ranks by this map and explicitly not by hit count.

Also create `index/TRAPS.md` (it can start almost empty) and add to it the moment
anything surprises you: a filename that names a different paper than it contains, one
work deposited twice under different titles, an extraction that produced two bytes.

## 4. Verify, then hand over

```bash
python3 $LT/skills/lit-claim-search/scripts/normalize.py --corpus <corpus>
python3 $LT/skills/lit-claim-search/scripts/build_manifest.py --corpus <corpus>
python3 $LT/skills/lit-claim-search/scripts/find.py --corpus <corpus> "<a phrase you know is in there>"
```

Check the manifest for `EXTRACTION-FAILED` rows (delete the text, re-register as a
stub — a corrupt text reads as coverage) and for `ocr-poor` ones. Ligatures and accents
are folded automatically, but a scan that replaced a glyph outright (`®nite` for
`ﬁnite`) needs a line under `normalize.substitutions` in `lit-corpus.json`
(`{"®": "fi"}`) and another run of `normalize.py`; a quick `find.py` for a word you
know the scan mangles tells you whether one is needed. Report the corpus as
what it is: how many texts, how many stubs, how many failed. Then tell the user the
next two moves: search a claim with `lit-claim-search`, or grow the corpus along its
citation frontier with `lit-expand`.
