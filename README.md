# Venuvra engineering standards

Central source of truth for the engineering rules that Venuvra repositories give to
AI coding assistants. Codex reads them from each repo's `AGENTS.md`; Claude Code reads
the same file through a one-line `@AGENTS.md` import in `CLAUDE.md`.

The generator and checker, `vstd`, use the Python 3.11+ standard library only.

## Status

Under construction (milestone M1). See the issues for the plan.

## Sync

The standards workflow in each repository checks out this repo at the commit pinned in
`.venuvra/standards.toml` and runs `python3 -I vstd/main.py sync --repo <repo>`:

- It verifies that tag `v<version>` points at `commit`, then picks the newest release the
  `upgrade` policy allows: `manual` stays put, `patch` takes new patches, `minor` takes new
  minors and patches. A new major is never proposed; the PR and log mention it instead.
- It renders into a scratch copy with the target release's own `vstd`, so the working tree
  is never written. Only `.venuvra/standards.toml`, `AGENTS.md` and `CLAUDE.md` files may change.
- If nothing changed, it stops. Otherwise it commits to `standards/update` (fast-forward
  only, never a force-push), opens or updates one PR, and sets the `standards/check` commit
  status. It never merges.
- `--dry-run` prints the diff and writes nothing. `--local` only renders this release into
  the given working tree, for local use.

It reads `GH_TOKEN` and `GITHUB_REPOSITORY` from the environment and talks only to
`api.github.com` and `github.com`. The token is never passed to the target release's code,
never put on a command line, and never logged.

## Workflows

- `templates/standards.yml` is the workflow `vstd init` installs in each repository. The
  `check` job runs on PRs and pushes with `contents: read`; the `sync` job runs weekly or
  by hand. Both read `version` and `commit` from `.venuvra/standards.toml`, confirm with
  `git ls-remote` that tag `v<version>` points at `commit`, and check this public repo out
  at that commit with no credentials. Upgrades only change `standards.toml`, so the
  workflow file never needs the `workflows` permission that `GITHUB_TOKEN` lacks.
- `.github/workflows/release.yml` runs when a `vX.Y.Z` tag is pushed. It checks that the
  tag is on `main`, matches `vstd/__init__.py` and has a green `ci` check, re-runs the
  tests, and publishes the release with the tag's `CHANGELOG.md` section. It never
  creates or moves tags.
- `vstd lint-workflows` checks our workflows in CI: no `pull_request_target` or
  `workflow_run`, explicit top-level `permissions` (never `write-all`), every `uses:`
  pinned to a full SHA, and no `${{ }}` inside `run:` (values go through `env:`). Python
  has no standard YAML parser, so it matches known patterns line by line. It is meant for
  these files, not as a general YAML linter.

## Development

```sh
python3 -m unittest discover -s tests -t .
```
