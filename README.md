# Venuvra engineering standards

Central source of truth for the engineering rules that Venuvra repositories give to
AI coding assistants. Codex reads them from each repo's `AGENTS.md`; Claude Code reads
the same file through a one-line `@AGENTS.md` import in `CLAUDE.md`.

The generator and checker, `vstd`, use the Python 3.11+ standard library only.

## Docs

- [Adopting the standards in a repository](docs/adopting.md)
- [Rolling out across repositories](docs/rollout.md)
- [Overrides](docs/overrides.md)
- [Container test gate](docs/container-testing.md)
- [Releasing](docs/releasing.md)
- [Changelog](CHANGELOG.md)

## Status

Milestone M1: core rules plus the TypeScript and Python stacks, `vstd check`, `sync`,
`init`, `rollout`, `eject` and `lint-workflows`. Released as v0.1.0, v0.1.1, v0.2.0 and v0.3.1 (v0.3.0 was tagged in error); see the
[changelog](CHANGELOG.md).

## Onboarding and leaving

From a clean checkout of a release tag (`git checkout vX.Y.Z`):

```sh
python3 -I vstd/main.py init --repo ../my-repo            # stacks detected from manifests
python3 -I vstd/main.py init --repo ../my-repo --stacks typescript,python
```

`init` writes `.venuvra/standards.toml`, `.github/workflows/standards.yml`, and the
first-run `AGENTS.md` / `CLAUDE.md` into the working tree and lists every file. Existing
`AGENTS.md` and `CLAUDE.md` content is kept. An existing config or standards workflow is
kept unless you pass `--force`. A person pushes this first PR, because `GITHUB_TOKEN`
can't create workflow files.

Stacks are detected from manifests in the root and one folder down: `package.json`,
`tsconfig.json` or `pnpm-lock.yaml` mean `typescript`; `pyproject.toml`, `setup.py`,
`setup.cfg`, `Pipfile`, `requirements*.txt`, `uv.lock` or `poetry.lock` mean `python`.

To onboard many repositories at once, `rollout` runs `init` and `check` on each one's
default branch and opens one PR per repository with your own token; it never merges.
See [docs/rollout.md](docs/rollout.md):

```sh
GH_TOKEN="$(gh auth token)" python3 -I vstd/main.py rollout --repos-file repos.txt --dry-run
```

`eject` stops using the central standards. It removes the markers from `AGENTS.md` and
keeps the rules as plain text, keeps `CLAUDE.md` and its `@AGENTS.md` import, and deletes
the config and the standards workflow (a workflow not installed by `init` is kept).
After that, `vstd check` reports the repo as not managed.

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
python3 -I -m unittest discover -s tests -t .
python3 -I vstd/main.py check --repo .
python3 -I vstd/main.py lint-workflows .github/workflows templates/standards.yml
```

This repository follows its own standards: see [AGENTS.md](AGENTS.md).
