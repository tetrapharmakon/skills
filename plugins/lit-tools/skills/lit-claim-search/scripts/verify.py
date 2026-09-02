#!/usr/bin/env python3
"""Check every quote in a findings file against the corpus texts.

The claim-search output becomes citations in published work, and an invented
or misplaced quote is the one failure that cannot be recovered later. The
skill asks the model to re-locate each quote before recording it; this makes
that a mechanical check instead of a promise.

  verify.py                                   # every file in <corpus>/findings/
  verify.py findings/some-claim.md            # one file
  verify.py --slack 5 findings/x.md           # tolerate line numbers off by 5

What is checked. Every markdown table row that carries a location cell of the
shape the skill's output contract prescribes,

    Decomposition:556-594            slug (or a unique part of it) : line range
    Introduction:5410-5416, 5462     several ranges in one file
    Elements:91-114; Threshold:552   several files

is paired with the row's quote cell. The quote is split on ellipses (… / ...
/ [...]) and on quote marks into fragments, each fragment is normalised
exactly as the search mirror is, and each must occur inside the quoted line
range (plus `--slack` lines either side). Fragments too short to be
distinctive after normalisation are skipped and said so -- that is also how
an editorial label such as `Prop. 3:` in front of a quote falls out.

A fragment need not be an exact substring: extracted text interleaves
equation numbers, page furniture and exploded diagram tokens inside a
sentence, so a fragment passes when at least COVERAGE of its characters are
matched in order inside the window, insertions in the text being free. A
paraphrase changes far more than that; a wrong line number matches nothing.

What a failure means. A fragment whose opening is found elsewhere in the file
is a wrong line number: the line is reported so it can be corrected. A
fragment found nowhere in the file is a quote that is not verbatim -- a
paraphrase, a reconstruction from memory, or an invention -- and the row
must be dropped or re-quoted from texts/.

Exit 0 when every fragment checks out, 1 when any fails, 2 when nothing
checkable was found.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus

MIN_FRAGMENT = 12   # normalised characters; shorter is not distinctive
COVERAGE = 0.90     # share of a fragment's characters that must match in order
MIN_BLOCK = 4       # matching runs shorter than this are coincidence, not text
WINDOW_ANY = 12     # lines joined per probe when locating a fragment anywhere
PROBE = 40          # leading normalised characters used for that probe

_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_RANGE = re.compile(r"^L?(\d+)(?:\s*[-–]\s*L?(\d+))?$")
_LOC = re.compile(r"^\s*([A-Za-z0-9_\-\.]+)\s*:\s*(L?\d+(?:\s*[-–]\s*L?\d+)?"
                  r"(?:\s*,\s*L?\d+(?:\s*[-–]\s*L?\d+)?)*)\s*$")
_SPLIT = re.compile(r"\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…|[\"“”„«»]")


def cells(row):
    parts = [p.strip() for p in _CELL_SPLIT.split(row.strip())]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.replace("\\|", "|") for p in parts]


def parse_location(text):
    """'Elements:91-114; Introduction:3515' -> [(slugpart, start, end), ...]
    or None when the cell is not a location."""
    out = []
    for seg in text.split(";"):
        m = _LOC.match(seg)
        if not m:
            return None
        slug, ranges = m.group(1), m.group(2)
        for rng in ranges.split(","):
            r = _RANGE.match(rng.strip())
            if not r:
                return None
            a = int(r.group(1))
            b = int(r.group(2)) if r.group(2) else a
            out.append((slug, min(a, b), max(a, b)))
    return out or None


def tables(lines):
    """Yield (header_cells, [(lineno, body_cells), ...]) per markdown table."""
    i, n = 0, len(lines)
    while i < n:
        if lines[i].lstrip().startswith("|") and i + 1 < n \
                and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            hdr = cells(lines[i])
            body, j = [], i + 2
            while j < n and lines[j].lstrip().startswith("|"):
                body.append((j + 1, cells(lines[j])))
                j += 1
            yield hdr, body
            i = j
        else:
            i += 1


def find_columns(hdr, body):
    """(loc_col, quote_col) or None. Header names first, then the shape of
    the cells, then the convention 'location, then quote'."""
    low = [h.lower() for h in hdr]
    loc = next((k for k, h in enumerate(low)
                if any(w in h for w in ("slug", "line", "location", "where"))), None)
    if loc is None:
        for k in range(len(hdr)):
            vals = [c[k] for _, c in body if k < len(c)]
            if vals and sum(1 for v in vals if parse_location(v)) >= max(1, len(vals) // 2):
                loc = k
                break
    if loc is None:
        return None
    quote = next((k for k, h in enumerate(low) if "quote" in h), None)
    if quote is None:
        quote = loc + 1
    return loc, quote


def fragments(quote, subs):
    out = []
    for piece in _SPLIT.split(quote):
        nrm = litcorpus.norm(piece, subs)
        if nrm:
            out.append((piece.strip(), nrm))
    return out


def coverage(frag, window):
    """Share of frag's characters that appear in order inside window, counting
    only runs of MIN_BLOCK or more. Insertions in window cost nothing, which is
    what lets a sentence with an equation number dropped into it still match."""
    sm = difflib.SequenceMatcher(None, frag, window, autojunk=False)
    got = sum(b.size for b in sm.get_matching_blocks() if b.size >= MIN_BLOCK)
    return got / max(len(frag), 1)


def resolve_slug(part, stems):
    if part in stems:
        return part, None
    cands = [s for s in stems if part.lower() in s.lower()]
    if len(cands) == 1:
        return cands[0], None
    if not cands:
        return None, f"no text matches '{part}'"
    return None, f"'{part}' is ambiguous: {', '.join(sorted(cands)[:4])}"


def locate_anywhere(nlines, frag):
    """First line (1-based) whose WINDOW_ANY-line join contains the opening
    PROBE characters of frag, or None. A probe, not the whole fragment: the
    question is only whether the quote exists somewhere the range missed."""
    probe = frag[:PROBE]
    for i in range(len(nlines)):
        if probe in "".join(nlines[i:i + WINDOW_ANY]):
            return i + 1
    return None


def check_file(path, c, mirror, slack):
    """Returns (checked_rows, failed_rows, messages)."""
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    stems = sorted(p.stem for p in c.texts_norm.glob("*.txt"))
    checked = failed = 0
    msgs = []
    for hdr, body in tables(lines):
        cols = find_columns(hdr, body)
        if not cols:
            continue
        lc, qc = cols
        for lineno, row in body:
            if max(lc, qc) >= len(row):
                continue
            locs = parse_location(row[lc])
            if not locs:
                continue
            frags = fragments(row[qc], c.substitutions)
            checked += 1
            problems, skipped, ok, fuzzy = [], 0, 0, []
            windows = {}        # stem -> concatenated normalised window text
            for part, a, b in locs:
                stem, err = resolve_slug(part, stems)
                if err:
                    problems.append(err)
                    continue
                nl = mirror(stem)
                lo, hi = max(0, a - 1 - slack), min(len(nl), b + slack)
                windows[stem] = windows.get(stem, "") + "".join(nl[lo:hi])
            for raw, frag in frags:
                if len(frag) < MIN_FRAGMENT:
                    skipped += 1
                    continue
                if any(frag in w for w in windows.values()):
                    ok += 1
                    continue
                best = max((coverage(frag, w) for w in windows.values()), default=0.0)
                if best >= COVERAGE:
                    ok += 1
                    fuzzy.append(best)
                    continue
                # Not at the stated lines. Anywhere in those files?
                where, inside = None, False
                for stem in windows:
                    hit = locate_anywhere(mirror(stem), frag)
                    if hit:
                        where = f"{stem}:L{hit}"
                        inside = any(a - slack <= hit <= b + slack
                                     for part, a, b in locs if part.lower() in stem.lower())
                        break
                short = raw if len(raw) <= 70 else raw[:67] + "..."
                if where and inside:
                    why = (f"opens at {where}, inside the range, but only {best:.0%} of it "
                           f"fits there: extend the range")
                elif where:
                    why = f"opens at {where}, outside the stated range"
                else:
                    why = f"is not in the text (best match {best:.0%})"
                problems.append(f'"{short}" {why}')
            loc_txt = row[lc] if len(row[lc]) <= 44 else row[lc][:41] + "..."
            if problems:
                failed += 1
                msgs.append(("FAIL", f"  FAIL  {path.name}:{lineno}  {loc_txt}"))
                msgs += [("FAIL", f"          {p}") for p in problems]
            else:
                tail = (f", {len(fuzzy)} tolerant (min {min(fuzzy):.0%})" if fuzzy else "") \
                    + (f", {skipped} short skipped" if skipped else "")
                if ok == 0:
                    msgs.append(("????", f"  ????  {path.name}:{lineno}  {loc_txt}  "
                                         f"(nothing long enough to check{tail})"))
                else:
                    msgs.append(("ok", f"  ok    {path.name}:{lineno}  {loc_txt}  "
                                       f"({ok} fragment{'s'[:ok ^ 1]}{tail})"))
    return checked, failed, msgs


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    ap.add_argument("files", nargs="*", help="findings files (default: all in findings/)")
    ap.add_argument("--slack", type=int, default=2,
                    help="lines of tolerance either side of a stated range (default 2)")
    ap.add_argument("-q", "--quiet", action="store_true", help="print failures only")
    a = ap.parse_args()
    try:
        c = litcorpus.from_args(a)
    except litcorpus.NoCorpus as e:
        sys.exit(str(e))
    if not c.texts_norm.is_dir():
        sys.exit(f"run normalize.py first (no {c.texts_norm})")
    stale = litcorpus.mirror_stale(c.texts_norm)
    if stale:
        print(f"WARNING: {stale}", file=sys.stderr)

    files = [Path(f) for f in a.files] or sorted(c.findings.glob("*.md"))
    if not files:
        sys.exit(f"nothing to verify: no files given and none in {c.findings}")

    cache = {}

    def mirror(stem):
        if stem not in cache:
            cache[stem] = (c.texts_norm / f"{stem}.txt").read_text(
                encoding="utf-8").split("\n")
        return cache[stem]

    total = failed = 0
    for f in files:
        if not f.is_file():
            print(f"  no such file: {f}", file=sys.stderr)
            continue
        n, bad, msgs = check_file(f, c, mirror, a.slack)
        total += n
        failed += bad
        for kind, m in msgs:
            if not a.quiet or kind != "ok":
                print(m)
    if total == 0:
        print("no rows with a slug:lines location and a quote were found", file=sys.stderr)
        return 2
    print(f"\n{total - failed}/{total} quoted rows verified"
          + (f"; {failed} FAILED -- drop or re-quote them" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
