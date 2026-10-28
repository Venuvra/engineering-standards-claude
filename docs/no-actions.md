# When GitHub Actions can't run

GitHub stops starting jobs in private repositories when the organisation's Actions minutes or
spending limit run out, or a payment fails. The job then fails with "The job was not started
because recent account payments have failed or your spending limit needs to be increased". Public
repositories, including this one, keep running on GitHub-hosted runners.

Nothing in the standards needs Actions to work: agents read `AGENTS.md` and `CLAUDE.md` from the
repository either way. Actions only automates the check, the sync and the release. Each has a
local equivalent that runs with your own GitHub login and reaches the same result.

| Actions does | Local equivalent |
| --- | --- |
| `standards/check` on each PR and push | `vstd check --post-status` |
| Weekly sync PR (Monday 06:17 UTC) and the first sync after onboarding | `vstd sync` |
| Publishing a release after the tag is pushed | `gh release create`, below |

Nothing here merges: every change still reaches a default branch through a PR you review.

## Set up once per shell

Run every command from a clean checkout of the release the repository pins (the `version` in
its `.venuvra/standards.toml`). In PowerShell:

```powershell
cd <path to engineering-standards-claude>
git fetch origin --tags
git switch --detach v<pinned version>
$env:GH_TOKEN = gh auth token
$env:GITHUB_REPOSITORY = "<org>/<repo>"
```

In a POSIX shell, use `export NAME=value` and `python3`.

## Check a PR

Check out the PR's branch in the repository, make sure it is pushed and has no uncommitted
changes, then:

```powershell
python -I vstd/main.py check --repo <path to repo> --post-status
```

It prints the usual report and sets the `standards/check` commit status on the checked-out
commit, marked "(local run)", so the PR shows the result as if the workflow had run. It refuses
when the working tree has uncommitted changes, because the status must describe exactly the
commit that was checked. Without `--post-status` nothing is sent to GitHub.

Repository CI other than the standards check (tests, builds) doesn't run either; run the
repository's own check commands from the project section of its `AGENTS.md`.

## Sync

From a clean checkout of the repository's default branch, up to date with the remote:

```powershell
python -I vstd/main.py sync --repo <path to repo> --base <default branch> --dry-run   # diff only
python -I vstd/main.py sync --repo <path to repo> --base <default branch>             # open or update the PR
```

The real run pushes `standards/update`, opens or updates its PR and sets `standards/check` on
it, exactly as the scheduled job does. Run it weekly while Actions is out, and once after merging
an onboarding PR.

## Release

This repository is public, so its release workflow keeps running. If it can't run anyway, the
release still reaches repositories: `vstd sync` reads release tags, not GitHub release objects,
and refuses a tag whose `vstd/__init__.py` names another version. To publish the release page by
hand, repeat the workflow's checks first:

```powershell
git fetch origin --tags
git switch --detach v<X.Y.Z>
Select-String '__version__' vstd/__init__.py      # must say <X.Y.Z>
python -I -m unittest discover -s tests -t .     # must end with OK
gh api "repos/<org>/engineering-standards-claude/commits/v<X.Y.Z>/check-runs?check_name=ci" --jq '.check_runs[].conclusion'
```

The last line must print `success`; if `ci` couldn't run, say so in the release notes. Then copy
the `## v<X.Y.Z>` section of `CHANGELOG.md` into `notes.md` and run:

```powershell
gh release create v<X.Y.Z> --verify-tag --title v<X.Y.Z> --notes-file notes.md
```

## When Actions is back

Nothing to undo. The next PR or push runs `standards/check` again, and the weekly sync finds any
PR you opened by hand and updates it instead of opening a second one.
