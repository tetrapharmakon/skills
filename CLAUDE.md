# skills

Personal Claude Code **plugin marketplace** (`.claude-plugin/marketplace.json`): a catalog of @tetrapharmakon's plugins, one folder per plugin under `plugins/<name>/`. It currently ships a single plugin, `lit-tools`.

Install and the add-a-plugin / add-a-skill walkthroughs live in [README.md](./README.md); what `lit-tools` itself does is in [plugins/lit-tools/README.md](./plugins/lit-tools/README.md).

## Repo layout

- `.claude-plugin/marketplace.json` — the marketplace manifest; lists every plugin. Add new plugins here.
- `plugins/<name>/.claude-plugin/plugin.json` — one folder per plugin, each with its own manifest and `version`.
- `plugins/<name>/skills/<skill>/SKILL.md` — the plugin's skills, alongside their `scripts/` and `references/`.
- `plugins/lit-tools/lib/` — code shared across that plugin's skills.

## Rules

- The repo is the marketplace; `lit-tools` is one plugin within it. Don't conflate the two — a new plugin gets its own `plugins/<name>/` folder *and* a marketplace entry.
- One skill per kebab-case folder; the folder name and frontmatter `name` must match. `SKILL.md` needs `name` + `description`, and the `description` must carry concrete trigger keywords — it is all Claude sees before loading the body.
- `SKILL.md` is a lean router: short body, detail in sibling files (`references/`, `scripts/`) loaded on demand.
- `lit-tools` skills stay inside the plugin directory. Their scripts resolve the shared `lib/` as `Path(__file__).resolve().parents[3] / "lib"`, so moving a skill up a level silently breaks every script; `SKILL.md` reaches them through `${CLAUDE_PLUGIN_ROOT}`.
- After editing manifests or skills, run `claude plugin validate plugins/<name> --strict` (plugin + skills) and `claude plugin validate . --strict` (marketplace). CI runs both on every push.
- Bump `version` in the relevant `plugin.json` on every release — it's the single source of truth; `claude plugin update` keys off it.
- English for repo docs, manifests, and commits.
