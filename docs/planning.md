# Where planning lives

Planning files are shared. Claude Code, Codex, Gemini CLI and Antigravity all read the same
ones, so every assistant works from the same design and stack. There are no per-assistant
plan files (no `CLAUDE-PLAN.md`, `CODEX-PLAN.md` and so on).

| File | Holds | Rule | Lifetime |
| --- | --- | --- | --- |
| `docs/architecture.md` | Stack, design, components, data flow, deploy target | DOC-005 | Whole project, kept current |
| `docs/adr/NNNN-title.md` | One significant decision and its reasons | ENG-009 | Permanent; superseded, never edited |
| `docs/plans/YYYY-MM-DD-<task>.md` | One task: goal, approach, choices, files, test plan | DOC-006 | Until the task is done |
| `AGENTS.md` project section | Build and test commands, a link to `docs/architecture.md` | DOC-005 | Whole project |

Starter files are in `templates/docs/` in the release you pin: copy `architecture.md` to
`docs/architecture.md` and `plan.md` to `docs/plans/<date>-<task>.md`. Sync doesn't create them;
they belong to the repository.

## Order for a new repository

1. Create the repository.
2. Onboard it (rollout Action or `vstd init`) so `AGENTS.md` and the rules exist first.
3. Ask an assistant to fill in `docs/architecture.md`, then add one line to the project section
   of `AGENTS.md`: `Read docs/architecture.md before planning a change.`
4. For each non-trivial task, write `docs/plans/<date>-<task>.md`, agree it, then code. When the
   plan settles something lasting, record an ADR and update `docs/architecture.md`.

`CLAUDE.md` below its import line, `GEMINI.md` and `.agents/rules/` are still only for notes that
one assistant alone should see (see `docs/agents.md`), never for the plan.
