#!/usr/bin/env python3
"""Regenerate <corpus>/index/WANTED.md from the current stubs.

Every `fulltext=no` row in bibmap.tsv is a paper judged relevant but not
obtainable. This renders them as a shopping list ordered by citation degree, so
the ones worth spending institutional access on are at the top.

Run after any ingest that creates stubs.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import _lib as L
import litcorpus

HEAD = """# Wanted — relevant papers with no reachable full text

Corpus **{corpus}**. {n} papers, ordered by citation degree (how many corpus sources
they connect to). Registered as metadata-only stubs: `lit-claim-search` reports them
as **unsearched**, so a null result never masquerades as evidence of novelty.

Most are behind publishers that block programmatic fetching outright (Elsevier
returns 403, MDPI serves a Cloudflare challenge). They need institutional access.

## How to add them

Download any of these, drop them in one folder, then:

```bash
python3 {ingest} --promote-dir ~/Downloads --corpus {root}
```

Each PDF is matched to its stub by the DOI embedded in the file, falling back to a
fuzzy filename match — so opaque publisher filenames like
`1-s2.0-S0303264719...-main.pdf` work as-is. Unmatched files are reported, not
guessed at.

| deg | year | title | venue | doi |
|---|---|---|---|---|"""


def slugify(t):
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", (t or "").strip()).strip("_"))[:120]


def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    args = ap.parse_args()
    try:
        c = L.use(litcorpus.from_args(args))
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1

    stubs = {r["slug"]: r for r in L.read_tsv(c.bibmap)
             if r.get("fulltext") == "no"}
    src = c.candidates
    recs = {}
    if src.is_file():
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[slugify(r["title"])] = r

    rows = []
    for slug, b in stubs.items():
        cand = recs.get(slug, {})
        deg = len(set(cand.get("seeds_back", [])) | set(cand.get("seeds_fwd", [])))
        rows.append((deg,
                     " ".join((cand.get("title") or slug.replace("_", " ")).split()),
                     cand.get("year") or "?", b.get("doi", "-"),
                     cand.get("venue") or "?"))
    rows.sort(key=lambda r: (-r[0], -(int(r[2]) if str(r[2]).isdigit() else 0)))

    def tilde(p):
        try:
            return "~/" + str(Path(p).relative_to(Path.home()))
        except ValueError:
            return str(p)
    out = [HEAD.format(n=len(rows), corpus=c.name,
                       ingest=tilde(Path(__file__).resolve().parent / "ingest.py"),
                       root=tilde(c.root))]
    for deg, title, year, doi, venue in rows:
        link = f"[{doi}](https://doi.org/{doi})" if doi and doi != "-" else "—"
        out.append(f"| {deg} | {year} | {title[:74].replace('|', '/')} | "
                   f"{venue[:24].replace('|', '/')} | {link} |")
    # DOI appendix, GENERATED (never hand-maintained). It used to be appended by
    # hand and this generator silently destroyed it on every run.
    dois = [d for _, _, _, d, _ in rows if d and d != "-"]
    out += ["", "---", "", "## Still missing — DOIs", "",
            "Generated from the stub rows above; do not hand-edit, it is rewritten",
            "on every run. One DOI per line, for `ingest.py --doi`:", "", "```"]
    out += dois
    out += ["```", ""]
    c.wanted.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} wanted papers ({len(dois)} with DOIs) -> {c.wanted}")


if __name__ == "__main__":
    sys.exit(main() or 0)
