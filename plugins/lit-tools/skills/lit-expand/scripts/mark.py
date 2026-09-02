#!/usr/bin/env python3
"""Mark rows of the review queue by ref id, without editing the file by hand.

CANDIDATES.md runs to thousands of lines on a real frontier. Marking it by
opening it in an editor -- or, for a model, by reading it back into context
and issuing a text edit per row -- costs far more than the decision does.
This edits the row in place and prints what changed.

  mark.py x f3f5474aa5 7e4e0946cb      # ingest full text
  mark.py s 0d0bf69491                 # stub, metadata only
  mark.py clear f3f5474aa5             # back to [ ]
  mark.py list                         # every marked row
  mark.py find "hecke kiselman"        # rows whose title contains the words, with refs

A ref may be abbreviated to a unique prefix of at least four characters.
Rows that match nothing are reported, never guessed. The queue's Detail
section is untouched; only the table row changes.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus

_ROW = re.compile(r"^(\|\s*`\[)([xs ])(\]`\s*\|\s*`)([^`]+)(`\s*\|)(.*)$")


def rows(lines):
    """(index, mark, ref, rest) for every markable table row."""
    for i, line in enumerate(lines):
        m = _ROW.match(line)
        if m:
            yield i, m.group(2), m.group(4).strip(), m.group(6)


def title_of(rest):
    """The title cell: after tier, score, deg, [infl,] year -- the first cell
    with letters that is longer than a venue abbreviation would be. Display
    only; never parsed for meaning."""
    cells = [x.strip() for x in rest.split("|")]
    for x in cells:
        if len(x) > 12 and re.search(r"[A-Za-z]{3}", x):
            return x
    return rest.strip()[:70]


def resolve(ref, known):
    if ref in known:
        return ref, None
    if len(ref) < 4:
        return None, f"'{ref}': give at least four characters"
    hits = [k for k in known if k.startswith(ref)]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, f"'{ref}': no such row"
    return None, f"'{ref}': ambiguous ({', '.join(hits[:4])})"


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    ap.add_argument("action", choices=("x", "s", "clear", "list", "find"))
    ap.add_argument("refs", nargs="*", help="ref ids (x/s/clear) or words (find)")
    a = ap.parse_args()
    try:
        c = litcorpus.from_args(a)
    except litcorpus.NoCorpus as e:
        sys.exit(str(e))
    if not c.queue.is_file():
        sys.exit(f"no {c.queue} -- run rank.py first")
    lines = c.queue.read_text(encoding="utf-8").split("\n")
    table = list(rows(lines))
    if not table:
        sys.exit(f"no markable rows in {c.queue}")

    if a.action == "list":
        marked = [(m, ref, rest) for _, m, ref, rest in table if m != " "]
        for m, ref, rest in marked:
            print(f"[{m}] {ref}  {title_of(rest)}")
        print(f"{len(marked)} marked of {len(table)} rows", file=sys.stderr)
        return 0

    if a.action == "find":
        words = [w.lower() for w in a.refs]
        if not words:
            sys.exit("find: give one or more words")
        n = 0
        for _, m, ref, rest in table:
            low = rest.lower()
            if all(w in low for w in words):
                print(f"[{m}] {ref}  {title_of(rest)}")
                n += 1
        print(f"{n} row{'s'[:n ^ 1]} match", file=sys.stderr)
        return 0

    if not a.refs:
        sys.exit(f"{a.action}: give one or more refs")
    known = {ref: i for i, _, ref, _ in table}
    new = {"x": "x", "s": "s", "clear": " "}[a.action]
    changed, errors = 0, []
    for ref in a.refs:
        full, err = resolve(ref, known)
        if err:
            errors.append(err)
            continue
        i = known[full]
        m = _ROW.match(lines[i])
        if m is None:        # cannot happen: `known` was built from this regex
            errors.append(f"'{full}': row {i + 1} no longer parses")
            continue
        if m.group(2) == new:
            print(f"    [{new}] {full}  (already)")
            continue
        lines[i] = m.group(1) + new + m.group(3) + m.group(4) + m.group(5) + m.group(6)
        print(f"[{m.group(2)}]->[{new}] {full}  {title_of(m.group(6))}")
        changed += 1
    if changed:
        c.queue.write_text("\n".join(lines), encoding="utf-8")
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    print(f"{changed} row{'s'[:changed ^ 1]} changed in {c.queue.name}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
