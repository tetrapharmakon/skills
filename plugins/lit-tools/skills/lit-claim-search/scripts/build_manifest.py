#!/usr/bin/env python3
"""Regenerate <corpus>/index/MANIFEST.tsv.

Mechanical columns (kb, lines, ocr, status) are recomputed from the texts. The
curated slug -> (bibkey, tradition) mapping lives in the DATA file
index/bibmap.tsv, not in this source -- filenames lie (see the corpus's own
index/TRAPS.md), and the lit-expand skill appends rows to it mechanically on
ingest.

Rows whose bibmap `fulltext` column is `no` have no file in texts/: they are
metadata-only stubs for papers judged relevant but not obtainable. They are
emitted with status `no-fulltext` so a null search result never silently
implies coverage that does not exist.
"""
import argparse
import csv
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


def ocr_score(t):
    toks = re.findall(r"[A-Za-z]+", t)
    return 100.0 * sum(len(x) == 1 for x in toks) / max(len(toks), 1)


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    args = ap.parse_args()
    try:
        c = litcorpus.from_args(args)
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1

    bibmap = load_bibmap(c.bibmap)
    rows, unmapped = [], []
    seen = set()

    for f in sorted(c.texts.glob("*.txt")):
        stem = f.stem
        seen.add(stem)
        t = f.read_text(encoding="utf-8", errors="replace")
        kb, lines, o = f.stat().st_size / 1024, t.count("\n") + 1, ocr_score(t)
        if kb < 1:
            status = "EXTRACTION-FAILED"
        elif o > 30:
            status = "ocr-poor"
        elif o > 18:
            status = "ocr-fair"
        else:
            status = "ok"
        rec = bibmap.get(stem)
        if rec is None:
            unmapped.append(stem)
            key, trad = "", "?"
        else:
            key, trad = rec["bibkey"], rec["tradition"]
        rows.append((stem, key or "-", trad, f"{kb:.0f}", str(lines), f"{o:.0f}", status))

    # metadata-only stubs: in the bibmap, deliberately absent from texts/
    stubs = 0
    for stem, rec in bibmap.items():
        if stem in seen:
            continue
        ft = rec.get("fulltext", "yes").strip().lower()
        if ft == "rejected":
            continue          # deliberately excluded; keeps it out of the queue too
        if ft in ("no", "no-fulltext", "stub"):
            rows.append((stem, rec["bibkey"] or "-", rec["tradition"], "0", "0", "-",
                         "no-fulltext"))
            stubs += 1
        else:
            print(f"  MISSING TEXT (bibmap says fulltext=yes): {stem}", file=sys.stderr)

    rows.sort(key=lambda r: r[0] + ".txt")  # match the old glob order exactly
    hdr = ("slug", "bibkey", "tradition", "kb", "lines", "ocr%", "status")
    c.manifest.parent.mkdir(parents=True, exist_ok=True)
    c.manifest.write_text("\n".join("\t".join(r) for r in [hdr] + rows) + "\n",
                          encoding="utf-8")
    print(f"{len(rows)} rows ({stubs} metadata-only stubs) -> {c.manifest}")
    for s in unmapped:
        print(f"  UNMAPPED (add a row to {c.bibmap.name}): {s}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
