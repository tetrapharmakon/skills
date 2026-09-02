#!/usr/bin/env python3
"""Report what is stale in an existing corpus, and the command that fixes each.

The tools evolve; a corpus built last month does not. Some of the drift
announces itself (find.py warns about an old search mirror), most of it does
not: a manifest with last year's columns, a frontier harvested before
citation contexts were kept, a review queue whose ref ids predate the current
scheme so that its marks match nothing. Run this on any corpus you did not
create in the current session, then do what it prints.

  doctor.py                     # report
  doctor.py --fix               # also apply the two safe local repairs
                                # (rebuild the mirror, rebuild the manifest)

Never applied by --fix, because each needs a decision: re-harvesting hits the
network and takes minutes; regenerating a queue discards its marks (they are
listed so they can be re-applied with mark.py).

Exit 0 when nothing is stale, 1 otherwise. Every check is a deterministic
comparison of files on disk; nothing here guesses.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / "lib"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "lit-expand" / "scripts"))
import litcorpus                       # noqa: E402
import build_manifest as BM            # noqa: E402
import verify as V                     # noqa: E402

SCRIPTS = {
    "normalize": HERE.parent / "normalize.py",
    "manifest": HERE.parent / "build_manifest.py",
    "verify": HERE.parent / "verify.py",
    "harvest": HERE.parents[2] / "lit-expand" / "scripts" / "harvest.py",
    "rank": HERE.parents[2] / "lit-expand" / "scripts" / "rank.py",
    "mark": HERE.parents[2] / "lit-expand" / "scripts" / "mark.py",
    "init": HERE.parents[2] / "lit-corpus-init" / "scripts" / "init_corpus.py",
}
_QUEUE_ROW = re.compile(r"^\|\s*`\[([xs ])\]`\s*\|\s*`([^`]+)`\s*\|(.*)$")


def cmd(name, c, extra=""):
    return f"python3 {SCRIPTS[name]} --corpus {c.root}" + (f" {extra}" if extra else "")


class Report:
    def __init__(self):
        self.items = []          # (kind, text, fix)  kind: STALE | note | ok

    def stale(self, text, fix):
        self.items.append(("STALE", text, fix))

    def note(self, text, fix=None):
        self.items.append(("note", text, fix))

    def ok(self, text):
        self.items.append(("ok", text, None))


# ------------------------------------------------------------------ checks

def check_mirror(c, rep):
    if not c.texts_norm.is_dir():
        rep.stale("no search mirror (texts-norm/)", cmd("normalize", c))
        return "mirror"
    why = litcorpus.mirror_stale(c.texts_norm)
    if why:
        rep.stale(f"search mirror built by an older normaliser: {why.split(';')[0]}",
                  cmd("normalize", c))
        return "mirror"
    texts = {p.name for p in c.texts.glob("*.txt")} if c.texts.is_dir() else set()
    mirror = {p.name for p in c.texts_norm.glob("*.txt")}
    if texts - mirror or mirror - texts:
        rep.stale(f"mirror out of step with texts/ ({len(texts - mirror)} unmirrored, "
                  f"{len(mirror - texts)} orphaned)", cmd("normalize", c))
        return "mirror"
    newer = [p.name for p in c.texts.glob("*.txt")
             if (c.texts_norm / p.name).stat().st_mtime < p.stat().st_mtime]
    if newer:
        rep.stale(f"{len(newer)} text(s) changed after the mirror was built",
                  cmd("normalize", c))
        return "mirror"
    rep.ok(f"search mirror current (normaliser v{litcorpus.NORM_VERSION}, "
           f"{len(mirror)} texts)")
    return None


def check_manifest(c, rep):
    if not c.manifest.is_file():
        rep.stale("no MANIFEST.tsv", cmd("manifest", c))
        return "manifest"
    hdr = tuple(c.manifest.read_text(encoding="utf-8").split("\n", 1)[0].split("\t"))
    if hdr != BM.MANIFEST_HEADER:
        gone = [h for h in hdr if h not in BM.MANIFEST_HEADER]
        rep.stale(f"MANIFEST.tsv has columns from an older build "
                  f"({', '.join(gone) or 'different header'})", cmd("manifest", c))
        return "manifest"
    m_time = c.manifest.stat().st_mtime
    newer = [p for p in (list(c.texts.glob("*.txt")) if c.texts.is_dir() else []) + [c.bibmap]
             if p.is_file() and p.stat().st_mtime > m_time]
    if newer:
        rep.stale(f"MANIFEST.tsv older than {len(newer)} text/bibmap file(s)",
                  cmd("manifest", c))
        return "manifest"
    rep.ok("MANIFEST.tsv current")
    return None


def check_frontier(c, rep):
    if not c.candidates.is_file():
        rep.note("no frontier yet (candidates.jsonl); nothing to check",
                 None)
        return
    recs = [json.loads(l) for l in c.candidates.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    if not recs:
        rep.note("candidates.jsonl is empty")
        return
    with_edges = sum(1 for r in recs if r.get("edges"))
    if with_edges == 0:
        rep.stale(f"candidates.jsonl: none of {len(recs)} records carries citation "
                  f"contexts (harvested before they were kept); the queue's infl and "
                  f"flags columns stay empty until re-harvested (network, minutes)",
                  cmd("harvest", c))
    elif with_edges < len(recs):
        rep.note(f"candidates.jsonl: {len(recs) - with_edges} of {len(recs)} records "
                 f"without citation contexts (a partial or older harvest)",
                 cmd("harvest", c))
    else:
        rep.ok(f"frontier carries citation contexts ({len(recs)} records)")


def check_queue(c, rep):
    if not c.queue.is_file():
        rep.note("no review queue (CANDIDATES.md)")
        return
    lines = c.queue.read_text(encoding="utf-8").split("\n")
    rows = [(m.group(1), m.group(2).strip(), m.group(3))
            for m in (_QUEUE_ROW.match(l) for l in lines) if m]
    if not rows:
        rep.note("CANDIDATES.md has no markable rows")
        return
    old = [r for r in rows if re.fullmatch(r"[a-z]+", r[1])]
    init = lines[0].lower().startswith("# init queue")
    regen = cmd("rank", c)
    if init:
        regen = (f"python3 {SCRIPTS['init']} {c.root} --pdfs <DIR> and/or --bib <FILE>  "
                 f"(the inputs it was built from)")
    if old:
        marked = [(m, rest) for m, _, rest in rows if m != " "]
        text = (f"CANDIDATES.md uses title-prefix refs from an older rank.py/init_corpus.py "
                f"({len(old)} of {len(rows)} rows); ingest.py --from-queue would match "
                f"none of its marks")
        if marked:
            titles = []
            for m, rest in marked[:8]:
                cells = [x.strip() for x in rest.split("|")]
                title = next((x for x in cells if len(x) > 12 and re.search(r"[A-Za-z]{3}", x)),
                             rest.strip()[:60])
                titles.append(f"[{m}] {title[:70]}")
            text += f"; {len(marked)} row(s) are marked and will need re-marking:\n" + \
                "\n".join("             " + t for t in titles)
        rep.stale(text, regen + f"\n         then re-mark: python3 {SCRIPTS['mark']} --corpus {c.root} x <ref> ...")
        return
    hdr_ok = any(l.startswith("| | ref | tier |") and "flags" in l for l in lines[:40])
    if not init and not hdr_ok:
        rep.note("CANDIDATES.md predates the infl/flags columns; rank.py rewrites it "
                 "(marks are kept only if you re-apply them)", cmd("rank", c))
        return
    rep.ok(f"CANDIDATES.md refs current ({len(rows)} rows, "
           f"{sum(1 for r in rows if r[0] != ' ')} marked)")


def check_findings(c, rep):
    if not c.findings.is_dir():
        rep.note("no findings/ yet")
        return
    files = sorted(c.findings.glob("*.md"))
    if not files:
        rep.note("findings/ is empty")
        return
    unchecked = []
    total = 0
    for f in files:
        lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
        n = 0
        has_table = False
        for hdr, body in V.tables(lines):
            has_table = True
            cols = V.find_columns(hdr, body)
            if not cols:
                continue
            lc, qc = cols
            n += sum(1 for _, row in body
                     if max(lc, qc) < len(row) and V.parse_location(row[lc]))
        total += n
        if has_table and n == 0:
            unchecked.append(f.name)
    if unchecked:
        rep.note(f"{len(unchecked)} findings file(s) have tables verify.py cannot read "
                 f"(no slug:Lstart-Lend location cell): {', '.join(unchecked[:4])}")
    if total:
        rep.note(f"findings/: {len(files)} file(s), {total} quoted rows; verify them",
                 cmd("verify", c))


def check_config(c, rep):
    if "normalize" not in (c.data or {}):
        rep.note("lit-corpus.json has no `normalize.substitutions` block (only needed when a "
                 "scan replaced glyphs, e.g. ® for fi; see the claim-search skill)")
    seeds = {r["slug"] for r in _tsv(c.seeds)}
    corpus = {r["slug"] for r in _tsv(c.bibmap)}
    if corpus and seeds is not None and corpus - seeds and c.seeds.is_file():
        rep.note(f"{len(corpus - seeds)} corpus source(s) have no SEEDS.tsv row (added "
                 f"since the last resolve); their citation frontier is not harvested",
                 f"python3 {SCRIPTS['harvest'].parent / 'resolve_seeds.py'} --corpus {c.root}")


def _tsv(path):
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, l.split("\t"))) for l in lines[1:] if l.strip()]


# -------------------------------------------------------------------- main

def main():
    ap = litcorpus.add_argument(argparse.ArgumentParser())
    ap.add_argument("--fix", action="store_true",
                    help="apply the safe local repairs (rebuild mirror and manifest)")
    a = ap.parse_args()
    try:
        c = litcorpus.from_args(a)
    except litcorpus.NoCorpus as e:
        sys.exit(str(e))
    print(c.describe())

    rep = Report()
    fixable = set()
    for chk in (check_mirror, check_manifest):
        tag = chk(c, rep)
        if tag:
            fixable.add(tag)
    check_frontier(c, rep)
    check_queue(c, rep)
    check_findings(c, rep)
    check_config(c, rep)

    if a.fix and fixable:
        order = [("mirror", "normalize"), ("manifest", "manifest")]
        for tag, name in order:
            if tag in fixable or (tag == "manifest" and "mirror" in fixable):
                print(f"\n--fix: {cmd(name, c)}", flush=True)
                subprocess.run([sys.executable, str(SCRIPTS[name]), "--corpus", str(c.root)],
                               check=False)
        # Report again on the repaired state.
        rep = Report()
        for chk in (check_mirror, check_manifest):
            chk(c, rep)
        check_frontier(c, rep)
        check_queue(c, rep)
        check_findings(c, rep)
        check_config(c, rep)
        print()

    stale = 0
    for kind, text, fix in rep.items:
        if kind == "STALE":
            stale += 1
        print(f"  {kind:<5}  {text}")
        if fix:
            print(f"         -> {fix}")
    if stale:
        print(f"\n{stale} stale item(s). Run the commands above in order"
              + ("" if a.fix else "; --fix applies the mirror and manifest ones") + ".")
    else:
        print("\nnothing stale.")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
