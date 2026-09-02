#!/usr/bin/env python3
"""Stage 2 -- enumerate the citation frontier of the corpus.

For every seed, collect the works it CITES (ancestors) and the works that CITE
it (descendants), then subtract everything already known. Result:
index/candidates.jsonl, one JSON object per unseen work.

Deliberately structural rather than lexical. A corpus spanning several research
traditions has disjoint vocabulary for the same ideas, so a keyword sweep both
misses papers that word things differently and drowns in papers sharing only
surface terms. A citation edge to a seed is much stronger evidence of belonging
than any phrase.

Default provider is **Semantic Scholar**, keyed by DOI: it is unmetered and
keyless, and it typically resolves far more of a corpus than OpenAlex ids do,
especially for old scanned journals. `--provider openalex` uses the metered
OpenAlex ids instead.

Hub seeds (see resolve_seeds.py) contribute references but not citers: a
foundational text of a neighbouring field has hundreds of citers and essentially
none concern this corpus.

  python3 harvest.py
  python3 harvest.py --provider openalex --max-citers 300
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import _lib as L
import litcorpus


def known(c):
    """What we must not propose: the corpus itself, plus the bibliography
    entries the attached paper actually cites. Uncited entries are deliberately
    NOT excluded -- they were collected once and dropped, so re-surfacing one
    with a citation-degree score is signal, not noise."""
    titles, dois = set(), set()
    bib = L.parse_refs_bib()
    for k in L.cited_keys():
        r = bib.get(k, {})
        if r.get("title"):
            titles.add(L.norm_title(r["title"]))
        if r.get("doi"):
            dois.add(r["doi"].lower().replace("https://doi.org/", ""))
    for r in L.read_tsv(c.bibmap):
        titles.add(L.norm_title(r["slug"].replace("_", " ")))
        if r.get("doi", "-") != "-":
            dois.add(r["doi"].lower())
    for r in L.read_tsv(c.seeds):
        if r.get("oa_title", "-") not in ("-", ""):
            titles.add(L.norm_title(r["oa_title"]))
        if r.get("doi", "-") != "-":
            dois.add(r["doi"].lower())
    return titles, dois


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=("s2", "openalex"), default="s2")
    ap.add_argument("--max-citers", type=int, default=0,
                    help="cap per edge direction (default: harvest.max_edges)")
    litcorpus.add_argument(ap)
    args = ap.parse_args()
    try:
        c = L.use(litcorpus.from_args(args))
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1
    cap = args.max_citers or c.max_edges

    seeds = L.read_tsv(c.seeds)
    if not seeds:
        print(f"no {c.seeds} -- run resolve_seeds.py first", file=sys.stderr)
        return 1
    field = "doi" if args.provider == "s2" else "openalex"
    usable = [r for r in seeds if r.get(field, "-") not in ("-", "")]
    print(f"{len(usable)}/{len(seeds)} seeds usable via {args.provider} "
          f"(keyed on {field})\n")

    kn_titles, kn_dois = known(c)
    cands, stopped = {}, False   # dedup key -> record + edge sets
    by_title = {}                # normalised title -> dedup key, for the
                                 # two-DOIs-one-paper collapse below

    def note(rec, slug, direction):
        r = L.s2_norm(rec) if args.provider == "s2" else rec
        tkey = L.norm_title(r["title"])
        key = r["doi"] or tkey
        if not key:
            return
        if tkey in kn_titles or (r["doi"] and r["doi"] in kn_dois):
            return
        # Same paper can carry two DOIs (Baianu 1973 has both a Springer and an
        # Elsevier one), so collapse on normalised title as well. Indexed rather
        # than scanned: a full frontier is ~1000 works reached by ~20k edges,
        # and a linear scan per edge made this stage quadratic.
        if tkey and tkey in by_title:
            cands[by_title[tkey]][direction].append(slug)
            return
        entry = cands.setdefault(key, {**r, "seeds_back": [], "seeds_fwd": []})
        if tkey:
            by_title.setdefault(tkey, key)
        entry[direction].append(slug)

    try:
        for r in usable:
            slug, ident = r["slug"], r[field]
            if args.provider != "s2":
                print("  openalex provider: use the previous release", file=sys.stderr)
                return 1
            refs = L.s2_edges(ident, "references", cap=cap)
            for x in refs:
                note(x, slug, "seeds_back")
            time.sleep(0.4)
            if r.get("hub") == "y":
                print(f"  refs {len(refs):>3} · citers  HUB (skipped)  {slug[:44]}")
                continue
            cits = L.s2_edges(ident, "citations", cap=cap)
            for x in cits:
                note(x, slug, "seeds_fwd")
            print(f"  refs {len(refs):>3} · citers {len(cits):>4}       {slug[:44]}")
            time.sleep(0.4)
    except L.RateLimited as e:
        print(f"\n  STOPPED: {e}\n  Writing the partial frontier; re-run to resume.",
              file=sys.stderr)
        stopped = True

    rows = list(cands.values())
    out = c.candidates
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    print(f"\n  {len(rows)} candidates -> {out}")
    return 2 if stopped else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except L.RateLimited as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(2)
