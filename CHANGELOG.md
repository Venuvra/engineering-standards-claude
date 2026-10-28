# Changelog

Each release lists the rule IDs it adds, changes or removes. `vstd sync` copies the
sections between a repository's pinned version and the target into the update PR, and
repeats any line containing `BREAKING` at the top of the PR body.

Versioning: MAJOR when a MUST rule is added or tightened, a rule is removed, or the
config schema breaks; MINOR for new SHOULD rules or a new stack profile; PATCH for
wording only. Tags `vX.Y.Z` are immutable.

## Unreleased

- Rules added, changed or removed: none.

## v0.4.1

Patch release. No rule changes.

- Rules added, changed or removed: none.
- Windows checkouts work. Git on Windows (`core.autocrlf`) checks files out with CRLF, which made
  `vstd check` and `vstd sync` report "the managed block was edited by hand (hash mismatch)" on an
  untouched block. The block check now ignores CRLF, and `vstd sync` starts from the committed
  bytes of the files it owns, so its PR carries LF only. Repositories pinned to an earlier release
  sync from a clone made with `git clone -c core.autocrlf=false` once; see `docs/no-actions.md`.

## v0.4.0

Minor release (new SHOULD rules only).

- Rules added: TST-007 (one-command container test gate for every deployable project),
  TST-008 (test container matches the cloud deploy target: base image, OS, CPU architecture,
  runtime and database versions), TST-009 (hosted CI such as GitHub Actions is optional;
  where it runs it calls the same container command, and every PR reports the result).
- New guide: `docs/container-testing.md`.
- `vstd check --post-status` sets the `standards/check` commit status from a local run, marked
  "(local run)", for when Actions can't run (for example, the organisation's minutes or spending
  limit ran out). It refuses a working tree with uncommitted changes.
- `docs/no-actions.md`: the local equivalent of each job the workflow runs (check, sync, release).

## v0.3.1

Patch release. No rule changes. Use this instead of v0.3.0.

- Rules added, changed or removed: none.
- The `v0.3.0` tag was pushed on the commit before the release PR merged, so it points at a
  development build (`0.2.1.dev0`) and was never published. Tags can't move; v0.3.1 carries
  everything listed under v0.3.0. Don't pin `v0.3.0`.
- `vstd sync` refuses a release tag whose `vstd/__init__.py` names a different version, so a
  mistagged release is never proposed.
- `docs/releasing.md`: tag the release PR's merge commit by its SHA, after the merge.

## v0.3.0 (tagged in error, not published)

Minor release. No rule changes. Onboarding with `vstd rollout` needs no manual step except the
merge, and the workflow runs the first sync by itself.

- Rules added, changed or removed: none.
- `vstd rollout` drafts the project section of a new `AGENTS.md` from the repository's own
  files (package.json scripts, Makefile targets, pyproject.toml tools, CI `run:` lines).
- `vstd rollout --allow-actions-prs` ticks "Allow GitHub Actions to create and approve pull
  requests" in each repository it onboards. It changes no other setting.
- `vstd rollout` ends with the onboarding PRs and their check state.
- Workflow template: the sync job also runs on a push that changes `.venuvra/standards.toml`,
  so the first sync after onboarding needs no manual run. Installed workflows keep the old
  behaviour until `vstd init --force`.

## v0.2.0

Minor release. No rule changes. New rollout tooling and a dropdown in the workflow's
manual-run form.

- Rules added, changed or removed: none.
- Workflow template: the manual "Run workflow" form uses a dropdown, `mode`, with
  `diff-only` (default, changes nothing) and `open-pr`, instead of the `dry_run` checkbox.
  Sync never rewrites an installed workflow, so repositories onboarded earlier keep the
  checkbox until they rerun `vstd init --force`.
- New `vstd rollout`: onboards a list of repositories, one `standards/onboard` PR each, on
  each repository's own default branch. Skips repositories already onboarded or with an open
  onboarding PR; `--dry-run` runs `init` and `check` without pushing. It never merges.

## v0.1.1

Patch release. No rule changes. Fixes found in the first live sync on the fixture.

- Rules added, changed or removed: none.
- `vstd sync`: when the GitHub API refuses a request, the error now includes GitHub's own
  message (one line, bounded), for example why a pull request could not be created.
- Rendering: an override `replacement` or `reason` that already ends in `.`, `!` or `?` no
  longer gets a second period in "Project overrides". Repositories without such overrides see
  only the version line change.

## v0.1.0

First release.

- Rules added: core AGT-001..008, ENG-001..009, SEC-001..012, TST-001..006, DOC-001..004,
  GIT-001..006 (45 rules, 22 MUST); stacks `typescript` TS-001..012 and `python` PY-001..013.
- Tooling: `vstd check`, `vstd sync` (`--dry-run`, `--local`), `vstd init`, `vstd eject`,
  `vstd lint-workflows`.
- Workflows: caller template `templates/standards.yml`; `release.yml` for this repo.
- Config: `.venuvra/standards.toml` schema 1.
