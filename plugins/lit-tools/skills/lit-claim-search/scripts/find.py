#!/usr/bin/env python3
"""OCR-robust literal search over the corpus texts.

Matches against texts-norm/ (whitespace- and punctuation-free) so that
"category of automata" also finds "c a t e g o r y of a u t o m a t a" and
"categoryofautomata". Reports and quotes the ORIGINAL text, with real line
numbers you can cite.

  find.py "closure to efficient causation"
  find.py -C2 "noncomputable" "non-computable"      # OR over patterns
  find.py -f Louie -f arbib "entailment"            # restrict by filename
  find.py -l "fixed genome"                         # per-file counts + density
  find.py --corpus ~/proj/rosen-dump "..."          # name the corpus

Patterns are normalized the same way as the corpus, so punctuation and spacing
in your query are ignored: "(M,R)-system" == "mrsystem". That also means short
patterns match inside longer words, and a phrase spanning more than WINDOW
lines will not match -- prefer distinctive multi-word phrases.

Two things make raw hit counts lie, and both are handled here:

- Running heads. A monograph repeats its chapter title on every page, so a
  query containing the field's name scores hundreds of hits that are all the
  same line. Lines that recur verbatim REPEAT_MIN times or more are not used
  as anchors (--keep-repeats to see them).
- Length. A 14,000-line book outscores an 800-line paper on any common word.
  `-l` therefore prints hits per thousand lines next to the count and sorts
  by that density, which is the comparable number.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus

WINDOW = 3        # lines joined per probe, so phrases spanning a line break still hit
REPEAT_MIN = 8    # a normalised line seen this often in one file is furniture
REPEAT_LEN = 12   # ... provided it is long enough not to be a common short line

norm = litcorpus.norm   # the same folding the mirror was built with


def hits(nlines, pats):
    """Anchor line indices whose WINDOW-line join contains some pattern."""
    out = {}
    for i in range(len(nlines)):
        joined = "".join(nlines[i:i + WINDOW])
        for p in pats:
            if p in joined:
                # anchor to the line the match actually starts on
                at = joined.index(p)
                run = 0
                for k in range(i, min(i + WINDOW, len(nlines))):
                    if run + len(nlines[k]) > at:
                        out.setdefault(k, set()).add(p)
                        break
                    run += len(nlines[k])
    return out


def furniture(nlines):
    """Indices of lines that repeat verbatim through the file: running heads,
    journal banners, page furniture. Anchoring on them inflates a count
    without adding one new sentence of evidence."""
    cnt = Counter(l for l in nlines if len(l) >= REPEAT_LEN)
    return {i for i, l in enumerate(nlines)
            if len(l) >= REPEAT_LEN and cnt[l] >= REPEAT_MIN}


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    ap.add_argument("patterns", nargs="+")
    ap.add_argument("-C", type=int, default=1, help="context lines (default 1)")
    ap.add_argument("-f", action="append", default=[], metavar="SUBSTR",
                    help="restrict to filenames containing SUBSTR (repeatable)")
    ap.add_argument("-l", action="store_true",
                    help="list files with hit counts and hits per 1000 lines, "
                         "densest first")
    ap.add_argument("--keep-repeats", action="store_true",
                    help="also anchor on lines that repeat through a file "
                         "(running heads); suppressed by default")
    a = ap.parse_args()
    try:
        c = litcorpus.from_args(a)
    except litcorpus.NoCorpus as e:
        sys.exit(str(e))

    SRC, NORM = c.texts, c.texts_norm
    if not NORM.is_dir():
        sys.exit(f"run normalize.py first (no {NORM})")
    stale = litcorpus.mirror_stale(NORM)
    if stale:
        print(f"WARNING: {stale}", file=sys.stderr)
    pats = [norm(p) for p in a.patterns]
    if not all(pats):
        sys.exit("a pattern normalized to empty")

    total, suppressed, listing = 0, 0, []
    for nf in sorted(NORM.glob("*.txt")):
        if a.f and not any(s.lower() in nf.name.lower() for s in a.f):
            continue
        orig = SRC / nf.name
        nlines = nf.read_text(encoding="utf-8").split("\n")
        found = hits(nlines, pats)
        if not a.keep_repeats:
            skip = furniture(nlines)
            kept = {k: v for k, v in found.items() if k not in skip}
            suppressed += len(found) - len(kept)
            found = kept
        if not found:
            continue
        total += len(found)
        if a.l:
            listing.append((1000.0 * len(found) / max(len(nlines), 1), len(found), nf.name))
            continue
        olines = orig.read_text(encoding="utf-8", errors="replace").split("\n")
        print(f"\n=== {nf.name}  ({len(found)} hit{'s'[:len(found) ^ 1]}) ===")
        for i in sorted(found):
            lo, hi = max(0, i - a.C), min(len(olines), i + a.C + 1)
            print(f"--- L{i + 1}  [{', '.join(sorted(found[i]))}]")
            for k in range(lo, hi):
                print(f"{k + 1:6d}{'>' if k == i else ':'} {olines[k].rstrip()}")
    if a.l and listing:
        print(f"{'hits':>4}  {'per kL':>7}  file")
        for dens, n, name in sorted(listing, key=lambda r: (-r[0], -r[1], r[2])):
            print(f"{n:4d}  {dens:7.1f}  {name}")
    note = f"  ({suppressed} on repeated lines suppressed; --keep-repeats to see them)" \
        if suppressed else ""
    print(f"\n{total} hit(s) for {a.patterns}{note}", file=sys.stderr)
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
