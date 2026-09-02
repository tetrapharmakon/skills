#!/usr/bin/env python3
"""Shared helpers for the lit-expand pipeline: bibliography parsing, provider
access (OpenAlex, Crossref, Semantic Scholar), and the title normalisation used
for deduplication.

Carries no path of its own. Every script binds a corpus first --
`L.use(litcorpus.from_args(args))` -- and all paths, the cache location and the
bibliography come from that corpus's lit-corpus.json.

OpenAlex is free and needs no key. Setting OPENALEX_MAILTO puts requests in
the faster "polite pool"; we never hardcode an address, since that would send
the user's email to a third party they did not ask us to contact.
"""
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import litcorpus  # noqa: E402

API = "https://api.openalex.org"
CORPUS = None  # bound by use(); the single source of every path
CACHE = None   # <corpus>/index/.cache, set by ensure_cache()


def use(c):
    """Bind the corpus every path in this module resolves against."""
    global CORPUS, CACHE
    CORPUS, CACHE = c, None
    return c


def corpus():
    if CORPUS is None:
        raise RuntimeError("no corpus bound: call L.use(litcorpus.from_args(args))")
    return CORPUS


class RateLimited(Exception):
    """OpenAlex budget exhausted. Emphatically NOT the same as "no such work":
    an early version conflated the two and silently demoted 25 correctly
    resolved seeds to unresolved. Callers must stop, never record an absence."""


def ensure_cache():
    global CACHE
    if CACHE is None:
        CACHE = corpus().cache
    return CACHE
WORK_FIELDS = (
    "id,doi,title,publication_year,publication_date,type,authorships,"
    "primary_location,cited_by_count,referenced_works,open_access,"
    "best_oa_location,abstract_inverted_index"
)


def searchable(title, minlen=1):
    """OpenAlex's title.search filter treats commas as filter separators and
    rejects $ { } ( ). Tokens shorter than `minlen` are dropped because the
    filter ANDs terms, so a stray "s" from "Rosen's" can zero out a query."""
    toks = [w for w in re.sub(r"[^A-Za-z0-9 ]+", " ", title or "").split()
            if len(w) >= minlen]
    return " ".join(toks)


def title_ratio(a, b):
    """Similarity on the alphanumeric skeleton. Calibrated against a real
    failure: the true record scored 0.95 while the three decoys the same query
    returned scored 0.41-0.48. Anything at/above 0.80 is the paper."""
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def crossref_doi(title, author="", year="", cutoff=0.80):
    """Crossref bibliographic search -> best DOI, or "".

    Indispensable for old scanned journals, whose publisher digitisations
    mangle the deposited titles -- one 1966 paper is deposited as "Categories of
    (l, R)-systems" -- so no title search against OpenAlex can reach them, while
    Crossref's fuzzy bibliographic query does."""
    q = " ".join(x for x in (author.split(",")[0], title, str(year)) if x)
    url = ("https://api.crossref.org/works?rows=6&select=DOI,title,issued"
           "&query.bibliographic=" + urllib.parse.quote(q))
    items = None
    for n in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lit-expand/1.0"})
            with urllib.request.urlopen(req, timeout=45) as fh:
                items = json.loads(fh.read().decode("utf-8"))["message"]["items"]
            break
        except Exception:
            time.sleep(1.5 * (n + 1))
    if not items:
        return ""
    best, best_r = "", 0.0
    for it in items:
        r = title_ratio(title, (it.get("title") or [""])[0])
        if r > best_r:
            best, best_r = it.get("DOI", ""), r
    return best if best_r >= cutoff else ""


def crossref_meta(doi):
    """DOI -> {title, authors, year, venue, doi}, or {} .

    Crossref rather than OpenAlex because init resolves a whole folder at once
    and OpenAlex's 1000/day budget is better spent on the citation frontier.
    Unmetered, keyless, and authoritative for what a publisher deposited."""
    if not doi:
        return {}
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi.strip().lower())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lit-tools/1.0"})
        with urllib.request.urlopen(req, timeout=45) as fh:
            m = json.loads(fh.read().decode("utf-8"))["message"]
    except Exception:
        return {}
    names = []
    for a in m.get("author") or []:
        nm = " ".join(x for x in (a.get("given"), a.get("family")) if x)
        if nm:
            names.append(nm)
    date = (m.get("issued") or {}).get("date-parts") or [[None]]
    return {
        "doi": (m.get("DOI") or "").lower(),
        "title": (m.get("title") or [""])[0],
        "authors": ", ".join(names[:4]) + (" et al." if len(names) > 4 else ""),
        "year": date[0][0] if date and date[0] else None,
        "venue": (m.get("container-title") or [""])[0],
        "type": m.get("type") or "",
    }


def norm_title(s):
    """Aggressive normalisation for dedup: the same folding normalize.py
    applies to the texts, so an OCR'd corpus title, a ligatured PDF title and
    a clean OpenAlex title collapse to one string."""
    return litcorpus.norm(s)


def ref_id(rec):
    """Ten-character handle printed in the review queue and read back by
    ingest.py, so the round trip through CANDIDATES.md is exact.

    Provider ids are unique already, so their prefix is enough. When there is
    none -- every record from lit-corpus-init, and the odd frontier record --
    hash the normalised title instead of taking its prefix: "Elements of a
    theory of simulation II" and "... III" share their first ten characters,
    and a prefix handle marked one of them and ingested both."""
    pid = rec.get("id") or ""
    if pid:
        return pid[:10]
    return hashlib.sha1(norm_title(rec.get("title", "")).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- bibliography

def parse_refs_bib(path=None):
    """key -> {type, title, author, year, doi, journal}. Deliberately small: a
    brace-counting scan, no bibtex library, since these files are hand-written.

    Defaults to the corpus's `bibliography.bib` -- an external project .bib when
    the corpus is attached to a paper, otherwise the corpus's own index/refs.bib.
    A corpus with neither is fine; it simply parses nothing."""
    path = Path(path) if path else corpus().bib
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
        etype, key = m.group(1).lower(), m.group(2).strip()
        i, depth = m.start() + m.group(0).index("{"), 0
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.start() + m.group(0).index("{") + 1:i]
        rec = {"type": etype}
        for f in ("title", "author", "year", "doi", "journal", "booktitle", "url"):
            fm = re.search(rf"\b{f}\s*=\s*", body, re.I)
            if not fm:
                continue
            j = fm.end()
            if j < len(body) and body[j] in "{\"":
                close = "}" if body[j] == "{" else "\""
                d, k = 0, j
                while k < len(body):
                    if body[k] == "{":
                        d += 1
                    elif body[k] == "}":
                        d -= 1
                        if d == 0 and close == "}":
                            break
                    elif body[k] == close and close == "\"" and k > j:
                        break
                    k += 1
                val = body[j + 1:k]
            else:
                val = body[j:].split(",")[0]
            val = re.sub(r"[{}]", "", val).strip().rstrip(",").strip()
            rec[f] = val
        out[key] = rec
    return out


def cited_keys(path=None):
    """Bibkeys actually cited in the attached paper, read from its .bbl. The
    rule: never dedup against bibliography entries the paper does not use --
    an entry collected once and dropped is signal when the frontier returns it.

    A corpus with no paper attached (no `bibliography.cited_from`) simply dedups
    against the corpus itself; that is the normal case, not a degradation."""
    path = Path(path) if path else corpus().cited_from
    if path is None:
        return set()
    if not path.is_file():
        print(f"warning: no {path}; dedup set will be corpus-only", file=sys.stderr)
        return set()
    return set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", path.read_text(
        encoding="utf-8", errors="replace")))


def read_tsv(path):
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, l.split("\t"))) for l in lines[1:] if l.strip()]


def write_tsv(path, header, rows):
    path.write_text("\n".join("\t".join(str(c) for c in r)
                              for r in [header] + rows) + "\n", encoding="utf-8")


# -------------------------------------------------------------------- OpenAlex

def _url(path, params):
    p = dict(params)
    mail = os.environ.get("OPENALEX_MAILTO")
    if mail:
        p["mailto"] = mail
    return f"{API}/{path}?{urllib.parse.urlencode(p)}"


def get(path, params, tries=3, cache=True):
    """GET with on-disk caching and backoff.

    Returns parsed JSON, or None for a genuine "no result / broken query".
    Raises RateLimited when the OpenAlex daily budget is gone -- the free tier
    is 1000 requests/day, which a full harvest can approach, so every response
    is cached to make re-runs and resumes free.
    """
    url = _url(path, params)
    key = hashlib.sha1(url.encode()).hexdigest()
    cf = ensure_cache() / f"{key}.json"
    if cache and cf.is_file():
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            pass

    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lit-expand/1.0"})
            with urllib.request.urlopen(req, timeout=60) as fh:
                data = json.loads(fh.read().decode("utf-8"))
            if cache:
                cf.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry = e.headers.get("retry-after", "?")
                raise RateLimited(
                    f"OpenAlex daily budget exhausted (resets in ~{retry}s). "
                    f"Cached responses still work; re-run after the reset.")
            if e.code in (500, 502, 503, 504) and n < tries - 1:
                time.sleep(2 ** n)
                continue
            # 400 = a query OpenAlex cannot parse: a real (empty) answer.
            if e.code != 400:
                print(f"  HTTP {e.code} on {url[:100]}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            if n < tries - 1:
                time.sleep(2 ** n)
                continue
            print(f"  network: {e.reason} on {url[:100]}", file=sys.stderr)
            return None
    return None


def paged(path, params, cap=1000):
    """Cursor-paginated results, capped so a hub seed cannot run away."""
    out, cursor = [], "*"
    while cursor and len(out) < cap:
        d = get(path, {**params, "per-page": 200, "cursor": cursor})
        if not d or not d.get("results"):
            break
        out.extend(d["results"])
        cursor = (d.get("meta") or {}).get("next_cursor")
        time.sleep(0.12)
    return out[:cap]


def fetch_works(ids, chunk=50):
    """Batch-hydrate OpenAlex work IDs into full records."""
    ids = [i for i in ids if i]
    out = {}
    for k in range(0, len(ids), chunk):
        batch = [i.rsplit("/", 1)[-1] for i in ids[k:k + chunk]]
        d = get("works", {"filter": "openalex_id:" + "|".join(batch),
                          "per-page": chunk, "select": WORK_FIELDS})
        for w in (d or {}).get("results", []):
            out[w["id"]] = w
        time.sleep(0.12)
    return out


def abstract(work):
    """Reconstruct plain text from OpenAlex's inverted index."""
    inv = work.get("abstract_inverted_index")
    if not inv:
        return ""
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    pos.sort()
    return " ".join(w for _, w in pos)


def venue(work):
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    return src.get("display_name") or ""


def authors(work, n=4):
    names = [(a.get("author") or {}).get("display_name", "")
             for a in work.get("authorships") or []]
    names = [x for x in names if x]
    return ", ".join(names[:n]) + (" et al." if len(names) > n else "")


def oa_pdf(work):
    for loc in (work.get("best_oa_location"), work.get("primary_location")):
        if loc and loc.get("pdf_url"):
            return loc["pdf_url"]
    return (work.get("open_access") or {}).get("oa_url") or ""


# --------------------------------------------------------- Semantic Scholar

S2 = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = ("title,year,externalIds,abstract,venue,authors,"
             "citationCount,openAccessPdf,publicationTypes")


def s2_get(path, params, tries=5, cache=True):
    """Semantic Scholar GET. Unmetered and keyless, unlike OpenAlex, which is
    why the harvest defaults to it: on the first corpus built this way, 38 of
    47 seeds carried a DOI while only 13 resolved to an OpenAlex id, so the
    DOI-keyed provider covered nearly three times as much. Old scanned journals
    are the usual reason. Raises RateLimited only after a patient backoff --
    S2's shared pool 429s transiently and that must not read as an absence."""
    url = f"{S2}/{path}?{urllib.parse.urlencode(params)}"
    key = hashlib.sha1(("s2:" + url).encode()).hexdigest()
    cf = ensure_cache() / f"{key}.json"
    if cache and cf.is_file():
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            pass
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lit-expand/1.0"})
            with urllib.request.urlopen(req, timeout=90) as fh:
                data = json.loads(fh.read().decode("utf-8"))
            if cache:
                cf.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # genuinely not in S2
            if e.code in (429, 500, 502, 503, 504):
                if n < tries - 1:
                    time.sleep(2.5 * (n + 1))
                    continue
                raise RateLimited(
                    "Semantic Scholar is rate-limiting persistently. Re-run "
                    "later; cached pages cost nothing.")
            print(f"  S2 HTTP {e.code} on {url[:100]}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            if n < tries - 1:
                time.sleep(2.0 * (n + 1))
                continue
            print(f"  S2 network: {e.reason}", file=sys.stderr)
            return None
    return None


def s2_edges(doi, direction, cap=500, pause=1.1):
    """direction: "citations" (who cites it) or "references" (what it cites).
    Returns the neighbouring paper records, flattened."""
    inner = "citingPaper" if direction == "citations" else "citedPaper"
    out, offset = [], 0
    while len(out) < cap:
        d = s2_get(f"paper/DOI:{doi}/{direction}",
                   {"fields": S2_FIELDS, "limit": 100, "offset": offset})
        if not d or not d.get("data"):
            break
        for row in d["data"]:
            rec = row.get(inner)
            if rec:
                out.append(rec)
        if d.get("next") is None:
            break
        offset = d["next"]
        time.sleep(pause)
    return out[:cap]


def s2_norm(rec):
    """S2 record -> the same shape harvest.py writes for every provider."""
    ext = rec.get("externalIds") or {}
    names = [a.get("name", "") for a in (rec.get("authors") or []) if a.get("name")]
    return {
        "id": rec.get("paperId") or "",
        "doi": (ext.get("DOI") or "").lower(),
        "arxiv": ext.get("ArXiv") or "",
        "title": rec.get("title") or "",
        "year": rec.get("year"),
        "authors": ", ".join(names[:4]) + (" et al." if len(names) > 4 else ""),
        "venue": rec.get("venue") or "",
        "type": (rec.get("publicationTypes") or [None])[0],
        "cited_by": rec.get("citationCount") or 0,
        "oa_pdf": (rec.get("openAccessPdf") or {}).get("url") or "",
        "abstract": (rec.get("abstract") or "")[:2000],
    }
