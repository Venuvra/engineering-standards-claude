# Which file each AI assistant reads

The shared rules live in one place: the managed block at the top of `AGENTS.md`. Every
assistant reads that block. Nothing copies rule text into a second file, so there is nothing
to keep in sync by hand.

| Assistant | How it reads the shared rules | File vstd manages |
| --- | --- | --- |
| Codex | Reads `AGENTS.md` directly | `AGENTS.md` |
| Claude Code | `CLAUDE.md` line 1 is `@AGENTS.md`, which imports it | `CLAUDE.md` |
| Gemini CLI | `.gemini/settings.json` lists `AGENTS.md` under `context.fileName` | `.gemini/settings.json` (when `gemini = true`) |
| Google Antigravity (`agy`, IDE and CLI) | Reads `AGENTS.md` directly at each folder level up to the repo root | none |

## Gemini CLI

By default Gemini CLI loads only `GEMINI.md` files. With `gemini = true` in
`.venuvra/standards.toml`, sync writes:

```json
{
  "context": {
    "fileName": [
      "AGENTS.md",
      "GEMINI.md"
    ]
  }
}
```

`AGENTS.md` comes first, so the shared rules load before any Gemini-only notes. `GEMINI.md`
stays in the list so an existing one keeps working. If the repository already has
`.gemini/settings.json`, sync adds `AGENTS.md` to its list and keeps every other setting
(the JSON is re-indented). A settings file with comments isn't rewritten: `vstd check` passes
if it already lists `"AGENTS.md"` and otherwise tells you to add it by hand.

Why a settings file and not a `GEMINI.md` with an import: Antigravity also reads `GEMINI.md`,
and its `@file` syntax doesn't inline the file the way Gemini CLI's does. A `GEMINI.md` wrapper
could leave Antigravity with no rules.

## Antigravity

Antigravity reads `AGENTS.md` (or `GEMINI.md`) in the workspace folder and each parent up to
the repository root, plus workspace rules in `.agents/rules/*.md` (legacy `.agent/rules/`).
It needs no file from vstd. Two things to know:

- Its docs describe loading `AGENTS.md` *or* `GEMINI.md` per folder, so a root `GEMINI.md`
  might be read in place of `AGENTS.md`. `vstd check` warns about a root `GEMINI.md`; move
  its notes into the project section of `AGENTS.md`.
- It truncates a rule file at 24,000 bytes, which is now the `AGENTS.md` size limit.

## Assistant-specific notes

Put notes for one assistant in the project section of `AGENTS.md` unless only that assistant
should see them. `CLAUDE.md` below the import, `GEMINI.md` and `.agents/rules/` are fine for
assistant-only notes, but `vstd check` fails if they contain rule ID lines such as
`[SEC-001 MUST]`, and warns when they mention a MUST rule next to words like "skip" or
"does not apply".

## Turning it on in an onboarded repository

Once the repository is on the release that adds `gemini`, add one line to
`.venuvra/standards.toml`:

```toml
gemini = true
```

The push runs sync, which opens a PR adding `.gemini/settings.json`. Turning it on before the
upgrade fails the check, because older releases don't know the key.

Sources: [Gemini CLI GEMINI.md](https://geminicli.com/docs/cli/gemini-md),
[Gemini CLI configuration](https://geminicli.com/docs/reference/configuration),
[Antigravity rules](https://antigravity.google/docs/rules).
