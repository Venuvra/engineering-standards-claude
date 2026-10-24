"""Command-line entry point: ``python3 -I path/to/vstd/main.py <command>``.

Run with ``-I`` so the target repository's files can't shadow stdlib modules.
That also stops Python adding this script's folder to ``sys.path``, so the
standards checkout is added explicitly below.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

STANDARDS_ROOT = Path(__file__).resolve().parent.parent
if str(STANDARDS_ROOT) not in sys.path:
    sys.path.insert(0, str(STANDARDS_ROOT))

from vstd import __version__  # noqa: E402
from vstd import config as config_mod  # noqa: E402
from vstd import sync as sync_mod  # noqa: E402
from vstd import writer  # noqa: E402
from vstd.eject import EjectError, eject  # noqa: E402
from vstd.init import InitError, init  # noqa: E402
from vstd.lint import lint_paths  # noqa: E402
from vstd.check import check  # noqa: E402
from vstd.github import GitHubError  # noqa: E402
from vstd.rules import RuleError, load_rules  # noqa: E402


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"### vstd\n\n```text\n{text}\n```\n")


def cmd_check(args) -> int:
    ruleset = load_rules(STANDARDS_ROOT / "rules")
    report = check(Path(args.repo), ruleset, __version__)
    out = report.format()
    print(out)
    _summary(out)
    return 0 if report.ok else 1


def cmd_sync_local(args) -> int:
    """Render this release into --repo's working tree. Used by sync on a scratch copy, and by humans locally."""
    repo = Path(args.repo)
    ruleset = load_rules(STANDARDS_ROOT / "rules")
    result = config_mod.load(repo, ruleset)
    for w in result.warnings:
        print(f"WARNING {w}")
    if not result.ok:
        for e in result.errors:
            print(f"ERROR {e}")
        return 1
    cfg = result.config
    if cfg.version != __version__ and ".dev" not in __version__:
        print(f"ERROR {config_mod.CONFIG_PATH}: pins v{cfg.version} but this is vstd {__version__}")
        return 1
    try:
        changes = writer.plan(repo, ruleset, cfg)
        writer.apply(repo, changes)
    except writer.WriterError as exc:
        print(f"ERROR {exc}")
        return 1
    for c in changes:
        print(f"{'created' if c.created else 'updated'} {c.path}")
    if not changes:
        print("up to date")
    return 0


def _run_url(repo: str | None) -> str | None:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id.isdigit():
        return f"https://github.com/{repo}/actions/runs/{run_id}"
    return None


def cmd_sync(args) -> int:
    if args.local:
        return cmd_sync_local(args)
    github_repo = os.environ.get("GITHUB_REPOSITORY")
    try:
        result = sync_mod.run(
            Path(args.repo),
            standards_root=STANDARDS_ROOT,
            tool_version=__version__,
            dry_run=args.dry_run,
            github_repo=github_repo,
            token=os.environ.get("GH_TOKEN"),
            base=args.base,
            target_url=_run_url(github_repo),
        )
    except (sync_mod.SyncError, GitHubError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        _summary(f"sync failed: {exc}")
        return 1
    if args.dry_run and result.diff:
        print(result.diff, end="")
    out = "\n".join(result.messages)
    print(out)
    _summary(out)
    return 0


def cmd_lint_workflows(args) -> int:
    errors = lint_paths([Path(p) for p in args.paths])
    for e in errors:
        print(f"ERROR {e}")
    print(f"lint-workflows: {'FAILED' if errors else 'OK'} ({len(errors)} error(s))")
    return 1 if errors else 0


def _git_out(args: list[str], cwd: Path) -> str | None:
    import subprocess

    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=sync_mod.child_env())
    return proc.stdout.strip() if proc.returncode == 0 else None


def cmd_init(args) -> int:
    if ".dev" in __version__:
        print(f"ERROR vstd {__version__} is a development build; run init from a release checkout (vX.Y.Z)")
        return 1
    commit = _git_out(["rev-parse", "HEAD"], STANDARDS_ROOT)
    if not commit or _git_out(["status", "--porcelain"], STANDARDS_ROOT):
        print("ERROR run init from a clean git checkout of a release, so the commit can be pinned")
        return 1
    if f"v{__version__}" not in (_git_out(["tag", "--points-at", "HEAD"], STANDARDS_ROOT) or "").split():
        print(f"ERROR this checkout is not tag v{__version__}; check out the release tag first")
        return 1
    repo = Path(args.repo)
    branch = args.default_branch or _git_out(["symbolic-ref", "--short", "HEAD"], repo) or "main"
    stacks = tuple(s.strip() for s in args.stacks.split(",") if s.strip()) if args.stacks is not None else None
    try:
        result = init(repo, load_rules(STANDARDS_ROOT / "rules"), version=__version__, commit=commit,
                      standards_root=STANDARDS_ROOT, stacks=stacks, default_branch=branch, force=args.force)
    except (InitError, writer.WriterError) as exc:
        print(f"ERROR {exc}")
        return 1
    print(f"stacks: {', '.join(result.stacks) or 'none (core rules only)'}")
    for rel in result.written:
        print(f"wrote {rel}")
    for rel in result.kept:
        print(f"kept existing {rel} (use --force to replace it)")
    print("Review the changes, then push them on a branch and open a PR.")
    return 0


def cmd_eject(args) -> int:
    try:
        result = eject(Path(args.repo))
    except (EjectError, writer.WriterError) as exc:
        print(f"ERROR {exc}")
        return 1
    for rel in result.written:
        print(f"inlined the rules in {rel} (markers removed)")
    for rel in result.removed:
        print(f"removed {rel}")
    for rel in result.kept:
        print(f"kept {rel}: not installed by vstd init")
    print("The rules are now plain text owned by this repository.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vstd", description="Venuvra engineering standards")
    parser.add_argument("--version", action="version", version=f"vstd {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="detect drift and invalid configuration")
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("sync", help="open or update the standards/update pull request")
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.add_argument("--dry-run", action="store_true", help="print the diff; write nothing, open nothing")
    p.add_argument("--local", action="store_true", help="only render this release into --repo's working tree")
    p.add_argument("--base", help="base branch for the PR (default: the checked-out branch)")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("init", help="onboard a repository (writes files for a PR you push)")
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.add_argument("--stacks", help="comma-separated stacks (default: detected from manifests)")
    p.add_argument("--default-branch", help="branch the check runs on for pushes (default: the checked-out branch)")
    p.add_argument("--force", action="store_true", help="replace an existing standards.toml or standards workflow")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("eject", help="stop using the central standards; keep the rules as plain text")
    p.add_argument("--repo", default=".", help="repository root (default: current directory)")
    p.set_defaults(func=cmd_eject)
    p = sub.add_parser("lint-workflows", help="check workflow files against the CI security rules")
    p.add_argument("paths", nargs="+", help="workflow files or directories")
    p.set_defaults(func=cmd_lint_workflows)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RuleError as exc:
        print(f"ERROR standards rules are invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
