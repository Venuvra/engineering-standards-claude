# Changelog

Each release lists the rule IDs it adds, changes or removes. `vstd sync` copies the
sections between a repository's pinned version and the target into the update PR, and
repeats any line containing `BREAKING` at the top of the PR body.

Versioning: MAJOR when a MUST rule is added or tightened, a rule is removed, or the
config schema breaks; MINOR for new SHOULD rules or a new stack profile; PATCH for
wording only. Tags `vX.Y.Z` are immutable.

## Unreleased

- Rules: core (AGT, ENG, SEC, TST, DOC, GIT), stacks `typescript` (TS) and `python` (PY).
- `vstd check`, `vstd sync` (`--dry-run`, `--local`).
