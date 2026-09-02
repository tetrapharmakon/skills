#!/usr/bin/env python3
"""Stage 3 -- rank the frontier and write the review queue.

Ranking is by CITATION DEGREE first, vocabulary second. That ordering is the
whole point: lexical scoring over a multi-tradition corpus inverts the truth --
on one real test query the corpus's foundational-but-irrelevant text scored 435
hits and the single relevant paper scored 1. Degree cannot be gamed by a common
word: a paper touching five seeds is in this conversation whatever words it uses.

The vocabulary gate (<corpus>/index/topic-terms.txt, written for this subject at
init time) only breaks ties and filters the long tail of single-edge works,
where degree carries no information. A corpus with no terms file ranks by degree
alone, which is the safe default.

  python3 rank.py                 # -> <corpus>/index/CANDIDATES.md
  python3 rank.py --min-score 6   # tighter queue
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


def load_terms(path):
    """Weighted vocabulary for this subject. Absent is legal: the ranking then
    rests entirely on citation degree, which is the signal that matters."""
    if not path.is_file():
        print(f"no {path}; ranking by citation degree only", file=sys.stderr)
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "\t" not in line:
            continue
        w, t = line.split("\t", 1)
        out.append((int(w), litcorpus.norm(t), t.strip()))
    return out


ref_id = L.ref_id   # one definition, shared with ingest.py and init_corpus.py


SUBSTANTIVE = {"methodology", "result"}   # S2 intents that mean "builds on it"


def blob_of(rec):
    return litcorpus.norm(rec["title"] + " " + (rec.get("abstract") or ""))


def term_stats(recs, terms):
    """How often each topic term fires across the whole frontier. The terms
    file asks of every term \"if a paper contains this and nothing else, is it
    about my subject?\"; the only way to answer is to see what it actually
    fires on. A positive term that fires on a third of the frontier is
    generic vocabulary wearing a topical weight, and it is what lets an
    off-topic paper enter tier A through the vocabulary route."""
    blobs = [blob_of(r) for r in recs]
    n = max(len(blobs), 1)
    # Matching is by substring, so a term contained in another always fires
    # with it and their weights add: "graph dynamical system" and "graph
    # dynamical systems" listed separately at 5 each are one term at 10.
    inside = {}
    for w, norm, label in terms:
        for _, norm2, label2 in terms:
            if norm and norm2 and norm != norm2 and norm in norm2:
                inside.setdefault(label2, label)
    rows = []
    for w, norm, label in terms:
        fires = sum(1 for b in blobs if norm and norm in b)
        rows.append((fires, w, label))
    rows.sort(key=lambda r: (-r[0], -abs(r[1])))
    print(f"{'fires':>5} {'share':>6} {'w':>3}  term        ({n} frontier records)")
    for fires, w, label in rows:
        share = fires / n
        if label in inside:
            note = f"  <- contains '{inside[label]}': always fires with it, weights add"
        elif w > 0 and share > 0.33:
            note = "  <- fires on a third of the frontier: not discriminating"
        elif fires == 0:
            note = "  <- never fires: no effect (or the frontier has no abstracts for it)"
        else:
            note = ""
        print(f"{fires:5d} {share:6.0%} {w:3d}  {label}{note}")


def score(rec, terms):
    """(total, degree, topic, matched-terms). Degree dominates by construction."""
    degree = len(set(rec["seeds_back"]) | set(rec["seeds_fwd"]))
    blob = blob_of(rec)
    topic, hits = 0, []
    for w, norm, label in terms:
        if norm and norm in blob:
            topic += w
            if w > 0:
                hits.append(label)
    topic = max(-8, min(topic, 14))          # cap so a keyword-stuffed abstract
    return 4 * degree + topic, degree, topic, hits[:6]


def edge_summary(rec):
    """What S2 says the citations ARE. `classified` is the number of edges S2
    attached a context or intent to; `influential` those it flagged so;
    `substantive` those flagged influential or with a methodology/result
    intent. A record harvested before edges were kept has none of this."""
    edges = rec.get("edges") or []
    classified = sum(1 for e in edges if e.get("contexts") or e.get("intents"))
    influential = sum(1 for e in edges if e.get("influential"))
    substantive = sum(1 for e in edges
                      if e.get("influential") or SUBSTANTIVE & set(e.get("intents") or []))
    return classified, influential, substantive


def surnames(s, bibtex=False):
    """Surnames of an author string, folded. BibTeX form 'Mortveit, H. S. and
    Reidys, C. M.' or provider form 'H. Mortveit, C. Reidys, ... et al.'.
    Two-letter surnames are dropped: 'Li' would flag half the frontier."""
    out = set()
    parts = [p for p in (s or "").replace(" et al.", "").split(" and " if bibtex else ",")]
    for p in parts:
        p = p.strip()
        if not p:
            continue
        name = p.split(",")[0] if (bibtex and "," in p) else p.split()[-1]
        n = litcorpus.norm(name)
        if len(n) >= 3:
            out.add(n)
    return out


def seed_authors(c):
    """slug -> surnames of the seed's authors, from the bibliography entry the
    bibmap names. Seeds with no entry (or a corpus with no .bib) contribute an
    empty set, which flags nothing."""
    bib = L.parse_refs_bib()
    return {r["slug"]: surnames(bib.get(r["bibkey"], {}).get("author", ""), bibtex=True)
            for r in L.read_tsv(c.bibmap)}


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_WANTED_HEADING = re.compile(r"not in (the )?corpus|wanted|missing", re.I)
_TITLE_SPAN = re.compile(r"\*([^*\n]{20,}?)\*|_([^_\n]{20,}?)_|[\"“]([^\"”\n]{20,}?)[\"”]")


def wanted_titles(c):
    """Titles named under a 'Not in corpus' (or 'Wanted' / 'Missing') heading
    of any findings file, as normalised strings. A claim search that ends by
    naming the paper it could not check is the strongest possible signal that
    the corpus should hold that paper; this is how the search feeds the
    expansion. Titles are read from emphasised or quoted spans of twenty
    characters or more, so a reference written as `Author, *Title*, Venue
    (Year)` is picked up and prose is not."""
    out = {}
    if not c.findings.is_dir():
        return out
    for f in sorted(c.findings.glob("*.md")):
        level, inside = 0, False
        for line in f.read_text(encoding="utf-8", errors="replace").split("\n"):
            m = _HEADING.match(line)
            if m:
                if inside and len(m.group(1)) <= level:
                    inside = False
                if _WANTED_HEADING.search(m.group(2)):
                    inside, level = True, len(m.group(1))
                continue
            if inside:
                for g in _TITLE_SPAN.finditer(line):
                    t = next(x for x in g.groups() if x)
                    out.setdefault(L.norm_title(t), (t.strip(), f.name))
    return out


def wanted_by(rec, wanted):
    """The findings file that asked for this candidate, or None."""
    n = L.norm_title(rec.get("title", ""))
    if len(n) < 20:
        return None
    for wn, (_, fname) in wanted.items():
        # 0.9, not the 0.8 used for provider records: titles in one field share
        # long phrases ("... of sequential dynamical systems"), and at 0.8 a
        # findings file asking for one paper lifted a different one. A wanted
        # title may also be the head of a longer candidate title (a subtitle
        # added), never a fragment inside it.
        if wn == n or L.title_ratio(n, wn) >= 0.9:
            return fname
        if len(wn) >= 30 and n.startswith(wn) and len(wn) >= 0.7 * len(n):
            return fname
    return None


def flags(rec, seeds_auth):
    """Short evidence tags for the reviewer -- not verdicts. On the corpus this
    was calibrated on no structural rule separated noise from signal: the same
    group that produced a mathematical-epidemiology prospectus (degree 5, no
    vocabulary) also produced the most relevant follow-ups (degree 3, all
    self-cited), and S2 flagged one of the prospectus's citations influential.
    So the queue shows the evidence and the tier stays what degree and
    vocabulary say.

      self   most connected seeds share an author with the candidate
      bg     S2 classified every edge as background, none influential
      noabs  no abstract from the provider: the vocabulary score is silence,
             not a judgement (old scans and encyclopedia entries)
    """
    out = []
    mine = surnames(rec.get("authors") or "")
    seeds = set(rec["seeds_back"]) | set(rec["seeds_fwd"])
    shared = sum(1 for s in seeds if mine & seeds_auth.get(s, set()))
    if seeds and shared * 2 > len(seeds):
        out.append("self")
    if rec["classified"] and not rec["substantive"]:
        out.append("bg")
    if not (rec.get("abstract") or "").strip():
        out.append("noabs")
    return out, shared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=4)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--term-stats", action="store_true",
                    help="print how often each topic term fires across the frontier "
                         "and exit without writing the queue")
    litcorpus.add_argument(ap)
    args = ap.parse_args()
    try:
        c = L.use(litcorpus.from_args(args))
    except litcorpus.NoCorpus as e:
        print(e, file=sys.stderr)
        return 1

    src = c.candidates
    if not src.is_file():
        print(f"no {src} -- run harvest.py first", file=sys.stderr)
        return 1
    # Anything already ingested or stubbed has been triaged; the queue is for
    # what has NOT been. candidates.jsonl stays the raw frontier, untouched.
    done = set()
    for r in L.read_tsv(c.bibmap):
        done.add(L.norm_title(r["slug"].replace("_", " ")))
    terms = load_terms(c.terms)
    seeds_auth = seed_authors(c)
    wanted = wanted_titles(c)
    if wanted:
        print(f"{len(wanted)} title(s) named as missing by findings files", file=sys.stderr)
    recs = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n = L.norm_title(r.get("title", ""))
        if n in done or any(n.startswith(d[:40]) for d in done if len(d) > 24):
            continue
        r["score"], r["degree"], r["topic"], r["hits"] = score(r, terms)
        r["classified"], r["influential"], r["substantive"] = edge_summary(r)
        r["flags"], r["self"] = flags(r, seeds_auth)
        r["wanted"] = wanted_by(r, wanted)
        if r["wanted"]:
            # Two degrees' worth: a search asked for this paper by name.
            r["score"] += 8
            r["flags"].insert(0, "wanted")
        recs.append(r)

    if args.term_stats:
        if not terms:
            print("no topic terms to report on", file=sys.stderr)
            return 1
        term_stats(recs, terms)
        return 0

    recs.sort(key=lambda r: (-r["score"], -r["influential"], -r["degree"], -(r["year"] or 0)))
    keep = [r for r in recs if r["score"] >= args.min_score][:args.limit]

    def tier(r):
        if r.get("wanted"):
            return "A"          # named as missing by a claim search
        if r["degree"] >= 3 or (r["degree"] >= 2 and r["topic"] >= 4):
            return "A"
        if r["degree"] >= 2 or r["topic"] >= 8:
            return "B"
        return "C"

    out = [
        "# Candidate queue",
        "",
        f"{len(recs)} works on the citation frontier of corpus '{c.name}'; "
        f"{len(keep)} scored >= {args.min_score}.",
        "",
        "**Score** = 4x(distinct seeds cited-by-or-citing) + vocabulary weight. "
        "Degree dominates deliberately -- it is the signal lexical search cannot fake. "
        "**infl** = citations Semantic Scholar flags as influential, over the edges it "
        "classified at all. **flags** are evidence, not verdicts: `self` = most connected "
        "seeds share an author with the candidate (a group's own later work in another "
        "field scores high on degree); `bg` = every classified edge is background, none "
        "influential (it names the seeds, it may not build on them); `noabs` = no abstract, "
        "so the vocabulary score is silence, not a judgement; `wanted` = a findings file "
        "named this title under *Not in corpus* (+8, tier A). The Detail section quotes the "
        "sentences in which the citations are made.",
        "",
        "Mark each row, then run `ingest.py`:",
        "",
        "- `[x]` ingest full text  ·  `[s]` stub (metadata only)  ·  `[ ]` skip",
        "",
        "| | ref | tier | score | deg | infl | flags | year | title | venue | OA |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in keep:
        # Titles can contain literal newlines, which silently break the
        # markdown row and make it unmarkable.
        t = " ".join(r["title"].split()).replace("|", "/")[:78]
        v = (r["venue"] or "")[:26].replace("|", "/")
        infl = f"{r['influential']}/{r['classified']}" if r["classified"] else "-"
        out.append(f"| `[ ]` | `{ref_id(r)}` | {tier(r)} | {r['score']} | "
                   f"{r['degree']} | {infl} | {' '.join(r['flags']) or '-'} | "
                   f"{r['year'] or '?'} | {t} | {v} | "
                   f"{'Y' if (r['oa_pdf'] or r.get('arxiv')) else '-'} |")

    out += ["", "---", "", "## Detail", ""]
    for r in keep:
        out += [
            f"### {r['title']}",
            f"- **id** `{r['id']}` · **doi** `{r['doi'] or '-'}` · "
            f"**{r['year'] or '?'}** · {r['authors'] or '?'}",
            f"- **venue**: {r['venue'] or '?'} · cited by {r['cited_by']} · "
            f"**OA pdf**: {'yes' if r['oa_pdf'] else ('arXiv:' + r['arxiv']) if r.get('arxiv') else 'NO -- stub or fetch by hand'}",
            f"- **tier {tier(r)}**, score {r['score']} "
            f"(degree {r['degree']}, vocab {r['topic']}"
            + (f", {r['influential']} influential / {r['substantive']} substantive "
               f"of {r['classified']} classified edges" if r["classified"] else "")
            + (f", {r['self']} of {r['degree']} seeds share an author" if r["self"] else "")
            + (f"; flags: {' '.join(r['flags'])}" if r["flags"] else "") + ")",
        ]
        if r.get("wanted"):
            out.append(f"- **wanted by** `findings/{r['wanted']}` (named under *Not in corpus*)")
        if r["seeds_back"]:
            out.append(f"- **cited by seeds**: {', '.join(s[:44] for s in r['seeds_back'][:6])}")
        if r["seeds_fwd"]:
            out.append(f"- **cites seeds**: {', '.join(s[:44] for s in r['seeds_fwd'][:6])}")
        if r["hits"]:
            out.append(f"- **vocabulary**: {', '.join(r['hits'])}")
        # The sentences in which the citations are made: the single most
        # useful thing a reviewer can see without opening the paper.
        # Influential and substantive edges first, then the rest.
        edges = sorted((e for e in r.get("edges") or [] if e.get("contexts")),
                       key=lambda e: (not e.get("influential"),
                                      not (SUBSTANTIVE & set(e.get("intents") or []))))
        for e in edges[:2]:
            tag = "influential" if e.get("influential") else \
                ("/".join(e.get("intents") or []) or "unclassified")
            arrow = "cites" if e["dir"] == "fwd" else "cited by"
            out.append(f"- **{arrow} {e['seed'][:40]}** ({tag}): "
                       f"“{e['contexts'][0][:240]}”")
        ab = (r.get("abstract") or "").strip()
        out += [f"- **abstract**: {ab[:600]}{'...' if len(ab) > 600 else ''}"
                if ab else "- **abstract**: (none from the provider)", ""]

    dst = c.queue
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    tiers = {}
    for r in keep:
        tiers[tier(r)] = tiers.get(tier(r), 0) + 1
    print(f"{len(keep)} candidates -> {dst}   tiers: " +
          " ".join(f"{k}={tiers.get(k,0)}" for k in "ABC"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
