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
left to confirm. Run locally, the token is your own because the PR adds a workflow file, which a
workflow's `GITHUB_TOKEN` can't push. The Action below uses a GitHub App or a fine-grained PAT
instead.

## From GitHub Actions: the `rollout` workflow

`.github/workflows/rollout.yml` in this repository runs the same `vstd rollout` from a release tag,
so nobody needs a local checkout. Start it from Actions → rollout → Run workflow:

| Input | Values | Meaning |
| --- | --- | --- |
| Release tag | `vX.Y.Z` | The release to check out and pin in every repository |
| Repositories | `a, b` or `<org>/a, <org>/b` | Repositories in this organisation only |
| What the rollout should do | `dry-run` (default), `open-prs` | `dry-run` runs init and check and pushes nothing |
| Actions PR setting | `no` (default), `yes` | `yes` adds `--allow-actions-prs` to an `open-prs` run |

The result is printed in the log and on the run's summary page, with the PR list. It runs on
GitHub-hosted runners: this repository is public, so the private-repository billing limit doesn't
stop it, and the self-hosted runners stay off a public repository. It never merges, and the PRs
still need a person's review.

**Skip list.** Repositories that must never get these PRs, for example ones that already carry a
different standards system, go in the variable `ROLLOUT_SKIP` (comma-separated) on the `rollout`
environment. The workflow reports them as skipped even when they are listed in a run. Keep the list
in the variable, not in a file, because this repository is public.

### Set up once: the token

A workflow's own `GITHUB_TOKEN` only reaches this repository, so the workflow needs a token that can
write to the others. Both options live in a GitHub environment named `rollout`, so only this
workflow can read them, and you can make every run wait for your approval.

**1. Create the environment.** Settings → Environments → New environment → `rollout`. Under
"Deployment protection rules" tick "Required reviewers" and add yourself, so a run starts only
after you approve it. Under "Deployment branches and tags" pick "Selected branches and tags" and add
`main`.

**2a. GitHub App (recommended).** Its tokens last an hour, cover only the repositories in the run,
and are revoked when the job ends; nothing is tied to a person's account.

1. Organisation Settings → Developer settings → GitHub Apps → New GitHub App.
   - Name: for example `<org>-standards-rollout`. Homepage URL: this repository's URL.
   - Webhook: untick "Active".
   - Repository permissions: Contents read and write, Pull requests read and write,
     Workflows read and write, Checks read-only (Metadata read-only is added for you). Add
     Administration read and write only if you will use the Actions PR setting `yes`.
   - "Where can this GitHub App be installed?": Only on this account.
2. Create it, note the **Client ID** at the top of the page, then "Generate a private key". A
   `.pem` file downloads.
3. Install App → the organisation → "All repositories", or "Only select repositories" listing the
   ones to roll out to. A run fails for a repository the App isn't installed on.
4. Store the client ID and key in the `rollout` environment. In PowerShell, from this repository's
   checkout:

   ```powershell
   gh variable set ROLLOUT_APP_CLIENT_ID --env rollout --body "<client id>"
   Get-Content -Raw "$HOME\Downloads\<file>.pem" | gh secret set ROLLOUT_APP_PRIVATE_KEY --env rollout
   Remove-Item "$HOME\Downloads\<file>.pem"
   ```

   In a POSIX shell: `gh secret set ROLLOUT_APP_PRIVATE_KEY --env rollout < <file>.pem`.

The onboarding commits and PRs show the App as author (`<app-name>[bot]`).

**2b. Fine-grained PAT (alternative).** Simpler to make, but it acts as you and has to be renewed
when it expires.

1. Your Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new
   token.
   - Resource owner: the organisation (the organisation may need to approve the token).
   - Expiration: as short as suits you, for example 30 days.
   - Repository access: only the repositories to roll out to.
   - Repository permissions: the same as the App above.
2. Store it:

   ```powershell
   gh secret set ROLLOUT_PAT --env rollout
   ```

   `gh` asks for the value; paste the token.

When `ROLLOUT_APP_CLIENT_ID` is set the workflow uses the App and ignores `ROLLOUT_PAT`. With
neither, the run stops with a message naming these settings.

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
