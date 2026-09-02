#!/usr/bin/env python3
"""Corpus discovery and configuration, shared by every lit-* skill.

A *corpus* is a directory that contains `lit-corpus.json` next to `texts/` and
`index/`. The config file is what makes the corpus self-describing: the tools
carry no knowledge of any particular subject, and a corpus can be moved,
copied to another machine, or sit next to five unrelated ones without any
edit to the code.

Everything domain-specific lives in the corpus, never in the plugin:

    <corpus>/lit-corpus.json     identity, layout, traditions, bibliography
    <corpus>/index/topic-terms.txt   vocabulary weights used to break rank ties
    <corpus>/index/glossary.md       the dialects this field uses for one idea
    <corpus>/index/TRAPS.md          hard-won facts about THIS corpus

Discovery, in order:

  1. `--corpus PATH` on any script (the directory, or the json file itself)
  2. `$LIT_CORPUS`
  3. walking up from the current directory: a `lit-corpus.json` at that level,
     otherwise exactly one in an immediate subdirectory (so working from the
     project root finds `rosen-dump/` without naming it).

Ambiguity is an error, never a guess: two candidate corpora side by side stop
the run and ask for `--corpus`. Picking one silently is how a paper ends up
cited from the wrong body of literature.
"""
import json
import os
from pathlib import Path

CONFIG_NAME = "lit-corpus.json"
SCHEMA_VERSION = 1

DEFAULT_LAYOUT = {
    "texts": "texts",
    "texts_norm": "texts-norm",
    "index": "index",
    "pdfs": "pdfs",
    "findings": "findings",
}


class NoCorpus(Exception):
    """No corpus config could be located, or more than one could."""


# ----------------------------------------------------------------- discovery

def _config_in(d: Path):
    c = d / CONFIG_NAME
    return c if c.is_file() else None


def _configs_below(d: Path):
    """Immediate subdirectories holding a config. One level only -- deeper and
    an unrelated corpus in a sibling checkout could capture the search."""
    out = []
    try:
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")):
                c = _config_in(sub)
                if c:
                    out.append(c)
    except PermissionError:
        pass
    return out


def _as_config(p):
    """Accept either the directory or the json file itself."""
    p = Path(p).expanduser()
    if p.is_file():
        return p
    c = _config_in(p)
    if c:
        return c
    raise NoCorpus(f"no {CONFIG_NAME} at {p}")


def discover(explicit=None, start=None):
    """Locate the corpus config. Returns its Path."""
    if explicit:
        return _as_config(explicit)
    env = os.environ.get("LIT_CORPUS")
    if env:
        return _as_config(env)

    here = Path(start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        c = _config_in(d)
        if c:
            return c
        below = _configs_below(d)
        if len(below) == 1:
            return below[0]
        if len(below) > 1:
            names = "\n  ".join(str(x.parent) for x in below)
            raise NoCorpus(
                f"{len(below)} corpora under {d}; name one with --corpus or "
                f"$LIT_CORPUS:\n  {names}")
    raise NoCorpus(
        f"no {CONFIG_NAME} found from {here} upwards.\n"
        f"Point at one with --corpus PATH or $LIT_CORPUS, or create a corpus "
        f"with the lit-corpus-init skill.")


# -------------------------------------------------------------------- corpus

class Corpus:
    """Resolved paths and domain settings for one corpus.

    Relative paths in the config resolve against the corpus directory, so
    `"bib": "../refs.bib"` reaches a LaTeX project one level up while the
    corpus itself stays relocatable as a unit.
    """

    def __init__(self, config_path, data):
        self.config_path = Path(config_path).resolve()
        self.root = self.config_path.parent
        self.data = data
        self.name = data.get("name") or self.root.name
        self.description = data.get("description", "")

        lay = {**DEFAULT_LAYOUT, **(data.get("layout") or {})}
        self.texts = self._p(lay["texts"])
        self.texts_norm = self._p(lay["texts_norm"])
        self.index = self._p(lay["index"])
        self.pdfs = self._p(lay["pdfs"])
        self.findings = self._p(lay["findings"])

        bib = data.get("bibliography") or {}
        # A corpus always has somewhere to put generated entries, even with no
        # paper attached: identifiers are useful on their own.
        self.bib = self._p(bib.get("bib") or f'{lay["index"]}/refs.bib')
        cited = bib.get("cited_from")
        self.cited_from = self._p(cited) if cited else None

        paper = data.get("paper") or []
        self.paper = [paper] if isinstance(paper, str) else list(paper)

        self.traditions = dict(data.get("traditions") or {})
        # Where a paper lands when no cue matches. Never invented: an honest
        # "unclassified" beats a confident wrong dialect, which is what the
        # cross-tradition routing in lit-claim-search keys on.
        self.default_tradition = data.get("default_tradition") or "unclassified"

        h = data.get("harvest") or {}
        self.hub_traditions = set(h.get("hub_traditions") or [])
        self.hub_cited_by = int(h.get("hub_cited_by") or 400)
        self.max_edges = int(h.get("max_edges") or 400)

    # ------------------------------------------------------------- helpers

    def _p(self, rel):
        p = Path(rel).expanduser()
        return p.resolve() if p.is_absolute() else (self.root / p).resolve()

    @property
    def cache(self):
        c = self.index / ".cache"
        c.mkdir(parents=True, exist_ok=True)
        return c

    # index artefacts, named once so no script spells them out
    @property
    def manifest(self):    return self.index / "MANIFEST.tsv"
    @property
    def bibmap(self):      return self.index / "bibmap.tsv"
    @property
    def seeds(self):       return self.index / "SEEDS.tsv"
    @property
    def candidates(self):  return self.index / "candidates.jsonl"
    @property
    def queue(self):       return self.index / "CANDIDATES.md"
    @property
    def wanted(self):      return self.index / "WANTED.md"
    @property
    def corpus_map(self):  return self.index / "CORPUS-MAP.md"
    @property
    def terms(self):       return self.index / "topic-terms.txt"
    @property
    def glossary(self):    return self.index / "glossary.md"
    @property
    def traps(self):       return self.index / "TRAPS.md"

    @property
    def tradition_names(self):
        return tuple(self.traditions)

    def tradition_cues(self):
        """[(name, (cue, ...)), ...] in config order -- most specific first,
        since guess_tradition takes the first match."""
        return [(k, tuple(v or ())) for k, v in self.traditions.items()]

    def paper_files(self):
        out = []
        for pat in self.paper:
            p = Path(pat).expanduser()
            base, pattern = (p.parent, p.name) if not p.is_absolute() else (p.parent, p.name)
            root = base if p.is_absolute() else (self.root / base)
            try:
                out.extend(sorted(root.glob(pattern)))
            except (OSError, ValueError):
                pass
        return out

    def ensure_dirs(self):
        for d in (self.texts, self.texts_norm, self.index, self.findings):
            d.mkdir(parents=True, exist_ok=True)

    def describe(self):
        n = len(list(self.texts.glob("*.txt"))) if self.texts.is_dir() else 0
        return f"corpus '{self.name}' — {n} texts — {self.root}"


# ------------------------------------------------------------------ loading

def load(explicit=None, start=None):
    path = discover(explicit, start)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NoCorpus(f"{path} is not valid JSON: {e}") from None
    v = data.get("version", SCHEMA_VERSION)
    if int(v) > SCHEMA_VERSION:
        raise NoCorpus(f"{path} declares version {v}; this plugin understands "
                       f"{SCHEMA_VERSION}. Update lit-tools.")
    return Corpus(path, data)


def add_argument(parser):
    """Every script takes --corpus, so a corpus can always be named explicitly
    regardless of where the command is run from."""
    parser.add_argument("--corpus", metavar="PATH", default=None,
                        help=f"corpus directory (or its {CONFIG_NAME}); "
                             f"default: $LIT_CORPUS, else found by walking up")
    return parser


def from_args(args, start=None):
    return load(getattr(args, "corpus", None), start)


def default_config(name, description="", traditions=None, bib=None, cited_from=None,
                   paper=None):
    """The config lit-corpus-init writes. Kept here so the schema has exactly
    one definition."""
    cfg = {
        "version": SCHEMA_VERSION,
        "name": name,
        "description": description,
        "layout": dict(DEFAULT_LAYOUT),
        "bibliography": {"bib": bib or "index/refs.bib"},
        "traditions": traditions or {},
        "default_tradition": "unclassified",
        "harvest": {"hub_traditions": [], "hub_cited_by": 400, "max_edges": 400},
    }
    if cited_from:
        cfg["bibliography"]["cited_from"] = cited_from
    if paper:
        cfg["paper"] = paper
    return cfg
