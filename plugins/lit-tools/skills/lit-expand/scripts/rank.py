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

_NONALNUM = re.compile(r"[^a-z0-9]+")


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
        out.append((int(w), _NONALNUM.sub("", t.lower()), t.strip()))
    return out


def ref_id(rec):
    """Short stable handle for a candidate, printed in the queue so the
    round-trip through CANDIDATES.md is exact. Title-prefix matching is not
    safe: "The Reflection of Life" appears twice, 2013 and 2015."""
    return (rec.get("id") or L.norm_title(rec.get("title", "")))[:10]


def score(rec, terms):
    """(total, degree, topic, matched-terms). Degree dominates by construction."""
    degree = len(set(rec["seeds_back"]) | set(rec["seeds_fwd"]))
    blob = _NONALNUM.sub("", (rec["title"] + " " + rec.get("abstract", "")).lower())
    topic, hits = 0, []
    for w, norm, label in terms:
        if norm and norm in blob:
            topic += w
            if w > 0:
                hits.append(label)
    topic = max(-8, min(topic, 14))          # cap so a keyword-stuffed abstract
    return 4 * degree + topic, degree, topic, hits[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=4)
    ap.add_argument("--limit", type=int, default=120)
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
    recs = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n = L.norm_title(r.get("title", ""))
        if n in done or any(n.startswith(d[:40]) for d in done if len(d) > 24):
            continue
        r["score"], r["degree"], r["topic"], r["hits"] = score(r, terms)
        recs.append(r)

    recs.sort(key=lambda r: (-r["score"], -r["degree"], -(r["year"] or 0)))
    keep = [r for r in recs if r["score"] >= args.min_score][:args.limit]

    def tier(r):
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
        "Degree dominates deliberately -- it is the signal lexical search cannot fake.",
        "",
        "Mark each row, then run `ingest.py`:",
        "",
        "- `[x]` ingest full text  ·  `[s]` stub (metadata only)  ·  `[ ]` skip",
        "",
        "| | ref | tier | score | deg | year | title | venue | OA |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in keep:
        # Titles can contain literal newlines, which silently break the
        # markdown row and make it unmarkable.
        t = " ".join(r["title"].split()).replace("|", "/")[:78]
        v = (r["venue"] or "")[:26].replace("|", "/")
        out.append(f"| `[ ]` | `{ref_id(r)}` | {tier(r)} | {r['score']} | "
                   f"{r['degree']} | {r['year'] or '?'} | {t} | {v} | "
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
            f"(degree {r['degree']}, vocab {r['topic']})",
        ]
        if r["seeds_back"]:
            out.append(f"- **cited by seeds**: {', '.join(s[:44] for s in r['seeds_back'][:6])}")
        if r["seeds_fwd"]:
            out.append(f"- **cites seeds**: {', '.join(s[:44] for s in r['seeds_fwd'][:6])}")
        if r["hits"]:
            out.append(f"- **vocabulary**: {', '.join(r['hits'])}")
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
