+++
profile = "core/git-workflow"
title = "Git workflow"
prefix = "GIT"
+++

- [GIT-001 MUST] Never push directly to the default branch; every change goes through a reviewed pull request.
- [GIT-002 MUST] Never force-push or rewrite history on a shared branch.
- [GIT-003 MUST] Never merge with failing required checks.
- [GIT-004 SHOULD] Keep one logical change per branch and PR, small enough to review in one sitting.
- [GIT-005 SHOULD] Write commit subjects in the imperative, at most 72 characters, with context in the body.
- [GIT-006 SHOULD] Describe in each PR what changed, why, how it was tested and the risks.
