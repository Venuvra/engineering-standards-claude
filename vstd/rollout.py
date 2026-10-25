"""Onboard many repositories at once (``vstd rollout``).

For each ``owner/name``, run from a checkout of a release:

1. Ask GitHub for the default branch. Skip the repository when it already has
   ``.venuvra/standards.toml`` there, or an open onboarding PR.
2. Shallow-clone the default branch into a scratch folder.
3. Run ``vstd init`` with that default branch, then ``vstd check``. Stop for
   this repository on any error. When init creates AGENTS.md, its project
   section lists the check commands the repository already declares.
4. Commit on ``standards/onboard``, push it (never force) and open one PR. A branch
   left by an earlier run is reused when its files match, else the repository fails.

With ``--allow-actions-prs`` it also ticks the repository's "Allow GitHub
Actions to create and approve pull requests" setting, so the weekly sync can
open its PRs; it changes no other setting. It never merges and never pushes to
the default branch. A failure in one repository is reported and the rest go on.
It runs with the token of the person starting it (``GH_TOKEN``): the first PR
adds a workflow file, which a workflow's ``GITHUB_TOKEN`` can't do.
``--dry-run`` stops after step 3 and pushes nothing.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from vstd import config as config_mod
from vstd import github
from vstd.check import check
from vstd.commands import detect_commands, project_section
from vstd.init import InitError, init
from vstd.rules import RuleSet
from vstd.sync import SyncError, git, git_auth_env
from vstd.writer import WriterError

BRANCH = "standards/onboard"
# The line of render.PROJECT_SECTION that the drafted commands replace in a new AGENTS.md.
PLACEHOLDER = "Add build and test commands, architecture notes and project rules here.\n"


@dataclass
class RepoResult:
    repo: str
    outcome: str  # "opened", "ready" (dry run), "skipped" or "failed"
    detail: str
    pr_url: str | None = None
    stacks: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)
    checks: str = ""  # CI state of the PR head: green, running, failing or no checks


def parse_repo_list(text: str) -> list[str]:
    """``owner/name`` per line or comma; ``#`` starts a comment. Duplicates are dropped, order kept."""
    repos: list[str] = []
    for line in text.splitlines():
        for item in line.split("#", 1)[0].split(","):
            item = item.strip()
            if item and item not in repos:
                repos.append(item)
    return repos


def pr_body(version: str, default_branch: str, stacks: tuple[str, ...], written: list[str], warnings: list[str],
            drafted: bool, setting: str | None) -> str:
    lines = [
        f"Onboards this repository to the Venuvra engineering standards v{version}, opened by `vstd rollout`.",
        "",
        f"- Stacks: {', '.join(stacks) or 'none detected (core rules only)'}",
        f"- Push check runs on `{default_branch}`",
        "- Files: " + ", ".join(f"`{p}`" for p in written),
        "",
        "Before merging:",
        ("- [ ] Confirm the check commands drafted in the project section at the end of `AGENTS.md`, and add the repository's own rules."
         if drafted else
         "- [ ] Fill in the project section at the end of `AGENTS.md` with this repository's build and test commands and its own rules."),
        "- [ ] Check that any existing `AGENTS.md` or `CLAUDE.md` text was kept.",
        ("- [x] \"Allow GitHub Actions to create and approve pull requests\" was turned on by `vstd rollout`."
         if setting else
         "- [ ] In Settings → Actions → General, allow GitHub Actions to create and approve pull requests, so the weekly sync can open its PRs."),
        "",
        "Merging runs the standards sync once by itself; it should log `nothing to do`.",
    ]
    if warnings:
        lines += ["", "`vstd check` warnings (advice only; not changed here):", ""] + [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"


def onboard(
    repo: str,
    ruleset: RuleSet,
    *,
    version: str,
    commit: str,
    standards_root: Path,
    token: str,
    author: tuple[str, str],
    workdir: Path,
    dry_run: bool = False,
    api_url: str = github.API_URL,
    clone_url: str | None = None,
    allow_actions_prs: bool = False,
) -> RepoResult:
    try:
        client = github.Client(repo, token, api_url)
        base = client.default_branch()
        notes: list[str] = []

        def setting() -> str | None:
            if not allow_actions_prs or dry_run:
                return None
            try:
                default = client.allow_actions_prs()
            except github.GitHubError as exc:
                # The PR is still useful; the owner can tick the box by hand.
                notes.append(f"could not turn on the Actions PR setting ({exc}); tick it in Settings → Actions → General")
                return None
            if default == "write":
                notes.append("the default GITHUB_TOKEN permission is read and write; consider read-only")
            return "on"

        if client.file_text(config_mod.CONFIG_PATH.as_posix(), base) is not None:
            setting()
            return RepoResult(repo, "skipped", f"already onboarded on {base}", warnings=notes)
        pr = client.find_open_pr(BRANCH, base)
        if pr is not None:
            setting()
            state = client.check_state(pr.head_sha) if pr.head_sha else "no checks"
            return RepoResult(repo, "skipped", "onboarding PR already open", pr.url, warnings=notes, checks=state)

        url = clone_url or f"https://github.com/{repo}.git"
        auth = git_auth_env(token) if url.startswith("https://github.com/") else {}
        dest = workdir / repo.replace("/", "__")
        git(["clone", "-q", "--depth", "1", "--branch", base, "--", url, str(dest)], env=auth)

        had_agents = (dest / "AGENTS.md").exists()
        result = init(dest, ruleset, version=version, commit=commit, standards_root=standards_root, default_branch=base)
        drafted = not had_agents
        if drafted:
            agents = dest / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8").replace(PLACEHOLDER, "\n" + project_section(detect_commands(dest)), 1),
                              encoding="utf-8", newline="")
        report = check(dest, ruleset, version)
        if report.errors:
            return RepoResult(repo, "failed", "vstd check: " + "; ".join(f"{p.path}: {p.problem}" for p in report.errors), stacks=result.stacks)
        warnings = [f"{p.path}: {p.problem}" for p in report.warnings]
        if dry_run:
            return RepoResult(repo, "ready", f"would open a PR against {base}", stacks=result.stacks, warnings=warnings)

        name, email = author
        who = ["-c", f"user.name={name}", "-c", f"user.email={email}"]
        git(["checkout", "-q", "-b", BRANCH], cwd=dest)
        git(["add", "--", *result.written], cwd=dest)
        git([*who, "commit", "-q", "-m", f"Adopt Venuvra engineering standards v{version}"], cwd=dest)
        if git(["ls-remote", "--heads", url, BRANCH], cwd=dest, env=auth):
            # Left by an earlier run whose PR creation failed. Reuse it when it holds exactly
            # this content; a new commit can't replace it without a force push.
            git(["fetch", "-q", "--depth", "1", url, f"refs/heads/{BRANCH}"], cwd=dest, env=auth)
            if git(["rev-parse", "FETCH_HEAD^{tree}"], cwd=dest) != git(["rev-parse", "HEAD^{tree}"], cwd=dest):
                return RepoResult(repo, "failed", f"branch {BRANCH} already exists with other content; review or delete it, then rerun",
                                  stacks=result.stacks)
        else:
            git(["push", "-q", url, f"HEAD:refs/heads/{BRANCH}"], cwd=dest, env=auth)
        on = setting()
        pr = client.create_pr(BRANCH, base, f"Adopt Venuvra engineering standards v{version}",
                              pr_body(version, base, result.stacks, result.written, warnings, drafted, on))
        return RepoResult(repo, "opened", f"PR against {base}", pr.url, result.stacks, warnings + notes, "running")
    except (github.GitHubError, SyncError, InitError, WriterError) as exc:
        return RepoResult(repo, "failed", str(exc))


def rollout(repos: list[str], ruleset: RuleSet, **kwargs) -> list[RepoResult]:
    bad = [r for r in repos if not github.valid_repo(r)]
    if bad:
        raise ValueError(f"not owner/name: {', '.join(bad)}")
    with tempfile.TemporaryDirectory(prefix="vstd-rollout-") as tmp:
        return [onboard(repo, ruleset, workdir=Path(tmp), **kwargs) for repo in repos]
