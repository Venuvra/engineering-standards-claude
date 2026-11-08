# Releasing

Only maintainers in `CODEOWNERS` release. Releases are tags `vX.Y.Z` on `main`; tags are
immutable, so a bad release is fixed by a new PATCH, never by moving a tag.

## Version bump rules

| Change | Bump |
| --- | --- |
| MUST rule added or tightened, any rule removed, config schema break | MAJOR |
| SHOULD rule added, new stack profile, new optional config key | MINOR |
| Wording that keeps the meaning, tooling fixes | PATCH |

Rule IDs are never reused. A removed rule's ID goes into `rules/retired.toml`.

## Steps

1. In a PR: set `__version__` in `vstd/__init__.py` to `X.Y.Z` and turn `## Unreleased`
   in `CHANGELOG.md` into `## vX.Y.Z`. List rule IDs added, changed and removed, and start
   any breaking line with `BREAKING:`. Set `version = "X.Y.Z"` in this repo's
   `.venuvra/standards.toml` (its `commit` stays zeroed). Then re-render this repo's `AGENTS.md`
   (`python3 -I vstd/main.py sync --local --repo .`) and update the golden files if the output changed.
2. Merge after `ci` is green. Merging is the release approval.
3. On the push to `main`, `ci` runs its tests, then its `tag` job sees a release version (no
   `.devN`) and creates the tag `vX.Y.Z` on that merge commit. It refuses when `CHANGELOG.md`
   has no `## vX.Y.Z` section and does nothing when the tag already exists, so re-runs are safe.
   Nobody types a SHA.
4. `ci` then calls `release.yml`, which checks the tag is on `main`, matches `__version__` and
   has a green `ci` check, re-runs the tests and publishes the release with that changelog
   section.

   By hand, if the automatic tag didn't run: tag the merge commit by SHA (the PR page shows it),
   not a branch name, and `release.yml` runs on the tag push the same way. In PowerShell:

   ```powershell
   git fetch origin
   git tag vX.Y.Z <merge sha>
   git push origin vX.Y.Z
   ```

   A tag on any other commit fails the release check and can't be moved; the fix is the next
   PATCH release.
5. Set `__version__` back to the next `.dev0` and add a new `## Unreleased` section.

Repositories pick the release up on their next weekly sync, subject to their `upgrade` policy.

## Settings this relies on

- A tag ruleset on `v*`: no updates or deletions, so released tags can't move. It must not
  restrict creation, or `ci`'s `tag` job (GitHub Actions) needs to be a bypass actor.
- A branch ruleset on `main` that requires PRs and the `ci` check.
