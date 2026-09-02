# lit-tools

Claude Code skills for building, growing and interrogating a full-text literature
corpus — on any subject.

| skill | what it does |
|---|---|
| `lit-corpus-init` | turn a folder of PDFs and/or a `.bib` into a corpus |
| `lit-expand` | grow it along its citation graph, behind a human review gate |
| `lit-claim-search` | ask who already said a claim, who said less, more, or the opposite |

## The one design rule

**The tools know nothing about any subject. The corpus knows everything.**

Everything domain-specific lives in the corpus directory, so the same plugin serves a
corpus on relational biology, one on algebraic topology and one on chemistry at the
same time:

```
<corpus>/lit-corpus.json         identity, layout, traditions, bibliography, OCR substitutions
<corpus>/texts/                  extracted full text, one file per source
<corpus>/texts-norm/             OCR-robust search mirror (generated; ligatures and accents folded)
<corpus>/index/bibmap.tsv        curated slug <-> bibkey <-> tradition
<corpus>/index/MANIFEST.tsv      generated: size, OCR quality, status
<corpus>/index/CORPUS-MAP.md     routing blocks — what to ask each source
<corpus>/index/glossary.md       the dialects each tradition uses for one idea
<corpus>/index/topic-terms.txt   weighted vocabulary for ranking candidates
<corpus>/index/TRAPS.md          filenames that lie, duplicate deposits, bad scans
<corpus>/findings/               one file per claim searched; quotes checked by verify.py,
                                 and its "Not in corpus" section feeds the next expansion
```

Corpus discovery: `--corpus PATH`, else `$LIT_CORPUS`, else walk up from the working
directory to a `lit-corpus.json` (or one in an immediate subdirectory). Two candidates
side by side is an error, never a guess.

## Install

```bash
claude plugin marketplace add tetrapharmakon/skills
claude plugin install lit-tools@tetrapharmakon
```

or `/plugin` inside Claude Code. This plugin is distributed from the
[tetrapharmakon/skills](https://github.com/tetrapharmakon/skills) marketplace.

## Why it works the way it does

- **Never `grep` an OCR'd corpus.** Scanned journals come out letter-spaced
  (`a u t o m a t a`) and word-joined; matching happens against a punctuation- and
  whitespace-free mirror instead. On one test query `grep` missed the only relevant
  source.
- **Fold before you strip.** A born-digital PDF encodes `fi` as one ligature glyph, and
  stripping non-ASCII turned `ﬁxed` into `xed`: nine hits in ten for "fixed point" were
  lost in a monograph. The mirror folds ligatures and accents first, and a per-corpus
  substitution table covers scans that replaced the glyph outright (`®nite`).
- **A quote is verified by a script, not by a sentence saying so.** `verify.py` checks
  every quote in a findings file against the text at the stated lines. On a real 30-row
  file it failed four rows: two paraphrases, a reconstructed formula, a range that
  stopped short of the lemma it quoted.
- **Rank candidates by citation degree, not keywords.** Lexical scoring over a
  multi-tradition corpus inverts the truth: one query scored a famous irrelevant text
  435 and the single relevant paper 1. Raw hit counts are corrected for length and for
  running heads before anyone reads them.
- **Degree is shown with its evidence, not adjusted by it.** Citing sentences,
  influential flags and author overlap sit next to each candidate in the queue; on the
  test corpus no cheap rule separated a group's off-topic prospectus from its most
  relevant follow-ups, so the call stays at the review gate. Papers a claim search names
  as missing go straight to the top of the next queue.
- **A rate limit is not an absence.** Every pipeline stage stops on a 429 and keeps
  what it has. Recording "not found" instead once demoted 25 correctly resolved seeds.
- **A paper with no reachable text is a stub, never a silent drop.** Claim search
  reports stubs as unsearched, so a null result cannot masquerade as novelty.
- **Ingestion stops at a review gate.** Curation is the user's; a bad screening call
  becomes a corpus entry that later gets cited.

Requires `python3` and `pdftotext` (poppler-utils). No API keys. A system wordlist
(`/usr/share/dict/words`, or `$LIT_WORDLIST`) sharpens the manifest's extraction-quality
column; without one it falls back to the letter-spacing signal alone.
