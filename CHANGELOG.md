# Changelog

Each release lists the rule IDs it adds, changes or removes. `vstd sync` copies the
sections between a repository's pinned version and the target into the update PR, and
repeats any line containing `BREAKING` at the top of the PR body.

Versioning: MAJOR when a MUST rule is added or tightened, a rule is removed, or the
config schema breaks; MINOR for new SHOULD rules or a new stack profile; PATCH for
wording only. Tags `vX.Y.Z` are immutable.

## v0.1.0

First release.

- Rules added: core AGT-001..008, ENG-001..009, SEC-001..012, TST-001..006, DOC-001..004,
  GIT-001..006 (45 rules, 22 MUST); stacks `typescript` TS-001..012 and `python` PY-001..013.
- Tooling: `vstd check`, `vstd sync` (`--dry-run`, `--local`), `vstd init`, `vstd eject`,
  `vstd lint-workflows`.
- Workflows: caller template `templates/standards.yml`; `release.yml` for this repo.
- Config: `.venuvra/standards.toml` schema 1.
