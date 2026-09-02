#!/usr/bin/env python3
"""Create a corpus from what you already have: a folder of PDFs, a .bib, or both.

Writes the skeleton and a lit-corpus.json, then resolves every input to real
metadata and puts it in the SAME review queue the expansion pipeline uses
(index/candidates.jsonl + index/CANDIDATES.md). Nothing is ingested here: you
mark the queue, and `lit-expand`'s ingest.py does the rest. One review gate,
one ingest path, one set of formats.

  init_corpus.py ~/corpora/alg-top --name alg-top --pdfs ~/Downloads/pdfs
  init_corpus.py ./chem-dump --bib ~/paper/refs.bib --pdfs ~/Downloads/chem
  init_corpus.py ./chem-dump --bib refs.bib --offline      # no network at all

PDFs are pre-marked `[x]`: you chose those files, so the screening call is
already yours. Bibliography entries are pre-marked `[ ]` -- a paper's .bib is
usually full of background that does not belong in a topical corpus, and
deciding that is exactly what the gate is for.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / "lib"))
sys.path.insert(0, str(HERE.parents[2] / "lit-expand" / "scripts"))
import litcorpus
import _lib as L
import ingest as IG


def pdf_title(path):
    """Best-effort title from a PDF's first page: the longest of the first few
    non-trivial lines. Crude, and only ever used to look a DOI up -- the
    resolved Crossref record is what gets recorded."""
    try:
        r = subprocess.run(["pdftotext", "-l", "1", str(path), "-"],
                           capture_output=True, timeout=120)
        lines = [" ".join(l.split()) for l in
                 r.stdout.decode("utf-8", "replace").splitlines()]
    except Exception:
        return ""
    cand = [l for l in lines[:40] if 20 <= len(l) <= 200 and
            not re.search(r"@|http|doi|arxiv|vol\.|issn|copyright", l, re.I)]
    return max(cand, key=len) if cand else ""


def from_pdfs(d, offline):
    """One record per PDF, resolved by embedded DOI, then by first-page title."""
    out = []
    pdfs = sorted(Path(d).expanduser().glob("*.pdf"))
    print(f"scanning {len(pdfs)} PDFs in {d}")
    for pdf in pdfs:
        doi = IG.pdf_doi(pdf)
        meta = {}
        if not offline:
            meta = L.crossref_meta(doi) if doi else {}
            if not meta:
                t = pdf_title(pdf)
                if t:
                    doi2 = L.crossref_doi(t)
                    meta = L.crossref_meta(doi2) if doi2 else {}
        title = meta.get("title") or pdf_title(pdf) or pdf.stem.replace("_", " ")
        rec = {
            "id": "", "doi": (meta.get("doi") or doi or "").lower(),
            "title": " ".join(title.split()),
            "year": meta.get("year"), "authors": meta.get("authors", ""),
            "venue": meta.get("venue", ""), "abstract": "", "oa_pdf": "",
            "cited_by": 0, "arxiv": "", "local_pdf": str(pdf),
            "seeds_back": [], "seeds_fwd": [], "origin": "pdf",
        }
        how = "doi" if meta and doi else ("title" if meta else "filename only")
        print(f"  [{how:>13}] {rec['title'][:66]}")
        out.append(rec)
    return out


def from_bib(path, offline):
    """One record per bibliography entry. A .bib gives clean keys and titles but
    no text: these become stubs unless acquisition succeeds at ingest time."""
    entries = L.parse_refs_bib(Path(path).expanduser())
    print(f"parsed {len(entries)} entries from {path}")
    out = []
    for key, e in entries.items():
        title = re.sub(r"\s+", " ", e.get("title", "")).strip()
        if not title:
            continue
        doi = (e.get("doi") or "").lower().replace("https://doi.org/", "")
        if not doi and not offline:
            # Hand-written entries often lack a DOI; the 0.80 cutoff inside
            # crossref_doi is what stops a near-miss becoming a wrong paper.
            doi = L.crossref_doi(title, e.get("author", ""), e.get("year", ""))
        out.append({
            "id": "", "doi": doi, "title": title, "year": e.get("year"),
            "authors": e.get("author", ""),
            "venue": e.get("journal") or e.get("booktitle") or "",
            "abstract": "", "oa_pdf": "", "cited_by": 0, "arxiv": "",
            "bibkey": key, "seeds_back": [], "seeds_fwd": [], "origin": "bib",
        })
        print(f"  [{'doi' if doi else 'no doi':>13}] {key}: {title[:56]}")
    return out


def dedup(recs):
    """Collapse on DOI and on normalised title -- a folder of PDFs and the .bib
    that describes them overlap by design, and that overlap is the good case:
    the bib entry contributes the key, the PDF contributes the text."""
    out, by_doi, by_title = [], {}, {}
    for r in recs:
        d, t = r.get("doi") or "", L.norm_title(r["title"])
        prev = by_doi.get(d) if d else None
        prev = prev if prev is not None else by_title.get(t)
        if prev is not None:
            for k, v in r.items():                 # fill gaps, never overwrite
                if v and not prev.get(k):
                    prev[k] = v
            continue
        out.append(r)
        if d:
            by_doi[d] = r
        if t:
            by_title[t] = r
    return out


def write_queue(c, recs):
    c.candidates.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
        encoding="utf-8")
    n_pdf = sum(1 for r in recs if r.get("local_pdf"))
    head = [
        f"# Init queue — corpus '{c.name}'",
        "",
        f"{len(recs)} works: {n_pdf} with a local PDF, {len(recs) - n_pdf} from the "
        f"bibliography (metadata only).",
        "",
        "Rows with a local PDF are pre-marked `[x]` — you chose those files. Rows from "
        "a bibliography are pre-marked `[ ]`: a paper's .bib is mostly background, and "
        "deciding what belongs in a topical corpus is what this gate is for.",
        "",
        "- `[x]` ingest full text  ·  `[s]` stub (metadata only)  ·  `[ ]` skip",
        "",
        "Then: `python3 <plugin>/skills/lit-expand/scripts/ingest.py --from-queue "
        f"--corpus {c.root}`",
        "",
        "| | ref | src | year | title | venue | doi |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        ref = L.ref_id(r)
        mark = "x" if r.get("local_pdf") else " "
        t = " ".join(r["title"].split()).replace("|", "/")[:70]
        v = (r.get("venue") or "")[:24].replace("|", "/")
        head.append(f"| `[{mark}]` | `{ref}` | {r.get('origin','?')} | "
                    f"{r.get('year') or '?'} | {t} | {v} | {r.get('doi') or '—'} |")
    c.queue.write_text("\n".join(head) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="corpus directory to create")
    ap.add_argument("--name", help="corpus name (default: directory name)")
    ap.add_argument("--description", default="")
    ap.add_argument("--pdfs", metavar="DIR", help="folder of PDFs you already have")
    ap.add_argument("--bib", metavar="FILE", help="a .bib to seed metadata from")
    ap.add_argument("--traditions", default="",
                    help="comma-separated tradition names (fill cues in later)")
    ap.add_argument("--paper-bib", metavar="PATH",
                    help="an existing project .bib to read and append to, "
                         "instead of the corpus's own index/refs.bib")
    ap.add_argument("--cited-from", metavar="PATH",
                    help="a .bbl whose cited keys are excluded from harvests")
    ap.add_argument("--offline", action="store_true",
                    help="no network: record what the files themselves say")
    args = ap.parse_args()

    root = Path(args.target).expanduser().resolve()
    cfg_path = root / litcorpus.CONFIG_NAME
    if cfg_path.is_file():
        print(f"{cfg_path} exists; leaving the config alone and refreshing the queue")
        c = litcorpus.load(cfg_path)
    else:
        root.mkdir(parents=True, exist_ok=True)
        trads = {t.strip(): [] for t in args.traditions.split(",") if t.strip()}
        cfg = litcorpus.default_config(
            args.name or root.name, args.description, trads,
            bib=args.paper_bib, cited_from=args.cited_from)
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        c = litcorpus.load(cfg_path)
        print(f"created {cfg_path}")
    c.ensure_dirs()
    L.use(c)

    if not c.bibmap.is_file():
        L.write_tsv(c.bibmap, ("slug", "bibkey", "tradition", "fulltext", "doi",
                               "openalex", "added"), [])

    recs = []
    if args.pdfs:
        recs += from_pdfs(args.pdfs, args.offline)
    if args.bib:
        recs += from_bib(args.bib, args.offline)
    if not recs:
        print("nothing to queue: give --pdfs and/or --bib", file=sys.stderr)
        print(f"\n{c.describe()}")
        return 0 if cfg_path.is_file() else 1

    recs = dedup(recs)
    write_queue(c, recs)
    print(f"\n{len(recs)} works -> {c.queue}")
    print("Review and mark the queue, then run ingest.py --from-queue.")
    print("Nothing has been ingested yet — that is deliberate.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except L.RateLimited as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(2)
