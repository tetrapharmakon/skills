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
<corpus>/lit-corpus.json         identity, layout, traditions, bibliography
<corpus>/texts/                  extracted full text, one file per source
<corpus>/texts-norm/             OCR-robust search mirror (generated)
<corpus>/index/bibmap.tsv        curated slug <-> bibkey <-> tradition
<corpus>/index/MANIFEST.tsv      generated: size, OCR quality, status
<corpus>/index/CORPUS-MAP.md     routing blocks — what to ask each source
<corpus>/index/glossary.md       the dialects each tradition uses for one idea
<corpus>/index/topic-terms.txt   weighted vocabulary for ranking candidates
<corpus>/index/TRAPS.md          filenames that lie, duplicate deposits, bad scans
<corpus>/findings/               one file per claim searched
```

Corpus discovery: `--corpus PATH`, else `$LIT_CORPUS`, else walk up from the working
directory to a `lit-corpus.json` (or one in an immediate subdirectory). Two candidates
side by side is an error, never a guess.

## Install

```bash
claude plugin marketplace add ~/repos/lit-tools
claude plugin install lit-tools@lit-tools
```

or `/plugin` inside Claude Code.

## Why it works the way it does

- **Never `grep` an OCR'd corpus.** Scanned journals come out letter-spaced
  (`a u t o m a t a`) and word-joined; matching happens against a punctuation- and
  whitespace-free mirror instead. On one test query `grep` missed the only relevant
  source.
- **Rank candidates by citation degree, not keywords.** Lexical scoring over a
  multi-tradition corpus inverts the truth: one query scored a famous irrelevant text
  435 and the single relevant paper 1.
- **A rate limit is not an absence.** Every pipeline stage stops on a 429 and keeps
  what it has. Recording "not found" instead once demoted 25 correctly resolved seeds.
- **A paper with no reachable text is a stub, never a silent drop.** Claim search
  reports stubs as unsearched, so a null result cannot masquerade as novelty.
- **Ingestion stops at a review gate.** Curation is the user's; a bad screening call
  becomes a corpus entry that later gets cited.

Requires `python3` and `pdftotext` (poppler-utils). No API keys.
