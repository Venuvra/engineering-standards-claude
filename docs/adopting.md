# Adopting the standards in a repository

The result: Codex reads the shared rules from `AGENTS.md`, Claude Code reads the same file
through `@AGENTS.md` in `CLAUDE.md`, and a weekly job proposes updates as a pull request.

## 1. Onboard (one PR, pushed by a person)

```sh
git clone https://github.com/Venuvra/engineering-standards-claude.git
cd engineering-standards-claude && git checkout vX.Y.Z      # the release to pin
python3 -I vstd/main.py init --repo ../your-repo            # or --stacks typescript,python
cd ../your-repo && git switch -c standards/onboard && git add -A && git status
```

`init` lists every file it wrote:

| File | What it is |
| --- | --- |
| `.venuvra/standards.toml` | Pinned `version` and `commit`, `upgrade` policy, `stacks`, overrides |
| `.github/workflows/standards.yml` | `check` on PRs and pushes; weekly `sync` |
| `AGENTS.md` | Managed block first, then your project section (existing text is kept below the block) |
| `CLAUDE.md` | Line 1 `@AGENTS.md`, then Claude Code-only notes (existing text is kept) |

Push the branch and open the PR yourself: `GITHUB_TOKEN` can't create workflow files, so
the first PR can't come from the bot. Review that the project section still says what it
said before, then merge.

## 2. Repository settings

- Actions: allow `actions/checkout` (the only action used). Workflow permissions can stay
  read-only by default; the `sync` job asks for its three scopes itself.
- Settings → Actions → General: allow GitHub Actions to create pull requests, or sync
  can push its branch but not open the PR.
- Branch ruleset on the default branch: require `standards/check`. On ordinary PRs that is
  the `check` job; on sync PRs it is the commit status sync sets, because PRs opened with
  `GITHUB_TOKEN` don't trigger workflows. Other required checks won't run on sync PRs by
  themselves; a maintainer starts them by closing and reopening the PR.

## 3. Day to day

- Put project rules in the project section of `AGENTS.md`, below the END marker. Never edit
  the block; `vstd check` fails on a hand edit.
- Claude Code-only notes go below the import in `CLAUDE.md`. Don't copy rule lines there.
- Need a different SHOULD rule? Add an override; see [overrides.md](overrides.md).
- Nested `AGENTS.md` files (for example `web/AGENTS.md`) are project-owned. Codex reads them only
  when started in that folder. Set `nested_parity = true` so Claude Code reads them too.
- Don't commit `AGENTS.override.md`; it makes Codex ignore `AGENTS.md` in that folder.

## 4. Updates and rollback

- The weekly job opens or updates one PR on `standards/update` with the files, rule IDs and
  changelog. It never merges. To update now, run the workflow by hand and pick `open-pr` under "What the sync should do"; the default, `diff-only`, prints the diff and changes nothing.
- `upgrade = "patch"` or `"minor"` limits what it proposes. A new major always needs a hand
  edit of `version` and `commit`.
- Roll back by reverting the sync PR, or set `version` and `commit` back to the earlier release
  and run sync. The generator reproduces each release byte for byte.
- To stay on the earlier release, also set `upgrade = "manual"`. Otherwise the next weekly
  sync proposes the newer release again.

## 5. Checking what each assistant loaded

- Codex: `codex --ask-for-approval never "Summarize the current instructions."`
- Claude Code: `/context` lists the memory files it loaded; `/memory` opens them.

## Leaving

`python3 -I vstd/main.py eject --repo ../your-repo` keeps the rules as plain text in
`AGENTS.md`, keeps `CLAUDE.md`, and removes the config and workflow.
