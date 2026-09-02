#!/usr/bin/env python3
"""Stage 5 -- add an approved candidate to the corpus.

Does the mechanical half of ingestion: fetch, extract, slug, and register the
paper in every place the two skills read from. The judgement half -- the
CORPUS-MAP routing block -- is yours; see references/ingest-checklist.md.

  # after marking rows [x] / [s] in index/CANDIDATES.md
  python3 ingest.py --from-queue
  python3 ingest.py --from-queue --dry-run

  # one-offs
  python3 ingest.py --doi 10.1007/bf02476988
  python3 ingest.py --pdf ~/Downloads/paper.pdf --title "..." --bibkey Foo2020 \\
                    --tradition automata          # a PDF you obtained yourself

A paper with no reachable full text is NOT dropped. It is registered as a
metadata-only stub (fulltext=no) and listed in index/WANTED.md. That keeps the
gap visible: lit-claim-search reports stubs as unsearched, so a null result can
never masquerade as evidence of novelty.
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import _lib as L
import litcorpus


def guess_tradition(rec, c):
    """Provisional dialect from vocabulary, using the corpus's own cue lists in
    config order (most specific first). A guess only -- the tradition column
    drives cross-dialect routing in lit-claim-search, so the ingest checklist
    must confirm it against the actual text."""
    blob = ((rec.get("title") or "") + " " + (rec.get("abstract") or "")).lower()
    for trad, cues in c.tradition_cues():
        if any(cue in blob for cue in cues):
            return trad
    return c.default_tradition


def already_have(c):
    """Normalised titles of everything in the corpus, for a PREFIX-aware check.

    Exact matching is not enough: the corpus holds "Some Thoughts on A. H.
    Louie's More Than Life Itself" while the frontier offers the same paper
    carrying its subtitle, so the strings differ by a tail."""
    out = []
    for r in L.read_tsv(c.bibmap):
        out.append((L.norm_title(r["slug"].replace("_", " ")), r["slug"]))
    for r in L.read_tsv(c.seeds):
        t = r.get("oa_title", "-")
        if t not in ("-", ""):
            out.append((L.norm_title(t), r["slug"]))
    return [(t, s) for t, s in out if len(t) > 24]


def is_duplicate(title, have):
    n = L.norm_title(title)
    if len(n) < 25:
        return None
    for t, slug in have:
        if n == t or n.startswith(t[:40]) or t.startswith(n[:40]):
            return slug
    return None


def slugify(title):
    """Match the corpus naming convention: Words_Joined_By_Underscores."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", (title or "").strip()).strip("_")
    return re.sub(r"_+", "_", s)[:120] or "untitled"


def make_bibkey(authors, year, taken):
    first = (authors or "").split(",")[0].strip()
    # Fold diacritics rather than deleting them: stripping non-ASCII turned
    # "Baianu" into "Bianu" and collided two different papers on one key.
    first = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode()
    surname = re.sub(r"[^A-Za-z]", "", first.split()[-1]) if first.split() else "Anon"
    base = f"{surname}{year or ''}" or "Anon"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}{chr(ord('a') + n - 2)}"
    return key


def bibtex_authors(s, already_bibtex=False):
    """Providers give "Ada Lovelace, Alan Turing"; BibTeX wants
    "Lovelace, A. and ...".

    A record that came from a .bib already carries the BibTeX form, and running
    the conversion on it turns "Riehl, Emily" into "Riehl and Emily" -- two
    authors, one of them a first name. So pass those through untouched, and
    treat an explicit " and " as the same signal."""
    if already_bibtex or " and " in (s or ""):
        return (s or "").strip()
    out = []
    for a in (s or "").split(","):
        a = a.strip().replace(" et al.", "")
        if not a:
            continue
        parts = a.split()
        if len(parts) == 1:
            out.append(parts[0])
        else:
            out.append(f"{parts[-1]}, {' '.join(p[0] + '.' for p in parts[:-1])}")
    return " and ".join(out)


UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _raw(url, limit=60_000_000):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=120) as fh:
            return fh.read(limit), fh.geturl()
    except Exception as e:
        code = getattr(e, "code", "")
        print(f"    fetch {type(e).__name__} {code}: {url[:64]}", file=sys.stderr)
        return None, url


def _citation_pdf_url(html, base):
    """Highwire `citation_pdf_url` meta tag. Emitted by most repositories and
    many publishers, and it is what turns a DOI landing page into a PDF."""
    for pat in (rb'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
                rb'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']'):
        m = re.search(pat, html, re.I)
        if m:
            return urllib.parse.urljoin(base, m.group(1).decode("utf-8", "replace"))
    return ""


def europepmc_pdf(doi):
    if not doi:
        return ""
    q = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:%22"
         + urllib.parse.quote(doi) + "%22&format=json&resultType=core")
    try:
        with urllib.request.urlopen(q, timeout=45) as fh:
            res = json.loads(fh.read()).get("resultList", {}).get("result", [])
    except Exception:
        return ""
    if res and res[0].get("isOpenAccess") == "Y" and res[0].get("pmcid"):
        return f"https://europepmc.org/articles/{res[0]['pmcid']}?pdf=render"
    return ""


def fetch_pdf(url, dst, doi="", arxiv=""):
    """Acquisition ladder. A bare DOI or repository link is a landing page, not
    a PDF -- 14 of the first batch's 36 failures were exactly that."""
    tries = []
    if arxiv:
        tries.append(f"https://arxiv.org/pdf/{arxiv}")
    pmc = europepmc_pdf(doi)
    if pmc:
        tries.append(pmc)
    if url:
        tries.append(url)

    for u in tries:
        data, final = _raw(u)
        if not data:
            continue
        if data[:4] == b"%PDF":
            dst.write_bytes(data)
            return True
        pdf = _citation_pdf_url(data, final)
        if pdf and pdf != u:
            data2, _ = _raw(pdf)
            if data2 and data2[:4] == b"%PDF":
                dst.write_bytes(data2)
                return True
        print(f"    landing page, no PDF: {final[:62]}", file=sys.stderr)
    return False


def extract(pdf, txt, layout=False):
    cmd = ["pdftotext"] + (["-layout"] if layout else []) + [str(pdf), str(txt)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except Exception as e:
        print(f"    pdftotext failed: {e}", file=sys.stderr)
        return 0
    return txt.stat().st_size if txt.is_file() else 0


def pdf_doi(path):
    """Pull a DOI out of a PDF's first pages -- the reliable way to match a
    hand-downloaded file to a stub, since publisher filenames are opaque
    (`1-s2.0-S0303264719...-main.pdf`)."""
    try:
        r = subprocess.run(["pdftotext", "-l", "2", str(path), "-"],
                           capture_output=True, timeout=120)
        txt = r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""
    m = re.search(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", txt)
    return m.group(1).rstrip(".,;)").lower() if m else ""


def promote_dir(d, c):
    """Match each PDF in `d` to a fulltext=no row and return ingest records."""
    rows = {r["slug"]: r for r in L.read_tsv(c.bibmap)
            if r.get("fulltext") == "no"}
    by_doi = {r["doi"].lower(): s for s, r in rows.items() if r.get("doi", "-") != "-"}
    out, unmatched = [], []
    for pdf in sorted(Path(d).glob("*.pdf")):
        slug = by_doi.get(pdf_doi(pdf))
        if not slug:  # fall back to fuzzy title match on the filename
            stem = L.norm_title(pdf.stem)
            best, br = None, 0.0
            for sl in rows:
                r = L.title_ratio(stem, sl.replace("_", " "))
                if r > br:
                    best, br = sl, r
            slug = best if br >= 0.60 else None
        if not slug:
            unmatched.append(pdf.name)
            continue
        r = rows[slug]
        out.append({"slug": slug, "bibkey": r["bibkey"], "tradition": r["tradition"],
                    "doi": r.get("doi", ""), "local_pdf": str(pdf), "title": slug,
                    "authors": "", "year": "", "venue": "", "id": ""})
    for u in unmatched:
        print(f"  UNMATCHED (ingest by hand with --pdf --slug): {u}", file=sys.stderr)
    print(f"matched {len(out)} PDFs to stubs")
    return out


def register(slug, bibkey, tradition, fulltext, doi, oaid, c):
    path = c.bibmap
    rows = L.read_tsv(path)
    hdr = ("slug", "bibkey", "tradition", "fulltext", "doi", "openalex", "added")
    for r in rows:
        if r["slug"] == slug:
            if r.get("fulltext") != fulltext:
                r["fulltext"] = fulltext
                L.write_tsv(path, hdr, [[x.get(c, "-") for c in hdr] for x in rows])
                print(f"    bibmap: {slug[:44]} fulltext -> {fulltext}")
            return
    rows.append({"slug": slug, "bibkey": bibkey or "-", "tradition": tradition,
                 "fulltext": fulltext, "doi": doi or "-", "openalex": oaid or "-",
                 "added": "lit-expand"})
    L.write_tsv(path, hdr, [[r.get(c, "-") for c in hdr] for r in rows])


def append_bib(key, rec, c):
    if not key or key in L.parse_refs_bib():
        return
    fields = [("title", rec.get("title")),
              ("author", bibtex_authors(rec.get("authors"),
                                        rec.get("origin") == "bib")),
              ("journal", rec.get("venue")), ("year", rec.get("year")),
              ("doi", rec.get("doi"))]
    body = "".join(f"  {k} = {{{v}}},\n" for k, v in fields if v)
    c.bib.parent.mkdir(parents=True, exist_ok=True)
    text = c.bib.read_text(encoding="utf-8") if c.bib.is_file() else ""
    banner = ("\n%% ---- machine-generated by lit-expand; UNVERIFIED ----\n"
              "%% Check author/journal/type against the title page before citing.\n")
    with c.bib.open("a", encoding="utf-8") as fh:
        if "machine-generated by lit-expand" not in text:
            fh.write(banner)
        fh.write(f"\n@article{{{key},\n{body}}}\n")
    print(f"    {c.bib.name} += {key}")


def want(rec, why, c):
    path = c.wanted
    if not path.is_file():
        path.write_text("# Wanted: relevant papers with no reachable full text\n\n"
                        "Registered as metadata-only stubs. Drop a PDF in and run\n"
                        "`ingest.py --pdf <file> --slug <slug>` to promote one.\n\n",
                        encoding="utf-8")
    line = (f"- **{rec.get('title')}** ({rec.get('year')}) · "
            f"doi `{rec.get('doi') or '-'}` · {rec.get('venue') or '?'} — {why}\n")
    if line not in path.read_text(encoding="utf-8"):
        path.open("a", encoding="utf-8").write(line)


def ingest_one(rec, tradition, args, taken, c, have=()):
    title = rec.get("title") or ""
    slug = rec.get("slug") or slugify(title)
    if (c.texts / f"{slug}.txt").is_file():
        print(f"  SKIP (already in texts/) {slug[:60]}")
        return None
    dup = None if rec.get("slug") else is_duplicate(title, have)
    if dup:
        print(f"  SKIP (duplicate of corpus '{dup[:52]}')\n    {title[:64]}")
        return None
    key = rec.get("bibkey") or make_bibkey(rec.get("authors"), rec.get("year"), taken)
    print(f"  {slug[:66]}\n    bibkey={key} tradition={tradition}")
    if args.dry_run:
        return None

    c.texts.mkdir(parents=True, exist_ok=True)
    txt = c.texts / f"{slug}.txt"
    got = 0
    local = rec.get("local_pdf")
    tmp = c.cache / f"{slug}.pdf"
    if local:
        got = extract(Path(local), txt, args.layout)
    elif fetch_pdf(rec.get("oa_pdf", ""), tmp, rec.get("doi", ""),
                   rec.get("arxiv", "")):
        got = extract(tmp, txt, args.layout)
        tmp.unlink(missing_ok=True)

    if got > 1024:
        print(f"    extracted {got/1024:.0f} KB -> texts/{slug}.txt")
        register(slug, key, tradition, "yes", rec.get("doi"), rec.get("id"), c)
    else:
        txt.unlink(missing_ok=True)
        why = "no OA pdf" if not rec.get("oa_pdf") else "fetch/extract failed"
        print(f"    STUB ({why})")
        register(slug, key, tradition, "no", rec.get("doi"), rec.get("id"), c)
        want(rec, why, c)
    append_bib(key, rec, c)
    taken.add(key)
    return slug


def from_queue(path, c):
    """Read [x]/[s] marks out of CANDIDATES.md and pair them with the records."""
    if not path.is_file():
        print(f"no {path} -- run rank.py first", file=sys.stderr)
        return []
    marks, refs = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`\[([xs ])\]`\s*\|\s*`([^`]+)`\s*\|", line)
        if m:
            refs.append(m.group(2).strip())
            if m.group(1) in ("x", "s"):
                marks[m.group(2).strip()] = m.group(1)
    if not marks:
        print("nothing marked [x] or [s] in the queue", file=sys.stderr)
        return []
    out, seen = [], set()
    for line in c.candidates.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ref = L.ref_id(r)
        if ref in marks:
            seen.add(ref)
            if marks[ref] == "s":
                r["oa_pdf"] = ""              # force a stub
            out.append(r)
    missing = [m for m in marks if m not in seen]
    if missing:
        print(f"  {len(missing)} marked row(s) match no candidate: "
              f"{', '.join(missing[:6])}", file=sys.stderr)
        # Refs from before the hashed scheme were the first ten letters of
        # the title ("elementsof"); current refs always carry digits. Say so,
        # or this reads as "the queue is empty" against a queue full of marks.
        if any(re.fullmatch(r"[a-z]+", x) for x in refs):
            print("  this queue was written by an older rank.py / init_corpus.py "
                  "(title-prefix refs). Regenerate it -- rank.py for a frontier queue, "
                  "init_corpus.py for an init queue -- and re-mark with mark.py.",
                  file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-queue", action="store_true")
    ap.add_argument("--promote-dir", metavar="DIR",
                    help="scan DIR for PDFs you downloaded by hand and match "
                         "each to a stub, by embedded DOI then by title")
    ap.add_argument("--retry-stubs", action="store_true",
                    help="re-attempt every fulltext=no row with the full ladder")
    ap.add_argument("--doi"); ap.add_argument("--openalex")
    ap.add_argument("--pdf"); ap.add_argument("--title"); ap.add_argument("--slug")
    ap.add_argument("--bibkey")
    ap.add_argument("--tradition", help="one of the corpus's declared traditions")
    litcorpus.add_argument(ap)
    ap.add_argument("--layout", action="store_true",
                    help="pdftotext -layout; better for tables, worse for 2-column scans")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    # Children (normalize/build_manifest) write straight to the terminal, so an
    # unflushed parent reports its work after theirs and reads as out of order.
    sys.stdout.reconfigure(line_buffering=True)
    try:
        c = L.use(litcorpus.from_args(args))
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1
    if args.tradition and c.traditions and args.tradition not in c.traditions:
        print(f"unknown tradition '{args.tradition}'; this corpus declares: "
              f"{', '.join(c.tradition_names)}", file=sys.stderr)
        return 1
    print(f"{c.describe()}\n")

    taken = set(L.parse_refs_bib())
    recs = []
    if args.promote_dir:
        recs = promote_dir(args.promote_dir, c)
    elif args.retry_stubs:
        stubs = {r["slug"]: r for r in L.read_tsv(c.bibmap)
                 if r.get("fulltext") == "no"}
        for line in c.candidates.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            cand = json.loads(line)
            sl = slugify(cand["title"])
            if sl in stubs:
                cand["slug"] = sl
                cand["bibkey"] = stubs[sl]["bibkey"]
                cand["tradition"] = stubs[sl]["tradition"]
                recs.append(cand)
        print(f"retrying {len(recs)} of {len(stubs)} stubs")
    elif args.from_queue:
        recs = from_queue(c.queue, c)
    elif args.pdf:
        recs = [{"title": args.title or Path(args.pdf).stem, "slug": args.slug,
                 "bibkey": args.bibkey, "local_pdf": args.pdf, "doi": args.doi or "",
                 "authors": "", "year": "", "venue": "", "id": ""}]
    elif args.doi or args.openalex:
        flt = f"doi:{args.doi}" if args.doi else f"openalex_id:{args.openalex}"
        d = L.get("works", {"filter": flt, "select": L.WORK_FIELDS, "per-page": 1})
        r = (d or {}).get("results") or []
        if not r:
            print("not found in OpenAlex", file=sys.stderr)
            return 1
        w = r[0]
        recs = [{"id": w["id"].rsplit("/", 1)[-1], "title": w.get("title") or "",
                 "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                 "year": w.get("publication_year"), "authors": L.authors(w),
                 "venue": L.venue(w), "oa_pdf": L.oa_pdf(w),
                 "slug": args.slug, "bibkey": args.bibkey}]
    else:
        ap.error("give --from-queue, --promote-dir, --retry-stubs, "
                 "--doi, --openalex or --pdf")

    if not recs:
        return 1
    added = []
    have = already_have(c)
    for r in recs:
        trad = args.tradition or r.get("tradition") or guess_tradition(r, c)
        s = ingest_one(r, trad, args, taken, c, have)
        if s:
            added.append(s)

    if added and not args.dry_run:
        skills = Path(__file__).resolve().parents[2]
        for script in ("normalize.py", "build_manifest.py"):
            subprocess.run([sys.executable,
                            str(skills / "lit-claim-search" / "scripts" / script),
                            "--corpus", str(c.root)], check=False)
        print(f"\n{len(added)} ingested. NOW DO THE JUDGEMENT HALF:\n"
              f"  write a routing block in {c.corpus_map} for each "
              f"(references/ingest-checklist.md),\n"
              f"  set the tradition honestly, and extend {c.glossary} "
              f"if the dialect is new.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except L.RateLimited as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(2)
