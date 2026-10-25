# 0001. `vstd rollout` may tick the Actions pull-request setting

- Status: accepted
- Date: 2026-10-25

## Context

The weekly sync opens its PR with the repository's own `GITHUB_TOKEN`. GitHub refuses that
until "Allow GitHub Actions to create and approve pull requests" is ticked in the repository
(and allowed by the organisation). Ticking it by hand in every onboarded repository was the
last manual setting in a rollout, and the maintainers asked for onboarding without manual
steps other than the merge.

## Decision

`vstd rollout --allow-actions-prs` sets `can_approve_pull_request_reviews: true` through
`PUT /repos/{repo}/actions/permissions/workflow`, using the token of the person running it.

- It is opt-in per run. Without the flag rollout changes no setting.
- It sends the repository's current `default_workflow_permissions` back unchanged, and warns
  when that is `write`.
- It changes nothing else: no rulesets, branch protection, secrets or other Actions settings.
- When the organisation locks the setting, the PR still opens and the result says to tick it
  by hand.

## Consequences

The API has one switch for both creating and approving PRs, the same as the checkbox, so
workflows in the repository can also approve PRs. Merges still need the review the branch
rules require, and nothing in `vstd` merges. A person reviews and merges every onboarding PR.
