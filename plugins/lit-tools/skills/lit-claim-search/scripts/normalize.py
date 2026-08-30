#!/usr/bin/env python3
"""Build an OCR-robust search mirror of the corpus texts.

Scanned journal PDFs come out of OCR letter-spaced ("a u t o m a t a") and
sometimes word-joined ("asubeategory"), so neither plain grep nor a de-spacing
heuristic is reliable. Instead we strip ALL whitespace and punctuation and
lowercase, which makes matching insensitive to both failure modes at once.

Line count is preserved exactly, so line N of texts-norm/X.txt corresponds to
line N of texts/X.txt. Always quote from texts/ -- the mirror is for locating
text, never for reading it.

  normalize.py                    # corpus found by walking up from cwd
  normalize.py --corpus ~/proj/rosen-dump
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus

KEEP = re.compile(r"[^a-z0-9]+")


def norm(s: str) -> str:
    return KEEP.sub("", s.lower())


def main() -> int:
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    args = ap.parse_args()
    try:
        c = litcorpus.from_args(args)
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1

    if not c.texts.is_dir():
        print(f"no texts at {c.texts}", file=sys.stderr)
        return 1
    c.texts_norm.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in sorted(c.texts.glob("*.txt")):
        lines = src.read_text(encoding="utf-8", errors="replace").split("\n")
        (c.texts_norm / src.name).write_text("\n".join(norm(l) for l in lines),
                                             encoding="utf-8")
        n += 1
    # A stale mirror silently answers queries about a text that is no longer
    # in the corpus, which reads as a real hit.
    stale = [f for f in c.texts_norm.glob("*.txt") if not (c.texts / f.name).is_file()]
    for f in stale:
        f.unlink()
    print(f"normalized {n} files -> {c.texts_norm}"
          + (f"  ({len(stale)} stale removed)" if stale else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
