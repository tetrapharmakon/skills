#!/usr/bin/env python3
"""Stage 1 -- resolve every corpus source to an OpenAlex work.

Seeds are the CORPUS (index/bibmap.tsv), not the attached paper's bibliography:
the point is to grow the body of texts, and a paper's .bib is usually full of
general background whose citation neighbourhoods would flood the harvest.

Writes index/SEEDS.tsv. Existing hand-corrections are preserved --
rows whose `pin` column is `y` are never re-resolved, which is how you fix a
bad automatic match permanently. Re-run freely.

  python3 resolve_seeds.py            # resolve anything unresolved
  python3 resolve_seeds.py --force    # re-resolve everything except pinned rows

`hub=y` marks a seed with a huge, off-topic citing literature -- a foundational
text of some neighbouring field, cited by thousands of works that have nothing
to do with this corpus. Hubs contribute their REFERENCES but never their CITERS.
Which traditions can produce hubs, and above what citation count, comes from the
corpus config (`harvest.hub_traditions`, `harvest.hub_cited_by`); both are a
starting guess, so edit the column by hand when it guesses wrong.
"""
import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import _lib as L
import litcorpus

MATCH_CUTOFF = 0.80
# A hub is imported machinery with a huge off-topic citing literature, not
# merely a well-cited seed: a central work OF this field can have 700 citers
# that are exactly the ones we want. So hub detection is restricted to the
# traditions the corpus declares as imported (`harvest.hub_traditions`), and
# never applied to the field's own tradition. Override the column by hand.
HDR = ("slug", "bibkey", "tradition", "openalex", "doi", "year",
       "cited_by", "n_refs", "hub", "match", "pin", "oa_title")


def slug_to_title(slug):
    return slug.replace("_", " ").replace("-", " ").strip()


def searchable(title):
    """OpenAlex's title.search filter rejects commas (they separate filters),
    and chokes on $ { } ( ). "Categories of (M,R)-systems" is a 400 as written."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]+", " ", title or "")).strip()


def by_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower().replace("https://doi.org/", "").replace("doi:", "")
    d = L.get("works", {"filter": f"doi:{doi}", "select": L.WORK_FIELDS, "per-page": 1})
    r = (d or {}).get("results") or []
    return r[0] if r else None


def by_title(title, year, minlen):
    q = L.searchable(title, minlen)
    if not q:
        return None
    flt = f"title.search:{q}"
    if year and str(year).isdigit():
        y = int(year)
        flt += f",publication_year:{y-1}|{y}|{y+1}"
    d = L.get("works", {"filter": flt, "select": L.WORK_FIELDS, "per-page": 10})
    results = (d or {}).get("results") or []
    if not results:
        d = L.get("works", {"filter": f"title.search:{q}",
                            "select": L.WORK_FIELDS, "per-page": 10})
        results = (d or {}).get("results") or []
    best, best_r = None, 0.0
    for w in results:
        r = L.title_ratio(title, w.get("title"))
        if r > best_r:
            best, best_r = w, r
    return best if best_r >= MATCH_CUTOFF else None


def resolve(title, year, doi):
    """A ladder, cheapest and most certain first. Returns (work, doi, how).

    Every rung is here because a real seed needed it: bare title.search fails
    on the mangled Springer scans, and Crossref rescues them by DOI. Nothing
    below the similarity cutoff is ever accepted -- an early version took the
    top hit and silently filed Warner's 1982 paper under Arbib's slug."""
    w = by_doi(doi)
    if w:
        return w, doi, "doi"
    for minlen, how in ((1, "title"), (2, "title-trimmed")):
        w = by_title(title, year, minlen)
        if w:
            return w, (w.get("doi") or "").replace("https://doi.org/", ""), how
    cdoi = L.crossref_doi(title, "", year, cutoff=MATCH_CUTOFF)
    if cdoi:
        w = by_doi(cdoi)
        # OpenAlex does not index every Crossref DOI; keep the DOI regardless,
        # it is still the right identifier for acquisition and for refs.bib.
        return w, cdoi, "crossref" if w else "crossref-doi-only"
    return None, doi, "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-resolve rows that already have an OpenAlex id")
    litcorpus.add_argument(ap)
    args = ap.parse_args()

    try:
        c = L.use(litcorpus.from_args(args))
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1
    print(f"{c.describe()}\n")

    bib = L.parse_refs_bib()
    seedrows = L.read_tsv(c.bibmap)
    if not seedrows:
        print(f"no {c.bibmap} -- build the corpus first", file=sys.stderr)
        return 1
    prev = {r["slug"]: r for r in L.read_tsv(c.seeds)}

    rows, stopped = [], False
    for i, rec in enumerate(seedrows):
        if stopped:  # keep whatever we knew before; never record an absence
            old = prev.get(rec["slug"], {})
            rows.append([old.get(col, "-") for col in HDR] if old else
                        [rec["slug"], rec["bibkey"], rec["tradition"],
                         "-", "-", "-", "-", "-", "n", "pending", "n", "-"])
            continue
        slug, key = rec["slug"], rec["bibkey"]
        old = prev.get(slug, {})
        if old.get("pin") == "y" or (old.get("openalex", "-") != "-" and not args.force):
            rows.append([old.get(col, "-") for col in HDR])
            continue

        b = bib.get(key, {}) if key != "-" else {}
        title = b.get("title") or slug_to_title(slug)
        author = b.get("author", "")
        try:
            w, doi, match = resolve(title, b.get("year", ""), b.get("doi", ""))
        except L.RateLimited as e:
            print(f"\n  STOPPED at seed {i+1}/{len(seedrows)}: {e}", file=sys.stderr)
            stopped = True
            old = prev.get(slug, {})
            rows.append([old.get(col, "-") for col in HDR] if old else
                        [slug, key, rec["tradition"], "-", "-", "-", "-", "-",
                         "n", "pending", "n", "-"])
            continue
        if w is None and author:  # retry Crossref with the author as a signal
            cdoi = L.crossref_doi(title, author, b.get("year", ""), MATCH_CUTOFF)
            time.sleep(0.1)
            if cdoi:
                w, doi, match = by_doi(cdoi), cdoi, "crossref"
                match = "crossref" if w else "crossref-doi-only"
        time.sleep(0.12)

        if w is None:
            if doi and doi != "-":
                rows.append([slug, key, rec["tradition"], "-", doi,
                             b.get("year", "-") or "-", "-", "-", "n",
                             "crossref-doi-only", "n", "-"])
                print(f"  DOI-ONLY    {doi:<32} {slug[:44]}")
                continue
            rows.append([slug, key, rec["tradition"], "-", "-",
                         b.get("year", "-") or "-", "-", "-", "n", "none", "n", "-"])
            print(f"  UNRESOLVED  {slug[:64]}")
            continue

        cited = w.get("cited_by_count", 0)
        hub = old.get("hub") if old.get("hub") in ("y", "n") else \
            ("y" if cited > c.hub_cited_by and rec["tradition"] in c.hub_traditions
             else "n")
        rows.append([
            slug, key, rec["tradition"], w["id"].rsplit("/", 1)[-1],
            (w.get("doi") or doi or "-").replace("https://doi.org/", "") or "-",
            w.get("publication_year", "-"), cited, len(w.get("referenced_works") or []),
            hub, match, "n", (w.get("title") or "-")[:90].replace("\t", " "),
        ])
        flag = "HUB " if hub == "y" else "    "
        print(f"  {flag}{match:<12} {cited:>6} cites  {slug[:56]}")

    L.write_tsv(c.seeds, HDR, rows)
    if stopped:
        print("\n  Quota exhausted mid-run. Rows already resolved were preserved;\n"
              "  unresolved ones stay marked and are retried automatically on the\n"
              "  next run (rows keep their OpenAlex id, so nothing is re-fetched).",
              file=sys.stderr)
    ok = sum(1 for r in rows if r[3] != "-")
    weak = sum(1 for r in rows if r[9] == "crossref-doi-only")
    print(f"\n{ok}/{len(rows)} resolved -> {c.seeds}"
          f"   ({weak} DOI-only: no OpenAlex record, so no citers to harvest)")
    return 2 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
