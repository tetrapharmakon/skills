#!/usr/bin/env python3
"""OCR-robust literal search over the corpus texts.

Matches against texts-norm/ (whitespace- and punctuation-free) so that
"category of automata" also finds "c a t e g o r y of a u t o m a t a" and
"categoryofautomata". Reports and quotes the ORIGINAL text, with real line
numbers you can cite.

  find.py "closure to efficient causation"
  find.py -C2 "noncomputable" "non-computable"      # OR over patterns
  find.py -f Louie -f arbib "entailment"            # restrict by filename
  find.py -l "fixed genome"                         # filenames + counts only
  find.py --corpus ~/proj/rosen-dump "..."          # name the corpus

Patterns are normalized the same way as the corpus, so punctuation and spacing
in your query are ignored: "(M,R)-system" == "mrsystem". That also means short
patterns match inside longer words, and a phrase spanning more than WINDOW
lines will not match -- prefer distinctive multi-word phrases.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus

WINDOW = 3  # lines joined per probe, so phrases spanning a line break still hit

norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())


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


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    ap.add_argument("patterns", nargs="+")
    ap.add_argument("-C", type=int, default=1, help="context lines (default 1)")
    ap.add_argument("-f", action="append", default=[], metavar="SUBSTR",
                    help="restrict to filenames containing SUBSTR (repeatable)")
    ap.add_argument("-l", action="store_true", help="list files and counts only")
    a = ap.parse_args()
    try:
        c = litcorpus.from_args(a)
    except litcorpus.NoCorpus as e:
        sys.exit(str(e))

    SRC, NORM = c.texts, c.texts_norm
    if not NORM.is_dir():
        sys.exit(f"run normalize.py first (no {NORM})")
    pats = [norm(p) for p in a.patterns]
    if not all(pats):
        sys.exit("a pattern normalized to empty")

    total = 0
    for nf in sorted(NORM.glob("*.txt")):
        if a.f and not any(s.lower() in nf.name.lower() for s in a.f):
            continue
        orig = SRC / nf.name
        nlines = nf.read_text(encoding="utf-8").split("\n")
        found = hits(nlines, pats)
        if not found:
            continue
        total += len(found)
        if a.l:
            print(f"{len(found):4d}  {nf.name}")
            continue
        olines = orig.read_text(encoding="utf-8", errors="replace").split("\n")
        print(f"\n=== {nf.name}  ({len(found)} hit{'s'[:len(found) ^ 1]}) ===")
        for i in sorted(found):
            lo, hi = max(0, i - a.C), min(len(olines), i + a.C + 1)
            print(f"--- L{i + 1}  [{', '.join(sorted(found[i]))}]")
            for k in range(lo, hi):
                print(f"{k + 1:6d}{'>' if k == i else ':'} {olines[k].rstrip()}")
    print(f"\n{total} hit(s) for {a.patterns}", file=sys.stderr)
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
