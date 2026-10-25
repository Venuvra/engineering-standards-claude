# Rolling the standards out across repositories

This runbook takes a set of repositories onto the standards, one onboarding PR per repository.
[adopting.md](adopting.md) explains each file and setting; this page is the order of work and
the checks that say a repository is done.

## Before you start

- **Approval.** A rollout to existing repositories needs the owner's go-ahead for the list of
  repositories. Nothing merges without a person's review.
- **Release.** Use the latest release (`vX.Y.Z` from the changelog). Every repository in one
  rollout gets the same pin.
- **Org setting.** If the organisation locks "Allow GitHub Actions to create and approve pull
  requests", unlock it at the organisation level first, or the repository setting stays greyed
  out.
- **One system per repository.** Skip any repository that already carries a different
  standards system; two managed blocks in one `AGENTS.md` contradict each other.

## Automated: `vstd rollout`

`vstd rollout` does every step below except the merge, for a list of repositories, from a clean
checkout of the release tag, with your own GitHub login. In PowerShell:

```powershell
git switch --detach vX.Y.Z
$env:GH_TOKEN = gh auth token
python -I vstd/main.py rollout --repos-file repos.txt --dry-run                # init and check only
python -I vstd/main.py rollout --repos-file repos.txt --allow-actions-prs      # push branches, open PRs
```

In a POSIX shell, use `export GH_TOKEN="$(gh auth token)"` and `python3`.

`repos.txt` lists `<org>/<repo>` one per line (or comma-separated); `#` starts a comment, so a
skipped repository can stay in the list with its reason. `--repos <org>/a,<org>/b` works too.

For each repository it reads the default branch from GitHub, skips the repository when
`.venuvra/standards.toml` is already on that branch or a `standards/onboard` PR is open, clones
the default branch into a temporary folder, runs `init --default-branch <default>` and `check`,
then commits on `standards/onboard`, pushes without force and opens one PR. A repository that
fails is reported and the rest go on; the command exits 1 if any failed. Rerunning it is safe:
repositories already done or with an open PR are skipped, and a `standards/onboard` branch left by
a run whose PR failed is reused when it holds the same files (otherwise that repository fails
with a message and the branch is left alone).

What it automates beyond the clone and PR:

- **Project section (step 5).** When `init` creates `AGENTS.md`, rollout drafts its project
  section from the repository's own files: `package.json` scripts, `Makefile` targets, tools
  configured in `pyproject.toml`, and one-line `run:` steps in its CI workflows. Nothing is
  guessed or run; if nothing is found, the section says so. A repository that already had
  `AGENTS.md` keeps its own text and gets no draft.
- **Actions setting (step 7).** With `--allow-actions-prs` it ticks "Allow GitHub Actions to
  create and approve pull requests" through the API and leaves the default token permission as
  it is (it warns when that is read and write). If the organisation locks the setting, the PR
  still opens and the warning says to tick it by hand. Without the flag, no setting changes.
- **First sync (step 9).** The workflow runs the sync by itself on the push that changes
  `.venuvra/standards.toml`, so merging the onboarding PR is enough. A rebase merge of several
  commits may not trigger it; the weekly sync then does the same check on Monday.
- **Merge list.** It ends with every onboarding PR and its check state (green, running,
  failing). Rerun it later to refresh the states.

The merge (step 8) stays with a person: standards changes reach a default branch only through a
reviewed PR, and rollout never merges or pushes to the default branch. The PR body lists what is
left to confirm. The token is the person's own because
the PR adds a workflow file, which a workflow's `GITHUB_TOKEN` can't push; a central Action
would need an organisation-wide token with workflow scope.

## Per repository

Work through the list one repository at a time. Each step's check must pass before the next.
`vstd rollout` above does all of them except 8.

| Step | Who | Do | Done when |
| --- | --- | --- | --- |
| 1. Survey | Agent or maintainer | Note the default branch (`gh api repos/<org>/<repo> --jq .default_branch`), the stacks, any existing `AGENTS.md` or `CLAUDE.md`, and open PRs | Default branch and stacks known |
| 2. Branch | Agent or maintainer | `git switch -c standards/onboard` from the default branch | Clean branch off the latest default branch |
| 3. Init | Agent or maintainer | `python3 -I vstd/main.py init --repo <path> --default-branch <default>` from the release checkout | Prints the stacks and the 4 files it wrote |
| 4. Check | Agent or maintainer | `python3 -I vstd/main.py check --repo <path>` | `OK (0 error(s))`; warnings are advice |
| 5. Project section | Agent or maintainer | Fill the section below the END marker in `AGENTS.md` with build and test commands and the repository's own rules, from its README | An agent could run the checks from that section alone |
| 6. PR | Agent or maintainer | Push the branch, open the PR against the default branch, assign the owner | `standards/check` and the repository's own CI are green |
| 7. Settings | Owner | Settings → Actions → General → tick "Allow GitHub Actions to create and approve pull requests" → Save | Box ticked |
| 8. Merge | Owner | Review and merge | `standards/check` passes on the push to the default branch |
| 9. Sync | Automatic | Runs on the merge push. By hand: Actions → standards → Run workflow, "What the sync should do" set to `open-pr` (workflows from before v0.2.0: untick "Print the diff only") | The `vstd sync` step logs `Up to date with vX.Y.Z; nothing to do.` |

## Branches

- **Default branch not `main`.** `init` writes the push trigger for the branch named by
  `--default-branch`, or the checked-out branch when the flag is left out. Pass it explicitly
  so a run from a feature branch doesn't pin the wrong one.
- **Renaming the default branch later.** Update `branches:` under `push:` in
  `.github/workflows/standards.yml` in the same PR as the rename, or rerun `init --force` with the
  new name. `vstd check` doesn't read that line, so nothing else flags the mismatch.
- **Long-lived release branches.** Onboard the default branch only. Other branches pick the files
  up when they merge from it; the weekly sync runs on the default branch alone.
- **Open PRs at onboarding.** They merge cleanly unless they also add `AGENTS.md` or `CLAUDE.md`.
  If one does, merge the onboarding PR first and rebase or merge the default branch into the other.

## Special cases

- **Existing `CLAUDE.md` with rules.** `init` keeps it and adds `@AGENTS.md` on line 1. Its rules
  stay Claude-only; Codex never reads `CLAUDE.md`. Move shared rules into the project section of
  `AGENTS.md` in a follow-up PR.
- **Stacks without rules yet.** A repository whose stacks aren't in this release gets the core
  rules only. Record the missing stacks in its PR.
- **Private repositories on the free plan.** Rulesets aren't available, so `standards/check` can't
  be required. It still runs and reports; treat it as advisory there.
- **Nested `AGENTS.md`.** Kept as project-owned. Set `nested_parity = true` if Claude Code should
  read them too.

## Tracking

Keep one row per repository in the rollout issue:

| Repository | Default branch | Stacks | PR | CI | Setting | Merged | Sync |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<repo>` | `main` | typescript | #1 | green | on | yes | nothing to do |

## Undo

- **Before merge:** close the PR and delete the branch.
- **After merge:** `vstd eject` keeps the rules as plain text in `AGENTS.md` and removes the config
  and the workflow; or revert the onboarding PR to remove everything.
