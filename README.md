# skills

Personal repository of [@tetrapharmakon](https://github.com/tetrapharmakon)'s Claude Code plugins, published as a **plugin marketplace** (`.claude-plugin/marketplace.json`) for native, versioned install.

Plugins live under `plugins/<name>/` and are listed in the marketplace manifest. Today it ships one:

| Plugin | What it does |
|--------|--------------|
| [`lit-tools`](./plugins/lit-tools) | Build, grow and interrogate a full-text literature corpus on any subject: `lit-corpus-init`, `lit-expand`, `lit-claim-search`. |

## Install

```bash
claude plugin marketplace add tetrapharmakon/skills
claude plugin install lit-tools@tetrapharmakon
```

or `/plugin` inside Claude Code. Update with `claude plugin update lit-tools` — users
only receive updates when `version` in the plugin's `plugin.json` is bumped.

For what `lit-tools` does and how to use it, see [its README](./plugins/lit-tools/README.md).

## Layout

```
.claude-plugin/marketplace.json          the catalog; lists every plugin
plugins/<name>/.claude-plugin/plugin.json  one manifest per plugin, carries `version`
plugins/<name>/skills/<skill>/SKILL.md     the plugin's skills
.github/workflows/validate.yml           CI: strict validation of marketplace + plugins
```

## Adding a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` — see [`lit-tools`](./plugins/lit-tools/.claude-plugin/plugin.json) for a template (`name`, `displayName`, `version`, `description`, `author`, `repository`, `keywords`).
2. Add an entry for it to the `plugins` array in `.claude-plugin/marketplace.json`.
3. Validate: `claude plugin validate plugins/<name> --strict` and `claude plugin validate . --strict`.

## Adding a skill to a plugin

1. Create `plugins/<name>/skills/<skill>/SKILL.md` (kebab-case folder) with YAML frontmatter:
   ```markdown
   ---
   name: <skill>
   description: What it does, and the concrete situations that should trigger it.
   ---
   ```
   The folder name and frontmatter `name` must match, and the `description` must make clear **when** the skill fires — it is all Claude sees before loading the body.
2. Keep `SKILL.md` lean: push detail into sibling files (`references/`, `scripts/`) loaded on demand.
3. Bump `version` in that plugin's `plugin.json` to release the change to marketplace users.
4. Validate with `claude plugin validate plugins/<name> --strict`.

## Conventions

- One marketplace, many plugins: each is a folder under `plugins/<name>/` with its own `.claude-plugin/plugin.json`, all listed in `.claude-plugin/marketplace.json`.
- Skills that ship executable code live **inside** their plugin (`plugins/<name>/skills/`), not at the top level: `lit-tools`' scripts resolve their shared `lib/` relative to the plugin root, and reach it from `SKILL.md` via `${CLAUDE_PLUGIN_ROOT}`.
- A future plugin holding only prose skills (no executables) may instead keep them at top-level `skills/` so `npx skills add tetrapharmakon/skills` can find them, symlinked into the plugin as `plugins/<name>/skills -> ../../skills`.
- Distribution and versioning live in the manifests; `claude plugin update` keys off `version`.
- English for repo docs, manifests, and commit messages.
