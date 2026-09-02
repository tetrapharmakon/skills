#!/usr/bin/env python3
"""Regenerate <corpus>/index/MANIFEST.tsv.

Mechanical columns (kb, lines, dict%, spaced%, status) are recomputed from the
texts. The curated slug -> (bibkey, tradition) mapping lives in the DATA file
index/bibmap.tsv, not in this source -- filenames lie (see the corpus's own
index/TRAPS.md), and the lit-expand skill appends rows to it mechanically on
ingest.

Two extraction-quality signals, both warnings rather than verdicts:

  dict%     share of 4+-letter tokens found in a wordlist. Clean mathematical
            prose sits around 70-78%; far below that the text is damaged.
  spaced%   share of letters inside runs of single-letter tokens -- the
            letter-spaced OCR ("a u t o m a t a") that made texts-norm/
            necessary. Variables put clean maths at 1-4%; real damage is >>10.

The previous single metric (share of single-letter tokens) rated every text in
a mathematics corpus "ocr-fair", born-digital monograph included, because
variables are single letters. It could not distinguish a clean text from a
damaged one, which is the only thing the column is for.

Rows whose bibmap `fulltext` column is `no` have no file in texts/: they are
metadata-only stubs for papers judged relevant but not obtainable. They are
emitted with status `no-fulltext` so a null search result never silently
implies coverage that does not exist.
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus


def load_bibmap(path):
    """slug -> dict of bibmap columns."""
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh, delimiter="\t")}


_WORD = re.compile(r"[^\W\d_]+")   # runs of letters, any script

WORDLIST_CANDIDATES = ("/usr/share/dict/words", "/usr/dict/words")


def load_wordlist():
    """A plain one-word-per-line list, or None. $LIT_WORDLIST overrides the
    system locations. Without one the dictionary column is blank and status
    falls back to letter-spacing alone."""
    paths = [os.environ["LIT_WORDLIST"]] if os.environ.get("LIT_WORDLIST") else []
    for p in paths + list(WORDLIST_CANDIDATES):
        try:
            return {w.strip().lower() for w in
                    open(p, encoding="utf-8", errors="replace") if len(w.strip()) >= 4}
        except OSError:
            continue
    return None


def dict_rate(toks, words):
    """Share of tokens of four letters or more that are dictionary words, after
    the same folding the search mirror applies. Mathematical prose sits around
    70-78% on a clean extraction (names, symbols, coined terms), so this is a
    warning signal for heavy damage, not a fine gauge."""
    ws = [litcorpus.norm(x) for x in toks]
    ws = [x for x in ws if len(x) >= 4]
    return 100.0 * sum(x in words for x in ws) / max(len(ws), 1)


def spaced_rate(toks):
    """Share of all letters that sit inside runs of three or more consecutive
    single-letter tokens -- the letter-spaced OCR (\"a u t o m a t a\") that made
    the search mirror necessary. Mathematical text scores 1-4% from variables;
    a scan with a third of its lines letter-spaced scored 37%. Counting single
    letters alone, as the old metric did, cannot tell the two apart."""
    letters = sum(map(len, toks)) or 1
    run = inrun = 0
    for x in toks + ["END"]:
        if len(x) == 1:
            run += 1
        else:
            if run >= 3:
                inrun += run
            run = 0
    return 100.0 * inrun / letters


def status_of(kb, d, s):
    if kb < 1:
        return "EXTRACTION-FAILED"
    if s >= 20 or (d is not None and d < 40):
        return "ocr-poor"
    if s >= 8 or (d is not None and d < 60):
        return "ocr-fair"
    return "ok"


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    args = ap.parse_args()
    try:
        c = litcorpus.from_args(args)
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1

    words = load_wordlist()
    if words is None:
        print("  no wordlist found (set $LIT_WORDLIST); dict% left blank, status from "
              "letter-spacing only", file=sys.stderr)
    bibmap = load_bibmap(c.bibmap)
    rows, unmapped = [], []
    seen = set()

    for f in sorted(c.texts.glob("*.txt")):
        stem = f.stem
        seen.add(stem)
        t = f.read_text(encoding="utf-8", errors="replace")
        toks = _WORD.findall(t)
        kb, lines = f.stat().st_size / 1024, t.count("\n") + 1
        d = dict_rate(toks, words) if words is not None else None
        s = spaced_rate(toks)
        status = status_of(kb, d, s)
        rec = bibmap.get(stem)
        if rec is None:
            unmapped.append(stem)
            key, trad = "", "?"
        else:
            key, trad = rec["bibkey"], rec["tradition"]
        rows.append((stem, key or "-", trad, f"{kb:.0f}", str(lines),
                     f"{d:.0f}" if d is not None else "-", f"{s:.0f}", status))

    # metadata-only stubs: in the bibmap, deliberately absent from texts/
    stubs = 0
    for stem, rec in bibmap.items():
        if stem in seen:
            continue
        ft = rec.get("fulltext", "yes").strip().lower()
        if ft == "rejected":
            continue          # deliberately excluded; keeps it out of the queue too
        if ft in ("no", "no-fulltext", "stub"):
            rows.append((stem, rec["bibkey"] or "-", rec["tradition"], "0", "0", "-", "-",
                         "no-fulltext"))
            stubs += 1
        else:
            print(f"  MISSING TEXT (bibmap says fulltext=yes): {stem}", file=sys.stderr)

    rows.sort(key=lambda r: r[0] + ".txt")  # match the old glob order exactly
    hdr = ("slug", "bibkey", "tradition", "kb", "lines", "dict%", "spaced%", "status")
    c.manifest.parent.mkdir(parents=True, exist_ok=True)
    c.manifest.write_text("\n".join("\t".join(r) for r in [hdr] + rows) + "\n",
                          encoding="utf-8")
    print(f"{len(rows)} rows ({stubs} metadata-only stubs) -> {c.manifest}")
    for s in unmapped:
        print(f"  UNMAPPED (add a row to {c.bibmap.name}): {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
