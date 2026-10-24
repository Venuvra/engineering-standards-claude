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
