# Changelog

Each release lists the rule IDs it adds, changes or removes. `vstd sync` copies the
sections between a repository's pinned version and the target into the update PR, and
repeats any line containing `BREAKING` at the top of the PR body.

Versioning: MAJOR when a MUST rule is added or tightened, a rule is removed, or the
config schema breaks; MINOR for new SHOULD rules or a new stack profile; PATCH for
wording only. Tags `vX.Y.Z` are immutable.

## Unreleased

- Rules added, changed or removed: none.
- Workflow template: the manual "Run workflow" form uses a dropdown, `mode`, with
  `diff-only` (default, changes nothing) and `open-pr`, instead of the `dry_run` checkbox.
  Sync never rewrites an installed workflow, so repositories onboarded earlier keep the
  checkbox until they rerun `vstd init --force`.

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
